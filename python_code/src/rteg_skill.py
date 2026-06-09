"""
RTEG preprocessing helpers.

Naming, preserved-metal loading, and frame placement for prepare_rteg.py and
build_rteg.py.

Foundation layout (built before each resonator is placed):
  1. Die frame (KB331_N_Frame) at the cell top-left
  2. ppd_1port centered inside the die frame
  3. Resonator bbox center aligned to the combined assembly center
"""
from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from pathlib import Path

import gdstk

from layermap import LayerMap
from separate import Resonator

DEFAULT_FRAME_W = 66.6  # legacy; not used for placement
CONNECT_BACKUP_MIN_POLYS = 10
GOLDEN_ANCHOR_INDEX = 6
GOLDEN_ANCHOR_INST_NAME = "S3"
INST_MAP_PATH = Path(__file__).parent / "resonator_inst_map.json"

# Die frame anchors at the top-left of the RTEG cell; ppd origin is computed.
FRAME_ORIGIN = (0.0, 0.0)


@dataclass(frozen=True)
class RtegFoundation:
    """Frame + ppd layout before the resonator is placed."""

    frame_origin: tuple[float, float]
    ppd_origin: tuple[float, float]
    assembly_bbox: tuple[tuple[float, float], tuple[float, float]]

    @property
    def assembly_center(self) -> tuple[float, float]:
        return bbox_center(self.assembly_bbox)


def bbox_center(
    bbox: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[float, float]:
    (x0, y0), (x1, y1) = bbox
    return (x0 + x1) / 2, (y0 + y1) / 2


def _translate_bbox(
    bbox: tuple[tuple[float, float], tuple[float, float]],
    origin: tuple[float, float],
) -> tuple[tuple[float, float], tuple[float, float]]:
    (x0, y0), (x1, y1) = bbox
    ox, oy = origin
    return (x0 + ox, y0 + oy), (x1 + ox, y1 + oy)


def _union_bbox(
    a: tuple[tuple[float, float], tuple[float, float]],
    b: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[tuple[float, float], tuple[float, float]]:
    return (
        (min(a[0][0], b[0][0]), min(a[0][1], b[0][1])),
        (max(a[1][0], b[1][0]), max(a[1][1], b[1][1])),
    )


def build_foundation(
    frame_cell: gdstk.Cell,
    ppd_cell: gdstk.Cell,
    frame_origin: tuple[float, float] = FRAME_ORIGIN,
) -> RtegFoundation:
    """
    Step 1: place die frame at ``frame_origin``.
    Step 2: center ppd_1port inside the frame bbox.
    Returns origins plus the combined assembly bbox (for resonator centering).
    """
    frame_bb = frame_cell.bounding_box()
    ppd_bb = ppd_cell.bounding_box()
    if frame_bb is None:
        raise ValueError("Frame cell has no bounding box")
    if ppd_bb is None:
        raise ValueError("ppd cell has no bounding box")

    frame_world_bb = _translate_bbox(frame_bb, frame_origin)
    fcx, fcy = bbox_center(frame_world_bb)
    pcx, pcy = bbox_center(ppd_bb)
    ppd_origin = (fcx - pcx, fcy - pcy)

    ppd_world_bb = _translate_bbox(ppd_bb, ppd_origin)
    assembly_bbox = _union_bbox(frame_world_bb, ppd_world_bb)

    return RtegFoundation(
        frame_origin=frame_origin,
        ppd_origin=ppd_origin,
        assembly_bbox=assembly_bbox,
    )


def add_foundation_refs(
    top: gdstk.Cell,
    frame_cell: gdstk.Cell,
    ppd_cell: gdstk.Cell,
    foundation: RtegFoundation,
) -> None:
    """Add frame and centered ppd references to a top cell."""
    top.add(gdstk.Reference(frame_cell, origin=foundation.frame_origin))
    top.add(gdstk.Reference(ppd_cell, origin=foundation.ppd_origin))


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
    ppd_cell: gdstk.Cell,
    *,
    foundation: RtegFoundation | None = None,
    layermap: LayerMap | None = None,
) -> tuple[float, float]:
    """
    (dx, dy) placing the resonator bbox center on the assembly center.

    Builds (or reuses) the frame + centered-ppd foundation, then shifts the
    resonator so its world bbox center matches ``foundation.assembly_center``.
    Preserved metal and vias receive the same shift.

    ``layermap`` is accepted for backward compatibility but not used here.
    """
    _ = layermap  # unused; resonator placement is bbox-centered on the foundation
    foundation = foundation or build_foundation(frame_cell, ppd_cell)
    acx, acy = foundation.assembly_center
    rcx, rcy = bbox_center(resonator_world_bbox(res))
    return acx - rcx, acy - rcy


def centering_shift(
    res: Resonator,
    frame_cell: gdstk.Cell,
    ppd_cell: gdstk.Cell,
    *,
    foundation: RtegFoundation | None = None,
    layermap: LayerMap | None = None,
) -> tuple[float, float]:
    """Alias for placement_shift (resonator bbox -> assembly center)."""
    return placement_shift(
        res, frame_cell, ppd_cell, foundation=foundation, layermap=layermap
    )


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
