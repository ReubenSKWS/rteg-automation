"""
Step 5.3 — Preserved filter MTE routing setup.

Filter ``connectMTE`` metal is already on the RTEG frame (step 4.1). This step
only selects the mouth collar and records SKILL slope intercepts for step 5.4 —
no new lip extension is drawn.

1. ``select_extension_collar`` — preserved BAW_MTE piece at the resonator mouth.
2. ``find_outward_lip_ab`` — SKILL slope intercepts on that collar (A/B).
3. ``build_preserved_extension_draw`` — routing metadata on the existing polygon.
"""
from __future__ import annotations

import math
import warnings
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
    RtegGeometryRoles,
    TaggedPolygon,
    _polygon_key,
    polys_touch,
    preserved_mte_overlap_with_body,
)
from rteg_utils import assign_layer

Point = tuple[float, float]
Edge = tuple[Point, Point]


def _bbox_intersects(
    a: tuple[tuple[float, float], tuple[float, float]],
    b: tuple[tuple[float, float], tuple[float, float]],
    *,
    margin_um: float = 0.0,
) -> bool:
    (ax0, ay0), (ax1, ay1) = a
    (bx0, by0), (bx1, by1) = b
    return not (
        ax1 + margin_um < bx0 - margin_um
        or bx1 + margin_um < ax0 - margin_um
        or ay1 + margin_um < by0 - margin_um
        or by1 + margin_um < ay0 - margin_um
    )


@dataclass(frozen=True)
class MteBuildConfig:
    """Tunable parameters for step 5.3 MTE collar extensions."""

    mte_layer: str = "BAW_MTE"
    collar_extension_um: float = 14.0
    collar_merge_inset_um: float = 4.0
    collar_touch_overlap_um: float = 0.5
    min_collar_overlap_um2: float = 0.01
    stadium_collar_area_um2: float = 2500.0
    stadium_edge_area_ratio: float = 0.6
    lip_long_edge_peak_fraction: float = 0.15
    lip_long_edge_min_um: float = 8.0
    max_overlap_fraction: float = 0.99
    min_merge_inset_check_um: float = 0.5
    min_connection_overlap_fraction: float = 0.10
    min_connection_merge_um: float = 1.0
    min_mouth_coverage_fraction: float = 0.65
    min_mouth_coverage_shunt_fraction: float = 0.85
    collar_association_gap_um: float = 35.0
    max_edge_collar_area_um2: float = 800.0
    stadium_tab_mouth_min_um: float = 12.0
    stadium_tab_mouth_max_um: float = 45.0
    boolean_precision: float = 1e-3
    inside_probe_half_um: float = 0.25
    feasible_merge_search_iterations: int = 24
    max_preserved_mte_vertices_after_pad_route: int = 15
    # SKILL ``rdsBawResonatorTEGConnection`` collar intercept constants
    skill_collar_shrink_um: float = 1.0
    skill_body_grow_um: float = 3.0
    skill_pad_expand_um: float = 5.0


@dataclass(frozen=True)
class LipIntercept:
    """Outward long-lip walk from corner A to corner B."""

    point_a: Point
    point_b: Point
    lip_vertex_indices: list[int]
    outward_normal: tuple[float, float]
    lip_edges: list[int]


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
    merge_inset_a_um: float = 0.0
    merge_inset_b_um: float = 0.0


@dataclass
class MteExtensionResult:
    collar: TaggedPolygon | None
    extension: gdstk.Polygon | None
    preserved_collar_polygons: list[gdstk.Polygon]
    n_extensions: int
    is_connected: bool
    collar_overlap_um2: float = 0.0
    extension_draw: CollarExtensionDraw | None = None
    route_draw: object | None = None  # MteRouteDraw when step 5.4 routed
    routed_net: gdstk.Polygon | None = None
    resonator_body_mte_polys: list[gdstk.Polygon] = field(default_factory=list)
    drc_violations: list[str] = field(default_factory=list)


class _HasPreserved(Protocol):
    preserved: PreservedMetal
    resonator_body_mte: Sequence[gdstk.Polygon]
    ground_plates: object


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


def _long_edge_indices(
    lengths: Sequence[float],
    *,
    peak_fraction: float,
    min_um: float,
) -> set[int]:
    peak = max(lengths) if lengths else 0.0
    threshold = max(peak * peak_fraction, min_um)
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


def _vertices_from_edge_chain(chain: Sequence[int], n: int) -> list[int]:
    if not chain:
        return []
    verts = [chain[0]]
    for edge in chain:
        end = (edge + 1) % n
        if verts[-1] != end:
            verts.append(end)
    return verts


def _is_stadium_collar(poly: gdstk.Polygon, cfg: MteBuildConfig) -> bool:
    return abs(poly.area()) >= cfg.stadium_collar_area_um2


def _is_edge_collar_tab(poly: gdstk.Polygon, cfg: MteBuildConfig) -> bool:
    """Separate collar piece ΓÇö smaller than the closed stadium shell."""
    return abs(poly.area()) < cfg.stadium_collar_area_um2


def _is_extension_collar_candidate(poly: gdstk.Polygon, cfg: MteBuildConfig) -> bool:
    """Only small tabs or the stadium shell ΓÇö never the die-wide interconnect bus."""
    return _is_edge_collar_tab(poly, cfg) or _is_stadium_collar(poly, cfg)


def _associated_edge_collars_from_pieces(
    pieces: Sequence[TaggedPolygon],
    cfg: MteBuildConfig,
) -> list[TaggedPolygon]:
    """Small edge tabs that boolean-touch a stadium piece in the same preserved set."""
    stadium_pieces = [
        tp for tp in pieces if _is_stadium_collar(tp.polygon, cfg)
    ]
    if not stadium_pieces:
        return []
    edge_tabs = [tp for tp in pieces if _is_edge_collar_tab(tp.polygon, cfg)]
    associated: list[TaggedPolygon] = []
    stadium_keys = {_polygon_key(stadium.polygon) for stadium in stadium_pieces}
    for tp in edge_tabs:
        if _polygon_key(tp.polygon) in stadium_keys:
            continue
        if any(
            polys_touch(
                tp.polygon,
                stadium.polygon,
                precision=cfg.boolean_precision,
            )
            for stadium in stadium_pieces
            if _polygon_key(stadium.polygon) != _polygon_key(tp.polygon)
        ):
            associated.append(tp)
    return associated


def _associated_edge_collars(
    preserved: PreservedMetal,
    cfg: MteBuildConfig,
) -> list[TaggedPolygon]:
    return _associated_edge_collars_from_pieces(preserved.mte, cfg)


