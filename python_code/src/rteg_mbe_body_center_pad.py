"""
Step 6.3 — MBE ground filler for ``center_pad`` resonators.

Keepouts mirror step 6.2: stadium / MTE offset clearance plus release-hole
zones. The filler is carved from those keepouts (same as 6.2), then the left
edge follows the carved clearance contour into the full filler-side MBE collar.
Top, right, and bottom bbox edges stay as drawn in step 4.
"""
from __future__ import annotations

import math
import os
import tempfile
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
    build_mte_trim_keepouts,
    carve_filler,
    empty_mbe_body_result,
    mte_route_obstacle_polys,
    offset_polys,
    trim_polygon_away_from_keepouts,
)
from rteg_mbe_extensions import (
    MbeConnectionConfig,
    _collar_mouth_edge_path,
    _collar_vertices,
    _locate_on_collar_boundary,
    _snap_point_to_collar,
    _walk_collar_boundary,
    select_collar_for_die_mouth,
    select_extension_collar_mbe,
    tag_baw_mbe,
)
from rteg_mte_extensions import MteExtensionResult

Point = tuple[float, float]

_COLLAR_EXEMPT_Y_MARGIN_UM = 2.0
_ENVELOPE_STEP_UM = 0.25
_COLLAR_LOCAL_BULGE_UM = 60.0
_BRIDGE_WIDTH_UM = 14.0


@dataclass(frozen=True)
class MbeBodyCenterPadConfig:
    """Tunable parameters for step 6.3 MBE ground filler."""

    mbe_layer: str = "BAW_MBE"
    boolean_precision: float = 1e-3
    intercept_tol_um: float = 0.05
    stadium_mte_clearance_um: float = 2.0
    # Extra margin on the final top/right/bottom trim only (avoids pinch corners).
    mte_trim_extra_clearance_um: float = 1.0
    release_hole_clearance_um: float = 6.0


def mbe_body_center_pad_applies(classification: NodeClassification) -> bool:
    """Step 6.3 applies when MTE is routed to the center signal pad."""
    return classification.mte_route_target == "center_pad"


def _rectangle_corners_ccw(filler: gdstk.Polygon) -> tuple[Point, Point, Point, Point]:
    """BL, BR, TR, TL from the filler bounding box."""
    bbox = filler.bounding_box()
    if bbox is None:
        raise ValueError("filler must have a bounding box")
    (x0, y0), (x1, y1) = bbox
    return (x0, y0), (x1, y0), (x1, y1), (x0, y1)


def _dedupe_points(points: Sequence[Point], tol: float) -> list[Point]:
    out: list[Point] = []
    for pt in points:
        if not any(
            abs(pt[0] - kept[0]) <= tol and abs(pt[1] - kept[1]) <= tol
            for kept in out
        ):
            out.append(pt)
    return out


def _left_edge_collar_hits(
    edge_x: float,
    y0: float,
    y1: float,
    collar: gdstk.Polygon,
    *,
    tol: float,
) -> list[Point]:
    """Intersections of the filler left edge with the collar boundary."""
    verts = _collar_vertices(collar)
    hits: list[Point] = []
    y_min, y_max = min(y0, y1), max(y0, y1)
    n = len(verts)
    for i in range(n):
        p0, p1 = verts[i], verts[(i + 1) % n]
        if abs(p1[0] - p0[0]) < 1e-9:
            if abs(p0[0] - edge_x) <= tol:
                for p in (p0, p1):
                    if y_min - tol <= p[1] <= y_max + tol:
                        hits.append((edge_x, p[1]))
            continue
        t = (edge_x - p0[0]) / (p1[0] - p0[0])
        if -tol <= t <= 1.0 + tol:
            y = p0[1] + t * (p1[1] - p0[1])
            if y_min - tol <= y <= y_max + tol:
                hits.append((edge_x, y))
    return sorted(_dedupe_points(hits, tol), key=lambda p: p[1])


def _collar_start_x(collar: gdstk.Polygon) -> float:
    """Minimum x of the preserved MBE collar (mouth start toward +x)."""
    verts = _collar_vertices(collar)
    return min(v[0] for v in verts)


def _exempt_keepouts_at_collar(
    keepouts: Sequence[gdstk.Polygon],
    collar: gdstk.Polygon,
    collar_start_x: float,
    *,
    boolean_precision: float,
) -> list[gdstk.Polygon]:
    """
    Remove stadium/MTE keepout for x >= ``collar_start_x`` in the collar y band.

    Release-hole keepouts are added separately and are not exempted here.
    """
    cbb = collar.bounding_box()
    if cbb is None or not keepouts:
        return list(keepouts)

    y0 = cbb[0][1] - _COLLAR_EXEMPT_Y_MARGIN_UM
    y1 = cbb[1][1] + _COLLAR_EXEMPT_Y_MARGIN_UM
    exempt_zone = gdstk.rectangle((collar_start_x, y0), (1.0e7, y1))

    trimmed: list[gdstk.Polygon] = []
    for keepout in keepouts:
        result = gdstk.boolean(
            keepout,
            exempt_zone,
            "not",
            precision=boolean_precision,
        )
        if result:
            trimmed.extend(result)
    return trimmed


