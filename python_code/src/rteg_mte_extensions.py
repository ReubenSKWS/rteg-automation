"""
Step 5.3 — MTE collar extensions.

1. select_extension_collar — smallest preserved BAW_MTE piece with body overlap
   (fallback: smallest piece if none overlap).
2. find_outward_lip_ab — best single long edge whose midpoint is farther from
   body MTE centroid than the collar centroid; A and B are that edge's corners.
3. draw_lip_extension — inner lip (0.5 µm inset) + outward extrusion with
   straight cap; default 30 µm; unequal heights at A/B when corner normals differ.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import gdstk

from export_gds import ExportResult, export_gds
from layermap import LayerMap
from prep_rteg_frame import RtegFrameAssembly
from rteg_collect import (
    PreservedMetal,
    TaggedPolygon,
    preserved_mte_overlap_with_body,
)
from rteg_utils import assign_layer

Point = tuple[float, float]
Edge = tuple[Point, Point]

_COLLAR_INSET_UM = 0.5
_MAX_OVERLAP_FRACTION = 0.5


@dataclass(frozen=True)
class MteBuildConfig:
    mte_layer: str = "BAW_MTE"
    collar_extension_um: float = 30.0
    boolean_precision: float = 1e-3
    min_collar_overlap_um2: float = 0.01


@dataclass(frozen=True)
class LipIntercept:
    """Outward long-lip walk from corner A to corner B."""

    point_a: Point
    point_b: Point
    lip_vertex_indices: list[int]
    outward_normal: tuple[float, float]
    lip_edges: list[int]


# Backward-compatible alias
CollarMouthIntercepts = LipIntercept


@dataclass(frozen=True)
class CollarExtensionDraw:
    polygon: gdstk.Polygon
    intercept_a: Point
    intercept_b: Point
    outer_edge: Edge
    extension_um: float
    target_extension_um: float
    endcap_edge_a: Edge = ((0.0, 0.0), (0.0, 0.0))
    endcap_edge_b: Edge = ((0.0, 0.0), (0.0, 0.0))
    endcap_index_a: int = -1
    endcap_index_b: int = -1
    mouth_span_um: float = 0.0
    mouth_vertices: int = 0
    collar_intercept_a: Point = (0.0, 0.0)
    collar_intercept_b: Point = (0.0, 0.0)


@dataclass
class MteExtensionResult:
    collar: TaggedPolygon | None
    extension: gdstk.Polygon | None
    preserved_collar_polygons: list[gdstk.Polygon]
    n_extensions: int
    is_connected: bool
    extension_draw: CollarExtensionDraw | None = None
    drc_violations: list[str] = field(default_factory=list)


class _HasPreserved(Protocol):
    preserved: PreservedMetal
    resonator_body_mte: Sequence[gdstk.Polygon]


def _polygon_centroid(poly: gdstk.Polygon) -> Point:
    pts = poly.points
    if len(pts) == 0:
        return (0.0, 0.0)
    cx = sum(float(p[0]) for p in pts) / len(pts)
    cy = sum(float(p[1]) for p in pts) / len(pts)
    return (cx, cy)


def _body_centroid(body_mte_polys: Sequence[gdstk.Polygon]) -> Point:
    total = 0.0
    cx = cy = 0.0
    for poly in body_mte_polys:
        area = abs(poly.area())
        if area < 1e-12:
            continue
        pcx, pcy = _polygon_centroid(poly)
        cx += pcx * area
        cy += pcy * area
        total += area
    if total > 1e-12:
        return (cx / total, cy / total)
    if not body_mte_polys:
        return (0.0, 0.0)
    xs: list[float] = []
    ys: list[float] = []
    for poly in body_mte_polys:
        for p in poly.points:
            xs.append(float(p[0]))
            ys.append(float(p[1]))
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def _edge_length(p0: Point, p1: Point) -> float:
    return math.hypot(p1[0] - p0[0], p1[1] - p0[1])


def _edge_points(pts: Sequence[Point], edge_idx: int) -> Edge:
    n = len(pts)
    return (
        (float(pts[edge_idx][0]), float(pts[edge_idx][1])),
        (float(pts[(edge_idx + 1) % n][0]), float(pts[(edge_idx + 1) % n][1])),
    )


def _long_edge_indices(lengths: Sequence[float]) -> set[int]:
    peak = max(lengths) if lengths else 0.0
    threshold = max(peak * 0.15, 8.0)
    return {i for i, length in enumerate(lengths) if length > threshold}


def _dist(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _edge_outward_normal(edge: Edge, body_centroid: Point) -> tuple[float, float]:
    p0, p1 = edge
    mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
    tx, ty = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(tx, ty)
    if length < 1e-9:
        dx, dy = mid[0] - body_centroid[0], mid[1] - body_centroid[1]
        length = math.hypot(dx, dy)
        return (dx / length, dy / length) if length > 1e-9 else (0.0, 1.0)
    tx, ty = tx / length, ty / length
    for nx, ny in ((-ty, tx), (ty, -tx)):
        if (mid[0] - body_centroid[0]) * nx + (mid[1] - body_centroid[1]) * ny > 1e-6:
            return (nx, ny)
    return (-ty, tx)


def _vertex_outward_normal(
    pts: Sequence[Point],
    vertex_idx: int,
    body_centroid: Point,
) -> tuple[float, float]:
    n = len(pts)
    prev_edge = _edge_points(pts, (vertex_idx - 1) % n)
    next_edge = _edge_points(pts, vertex_idx)
    n_prev = _edge_outward_normal(prev_edge, body_centroid)
    n_next = _edge_outward_normal(next_edge, body_centroid)
    nx = n_prev[0] + n_next[0]
    ny = n_prev[1] + n_next[1]
    length = math.hypot(nx, ny)
    if length < 1e-9:
        return n_next
    return (nx / length, ny / length)


def _extend_long_chain(
    seed: int,
    long_edges: set[int],
    n: int,
) -> list[int]:
    """Single outward long edge (corner A to corner B)."""
    del long_edges, n
    return [seed]


def _vertices_from_edge_chain(chain: Sequence[int], n: int) -> list[int]:
    if not chain:
        return []
    verts = [chain[0]]
    for edge in chain:
        end = (edge + 1) % n
        if verts[-1] != end:
            verts.append(end)
    return verts


def select_extension_collar(
    preserved: PreservedMetal,
    body_mte_polys: Sequence[gdstk.Polygon],
    *,
    min_overlap_um2: float = 0.01,
    precision: float = 1e-3,
) -> TaggedPolygon | None:
    """
    Pick the extension collar on ``BAW_MTE`` (layermap 5/0).

    Smallest preserved BAW_MTE piece with body overlap (fallback: smallest piece
    if none overlap). Step 5.1 often yields two pieces — resonator outline plus
    edge collar; the extension collar is the smaller piece that touches
    resonator-body MTE.
    """
    if not preserved.mte:
        return None
    overlapping = [
        tp
        for tp in preserved.mte
        if preserved_mte_overlap_with_body(
            tp.polygon, body_mte_polys, precision=precision
        )
        >= min_overlap_um2
    ]
    pool = overlapping if overlapping else list(preserved.mte)
    return min(pool, key=lambda tp: abs(tp.polygon.area()))


select_edge_collar_mte = select_extension_collar


def find_outward_lip_ab(
    collar: gdstk.Polygon,
    body_mte_polys: Sequence[gdstk.Polygon],
) -> LipIntercept:
    """
    Find intercept corners A and B on the extension collar mouth.

    Best single long edge whose midpoint is farther from body MTE centroid than
    the collar centroid; A and B are that edge's corners. Orientation and pad
    facing are ignored — outward is inferred from geometry only.
    """
    pts = [(float(p[0]), float(p[1])) for p in collar.points]
    if len(pts) < 4:
        raise ValueError("collar must have at least 4 vertices")

    body_centroid = _body_centroid(body_mte_polys)
    collar_centroid = _polygon_centroid(collar)
    body_from_collar = _dist(collar_centroid, body_centroid)

    n = len(pts)
    lengths = [_edge_length(pts[i], pts[(i + 1) % n]) for i in range(n)]
    long_edges = _long_edge_indices(lengths)
    if not long_edges:
        raise ValueError("collar has no long edges")

    best_seed: int | None = None
    best_score = -1.0
    for edge_idx in long_edges:
        p0, p1 = _edge_points(pts, edge_idx)
        mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
        mid_from_body = _dist(mid, body_centroid)
        if mid_from_body <= body_from_collar + 1e-6:
            continue
        if mid_from_body > best_score:
            best_score = mid_from_body
            best_seed = edge_idx

    if best_seed is None:
        best_seed = max(
            long_edges,
            key=lambda i: _dist(
                ((pts[i][0] + pts[(i + 1) % n][0]) / 2.0,
                 (pts[i][1] + pts[(i + 1) % n][1]) / 2.0),
                body_centroid,
            ),
        )

    lip_edges = _extend_long_chain(best_seed, long_edges, n)
    lip_vertices = _vertices_from_edge_chain(lip_edges, n)
    if len(lip_vertices) < 2:
        raise ValueError("outward lip chain is degenerate")

    point_a = (pts[lip_vertices[0]][0], pts[lip_vertices[0]][1])
    point_b = (pts[lip_vertices[-1]][0], pts[lip_vertices[-1]][1])
    seed_edge = _edge_points(pts, best_seed)
    outward_normal = _edge_outward_normal(seed_edge, body_centroid)

    return LipIntercept(
        point_a=point_a,
        point_b=point_b,
        lip_vertex_indices=lip_vertices,
        outward_normal=outward_normal,
        lip_edges=lip_edges,
    )


def find_collar_mouth_intercepts(
    preserved_collar: gdstk.Polygon,
    body_mte_polys: Sequence[gdstk.Polygon],
) -> LipIntercept:
    """Backward-compatible name for :func:`find_outward_lip_ab`."""
    return find_outward_lip_ab(preserved_collar, body_mte_polys)


def _extrusion_heights(
    point_a: Point,
    point_b: Point,
    n_a: tuple[float, float],
    n_b: tuple[float, float],
    target_um: float,
) -> tuple[float, float]:
    """
    Heights at A and B so the straight cap sits ~target_um from the lip.

    Equal when normals are parallel; otherwise solve for perpendicular mid-distance.
    """
    cross = abs(n_a[0] * n_b[1] - n_a[1] * n_b[0])
    if cross < 0.05:
        return target_um, target_um

    mid = ((point_a[0] + point_b[0]) / 2.0, (point_a[1] + point_b[1]) / 2.0)
    dom = (
        (n_a[0] + n_b[0]) / 2.0,
        (n_a[1] + n_b[1]) / 2.0,
    )
    dom_len = math.hypot(dom[0], dom[1])
    if dom_len < 1e-9:
        return target_um, target_um
    dom = (dom[0] / dom_len, dom[1] / dom_len)

    h_a = target_um
    o_a = (point_a[0] + n_a[0] * h_a, point_a[1] + n_a[1] * h_a)
    cap_dir = (point_b[0] - point_a[0], point_b[1] - point_a[1])
    cap_len = math.hypot(cap_dir[0], cap_dir[1])
    if cap_len < 1e-9:
        return target_um, target_um
    cap_dir = (cap_dir[0] / cap_len, cap_dir[1] / cap_len)

    # Place cap midpoint ~target_um along dominant outward normal from lip mid.
    desired_mid = (
        mid[0] + dom[0] * target_um,
        mid[1] + dom[1] * target_um,
    )
    o_b_x = 2.0 * desired_mid[0] - o_a[0]
    o_b_y = 2.0 * desired_mid[1] - o_a[1]
    denom = n_b[0] * cap_dir[0] + n_b[1] * cap_dir[1]
    if abs(denom) < 1e-9:
        return target_um, target_um
    t = ((o_b_x - point_b[0]) * cap_dir[0] + (o_b_y - point_b[1]) * cap_dir[1]) / denom
    h_b = max(t, target_um * 0.25)
    return h_a, h_b


def draw_lip_extension(
    collar: gdstk.Polygon,
    lip: LipIntercept,
    body_mte_polys: Sequence[gdstk.Polygon],
    extension_um: float,
    layer: int,
    datatype: int,
) -> CollarExtensionDraw:
    """
    Draw one new MTE polygon extruding outward from intercepts A and B.

    Inner lip (0.5 µm inset) + outward extrusion with straight cap; default 30 µm
    (``MteBuildConfig.collar_extension_um``); unequal heights at A/B when corner
    normals differ so the closing edge stays one straight line.
    """
    if extension_um <= 0:
        raise ValueError("extension_um must be positive")

    pts = [(float(p[0]), float(p[1])) for p in collar.points]
    body_centroid = _body_centroid(body_mte_polys)
    inward = (-lip.outward_normal[0], -lip.outward_normal[1])

    inner_chain = [
        (
            pts[i][0] + inward[0] * _COLLAR_INSET_UM,
            pts[i][1] + inward[1] * _COLLAR_INSET_UM,
        )
        for i in lip.lip_vertex_indices
    ]

    n_a = _vertex_outward_normal(pts, lip.lip_vertex_indices[0], body_centroid)
    n_b = _vertex_outward_normal(pts, lip.lip_vertex_indices[-1], body_centroid)
    h_a, h_b = _extrusion_heights(lip.point_a, lip.point_b, n_a, n_b, extension_um)

    o_a = (lip.point_a[0] + n_a[0] * h_a, lip.point_a[1] + n_a[1] * h_a)
    o_b = (lip.point_b[0] + n_b[0] * h_b, lip.point_b[1] + n_b[1] * h_b)

    polygon = gdstk.Polygon(
        list(inner_chain) + [o_b, o_a],
        layer=layer,
        datatype=datatype,
    )
    span = _dist(lip.point_a, lip.point_b)
    n = len(pts)
    edge_a = _edge_points(pts, lip.lip_edges[0])
    edge_b = _edge_points(pts, lip.lip_edges[-1])

    return CollarExtensionDraw(
        polygon=polygon,
        intercept_a=inner_chain[0],
        intercept_b=inner_chain[-1],
        outer_edge=(o_b, o_a),
        extension_um=max(h_a, h_b),
        target_extension_um=extension_um,
        endcap_edge_a=edge_a,
        endcap_edge_b=edge_b,
        endcap_index_a=lip.lip_edges[0],
        endcap_index_b=lip.lip_edges[-1],
        mouth_span_um=span,
        mouth_vertices=len(lip.lip_vertex_indices),
        collar_intercept_a=lip.point_a,
        collar_intercept_b=lip.point_b,
    )


def _collar_overlap_area(
    ext: gdstk.Polygon, collar: gdstk.Polygon, precision: float
) -> float:
    inter = gdstk.boolean(ext, collar, "and", precision=precision)
    return sum(abs(p.area()) for p in inter) if inter else 0.0


def _validate_extension(
    ext: gdstk.Polygon,
    collar: gdstk.Polygon,
    *,
    precision: float,
    min_overlap_um2: float,
    resonator_index: int | None = None,
) -> None:
    overlap = _collar_overlap_area(ext, collar, precision)
    collar_area = abs(collar.area())
    prefix = f"resonator {resonator_index}: " if resonator_index is not None else ""
    if overlap < min_overlap_um2:
        raise ValueError(
            f"{prefix}MTE extension not attached to collar "
            f"(overlap {overlap:.2f} um² < {min_overlap_um2:.2f} um²)"
        )
    if collar_area > 1e-6 and overlap / collar_area > _MAX_OVERLAP_FRACTION:
        raise ValueError(
            f"{prefix}MTE extension covers too much of collar "
            f"(overlap/collar = {overlap / collar_area:.2f} > {_MAX_OVERLAP_FRACTION})"
        )


def draw_collar_extension(
    collar_tp: TaggedPolygon,
    layermap: LayerMap,
    cfg: MteBuildConfig,
    *,
    body_mte_polys: Sequence[gdstk.Polygon],
    resonator_index: int | None = None,
) -> CollarExtensionDraw:
    layer, datatype = layermap.pair(cfg.mte_layer)
    lip = find_outward_lip_ab(collar_tp.polygon, body_mte_polys)
    draw = draw_lip_extension(
        collar_tp.polygon,
        lip,
        body_mte_polys,
        cfg.collar_extension_um,
        layer,
        datatype,
    )
    ext = assign_layer(draw.polygon, layermap, cfg.mte_layer)
    draw = CollarExtensionDraw(
        polygon=ext,
        intercept_a=draw.intercept_a,
        intercept_b=draw.intercept_b,
        outer_edge=draw.outer_edge,
        extension_um=draw.extension_um,
        target_extension_um=draw.target_extension_um,
        endcap_edge_a=draw.endcap_edge_a,
        endcap_edge_b=draw.endcap_edge_b,
        endcap_index_a=draw.endcap_index_a,
        endcap_index_b=draw.endcap_index_b,
        mouth_span_um=draw.mouth_span_um,
        mouth_vertices=draw.mouth_vertices,
        collar_intercept_a=draw.collar_intercept_a,
        collar_intercept_b=draw.collar_intercept_b,
    )
    _validate_extension(
        draw.polygon,
        collar_tp.polygon,
        precision=cfg.boolean_precision,
        min_overlap_um2=cfg.min_collar_overlap_um2,
        resonator_index=resonator_index,
    )
    return draw


def _extension_for_roles(
    roles: _HasPreserved,
    layermap: LayerMap,
    cfg: MteBuildConfig,
    *,
    resonator_index: int,
) -> MteExtensionResult:
    preserved_polys = [tp.polygon for tp in roles.preserved.mte]
    collar_tp = select_extension_collar(
        roles.preserved,
        roles.resonator_body_mte,
        min_overlap_um2=cfg.min_collar_overlap_um2,
        precision=cfg.boolean_precision,
    )
    if collar_tp is None:
        raise ValueError(
            f"resonator {resonator_index}: no preserved MTE collar to extend"
        )
    draw = draw_collar_extension(
        collar_tp,
        layermap,
        cfg,
        body_mte_polys=roles.resonator_body_mte,
        resonator_index=resonator_index,
    )
    return MteExtensionResult(
        collar=collar_tp,
        extension=draw.polygon,
        preserved_collar_polygons=preserved_polys,
        n_extensions=1,
        is_connected=True,
        extension_draw=draw,
    )


def build_mte_extensions(
    roles_by_index: Mapping[int, _HasPreserved],
    layermap: LayerMap,
    config: MteBuildConfig | None = None,
) -> dict[int, MteExtensionResult]:
    cfg = config or MteBuildConfig()
    return {
        idx: _extension_for_roles(roles, layermap, cfg, resonator_index=idx)
        for idx, roles in roles_by_index.items()
    }


def mte_extensions_overview_rows(
    extensions: Mapping[int, MteExtensionResult],
    *,
    inst_names: Mapping[int, str] | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx in sorted(extensions):
        result = extensions[idx]
        rows.append(
            {
                "index": idx,
                "inst_name": inst_names.get(idx) if inst_names else None,
                "n_preserved_mte": len(result.preserved_collar_polygons),
                "n_extensions": result.n_extensions,
                "is_connected": result.is_connected,
            }
        )
    return rows


def _fmt_point(pt: Point) -> str:
    return f"({pt[0]:.2f}, {pt[1]:.2f})"


def _fmt_edge(edge: Edge) -> str:
    return f"{_fmt_point(edge[0])} -> {_fmt_point(edge[1])}"


def mte_intercept_breakdown_rows(
    extensions: Mapping[int, MteExtensionResult],
    *,
    inst_names: Mapping[int, str] | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx in sorted(extensions):
        result = extensions[idx]
        draw = result.extension_draw
        row: dict[str, object] = {
            "index": idx,
            "inst_name": inst_names.get(idx) if inst_names else None,
            "n_extensions": result.n_extensions,
        }
        if draw is None:
            row.update(
                {
                    "collar_intercept_a": None,
                    "collar_intercept_b": None,
                    "endcap_edge_a": None,
                    "endcap_edge_b": None,
                    "endcap_index_a": None,
                    "endcap_index_b": None,
                    "mouth_span_um": None,
                    "mouth_vertices": None,
                    "extension_um": None,
                    "target_extension_um": None,
                }
            )
        else:
            row.update(
                {
                    "collar_intercept_a": _fmt_point(draw.collar_intercept_a),
                    "collar_intercept_b": _fmt_point(draw.collar_intercept_b),
                    "endcap_edge_a": _fmt_edge(draw.endcap_edge_a),
                    "endcap_edge_b": _fmt_edge(draw.endcap_edge_b),
                    "endcap_index_a": draw.endcap_index_a,
                    "endcap_index_b": draw.endcap_index_b,
                    "mouth_span_um": round(draw.mouth_span_um, 2),
                    "mouth_vertices": draw.mouth_vertices,
                    "extension_um": round(draw.extension_um, 2),
                    "target_extension_um": round(draw.target_extension_um, 2),
                }
            )
        rows.append(row)
    return rows


@dataclass
class MteRtegAssembly:
    frame: RtegFrameAssembly
    extension: MteExtensionResult

    @property
    def index(self) -> int:
        return self.frame.index

    @property
    def inst_name(self) -> str:
        return self.frame.inst_name

    @property
    def top_cell(self) -> gdstk.Cell:
        return self.frame.top_cell

    @property
    def library(self) -> gdstk.Library:
        return self.frame.library

    def flatten(self) -> gdstk.Cell:
        cell = self.frame.flatten().copy(f"rteg_{self.index:02d}_{self.inst_name}_mte")
        if self.extension.extension is not None:
            p = self.extension.extension
            cell.add(gdstk.Polygon(p.points, p.layer, p.datatype))
        return cell


def export_mte_extensions_gds(
    frame_assemblies: Sequence[RtegFrameAssembly],
    extensions: Mapping[int, MteExtensionResult],
    output_dir: str | Path,
    *,
    layermap: LayerMap,
    parent: str | None = None,
    flatten: bool = True,
    write_lyp: bool = True,
) -> list[ExportResult]:
    assemblies = [
        MteRtegAssembly(frame=asm, extension=extensions[asm.index])
        for asm in frame_assemblies
        if asm.index in extensions and extensions[asm.index].n_extensions > 0
    ]
    return export_gds(
        assemblies,
        output_dir,
        layermap=layermap,
        parent=parent,
        stage="mte",
        flatten=flatten,
        write_lyp=write_lyp,
    )


__all__ = [
    "CollarExtensionDraw",
    "CollarMouthIntercepts",
    "LipIntercept",
    "MteBuildConfig",
    "MteExtensionResult",
    "MteRtegAssembly",
    "build_mte_extensions",
    "draw_collar_extension",
    "draw_lip_extension",
    "export_mte_extensions_gds",
    "find_collar_mouth_intercepts",
    "find_outward_lip_ab",
    "mte_extensions_overview_rows",
    "mte_intercept_breakdown_rows",
    "select_edge_collar_mte",
    "select_extension_collar",
]
