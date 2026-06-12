"""
Step 5.2 (geometry) — resonator collar orientation and placement.

Pure-geometry analysis of where a resonator's preserved collar metal points
relative to the GSG probe pads. Downstream classification (``rteg_classify``)
uses this to decide which terminal (MTE / MBE) is the signal connection and
which pad band is the signal pad — replacing the old ``res_type`` table.

All functions take bounding boxes / polygons in and return plain values; no
resonator or assembly objects are referenced inside, so the same helpers serve
both the deterministic orchestrator and any future agent tool-call.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import gdstk

from rteg_utils import polys_bbox

Point = tuple[float, float]
Bbox = tuple[Point, Point]
Axis = Literal["east_west", "north_south"]
Band = Literal["top", "center", "bottom"]
MteRouteTarget = Literal["center_pad", "collar_extend"]

_ELONGATION_RATIO = 2.5


@dataclass(frozen=True)
class BboxSummary:
    """Axis-aligned bounding box with derived center and extents."""

    min_xy: Point
    max_xy: Point
    center: Point
    width: float
    height: float

    @property
    def bbox(self) -> Bbox:
        return (self.min_xy, self.max_xy)


@dataclass(frozen=True)
class CollarOrientation:
    """How the preserved collar metal sits relative to the GSG pads."""

    axis: Axis
    mte_faces_center: bool
    mte_route_target: MteRouteTarget
    facing_pad: Band
    placement_shift: tuple[float, float]

    @property
    def mte_faces_pad(self) -> bool:
        """True when preserved MTE routes to the center signal pad."""
        return self.mte_faces_center


@dataclass(frozen=True)
class OrientationAnalysis:
    """Bundle of bbox summaries plus the collar orientation decision."""

    body: BboxSummary
    mte_collar: BboxSummary | None
    mbe_collar: BboxSummary | None
    collar: CollarOrientation


def bbox_summary(
    source: gdstk.Polygon | Sequence[gdstk.Polygon] | Bbox,
) -> BboxSummary | None:
    """Summarize a polygon, sequence of polygons, or raw bbox tuple."""
    if isinstance(source, gdstk.Polygon):
        bb = source.bounding_box()
    elif isinstance(source, tuple):
        bb = source
    else:
        bb = polys_bbox(source)
    if bb is None:
        return None
    (x0, y0), (x1, y1) = bb
    return BboxSummary(
        min_xy=(x0, y0),
        max_xy=(x1, y1),
        center=((x0 + x1) / 2.0, (y0 + y1) / 2.0),
        width=x1 - x0,
        height=y1 - y0,
    )


def _union_bbox(boxes: Sequence[Bbox]) -> Bbox:
    return (
        (min(b[0][0] for b in boxes), min(b[0][1] for b in boxes)),
        (max(b[1][0] for b in boxes), max(b[1][1] for b in boxes)),
    )


def collar_axis(
    mte_bbox: BboxSummary | None,
    mbe_bbox: BboxSummary | None,
    body_bbox: BboxSummary,
) -> Axis:
    """Collar long axis: ``east_west`` when wider than tall, else ``north_south``."""
    boxes = [b.bbox for b in (mte_bbox, mbe_bbox) if b is not None]
    ref = bbox_summary(_union_bbox(boxes)) if boxes else body_bbox
    assert ref is not None
    return "east_west" if ref.width >= ref.height else "north_south"


def _nearest_band(
    point: Point, pad_bboxes_by_band: Mapping[str, Bbox | None]
) -> Band:
    best_band: Band = "center"
    best_d = float("inf")
    for band, bb in pad_bboxes_by_band.items():
        if bb is None:
            continue
        cx, cy = (bb[0][0] + bb[1][0]) / 2.0, (bb[0][1] + bb[1][1]) / 2.0
        d = math.hypot(point[0] - cx, point[1] - cy)
        if d < best_d:
            best_d = d
            best_band = band  # type: ignore[assignment]
    return best_band


def pad_facing_direction(
    collar_bbox: BboxSummary,
    pad_bboxes_by_band: Mapping[str, Bbox | None],
) -> Band:
    """GSG band whose pad center is closest to the collar — the pad it faces."""
    return _nearest_band(collar_bbox.center, pad_bboxes_by_band)


def _pad_center(bb: Bbox) -> Point:
    return ((bb[0][0] + bb[1][0]) / 2.0, (bb[0][1] + bb[1][1]) / 2.0)


def mte_opposite_center_pad_east_west(
    mte_bbox: BboxSummary,
    body_bbox: BboxSummary,
    center_pad_bb: Bbox | None,
) -> bool:
    """
    True when east-west MTE sits on the far side of the body from the center pad.

    GSG pads sit west of the resonator; MTE on the east half (past the pad–body
    midpoint in X) is directly opposite the center pad even if Y aligns with the
    center band.
    """
    if center_pad_bb is None:
        return False
    pad_cx = _pad_center(center_pad_bb)[0]
    body_cx = body_bbox.center[0]
    mte_cx = mte_bbox.center[0]
    mid_x = (pad_cx + body_cx) / 2.0
    if pad_cx <= body_cx:
        return mte_cx > mid_x
    return mte_cx < mid_x


def mte_faces_center_pad(
    mte_bbox: BboxSummary | None,
    pad_bboxes_by_band: Mapping[str, Bbox | None],
    *,
    body_bbox: BboxSummary | None = None,
    axis: Axis | None = None,
) -> bool:
    """
    True when MTE may route to the center signal pad.

    Requires nearest band **center**, and for east-west collars MTE must sit on
    the pad side of the body (not directly opposite across the body midline).
    """
    if mte_bbox is None:
        return False
    if _nearest_band(mte_bbox.center, pad_bboxes_by_band) != "center":
        return False
    if axis == "east_west" and body_bbox is not None:
        center_bb = pad_bboxes_by_band.get("center")
        if mte_opposite_center_pad_east_west(mte_bbox, body_bbox, center_bb):
            return False
    return True


def mte_route_target(
    mte_bbox: BboxSummary | None,
    pad_bboxes_by_band: Mapping[str, Bbox | None],
    *,
    body_bbox: BboxSummary | None = None,
    axis: Axis | None = None,
) -> MteRouteTarget:
    """``center_pad`` when MTE faces center; else a short collar extension only."""
    if mte_faces_center_pad(
        mte_bbox, pad_bboxes_by_band, body_bbox=body_bbox, axis=axis
    ):
        return "center_pad"
    return "collar_extend"


def mte_faces_signal_pad(
    mte_bbox: BboxSummary | None,
    facing_pad: Band,
    pad_bboxes_by_band: Mapping[str, Bbox | None],
    *,
    body_bbox: BboxSummary | None = None,
    axis: Axis | None = None,
) -> bool:
    """Deprecated alias — use ``mte_faces_center_pad``."""
    _ = facing_pad
    return mte_faces_center_pad(
        mte_bbox, pad_bboxes_by_band, body_bbox=body_bbox, axis=axis
    )


def recommend_placement_shift(
    axis: Axis,
    collar_bbox: BboxSummary | None,
    pad_bbox: Bbox | None,
    body_bbox: BboxSummary,
) -> tuple[float, float]:
    """
    Extra ``(dx, dy)`` placement nudge from collar orientation.

    - East-west collar: no shift (already aligned with the pad row).
    - North-south collar: Y-shift bringing the collar center onto the signal
      pad center.
    - Very elongated body: small X-shift **away** from the signal pad to free
      ground-side routing space (never toward the pad).
    """
    if collar_bbox is None or pad_bbox is None:
        return (0.0, 0.0)
    pad_cx = (pad_bbox[0][0] + pad_bbox[1][0]) / 2.0
    pad_cy = (pad_bbox[0][1] + pad_bbox[1][1]) / 2.0

    dy = 0.0
    if axis == "north_south":
        dy = pad_cy - collar_bbox.center[1]

    dx = 0.0
    long, short = max(body_bbox.width, body_bbox.height), min(
        body_bbox.width, body_bbox.height
    )
    if short > 0 and long / short >= _ELONGATION_RATIO:
        away = -1.0 if body_bbox.center[0] >= pad_cx else 1.0
        dx = away * 0.5 * short

    return (dx, dy)


def analyze_orientation(
    body_polys: Sequence[gdstk.Polygon],
    mte_polys: Sequence[gdstk.Polygon],
    mbe_polys: Sequence[gdstk.Polygon],
    pad_bboxes_by_band: Mapping[str, Bbox | None],
) -> OrientationAnalysis:
    """
    Orchestrate collar orientation for one resonator from raw polygons.

    ``pad_bboxes_by_band`` maps ``"top"`` / ``"center"`` / ``"bottom"`` to the
    signal-side pad bbox (or ``None`` when a band has no pad).
    """
    body = bbox_summary(body_polys)
    if body is None:
        raise ValueError("resonator body has no bounding box")
    mte = bbox_summary(mte_polys)
    mbe = bbox_summary(mbe_polys)

    collar_summary = mte or mbe or body
    axis = collar_axis(mte, mbe, body)
    facing_pad = pad_facing_direction(collar_summary, pad_bboxes_by_band)
    faces_center = mte_faces_center_pad(
        mte, pad_bboxes_by_band, body_bbox=body, axis=axis
    )
    route = mte_route_target(
        mte, pad_bboxes_by_band, body_bbox=body, axis=axis
    )
    shift = recommend_placement_shift(
        axis, collar_summary, pad_bboxes_by_band.get("center"), body
    )

    return OrientationAnalysis(
        body=body,
        mte_collar=mte,
        mbe_collar=mbe,
        collar=CollarOrientation(
            axis=axis,
            mte_faces_center=faces_center,
            mte_route_target=route,
            facing_pad=facing_pad,
            placement_shift=shift,
        ),
    )
