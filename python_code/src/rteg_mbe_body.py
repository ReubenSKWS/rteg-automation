"""
Step 6.2 — MBE ground body for ``collar_extend`` resonators.

MBE cap on 5.3 MTE extension + carved filler bridge. Step 6.3 lives in
``rteg_mbe_body_center_pad.py``.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import gdstk

from layermap import LayerMap
from prep_resonator_ppd import _grown_keepout_polys
from rteg_classify import NodeClassification
from rteg_collect import RtegGeometryRoles
from rteg_mbe_body_common import (
    MbeBodyResult,
    base_filler_polygon,
    carve_filler,
    empty_mbe_body_result,
    merge_filler_with_bridge,
    mte_route_obstacle_polys,
    offset_polys,
)
from rteg_mbe_body_center_pad import (
    MbeBodyCenterPadConfig,
    build_mbe_body_center_pad,
    mbe_body_center_pad_applies,
)
from rteg_mbe_extensions import MbeConnectionConfig, MbeExtensionResult, tag_baw_mbe
from rteg_mte_extensions import CollarExtensionDraw, MteExtensionResult

Point = tuple[float, float]


@dataclass(frozen=True)
class MbeBodyConfig:
    """Tunable parameters for step 6.2 MBE ground body."""

    mbe_layer: str = "BAW_MBE"
    mbe_mte_min_spacing_um: float = 14.0
    stadium_clearance_factor: float = 2.0
    release_hole_clearance_um: float = 6.0
    cap_shift_um: float = 3.5  # outward shift after halving (overlaps MTE + filler)
    bridge_step_back_um: float = 1.0  # ray origin inset from cap outer edge toward MTE
    bridge_cap_overlap_um: float = 0.8  # bridge start edge overlap into cap for connectivity
    curve_merge_max_gap_um: float = 25.0  # straight merge when carved curve is this close to cap
    boolean_precision: float = 1e-3
    filler_bbox_tol_um: float = 1.0


def _center_pad_config_from_body(cfg: MbeBodyConfig) -> MbeBodyCenterPadConfig:
    return MbeBodyCenterPadConfig(
        mbe_layer=cfg.mbe_layer,
        boolean_precision=cfg.boolean_precision,
        release_hole_clearance_um=cfg.release_hole_clearance_um,
    )


def mbe_body_collar_extend_applies(classification: NodeClassification) -> bool:
    """Step 6.2 applies when preserved MTE did not face the center signal pad."""
    return classification.mte_route_target == "collar_extend"


def mbe_body_applies(classification: NodeClassification) -> bool:
    """Steps 6.2 or 6.3 apply for collar_extend and center_pad resonators."""
    return classification.mte_route_target in ("collar_extend", "center_pad")


def _empty_mbe_body_result(*, violations: list[str] | None = None) -> MbeBodyResult:
    return empty_mbe_body_result(violations=violations)


def _normalize_vector(dx: float, dy: float) -> Point:
    length = math.hypot(dx, dy)
    if length < 1e-9:
        raise ValueError("degenerate direction vector")
    return (dx / length, dy / length)


def _outward_normal_from_draw(draw: CollarExtensionDraw) -> Point:
    """Outward normal from inner mouth edge toward the extension outer edge."""
    ia, ib = draw.intercept_a, draw.intercept_b
    (oa, ob) = draw.outer_edge
    inner_mid = ((ia[0] + ib[0]) / 2.0, (ia[1] + ib[1]) / 2.0)
    outer_mid = ((oa[0] + ob[0]) / 2.0, (oa[1] + ob[1]) / 2.0)
    return _normalize_vector(
        outer_mid[0] - inner_mid[0],
        outer_mid[1] - inner_mid[1],
    )


def _outward_normal_from_polygon(poly: gdstk.Polygon) -> Point:
    """Fallback when ``extension_draw`` is unavailable (quad extension layout)."""
    pts = [(float(p[0]), float(p[1])) for p in poly.points]
    if len(pts) < 4:
        raise ValueError("MTE extension polygon has fewer than 4 vertices")
    inner_mid = ((pts[0][0] + pts[1][0]) / 2.0, (pts[0][1] + pts[1][1]) / 2.0)
    outer_mid = ((pts[2][0] + pts[3][0]) / 2.0, (pts[2][1] + pts[3][1]) / 2.0)
    return _normalize_vector(
        outer_mid[0] - inner_mid[0],
        outer_mid[1] - inner_mid[1],
    )


def _extension_corners(
    mte_ext: gdstk.Polygon,
    extension_draw: CollarExtensionDraw | None,
) -> tuple[Point, Point, Point, Point]:
    """Return ``(inner_a, inner_b, outer_b, outer_a)`` from the MTE extension polygon."""
    pts = [(float(p[0]), float(p[1])) for p in mte_ext.points]
    if len(pts) >= 4:
        return pts[0], pts[1], pts[2], pts[3]
    if extension_draw is not None:
        return (
            extension_draw.intercept_a,
            extension_draw.intercept_b,
            extension_draw.outer_edge[0],
            extension_draw.outer_edge[1],
        )
    raise ValueError("MTE extension polygon has fewer than 4 vertices")


def _extension_outer_edge(
    mte_ext: gdstk.Polygon,
    extension_draw: CollarExtensionDraw | None,
) -> tuple[Point, Point, Point]:
    """Return ``(outer_a, outer_b, outward_normal)`` for the 5.3 MTE extension."""
    inner_a, inner_b, outer_b, outer_a = _extension_corners(mte_ext, extension_draw)
    _ = inner_a, inner_b
    if extension_draw is not None:
        ox, oy = _outward_normal_from_draw(extension_draw)
    else:
        ox, oy = _outward_normal_from_polygon(mte_ext)
    return outer_a, outer_b, (ox, oy)


def _extension_depth_um(
    inner_a: Point,
    outer_a: Point,
    outward: Point,
) -> float:
    ox, oy = outward
    depth = (outer_a[0] - inner_a[0]) * ox + (outer_a[1] - inner_a[1]) * oy
    if depth <= 0:
        raise ValueError("MTE extension depth must be positive")
    return depth


def _outer_half_extension_points(
    inner_a: Point,
    inner_b: Point,
    outer_b: Point,
    outer_a: Point,
    outward: Point,
    depth_um: float,
    shift_um: float,
) -> list[Point]:
    """Outer half of the MTE extension, shifted outward by ``shift_um``."""
    ox, oy = outward
    half = depth_um / 2.0
    mid_a = (inner_a[0] + ox * half, inner_a[1] + oy * half)
    mid_b = (inner_b[0] + ox * half, inner_b[1] + oy * half)
    sx, sy = ox * shift_um, oy * shift_um
    return [
        (mid_a[0] + sx, mid_a[1] + sy),
        (mid_b[0] + sx, mid_b[1] + sy),
        (outer_b[0] + sx, outer_b[1] + sy),
        (outer_a[0] + sx, outer_a[1] + sy),
    ]


def draw_mbe_cap_on_mte_extension(
    mte_ext: gdstk.Polygon,
    extension_draw: CollarExtensionDraw | None,
    layermap: LayerMap,
    cfg: MbeBodyConfig | None = None,
) -> gdstk.Polygon:
    """MBE cap: outer half of the MTE extension, shifted outward onto filler.

    Copies the exact 5.3 extension outline, keeps the outer depth half, then
    moves it ``cap_shift_um`` along the outward normal so it overlaps both the
    MTE extension and the carved MBE filler plate.
    """
    c = cfg or MbeBodyConfig()
    inner_a, inner_b, outer_b, outer_a = _extension_corners(mte_ext, extension_draw)
    _, _, outward = _extension_outer_edge(mte_ext, extension_draw)
    depth_um = _extension_depth_um(inner_a, outer_a, outward)

    points = _outer_half_extension_points(
        inner_a,
        inner_b,
        outer_b,
        outer_a,
        outward,
        depth_um,
        c.cap_shift_um,
    )
    cap = gdstk.Polygon(points, layer=mte_ext.layer, datatype=mte_ext.datatype)
    return tag_baw_mbe(cap, layermap)


def _offset_polys(
    polys: Sequence[gdstk.Polygon],
    distance: float,
) -> list[gdstk.Polygon]:
    return offset_polys(polys, distance)


def _project_along(point: Point, axis: Point) -> float:
    return point[0] * axis[0] + point[1] * axis[1]


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


def _raycast_nearest_hit(
    polys: Sequence[gdstk.Polygon],
    origin: Point,
    direction: Point,
) -> Point | None:
    """First intersection along ``origin + t * direction`` for ``t > 0``."""
    best_t: float | None = None
    for poly in polys:
        pts = [(float(p[0]), float(p[1])) for p in poly.points]
        if len(pts) < 2:
            continue
        n = len(pts)
        for i in range(n):
            t = _ray_segment_hit_t(origin, direction, pts[i], pts[(i + 1) % n])
            if t is None:
                continue
            if best_t is None or t < best_t:
                best_t = t
    if best_t is None:
        return None
    return (
        origin[0] + direction[0] * best_t,
        origin[1] + direction[1] * best_t,
    )


def _cap_outer_edge_endpoints(
    cap: gdstk.Polygon,
    outward: Point,
) -> tuple[Point, Point]:
    """The cap edge segment that faces the MBE filler plate."""
    pts = [(float(p[0]), float(p[1])) for p in cap.points]
    if len(pts) < 2:
        raise ValueError("MBE cap polygon has fewer than 2 vertices")
    projections = [_project_along(p, outward) for p in pts]
    max_proj = max(projections)
    tol = 0.5
    outer_pts = [p for p, proj in zip(pts, projections, strict=True) if proj >= max_proj - tol]
    if len(outer_pts) < 2:
        ranked = sorted(zip(projections, pts, strict=True), key=lambda item: item[0], reverse=True)
        outer_pts = [ranked[0][1], ranked[1][1]]
    tangent = (-outward[1], outward[0])
    outer_pts.sort(key=lambda p: _project_along(p, tangent))
    return outer_pts[0], outer_pts[-1]


def _dist_point_to_segment(
    point: Point,
    p0: Point,
    p1: Point,
) -> float:
    px, py = point
    x0, y0 = p0
    x1, y1 = p1
    dx, dy = x1 - x0, y1 - y0
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-18:
        return math.hypot(px - x0, py - y0)
    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / length_sq))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def _dist_point_to_polygon(point: Point, poly: gdstk.Polygon) -> float:
    pts = [(float(p[0]), float(p[1])) for p in poly.points]
    if len(pts) < 2:
        return float("inf")
    n = len(pts)
    return min(
        _dist_point_to_segment(point, pts[i], pts[(i + 1) % n]) for i in range(n)
    )


def _min_gap_cap_to_polys(cap: gdstk.Polygon, polys: Sequence[gdstk.Polygon]) -> float:
    best = float("inf")
    for x, y in cap.points:
        point = (float(x), float(y))
        for poly in polys:
            best = min(best, _dist_point_to_polygon(point, poly))
    return best


def _nearest_carved_intercept_at_corner(
    corner: Point,
    cap: gdstk.Polygon,
    carved_filler: Sequence[gdstk.Polygon],
    tangent: Point,
    max_gap_um: float,
    tangent_slack_um: float,
) -> Point | None:
    """Carved boundary point closest to one cap corner within the mouth corridor."""
    t_corner = _project_along(corner, tangent)
    best_dist = float("inf")
    best_point: Point | None = None
    for poly in carved_filler:
        for x, y in poly.points:
            pt = (float(x), float(y))
            t = _project_along(pt, tangent)
            if abs(t - t_corner) > tangent_slack_um:
                continue
            gap = _dist_point_to_polygon(pt, cap)
            if gap > max_gap_um:
                continue
            dist = math.hypot(pt[0] - corner[0], pt[1] - corner[1])
            if dist < best_dist:
                best_dist = dist
                best_point = pt
    return best_point


def _carved_intercepts_near_cap(
    cap: gdstk.Polygon,
    carved_filler: Sequence[gdstk.Polygon],
    start_a: Point,
    start_b: Point,
    outward: Point,
    max_gap_um: float,
    *,
    tangent_slack_um: float = 20.0,
) -> tuple[Point, Point] | None:
    """Endpoints of the carved boundary curve that sits near the cap mouth."""
    tangent = (-outward[1], outward[0])
    intercept_a = _nearest_carved_intercept_at_corner(
        start_a,
        cap,
        carved_filler,
        tangent,
        max_gap_um,
        tangent_slack_um,
    )
    intercept_b = _nearest_carved_intercept_at_corner(
        start_b,
        cap,
        carved_filler,
        tangent,
        max_gap_um,
        tangent_slack_um,
    )
    if intercept_a is not None and intercept_b is not None:
        return intercept_a, intercept_b

    t_lo = min(_project_along(start_a, tangent), _project_along(start_b, tangent))
    t_hi = max(_project_along(start_a, tangent), _project_along(start_b, tangent))
    margin = 2.0
    candidates: list[tuple[float, float, Point]] = []
    for poly in carved_filler:
        for x, y in poly.points:
            pt = (float(x), float(y))
            t = _project_along(pt, tangent)
            if t < t_lo - margin or t > t_hi + margin:
                continue
            gap = _dist_point_to_polygon(pt, cap)
            if gap <= max_gap_um:
                candidates.append((t, gap, pt))
    if len(candidates) < 2:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][2], candidates[-1][2]


def _cap_inset_points(
    start_a: Point,
    start_b: Point,
    outward: Point,
    inset_um: float,
) -> tuple[Point, Point]:
    return (
        (start_a[0] - outward[0] * inset_um, start_a[1] - outward[1] * inset_um),
        (start_b[0] - outward[0] * inset_um, start_b[1] - outward[1] * inset_um),
    )


def _build_curve_merge_at_cap(
    cap: gdstk.Polygon,
    extension_draw: CollarExtensionDraw | None,
    mte_ext: gdstk.Polygon,
    carved_filler: Sequence[gdstk.Polygon],
    layermap: LayerMap,
    cfg: MbeBodyConfig,
) -> gdstk.Polygon | None:
    """Straight merge when a carved stadium curve sits right on the cap."""
    _, _, outward = _extension_outer_edge(mte_ext, extension_draw)
    start_a, start_b = _cap_outer_edge_endpoints(cap, outward)
    intercepts = _carved_intercepts_near_cap(
        cap,
        carved_filler,
        start_a,
        start_b,
        outward,
        cfg.curve_merge_max_gap_um,
    )
    if intercepts is None:
        return None
    intercept_a, intercept_b = intercepts
    bite = cfg.bridge_cap_overlap_um
    intercept_a = (
        intercept_a[0] + outward[0] * bite,
        intercept_a[1] + outward[1] * bite,
    )
    intercept_b = (
        intercept_b[0] + outward[0] * bite,
        intercept_b[1] + outward[1] * bite,
    )

    bridge_start_a, bridge_start_b = _cap_inset_points(
        start_a,
        start_b,
        outward,
        cfg.bridge_cap_overlap_um,
    )
    merge = gdstk.Polygon(
        [bridge_start_a, bridge_start_b, intercept_b, intercept_a],
        layer=cap.layer,
        datatype=cap.datatype,
    )
    return tag_baw_mbe(merge, layermap)


def _build_ray_bridge_at_cap(
    cap: gdstk.Polygon,
    extension_draw: CollarExtensionDraw | None,
    mte_ext: gdstk.Polygon,
    carved_filler: Sequence[gdstk.Polygon],
    layermap: LayerMap,
    cfg: MbeBodyConfig,
) -> gdstk.Polygon | None:
    """Ray-cast bridge when the carved filler is far from the cap."""
    _, _, outward = _extension_outer_edge(mte_ext, extension_draw)
    start_a, start_b = _cap_outer_edge_endpoints(cap, outward)
    step = cfg.bridge_step_back_um
    origin_a = (start_a[0] - outward[0] * step, start_a[1] - outward[1] * step)
    origin_b = (start_b[0] - outward[0] * step, start_b[1] - outward[1] * step)
    mid = ((start_a[0] + start_b[0]) / 2.0, (start_a[1] + start_b[1]) / 2.0)
    origin_m = (mid[0] - outward[0] * step, mid[1] - outward[1] * step)

    travel_t: float | None = None
    for origin in (origin_m, origin_a, origin_b):
        hit = _raycast_nearest_hit(carved_filler, origin, outward)
        if hit is None:
            continue
        travel_t = _project_along(
            (hit[0] - origin[0], hit[1] - origin[1]),
            outward,
        )
        break
    if travel_t is None or travel_t <= 0:
        return None

    hit_a = (
        origin_a[0] + outward[0] * travel_t,
        origin_a[1] + outward[1] * travel_t,
    )
    hit_b = (
        origin_b[0] + outward[0] * travel_t,
        origin_b[1] + outward[1] * travel_t,
    )

    cap_inset = cfg.bridge_cap_overlap_um
    bridge_start_a, bridge_start_b = _cap_inset_points(
        start_a,
        start_b,
        outward,
        cap_inset,
    )

    bridge = gdstk.Polygon(
        [bridge_start_a, bridge_start_b, hit_b, hit_a],
        layer=cap.layer,
        datatype=cap.datatype,
    )
    return tag_baw_mbe(bridge, layermap)


def _build_filler_bridge(
    cap: gdstk.Polygon,
    extension_draw: CollarExtensionDraw | None,
    mte_ext: gdstk.Polygon,
    carved_filler: Sequence[gdstk.Polygon],
    layermap: LayerMap,
    cfg: MbeBodyConfig,
) -> gdstk.Polygon | None:
    """Reconnect carved filler to the MBE cap across the stadium keepout gap."""
    if not carved_filler:
        return None

    if gdstk.boolean(
        list(carved_filler),
        cap,
        "and",
        precision=cfg.boolean_precision,
    ):
        return None

    gap = _min_gap_cap_to_polys(cap, carved_filler)
    if gap <= cfg.curve_merge_max_gap_um and len(carved_filler) == 1:
        merge = _build_curve_merge_at_cap(
            cap,
            extension_draw,
            mte_ext,
            carved_filler,
            layermap,
            cfg,
        )
        if merge is not None:
            return merge

    return _build_ray_bridge_at_cap(
        cap,
        extension_draw,
        mte_ext,
        carved_filler,
        layermap,
        cfg,
    )


def build_mbe_body_keepouts(
    roles: RtegGeometryRoles,
    signal_route: gdstk.Polygon | None,
    cfg: MbeBodyConfig | None = None,
    *,
    mte_result: MteExtensionResult | None = None,
) -> list[gdstk.Polygon]:
    """Stadium, release-hole, and routed-signal clearance zones for step 6.2.

    ``signal_route`` is the 6.1 MBE routed net. MTE obstacles include resonator
    body MTE, the 5.3 extension, and any center-pad MTE route on layer 5/0.
    """
    c = cfg or MbeBodyConfig()
    keepouts: list[gdstk.Polygon] = []

    mte_extension = mte_result.extension if mte_result is not None else None
    mte_routed_net = mte_result.routed_net if mte_result is not None else None
    mte_obstacles = mte_route_obstacle_polys(
        roles.resonator_body_mte,
        mte_extension,
        mte_routed_net,
    )
    clearance_um = c.mbe_mte_min_spacing_um * c.stadium_clearance_factor
    if mte_obstacles and clearance_um > 0:
        keepouts.extend(_offset_polys(mte_obstacles, clearance_um))

    release_polys = [tp.polygon for tp in roles.release_holes.all_items()]
    if release_polys and c.release_hole_clearance_um > 0:
        keepouts.extend(
            _grown_keepout_polys(release_polys, c.release_hole_clearance_um)
        )

    if signal_route is not None and c.mbe_mte_min_spacing_um > 0:
        keepouts.extend(_offset_polys([signal_route], c.mbe_mte_min_spacing_um))

    return keepouts


def build_mbe_body_filler(
    base_filler: gdstk.Polygon,
    keepouts: Sequence[gdstk.Polygon],
    cfg: MbeBodyConfig | None = None,
) -> tuple[list[gdstk.Polygon], list[str]]:
    """Carve keepouts from the step-4 filler and clip to the filler bbox."""
    c = cfg or MbeBodyConfig()
    return carve_filler(
        base_filler,
        keepouts,
        boolean_precision=c.boolean_precision,
    )


def _merge_filler_with_bridge(
    carved: list[gdstk.Polygon],
    bridge: gdstk.Polygon | None,
    base_filler: gdstk.Polygon,
    cfg: MbeBodyConfig,
) -> list[gdstk.Polygon]:
    return merge_filler_with_bridge(
        carved,
        bridge,
        base_filler,
        boolean_precision=cfg.boolean_precision,
    )


def _base_filler_polygon(classification: NodeClassification) -> gdstk.Polygon | None:
    return base_filler_polygon(classification)


def build_mbe_body_collar_extend(
    roles: RtegGeometryRoles,
    classification: NodeClassification,
    mte_result: MteExtensionResult,
    mbe_signal: MbeExtensionResult | None,
    layermap: LayerMap,
    cfg: MbeBodyConfig | None = None,
) -> MbeBodyResult:
    """Run step 6.2 for a single ``collar_extend`` resonator."""
    c = cfg or MbeBodyConfig()
    if not mbe_body_collar_extend_applies(classification):
        return _empty_mbe_body_result()

    base_filler = _base_filler_polygon(classification)
    if base_filler is None:
        return _empty_mbe_body_result(violations=["missing step-4 MBE width filler"])

    mte_ext = mte_result.extension
    if mte_ext is None:
        return _empty_mbe_body_result(violations=["missing 5.3 MTE collar extension"])

    violations: list[str] = []
    cap = draw_mbe_cap_on_mte_extension(
        mte_ext,
        mte_result.extension_draw,
        layermap,
        c,
    )
    overlap = gdstk.boolean(cap, mte_ext, "and", precision=c.boolean_precision)
    if not overlap:
        violations.append("MBE cap does not overlap 5.3 MTE extension")

    signal_route = None
    if mbe_signal is not None:
        signal_route = mbe_signal.routed_net or mbe_signal.extension

    keepouts = build_mbe_body_keepouts(roles, signal_route, c, mte_result=mte_result)
    carved, filler_violations = build_mbe_body_filler(base_filler, keepouts, c)
    violations.extend(filler_violations)

    bridge = _build_filler_bridge(
        cap,
        mte_result.extension_draw,
        mte_ext,
        carved,
        layermap,
        c,
    )
    if bridge is None and carved and not gdstk.boolean(
        carved,
        cap,
        "and",
        precision=c.boolean_precision,
    ):
        violations.append("could not build filler bridge from MBE cap to carved filler")
    carved = _merge_filler_with_bridge(carved, bridge, base_filler, c)

    export_polys = [*carved, cap]
    return MbeBodyResult(
        cap=cap,
        filler=carved,
        bridge=bridge,
        routed_net=export_polys,
        n_pieces=len(export_polys),
        drc_violations=violations,
    )


def build_mbe_body(
    roles: RtegGeometryRoles,
    classification: NodeClassification,
    mte_result: MteExtensionResult,
    mbe_signal: MbeExtensionResult | None,
    layermap: LayerMap,
    cfg: MbeBodyConfig | None = None,
    conn_cfg: MbeConnectionConfig | None = None,
) -> MbeBodyResult:
    """Run step 6.2 or 6.3 for a single resonator."""
    c = cfg or MbeBodyConfig()
    if not mbe_body_applies(classification):
        return _empty_mbe_body_result()

    if mbe_body_center_pad_applies(classification):
        return build_mbe_body_center_pad(
            roles,
            classification,
            mte_result,
            layermap,
            _center_pad_config_from_body(c),
            conn_cfg,
        )

    return build_mbe_body_collar_extend(
        roles,
        classification,
        mte_result,
        mbe_signal,
        layermap,
        c,
    )


def build_mbe_body_collar_extends(
    roles_by_index: Mapping[int, RtegGeometryRoles],
    classifications: Mapping[int, NodeClassification],
    mte_by_index: Mapping[int, MteExtensionResult],
    mbe_signal_by_index: Mapping[int, MbeExtensionResult],
    layermap: LayerMap,
    config: MbeBodyConfig | None = None,
) -> dict[int, MbeBodyResult]:
    """Run step 6.2 for every resonator index in ``roles_by_index``."""
    cfg = config or MbeBodyConfig()
    out: dict[int, MbeBodyResult] = {}
    for idx, roles in roles_by_index.items():
        classification = classifications[idx]
        if not mbe_body_collar_extend_applies(classification):
            out[idx] = _empty_mbe_body_result()
            continue
        out[idx] = build_mbe_body_collar_extend(
            roles,
            classification,
            mte_by_index[idx],
            mbe_signal_by_index.get(idx),
            layermap,
            cfg,
        )
    return out


def build_mbe_bodies(
    roles_by_index: Mapping[int, RtegGeometryRoles],
    classifications: Mapping[int, NodeClassification],
    mte_by_index: Mapping[int, MteExtensionResult],
    mbe_signal_by_index: Mapping[int, MbeExtensionResult],
    layermap: LayerMap,
    config: MbeBodyConfig | None = None,
    conn_config: MbeConnectionConfig | None = None,
) -> dict[int, MbeBodyResult]:
    """Run step 6.2 / 6.3 for every resonator index in ``roles_by_index``."""
    cfg = config or MbeBodyConfig()
    conn_cfg = conn_config or MbeConnectionConfig()
    out: dict[int, MbeBodyResult] = {}
    for idx, roles in roles_by_index.items():
        classification = classifications[idx]
        if not mbe_body_applies(classification):
            out[idx] = _empty_mbe_body_result()
            continue
        out[idx] = build_mbe_body(
            roles,
            classification,
            mte_by_index[idx],
            mbe_signal_by_index.get(idx),
            layermap,
            cfg,
            conn_cfg,
        )
    return out


def mbe_body_overview_rows(
    bodies: Mapping[int, MbeBodyResult],
    *,
    inst_names: Mapping[int, str] | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx in sorted(bodies):
        result = bodies[idx]
        cap_area = abs(result.cap.area()) if result.cap is not None else 0.0
        filler_area = sum(abs(p.area()) for p in result.filler)
        rows.append(
            {
                "index": idx,
                "inst_name": inst_names.get(idx) if inst_names else None,
                "n_pieces": result.n_pieces,
                "cap_area_um2": round(cap_area, 2),
                "filler_area_um2": round(filler_area, 2),
                "drc_violations": "; ".join(result.drc_violations) or None,
            }
        )
    return rows


__all__ = [
    "MbeBodyConfig",
    "MbeBodyResult",
    "build_mbe_bodies",
    "build_mbe_body",
    "build_mbe_body_collar_extend",
    "build_mbe_body_collar_extends",
    "build_mbe_body_filler",
    "build_mbe_body_keepouts",
    "draw_mbe_cap_on_mte_extension",
    "mbe_body_applies",
    "mbe_body_center_pad_applies",
    "mbe_body_collar_extend_applies",
    "mbe_body_overview_rows",
]
