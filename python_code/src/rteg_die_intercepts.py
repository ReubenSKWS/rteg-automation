"""
Step 2.4 — Original-die collar intercept capture.

Reads filter connect cells (``connectMTE`` / ``connectMBE`` / ``connect_backup``),
finds where preserved interconnect meets each resonator collar on MBE and MTE, and
records mouth intercept points plus attachment angles in **filter-die world**
coordinates for downstream steps 5–6.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import gdstk

from layermap import LayerMap
from prep_resonator_ppd import resonator_metal_polys
from prep_rteg_frame import RtegFrameAssembly
from rteg_collect import (
    RtegCollectConfig,
    TaggedPolygon,
    _find_connect_cell,
    _polygon_key,
    _resonator_body_mbe_at_filter,
    _resonator_body_mte_at_filter,
    _resonator_shift,
    collect_filter_die_collar_metal,
)
from rteg_mte_extensions import LipIntercept, _body_centroid
from rteg_utils import bbox_center, polys_bbox, resonator_world_bbox
from separate import IdentificationResult, Resonator

Point = tuple[float, float]
ProbeSide = Literal["left", "right", "top", "bottom"]
Bbox = tuple[tuple[float, float], tuple[float, float]]


@dataclass(frozen=True)
class MouthCornerSpec:
    """One mouth-corner aim before projection onto collar geometry."""

    parallel_frac: float
    outward_um: float
    parallel_offset_um: float = 0.0


@dataclass(frozen=True)
class LayerMouthAims:
    corner_a: MouthCornerSpec
    corner_b: MouthCornerSpec


@dataclass(frozen=True)
class DieInterceptConfig:
    """Per-probe-side mouth aim specs (tuned on KB331 reference layouts)."""

    left: LayerMouthAims = LayerMouthAims(
        corner_a=MouthCornerSpec(0.0, 33.0, parallel_offset_um=-18.0),
        corner_b=MouthCornerSpec(0.68, 61.0),
    )
    right: LayerMouthAims = LayerMouthAims(
        corner_a=MouthCornerSpec(0.0, 33.0, parallel_offset_um=-18.0),
        corner_b=MouthCornerSpec(0.68, 61.0),
    )
    top_mte: LayerMouthAims = LayerMouthAims(
        corner_a=MouthCornerSpec(0.38, 93.0),
        corner_b=MouthCornerSpec(0.72, 107.0),
    )
    top_mbe: LayerMouthAims = LayerMouthAims(
        corner_a=MouthCornerSpec(0.26, 28.0),
        corner_b=MouthCornerSpec(0.83, 112.0),
    )
    bottom: LayerMouthAims = LayerMouthAims(
        corner_a=MouthCornerSpec(0.26, 28.0),
        corner_b=MouthCornerSpec(0.83, 112.0),
    )
    left_mbe: LayerMouthAims = LayerMouthAims(
        corner_a=MouthCornerSpec(0.66, 36.0),
        corner_b=MouthCornerSpec(-0.07, -17.0),
    )
    # MTE mouth on upper collar lip when horizontal + vertical collar extensions
    # are comparable (series resonators probed from a top-right collar corner).
    corner_top_mte: LayerMouthAims = LayerMouthAims(
        corner_a=MouthCornerSpec(0.70, 93.0),
        corner_b=MouthCornerSpec(0.50, 107.0),
    )

    def layer_aims(self, layer_name: str, side: ProbeSide) -> LayerMouthAims:
        if layer_name == "BAW_MBE" and side == "left":
            return self.left_mbe
        if layer_name == "BAW_MTE" and side == "top":
            return self.top_mte
        if layer_name == "BAW_MBE" and side == "top":
            return self.top_mbe
        if side == "top":
            return self.top_mte
        return getattr(self, side)


def _angle_deg(dx: float, dy: float) -> float:
    return math.degrees(math.atan2(dy, dx)) % 360.0


def _dist(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _fmt_point(p: Point | None) -> str | None:
    if p is None:
        return None
    return f"({p[0]:.2f}, {p[1]:.2f})"


@dataclass(frozen=True)
class LayerCollarIntercept:
    """Collar mouth intercept on one metal layer at filter-die placement."""

    layer: str
    status: str
    intercept_a: Point | None = None
    intercept_b: Point | None = None
    mouth_span_um: float | None = None
    mouth_angle_deg: float | None = None
    entry_angle_deg: float | None = None
    outward_normal: tuple[float, float] | None = None
    collar_area_um2: float | None = None
    n_connect_pieces: int = 0
    anchor_center: Point | None = None
    intercept_a_local: Point | None = None
    intercept_b_local: Point | None = None
    source: str = "geometry"


@dataclass(frozen=True)
class DieCollarIntercepts:
    """Per-resonator MBE/MTE die intercept record."""

    index: int
    inst_name: str
    mte: LayerCollarIntercept | None = None
    mbe: LayerCollarIntercept | None = None


@dataclass
class DieInterceptCollection:
    """All resonators' original-die collar intercepts."""

    parent: str
    items: list[DieCollarIntercepts] = field(default_factory=list)

    def by_index(self) -> dict[int, DieCollarIntercepts]:
        return {item.index: item for item in self.items}

    def get(self, index: int) -> DieCollarIntercepts | None:
        return self.by_index().get(index)


def resonator_anchor_center(
    res: Resonator,
    dx: float = 0.0,
    dy: float = 0.0,
) -> Point:
    """
    Center of the resonator master MBE+MTE metal bbox at placement ``(dx, dy)``.

    Intercept offsets relative to this point are stable when the resonator moves
    from filter-die placement to RTEG placement (same rotation).
    """
    bb = polys_bbox(resonator_metal_polys(res, dx, dy))
    if bb is None:
        return bbox_center(resonator_world_bbox(res))
    return bbox_center(bb)


def _local_offset(point: Point, center: Point) -> Point:
    """World-frame offset from anchor (legacy / reference GDS)."""
    return (point[0] - center[0], point[1] - center[1])


def _apply_local_offset(local: Point, center: Point) -> Point:
    return (local[0] + center[0], local[1] + center[1])


def _world_to_body_local(point: Point, anchor: Point, rotation: float) -> Point:
    """Rotate filter-die world coords into resonator body-local frame."""
    dx, dy = point[0] - anchor[0], point[1] - anchor[1]
    c, s = math.cos(-rotation), math.sin(-rotation)
    return (dx * c - dy * s, dx * s + dy * c)


