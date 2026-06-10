"""
Step 5 — MBE ground interconnect as a boolean plate merge on step-4 assemblies.

Consumes ``RtegFrameAssembly`` (step 4), ``IdentificationResult`` (step 2), and
``LayerMap`` (step 1). Extracts preserved filter metal from ``connectMBE``,
classifies GSG pad roles, and fuses the GSG ground arms + MBE filler plate +
preserved connector into one carved ground body via :mod:`ground_merge`. Emits
``RtegRoutedAssembly`` objects plus a summary report DataFrame.

The ground side is **not** a thin wire. The outer GSG ground pads sit on wide
MBE arms, the right half of the cavity is an MBE filler plate, and the preserved
filter connector is another MBE body — all one ground net. Earlier wire-search
versions could not connect a 14 µm stroke across these plates; the plate merge
unions them, (auto-)bridges any gap, carves the DRC keepouts, and verifies a
single connected, clean ground plane. ``route_search.py`` is retained for the
future signal/MTE pass.

## Assumption register
| ID | Assumption |
|----|------------|
| A1 | GSG frame has 3 vertical pads: outer top/bottom = ground (MBE), center = signal (MTE). |
| A2 | Ground v1 merges plates only; center signal pad is a carve obstacle, never fused. |
| A3 | Preserved metal from ``{parent}_connect_backup`` then ``{parent}_connectMBE``. |
| A4 | Overlap window = resonator filter bbox + ``preserved_overlap_margin_um``. |
| A5 | Placement shifts translate resonator + preserved metal only (no rotation). |
| A6 | PPD and die frame stay fixed. |
| A7 | Carve keepouts = signal/MTE (+14 µm) + resonator MBE (+14 µm) + release holes (+6 µm). |
| A10 | Ground collar not inferred; preserved MBE fused directly into the body. |
| A11 | Via at center pad (MBE→MTE) re-checked: carved ground must not overlap center signal. |
| A14 | Layer numbers resolved via layermap names only. |

## Skip behavior
Resonators are skipped (logged in summary ``skip_reason``) when pad classification
fails, the connect cell is missing, no preserved metal overlaps the resonator
window, or :func:`ground_merge.feasibility_precheck` rejects the geometry.
"""
from __future__ import annotations

import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import gdstk
import pandas as pd

from ground_merge import GroundMergeConfig, GroundMergeResult, run_ground_merge
from layermap import LayerMap
from prep_resonator_ppd import (
    ResonatorPpdAssembly,
    ppd_pad_keepout_polys,
    resonator_metal_polys,
)
from prep_rteg_frame import RtegFrameAssembly
from rteg_utils import frame_top_cell
from route_primitives import (
    grow_polygon,
    polygons_union,
    translate_polygon,
    translate_polygons,
)
from route_search import RouteSearchConfig
from rteg_utils import resonator_world_bbox
from separate import IdentificationResult, Resonator

MIN_PAD_POLY_AREA = 10.0


@dataclass(frozen=True)
class GsgPadRoles:
    top_ground: list[gdstk.Polygon]
    center_signal: list[gdstk.Polygon]
    bottom_ground: list[gdstk.Polygon]

    @property
    def ground_pads(self) -> list[tuple[str, gdstk.Polygon]]:
        pads: list[tuple[str, gdstk.Polygon]] = []
        for poly in self.top_ground:
            pads.append(("top_ground", poly))
        for poly in self.bottom_ground:
            pads.append(("bottom_ground", poly))
        return pads


def _ppd_world_origin(assembly: RtegFrameAssembly) -> tuple[float, float]:
    ppd = assembly.ppd_assembly
    return (
        assembly.assembly_origin[0] + ppd.ppd_origin[0],
        assembly.assembly_origin[1] + ppd.ppd_origin[1],
    )


def _resonator_rteg_origin(assembly: RtegFrameAssembly) -> tuple[float, float]:
    ppd = assembly.ppd_assembly
    return (
        assembly.assembly_origin[0] + ppd.resonator_origin[0],
        assembly.assembly_origin[1] + ppd.resonator_origin[1],
    )