def build_center_pad_keepouts(
    roles: RtegGeometryRoles,
    mte_result: MteExtensionResult | None,
    collar: gdstk.Polygon,
    cfg: MbeBodyCenterPadConfig,
) -> list[gdstk.Polygon]:
    """
    Clearance zones for step 6.3 — same MTE sources as step 6.2 keepouts.

    Use resonator-body MTE and the step-5.1 extension only. Preserved filter
    connectMTE collars are not carved here: they are not written into the RTEG
    cell and must not bite the step-4 top/right/bottom bbox edges.

    Stadium / extension MTE are offset by ``stadium_mte_clearance_um`` (2 µm).
    Release holes use ``release_hole_clearance_um`` (6 µm). Stadium keepouts
    are clipped at the MBE collar mouth so filler can reach the collar.
    """
    clearance_um = cfg.stadium_mte_clearance_um
    keepouts: list[gdstk.Polygon] = []

    mte_extension = mte_result.extension if mte_result is not None else None
    mte_routed_net = mte_result.routed_net if mte_result is not None else None
    stadium_mte_obstacles = mte_route_obstacle_polys(
        roles.resonator_body_mte,
        mte_extension,
        mte_routed_net,
    )

    if clearance_um > 0 and stadium_mte_obstacles:
        stadium_mte_keepouts = offset_polys(stadium_mte_obstacles, clearance_um)
        collar_start_x = _collar_start_x(collar)
        keepouts.extend(
            _exempt_keepouts_at_collar(
                stadium_mte_keepouts,
                collar,
                collar_start_x,
                boolean_precision=cfg.boolean_precision,
            )
        )

    release_polys = [tp.polygon for tp in roles.release_holes.all_items()]
    if release_polys and cfg.release_hole_clearance_um > 0:
        keepouts.extend(
            _grown_keepout_polys(release_polys, cfg.release_hole_clearance_um)
        )

    return keepouts


def _boolean_or_union(
    pieces: Sequence[gdstk.Polygon],
    *,
    boolean_precision: float,
) -> list[gdstk.Polygon]:
    if not pieces:
        return []
    if len(pieces) == 1:
        return [pieces[0]]
    return gdstk.boolean(pieces, [], "or", precision=boolean_precision) or list(pieces)


def _merge_carved_pieces(
    carved: Sequence[gdstk.Polygon],
    *,
    boolean_precision: float,
) -> gdstk.Polygon | None:
    """Pick the largest carved slab when carve_filler returns disjoint pieces."""
    if not carved:
        return None
    pieces = list(carved)
    if len(pieces) == 1:
        return pieces[0]
    united = _boolean_or_union(pieces, boolean_precision=boolean_precision)
    return max(united, key=lambda p: abs(p.area()))


def _clean_polygon(
    poly: gdstk.Polygon,
    *,
    boolean_precision: float,
) -> gdstk.Polygon:
    """Resolve self-intersections into one DRC-clean polygon."""
    cleaned = gdstk.boolean(poly, poly, "or", precision=boolean_precision)
    if not cleaned:
        return poly
    if len(cleaned) == 1:
        return cleaned[0]
    united = _boolean_or_union(cleaned, boolean_precision=boolean_precision)
    return max(united, key=lambda p: abs(p.area()))


def _vertex_interior_angle_deg(points: Sequence[Point], index: int) -> float:
    n = len(points)
    p0, p1, p2 = points[(index - 1) % n], points[index], points[(index + 1) % n]
    v1 = (p0[0] - p1[0], p0[1] - p1[1])
    v2 = (p2[0] - p1[0], p2[1] - p1[1])
    l1 = math.hypot(v1[0], v1[1])
    l2 = math.hypot(v2[0], v2[1])
    if l1 < 1e-9 or l2 < 1e-9:
        return 180.0
    cos_angle = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)))
    return math.degrees(math.acos(cos_angle))


def _remove_acute_vertices(
    poly: gdstk.Polygon,
    *,
    min_angle_deg: float = 45.0,
    max_removals: int = 50,
) -> gdstk.Polygon:
    """Drop pinch vertices left by boolean collar attach (e.g. resonator 6 spike)."""
    points: list[Point] = [(float(x), float(y)) for x, y in poly.points]
    layer, datatype = poly.layer, poly.datatype
    for _ in range(max_removals):
        if len(points) < 4:
            break
        worst_index = min(
            range(len(points)),
            key=lambda i: _vertex_interior_angle_deg(points, i),
        )
        if _vertex_interior_angle_deg(points, worst_index) >= min_angle_deg:
            break
        del points[worst_index]
    return gdstk.Polygon(points, layer=layer, datatype=datatype)