def _body_local_to_world(local: Point, anchor: Point, rotation: float) -> Point:
    """Map body-local coords back to filter-die / RTEG world space."""
    c, s = math.cos(rotation), math.sin(rotation)
    return (
        anchor[0] + local[0] * c - local[1] * s,
        anchor[1] + local[0] * s + local[1] * c,
    )


def _nearest_boundary_point(
    polys: Sequence[gdstk.Polygon],
    target: Point,
) -> Point:
    """Closest point on any polygon edge to ``target``."""
    tx, ty = target
    best_d = float("inf")
    best_pt: Point = target
    for poly in polys:
        pts = [(float(x), float(y)) for x, y in poly.points]
        for i in range(len(pts)):
            p0, p1 = pts[i], pts[(i + 1) % len(pts)]
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
            el2 = dx * dx + dy * dy
            if el2 < 1e-9:
                continue
            t = max(0.0, min(1.0, ((tx - p0[0]) * dx + (ty - p0[1]) * dy) / el2))
            pt = (p0[0] + t * dx, p0[1] + t * dy)
            d = math.hypot(pt[0] - tx, pt[1] - ty)
            if d < best_d:
                best_d = d
                best_pt = pt
    return best_pt


def _collar_side_extensions(
    metal_bb: Bbox,
    collar_polys: Sequence[gdstk.Polygon],
) -> dict[ProbeSide, float]:
    collar_bb = polys_bbox(list(collar_polys))
    if collar_bb is None:
        return {"left": 0.0, "right": 0.0, "top": 0.0, "bottom": 0.0}
    (x0, y0), (x1, y1) = metal_bb
    (cx0, cy0), (cx1, cy1) = collar_bb
    return {
        "left": max(0.0, x0 - cx0),
        "right": max(0.0, cx1 - x1),
        "top": max(0.0, cy1 - y1),
        "bottom": max(0.0, y0 - cy0),
    }


def detect_probe_facing_side(
    metal_bb: Bbox,
    collar_polys: Sequence[gdstk.Polygon],
    *,
    min_extension_um: float = 5.0,
) -> ProbeSide:
    """
    Probe-facing side = where filter collar metal extends furthest past the body.

    Evaluated per layer so MTE and MBE can face different GSG bands.
    """
    ext = _collar_side_extensions(metal_bb, collar_polys)
    ranked = sorted(ext.items(), key=lambda item: item[1], reverse=True)
    if ranked[0][1] >= min_extension_um:
        return ranked[0][0]  # type: ignore[return-value]
    return "left"


def _parallel_coord(
    spec: MouthCornerSpec,
    *,
    parallel_span: float,
    parallel_origin: float,
) -> float:
    return parallel_origin + spec.parallel_offset_um + spec.parallel_frac * parallel_span


def _is_mte_probe_corner_top(
    metal_bb: Bbox,
    collar_polys: Sequence[gdstk.Polygon],
    *,
    secondary_ratio: float = 0.85,
) -> bool:
    """
    True when collar extends horizontally and vertically by similar amounts.

    The pad-facing MTE mouth then sits on the upper collar lip rather than a
    single body side (KB331 series @ 270°).
    """
    ext = _collar_side_extensions(metal_bb, collar_polys)
    ranked = sorted(ext.items(), key=lambda item: item[1], reverse=True)
    primary, pval = ranked[0][0], ranked[0][1]
    secondary, sval = ranked[1][0], ranked[1][1]
    return (
        primary in ("left", "right")
        and secondary == "top"
        and sval >= secondary_ratio * pval
    )


def _is_mbe_right_top_collar(
    metal_bb: Bbox,
    collar_polys: Sequence[gdstk.Polygon],
) -> bool:
    """MBE bus exits to the right with significant upward collar metal."""
    ext = _collar_side_extensions(metal_bb, collar_polys)
    return (
        ext["right"] > ext["left"]
        and ext["right"] > 150.0
        and ext["top"] > 0.25 * ext["right"]
    )


def _mouth_aim_corner_top(
    metal_bb: Bbox,
    collar_bb: Bbox,
    spec: MouthCornerSpec,
) -> Point:
    """Top-edge aim with parallel coord spanning the full collar bbox width."""
    (mx0, my0), (mx1, my1) = metal_bb
    (cx0, cy0), (cx1, cy1) = collar_bb
    return (
        _parallel_coord(spec, parallel_span=cx1 - cx0, parallel_origin=cx0),
        my1 + spec.outward_um,
    )


def _mouth_aim_point(
    metal_bb: Bbox,
    side: ProbeSide,
    spec: MouthCornerSpec,
) -> Point:
    (x0, y0), (x1, y1) = metal_bb
    width, height = x1 - x0, y1 - y0
    if side == "left":
        return (
            x0 - spec.outward_um,
            _parallel_coord(spec, parallel_span=height, parallel_origin=y0),
        )
    if side == "right":
        return (
            x1 + spec.outward_um,
            _parallel_coord(spec, parallel_span=height, parallel_origin=y0),
        )
    if side == "top":
        return (
            _parallel_coord(spec, parallel_span=width, parallel_origin=x0),
            y1 + spec.outward_um,
        )
    return (
        _parallel_coord(spec, parallel_span=width, parallel_origin=x0),
        y0 - spec.outward_um,
    )


def _mouth_outward_normal(
    point_a: Point,
    point_b: Point,
    body_polys: Sequence[gdstk.Polygon],
    side: ProbeSide,
) -> tuple[float, float]:
    body_c = _body_centroid(body_polys)
    side_normal = {
        "left": (-1.0, 0.0),
        "right": (1.0, 0.0),
        "top": (0.0, 1.0),
        "bottom": (0.0, -1.0),
    }[side]
    mid = ((point_a[0] + point_b[0]) / 2.0, (point_a[1] + point_b[1]) / 2.0)
    vx, vy = mid[0] - body_c[0], mid[1] - body_c[1]
    vlen = math.hypot(vx, vy)
    if vlen < 1e-9:
        return side_normal
    nx, ny = vx / vlen, vy / vlen
    if nx * side_normal[0] + ny * side_normal[1] < 0.0:
        return (-nx, -ny)
    return (nx, ny)


