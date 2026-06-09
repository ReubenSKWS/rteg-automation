"""
Geometry helpers for routing: flatten cells to world-space polygons, select by
layer (via layermap), grow/shrink, boolean ops, a routable-region builder,
simple connector generation, connectivity-aware net building, and golden
overlap-area metrics.

These wrap gdstk.boolean / gdstk.offset so the router reads at the level of
layout intent ("subtract the resonator clearance from the ground region")
rather than gdstk call mechanics. Boolean failures are caught and surfaced
rather than crashing the pipeline.
"""
from __future__ import annotations

import math

import gdstk

from layermap import LayerMap


def flatten_cell(cell: gdstk.Cell) -> list[gdstk.Polygon]:
    """All polygons in world coordinates, expanding every reference."""
    return list(cell.get_polygons())


def polygons_on_layer(
    polygons: list[gdstk.Polygon], layermap: LayerMap, name: str
) -> list[gdstk.Polygon]:
    """Subset of polygons whose (layer, datatype) matches a named layer."""
    if name not in layermap:
        return []
    pair = layermap.pair(name)
    return [p for p in polygons if (p.layer, p.datatype) == pair]


def grow(
    polygons: list[gdstk.Polygon], margin: float, layer: int = 0, datatype: int = 0
) -> list[gdstk.Polygon]:
    """Offset polygons outward by ``margin`` (shrink if negative)."""
    if not polygons:
        return []
    result = gdstk.offset(polygons, margin, layer=layer, datatype=datatype)
    return result


def subtract(
    a: list[gdstk.Polygon], b: list[gdstk.Polygon], layer: int = 0, datatype: int = 0
) -> list[gdstk.Polygon]:
    """Polygons in A not covered by B (gdstk boolean 'not')."""
    if not a:
        return []
    if not b:
        return list(a)
    return gdstk.boolean(a, b, "not", layer=layer, datatype=datatype)


def intersect(
    a: list[gdstk.Polygon], b: list[gdstk.Polygon], layer: int = 0, datatype: int = 0
) -> list[gdstk.Polygon]:
    """Overlap of A and B (gdstk boolean 'and')."""
    if not a or not b:
        return []
    return gdstk.boolean(a, b, "and", layer=layer, datatype=datatype)


def union(
    polygons: list[gdstk.Polygon], layer: int = 0, datatype: int = 0
) -> list[gdstk.Polygon]:
    """Merge overlapping polygons into one net (gdstk boolean 'or')."""
    if not polygons:
        return []
    return gdstk.boolean(polygons, [], "or", layer=layer, datatype=datatype)


def bbox_of(polygons: list[gdstk.Polygon]):
    """Combined (min, max) bounding box of polygons, or None if empty."""
    boxes = [p.bounding_box() for p in polygons if p.bounding_box() is not None]
    if not boxes:
        return None
    x0 = min(b[0][0] for b in boxes)
    y0 = min(b[0][1] for b in boxes)
    x1 = max(b[1][0] for b in boxes)
    y1 = max(b[1][1] for b in boxes)
    return (x0, y0), (x1, y1)


def rectangle(
    bbox, layer: int = 0, datatype: int = 0
) -> gdstk.Polygon:
    """Axis-aligned rectangle polygon from a ((x0,y0),(x1,y1)) bbox."""
    (x0, y0), (x1, y1) = bbox
    return gdstk.rectangle((x0, y0), (x1, y1), layer=layer, datatype=datatype)


def total_area(polygons: list[gdstk.Polygon]) -> float:
    """Sum of polygon areas (union first to avoid double-counting overlap)."""
    if not polygons:
        return 0.0
    merged = union(polygons)
    return sum(p.area() for p in merged)


