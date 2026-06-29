"""
Step 5.4 — straighten release-hole keepout curves on routed MBE (2/0) polygons.

``BAW_REV`` circle clearout (step 5.3) carves circular notches into MBE routes
using a grown keepout ring (hole radius + PDK6 clearance). Boolean / offset ops
leave GDS arc approximations along that ring. This module finds only those
keepout-boundary runs and replaces each with three chord segments.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace

import gdstk

from layermap import LayerMap
from prep_resonator_ppd import MIN_RELEASE_HOLE_CLEARANCE_UM
from rteg_route_new import ResonatorRoute, rev_circle_polys_from_roles

Point = tuple[float, float]
RevCircleSpec = tuple[Point, float]  # (center, radius)


@dataclass(frozen=True)
class RouteCleanConfig:
    """Tunables for release-hole keepout notch detection on route polygons."""

    layer: int = 2
    datatype: int = 0
    min_arc_vertices: int = 5
    min_clusters: int = 3
    dedupe_tol_um: float = 0.05
    keepout_radius_tol_um: float = 5.0
    min_notch_span_deg: float = 20.0
    max_notch_span_deg: float = 270.0
    max_keepout_radius_um: float = 25.0


@dataclass
class ArcStraightenResult:
    """Per-polygon cleanup summary."""

    before_vertices: int
    after_vertices: int
    arcs_found: int
    arcs_straightened: int


def _dedupe_vertices(points: Sequence[Point], tol_um: float) -> list[Point]:
    if not points:
        return []
    out: list[Point] = [(float(points[0][0]), float(points[0][1]))]
    for x, y in points[1:]:
        px, py = out[-1]
        if math.hypot(x - px, y - py) > tol_um:
            out.append((float(x), float(y)))
    if len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= tol_um:
        out[-1] = out[0]
    return out


def rev_circle_specs(circle_polys: Sequence[gdstk.Polygon]) -> list[RevCircleSpec]:
    """(center, radius) for each ``BAW_REV`` release-hole circle outline."""
    specs: list[RevCircleSpec] = []
    for poly in circle_polys:
        bb = poly.bounding_box()
        if bb is None:
            continue
        (x0, y0), (x1, y1) = bb
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        pts = poly.points
        if len(pts) == 0:
            continue
        radius = sum(math.hypot(x - cx, y - cy) for x, y in pts) / len(pts)
        specs.append(((cx, cy), radius))
    return specs


def _vertex_on_keepout_ring(
    pt: Point,
    center: Point,
    zone_radius_um: float,
    tol_um: float,
) -> bool:
    dist = math.hypot(pt[0] - center[0], pt[1] - center[1])
    return abs(dist - zone_radius_um) <= tol_um


def _arc_span_deg(seg: Sequence[Point], center: Point) -> float:
    """Angular span covered by ``seg`` around ``center`` (degrees)."""
    cx, cy = center
    angles = sorted(math.atan2(y - cy, x - cx) for x, y in seg)
    if len(angles) < 2:
        return 0.0
    max_gap = max(angles[i + 1] - angles[i] for i in range(len(angles) - 1))
    max_gap = max(max_gap, angles[0] + 2.0 * math.pi - angles[-1])
    return math.degrees(2.0 * math.pi - max_gap)


def _merge_wraparound_runs(
    points: Sequence[Point],
    runs: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Merge a keepout run at index 0 with one ending at the polygon tail."""
    if len(runs) < 2 or not points:
        return runs
    first_a, _ = runs[0]
    _, last_b = runs[-1]
    if first_a == 0 and last_b == len(points) - 1:
        merged = [(0, last_b)] + runs[1:-1]
        return merged
    return runs


