"""
Step 3 — Separation: center each resonator in the GSG PPD frame.

Accepts ``res_df`` + ``Resonator`` objects from ``separate.identify()`` (step 2).
Returns in-memory ``ResonatorPpdAssembly`` objects for step 4 and export.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import gdstk
import pandas as pd

from layermap import LayerMap
from rteg_utils import bbox_center, frame_top_cell, resonator_world_bbox, translate_bbox
from separate import IdentificationResult, Resonator

# GSG PPD pad / frame metal vs resonator MBE+MTE (same layers, different cells).
PPD_PAD_LAYERS = frozenset({(33, 0), (81, 0), (202, 0), (2, 0)})
RESONATOR_METAL_LAYERS = frozenset({(2, 0), (5, 0)})
# BAW_ReF + BAW_CAV on the resonator (layermap layer/datatype pairs).
RELEASE_HOLE_LAYERS = frozenset({(33, 0), (36, 0)})
MIN_KEEPOUT_POLY_AREA = 10.0
MIN_FRAME_CLEARANCE_UM = 10.0
MIN_RELEASE_HOLE_CLEARANCE_UM = 6.0
# Orientation placement must keep at least this gap to GSG pads (PDK6 MBE/MTE min).
ORIENTATION_MIN_CLEARANCE_UM = 14.0
ORIENTATION_SEARCH_STEP_UM = 10.0
ORIENTATION_SEARCH_RADIUS_UM = 60.0


@dataclass(frozen=True)
class PpdSlotBounds:
    """Axis-aligned probe-pad keepout edges derived from the PPD cell."""

    left_x1: float
    top_y1: float
    bottom_y0: float


def ppd_assembly_center(
    ppd_cell: gdstk.Cell,
    ppd_origin: tuple[float, float] = (0.0, 0.0),
) -> tuple[float, float]:
    """Center of the PPD cell bbox when placed at ``ppd_origin``."""
    ppd_bb = ppd_cell.bounding_box()
    if ppd_bb is None:
        raise ValueError("PPD cell has no bounding box")
    return bbox_center(translate_bbox(ppd_bb, ppd_origin))


def resonator_ppd_shift(
    res: Resonator,
    ppd_cell: gdstk.Cell,
    *,
    ppd_origin: tuple[float, float] = (0.0, 0.0),
) -> tuple[float, float]:
    """(dx, dy) placing resonator bbox center on the PPD assembly center."""
    acx, acy = ppd_assembly_center(ppd_cell, ppd_origin)
    rcx, rcy = bbox_center(resonator_world_bbox(res))
    return acx - rcx, acy - rcy


def ppd_pad_keepout_polys(
    ppd_cell: gdstk.Cell,
    ppd_origin: tuple[float, float] = (0.0, 0.0),
) -> list[gdstk.Polygon]:
    """Pad / frame metal from the flattened PPD, translated to ``ppd_origin``."""
    ox, oy = ppd_origin
    # Flatten on a throwaway wrapper so the source cell keeps its references
    # (``Cell.flatten()`` mutates in place; step 5.2b re-prep needs them intact).
    probe = gdstk.Cell("_ppd_pad_keepout_probe")
    probe.add(gdstk.Reference(ppd_cell))
    keepouts: list[gdstk.Polygon] = []
    for poly in probe.flatten().polygons:
        if (poly.layer, poly.datatype) not in PPD_PAD_LAYERS:
            continue
        if abs(poly.area()) < MIN_KEEPOUT_POLY_AREA:
            continue
        keepouts.append(
            gdstk.Polygon(
                [(x + ox, y + oy) for x, y in poly.points],
                layer=poly.layer,
                datatype=poly.datatype,
            )
        )
    return keepouts


def ppd_slot_bounds(keepout_polys: Sequence[gdstk.Polygon]) -> PpdSlotBounds:
    """Infer left / top / bottom pad edges from the PPD keepout polygons."""
    left_x1 = max(
        bb[1][0]
        for poly in keepout_polys
        if (bb := poly.bounding_box()) is not None and bb[1][0] < 360.0
    )
    top_y1 = max(
        bb[1][1]
        for poly in keepout_polys
        if (bb := poly.bounding_box()) is not None
        and bb[0][0] >= 330.0
        and bb[1][1] < 150.0
    )
    bottom_y0 = min(
        bb[0][1]
        for poly in keepout_polys
        if (bb := poly.bounding_box()) is not None
        and bb[0][0] >= 330.0
        and bb[0][1] > 350.0
    )
    return PpdSlotBounds(left_x1=left_x1, top_y1=top_y1, bottom_y0=bottom_y0)


def _shifted_resonator_polys(
    res: Resonator,
    dx: float,
    dy: float,
    *,
    layers: frozenset[tuple[int, int]],
) -> list[gdstk.Polygon]:
    """Flattened resonator polygons on ``layers`` after ``(dx, dy)`` placement."""
    origin = (res.origin[0] + dx, res.origin[1] + dy)
    ref = gdstk.Reference(
        res.reference.cell,
        origin=origin,
        rotation=res.rotation,
        magnification=res.magnification,
        x_reflection=res.x_reflection,
    )
    tmp = gdstk.Cell("_res_polys")
    tmp.add(ref)
    return [
        poly
        for poly in tmp.flatten().polygons
        if (poly.layer, poly.datatype) in layers
    ]


def resonator_metal_polys(
    res: Resonator,
    dx: float,
    dy: float,
) -> list[gdstk.Polygon]:
    """Resonator MBE/MTE polygons after applying ``(dx, dy)`` to the filter placement."""
    return _shifted_resonator_polys(res, dx, dy, layers=RESONATOR_METAL_LAYERS)


def resonator_release_hole_polys(
    res: Resonator,
    dx: float,
    dy: float,
) -> list[gdstk.Polygon]:
    """Resonator BAW_ReF / BAW_CAV polygons after ``(dx, dy)`` placement."""
    return _shifted_resonator_polys(res, dx, dy, layers=RELEASE_HOLE_LAYERS)


def resonator_layer_polys(
    res: Resonator,
    dx: float,
    dy: float,
    layer_pair: tuple[int, int],
) -> list[gdstk.Polygon]:
    """Flattened resonator polygons on one GDS layer pair after ``(dx, dy)`` placement."""
    return _shifted_resonator_polys(res, dx, dy, layers=frozenset({layer_pair}))


def _metal_bbox(
    metal_polys: Sequence[gdstk.Polygon],
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    bboxes = [poly.bounding_box() for poly in metal_polys if poly.bounding_box()]
    if not bboxes:
        return None
    return (
        (min(bb[0][0] for bb in bboxes), min(bb[0][1] for bb in bboxes)),
        (max(bb[1][0] for bb in bboxes), max(bb[1][1] for bb in bboxes)),
    )


def metal_overlaps_keepout(
    metal_polys: Sequence[gdstk.Polygon],
    keepout_polys: Sequence[gdstk.Polygon],
) -> bool:
    for metal in metal_polys:
        for keepout in keepout_polys:
            if gdstk.boolean(metal, keepout, "and"):
                return True
    return False


def _grown_keepout_polys(
    keepout_polys: Sequence[gdstk.Polygon],
    min_gap: float,
) -> list[gdstk.Polygon]:
    """Pad keepouts expanded outward by ``min_gap`` (closest-point clearance zone)."""
    grown: list[gdstk.Polygon] = []
    for keepout in keepout_polys:
        offset_polys = gdstk.offset(keepout, min_gap)
        if offset_polys:
            grown.extend(offset_polys)
        else:
            grown.append(keepout)
    return grown


def polys_satisfy_clearance(
    polys: Sequence[gdstk.Polygon],
    keepout_polys: Sequence[gdstk.Polygon],
    *,
    min_gap: float,
) -> bool:
    """True when every polygon is at least ``min_gap`` from every keepout polygon."""
    if min_gap <= 0:
        return not metal_overlaps_keepout(polys, keepout_polys)

    clearance_zone = _grown_keepout_polys(keepout_polys, min_gap)
    for poly in polys:
        for zone in clearance_zone:
            if gdstk.boolean(poly, zone, "and"):
                return False
    return True


def ppd_clearance_satisfied(
    metal_polys: Sequence[gdstk.Polygon],
    release_polys: Sequence[gdstk.Polygon],
    keepout_polys: Sequence[gdstk.Polygon],
    *,
    min_metal_gap: float = MIN_FRAME_CLEARANCE_UM,
    min_release_gap: float = MIN_RELEASE_HOLE_CLEARANCE_UM,
) -> bool:
    """Metal and release-hole clearance vs the GSG PPD frame."""
    if not polys_satisfy_clearance(metal_polys, keepout_polys, min_gap=min_metal_gap):
        return False
    if release_polys and not polys_satisfy_clearance(
        release_polys, keepout_polys, min_gap=min_release_gap
    ):
        return False
    return True


def min_clearance_um(
    polys: Sequence[gdstk.Polygon],
    keepout_polys: Sequence[gdstk.Polygon],
) -> float:
    """Minimum vertex-sample spacing from ``polys`` to ``keepout_polys`` (0 = overlap)."""
    best = float("inf")
    for poly in polys:
        for keepout in keepout_polys:
            if gdstk.boolean(poly, keepout, "and"):
                return 0.0
            for pa in poly.points:
                for pb in keepout.points:
                    d = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
                    if d < best:
                        best = d
    return 0.0 if best == float("inf") else best


def avoid_ppd_frame_overlap(
    res: Resonator,
    ppd_cell: gdstk.Cell,
    dx: float,
    dy: float,
    *,
    ppd_origin: tuple[float, float] = (0.0, 0.0),
    min_gap: float = MIN_FRAME_CLEARANCE_UM,
    min_release_gap: float = MIN_RELEASE_HOLE_CLEARANCE_UM,
    max_iterations: int = 24,
) -> tuple[float, float]:
    """
    Extra ``(dx, dy)`` nudging the resonator on one axis at a time to clear PPD pads.

    Starts from the centered shift ``(dx, dy)``. Only x/y translation is applied;
    resonator rotation and magnification are unchanged. Keeps at least ``min_gap``
    between resonator MBE/MTE and GSG pad metal, and ``min_release_gap`` between
    resonator BAW_ReF / BAW_CAV release holes and the GSG frame.
    """
    keepouts = ppd_pad_keepout_polys(ppd_cell, ppd_origin)
    if not keepouts:
        return 0.0, 0.0

    slot = ppd_slot_bounds(keepouts)
    extra_dx = 0.0
    extra_dy = 0.0
    drive_gap = max(min_gap, min_release_gap)

    def _placed_polys(shift_x: float, shift_y: float) -> tuple[list[gdstk.Polygon], list[gdstk.Polygon]]:
        tx, ty = dx + shift_x, dy + shift_y
        return (
            resonator_metal_polys(res, tx, ty),
            resonator_release_hole_polys(res, tx, ty),
        )

    def _satisfied(shift_x: float, shift_y: float) -> bool:
        metal, release = _placed_polys(shift_x, shift_y)
        return ppd_clearance_satisfied(
            metal,
            release,
            keepouts,
            min_metal_gap=min_gap,
            min_release_gap=min_release_gap,
        )

    for _ in range(max_iterations):
        if _satisfied(extra_dx, extra_dy):
            return extra_dx, extra_dy

        metal, release = _placed_polys(extra_dx, extra_dy)
        bbox = _metal_bbox([*metal, *release])
        if bbox is None:
            return extra_dx, extra_dy

        (x0, y0), (x1, y1) = bbox
        moved = False

        if x0 < slot.left_x1 + drive_gap:
            extra_dx += slot.left_x1 + drive_gap - x0
            moved = True
        elif y1 > slot.bottom_y0 - drive_gap:
            extra_dy += slot.bottom_y0 - drive_gap - y1
            moved = True
        elif y0 < slot.top_y1 + drive_gap:
            extra_dy += slot.top_y1 + drive_gap - y0
            moved = True

        if moved:
            continue

        # Fallback: smallest single-axis nudge that restores clearance.
        best: tuple[float, float] | None = None
        for keepout in keepouts:
            kbb = keepout.bounding_box()
            if kbb is None:
                continue
            (kx0, ky0), (kx1, ky1) = kbb
            if (
                x1 <= kx0 - drive_gap
                or x0 >= kx1 + drive_gap
                or y1 <= ky0 - drive_gap
                or y0 >= ky1 + drive_gap
            ):
                continue
            candidates = (
                (kx1 - x0 + drive_gap, 0.0),
                (kx0 - x1 - drive_gap, 0.0),
                (0.0, ky1 - y0 + drive_gap),
                (0.0, ky0 - y1 - drive_gap),
            )
            for cand_dx, cand_dy in candidates:
                if cand_dx == 0.0 and cand_dy == 0.0:
                    continue
                if _satisfied(extra_dx + cand_dx, extra_dy + cand_dy):
                    best = (extra_dx + cand_dx, extra_dy + cand_dy)
                    break
            if best is not None:
                break

        if best is None:
            break
        extra_dx, extra_dy = best

    return extra_dx, extra_dy


@dataclass
class ResonatorPpdAssembly:
    """In-memory PPD + centered resonator (step 3)."""

    index: int
    inst_name: str
    res_type: str
    master_name: str
    ppd_origin: tuple[float, float]
    resonator_origin: tuple[float, float]
    centering_shift: tuple[float, float]
    clearance_shift: tuple[float, float]
    orientation_shift: tuple[float, float]
    min_release_clearance_um: float
    shift: tuple[float, float]
    assembly_center: tuple[float, float]
    top_cell: gdstk.Cell
    library: gdstk.Library

    def flatten(self) -> gdstk.Cell:
        return self.top_cell.flatten()

    def summary_row(self) -> dict[str, object]:
        return {
            "index": self.index,
            "inst_name": self.inst_name,
            "master_name": self.master_name,
            "type": self.res_type,
            "ppd_origin_x": round(self.ppd_origin[0], 1),
            "ppd_origin_y": round(self.ppd_origin[1], 1),
            "resonator_origin_x": round(self.resonator_origin[0], 1),
            "resonator_origin_y": round(self.resonator_origin[1], 1),
            "centering_shift_x": round(self.centering_shift[0], 1),
            "centering_shift_y": round(self.centering_shift[1], 1),
            "clearance_shift_x": round(self.clearance_shift[0], 1),
            "clearance_shift_y": round(self.clearance_shift[1], 1),
            "orientation_shift_x": round(self.orientation_shift[0], 1),
            "orientation_shift_y": round(self.orientation_shift[1], 1),
            "min_release_clearance_um": round(self.min_release_clearance_um, 1),
            "shift_x": round(self.shift[0], 1),
            "shift_y": round(self.shift[1], 1),
            "assembly_center_x": round(self.assembly_center[0], 1),
            "assembly_center_y": round(self.assembly_center[1], 1),
        }


def _validate_res_df(res_df: pd.DataFrame, resonators: Sequence[Resonator]) -> list[int]:
    if "index" not in res_df.columns:
        raise ValueError("res_df must contain an 'index' column")
    indices = [int(i) for i in res_df["index"].tolist()]
    if len(indices) != len(resonators):
        raise ValueError(
            f"res_df has {len(indices)} rows but {len(resonators)} resonators were provided"
        )
    if sorted(indices) != list(range(len(resonators))):
        raise ValueError(
            "res_df 'index' values must be 0..n-1 matching enumerate(resonators)"
        )
    return indices


def _load_ppd_cell(
    ppd_gds: str | Path,
    ppd_cell: gdstk.Cell | None,
) -> tuple[gdstk.Library, gdstk.Cell]:
    if ppd_cell is not None:
        lib = gdstk.Library()
        lib.add(ppd_cell)
        return lib, ppd_cell
    ppd_gds = Path(ppd_gds)
    if not ppd_gds.is_file():
        raise FileNotFoundError(ppd_gds)
    lib = gdstk.read_gds(ppd_gds)
    cell = frame_top_cell(lib)
    return lib, cell


def find_orientation_placement_shift(
    res: Resonator,
    base_dx: float,
    base_dy: float,
    ppd_cell: gdstk.Cell,
    *,
    ppd_origin: tuple[float, float] = (0.0, 0.0),
    min_metal_gap: float = ORIENTATION_MIN_CLEARANCE_UM,
    min_release_gap: float = MIN_RELEASE_HOLE_CLEARANCE_UM,
    search_step_um: float = ORIENTATION_SEARCH_STEP_UM,
    search_radius_um: float = ORIENTATION_SEARCH_RADIUS_UM,
) -> tuple[float, float]:
    """
    Extra ``(dx, dy)`` moving the resonator in any direction while keeping a
    significant clearance gap to GSG pad metal.

    Scans a square window around the base placement and picks the offset that
    maximizes minimum metal/release clearance to pads without overlap.
    """
    keepouts = ppd_pad_keepout_polys(ppd_cell, ppd_origin)
    if not keepouts:
        return 0.0, 0.0

    def _evaluate(extra_dx: float, extra_dy: float) -> float | None:
        tx, ty = base_dx + extra_dx, base_dy + extra_dy
        metal = resonator_metal_polys(res, tx, ty)
        release = resonator_release_hole_polys(res, tx, ty)
        if not ppd_clearance_satisfied(
            metal,
            release,
            keepouts,
            min_metal_gap=min_metal_gap,
            min_release_gap=min_release_gap,
        ):
            return None
        metal_clear = min_clearance_um(metal, keepouts)
        release_clear = (
            min_clearance_um(release, keepouts) if release else float("inf")
        )
        return min(metal_clear, release_clear)

    best_shift = (0.0, 0.0)
    best_clear = _evaluate(0.0, 0.0)
    if best_clear is None:
        best_clear = -1.0

    steps = max(1, int(search_radius_um / search_step_um))
    # Center-first spiral-ish order: try (0,0) then expanding rings
    candidates: list[tuple[float, float]] = [(0.0, 0.0)]
    for ring in range(1, steps + 1):
        d = ring * search_step_um
        for extra_dx in (-d, 0.0, d):
            for extra_dy in (-d, 0.0, d):
                if extra_dx == 0.0 and extra_dy == 0.0:
                    continue
                candidates.append((extra_dx, extra_dy))

    for extra_dx, extra_dy in candidates:
        score = _evaluate(extra_dx, extra_dy)
        if score is not None and score > best_clear:
            best_clear = score
            best_shift = (extra_dx, extra_dy)
            if score >= min_metal_gap * 2.0:
                break

    return best_shift


def _orientation_placement_shift(
    res: Resonator,
    ppd_master: gdstk.Cell,
    ppd_origin: tuple[float, float],
    dx: float,
    dy: float,
) -> tuple[float, float]:
    """Extra placement shift maximizing pad clearance (any axis)."""
    return find_orientation_placement_shift(
        res, dx, dy, ppd_master, ppd_origin=ppd_origin
    )


def prep_resonator_ppd(
    res_df: pd.DataFrame,
    resonators: Sequence[Resonator],
    ppd_gds: str | Path,
    *,
    ppd_origin: tuple[float, float] = (0.0, 0.0),
    ppd_cell: gdstk.Cell | None = None,
    identification: IdentificationResult | None = None,
    layermap: LayerMap | None = None,
    min_frame_clearance: float = MIN_FRAME_CLEARANCE_UM,
    min_release_hole_clearance: float = MIN_RELEASE_HOLE_CLEARANCE_UM,
) -> list[ResonatorPpdAssembly]:
    """
    Build one PPD + centered-resonator assembly per ``res_df`` row.

    PPD is placed at ``ppd_origin`` (default top-left). Each resonator is shifted
    so its bbox center lands on the PPD bbox center, then nudged axis-aligned to
    keep at least ``min_frame_clearance`` between resonator metal and GSG pads,
    and ``min_release_hole_clearance`` between BAW_ReF / BAW_CAV and the frame.
    Only x/y placement changes; scale and orientation are preserved.
    """
    indices = _validate_res_df(res_df, resonators)
    ppd_lib, ppd_master = _load_ppd_cell(ppd_gds, ppd_cell)
    center = ppd_assembly_center(ppd_master, ppd_origin)
    keepouts = ppd_pad_keepout_polys(ppd_master, ppd_origin)

    assemblies: list[ResonatorPpdAssembly] = []
    for idx in indices:
        res = resonators[idx]
        row = res_df.loc[res_df["index"] == idx].iloc[0]
        inst_name = str(row.get("inst_name", res.inst_name))
        center_dx, center_dy = resonator_ppd_shift(
            res, ppd_master, ppd_origin=ppd_origin
        )
        clear_dx, clear_dy = avoid_ppd_frame_overlap(
            res,
            ppd_master,
            center_dx,
            center_dy,
            ppd_origin=ppd_origin,
            min_gap=min_frame_clearance,
            min_release_gap=min_release_hole_clearance,
        )
        dx = center_dx + clear_dx
        dy = center_dy + clear_dy
        orient_dx, orient_dy = _orientation_placement_shift(
            res,
            ppd_master,
            ppd_origin,
            dx,
            dy,
        )
        dx += orient_dx
        dy += orient_dy
        release_polys = resonator_release_hole_polys(res, dx, dy)
        min_release_clear = (
            min_clearance_um(release_polys, keepouts) if release_polys else float("inf")
        )
        rteg_origin = (res.origin[0] + dx, res.origin[1] + dy)
        cell_name = f"ppd_{idx}_{inst_name}"

        top = gdstk.Cell(cell_name)
        top.add(gdstk.Reference(ppd_master, origin=ppd_origin))
        top.add(
            gdstk.Reference(
                res.reference.cell,
                origin=rteg_origin,
                rotation=res.rotation,
                magnification=res.magnification,
                x_reflection=res.x_reflection,
            )
        )

        out_lib = gdstk.Library()
        for c in ppd_lib.cells:
            out_lib.add(c)
        out_lib.add(res.reference.cell)
        out_lib.add(top)

        assemblies.append(
            ResonatorPpdAssembly(
                index=idx,
                inst_name=inst_name,
                res_type=res.res_type,
                master_name=res.master_name,
                ppd_origin=ppd_origin,
                resonator_origin=rteg_origin,
                centering_shift=(center_dx, center_dy),
                clearance_shift=(clear_dx, clear_dy),
                orientation_shift=(orient_dx, orient_dy),
                min_release_clearance_um=min_release_clear,
                shift=(dx, dy),
                assembly_center=center,
                top_cell=top,
                library=out_lib,
            )
        )
    return assemblies


def assemblies_summary_df(
    assemblies: Sequence[ResonatorPpdAssembly],
) -> pd.DataFrame:
    return pd.DataFrame([a.summary_row() for a in assemblies])