def select_extension_collar_from_pieces(
    pieces: Sequence[TaggedPolygon],
    body_polys: Sequence[gdstk.Polygon],
    overlap_with_body,
    cfg: MteBuildConfig | None = None,
) -> TaggedPolygon | None:
    """
    Pick the extension collar from a preserved metal set.

    Prefer the small edge collar tab over the stadium shell when both are
    present. Collect often yields two pieces ΓÇö resonator outline plus edge
    collar; the extension collar is the smaller piece at the interconnect mouth.
    """
    c = cfg or MteBuildConfig()
    if not pieces:
        return None

    associated_edges = _associated_edge_collars_from_pieces(pieces, c)
    if associated_edges:
        with_body = [
            tp
            for tp in associated_edges
            if overlap_with_body(tp.polygon, body_polys, precision=c.boolean_precision)
            >= c.min_collar_overlap_um2
        ]
        if with_body:
            return min(with_body, key=lambda tp: abs(tp.polygon.area()))
        return min(associated_edges, key=lambda tp: abs(tp.polygon.area()))

    overlapping = [
        tp
        for tp in pieces
        if _is_extension_collar_candidate(tp.polygon, c)
        and overlap_with_body(tp.polygon, body_polys, precision=c.boolean_precision)
        >= c.min_collar_overlap_um2
    ]
    if overlapping:
        smallest_overlap = min(overlapping, key=lambda tp: abs(tp.polygon.area()))
        smallest_all = min(pieces, key=lambda tp: abs(tp.polygon.area()))
        overlap_area = abs(smallest_overlap.polygon.area())
        edge_overlap = overlap_with_body(
            smallest_all.polygon, body_polys, precision=c.boolean_precision
        )
        stadium_targets = [
            tp for tp in overlapping if _is_stadium_collar(tp.polygon, c)
        ]
        if (
            overlap_area >= c.stadium_collar_area_um2
            and _is_edge_collar_tab(smallest_all.polygon, c)
            and smallest_all not in overlapping
            and edge_overlap >= c.min_collar_overlap_um2
            and stadium_targets
            and any(
                polys_touch(
                    smallest_all.polygon,
                    stadium.polygon,
                    precision=c.boolean_precision,
                )
                for stadium in stadium_targets
            )
        ):
            return smallest_all
        return smallest_overlap

    stadium_pieces = [tp for tp in pieces if _is_stadium_collar(tp.polygon, c)]
    if stadium_pieces:
        return min(stadium_pieces, key=lambda tp: abs(tp.polygon.area()))

    return min(pieces, key=lambda tp: abs(tp.polygon.area()))


def select_extension_collar(
    preserved: PreservedMetal,
    body_mte_polys: Sequence[gdstk.Polygon],
    cfg: MteBuildConfig | None = None,
) -> TaggedPolygon | None:
    """Pick the extension collar on ``BAW_MTE`` (layermap 5/0)."""
    return select_extension_collar_from_pieces(
        preserved.mte,
        body_mte_polys,
        preserved_mte_overlap_with_body,
        cfg,
    )


def _collar_body_overlap_centroid(
    collar: gdstk.Polygon,
    body_mte_polys: Sequence[gdstk.Polygon],
    *,
    precision: float,
) -> Point | None:
    """Area-weighted centroid of ``collar Γê⌐ body``; ``None`` when disjoint."""
    total = 0.0
    cx = cy = 0.0
    for body in body_mte_polys:
        inter = gdstk.boolean(collar, body, "and", precision=precision)
        if not inter:
            continue
        for piece in inter:
            area = abs(piece.area())
            if area < 1e-12:
                continue
            pcx, pcy = _polygon_centroid(piece)
            cx += pcx * area
            cy += pcy * area
            total += area
    if total < 1e-12:
        return None
    return (cx / total, cy / total)


def _lip_candidate_score(
    collar: gdstk.Polygon,
    pts: Sequence[Point],
    edge_idx: int,
    body_mte_polys: Sequence[gdstk.Polygon],
    body_centroid: Point,
    body_overlap_centroid: Point | None,
    cfg: MteBuildConfig,
) -> tuple[float, float, float]:
    """
    Rank key for one lip edge: ``(min_merge_um, edge_length_um, body_proximity)``.
    """
    p0, p1 = _edge_points(pts, edge_idx)
    outward = _edge_outward_normal((p0, p1), body_centroid)
    merge_a = _feasible_merge_um(
        p0,
        outward,
        collar,
        cfg.collar_merge_inset_um,
        precision=cfg.boolean_precision,
        probe_half_um=cfg.inside_probe_half_um,
        search_iterations=cfg.feasible_merge_search_iterations,
    )
    merge_b = _feasible_merge_um(
        p1,
        outward,
        collar,
        cfg.collar_merge_inset_um,
        precision=cfg.boolean_precision,
        probe_half_um=cfg.inside_probe_half_um,
        search_iterations=cfg.feasible_merge_search_iterations,
    )
    min_merge = min(merge_a, merge_b)
    edge_len = _edge_length(p0, p1)
    mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
    ref = body_overlap_centroid if body_overlap_centroid is not None else body_centroid
    body_proximity = 1.0 / (_dist(mid, ref) + 1e-3)
    return (min_merge, edge_len, body_proximity)


def _offset_collar(poly: gdstk.Polygon, delta_um: float, *, precision: float) -> gdstk.Polygon | None:
    if abs(delta_um) < 1e-9:
        return gdstk.Polygon(poly.points, layer=poly.layer, datatype=poly.datatype)
    grown = gdstk.offset(poly, delta_um, precision=precision, join="miter")
    if not grown:
        return None
    best = max(grown, key=lambda p: abs(p.area()))
    return gdstk.Polygon(best.points, layer=poly.layer, datatype=poly.datatype)


def _skill_outer_collar_points(
    collar: gdstk.Polygon,
    body_mte_polys: Sequence[gdstk.Polygon],
    cfg: MteBuildConfig,
) -> list[Point]:
    """SKILL ``mteclrOut``: shrunk-collar vertices outside grown resonator MTE body."""
    shrunk = _offset_collar(
        collar, -cfg.skill_collar_shrink_um, precision=cfg.boolean_precision
    )
    if shrunk is None:
        return []
    grown: list[gdstk.Polygon] = []
    for body in body_mte_polys:
        piece = _offset_collar(
            body, cfg.skill_body_grow_um, precision=cfg.boolean_precision
        )
        if piece is not None:
            grown.append(piece)
    if not grown:
        return [(float(x), float(y)) for x, y in shrunk.points]

    probe_half = cfg.inside_probe_half_um
    out: list[Point] = []
    for x, y in shrunk.points:
        pt = (float(x), float(y))
        inside_any = False
        for body in grown:
            probe = gdstk.rectangle(
                (pt[0] - probe_half, pt[1] - probe_half),
                (pt[0] + probe_half, pt[1] + probe_half),
            )
            if gdstk.boolean(probe, body, "and", precision=cfg.boolean_precision):
                inside_any = True
                break
        if not inside_any:
            out.append(pt)
    deduped: list[Point] = []
    for pt in out:
        if not any(math.hypot(pt[0] - q[0], pt[1] - q[1]) < 0.05 for q in deduped):
            deduped.append(pt)
    return deduped


def _skill_pad_vtb_corners(
    signal_polys: Sequence[gdstk.Polygon],
    *,
    expand_um: float,
) -> tuple[Point, Point]:
    """SKILL vtb anchors: top-right and bottom-right of expanded signal pad rect."""
    boxes = [p.bounding_box() for p in signal_polys if p.bounding_box() is not None]
    if not boxes:
        raise ValueError("center signal pad has no geometry")
    x0 = min(b[0][0] for b in boxes) - expand_um
    y0 = min(b[0][1] for b in boxes) - expand_um
    x1 = max(b[1][0] for b in boxes) + expand_um
    y1 = max(b[1][1] for b in boxes) + expand_um
    _ = x0, y0
    return (x1, y1), (x1, y0)


def _skill_find_min_max_slope_point(
    origin: Point,
    targets: Sequence[Point],
    mode: str,
    *,
    exclude: Point | None = None,
    exclude_tol_um: float = 0.5,
) -> Point | None:
    """SKILL ``rdsBawFindMinMaxSlope2``."""
    if not targets:
        return None
    ox, oy = origin
    best: Point | None = None
    best_slope = float("-inf") if mode == "max" else float("inf")
    for tx, ty in targets:
        if exclude is not None and math.hypot(tx - exclude[0], ty - exclude[1]) < exclude_tol_um:
            continue
        if abs(tx - ox) < 1e-9:
            slope = float("inf") if ty > oy else float("-inf")
        else:
            slope = (ty - oy) / (tx - ox)
        if mode == "max":
            if slope > best_slope:
                best_slope = slope
                best = (tx, ty)
        elif slope < best_slope:
            best_slope = slope
            best = (tx, ty)
    return best


