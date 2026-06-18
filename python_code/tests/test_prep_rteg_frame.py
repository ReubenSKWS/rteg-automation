"""Step 4 — die frame placement and MBE filler right margin."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for p in (str(SRC), str(TESTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from kb331_pipeline import load_kb331_pipeline
from prep_rteg_frame import (
    DEFAULT_RESONATOR_FILLER_RIGHT_MARGIN_UM,
    assembly_placement_origin,
    resonator_filler_right_shift,
)
from rteg_collect import _resonator_rteg_bbox

MARGIN_UM = DEFAULT_RESONATOR_FILLER_RIGHT_MARGIN_UM
WIDE_SHUNT_INDICES = (0, 1)
NARROW_SERIES_INDEX = 2
LEGACY_WIDE_SHUNT_ORIGIN_X = -216.2


def _filler_resonator_gap(assembly, res) -> float:
    (_, _), (filler_x1, _) = assembly.mbe_filler_bbox
    (_, _), (res_x1, _) = _resonator_rteg_bbox(res, assembly)
    return filler_x1 - res_x1


class TestPrepRtegFrameKB331(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pipeline = load_kb331_pipeline()
        cls.res_by_index = {
            i: r for i, r in enumerate(cls.pipeline["res_list"])
        }

    def test_wide_shunt_resonators_keep_filler_right_margin(self) -> None:
        for idx in WIDE_SHUNT_INDICES:
            asm = self.pipeline["frame_assemblies"][idx]
            res = self.res_by_index[idx]
            gap = _filler_resonator_gap(asm, res)
            self.assertGreaterEqual(
                gap,
                MARGIN_UM - 1e-3,
                f"index {idx}: expected >= {MARGIN_UM} µm gap, got {gap:.3f}",
            )

    def test_wide_shunt_ppd_frame_stays_left_aligned(self) -> None:
        for idx in WIDE_SHUNT_INDICES:
            asm = self.pipeline["frame_assemblies"][idx]
            self.assertAlmostEqual(
                asm.assembly_origin[0],
                LEGACY_WIDE_SHUNT_ORIGIN_X,
                places=1,
                msg=f"index {idx}: PPD frame should stay left-aligned",
            )

    def test_wide_shunt_index1_resonator_shifted_left_only(self) -> None:
        asm = self.pipeline["frame_assemblies"][1]
        self.assertLess(
            asm.resonator_frame_shift[0],
            0.0,
            "index 1 resonator should shift left within the PPD frame",
        )
        self.assertAlmostEqual(asm.resonator_frame_shift[1], 0.0, places=6)

    def test_narrow_resonator_unchanged_when_margin_not_binding(self) -> None:
        ppd_assemblies = self.pipeline["ppd_assemblies"]
        content_bb = self.pipeline["frame_assemblies"][0].content_bbox
        content_center = self.pipeline["frame_assemblies"][0].content_center
        ppd_asm = ppd_assemblies[NARROW_SERIES_INDEX]

        origin = assembly_placement_origin(ppd_asm, content_bb, content_center)
        shift_no_margin = resonator_filler_right_shift(
            ppd_asm,
            origin,
            content_bb,
            resonator_filler_right_margin_um=0.0,
        )
        shift_with_margin = resonator_filler_right_shift(
            ppd_asm,
            origin,
            content_bb,
            resonator_filler_right_margin_um=MARGIN_UM,
        )
        self.assertEqual(shift_no_margin, (0.0, 0.0))
        self.assertEqual(shift_with_margin, (0.0, 0.0))


if __name__ == "__main__":
    unittest.main()