def find_release_keepout_notch_runs(
    points: Sequence[Point],
    rev_specs: Sequence[RevCircleSpec],
    clearance_um: float,
    cfg: RouteCleanConfig | None = None,
) -> list[tuple[int, int]]:
    """
    Return inclusive (start, end) pairs for vertices on a ``BAW_REV`` keepout ring.

    Only matches arcs carved by the release-hole clearout (vertices lying on the
    grown circle at ``rev_radius + clearance_um`` around each hole center).
    Semicircular notches and partial keepout arcs are kept; full-ring filler joins
    are rejected by the angular-span cap.
    """
    cfg = cfg or RouteCleanConfig()
    if len(points) < cfg.min_arc_vertices or not rev_specs:
        return []

    claimed = [False] * len(points)
    runs: list[tuple[int, int]] = []

    for center, rev_radius in rev_specs:
        zone_r = rev_radius + clearance_um
        if zone_r > cfg.max_keepout_radius_um:
            continue
        on_ring = [
            (
                not claimed[i]
                and _vertex_on_keepout_ring(
                    points[i], center, zone_r, cfg.keepout_radius_tol_um,
                )
            )
            for i in range(len(points))
        ]
        i = 0
        while i < len(points):
            if not on_ring[i]:
                i += 1
                continue
            j = i
            while j < len(points) and on_ring[j]:
                j += 1
            if j - i >= cfg.min_arc_vertices:
                seg = points[i:j]
                span = _arc_span_deg(seg, center)
                if cfg.min_notch_span_deg <= span <= cfg.max_notch_span_deg:
                    runs.append((i, j - 1))
                    for k in range(i, j):
                        claimed[k] = True
            i = j

    runs.sort(key=lambda pair: pair[0])
    return _merge_wraparound_runs(points, runs)


def _cluster_chord_points(
    seg: Sequence[Point],
    n_clusters: int,
) -> list[Point]:
    """Split ``seg`` into ``n_clusters`` groups; keep only cluster endpoints."""
    if len(seg) < 2:
        return list(seg)
    n_clusters = max(3, n_clusters)
    if len(seg) <= n_clusters:
        return [seg[0], seg[-1]]
    out = [seg[0]]
    base = len(seg) // n_clusters
    rem = len(seg) % n_clusters
    idx = 0
    for cluster_idx in range(n_clusters):
        size = base + (1 if cluster_idx < rem else 0)
        idx += size
        if cluster_idx == n_clusters - 1:
            out.append(seg[-1])
        else:
            out.append(seg[min(idx, len(seg) - 1)])
    compact: list[Point] = [out[0]]
    for pt in out[1:]:
        if math.hypot(pt[0] - compact[-1][0], pt[1] - compact[-1][1]) > 1e-6:
            compact.append(pt)
    return compact


def straighten_arc_run(
    points: Sequence[Point],
    start: int,
    end: int,
    *,
    n_clusters: int = 3,
) -> list[Point]:
    """Replace one arc run with chord endpoints (``n_clusters`` line segments)."""
    seg = points[start : end + 1]
    chord_pts = _cluster_chord_points(seg, n_clusters)
    return [*points[:start], *chord_pts, *points[end + 1 :]]


def _clearance_um_from_roles(roles: object | None) -> float:
    if roles is None:
        return MIN_RELEASE_HOLE_CLEARANCE_UM
    rev_role = getattr(roles, "rev_release_circles", None)
    if rev_role is not None:
        return float(rev_role.clearance_um)
    return MIN_RELEASE_HOLE_CLEARANCE_UM


def clean_route_polygon_curves(
    poly: gdstk.Polygon,
    cfg: RouteCleanConfig | None = None,
    *,
    rev_circles: Sequence[gdstk.Polygon] | None = None,
    clearance_um: float | None = None,
) -> tuple[gdstk.Polygon, ArcStraightenResult]:
    """Straighten release-hole keepout arcs on one MBE polygon."""
    cfg = cfg or RouteCleanConfig()
    if (poly.layer, poly.datatype) != (cfg.layer, cfg.datatype):
        return poly, ArcStraightenResult(len(poly.points), len(poly.points), 0, 0)
    if not rev_circles:
        return poly, ArcStraightenResult(len(poly.points), len(poly.points), 0, 0)

    pts = _dedupe_vertices(
        [(float(x), float(y)) for x, y in poly.points],
        cfg.dedupe_tol_um,
    )
    before = len(pts)
    specs = rev_circle_specs(rev_circles)
    gap = clearance_um if clearance_um is not None else MIN_RELEASE_HOLE_CLEARANCE_UM
    runs = find_release_keepout_notch_runs(pts, specs, gap, cfg)
    straightened = 0
    for start, end in reversed(runs):
        if end - start + 1 < cfg.min_clusters * 2:
            continue
        pts = straighten_arc_run(
            pts, start, end, n_clusters=cfg.min_clusters,
        )
        straightened += 1

    out = gdstk.Polygon(pts, layer=poly.layer, datatype=poly.datatype)
    return out, ArcStraightenResult(
        before_vertices=before,
        after_vertices=len(pts),
        arcs_found=len(runs),
        arcs_straightened=straightened,
    )


