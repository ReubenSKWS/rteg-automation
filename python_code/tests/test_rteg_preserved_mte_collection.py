"""KB331 step 5.1 — preserved MTE collar collection (baseline: stadium + touching collar)."""
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
from rteg_collect import RtegCollectConfig, collect_geometry_roles, polys_touch


class TestPreservedMteCollectionKB331(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ctx = load_kb331_pipeline()
        except FileNotFoundError:
            raise unittest.SkipTest("KB331 input files not available")
        cls.collect_cfg = RtegCollectConfig()

    def _roles(self, index: int):
        return collect_geometry_roles(
            self.ctx["frame_assemblies"][index],
            self.ctx["res_list"][index],
            self.ctx["identification"],
            self.ctx["layermap"],
            config=self.collect_cfg,
        )

    def test_known_multi_piece_indices_collect_at_least_two_mte(self):
        for index in (0, 1, 2, 4, 5, 6, 7):
            roles = self._roles(index)
            self.assertGreaterEqual(
                len(roles.preserved.mte),
                2,
                msg=f"index {index}",
            )

    def test_index0_collects_two_small_tabs_without_stadium(self):
        roles = self._roles(0)
        areas = sorted(abs(tp.polygon.area()) for tp in roles.preserved.mte)
        self.assertEqual(len(areas), 2)
        self.assertLess(max(areas), self.collect_cfg.stadium_collar_area_um2)

    def test_index6_golden_baseline_collection(self):
        """Index 6 baseline: exactly stadium [5191] + collar [911], touching."""
        roles = self._roles(6)
        areas = sorted(round(tp.area_um2) for tp in roles.preserved.mte)
        self.assertEqual(areas, [911, 5191])
        stadium = max(roles.preserved.mte, key=lambda tp: tp.area_um2)
        collar = min(roles.preserved.mte, key=lambda tp: tp.area_um2)
        self.assertTrue(polys_touch(stadium.polygon, collar.polygon, precision=1e-3))

    def test_indices6_and_7_collect_stadium_and_touching_collar(self):
        expected_collar = {6: 911, 7: 1245}
        for index in (6, 7):
            roles = self._roles(index)
            areas = sorted(round(tp.area_um2) for tp in roles.preserved.mte)
            self.assertEqual(len(areas), 2, msg=f"index {index}")
            self.assertIn(5191, areas, msg=f"index {index}")
            self.assertIn(
                expected_collar[index],
                areas,
                msg=f"index {index}",
            )
            stadium = max(roles.preserved.mte, key=lambda tp: tp.area_um2)
            collar = min(roles.preserved.mte, key=lambda tp: tp.area_um2)
            self.assertTrue(
                polys_touch(stadium.polygon, collar.polygon, precision=1e-3),
                msg=f"index {index}: collar must touch stadium",
            )

    def test_index4_keeps_connectmte_bus_in_preserved_for_npi(self):
        roles = self._roles(4)
        areas = sorted(round(tp.area_um2) for tp in roles.preserved.mte)
        self.assertIn(2096, areas)
        self.assertIn(5191, areas)


if __name__ == "__main__":
    unittest.main()