def drc_spacing_violation(
    net_a: list[gdstk.Polygon],
    net_b: list[gdstk.Polygon],
    min_spacing: float,
) -> list[gdstk.Polygon]:
    """
    Coarse spacing check between two unconnected nets.

    Grows A by half the minimum spacing and intersects with B grown by half.
    A non-empty result means the two nets are closer than ``min_spacing``.
    Returns the violating overlap polygons (empty list = clean).
    """
    if not net_a or not net_b:
        return []
    half = min_spacing / 2.0
    grown_a = grow(net_a, half)
    grown_b = grow(net_b, half)
    return intersect(grown_a, grown_b)


# --- Coordinate transforms ---------------------------------------------------

def transform_polygons(
    polygons: list[gdstk.Polygon],
    origin: tuple[float, float] = (0.0, 0.0),
    rotation: float = 0.0,
    x_reflection: bool = False,
) -> list[gdstk.Polygon]:
    """Apply a reference transform (reflect, rotate, translate) to polygons."""
    dx, dy = origin
    cos_r, sin_r = math.cos(rotation), math.sin(rotation)
    out: list[gdstk.Polygon] = []
    for poly in polygons:
        pts = []
        for x, y in poly.points:
            if x_reflection:
                y = -y
            xr = x * cos_r - y * sin_r + dx
            yr = x * sin_r + y * cos_r + dy
            pts.append((xr, yr))
        out.append(gdstk.Polygon(pts, layer=poly.layer, datatype=poly.datatype))
    return out


# --- Routable region ---------------------------------------------------------

def compute_routable_region(
    frame_interior: list[gdstk.Polygon],
    resonator_body: list[gdstk.Polygon],
    release_holes: list[gdstk.Polygon],
    other_net_metal: list[gdstk.Polygon],
    resonator_clearance: float,
    release_clearance: float,
    safety_margin: float,
) -> list[gdstk.Polygon]:
    """
    Region a signal route may occupy and stay DRC-clean by construction:

        routable = frame_interior
                 - grow(resonator_body, resonator_clearance)
                 - grow(release_holes, release_clearance)
                 - grow(other_net_metal, safety_margin)
    """
    region = list(frame_interior)
    if resonator_body:
        region = subtract(region, grow(resonator_body, resonator_clearance))
    if release_holes:
        region = subtract(region, grow(release_holes, release_clearance))
    if other_net_metal:
        region = subtract(region, grow(other_net_metal, safety_margin))
    return region


def path_inside_routable(
    path_polys: list[gdstk.Polygon],
    routable: list[gdstk.Polygon],
    tolerance_area: float = 1.0,
) -> bool:
    """True if the fattened path lies inside routable (allowing sliver error)."""
    if not path_polys:
        return False
    if not routable:
        return False
    outside = subtract(path_polys, routable)
    return total_area(outside) <= tolerance_area


# --- Minimum-distance point pair --------------------------------------------

def _seg_point_closest(
    a: tuple[float, float], b: tuple[float, float], p: tuple[float, float]
) -> tuple[float, float]:
    """Closest point on segment a-b to point p."""
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return a
    t = ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return (ax + t * dx, ay + t * dy)


def _edges(poly: gdstk.Polygon):
    pts = [tuple(pt) for pt in poly.points]
    for i in range(len(pts)):
        yield pts[i], pts[(i + 1) % len(pts)]


def min_distance_point_pair(
    polys_a: list[gdstk.Polygon], polys_b: list[gdstk.Polygon]
) -> tuple[tuple[float, float], tuple[float, float], float]:
    """
    Closest point pair between two polygon sets (point on A, point on B, dist).

    Compares every edge-vertex combination both directions; adequate for the
    small polygon counts in a single RTEG.
    """
    best = (None, None, float("inf"))
    for pa in polys_a:
        a_pts = [tuple(pt) for pt in pa.points]
        for pb in polys_b:
            for e0, e1 in _edges(pb):
                for v in a_pts:
                    c = _seg_point_closest(e0, e1, v)
                    d = (c[0] - v[0]) ** 2 + (c[1] - v[1]) ** 2
                    if d < best[2]:
                        best = (v, c, d)
            b_pts = [tuple(pt) for pt in pb.points]
            for e0, e1 in _edges(pa):
                for v in b_pts:
                    c = _seg_point_closest(e0, e1, v)
                    d = (c[0] - v[0]) ** 2 + (c[1] - v[1]) ** 2
                    if d < best[2]:
                        best = (c, v, d)
    pa_pt, pb_pt, dsq = best
    return pa_pt, pb_pt, (dsq ** 0.5 if dsq != float("inf") else float("inf"))


