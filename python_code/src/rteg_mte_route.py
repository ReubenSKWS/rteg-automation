"""
Step 5.4 — Route 5.3 MTE collar extensions to the center signal pad.

When ``mte_route_target == "center_pad"``, build a constant-width corridor from the
5.3 extension outer cap into the classified signal pad with configurable overlap.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

import gdstk

from layermap import LayerMap
from rteg_classify import NodeClassification
from rteg_collect import GroundPlates, RtegGeometryRoles
from rteg_mte_extensions import CollarExtensionDraw, MteExtensionResult
from rteg_utils import assign_layer, polys_bbox

Point = tuple[float, float]
Bbox = tuple[tuple[float, float], tuple[float, float]]
Edge = tuple[Point, Point]


@dataclass(frozen=True)
class MteRouteConfig:
    """Tunable parameters for step 5.4 pad routing."""

    mte_layer: str = "BAW_MTE"
    pad_touch_overlap_um: float = 0.5
    min_pad_overlap_um2: float = 0.01
    route_width_um: float | None = None
    min_ground_clearance_um: float = 14.0
    allow_45_degree_corners: bool = True
    boolean_precision: float = 1e-3
    inside_probe_half_um: float = 0.25


@dataclass(frozen=True)
class RouteStart:
    """Attach point on the pad-facing edge of the 5.3 extension."""

    center: Point
    width_um: float
    outer_edge: Edge


@dataclass(frozen=True)
class MteRouteDraw:
    """Pad-routing geometry for one resonator."""

    route_polygon: gdstk.Polygon
    routed_net_polygon: gdstk.Polygon
    waypoints: list[Point]
    pad_entry: Point
    route_width_um: float
    pad_overlap_um2: float


def _dist(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _unit(dx: float, dy: float) -> tuple[float, float]:
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def _pad_reference_point(signal_polys: Sequence[gdstk.Polygon]) -> Point:
    bbox = _union_pad_bbox(signal_polys)
    if bbox is None:
        raise ValueError("signal pad has no geometry")
    (x0, y0), (x1, y1) = bbox
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def pick_route_start(
    extension_draw: CollarExtensionDraw,
    *,
    toward_point: Point | None = None,
) -> RouteStart:
    """
    Midpoint and width on the extension edge that faces ``toward_point``.

    When the 5.3 lip extrudes away from the route target (outer cap on the far
  side), attach on the collar-mouth edge instead so the corridor leaves from the
    pad-facing side of the extension.
    """
    p0, p1 = extension_draw.outer_edge
    outer_center = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
    width = extension_draw.mouth_span_um
    if width < 1e-6:
        width = _dist(p0, p1)

    if toward_point is None:
        return RouteStart(
            center=outer_center,
            width_um=width,
            outer_edge=extension_draw.outer_edge,
        )

    ia, ib = extension_draw.intercept_a, extension_draw.intercept_b
    inner_center = ((ia[0] + ib[0]) / 2.0, (ia[1] + ib[1]) / 2.0)
    ox, oy = outer_center[0] - inner_center[0], outer_center[1] - inner_center[1]
    tx, ty = toward_point[0] - inner_center[0], toward_point[1] - inner_center[1]
    if ox * tx + oy * ty > 0.0:
        return RouteStart(
            center=outer_center,
            width_um=width,
            outer_edge=extension_draw.outer_edge,
        )
    return RouteStart(
        center=inner_center,
        width_um=width,
        outer_edge=(ia, ib),
    )


def _union_pad_bbox(signal_polys: Sequence[gdstk.Polygon]) -> Bbox | None:
    return polys_bbox(list(signal_polys)) if signal_polys else None


def pick_pad_entry(
    signal_polys: Sequence[gdstk.Polygon],
    from_point: Point,
    *,
    touch_overlap_um: float,
) -> Point:
    """
    Point inside the signal pad nearest ``from_point``, shifted ``touch_overlap_um``
    inward from the closest pad bbox edge.
    """
    bbox = _union_pad_bbox(signal_polys)
    if bbox is None:
        raise ValueError("signal pad has no geometry")

    (x0, y0), (x1, y1) = bbox
    fx, fy = from_point
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0

    candidates: list[tuple[float, Point, tuple[float, float]]] = []
    if fx >= x0:
        candidates.append((fx - x1, (x1, cy), (-1.0, 0.0)))
    if fx <= x1:
        candidates.append((x0 - fx, (x0, cy), (1.0, 0.0)))
    if fy >= y0:
        candidates.append((fy - y1, (cx, y1), (0.0, -1.0)))
    if fy <= y1:
        candidates.append((y0 - fy, (cx, y0), (0.0, 1.0)))

    if not candidates:
        return (cx, cy)

    _, edge_pt, inward = min(candidates, key=lambda item: abs(item[0]))
    return (
        edge_pt[0] + inward[0] * touch_overlap_um,
        edge_pt[1] + inward[1] * touch_overlap_um,
    )


def _inflate_bbox(bbox: Bbox, margin: float) -> Bbox:
    (x0, y0), (x1, y1) = bbox
    return ((x0 - margin, y0 - margin), (x1 + margin, y1 + margin))


def _segment_bbox_intersects(p0: Point, p1: Point, bbox: Bbox) -> bool:
    (x0, y0), (x1, y1) = bbox
    min_x, max_x = min(p0[0], p1[0]), max(p0[0], p1[0])
    min_y, max_y = min(p0[1], p1[1]), max(p0[1], p1[1])
    if max_x < x0 or min_x > x1 or max_y < y0 or min_y > y1:
        return False
    return True


def _ground_obstacle_bboxes(ground_plates: GroundPlates) -> list[Bbox]:
    obstacles: list[Bbox] = []
    for group in (ground_plates.top, ground_plates.bottom):
        bb = polys_bbox([tp.polygon for tp in group])
        if bb is not None:
            obstacles.append(bb)
    return obstacles


def _path_clearance_score(
    waypoints: Sequence[Point],
    obstacles: Sequence[Bbox],
    *,
    half_width: float,
    clearance_um: float,
) -> int:
    margin = clearance_um + half_width
    violations = 0
    for i in range(len(waypoints) - 1):
        p0, p1 = waypoints[i], waypoints[i + 1]
        for bb in obstacles:
            if _segment_bbox_intersects(p0, p1, _inflate_bbox(bb, margin)):
                violations += 1
    return violations


def _strip_polygon(
    p0: Point,
    p1: Point,
    width_um: float,
    layer: int,
    datatype: int,
) -> gdstk.Polygon | None:
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return None
    tx, ty = dx / length, dy / length
    nx, ny = -ty, tx
    hw = width_um / 2.0
    pts = [
        (p0[0] + nx * hw, p0[1] + ny * hw),
        (p0[0] - nx * hw, p0[1] - ny * hw),
        (p1[0] - nx * hw, p1[1] - ny * hw),
        (p1[0] + nx * hw, p1[1] + ny * hw),
    ]
    return gdstk.Polygon(pts, layer=layer, datatype=datatype)


def _chamfer_corner(
    prev: Point,
    corner: Point,
    nxt: Point,
    *,
    chamfer_um: float,
) -> tuple[Point, Point]:
    v1x, v1y = _unit(corner[0] - prev[0], corner[1] - prev[1])
    v2x, v2y = _unit(nxt[0] - corner[0], nxt[1] - corner[1])
    d1 = min(chamfer_um, _dist(prev, corner) * 0.45)
    d2 = min(chamfer_um, _dist(corner, nxt) * 0.45)
    return (
        (corner[0] - v1x * d1, corner[1] - v1y * d1),
        (corner[0] + v2x * d2, corner[1] + v2y * d2),
    )


def _polyline_strips(
    waypoints: Sequence[Point],
    width_um: float,
    layer: int,
    datatype: int,
    *,
    allow_45: bool,
    precision: float,
) -> list[gdstk.Polygon]:
    if len(waypoints) < 2:
        return []
    pts = list(waypoints)
    if allow_45 and len(pts) == 3:
        a, b, c = pts
        chamfer = min(width_um, 4.0)
        p0, p1 = _chamfer_corner(a, b, c, chamfer_um=chamfer)
        segs = [(a, p0), (p0, p1), (p1, c)]
    else:
        segs = [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]

    strips: list[gdstk.Polygon] = []
    for s0, s1 in segs:
        strip = _strip_polygon(s0, s1, width_um, layer, datatype)
        if strip is not None:
            strips.append(strip)
    return strips


def _boolean_or_polys(
    polys: Sequence[gdstk.Polygon], precision: float
) -> gdstk.Polygon | None:
    if not polys:
        return None
    acc: list[gdstk.Polygon] = [polys[0]]
    for poly in polys[1:]:
        merged = gdstk.boolean(acc, [poly], "or", precision=precision)
        acc = list(merged) if merged else acc
    if not acc:
        return None
    if len(acc) == 1:
        return acc[0]
    merged = gdstk.boolean(acc, "or", precision=precision)
    return merged[0] if merged else acc[0]


def build_corridor_route(
    start: Point,
    end: Point,
    width_um: float,
    obstacles: Sequence[Bbox],
    layer: int,
    datatype: int,
    cfg: MteRouteConfig,
) -> tuple[gdstk.Polygon, list[Point]]:
    """Manhattan corridor from ``start`` to ``end`` with constant width."""
    half_w = width_um / 2.0
    corner_hv = (end[0], start[1])
    corner_vh = (start[0], end[1])
    candidates = [
        [start, corner_hv, end],
        [start, corner_vh, end],
        [start, end],
    ]
    best = min(
        candidates,
        key=lambda path: (
            _path_clearance_score(
                path,
                obstacles,
                half_width=half_w,
                clearance_um=cfg.min_ground_clearance_um,
            ),
            sum(_dist(path[i], path[i + 1]) for i in range(len(path) - 1)),
        ),
    )
    strips = _polyline_strips(
        best,
        width_um,
        layer,
        datatype,
        allow_45=cfg.allow_45_degree_corners,
        precision=cfg.boolean_precision,
    )
    route = _boolean_or_polys(strips, cfg.boolean_precision)
    if route is None:
        raise ValueError("corridor route is degenerate")
    return route, best


def union_mte_net(
    extension_poly: gdstk.Polygon,
    route_poly: gdstk.Polygon,
    *,
    precision: float,
) -> gdstk.Polygon:
    merged = gdstk.boolean([extension_poly], [route_poly], "or", precision=precision)
    if not merged:
        raise ValueError("failed to union extension and route")
    return merged[0] if len(merged) == 1 else _boolean_or_polys(merged, precision)  # type: ignore[arg-type]


def _pad_overlap_area(
    net_poly: gdstk.Polygon,
    signal_polys: Sequence[gdstk.Polygon],
    precision: float,
) -> float:
    if not signal_polys:
        return 0.0
    inter = gdstk.boolean([net_poly], list(signal_polys), "and", precision=precision)
    return sum(abs(p.area()) for p in inter) if inter else 0.0


def validate_pad_attachment(
    net_poly: gdstk.Polygon,
    signal_polys: Sequence[gdstk.Polygon],
    cfg: MteRouteConfig,
    *,
    resonator_index: int | None = None,
) -> float:
    overlap = _pad_overlap_area(net_poly, signal_polys, cfg.boolean_precision)
    prefix = f"resonator {resonator_index}: " if resonator_index is not None else ""
    if overlap < cfg.min_pad_overlap_um2:
        raise ValueError(
            f"{prefix}MTE routed net not attached to signal pad "
            f"(overlap {overlap:.4f} um² < {cfg.min_pad_overlap_um2:.4f} um²)"
        )
    return overlap


def build_mte_pad_route(
    roles: RtegGeometryRoles,
    classification: NodeClassification,
    mte_result: MteExtensionResult,
    layermap: LayerMap,
    cfg: MteRouteConfig | None = None,
    *,
    resonator_index: int | None = None,
) -> MteRouteDraw | None:
    """Build pad connector when ``mte_route_target == center_pad``; else ``None``."""
    c = cfg or MteRouteConfig()
    if classification.mte_route_target != "center_pad":
        return None
    if mte_result.extension is None or mte_result.extension_draw is None:
        return None

    signal_tps = classification.signal_polygons()
    if not signal_tps:
        raise ValueError(
            f"resonator {resonator_index}: center_pad route but no signal polygons"
        )

    layer, datatype = layermap.pair(c.mte_layer)
    signal_polys = [tp.polygon for tp in signal_tps]
    pad_ref = _pad_reference_point(signal_polys)
    start_info = pick_route_start(
        mte_result.extension_draw,
        toward_point=pad_ref,
    )
    width = c.route_width_um if c.route_width_um is not None else start_info.width_um
    if width <= 0:
        raise ValueError(f"resonator {resonator_index}: route width must be positive")

    pad_entry = pick_pad_entry(
        signal_polys,
        start_info.center,
        touch_overlap_um=c.pad_touch_overlap_um,
    )
    obstacles = _ground_obstacle_bboxes(roles.ground_plates)
    route_poly, waypoints = build_corridor_route(
        start_info.center,
        pad_entry,
        width,
        obstacles,
        layer,
        datatype,
        c,
    )
    route_poly = assign_layer(route_poly, layermap, c.mte_layer)
    ext = mte_result.extension
    routed_net = union_mte_net(ext, route_poly, precision=c.boolean_precision)
    routed_net = assign_layer(routed_net, layermap, c.mte_layer)
    overlap = validate_pad_attachment(
        routed_net,
        [tp.polygon for tp in signal_tps],
        c,
        resonator_index=resonator_index,
    )
    return MteRouteDraw(
        route_polygon=route_poly,
        routed_net_polygon=routed_net,
        waypoints=waypoints,
        pad_entry=pad_entry,
        route_width_um=width,
        pad_overlap_um2=overlap,
    )


def apply_mte_pad_route(
    mte_result: MteExtensionResult,
    route_draw: MteRouteDraw | None,
) -> MteExtensionResult:
    """Attach route draw / routed net onto an extension result."""
    if route_draw is None:
        return mte_result
    return replace(
        mte_result,
        route_draw=route_draw,
        routed_net=route_draw.routed_net_polygon,
    )


def build_mte_pad_routes(
    roles_by_index: Mapping[int, RtegGeometryRoles],
    classifications: Mapping[int, NodeClassification],
    extensions: Mapping[int, MteExtensionResult],
    layermap: LayerMap,
    config: MteRouteConfig | None = None,
) -> dict[int, MteExtensionResult]:
    """Run 5.4 pad routing for every resonator index present in ``extensions``."""
    cfg = config or MteRouteConfig()
    out: dict[int, MteExtensionResult] = {}
    for idx, result in extensions.items():
        roles = roles_by_index[idx]
        classification = classifications[idx]
        route_draw = build_mte_pad_route(
            roles,
            classification,
            result,
            layermap,
            cfg,
            resonator_index=idx,
        )
        out[idx] = apply_mte_pad_route(result, route_draw)
    return out


def mte_route_overview_rows(
    extensions: Mapping[int, MteExtensionResult],
    classifications: Mapping[int, NodeClassification],
    *,
    inst_names: Mapping[int, str] | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx in sorted(extensions):
        result = extensions[idx]
        classification = classifications[idx]
        draw = result.route_draw
        rows.append(
            {
                "index": idx,
                "inst_name": inst_names.get(idx) if inst_names else None,
                "mte_route_target": classification.mte_route_target,
                "mte_faces_center": classification.collar_orientation.mte_faces_center,
                "routed_to_pad": draw is not None,
                "pad_overlap_um2": round(draw.pad_overlap_um2, 4) if draw else None,
                "route_width_um": round(draw.route_width_um, 2) if draw else None,
                "n_waypoints": len(draw.waypoints) if draw else None,
            }
        )
    return rows


__all__ = [
    "MteRouteConfig",
    "MteRouteDraw",
    "RouteStart",
    "apply_mte_pad_route",
    "build_corridor_route",
    "build_mte_pad_route",
    "build_mte_pad_routes",
    "mte_route_overview_rows",
    "pick_pad_entry",
    "pick_route_start",
    "union_mte_net",
    "validate_pad_attachment",
]