def find_die_collar_mouth_ab(
    collar_polys: Sequence[gdstk.Polygon],
    body_polys: Sequence[gdstk.Polygon],
    *,
    layer_name: str,
    intercept_config: DieInterceptConfig | None = None,
) -> LipIntercept:
    """
    Pad-facing collar mouth corners on original filter-die metal.

    Detects which body edge faces the probe from collar overhang, places two
    aim points on that edge (or on the upper collar lip for corner cases),
    then projects onto the nearest collar boundary.
    """
    cfg = intercept_config or DieInterceptConfig()
    metal_bb = polys_bbox(body_polys)
    if metal_bb is None:
        raise ValueError("resonator body has no metal bbox")

    collar_bb = polys_bbox(list(collar_polys))
    side: ProbeSide
    if (
        layer_name == "BAW_MTE"
        and collar_bb is not None
        and _is_mte_probe_corner_top(metal_bb, collar_polys)
    ):
        side = "top"
        aims = cfg.corner_top_mte
        aim_a = _mouth_aim_corner_top(metal_bb, collar_bb, aims.corner_a)
        aim_b = _mouth_aim_corner_top(metal_bb, collar_bb, aims.corner_b)
    elif (
        layer_name == "BAW_MBE"
        and collar_bb is not None
        and _is_mbe_right_top_collar(metal_bb, collar_polys)
    ):
        side = "top"
        aims = cfg.top_mbe
        aim_a = _mouth_aim_corner_top(metal_bb, collar_bb, aims.corner_a)
        aim_b = _mouth_aim_corner_top(metal_bb, collar_bb, aims.corner_b)
    else:
        side = detect_probe_facing_side(metal_bb, collar_polys)
        aims = cfg.layer_aims(layer_name, side)
        aim_a = _mouth_aim_point(metal_bb, side, aims.corner_a)
        aim_b = _mouth_aim_point(metal_bb, side, aims.corner_b)

    point_a = _nearest_boundary_point(collar_polys, aim_a)
    point_b = _nearest_boundary_point(collar_polys, aim_b)
    outward = _mouth_outward_normal(point_a, point_b, body_polys, side)
    return LipIntercept(
        point_a=point_a,
        point_b=point_b,
        lip_vertex_indices=[],
        outward_normal=outward,
        lip_edges=[],
    )


def probe_side_from_signal_pads(
    body_polys: Sequence[gdstk.Polygon],
    signal_polys: Sequence[gdstk.Polygon],
) -> ProbeSide | None:
    """Map center signal pad position to the body edge that faces the probes."""
    body_bb = polys_bbox(list(body_polys))
    pad_bb = polys_bbox(list(signal_polys))
    if body_bb is None or pad_bb is None:
        return None
    body_c = bbox_center(body_bb)
    pad_c = bbox_center(pad_bb)
    dx, dy = pad_c[0] - body_c[0], pad_c[1] - body_c[1]
    if abs(dx) >= abs(dy):
        return "left" if dx < 0.0 else "right"
    return "bottom" if dy < 0.0 else "top"


def find_rteg_collar_mouth_ab(
    collar_polys: Sequence[gdstk.Polygon],
    body_polys: Sequence[gdstk.Polygon],
    *,
    layer_name: str,
    probe_side: ProbeSide | None = None,
    intercept_config: DieInterceptConfig | None = None,
) -> LipIntercept:
    """
    Pad-facing collar mouth on **RTEG placed** preserved metal.

    When ``probe_side`` is supplied (from signal-pad geometry), the mouth is
    aimed on that body edge instead of the filter-die corner-top heuristic.
    Coordinates are already in the exported RTEG assembly frame.
    """
    if probe_side is not None:
        cfg = intercept_config or DieInterceptConfig()
        metal_bb = polys_bbox(body_polys)
        if metal_bb is None:
            raise ValueError("resonator body has no metal bbox")
        aims = cfg.layer_aims(layer_name, probe_side)
        aim_a = _mouth_aim_point(metal_bb, probe_side, aims.corner_a)
        aim_b = _mouth_aim_point(metal_bb, probe_side, aims.corner_b)
        point_a = _nearest_boundary_point(collar_polys, aim_a)
        point_b = _nearest_boundary_point(collar_polys, aim_b)
        outward = _mouth_outward_normal(
            point_a, point_b, body_polys, probe_side
        )
        return LipIntercept(
            point_a=point_a,
            point_b=point_b,
            lip_vertex_indices=[],
            outward_normal=outward,
            lip_edges=[],
        )
    return find_die_collar_mouth_ab(
        collar_polys,
        body_polys,
        layer_name=layer_name,
        intercept_config=intercept_config,
    )


def extra_rteg_collar_pieces(
    roles: object,
    res: Resonator,
    assembly: RtegFrameAssembly,
    identification: IdentificationResult,
    layermap: LayerMap,
    layer_name: str,
    *,
    config: RtegCollectConfig | None = None,
) -> list[TaggedPolygon]:
    """Expanded filter collar polygons in RTEG space not already in preserved."""
    cfg = config or RtegCollectConfig()
    if layer_name == cfg.mte_layer:
        preserved = roles.preserved.mte  # type: ignore[attr-defined]
    else:
        preserved = roles.preserved.mbe  # type: ignore[attr-defined]
    seen = {_polygon_key(tp.polygon) for tp in preserved}
    extras: list[TaggedPolygon] = []
    for i, poly in enumerate(
        expanded_rteg_collar_polys(
            res,
            assembly,
            identification,
            layermap,
            layer_name,
            config=cfg,
        )
    ):
        key = _polygon_key(poly)
        if key in seen:
            continue
        seen.add(key)
        extras.append(
            TaggedPolygon(
                f"expanded_{layer_name}[{i}]",
                layer_name,
                poly,
            )
        )
    return extras


def capture_rteg_routing_lip(
    roles: object,
    classification: object | None,
    layermap: LayerMap,
    layer_name: str,
) -> LipIntercept | None:
    """Mouth intercept on preserved RTEG collar metal for steps 5–6."""
    if layer_name == "BAW_MTE":
        pieces = roles.preserved.mte  # type: ignore[attr-defined]
        body_polys = roles.resonator_body_mte  # type: ignore[attr-defined]
    else:
        pieces = roles.preserved.mbe  # type: ignore[attr-defined]
        body_polys = roles.resonator_body_mbe  # type: ignore[attr-defined]
    if not pieces:
        return None

    signal_polys: list[gdstk.Polygon] = []
    if classification is not None:
        signal_polys = [
            tp.polygon
            for tp in classification.center_pad_polygons()  # type: ignore[attr-defined]
        ]
    probe_side = (
        probe_side_from_signal_pads(body_polys, signal_polys)
        if signal_polys
        else None
    )
    try:
        return find_rteg_collar_mouth_ab(
            [tp.polygon for tp in pieces],
            body_polys,
            layer_name=layer_name,
            probe_side=probe_side,
        )
    except ValueError:
        return None


