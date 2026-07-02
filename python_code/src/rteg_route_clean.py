"""
Step 5.4 — clean routed MTE/MBE polygons after boolean merge and release-hole clearout.

1. **Spike removal** — boolean ``or`` / clearout can leave narrow inward notches
   (the boundary takes a short detour instead of closing along the chord). Drop
   acute tip vertices whose adjacent edges are short.
2. **Keepout arc straightening** — ``BAW_REV`` circle clearout carves circular
   notches into MBE routes; replace those ring-following runs with chord segments.
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
class SpikeCleanConfig:
    """Tunables for removing boolean-merge inward notches on route polygons."""

    max_interior_angle_deg: float = 45.0
    max_spike_edge_um: float = 15.0
    max_spike_height_um: float = 3.0
    acute_interior_angle_deg: float = 25.0
    acute_short_edge_um: float = 2.0
    dedupe_tol_um: float = 0.05
    boolean_precision: float = 1e-3


@dataclass(frozen=True)
class RouteCleanConfig:
    """Tunables for release-hole keepout notch detection on route polygons."""

    layer: int = 2
    datatype: int = 0
    min_arc_vertices: int = 5
    min_clusters: int = 3
    dedupe_tol_um: float = 0.05
    keepout_radius_tol_um: float = 8.0
    min_notch_span_deg: float = 20.0
    max_notch_span_deg: float = 270.0
    max_keepout_radius_um: float = 25.0
    min_smooth_interior_angle_deg: float = 160.0
    min_arc_bow_ratio: float = 1.025
    max_arc_bow_ratio: float = 2.0
    max_smooth_arc_radius_um: float = 40.0
    large_smooth_arc_radius_um: float = 35.0
    large_arc_keepout_tol_um: float = 15.0


@dataclass
class SpikeCleanResult:
    """Per-polygon spike-removal summary."""

    before_vertices: int
    after_vertices: int
    spikes_removed: int


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


def _interior_angle_deg(points: Sequence[Point], index: int) -> float:
    n = len(points)
    p0, p1, p2 = points[(index - 1) % n], points[index], points[(index + 1) % n]
    v1 = (p0[0] - p1[0], p0[1] - p1[1])
    v2 = (p2[0] - p1[0], p2[1] - p1[1])
    l1, l2 = math.hypot(*v1), math.hypot(*v2)
    if l1 < 1e-9 or l2 < 1e-9:
        return 180.0
    cos = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)))
    return math.degrees(math.acos(cos))


def _spike_height_um(points: Sequence[Point], index: int) -> float:
    """Perpendicular distance from ``points[index]`` to the chord at its neighbors."""
    n = len(points)
    ax, ay = points[(index - 1) % n]
    bx, by = points[(index + 1) % n]
    tx, ty = points[index]
    lab = math.hypot(bx - ax, by - ay)
    if lab < 1e-9:
        return 0.0
    return abs((by - ay) * tx - (bx - ax) * ty + bx * ay - by * ax) / lab


def remove_polygon_spikes(
    points: Sequence[Point],
    cfg: SpikeCleanConfig | None = None,
) -> tuple[list[Point], int]:
    """
    Drop acute tip vertices from a route ring — inward boolean notches / spikes.

    Iterates until stable. Each removed vertex is an acute corner where both
    adjacent edges are short, or a very short acute tip.
    """
    cfg = cfg or SpikeCleanConfig()
    pts = _dedupe_vertices(points, cfg.dedupe_tol_um)
    removed = 0
    changed = True
    while changed and len(pts) >= 4:
        changed = False
        n = len(pts)
        drop: set[int] = set()
        for i in range(n):
            ang = _interior_angle_deg(pts, i)
            edge_prev = math.hypot(pts[i][0] - pts[(i - 1) % n][0], pts[i][1] - pts[(i - 1) % n][1])
            edge_next = math.hypot(pts[i][0] - pts[(i + 1) % n][0], pts[i][1] - pts[(i + 1) % n][1])
            height = _spike_height_um(pts, i)
            if (
                ang < cfg.max_interior_angle_deg
                and edge_prev < cfg.max_spike_edge_um
                and edge_next < cfg.max_spike_edge_um
            ):
                drop.add(i)
                continue
            if (
                ang < cfg.acute_interior_angle_deg
                and min(edge_prev, edge_next) < cfg.acute_short_edge_um
            ):
                drop.add(i)
                continue
            if (
                ang < cfg.max_interior_angle_deg
                and height < cfg.max_spike_height_um
                and max(edge_prev, edge_next) < cfg.max_spike_edge_um
            ):
                drop.add(i)
        if drop:
            pts = [pt for j, pt in enumerate(pts) if j not in drop]
            pts = _dedupe_vertices(pts, cfg.dedupe_tol_um)
            removed += len(drop)
            changed = True
    return pts, removed


def clean_route_polygon_spikes(
    poly: gdstk.Polygon,
    cfg: SpikeCleanConfig | None = None,
) -> tuple[gdstk.Polygon, SpikeCleanResult]:
    """Remove inward boolean spikes, then re-heal with a single ``or`` merge."""
    cfg = cfg or SpikeCleanConfig()
    before = len(poly.points)
    pts, removed = remove_polygon_spikes(
        [(float(x), float(y)) for x, y in poly.points],
        cfg,
    )
    out = gdstk.Polygon(pts, layer=poly.layer, datatype=poly.datatype)
    merged = gdstk.boolean([out], [], "or", precision=cfg.boolean_precision)
    if merged:
        best = max(merged, key=lambda p: abs(p.area()))
        out = gdstk.Polygon(
            [(float(x), float(y)) for x, y in best.points],
            layer=poly.layer,
            datatype=poly.datatype,
        )
    return out, SpikeCleanResult(
        before_vertices=before,
        after_vertices=len(out.points),
        spikes_removed=removed,
    )


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


def _path_bow_ratio(seg: Sequence[Point]) -> float:
    """Arc length divided by end-to-end chord — 1.0 is straight, larger is more bowed."""
    if len(seg) < 2:
        return 1.0
    chord = math.hypot(seg[-1][0] - seg[0][0], seg[-1][1] - seg[0][1])
    if chord < 1e-6:
        return float("inf")
    arc = sum(
        math.hypot(seg[i + 1][0] - seg[i][0], seg[i + 1][1] - seg[i][1])
        for i in range(len(seg) - 1)
    )
    return arc / chord


def _mean_fit_radius(seg: Sequence[Point]) -> float:
    """Mean vertex distance to the segment centroid — coarse arc radius estimate."""
    n = len(seg)
    if n == 0:
        return 0.0
    cx = sum(p[0] for p in seg) / n
    cy = sum(p[1] for p in seg) / n
    return sum(math.hypot(p[0] - cx, p[1] - cy) for p in seg) / n


def _max_fit_radius(seg: Sequence[Point]) -> float:
    """Max vertex distance to the segment centroid."""
    n = len(seg)
    if n == 0:
        return 0.0
    cx = sum(p[0] for p in seg) / n
    cy = sum(p[1] for p in seg) / n
    return max(math.hypot(p[0] - cx, p[1] - cy) for p in seg)


def _run_has_keepout_anchor(
    seg: Sequence[Point],
    rev_specs: Sequence[RevCircleSpec],
    clearance_um: float,
    cfg: RouteCleanConfig,
    *,
    tol_um: float | None = None,
) -> bool:
    """True when at least one vertex lies on a ``BAW_REV`` keepout ring."""
    ring_tol = tol_um if tol_um is not None else cfg.keepout_radius_tol_um
    for pt in seg:
        for center, rev_radius in rev_specs:
            zone_r = rev_radius + clearance_um
            if zone_r > cfg.max_keepout_radius_um:
                continue
            if _vertex_on_keepout_ring(pt, center, zone_r, ring_tol):
                return True
    return False


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
    *,
    claimed: list[bool] | None = None,
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

    if claimed is None:
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


def find_smooth_arc_runs(
    points: Sequence[Point],
    cfg: RouteCleanConfig | None = None,
    *,
    claimed: list[bool] | None = None,
    rev_specs: Sequence[RevCircleSpec] | None = None,
    clearance_um: float = MIN_RELEASE_HOLE_CLEARANCE_UM,
) -> list[tuple[int, int]]:
    """
    Return inclusive (start, end) pairs for gently bowed GDS arc vertex runs.

    Catches boolean-merge curve approximations that no longer sit exactly on the
    ``BAW_REV`` keepout ring. Rejects near-straight edges, tight U-bulges, and
    large-radius filler joins via bow ratio and fitted-radius caps.
    """
    cfg = cfg or RouteCleanConfig()
    if len(points) < cfg.min_arc_vertices:
        return []
    if claimed is None:
        claimed = [False] * len(points)

    def _is_smooth_vertex(index: int) -> bool:
        return (
            not claimed[index]
            and _interior_angle_deg(points, index) >= cfg.min_smooth_interior_angle_deg
        )

    runs: list[tuple[int, int]] = []
    i = 0
    while i < len(points):
        if not _is_smooth_vertex(i):
            i += 1
            continue
        j = i
        while j < len(points) and _is_smooth_vertex(j):
            j += 1
        if j - i >= cfg.min_arc_vertices:
            seg = points[i:j]
            bow = _path_bow_ratio(seg)
            fit_r = _mean_fit_radius(seg)
            max_r = _max_fit_radius(seg)
            if not (
                cfg.min_arc_bow_ratio <= bow <= cfg.max_arc_bow_ratio
                and fit_r <= cfg.max_smooth_arc_radius_um
            ):
                i = j
                continue
            if max_r > cfg.large_smooth_arc_radius_um:
                if not rev_specs or not _run_has_keepout_anchor(
                    seg, rev_specs, clearance_um, cfg,
                    tol_um=cfg.large_arc_keepout_tol_um,
                ):
                    i = j
                    continue
            runs.append((i, j - 1))
            for k in range(i, j):
                claimed[k] = True
        i = j

    runs.sort(key=lambda pair: pair[0])
    return _merge_wraparound_runs(points, runs)


def find_arc_runs_to_straighten(
    points: Sequence[Point],
    rev_specs: Sequence[RevCircleSpec],
    clearance_um: float,
    cfg: RouteCleanConfig | None = None,
) -> list[tuple[int, int]]:
    """Keepout-ring notches first, then supplemental smooth-arc runs."""
    cfg = cfg or RouteCleanConfig()
    claimed = [False] * len(points)
    runs = find_release_keepout_notch_runs(
        points, rev_specs, clearance_um, cfg, claimed=claimed,
    )
    runs.extend(
        find_smooth_arc_runs(
            points, cfg, claimed=claimed, rev_specs=rev_specs, clearance_um=clearance_um,
        )
    )
    runs.sort(key=lambda pair: pair[0])
    return runs


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
    runs = find_arc_runs_to_straighten(pts, specs, gap, cfg)
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
    spike_cfg: SpikeCleanConfig | None = None,
) -> tuple[ResonatorRoute, list[ArcStraightenResult], list[SpikeCleanResult]]:
    """Spike removal on all route polygons, then MBE keepout-arc straightening."""
    cfg = cfg or RouteCleanConfig()
    spike_cfg = spike_cfg or SpikeCleanConfig()
    mbe_pair = layermap.pair("BAW_MBE")
    if (cfg.layer, cfg.datatype) != mbe_pair:
        cfg = replace(cfg, layer=mbe_pair[0], datatype=mbe_pair[1])

    circles = list(rev_circles if rev_circles is not None else rev_circle_polys_from_roles(roles))
    gap = clearance_um if clearance_um is not None else _clearance_um_from_roles(roles)

    arc_results: list[ArcStraightenResult] = []
    spike_results: list[SpikeCleanResult] = []

    signal_net = route.signal_net
    if signal_net is not None:
        signal_net, spike_res = clean_route_polygon_spikes(signal_net, spike_cfg)
        spike_results.append(spike_res)
        if (signal_net.layer, signal_net.datatype) == mbe_pair:
            signal_net, arc_res = clean_route_polygon_curves(
                signal_net, cfg, rev_circles=circles, clearance_um=gap,
            )
            arc_results.append(arc_res)

    filler_nets: list[gdstk.Polygon] = []
    for fp in route.filler_nets:
        cleaned, spike_res = clean_route_polygon_spikes(fp, spike_cfg)
        spike_results.append(spike_res)
        if (cleaned.layer, cleaned.datatype) == mbe_pair:
            cleaned, arc_res = clean_route_polygon_curves(
                cleaned, cfg, rev_circles=circles, clearance_um=gap,
            )
            arc_results.append(arc_res)
        filler_nets.append(cleaned)

    cleaned_route = replace(
        route,
        signal_net=signal_net,
        filler_nets=filler_nets,
    )
    return cleaned_route, arc_results, spike_results


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
        cleaned, _, _ = clean_resonator_route(
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
        _, arc_results, spike_results = clean_resonator_route(route, layermap, cfg, roles=roles)
        rows.append(
            {
                "index": route.index,
                "inst_name": route.inst_name,
                "route_polys_cleaned": len(spike_results),
                "spikes_removed": sum(r.spikes_removed for r in spike_results),
                "mbe_polys_arc_cleaned": len(arc_results),
                "notches_found": sum(r.arcs_found for r in arc_results),
                "notches_straightened": sum(r.arcs_straightened for r in arc_results),
                "verts_before": sum(r.before_vertices for r in spike_results),
                "verts_after": sum(r.after_vertices for r in spike_results),
            }
        )
    return rows


__all__ = [
    "ArcStraightenResult",
    "RouteCleanConfig",
    "RevCircleSpec",
    "SpikeCleanConfig",
    "SpikeCleanResult",
    "clean_all_routes",
    "clean_resonator_route",
    "clean_route_polygon_curves",
    "clean_route_polygon_spikes",
    "find_arc_runs_to_straighten",
    "find_release_keepout_notch_runs",
    "find_smooth_arc_runs",
    "remove_polygon_spikes",
    "rev_circle_specs",
    "route_clean_overview_rows",
    "straighten_arc_run",
]
