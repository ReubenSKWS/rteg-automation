"""
Series resonator MTE — outward offset ring between release holes.

For ``res_type == "series"``, the signal MTE is a thin **filled ring** offset
outward from the resonator MBE body (visible gap + band), clipped to the
perimeter arc between two release-hole anchors (BAW_ReF / BAW_CAV).

Assumptions
-----------
- Resonator outline = boolean-OR of resonator **MBE** polygons in RTEG space.
- Signal arc = shorter perimeter gap between the two smallest touching holes.
- Ring = ``offset(body, margin+band) NOT offset(body, margin)`` on the arc only.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import gdstk

from layermap import LayerMap
from prep_resonator_ppd import resonator_metal_polys
from prep_rteg_frame import RtegFrameAssembly
from rteg_collect import ReleaseHoles, TaggedPolygon, _resonator_shift
from separate import Resonator

if TYPE_CHECKING:
    from rteg_signal import SignalBuildConfig

Point = tuple[float, float]
EdgeMode = Literal["centered", "outward", "inward"]
BuildMode = Literal["offset_ring", "stroke"]
MBE_LAYER = 2
_MIN_STRIP_AREA_UM2 = 1.0
DEFAULT_MARGIN_UM = 2.0
DEFAULT_BAND_UM = 2.0
_ARC_CLIP_PAD_UM = 12.0


@dataclass
class SeriesStripBuildResult:
    """Full series perimeter strip build — used by experiment + export."""

    strip: gdstk.Polygon
    centerline: list[Point]
    shape_name: str
    hole_a: TaggedPolygon
    hole_b: TaggedPolygon
    strip_width_um: float
    edge_mode: EdgeMode
    arc_length_um: float
    strip_area_um2: float
    body_overlap_fraction: float
    min_ground_spacing_um: float
    margin_um: float = DEFAULT_MARGIN_UM
    band_thickness_um: float = DEFAULT_BAND_UM
    build_mode: BuildMode = "offset_ring"
    drc_violations: list[str] = field(default_factory=list)
    used_drc_finalize: bool = False
    body: gdstk.Polygon | None = None

    @property
    def is_drc_clean(self) -> bool:
        return not self.drc_violations

    def summary(self) -> dict[str, object]:
        return {
            "build_mode": self.build_mode,
            "margin_um": round(self.margin_um, 2),
            "band_thickness_um": round(self.band_thickness_um, 2),
            "strip_width_um": self.strip_width_um,
            "edge_mode": self.edge_mode,
            "arc_length_um": round(self.arc_length_um, 1),
            "strip_area_um2": round(self.strip_area_um2, 1),
            "body_overlap_fraction": round(self.body_overlap_fraction, 3),
            "min_ground_spacing_um": round(self.min_ground_spacing_um, 1),
            "used_drc_finalize": self.used_drc_finalize,
            "is_drc_clean": self.is_drc_clean,
            "hole_a": self.hole_a.label,
            "hole_b": self.hole_b.label,
            "drc_violations": self.drc_violations,
            "mte_style": "filled_ring",
        }


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


def resonator_mbe_body(
    res: Resonator, assembly: RtegFrameAssembly, precision: float
) -> gdstk.Polygon:
    """Public alias for experiment tools."""
    return _resonator_mbe_body(res, assembly, precision)


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


def _assign_mte_layer(
    poly: gdstk.Polygon, layermap: LayerMap, config: SignalBuildConfig
) -> gdstk.Polygon:
    """Re-apply BAW_MTE after gdstk booleans that drop layer/datatype."""
    layer, datatype = layermap.pair(config.mte_layer)
    return gdstk.Polygon(list(poly.points), layer, datatype)


def _preserve_strip_layer(source: gdstk.Polygon, result: gdstk.Polygon) -> gdstk.Polygon:
    return gdstk.Polygon(list(result.points), source.layer, source.datatype)


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
    return _preserve_strip_layer(strip, max(carved, key=lambda poly: abs(poly.area())))


def _offset_centerline_normal(
    centerline: Sequence[Point],
    body: gdstk.Polygon,
    offset_um: float,
    *,
    outward: bool,
) -> list[Point]:
    """Shift centerline along outward or inward normal by ``offset_um``."""
    if offset_um <= 0:
        return list(centerline)
    inward_pts = _offset_centerline_inward(centerline, body, offset_um)
    if not outward:
        return inward_pts
    pts = list(centerline)
    out: list[Point] = []
    for i, (pt, inn) in enumerate(zip(pts, inward_pts)):
        out.append(
            (
                pt[0] + (pt[0] - inn[0]),
                pt[1] + (pt[1] - inn[1]),
            )
        )
    return out


def _apply_edge_mode(
    centerline: Sequence[Point],
    body: gdstk.Polygon,
    strip_width_um: float,
    edge_mode: EdgeMode,
) -> list[Point]:
    half = strip_width_um / 2.0
    if edge_mode == "centered":
        return list(centerline)
    if edge_mode == "inward":
        return _offset_centerline_inward(centerline, body, half)
    # Thin strips need extra exterior offset so hole booleans remain stable.
    outward_offset = half if strip_width_um >= 8.0 else strip_width_um * 2.0
    return _offset_centerline_normal(centerline, body, outward_offset, outward=True)


def _centerline_length(centerline: Sequence[Point]) -> float:
    total = 0.0
    for i in range(1, len(centerline)):
        total += math.hypot(
            centerline[i][0] - centerline[i - 1][0],
            centerline[i][1] - centerline[i - 1][1],
        )
    return total


def _body_overlap_fraction(
    strip: gdstk.Polygon, body: gdstk.Polygon, precision: float
) -> float:
    overlap = gdstk.boolean(strip, body, "and", precision=precision)
    if not overlap:
        return 0.0
    strip_area = abs(strip.area())
    if strip_area <= 0:
        return 0.0
    return sum(abs(p.area()) for p in overlap) / strip_area


def check_series_strip_drc(
    strip: gdstk.Polygon,
    ground_obstacles: Sequence[gdstk.Polygon],
    min_spacing_um: float,
    precision: float,
) -> tuple[float, list[str]]:
    """Return (min_ground_spacing_um, violation messages)."""
    violations: list[str] = []
    min_ground = _min_ground_spacing(strip, ground_obstacles, precision)
    if min_ground < min_spacing_um - 1e-6:
        violations.append(
            f"series MTE/ground MBE spacing: {min_ground:.1f}um < {min_spacing_um:.0f}um"
        )
    if min_ground == float("inf"):
        min_ground = float("nan")
    return min_ground, violations


def _offset_polygon_outward(
    poly: gdstk.Polygon, distance_um: float, precision: float
) -> gdstk.Polygon | None:
    if distance_um <= 0:
        return poly
    parts = gdstk.offset(poly, distance_um)
    if not parts:
        return None
    return max(parts, key=lambda p: abs(p.area()))


def _build_outward_ring(
    body: gdstk.Polygon,
    margin_um: float,
    band_thickness_um: float,
    precision: float,
) -> gdstk.Polygon:
    """Filled annulus: offset(body, margin+band) NOT offset(body, margin)."""
    if margin_um <= 0 or band_thickness_um <= 0:
        raise ValueError("margin_um and band_thickness_um must be positive")
    inner = _offset_polygon_outward(body, margin_um, precision)
    outer = _offset_polygon_outward(body, margin_um + band_thickness_um, precision)
    if inner is None or outer is None:
        raise ValueError("could not grow resonator body for outward MTE ring")
    ring_parts = gdstk.boolean(outer, inner, "not", precision=precision)
    if not ring_parts:
        raise ValueError("outward ring boolean failed")
    return max(ring_parts, key=lambda p: abs(p.area()))


def _clip_ring_to_arc(
    ring: gdstk.Polygon,
    body: gdstk.Polygon,
    arc_centerline: Sequence[Point],
    margin_um: float,
    band_thickness_um: float,
    precision: float,
) -> gdstk.Polygon:
    """Keep only the ring segment spanning the release-hole arc."""
    if len(arc_centerline) < 2:
        raise ValueError("arc centerline has fewer than 2 points")
    mid_offset = margin_um + band_thickness_um / 2.0
    midline = _offset_centerline_normal(
        arc_centerline, body, mid_offset, outward=True
    )
    corridor_w = band_thickness_um + 2.0 * margin_um + _ARC_CLIP_PAD_UM
    corridor = _stroke_polygon(midline, corridor_w, 0, 0)
    clipped = gdstk.boolean(ring, corridor, "and", precision=precision)
    if not clipped:
        raise ValueError("arc corridor removed entire outward ring")
    return max(clipped, key=lambda p: abs(p.area()))


def _ring_midline(
    arc_centerline: Sequence[Point],
    body: gdstk.Polygon,
    margin_um: float,
    band_thickness_um: float,
    hole_a: _HoleAnchor,
    hole_b: _HoleAnchor,
) -> list[Point]:
    mid = margin_um + band_thickness_um / 2.0
    centerline = _offset_centerline_normal(arc_centerline, body, mid, outward=True)
    if len(centerline) >= 2:
        centerline[0] = hole_a.contact
        centerline[-1] = hole_b.contact
    return centerline


def _build_offset_ring_strip(
    body: gdstk.Polygon,
    arc_centerline: Sequence[Point],
    holes: Sequence[TaggedPolygon],
    layermap: LayerMap,
    config: SignalBuildConfig,
    *,
    margin_um: float,
    band_thickness_um: float,
    hole_a: _HoleAnchor,
    hole_b: _HoleAnchor,
) -> tuple[gdstk.Polygon, list[Point]]:
    precision = config.boolean_precision
    ring = _build_outward_ring(body, margin_um, band_thickness_um, precision)
    arc_strip = _clip_ring_to_arc(
        ring, body, arc_centerline, margin_um, band_thickness_um, precision
    )
    arc_strip = _clip_strip_from_holes(arc_strip, holes, precision)
    mte_pair = layermap.pair(config.mte_layer)
    strip = gdstk.Polygon(
        list(arc_strip.points), mte_pair[0], mte_pair[1]
    )
    centerline = _ring_midline(
        arc_centerline, body, margin_um, band_thickness_um, hole_a, hole_b
    )
    return strip, centerline


def _finalize_offset_ring_drc(
    body: gdstk.Polygon,
    arc_centerline: list[Point],
    holes: Sequence[TaggedPolygon],
    ground_obstacles: Sequence[gdstk.Polygon],
    layermap: LayerMap,
    config: SignalBuildConfig,
    *,
    margin_um: float,
    band_thickness_um: float,
    hole_a: _HoleAnchor,
    hole_b: _HoleAnchor,
) -> tuple[gdstk.Polygon, list[Point], bool]:
    """Increase outward margin and/or trim ground until DRC passes."""
    if not ground_obstacles:
        strip, centerline = _build_offset_ring_strip(
            body,
            arc_centerline,
            holes,
            layermap,
            config,
            margin_um=margin_um,
            band_thickness_um=band_thickness_um,
            hole_a=hole_a,
            hole_b=hole_b,
        )
        return strip, centerline, False

    min_um = config.mbe_mte_spacing_um
    precision = config.boolean_precision
    candidates: list[tuple[gdstk.Polygon, list[Point], float, float]] = []

    for margin_delta in (0.0, 1.0, 2.0, 3.0, 5.0):
        try:
            strip, centerline = _build_offset_ring_strip(
                body,
                arc_centerline,
                holes,
                layermap,
                config,
                margin_um=margin_um + margin_delta,
                band_thickness_um=band_thickness_um,
                hole_a=hole_a,
                hole_b=hole_b,
            )
        except ValueError:
            continue
        trimmed = _trim_strip_for_ground_clearance(
            strip, ground_obstacles, min_um, precision
        )
        trimmed = _clip_strip_from_holes(trimmed, holes, precision)
        if abs(trimmed.area()) < _MIN_STRIP_AREA_UM2:
            continue
        if any(
            gdstk.boolean(trimmed, tag.polygon, "and", precision=precision)
            for tag in holes
        ):
            continue
        spacing = _min_ground_spacing(trimmed, ground_obstacles, precision)
        candidates.append((trimmed, centerline, spacing, abs(trimmed.area())))

    if not candidates:
        strip, centerline = _build_offset_ring_strip(
            body,
            arc_centerline,
            holes,
            layermap,
            config,
            margin_um=margin_um,
            band_thickness_um=band_thickness_um,
            hole_a=hole_a,
            hole_b=hole_b,
        )
        return strip, centerline, False

    passing = [c for c in candidates if c[2] >= min_um - 1e-6]
    if passing:
        strip, cl, _, _ = max(passing, key=lambda item: item[3])
        return strip, cl, True
    strip, cl, _, _ = max(candidates, key=lambda item: item[2])
    return strip, cl, True


def _stroke_series_strip(
    centerline: Sequence[Point],
    holes: Sequence[TaggedPolygon],
    layermap: LayerMap,
    config: SignalBuildConfig,
    *,
    strip_width_um: float | None = None,
) -> gdstk.Polygon:
    mte_pair = layermap.pair(config.mte_layer)
    width = strip_width_um if strip_width_um is not None else config.plate_width_um
    strip = _stroke_polygon(centerline, width, mte_pair[0], mte_pair[1])
    return _clip_strip_from_holes(strip, holes, config.boolean_precision)


def _finalize_series_strip_drc(
    centerline: list[Point],
    body: gdstk.Polygon,
    holes: Sequence[TaggedPolygon],
    ground_obstacles: Sequence[gdstk.Polygon],
    layermap: LayerMap,
    config: SignalBuildConfig,
    *,
    strip_width_um: float,
    edge_mode: EdgeMode = "centered",
) -> tuple[gdstk.Polygon, list[Point], bool]:
    """
  Pick inward offset / ground trim so the strip clears ground MBE.

    The perimeter stroke is centered on the body edge; on filler-facing sides
    half the plate width can protrude into the step-4 MBE filler. Try small
    inward shifts before trimming against grown ground keepouts.
    """
    if not ground_obstacles:
        cl = _apply_edge_mode(centerline, body, strip_width_um, edge_mode)
        return (
            _stroke_series_strip(
                cl, holes, layermap, config, strip_width_um=strip_width_um
            ),
            cl,
            False,
        )

    min_um = config.mbe_mte_spacing_um
    precision = config.boolean_precision
    candidates: list[tuple[gdstk.Polygon, list[Point], float, float]] = []

    for inward in (0.0, 3.5, 5.0, 7.0):
        base = _apply_edge_mode(centerline, body, strip_width_um, edge_mode)
        cl = (
            _offset_centerline_inward(base, body, inward)
            if inward > 0
            else list(base)
        )
        raw = _stroke_series_strip(
            cl, holes, layermap, config, strip_width_um=strip_width_um
        )
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
        cl = _apply_edge_mode(centerline, body, strip_width_um, edge_mode)
        return (
            _stroke_series_strip(
                cl, holes, layermap, config, strip_width_um=strip_width_um
            ),
            cl,
            False,
        )

    passing = [c for c in candidates if c[2] >= min_um - 1e-6]
    if passing:
        strip, cl, _, _ = max(passing, key=lambda item: item[3])
        return strip, cl, True
    strip, cl, _, _ = max(candidates, key=lambda item: item[2])
    return strip, cl, True


def _clip_strip_from_holes(
    strip: gdstk.Polygon,
    holes: Sequence[TaggedPolygon],
    precision: float,
) -> gdstk.Polygon:
    """Remove release-hole interiors so the strip hugs the body edge only."""
    hole_polys = [tag.polygon for tag in holes]
    if not hole_polys:
        return strip

    def _usable(poly: gdstk.Polygon) -> bool:
        return abs(poly.area()) >= _MIN_STRIP_AREA_UM2

    carved = gdstk.boolean([strip], hole_polys, "not", precision=precision)
    if carved and _usable(carved[0]):
        out = carved[0]
    else:
        fragments = [strip]
        for tag in holes:
            grown = gdstk.offset(tag.polygon, 0.05)
            hp = grown[0] if grown else tag.polygon
            nxt: list[gdstk.Polygon] = []
            for frag in fragments:
                parts = gdstk.boolean([frag], [hp], "not", precision=precision)
                if parts:
                    nxt.extend(parts)
            fragments = nxt
        fragments = [f for f in fragments if _usable(f)]
        if not fragments:
            return strip
        out = fragments[0]
        for frag in fragments[1:]:
            united = gdstk.boolean(out, frag, "or", precision=precision)
            if united:
                out = united[0]

    shrunk = gdstk.offset(out, -0.05)
    result = shrunk[0] if shrunk else out
    return _preserve_strip_layer(strip, result)


def _verify_series_boundary_invariants(
    strip: gdstk.Polygon,
    centerline: Sequence[Point],
    body: gdstk.Polygon,
    hole_a: TaggedPolygon,
    hole_b: TaggedPolygon,
    all_holes: Sequence[TaggedPolygon],
    res: Resonator,
    config: SignalBuildConfig,
    *,
    build_mode: BuildMode = "offset_ring",
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
        if tagged.label in (hole_a.label, hole_b.label):
            continue
        if gdstk.boolean(strip, tagged.polygon, "and", precision=precision):
            raise ValueError(
                f"[{res.inst_name}] series MTE strip overlaps release hole {tagged.label}"
            )

    overlap = gdstk.boolean(strip, body, "and", precision=precision)
    if overlap:
        overlap_area = sum(abs(p.area()) for p in overlap)
        strip_area = abs(strip.area())
        if build_mode == "offset_ring":
            if overlap_area > max(1.0, 0.02 * strip_area):
                raise ValueError(
                    f"[{res.inst_name}] outward MTE ring overlaps resonator body "
                    f"({overlap_area:.1f}um^2)"
                )
        elif strip_area > 0 and overlap_area > 0.5 * strip_area:
            raise ValueError(
                f"[{res.inst_name}] series MTE strip fills resonator interior "
                f"({overlap_area:.0f}um^2 inside body)"
            )


def build_series_strip(
    res: Resonator,
    assembly: RtegFrameAssembly,
    release_holes: ReleaseHoles,
    layermap: LayerMap,
    config: SignalBuildConfig,
    *,
    margin_um: float | None = None,
    band_thickness_um: float | None = None,
    strip_width_um: float | None = None,
    edge_mode: EdgeMode = "outward",
    build_mode: BuildMode = "offset_ring",
    apply_drc_finalize: bool = True,
    ground_obstacles: Sequence[gdstk.Polygon] | None = None,
    verify: bool = True,
) -> SeriesStripBuildResult:
    """
    Build a series MTE strip — default is an outward offset filled ring on the arc.
    """
    precision = config.boolean_precision
    margin = margin_um if margin_um is not None else DEFAULT_MARGIN_UM
    band = (
        band_thickness_um
        if band_thickness_um is not None
        else (strip_width_um if strip_width_um is not None else DEFAULT_BAND_UM)
    )
    body = _resonator_mbe_body(res, assembly, precision)
    edges = _perimeter_edges(body)
    total = _perimeter_length(edges)
    anchors = _hole_anchors(body, release_holes, precision)
    s0, s1, hole_a, hole_b = _select_signal_gap(anchors, total)
    base_centerline = _extract_arc_centerline(s0, s1, edges, total)
    if len(base_centerline) < 2:
        base_centerline = [hole_a.contact, hole_b.contact]
    arc_length = _centerline_length(base_centerline)
    holes = release_holes.all_items()
    used_finalize = False

    if build_mode == "offset_ring":
        if ground_obstacles and apply_drc_finalize:
            strip, centerline, used_finalize = _finalize_offset_ring_drc(
                body,
                list(base_centerline),
                holes,
                ground_obstacles,
                layermap,
                config,
                margin_um=margin,
                band_thickness_um=band,
                hole_a=hole_a,
                hole_b=hole_b,
            )
        else:
            strip, centerline = _build_offset_ring_strip(
                body,
                base_centerline,
                holes,
                layermap,
                config,
                margin_um=margin,
                band_thickness_um=band,
                hole_a=hole_a,
                hole_b=hole_b,
            )
    elif ground_obstacles and apply_drc_finalize:
        width = strip_width_um if strip_width_um is not None else config.plate_width_um
        strip, centerline, used_finalize = _finalize_series_strip_drc(
            list(base_centerline),
            body,
            holes,
            ground_obstacles,
            layermap,
            config,
            strip_width_um=width,
            edge_mode=edge_mode,
        )
        strip = _clip_strip_from_holes(strip, holes, precision)
        band = width
    else:
        width = strip_width_um if strip_width_um is not None else config.plate_width_um
        centerline = _apply_edge_mode(base_centerline, body, width, edge_mode)
        strip = _stroke_series_strip(
            centerline, holes, layermap, config, strip_width_um=width
        )
        strip = _clip_strip_from_holes(strip, holes, precision)
        band = width

    if verify:
        _verify_series_boundary_invariants(
            strip,
            centerline,
            body,
            hole_a.hole,
            hole_b.hole,
            holes,
            res,
            config,
            build_mode=build_mode,
        )

    strip = _assign_mte_layer(strip, layermap, config)

    min_clear = float("nan")
    drc_violations: list[str] = []
    if ground_obstacles:
        min_clear, drc_violations = check_series_strip_drc(
            strip,
            ground_obstacles,
            config.mbe_mte_spacing_um,
            precision,
        )

    return SeriesStripBuildResult(
        strip=strip,
        centerline=list(centerline),
        shape_name="on_resonator",
        hole_a=hole_a.hole,
        hole_b=hole_b.hole,
        strip_width_um=band,
        edge_mode=edge_mode,
        margin_um=margin,
        band_thickness_um=band,
        build_mode=build_mode,
        arc_length_um=arc_length,
        strip_area_um2=abs(strip.area()),
        body_overlap_fraction=_body_overlap_fraction(strip, body, precision),
        min_ground_spacing_um=min_clear,
        drc_violations=drc_violations,
        used_drc_finalize=used_finalize,
        body=body,
    )


def build_series_boundary_mte(
    res: Resonator,
    assembly: RtegFrameAssembly,
    release_holes: ReleaseHoles,
    layermap: LayerMap,
    config: SignalBuildConfig,
    *,
    margin_um: float | None = None,
    band_thickness_um: float | None = None,
    strip_width_um: float | None = None,
    edge_mode: EdgeMode = "outward",
    build_mode: BuildMode = "offset_ring",
    apply_drc_finalize: bool = True,
    ground_obstacles: Sequence[gdstk.Polygon] | None = None,
) -> tuple[list[gdstk.Polygon], list[Point], str, TaggedPolygon, TaggedPolygon]:
    """
    Build a thin MTE strip along the resonator MBE perimeter between release holes.

    Returns ``(net_polygons, centerline, shape_name, hole_a, hole_b)``.
    """
    result = build_series_strip(
        res,
        assembly,
        release_holes,
        layermap,
        config,
        margin_um=margin_um,
        band_thickness_um=band_thickness_um,
        strip_width_um=strip_width_um,
        edge_mode=edge_mode,
        build_mode=build_mode,
        apply_drc_finalize=apply_drc_finalize,
        ground_obstacles=ground_obstacles,
        verify=True,
    )
    return (
        [result.strip],
        result.centerline,
        result.shape_name,
        result.hole_a,
        result.hole_b,
    )
