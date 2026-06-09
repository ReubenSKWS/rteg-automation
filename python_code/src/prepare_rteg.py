"""
Prepare resonator(s) as routing-ready RTEG input.

Builds standalone RTEGs: die frame at top-left, ppd centered in frame, resonator
centered on the assembly, preserved metal and vias, golden layer trim.

Output: draft_output/<parent>_RTEG1_<instName>_prepared.gds
"""
from __future__ import annotations

import argparse
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import gdstk

import geometry as G
from layer_labels import describe_layers, gds_pairs_in_cell
from layermap import load_layermap
from paths import DEFAULT_LAYERMAP
from route_rteg import GOLDEN_DEFAULT, RouteConfig, resolve_allowed_layer_pairs
from rteg_skill import (
    add_foundation_refs,
    build_foundation,
    frame_top_cell,
    infer_inst_names,
    load_connect_backup,
    placement_shift,
    polygons_overlapping_bbox,
    resonator_world_bbox,
    rteg_cell_name,
    shift_polygon,
)
from separate import Resonator, find_vias, separate, vias_near

FILTER_GDS = Path(__file__).parent / "KB331_N_01_clean.gds"
FRAME_GDS = Path(__file__).parent / "KB331_N_Frame.gds"
PPD_GDS = Path(__file__).parent / "ppd_1port.gds"
PPD_TOP = "ppd_1port"
CONNECT_MTE_SUFFIX = "_connectMTE"
CONNECT_MBE_SUFFIX = "_connectMBE"


@dataclass
class PrepareStats:
    """Summary for one prepared resonator."""

    cell_name: str
    inst_name: str
    res_type: str
    master_name: str
    filter_origin: tuple[float, float]
    rteg_origin: tuple[float, float]
    rotation: float
    via_count: int
    metal_source: str
    preserved_poly_count: int
    mte_poly_count: int
    mbe_poly_count: int
    trimmed_poly_count: int = 0
    layers_absent_from_golden: list[str] = field(default_factory=list)
    layers: list[str] = field(default_factory=list)


def _layers_absent_from_golden(
    polys: list[gdstk.Polygon], allowed: set[tuple[int, int]], layermap
) -> list[str]:
    absent: set[str] = set()
    for p in polys:
        pair = (p.layer, p.datatype)
        if pair not in allowed:
            name = layermap.name(p.layer, p.datatype) or f"{p.layer}/{p.datatype}"
            absent.add(name)
    return sorted(absent)


def _find_connect_cell(lib: gdstk.Library, parent: str, suffix: str) -> gdstk.Cell | None:
    target = f"{parent}{suffix}"
    return next((c for c in lib.cells if c.name == target), None)


def _select_parent(
    resonators_by_parent: dict[str, list[Resonator]],
) -> tuple[str, list[Resonator]]:
    if not resonators_by_parent:
        raise ValueError("No resonators found in filter GDS")
    parent = sorted(resonators_by_parent)[0]
    return parent, resonators_by_parent[parent]


def _preserved_metal_polys(
    filter_lib: gdstk.Library,
    parent: str,
    res_bbox: tuple[tuple[float, float], tuple[float, float]],
    search_dir: Path,
) -> tuple[list[gdstk.Polygon], str, int, int]:
    """Return (polys, source_label, mte_count, mbe_count)."""
    backup = load_connect_backup(parent, search_dir, filter_lib)
    if backup is not None:
        polys = polygons_overlapping_bbox(backup, res_bbox)
        return polys, "connect_backup", 0, 0

    warnings.warn(
        f"No usable {parent}_connect_backup — using connectMTE/MBE fallback",
        stacklevel=3,
    )
    mte_cell = _find_connect_cell(filter_lib, parent, CONNECT_MTE_SUFFIX)
    mbe_cell = _find_connect_cell(filter_lib, parent, CONNECT_MBE_SUFFIX)
    mte_polys = polygons_overlapping_bbox(mte_cell, res_bbox) if mte_cell else []
    mbe_polys = polygons_overlapping_bbox(mbe_cell, res_bbox) if mbe_cell else []
    return mte_polys + mbe_polys, "connectMTE/MBE", len(mte_polys), len(mbe_polys)