def _coalesce_to_single_polygon(
    pieces: Sequence[gdstk.Polygon],
    *,
    boolean_precision: float,
    prefer: gdstk.Polygon | None = None,
) -> gdstk.Polygon:
    """
    Union boolean fragments and return one closed polygon.

    When clipping would split a connected ring across disjoint carved slabs,
    keep ``prefer`` if it is still one piece.
    """
    if not pieces:
        if prefer is not None:
            return prefer
        raise ValueError("no polygon pieces to coalesce")
    united = _boolean_or_union(pieces, boolean_precision=boolean_precision)
    cleaned: list[gdstk.Polygon] = []
    for piece in united:
        cleaned.extend(
            gdstk.boolean(piece, piece, "or", precision=boolean_precision) or [piece]
        )
    united = _boolean_or_union(cleaned, boolean_precision=boolean_precision)
    if len(united) == 1:
        return united[0]
    if prefer is not None:
        prefer_parts = gdstk.boolean(prefer, prefer, "or", precision=boolean_precision)
        if prefer_parts and len(prefer_parts) == 1:
            return prefer_parts[0]
    return max(united, key=lambda p: abs(p.area()))


def _clip_preserving_connectivity(
    merged: gdstk.Polygon,
    allowed_region: Sequence[gdstk.Polygon],
    *,
    boolean_precision: float,
) -> gdstk.Polygon:
    """
    Trim filler to carved+collar metal without splitting a connected ring.

    When carve_filler yields disjoint slabs, AND with their union would cut
    the left-edge ring into separate upper/lower pieces — skip that clip.
    """
    if not allowed_region:
        return merged
    allowed_united = _boolean_or_union(
        allowed_region,
        boolean_precision=boolean_precision,
    )
    if len(allowed_united) > 1:
        return merged
    clipped = gdstk.boolean(
        merged,
        allowed_united,
        "and",
        precision=boolean_precision,
    )
    if not clipped:
        return merged
    return _coalesce_to_single_polygon(
        clipped,
        boolean_precision=boolean_precision,
        prefer=merged,
    )


def _clip_to_bbox(
    merged: gdstk.Polygon,
    bbox: tuple[tuple[float, float], tuple[float, float]],
    *,
    boolean_precision: float,
) -> gdstk.Polygon:
    clip_rect = gdstk.rectangle(bbox[0], bbox[1])
    clipped = gdstk.boolean(merged, clip_rect, "and", precision=boolean_precision)
    if not clipped:
        return merged
    return _coalesce_to_single_polygon(
        clipped,
        boolean_precision=boolean_precision,
        prefer=merged,
    )


def _arc_hit_endpoints(hits: Sequence[Point]) -> tuple[Point, Point]:
    """Bracketing hits for the single collar trace along the left edge."""
    if len(hits) >= 4:
        return hits[1], hits[-2]
    return hits[0], hits[-1]


def _append_if_far(points: list[Point], pt: Point, tol: float) -> None:
    if not points:
        points.append(pt)
        return
    last = points[-1]
    if abs(last[0] - pt[0]) > tol or abs(last[1] - pt[1]) > tol:
        points.append(pt)


def _clamp_path_min_x(path: Sequence[Point], min_x: float) -> list[Point]:
    """Keep collar traces on the filler side of the step-4 left edge."""
    return [(max(pt[0], min_x), pt[1]) for pt in path]


def _bridge_vertical_on_edge(
    anchor: Point,
    envelope: Sequence[Point],
    edge_x: float,
    *,
    tol: float,
) -> list[Point]:
    """
    Step along x=edge_x when the clearance outline steps outward above a hit.

    Only used for a local outward step on the filler side; large jumps are left
    to the carved-boundary clip so we do not chord through keepouts.
    """
    if not envelope:
        return []
    target = envelope[0]
    if target[0] <= edge_x + tol:
        return list(envelope)
    if target[0] > edge_x + _COLLAR_LOCAL_BULGE_UM:
        return list(envelope)
    y_lo, y_hi = min(anchor[1], target[1]), max(anchor[1], target[1])
    bridge: list[Point] = []
    y = y_lo
    while y <= y_hi + 1e-9:
        bridge.append((edge_x, y))
        y += _ENVELOPE_STEP_UM
    if bridge and abs(bridge[-1][1] - target[1]) > tol:
        bridge.append((edge_x, target[1]))
    return bridge + list(envelope)


def _point_in_carved(polys: Sequence[gdstk.Polygon], x: float, y: float) -> bool:
    return any(poly.contain((x, y)) for poly in polys)