def _nearest_edge_index(pts: Sequence[Point], point: Point) -> int:
    n = len(pts)
    best_idx = 0
    best_dist = float("inf")
    for i in range(n):
        p0, p1 = pts[i], pts[(i + 1) % n]
        mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
        d = _dist(mid, point)
        if d < best_dist:
            best_dist = d
            best_idx = i
    return best_idx


def _mouth_outward_normal(
    point_a: Point,
    point_b: Point,
    body_centroid: Point,
    *,
    pad_ref: Point | None = None,
) -> tuple[float, float]:
    """Unit normal from the intercept chord toward the signal pad."""
    edge_dx = point_b[0] - point_a[0]
    edge_dy = point_b[1] - point_a[1]
    if abs(edge_dx) < 1e-9 and abs(edge_dy) < 1e-9:
        if pad_ref is not None:
            mid = point_a
            dx = pad_ref[0] - mid[0]
            dy = pad_ref[1] - mid[1]
        else:
            dx = point_a[0] - body_centroid[0]
            dy = point_a[1] - body_centroid[1]
    else:
        n1 = (-edge_dy, edge_dx)
        n2 = (edge_dy, -edge_dx)
        mid = ((point_a[0] + point_b[0]) / 2.0, (point_a[1] + point_b[1]) / 2.0)
        if pad_ref is not None:
            to_pad = (pad_ref[0] - mid[0], pad_ref[1] - mid[1])
            dot1 = n1[0] * to_pad[0] + n1[1] * to_pad[1]
            dot2 = n2[0] * to_pad[0] + n2[1] * to_pad[1]
            dx, dy = n1 if dot1 >= dot2 else n2
        else:
            dot1 = n1[0] * (mid[0] - body_centroid[0]) + n1[1] * (mid[1] - body_centroid[1])
            dot2 = n2[0] * (mid[0] - body_centroid[0]) + n2[1] * (mid[1] - body_centroid[1])
            dx, dy = n1 if dot1 >= dot2 else n2
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return (1.0, 0.0)
    return (dx / length, dy / length)


def _project_to_collar_boundary(point: Point, collar: gdstk.Polygon) -> Point:
    """Nearest point on the collar polygon boundary."""
    pts = [(float(x), float(y)) for x, y in collar.points]
    if len(pts) < 2:
        return point
    best = point
    best_d = float("inf")
    n = len(pts)
    px, py = point
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        length_sq = dx * dx + dy * dy
        if length_sq < 1e-18:
            t = 0.0
        else:
            t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / length_sq))
        qx, qy = x0 + t * dx, y0 + t * dy
        d = math.hypot(px - qx, py - qy)
        if d < best_d:
            best_d = d
            best = (qx, qy)
    return best


def find_outward_lip_ab(
    collar: gdstk.Polygon,
    body_mte_polys: Sequence[gdstk.Polygon],
    cfg: MteBuildConfig | None = None,
    *,
    signal_polys: Sequence[gdstk.Polygon] | None = None,
    collar_pieces: Sequence[gdstk.Polygon] | None = None,
) -> LipIntercept:
    """
    Collar mouth corners A and B at SKILL slope intercepts on the preserved collar.

    Uses ``rdsBawFindMinMaxSlope2`` from the signal-pad right-edge anchors to the
    outer MTE collar ring (``rdsBawResonatorTEGConnection``), not lip-edge search.
    """
    c = cfg or MteBuildConfig()
    if not signal_polys:
        raise ValueError("signal_polys required for SKILL collar intercept routing")

    pts = [(float(p[0]), float(p[1])) for p in collar.points]
    if len(pts) < 4:
        raise ValueError("collar must have at least 4 vertices")

    body_centroid = _body_centroid(body_mte_polys)
    pieces = list(collar_pieces) if collar_pieces else [collar]
    outer_pts: list[Point] = []
    for piece in pieces:
        outer_pts.extend(_skill_outer_collar_points(piece, body_mte_polys, c))
    deduped: list[Point] = []
    for pt in outer_pts:
        if not any(math.hypot(pt[0] - q[0], pt[1] - q[1]) < 0.05 for q in deduped):
            deduped.append(pt)
    outer_pts = deduped
    if len(outer_pts) < 2:
        raise ValueError("fewer than 2 outer MTE collar points for intercept routing")

    vtb_up, vtb_dn = _skill_pad_vtb_corners(
        signal_polys, expand_um=c.skill_pad_expand_um
    )
    pad_ref = ((vtb_up[0] + vtb_dn[0]) / 2.0, (vtb_up[1] + vtb_dn[1]) / 2.0)
    collar_cx = sum(p[0] for p in pts) / len(pts)
    if pad_ref[0] <= collar_cx:
        facing = [p for p in outer_pts if p[0] <= collar_cx + 30.0]
    else:
        facing = [p for p in outer_pts if p[0] >= collar_cx - 30.0]
    if len(facing) >= 2:
        outer_pts = facing

    mte_up = _skill_find_min_max_slope_point(vtb_up, outer_pts, "max")
    mte_dn = _skill_find_min_max_slope_point(
        vtb_dn, outer_pts, "min", exclude=mte_up
    )
    if mte_dn is None:
        mte_dn = _skill_find_min_max_slope_point(vtb_dn, outer_pts, "min")
    if mte_up is None or mte_dn is None:
        raise ValueError("SKILL slope intercept search failed on MTE collar")

    point_a = _project_to_collar_boundary(mte_up, collar)
    point_b = _project_to_collar_boundary(mte_dn, collar)
    if math.hypot(point_a[0] - point_b[0], point_a[1] - point_b[1]) < 1.0:
        alt = _skill_find_min_max_slope_point(
            vtb_dn, outer_pts, "min", exclude=point_a, exclude_tol_um=1.0
        )
        if alt is not None:
            point_b = _project_to_collar_boundary(alt, collar)
    if math.hypot(point_a[0] - point_b[0], point_a[1] - point_b[1]) < 1.0 and len(outer_pts) >= 2:
        hi = max(outer_pts, key=lambda p: p[1])
        lo = min(outer_pts, key=lambda p: p[1])
        point_a = _project_to_collar_boundary(hi, collar)
        point_b = _project_to_collar_boundary(lo, collar)
    if point_a[1] < point_b[1] or (
        abs(point_a[1] - point_b[1]) < 1e-6 and point_a[0] < point_b[0]
    ):
        point_a, point_b = point_b, point_a

    edge_a = _nearest_edge_index(pts, point_a)
    edge_b = _nearest_edge_index(pts, point_b)
    lip_edges = [edge_a] if edge_a == edge_b else [edge_a, edge_b]
    lip_vertices = _vertices_from_edge_chain(lip_edges, len(pts))
    outward_normal = _mouth_outward_normal(
        point_a, point_b, body_centroid, pad_ref=pad_ref
    )

    return LipIntercept(
        point_a=point_a,
        point_b=point_b,
        lip_vertex_indices=lip_vertices,
        outward_normal=outward_normal,
        lip_edges=lip_edges,
    )


def _point_inside_polygon(
    point: Point,
    polygon: gdstk.Polygon,
    *,
    precision: float,
    probe_half_um: float,
) -> bool:
    probe = gdstk.rectangle(
        (point[0] - probe_half_um, point[1] - probe_half_um),
        (point[0] + probe_half_um, point[1] + probe_half_um),
    )
    return bool(gdstk.boolean(probe, polygon, "and", precision=precision))