def capture_die_transformed_routing_lip(
    intercept: LayerCollarIntercept,
    roles: object,
    res: Resonator,
    assembly: RtegFrameAssembly,
    identification: IdentificationResult,
    layermap: LayerMap,
    layer_name: str,
    *,
    classification: object | None = None,
    config: RtegCollectConfig | None = None,
) -> LipIntercept | None:
    """
    Map step-2.4 filter-die mouth corners into the RTEG frame and snap them
    onto expanded preserved collar metal already placed in that frame.
    """
    cfg = config or RtegCollectConfig()
    lip_aim = transform_die_intercept_to_rteg(intercept, res, assembly)
    if lip_aim is None:
        return None

    collar_polys = expanded_rteg_collar_polys(
        res,
        assembly,
        identification,
        layermap,
        layer_name,
        config=cfg,
    )
    if not collar_polys:
        return lip_aim

    dominant = _dominant_collar_polygon(
        collar_polys, lip_aim.point_a, lip_aim.point_b
    )
    point_a = _nearest_boundary_point([dominant], lip_aim.point_a)
    point_b = _nearest_boundary_point([dominant], lip_aim.point_b)
    body_polys = (
        roles.resonator_body_mte  # type: ignore[attr-defined]
        if layer_name == cfg.mte_layer
        else roles.resonator_body_mbe  # type: ignore[attr-defined]
    )
    signal_polys: list[gdstk.Polygon] = []
    if classification is not None:
        signal_polys = [
            tp.polygon
            for tp in classification.center_pad_polygons()  # type: ignore[attr-defined]
        ]
    probe_side = (
        probe_side_from_signal_pads(body_polys, signal_polys)
        if signal_polys
        else None
    )
    if probe_side is None:
        metal_bb = polys_bbox(body_polys)
        if metal_bb is None:
            return lip_aim
        probe_side = detect_probe_facing_side(metal_bb, collar_polys)
    outward = _mouth_outward_normal(point_a, point_b, body_polys, probe_side)
    return LipIntercept(
        point_a=point_a,
        point_b=point_b,
        lip_vertex_indices=[],
        outward_normal=outward,
        lip_edges=[],
    )


def build_rteg_routing_lips(
    roles_by_index: Mapping[int, object],
    classifications_by_index: Mapping[int, object],
    layermap: LayerMap,
    *,
    res_by_index: Mapping[int, Resonator],
    assembly_by_index: Mapping[int, RtegFrameAssembly],
    identification: IdentificationResult,
    die_intercepts: DieInterceptCollection | None = None,
    reference_gds_by_index: Mapping[int, str | Path] | None = None,
    config: RtegCollectConfig | None = None,
) -> tuple[dict[int, dict[LayerName, LipIntercept]], dict[int, dict[LayerName, tuple[TaggedPolygon, ...]]]]:
    """
    Per-index MTE/MBE mouths in RTEG assembly coordinates.

    Production path (default): step-2.4 filter-die intercepts transformed into
    the RTEG frame and snapped onto expanded preserved collar metal. Pass
    ``reference_gds_by_index`` only for golden-layout validation.
    """
    cfg = config or RtegCollectConfig()
    ref_map = dict(reference_gds_by_index or {})
    die_by_index = die_intercepts.by_index() if die_intercepts is not None else {}
    lips: dict[int, dict[LayerName, LipIntercept]] = {}
    extras: dict[int, dict[LayerName, tuple[TaggedPolygon, ...]]] = {}
    for idx, roles in roles_by_index.items():
        classification = classifications_by_index.get(idx)
        res = res_by_index.get(idx)
        assembly = assembly_by_index.get(idx)
        if res is None or assembly is None:
            continue
        layer_lips: dict[LayerName, LipIntercept] = {}
        layer_extras: dict[LayerName, tuple[TaggedPolygon, ...]] = {}
        ref_path = ref_map.get(idx)
        die_item = die_by_index.get(idx)
        if ref_path is not None:
            for layer_key, layer_name in (("mte", cfg.mte_layer), ("mbe", cfg.mbe_layer)):
                ref_lip = capture_reference_routing_lip(
                    ref_path,
                    layer_key,
                    roles,
                    layermap,
                    res,
                    assembly,
                    identification,
                    classification=classification,
                    config=cfg,
                )
                if ref_lip is not None:
                    layer_lips[layer_key] = ref_lip
                extra = extra_rteg_collar_pieces(
                    roles,
                    res,
                    assembly,
                    identification,
                    layermap,
                    layer_name,
                    config=cfg,
                )
                if extra:
                    layer_extras[layer_key] = tuple(extra)
        elif die_item is not None:
            for layer_key, layer_name, intercept in (
                ("mte", cfg.mte_layer, die_item.mte),
                ("mbe", cfg.mbe_layer, die_item.mbe),
            ):
                if intercept is not None and intercept.status == "ok":
                    die_lip = capture_die_transformed_routing_lip(
                        intercept,
                        roles,
                        res,
                        assembly,
                        identification,
                        layermap,
                        layer_name,
                        classification=classification,
                        config=cfg,
                    )
                    if die_lip is not None:
                        layer_lips[layer_key] = die_lip
                extra = extra_rteg_collar_pieces(
                    roles,
                    res,
                    assembly,
                    identification,
                    layermap,
                    layer_name,
                    config=cfg,
                )
                if extra:
                    layer_extras[layer_key] = tuple(extra)
        else:
            mte_lip = capture_rteg_routing_lip(
                roles, classification, layermap, "BAW_MTE"
            )
            mbe_lip = capture_rteg_routing_lip(
                roles, classification, layermap, "BAW_MBE"
            )
            if mte_lip is not None:
                layer_lips["mte"] = mte_lip
            if mbe_lip is not None:
                layer_lips["mbe"] = mbe_lip
        if layer_extras:
            extras[idx] = layer_extras
        if layer_lips:
            lips[idx] = layer_lips
    return lips, extras


def _dominant_collar_polygon(
    collar_polys: Sequence[gdstk.Polygon],
    aim_a: Point,
    aim_b: Point,
) -> gdstk.Polygon:
    """Collar polygon whose boundary is closest to both mouth corners."""
    best: gdstk.Polygon | None = None
    best_score = float("inf")
    for poly in collar_polys:
        pa = _nearest_boundary_point([poly], aim_a)
        pb = _nearest_boundary_point([poly], aim_b)
        score = _dist(pa, aim_a) + _dist(pb, aim_b)
        if score < best_score:
            best_score = score
            best = poly
    if best is None:
        raise ValueError("no collar polygons supplied")
    return best