def prepare_resonator(
    index: int,
    filter_gds: str | Path = FILTER_GDS,
    frame_gds: str | Path = FRAME_GDS,
    ppd_gds: str | Path = PPD_GDS,
    output_dir: str | Path | None = None,
    layermap_path: str | Path | None = None,
    golden_gds: str | Path = GOLDEN_DEFAULT,
    config: RouteConfig | None = None,
    inst_map_path: Path | None = None,
    inst_names: dict[int, str] | None = None,
) -> tuple[Path, PrepareStats]:
    """Build one prepared RTEG. Returns (output_path, stats)."""
    filter_gds = Path(filter_gds)
    frame_gds = Path(frame_gds)
    ppd_gds = Path(ppd_gds)
    golden_gds = Path(golden_gds)
    output_dir = Path(output_dir or (Path(__file__).parent / "draft_output"))
    output_dir.mkdir(parents=True, exist_ok=True)
    cfg = config or RouteConfig()

    layermap = load_layermap(layermap_path or DEFAULT_LAYERMAP)
    allowed = resolve_allowed_layer_pairs(cfg, golden_gds)
    filter_lib = gdstk.read_gds(filter_gds)
    frame_lib = gdstk.read_gds(frame_gds)
    ppd_lib = gdstk.read_gds(ppd_gds)

    frame_cell = frame_top_cell(frame_lib)
    frame_subcells = {c.name: c for c in frame_lib.cells}
    ppd_cell = next(c for c in ppd_lib.cells if c.name == PPD_TOP)
    foundation = build_foundation(frame_cell, ppd_cell)

    resonators_by_parent = separate(filter_lib)
    parent, res_list = _select_parent(resonators_by_parent)
    if not 0 <= index < len(res_list):
        raise IndexError(
            f"Resonator index {index} out of range (0..{len(res_list) - 1})"
        )
    res = res_list[index]

    names = inst_names or infer_inst_names(res_list, inst_map_path)
    inst_name = names[index]
    name = rteg_cell_name(parent, inst_name)

    dx, dy = placement_shift(res, frame_cell, ppd_cell, foundation=foundation)
    rteg_origin = (res.origin[0] + dx, res.origin[1] + dy)

    top = gdstk.Cell(name)
    add_foundation_refs(top, frame_cell, ppd_cell, foundation)
    top.add(
        gdstk.Reference(
            res.reference.cell,
            origin=rteg_origin,
            rotation=res.rotation,
            magnification=res.magnification,
            x_reflection=res.x_reflection,
        )
    )

    filter_cell = next(c for c in filter_lib.cells if c.name == parent)
    res_bbox = resonator_world_bbox(res)
    metal_polys, metal_source, mte_count, mbe_count = _preserved_metal_polys(
        filter_lib, parent, res_bbox, filter_gds.parent
    )
    for poly in metal_polys:
        top.add(shift_polygon(poly, dx, dy))

    near_vias = vias_near(res, find_vias(filter_cell))
    for via in near_vias:
        top.add(
            gdstk.Reference(
                via.cell,
                origin=(via.origin[0] + dx, via.origin[1] + dy),
                rotation=via.rotation,
                magnification=via.magnification,
                x_reflection=via.x_reflection,
            )
        )

    out_lib = gdstk.Library()
    for cell in frame_subcells.values():
        out_lib.add(cell)
    out_lib.add(ppd_cell)
    out_lib.add(res.reference.cell)
    for via in near_vias:
        if via.cell is not None:
            out_lib.add(via.cell)
    out_lib.add(top)

    trimmed_poly_count = 0
    if allowed is not None:
        for cell in out_lib.cells:
            trimmed_poly_count += G.filter_cell_layers_inplace(cell, allowed)

    flat_before_report = G.flatten_cell(top)
    absent = (
        _layers_absent_from_golden(flat_before_report, allowed, layermap)
        if allowed is not None
        else []
    )

    out_path = output_dir / f"{name}_prepared.gds"
    out_lib.write_gds(out_path)

    stats = PrepareStats(
        cell_name=name,
        inst_name=inst_name,
        res_type=res.res_type,
        master_name=res.master_name,
        filter_origin=res.origin,
        rteg_origin=rteg_origin,
        rotation=res.rotation,
        via_count=len(near_vias),
        metal_source=metal_source,
        preserved_poly_count=len(metal_polys),
        mte_poly_count=mte_count,
        mbe_poly_count=mbe_count,
        trimmed_poly_count=trimmed_poly_count,
        layers_absent_from_golden=absent,
        layers=describe_layers(gds_pairs_in_cell(res.reference.cell), layermap),
    )
    return out_path, stats