def _left_envelope_from_carved(
    carved: Sequence[gdstk.Polygon],
    y_start: float,
    y_end: float,
    edge_x: float,
    x_right: float,
    *,
    tol: float,
) -> list[Point]:
    """Leftmost allowed-metal x at each y across one or more carved pieces."""
    ascending = y_end >= y_start
    y_lo, y_hi = min(y_start, y_end), max(y_start, y_end)
    points: list[Point] = []
    y = y_lo
    while y <= y_hi + 1e-9:
        x = edge_x
        found: float | None = None
        while x <= x_right + 1e-9:
            if _point_in_carved(carved, x, y):
                found = x
                break
            x += _ENVELOPE_STEP_UM
        if found is not None:
            points.append((found, y))
        y += _ENVELOPE_STEP_UM
    if not ascending:
        points.reverse()
    return _dedupe_points(points, tol)


def _collar_filler_side_path(
    collar: gdstk.Polygon,
    hit_a: Point,
    hit_b: Point,
    edge_x: float,
) -> list[Point]:
    """Collar trace on the filler (+x bulge) side between two intercepts."""
    verts = _collar_vertices(collar)
    if len(verts) < 2:
        return [hit_a, hit_b]

    edge_a, t_a = _locate_on_collar_boundary(hit_a, verts)
    edge_b, t_b = _locate_on_collar_boundary(hit_b, verts)
    path_fwd = _walk_collar_boundary(verts, edge_a, t_a, edge_b, t_b, True)
    path_bwd = _walk_collar_boundary(verts, edge_a, t_a, edge_b, t_b, False)
    x_limit = edge_x + _COLLAR_LOCAL_BULGE_UM

    def bulge(path: Sequence[Point]) -> float:
        return max(p[0] for p in path)

    bulge_fwd, bulge_bwd = bulge(path_fwd), bulge(path_bwd)
    # Inner mouth chord at x=edge_x leaves a gap when a modest local bulge exists.
    if (
        bulge_bwd <= edge_x + 1e-6
        and edge_x + 1e-6 < bulge_fwd <= x_limit + 1e-6
    ):
        return path_fwd

    local = [p for p in (path_fwd, path_bwd) if bulge(p) <= x_limit + 1e-6]
    if not local:
        local = [min((path_fwd, path_bwd), key=bulge)]
    return max(local, key=bulge)


def _collar_trace_path(
    collar: gdstk.Polygon,
    hit_a: Point,
    hit_b: Point,
    edge_x: float,
    *,
    n_hits: int,
) -> list[Point]:
    if n_hits >= 4:
        path = _collar_mouth_edge_path(collar, hit_a, hit_b)
    else:
        path = _collar_filler_side_path(collar, hit_a, hit_b, edge_x)
    return _clamp_path_min_x(path, edge_x)


def _y_extent_on_poly_at_x(
    poly: gdstk.Polygon,
    x: float,
    y_lo: float,
    y_hi: float,
) -> tuple[float | None, float | None]:
    """First and last y on ``poly`` at fixed x, sampled at ``_ENVELOPE_STEP_UM``."""
    y = y_lo
    first: float | None = None
    last: float | None = None
    while y <= y_hi + 1e-9:
        if poly.contain((x, y)):
            if first is None:
                first = y
            last = y
        y += _ENVELOPE_STEP_UM
    return first, last


def _gap_between_carved_slabs(
    carved: Sequence[gdstk.Polygon],
    *,
    tol: float,
) -> tuple[float, float] | None:
    if len(carved) < 2:
        return None
    slabs = sorted(carved, key=lambda p: p.bounding_box()[0][1])
    gap_lo = slabs[0].bounding_box()[1][1]
    gap_hi = slabs[-1].bounding_box()[0][1]
    if gap_hi <= gap_lo + tol:
        return None
    return gap_lo, gap_hi


def _bridge_split_carved_slabs(
    carved: Sequence[gdstk.Polygon],
    edge_x: float,
    y_lo: float,
    y_hi: float,
    *,
    layer: int,
    datatype: int,
    bridge_width_um: float = _BRIDGE_WIDTH_UM,
) -> gdstk.Polygon | None:
    """Thin +x strip at the step-4 left edge so carved slabs boolean-OR to one piece."""
    slabs = sorted(carved, key=lambda p: p.bounding_box()[0][1])
    upper, lower = slabs[0], slabs[-1]
    _, upper_last = _y_extent_on_poly_at_x(upper, edge_x, y_lo, y_hi)
    lower_first, _ = _y_extent_on_poly_at_x(lower, edge_x, y_lo, y_hi)
    if upper_last is None or lower_first is None or lower_first <= upper_last + 1e-6:
        return None
    return gdstk.rectangle(
        (edge_x, upper_last),
        (edge_x + bridge_width_um, lower_first),
        layer=layer,
        datatype=datatype,
    )


def _union_carved_with_collar(
    carved: Sequence[gdstk.Polygon],
    collar_piece: Sequence[gdstk.Polygon] | None,
    bridge: gdstk.Polygon | None,
    *,
    boolean_precision: float,
) -> gdstk.Polygon | None:
    pieces = list(carved)
    if bridge is not None:
        pieces.append(bridge)
    if collar_piece:
        pieces.extend(collar_piece)
    united = _boolean_or_union(pieces, boolean_precision=boolean_precision)
    if not united:
        return None
    return _coalesce_to_single_polygon(united, boolean_precision=boolean_precision)