def _feasible_merge_um(
    point: Point,
    outward: tuple[float, float],
    collar: gdstk.Polygon,
    target_um: float,
    *,
    precision: float,
    probe_half_um: float,
    search_iterations: int,
) -> float:
    """Largest inward merge (toward body, ``-outward``) that stays inside the collar."""
    ix, iy = -outward[0], -outward[1]
    lo, hi = 0.0, target_um
    best = 0.0
    for _ in range(search_iterations):
        mid = (lo + hi) / 2.0
        test = (point[0] + ix * mid, point[1] + iy * mid)
        if _point_inside_polygon(
            test, collar, precision=precision, probe_half_um=probe_half_um
        ):
            best = mid
            lo = mid
        else:
            hi = mid
    return best


def draw_lip_extension(
    collar: gdstk.Polygon,
    lip: LipIntercept,
    body_mte_polys: Sequence[gdstk.Polygon],
    cfg: MteBuildConfig,
    layer: int,
    datatype: int,
) -> CollarExtensionDraw:
    """
    Draw one new MTE polygon extruding outward from intercepts A and B.

    Inset and extrusion use the outward normal from ``find_outward_lip_ab``
    (perpendicular to the lip, away from resonator-body MTE). The inner edge is
    shifted ``merge_um`` toward the body; the whole rectangle is then shifted a
    little further into the collar (``touch_overlap_um``) so it meets preserved
    metal in layout viewers. The outer edge is ``collar_extension_um`` from the mouth.
    """
    extension_um = cfg.collar_extension_um
    merge_um = cfg.collar_merge_inset_um
    touch_overlap_um = cfg.collar_touch_overlap_um
    boolean_precision = cfg.boolean_precision

    if extension_um <= 0:
        raise ValueError("extension_um must be positive")
    if merge_um <= 0:
        raise ValueError("merge_um must be positive")
    if touch_overlap_um < 0:
        raise ValueError("touch_overlap_um must be non-negative")

    _ = body_mte_polys  # lip.outward_normal already encodes body-relative direction
    ox, oy = lip.outward_normal
    olen = math.hypot(ox, oy)
    if olen < 1e-9:
        raise ValueError("lip outward_normal is degenerate")
    ox, oy = ox / olen, oy / olen

    merge_a = _feasible_merge_um(
        lip.point_a,
        (ox, oy),
        collar,
        merge_um,
        precision=boolean_precision,
        probe_half_um=cfg.inside_probe_half_um,
        search_iterations=cfg.feasible_merge_search_iterations,
    )
    merge_b = _feasible_merge_um(
        lip.point_b,
        (ox, oy),
        collar,
        merge_um,
        precision=boolean_precision,
        probe_half_um=cfg.inside_probe_half_um,
        search_iterations=cfg.feasible_merge_search_iterations,
    )
    if min(merge_a, merge_b) < cfg.min_merge_inset_check_um * 0.5:
        ox, oy = -ox, -oy
        merge_a = _feasible_merge_um(
            lip.point_a,
            (ox, oy),
            collar,
            merge_um,
            precision=boolean_precision,
            probe_half_um=cfg.inside_probe_half_um,
            search_iterations=cfg.feasible_merge_search_iterations,
        )
        merge_b = _feasible_merge_um(
            lip.point_b,
            (ox, oy),
            collar,
            merge_um,
            precision=boolean_precision,
            probe_half_um=cfg.inside_probe_half_um,
            search_iterations=cfg.feasible_merge_search_iterations,
        )

    inner_a = (
        lip.point_a[0] - ox * merge_a,
        lip.point_a[1] - oy * merge_a,
    )
    inner_b = (
        lip.point_b[0] - ox * merge_b,
        lip.point_b[1] - oy * merge_b,
    )
    outer_a = (
        lip.point_a[0] + ox * extension_um,
        lip.point_a[1] + oy * extension_um,
    )
    outer_b = (
        lip.point_b[0] + ox * extension_um,
        lip.point_b[1] + oy * extension_um,
    )

    # Shift the whole extension into the collar (ΓêÆoutward) to close sub-┬╡m viewer gaps.
    if touch_overlap_um > 0:
        total_a = _feasible_merge_um(
            lip.point_a,
            (ox, oy),
            collar,
            merge_um + touch_overlap_um,
            precision=boolean_precision,
            probe_half_um=cfg.inside_probe_half_um,
            search_iterations=cfg.feasible_merge_search_iterations,
        )
        total_b = _feasible_merge_um(
            lip.point_b,
            (ox, oy),
            collar,
            merge_um + touch_overlap_um,
            precision=boolean_precision,
            probe_half_um=cfg.inside_probe_half_um,
            search_iterations=cfg.feasible_merge_search_iterations,
        )
        shift = min(
            touch_overlap_um,
            max(0.0, total_a - merge_a),
            max(0.0, total_b - merge_b),
        )
        if shift > 0:
            sx, sy = -ox * shift, -oy * shift
            inner_a = (inner_a[0] + sx, inner_a[1] + sy)
            inner_b = (inner_b[0] + sx, inner_b[1] + sy)
            outer_a = (outer_a[0] + sx, outer_a[1] + sy)
            outer_b = (outer_b[0] + sx, outer_b[1] + sy)
            merge_a += shift
            merge_b += shift

    polygon = gdstk.Polygon(
        [inner_a, inner_b, outer_b, outer_a],
        layer=layer,
        datatype=datatype,
    )
    span = _dist(lip.point_a, lip.point_b)
    pts = [(float(p[0]), float(p[1])) for p in collar.points]
    edge_a = _edge_points(pts, lip.lip_edges[0])
    edge_b = _edge_points(pts, lip.lip_edges[-1])

    return CollarExtensionDraw(
        polygon=polygon,
        intercept_a=inner_a,
        intercept_b=inner_b,
        outer_edge=(outer_b, outer_a),
        extension_um=extension_um,
        target_extension_um=extension_um,
        endcap_edge_a=edge_a,
        endcap_edge_b=edge_b,
        endcap_index_a=lip.lip_edges[0],
        endcap_index_b=lip.lip_edges[-1],
        mouth_span_um=span,
        mouth_vertices=2,
        collar_intercept_a=lip.point_a,
        collar_intercept_b=lip.point_b,
        merge_inset_a_um=merge_a,
        merge_inset_b_um=merge_b,
    )


def _collar_overlap_area(
    ext: gdstk.Polygon, collar: gdstk.Polygon, precision: float
) -> float:
    inter = gdstk.boolean(ext, collar, "and", precision=precision)
    return sum(abs(p.area()) for p in inter) if inter else 0.0


def extension_is_connected(
    ext: gdstk.Polygon,
    collar: gdstk.Polygon,
    draw: CollarExtensionDraw,
    cfg: MteBuildConfig,
) -> bool:
    """
    True when the extension is materially merged into the collar, not merely
    touching at a boolean sliver.

    Requires meaningful overlap area, both mouth corners merged into the collar
    by at least ``min_connection_merge_um``, and overlap covering at least
    ``min_connection_overlap_fraction`` of the extension polygon.
    """
    overlap = _collar_overlap_area(ext, collar, cfg.boolean_precision)
    if overlap < cfg.min_collar_overlap_um2:
        return False
    ext_area = abs(ext.area())
    if ext_area > 1e-6 and overlap / ext_area < cfg.min_connection_overlap_fraction:
        return False
    min_merge = min(draw.merge_inset_a_um, draw.merge_inset_b_um)
    collar_area = abs(collar.area())

    if collar_area < cfg.stadium_collar_area_um2:
        if collar_area < 700.0:
            min_merge_req = cfg.min_connection_merge_um
        else:
            min_merge_req = cfg.min_merge_inset_check_um * 0.6
        min_mouth_req = cfg.min_mouth_coverage_fraction
        collar_bb = collar.bounding_box()
        mouth_coverage = 0.0
        if collar_bb is not None:
            (x0, y0), (x1, y1) = collar_bb
            collar_width = max(x1 - x0, y1 - y0)
            if collar_width > 1e-6:
                mouth_coverage = draw.mouth_span_um / collar_width
        if min_merge < min_merge_req:
            return False
        if mouth_coverage < min_mouth_req:
            return False
        return True

    min_merge_req = cfg.min_merge_inset_check_um * 0.6
    if min_merge < min_merge_req:
        return False
    return (
        cfg.stadium_tab_mouth_min_um
        <= draw.mouth_span_um
        <= cfg.stadium_tab_mouth_max_um
    )