def _lip_to_layer_intercept(
    layer: str,
    lip: LipIntercept,
    collar_poly: gdstk.Polygon,
    n_connect_pieces: int,
    anchor_center: Point,
    rotation: float,
) -> LayerCollarIntercept:
    ax, ay = lip.point_a
    bx, by = lip.point_b
    nx, ny = lip.outward_normal
    local_a = _world_to_body_local(lip.point_a, anchor_center, rotation)
    local_b = _world_to_body_local(lip.point_b, anchor_center, rotation)
    return LayerCollarIntercept(
        layer=layer,
        status="ok",
        intercept_a=lip.point_a,
        intercept_b=lip.point_b,
        mouth_span_um=round(_dist(lip.point_a, lip.point_b), 3),
        mouth_angle_deg=round(_angle_deg(bx - ax, by - ay), 1),
        entry_angle_deg=round(_angle_deg(nx, ny), 1),
        outward_normal=(round(nx, 6), round(ny, 6)),
        collar_area_um2=round(abs(collar_poly.area()), 1),
        n_connect_pieces=n_connect_pieces,
        anchor_center=(round(anchor_center[0], 3), round(anchor_center[1], 3)),
        intercept_a_local=(round(local_a[0], 3), round(local_a[1], 3)),
        intercept_b_local=(round(local_b[0], 3), round(local_b[1], 3)),
        source="geometry",
    )


def _layer_intercept_from_reference(
    layer_name: str,
    ref_layer: dict[str, object],
    anchor_center: Point,
) -> LayerCollarIntercept:
    local_a = ref_layer["intercept_a_local"]
    local_b = ref_layer["intercept_b_local"]
    assert isinstance(local_a, tuple) and isinstance(local_b, tuple)
    point_a = _apply_local_offset(local_a, anchor_center)
    point_b = _apply_local_offset(local_b, anchor_center)
    ax, ay = point_a
    bx, by = point_b
    nx = -1.0 if local_a[0] <= local_b[0] else 1.0
    return LayerCollarIntercept(
        layer=layer_name,
        status="ok",
        intercept_a=point_a,
        intercept_b=point_b,
        mouth_span_um=round(_dist(point_a, point_b), 3),
        mouth_angle_deg=round(_angle_deg(bx - ax, by - ay), 1),
        entry_angle_deg=round(_angle_deg(nx, 0.0), 1),
        outward_normal=(nx, 0.0),
        collar_area_um2=ref_layer.get("polygon_area_um2"),  # type: ignore[arg-type]
        n_connect_pieces=0,
        anchor_center=(round(anchor_center[0], 3), round(anchor_center[1], 3)),
        intercept_a_local=(round(local_a[0], 3), round(local_a[1], 3)),
        intercept_b_local=(round(local_b[0], 3), round(local_b[1], 3)),
        source="reference_gds",
    )


def _extract_layer_intercept(
    layer_name: str,
    pieces: list,
    body_polys: list[gdstk.Polygon],
    connect_cell_found: bool,
    intercept_config: DieInterceptConfig | None,
    anchor_center: Point,
    rotation: float,
) -> LayerCollarIntercept:
    n_pieces = len(pieces)
    if not connect_cell_found:
        return LayerCollarIntercept(layer=layer_name, status="no_connect_cell")
    if not pieces:
        return LayerCollarIntercept(
            layer=layer_name, status="no_collar", n_connect_pieces=0
        )

    collar_polys = [tp.polygon for tp in pieces]
    cfg = intercept_config or DieInterceptConfig()
    try:
        lip = find_die_collar_mouth_ab(
            collar_polys,
            body_polys,
            layer_name=layer_name,
            intercept_config=cfg,
        )
    except ValueError:
        return LayerCollarIntercept(
            layer=layer_name,
            status="lip_failed",
            n_connect_pieces=n_pieces,
        )

    metal_bb = polys_bbox(body_polys)
    if metal_bb is None:
        return LayerCollarIntercept(
            layer=layer_name, status="lip_failed", n_connect_pieces=n_pieces
        )
    side = detect_probe_facing_side(metal_bb, collar_polys)
    aims = cfg.layer_aims(layer_name, side)
    aim_a = _mouth_aim_point(metal_bb, side, aims.corner_a)
    aim_b = _mouth_aim_point(metal_bb, side, aims.corner_b)
    collar_poly = _dominant_collar_polygon(collar_polys, aim_a, aim_b)

    return _lip_to_layer_intercept(
        layer_name, lip, collar_poly, n_pieces, anchor_center, rotation
    )


def _collect_anchor_center(res: Resonator) -> Point:
    return resonator_anchor_center(res, 0.0, 0.0)


def default_kb331_reference_gds_by_index() -> dict[int, Path]:
    """Known hand-drawn reference RTEG layouts for KB331 resonator indices."""
    root = Path(__file__).resolve().parents[1] / "reference_gds"
    mapping: dict[int, Path] = {}
    s1b = root / "KB331_N_01_RTEG1_S1B.gds"
    s3 = root / "KB331_N_01_RTEG1_S3.gds"
    if s1b.is_file():
        mapping[3] = s1b
    if s3.is_file():
        mapping[6] = s3
    return mapping


def expanded_rteg_collar_polys(
    res: Resonator,
    assembly: RtegFrameAssembly,
    identification: IdentificationResult,
    layermap: LayerMap,
    layer_name: str,
    *,
    config: RtegCollectConfig | None = None,
) -> list[gdstk.Polygon]:
    """Filter-die collar cluster (connect + touching bus) shifted into RTEG space."""
    cfg = config or RtegCollectConfig()
    dx, dy = _resonator_shift(res, assembly)
    preserved = collect_filter_die_collar_metal(
        res, identification, layermap, cfg
    )
    pieces = preserved.mte if layer_name == cfg.mte_layer else preserved.mbe
    return [
        gdstk.Polygon(
            [(x + dx, y + dy) for x, y in tp.polygon.points],
            layer=tp.polygon.layer,
            datatype=tp.polygon.datatype,
        )
        for tp in pieces
    ]


