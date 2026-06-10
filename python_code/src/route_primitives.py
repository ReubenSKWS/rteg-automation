"""
Step 5 — Pure geometry primitives for interconnect candidate routes.

## Assumptions
- Coordinates are in RTEG world space (µm). Callers transform filter/PPD geometry.
- Routes use orthogonal and 45° segments only (no acute angles in emitted shapes).
- Inputs are ``gdstk.Polygon`` instances; paths/labels are not supported here.
- ``nearest_points`` measures true boundary-to-boundary distance, not bbox centers.
- No layermap, file I/O, or pipeline types in this module.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

import gdstk

Point = tuple[float, float]


def _unit(dx: float, dy: float) -> Point:
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def _segment_distance(p1: Point, p2: Point, q1: Point, q2: Point) -> tuple[float, Point, Point]:
    """Minimum distance between two line segments and the achieving endpoints."""
    ux, uy = p2[0] - p1[0], p2[1] - p1[1]
    vx, vy = q2[0] - q1[0], q2[1] - q1[1]
    wx, wy = p1[0] - q1[0], p1[1] - q1[1]
    a = ux * ux + uy * uy
    b = ux * vx + uy * vy
    c = vx * vx + vy * vy
    d = ux * wx + uy * wy
    e = vx * wx + vy * wy
    denom = a * c - b * b
    if denom < 1e-12:
        candidates = [
            (math.hypot(p1[0] - q1[0], p1[1] - q1[1]), p1, q1),
            (math.hypot(p1[0] - q2[0], p1[1] - q2[1]), p1, q2),
            (math.hypot(p2[0] - q1[0], p2[1] - q1[1]), p2, q1),
            (math.hypot(p2[0] - q2[0], p2[1] - q2[1]), p2, q2),
        ]
        return min(candidates, key=lambda item: item[0])

    sc = (b * e - c * d) / denom
    tc = (a * e - b * d) / denom
    sc = min(1.0, max(0.0, sc))
    tc = min(1.0, max(0.0, tc))
    pc = (p1[0] + sc * ux, p1[1] + sc * uy)
    qc = (q1[0] + tc * vx, q1[1] + tc * vy)
    return math.hypot(pc[0] - qc[0], pc[1] - qc[1]), pc, qc


def _polygon_edges(poly: gdstk.Polygon) -> list[tuple[Point, Point]]:
    pts = list(poly.points)
    if len(pts) < 2:
        return []
    edges: list[tuple[Point, Point]] = []
    for i in range(len(pts)):
        edges.append((pts[i], pts[(i + 1) % len(pts)]))
    return edges


def nearest_points(poly_a: gdstk.Polygon, poly_b: gdstk.Polygon) -> tuple[Point, Point]:
    """
    Closest point pair on two polygon boundaries.

    Assumes simple closed polygons (not self-intersecting paths).
    """
    best_dist = float("inf")
    best_pair: tuple[Point, Point] = (poly_a.points[0], poly_b.points[0])
    for e1 in _polygon_edges(poly_a):
        for e2 in _polygon_edges(poly_b):
            dist, p, q = _segment_distance(e1[0], e1[1], e2[0], e2[1])
            if dist < best_dist:
                best_dist = dist
                best_pair = (p, q)
    return best_pair


def polyline_length(points: Sequence[Point]) -> float:
    total = 0.0
    for i in range(1, len(points)):
        total += math.hypot(
            points[i][0] - points[i - 1][0],
            points[i][1] - points[i - 1][1],
        )
    return total


def _stroke_polygon(centerline: Sequence[Point], width: float) -> gdstk.Polygon:
    """Build a constant-width stroke along ``centerline`` (orthogonal/45 segments)."""
    if len(centerline) < 2:
        raise ValueError("centerline needs at least two points")
    half = width / 2.0
    left: list[Point] = []
    right: list[Point] = []
    for i, pt in enumerate(centerline):
        if i == 0:
            ux, uy = _unit(centerline[1][0] - pt[0], centerline[1][1] - pt[1])
        elif i == len(centerline) - 1:
            ux, uy = _unit(pt[0] - centerline[i - 1][0], pt[1] - centerline[i - 1][1])
        else:
            u1 = _unit(pt[0] - centerline[i - 1][0], pt[1] - centerline[i - 1][1])
            u2 = _unit(centerline[i + 1][0] - pt[0], centerline[i + 1][1] - pt[1])
            ux, uy = _unit(u1[0] + u2[0], u1[1] + u2[1])
        nx, ny = -uy, ux
        left.append((pt[0] + half * nx, pt[1] + half * ny))
        right.append((pt[0] - half * nx, pt[1] - half * ny))
    ring = left + list(reversed(right))
    return gdstk.Polygon(ring)


def route_straight(p1: Point, p2: Point, width: float) -> gdstk.Polygon:
    """Single straight connector between ``p1`` and ``p2``."""
    return _stroke_polygon([p1, p2], width)


def route_45(p1: Point, p2: Point, width: float) -> gdstk.Polygon:
    """
    One 45° transition: axis-aligned legs with a diagonal corner.

    Chooses horizontal-first or vertical-first based on dominant separation.
    """
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    if abs(dx) >= abs(dy):
        corner = (p2[0], p1[1])
    else:
        corner = (p1[0], p2[1])
    if abs(corner[0] - p1[0]) < 1e-6 and abs(corner[1] - p1[1]) < 1e-6:
        return route_straight(p1, p2, width)
    if abs(corner[0] - p2[0]) < 1e-6 and abs(corner[1] - p2[1]) < 1e-6:
        return route_straight(p1, p2, width)
    return _stroke_polygon([p1, corner, p2], width)


def route_L(
    p1: Point,
    p2: Point,
    width: float,
    *,
    corner: Point | None = None,
) -> gdstk.Polygon:
    """
    L-route: two orthogonal legs. ``corner`` fixes the bend; otherwise both
    corner choices are implied by calling code.
    """
    if corner is None:
        raise ValueError("corner is required for route_L")
    return _stroke_polygon([p1, corner, p2], width)


def l_route_corners(p1: Point, p2: Point) -> tuple[Point, Point]:
    """Both orthogonal L-bend corner options between ``p1`` and ``p2``."""
    return (p1[0], p2[1]), (p2[0], p1[1])


def grow_polygon(poly: gdstk.Polygon, margin: float) -> list[gdstk.Polygon]:
    """Outward offset by ``margin`` (µm). Returns empty list if offset fails."""
    if margin <= 0:
        return [poly]
    grown = gdstk.offset(poly, margin)
    return list(grown) if grown else [poly]


def polygons_union(polys: Sequence[gdstk.Polygon]) -> list[gdstk.Polygon]:
    if not polys:
        return []
    acc = [polys[0]]
    for poly in polys[1:]:
        result = gdstk.boolean(acc, poly, "or", precision=1e-3)
        acc = result if result else acc
    return acc


def polygon_inside_region(route: gdstk.Polygon, region: Sequence[gdstk.Polygon]) -> bool:
    """
    True when all ``route`` vertices lie inside the union of ``region`` polygons.

    Uses vertex tests instead of boolean ``not`` so pad-launch endpoints on region
    boundaries are not rejected by numerical slivers.
    """
    if not region:
        return False
    for point in route.points:
        if not any(gdstk.inside([point], poly)[0] for poly in region):
            return False
    return True


def min_spacing(poly_a: gdstk.Polygon, poly_b: gdstk.Polygon) -> float:
    """Minimum boundary separation between two polygons."""
    pa, pb = nearest_points(poly_a, poly_b)
    return math.hypot(pa[0] - pb[0], pa[1] - pb[1])


def min_spacing_to_many(route: gdstk.Polygon, obstacles: Sequence[gdstk.Polygon]) -> float:
    if not obstacles:
        return float("inf")
    return min(min_spacing(route, obs) for obs in obstacles)


def translate_polygon(poly: gdstk.Polygon, dx: float, dy: float) -> gdstk.Polygon:
    return gdstk.Polygon(
        [(x + dx, y + dy) for x, y in poly.points],
        layer=poly.layer,
        datatype=poly.datatype,
    )


def translate_polygons(
    polys: Sequence[gdstk.Polygon], dx: float, dy: float
) -> list[gdstk.Polygon]:
    return [translate_polygon(p, dx, dy) for p in polys]
