"""
Series resonator MTE — thin perimeter strip between release holes.

For ``res_type == "series"``, the signal MTE is a stroked band along one arc
of the resonator MBE body outline, bounded at both ends by release holes
(BAW_ReF / BAW_CAV). It is not filter connect MTE and not interior fill.

Assumptions
-----------
- Resonator outline = boolean-OR of resonator **MBE** polygons in RTEG space.
- Signal arc = shorter perimeter gap between the two smallest touching holes.
- Strip width = ``SignalBuildConfig.plate_width_um``.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import gdstk

from layermap import LayerMap
from prep_resonator_ppd import resonator_metal_polys
from prep_rteg_frame import RtegFrameAssembly
from rteg_collect import ReleaseHoles, TaggedPolygon, _resonator_shift
from separate import Resonator

if TYPE_CHECKING:
    from rteg_signal import SignalBuildConfig

Point = tuple[float, float]
MBE_LAYER = 2
_MIN_STRIP_AREA_UM2 = 1.0


@dataclass(frozen=True)
class _HoleAnchor:
    arc_um: float
    contact: Point
    hole: TaggedPolygon

    @property
    def area_um2(self) -> float:
        return abs(self.hole.polygon.area())


def _union_polys(polys: list[gdstk.Polygon], precision: float) -> list[gdstk.Polygon]:
    if not polys:
        return []
    acc: list[gdstk.Polygon] = [polys[0]]
    for poly in polys[1:]:
        nxt = gdstk.boolean(acc, poly, "or", precision=precision)
        acc = nxt if nxt else acc + [poly]
    return acc


def _resonator_mbe_body(
    res: Resonator, assembly: RtegFrameAssembly, precision: float
) -> gdstk.Polygon:
    dx, dy = _resonator_shift(res, assembly)
    mbe = [p for p in resonator_metal_polys(res, dx, dy) if p.layer == MBE_LAYER]
    if not mbe:
        raise ValueError(f"[{res.inst_name}] resonator has no MBE polygons")
    united = _union_polys(mbe, precision)
    if not united:
        raise ValueError(f"[{res.inst_name}] could not union resonator MBE body")
    return united[0]


def _perimeter_edges(body: gdstk.Polygon) -> list[tuple[Point, Point, float]]:
    pts = list(body.points)
    if len(pts) < 2:
        return []
    edges: list[tuple[Point, Point, float]] = []
    arc = 0.0
    for i in range(len(pts)):
        p0 = pts[i]
        p1 = pts[(i + 1) % len(pts)]
        edges.append((p0, p1, arc))
        arc += math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    return edges


def _perimeter_length(edges: list[tuple[Point, Point, float]]) -> float:
    if not edges:
        return 0.0
    p0, p1, _ = edges[-1]
    return edges[-1][2] + math.hypot(p1[0] - p0[0], p1[1] - p0[1])


def _project_to_segment(pt: Point, a: Point, b: Point) -> tuple[Point, float]:
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    len2 = dx * dx + dy * dy
    if len2 < 1e-18:
        return a, math.hypot(pt[0] - ax, pt[1] - ay)
    t = max(0.0, min(1.0, ((pt[0] - ax) * dx + (pt[1] - ay) * dy) / len2))
    proj = (ax + t * dx, ay + t * dy)
    return proj, math.hypot(pt[0] - proj[0], pt[1] - proj[1])


def _contact_on_perimeter(
    body: gdstk.Polygon,
    hole: gdstk.Polygon,
    precision: float,
) -> Point | None:
    inter = gdstk.boolean(body, hole, "and", precision=precision)
    if not inter:
        return None
    xs = [p[0] for poly in inter for p in poly.points]
    ys = [p[1] for poly in inter for p in poly.points]
    if not xs:
        return None
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _arc_at_point(
    contact: Point, edges: list[tuple[Point, Point, float]]
) -> float:
    best_arc = 0.0
    best_dist = float("inf")
    for p0, p1, arc0 in edges:
        proj, dist = _project_to_segment(contact, p0, p1)
        if dist < best_dist:
            best_dist = dist
            seg_len = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            along = math.hypot(proj[0] - p0[0], proj[1] - p0[1])
            best_arc = arc0 + along if seg_len > 1e-12 else arc0
    return best_arc


def _point_at_arc(
    s: float, edges: list[tuple[Point, Point, float]], total: float
) -> Point:
    if total <= 0 or not edges:
        return (0.0, 0.0)
    s = s % total
    for p0, p1, arc0 in edges:
        seg_len = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if s <= arc0 + seg_len + 1e-9:
            if seg_len < 1e-12:
                return p0
            t = (s - arc0) / seg_len
            return (p0[0] + t * (p1[0] - p0[0]), p0[1] + t * (p1[1] - p0[1]))
    p0, p1, _ = edges[-1]
    return p1


def _vertices_between(
    s0: float, s1: float, edges: list[tuple[Point, Point, float]]
) -> list[Point]:
    out: list[Point] = []
    for p0, p1, arc0 in edges:
        seg_len = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        seg_end = arc0 + seg_len
        if seg_end > s0 + 1e-9 and arc0 < s1 - 1e-9:
            if arc0 > s0 + 1e-9:
                out.append(p0)
            if seg_end < s1 - 1e-9:
                out.append(p1)
    return out


def _extract_arc_centerline(
    s0: float, s1: float, edges: list[tuple[Point, Point, float]], total: float
) -> list[Point]:
    if total <= 0:
        return []
    s0 = s0 % total
    s1 = s1 % total
    if abs(s1 - s0) < 1e-9:
        return [_point_at_arc(s0, edges, total)]
    if s0 < s1:
        pts = [_point_at_arc(s0, edges, total)]
        pts.extend(_vertices_between(s0, s1, edges))
        pts.append(_point_at_arc(s1, edges, total))
        return _dedupe_points(pts)
    pts = [_point_at_arc(s0, edges, total)]
    pts.extend(_vertices_between(s0, total, edges))
    pts.extend(_vertices_between(0.0, s1, edges))
    pts.append(_point_at_arc(s1, edges, total))
    return _dedupe_points(pts)


def _dedupe_points(points: Sequence[Point], tol: float = 1e-6) -> list[Point]:
    out: list[Point] = []
    for pt in points:
        if not out or math.hypot(pt[0] - out[-1][0], pt[1] - out[-1][1]) > tol:
            out.append(pt)
    return out


def _stroke_polygon(
    centerline: Sequence[Point], width: float, layer: int, datatype: int
) -> gdstk.Polygon:
    flex = gdstk.FlexPath(list(centerline), width, layer=layer, datatype=datatype)
    polys = flex.to_polygons()
    if not polys:
        raise ValueError("centerline produced no stroke polygon")
    return polys[0]


def _min_spacing(poly_a: gdstk.Polygon, poly_b: gdstk.Polygon, precision: float) -> float:
    if gdstk.boolean(poly_a, poly_b, "and", precision=precision):
        return 0.0
    best = float("inf")
    for pa in poly_a.points:
        for pb in poly_b.points:
            best = min(best, math.hypot(pa[0] - pb[0], pa[1] - pb[1]))
    return best


def _hole_anchors(
    body: gdstk.Polygon,
    release_holes: ReleaseHoles,
    precision: float,
) -> list[_HoleAnchor]:
    edges = _perimeter_edges(body)
    anchors: list[_HoleAnchor] = []
    for tagged in release_holes.all_items():
        contact = _contact_on_perimeter(body, tagged.polygon, precision)
        if contact is None:
            continue
        arc = _arc_at_point(contact, edges)
        anchors.append(_HoleAnchor(arc_um=arc, contact=contact, hole=tagged))
    anchors.sort(key=lambda a: a.arc_um)
    return anchors


def _select_signal_gap(
    anchors: list[_HoleAnchor], total: float
) -> tuple[float, float, _HoleAnchor, _HoleAnchor]:
    if len(anchors) < 2:
        raise ValueError("need at least two release holes touching resonator boundary")
    smallest = sorted(anchors, key=lambda a: a.area_um2)[:2]
    hole_a, hole_b = smallest[0], smallest[1]
    s_a, s_b = hole_a.arc_um, hole_b.arc_um
    if s_a <= s_b:
        forward = s_b - s_a
        backward = total - forward
        if forward <= backward:
            return s_a, s_b, hole_a, hole_b
        return s_b, s_a, hole_b, hole_a
    forward = s_a - s_b
    backward = total - forward
    if forward <= backward:
        return s_b, s_a, hole_b, hole_a
    return s_a, s_b, hole_a, hole_b


def _offset_centerline_inward(
    centerline: Sequence[Point],
    body: gdstk.Polygon,
    offset_um: float,
) -> list[Point]:
    """Shift the arc centerline toward the resonator interior by ``offset_um``."""
    if offset_um <= 0:
        return list(centerline)
    pts = list(centerline)
    out: list[Point] = []
    for i, pt in enumerate(pts):
        if i == 0:
            tx, ty = pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]
        elif i == len(pts) - 1:
            tx, ty = pts[-1][0] - pts[-2][0], pts[-1][1] - pts[-2][1]
        else:
            tx, ty = pts[i + 1][0] - pts[i - 1][0], pts[i + 1][1] - pts[i - 1][1]
        length = math.hypot(tx, ty)
        if length < 1e-9:
            out.append(pt)
            continue
        tx, ty = tx / length, ty / length
        chosen = pt
        for sign in (1, -1):
            nx, ny = -ty * sign, tx * sign
            probe = (pt[0] + nx * 0.2, pt[1] + ny * 0.2)
            if body.contain(probe):
                chosen = (pt[0] + nx * offset_um, pt[1] + ny * offset_um)
                break
        out.append(chosen)
    return out


def _min_ground_spacing(
    strip: gdstk.Polygon,
    ground_obstacles: Sequence[gdstk.Polygon],
    precision: float,
) -> float:
    best = float("inf")
    for obs in ground_obstacles:
        best = min(best, _min_spacing(strip, obs, precision))
    return best


def _trim_strip_for_ground_clearance(
    strip: gdstk.Polygon,
    ground_obstacles: Sequence[gdstk.Polygon],
    min_spacing_um: float,
    precision: float,
) -> gdstk.Polygon:
    """Carve grown ground keepouts; keep the largest surviving fragment."""
    if not ground_obstacles:
        return strip
    grown: list[gdstk.Polygon] = []
    for obs in ground_obstacles:
        grown.extend(gdstk.offset(obs, min_spacing_um) or [])
    carved = gdstk.boolean([strip], grown, "not", precision=precision)
    if not carved:
        return strip
    return max(carved, key=lambda poly: abs(poly.area()))


def _stroke_series_strip(
    centerline: Sequence[Point],
    holes: Sequence[TaggedPolygon],
    layermap: LayerMap,
    config: SignalBuildConfig,
) -> gdstk.Polygon:
    mte_pair = layermap.pair(config.mte_layer)
    strip = _stroke_polygon(
        centerline, config.plate_width_um, mte_pair[0], mte_pair[1]
    )
    return _clip_strip_from_holes(strip, holes, config.boolean_precision)


def _finalize_series_strip_drc(
    centerline: list[Point],
    body: gdstk.Polygon,
    holes: Sequence[TaggedPolygon],
    ground_obstacles: Sequence[gdstk.Polygon],
    layermap: LayerMap,
    config: SignalBuildConfig,
) -> tuple[gdstk.Polygon, list[Point]]:
    """
  Pick inward offset / ground trim so the strip clears ground MBE.

    The perimeter stroke is centered on the body edge; on filler-facing sides
    half the plate width can protrude into the step-4 MBE filler. Try small
    inward shifts before trimming against grown ground keepouts.
    """
    if not ground_obstacles:
        return _stroke_series_strip(centerline, holes, layermap, config), centerline

    min_um = config.mbe_mte_spacing_um
    precision = config.boolean_precision
    candidates: list[tuple[gdstk.Polygon, list[Point], float, float]] = []

    for inward in (0.0, 3.5, 5.0, 7.0):
        cl = (
            _offset_centerline_inward(centerline, body, inward)
            if inward > 0
            else list(centerline)
        )
        raw = _stroke_series_strip(cl, holes, layermap, config)
        trimmed = _trim_strip_for_ground_clearance(
            raw, ground_obstacles, min_um, precision
        )
        trimmed = _clip_strip_from_holes(trimmed, holes, precision)
        spacing = _min_ground_spacing(trimmed, ground_obstacles, precision)
        if abs(trimmed.area()) < _MIN_STRIP_AREA_UM2:
            continue
        if any(
            gdstk.boolean(trimmed, tag.polygon, "and", precision=precision)
            for tag in holes
        ):
            continue
        candidates.append((trimmed, cl, spacing, abs(trimmed.area())))

    if not candidates:
        strip = _stroke_series_strip(centerline, holes, layermap, config)
        return strip, list(centerline)

    passing = [c for c in candidates if c[2] >= min_um - 1e-6]
    if passing:
        strip, cl, _, _ = max(passing, key=lambda item: item[3])
        return strip, cl
    strip, cl, _, _ = max(candidates, key=lambda item: item[2])
    return strip, cl


def _clip_strip_from_holes(
    strip: gdstk.Polygon,
    holes: Sequence[TaggedPolygon],
    precision: float,
) -> gdstk.Polygon:
    """Remove release-hole interiors so the strip hugs the body edge only."""
    hole_polys = [tag.polygon for tag in holes]
    if not hole_polys:
        return strip
    carved = gdstk.boolean([strip], hole_polys, "not", precision=precision)
    if not carved:
        return strip
    out = carved[0]
    shrunk = gdstk.offset(out, -0.05)
    return shrunk[0] if shrunk else out


def _verify_series_boundary_invariants(
    strip: gdstk.Polygon,
    centerline: Sequence[Point],
    body: gdstk.Polygon,
    hole_a: TaggedPolygon,
    hole_b: TaggedPolygon,
    all_holes: Sequence[TaggedPolygon],
    res: Resonator,
    config: SignalBuildConfig,
) -> None:
    if len(centerline) < 2:
        raise ValueError(
            f"[{res.inst_name}] series MTE centerline has fewer than 2 points"
        )
    if abs(strip.area()) < _MIN_STRIP_AREA_UM2:
        raise ValueError(f"[{res.inst_name}] series MTE strip has zero area")

    tol = config.connect_tolerance_um + 1e-6
    precision = config.boolean_precision
    for endpt, hole in ((centerline[0], hole_a), (centerline[-1], hole_b)):
        d = _min_spacing(
            gdstk.rectangle(
                (endpt[0] - 1.0, endpt[1] - 1.0),
                (endpt[0] + 1.0, endpt[1] + 1.0),
                layer=strip.layer,
                datatype=strip.datatype,
            ),
            hole.polygon,
            precision,
        )
        if d > tol:
            raise ValueError(
                f"[{res.inst_name}] series MTE endpoint ({endpt[0]:.1f}, {endpt[1]:.1f}) "
                f"is {d:.1f}um from release hole {hole.label} (>{tol:.1f}um)"
            )

    for tagged in all_holes:
        if gdstk.boolean(strip, tagged.polygon, "and", precision=precision):
            raise ValueError(
                f"[{res.inst_name}] series MTE strip overlaps release hole {tagged.label}"
            )

    overlap = gdstk.boolean(strip, body, "and", precision=precision)
    if overlap:
        overlap_area = sum(abs(p.area()) for p in overlap)
        strip_area = abs(strip.area())
        if strip_area > 0 and overlap_area > 0.5 * strip_area:
            raise ValueError(
                f"[{res.inst_name}] series MTE strip fills resonator interior "
                f"({overlap_area:.0f}um^2 inside body)"
            )


def build_series_boundary_mte(
    res: Resonator,
    assembly: RtegFrameAssembly,
    release_holes: ReleaseHoles,
    layermap: LayerMap,
    config: SignalBuildConfig,
    *,
    ground_obstacles: Sequence[gdstk.Polygon] | None = None,
) -> tuple[list[gdstk.Polygon], list[Point], str, TaggedPolygon, TaggedPolygon]:
    """
    Build a thin MTE strip along the resonator MBE perimeter between release holes.

    Returns ``(net_polygons, centerline, shape_name, hole_a, hole_b)``.
    """
    precision = config.boolean_precision
    body = _resonator_mbe_body(res, assembly, precision)
    edges = _perimeter_edges(body)
    total = _perimeter_length(edges)
    anchors = _hole_anchors(body, release_holes, precision)
    s0, s1, hole_a, hole_b = _select_signal_gap(anchors, total)
    centerline = _extract_arc_centerline(s0, s1, edges, total)
    if len(centerline) < 2:
        centerline = [hole_a.contact, hole_b.contact]
    holes = release_holes.all_items()
    if ground_obstacles:
        strip, centerline = _finalize_series_strip_drc(
            list(centerline),
            body,
            holes,
            ground_obstacles,
            layermap,
            config,
        )
    else:
        strip = _stroke_series_strip(centerline, holes, layermap, config)
    strip = _clip_strip_from_holes(strip, holes, precision)
    _verify_series_boundary_invariants(
        strip,
        centerline,
        body,
        hole_a.hole,
        hole_b.hole,
        release_holes.all_items(),
        res,
        config,
    )
    return [strip], centerline, "on_resonator", hole_a.hole, hole_b.hole
