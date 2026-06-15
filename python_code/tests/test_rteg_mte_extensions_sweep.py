"""KB331 sweep — MTE extensions attach to edge collars without interior fill."""
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
from rteg_collect import collect_geometry_roles, preserved_mte_overlap_with_body
from rteg_mte_extensions import (
    MteBuildConfig,
    _body_centroid,
    _collar_overlap_area,
    build_mte_extensions,
    extension_is_connected,
    find_outward_lip_ab,
    select_extension_collar,
)


class TestMteExtensionsSweep(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ctx = load_kb331_pipeline()
        except FileNotFoundError:
            raise unittest.SkipTest("KB331 input files not available")
        cls.cfg = MteBuildConfig()

    def test_every_resonator_gets_one_extension(self):
        results = build_mte_extensions(
            {
                asm.index: collect_geometry_roles(
                    asm,
                    res,
                    self.ctx["identification"],
                    self.ctx["layermap"],
                )
                for asm, res in zip(
                    self.ctx["frame_assemblies"],
                    self.ctx["res_list"],
                    strict=True,
                )
            },
            self.ctx["layermap"],
            self.cfg,
        )
        for index, result in results.items():
            roles = collect_geometry_roles(
                self.ctx["frame_assemblies"][index],
                self.ctx["res_list"][index],
                self.ctx["identification"],
                self.ctx["layermap"],
            )
            if not roles.preserved.mte:
                continue
            self.assertEqual(
                result.n_extensions,
                1,
                msg=f"index {index}: {getattr(result, 'drc_violations', '')}",
            )
            collar = select_extension_collar(
                roles.preserved, roles.resonator_body_mte, self.cfg
            )
            assert collar is not None
            assert result.extension is not None
            assert result.extension_draw is not None
            self.assertEqual(
                result.is_connected,
                extension_is_connected(
                    result.extension,
                    collar.polygon,
                    result.extension_draw,
                    self.cfg,
                ),
                msg=f"index {index}",
            )

    def test_successful_extensions_attach_with_modest_overlap(self):
        for index in range(len(self.ctx["res_list"])):
            roles = collect_geometry_roles(
                self.ctx["frame_assemblies"][index],
                self.ctx["res_list"][index],
                self.ctx["identification"],
                self.ctx["layermap"],
            )
            if not roles.preserved.mte:
                continue
            result = build_mte_extensions({index: roles}, self.ctx["layermap"], self.cfg)[index]
            self.assertEqual(result.n_extensions, 1, msg=f"index {index}")
            collar = select_extension_collar(
                roles.preserved, roles.resonator_body_mte, self.cfg
            )
            assert collar is not None and result.extension is not None
            overlap = _collar_overlap_area(
                result.extension, collar.polygon, self.cfg.boolean_precision
            )
            self.assertGreaterEqual(overlap, self.cfg.min_collar_overlap_um2, msg=f"index {index}")
            if result.extension_draw is not None:
                for corner, pt, merge in (
                    ("A", result.extension_draw.intercept_a, result.extension_draw.merge_inset_a_um),
                    ("B", result.extension_draw.intercept_b, result.extension_draw.merge_inset_b_um),
                ):
                    if merge < 0.5:
                        continue
                    probe = gdstk.rectangle(
                        (pt[0] - 0.25, pt[1] - 0.25),
                        (pt[0] + 0.25, pt[1] + 0.25),
                    )
                    self.assertTrue(
                        gdstk.boolean(
                            probe, collar.polygon, "and", precision=self.cfg.boolean_precision
                        ),
                        msg=f"index {index}: merge inset {corner} not inside collar",
                    )
            lip = find_outward_lip_ab(collar.polygon, roles.resonator_body_mte, self.cfg)
            body_centroid = _body_centroid(roles.resonator_body_mte)
            mouth_mid = (
                (lip.point_a[0] + lip.point_b[0]) / 2.0,
                (lip.point_a[1] + lip.point_b[1]) / 2.0,
            )
            away = (
                (mouth_mid[0] - body_centroid[0]) * lip.outward_normal[0]
                + (mouth_mid[1] - body_centroid[1]) * lip.outward_normal[1]
            )
            self.assertGreater(away, 0.0, msg=f"index {index}: outward normal wrong")
            self.assertLess(
                overlap / abs(collar.polygon.area()),
                0.99,
                msg=f"index {index}",
            )
            overlapping = [
                tp
                for tp in roles.preserved.mte
                if preserved_mte_overlap_with_body(
                    tp.polygon, roles.resonator_body_mte, precision=self.cfg.boolean_precision
                )
                >= self.cfg.min_collar_overlap_um2
            ]
            if len(overlapping) >= 2:
                self.assertEqual(
                    collar,
                    min(overlapping, key=lambda tp: abs(tp.polygon.area())),
                    msg=f"index {index}",
                )

    def test_index4_selects_edge_collar_not_stadium(self):
        index = 4
        roles = collect_geometry_roles(
            self.ctx["frame_assemblies"][index],
            self.ctx["res_list"][index],
            self.ctx["identification"],
            self.ctx["layermap"],
        )
        collar = select_extension_collar(
            roles.preserved, roles.resonator_body_mte, self.cfg
        )
        assert collar is not None
        self.assertLess(abs(collar.polygon.area()), 3000.0)


if __name__ == "__main__":
    unittest.main()