def capture_reference_routing_lip(
    gds_path: str | Path,
    layer_key: LayerName,
    roles: object,
    layermap: LayerMap,
    res: Resonator,
    assembly: RtegFrameAssembly,
    identification: IdentificationResult,
    *,
    classification: object | None = None,
    config: RtegCollectConfig | None = None,
) -> LipIntercept | None:
    """
    Mouth targets from a hand-drawn reference RTEG GDS in top-cell coordinates.

    Reference intercepts are snapped onto the expanded preserved-collar cluster
    so both endpoints land on real collar metal in the exported frame.
    """
    cfg = config or RtegCollectConfig()
    layer_name = cfg.mte_layer if layer_key == "mte" else cfg.mbe_layer
    ref = extract_reference_rteg_intercepts(gds_path, layermap)
    layer_data = ref.get(layer_key)
    if not isinstance(layer_data, dict):
        return None
    intercept_a = layer_data.get("intercept_a")
    intercept_b = layer_data.get("intercept_b")
    if not isinstance(intercept_a, tuple) or not isinstance(intercept_b, tuple):
        return None

    collar_polys = expanded_rteg_collar_polys(
        res,
        assembly,
        identification,
        layermap,
        layer_name,
        config=cfg,
    )
    if not collar_polys:
        return None

    dominant = _dominant_collar_polygon(collar_polys, intercept_a, intercept_b)
    point_a = _nearest_boundary_point([dominant], intercept_a)
    point_b = _nearest_boundary_point([dominant], intercept_b)
    body_polys = (
        roles.resonator_body_mte  # type: ignore[attr-defined]
        if layer_key == "mte"
        else roles.resonator_body_mbe  # type: ignore[attr-defined]
    )
    signal_polys: list[gdstk.Polygon] = []
    if classification is not None:
        signal_polys = [
            tp.polygon
            for tp in classification.center_pad_polygons()  # type: ignore[attr-defined]
        ]
    probe_side = (
        probe_side_from_signal_pads(body_polys, signal_polys)
        if signal_polys
        else None
    )
    if probe_side is None:
        metal_bb = polys_bbox(body_polys)
        if metal_bb is None:
            return None
        probe_side = detect_probe_facing_side(metal_bb, collar_polys)
    outward = _mouth_outward_normal(point_a, point_b, body_polys, probe_side)
    return LipIntercept(
        point_a=point_a,
        point_b=point_b,
        lip_vertex_indices=[],
        outward_normal=outward,
        lip_edges=[],
    )


def _reference_layer_intercepts(
    gds_path: str | Path,
    layermap: LayerMap,
    anchor_center: Point,
    collect_config: RtegCollectConfig,
) -> tuple[LayerCollarIntercept | None, LayerCollarIntercept | None]:
    ref = extract_reference_rteg_intercepts(gds_path, layermap)
    mte = (
        _layer_intercept_from_reference(
            collect_config.mte_layer, ref["mte"], anchor_center  # type: ignore[arg-type]
        )
        if ref.get("mte") is not None
        else None
    )
    mbe = (
        _layer_intercept_from_reference(
            collect_config.mbe_layer, ref["mbe"], anchor_center  # type: ignore[arg-type]
        )
        if ref.get("mbe") is not None
        else None
    )
    return mte, mbe


def collect_die_collar_intercepts(
    identification: IdentificationResult,
    layermap: LayerMap,
    *,
    collect_config: RtegCollectConfig | None = None,
    intercept_config: DieInterceptConfig | None = None,
    reference_gds_by_index: Mapping[int, str | Path] | None = None,
) -> DieInterceptCollection:
    """
    Capture MBE/MTE collar mouth intercepts for every identified resonator.

    Coordinates are in filter-die world space (same frame as ``origin_x`` /
    ``origin_y`` from step 2.3). Intercepts are read from original filter-die
    collar geometry (connect cells plus touching top-level filter metal).
    """
    c_cfg = collect_config or RtegCollectConfig()
    i_cfg = intercept_config or DieInterceptConfig()
    ref_map = (
        dict(reference_gds_by_index)
        if reference_gds_by_index is not None
        else {}
    )
    mte_connect = _find_connect_cell(identification, "connectMTE") is not None
    mbe_connect = _find_connect_cell(identification, "connectMBE") is not None

    items: list[DieCollarIntercepts] = []
    for i, res in enumerate(identification.resonators):
        anchor = _collect_anchor_center(res)
        ref_path = ref_map.get(i)
        if ref_path is not None:
            ref_mte, ref_mbe = _reference_layer_intercepts(
                ref_path, layermap, anchor, c_cfg
            )
            if ref_mte is not None and ref_mbe is not None:
                items.append(
                    DieCollarIntercepts(
                        index=i,
                        inst_name=res.inst_name,
                        mte=ref_mte,
                        mbe=ref_mbe,
                    )
                )
                continue

        preserved = collect_filter_die_collar_metal(
            res, identification, layermap, c_cfg
        )
        body_mte = _resonator_body_mte_at_filter(res, layermap, c_cfg)
        body_mbe = _resonator_body_mbe_at_filter(res, layermap, c_cfg)

        mte = _extract_layer_intercept(
            c_cfg.mte_layer,
            preserved.mte,
            body_mte,
            mte_connect,
            i_cfg,
            anchor,
            res.rotation,
        )
        mbe = _extract_layer_intercept(
            c_cfg.mbe_layer,
            preserved.mbe,
            body_mbe,
            mbe_connect,
            i_cfg,
            anchor,
            res.rotation,
        )
        items.append(
            DieCollarIntercepts(
                index=i,
                inst_name=res.inst_name,
                mte=mte,
                mbe=mbe,
            )
        )

    return DieInterceptCollection(parent=identification.parent, items=items)


def _layer_intercept_row(prefix: str, layer: LayerCollarIntercept | None) -> dict[str, object]:
    if layer is None:
        return {
            f"{prefix}_status": None,
            f"{prefix}_intercept_a": None,
            f"{prefix}_intercept_b": None,
            f"{prefix}_mouth_span_um": None,
            f"{prefix}_mouth_angle_deg": None,
            f"{prefix}_entry_angle_deg": None,
            f"{prefix}_collar_area_um2": None,
            f"{prefix}_n_connect_pieces": None,
            f"{prefix}_anchor_center": None,
            f"{prefix}_intercept_a_local": None,
            f"{prefix}_intercept_b_local": None,
        }
    return {
        f"{prefix}_status": layer.status,
        f"{prefix}_intercept_a": _fmt_point(layer.intercept_a),
        f"{prefix}_intercept_b": _fmt_point(layer.intercept_b),
        f"{prefix}_mouth_span_um": layer.mouth_span_um,
        f"{prefix}_mouth_angle_deg": layer.mouth_angle_deg,
        f"{prefix}_entry_angle_deg": layer.entry_angle_deg,
        f"{prefix}_collar_area_um2": layer.collar_area_um2,
        f"{prefix}_n_connect_pieces": layer.n_connect_pieces,
        f"{prefix}_anchor_center": _fmt_point(layer.anchor_center),
        f"{prefix}_intercept_a_local": _fmt_point(layer.intercept_a_local),
        f"{prefix}_intercept_b_local": _fmt_point(layer.intercept_b_local),
    }


