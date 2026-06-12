"""
Step 5.3 geometry — MTE linear span and pad strip (agent-ready polygon in/out).

All draw functions take explicit ``layer`` / ``datatype`` from
``layermap.pair(mte_layer)``; callers re-tag with ``assign_layer`` after booleans.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

import gdstk

from layermap import LayerMap
from rteg_utils import assign_layer

Point = tuple[float, float]
Edge = tuple[Point, Point]

_COLLAR_OVERLAP_UM = 0.5


def _edge_midpoint(edge: Edge) -> Point:
    return (
        (edge[0][0] + edge[1][0]) / 2.0,
        (edge[0][1] + edge[1][1]) / 2.0,
    )


def _edge_length(edge: Edge) -> float:
    return math.hypot(edge[1][0] - edge[0][0], edge[1][1] - edge[0][1])


def _closest_on_segment(pt: Point, edge: Edge) -> Point:
    (x0, y0), (x1, y1) = edge
    dx, dy = x1 - x0, y1 - y0
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-12:
        return edge[0]
    t = max(
        0.0,
        min(1.0, ((pt[0] - x0) * dx + (pt[1] - y0) * dy) / length_sq),
    )
    return (x0 + t * dx, y0 + t * dy)


def _polygon_centroid(poly: gdstk.Polygon) -> Point:
    pts = poly.points
    if len(pts) == 0:
        return (0.0, 0.0)
    return (
        sum(float(p[0]) for p in pts) / len(pts),
        sum(float(p[1]) for p in pts) / len(pts),
    )


def find_collar_facing_edge(collar_polygon: gdstk.Polygon, toward: Point) -> Edge:
    """Edge of ``collar_polygon`` on the side that faces ``toward`` (not bbox)."""
    pts = list(collar_polygon.points)
    if len(pts) < 2:
        raise ValueError("collar polygon has fewer than 2 points")
    cx, cy = _polygon_centroid(collar_polygon)
    tx, ty = toward
    best_edge: Edge | None = None
    best_score = float("inf")
    n = len(pts)
    for i in range(n):
        p0 = (float(pts[i][0]), float(pts[i][1]))
        p1 = (float(pts[(i + 1) % n][0]), float(pts[(i + 1) % n][1]))
        mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
        outward = (mid[0] - cx, mid[1] - cy)
        inward = (tx - cx, ty - cy)
        if outward[0] * inward[0] + outward[1] * inward[1] <= 0:
            continue
        d = math.hypot(mid[0] - tx, mid[1] - ty)
        if d < best_score:
            best_score = d
            best_edge = (p0, p1)
    if best_edge is None:
        best_edge = (
            (float(pts[0][0]), float(pts[0][1])),
            (float(pts[1][0]), float(pts[1][1])),
        )
    return best_edge


def find_intercept_point(
    collar_polygon: gdstk.Polygon,
    pad_inner_edge: Edge,
) -> Point:
    """Point on the collar perimeter closest to the pad inner edge."""
    target = _edge_midpoint(pad_inner_edge)
    pts = list(collar_polygon.points)
    if not pts:
        raise ValueError("collar polygon has no points")
    best = (float(pts[0][0]), float(pts[0][1]))
    best_d = float("inf")
    n = len(pts)
    for i in range(n):
        edge = (
            (float(pts[i][0]), float(pts[i][1])),
            (float(pts[(i + 1) % n][0]), float(pts[(i + 1) % n][1])),
        )
        candidate = _closest_on_segment(target, edge)
        d = math.hypot(candidate[0] - target[0], candidate[1] - target[1])
        if d < best_d:
            best_d = d
            best = candidate
    return best


def _outward_normal(edge: Edge, toward: Point) -> tuple[float, float]:
    (x0, y0), (x1, y1) = edge
    mid = _edge_midpoint(edge)
    tx, ty = x1 - x0, y1 - y0
    length = math.hypot(tx, ty)
    if length < 1e-9:
        dx, dy = toward[0] - mid[0], toward[1] - mid[1]
        length = math.hypot(dx, dy)
        return (dx / length, dy / length) if length > 1e-9 else (0.0, 1.0)
    nx, ny = -ty / length, tx / length
    if (toward[0] - mid[0]) * nx + (toward[1] - mid[1]) * ny < 0:
        nx, ny = -nx, -ny
    return nx, ny


def build_pad_linear_strip(
    pad_inner_edge: Edge,
    width_um: float,
    layer: int,
    datatype: int,
    *,
    toward: Point | None = None,
) -> gdstk.Polygon:
    if width_um <= 0:
        raise ValueError("width_um must be positive")
    if _edge_length(pad_inner_edge) < 1e-6:
        raise ValueError("pad_inner_edge is degenerate")
    mid = _edge_midpoint(pad_inner_edge)
    target = toward if toward is not None else mid
    nx, ny = _outward_normal(pad_inner_edge, target)
    (x0, y0), (x1, y1) = pad_inner_edge
    ox, oy = nx * width_um, ny * width_um
    pts = [
        (x0, y0),
        (x1, y1),
        (x1 + ox, y1 + oy),
        (x0 + ox, y0 + oy),
    ]
    return gdstk.Polygon(pts, layer=layer, datatype=datatype)


def build_linear_span(
    intercept_point: Point,
    pad_strip_polygon: gdstk.Polygon,
    width_um: float,
    layer: int,
    datatype: int,
    *,
    collar_polygon: gdstk.Polygon | None = None,
) -> gdstk.Polygon:
    """Straight metal from collar intercept to pad strip; start inside collar when given."""
    if width_um <= 0:
        raise ValueError("width_um must be positive")
    bb = pad_strip_polygon.bounding_box()
    if bb is None:
        raise ValueError("pad_strip_polygon has no bounding box")
    target = (
        (bb[0][0] + bb[1][0]) / 2.0,
        (bb[0][1] + bb[1][1]) / 2.0,
    )
    start = intercept_point
    if collar_polygon is not None:
        cx, cy = _polygon_centroid(collar_polygon)
        dx, dy = cx - intercept_point[0], cy - intercept_point[1]
        length = math.hypot(dx, dy)
        if length > 1e-9:
            inset = min(_COLLAR_OVERLAP_UM, length * 0.25)
            start = (
                intercept_point[0] + dx / length * inset,
                intercept_point[1] + dy / length * inset,
            )
    flex = gdstk.FlexPath([start, target], width_um, layer=layer, datatype=datatype)
    polys = flex.to_polygons()
    if not polys:
        raise ValueError("linear span produced no polygon")
    return polys[0]


def _outward_target(collar_polygon: gdstk.Polygon) -> Point:
    """Exterior reference point from collar geometry only."""
    cx, cy = _polygon_centroid(collar_polygon)
    best = max(
        collar_polygon.points,
        key=lambda p: (float(p[0]) - cx) ** 2 + (float(p[1]) - cy) ** 2,
    )
    return (float(best[0]), float(best[1]))


def draw_preserved_mte_extension(
    preserved_collar: gdstk.Polygon,
    extension_um: float,
    layer: int,
    datatype: int,
    *,
    overlap_um: float = _COLLAR_OVERLAP_UM,
) -> gdstk.Polygon:
    """
    Draw one new MTE polygon from a preserved collar.

    The outline follows the preserved collar shape. Vertices on the open
    (outward) side shift along one normal so the far end is a straight line
    parallel to the collar mouth. Inward vertices stay fixed so the draw
    overlaps the original collar without replacing it.
    """
    if extension_um <= 0:
        raise ValueError("extension_um must be positive")
    pts_in = list(preserved_collar.points)
    if len(pts_in) < 3:
        raise ValueError("preserved collar must have at least 3 vertices")

    toward = _outward_target(preserved_collar)
    facing = find_collar_facing_edge(preserved_collar, toward)
    nx, ny = _outward_normal(facing, toward)
    cx, cy = _polygon_centroid(preserved_collar)

    out: list[Point] = []
    for p in pts_in:
        px, py = float(p[0]), float(p[1])
        outward_score = (px - cx) * nx + (py - cy) * ny
        if outward_score >= -overlap_um:
            out.append((px + nx * extension_um, py + ny * extension_um))
        else:
            out.append((px, py))

    return gdstk.Polygon(out, layer=layer, datatype=datatype)


def build_collar_extension_box(
    collar_polygon: gdstk.Polygon,
    toward: Point,
    extension_um: float,
    layer: int,
    datatype: int,
    *,
    width_um: float | None = None,
) -> gdstk.Polygon:
    """Legacy alias — prefer ``draw_preserved_mte_extension``."""
    del toward, width_um
    return draw_preserved_mte_extension(
        collar_polygon,
        extension_um,
        layer,
        datatype,
    )


def merge_single_mte_net(
    preserved: gdstk.Polygon,
    *additions: gdstk.Polygon,
    precision: float,
    layermap: LayerMap,
    mte_layer_name: str,
) -> gdstk.Polygon:
    """Boolean-OR drawn additions only; original ``preserved`` collar is untouched."""
    if not additions:
        raise ValueError("no drawn MTE additions to merge")
    acc: list[gdstk.Polygon] = [additions[0]]
    for poly in additions[1:]:
        nxt = gdstk.boolean(acc, poly, "or", precision=precision)
        acc = nxt if nxt else acc + [poly]
    merged = acc

    connected = [p for p in merged if _polygons_touch(p, preserved, precision)]
    if len(connected) != 1 or len(merged) != 1:
        raise ValueError("no drawn MTE overlaps preserved collar after merge")

    return assign_layer(connected[0], layermap, mte_layer_name)


def collar_overlap_area(
    net: gdstk.Polygon,
    collar: gdstk.Polygon,
    precision: float,
) -> float:
    inter = gdstk.boolean(net, collar, "and", precision=precision)
    return sum(abs(p.area()) for p in inter) if inter else 0.0


def check_mte_attached_to_collar(
    net_polygon: gdstk.Polygon,
    collar_polygon: gdstk.Polygon,
    precision: float,
    *,
    min_overlap_um2: float = 0.01,
) -> list[str]:
    """DRC: drawn MTE must share area with the preserved collar polygon."""
    overlap = collar_overlap_area(net_polygon, collar_polygon, precision)
    if overlap < min_overlap_um2:
        return [
            f"MTE net not attached to preserved collar (overlap {overlap:.2f} um² < {min_overlap_um2:.2f} um²)"
        ]
    return []


def check_mte_detached_from_resonator(
    mte_polygons: Sequence[gdstk.Polygon],
    anchor_collar: gdstk.Polygon,
    precision: float,
    *,
    min_overlap_um2: float = 0.01,
) -> list[str]:
    """
    DRC for export/layout review: every MTE polygon must be connected to the
    route anchor collar, directly or through other MTE polygons.
    """
    connected = mte_connected_component_indices(
        mte_polygons,
        anchor_collar,
        precision,
        min_overlap_um2=min_overlap_um2,
    )
    if not mte_polygons:
        return []
    if not connected:
        return ["no exported MTE polygon is attached to the anchor collar"]

    violations: list[str] = []
    for i, poly in enumerate(mte_polygons):
        if i not in connected:
            bb = poly.bounding_box()
            bbox = (
                (
                    round(float(bb[0][0]), 3),
                    round(float(bb[0][1]), 3),
                ),
                (
                    round(float(bb[1][0]), 3),
                    round(float(bb[1][1]), 3),
                ),
            ) if bb else None
            violations.append(
                f"MTE polygon {i} is detached from anchor collar network; bbox={bbox}"
            )
    return violations


def mte_connected_component_indices(
    mte_polygons: Sequence[gdstk.Polygon],
    anchor_collar: gdstk.Polygon,
    precision: float,
    *,
    min_overlap_um2: float = 0.01,
) -> set[int]:
    """Indices of MTE polygons connected to the anchor collar network."""
    connected = {
        i
        for i, poly in enumerate(mte_polygons)
        if _polygons_touch(poly, anchor_collar, precision)
        and collar_overlap_area(poly, anchor_collar, precision) >= min_overlap_um2
    }
    changed = True
    while changed:
        changed = False
        for i, poly in enumerate(mte_polygons):
            if i in connected:
                continue
            if any(_polygons_touch(poly, mte_polygons[j], precision) for j in connected):
                connected.add(i)
                changed = True
    return connected


def check_mte_reaches_center_pad(
    net_polygon: gdstk.Polygon,
    signal_pad_polygons: Sequence[gdstk.Polygon],
    precision: float,
    *,
    connect_tolerance_um: float = 0.5,
) -> tuple[bool, list[str]]:
    """DRC: center route must geometrically reach the center signal pad region."""
    if not signal_pad_polygons:
        return False, ["no center signal pad polygons"]
    violations: list[str] = []
    for i, pad in enumerate(signal_pad_polygons):
        if gdstk.boolean(net_polygon, pad, "and", precision=precision):
            return True, []
        bb_n = net_polygon.bounding_box()
        bb_p = pad.bounding_box()
        if bb_n and bb_p:
            gap = _bbox_gap(bb_n, bb_p)
            if gap <= connect_tolerance_um:
                return True, []
        violations.append(f"center signal pad {i}: MTE net does not reach pad")
    return False, violations


def check_mte_vs_ground_drc(
    mte_polygon: gdstk.Polygon,
    ground_polygons: Sequence[gdstk.Polygon],
    min_spacing_um: float,
    precision: float,
) -> tuple[float, list[str]]:
    min_clear = float("inf")
    violations: list[str] = []
    for i, ground in enumerate(ground_polygons):
        if gdstk.boolean(mte_polygon, ground, "and", precision=precision):
            min_clear = 0.0
            violations.append(f"overlap with ground polygon {i}")
            continue
        d = _min_vertex_spacing(mte_polygon, ground)
        if d < min_clear:
            min_clear = d
        if d < min_spacing_um:
            violations.append(
                f"ground polygon {i}: spacing {d:.2f} um < {min_spacing_um:.2f} um"
            )
    if min_clear == float("inf"):
        min_clear = float("nan")
    return min_clear, violations


def _bbox_gap(a: tuple[Point, Point], b: tuple[Point, Point]) -> float:
    dx = max(0.0, max(a[0][0] - b[1][0], b[0][0] - a[1][0]))
    dy = max(0.0, max(a[0][1] - b[1][1], b[0][1] - a[1][1]))
    return math.hypot(dx, dy)


def _polygons_touch(a: gdstk.Polygon, b: gdstk.Polygon, precision: float) -> bool:
    if gdstk.boolean(a, b, "and", precision=precision):
        return True
    bb_a = a.bounding_box()
    bb_b = b.bounding_box()
    if bb_a is None or bb_b is None:
        return False
    return _bbox_gap(bb_a, bb_b) <= precision


def _min_vertex_spacing(a: gdstk.Polygon, b: gdstk.Polygon) -> float:
    best = float("inf")
    for pa in a.points:
        for pb in b.points:
            d = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
            if d < best:
                best = d
    return best
