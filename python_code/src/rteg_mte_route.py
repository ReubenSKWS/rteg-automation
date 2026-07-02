"""
Step 5.4 — MTE pad routing for center-pad targets.

When ``mte_route_target == "center_pad"``, build ``mteConn`` from the signal
pad top-right / bottom-right corners to the junction where the filter MTE
extension meets the MTE collar, then boolean-merge route + extension stub
(never the collar — collar stays a separate polygon).
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

import gdstk

from layermap import LayerMap
from rteg_classify import NodeClassification
from rteg_collect import (
    RtegGeometryRoles,
    TaggedPolygon,
    polys_associated,
    polys_touch,
    preserved_mte_overlap_with_body,
)
from rteg_mte_extensions import (
    CollarExtensionDraw,
    MteBuildConfig,
    MteExtensionResult,
    _associated_edge_collars_from_pieces,
    _body_centroid,
    _edge_length,
    _edge_outward_normal,
    _edge_points,
    _is_stadium_collar,
    _skill_pad_vtb_corners,
    select_extension_collar_from_pieces,
)
from rteg_utils import assign_layer, polys_bbox

Point = tuple[float, float]
Bbox = tuple[tuple[float, float], tuple[float, float]]
Edge = tuple[Point, Point]


@dataclass(frozen=True)
class MteRouteConfig:
    """Tunable parameters for step 5.4 pad stretch routing."""

    mte_layer: str = "BAW_MTE"
    pad_touch_overlap_um: float = 0.5
    junction_merge_inset_um: float = 0.5
    collar_merge_inset_um: float = 4.0
    min_pad_overlap_um2: float = 0.01
    min_mouth_span_fraction: float = 0.5
    boolean_precision: float = 1e-3
    boundary_tolerance_um: float = 0.15
    inside_probe_half_um: float = 0.25
    skill_pad_expand_um: float = 5.0


@dataclass(frozen=True)
class RouteStart:
    """Attach point on the pad-facing edge of the preserved MTE interconnect."""

    center: Point
    width_um: float
    outer_edge: Edge


@dataclass(frozen=True)
class PadAttachmentEdge:
    """Pad bbox edge corners shifted inward for overlap."""

    corner_low: Point
    corner_high: Point
    inward_normal: tuple[float, float]
    pad_entry: Point
    span_um: float


@dataclass(frozen=True)
class PreservedMteParts:
    """Filter MTE collar + extension stub already on the RTEG frame."""

    collar: gdstk.Polygon | None
    extension: gdstk.Polygon
    merge_polys: tuple[gdstk.Polygon, ...]
    """Extension stub(s) only — pad routes boolean-merge with these, never the collar."""


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

    When the preserved interconnect extrudes away from the route target, use the
    collar-mouth edge as the pad-facing reference instead.
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


def _facing_pad_edge(
    bbox: Bbox,
    from_point: Point,
) -> tuple[Point, Point, tuple[float, float]]:
    """Return both corners of the pad bbox edge that faces ``from_point``."""
    (x0, y0), (x1, y1) = bbox
    fx, fy = from_point
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    dx, dy = fx - cx, fy - cy

    if abs(dx) >= abs(dy):
        if dx >= 0.0:
            return ((x1, y0), (x1, y1), (-1.0, 0.0))
        return ((x0, y0), (x0, y1), (1.0, 0.0))
    if dy >= 0.0:
        return ((x0, y1), (x1, y1), (0.0, -1.0))
    return ((x0, y0), (x1, y0), (0.0, 1.0))


def pick_pad_attachment_edge(
    signal_polys: Sequence[gdstk.Polygon],
    from_point: Point,
    *,
    touch_overlap_um: float,
) -> PadAttachmentEdge:
    """
    Both corners of the signal-pad edge nearest ``from_point``, shifted
    ``touch_overlap_um`` inward so the stretched extension overlaps the pad.
    """
    bbox = _union_pad_bbox(signal_polys)
    if bbox is None:
        raise ValueError("signal pad has no geometry")

    corner_low, corner_high, inward = _facing_pad_edge(bbox, from_point)
    ix, iy = inward
    corner_low = (
        corner_low[0] + ix * touch_overlap_um,
        corner_low[1] + iy * touch_overlap_um,
    )
    corner_high = (
        corner_high[0] + ix * touch_overlap_um,
        corner_high[1] + iy * touch_overlap_um,
    )
    pad_entry = (
        (corner_low[0] + corner_high[0]) / 2.0,
        (corner_low[1] + corner_high[1]) / 2.0,
    )
    return PadAttachmentEdge(
        corner_low=corner_low,
        corner_high=corner_high,
        inward_normal=inward,
        pad_entry=pad_entry,
        span_um=_dist(corner_low, corner_high),
    )


def _outer_vertices(draw: CollarExtensionDraw) -> tuple[Point, Point]:
    """Return ``(outer_b, outer_a)`` matching ``draw_lip_extension`` vertex order."""
    return draw.outer_edge[0], draw.outer_edge[1]


def _collar_intercepts(draw: CollarExtensionDraw) -> tuple[Point, Point]:
    """Legacy SKILL slope intercepts (used by keepout helpers only)."""
    hi = draw.collar_intercept_a
    lo = draw.collar_intercept_b
    if hi == (0.0, 0.0) and lo == (0.0, 0.0):
        hi, lo = draw.intercept_a, draw.intercept_b
    if hi[1] < lo[1] or (abs(hi[1] - lo[1]) < 1e-6 and hi[0] < lo[0]):
        hi, lo = lo, hi
    return hi, lo


def _order_attach_corners(p0: Point, p1: Point) -> tuple[Point, Point]:
    """Return ``(mte_up, mte_dn)`` with higher Y first; tie-break on X."""
    if p0[1] > p1[1] + 1e-9:
        return p0, p1
    if p1[1] > p0[1] + 1e-9:
        return p1, p0
    if p0[0] >= p1[0]:
        return p0, p1
    return p1, p0


def _point_on_polygon_boundary(
    point: Point,
    poly: gdstk.Polygon,
    tol_um: float,
) -> bool:
    pts = [(float(p[0]), float(p[1])) for p in poly.points]
    n = len(pts)
    px, py = point
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        length_sq = dx * dx + dy * dy
        if length_sq < 1e-18:
            if math.hypot(px - x0, py - y0) <= tol_um:
                return True
            continue
        t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / length_sq))
        qx, qy = x0 + t * dx, y0 + t * dy
        if math.hypot(px - qx, py - qy) <= tol_um:
            return True
    return False


def _dedupe_points(points: Sequence[Point], tol_um: float) -> list[Point]:
    unique: list[Point] = []
    for pt in points:
        if not any(math.hypot(pt[0] - q[0], pt[1] - q[1]) <= tol_um for q in unique):
            unique.append(pt)
    return unique


def _farthest_pair(points: Sequence[Point]) -> tuple[Point, Point]:
    if len(points) < 2:
        raise ValueError("need at least two points for junction corners")
    best_a, best_b = points[0], points[1]
    best_len = _dist(best_a, best_b)
    for i, a in enumerate(points):
        for b in points[i + 1 :]:
            length = _dist(a, b)
            if length > best_len:
                best_len = length
                best_a, best_b = a, b
    return best_a, best_b


def identify_preserved_mte_parts(
    preserved_mte_polys: Sequence[gdstk.Polygon],
    body_mte_polys: Sequence[gdstk.Polygon],
    *,
    mte_build_cfg: MteBuildConfig | None = None,
    boolean_precision: float = 1e-3,
) -> PreservedMteParts:
    """
    Split frame MTE into the resonator-mouth collar and the interconnect extension.

    The extension is the stub selected by step 5.3. The collar is the stadium
    shell it touches when present, otherwise ``None`` (junction falls back to
    resonator-body overlap on the extension).
    """
    cfg = mte_build_cfg or MteBuildConfig()
    if not preserved_mte_polys:
        raise ValueError("no preserved MTE polygons on frame")

    tagged = [
        TaggedPolygon(f"preserved_mte[{i}]", cfg.mte_layer, poly)
        for i, poly in enumerate(preserved_mte_polys)
    ]
    ext_tp = select_extension_collar_from_pieces(
        tagged,
        body_mte_polys,
        preserved_mte_overlap_with_body,
        cfg,
    )
    if ext_tp is None:
        raise ValueError("no preserved MTE extension on frame")
    extension = ext_tp.polygon

    stadiums = [tp for tp in tagged if _is_stadium_collar(tp.polygon, cfg)]
    associated = _associated_edge_collars_from_pieces(tagged, cfg)
    collar_poly: gdstk.Polygon | None = None

    if associated:
        extension = associated[0].polygon
        for stadium in stadiums:
            if polys_touch(
                stadium.polygon,
                extension,
                precision=boolean_precision,
                min_overlap_um2=0.01,
            ):
                collar_poly = stadium.polygon
                break

    if collar_poly is None and stadiums:
        for stadium in stadiums:
            for tp in tagged:
                if _polygon_key(tp.polygon) == _polygon_key(stadium.polygon):
                    continue
                if polys_touch(
                    tp.polygon,
                    stadium.polygon,
                    precision=boolean_precision,
                    min_overlap_um2=0.01,
                ):
                    collar_poly = stadium.polygon
                    extension = tp.polygon
                    break
            if collar_poly is not None:
                break

    if collar_poly is None and stadiums:
        collar_poly = min(stadiums, key=lambda tp: abs(tp.polygon.area())).polygon

    return PreservedMteParts(
        collar=collar_poly,
        extension=extension,
        merge_polys=(extension,),
    )


def _polygon_key(poly: gdstk.Polygon) -> tuple[float, float, float, float, float]:
    bb = poly.bounding_box()
    if bb is None:
        return (0.0, 0.0, 0.0, 0.0, 0.0)
    (x0, y0), (x1, y1) = bb
    return (round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3), round(abs(poly.area()), 3))


def mte_extension_is_perfect(
    parts: PreservedMteParts,
    body_mte_polys: Sequence[gdstk.Polygon],
    *,
    precision: float = 1e-3,
    max_body_overlap_fraction: float = 0.5,
) -> bool:
    """
    True when the preserved MTE extension is already a flat filter-side stub.

    Wild resonators (indices 5/7 on KB331) attach the extension polygon entirely
    to resonator-body MTE; those need a redraw and are excluded here.
    """
    ext = parts.extension
    ext_area = abs(ext.area())
    if ext_area < 1e-6:
        return False
    overlap = preserved_mte_overlap_with_body(ext, body_mte_polys, precision=precision)
    return overlap / ext_area <= max_body_overlap_fraction


def _preserved_mte_connected_cluster(
    preserved_polys: Sequence[gdstk.Polygon],
    seeds: Sequence[gdstk.Polygon],
    *,
    precision: float = 1e-3,
    min_overlap_um2: float = 0.01,
) -> list[gdstk.Polygon]:
    """Flood-fill preserved filter MTE polygons boolean-touching any seed."""
    cluster: list[gdstk.Polygon] = []
    seed_keys = {_polygon_key(seed) for seed in seeds}

    for poly in preserved_polys:
        key = _polygon_key(poly)
        if key in seed_keys or any(
            polys_touch(
                poly,
                seed,
                precision=precision,
                min_overlap_um2=min_overlap_um2,
            )
            for seed in seeds
        ):
            cluster.append(poly)

    changed = True
    while changed:
        changed = False
        for poly in preserved_polys:
            if poly in cluster:
                continue
            if any(
                polys_touch(
                    member,
                    poly,
                    precision=precision,
                    min_overlap_um2=min_overlap_um2,
                )
                for member in cluster
            ):
                cluster.append(poly)
                changed = True
    return cluster


def disconnected_preserved_mte_orphans(
    preserved_polys: Sequence[gdstk.Polygon],
    body_mte_polys: Sequence[gdstk.Polygon],
    parts: PreservedMteParts,
    *,
    precision: float = 1e-3,
    min_overlap_um2: float = 0.01,
) -> list[gdstk.Polygon]:
    """
    Preserved filter MTE pieces not connected to body + collar + extension.

    Only returns polygons from ``preserved_polys``; frame-template MTE is never
    included.
    """
    seeds: list[gdstk.Polygon] = list(body_mte_polys)
    seeds.append(parts.extension)
    if parts.collar is not None:
        seeds.append(parts.collar)
    for poly in preserved_polys:
        if preserved_mte_overlap_with_body(poly, body_mte_polys, precision=precision) >= min_overlap_um2:
            seeds.append(poly)
        elif any(
            polys_touch(
                poly,
                body,
                precision=precision,
                min_overlap_um2=min_overlap_um2,
            )
            for body in body_mte_polys
        ):
            seeds.append(poly)

    cluster = _preserved_mte_connected_cluster(
        preserved_polys,
        seeds,
        precision=precision,
        min_overlap_um2=min_overlap_um2,
    )
    cluster_keys = {_polygon_key(poly) for poly in cluster}
    return [poly for poly in preserved_polys if _polygon_key(poly) not in cluster_keys]


def _junction_on_shared_boundary(
    extension: gdstk.Polygon,
    collar: gdstk.Polygon,
    *,
    tol_um: float,
    boolean_precision: float,
) -> tuple[Point, Point] | None:
    """Corners where the extension polygon meets the MTE collar polygon."""
    ext_pts = [(float(p[0]), float(p[1])) for p in extension.points]
    candidates: list[Point] = []
    for vertex in ext_pts:
        if _point_on_polygon_boundary(vertex, collar, tol_um):
            candidates.append(vertex)

    n = len(ext_pts)
    for i in range(n):
        p0, p1 = ext_pts[i], ext_pts[(i + 1) % n]
        if _point_on_polygon_boundary(p0, collar, tol_um) and _point_on_polygon_boundary(
            p1, collar, tol_um
        ):
            candidates.extend([p0, p1])

    unique = _dedupe_points(candidates, tol_um)
    if len(unique) >= 2:
        return _farthest_pair(unique)

    inter = gdstk.boolean(extension, collar, "and", precision=boolean_precision)
    if inter:
        overlap = max(inter, key=lambda p: abs(p.area()))
        on_overlap = [
            v for v in ext_pts if _point_on_polygon_boundary(v, overlap, tol_um)
        ]
        unique = _dedupe_points(on_overlap, tol_um)
        if len(unique) >= 2:
            return _farthest_pair(unique)
    return None


def _junction_on_body_overlap(
    extension: gdstk.Polygon,
    body_mte_polys: Sequence[gdstk.Polygon],
    *,
    tol_um: float,
    boolean_precision: float,
) -> tuple[Point, Point] | None:
    """Fallback junction: extension vertices on the resonator-body MTE overlap."""
    inter_pieces: list[gdstk.Polygon] = []
    for body in body_mte_polys:
        inter = gdstk.boolean(extension, body, "and", precision=boolean_precision)
        if inter:
            inter_pieces.extend(inter)
    if not inter_pieces:
        return None

    overlap = max(inter_pieces, key=lambda p: abs(p.area()))
    ext_pts = [(float(p[0]), float(p[1])) for p in extension.points]
    on_overlap = [
        v for v in ext_pts if _point_on_polygon_boundary(v, overlap, tol_um)
    ]
    unique = _dedupe_points(on_overlap, tol_um)
    if len(unique) >= 2:
        return _farthest_pair(unique)
    return None


def collar_extension_junction_corners(
    parts: PreservedMteParts,
    body_mte_polys: Sequence[gdstk.Polygon],
    cfg: MteRouteConfig | None = None,
) -> tuple[Point, Point]:
    """Two corners where the filter MTE extension meets the MTE collar."""
    c = cfg or MteRouteConfig()
    if parts.collar is not None:
        shared = _junction_on_shared_boundary(
            parts.extension,
            parts.collar,
            tol_um=c.boundary_tolerance_um,
            boolean_precision=c.boolean_precision,
        )
        if shared is not None:
            return _order_attach_corners(*shared)

    body = _junction_on_body_overlap(
        parts.extension,
        body_mte_polys,
        tol_um=c.boundary_tolerance_um,
        boolean_precision=c.boolean_precision,
    )
    if body is not None:
        return _order_attach_corners(*body)

    raise ValueError("could not find MTE collar-extension junction corners")


def preserved_extension_attach_corners(
    parts: PreservedMteParts,
    body_mte_polys: Sequence[gdstk.Polygon],
    cfg: MteRouteConfig | None = None,
) -> tuple[Point, Point]:
    """Junction corners between preserved filter MTE extension and collar."""
    return collar_extension_junction_corners(parts, body_mte_polys, cfg)


def _probe_overlaps_polygon(
    point: Point,
    polygon: gdstk.Polygon,
    *,
    boolean_precision: float,
    probe_half_um: float,
) -> bool:
    probe = gdstk.rectangle(
        (point[0] - probe_half_um, point[1] - probe_half_um),
        (point[0] + probe_half_um, point[1] + probe_half_um),
    )
    return bool(gdstk.boolean(probe, polygon, "and", precision=boolean_precision))


def _inset_junction_corner_for_merge(
    corner: Point,
    extension: gdstk.Polygon,
    *,
    cfg: MteRouteConfig,
    junction_peer: Point | None = None,
) -> Point:
    """
    Nudge a junction corner slightly into ``extension`` so the route quad shares
    area with preserved metal (edge-only contact does not boolean-merge).
    """
    inset_um = cfg.junction_merge_inset_um
    if inset_um <= 0.0:
        return corner

    bb = extension.bounding_box()
    tol = cfg.boundary_tolerance_um
    if bb is not None:
        (x0, y0), (x1, y1) = bb
        axis_trials: list[Point] = []
        if abs(corner[0] - x0) <= tol:
            axis_trials.append((corner[0] + inset_um, corner[1]))
        if abs(corner[0] - x1) <= tol:
            axis_trials.append((corner[0] - inset_um, corner[1]))
        if abs(corner[1] - y0) <= tol:
            axis_trials.append((corner[0], corner[1] + inset_um))
        if abs(corner[1] - y1) <= tol:
            axis_trials.append((corner[0], corner[1] - inset_um))
        for dx, dy in (
            (inset_um, 0.0),
            (-inset_um, 0.0),
            (0.0, inset_um),
            (0.0, -inset_um),
        ):
            axis_trials.append((corner[0] + dx, corner[1] + dy))
        for trial in axis_trials:
            if _probe_overlaps_polygon(
                trial,
                extension,
                boolean_precision=cfg.boolean_precision,
                probe_half_um=cfg.inside_probe_half_um,
            ):
                return trial

    directions: list[tuple[float, float]] = []
    bb = extension.bounding_box()
    if bb is not None:
        cx = (bb[0][0] + bb[1][0]) / 2.0
        cy = (bb[0][1] + bb[1][1]) / 2.0
        dx, dy = cx - corner[0], cy - corner[1]
        length = math.hypot(dx, dy)
        if length > 1e-9:
            directions.append((dx / length, dy / length))

    if junction_peer is not None:
        jx = junction_peer[0] - corner[0]
        jy = junction_peer[1] - corner[1]
        length = math.hypot(jx, jy)
        if length > 1e-9:
            px, py = -jy / length, jx / length
            directions.extend([(px, py), (-px, -py)])

    for ux, uy in ((1.0, 0.0), (-1.0, 0.0), (0.0, 1.0), (0.0, -1.0)):
        directions.append((ux, uy))

    seen: set[tuple[float, float]] = set()
    unique_dirs: list[tuple[float, float]] = []
    for ux, uy in directions:
        key = (round(ux, 6), round(uy, 6))
        if key in seen:
            continue
        seen.add(key)
        unique_dirs.append((ux, uy))

    max_step = inset_um * 8.0
    for ux, uy in unique_dirs:
        lo, hi = 0.0, max_step
        best = corner
        for _ in range(12):
            mid = (lo + hi) / 2.0
            trial = (corner[0] + ux * mid, corner[1] + uy * mid)
            if _probe_overlaps_polygon(
                trial,
                extension,
                boolean_precision=cfg.boolean_precision,
                probe_half_um=cfg.inside_probe_half_um,
            ):
                best = trial
                lo = mid
            else:
                hi = mid
        if best != corner:
            return best
    return corner


def junction_route_corners_for_merge(
    junction_up: Point,
    junction_dn: Point,
    extension: gdstk.Polygon,
    cfg: MteRouteConfig,
) -> tuple[Point, Point]:
    """Route-quad collar-side corners, inset into ``extension`` when needed."""
    route_up = _inset_junction_corner_for_merge(
        junction_up,
        extension,
        cfg=cfg,
        junction_peer=junction_dn,
    )
    route_dn = _inset_junction_corner_for_merge(
        junction_dn,
        extension,
        cfg=cfg,
        junction_peer=junction_up,
    )
    return _order_attach_corners(route_up, route_dn)


def _route_fragment_overlap(frag: gdstk.Polygon, route: gdstk.Polygon, *, precision: float) -> float:
    inter = gdstk.boolean(frag, route, "and", precision=precision)
    return sum(abs(p.area()) for p in inter) if inter else 0.0


def merge_mte_route_with_extensions(
    route: gdstk.Polygon,
    extension_polys: Sequence[gdstk.Polygon],
    *,
    boolean_precision: float,
    association_gap_um: float = 0.01,
) -> gdstk.Polygon:
    """Boolean-OR the pad-route quad with preserved extension stub(s) only."""
    if not extension_polys:
        return route
    pieces = [route, *extension_polys]
    merged = gdstk.boolean(pieces, [], "or", precision=boolean_precision)
    if not merged:
        return route
    if len(merged) == 1:
        return merged[0]

    route_frag = max(
        merged,
        key=lambda frag: _route_fragment_overlap(frag, route, precision=boolean_precision),
    )
    kept = [route_frag]
    changed = True
    while changed:
        changed = False
        for frag in merged:
            if frag in kept:
                continue
            if any(
                polys_associated(
                    frag,
                    member,
                    gap_um=association_gap_um,
                    precision=boolean_precision,
                )
                for member in kept
            ):
                kept.append(frag)
                changed = True

    if len(kept) == 1:
        return kept[0]
    remerged = gdstk.boolean(kept, [], "or", precision=boolean_precision)
    if not remerged:
        return kept[0]
    if len(remerged) == 1:
        return remerged[0]
    return max(remerged, key=lambda p: abs(p.area()))


def _merged_overlap_area(
    merged: gdstk.Polygon,
    extension: gdstk.Polygon,
    *,
    boolean_precision: float,
) -> float:
    inter = gdstk.boolean(merged, extension, "and", precision=boolean_precision)
    return sum(abs(p.area()) for p in inter) if inter else 0.0


def merge_pad_route_with_preserved(
    route: gdstk.Polygon,
    parts: PreservedMteParts,
    junction_up: Point,
    junction_dn: Point,
    cfg: MteRouteConfig,
) -> gdstk.Polygon:
    """
    Boolean-merge the pad route with the preserved extension stub.

    The collar polygon is never merged here — it remains a separate piece on the
    frame. When the route quad only edge-touches the extension (no shared area),
    rebuild the collar-side corners with a small inset so gdstk can form one net.
    """
    merged = merge_mte_route_with_extensions(
        route,
        parts.merge_polys,
        boolean_precision=cfg.boolean_precision,
    )
    if _merged_overlap_area(merged, parts.extension, boolean_precision=cfg.boolean_precision) > 0.1:
        return merged

    route_up, route_dn = junction_route_corners_for_merge(
        junction_up, junction_dn, parts.extension, cfg
    )
    pts = route.points
    merge_route = gdstk.Polygon(
        [
            (float(pts[0][0]), float(pts[0][1])),
            (float(pts[1][0]), float(pts[1][1])),
            route_up,
            route_dn,
        ],
        layer=route.layer,
        datatype=route.datatype,
    )
    return merge_mte_route_with_extensions(
        merge_route,
        parts.merge_polys,
        boolean_precision=cfg.boolean_precision,
    )


def _skill_mte_conn_vertices(
    signal_polys: Sequence[gdstk.Polygon],
    cfg: MteRouteConfig,
    parts: PreservedMteParts,
    body_mte_polys: Sequence[gdstk.Polygon],
) -> tuple[list[Point], PadAttachmentEdge]:
    """
    ``mteConn`` quad: ``[vtbdn, vtbup, mteupFinal, mtednFinal]``.

    Pad corners are the signal-pad bbox top-right / bottom-right. Collar-side
    corners are the junction where the filter MTE extension meets the collar.
    """
    vtb_up, vtb_dn = _skill_pad_vtb_corners(signal_polys, expand_um=0.0)
    overlap = cfg.pad_touch_overlap_um
    vtb_up = (vtb_up[0] - overlap, vtb_up[1])
    vtb_dn = (vtb_dn[0] - overlap, vtb_dn[1])

    junction_up, junction_dn = preserved_extension_attach_corners(
        parts, body_mte_polys, cfg
    )
    mte_up, mte_dn = junction_up, junction_dn

    pad_entry = (
        (vtb_dn[0] + vtb_up[0]) / 2.0,
        (vtb_dn[1] + vtb_up[1]) / 2.0,
    )
    attachment = PadAttachmentEdge(
        corner_low=vtb_dn,
        corner_high=vtb_up,
        inward_normal=(-1.0, 0.0),
        pad_entry=pad_entry,
        span_um=_dist(vtb_dn, vtb_up),
    )
    return [vtb_dn, vtb_up, mte_up, mte_dn], attachment


def _mouth_span_along_pad_edge(
    mouth_a: Point,
    mouth_b: Point,
    inward_normal: tuple[float, float],
) -> float:
    """Span of a mouth segment along the axis parallel to the pad attachment edge."""
    ix, iy = inward_normal
    if abs(ix) >= abs(iy):
        return abs(mouth_a[1] - mouth_b[1])
    return abs(mouth_a[0] - mouth_b[0])


def collar_mouth_facing_pad(
    collar: gdstk.Polygon,
    body_mte_polys: Sequence[gdstk.Polygon],
    signal_polys: Sequence[gdstk.Polygon],
    *,
    merge_inset_um: float,
    min_edge_um: float = 5.0,
) -> tuple[Point, Point]:
    """
    Collar intercept pair on the edge whose outward normal best aligns with the pad.

    Endpoints are shifted ``merge_inset_um`` inward from the collar boundary.
    """
    pad_ref = _pad_reference_point(signal_polys)
    body_centroid = _body_centroid(body_mte_polys)
    pts = [(float(p[0]), float(p[1])) for p in collar.points]
    if len(pts) < 4:
        raise ValueError("collar must have at least 4 vertices")

    n = len(pts)
    best: tuple[tuple[float, float], Edge, tuple[float, float]] | None = None
    for edge_idx in range(n):
        p0, p1 = _edge_points(pts, edge_idx)
        edge_len = _edge_length(p0, p1)
        if edge_len < min_edge_um:
            continue
        outward = _edge_outward_normal((p0, p1), body_centroid)
        mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
        to_pad = (pad_ref[0] - mid[0], pad_ref[1] - mid[1])
        to_pad_len = math.hypot(to_pad[0], to_pad[1])
        if to_pad_len < 1e-9:
            continue
        alignment = (
            outward[0] * to_pad[0] / to_pad_len + outward[1] * to_pad[1] / to_pad_len
        )
        score = (alignment, edge_len)
        if best is None or score > best[0]:
            best = (score, (p0, p1), outward)

    if best is None:
        raise ValueError("collar has no edge facing the signal pad")

    _, (p0, p1), outward = best
    inward = (-outward[0], -outward[1])
    return (
        (
            p0[0] + inward[0] * merge_inset_um,
            p0[1] + inward[1] * merge_inset_um,
        ),
        (
            p1[0] + inward[0] * merge_inset_um,
            p1[1] + inward[1] * merge_inset_um,
        ),
    )


def _resolve_stretch_inner_mouth(
    draw: CollarExtensionDraw,
    signal_polys: Sequence[gdstk.Polygon],
    cfg: MteRouteConfig,
    *,
    collar: gdstk.Polygon | None,
    body_mte_polys: Sequence[gdstk.Polygon] | None,
    from_point: Point,
) -> tuple[Point, Point]:
    """Pick collar-side vertices for the stretched trapezoid."""
    inner_a = draw.intercept_a
    inner_b = draw.intercept_b
    if collar is None or body_mte_polys is None:
        return inner_a, inner_b

    attachment = pick_pad_attachment_edge(
        signal_polys, from_point, touch_overlap_um=cfg.pad_touch_overlap_um
    )
    pad_facing = collar_mouth_facing_pad(
        collar,
        body_mte_polys,
        signal_polys,
        merge_inset_um=cfg.collar_merge_inset_um,
    )
    span_53 = _mouth_span_along_pad_edge(
        inner_a, inner_b, attachment.inward_normal
    )
    span_pad = _mouth_span_along_pad_edge(
        pad_facing[0], pad_facing[1], attachment.inward_normal
    )
    if span_pad > 1e-6 and span_53 < cfg.min_mouth_span_fraction * span_pad:
        return pad_facing
    return inner_a, inner_b


def stretch_extension_to_pad(
    draw: CollarExtensionDraw,
    signal_polys: Sequence[gdstk.Polygon],
    cfg: MteRouteConfig,
    layer: int,
    datatype: int,
    *,
    from_point: Point | None = None,
    collar: gdstk.Polygon | None = None,
    body_mte_polys: Sequence[gdstk.Polygon] | None = None,
    preserved: gdstk.Polygon | None = None,
    parts: PreservedMteParts | None = None,
) -> tuple[gdstk.Polygon, PadAttachmentEdge]:
    """
    Build ``mteConn`` quad from pad corners to the collar-extension junction.

    Returns the route trapezoid and pad attachment metadata.
    """
    _ = draw, from_point, collar
    if parts is None:
        raise ValueError("preserved MTE parts are required for pad routing")
    if body_mte_polys is None:
        raise ValueError("body_mte_polys required for collar-extension junction")
    vertices, attachment = _skill_mte_conn_vertices(
        signal_polys, cfg, parts, body_mte_polys
    )
    stretched = gdstk.Polygon(vertices, layer=layer, datatype=datatype)
    return stretched, attachment


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
            f"(overlap {overlap:.4f} um┬▓ < {cfg.min_pad_overlap_um2:.4f} um┬▓)"
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
    """Stretch extension to pad when ``mte_route_target == center_pad``; else ``None``."""
    _ = roles  # reserved for future clearance checks
    c = cfg or MteRouteConfig()
    if classification.mte_route_target != "center_pad":
        return None
    if mte_result.extension_draw is None:
        return None

    signal_tps = classification.signal_polygons()
    if not signal_tps:
        raise ValueError(
            f"resonator {resonator_index}: center_pad route but no signal polygons"
        )

    layer, datatype = layermap.pair(c.mte_layer)
    signal_polys = [tp.polygon for tp in signal_tps]
    draw = mte_result.extension_draw
    pad_ref = _pad_reference_point(signal_polys)
    start_info = pick_route_start(draw, toward_point=pad_ref)

    collar_poly = mte_result.collar.polygon if mte_result.collar is not None else None
    parts = identify_preserved_mte_parts(
        mte_result.preserved_collar_polygons,
        roles.resonator_body_mte,
        boolean_precision=c.boolean_precision,
    )

    route_quad, attachment = stretch_extension_to_pad(
        draw,
        signal_polys,
        c,
        layer,
        datatype,
        from_point=start_info.center,
        collar=collar_poly,
        body_mte_polys=roles.resonator_body_mte,
        preserved=parts.extension,
        parts=parts,
    )
    route_quad = assign_layer(route_quad, layermap, c.mte_layer)
    junction_up, junction_dn = preserved_extension_attach_corners(
        parts, roles.resonator_body_mte, c
    )
    merged = merge_pad_route_with_preserved(
        route_quad,
        parts,
        junction_up,
        junction_dn,
        c,
    )
    stretched = assign_layer(merged, layermap, c.mte_layer)
    overlap = validate_pad_attachment(
        route_quad,
        signal_polys,
        c,
        resonator_index=resonator_index,
    )
    return MteRouteDraw(
        route_polygon=route_quad,
        routed_net_polygon=stretched,
        waypoints=[attachment.corner_low, attachment.corner_high],
        pad_entry=attachment.pad_entry,
        route_width_um=attachment.span_um,
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
        n_extensions=1,
    )


def build_mte_pad_routes(
    roles_by_index: Mapping[int, RtegGeometryRoles],
    classifications: Mapping[int, NodeClassification],
    extensions: Mapping[int, MteExtensionResult],
    layermap: LayerMap,
    config: MteRouteConfig | None = None,
) -> dict[int, MteExtensionResult]:
    """Run 5.4 pad stretch routing for every resonator index in ``extensions``."""
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
    "PadAttachmentEdge",
    "PreservedMteParts",
    "RouteStart",
    "apply_mte_pad_route",
    "build_mte_pad_route",
    "build_mte_pad_routes",
    "collar_extension_junction_corners",
    "collar_mouth_facing_pad",
    "disconnected_preserved_mte_orphans",
    "identify_preserved_mte_parts",
    "junction_route_corners_for_merge",
    "merge_mte_route_with_extensions",
    "merge_pad_route_with_preserved",
    "mte_extension_is_perfect",
    "mte_route_overview_rows",
    "pick_pad_attachment_edge",
    "pick_route_start",
    "preserved_extension_attach_corners",
    "stretch_extension_to_pad",
    "validate_pad_attachment",
    "_polygon_key",
]
