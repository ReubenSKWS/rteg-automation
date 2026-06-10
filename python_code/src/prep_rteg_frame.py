"""
Step 4: place each PPD+resonator assembly inside the die frame.

Accepts in-memory ``ResonatorPpdAssembly`` objects from ``prep_resonator_ppd``.
Margins are measured from the inner die frame (MBE ring cavity), not the outer
460×580 bbox. An MBE filler rectangle on the right normalizes RTEG width.
"""
from __future__ import annotations

import tempfile
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import gdstk
import pandas as pd

from prep_resonator_ppd import ResonatorPpdAssembly
from rteg_utils import bbox_center, frame_top_cell

DEFAULT_X_MARGIN_PCT = 0.04
DEFAULT_Y_MARGIN_PCT = 0.07
MBE_LAYER = 2
MBE_DATATYPE = 0
INNER_FRAME_RING_MIN_AREA = 10_000.0


def _translate_bbox(
    bbox: tuple[tuple[float, float], tuple[float, float]],
    origin: tuple[float, float],
) -> tuple[tuple[float, float], tuple[float, float]]:
    (x0, y0), (x1, y1) = bbox
    ox, oy = origin
    return (x0 + ox, y0 + oy), (x1 + ox, y1 + oy)


def inner_die_frame_bbox(
    frame_cell: gdstk.Cell,
    frame_origin: tuple[float, float] = (0.0, 0.0),
) -> tuple[tuple[float, float], tuple[float, float]]:
    """
    Inner cavity of the die frame MBE ring (inside the inner blue border).

    Parsed from the largest MBE polygon in the frame cell — a rectangular ring
    with outer/inner x and y coordinates.
    """
    ring_candidates = [
        poly
        for poly in frame_cell.flatten().polygons
        if poly.layer == MBE_LAYER
        and poly.datatype == MBE_DATATYPE
        and abs(poly.area()) >= INNER_FRAME_RING_MIN_AREA
    ]
    if not ring_candidates:
        raise ValueError("Frame cell has no MBE ring polygon")

    ring = max(ring_candidates, key=lambda poly: abs(poly.area()))
    xs = sorted({x for x, _y in ring.points})
    ys = sorted({y for _x, y in ring.points})
    if len(xs) < 4 or len(ys) < 4:
        raise ValueError("Frame MBE ring is not a rectangular ring")

    local_bb = ((xs[1], ys[1]), (xs[2], ys[2]))
    return _translate_bbox(local_bb, frame_origin)