def _cluster_pads_by_y(
    keepouts: Sequence[gdstk.Polygon],
) -> GsgPadRoles | None:
    """
    Cluster pad keepouts into three Y-sorted regions (A1).

    Uses bbox-centroid Y gaps to split into top / center / bottom bands.
    """
    entries: list[tuple[float, gdstk.Polygon]] = []
    for poly in keepouts:
        bb = poly.bounding_box()
        if bb is None or abs(poly.area()) < MIN_PAD_POLY_AREA:
            continue
        cy = (bb[0][1] + bb[1][1]) / 2.0
        entries.append((cy, poly))
    if len(entries) < 3:
        return None

    entries.sort(key=lambda item: item[0], reverse=True)
    ys = [cy for cy, _ in entries]
    gaps = [(ys[i] - ys[i + 1], i) for i in range(len(ys) - 1)]
    gaps.sort(reverse=True)
    if len(gaps) < 2:
        return None
    split_a = gaps[0][1] + 1
    split_b = gaps[1][1] + 1
    if split_a == split_b:
        split_b = split_a + 1
    splits = sorted({split_a, split_b})
    if len(splits) != 2:
        return None

    top = [p for _y, p in entries[: splits[0]]]
    center = [p for _y, p in entries[splits[0] : splits[1]]]
    bottom = [p for _y, p in entries[splits[1] :]]
    if not top or not center or not bottom:
        return None

    top_cy = sum((p.bounding_box()[0][1] + p.bounding_box()[1][1]) / 2 for p in top) / len(top)
    center_cy = sum((p.bounding_box()[0][1] + p.bounding_box()[1][1]) / 2 for p in center) / len(center)
    bottom_cy = sum((p.bounding_box()[0][1] + p.bounding_box()[1][1]) / 2 for p in bottom) / len(bottom)
    if not (top_cy > center_cy > bottom_cy):
        return None
    return GsgPadRoles(top_ground=top, center_signal=center, bottom_ground=bottom)


def _cell_bbox_area(cell: gdstk.Cell) -> float:
    bb = cell.bounding_box()
    if bb is None:
        bb = cell.flatten().bounding_box()
    if bb is None:
        return 0.0
    return max(0.0, (bb[1][0] - bb[0][0]) * (bb[1][1] - bb[0][1]))


def _ppd_master_cell(ppd_asm: ResonatorPpdAssembly) -> gdstk.Cell | None:
    """
    PPD / GSG frame master used for pad keepouts (excludes resonator master).

    Resolves wrapper cells such as ``GSG_frame`` → ``ppd_1port`` and falls back
    to the largest non-resonator cell in ``ppd_asm.library`` when references are
    missing (e.g. stale notebook kernel state).
    """
    skip_names = {ppd_asm.master_name, ppd_asm.top_cell.name}
    best: gdstk.Cell | None = None
    best_area = 0.0

    def consider(cell: gdstk.Cell | None) -> None:
        nonlocal best, best_area
        if cell is None or cell.name in skip_names:
            return
        area = _cell_bbox_area(cell)
        if area > best_area:
            best_area = area
            best = cell

    for ref in ppd_asm.top_cell.references:
        consider(ref.cell)
        if ref.cell is not None and not ref.cell.polygons:
            for inner in ref.cell.references:
                consider(inner.cell)

    if best is None:
        for cell in ppd_asm.library.cells:
            consider(cell)

    if best is None and ppd_asm.library.cells:
        try:
            consider(frame_top_cell(ppd_asm.library))
        except ValueError:
            pass

    return best


def classify_gsg_pads(assembly: RtegFrameAssembly) -> GsgPadRoles | None:
    """
    Structural GSG pad classification on the placed PPD (A1).

    Returns ``None`` when three vertical pad bands cannot be resolved.
    """
    ppd_asm = assembly.ppd_assembly
    ppd_master = _ppd_master_cell(ppd_asm)
    world_origin = _ppd_world_origin(assembly)
    if ppd_master is not None:
        keepouts = ppd_pad_keepout_polys(ppd_master, world_origin)
    else:
        # Last resort: placed PPD assembly top cell (may include resonator MBE).
        keepouts = ppd_pad_keepout_polys(ppd_asm.top_cell, world_origin)
    return _cluster_pads_by_y(keepouts)