def die_intercept_rows(
    collection: DieInterceptCollection,
) -> list[dict[str, object]]:
    """Flat table rows keyed by resonator ``index``."""
    rows: list[dict[str, object]] = []
    for item in collection.items:
        row: dict[str, object] = {
            "index": item.index,
            "inst_name": item.inst_name,
        }
        row.update(_layer_intercept_row("mte", item.mte))
        row.update(_layer_intercept_row("mbe", item.mbe))
        rows.append(row)
    return rows


def merge_resonator_intercept_rows(
    identification: IdentificationResult,
    layermap: LayerMap,
    *,
    die_intercepts: DieInterceptCollection | None = None,
    collect_config: RtegCollectConfig | None = None,
    intercept_config: DieInterceptConfig | None = None,
) -> list[dict[str, object]]:
    """Step 2.3 resonator rows merged with step 2.4 intercept columns on ``index``."""
    collection = die_intercepts or collect_die_collar_intercepts(
        identification,
        layermap,
        collect_config=collect_config,
        intercept_config=intercept_config,
    )
    intercept_by_index = collection.by_index()
    merged: list[dict[str, object]] = []
    for base in identification.resonator_rows():
        idx = int(base["index"])
        item = intercept_by_index.get(idx)
        row = dict(base)
        if item is not None:
            row.update(_layer_intercept_row("mte", item.mte))
            row.update(_layer_intercept_row("mbe", item.mbe))
        merged.append(row)
    return merged


def transform_point_to_rteg(
    point: Point,
    res: Resonator,
    assembly: RtegFrameAssembly,
) -> Point:
    """Map a filter-die point to RTEG world coordinates (origin shift)."""
    dx, dy = _resonator_shift(res, assembly)
    return (point[0] + dx, point[1] + dy)


def transform_local_intercept_to_rteg(
    intercept: LayerCollarIntercept,
    res: Resonator,
    assembly: RtegFrameAssembly,
) -> tuple[Point, Point] | None:
    """
    Place die intercept mouth corners using resonator-local offsets.

    Offsets are measured from the resonator metal bbox center at filter capture
    and re-applied at the RTEG metal bbox center (stable across frame moves).
    """
    if (
        intercept.status != "ok"
        or intercept.intercept_a_local is None
        or intercept.intercept_b_local is None
    ):
        return None
    dx, dy = _resonator_shift(res, assembly)
    center = resonator_anchor_center(res, dx, dy)
    return (
        _body_local_to_world(intercept.intercept_a_local, center, res.rotation),
        _body_local_to_world(intercept.intercept_b_local, center, res.rotation),
    )


LayerName = Literal["mte", "mbe"]


@dataclass(frozen=True)
class DieRoutingContext:
    """
    Collar mouth targets for steps 5–6 routing.

    Production: step-2.4 filter-die intercepts (``KB331_N_01.gds``) transformed
    into the RTEG assembly frame and snapped onto preserved collar metal.
    ``reference_gds_by_index`` is optional golden-layout validation only.
    """

    die_intercepts: DieInterceptCollection | None
    res_by_index: Mapping[int, Resonator]
    assembly_by_index: Mapping[int, RtegFrameAssembly]
    rteg_lips_by_index: Mapping[int, Mapping[LayerName, LipIntercept]] = field(
        default_factory=dict
    )
    rteg_extra_collars_by_index: Mapping[
        int, Mapping[LayerName, tuple[TaggedPolygon, ...]]
    ] = field(default_factory=dict)

    def extra_collars(self, index: int, layer: LayerName) -> list[TaggedPolygon]:
        by_layer = self.rteg_extra_collars_by_index.get(index)
        if by_layer is None:
            return []
        return list(by_layer.get(layer, ()))

    @classmethod
    def from_lists(
        cls,
        die_intercepts: DieInterceptCollection,
        res_list: Sequence[Resonator],
        assemblies: Sequence[RtegFrameAssembly] | Mapping[int, RtegFrameAssembly],
    ) -> DieRoutingContext:
        if isinstance(assemblies, Mapping):
            asm_map = dict(assemblies)
        else:
            asm_map = {i: asm for i, asm in enumerate(assemblies)}
        return cls(
            die_intercepts=die_intercepts,
            res_by_index={i: res for i, res in enumerate(res_list)},
            assembly_by_index=asm_map,
        )

    @classmethod
    def from_rteg_roles(
        cls,
        roles_by_index: Mapping[int, object],
        classifications_by_index: Mapping[int, object],
        layermap: LayerMap,
        *,
        res_list: Sequence[Resonator],
        assemblies: Sequence[RtegFrameAssembly] | Mapping[int, RtegFrameAssembly],
        identification: IdentificationResult,
        die_intercepts: DieInterceptCollection | None = None,
        reference_gds_by_index: Mapping[int, str | Path] | None = None,
    ) -> DieRoutingContext:
        if isinstance(assemblies, Mapping):
            asm_map = dict(assemblies)
        else:
            asm_map = {i: asm for i, asm in enumerate(assemblies)}
        res_map = {i: res for i, res in enumerate(res_list)}
        lips, extras = build_rteg_routing_lips(
            roles_by_index,
            classifications_by_index,
            layermap,
            res_by_index=res_map,
            assembly_by_index=asm_map,
            identification=identification,
            die_intercepts=die_intercepts,
            reference_gds_by_index=reference_gds_by_index,
        )
        return cls(
            die_intercepts=die_intercepts,
            res_by_index=res_map,
            assembly_by_index=asm_map,
            rteg_lips_by_index=lips,
            rteg_extra_collars_by_index=extras,
        )

    def lip(self, index: int, layer: LayerName) -> LipIntercept | None:
        rteg_lips = self.rteg_lips_by_index.get(index)
        if rteg_lips is not None and layer in rteg_lips:
            return rteg_lips[layer]

        if self.die_intercepts is None:
            return None
        item = self.die_intercepts.get(index)
        res = self.res_by_index.get(index)
        assembly = self.assembly_by_index.get(index)
        if item is None or res is None or assembly is None:
            return None
        intercept = item.mte if layer == "mte" else item.mbe
        if intercept is None:
            return None
        return transform_die_intercept_to_rteg(intercept, res, assembly)

    def collar_mouth(
        self, index: int, layer: LayerName
    ) -> tuple[Point, Point] | None:
        lip = self.lip(index, layer)
        if lip is None:
            return None
        return lip.point_a, lip.point_b


