"""
Step 6.1 — MBE pad-to-collar connection.

Applies only when MTE does **not** face the center pad (``collar_extend`` /
``mte_faces_center == false``). Resonators routed by step 5.4 (``center_pad``)
are skipped — MTE already carries signal to the pad.

Mirrors the 5.3/5.4 MTE intercept pattern on MBE:
  5.3  ``find_outward_lip_ab`` → SKILL slope intercepts on MTE collar
  5.4  pad TR/BR → intercept_a / intercept_b
  6.1  same intercept logic on the MBE collar → stretch MBE to those intercepts
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import gdstk

from layermap import LayerMap
from rteg_classify import NodeClassification
from rteg_collect import (
    PreservedMetal,
    RtegGeometryRoles,
    TaggedPolygon,
    preserved_mbe_overlap_with_body,
)
from rteg_mte_extensions import (
    MteBuildConfig,
    find_outward_lip_ab,
    select_extension_collar_from_pieces,
)
from rteg_mte_route import _union_pad_bbox
from rteg_utils import assign_layer

Point = tuple[float, float]

MBE_LAYER_NAME = "BAW_MBE"
PDK6_MBE_GDS_PAIR = (2, 0)


def tag_baw_mbe(poly: gdstk.Polygon, layermap: LayerMap) -> gdstk.Polygon:
    """Re-tag geometry onto ``BAW_MBE`` (layermap 2/0)."""
    pair = layermap.pair(MBE_LAYER_NAME)
    if pair != PDK6_MBE_GDS_PAIR:
        import warnings

        warnings.warn(
            f"{MBE_LAYER_NAME} maps to GDS {pair}, expected PDK6 {PDK6_MBE_GDS_PAIR}",
            stacklevel=2,
        )
    return assign_layer(poly, layermap, MBE_LAYER_NAME)


@dataclass(frozen=True)
class MbeConnectionConfig:
    """Tunable parameters for step 6.1 MBE pad-to-collar connection."""

    mbe_layer: str = "BAW_MBE"
    boolean_precision: float = 1e-3
    boundary_tolerance_um: float = 0.15
    pad_touch_overlap_um: float = 0.5
    junction_merge_inset_um: float = 0.5
    min_collar_overlap_um2: float = 1.0
    skill_pad_expand_um: float = 5.0


@dataclass(frozen=True)
class MbeConnectionDraw:
    """Pad-to-collar connection geometry for one resonator."""

    point_a: Point
    point_b: Point
    hit_a: Point
    hit_b: Point


@dataclass
class MbeExtensionResult:
    collar: TaggedPolygon | None
    extension: gdstk.Polygon | None
    routed_net: gdstk.Polygon | None
    preserved_collar_polygons: list[gdstk.Polygon]
    n_extensions: int
    connection_draw: MbeConnectionDraw | None = None
    drc_violations: list[str] = field(default_factory=list)


def mbe_extension_applies(classification: NodeClassification) -> bool:
    """Step 6.1 applies only when step 5.4 does not route MTE to the pad."""
    return classification.mte_route_target == "collar_extend"


def _fmt_point(p: Point | None) -> str | None:
    if p is None:
        return None
    return f"({p[0]:.2f}, {p[1]:.2f})"


def _pad_corners_tr_br(signal_polys: Sequence[gdstk.Polygon]) -> tuple[Point, Point]:
    """Top-right and bottom-right corners of the center signal pad bbox."""
    bbox = _union_pad_bbox(signal_polys)
    if bbox is None:
        raise ValueError("center signal pad has no geometry")
    (x0, y0), (x1, y1) = bbox
    _ = x0, y0
    return (x1, y1), (x1, y0)


def _collar_vertices(collar: gdstk.Polygon) -> list[Point]:
    return [(float(p[0]), float(p[1])) for p in collar.points]


def _locate_on_collar_boundary(point: Point, verts: Sequence[Point]) -> tuple[int, float]:
    """Return ``(edge_index, t)`` for the closest point on the collar ring."""
    best_dist = float("inf")
    best_edge = 0
    best_t = 0.0
    n = len(verts)
    for i in range(n):
        a = verts[i]
        b = verts[(i + 1) % n]
        dx, dy = b[0] - a[0], b[1] - a[1]
        length_sq = dx * dx + dy * dy
        if length_sq < 1e-12:
            t = 0.0
            proj = a
        else:
            t = max(0.0, min(1.0, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length_sq))
            proj = (a[0] + t * dx, a[1] + t * dy)
        dist = math.hypot(point[0] - proj[0], point[1] - proj[1])
        if dist < best_dist:
            best_dist = dist
            best_edge = i
            best_t = t
    return best_edge, best_t


def _interp_collar_edge(verts: Sequence[Point], edge: int, t: float) -> Point:
    a = verts[edge]
    b = verts[(edge + 1) % len(verts)]
    return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))


def _ring_cum_lengths(verts: Sequence[Point]) -> tuple[list[float], list[float], float]:
    n = len(verts)
    edge_lens = [_edge_length(verts[i], verts[(i + 1) % n]) for i in range(n)]
    cum = [0.0]
    for length in edge_lens:
        cum.append(cum[-1] + length)
    return edge_lens, cum, cum[-1]


def _forward_ring_distance(s0: float, s1: float, perimeter: float) -> float:
    return s1 - s0 if s1 >= s0 else perimeter - s0 + s1


def _walk_collar_boundary(
    verts: Sequence[Point],
    edge_a: int,
    t_a: float,
    edge_b: int,
    t_b: float,
    forward: bool,
) -> list[Point]:
    """Walk the collar ring from one boundary point to another."""
    n = len(verts)
    edge_lens, cum, perimeter = _ring_cum_lengths(verts)
    s0 = cum[edge_a] + t_a * edge_lens[edge_a]
    s1 = cum[edge_b] + t_b * edge_lens[edge_b]
    start = _interp_collar_edge(verts, edge_a, t_a)
    end = _interp_collar_edge(verts, edge_b, t_b)
    inner: list[Point] = []
    s = s0
    for _ in range(n + 2):
        remaining = (
            _forward_ring_distance(s, s1, perimeter)
            if forward
            else _forward_ring_distance(s1, s, perimeter)
        )
        if remaining <= 1e-6:
            break
        next_vertex: int | None = None
        next_dist = remaining
        for j in range(n):
            vertex_s = cum[j]
            if forward:
                dist = _forward_ring_distance(s, vertex_s, perimeter)
            else:
                dist = _forward_ring_distance(vertex_s, s, perimeter)
            if dist > 1e-9 and dist < next_dist - 1e-9:
                next_dist = dist
                next_vertex = j
        if next_vertex is None:
            break
        inner.append(verts[next_vertex])
        s = cum[next_vertex]
    return [start, *inner, end]


def _max_chord_distance(path: Sequence[Point], hit_a: Point, hit_b: Point) -> float:
    xa, ya = hit_a
    xb, yb = hit_b
    dx, dy = xb - xa, yb - ya
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-12:
        return 0.0
    max_dist = 0.0
    for px, py in path[1:-1]:
        t = max(0.0, min(1.0, ((px - xa) * dx + (py - ya) * dy) / length_sq))
        proj_x = xa + t * dx
        proj_y = ya + t * dy
        max_dist = max(max_dist, math.hypot(px - proj_x, py - proj_y))
    return max_dist


def _path_arc_length(pts: Sequence[Point]) -> float:
    return sum(
        _edge_length(pts[i], pts[i + 1]) for i in range(len(pts) - 1)
    )


def _collar_mouth_edge_path(
    collar: gdstk.Polygon,
    hit_a: Point,
    hit_b: Point,
) -> list[Point]:
    """
    Collar-boundary path between the top and bottom hits.

    Locates each hit on its actual collar edge, walks both ring directions,
    and picks the arc that stays closest to the direct chord so the mouth
    follows the inner fillet instead of cutting through the resonator body
    or detouring around the outer collar rim.
    """
    verts = _collar_vertices(collar)
    if len(verts) < 2:
        return [hit_a, hit_b]

    edge_a, t_a = _locate_on_collar_boundary(hit_a, verts)
    edge_b, t_b = _locate_on_collar_boundary(hit_b, verts)
    path_fwd = _walk_collar_boundary(verts, edge_a, t_a, edge_b, t_b, True)
    path_bwd = _walk_collar_boundary(verts, edge_a, t_a, edge_b, t_b, False)

    chord_fwd = _max_chord_distance(path_fwd, hit_a, hit_b)
    chord_bwd = _max_chord_distance(path_bwd, hit_a, hit_b)
    if chord_fwd < chord_bwd - 1e-6:
        ring = path_fwd
    elif chord_bwd < chord_fwd - 1e-6:
        ring = path_bwd
    elif _path_arc_length(path_fwd) < _path_arc_length(path_bwd):
        ring = path_fwd
    else:
        ring = path_bwd

    inner = ring[1:-1]
    return [hit_a, *inner, hit_b]


def _connection_points(
    point_a: Point,
    point_b: Point,
    hit_a: Point,
    hit_b: Point,
    collar: gdstk.Polygon,
) -> list[Point]:
    mouth = _collar_mouth_edge_path(collar, hit_a, hit_b)
    return [point_b, point_a, *mouth]


def _edge_length(p0: Point, p1: Point) -> float:
    return math.hypot(p1[0] - p0[0], p1[1] - p0[1])


def _find_mbe_collar_intercepts(
    collar: gdstk.Polygon,
    body_mbe_polys: Sequence[gdstk.Polygon],
    signal_polys: Sequence[gdstk.Polygon],
    cfg: MbeConnectionConfig,
) -> tuple[Point, Point]:
    """
    SKILL slope intercepts on the MBE collar mouth (mirrors 5.3 MTE intercept logic).

    Calls ``find_outward_lip_ab`` with the MBE collar and resonator body MBE
    polygons — same ``rdsBawFindMinMaxSlope2`` algorithm used for MTE in step 5.3.
    Returns ``(hit_a, hit_b)`` with higher-Y point first.
    """
    mte_cfg = MteBuildConfig(
        skill_pad_expand_um=cfg.skill_pad_expand_um,
        boolean_precision=cfg.boolean_precision,
    )
    lip = find_outward_lip_ab(
        collar,
        body_mbe_polys,
        mte_cfg,
        signal_polys=signal_polys,
    )
    return lip.point_a, lip.point_b


def _select_collar_by_pad_proximity(
    pieces: Sequence[TaggedPolygon],
    body_mbe_polys: Sequence[gdstk.Polygon],
    signal_polys: Sequence[gdstk.Polygon],
    cfg: MbeConnectionConfig,
) -> TaggedPolygon | None:
    """Prefer the body-touching MBE piece whose Y span best aligns with the pad."""
    overlapping = [
        tp
        for tp in pieces
        if preserved_mbe_overlap_with_body(
            tp.polygon,
            body_mbe_polys,
            precision=cfg.boolean_precision,
        )
        >= cfg.min_collar_overlap_um2
    ]
    if not overlapping:
        return None

    pad_bbox = _union_pad_bbox(signal_polys)
    if pad_bbox is None:
        return min(overlapping, key=lambda tp: abs(tp.polygon.area()))

    (px0, py0), (px1, py1) = pad_bbox
    scored: list[tuple[tuple[float, float, float], TaggedPolygon]] = []
    for tp in overlapping:
        bb = tp.polygon.bounding_box()
        y_overlap = max(0.0, min(bb[1][1], py1) - max(bb[0][1], py0))
        if px1 <= bb[0][0]:
            x_sep = bb[0][0] - px1
        elif px0 >= bb[1][0]:
            x_sep = px0 - bb[1][0]
        else:
            x_sep = 0.0
        area = abs(tp.polygon.area())
        scored.append(((-y_overlap, x_sep, area), tp))

    scored.sort(key=lambda item: item[0])
    best_score, best_tp = scored[0]
    if len(scored) > 1:
        second_score, second_tp = scored[1]
        if abs(best_score[0] - second_score[0]) < 2.0 and second_score[2] < best_score[2]:
            return second_tp
    return best_tp


def select_extension_collar_mbe(
    preserved: PreservedMetal,
    body_mbe_polys: Sequence[gdstk.Polygon],
    cfg: MbeConnectionConfig | None = None,
    *,
    signal_polys: Sequence[gdstk.Polygon] | None = None,
) -> TaggedPolygon | None:
    """Pick the extension collar on preserved ``BAW_MBE``."""
    c = cfg or MbeConnectionConfig()
    if signal_polys:
        picked = _select_collar_by_pad_proximity(
            preserved.mbe,
            body_mbe_polys,
            signal_polys,
            c,
        )
        if picked is not None:
            return picked
    return select_extension_collar_from_pieces(
        preserved.mbe,
        body_mbe_polys,
        preserved_mbe_overlap_with_body,
        c,
    )


def _empty_mbe_result(preserved: PreservedMetal) -> MbeExtensionResult:
    return MbeExtensionResult(
        collar=None,
        extension=None,
        routed_net=None,
        preserved_collar_polygons=[tp.polygon for tp in preserved.mbe],
        n_extensions=0,
        connection_draw=None,
    )


def draw_mbe_pad_connection(
    collar_tp: TaggedPolygon,
    body_mbe_polys: Sequence[gdstk.Polygon],
    signal_polys: Sequence[gdstk.Polygon],
    layermap: LayerMap,
    cfg: MbeConnectionConfig | None = None,
) -> tuple[gdstk.Polygon, MbeConnectionDraw]:
    """
    Build a pad-to-collar MBE connector using SKILL slope intercepts.

    Mirrors the 5.3/5.4 MTE pattern: ``find_outward_lip_ab`` locates the
    intercept points on the MBE collar mouth, then the polygon connects
    the signal pad TR/BR corners to those intercepts, tracing the collar
    boundary between them.
    """
    c = cfg or MbeConnectionConfig()
    layer, datatype = layermap.pair(c.mbe_layer)
    collar = collar_tp.polygon

    point_a, point_b = _pad_corners_tr_br(signal_polys)
    hit_a, hit_b = _find_mbe_collar_intercepts(collar, body_mbe_polys, signal_polys, c)

    connection = gdstk.Polygon(
        _connection_points(point_a, point_b, hit_a, hit_b, collar),
        layer=layer,
        datatype=datatype,
    )
    draw = MbeConnectionDraw(
        point_a=point_a,
        point_b=point_b,
        hit_a=hit_a,
        hit_b=hit_b,
    )
    return tag_baw_mbe(connection, layermap), draw


def _extension_for_roles(
    roles: RtegGeometryRoles,
    classification: NodeClassification,
    layermap: LayerMap,
    cfg: MbeConnectionConfig,
) -> MbeExtensionResult:
    preserved = roles.preserved
    signal_polys = [tp.polygon for tp in classification.center_pad_polygons()]
    if not signal_polys:
        return MbeExtensionResult(
            collar=None,
            extension=None,
            routed_net=None,
            preserved_collar_polygons=[tp.polygon for tp in preserved.mbe],
            n_extensions=0,
            connection_draw=None,
            drc_violations=["no center signal pad geometry"],
        )

    collar_tp = select_extension_collar_mbe(
        preserved,
        roles.resonator_body_mbe,
        cfg,
        signal_polys=signal_polys,
    )
    if collar_tp is None:
        return _empty_mbe_result(preserved)

    try:
        connection, draw = draw_mbe_pad_connection(
            collar_tp, roles.resonator_body_mbe, signal_polys, layermap, cfg
        )
    except ValueError as exc:
        return MbeExtensionResult(
            collar=collar_tp,
            extension=None,
            routed_net=None,
            preserved_collar_polygons=[tp.polygon for tp in preserved.mbe],
            n_extensions=0,
            connection_draw=None,
            drc_violations=[str(exc)],
        )

    return MbeExtensionResult(
        collar=collar_tp,
        extension=connection,
        routed_net=connection,
        preserved_collar_polygons=[tp.polygon for tp in preserved.mbe],
        n_extensions=1,
        connection_draw=draw,
    )


def build_mbe_extensions(
    roles_by_index: Mapping[int, RtegGeometryRoles],
    classifications: Mapping[int, NodeClassification],
    layermap: LayerMap,
    config: MbeConnectionConfig | None = None,
) -> dict[int, MbeExtensionResult]:
    """Run step 6.1 for every resonator index in ``roles_by_index``."""
    cfg = config or MbeConnectionConfig()
    out: dict[int, MbeExtensionResult] = {}
    for idx, roles in roles_by_index.items():
        classification = classifications[idx]
        if not mbe_extension_applies(classification):
            out[idx] = _empty_mbe_result(roles.preserved)
            continue
        if not roles.preserved.mbe:
            out[idx] = _empty_mbe_result(roles.preserved)
            continue
        out[idx] = _extension_for_roles(roles, classification, layermap, cfg)
    return out


def mbe_extensions_overview_rows(
    extensions: Mapping[int, MbeExtensionResult],
    *,
    inst_names: Mapping[int, str] | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx in sorted(extensions):
        result = extensions[idx]
        draw = result.connection_draw
        area = abs(result.extension.area()) if result.extension is not None else 0.0
        rows.append(
            {
                "index": idx,
                "inst_name": inst_names.get(idx) if inst_names else None,
                "n_preserved_mbe": len(result.preserved_collar_polygons),
                "n_extensions": result.n_extensions,
                "point_a": _fmt_point(draw.point_a) if draw else None,
                "point_b": _fmt_point(draw.point_b) if draw else None,
                "hit_a": _fmt_point(draw.hit_a) if draw else None,
                "hit_b": _fmt_point(draw.hit_b) if draw else None,
                "area_um2": round(area, 2),
                "drc_violations": "; ".join(result.drc_violations) or None,
            }
        )
    return rows


__all__ = [
    "MBE_LAYER_NAME",
    "MbeConnectionConfig",
    "MbeConnectionDraw",
    "MbeExtensionResult",
    "PDK6_MBE_GDS_PAIR",
    "build_mbe_extensions",
    "draw_mbe_pad_connection",
    "mbe_extension_applies",
    "mbe_extensions_overview_rows",
    "select_extension_collar_mbe",
    "tag_baw_mbe",
]