def _ring_extra_without_gap_fill(
    ring: gdstk.Polygon,
    carved_u: gdstk.Polygon,
    gap_lo: float,
    gap_hi: float,
    br: Point,
    edge_x: float,
    *,
    layer: int,
    datatype: int,
    boolean_precision: float,
) -> list[gdstk.Polygon]:
    """
    Metal traced by the routed ring but outside carved+collar, minus the
    horizontal keepout slab across a split-carve gap.
    """
    extra = gdstk.boolean(ring, carved_u, "not", precision=boolean_precision)
    if not extra:
        return []
    gap_rect = gdstk.rectangle(
        (edge_x + _ENVELOPE_STEP_UM, gap_lo),
        (br[0], gap_hi),
        layer=layer,
        datatype=datatype,
    )
    return gdstk.boolean(extra, gap_rect, "not", precision=boolean_precision) or []


def _merge_split_carve_filler(
    carved_u: gdstk.Polygon,
    ring: gdstk.Polygon,
    gap_lo: float,
    gap_hi: float,
    br: Point,
    edge_x: float,
    layer: int,
    datatype: int,
    *,
    boolean_precision: float,
) -> gdstk.Polygon:
    trim_extra = _ring_extra_without_gap_fill(
        ring,
        carved_u,
        gap_lo,
        gap_hi,
        br,
        edge_x,
        layer=layer,
        datatype=datatype,
        boolean_precision=boolean_precision,
    )
    pieces = [carved_u, *trim_extra]
    return _coalesce_to_single_polygon(pieces, boolean_precision=boolean_precision)


def _collar_x_intercepts_at_y(
    collar: gdstk.Polygon,
    y: float,
    *,
    tol: float,
) -> list[float]:
    verts = _collar_vertices(collar)
    xs: list[float] = []
    n = len(verts)
    for i in range(n):
        p0, p1 = verts[i], verts[(i + 1) % n]
        if abs(p1[1] - p0[1]) < 1e-9:
            if abs(p0[1] - y) <= tol:
                xs.extend([p0[0], p1[0]])
            continue
        t = (y - p0[1]) / (p1[1] - p0[1])
        if -tol <= t <= 1.0 + tol:
            xs.append(p0[0] + t * (p1[0] - p0[0]))
    return xs


def _left_boundary_x_at_y(
    y: float,
    edge_x: float,
    x_right: float,
    carved: Sequence[gdstk.Polygon],
    collar: gdstk.Polygon,
    hit_bot: Point,
    hit_top: Point,
    *,
    tol: float,
) -> float | None:
    """
    Leftmost filler-metal x on row ``y``.

    Returns ``None`` when no metal is allowed on that row (split-carve gap).
    """
    in_collar = (
        hit_bot[1] - _COLLAR_EXEMPT_Y_MARGIN_UM - tol
        <= y
        <= hit_top[1] + _COLLAR_EXEMPT_Y_MARGIN_UM + tol
    )
    if in_collar:
        xs = _collar_x_intercepts_at_y(collar, y, tol=tol)
        if xs:
            return max(edge_x, min(xs))
        return edge_x

    x = edge_x
    while x <= x_right + 1e-9:
        if _point_in_carved(carved, x, y):
            return x
        x += _ENVELOPE_STEP_UM
    return None


def _gds_polygon_count(
    poly: gdstk.Polygon,
    *,
    boolean_precision: float,
) -> int:
    """How many simple polygons GDS writers emit for ``poly``."""
    with tempfile.NamedTemporaryFile(suffix=".gds", delete=False) as handle:
        path = handle.name
    try:
        lib = gdstk.Library()
        cell = gdstk.Cell("probe")
        cell.add(poly.copy())
        lib.add(cell)
        lib.write_gds(path)
        return len(gdstk.read_gds(path).cells[0].polygons)
    finally:
        os.unlink(path)


def _rebuild_simple_polygon(
    poly: gdstk.Polygon,
    bbox: tuple[tuple[float, float], tuple[float, float]],
    *,
    boolean_precision: float,
) -> gdstk.Polygon:
    """
  Reconstruct one GDS-safe polygon from the filled interior.

    Self-intersecting vertex lists decompose into multiple GDS polygons even
    when ``boolean(poly, poly, 'or')`` returns one object. Row strips rebuilt
    from ``poly.contain`` recover the true interior as a single polygon.
    """
    (x0, y0), (x1, y1) = bbox
    layer, datatype = poly.layer, poly.datatype
    strips: list[gdstk.Polygon] = []
    y = y0
    while y <= y1 + 1e-9:
        x = x0
        inside = False
        start: float | None = None
        while x <= x1 + 1e-9:
            if poly.contain((x, y)):
                if not inside:
                    start = x
                    inside = True
            elif inside and start is not None:
                strips.append(
                    gdstk.rectangle(
                        (start, y),
                        (x, y + _ENVELOPE_STEP_UM),
                        layer=layer,
                        datatype=datatype,
                    )
                )
                inside = False
                start = None
            x += _ENVELOPE_STEP_UM
        if inside and start is not None:
            strips.append(
                gdstk.rectangle(
                    (start, y),
                    (x1, y + _ENVELOPE_STEP_UM),
                    layer=layer,
                    datatype=datatype,
                )
            )
        y += _ENVELOPE_STEP_UM
    if not strips:
        return poly
    united = gdstk.boolean(strips, [], "or", precision=boolean_precision)
    if not united:
        return poly
    return _coalesce_to_single_polygon(united, boolean_precision=boolean_precision)