def _find_connect_cell(
    library: gdstk.Library,
    parent: str,
) -> gdstk.Cell | None:
    for suffix in ("_connect_backup", "_connectMBE"):
        name = f"{parent}{suffix}"
        for cell in library.cells:
            if cell.name == name:
                return cell
    return None


def _bbox_overlap(
    a: tuple[tuple[float, float], tuple[float, float]],
    b: tuple[tuple[float, float], tuple[float, float]],
) -> bool:
    (ax0, ay0), (ax1, ay1) = a
    (bx0, by0), (bx1, by1) = b
    return ax0 <= bx1 and bx0 <= ax1 and ay0 <= by1 and by0 <= ay1


def _expand_bbox(
    bbox: tuple[tuple[float, float], tuple[float, float]],
    margin: float,
) -> tuple[tuple[float, float], tuple[float, float]]:
    (x0, y0), (x1, y1) = bbox
    return (x0 - margin, y0 - margin), (x1 + margin, y1 + margin)


def _polys_near_bbox(
    polys: Sequence[gdstk.Polygon],
    bbox: tuple[tuple[float, float], tuple[float, float]],
) -> list[gdstk.Polygon]:
    return [
        poly
        for poly in polys
        if (bb := poly.bounding_box()) is not None and _bbox_overlap(bb, bbox)
    ]


def extract_preserved_metal(
    identification: IdentificationResult,
    res: Resonator,
    layermap: LayerMap,
    config: RouteSearchConfig | GroundMergeConfig,
) -> list[gdstk.Polygon]:
    """
    Preserved interconnect polygons from connect cell in filter coordinates (A3, A4).

  Filtered to ``config.target_route_layer`` and overlapping resonator bbox + margin.
  """
    connect = _find_connect_cell(identification.library, identification.parent)
    if connect is None:
        return []

    layer, datatype = layermap.pair(config.target_route_layer)
    flat = connect.flatten()
    (rx0, ry0), (rx1, ry1) = resonator_world_bbox(res)
    margin = config.preserved_overlap_margin_um
    overlap_bb = ((rx0 - margin, ry0 - margin), (rx1 + margin, ry1 + margin))

    polys: list[gdstk.Polygon] = []
    for poly in flat.polygons:
        if (poly.layer, poly.datatype) != (layer, datatype):
            continue
        bb = poly.bounding_box()
        if bb is None or not _bbox_overlap(bb, overlap_bb):
            continue
        polys.append(poly)
    return polys


def filter_to_rteg_world(
    filter_polys: Sequence[gdstk.Polygon],
    res: Resonator,
    assembly: RtegFrameAssembly,
    *,
    extra_shift: tuple[float, float] = (0.0, 0.0),
) -> list[gdstk.Polygon]:
    """Map filter-space preserved metal into RTEG top-cell coordinates (A5)."""
    rteg_origin = _resonator_rteg_origin(assembly)
    tx = rteg_origin[0] - res.origin[0] + extra_shift[0]
    ty = rteg_origin[1] - res.origin[1] + extra_shift[1]
    return translate_polygons(filter_polys, tx, ty)


def resonator_metal_rteg(
    res: Resonator,
    assembly: RtegFrameAssembly,
    *,
    extra_shift: tuple[float, float] = (0.0, 0.0),
) -> list[gdstk.Polygon]:
    """Resonator MBE/MTE polygons in RTEG world space."""
    ppd = assembly.ppd_assembly
    polys = resonator_metal_polys(
        res,
        ppd.shift[0] + extra_shift[0],
        ppd.shift[1] + extra_shift[1],
    )
    return translate_polygons(polys, assembly.assembly_origin[0], assembly.assembly_origin[1])


