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
from rteg_mte_extensions import (
    MteBuildConfig,
    MteRtegAssembly,
    _collar_overlap_area,
    build_mte_extensions,
    export_mte_extensions_gds,
    extension_is_connected,
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

    def test_one_extension_from_collar_overlapping_body(self):
        for index in range(len(self.ctx["res_list"])):
            result, roles = self._build(index)
            if not roles.preserved.mte:
                self.assertEqual(result.n_extensions, 0)
                continue

            collar = select_extension_collar(
                roles.preserved, roles.resonator_body_mte, self.cfg
            )
            if collar is None or result.n_extensions == 0:
                continue

            self.assertEqual(result.n_extensions, 1)
            ext = result.extension
            assert ext is not None
            draw = result.extension_draw
            assert draw is not None
            connected = extension_is_connected(
                ext, collar.polygon, draw, self.cfg
            )
            self.assertEqual(
                result.is_connected,
                connected,
                f"index {index}: is_connected must match extension_is_connected",
            )
            if result.is_connected:
                self.assertTrue(
                    gdstk.boolean(ext, collar.polygon, "and", precision=1e-3),
                    f"index {index}: extension must overlap selected collar",
                )
                overlap = _collar_overlap_area(
                    ext, collar.polygon, self.cfg.boolean_precision
                )
                self.assertGreaterEqual(overlap, self.cfg.min_collar_overlap_um2)
                self.assertGreaterEqual(
                    overlap / abs(ext.area()),
                    self.cfg.min_connection_overlap_fraction,
                )
                collar_area = abs(collar.polygon.area())
                min_merge_req = (
                    self.cfg.min_connection_merge_um
                    if collar_area < 700.0
                    else self.cfg.min_merge_inset_check_um * 0.6
                )
                self.assertGreaterEqual(
                    min(draw.merge_inset_a_um, draw.merge_inset_b_um),
                    min_merge_req,
                )
            self.assertAlmostEqual(
                result.collar_overlap_um2,
                _collar_overlap_area(ext, collar.polygon, self.cfg.boolean_precision),
                places=2,
            )
            self.assertLess(
                result.collar_overlap_um2 / abs(collar.polygon.area()),
                0.99,
            )
            self.assertEqual((ext.layer, ext.datatype), self.mte_pair)
            self.assertEqual(result.collar, collar)

    def test_golden_shunt_collars_indices0_and_1(self):
        for index in (0, 1):
            result, roles = self._build(index)
            assert result.extension_draw is not None and result.collar is not None
            collar_area = abs(result.collar.polygon.area())
            self.assertLess(collar_area, 700.0, msg=f"index {index}")
            cbb = result.collar.polygon.bounding_box()
            collar_width = max(cbb[1][0] - cbb[0][0], cbb[1][1] - cbb[0][1])
            mouth_coverage = result.extension_draw.mouth_span_um / collar_width
            self.assertGreaterEqual(
                mouth_coverage,
                self.cfg.min_mouth_coverage_shunt_fraction,
                msg=f"index {index}",
            )
            self.assertTrue(result.is_connected, msg=f"index {index}")

    def test_export_keeps_frame_mte_and_adds_extensions(self):
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
            self.assertEqual(len(export_results), 1)
            flat = MteRtegAssembly(frame=asm, extension=result).flatten()
            export_mte = [
                p for p in flat.polygons if (p.layer, p.datatype) == self.mte_pair
            ]
            self.assertGreaterEqual(
                len(export_mte),
                len(frame_mte) + result.n_extensions,
                f"index {index}: export must keep frame MTE and add extensions",
            )


if __name__ == "__main__":
    unittest.main()
