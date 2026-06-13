#!/usr/bin/env python3
"""Print KB331 MTE extension validation table (step 5.3)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from kb331_pipeline import load_kb331_pipeline
from rteg_collect import collect_geometry_roles
from rteg_mte_extensions import MteBuildConfig, build_mte_extensions, select_edge_collar_mte


def main() -> int:
    ctx = load_kb331_pipeline()
    layermap = ctx["layermap"]
    mte_pair = layermap.pair("BAW_MTE")
    cfg = MteBuildConfig()

    headers = [
        "index",
        "inst_name",
        "n_extensions",
        "is_connected",
        "collar_area",
        "extension_area",
        "violations",
    ]
    print("\t".join(headers))

    for asm, res in zip(ctx["frame_assemblies"], ctx["res_list"], strict=True):
        roles = collect_geometry_roles(asm, res, ctx["identification"], layermap)
        result = build_mte_extensions({asm.index: roles}, layermap, cfg)[asm.index]
        collar = select_edge_collar_mte(roles.preserved, roles.resonator_body_mte)
        row = [
            str(asm.index),
            asm.inst_name,
            str(result.n_extensions),
            str(result.is_connected),
            f"{abs(collar.polygon.area()):.0f}" if collar else "",
            f"{abs(result.extension.area()):.0f}" if result.extension else "",
            ";".join(result.drc_violations[:1]),
        ]
        print("\t".join(row))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