def build_routable_region(
    assembly: RtegFrameAssembly,
    obstacle_polys: Sequence[gdstk.Polygon],
    config: RouteSearchConfig | GroundMergeConfig,
) -> list[gdstk.Polygon]:
    """
    Inner die cavity minus grown obstacles.

  Retained for the agentic context and future signal routing. Obstacles include
  resonator metal, release holes, and other-net layers.
  """
    (ix0, iy0), (ix1, iy1) = assembly.inner_die_frame_bbox
    cavity = gdstk.rectangle((ix0, iy0), (ix1, iy1))
    if not obstacle_polys:
        return [cavity]

    grown: list[gdstk.Polygon] = []
    for poly in obstacle_polys:
        margin = max(config.mbe_mte_spacing_um / 2.0, 1.0)
        grown.extend(grow_polygon(poly, margin))

    if not grown:
        return [cavity]

    obs_union = polygons_union(grown)
    if not obs_union:
        return [cavity]
    free = gdstk.boolean(cavity, obs_union, "not", precision=1e-3)
    return free if free else []


def _collect_layer_polys(
    assembly: RtegFrameAssembly,
    layermap: LayerMap,
    layer_names: Sequence[str],
    *,
    extra_shift: tuple[float, float] = (0.0, 0.0),
) -> list[gdstk.Polygon]:
    pairs = {layermap.pair(name) for name in layer_names}
    flat = assembly.flatten()
    polys: list[gdstk.Polygon] = []
    for poly in flat.polygons:
        if (poly.layer, poly.datatype) not in pairs:
            continue
        if extra_shift != (0.0, 0.0):
            polys.append(translate_polygon(poly, *extra_shift))
        else:
            polys.append(poly)
    return polys


def _via_at_center_needed(
    pads: GsgPadRoles,
    ground_body: Sequence[gdstk.Polygon],
    layermap: LayerMap,
) -> bool:
    """
    A11 — True when the carved ground body overlaps the center signal-pad region.

  Ground-only plate merge should stay clear of the center signal pad; flag any
  overlap so the operator re-checks whether a center MBE→MTE via is implied.
  """
    mte_pair = layermap.pair("BAW_MTE")
    center_mte = [p for p in pads.center_signal if (p.layer, p.datatype) == mte_pair]
    if not center_mte:
        center_mte = list(pads.center_signal)
    for body_poly in ground_body:
        for pad in center_mte:
            if gdstk.boolean(body_poly, pad, "and", precision=1e-3):
                return True
    return False


@dataclass
class RtegRoutedAssembly:
    """Step-5 output: step-4 assembly + carved ground body + preserved metal."""

    index: int
    inst_name: str
    frame_assembly: RtegFrameAssembly
    ground_body: list[gdstk.Polygon]
    preserved_metal: list[gdstk.Polygon]
    placement_shift: tuple[float, float]
    status: str
    skip_reason: str | None
    merge_skip_reason: str | None
    bridges_applied: int
    connector_used: bool
    n_severed_fragments: int
    mbe_area_um2: float
    ground_body_hash: str
    drc_violations: int
    via_at_center_flag: bool
    pads_connected: tuple[str, ...]
    top_cell: gdstk.Cell
    library: gdstk.Library
    # Deprecated wire-search fields (kept ``None``/``0`` so notebook/export and
    # the comparison report keep their column shape).
    route_polygon: gdstk.Polygon | None = None
    route_shape: str | None = None
    pad_label: str | None = None
    score: float | None = None
    n_candidates: int = 0
    n_clean: int = 0

    def flatten(self) -> gdstk.Cell:
        return self.top_cell.flatten()

    def summary_row(self) -> dict[str, object]:
        return {
            "index": self.index,
            "inst_name": self.inst_name,
            "status": self.status,
            "skip_reason": self.skip_reason or "",
            "bridges": self.bridges_applied,
            "connector": self.connector_used,
            "severed": self.n_severed_fragments,
            "pads_connected": ",".join(self.pads_connected),
            "mbe_area_um2": round(self.mbe_area_um2, 1),
            "ground_body_hash": self.ground_body_hash,
            "drc_violations": self.drc_violations,
            "via_at_center_flag": self.via_at_center_flag,
            "n_preserved_polys": len(self.preserved_metal),
        }


