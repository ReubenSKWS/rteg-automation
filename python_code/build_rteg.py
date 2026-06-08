"""
Export one resonator per GDS, centered inside the GSG frame template.

Each file: GSG_frame at origin + one resonator pasted at the frame center.
One GDS per resonator. No vias or filter metal yet.

Draft outputs go to draft_output/. Ground truth stays in example_output/.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import gdstk

from layermap import LAYERMAP_PATH, describe_layers, gds_pairs_in_cell, load_layermap
from separate import Resonator, separate

FRAME_GDS = Path(__file__).parent / "GSG_frame.gds"
FRAME_TOP = "GSG_frame"


@dataclass
class ResonatorExportStats:
    """Summary for one exported resonator GDS."""

    cell_name: str
    res_type: str
    master_name: str
    filter_origin: tuple[float, float]
    rteg_origin: tuple[float, float]
    rotation: float
    layers: list[str]


def rteg_cell_name(parent: str, index: int, res: Resonator) -> str:
    """Indexed name when Virtuoso instance names are unavailable in GDS."""
    return f"{parent}_RTEG1_{index:02d}_{res.res_type}"


def _bbox_center(
    bbox: tuple[tuple[float, float], tuple[float, float]],
) -> tuple[float, float]:
    (x0, y0), (x1, y1) = bbox
    return (x0 + x1) / 2, (y0 + y1) / 2


def center_in_frame(
    res_cell: gdstk.Cell, frame_cell: gdstk.Cell
) -> tuple[float, float]:
    """Origin for resonator so its bbox center sits on the frame bbox center."""
    res_bb = res_cell.bounding_box()
    frame_bb = frame_cell.bounding_box()
    if res_bb is None or frame_bb is None:
        raise ValueError("Resonator or frame cell has no bounding box")
    rcx, rcy = _bbox_center(res_bb)
    fcx, fcy = _bbox_center(frame_bb)
    return fcx - rcx, fcy - rcy


def export_resonators(
    filter_gds: str | Path,
    output_dir: str | Path,
    frame_gds: str | Path | None = None,
    layermap_path: str | Path | None = None,
) -> list[ResonatorExportStats]:
    """
    For each resonator, write one GDS: GSG_frame + resonator centered in frame.
    """
    filter_gds = Path(filter_gds)
    frame_gds = Path(frame_gds or FRAME_GDS)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    layermap = load_layermap(layermap_path)
    filter_lib = gdstk.read_gds(filter_gds)
    frame_lib = gdstk.read_gds(frame_gds)

    frame_cell = next(c for c in frame_lib.cells if c.name == FRAME_TOP)
    frame_subcells = {c.name: c for c in frame_lib.cells}

    resonators_by_parent = separate(filter_lib)
    all_stats: list[ResonatorExportStats] = []

    for parent, res_list in resonators_by_parent.items():
        for index, res in enumerate(res_list):
            name = rteg_cell_name(parent, index, res)
            origin = center_in_frame(res.reference.cell, frame_cell)

            top = gdstk.Cell(name)
            top.add(gdstk.Reference(frame_cell, origin=(0.0, 0.0)))
            top.add(
                gdstk.Reference(
                    res.reference.cell,
                    origin=origin,
                    rotation=res.rotation,
                    magnification=res.magnification,
                    x_reflection=res.x_reflection,
                )
            )

            out_lib = gdstk.Library()
            for cell in frame_subcells.values():
                out_lib.add(cell)
            out_lib.add(res.reference.cell)
            out_lib.add(top)
            out_lib.write_gds(output_dir / f"{name}.gds")

            layers = describe_layers(
                gds_pairs_in_cell(res.reference.cell), layermap
            )
            all_stats.append(
                ResonatorExportStats(
                    cell_name=name,
                    res_type=res.res_type,
                    master_name=res.master_name,
                    filter_origin=res.origin,
                    rteg_origin=origin,
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
            f"    type={s.res_type}  master={s.master_name}\n"
            f"    filter@={filt_xy}  centered@={rteg_xy}  rotation={rot_deg} deg\n"
            f"    layers: {layer_preview}"
        )
