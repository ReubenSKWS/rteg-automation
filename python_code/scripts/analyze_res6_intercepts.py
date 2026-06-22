"""Compare filter-die vs reference RTEG intercepts for resonator 6 (S3)."""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parents[1] / "tests"
for p in (str(SRC), str(TESTS)):
    sys.path.insert(0, p)

from kb331_pipeline import load_kb331_pipeline
from rteg_collect import _resonator_shift
from rteg_die_intercepts import (
    collect_die_collar_intercepts,
    compare_filter_reference_locals,
    extract_reference_rteg_intercepts,
    resonator_anchor_center,
    transform_local_intercept_to_rteg,
    transform_point_to_rteg,
)


def main() -> None:
    root = SRC.parent
    p = load_kb331_pipeline()
    ident, lm, asm, res = (
        p["identification"],
        p["layermap"],
        p["frame_assemblies"],
        p["res_list"],
    )
    coll = collect_die_collar_intercepts(ident, lm)
    idx = 6
    item = coll.get(idx)
    res6 = res[idx]
    asm6 = asm[idx]
    ref_path = root / "reference_gds" / "KB331_N_01_RTEG1_S3.gds"
    ref = extract_reference_rteg_intercepts(ref_path, lm)

    fc = resonator_anchor_center(res6, 0.0, 0.0)
    shift = _resonator_shift(res6, asm6)
    rc = resonator_anchor_center(res6, shift[0], shift[1])
    print("=== Resonator 6 placement ===")
    print(f"filter anchor center: {fc}")
    print(f"rteg anchor center:   {rc}")
    print(f"origin shift:         {shift}")
    print(f"center delta:         ({rc[0]-fc[0]:.3f}, {rc[1]-fc[1]:.3f})")

    mte = item.mte
    assert mte is not None
    print("\n=== Filter die MTE (world + local) ===")
    print(f"A world: {mte.intercept_a}  local: {mte.intercept_a_local}")
    print(f"B world: {mte.intercept_b}  local: {mte.intercept_b_local}")
    print(
        f"span: {mte.mouth_span_um} um  angle: {mte.mouth_angle_deg} deg"
        f"  area: {mte.collar_area_um2}"
    )

    mbe = item.mbe
    assert mbe is not None
    print("\n=== Filter die MBE ===")
    print(f"A world: {mbe.intercept_a}  local: {mbe.intercept_a_local}")
    print(f"B world: {mbe.intercept_b}  local: {mbe.intercept_b_local}")
    print(f"span: {mbe.mouth_span_um} um  area: {mbe.collar_area_um2}")

    print("\n=== Reference RTEG S3 ===")
    print(f"anchor: {ref['anchor_center']}")
    for layer in ("mte", "mbe"):
        r = ref[layer]
        if r:
            print(f"{layer.upper()}: A={r['intercept_a']} B={r['intercept_b']}")
            la = tuple(round(x, 2) for x in r["intercept_a_local"])
            lb = tuple(round(x, 2) for x in r["intercept_b_local"])
            print(f"  local A={la} B={lb}")
            print(f"  span={r['mouth_span_um']} area={r['polygon_area_um2']}")

    local = transform_local_intercept_to_rteg(mte, res6, asm6)
    assert local is not None and mte.intercept_a is not None
    orig_a = transform_point_to_rteg(mte.intercept_a, res6, asm6)
    print("\n=== RTEG transform comparison (MTE) ===")
    print(f"local transform A: {tuple(round(x, 2) for x in local[0])}")
    print(f"origin shift A:    {tuple(round(x, 2) for x in orig_a)}")
    print(
        f"delta local vs origin: ({local[0][0]-orig_a[0]:.3f},"
        f" {local[0][1]-orig_a[1]:.3f})"
    )

    for layer in ("mte", "mbe"):
        cmp = compare_filter_reference_locals(item, ref, layer=layer)
        print(f"\n=== Filter vs reference local ({layer}) ===")
        for k, v in cmp.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