def _validate_extension(
    ext: gdstk.Polygon,
    collar: gdstk.Polygon,
    cfg: MteBuildConfig,
    *,
    resonator_index: int | None = None,
    merge_inset_points: Sequence[Point] | None = None,
    merge_inset_um: Sequence[float] | None = None,
) -> None:
    overlap = _collar_overlap_area(ext, collar, cfg.boolean_precision)
    collar_area = abs(collar.area())
    prefix = f"resonator {resonator_index}: " if resonator_index is not None else ""
    if merge_inset_points and merge_inset_um:
        for idx, (pt, merge) in enumerate(zip(merge_inset_points, merge_inset_um, strict=True)):
            if merge >= cfg.min_merge_inset_check_um and not _point_inside_polygon(
                pt,
                collar,
                precision=cfg.boolean_precision,
                probe_half_um=cfg.inside_probe_half_um,
            ):
                raise ValueError(
                    f"{prefix}MTE extension merge inset {idx} is not inside collar "
                    f"(placement error, not overlap area)"
                )
    if overlap < cfg.min_collar_overlap_um2:
        raise ValueError(
            f"{prefix}MTE extension not attached to collar "
            f"(overlap {overlap:.2f} um┬▓ < {cfg.min_collar_overlap_um2:.2f} um┬▓)"
        )
    if collar_area > 1e-6 and overlap / collar_area > cfg.max_overlap_fraction:
        raise ValueError(
            f"{prefix}MTE extension covers too much of collar "
            f"(overlap/collar = {overlap / collar_area:.2f} > {cfg.max_overlap_fraction})"
        )


def draw_collar_extension(
    collar_tp: TaggedPolygon,
    layermap: LayerMap,
    cfg: MteBuildConfig,
    *,
    body_mte_polys: Sequence[gdstk.Polygon],
    signal_polys: Sequence[gdstk.Polygon],
    collar_pieces: Sequence[gdstk.Polygon] | None = None,
    resonator_index: int | None = None,
) -> CollarExtensionDraw:
    layer, datatype = layermap.pair(cfg.mte_layer)
    lip = find_outward_lip_ab(
        collar_tp.polygon,
        body_mte_polys,
        cfg,
        signal_polys=signal_polys,
        collar_pieces=collar_pieces,
    )
    draw = draw_lip_extension(
        collar_tp.polygon,
        lip,
        body_mte_polys,
        cfg,
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
        merge_inset_a_um=draw.merge_inset_a_um,
        merge_inset_b_um=draw.merge_inset_b_um,
    )
    _validate_extension(
        draw.polygon,
        collar_tp.polygon,
        cfg,
        resonator_index=resonator_index,
        merge_inset_points=(draw.intercept_a, draw.intercept_b),
        merge_inset_um=(draw.merge_inset_a_um, draw.merge_inset_b_um),
    )
    return draw


