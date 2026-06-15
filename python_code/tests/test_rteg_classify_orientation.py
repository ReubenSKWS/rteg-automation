"""KB331 orientation-based classification (step 5.2)."""
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
from rteg_classify import classify_nodes
from rteg_collect import collect_geometry_roles, collect_orientation_inputs


class TestClassifyOrientationKB331(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ctx = load_kb331_pipeline()
        except FileNotFoundError:
            raise unittest.SkipTest("KB331 input files not available")

    def test_kb331_index2_series_opposite_center_is_collar_extend(self):
        ctx = load_kb331_pipeline()
        idx = 2
        roles = collect_geometry_roles(
            ctx["frame_assemblies"][idx],
            ctx["res_list"][idx],
            ctx["identification"],
            ctx["layermap"],
        )
        orientation = collect_orientation_inputs(
            ctx["frame_assemblies"][idx],
            ctx["res_list"][idx],
            ctx["identification"],
            ctx["layermap"],
            ground_plates=roles.ground_plates,
        )
        self.assertEqual(orientation.collar.axis, "east_west")
        self.assertEqual(orientation.collar.mte_route_target, "collar_extend")
        self.assertFalse(orientation.collar.mte_faces_center)

    def test_every_index_orientation_method(self):
        for asm, res in zip(
            self.ctx["frame_assemblies"],
            self.ctx["res_list"],
            strict=True,
        ):
            roles = collect_geometry_roles(
                asm,
                res,
                self.ctx["identification"],
                self.ctx["layermap"],
            )
            orientation = collect_orientation_inputs(
                asm,
                res,
                self.ctx["identification"],
                self.ctx["layermap"],
                ground_plates=roles.ground_plates,
            )
            classification = classify_nodes(
                roles.ground_plates,
                roles.preserved,
                orientation=orientation,
                res_type=res.res_type,
            )
            self.assertEqual(classification.method, "orientation")
            self.assertIn(classification.mte_route_target, ("center_pad", "collar_extend"))
            self.assertIn(classification.signal_terminal, ("MTE", "MBE"))
            self.assertEqual(
                classification.signal_drawable,
                bool(roles.preserved.mte),
            )
            if classification.mte_route_target == "center_pad":
                self.assertTrue(classification.collar_orientation.mte_faces_center)
                self.assertEqual(classification.by_band()["center"].net, "signal")


if __name__ == "__main__":
    unittest.main()
