"""Probe reference vs filter geometry for resonator 6 intercepts."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import gdstk

SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parents[1] / "tests"
for p in (str(SRC), str(TESTS)):
    sys.path.insert(0, p)

from kb331_pipeline import load_kb331_pipeline
from rteg_die_intercepts import extract_reference_rteg_intercepts, resonator_anchor_center


def vertical_edges(poly: gdstk.Polygon, anchor: tuple[float, float]) -> None:
    pts = [(float(x), float(y)) for x, y in poly.points]
    for i in range(len(pts)):
        p0, p1 = pts[i], pts[(i + 1) % len(pts)]
        el = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        if abs(p0[0] - p1[0]) > 1.0 or el < 50:
            continue
        la0 = (p0[0] - anchor[0], p0[1] - anchor[1])
        la1 = (p1[0] - anchor[0], p1[1] - anchor[1])
        print(
            f"  vert x={p0[0]:.1f} y={min(p0[1], p1[1]):.1f}-{max(p0[1], p1[1]):.1f}"
            f" len={el:.1f} localA={tuple(round(x, 1) for x in la0)}"
            f" localB={tuple(round(x, 1) for x in la1)}"
        )


def main() -> None:
    pipeline = load_kb331_pipeline()
    layermap = pipeline["layermap"]
    res = pipeline["res_list"][6]
    mte_pair = layermap.pair("BAW_MTE")

    ref_path = SRC.parent / "reference_gds" / "KB331_N_01_RTEG1_S3.gds"
    ref_data = extract_reference_rteg_intercepts(ref_path, layermap)
    anchor_ref = ref_data["anchor_center"]
    print("Reference anchor:", anchor_ref)
    print("Reference MTE intercept:", ref_data["mte"])

    flat = gdstk.read_gds(str(ref_path)).top_level()[0].flatten()
    big = [
        p
        for p in flat.polygons
        if (p.layer, p.datatype) == mte_pair and abs(p.area()) > 3000
    ]
    big.sort(key=lambda p: -abs(p.area()))
    print(f"\nReference largest MTE ({len(big)} candidates):")
    for poly in big[:3]:
        print(f"  area={abs(poly.area()):.1f} bb={poly.bounding_box()}")
        vertical_edges(poly, anchor_ref)

    anchor_filter = resonator_anchor_center(res, 0.0, 0.0)
    print("\nFilter anchor:", anchor_filter)
    flib = gdstk.read_gds(str(SRC.parent / "input_files" / "KB331_N_01.gds"))
    fflat = flib.top_level()[0].flatten()
    fbig = [
        p
        for p in fflat.polygons
        if (p.layer, p.datatype) == mte_pair and abs(p.area()) > 3000
    ]
    fbig = [p for p in fbig if p.bounding_box() and p.bounding_box()[0][0] < 300]
    fbig.sort(key=lambda p: abs(p.area()))
    print(f"\nFilter MTE near resonator 6 ({len(fbig)} candidates):")
    for poly in fbig[:5]:
        bb = poly.bounding_box()
        print(f"  area={abs(poly.area()):.1f} bb={bb}")
        vertical_edges(poly, anchor_filter)


if __name__ == "__main__":
    main()