def build_preserved_extension_draw(
    collar_tp: TaggedPolygon,
    layermap: LayerMap,
    cfg: MteBuildConfig,
    *,
    body_mte_polys: Sequence[gdstk.Polygon],
    signal_polys: Sequence[gdstk.Polygon],
    collar_pieces: Sequence[gdstk.Polygon] | None = None,
    resonator_index: int | None = None,
) -> CollarExtensionDraw:
    """
    Routing metadata for filter-preserved MTE — no new geometry is drawn.

    Collar intercepts come from ``find_outward_lip_ab``; the polygon is the
    existing preserved interconnect piece already on the frame cell.
    """
    _ = resonator_index
    collar = collar_tp.polygon
    lip = find_outward_lip_ab(
        collar,
        body_mte_polys,
        cfg,
        signal_polys=signal_polys,
        collar_pieces=collar_pieces,
    )
    ox, oy = lip.outward_normal
    olen = math.hypot(ox, oy)
    if olen < 1e-9:
        raise ValueError("lip outward_normal is degenerate")
    ox, oy = ox / olen, oy / olen

    merge_a = _feasible_merge_um(
        lip.point_a,
        (ox, oy),
        collar,
        cfg.collar_merge_inset_um,
        precision=cfg.boolean_precision,
        probe_half_um=cfg.inside_probe_half_um,
        search_iterations=cfg.feasible_merge_search_iterations,
    )
    merge_b = _feasible_merge_um(
        lip.point_b,
        (ox, oy),
        collar,
        cfg.collar_merge_inset_um,
        precision=cfg.boolean_precision,
        probe_half_um=cfg.inside_probe_half_um,
        search_iterations=cfg.feasible_merge_search_iterations,
    )
    inner_a = (lip.point_a[0] - ox * merge_a, lip.point_a[1] - oy * merge_a)
    inner_b = (lip.point_b[0] - ox * merge_b, lip.point_b[1] - oy * merge_b)
    cap_um = cfg.collar_extension_um
    outer_a = (inner_a[0] + ox * cap_um, inner_a[1] + oy * cap_um)
    outer_b = (inner_b[0] + ox * cap_um, inner_b[1] + oy * cap_um)
    layer, datatype = layermap.pair(cfg.mte_layer)
    poly = assign_layer(collar, layermap, cfg.mte_layer)
    _ = layer, datatype
    pts = [(float(p[0]), float(p[1])) for p in collar.points]
    edge_a = _edge_points(pts, lip.lip_edges[0]) if lip.lip_edges else ((0.0, 0.0), (0.0, 0.0))
    edge_b = _edge_points(pts, lip.lip_edges[-1]) if lip.lip_edges else edge_a

    return CollarExtensionDraw(
        polygon=poly,
        intercept_a=inner_a,
        intercept_b=inner_b,
        outer_edge=(outer_b, outer_a),
        extension_um=0.0,
        target_extension_um=0.0,
        endcap_edge_a=edge_a,
        endcap_edge_b=edge_b,
        endcap_index_a=lip.lip_edges[0] if lip.lip_edges else -1,
        endcap_index_b=lip.lip_edges[-1] if lip.lip_edges else -1,
        mouth_span_um=_dist(lip.point_a, lip.point_b),
        mouth_vertices=2,
        collar_intercept_a=lip.point_a,
        collar_intercept_b=lip.point_b,
        merge_inset_a_um=merge_a,
        merge_inset_b_um=merge_b,
    )


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
        cfg,
    )
    if collar_tp is None:
        raise ValueError(
            f"resonator {resonator_index}: no preserved MTE collar to extend"
        )
    signal_polys = [tp.polygon for tp in roles.ground_plates.center]
    if not signal_polys:
        raise ValueError(
            f"resonator {resonator_index}: no center signal pad for collar intercept"
        )
    draw = build_preserved_extension_draw(
        collar_tp,
        layermap,
        cfg,
        body_mte_polys=roles.resonator_body_mte,
        signal_polys=signal_polys,
        collar_pieces=preserved_polys,
        resonator_index=resonator_index,
    )
    return MteExtensionResult(
        collar=collar_tp,
        extension=draw.polygon,
        preserved_collar_polygons=preserved_polys,
        n_extensions=0,
        is_connected=True,
        collar_overlap_um2=abs(draw.polygon.area()),
        extension_draw=draw,
        resonator_body_mte_polys=list(roles.resonator_body_mte),
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


def _fmt_point(pt: Point) -> str:
    return f"({pt[0]:.2f}, {pt[1]:.2f})"


def _fmt_edge(edge: Edge) -> str:
    return f"{_fmt_point(edge[0])} -> {_fmt_point(edge[1])}"


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
                "collar_overlap_um2": round(result.collar_overlap_um2, 2),
                "is_connected": result.is_connected,
            }
        )
    return rows


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
                    "lip_edge_index": None,
                    "merge_inset_a_um": None,
                    "merge_inset_b_um": None,
                    "min_merge_um": None,
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
                    "lip_edge_index": draw.endcap_index_a,
                    "merge_inset_a_um": round(draw.merge_inset_a_um, 2),
                    "merge_inset_b_um": round(draw.merge_inset_b_um, 2),
                    "min_merge_um": round(
                        min(draw.merge_inset_a_um, draw.merge_inset_b_um), 2
                    ),
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
    layermap: LayerMap | None = None
    mbe_extension: object | None = None
    mbe_body: object | None = None

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

    def _strip_raw_filler(self, cell: gdstk.Cell) -> None:
        """Remove the step-4 width filler rectangle before writing the carved body."""
        if self.layermap is None:
            return
        mbe_pair = self.layermap.pair("BAW_MBE")
        (fx0, fy0), (fx1, fy1) = self.frame.mbe_filler_bbox
        tol = 1.0
        keep: list[gdstk.Polygon] = []
        for poly in cell.polygons:
            if (poly.layer, poly.datatype) != mbe_pair:
                keep.append(poly)
                continue
            bb = poly.bounding_box()
            if bb is None:
                keep.append(poly)
                continue
            if (
                abs(bb[0][0] - fx0) <= tol
                and abs(bb[0][1] - fy0) <= tol
                and abs(bb[1][0] - fx1) <= tol
                and abs(bb[1][1] - fy1) <= tol
            ):
                continue
            keep.append(poly)
        cell.remove(*cell.polygons)
        cell.add(*keep)

    def _strip_absorbed_mbe(
        self,
        cell: gdstk.Cell,
        absorbed: Sequence[gdstk.Polygon],
        *,
        overlap_fraction: float = 0.85,
        boolean_precision: float = 1e-3,
    ) -> None:
        """Drop preserved MBE polygons already merged into the center-pad filler."""
        if not absorbed or self.layermap is None:
            return
        mbe_pair = self.layermap.pair("BAW_MBE")
        keep: list[gdstk.Polygon] = []
        for poly in cell.polygons:
            if (poly.layer, poly.datatype) != mbe_pair:
                keep.append(poly)
                continue
            drop = False
            poly_area = abs(poly.area())
            for target in absorbed:
                overlap = gdstk.boolean(
                    poly,
                    target,
                    "and",
                    precision=boolean_precision,
                )
                if not overlap:
                    continue
                overlap_area = sum(abs(p.area()) for p in overlap)
                if poly_area > 1e-6 and overlap_area / poly_area >= overlap_fraction:
                    drop = True
                    break
            if not drop:
                keep.append(poly)
        cell.remove(*cell.polygons)
        cell.add(*keep)

    def _strip_mbe_inside_filler_bbox(
        self,
        cell: gdstk.Cell,
        filler: gdstk.Polygon,
        *,
        tol: float = 1.0,
    ) -> None:
        """Clear frame MBE inside the step-4 filler window before writing the body."""
        if self.layermap is None:
            return
        mbe_pair = self.layermap.pair("BAW_MBE")
        fbb = filler.bounding_box()
        if fbb is None:
            return
        (fx0, fy0), (fx1, fy1) = fbb
        keep: list[gdstk.Polygon] = []
        for poly in cell.polygons:
            if (poly.layer, poly.datatype) != mbe_pair:
                keep.append(poly)
                continue
            bb = poly.bounding_box()
            if bb is None:
                keep.append(poly)
                continue
            inside = (
                bb[0][0] >= fx0 - tol
                and bb[0][1] >= fy0 - tol
                and bb[1][0] <= fx1 + tol
                and bb[1][1] <= fy1 + tol
            )
            if inside:
                continue
            keep.append(poly)
        cell.remove(*cell.polygons)
        cell.add(*keep)

    def _strip_overlapping_mbe_in_filler(
        self,
        cell: gdstk.Cell,
        filler_polys: Sequence[gdstk.Polygon],
        *,
        overlap_fraction: float = 0.85,
        boolean_precision: float = 1e-3,
    ) -> None:
        """Remove frame MBE that substantially duplicates generated filler metal."""
        if not filler_polys or self.layermap is None:
            return
        mbe_pair = self.layermap.pair("BAW_MBE")
        keep: list[gdstk.Polygon] = []
        for poly in cell.polygons:
            if (poly.layer, poly.datatype) != mbe_pair:
                keep.append(poly)
                continue
            poly_area = abs(poly.area())
            drop = False
            for filler in filler_polys:
                overlap = gdstk.boolean(
                    poly,
                    filler,
                    "and",
                    precision=boolean_precision,
                )
                if not overlap:
                    continue
                overlap_area = sum(abs(p.area()) for p in overlap)
                if (
                    poly_area > 1e-6
                    and overlap_area / poly_area >= overlap_fraction
                ):
                    drop = True
                    break
            if not drop:
                keep.append(poly)
        cell.remove(*cell.polygons)
        cell.add(*keep)

    def _strip_mbe_merged_into_route(
        self,
        cell: gdstk.Cell,
        routed_net: gdstk.Polygon,
        *,
        overlap_fraction: float = 0.85,
        boolean_precision: float = 1e-3,
    ) -> None:
        """Drop preserved MBE polygons already merged into the routed net."""
        if self.layermap is None:
            return
        mbe_pair = self.layermap.pair("BAW_MBE")
        keep: list[gdstk.Polygon] = []
        for poly in cell.polygons:
            if (poly.layer, poly.datatype) != mbe_pair:
                keep.append(poly)
                continue
            overlap = gdstk.boolean(
                poly, routed_net, "and", precision=boolean_precision
            )
            poly_area = abs(poly.area())
            if (
                overlap
                and poly_area > 1e-6
                and sum(abs(p.area()) for p in overlap) / poly_area
                >= overlap_fraction
            ):
                continue
            keep.append(poly)
        cell.remove(*cell.polygons)
        cell.add(*keep)

    def _strip_mte_merged_into_route(
        self,
        cell: gdstk.Cell,
        routed_net: gdstk.Polygon,
        *,
        overlap_fraction: float = 0.85,
        boolean_precision: float = 1e-3,
    ) -> None:
        """Drop preserved MTE polygons already merged into the routed net."""
        if self.layermap is None:
            return
        mte_pair = self.layermap.pair("BAW_MTE")
        keep: list[gdstk.Polygon] = []
        for poly in cell.polygons:
            if (poly.layer, poly.datatype) != mte_pair:
                keep.append(poly)
                continue
            overlap = gdstk.boolean(
                poly, routed_net, "and", precision=boolean_precision
            )
            poly_area = abs(poly.area())
            if (
                overlap
                and poly_area > 1e-6
                and sum(abs(p.area()) for p in overlap) / poly_area
                >= overlap_fraction
            ):
                continue
            keep.append(poly)
        cell.remove(*cell.polygons)
        cell.add(*keep)

    def _strip_mte_extension_stub(
        self,
        cell: gdstk.Cell,
        replaced: gdstk.Polygon,
        *,
        reshaped: gdstk.Polygon | None = None,
        overlap_fraction: float = 0.15,
        max_extension_area_um2: float = 6000.0,
        boolean_precision: float = 1e-3,
    ) -> None:
        """Drop preserved MTE extension stubs replaced by step 6.2 reshape."""
        if self.layermap is None:
            return
        mte_pair = self.layermap.pair("BAW_MTE")
        targets = [replaced]
        if reshaped is not None:
            targets.append(reshaped)
        reshaped_bbox = reshaped.bounding_box() if reshaped is not None else None
        keep: list[gdstk.Polygon] = []
        for poly in cell.polygons:
            if (poly.layer, poly.datatype) != mte_pair:
                keep.append(poly)
                continue
            poly_area = abs(poly.area())
            drop = False
            for target in targets:
                overlap = gdstk.boolean(
                    poly, target, "and", precision=boolean_precision
                )
                if (
                    overlap
                    and poly_area > 1e-6
                    and sum(abs(p.area()) for p in overlap) / poly_area
                    >= overlap_fraction
                ):
                    drop = True
                    break
            if (
                not drop
                and reshaped_bbox is not None
                and len(poly.points) > 20
                and poly_area <= max_extension_area_um2
            ):
                poly_bbox = poly.bounding_box()
                if poly_bbox is not None and _bbox_intersects(
                    poly_bbox, reshaped_bbox, margin_um=2.0
                ):
                    drop = True
            if drop:
                continue
            keep.append(poly)
        cell.remove(*cell.polygons)
        cell.add(*keep)

    def _polygon_matches_any(
        self,
        poly: gdstk.Polygon,
        candidates: Sequence[gdstk.Polygon],
        *,
        boolean_precision: float = 1e-3,
        overlap_fraction: float = 0.85,
    ) -> bool:
        if _polygon_key(poly) in {_polygon_key(c) for c in candidates}:
            return True
        poly_area = abs(poly.area())
        if poly_area < 1e-6:
            return False
        for target in candidates:
            inter = gdstk.boolean(poly, target, "and", precision=boolean_precision)
            if not inter:
                continue
            overlap = sum(abs(p.area()) for p in inter)
            if overlap / poly_area >= overlap_fraction:
                return True
        return False

    def _strip_preserved_mte_except(
        self,
        cell: gdstk.Cell,
        keep: Sequence[gdstk.Polygon],
        *,
        preserved_pool: Sequence[gdstk.Polygon] | None = None,
        boolean_precision: float = 1e-3,
        overlap_fraction: float = 0.85,
    ) -> None:
        """Drop attached filter MTE on ``cell`` except the collar + extension stub."""
        if self.layermap is None:
            return
        if not keep and not preserved_pool:
            return
        mte_pair = self.layermap.pair("BAW_MTE")
        pool = list(preserved_pool or keep)

        kept: list[gdstk.Polygon] = []
        for poly in cell.polygons:
            if (poly.layer, poly.datatype) != mte_pair:
                kept.append(poly)
                continue
            if pool and not self._polygon_matches_any(
                poly,
                pool,
                boolean_precision=boolean_precision,
                overlap_fraction=overlap_fraction,
            ):
                kept.append(poly)
                continue
            if self._polygon_matches_any(
                poly,
                keep,
                boolean_precision=boolean_precision,
                overlap_fraction=overlap_fraction,
            ):
                kept.append(poly)
        cell.remove(*cell.polygons)
        cell.add(*kept)

    def _strip_preserved_mte_for_pad_route_on_frame(self) -> None:
        """
        Drop extra filter ``connectMTE`` pieces on the frame cell only.

        Resonator-body MTE lives inside the resonator reference and is untouched.
        Frame-template MTE (pads, etc.) is also untouched.

        Applies only when step 5.4 routed to the center pad (``routed_net`` set);
        ``collar_extend`` resonators skip this path entirely.
        """
        if self.layermap is None or self.extension.routed_net is None:
            return
        from rteg_mte_route import identify_preserved_mte_parts

        try:
            parts = identify_preserved_mte_parts(
                self.extension.preserved_collar_polygons,
                self.extension.resonator_body_mte_polys,
            )
        except ValueError:
            return
        max_vertices = MteBuildConfig().max_preserved_mte_vertices_after_pad_route
        keep: list[gdstk.Polygon] = []
        if len(parts.extension.points) <= max_vertices:
            keep.append(parts.extension)
        if parts.collar is not None and len(parts.collar.points) <= max_vertices:
            keep.append(parts.collar)
        self._strip_preserved_mte_except(
            self.frame.top_cell,
            keep,
            preserved_pool=self.extension.preserved_collar_polygons,
        )

    def _connected_mte_cluster(
        self,
        mte_polys: Sequence[gdstk.Polygon],
        seeds: Sequence[gdstk.Polygon],
        *,
        boolean_precision: float = 1e-3,
        overlap_fraction: float = 0.85,
    ) -> list[gdstk.Polygon]:
        """Flood-fill MTE polygons that boolean-touch any seed."""
        cluster: list[gdstk.Polygon] = []
        for seed in seeds:
            for poly in mte_polys:
                if poly in cluster:
                    continue
                if self._polygon_matches_any(
                    poly,
                    [seed],
                    boolean_precision=boolean_precision,
                    overlap_fraction=overlap_fraction,
                ) or polys_touch(poly, seed, precision=boolean_precision):
                    cluster.append(poly)

        changed = True
        while changed:
            changed = False
            for poly in mte_polys:
                if poly in cluster:
                    continue
                if any(
                    polys_touch(poly, member, precision=boolean_precision)
                    for member in cluster
                ):
                    cluster.append(poly)
                    changed = True
        return cluster

    def _strip_disconnected_preserved_mte(self, cell: gdstk.Cell) -> None:
        """
        Drop preserved filter MTE that does not touch the routed signal cluster.

        After step 5.4 the layout should retain only resonator-body MTE, the
        extension stub, any collar that actually bridges to them, and the pad
        route. Spurious stadium shells or distant ``connectMTE`` tabs that
        ``identify_preserved_mte_parts`` mis-labels as the collar are removed.
        Frame-template MTE (pads, etc.) is untouched.
        """
        if self.layermap is None or self.extension.routed_net is None:
            return
        from rteg_mte_route import identify_preserved_mte_parts

        mte_pair = self.layermap.pair("BAW_MTE")
        mte_polys = [p for p in cell.polygons if (p.layer, p.datatype) == mte_pair]
        if not mte_polys:
            return

        pool = self.extension.preserved_collar_polygons
        seeds: list[gdstk.Polygon] = list(self.extension.resonator_body_mte_polys)
        seeds.append(self.extension.routed_net)
        try:
            parts = identify_preserved_mte_parts(
                self.extension.preserved_collar_polygons,
                self.extension.resonator_body_mte_polys,
            )
            seeds.append(parts.extension)
        except ValueError:
            pass

        cluster = self._connected_mte_cluster(mte_polys, seeds)
        cluster_ids = {id(p) for p in cluster}

        kept: list[gdstk.Polygon] = []
        for poly in cell.polygons:
            if (poly.layer, poly.datatype) != mte_pair:
                kept.append(poly)
                continue
            if pool and not self._polygon_matches_any(poly, pool):
                kept.append(poly)
                continue
            if id(poly) in cluster_ids:
                kept.append(poly)
        cell.remove(*cell.polygons)
        cell.add(*kept)

    def _strip_complex_preserved_mte(self, cell: gdstk.Cell) -> None:
        """
        Drop high-vertex preserved filter MTE left under the step-5.4 route.

        Filter ``connectMTE`` stadium shells (often 100+ vertices) can overlap
        the clean pad-route quad; resonator-body MTE and the routed net are kept.
        """
        if self.layermap is None or self.extension.routed_net is None:
            return
        max_vertices = MteBuildConfig().max_preserved_mte_vertices_after_pad_route
        mte_pair = self.layermap.pair("BAW_MTE")
        pool = self.extension.preserved_collar_polygons
        routed = self.extension.routed_net

        kept: list[gdstk.Polygon] = []
        for poly in cell.polygons:
            if (poly.layer, poly.datatype) != mte_pair:
                kept.append(poly)
                continue
            if pool and self._polygon_matches_any(poly, pool):
                if self._polygon_matches_any(poly, [routed]):
                    kept.append(poly)
                    continue
                if len(poly.points) > max_vertices:
                    continue
            kept.append(poly)
        cell.remove(*cell.polygons)
        cell.add(*kept)

    def flatten(self) -> gdstk.Cell:
        if self.extension.routed_net is not None:
            self._strip_preserved_mte_for_pad_route_on_frame()
        cell = self.frame.flatten().copy(f"rteg_{self.index:02d}_{self.inst_name}_mte")
        if self.mbe_body is not None and getattr(self.mbe_body, "n_pieces", 0) > 0:
            self._strip_raw_filler(cell)
            absorbed = getattr(self.mbe_body, "absorbed_mbe", None) or []
            if absorbed:
                self._strip_absorbed_mbe(cell, absorbed)
        if self.extension.routed_net is not None:
            net = self.extension.routed_net
            self._strip_mte_merged_into_route(cell, net)
            cell.add(gdstk.Polygon(net.points, net.layer, net.datatype))
            self._strip_disconnected_preserved_mte(cell)
            self._strip_complex_preserved_mte(cell)
        elif self.extension.n_extensions > 0 and self.extension.extension is not None:
            net = self.extension.extension
            self._strip_mte_merged_into_route(cell, net)
            cell.add(gdstk.Polygon(net.points, net.layer, net.datatype))
        if self.layermap is not None and self.mbe_extension is not None:
            mbe_net = self.mbe_extension.routed_net or self.mbe_extension.extension
            if mbe_net is not None and self.mbe_extension.n_extensions > 0:
                self._strip_mbe_merged_into_route(cell, mbe_net)
                tagged = assign_layer(mbe_net, self.layermap, "BAW_MBE")
                cell.add(gdstk.Polygon(tagged.points, tagged.layer, tagged.datatype))
        if self.layermap is not None and self.mbe_body is not None:
            body = self.mbe_body
            reshaped_mte = getattr(body, "mte_extension", None)
            if reshaped_mte is not None:
                replaced = getattr(body, "replaced_mte_extension", None) or reshaped_mte
                self._strip_mte_extension_stub(
                    cell,
                    replaced,
                    reshaped=reshaped_mte,
                    overlap_fraction=0.15,
                )
                tagged = assign_layer(reshaped_mte, self.layermap, "BAW_MTE")
                cell.add(
                    gdstk.Polygon(tagged.points, tagged.layer, tagged.datatype)
                )
            if getattr(body, "cap", None) is not None:
                tagged = assign_layer(body.cap, self.layermap, "BAW_MBE")
                cell.add(gdstk.Polygon(tagged.points, tagged.layer, tagged.datatype))
            filler_polys = getattr(body, "filler", []) or []
            if len(filler_polys) == 1:
                self._strip_mbe_inside_filler_bbox(cell, filler_polys[0])
            elif filler_polys:
                self._strip_overlapping_mbe_in_filler(cell, filler_polys)
            for poly in filler_polys:
                tagged = assign_layer(poly, self.layermap, "BAW_MBE")
                cell.add(gdstk.Polygon(tagged.points, tagged.layer, tagged.datatype))
        return cell


