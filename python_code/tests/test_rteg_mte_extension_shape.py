"""Step 6.2 — preserved MTE extension simplification."""
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

    def test_index7_is_five_point_right_angle(self):
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

        mte_pair = self.ctx["layermap"].pair("BAW_MTE")
        cell = MteRtegAssembly(
            self.ctx["frame_assemblies"][index],
            mte,
            layermap=self.ctx["layermap"],
            mbe_extension=self.all_mbe[index],
            mbe_body=self.all_body[index],
        ).flatten()
        ext_polys = [
            p
            for p in cell.polygons
            if (p.layer, p.datatype) == mte_pair and len(p.points) <= 8
        ]
        compact = [p for p in ext_polys if len(p.points) == 5]
        self.assertTrue(compact, msg="expected 5-vertex reshaped extension in export")
        wild = [p for p in cell.polygons if (p.layer, p.datatype) == mte_pair and len(p.points) > 20 and abs(p.area()) < 2000]
        self.assertFalse(wild, msg="wild extension stub should be stripped from export")

    def test_collar_extend_produces_reshaped_extension(self):
        for index in COLLAR_EXTEND_INDICES:
            body = self.all_body[index]
            self.assertIsNotNone(body.mte_extension, msg=f"index {index}")
            self.assertLessEqual(
                len(body.mte_extension.points),
                8,
                msg=f"index {index}: expected compact polygon",
            )


if __name__ == "__main__":
    unittest.main()
