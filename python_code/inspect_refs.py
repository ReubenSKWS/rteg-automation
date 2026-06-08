"""
Inspect how instance identity survives GDS export.

Defaults to the filter GDS and the ppd_1port probe-pad template used by the
prepare/route test pipeline. Pass a path to inspect other files (e.g. prepared
or routed draft outputs).
"""
from __future__ import annotations

import sys
from pathlib import Path

import gdstk

FILTER_GDS = Path(__file__).parent / "KB331_N_01_clean.gds"
FRAME_GDS = Path(__file__).parent / "ppd_1port.gds"
FRAME_TOP = "ppd_1port"


def inspect_cell(cell: gdstk.Cell, max_refs: int = 15) -> None:
    refs = cell.references
    if refs:
        print(f"\n{cell.name}: {len(refs)} references")
        for ref in refs[:max_refs]:
            master = ref.cell.name if ref.cell else "<raw>"
            props = getattr(ref, "properties", None)
            print(
                f"   -> {master:24s} @ {tuple(round(c, 2) for c in ref.origin)}"
                f"  rot={ref.rotation}  props={props if props else '—'}"
            )
        if len(refs) > max_refs:
            print(f"   ... +{len(refs) - max_refs} more")
    else:
        bb = cell.bounding_box()
        bb_str = (
            f"({bb[0][0]:.1f}, {bb[0][1]:.1f})-({bb[1][0]:.1f}, {bb[1][1]:.1f})"
            if bb
            else "none"
        )
        print(f"\n{cell.name}: {len(cell.polygons)} polys, bbox {bb_str} (no references)")

    if cell.labels:
        print(f"   labels ({len(cell.labels)}):")
        for lbl in cell.labels[:max_refs]:
            print(
                f"     '{lbl.text}' @ {tuple(round(c, 2) for c in lbl.origin)}"
                f"  layer=({lbl.layer},{lbl.texttype})"
            )


def inspect_gds(path: Path) -> None:
    print(f"\n=== {path.name} ===")
    lib = gdstk.read_gds(path)
    for cell in lib.cells:
        if cell.references or cell.labels or cell.name in lib.top_level():
            inspect_cell(cell)


if __name__ == "__main__":
    paths = [Path(p) for p in sys.argv[1:]] if len(sys.argv) > 1 else [FILTER_GDS, FRAME_GDS]
    for gds_path in paths:
        inspect_gds(gds_path)
