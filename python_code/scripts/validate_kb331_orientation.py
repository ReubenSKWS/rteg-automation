#!/usr/bin/env python3
"""Print KB331 orientation routing validation table (steps 5.2 + 5.3)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from kb331_pipeline import load_kb331_pipeline
from rteg_classify import classify_nodes
from rteg_collect import collect_geometry_roles, collect_orientation_inputs
from rteg_signal import SignalBuildConfig, build_signal_net


def main() -> int:
    ctx = load_kb331_pipeline()
    layermap = ctx["layermap"]
    mte_pair = layermap.pair("BAW_MTE")
    cfg = SignalBuildConfig()

    headers = [
        "index",
        "res_type",
        "signal_terminal",
        "collar_axis",
        "facing_pad",
        "mte_route_target",
        "mte_faces_center",
        "intercept_xy",
        "drc_clean",
        "min_spacing_um",
        "placement_shift",
        "mte_layer",
    ]
    print("\t".join(headers))

    for asm, res, ppd in zip(
        ctx["frame_assemblies"],
        ctx["res_list"],
        ctx["ppd_assemblies"],
        strict=True,
    ):
        roles = collect_geometry_roles(
            asm, res, ctx["identification"], layermap
        )
        orientation = collect_orientation_inputs(
            asm,
            res,
            ctx["identification"],
            layermap,
            ground_plates=roles.ground_plates,
        )
        classification = classify_nodes(
            roles.ground_plates,
            roles.preserved,
            orientation=orientation,
            res_type=res.res_type,
        )
        signal = build_signal_net(
            roles.preserved,
            classification,
            roles.ground_plates,
            layermap,
            cfg,
            release_holes=roles.release_holes,
        )
        collar = classification.collar_orientation
        intercept = signal.endpoints.metal_point
        layers = {
            (p.layer, p.datatype) for p in signal.net_polygons
        } or {None}
        mte_layer = next(iter(layers)) if signal.net_polygons else mte_pair
        row = [
            str(asm.index),
            res.res_type,
            classification.signal_terminal,
            collar.axis,
            collar.facing_pad,
            classification.mte_route_target,
            str(classification.collar_orientation.mte_faces_center),
            f"({intercept[0]:.1f},{intercept[1]:.1f})",
            str(signal.is_success),
            f"{signal.min_ground_spacing_um:.1f}"
            if signal.min_ground_spacing_um == signal.min_ground_spacing_um
            else "nan",
            f"({ppd.orientation_shift[0]:.1f},{ppd.orientation_shift[1]:.1f})",
            str(mte_layer),
        ]
        print("\t".join(row))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