def prepare_all(
    filter_gds: str | Path = FILTER_GDS,
    frame_gds: str | Path = FRAME_GDS,
    ppd_gds: str | Path = PPD_GDS,
    output_dir: str | Path | None = None,
    layermap_path: str | Path | None = None,
    golden_gds: str | Path = GOLDEN_DEFAULT,
    config: RouteConfig | None = None,
    inst_map_path: Path | None = None,
) -> list[tuple[Path, PrepareStats]]:
    """Prepare all resonators in the filter variant."""
    filter_gds = Path(filter_gds)
    filter_lib = gdstk.read_gds(filter_gds)
    parent, res_list = _select_parent(separate(filter_lib))
    inst_names = infer_inst_names(res_list, inst_map_path)

    results: list[tuple[Path, PrepareStats]] = []
    for index in range(len(res_list)):
        results.append(
            prepare_resonator(
                index,
                filter_gds=filter_gds,
                frame_gds=frame_gds,
                ppd_gds=ppd_gds,
                output_dir=output_dir,
                layermap_path=layermap_path,
                golden_gds=golden_gds,
                config=config,
                inst_map_path=inst_map_path,
                inst_names=inst_names,
            )
        )
    return results


def _print_stats(stats: PrepareStats) -> None:
    filt_xy = tuple(round(x, 1) for x in stats.filter_origin)
    rteg_xy = tuple(round(x, 1) for x in stats.rteg_origin)
    rot_deg = round(stats.rotation * 180 / 3.141592653589793, 1)
    print(f"  {stats.cell_name}  ({stats.res_type}, inst={stats.inst_name})")
    print(f"    master={stats.master_name}")
    print(f"    filter@={filt_xy}  rteg@={rteg_xy}  (resonator -> assembly center)")
    print(f"    rotation={rot_deg} deg  vias={stats.via_count}")
    print(
        f"    preserved metal: {stats.preserved_poly_count} polys"
        f" ({stats.metal_source})"
    )
    if stats.metal_source == "connectMTE/MBE":
        print(f"      MTE={stats.mte_poly_count} MBE={stats.mbe_poly_count}")
    print(f"    trimmed {stats.trimmed_poly_count} polys to golden layer set")
    if stats.layers_absent_from_golden:
        print(f"    layers still absent from golden: {stats.layers_absent_from_golden}")
    else:
        print("    layers absent from golden: none")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Prepare RTEG routing input(s).")
    ap.add_argument("--index", type=int, default=None, help="Single resonator index")
    ap.add_argument("--all", action="store_true", help="Prepare all resonators")
    ap.add_argument(
        "--golden",
        type=Path,
        default=GOLDEN_DEFAULT,
        help="Golden GDS for layer allow-list (default S3).",
    )
    args = ap.parse_args()

    if args.all and args.index is not None:
        ap.error("Use either --all or --index, not both")
    if not args.all and args.index is None:
        args.index = 6

    print(f"Filter:   {FILTER_GDS}")
    print(f"Frame:    {FRAME_GDS}")
    print(f"PPD:      {PPD_GDS}")
    print(f"Golden:   {args.golden}")
    print(f"Layermap: {DEFAULT_LAYERMAP}\n")

    if args.all:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            results = prepare_all(golden_gds=args.golden)
        print(f"Prepared {len(results)} resonator(s):\n")
        for _, stats in results:
            _print_stats(stats)
            print()
        for w in caught:
            print(f"WARNING: {w.message}")
    else:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            out_path, stats = prepare_resonator(
                args.index,
                golden_gds=args.golden,
            )
        print(f"Output:   {out_path}\n")
        _print_stats(stats)
        for w in caught:
            print(f"\nWARNING: {w.message}")
