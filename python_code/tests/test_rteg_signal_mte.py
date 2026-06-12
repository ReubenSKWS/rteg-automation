"""KB331 step 5.3 — preserved MTE collar extensions."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import gdstk

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for p in (str(SRC), str(TESTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from kb331_pipeline import load_kb331_pipeline
from rteg_collect import collect_geometry_roles, select_preserved_collar_mte
from rteg_signal import SignalBuildConfig, build_mte_extensions, build_signal_rteg_assemblies


class TestSignalMteKB331(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ctx = load_kb331_pipeline()
        except FileNotFoundError:
            raise unittest.SkipTest("KB331 input files not available")
        cls.mte_pair = cls.ctx["layermap"].pair("BAW_MTE")

    def _build(self, index: int):
        asm = self.ctx["frame_assemblies"][index]
        res = self.ctx["res_list"][index]
        roles = collect_geometry_roles(
            asm, res, self.ctx["identification"], self.ctx["layermap"]
        )
        extensions = build_mte_extensions({index: roles}, self.ctx["layermap"], SignalBuildConfig())
        return extensions[index], roles

    def test_one_extension_from_collar_overlapping_body(self):
        for index in range(len(self.ctx["res_list"])):
            signal, roles = self._build(index)
            if not roles.preserved.mte:
                self.assertEqual(signal.net_polygons, [])
                self.assertEqual(signal.connector.shape_name, "none")
                continue

            collar = select_preserved_collar_mte(
                roles.preserved, roles.resonator_body_mte
            )
            if collar is None:
                self.assertEqual(signal.net_polygons, [])
                continue

            self.assertEqual(signal.connector.shape_name, "collar_extend")
            self.assertLessEqual(len(signal.net_polygons), 1)
            self.assertEqual(len(signal.net_polygons), 1)
            ext = signal.net_polygons[0]
            self.assertTrue(
                gdstk.boolean(ext, collar.polygon, "and", precision=1e-3),
                f"index {index}: extension must overlap selected collar",
            )
            self.assertGreaterEqual(
                abs(ext.area()),
                collar.area_um2,
                f"index {index}: draw should follow/extend collar footprint",
            )
            self.assertEqual((ext.layer, ext.datatype), self.mte_pair)
            self.assertGreater(abs(ext.area()), 0.0)
            self.assertEqual(signal.endpoints.preserved.label, collar.label)

    def test_export_keeps_frame_mte_and_adds_extensions(self):
        from rteg_signal import build_signal_rteg_assemblies

        for index in range(len(self.ctx["res_list"])):
            signal, roles = self._build(index)
            if not roles.preserved.mte or not signal.net_polygons:
                continue
            asm = self.ctx["frame_assemblies"][index]
            frame_mte = [
                p
                for p in asm.flatten().polygons
                if (p.layer, p.datatype) == self.mte_pair
            ]
            sra = build_signal_rteg_assemblies([asm], {index: signal})[0]
            export_mte = [
                p
                for p in sra.flatten().polygons
                if (p.layer, p.datatype) == self.mte_pair
            ]
            self.assertGreaterEqual(
                len(export_mte),
                len(frame_mte) + len(signal.net_polygons),
                f"index {index}: export must keep frame MTE and add extensions",
            )


if __name__ == "__main__":
    unittest.main()
