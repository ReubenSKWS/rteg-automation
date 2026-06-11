"""
Step 5.3 — Build the signal (MTE) net.

**Shunt:** connects preserved filter MTE to the classified **signal** GSG pad
with a shaped connector plate (45/90° segments only), then boolean-unions
preserved MTE + connector into one MTE polygon.

**Series:** a thin MTE strip along the resonator MBE perimeter between two
release holes — no pad-directed connector and no GSG signal pad
(``on_resonator`` mode).

Signal probe pads are MBE; shunt connectors are extended to meet them within
``connect_tolerance_um`` so downstream carving can treat the full signal path
as a keepout.

Public API
----------
``signal_endpoints``   — facing launch points between preserved MTE and signal pad
``build_signal_plate`` — orthogonal connector polygon between those points
``union_preserved_mte_net`` — OR preserved MTE only (series / on_resonator)
``union_signal_net``   — OR preserved MTE + connector into one MTE net
``build_signal_net``   — orchestrator + DRC vs ground MBE
``export_signal_rteg_gds`` — write full framed RTEG + MTE connector to GDS
``preview_signal_net_svg`` — SVG preview for notebooks
"""
from __future__ import annotations

import math
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import gdstk

from export_gds import ExportResult, export_gds
from layermap import LayerMap
from prep_rteg_frame import RtegFrameAssembly
from rteg_classify import NodeClassification
from rteg_collect import GroundPlates, PreservedMetal, ReleaseHoles, TaggedPolygon
from separate import Resonator

Point = tuple[float, float]
Edge = tuple[Point, Point]

_ANGLE_TOL_DEG = 0.5
_JOG_STEP_UM = 2.0
_DEFAULT_JOG_MARGIN_UM = 80.0


@dataclass(frozen=True)
class SignalBuildConfig:
    """Tunables for MTE connector geometry and DRC."""

    mte_layer: str = "BAW_MTE"
    mbe_layer: str = "BAW_MBE"
    mbe_mte_spacing_um: float = 14.0
    connect_tolerance_um: float = 0.5
    plate_width_um: float = 14.0
    boolean_precision: float = 1e-3
    jog_search_margin_um: float = 80.0


@dataclass
class SignalEndpoints:
    """Facing launch pair between preserved MTE and the signal node."""

    preserved: TaggedPolygon
    signal_pad: TaggedPolygon | None
    metal_point: Point
    pad_point: Point
    metal_edge: Edge
    pad_edge: Edge
    clearance_um: float

    def summary(self) -> dict[str, object]:
        row: dict[str, object] = {
            "preserved_label": self.preserved.label,
            "metal_point": (round(self.metal_point[0], 1), round(self.metal_point[1], 1)),
            "pad_point": (round(self.pad_point[0], 1), round(self.pad_point[1], 1)),
            "clearance_um": (
                round(self.clearance_um, 1)
                if not math.isnan(self.clearance_um)
                else None
            ),
            "metal_edge": (
                (round(self.metal_edge[0][0], 1), round(self.metal_edge[0][1], 1)),
                (round(self.metal_edge[1][0], 1), round(self.metal_edge[1][1], 1)),
            ),
        }
        if self.signal_pad is not None:
            row["pad_edge"] = (
                (round(self.pad_edge[0][0], 1), round(self.pad_edge[0][1], 1)),
                (round(self.pad_edge[1][0], 1), round(self.pad_edge[1][1], 1)),
            )
        else:
            row["pad_edge"] = None
        return row


@dataclass
class SignalPlate:
    """Connector plate between preserved MTE and the signal pad."""

    polygon: gdstk.Polygon
    centerline: list[Point]
    shape_name: str


@dataclass
class SignalNetResult:
    """Fused signal net ready for ground carve keepouts."""

    endpoints: SignalEndpoints
    connector: SignalPlate
    net_polygons: list[gdstk.Polygon]
    signal_pad_polygons: list[gdstk.Polygon]
    n_net_polygons: int
    is_connected: bool
    reaches_pad: bool
    min_ground_spacing_um: float
    drc_violations: list[str] = field(default_factory=list)

    @property
    def is_on_resonator(self) -> bool:
        return self.connector.shape_name == "on_resonator"

    @property
    def is_success(self) -> bool:
        if self.is_on_resonator:
            return self.is_connected and not self.drc_violations
        return self.is_connected and self.reaches_pad and not self.drc_violations

    def summary(self) -> dict[str, object]:
        return {
            "n_net_polygons": self.n_net_polygons,
            "is_connected": self.is_connected,
            "reaches_pad": self.reaches_pad,
            "is_success": self.is_success,
            "shape": self.connector.shape_name,
            "min_ground_spacing_um": round(self.min_ground_spacing_um, 1),
            "drc_violations": len(self.drc_violations),
            "clearance_um": round(self.endpoints.clearance_um, 1),
        }


# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #
def _min_spacing(poly_a: gdstk.Polygon, poly_b: gdstk.Polygon) -> tuple[float, Point, Point]:
    if gdstk.boolean(poly_a, poly_b, "and", precision=1e-3):
        p = poly_a.points[0]
        q = (float(p[0]), float(p[1]))
        return 0.0, q, q
    best = float("inf")
    best_p: Point = (0.0, 0.0)
    best_q: Point = (0.0, 0.0)
    for pa in poly_a.points:
        for pb in poly_b.points:
            d = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
            if d < best:
                best = d
                best_p = (float(pa[0]), float(pa[1]))
                best_q = (float(pb[0]), float(pb[1]))
    return best, best_p, best_q


def _min_spacing_to_many(
    poly: gdstk.Polygon, obstacles: Sequence[gdstk.Polygon]
) -> tuple[float, Point]:
    best = float("inf")
    where: Point = (0.0, 0.0)
    for obs in obstacles:
        d, p, _ = _min_spacing(poly, obs)
        if d < best:
            best = d
            where = p
    return best, where


def _bbox_center(bb: tuple[Point, Point]) -> Point:
    return ((bb[0][0] + bb[1][0]) / 2.0, (bb[0][1] + bb[1][1]) / 2.0)


def _facing_edge(bb: tuple[Point, Point], toward: Point) -> Edge:
    """Side of axis-aligned ``bb`` that faces ``toward``."""
    (x0, y0), (x1, y1) = bb
    cx, cy = _bbox_center(bb)
    tx, ty = toward
    if abs(tx - cx) >= abs(ty - cy):
        return ((x0, y0), (x0, y1)) if tx < cx else ((x1, y0), (x1, y1))
    return ((x0, y0), (x1, y0)) if ty < cy else ((x0, y1), (x1, y1))


def _launch_on_edge(edge: Edge, toward: Point) -> Point:
    """Point on ``edge`` closest to ``toward`` (clamped to the segment)."""
    (x0, y0), (x1, y1) = edge
    if abs(x0 - x1) < 1e-6:
        y = max(min(toward[1], max(y0, y1)), min(y0, y1))
        return (x0, y)
    x = max(min(toward[0], max(x0, x1)), min(x0, x1))
    return (x, y0)


def _segment_is_45_90(p1: Point, p2: Point) -> bool:
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return False
    angle = math.degrees(math.atan2(dy, dx)) % 45.0
    return min(angle, 45.0 - angle) <= _ANGLE_TOL_DEG


def _centerline_length(centerline: Sequence[Point]) -> float:
    return sum(
        math.hypot(centerline[i][0] - centerline[i - 1][0], centerline[i][1] - centerline[i - 1][1])
        for i in range(1, len(centerline))
    )