def _bbox_close(a, b, tol: float = 1.0) -> bool:
    return (
        abs(a[0][0] - b[0][0]) <= tol
        and abs(a[0][1] - b[0][1]) <= tol
        and abs(a[1][0] - b[1][0]) <= tol
        and abs(a[1][1] - b[1][1]) <= tol
    )


def _build_routed_top_cell(
    assembly: RtegFrameAssembly,
    preserved: Sequence[gdstk.Polygon],
    ground_body: Sequence[gdstk.Polygon],
    consumed_bboxes: Sequence[tuple[tuple[float, float], tuple[float, float]]],
    mbe_pair: tuple[int, int],
) -> tuple[gdstk.Cell, gdstk.Library]:
    """
    Frame geometry + carved ground body + exact preserved metal.

    The MBE plates consumed by the merge (GSG ground arms + filler) are dropped
    from the flattened frame and replaced by the carved ground body. The die
    frame ring and all non-MBE pad markers are kept. Preserved metal is re-added
    exactly (NPI), which also reconnects any micro-fragment the carve pinched off.
    """
    top = gdstk.Cell(f"routed_{assembly.index}_{assembly.inst_name}")
    for poly in assembly.flatten().polygons:
        if (poly.layer, poly.datatype) == mbe_pair:
            bb = poly.bounding_box()
            if bb is not None and any(_bbox_close(bb, cb) for cb in consumed_bboxes):
                continue  # replaced by the carved ground body
        top.add(poly)
    for poly in ground_body:
        top.add(gdstk.Polygon(poly.points, layer=mbe_pair[0], datatype=mbe_pair[1]))
    for poly in preserved:
        top.add(poly)

    out_lib = gdstk.Library()
    for cell in assembly.library.cells:
        out_lib.add(cell)
    out_lib.add(top)
    return top, out_lib


def _near_resonator_release_holes(
    assembly: RtegFrameAssembly,
    res: Resonator,
    layermap: LayerMap,
    config: GroundMergeConfig,
) -> list[gdstk.Polygon]:
    """Release-hole polys limited to the resonator neighborhood (excludes pad cavities)."""
    rh_pairs = {layermap.pair(n) for n in config.release_hole_layers}
    flat = assembly.flatten()
    res_metal = resonator_metal_rteg(res, assembly)
    res_bboxes = [bb for p in res_metal if (bb := p.bounding_box()) is not None]
    if res_bboxes:
        rteg_res_bb = _expand_bbox(
            (
                (min(bb[0][0] for bb in res_bboxes), min(bb[0][1] for bb in res_bboxes)),
                (max(bb[1][0] for bb in res_bboxes), max(bb[1][1] for bb in res_bboxes)),
            ),
            config.preserved_overlap_margin_um,
        )
    else:
        origin = _resonator_rteg_origin(assembly)
        rteg_res_bb = _expand_bbox(
            (origin, origin), config.preserved_overlap_margin_um
        )
    return _polys_near_bbox(
        [p for p in flat.polygons if (p.layer, p.datatype) in rh_pairs],
        rteg_res_bb,
    )


def _skipped_result(
    assembly: RtegFrameAssembly,
    preserved: Sequence[gdstk.Polygon],
    reason: str,
) -> RtegRoutedAssembly:
    top, lib = _build_routed_top_cell(assembly, preserved, [], [], (-1, -1))
    return RtegRoutedAssembly(
        index=assembly.index,
        inst_name=assembly.inst_name,
        frame_assembly=assembly,
        ground_body=[],
        preserved_metal=list(preserved),
        placement_shift=(0.0, 0.0),
        status="skipped",
        skip_reason=reason,
        merge_skip_reason=reason,
        bridges_applied=0,
        connector_used=False,
        n_severed_fragments=0,
        mbe_area_um2=0.0,
        ground_body_hash="(empty)",
        drc_violations=0,
        via_at_center_flag=False,
        pads_connected=(),
        top_cell=top,
        library=lib,
    )