def export_mte_extensions_gds(
    frame_assemblies: Sequence[RtegFrameAssembly],
    extensions: Mapping[int, MteExtensionResult],
    output_dir: str | Path,
    *,
    layermap: LayerMap,
    mbe_extensions: Mapping[int, object] | None = None,
    mbe_bodies: Mapping[int, object] | None = None,
    parent: str | None = None,
    stage: str = "mte",
    flatten: bool = True,
    write_lyp: bool = True,
) -> list[ExportResult]:
    """
    Export one GDS per resonator: frame + MTE route/extension (+ optional MBE).

    Pass ``mbe_extensions`` from step 6.1 and ``mbe_bodies`` from steps 6.2/6.3
    to write MTE (5/0) and MBE (2/0) into the same file under ``output_dir``.

    For the complete pipeline output (steps 4ΓÇô6.3), prefer
    :func:`export_full_rteg_gds` which validates all indices and uses the
    one GDS filename per resonator (no stage suffix).
    """
    mbe_map = mbe_extensions or {}
    body_map = mbe_bodies or {}
    assemblies: list[MteRtegAssembly] = []
    for asm in frame_assemblies:
        if asm.index not in extensions:
            continue
        mte = extensions[asm.index]
        mbe = mbe_map.get(asm.index)
        body = body_map.get(asm.index)
        has_mte = mte.n_extensions > 0 or mte.routed_net is not None
        has_mbe = mbe is not None and mbe.n_extensions > 0
        has_body = body is not None and body.n_pieces > 0
        if not has_mte and not has_mbe and not has_body:
            continue
        assemblies.append(
            MteRtegAssembly(
                frame=asm,
                extension=mte,
                layermap=layermap,
                mbe_extension=mbe if has_mbe else None,
                mbe_body=body if has_body else None,
            )
        )
    return export_gds(
        assemblies,
        output_dir,
        layermap=layermap,
        parent=parent,
        stage=stage,
        flatten=flatten,
        write_lyp=write_lyp,
    )


