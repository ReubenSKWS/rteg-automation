"""Step 6.2 export contracts and optional MTE extension reshape helpers."""
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
from rteg_collect import (
    _polygon_key,
    attach_preserved_filter_interconnect,
    collect_geometry_roles,
    collect_orientation_inputs,
)
from rteg_mbe_body import MbeBodyConfig, build_mbe_body_collar_extends
from rteg_mbe_extensions import MbeConnectionConfig, build_mbe_extensions
from rteg_mte_route import identify_preserved_mte_parts
from rteg_mte_extension_shape import simplify_mte_extension
from rteg_mte_extensions import MteBuildConfig, MteRtegAssembly, build_mte_extensions

COLLAR_EXTEND_INDICES = (0, 2, 5, 7)


class TestMteExtensionSimplify(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = load_kb331_pipeline()
        cls.all_roles: dict[int, object] = {}
        cls.all_classify: dict[int, object] = {}
        for asm, res in zip(
            cls.ctx["frame_assemblies"],
            cls.ctx["res_list"],
            strict=True,
        ):
            roles = collect_geometry_roles(
                asm, res, cls.ctx["identification"], cls.ctx["layermap"]
            )
            orientation = collect_orientation_inputs(
                asm,
                res,
                cls.ctx["identification"],
                cls.ctx["layermap"],
                ground_plates=roles.ground_plates,
            )
            cls.all_roles[asm.index] = roles
            cls.all_classify[asm.index] = classify_nodes(
                roles.ground_plates,
                roles.preserved,
                orientation=orientation,
                res_type=res.res_type,
            )
        cls.all_mte = build_mte_extensions(cls.all_roles, cls.ctx["layermap"], MteBuildConfig())
        cls.all_mbe = build_mbe_extensions(
            cls.all_roles,
            cls.all_classify,
            cls.ctx["layermap"],
            MbeConnectionConfig(),
        )
        cls.all_body = build_mbe_body_collar_extends(
            cls.all_roles,
            cls.all_classify,
            cls.all_mte,
            cls.all_mbe,
            cls.ctx["layermap"],
            MbeBodyConfig(),
        )

    def test_index7_simplify_mte_extension_unit(self):
        """``simplify_mte_extension`` remains available but is not used in 6.2 export."""
        index = 7
        roles = self.all_roles[index]
        mte = self.all_mte[index]
        assert mte.extension is not None and mte.extension_draw is not None
        parts = identify_preserved_mte_parts(
            [tp.polygon for tp in roles.preserved.mte],
            roles.resonator_body_mte,
            boolean_precision=1e-3,
        )
        simplified, violations = simplify_mte_extension(
            mte.extension,
            roles.resonator_body_mte,
            self.ctx["layermap"],
            extension_draw=mte.extension_draw,
            preserved_parts=parts,
        )
        self.assertIsNotNone(simplified, msg=violations)
        assert simplified is not None
        self.assertLessEqual(len(simplified.points), 6, msg="expected ~5 vertices, not jagged chain")
        self.assertGreaterEqual(len(simplified.points), 4)

        pts = [(float(p[0]), float(p[1])) for p in simplified.points]
        leg_mouth, corner, leg_far = pts[2], pts[3], pts[4]
        self.assertAlmostEqual(leg_far[0], corner[0], places=1)
        self.assertAlmostEqual(corner[1], leg_mouth[1], places=1)
        self.assertGreater(leg_far[0], 300.0)
        self.assertGreater(leg_mouth[1], 315.0)

    def test_collar_extend_export_leaves_mte_unchanged(self):
        mte_pair = self.ctx["layermap"].pair("BAW_MTE")
        for index in COLLAR_EXTEND_INDICES:
            frame_asm = self.ctx["frame_assemblies"][index]
            res = self.ctx["res_list"][index]
            attach_preserved_filter_interconnect(
                frame_asm,
                res,
                self.ctx["identification"],
                self.ctx["layermap"],
            )
            mte_only = MteRtegAssembly(
                frame_asm,
                self.all_mte[index],
                layermap=self.ctx["layermap"],
                mbe_extension=self.all_mbe[index],
                mbe_body=None,
            ).flatten()
            full = MteRtegAssembly(
                frame_asm,
                self.all_mte[index],
                layermap=self.ctx["layermap"],
                mbe_extension=self.all_mbe[index],
                mbe_body=self.all_body[index],
            ).flatten()

            def mte_keys(cell: object) -> set[tuple[float, ...]]:
                return {
                    _polygon_key(p)
                    for p in cell.polygons
                    if (p.layer, p.datatype) == mte_pair
                }

            self.assertEqual(
                mte_keys(mte_only),
                mte_keys(full),
                msg=f"index {index}: step 6.2 must not add or remove MTE polygons",
            )

    def test_collar_extend_export_preserves_mte_collar(self):
        mte_pair = self.ctx["layermap"].pair("BAW_MTE")
        for index in COLLAR_EXTEND_INDICES:
            frame_asm = self.ctx["frame_assemblies"][index]
            res = self.ctx["res_list"][index]
            attach_preserved_filter_interconnect(
                frame_asm,
                res,
                self.ctx["identification"],
                self.ctx["layermap"],
            )
            asm = MteRtegAssembly(
                frame_asm,
                self.all_mte[index],
                layermap=self.ctx["layermap"],
                mbe_extension=self.all_mbe[index],
                mbe_body=self.all_body[index],
            )
            keepers = asm._preserved_mte_collar_keepers()
            if not keepers:
                continue
            cell = asm.flatten()
            mte_polys = [
                p for p in cell.polygons if (p.layer, p.datatype) == mte_pair
            ]
            self.assertTrue(
                any(asm._polygon_matches_any(p, keepers) for p in mte_polys),
                msg=f"index {index}: preserved MTE collar missing from export",
            )

    def test_collar_extend_does_not_store_fabricated_mte(self):
        for index in COLLAR_EXTEND_INDICES:
            body = self.all_body[index]
            self.assertIsNone(
                body.mte_extension,
                msg=f"index {index}: step 6.2 must not replace filter MTE",
            )


if __name__ == "__main__":
    unittest.main()