def _finalize_simple_filler(
    merged: gdstk.Polygon,
    bbox: tuple[tuple[float, float], tuple[float, float]],
    collar: gdstk.Polygon,
    collar_piece: Sequence[gdstk.Polygon] | None,
    *,
    boolean_precision: float,
) -> gdstk.Polygon:
    """Clip to step-4 bbox and absorb collar metal that still hovers in the filler."""
    _ = collar_piece
    merged = _clip_to_bbox(merged, bbox, boolean_precision=boolean_precision)
    merged = _clean_polygon(merged, boolean_precision=boolean_precision)
    gap = gdstk.boolean(collar, merged, "not", precision=boolean_precision)
    if gap:
        filler_side = gdstk.rectangle(bbox[0], bbox[1])
        attach = gdstk.boolean(gap, filler_side, "and", precision=boolean_precision)
        attach_area = sum(abs(p.area()) for p in attach) if attach else 0.0
        if attach_area > 1e-3:
            merged = _coalesce_to_single_polygon(
                [merged, *attach],
                boolean_precision=boolean_precision,
                prefer=merged,
            )
            merged = _clean_polygon(merged, boolean_precision=boolean_precision)
    merged = _remove_acute_vertices(merged)
    return _clean_polygon(merged, boolean_precision=boolean_precision)


_BOUNDARY_SIMPLIFY_TOL_UM = 1.0


def _simplify_monotonic_path(points: Sequence[Point], *, tol: float) -> list[Point]:
    """Drop nearly duplicate samples so GDS export stays one simple polygon."""
    if not points:
        return []
    out: list[Point] = [points[0]]
    for pt in points[1:]:
        last = out[-1]
        if abs(pt[0] - last[0]) > tol or abs(pt[1] - last[1]) > tol:
            out.append(pt)
    return out


def _build_y_monotonic_filler(
    carved_list: Sequence[gdstk.Polygon],
    collar: gdstk.Polygon,
    collar_piece: Sequence[gdstk.Polygon] | None,
    bridge: gdstk.Polygon | None,
    bl: Point,
    br: Point,
    tr: Point,
    hit_bot: Point,
    hit_top: Point,
    gap: tuple[float, float] | None,
    layer: int,
    datatype: int,
    *,
    boolean_precision: float,
    tol: float,
    simplify_tol: float = _BOUNDARY_SIMPLIFY_TOL_UM,
) -> gdstk.Polygon:
    """
    One simple polygon: left boundary hugs the filler-side collar, bbox closes.

    Dense left-edge sampling self-intersects on GDS write; simplify before export.
    """
    gap_lo, gap_hi = gap if gap is not None else (float("inf"), float("-inf"))
    left: list[Point] = [bl]
    y = bl[1]
    while y <= tr[1] + 1e-9:
        if gap is not None and gap_lo + tol < y < gap_hi - tol:
            y += _ENVELOPE_STEP_UM
            continue
        x_left = _left_boundary_x_at_y(
            y,
            bl[0],
            br[0],
            carved_list,
            collar,
            hit_bot,
            hit_top,
            tol=tol,
        )
        if x_left is not None:
            left.append((x_left, y))
        y += _ENVELOPE_STEP_UM

    left = _simplify_monotonic_path(left, tol=simplify_tol)
    left.extend([tr, br])
    shell = gdstk.Polygon(left, layer=layer, datatype=datatype)
    shell = _clean_polygon(shell, boolean_precision=boolean_precision)

    pieces: list[gdstk.Polygon] = [shell]
    if bridge is not None:
        pieces.append(bridge)
    if collar_piece:
        pieces.extend(collar_piece)
    united = _boolean_or_union(pieces, boolean_precision=boolean_precision)
    merged = _coalesce_to_single_polygon(united, boolean_precision=boolean_precision)
    allowed: list[gdstk.Polygon] = list(carved_list)
    if bridge is not None:
        allowed.append(bridge)
    if collar_piece:
        allowed.extend(collar_piece)
    clipped = _clip_preserving_connectivity(
        merged,
        allowed,
        boolean_precision=boolean_precision,
    )
    if _gds_polygon_count(clipped, boolean_precision=boolean_precision) == 1:
        merged = clipped
    return _clean_polygon(merged, boolean_precision=boolean_precision)