# --- Simple connectors -------------------------------------------------------

def _flexpath_polys(
    centerline: list[tuple[float, float]], width: float
) -> list[gdstk.Polygon]:
    return gdstk.FlexPath(centerline, width, layer=0, datatype=0).to_polygons()


def _chamfered_l(
    start: tuple[float, float],
    corner: tuple[float, float],
    end: tuple[float, float],
    chamfer: float,
) -> list[tuple[float, float]]:
    """L centerline with the 90-degree corner replaced by a 45-degree chamfer."""
    def _pull(frm, twd, dist):
        vx, vy = twd[0] - frm[0], twd[1] - frm[1]
        length = math.hypot(vx, vy)
        if length == 0:
            return frm
        f = min(dist, length / 2.0) / length
        return (frm[0] + vx * f, frm[1] + vy * f)

    c_in = _pull(corner, start, chamfer)
    c_out = _pull(corner, end, chamfer)
    return [start, c_in, c_out, end]


def connector_candidates(
    start: tuple[float, float],
    end: tuple[float, float],
    chamfer: float,
) -> list[tuple[str, list[tuple[float, float]]]]:
    """Ordered (kind, centerline) candidates: straight, then two chamfered Ls."""
    candidates: list[tuple[str, list[tuple[float, float]]]] = [
        ("straight", [start, end])
    ]
    corner_h = (end[0], start[1])
    corner_v = (start[0], end[1])
    if corner_h != start and corner_h != end:
        candidates.append(("L-bend-h", _chamfered_l(start, corner_h, end, chamfer)))
    if corner_v != start and corner_v != end:
        candidates.append(("L-bend-v", _chamfered_l(start, corner_v, end, chamfer)))
    return candidates


def try_connectors(
    start: tuple[float, float],
    end: tuple[float, float],
    width: float,
    routable: list[gdstk.Polygon],
    chamfer: float | None = None,
) -> tuple[list[gdstk.Polygon] | None, str]:
    """
    Return (fattened_polys, kind) for the first candidate that stays inside
    routable, else (None, reason). Tries straight, then one L-bend each way.
    """
    chamfer = chamfer if chamfer is not None else width
    for kind, centerline in connector_candidates(start, end, chamfer):
        polys = _flexpath_polys(centerline, width)
        if path_inside_routable(polys, routable):
            return polys, kind
    return None, "no straight/single-bend connector stays inside routable region"


# --- Connectivity-aware nets -------------------------------------------------

class _DisjointSet:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        ri, rj = self.find(i), self.find(j)
        if ri != rj:
            self.parent[ri] = rj


def build_nets(
    polygons: list[gdstk.Polygon],
    bridge_bbox=None,
    bridge_margin: float = 0.0,
) -> list[list[gdstk.Polygon]]:
    """
    Group polygons into connected nets. Two polygons join when they overlap;
    additionally, any two polygons that both touch the bridge region (the
    resonator body) join, so metal connected *through* the resonator counts as
    one net. Returns a list of polygon groups.
    """
    n = len(polygons)
    if n == 0:
        return []
    ds = _DisjointSet(n)

    bridge_rect = None
    if bridge_bbox is not None:
        (x0, y0), (x1, y1) = bridge_bbox
        bridge_rect = gdstk.rectangle(
            (x0 - bridge_margin, y0 - bridge_margin),
            (x1 + bridge_margin, y1 + bridge_margin),
        )
    touches_bridge = [False] * n
    if bridge_rect is not None:
        for i, p in enumerate(polygons):
            touches_bridge[i] = bool(intersect([p], [bridge_rect]))

    for i in range(n):
        for j in range(i + 1, n):
            if intersect([polygons[i]], [polygons[j]]):
                ds.union(i, j)
            elif touches_bridge[i] and touches_bridge[j]:
                ds.union(i, j)

    groups: dict[int, list[gdstk.Polygon]] = {}
    for i, p in enumerate(polygons):
        groups.setdefault(ds.find(i), []).append(p)
    return list(groups.values())


