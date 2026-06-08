"""
Export one resonator per GDS with the GSG frame at top-left and signal node at frame center.

Each file: GSG frame + ppd at top-left, resonator shifted so signal node is at
frame center. Visual sanity check — no preserved metal or vias.

Draft outputs go to draft_output/. Ground truth stays in example_output/.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import gdstk

from layermap import LAYERMAP_PATH, describe_layers, gds_pairs_in_cell, load_layermap
from rteg_skill import (
    FRAME_ORIGIN,
    PPD_ORIGIN,
    frame_top_cell,
    infer_inst_names,
    placement_shift,
    rteg_cell_name,
)
from separate import separate

FILTER_GDS = Path(__file__).parent / "KB331_N_01_clean.gds"
FRAME_GDS = Path(__file__).parent / "KB331_N_Frame.gds"
PPD_GDS = Path(__file__).parent / "ppd_1port.gds"
PPD_TOP = "ppd_1port"


@dataclass
class ResonatorExportStats:
    """Summary for one exported resonator GDS."""

    cell_name: str
    inst_name: str
    res_type: str
    master_name: str
    filter_origin: tuple[float, float]
    rteg_origin: tuple[float, float]
    rotation: float
    layers: list[str]


def export_resonators(
    filter_gds: str | Path,
    output_dir: str | Path,
    frame_gds: str | Path | None = None,
    ppd_gds: str | Path | None = None,
    layermap_path: str | Path | None = None,
) -> list[ResonatorExportStats]:
    """For each resonator, write one GDS with top-left frame and signal-node placement."""
    filter_gds = Path(filter_gds)
    frame_gds = Path(frame_gds or FRAME_GDS)
    ppd_gds = Path(ppd_gds or PPD_GDS)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    layermap = load_layermap(layermap_path)
    filter_lib = gdstk.read_gds(filter_gds)
    frame_lib = gdstk.read_gds(frame_gds)
    ppd_lib = gdstk.read_gds(ppd_gds)

    frame_cell = frame_top_cell(frame_lib)
    frame_subcells = {c.name: c for c in frame_lib.cells}
    ppd_cell = next(c for c in ppd_lib.cells if c.name == PPD_TOP)

    resonators_by_parent = separate(filter_lib)
    all_stats: list[ResonatorExportStats] = []

    for parent, res_list in resonators_by_parent.items():
        inst_names = infer_inst_names(res_list)
        for index, res in enumerate(res_list):
            inst_name = inst_names[index]
            name = rteg_cell_name(parent, inst_name)
            dx, dy = placement_shift(res, frame_cell, layermap)
            rteg_origin = (res.origin[0] + dx, res.origin[1] + dy)

            top = gdstk.Cell(name)
            top.add(gdstk.Reference(frame_cell, origin=FRAME_ORIGIN))
            top.add(gdstk.Reference(ppd_cell, origin=PPD_ORIGIN))
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
            for cell in frame_subcells.values():
                out_lib.add(cell)
            out_lib.add(ppd_cell)
            out_lib.add(res.reference.cell)
            out_lib.add(top)
            out_lib.write_gds(output_dir / f"{name}.gds")

            layers = describe_layers(
                gds_pairs_in_cell(res.reference.cell), layermap
            )
            all_stats.append(
                ResonatorExportStats(
                    cell_name=name,
                    inst_name=inst_name,
                    res_type=res.res_type,
                    master_name=res.master_name,
                    filter_origin=res.origin,
                    rteg_origin=rteg_origin,
                    rotation=res.rotation,
                    layers=layers,
                )
            )

    return all_stats


if __name__ == "__main__":
    base = Path(__file__).parent
    filter_path = base / "KB331_N_01_clean.gds"
    out_dir = base / "draft_output"

    print(f"Filter: {filter_path}")
    print(f"Frame:  {FRAME_GDS}")
    print(f"PPD:    {PPD_GDS}")
    print(f"Layermap: {LAYERMAP_PATH}")
    print(f"Output: {out_dir}\n")

    stats_list = export_resonators(filter_path, out_dir)
    print(f"Exported {len(stats_list)} resonator(s):\n")
    for s in stats_list:
        filt_xy = tuple(round(x, 1) for x in s.filter_origin)
        rteg_xy = tuple(round(x, 1) for x in s.rteg_origin)
        rot_deg = round(s.rotation * 180 / 3.141592653589793, 1)
        layer_preview = ", ".join(s.layers[:4])
        if len(s.layers) > 4:
            layer_preview += f" ... +{len(s.layers) - 4} more"
        print(
            f"  {s.cell_name}.gds\n"
            f"    inst={s.inst_name}  type={s.res_type}  master={s.master_name}\n"
            f"    filter@={filt_xy}  rteg@={rteg_xy}\n"
            f"    rotation={rot_deg} deg\n"
            f"    layers: {layer_preview}"
        )