def route_filler_around_collar(
    base_filler: gdstk.Polygon,
    collar: gdstk.Polygon,
    body_polys: Sequence[gdstk.Polygon],
    layermap: LayerMap,
    cfg: MbeBodyCenterPadConfig,
    *,
    keepouts: Sequence[gdstk.Polygon] | None = None,
    mte_trim_keepouts: Sequence[gdstk.Polygon] | None = None,
    collar_hits: tuple[Point, Point] | None = None,
) -> list[gdstk.Polygon]:
    """
    Carve with 6.2-style keepouts, trace the left edge from a sampled clearance
    envelope, union the preserved collar, and return one connected polygon.
    """
    _ = body_polys
    keepout_list = list(keepouts or [])
    carved_list, _ = carve_filler(
        base_filler,
        keepout_list,
        boolean_precision=cfg.boolean_precision,
    )
    if not carved_list:
        carved_list = [base_filler]
    template = max(carved_list, key=lambda p: abs(p.area()))

    bl, br, tr, tl = _rectangle_corners_ccw(base_filler)
    edge_x = bl[0]
    filler_bb = base_filler.bounding_box()
    if collar_hits is not None:
        from rteg_die_intercepts import mouth_hits_for_left_edge

        hit_bot, hit_top = mouth_hits_for_left_edge(collar_hits[0], collar_hits[1])
        hit_bot = _snap_point_to_collar(collar, hit_bot)
        hit_top = _snap_point_to_collar(collar, hit_top)
        hits = [hit_bot, hit_top]
    else:
        hits = _left_edge_collar_hits(
            edge_x, bl[1], tl[1], collar, tol=cfg.intercept_tol_um
        )
    if len(hits) >= 2:
        hit_bot, hit_top = _arc_hit_endpoints(hits)
        layer, datatype = template.layer, template.datatype
        collar_band = gdstk.rectangle(
            (edge_x, hit_bot[1] - _COLLAR_EXEMPT_Y_MARGIN_UM),
            (br[0], hit_top[1] + _COLLAR_EXEMPT_Y_MARGIN_UM),
            layer=layer,
            datatype=datatype,
        )
        collar_piece = gdstk.boolean(
            collar,
            collar_band,
            "and",
            precision=cfg.boolean_precision,
        )
        gap = _gap_between_carved_slabs(
            carved_list, tol=cfg.intercept_tol_um
        )
        bridge = None
        if gap is not None:
            bridge = _bridge_split_carved_slabs(
                carved_list,
                edge_x,
                bl[1],
                tr[1],
                layer=layer,
                datatype=datatype,
            )
        for simplify_tol in (_BOUNDARY_SIMPLIFY_TOL_UM, 2.0, 3.0):
            merged = _build_y_monotonic_filler(
                carved_list,
                collar,
                collar_piece,
                bridge,
                bl,
                br,
                tr,
                hit_bot,
                hit_top,
                gap,
                layer,
                datatype,
                boolean_precision=cfg.boolean_precision,
                tol=cfg.intercept_tol_um,
                simplify_tol=simplify_tol,
            )
            if filler_bb is not None:
                trial = _finalize_simple_filler(
                    merged,
                    filler_bb,
                    collar,
                    collar_piece,
                    boolean_precision=cfg.boolean_precision,
                )
            else:
                trial = merged
            if _gds_polygon_count(trial, boolean_precision=cfg.boolean_precision) == 1:
                merged = trial
                break
            merged = trial
    else:
        merged = _merge_carved_pieces(
            carved_list,
            boolean_precision=cfg.boolean_precision,
        )
        if merged is None:
            merged = base_filler
        collar_piece = None

    if merged is None:
        merged = template

    if filler_bb is not None and len(hits) < 2:
        merged = _finalize_simple_filler(
            merged,
            filler_bb,
            collar,
            None,
            boolean_precision=cfg.boolean_precision,
        )

    if mte_trim_keepouts:
        merged = trim_polygon_away_from_keepouts(
            merged,
            mte_trim_keepouts,
            anchor=collar,
            boolean_precision=cfg.boolean_precision,
        )
        merged = _clean_polygon(merged, boolean_precision=cfg.boolean_precision)
        merged = _remove_acute_vertices(merged)
        merged = _clean_polygon(merged, boolean_precision=cfg.boolean_precision)
        merged = trim_polygon_away_from_keepouts(
            merged,
            mte_trim_keepouts,
            anchor=collar,
            boolean_precision=cfg.boolean_precision,
        )
        merged = _clean_polygon(merged, boolean_precision=cfg.boolean_precision)

    return [tag_baw_mbe(merged, layermap)]


