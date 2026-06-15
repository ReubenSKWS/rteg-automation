"""
Step 5.4 — Stretch 5.3 MTE collar extensions to the center signal pad.

When ``mte_route_target == "center_pad"``, move the pad-facing outer cap of the
5.3 extension to the nearest signal-pad edge corners (with overlap). The collar
mouth is taken from the 5.3 extension unless that mouth has negligible span
along the pad edge — then the full collar edge facing the pad is used instead.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

import gdstk

from layermap import LayerMap
from rteg_classify import NodeClassification
from rteg_collect import RtegGeometryRoles
from rteg_mte_extensions import CollarExtensionDraw, MteExtensionResult, _body_centroid, _edge_length, _edge_outward_normal, _edge_points
from rteg_utils import assign_layer, polys_bbox

Point = tuple[float, float]
Bbox = tuple[tuple[float, float], tuple[float, float]]
Edge = tuple[Point, Point]


@dataclass(frozen=True)
class MteRouteConfig:
    """Tunable parameters for step 5.4 pad stretch routing."""

    mte_layer: str = "BAW_MTE"
    pad_touch_overlap_um: float = 0.5
    collar_merge_inset_um: float = 4.0
    min_pad_overlap_um2: float = 0.01
    min_mouth_span_fraction: float = 0.5
    boolean_precision: float = 1e-3
    inside_probe_half_um: float = 0.25


@dataclass(frozen=True)
class RouteStart:
    """Attach point on the pad-facing edge of the 5.3 extension."""

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

    When the 5.3 lip extrudes away from the route target (outer cap on the far
    side), use the collar-mouth edge as the pad-facing reference instead.
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
) -> tuple[gdstk.Polygon, PadAttachmentEdge]:
    """
    Morph the 5.3 extension: collar mouth on the pad-facing side, outer cap on pad.

    Returns the stretched polygon and pad attachment metadata.
    """
    outer_b, outer_a = _outer_vertices(draw)

    ref = from_point
    if ref is None:
        ref = (
            (outer_a[0] + outer_b[0]) / 2.0,
            (outer_a[1] + outer_b[1]) / 2.0,
        )

    inner_a, inner_b = _resolve_stretch_inner_mouth(
        draw,
        signal_polys,
        cfg,
        collar=collar,
        body_mte_polys=body_mte_polys,
        from_point=ref,
    )

    attachment = pick_pad_attachment_edge(
        signal_polys, ref, touch_overlap_um=cfg.pad_touch_overlap_um
    )

    pad_low = attachment.corner_low
    pad_high = attachment.corner_high

    if outer_b[1] <= outer_a[1]:
        outer_b_new, outer_a_new = pad_low, pad_high
    else:
        outer_b_new, outer_a_new = pad_high, pad_low

    stretched = gdstk.Polygon(
        [inner_a, inner_b, outer_b_new, outer_a_new],
        layer=layer,
        datatype=datatype,
    )
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
            f"(overlap {overlap:.4f} um² < {cfg.min_pad_overlap_um2:.4f} um²)"
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
    if mte_result.extension is None or mte_result.extension_draw is None:
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
    stretched, attachment = stretch_extension_to_pad(
        draw,
        signal_polys,
        c,
        layer,
        datatype,
        from_point=start_info.center,
        collar=collar_poly,
        body_mte_polys=roles.resonator_body_mte,
    )
    stretched = assign_layer(stretched, layermap, c.mte_layer)
    overlap = validate_pad_attachment(
        stretched,
        signal_polys,
        c,
        resonator_index=resonator_index,
    )
    return MteRouteDraw(
        route_polygon=stretched,
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
    "RouteStart",
    "apply_mte_pad_route",
    "build_mte_pad_route",
    "build_mte_pad_routes",
    "collar_mouth_facing_pad",
    "mte_route_overview_rows",
    "pick_pad_attachment_edge",
    "pick_route_start",
    "stretch_extension_to_pad",
    "validate_pad_attachment",
]
