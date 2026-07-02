"""
Step 5.5 — Right-edge bridge for split MBE rectangle filler.

After step 5.3b keepout carving, some ``collar_extend`` resonators end up with the
step-4 MBE width-filler rectangle split into two disconnected plate polygons
(e.g. KB331 index 0). Reconnect them with a 1 µm-wide vertical strap from the
rectangle top-right corner down to the bottom-right corner at the same height as
the GSG MBE frame (layer 2/0 top/bottom ground plates), then merge into one
closed polygon. Then append an independent MBE frame-ring cap polygon on the same
layer (not unioned into the filler plate). No clearance rules apply to the bridge
or cap.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

import gdstk

from layermap import LayerMap
from rteg_classify import NodeClassification
from rteg_filler_keepout import filler_keepout_applies
from rteg_route_clean import SpikeCleanConfig, clean_route_polygon_spikes
from rteg_route_new import ResonatorRoute
from rteg_utils import polys_bbox

DEFAULT_FILLER_BRIDGE_WIDTH_UM = 1.0
DEFAULT_MIN_SPLIT_PLATE_AREA_UM2 = 100.0
DEFAULT_FRAME_CAP_OVERLAP_UM = 5.0

# Boolean union of the 1 µm bridge strap with carved plate pieces can leave
# ultra-acute tips on the strap's left edge where one adjacent edge is long.
FILLER_BRIDGE_SPIKE_CLEAN = SpikeCleanConfig(
    max_interior_angle_deg=45.0,
    max_spike_edge_um=500.0,
    max_spike_height_um=4.0,
    acute_interior_angle_deg=5.0,
    acute_short_edge_um=500.0,
)


@dataclass(frozen=True)
class FillerBridgeConfig:
    bridge_width_um: float = DEFAULT_FILLER_BRIDGE_WIDTH_UM
    min_plate_piece_area_um2: float = DEFAULT_MIN_SPLIT_PLATE_AREA_UM2
    frame_cap_overlap_um: float = DEFAULT_FRAME_CAP_OVERLAP_UM
    boolean_precision: float = 1e-3
    spike_cfg: SpikeCleanConfig = FILLER_BRIDGE_SPIKE_CLEAN


@dataclass(frozen=True)
class FillerBridgeResult:
    applied: bool
    n_plate_pieces: int
    bridge_from: tuple[float, float] | None
    bridge_to: tuple[float, float] | None
    bridge_width_um: float
    bridge_length_um: float | None
    frame_cap_applied: bool
    frame_cap_x0: float | None
    frame_cap_x1: float | None
    frame_cap_overlap_um: float
    filler_pieces_before: int
    filler_pieces_after: int

    def summary_row(
        self,
        *,
        index: int,
        inst_name: str,
        mte_route_target: str,
    ) -> dict[str, object]:
        fx, fy = self.bridge_from or (None, None)
        tx, ty = self.bridge_to or (None, None)
        return {
            "index": index,
            "inst_name": inst_name,
            "mte_route_target": mte_route_target,
            "applied": self.applied,
            "n_plate_pieces": self.n_plate_pieces,
            "bridge_from_x": round(fx, 2) if fx is not None else None,
            "bridge_from_y": round(fy, 2) if fy is not None else None,
            "bridge_to_x": round(tx, 2) if tx is not None else None,
            "bridge_to_y": round(ty, 2) if ty is not None else None,
            "bridge_width_um": self.bridge_width_um,
            "bridge_length_um": round(self.bridge_length_um, 2) if self.bridge_length_um is not None else None,
            "frame_cap_applied": self.frame_cap_applied,
            "frame_cap_x0": round(self.frame_cap_x0, 2) if self.frame_cap_x0 is not None else None,
            "frame_cap_x1": round(self.frame_cap_x1, 2) if self.frame_cap_x1 is not None else None,
            "frame_cap_overlap_um": self.frame_cap_overlap_um,
            "filler_pieces_before": self.filler_pieces_before,
            "filler_pieces_after": self.filler_pieces_after,
        }


def _rectangle_plate_pieces(
    filler_nets: Sequence[gdstk.Polygon],
    filler_plate: Sequence[gdstk.Polygon],
    *,
    precision: float,
) -> list[gdstk.Polygon]:
    """Filler-net fragments that overlap the step-4 MBE width-filler rectangle."""
    plate = list(filler_plate)
    if not plate or not filler_nets:
        return []
    pieces: list[gdstk.Polygon] = []
    for net_poly in filler_nets:
        overlap = gdstk.boolean([net_poly], plate, "and", precision=precision) or []
        pieces.extend(overlap)
    return pieces


def _substantial_plate_pieces(
    pieces: Sequence[gdstk.Polygon],
    *,
    min_area_um2: float,
) -> list[gdstk.Polygon]:
    return [p for p in pieces if abs(p.area()) >= min_area_um2]


def _filler_plate_bbox(
    filler_plate: Sequence[gdstk.Polygon],
) -> tuple[float, float, float, float] | None:
    """Return ``(x0, y0, x1, y1)`` for the step-4 MBE width-filler rectangle."""
    xs: list[float] = []
    ys: list[float] = []
    for poly in filler_plate:
        bb = poly.bounding_box()
        if bb:
            xs.extend([bb[0][0], bb[1][0]])
            ys.extend([bb[0][1], bb[1][1]])
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def gsg_frame_y_span(ground_plates: object) -> tuple[float, float] | None:
    """
    Y extent of the GSG MBE frame on layer 2/0.

    Matches ``ground_filler_frame_mask``: bottom ground-plate min-Y through top
    ground-plate max-Y.
    """
    top_bb = polys_bbox([tp.polygon for tp in ground_plates.top])
    bot_bb = polys_bbox([tp.polygon for tp in ground_plates.bottom])
    if not top_bb or not bot_bb:
        return None
    y_lo, y_hi = bot_bb[0][1], top_bb[1][1]
    if y_hi <= y_lo:
        return None
    return y_lo, y_hi


def right_edge_bridge_polygon(
    filler_plate: Sequence[gdstk.Polygon],
    ground_plates: object,
    *,
    width_um: float,
    layer: int,
    datatype: int,
) -> tuple[gdstk.Polygon, tuple[float, float], tuple[float, float]] | None:
    """1 µm-wide vertical strap on the rectangle right edge, GSG-frame height."""
    if width_um <= 0:
        return None
    bbox = _filler_plate_bbox(filler_plate)
    y_span = gsg_frame_y_span(ground_plates)
    if bbox is None or y_span is None:
        return None
    y0, y1 = y_span
    _x0, _plate_y0, x1, _plate_y1 = bbox
    top_right = (x1, y1)
    bottom_right = (x1, y0)
    return (
        gdstk.rectangle(
            (x1 - width_um, y0),
            (x1, y1),
            layer=layer,
            datatype=datatype,
        ),
        top_right,
        bottom_right,
    )


def _inner_cavity_right_x(frame_boundary: object) -> float | None:
    cavity = getattr(frame_boundary, "cavity", None)
    cavity_poly = getattr(cavity, "polygon", None) if cavity is not None else None
    cavity_bb = cavity_poly.bounding_box() if cavity_poly is not None else None
    if cavity_bb is None:
        return None
    return cavity_bb[1][0]


def right_frame_cap_polygon(
    filler_plate: Sequence[gdstk.Polygon],
    ground_plates: object,
    frame_boundary: object,
    *,
    overlap_um: float,
    layer: int,
    datatype: int,
) -> tuple[gdstk.Polygon, float, float] | None:
    """
    Independent MBE cap on the filler right edge, GSG-frame height, overlapping the die frame inward.

    Spans from the step-4 rectangle filler right edge to ``inner_cavity_right + overlap_um``
    so the cap reaches about ``overlap_um`` into the RTEG frame ring. Returned as its own
    closed polygon — not boolean-merged with the filler plate.
    """
    if overlap_um <= 0:
        return None
    bbox = _filler_plate_bbox(filler_plate)
    y_span = gsg_frame_y_span(ground_plates)
    cavity_right_x = _inner_cavity_right_x(frame_boundary)
    if bbox is None or y_span is None or cavity_right_x is None:
        return None
    y_lo, y_hi = y_span
    filler_right_x = bbox[2]
    cap_right_x = cavity_right_x + overlap_um
    if cap_right_x <= filler_right_x + 1e-6:
        return None
    return (
        gdstk.rectangle(
            (filler_right_x, y_lo),
            (cap_right_x, y_hi),
            layer=layer,
            datatype=datatype,
        ),
        filler_right_x,
        cap_right_x,
    )


def split_rectangle_plate_detected(
    filler_nets: Sequence[gdstk.Polygon],
    filler_plate: Sequence[gdstk.Polygon],
    *,
    cfg: FillerBridgeConfig | None = None,
) -> tuple[bool, list[gdstk.Polygon]]:
    """
    True when the step-4 rectangle plate appears as exactly two disconnected pieces.

    Tiny boolean slivers (center_pad notch artifacts) are ignored via ``min_plate_piece_area_um2``.
    """
    cfg = cfg or FillerBridgeConfig()
    pieces = _substantial_plate_pieces(
        _rectangle_plate_pieces(
            filler_nets, filler_plate, precision=cfg.boolean_precision,
        ),
        min_area_um2=cfg.min_plate_piece_area_um2,
    )
    if len(pieces) != 2:
        return False, pieces
    merged = gdstk.boolean(pieces, [], "or", precision=cfg.boolean_precision) or pieces
    return len(merged) == 2, pieces


def filler_bridge_applies(
    route: ResonatorRoute,
    roles: object,
    classification: NodeClassification,
    *,
    cfg: FillerBridgeConfig | None = None,
) -> bool:
    """``collar_extend`` routes whose carved rectangle plate split into two polygons."""
    if not filler_keepout_applies(classification):
        return False
    filler_plate = [tp.polygon for tp in roles.ground_plates.filler]
    detected, _ = split_rectangle_plate_detected(
        route.filler_nets, filler_plate, cfg=cfg,
    )
    return detected


def _union_filler_with_extras(
    filler_nets: Sequence[gdstk.Polygon],
    extras: Sequence[gdstk.Polygon],
    *,
    layer: int,
    datatype: int,
    precision: float,
    spike_cfg: SpikeCleanConfig,
) -> list[gdstk.Polygon]:
    if not extras:
        return list(filler_nets)
    merged = gdstk.boolean([*filler_nets, *extras], [], "or", precision=precision) or [
        *filler_nets,
        *extras,
    ]
    cleaned: list[gdstk.Polygon] = []
    for piece in merged:
        poly = gdstk.Polygon(
            [(float(x), float(y)) for x, y in piece.points],
            layer,
            datatype,
        )
        smoothed, _ = clean_route_polygon_spikes(poly, spike_cfg)
        cleaned.append(smoothed)
    if len(cleaned) > 1:
        remerged = gdstk.boolean(cleaned, [], "or", precision=precision) or cleaned
        cleaned = [
            gdstk.Polygon(
                [(float(x), float(y)) for x, y in piece.points],
                layer,
                datatype,
            )
            for piece in remerged
        ]
    return cleaned


def _merge_filler_with_bridge(
    filler_nets: Sequence[gdstk.Polygon],
    bridge: gdstk.Polygon,
    *,
    layer: int,
    datatype: int,
    precision: float,
    spike_cfg: SpikeCleanConfig,
) -> list[gdstk.Polygon]:
    return _union_filler_with_extras(
        filler_nets,
        [bridge],
        layer=layer,
        datatype=datatype,
        precision=precision,
        spike_cfg=spike_cfg,
    )


def apply_filler_bridge_to_route(
    route: ResonatorRoute,
    roles: object,
    classification: NodeClassification,
    layermap: LayerMap,
    *,
    cfg: FillerBridgeConfig | None = None,
) -> tuple[ResonatorRoute, FillerBridgeResult]:
    """Bridge a split rectangle plate, then append an independent frame-ring cap."""
    _ = layermap
    cfg = cfg or FillerBridgeConfig()
    precision = cfg.boolean_precision
    empty = FillerBridgeResult(
        applied=False,
        n_plate_pieces=0,
        bridge_from=None,
        bridge_to=None,
        bridge_width_um=cfg.bridge_width_um,
        bridge_length_um=None,
        frame_cap_applied=False,
        frame_cap_x0=None,
        frame_cap_x1=None,
        frame_cap_overlap_um=cfg.frame_cap_overlap_um,
        filler_pieces_before=len(route.filler_nets),
        filler_pieces_after=len(route.filler_nets),
    )

    if not filler_keepout_applies(classification) or not route.filler_nets:
        return route, empty

    filler_plate = [tp.polygon for tp in roles.ground_plates.filler]
    detected, plate_pieces = split_rectangle_plate_detected(
        route.filler_nets, filler_plate, cfg=cfg,
    )
    if not detected:
        return route, replace(empty, n_plate_pieces=len(plate_pieces))

    layer = route.filler_nets[0].layer
    datatype = route.filler_nets[0].datatype
    bridge_info = right_edge_bridge_polygon(
        filler_plate,
        roles.ground_plates,
        width_um=cfg.bridge_width_um,
        layer=layer,
        datatype=datatype,
    )
    if bridge_info is None:
        return route, replace(empty, n_plate_pieces=2)

    bridge, top_right, bottom_right = bridge_info
    bridge_length = top_right[1] - bottom_right[1]
    new_nets = _merge_filler_with_bridge(
        route.filler_nets,
        bridge,
        layer=layer,
        datatype=datatype,
        precision=precision,
        spike_cfg=cfg.spike_cfg,
    )

    frame_cap_applied = False
    frame_cap_x0: float | None = None
    frame_cap_x1: float | None = None
    cap_info = right_frame_cap_polygon(
        filler_plate,
        roles.ground_plates,
        roles.frame_boundary,
        overlap_um=cfg.frame_cap_overlap_um,
        layer=layer,
        datatype=datatype,
    )
    if cap_info is not None:
        cap, frame_cap_x0, frame_cap_x1 = cap_info
        new_nets = [*new_nets, cap]
        frame_cap_applied = True

    result = FillerBridgeResult(
        applied=True,
        n_plate_pieces=2,
        bridge_from=top_right,
        bridge_to=bottom_right,
        bridge_width_um=cfg.bridge_width_um,
        bridge_length_um=bridge_length,
        frame_cap_applied=frame_cap_applied,
        frame_cap_x0=frame_cap_x0,
        frame_cap_x1=frame_cap_x1,
        frame_cap_overlap_um=cfg.frame_cap_overlap_um,
        filler_pieces_before=len(route.filler_nets),
        filler_pieces_after=len(new_nets),
    )
    return replace(route, filler_nets=new_nets), result


def apply_filler_bridge_all_routes(
    routes: dict[int, ResonatorRoute],
    roles_by_index: dict[int, object],
    classifications: dict[int, NodeClassification],
    layermap: LayerMap,
    *,
    indices: Sequence[int] | None = None,
    cfg: FillerBridgeConfig | None = None,
) -> dict[int, ResonatorRoute]:
    """Apply step 5.5 filler bridge where the rectangle plate split."""
    out = dict(routes)
    keys = indices if indices is not None else sorted(routes)
    for idx in keys:
        if idx not in routes or idx not in roles_by_index or idx not in classifications:
            continue
        bridged, _ = apply_filler_bridge_to_route(
            routes[idx],
            roles_by_index[idx],
            classifications[idx],
            layermap,
            cfg=cfg,
        )
        out[idx] = bridged
    return out


def filler_bridge_overview_rows(
    routes: dict[int, ResonatorRoute],
    roles_by_index: dict[int, object],
    classifications: dict[int, NodeClassification],
    layermap: LayerMap,
    *,
    indices: Sequence[int] | None = None,
    cfg: FillerBridgeConfig | None = None,
    include_skipped: bool = False,
) -> list[dict[str, object]]:
    """Preview bridge stats without mutating routes."""
    keys = indices if indices is not None else sorted(routes)
    rows: list[dict[str, object]] = []
    for idx in keys:
        if idx not in routes or idx not in roles_by_index or idx not in classifications:
            continue
        classification = classifications[idx]
        if not include_skipped and not filler_keepout_applies(classification):
            continue
        roles = roles_by_index[idx]
        _, result = apply_filler_bridge_to_route(
            routes[idx], roles, classification, layermap, cfg=cfg,
        )
        if not include_skipped and not result.applied:
            continue
        rows.append(
            result.summary_row(
                index=idx,
                inst_name=roles.inst_name,
                mte_route_target=classification.mte_route_target,
            )
        )
    return rows


__all__ = [
    "DEFAULT_FILLER_BRIDGE_WIDTH_UM",
    "DEFAULT_FRAME_CAP_OVERLAP_UM",
    "DEFAULT_MIN_SPLIT_PLATE_AREA_UM2",
    "FILLER_BRIDGE_SPIKE_CLEAN",
    "FillerBridgeConfig",
    "FillerBridgeResult",
    "apply_filler_bridge_all_routes",
    "apply_filler_bridge_to_route",
    "right_edge_bridge_polygon",
    "right_frame_cap_polygon",
    "gsg_frame_y_span",
    "filler_bridge_applies",
    "filler_bridge_overview_rows",
    "split_rectangle_plate_detected",
]
