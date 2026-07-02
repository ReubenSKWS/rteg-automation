"""KB331 step 5.3 — preserved filter MTE routing metadata (no lip draw)."""
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
from rteg_collect import collect_geometry_roles
from rteg_mte_extensions import (
    MteBuildConfig,
    MteRtegAssembly,
    build_mte_extensions,
    export_mte_extensions_gds,
    select_extension_collar,
)


class TestSignalMteKB331(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ctx = load_kb331_pipeline()
        except FileNotFoundError:
            raise unittest.SkipTest("KB331 input files not available")
        cls.mte_pair = cls.ctx["layermap"].pair("BAW_MTE")
        cls.cfg = MteBuildConfig()

    def _build(self, index: int):
        asm = self.ctx["frame_assemblies"][index]
        res = self.ctx["res_list"][index]
        roles = collect_geometry_roles(
            asm, res, self.ctx["identification"], self.ctx["layermap"]
        )
        extensions = build_mte_extensions({index: roles}, self.ctx["layermap"], self.cfg)
        return extensions[index], roles

    def test_preserved_collar_metadata_for_all_indices(self):
        for index in range(len(self.ctx["res_list"])):
            result, roles = self._build(index)
            if not roles.preserved.mte:
                self.assertEqual(result.n_extensions, 0)
                continue

            collar = select_extension_collar(
                roles.preserved, roles.resonator_body_mte, self.cfg
            )
            self.assertIsNotNone(collar, msg=f"index {index}")
            assert collar is not None
            self.assertEqual(result.n_extensions, 0)
            self.assertTrue(result.is_connected, msg=f"index {index}")
            self.assertIsNotNone(result.extension)
            self.assertIsNotNone(result.extension_draw)
            assert result.extension is not None
            self.assertEqual(result.extension.points.tolist(), collar.polygon.points.tolist())
            draw = result.extension_draw
            assert draw is not None
            self.assertAlmostEqual(draw.extension_um, 0.0)
            self.assertGreater(draw.mouth_span_um, 0.0)
            self.assertNotEqual(draw.collar_intercept_a, (0.0, 0.0))
            self.assertEqual((result.extension.layer, result.extension.datatype), self.mte_pair)
            self.assertEqual(result.collar, collar)

    def test_golden_shunt_collars_indices0_and_1(self):
        for index in (0, 1):
            result, _roles = self._build(index)
            assert result.extension_draw is not None and result.collar is not None
            self.assertTrue(result.is_connected, msg=f"index {index}")
            self.assertGreater(result.extension_draw.mouth_span_um, 0.0, msg=f"index {index}")

    def test_export_keeps_frame_mte_without_duplicate_lip(self):
        for index in range(len(self.ctx["res_list"])):
            result, roles = self._build(index)
            if not roles.preserved.mte or not result.extension:
                continue
            asm = self.ctx["frame_assemblies"][index]
            frame_mte = [
                p
                for p in asm.flatten().polygons
                if (p.layer, p.datatype) == self.mte_pair
            ]
            export_results = export_mte_extensions_gds(
                [asm],
                {index: result},
                ROOT / "tests" / "_tmp_mte_export",
                layermap=self.ctx["layermap"],
            )
            self.assertEqual(len(export_results), 0, msg=f"index {index}: no new MTE until 5.4")
            flat = MteRtegAssembly(frame=asm, extension=result).flatten()
            export_mte = [
                p for p in flat.polygons if (p.layer, p.datatype) == self.mte_pair
            ]
            self.assertEqual(
                len(export_mte),
                len(frame_mte),
                f"index {index}: export must not duplicate preserved MTE before routing",
            )


if __name__ == "__main__":
    unittest.main()
