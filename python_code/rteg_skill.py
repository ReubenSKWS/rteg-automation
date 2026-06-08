"""
RTEG preprocessing helpers.

Naming, preserved-metal loading, and frame placement for prepare_rteg.py and
build_rteg.py. The GSG frame (KB331_N_Frame) sits at the cell top-left (0, 0).
The resonator is shifted so its signal feed centroid lands on the frame center.
"""
from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import gdstk

from layermap import LayerMap, load_layermap
from separate import Resonator

DEFAULT_FRAME_W = 66.6  # legacy; not used for placement (centering is used instead)
CONNECT_BACKUP_MIN_POLYS = 10
GOLDEN_ANCHOR_INDEX = 6
GOLDEN_ANCHOR_INST_NAME = "S3"
INST_MAP_PATH = Path(__file__).parent / "resonator_inst_map.json"

# GSG frame and ppd template both anchor at the top-left of the RTEG cell.
FRAME_ORIGIN = (0.0, 0.0)
PPD_ORIGIN = (0.0, 0.0)


def _bbox_center(
    bbox: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[float, float]:
    (x0, y0), (x1, y1) = bbox
    return (x0 + x1) / 2, (y0 + y1) / 2


def _signal_feed_layer(res: Resonator) -> str:
    """Layer carrying the resonator signal feed (matches route_rteg series/shunt rule)."""
    if res.res_type == "series":
        return "BAW_MTE"
    return "BAW_MBE"


def _world_layer_centroid(
    res: Resonator, layer_name: str, layermap: LayerMap
) -> tuple[float, float] | None:
    """Centroid of one layer's polygons in filter layout coordinates."""
    if layer_name not in layermap:
        return None
    layer, datatype = layermap.pair(layer_name)
    ox, oy = res.origin
    rot = res.rotation
    cos_r, sin_r = math.cos(rot), math.sin(rot)
    xs: list[float] = []
    ys: list[float] = []
    for poly in res.reference.cell.polygons:
        if (poly.layer, poly.datatype) != (layer, datatype):
            continue
        for x, y in poly.points:
            xr, yr = float(x), float(y)
            if res.x_reflection:
                xr = -xr
            xs.append(ox + cos_r * xr - sin_r * yr)
            ys.append(oy + sin_r * xr + cos_r * yr)
    if not xs:
        return None
    return sum(xs) / len(xs), sum(ys) / len(ys)


def placement_shift(
    res: Resonator,
    frame_cell: gdstk.Cell,
    layermap: LayerMap | None = None,
) -> tuple[float, float]:
    """
    (dx, dy) placing the resonator so its signal node sits on the frame center.

    Signal node = centroid of the signal feed layer on the resonator master
    (BAW_MTE for series, BAW_MBE for shunt). Falls back to bbox center if absent.
    Preserved metal and vias receive the same shift.
    """
    layermap = layermap or load_layermap()
    frame_bb = frame_cell.bounding_box()
    if frame_bb is None:
        raise ValueError("Frame cell has no bounding box")
    fcx, fcy = _bbox_center(frame_bb)

    anchor = _world_layer_centroid(res, _signal_feed_layer(res), layermap)
    if anchor is None:
        anchor = _bbox_center(resonator_world_bbox(res))
    acx, acy = anchor
    return fcx - acx, fcy - acy


def centering_shift(
    res: Resonator,
    frame_cell: gdstk.Cell,
    layermap: LayerMap | None = None,
) -> tuple[float, float]:
    """Alias for placement_shift (signal node → frame center)."""
    return placement_shift(res, frame_cell, layermap)


def rteg_cell_name(parent: str, inst_name: str) -> str:
    return f"{parent}_RTEG1_{inst_name}"


def resonator_world_bbox(
    res: Resonator,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Resonator bounding box in filter layout coordinates."""
    rb = res.reference.cell.bounding_box()
    if rb is None:
        raise ValueError(f"No bounding box for {res.master_name}")
    (rx0, ry0), (rx1, ry1) = rb
    ox, oy = res.origin
    return (rx0 + ox, ry0 + oy), (rx1 + ox, ry1 + oy)


def polygons_overlapping_bbox(
    cell: gdstk.Cell, bbox: tuple[tuple[float, float], tuple[float, float]]
) -> list[gdstk.Polygon]:
    """Polygons whose bbox overlaps `bbox` (SKILL dbGetTrueOverlaps on filter side)."""
    (bx0, by0), (bx1, by1) = bbox
    out: list[gdstk.Polygon] = []
    for poly in cell.polygons:
        pbb = poly.bounding_box()
        if pbb is None:
            continue
        (px0, py0), (px1, py1) = pbb
        if px0 <= bx1 and px1 >= bx0 and py0 <= by1 and py1 >= by0:
            out.append(poly)
    return out


def shift_polygon(poly: gdstk.Polygon, dx: float, dy: float) -> gdstk.Polygon:
    pts = [(x + dx, y + dy) for x, y in poly.points]
    return gdstk.Polygon(pts, layer=poly.layer, datatype=poly.datatype)


def _infer_base_names(resonators: list[Resonator]) -> dict[int, str]:
    """Best-effort Virtuoso-style names from sorted filter placement."""
    series_idx = [
        i for i, r in enumerate(resonators) if r.res_type == "series"
    ]
    shunt_idx = [i for i, r in enumerate(resonators) if r.res_type == "shunt"]
    rcap_idx = [
        i for i, r in enumerate(resonators) if r.res_type in ("rcap", "mimcap")
    ]

    names: dict[int, str] = {}

    series_sorted = sorted(
        series_idx, key=lambda i: (-resonators[i].origin[1], resonators[i].origin[0])
    )
    for rank, idx in enumerate(series_sorted, start=1):
        names[idx] = f"S{rank}"

    shunt_sorted = sorted(
        shunt_idx, key=lambda i: (-resonators[i].origin[1], resonators[i].origin[0])
    )
    for rank, idx in enumerate(shunt_sorted, start=1):
        names[idx] = f"P{rank}"

    other_sorted = sorted(
        rcap_idx, key=lambda i: (-resonators[i].origin[1], resonators[i].origin[0])
    )
    for rank, idx in enumerate(other_sorted, start=1):
        names[idx] = f"C{rank}"

    return names


def _load_inst_overrides(path: Path | None = None) -> dict[int, str]:
    path = path or INST_MAP_PATH
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("overrides_by_index", data)
    return {int(k): str(v) for k, v in raw.items()}


def infer_inst_names(
    resonators: list[Resonator],
    inst_map_path: Path | None = None,
) -> dict[int, str]:
    """
    Map resonator list index -> instName for {parent}_RTEG1_{instName}.

    Applies optional overrides from resonator_inst_map.json after inference.
    Warns when golden anchor index 6 would not be named S3 without override.
    """
    inferred = _infer_base_names(resonators)
    overrides = _load_inst_overrides(inst_map_path)

    if (
        GOLDEN_ANCHOR_INDEX in inferred
        and inferred[GOLDEN_ANCHOR_INDEX] != GOLDEN_ANCHOR_INST_NAME
        and GOLDEN_ANCHOR_INDEX not in overrides
    ):
        warnings.warn(
            f"Inferred inst name for index {GOLDEN_ANCHOR_INDEX} is "
            f"'{inferred[GOLDEN_ANCHOR_INDEX]}', not golden anchor "
            f"'{GOLDEN_ANCHOR_INST_NAME}' — override via {INST_MAP_PATH.name}",
            stacklevel=2,
        )

    result = dict(inferred)
    for idx, name in sorted(overrides.items()):
        if idx not in result:
            continue
        for other_idx, other_name in list(result.items()):
            if other_idx != idx and other_name == name:
                prefix = "S" if resonators[other_idx].res_type == "series" else "P"
                if resonators[other_idx].res_type in ("rcap", "mimcap"):
                    prefix = "C"
                used = set(result.values())
                n = 1
                while f"{prefix}{n}" in used:
                    n += 1
                result[other_idx] = f"{prefix}{n}"
        result[idx] = name
    return result


def load_connect_backup(
    parent: str,
    search_dir: Path,
    filter_lib: gdstk.Library | None = None,
    min_polys: int = CONNECT_BACKUP_MIN_POLYS,
) -> gdstk.Cell | None:
    """
    Load {parent}_connect_backup if present and has enough polygons.

    Checks standalone GDS in search_dir, then cells inside filter_lib.
    """
    cell_name = f"{parent}_connect_backup"
    candidates: list[gdstk.Cell] = []

    gds_path = search_dir / f"{cell_name}.gds"
    if gds_path.is_file():
        lib = gdstk.read_gds(gds_path)
        candidates.extend(lib.cells)

    if filter_lib is not None:
        match = next((c for c in filter_lib.cells if c.name == cell_name), None)
        if match is not None:
            candidates.append(match)

    for cell in candidates:
        if len(cell.polygons) >= min_polys:
            return cell
    return None


def frame_top_cell(frame_lib: gdstk.Library) -> gdstk.Cell:
    """Return the frame's top cell (e.g. KB331_N_Frame)."""
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
