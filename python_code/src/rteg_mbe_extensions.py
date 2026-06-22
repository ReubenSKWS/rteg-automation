"""
Step 6.1 ΓÇö MBE pad-to-collar connection for ``collar_extend`` resonators.

Four-sided connector: pad right edge on the left, straight lines from the top
and bottom pad corners to collar bends on the pad-facing side, and a straight
line between those two collar points on the right.
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
from rteg_mte_extensions import select_extension_collar_from_pieces
from rteg_mte_route import _union_pad_bbox
from rteg_utils import assign_layer

Point = tuple[float, float]

MBE_LAYER_NAME = "BAW_MBE"
PDK6_MBE_GDS_PAIR = (2, 0)
_PAD_FACING_X_MARGIN_UM = 30.0


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
    min_collar_overlap_um2: float = 1.0
    stadium_collar_area_um2: float = 2500.0
    max_edge_collar_area_um2: float = 800.0
    collar_association_gap_um: float = 35.0
    mouth_y_margin_um: float = 30.0
    horiz_angle_tol_deg: float = 8.0
    cluster_short_edge_um: float = 3.5
    cluster_long_edge_um: float = 8.0
    cluster_min_points: int = 4
    cluster_y_sweep_step_um: float = 0.25


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
    """Step 6.1 applies when preserved MTE does not face center."""
    return not classification.collar_orientation.mte_faces_center


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


def _collar_centroid(collar: gdstk.Polygon) -> Point:
    verts = _collar_vertices(collar)
    if not verts:
        return (0.0, 0.0)
    return (
        sum(v[0] for v in verts) / len(verts),
        sum(v[1] for v in verts) / len(verts),
    )


def _pad_on_left(collar: gdstk.Polygon, pad_ref: Point) -> bool:
    cx, _ = _collar_centroid(collar)
    return pad_ref[0] <= cx


def _pad_facing_vertices(collar: gdstk.Polygon, pad_ref: Point) -> list[Point]:
    """Collar vertices on the side that faces the signal pad."""
    verts = _collar_vertices(collar)
    cx, _ = _collar_centroid(collar)
    margin = _PAD_FACING_X_MARGIN_UM
    if pad_ref[0] <= cx:
        return [v for v in verts if v[0] <= cx + margin]
    return [v for v in verts if v[0] >= cx - margin]


def _ray_segment_hit_t(
    origin: Point,
    direction: Point,
    p0: Point,
    p1: Point,
) -> float | None:
    ox, oy = origin
    dx, dy = direction
    sx, sy = p1[0] - p0[0], p1[1] - p0[1]
    denom = dx * sy - dy * sx
    if abs(denom) < 1e-12:
        return None
    qx, qy = p0[0] - ox, p0[1] - oy
    t = (qx * sy - qy * sx) / denom
    s = (qx * dy - qy * dx) / denom
    if t >= 1e-6 and -1e-6 <= s <= 1.0 + 1e-6:
        return t
    return None


def _raycast_collar_hits(
    collar: gdstk.Polygon,
    origin: Point,
    target: Point,
    pad_ref: Point,
) -> list[tuple[float, Point]]:
    """Ray intersections with the collar boundary, sorted by distance from *origin*."""
    dx, dy = target[0] - origin[0], target[1] - origin[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return []
    direction = (dx / length, dy / length)
    pad_on_left = _pad_on_left(collar, pad_ref)
    cx, _ = _collar_centroid(collar)
    margin = _PAD_FACING_X_MARGIN_UM
    verts = _collar_vertices(collar)
    n = len(verts)
    hits: list[tuple[float, Point]] = []
    for i in range(n):
        p0, p1 = verts[i], verts[(i + 1) % n]
        t = _ray_segment_hit_t(origin, direction, p0, p1)
        if t is None:
            continue
        hit = (
            origin[0] + direction[0] * t,
            origin[1] + direction[1] * t,
        )
        if pad_on_left and hit[0] > cx + margin:
            continue
        if not pad_on_left and hit[0] < cx - margin:
            continue
        hits.append((t, hit))
    hits.sort(key=lambda item: item[0])
    return hits


def _snap_to_collar_vertex(point: Point, collar: gdstk.Polygon, tol: float = 0.01) -> Point:
    for v in _collar_vertices(collar):
        if abs(v[0] - point[0]) <= tol and abs(v[1] - point[1]) <= tol:
            return v
    return point


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


def _edge_angle_deg(p0: Point, p1: Point) -> float:
    return math.degrees(math.atan2(p1[1] - p0[1], p1[0] - p0[0]))


def _edge_length(p0: Point, p1: Point) -> float:
    return math.hypot(p1[0] - p0[0], p1[1] - p0[1])


def _vertex_turn_deg(verts: Sequence[Point], index: int) -> float:
    n = len(verts)
    p0 = verts[(index - 1) % n]
    p1 = verts[index]
    p2 = verts[(index + 1) % n]
    a1 = _edge_angle_deg(p0, p1)
    a2 = _edge_angle_deg(p1, p2)
    return abs((a2 - a1 + 180.0) % 360.0 - 180.0)


def _collar_bend_clusters(
    verts: Sequence[Point],
    cfg: MbeConnectionConfig,
) -> list[list[Point]]:
    """Group fillet vertices into bend clusters (short-edge chains)."""
    n = len(verts)
    if n < cfg.cluster_min_points:
        return []

    clusters: list[list[Point]] = []
    i = 0
    while i < n:
        cluster = [verts[i]]
        i += 1
        while i < n:
            edge_len = _edge_length(verts[i - 1], verts[i])
            if edge_len > cfg.cluster_long_edge_um and len(cluster) >= cfg.cluster_min_points:
                break
            is_short = edge_len <= cfg.cluster_short_edge_um
            is_turn = _vertex_turn_deg(verts, i) >= cfg.horiz_angle_tol_deg
            if not is_short and not is_turn and len(cluster) >= cfg.cluster_min_points:
                break
            cluster.append(verts[i])
            i += 1
            if len(cluster) > 80:
                break
        if len(cluster) >= cfg.cluster_min_points:
            clusters.append(cluster)
    return clusters


def _cluster_mouth_corner(cluster: Sequence[Point], pad_on_left: bool) -> Point:
    if pad_on_left:
        return max(cluster, key=lambda v: (v[0], v[1]))
    return min(cluster, key=lambda v: (v[0], -v[1]))


def _horizontal_collar_hits(
    collar: gdstk.Polygon,
    pad_x: float,
    y: float,
    pad_ref: Point,
) -> list[Point]:
    """Horizontal ray from the pad side through the collar at fixed *y*."""
    bbox = collar.bounding_box()
    if bbox is None:
        return []
    far_x = bbox[1][0] + 50.0 if _pad_on_left(collar, pad_ref) else bbox[0][0] - 50.0
    return [hit for _, hit in _raycast_collar_hits(collar, (pad_x, y), (far_x, y), pad_ref)]


def _stretch_hit_to_cluster(
    collar: gdstk.Polygon,
    pad_corner: Point,
    cluster: Sequence[Point],
    pad_ref: Point,
    cfg: MbeConnectionConfig,
) -> Point:
    """Farthest pad-side collar hit across the cluster Y band."""
    pad_on_left = _pad_on_left(collar, pad_ref)
    corner = _cluster_mouth_corner(cluster, pad_on_left)
    y_lo = min(v[1] for v in cluster)
    y_hi = max(v[1] for v in cluster)
    y_start = min(pad_corner[1], y_lo) if pad_corner[1] <= y_hi else y_lo
    y_end = max(pad_corner[1], y_hi)

    best = corner
    best_score = corner[0] if pad_on_left else -corner[0]
    y = y_start
    while y <= y_end + 1e-6:
        for hit in _horizontal_collar_hits(collar, pad_corner[0], y, pad_ref):
            score = hit[0] if pad_on_left else -hit[0]
            if score > best_score + 1e-6:
                best = hit
                best_score = score
        y += cfg.cluster_y_sweep_step_um
    return _snap_to_collar_vertex(best, collar)


def _pick_bend_cluster(
    clusters: Sequence[Sequence[Point]],
    pad_corner_y: float,
    is_upper: bool,
    mid_y: float,
    pad_on_left: bool,
) -> list[Point] | None:
    in_half = [
        c
        for c in clusters
        if (sum(v[1] for v in c) / len(c) >= mid_y) == is_upper
    ]
    if not in_half:
        return None

    def mouth_x(c: Sequence[Point]) -> float:
        corner = _cluster_mouth_corner(c, pad_on_left)
        return corner[0] if pad_on_left else -corner[0]

    def centroid_y(c: Sequence[Point]) -> float:
        return sum(v[1] for v in c) / len(c)

    if is_upper:
        return max(
            in_half,
            key=lambda c: (mouth_x(c), -abs(centroid_y(c) - pad_corner_y), len(c)),
        )
    return min(
        in_half,
        key=lambda c: (abs(centroid_y(c) - pad_corner_y), -mouth_x(c), -len(c)),
    )


def _collar_mouth_bends(
    collar: gdstk.Polygon,
    pad_ref: Point,
    pad_top: Point,
    pad_bot: Point,
    cfg: MbeConnectionConfig,
) -> tuple[Point | None, Point | None]:
    """Detect pad-facing fillet bends and stretch hits to the inner mouth corner."""
    pad_on_left = _pad_on_left(collar, pad_ref)
    facing = set(_pad_facing_vertices(collar, pad_ref))
    verts = _collar_vertices(collar)
    if not verts:
        return None, None

    mid_y = (pad_top[1] + pad_bot[1]) / 2.0
    y_min = pad_bot[1] - cfg.mouth_y_margin_um
    y_max = pad_top[1] + cfg.mouth_y_margin_um

    mouth_clusters: list[list[Point]] = []
    for cluster in _collar_bend_clusters(verts, cfg):
        if not any(v in facing for v in cluster):
            continue
        cy = sum(v[1] for v in cluster) / len(cluster)
        if y_min <= cy <= y_max:
            mouth_clusters.append(list(cluster))

    top_cluster = _pick_bend_cluster(mouth_clusters, pad_top[1], True, mid_y, pad_on_left)
    bot_cluster = _pick_bend_cluster(mouth_clusters, pad_bot[1], False, mid_y, pad_on_left)

    bend_top = (
        _stretch_hit_to_cluster(collar, pad_top, top_cluster, pad_ref, cfg)
        if top_cluster
        else None
    )
    bend_bottom = (
        _stretch_hit_to_cluster(collar, pad_bot, bot_cluster, pad_ref, cfg)
        if bot_cluster
        else None
    )
    return bend_top, bend_bottom


def _fallback_collar_hit(
    collar: gdstk.Polygon,
    pad_corner: Point,
    pad_ref: Point,
) -> Point:
    """Ray hit when no fillet cluster is found near the pad corner."""
    facing = _pad_facing_vertices(collar, pad_ref)
    is_upper = pad_corner[1] >= pad_ref[1]
    mouth = [v for v in facing if v[0] > pad_corner[0] + _PAD_FACING_X_MARGIN_UM]
    if not mouth:
        return _collar_centroid(collar)

    if is_upper:
        aim = max(
            mouth,
            key=lambda v: (
                v[1],
                -math.hypot(v[0] - pad_corner[0], v[1] - pad_corner[1]),
            ),
        )
    else:
        aim = min(
            mouth,
            key=lambda v: (
                v[1],
                math.hypot(v[0] - pad_corner[0], v[1] - pad_corner[1]),
            ),
        )

    dx, dy = aim[0] - pad_corner[0], aim[1] - pad_corner[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return _snap_to_collar_vertex(aim, collar)

    direction = (dx / length, dy / length)
    far = (pad_corner[0] + direction[0] * 1e4, pad_corner[1] + direction[1] * 1e4)
    hits = _raycast_collar_hits(collar, pad_corner, far, pad_ref)
    verts_on_ray = [
        (t, v)
        for v in _collar_vertices(collar)
        if (t := _ray_vertex_t(pad_corner, direction, v)) is not None
    ]

    bbox = collar.bounding_box()
    horizontal_far = (bbox[1][0] + 50.0, pad_corner[1]) if bbox else far
    hits_h = _raycast_collar_hits(collar, pad_corner, horizontal_far, pad_ref)

    if is_upper:
        if hits_h:
            use_h = True
            if hits and len(verts_on_ray) >= 2:
                if max(t for t, _ in verts_on_ray) - hits[0][0] > 25.0:
                    use_h = False
            hit = (
                hits_h[0][1]
                if use_h
                else max(verts_on_ray, key=lambda item: item[0])[1]
            )
        elif hits:
            hit = hits[0][1]
        else:
            hit = aim
    elif hits_h:
        hit = hits_h[0][1]
    elif hits:
        hit = hits[0][1]
    else:
        hit = aim

    return _snap_to_collar_vertex(hit, collar)


def _ray_vertex_t(
    origin: Point,
    direction: Point,
    point: Point,
    tol: float = 0.5,
) -> float | None:
    vx, vy = point[0] - origin[0], point[1] - origin[1]
    if abs(vx * direction[1] - vy * direction[0]) > tol:
        return None
    t = vx * direction[0] + vy * direction[1]
    return t if t > 1e-6 else None


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
    signal_polys: Sequence[gdstk.Polygon],
    layermap: LayerMap,
    cfg: MbeConnectionConfig | None = None,
) -> tuple[gdstk.Polygon, MbeConnectionDraw]:
    """Build a pad-to-collar connector tracing the collar mouth edge."""
    c = cfg or MbeConnectionConfig()
    layer, datatype = layermap.pair(c.mbe_layer)
    collar = collar_tp.polygon

    point_a, point_b = _pad_corners_tr_br(signal_polys)
    pad_ref = ((point_a[0] + point_b[0]) / 2.0, (point_a[1] + point_b[1]) / 2.0)
    bend_top, bend_bottom = _collar_mouth_bends(collar, pad_ref, point_a, point_b, c)
    hit_a = bend_top or _fallback_collar_hit(collar, point_a, pad_ref)
    hit_b = bend_bottom or _fallback_collar_hit(collar, point_b, pad_ref)

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
    collar_tp = select_extension_collar_mbe(
        preserved,
        roles.resonator_body_mbe,
        cfg,
        signal_polys=signal_polys or None,
    )
    if collar_tp is None:
        return _empty_mbe_result(preserved)
    if not signal_polys:
        return MbeExtensionResult(
            collar=collar_tp,
            extension=None,
            routed_net=None,
            preserved_collar_polygons=[tp.polygon for tp in preserved.mbe],
            n_extensions=0,
            connection_draw=None,
            drc_violations=["no center signal pad geometry"],
        )

    connection, draw = draw_mbe_pad_connection(collar_tp, signal_polys, layermap, cfg)

    return MbeExtensionResult(
        collar=collar_tp,
        extension=connection,
        routed_net=connection,
        preserved_collar_polygons=[tp.polygon for tp in preserved.mbe],
        n_extensions=1,
        connection_draw=draw,
    )


def build_mbe_extension(
    roles: RtegGeometryRoles,
    classification: NodeClassification,
    layermap: LayerMap,
    config: MbeConnectionConfig | None = None,
) -> MbeExtensionResult:
    """Run step 6.1 for a single resonator."""
    cfg = config or MbeConnectionConfig()
    if not mbe_extension_applies(classification):
        return _empty_mbe_result(roles.preserved)
    if not roles.preserved.mbe:
        return _empty_mbe_result(roles.preserved)
    return _extension_for_roles(roles, classification, layermap, cfg)


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
    "build_mbe_extension",
    "build_mbe_extensions",
    "draw_mbe_pad_connection",
    "mbe_extension_applies",
    "mbe_extensions_overview_rows",
    "select_extension_collar_mbe",
    "tag_baw_mbe",
]