def clean_resonator_route(
    route: ResonatorRoute,
    layermap: LayerMap,
    cfg: RouteCleanConfig | None = None,
    *,
    roles: object | None = None,
    rev_circles: Sequence[gdstk.Polygon] | None = None,
    clearance_um: float | None = None,
) -> tuple[ResonatorRoute, list[ArcStraightenResult]]:
    """Apply release-hole keepout curve cleanup to MBE route polygons."""
    cfg = cfg or RouteCleanConfig()
    mbe_pair = layermap.pair("BAW_MBE")
    if (cfg.layer, cfg.datatype) != mbe_pair:
        cfg = replace(cfg, layer=mbe_pair[0], datatype=mbe_pair[1])

    circles = list(rev_circles if rev_circles is not None else rev_circle_polys_from_roles(roles))
    gap = clearance_um if clearance_um is not None else _clearance_um_from_roles(roles)

    results: list[ArcStraightenResult] = []
    signal_net = route.signal_net
    if signal_net is not None and (signal_net.layer, signal_net.datatype) == mbe_pair:
        signal_net, res = clean_route_polygon_curves(
            signal_net, cfg, rev_circles=circles, clearance_um=gap,
        )
        results.append(res)

    filler_nets: list[gdstk.Polygon] = []
    for fp in route.filler_nets:
        if (fp.layer, fp.datatype) != mbe_pair:
            filler_nets.append(fp)
            continue
        cleaned, res = clean_route_polygon_curves(
            fp, cfg, rev_circles=circles, clearance_um=gap,
        )
        filler_nets.append(cleaned)
        results.append(res)

    cleaned_route = replace(
        route,
        signal_net=signal_net,
        filler_nets=filler_nets,
    )
    return cleaned_route, results


def clean_all_routes(
    routes: dict[int, ResonatorRoute],
    layermap: LayerMap,
    *,
    roles_by_index: dict[int, object] | None = None,
    indices: Sequence[int] | None = None,
    cfg: RouteCleanConfig | None = None,
) -> dict[int, ResonatorRoute]:
    """Clean release-hole keepout curves on every route (or a subset of indices)."""
    keys = indices if indices is not None else sorted(routes)
    out = dict(routes)
    for idx in keys:
        if idx not in routes:
            continue
        roles = roles_by_index.get(idx) if roles_by_index else None
        cleaned, _ = clean_resonator_route(
            routes[idx], layermap, cfg, roles=roles,
        )
        out[idx] = cleaned
    return out


def route_clean_overview_rows(
    routes: dict[int, ResonatorRoute],
    layermap: LayerMap,
    *,
    roles_by_index: dict[int, object] | None = None,
    cfg: RouteCleanConfig | None = None,
) -> list[dict[str, object]]:
    """Rows for a pandas DataFrame — cleanup stats without mutating routes."""
    rows: list[dict[str, object]] = []
    for idx in sorted(routes):
        route = routes[idx]
        roles = roles_by_index.get(idx) if roles_by_index else None
        _, results = clean_resonator_route(route, layermap, cfg, roles=roles)
        rows.append(
            {
                "index": route.index,
                "inst_name": route.inst_name,
                "mbe_polys_cleaned": len(results),
                "notches_found": sum(r.arcs_found for r in results),
                "notches_straightened": sum(r.arcs_straightened for r in results),
                "verts_before": sum(r.before_vertices for r in results),
                "verts_after": sum(r.after_vertices for r in results),
            }
        )
    return rows


__all__ = [
    "ArcStraightenResult",
    "RouteCleanConfig",
    "RevCircleSpec",
    "clean_all_routes",
    "clean_resonator_route",
    "clean_route_polygon_curves",
    "find_release_keepout_notch_runs",
    "rev_circle_specs",
    "route_clean_overview_rows",
    "straighten_arc_run",
]
