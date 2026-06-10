"""
Step 1 — Process inputs: inspect GDS hierarchy and reference properties.

Lists placed instances and labels so you can confirm the filter export is
hierarchical and see whether Virtuoso instance names survived export.
"""
from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

import gdstk


def inspect_cell(cell: gdstk.Cell, max_refs: int = 15) -> None:
    refs = cell.references
    if refs:
        print(f"\n{cell.name}: {len(refs)} references")
        for ref in refs[:max_refs]:
            master = ref.cell.name if ref.cell else "<raw>"
            props = getattr(ref, "properties", None)
            print(
                f"   -> {master:24s} @ {tuple(round(c, 2) for c in ref.origin)}"
                f"  rot={ref.rotation}  props={props if props else '-'}"
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


def inspect_gds(path: str | Path, *, max_refs: int = 15) -> None:
    """Print hierarchy summary for one GDS file."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    print(f"\n=== {path.name} ===")
    lib = gdstk.read_gds(path)
    tops = {c.name for c in lib.top_level()}
    for cell in lib.cells:
        if cell.references or cell.labels or cell.name in tops:
            inspect_cell(cell, max_refs=max_refs)


def inspect_gds_files(
    paths: Sequence[str | Path],
    *,
    max_refs: int = 15,
    skip_missing: bool = False,
) -> None:
    """Print hierarchy summary for each GDS path in ``paths``."""
    for path in paths:
        path = Path(path)
        if not path.is_file():
            if skip_missing:
                print(f"ERROR: missing file: {path}")
                continue
            raise FileNotFoundError(path)
        inspect_gds(path, max_refs=max_refs)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python inspect_refs.py <file.gds> [more.gds ...]", file=sys.stderr)
        sys.exit(1)
    inspect_gds_files(sys.argv[1:], skip_missing=True)