def _extend_into_bbox(pt: Point, bb: tuple[Point, Point], extend_um: float) -> Point:
    """Nudge ``pt`` toward the interior of ``bb`` for boolean overlap."""
    if extend_um <= 0:
        return pt
    cx, cy = _bbox_center(bb)
    dx, dy = cx - pt[0], cy - pt[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return pt
    scale = extend_um / length
    return (pt[0] + dx * scale, pt[1] + dy * scale)


def _extend_centerline(
    centerline: list[Point],
    extend_um: float,
    *,
    metal_bb: tuple[Point, Point] | None = None,
    pad_bb: tuple[Point, Point] | None = None,
) -> list[Point]:
    """Extend launch points into preserved MTE and the signal pad for union overlap."""
    if len(centerline) < 2 or extend_um <= 0:
        return list(centerline)
    out = list(centerline)

    def _step_outward(a: Point, b: Point) -> Point:
        dx, dy = a[0] - b[0], a[1] - b[1]
        length = math.hypot(dx, dy)
        if length < 1e-9:
            return a
        scale = extend_um / length
        return (a[0] + dx * scale, a[1] + dy * scale)

    if metal_bb is not None:
        out[0] = _extend_into_bbox(out[0], metal_bb, extend_um)
    else:
        out[0] = _step_outward(out[0], out[1])
    if pad_bb is not None:
        out[-1] = _extend_into_bbox(out[-1], pad_bb, extend_um)
    return out


def _stroke_polygon(
    centerline: Sequence[Point],
    width: float,
    layer: int,
    datatype: int,
) -> gdstk.Polygon:
    flex = gdstk.FlexPath(list(centerline), width, layer=layer, datatype=datatype)
    polys = flex.to_polygons()
    if not polys:
        raise ValueError("centerline produced no stroke polygon")
    return polys[0]


def _union_polys(
    polys: Sequence[gdstk.Polygon], precision: float
) -> list[gdstk.Polygon]:
    if not polys:
        return []
    acc: list[gdstk.Polygon] = [polys[0]]
    for poly in polys[1:]:
        nxt = gdstk.boolean(acc, poly, "or", precision=precision)
        acc = nxt if nxt else acc + [poly]
    return acc


def _infer_plate_width(preserved: TaggedPolygon, config: SignalBuildConfig) -> float:
    bb = preserved.bbox
    if bb is None:
        return config.plate_width_um
    w = min(bb[1][0] - bb[0][0], bb[1][1] - bb[0][1])
    return max(config.plate_width_um, min(w, 2 * config.plate_width_um))


def _spacing_violates(
    poly: gdstk.Polygon,
    obstacles: Sequence[gdstk.Polygon],
    min_um: float,
    precision: float,
) -> tuple[bool, float, Point]:
    """True when ``poly`` overlaps or encroaches within ``min_um`` of ground MBE."""
    worst = float("inf")
    where: Point = (0.0, 0.0)
    for obs in obstacles:
        if gdstk.boolean(poly, obs, "and", precision=precision):
            return True, 0.0, where
        grown = gdstk.offset(obs, min_um)
        if grown and gdstk.boolean(poly, grown, "and", precision=precision):
            return True, 0.0, where
        d, p, _ = _min_spacing(poly, obs)
        if d < worst:
            worst = d
            where = p
    return False, worst, where


def _path_net_polygon(
    net_polys: Sequence[gdstk.Polygon], connector: gdstk.Polygon, precision: float
) -> gdstk.Polygon | None:
    for net in net_polys:
        if gdstk.boolean(net, connector, "and", precision=precision):
            return net
    return None


def _ground_mbe_obstacles(
    classification: NodeClassification,
    ground_plates: GroundPlates,
    layermap: LayerMap,
    config: SignalBuildConfig,
) -> list[gdstk.Polygon]:
    """Ground-net MBE only (non-signal GSG bands + filler)."""
    mbe_pair = layermap.pair(config.mbe_layer)
    out: list[gdstk.Polygon] = []
    for node in classification.nodes:
        if node.net == "ground":
            for tagged in node.polygons:
                if layermap.pair(tagged.layer_name) == mbe_pair:
                    out.append(tagged.polygon)
    for tagged in ground_plates.filler:
        if layermap.pair(tagged.layer_name) == mbe_pair:
            out.append(tagged.polygon)
    return out


def _signal_pad_polygons(
    classification: NodeClassification,
    layermap: LayerMap,
    config: SignalBuildConfig,
) -> list[gdstk.Polygon]:
    mbe_pair = layermap.pair(config.mbe_layer)
    return [
        tag.polygon
        for tag in classification.signal_polygons()
        if layermap.pair(tag.layer_name) == mbe_pair
    ]


# --------------------------------------------------------------------------- #
# Public steps
# --------------------------------------------------------------------------- #
def signal_endpoints(
    preserved: PreservedMetal,
    classification: NodeClassification,
    config: SignalBuildConfig | None = None,
) -> SignalEndpoints:
    """
    Facing launch pair between preserved MTE and the classified signal node.

    Picks the preserved MTE polygon with the shortest approach to the signal
    band, then places launch points on the mutually facing edges.
    """
    cfg = config or SignalBuildConfig()
    signal_polys = classification.signal_polygons()
    if not preserved.mte:
        raise ValueError("no preserved MTE to route from")
    if not signal_polys:
        raise ValueError("no signal-node polygons in classification")

    best_d = float("inf")
    best_mte: TaggedPolygon | None = None
    best_pad_tag: TaggedPolygon | None = None

    signal_gds = [t.polygon for t in signal_polys]
    for mte_tag in preserved.mte:
        for sig_tag, sig_poly in zip(signal_polys, signal_gds, strict=True):
            d, _, _ = _min_spacing(mte_tag.polygon, sig_poly)
            if d < best_d:
                best_d = d
                best_mte = mte_tag
                best_pad_tag = sig_tag

    assert best_mte is not None and best_pad_tag is not None
    mte_bb = best_mte.bbox or ((0.0, 0.0), (0.0, 0.0))
    pad_bb = best_pad_tag.bbox or ((0.0, 0.0), (0.0, 0.0))
    pad_center = _bbox_center(pad_bb)
    metal_center = _bbox_center(mte_bb)

    metal_edge = _facing_edge(mte_bb, pad_center)
    pad_edge = _facing_edge(pad_bb, metal_center)
    metal_point = _launch_on_edge(metal_edge, pad_center)
    pad_point = _launch_on_edge(pad_edge, metal_center)

    return SignalEndpoints(
        preserved=best_mte,
        signal_pad=best_pad_tag,
        metal_point=metal_point,
        pad_point=pad_point,
        metal_edge=metal_edge,
        pad_edge=pad_edge,
        clearance_um=best_d,
    )


def _route_candidates(
    p1: Point, p2: Point, *, margin_um: float = _DEFAULT_JOG_MARGIN_UM
) -> list[tuple[str, list[Point]]]:
    """Orthogonal / 45° centerline options between two launch points."""
    x1, y1 = p1
    x2, y2 = p2
    out: list[tuple[str, list[Point]]] = []

    if abs(x1 - x2) < 1e-6 or abs(y1 - y2) < 1e-6:
        out.append(("straight", [p1, p2]))
    else:
        out.append(("route_L", [p1, (x2, y1), p2]))
        out.append(("route_L", [p1, (x1, y2), p2]))
        corner_45 = (x2, y1) if abs(x2 - x1) >= abs(y2 - y1) else (x1, y2)
        out.append(("route_45", [p1, corner_45, p2]))

        y_lo = min(y1, y2) - margin_um
        y_hi = max(y1, y2) + margin_um
        y = y_lo
        while y <= y_hi + 1e-6:
            out.append(("route_Z", [p1, (x1, y), (x2, y), p2]))
            out.append(("route_Z", [p1, (x2, y1), (x2, y), p2]))
            y += _JOG_STEP_UM

        x_lo = min(x1, x2) - margin_um
        x_hi = max(x1, x2) + margin_um
        x = x_lo
        while x <= x_hi + 1e-6:
            out.append(("route_Z", [p1, (x, y1), (x, y2), p2]))
            out.append(("route_Z", [p1, (x, y1), (x2, y1), p2]))
            x += _JOG_STEP_UM

    seen: set[tuple[Point, ...]] = set()
    unique: list[tuple[str, list[Point]]] = []
    for name, cl in out:
        key = tuple(cl)
        if key in seen:
            continue
        seen.add(key)
        unique.append((name, cl))
    return unique


def build_signal_plate(
    endpoints: SignalEndpoints,
    layermap: LayerMap,
    config: SignalBuildConfig | None = None,
    *,
    ground_obstacles: Sequence[gdstk.Polygon] | None = None,
) -> SignalPlate:
    """
    Shaped MTE connector plate between ``endpoints`` (45/90° only).

    Tries straight / L / 45 / Z candidates and picks the shortest that satisfies
    ``mbe_mte_spacing_um`` vs ground MBE when obstacles are provided.
    """
    cfg = config or SignalBuildConfig()
    mte_pair = layermap.pair(cfg.mte_layer)
    width = _infer_plate_width(endpoints.preserved, cfg)
    p1, p2 = endpoints.metal_point, endpoints.pad_point

    metal_bb = endpoints.preserved.bbox
    pad_bb = endpoints.signal_pad.bbox
    extend_um = max(cfg.connect_tolerance_um, width * 0.5)

    best: SignalPlate | None = None
    best_len = float("inf")
    fallback: SignalPlate | None = None
    fallback_len = float("inf")

    for shape_name, centerline in _route_candidates(
        p1, p2, margin_um=cfg.jog_search_margin_um
    ):
        for i in range(1, len(centerline)):
            if not _segment_is_45_90(centerline[i - 1], centerline[i]):
                break
        else:
            extended = _extend_centerline(
                centerline,
                extend_um,
                metal_bb=metal_bb,
                pad_bb=pad_bb,
            )
            poly = _stroke_polygon(extended, width, mte_pair[0], mte_pair[1])
            length = _centerline_length(centerline)
            if ground_obstacles:
                violates, _, _ = _spacing_violates(
                    poly, ground_obstacles, cfg.mbe_mte_spacing_um, cfg.boolean_precision
                )
                if violates:
                    if length < fallback_len:
                        fallback_len = length
                        fallback = SignalPlate(
                            polygon=poly,
                            centerline=extended,
                            shape_name=shape_name,
                        )
                    continue
            if length < best_len:
                best_len = length
                best = SignalPlate(
                    polygon=poly, centerline=extended, shape_name=shape_name
                )

    if best is not None:
        return best
    if fallback is not None:
        return fallback

    centerline = _extend_centerline(
        [p1, p2],
        extend_um,
        metal_bb=metal_bb,
        pad_bb=pad_bb,
    )
    poly = _stroke_polygon(centerline, width, mte_pair[0], mte_pair[1])
    return SignalPlate(polygon=poly, centerline=centerline, shape_name="straight")


def union_preserved_mte_net(
    preserved: PreservedMetal,
    layermap: LayerMap,
    config: SignalBuildConfig | None = None,
) -> list[gdstk.Polygon]:
    """Boolean-OR preserved MTE polygons only (series / on-resonator signal net)."""
    cfg = config or SignalBuildConfig()
    mte_pair = layermap.pair(cfg.mte_layer)
    parts: list[gdstk.Polygon] = [
        tag.polygon
        for tag in preserved.mte
        if layermap.pair(tag.layer_name) == mte_pair
    ]
    return _union_polys(parts, cfg.boolean_precision)


def union_signal_net(
    preserved: PreservedMetal,
    connector: SignalPlate,
    layermap: LayerMap,
    config: SignalBuildConfig | None = None,
) -> list[gdstk.Polygon]:
    """Boolean-OR all preserved MTE polygons with the connector plate."""
    cfg = config or SignalBuildConfig()
    mte_pair = layermap.pair(cfg.mte_layer)
    parts: list[gdstk.Polygon] = [
        tag.polygon
        for tag in preserved.mte
        if layermap.pair(tag.layer_name) == mte_pair
    ]
    parts.append(connector.polygon)
    return _union_polys(parts, cfg.boolean_precision)


def _series_signal_endpoints(
    preserved: PreservedMetal,
    arc_start: Point,
    arc_end: Point,
) -> SignalEndpoints:
    """Endpoints for series perimeter strip — arc launch points, no GSG pad."""
    mte_tag = preserved.mte[0] if preserved.mte else None
    if mte_tag is None:
        mte_tag = TaggedPolygon(
            label="series_boundary",
            layer_name="BAW_MTE",
            polygon=gdstk.Polygon([(0.0, 0.0)]),
        )
    edge: Edge = (arc_start, arc_end)
    return SignalEndpoints(
        preserved=mte_tag,
        signal_pad=None,
        metal_point=arc_start,
        pad_point=arc_end,
        metal_edge=edge,
        pad_edge=edge,
        clearance_um=float("nan"),
    )


def _verify_signal_net(
    net_polys: Sequence[gdstk.Polygon],
    connector: gdstk.Polygon,
    signal_pads: Sequence[gdstk.Polygon],
    ground_obstacles: Sequence[gdstk.Polygon],
    config: SignalBuildConfig,
) -> tuple[bool, bool, float, list[str]]:
    violations: list[str] = []
    if not net_polys:
        return False, False, 0.0, ["signal net is empty"]

    path_poly = _path_net_polygon(net_polys, connector, config.boolean_precision)
    is_connected = path_poly is not None
    if not is_connected:
        violations.append("connector does not merge with any preserved MTE polygon")

    pad_clear = float("inf")
    reaches_pad = False
    check_polys = [path_poly] if path_poly is not None else list(net_polys)
    for pad in signal_pads:
        for net in check_polys:
            d, _, _ = _min_spacing(net, pad)
            pad_clear = min(pad_clear, d)
            if d <= config.connect_tolerance_um + 1e-6:
                reaches_pad = True
    if signal_pads and not reaches_pad:
        violations.append(
            f"connector does not reach signal pad within {config.connect_tolerance_um}um "
            f"(closest {pad_clear:.1f}um)"
        )

    min_ground = float("inf")
    violates, d, where = _spacing_violates(
        connector,
        ground_obstacles,
        config.mbe_mte_spacing_um,
        config.boolean_precision,
    )
    min_ground = d
    if violates or d < config.mbe_mte_spacing_um - 1e-6:
        violations.append(
            f"connector/ground MBE spacing at ({where[0]:.1f}, {where[1]:.1f}): "
            f"{d:.1f}um < {config.mbe_mte_spacing_um:.0f}um"
        )

    if min_ground == float("inf"):
        min_ground = float("nan")

    is_success_path = is_connected and reaches_pad
    return is_success_path, reaches_pad, min_ground, violations


def _verify_series_signal_net(
    net_polys: Sequence[gdstk.Polygon],
    ground_obstacles: Sequence[gdstk.Polygon],
    config: SignalBuildConfig,
) -> tuple[bool, float, list[str]]:
    """Series on-resonator net: non-empty perimeter strip, DRC vs ground MBE."""
    violations: list[str] = []
    if not net_polys:
        return False, 0.0, ["signal net is empty"]

    min_ground = float("inf")
    for net in net_polys:
        violates, d, where = _spacing_violates(
            net,
            ground_obstacles,
            config.mbe_mte_spacing_um,
            config.boolean_precision,
        )
        if d < min_ground:
            min_ground = d
        if violates or d < config.mbe_mte_spacing_um - 1e-6:
            violations.append(
                f"series MTE/ground MBE spacing at ({where[0]:.1f}, {where[1]:.1f}): "
                f"{d:.1f}um < {config.mbe_mte_spacing_um:.0f}um"
            )

    if min_ground == float("inf"):
        min_ground = float("nan")

    return True, min_ground, violations


def build_signal_net(
    preserved: PreservedMetal,
    classification: NodeClassification,
    ground_plates: GroundPlates,
    layermap: LayerMap,
    config: SignalBuildConfig | None = None,
    *,
    res: Resonator | None = None,
    assembly: RtegFrameAssembly | None = None,
    release_holes: ReleaseHoles | None = None,
) -> SignalNetResult:
    """Full step-5.3 pipeline: shunt pad route or series on-resonator MTE."""
    cfg = config or SignalBuildConfig()
    ground_obs = _ground_mbe_obstacles(classification, ground_plates, layermap, cfg)

    if classification.signal_band == "on_resonator":
        if res is None or assembly is None or release_holes is None:
            raise ValueError(
                "series on_resonator signal net requires res, assembly, and release_holes"
            )
        from rteg_series_mte import build_series_boundary_mte

        net_polys, centerline, shape_name, hole_a, hole_b = build_series_boundary_mte(
            res,
            assembly,
            release_holes,
            layermap,
            cfg,
            ground_obstacles=ground_obs,
        )
        endpoints = _series_signal_endpoints(
            preserved, centerline[0], centerline[-1]
        )
        connector = SignalPlate(
            polygon=net_polys[0],
            centerline=list(centerline),
            shape_name=shape_name,
        )
        is_connected = bool(net_polys)
        violations: list[str] = []
        if not is_connected:
            violations.append("signal net is empty")
        _, min_clear, drc_violations = _verify_series_signal_net(
            net_polys, ground_obs, cfg
        )
        violations.extend(drc_violations)
        return SignalNetResult(
            endpoints=endpoints,
            connector=connector,
            net_polygons=net_polys,
            signal_pad_polygons=[],
            n_net_polygons=len(net_polys),
            is_connected=is_connected,
            reaches_pad=False,
            min_ground_spacing_um=min_clear,
            drc_violations=violations,
        )

    endpoints = signal_endpoints(preserved, classification, cfg)
    signal_pads = _signal_pad_polygons(classification, layermap, cfg)
    connector = build_signal_plate(
        endpoints, layermap, cfg, ground_obstacles=ground_obs
    )
    net_polys = union_signal_net(preserved, connector, layermap, cfg)
    is_connected, reaches_pad, min_clear, violations = _verify_signal_net(
        net_polys, connector.polygon, signal_pads, ground_obs, cfg
    )
    return SignalNetResult(
        endpoints=endpoints,
        connector=connector,
        net_polygons=net_polys,
        signal_pad_polygons=signal_pads,
        n_net_polygons=len(net_polys),
        is_connected=is_connected,
        reaches_pad=reaches_pad,
        min_ground_spacing_um=min_clear,
        drc_violations=violations,
    )


@dataclass
class SignalRtegAssembly:
    """Step-4 frame assembly with the step-5.3 MTE connector merged for export."""

    frame: RtegFrameAssembly
    signal: SignalNetResult

    @property
    def index(self) -> int:
        return self.frame.index

    @property
    def inst_name(self) -> str:
        return self.frame.inst_name

    @property
    def top_cell(self) -> gdstk.Cell:
        return self.frame.top_cell

    @property
    def library(self) -> gdstk.Library:
        return self.frame.library

    def flatten(self) -> gdstk.Cell:
        """Full framed RTEG layout plus the generated MTE connector plate."""
        cell = self.frame.flatten().copy(
            f"rteg_{self.index:02d}_{self.inst_name}_mte"
        )
        if self.signal.is_on_resonator:
            for poly in self.signal.net_polygons:
                cell.add(gdstk.Polygon(poly.points, poly.layer, poly.datatype))
        else:
            conn = self.signal.connector.polygon
            cell.add(gdstk.Polygon(conn.points, conn.layer, conn.datatype))
        return cell


def build_signal_rteg_assemblies(
    frame_assemblies: Sequence[RtegFrameAssembly],
    signals: Mapping[int, SignalNetResult],
) -> list[SignalRtegAssembly]:
    """Pair each framed assembly with its built signal net."""
    return [
        SignalRtegAssembly(frame=asm, signal=signals[asm.index])
        for asm in frame_assemblies
    ]


def export_signal_rteg_gds(
    frame_assemblies: Sequence[RtegFrameAssembly],
    signals: Mapping[int, SignalNetResult],
    output_dir: str | Path,
    *,
    layermap: LayerMap,
    parent: str | None = None,
    flatten: bool = True,
    write_lyp: bool = True,
) -> list[ExportResult]:
    """
    Export full framed RTEG layouts with the generated MTE connector to GDS.

    Writes one ``.gds`` (and matching ``.lyp`` when ``layermap`` is set) per
    resonator under ``output_dir``. Filenames follow the step-4 convention with
    stage suffix ``mte``.
    """
    assemblies = build_signal_rteg_assemblies(frame_assemblies, signals)
    return export_gds(
        assemblies,
        output_dir,
        layermap=layermap,
        parent=parent,
        stage="mte",
        flatten=flatten,
        write_lyp=write_lyp,
    )


def signal_net_summary_table(result: SignalNetResult) -> list[dict[str, object]]:
    """Flat rows for notebook display."""
    rows: list[dict[str, object]] = [
        {"section": "summary", **result.summary()},
        {"section": "endpoints", **result.endpoints.summary()},
    ]
    for i, poly in enumerate(result.net_polygons):
        bb = poly.bounding_box()
        rows.append(
            {
                "section": "net_polygon",
                "index": i,
                "vertices": len(poly.points),
                "bbox": (
                    (round(bb[0][0], 1), round(bb[0][1], 1)),
                    (round(bb[1][0], 1), round(bb[1][1], 1)),
                ),
            }
        )
    for v in result.drc_violations:
        rows.append({"section": "drc", "message": v})
    return rows


def _union_bbox(
    boxes: Sequence[tuple[Point, Point]], margin_um: float = 0.0
) -> tuple[Point, Point]:
    xs: list[float] = []
    ys: list[float] = []
    for (x0, y0), (x1, y1) in boxes:
        xs.extend([x0, x1])
        ys.extend([y0, y1])
    if not xs:
        return (0.0, 0.0), (0.0, 0.0)
    return (
        (min(xs) - margin_um, min(ys) - margin_um),
        (max(xs) + margin_um, max(ys) + margin_um),
    )


def _bbox_intersects(a: tuple[Point, Point], b: tuple[Point, Point]) -> bool:
    return not (a[1][0] < b[0][0] or a[0][0] > b[1][0] or a[1][1] < b[0][1] or a[0][1] > b[1][1])


def _crop_svg_to_bbox(
    svg: str, focus: tuple[Point, Point], *, max_width_px: float = 320.0
) -> str:
    """Crop gdstk SVG to a GDS bbox and cap rendered pixel width."""
    (x0, y0), (x1, y1) = focus
    width = x1 - x0
    height = y1 - y0
    if width <= 0 or height <= 0:
        return svg
    px_w = max_width_px
    px_h = max_width_px * (height / width)
    header = (
        f'width="{px_w:g}" height="{px_h:g}" '
        f'viewBox="{x0:g} {-y1:g} {width:g} {height:g}"'
    )
    return re.sub(
        r'width="[^"]+" height="[^"]+" viewBox="[^"]+"',
        header,
        svg,
        count=1,
    )


def _copy_flat_cell(flat: gdstk.Cell, name: str) -> gdstk.Cell:
    """Clone a flattened layout cell for preview overlays."""
    return flat.copy(name)


def preview_signal_net_svg(
    result: SignalNetResult,
    layermap: LayerMap,
    *,
    assembly: RtegFrameAssembly | None = None,
    classification: NodeClassification | None = None,
    ground_plates: GroundPlates | None = None,
    show_ground_context: bool = True,
    focus_margin_um: float = 40.0,
    max_width_px: float = 320.0,
    config: SignalBuildConfig | None = None,
) -> str:
    """
    Render the signal MTE route on top of the full RTEG frame assembly.

    Pass ``assembly`` (step-4 ``RtegFrameAssembly``) to show the resonator, GSG
    pads, frame, and filler at the same scale as ``prep_rteg_frame.preview_assembly_svg``.
    The new connector plate is drawn in translucent red; the centerline and
    launch squares are orange.

    Without ``assembly``, falls back to a cropped route-only view (legacy).
    """
    cfg = config or SignalBuildConfig()
    mte_pair = layermap.pair(cfg.mte_layer)
    mbe_pair = layermap.pair(cfg.mbe_layer)
    edge_pair = layermap.pair("BAW_EDGE")
    connector_dt = mte_pair[1] + 100
    overlay_pair = (edge_pair[0], edge_pair[1] + 1)

    if assembly is not None:
        cell = _copy_flat_cell(assembly.flatten(), "signal_mte_preview")
        focus_bb = None
    else:
        ground_dt = mbe_pair[1] + 10
        signal_dt = mbe_pair[1] + 11
        mp, pp = result.endpoints.metal_point, result.endpoints.pad_point
        focus_bb = _union_bbox(
            [
                *(poly.bounding_box() for poly in result.net_polygons),
                result.connector.polygon.bounding_box(),
                *((p.bounding_box() for p in result.signal_pad_polygons)),
                ((mp[0] - 8.0, mp[1] - 8.0), (mp[0] + 8.0, mp[1] + 8.0)),
                ((pp[0] - 8.0, pp[1] - 8.0), (pp[0] + 8.0, pp[1] + 8.0)),
            ],
            margin_um=focus_margin_um,
        )
        cell = gdstk.Cell("signal_mte_preview")
        if show_ground_context and classification is not None and ground_plates is not None:
            for node in classification.nodes:
                if node.net == "ground":
                    for tagged in node.polygons:
                        if layermap.pair(tagged.layer_name) != mbe_pair:
                            continue
                        if not _bbox_intersects(tagged.bbox or focus_bb, focus_bb):
                            continue
                        cell.add(
                            gdstk.Polygon(
                                tagged.polygon.points, mbe_pair[0], ground_dt
                            )
                        )
            for tagged in ground_plates.filler:
                if layermap.pair(tagged.layer_name) != mbe_pair:
                    continue
                if not _bbox_intersects(tagged.bbox or focus_bb, focus_bb):
                    continue
                cell.add(
                    gdstk.Polygon(
                        tagged.polygon.points, mbe_pair[0], ground_dt
                    )
                )
        for pad in result.signal_pad_polygons:
            cell.add(gdstk.Polygon(pad.points, mbe_pair[0], signal_dt))
        for poly in result.net_polygons:
            cell.add(gdstk.Polygon(poly.points, *mte_pair))

    if result.is_on_resonator:
        for poly in result.net_polygons:
            cell.add(
                gdstk.Polygon(poly.points, mte_pair[0], connector_dt)
            )
        if len(result.connector.centerline) >= 2:
            cell.add(
                gdstk.FlexPath(
                    result.connector.centerline,
                    1.5,
                    layer=overlay_pair[0],
                    datatype=overlay_pair[1],
                )
            )
        for pt in (result.endpoints.metal_point, result.endpoints.pad_point):
            cell.add(
                gdstk.rectangle(
                    (pt[0] - 4.0, pt[1] - 4.0),
                    (pt[0] + 4.0, pt[1] + 4.0),
                    layer=overlay_pair[0],
                    datatype=overlay_pair[1],
                )
            )
    else:
        cell.add(
            gdstk.Polygon(
                result.connector.polygon.points, mte_pair[0], connector_dt
            )
        )

        if len(result.connector.centerline) >= 2:
            cell.add(
                gdstk.FlexPath(
                    result.connector.centerline,
                    1.5,
                    layer=overlay_pair[0],
                    datatype=overlay_pair[1],
                )
            )

        for pt in (result.endpoints.metal_point, result.endpoints.pad_point):
            cell.add(
                gdstk.rectangle(
                    (pt[0] - 4.0, pt[1] - 4.0),
                    (pt[0] + 4.0, pt[1] + 4.0),
                    layer=overlay_pair[0],
                    datatype=overlay_pair[1],
                )
            )

    shape_style: dict[tuple[int, int], dict[str, str]] = {}
    if result.is_on_resonator:
        shape_style = {
            (mte_pair[0], connector_dt): {
                "fill": "#e74c3c",
                "fill-opacity": "0.55",
                "stroke": "#c0392b",
                "stroke-width": "2",
            },
            overlay_pair: {
                "fill": "#f39c12",
                "stroke": "#d35400",
                "stroke-width": "2",
                "stroke-dasharray": "5,3",
            },
        }
    elif not result.is_on_resonator:
        shape_style = {
            (mte_pair[0], connector_dt): {
                "fill": "#e74c3c",
                "fill-opacity": "0.55",
                "stroke": "#c0392b",
                "stroke-width": "2",
            },
            overlay_pair: {
                "fill": "#f39c12",
                "stroke": "#d35400",
                "stroke-width": "2",
                "stroke-dasharray": "5,3",
            },
        }
    if assembly is None:
        ground_dt = mbe_pair[1] + 10
        signal_dt = mbe_pair[1] + 11
        shape_style.update(
            {
                (mbe_pair[0], ground_dt): {
                    "fill": "#cccccc",
                    "fill-opacity": "0.25",
                    "stroke": "#999999",
                    "stroke-width": "0.75",
                },
                (mbe_pair[0], signal_dt): {
                    "fill": "#4a90d9",
                    "fill-opacity": "0.45",
                    "stroke": "#1a5276",
                    "stroke-width": "1.5",
                },
                mte_pair: {
                    "fill": "#e74c3c",
                    "fill-opacity": "0.8",
                    "stroke": "#922b21",
                    "stroke-width": "1.5",
                },
            }
        )

    with tempfile.TemporaryDirectory() as tmp:
        svg_path = Path(tmp) / "signal_mte.svg"
        cell.write_svg(
            str(svg_path),
            scaling=1.0,
            background="#fafafa",
            shape_style=shape_style,
            pad="0",
            sort_function=lambda p1, p2: (p1.layer, p1.datatype) < (p2.layer, p2.datatype),
        )
        svg = svg_path.read_text(encoding="utf-8")
        if assembly is None:
            return _crop_svg_to_bbox(svg, focus_bb, max_width_px=max_width_px)
        return svg
