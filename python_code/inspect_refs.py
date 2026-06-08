"""
Inspect how instance identity survives GDS export.
"""
import sys
import gdstk
from pathlib import Path

gds_path = Path(__file__).parent / "KB331_N_01_clean.gds"
lib = gdstk.read_gds(gds_path)
for cell in lib.cells:
    refs = cell.references
    if not refs:
        continue
    print(f"\n{cell.name}: {len(refs)} references")
    for ref in refs[:15]:
        master = ref.cell.name if ref.cell else "<raw>"
        props = getattr(ref, "properties", None)
        print(f"   -> {master:24s} @ {tuple(round(c,2) for c in ref.origin)}"
              f"  rot={ref.rotation}  props={props if props else '—'}")
    # show any text labels that might carry resonator identity
    if cell.labels:
        print(f"   labels ({len(cell.labels)}):")
        for lbl in cell.labels[:15]:
            print(f"     '{lbl.text}' @ {tuple(round(c,2) for c in lbl.origin)}"
                  f"  layer=({lbl.layer},{lbl.texttype})")
