"""
Shared geometry helpers for the modular R-tag pipeline.

Used by ``prep_resonator_ppd`` (step 3), ``prep_rteg_frame`` (step 4),
``rteg_collect`` (step 5.1), ``rteg_orientation`` (step 5.2), ``rteg_mte_extensions``
(step 5.3), and ``export_gds``.
"""
from __future__ import annotations

from collections.abc import Sequence

import gdstk

from layermap import LayerMap
from separate import Resonator

Point = tuple[float, float]
Bbox = tuple[Point, Point]


def bbox_center(
    bbox: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[float, float]:
    (x0, y0), (x1, y1) = bbox
    return (x0 + x1) / 2, (y0 + y1) / 2


def polys_bbox(polys: Sequence[gdstk.Polygon]) -> Bbox | None:
    """Union bounding box of a sequence of polygons (``None`` when empty)."""
    boxes = [bb for p in polys if (bb := p.bounding_box()) is not None]
    if not boxes:
        return None
    return (
        (min(b[0][0] for b in boxes), min(b[0][1] for b in boxes)),
        (max(b[1][0] for b in boxes), max(b[1][1] for b in boxes)),
    )


def assign_layer(
    poly: gdstk.Polygon,
    layermap: LayerMap,
    layer_name: str,
) -> gdstk.Polygon:
    """Re-tag a polygon onto ``layer_name`` (gdstk booleans drop layer/datatype)."""
    layer, datatype = layermap.pair(layer_name)
    return gdstk.Polygon(list(poly.points), layer, datatype)


def split_by_y_gaps(
    polys: Sequence[gdstk.Polygon],
) -> tuple[list[gdstk.Polygon], list[gdstk.Polygon], list[gdstk.Polygon]]:
    """
    Split polygons into top / center / bottom groups (by Y centroid).

    Sorts by Y centroid descending and cuts at the two largest gaps. With fewer
    than three polygons everything lands in the top group. Shared by the GSG pad
    banding in ``rteg_collect`` (step 5.1) and the orientation pad bboxes in
    ``prep_resonator_ppd`` (step 3).
    """
    entries: list[tuple[float, gdstk.Polygon]] = []
    for poly in polys:
        bb = poly.bounding_box()
        if bb is None:
            continue
        entries.append(((bb[0][1] + bb[1][1]) / 2.0, poly))
    if len(entries) < 3:
        return [p for _, p in entries], [], []

    entries.sort(key=lambda item: item[0], reverse=True)
    ys = [cy for cy, _ in entries]
    gaps = sorted(((ys[i] - ys[i + 1], i) for i in range(len(ys) - 1)), reverse=True)
    split_a, split_b = sorted((gaps[0][1], gaps[1][1]))
    top = [p for _, p in entries[: split_a + 1]]
    center = [p for _, p in entries[split_a + 1 : split_b + 1]]
    bottom = [p for _, p in entries[split_b + 1 :]]
    return top, center, bottom


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