def _margined_content_bbox(
    inner_bb: tuple[tuple[float, float], tuple[float, float]],
    *,
    x_margin_pct: float,
    y_margin_pct: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    (ix0, iy0), (ix1, iy1) = inner_bb
    iw = ix1 - ix0
    ih = iy1 - iy0
    return (
        (ix0 + x_margin_pct * iw, iy0 + y_margin_pct * ih),
        (ix1 - x_margin_pct * iw, iy1 - y_margin_pct * ih),
    )


def frame_content_center(
    frame_cell: gdstk.Cell,
    frame_origin: tuple[float, float] = (0.0, 0.0),
    *,
    x_margin_pct: float = DEFAULT_X_MARGIN_PCT,
    y_margin_pct: float = DEFAULT_Y_MARGIN_PCT,
) -> tuple[float, float]:
    """Center of the content box after percentage margins inside the inner die frame."""
    inner_bb = inner_die_frame_bbox(frame_cell, frame_origin)
    content_bb = _margined_content_bbox(
        inner_bb,
        x_margin_pct=x_margin_pct,
        y_margin_pct=y_margin_pct,
    )
    return bbox_center(content_bb)


def assembly_placement_origin(
    assembly: ResonatorPpdAssembly,
    content_bb: tuple[tuple[float, float], tuple[float, float]],
    content_center: tuple[float, float],
) -> tuple[float, float]:
    """
    Place assembly with fixed left X margin and centered Y.

    X: left edge on the margined content left (4% inside inner die frame).
    Y: bbox center on the margined content center (7% inside inner die frame).
    """
    asm_bb = assembly.top_cell.bounding_box()
    if asm_bb is None:
        raise ValueError(f"Assembly {assembly.top_cell.name} has no bounding box")
    (ax0, _ay0), (_ax1, _ay1) = asm_bb
    _acx, acy = bbox_center(asm_bb)
    (cx0, _cy0), (_cx1, _cy1) = content_bb
    return cx0 - ax0, content_center[1] - acy


def mbe_width_filler_polygon(
    assembly: ResonatorPpdAssembly,
    assembly_origin: tuple[float, float],
    inner_bb: tuple[tuple[float, float], tuple[float, float]],
    content_bb: tuple[tuple[float, float], tuple[float, float]],
    *,
    layer: int = MBE_LAYER,
    datatype: int = MBE_DATATYPE,
) -> gdstk.Polygon:
    """
    MBE plate on the right half of the inner die frame.

    Height matches the placed GSG/resonator assembly bbox. Its right edge sits
    at the 4% X margin inside the inner die frame; its left edge is the
    inner-frame center line.
    """
    asm_bb = assembly.top_cell.bounding_box()
    if asm_bb is None:
        raise ValueError(f"Assembly {assembly.top_cell.name} has no bounding box")

    (_ax0, ay0), (_ax1, ay1) = asm_bb
    ox, oy = assembly_origin
    asm_y0, asm_y1 = ay0 + oy, ay1 + oy

    (ix0, _iy0), (ix1, _iy1) = inner_bb
    (_cx0, _cy0), (cx1, _cy1) = content_bb
    filler_x0 = (ix0 + ix1) / 2.0
    if filler_x0 >= cx1 - 1e-6:
        raise ValueError("Inner frame is too narrow for the MBE width filler")

    return gdstk.rectangle(
        (filler_x0, asm_y0),
        (cx1, asm_y1),
        layer=layer,
        datatype=datatype,
    )


def _load_frame_cell(
    frame_gds: str | Path,
    frame_cell: gdstk.Cell | None,
) -> tuple[gdstk.Library, gdstk.Cell]:
    if frame_cell is not None:
        lib = gdstk.Library()
        lib.add(frame_cell)
        return lib, frame_cell
    frame_gds = Path(frame_gds)
    if not frame_gds.is_file():
        raise FileNotFoundError(frame_gds)
    lib = gdstk.read_gds(frame_gds)
    cell = frame_top_cell(lib)
    return lib, cell


def _assembly_exceeds_content_x(
    assembly: ResonatorPpdAssembly,
    assembly_origin: tuple[float, float],
    content_bb: tuple[tuple[float, float], tuple[float, float]],
) -> bool:
    """True when the functional assembly sticks out past the margined content box in X."""
    asm_bb = assembly.top_cell.bounding_box()
    if asm_bb is None:
        return False
    (ax0, _ay0), (ax1, _ay1) = asm_bb
    ox, _oy = assembly_origin
    wx0, wx1 = ax0 + ox, ax1 + ox
    (cx0, _cy0), (cx1, _cy1) = content_bb
    return wx0 < cx0 - 1e-6 or wx1 > cx1 + 1e-6


@dataclass
class RtegFrameAssembly:
    """In-memory die frame + PPD/resonator assembly (step 4 of the modular pipeline)."""

    index: int
    inst_name: str
    frame_origin: tuple[float, float]
    assembly_origin: tuple[float, float]
    content_center: tuple[float, float]
    inner_die_frame_bbox: tuple[tuple[float, float], tuple[float, float]]
    content_bbox: tuple[tuple[float, float], tuple[float, float]]
    mbe_filler_bbox: tuple[tuple[float, float], tuple[float, float]]
    inner_content_width: float
    mbe_filler_width: float
    x_margin_pct: float
    y_margin_pct: float
    ppd_assembly: ResonatorPpdAssembly
    top_cell: gdstk.Cell
    library: gdstk.Library

    def flatten(self) -> gdstk.Cell:
        return self.top_cell.flatten()

    def summary_row(self) -> dict[str, object]:
        (fx0, fy0), (fx1, fy1) = self.inner_die_frame_bbox
        (filler_x0, filler_y0), (filler_x1, filler_y1) = self.mbe_filler_bbox
        return {
            "index": self.index,
            "inst_name": self.inst_name,
            "type": self.ppd_assembly.res_type,
            "frame_origin_x": round(self.frame_origin[0], 1),
            "frame_origin_y": round(self.frame_origin[1], 1),
            "assembly_origin_x": round(self.assembly_origin[0], 1),
            "assembly_origin_y": round(self.assembly_origin[1], 1),
            "content_center_x": round(self.content_center[0], 1),
            "content_center_y": round(self.content_center[1], 1),
            "inner_frame_x0": round(fx0, 1),
            "inner_frame_y0": round(fy0, 1),
            "inner_frame_x1": round(fx1, 1),
            "inner_frame_y1": round(fy1, 1),
            "mbe_filler_x0": round(filler_x0, 1),
            "mbe_filler_y0": round(filler_y0, 1),
            "mbe_filler_x1": round(filler_x1, 1),
            "mbe_filler_y1": round(filler_y1, 1),
            "inner_content_width": round(self.inner_content_width, 1),
            "mbe_filler_width": round(self.mbe_filler_width, 1),
            "x_margin_pct": self.x_margin_pct,
            "y_margin_pct": self.y_margin_pct,
        }


# Backward-compatible alias
FrameAssembly = RtegFrameAssembly


def prep_rteg_in_frame(
    assemblies: Sequence[ResonatorPpdAssembly],
    frame_gds: str | Path,
    *,
    frame_origin: tuple[float, float] = (0.0, 0.0),
    frame_cell: gdstk.Cell | None = None,
    x_margin_pct: float = DEFAULT_X_MARGIN_PCT,
    y_margin_pct: float = DEFAULT_Y_MARGIN_PCT,
) -> list[RtegFrameAssembly]:
    """
    Build one die-frame + PPD assembly per step-2 object.

    Margins are measured from the inner die frame cavity. Each assembly is
    left-aligned in X (4%) and centered in Y (7%), then an MBE rectangle fills
    the right side from the inner-frame center to the margined right edge at the
    same height as the placed assembly.
    """
    if not assemblies:
        return []

    frame_lib, frame_master = _load_frame_cell(frame_gds, frame_cell)
    inner_bb = inner_die_frame_bbox(frame_master, frame_origin)
    content_bb = _margined_content_bbox(
        inner_bb,
        x_margin_pct=x_margin_pct,
        y_margin_pct=y_margin_pct,
    )
    content_center = bbox_center(content_bb)
    (_cx0, _cy0), (cx1, _cy1) = content_bb
    inner_content_width = cx1 - _cx0

    results: list[RtegFrameAssembly] = []
    for ppd_asm in assemblies:
        asm_origin = assembly_placement_origin(ppd_asm, content_bb, content_center)
        filler = mbe_width_filler_polygon(
            ppd_asm, asm_origin, inner_bb, content_bb
        )
        filler_bb = filler.bounding_box()
        if filler_bb is None:
            raise ValueError("MBE filler polygon has no bounding box")
        filler_width = filler_bb[1][0] - filler_bb[0][0]

        if _assembly_exceeds_content_x(ppd_asm, asm_origin, content_bb):
            warnings.warn(
                f"Assembly [{ppd_asm.index}] {ppd_asm.inst_name} extends past "
                f"the {x_margin_pct:.1%}/{y_margin_pct:.1%} content box inside "
                "the inner die frame",
                stacklevel=2,
            )

        cell_name = f"rteg_{ppd_asm.index}_{ppd_asm.inst_name}"
        top = gdstk.Cell(cell_name)
        top.add(gdstk.Reference(frame_master, origin=frame_origin))
        top.add(gdstk.Reference(ppd_asm.top_cell, origin=asm_origin))
        top.add(filler)

        out_lib = gdstk.Library()
        for c in frame_lib.cells:
            out_lib.add(c)
        for c in ppd_asm.library.cells:
            out_lib.add(c)
        out_lib.add(top)

        results.append(
            RtegFrameAssembly(
                index=ppd_asm.index,
                inst_name=ppd_asm.inst_name,
                frame_origin=frame_origin,
                assembly_origin=asm_origin,
                content_center=content_center,
                inner_die_frame_bbox=inner_bb,
                content_bbox=content_bb,
                mbe_filler_bbox=filler_bb,
                inner_content_width=inner_content_width,
                mbe_filler_width=filler_width,
                x_margin_pct=x_margin_pct,
                y_margin_pct=y_margin_pct,
                ppd_assembly=ppd_asm,
                top_cell=top,
                library=out_lib,
            )
        )
    return results


def assemblies_summary_df(
    assemblies: Sequence[RtegFrameAssembly],
) -> pd.DataFrame:
    return pd.DataFrame([a.summary_row() for a in assemblies])


def preview_assembly_svg(assembly: RtegFrameAssembly) -> str:
    """Render one frame assembly to SVG text for notebook display."""
    flat = assembly.flatten()
    with tempfile.TemporaryDirectory() as tmp:
        svg_path = Path(tmp) / f"{assembly.top_cell.name}.svg"
        flat.write_svg(str(svg_path))
        return svg_path.read_text(encoding="utf-8")