def _merge_ground_one_assembly(
    assembly: RtegFrameAssembly,
    res: Resonator,
    identification: IdentificationResult,
    layermap: LayerMap,
    config: GroundMergeConfig,
) -> RtegRoutedAssembly:
    """Plate-merge the ground side for one assembly (auto bridge + auto connector)."""
    pads = classify_gsg_pads(assembly)
    if pads is None:
        return _skipped_result(assembly, [], "pad_classification_failed")

    filter_preserved = extract_preserved_metal(identification, res, layermap, config)
    if not filter_preserved:
        return _skipped_result(assembly, [], "no_preserved_metal")
    preserved = filter_to_rteg_world(filter_preserved, res, assembly)

    mbe_pair = layermap.pair(config.target_route_layer)
    signal_pair = layermap.pair(config.signal_layer)
    res_mbe = [
        p
        for p in resonator_metal_rteg(res, assembly)
        if (p.layer, p.datatype) == mbe_pair
    ]
    center_mte = [
        p for p in pads.center_signal if (p.layer, p.datatype) == signal_pair
    ] or list(pads.center_signal)
    mte_obstacles = _collect_layer_polys(assembly, layermap, config.obstacle_layers)
    spacing_obstacles = center_mte + mte_obstacles + res_mbe
    release_holes = _near_resonator_release_holes(assembly, res, layermap, config)

    result: GroundMergeResult = run_ground_merge(
        assembly=assembly,
        layermap=layermap,
        pads=pads,
        preserved=preserved,
        spacing_obstacles=spacing_obstacles,
        release_holes=release_holes,
        config=config,
    )

    if result.skip_reason is not None:
        return _skipped_result(assembly, preserved, result.skip_reason)

    rep = result.report
    consumed = [
        bb for p in result.plates.all() if (bb := p.bounding_box()) is not None
    ]
    via_flag = _via_at_center_needed(pads, result.carved_body, layermap)
    status = "routed" if result.is_success else "failed"
    merge_skip = None if result.is_success else "ground_merge_not_clean"

    top, lib = _build_routed_top_cell(
        assembly, preserved, result.carved_body, consumed, mbe_pair
    )
    return RtegRoutedAssembly(
        index=assembly.index,
        inst_name=assembly.inst_name,
        frame_assembly=assembly,
        ground_body=result.carved_body,
        preserved_metal=preserved,
        placement_shift=(0.0, 0.0),
        status=status,
        skip_reason=merge_skip,
        merge_skip_reason=merge_skip,
        bridges_applied=len(result.bridges),
        connector_used=result.connector_rect is not None,
        n_severed_fragments=len(rep.split_locations),
        mbe_area_um2=rep.mbe_area_um2,
        ground_body_hash=rep.ground_body_hash,
        drc_violations=len(rep.violations),
        via_at_center_flag=via_flag,
        pads_connected=tuple(sorted(rep.pads_connected)),
        top_cell=top,
        library=lib,
    )


def route_rteg_assemblies(
    assemblies: Sequence[RtegFrameAssembly],
    identification: IdentificationResult,
    layermap: LayerMap,
    *,
    config: GroundMergeConfig | None = None,
    indices: Sequence[int] | None = None,
) -> tuple[list[RtegRoutedAssembly], pd.DataFrame]:
    """
    Run step-5 MBE ground plate merge for selected frame assemblies.

  ``indices`` defaults to all assemblies (notebook typically starts with ``[5]``).
  """
    cfg = config or GroundMergeConfig()
    selected = list(indices) if indices is not None else [a.index for a in assemblies]
    index_set = set(selected)

    resonators = identification.resonators
    by_index = {a.index: a for a in assemblies}

    results: list[RtegRoutedAssembly] = []
    for idx in sorted(index_set):
        if idx not in by_index:
            continue
        if idx >= len(resonators):
            continue
        results.append(
            _merge_ground_one_assembly(
                by_index[idx],
                resonators[idx],
                identification,
                layermap,
                cfg,
            )
        )

    return results, pd.DataFrame([r.summary_row() for r in results])


def preview_routed_svg(assembly: RtegRoutedAssembly) -> str:
    flat = assembly.flatten()
    with tempfile.TemporaryDirectory() as tmp:
        svg_path = Path(tmp) / f"{assembly.top_cell.name}.svg"
        flat.write_svg(str(svg_path))
        return svg_path.read_text(encoding="utf-8")