def export_full_rteg_gds(
    frame_assemblies: Sequence[RtegFrameAssembly],
    extensions: Mapping[int, MteExtensionResult],
    output_dir: str | Path,
    *,
    layermap: LayerMap,
    mbe_extensions: Mapping[int, object],
    mbe_bodies: Mapping[int, object],
    parent: str | None = None,
    flatten: bool = True,
    write_lyp: bool = True,
) -> list[ExportResult]:
    """
    Export the complete routed RTEG (steps 4ΓÇô6.3) ΓÇö one GDS per resonator.

    Each file includes the die frame, PPD, resonator placement (including any
    step-4 resonator-only shift), preserved filter MTE and pad routes (5.3–5.4),
    MBE signal routes where applicable (6.1), and carved MBE ground filler
    (6.2 for ``collar_extend``, 6.3 for ``center_pad``).

    ``mbe_bodies`` must be the merged dict from steps 6.2 and 6.3, e.g.
    ``merge_mbe_bodies(collar_extend_body, center_pad_body)``.
    """
    expected = {asm.index for asm in frame_assemblies}
    missing_mte = expected - set(extensions)
    if missing_mte:
        raise ValueError(
            "Full RTEG export requires MTE extensions for every framed resonator; "
            f"missing indices: {sorted(missing_mte)}"
        )

    results = export_mte_extensions_gds(
        frame_assemblies,
        extensions,
        output_dir,
        layermap=layermap,
        mbe_extensions=mbe_extensions,
        mbe_bodies=mbe_bodies,
        parent=parent,
        stage="",
        flatten=flatten,
        write_lyp=write_lyp,
    )
    exported = {r.index for r in results}
    if exported != expected:
        missing = sorted(expected - exported)
        warnings.warn(
            "Full RTEG export did not write GDS for indices "
            f"{missing}. Confirm steps 5.3ΓÇô6.3 ran and routing applied.",
            stacklevel=2,
        )
    return results


__all__ = [
    "CollarExtensionDraw",
    "LipIntercept",
    "MteBuildConfig",
    "MteExtensionResult",
    "MteRtegAssembly",
    "build_mte_extensions",
    "build_preserved_extension_draw",
    "draw_collar_extension",
    "draw_lip_extension",
    "export_full_rteg_gds",
    "export_mte_extensions_gds",
    "extension_is_connected",
    "find_outward_lip_ab",
    "mte_extensions_overview_rows",
    "mte_intercept_breakdown_rows",
    "select_extension_collar",
    "select_extension_collar_from_pieces",
]