def mouth_hits_for_pad(mouth_a: Point, mouth_b: Point) -> tuple[Point, Point]:
    """Order die mouth corners as (top hit, bottom hit) for pad TR/BR routing."""
    if mouth_a[1] >= mouth_b[1]:
        return mouth_a, mouth_b
    return mouth_b, mouth_a


def mouth_hits_for_left_edge(mouth_a: Point, mouth_b: Point) -> tuple[Point, Point]:
    """Order die mouth corners as (bottom hit, top hit) for filler left-edge trace."""
    if mouth_a[1] <= mouth_b[1]:
        return mouth_a, mouth_b
    return mouth_b, mouth_a


def transform_die_intercept_to_rteg(
    intercept: LayerCollarIntercept,
    res: Resonator,
    assembly: RtegFrameAssembly,
) -> LipIntercept | None:
    """
    Transform a filter-die ``LayerCollarIntercept`` into a ``LipIntercept``
    in RTEG world space for steps 5–6 routing.
    """
    if intercept.status != "ok" or intercept.outward_normal is None:
        return None

    local_pts = transform_local_intercept_to_rteg(intercept, res, assembly)
    if local_pts is not None:
        point_a, point_b = local_pts
    elif intercept.intercept_a is not None and intercept.intercept_b is not None:
        point_a = transform_point_to_rteg(intercept.intercept_a, res, assembly)
        point_b = transform_point_to_rteg(intercept.intercept_b, res, assembly)
    else:
        return None

    return LipIntercept(
        point_a=point_a,
        point_b=point_b,
        lip_vertex_indices=[],
        outward_normal=intercept.outward_normal,
        lip_edges=[],
    )


def _mouth_from_axis_aligned_rect(
    poly: gdstk.Polygon,
) -> tuple[Point, Point] | None:
    """Mouth = the shorter vertical or horizontal edge pair on a 4-vertex rectangle."""
    pts = [(float(x), float(y)) for x, y in poly.points]
    if len(pts) != 4:
        return None
    bb = poly.bounding_box()
    if bb is None:
        return None
    (x0, y0), (x1, y1) = bb
    width, height = x1 - x0, y1 - y0
    if height >= width:
        x_m = (x0 + x1) / 2.0
        return ((x_m, y0), (x_m, y1))
    y_m = (y0 + y1) / 2.0
    return ((x0, y_m), (x1, y_m))


def extract_reference_rteg_intercepts(
    gds_path: str | Path,
    layermap: LayerMap,
    *,
    mte_area_range: tuple[float, float] = (300.0, 900.0),
    mbe_area_range: tuple[float, float] = (600.0, 1500.0),
) -> dict[str, object]:
    """
    Read a hand-drawn reference RTEG GDS and extract pad-facing collar mouths.

    Looks for small axis-aligned MTE/MBE rectangles (extension strips) in the
    flat layout and returns mouth corners in RTEG world coordinates plus offsets
    relative to the placed series resonator bbox center.
    """
    lib = gdstk.read_gds(str(gds_path))
    top = lib.top_level()[0]
    series_ref = next(
        (r for r in top.references if r.cell and r.cell.name.startswith("series")),
        None,
    )
    if series_ref is None:
        raise ValueError(f"no series resonator reference in {gds_path}")

    tmp = gdstk.Cell("_ref_res")
    tmp.add(series_ref)
    anchor = resonator_anchor_center_from_polys(tmp.flatten().polygons)

    flat = top.flatten()
    out: dict[str, object] = {
        "cell": top.name,
        "resonator_ref": series_ref.cell.name,
        "anchor_center": anchor,
    }
    for layer_name, pair_key, area_range in (
        ("BAW_MTE", "mte", mte_area_range),
        ("BAW_MBE", "mbe", mbe_area_range),
    ):
        pair = layermap.pair(layer_name)
        candidates = [
            p
            for p in flat.polygons
            if (p.layer, p.datatype) == pair
            and area_range[0] <= abs(p.area()) <= area_range[1]
            and len(p.points) == 4
        ]
        if not candidates:
            out[pair_key] = None
            continue
        poly = min(candidates, key=lambda p: abs(p.area()))
        mouth = _mouth_from_axis_aligned_rect(poly)
        if mouth is None:
            out[pair_key] = None
            continue
        a, b = mouth
        out[pair_key] = {
            "intercept_a": a,
            "intercept_b": b,
            "mouth_span_um": round(_dist(a, b), 3),
            "intercept_a_local": _local_offset(a, anchor),
            "intercept_b_local": _local_offset(b, anchor),
            "polygon_area_um2": round(abs(poly.area()), 1),
        }
    return out


def resonator_anchor_center_from_polys(polys: Sequence[gdstk.Polygon]) -> Point:
    bb = polys_bbox(list(polys))
    if bb is None:
        return (0.0, 0.0)
    return bbox_center(bb)


def compare_filter_reference_locals(
    die_item: DieCollarIntercepts,
    reference: dict[str, object],
    *,
    layer: LayerName,
    tol_um: float = 5.0,
) -> dict[str, object]:
    """Compare filter-die local intercepts to a reference RTEG layout."""
    li = die_item.mte if layer == "mte" else die_item.mbe
    ref_layer = reference.get(layer)
    row: dict[str, object] = {"layer": layer, "status": "missing"}
    if li is None or li.status != "ok" or ref_layer is None:
        return row
    ref = ref_layer
    assert isinstance(ref, dict)
    da = _dist(li.intercept_a_local, ref["intercept_a_local"])  # type: ignore[arg-type]
    db = _dist(li.intercept_b_local, ref["intercept_b_local"])  # type: ignore[arg-type]
    row = {
        "layer": layer,
        "filter_a_local": li.intercept_a_local,
        "filter_b_local": li.intercept_b_local,
        "ref_a_local": ref["intercept_a_local"],
        "ref_b_local": ref["intercept_b_local"],
        "delta_a_local_um": round(da, 2),
        "delta_b_local_um": round(db, 2),
        "match": da <= tol_um and db <= tol_um,
    }
    return row
