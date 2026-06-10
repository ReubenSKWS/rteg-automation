"""
Shared geometry helpers for the modular R-tag pipeline.

Used by ``prep_resonator_ppd`` (step 3), ``prep_rteg_frame`` (step 4), and
``export_gds``. Step 5 routing may extend this module later.
"""
from __future__ import annotations

import gdstk

from separate import Resonator


def bbox_center(
    bbox: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[float, float]:
    (x0, y0), (x1, y1) = bbox
    return (x0 + x1) / 2, (y0 + y1) / 2


def translate_bbox(
    bbox: tuple[tuple[float, float], tuple[float, float]],
    origin: tuple[float, float],
) -> tuple[tuple[float, float], tuple[float, float]]:
    (x0, y0), (x1, y1) = bbox
    ox, oy = origin
    return (x0 + ox, y0 + oy), (x1 + ox, y1 + oy)


def resonator_world_bbox(
    res: Resonator,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Resonator master bbox after filter placement (origin, rotation preserved)."""
    rb = res.reference.cell.bounding_box()
    if rb is None:
        raise ValueError(f"No bounding box for {res.master_name}")
    (rx0, ry0), (rx1, ry1) = rb
    ox, oy = res.origin
    return (rx0 + ox, ry0 + oy), (rx1 + ox, ry1 + oy)


def frame_top_cell(frame_lib: gdstk.Library) -> gdstk.Cell:
    """Return the sole top cell, or the largest by bbox area if ambiguous."""
    tops = frame_lib.top_level()
    if len(tops) == 1:
        return tops[0]

    def area(cell: gdstk.Cell) -> float:
        bb = cell.bounding_box()
        if bb is None:
            return 0.0
        (x0, y0), (x1, y1) = bb
        return (x1 - x0) * (y1 - y0)

    return max(tops or frame_lib.cells, key=area)