def build_mbe_body_center_pad(
    roles: RtegGeometryRoles,
    classification: NodeClassification,
    mte_result: MteExtensionResult | None,
    layermap: LayerMap,
    cfg: MbeBodyCenterPadConfig | None = None,
    conn_cfg: MbeConnectionConfig | None = None,
    *,
    die_routing: object | None = None,
    resonator_index: int | None = None,
) -> MbeBodyResult:
    """Run step 6.3 for a single ``center_pad`` resonator."""
    c = cfg or MbeBodyCenterPadConfig()
    if not mbe_body_center_pad_applies(classification):
        return empty_mbe_body_result()

    base_filler = base_filler_polygon(classification)
    if base_filler is None:
        return empty_mbe_body_result(violations=["missing step-4 MBE width filler"])

    violations: list[str] = []
    connection_cfg = conn_cfg or MbeConnectionConfig()
    signal_polys = [tp.polygon for tp in classification.center_pad_polygons()]
    collar_tp = select_extension_collar_mbe(
        roles.preserved,
        roles.resonator_body_mbe,
        connection_cfg,
        signal_polys=signal_polys or None,
    )
    collar_hits = None
    if die_routing is not None and resonator_index is not None:
        collar_hits = die_routing.collar_mouth(resonator_index, "mbe")
    if collar_hits is not None:
        mbe_pieces = list(roles.preserved.mbe)
        if die_routing is not None and resonator_index is not None:
            mbe_pieces.extend(die_routing.extra_collars(resonator_index, "mbe"))
        picked = select_collar_for_die_mouth(
            mbe_pieces,
            collar_hits[0],
            collar_hits[1],
        )
        if picked is not None:
            collar_tp = picked
    if collar_tp is None:
        violations.append("missing preserved MBE collar for filler routing")
        filler: list[gdstk.Polygon] = [base_filler]
        absorbed_mbe: list[gdstk.Polygon] = []
    else:
        keepouts = build_center_pad_keepouts(
            roles,
            mte_result,
            collar_tp.polygon,
            c,
        )
        mte_extension = mte_result.extension if mte_result is not None else None
        mte_routed_net = mte_result.routed_net if mte_result is not None else None
        mte_obstacles = mte_route_obstacle_polys(
            roles.resonator_body_mte,
            mte_extension,
            mte_routed_net,
        )
        mte_trim_keepouts = build_mte_trim_keepouts(
            mte_obstacles,
            c.stadium_mte_clearance_um,
            extra_clearance_um=c.mte_trim_extra_clearance_um,
            boolean_precision=c.boolean_precision,
        )
        filler = route_filler_around_collar(
            base_filler,
            collar_tp.polygon,
            roles.resonator_body_mbe,
            layermap,
            c,
            keepouts=keepouts,
            mte_trim_keepouts=mte_trim_keepouts,
            collar_hits=(
                die_routing.collar_mouth(resonator_index, "mbe")
                if die_routing is not None and resonator_index is not None
                else None
            ),
        )
        absorbed_mbe = [collar_tp.polygon]

    return MbeBodyResult(
        cap=None,
        filler=filler,
        bridge=None,
        routed_net=list(filler),
        n_pieces=len(filler),
        drc_violations=violations,
        absorbed_mbe=absorbed_mbe,
    )


def build_mbe_body_center_pads(
    roles_by_index: Mapping[int, RtegGeometryRoles],
    classifications: Mapping[int, NodeClassification],
    mte_by_index: Mapping[int, MteExtensionResult],
    layermap: LayerMap,
    config: MbeBodyCenterPadConfig | None = None,
    conn_config: MbeConnectionConfig | None = None,
    *,
    die_routing: object | None = None,
) -> dict[int, MbeBodyResult]:
    """Run step 6.3 for every ``center_pad`` index in ``roles_by_index``."""
    cfg = config or MbeBodyCenterPadConfig()
    conn_cfg = conn_config or MbeConnectionConfig()
    out: dict[int, MbeBodyResult] = {}
    for idx, roles in roles_by_index.items():
        classification = classifications[idx]
        if not mbe_body_center_pad_applies(classification):
            continue
        out[idx] = build_mbe_body_center_pad(
            roles,
            classification,
            mte_by_index.get(idx),
            layermap,
            cfg,
            conn_cfg,
            die_routing=die_routing,
            resonator_index=idx,
        )
    return out


def mbe_body_center_pad_overview_rows(
    bodies: Mapping[int, MbeBodyResult],
    *,
    inst_names: Mapping[int, str] | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx in sorted(bodies):
        result = bodies[idx]
        filler_area = sum(abs(p.area()) for p in result.filler)
        rows.append(
            {
                "index": idx,
                "inst_name": inst_names.get(idx) if inst_names else None,
                "n_pieces": result.n_pieces,
                "filler_area_um2": round(filler_area, 2),
                "drc_violations": "; ".join(result.drc_violations) or None,
            }
        )
    return rows


__all__ = [
    "MbeBodyCenterPadConfig",
    "build_center_pad_keepouts",
    "build_mbe_body_center_pad",
    "build_mbe_body_center_pads",
    "mbe_body_center_pad_applies",
    "mbe_body_center_pad_overview_rows",
    "route_filler_around_collar",
]