def drc_violations_between_nets(
    nets: list[list[gdstk.Polygon]], min_spacing: float
) -> list[gdstk.Polygon]:
    """Spacing violations only BETWEEN different nets (same-net pairs ignored)."""
    violations: list[gdstk.Polygon] = []
    for a in range(len(nets)):
        for b in range(a + 1, len(nets)):
            violations.extend(
                drc_spacing_violation(nets[a], nets[b], min_spacing)
            )
    return violations


# --- Golden overlap metrics --------------------------------------------------

def layer_overlap_metrics(
    golden_polys: list[gdstk.Polygon], routed_polys: list[gdstk.Polygon]
) -> dict:
    """
    Area-based comparison of one layer between golden and routed output:
    intersection area, each side's area, overlap fraction of golden, and
    symmetric-difference area.
    """
    g_union = union(golden_polys) if golden_polys else []
    r_union = union(routed_polys) if routed_polys else []
    g_area = sum(p.area() for p in g_union)
    r_area = sum(p.area() for p in r_union)

    inter = intersect(g_union, r_union) if g_union and r_union else []
    i_area = sum(p.area() for p in inter)

    if g_union and r_union:
        symdiff = gdstk.boolean(g_union, r_union, "xor")
        s_area = sum(p.area() for p in symdiff)
    else:
        s_area = g_area + r_area

    return {
        "golden_area": g_area,
        "routed_area": r_area,
        "intersection_area": i_area,
        "overlap_fraction_of_golden": (i_area / g_area) if g_area else 0.0,
        "symmetric_difference_area": s_area,
    }


# --- Golden layer allow-list (standalone GSG trim) ---------------------------


def golden_layer_pairs(golden_path: str | Path) -> set[tuple[int, int]]:
    """
    Return the set of (layer, datatype) pairs present in a golden GDS top cell.
    Used as the v1 golden-derived allow-list (NOT a general RTEG-layer spec).
    """
    from pathlib import Path as _Path

    lib = gdstk.read_gds(str(_Path(golden_path)))
    tops = lib.top_level()
    top = tops[0] if tops else lib.cells[0]
    return {(p.layer, p.datatype) for p in top.get_polygons()}


def filter_cell_layers_inplace(
    cell: gdstk.Cell, allowed: set[tuple[int, int]]
) -> int:
    """
    Drop geometry whose (layer, datatype) is not in ``allowed``. Handles polygons,
    paths, flexpaths, and labels. References are untouched so frame pad3 refs
    and their launch metal survive for routing. Returns items removed.
    """
    removed = 0
    for poly in list(cell.polygons):
        if (poly.layer, poly.datatype) not in allowed:
            cell.remove(poly)
            removed += 1
    for path in list(cell.paths):
        pairs = set(zip(path.layers, path.datatypes))
        if not pairs.issubset(allowed):
            cell.remove(path)
            removed += 1
    for fpath in list(getattr(cell, "flexpaths", ())):
        pairs = set(zip(fpath.layers, fpath.datatypes))
        if not pairs.issubset(allowed):
            cell.remove(fpath)
            removed += 1
    for label in list(cell.labels):
        pair = (label.layer, label.texttype)
        if pair not in allowed:
            cell.remove(label)
            removed += 1
    return removed
