"""Tests for step 2.4 original-die collar intercept capture."""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
TESTS = Path(__file__).resolve().parents[1] / "tests"
for p in (str(SRC), str(TESTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from kb331_pipeline import load_kb331_pipeline
from rteg_collect import _resonator_shift
from rteg_die_intercepts import (
    DieRoutingContext,
    _world_to_body_local,
    collect_die_collar_intercepts,
    detect_probe_facing_side,
    die_intercept_rows,
    merge_resonator_intercept_rows,
    mouth_hits_for_pad,
    resonator_anchor_center,
    transform_local_intercept_to_rteg,
    transform_point_to_rteg,
)
from prep_resonator_ppd import resonator_metal_polys
from rteg_utils import polys_bbox
from rteg_collect import collect_filter_die_collar_metal, RtegCollectConfig
from rteg_classify import classify_nodes
from rteg_collect import collect_geometry_roles, collect_orientation_inputs
from rteg_mbe_body_center_pad import build_mbe_body_center_pads
from rteg_mbe_extensions import MbeConnectionConfig, build_mbe_extensions
from rteg_mte_extensions import MteBuildConfig, build_mte_extensions

RES6_GOLDEN = {
    "mte": ((224.0, 235.0), (196.0, 341.0)),
    "mbe": ((221.0, 335.0), (274.0, 244.0)),
}
RES6_TOL = {"mte": (10.0, 12.0), "mbe": (8.0, 8.0)}

RES1_GOLDEN = {
    "mte": ((205.0, 239.0), (290.0, 253.0)),
    "mbe": ((176.0, 174.0), (318.0, 258.0)),
}
RES1_TOL = {"mte": (16.0, 32.0), "mbe": (10.0, 28.0)}

RES3_GOLDEN = {
    "mte": ((216.0, 332.0), (175.0, 350.0)),
    "mbe": ((218.0, 386.0), (236.0, 332.0)),
}
RES3_TOL = {"mte": (8.0, 8.0), "mbe": (160.0, 28.0)}


class TestDieCollarInterceptsKB331(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not (SRC.parent / "input_files" / "KB331_N_01.gds").is_file():
            raise unittest.SkipTest("KB331 input GDS not available")
        cls.pipeline = load_kb331_pipeline()
        cls.identification = cls.pipeline["identification"]
        cls.layermap = cls.pipeline["layermap"]
        cls.frame_assemblies = cls.pipeline["frame_assemblies"]
        cls.res_list = cls.pipeline["res_list"]
        cls.collection = collect_die_collar_intercepts(
            cls.identification, cls.layermap
        )

    def test_all_resonators_ok_on_both_layers(self) -> None:
        self.assertEqual(len(self.collection.items), 8)
        for item in self.collection.items:
            self.assertIsNotNone(item.mte)
            self.assertIsNotNone(item.mbe)
            self.assertEqual(item.mte.status, "ok", msg=f"index {item.index} MTE")
            self.assertEqual(item.mbe.status, "ok", msg=f"index {item.index} MBE")

    def test_index6_filter_die_intercepts_match_golden(self) -> None:
        """Golden coords are filter-die world frame from reference layout."""
        self._assert_golden_intercepts(6, RES6_GOLDEN, RES6_TOL)

    def test_index1_filter_die_intercepts_match_golden(self) -> None:
        """Shunt @ 180° — probe-facing top; geometry limits MTE y to ~223 µm bus."""
        self._assert_golden_intercepts(1, RES1_GOLDEN, RES1_TOL)

    def test_index3_filter_die_intercepts_match_golden(self) -> None:
        """Series @ 270° — MTE mouth on upper collar lip; MBE A may sit off connect metal."""
        self._assert_golden_intercepts(3, RES3_GOLDEN, RES3_TOL)

    def test_index3_intercepts_are_body_local_not_world_offset(self) -> None:
        item = self.collection.get(3)
        assert item is not None and item.mte is not None
        res = self.res_list[3]
        anchor = resonator_anchor_center(res, 0.0, 0.0)
        assert item.mte.intercept_a is not None and item.mte.intercept_a_local is not None
        expected = _world_to_body_local(
            item.mte.intercept_a, anchor, res.rotation
        )
        self.assertAlmostEqual(item.mte.intercept_a_local[0], expected[0], places=2)
        self.assertAlmostEqual(item.mte.intercept_a_local[1], expected[1], places=2)
        self.assertNotAlmostEqual(
            item.mte.intercept_a_local[0],
            item.mte.intercept_a[0] - anchor[0],
            places=0,
        )

    def test_index1_probe_side_is_top(self) -> None:
        cfg = RtegCollectConfig()
        res = self.res_list[1]
        metal_bb = polys_bbox(resonator_metal_polys(res, 0.0, 0.0))
        assert metal_bb is not None
        preserved = collect_filter_die_collar_metal(
            res, self.identification, self.layermap, cfg
        )
        mte_polys = [tp.polygon for tp in preserved.mte]
        mbe_polys = [tp.polygon for tp in preserved.mbe]
        self.assertEqual(detect_probe_facing_side(metal_bb, mte_polys), "top")
        self.assertEqual(detect_probe_facing_side(metal_bb, mbe_polys), "top")

    def test_index6_probe_side_is_left(self) -> None:
        cfg = RtegCollectConfig()
        res = self.res_list[6]
        metal_bb = polys_bbox(resonator_metal_polys(res, 0.0, 0.0))
        assert metal_bb is not None
        preserved = collect_filter_die_collar_metal(
            res, self.identification, self.layermap, cfg
        )
        mte_polys = [tp.polygon for tp in preserved.mte]
        mbe_polys = [tp.polygon for tp in preserved.mbe]
        self.assertEqual(detect_probe_facing_side(metal_bb, mte_polys), "left")
        self.assertEqual(detect_probe_facing_side(metal_bb, mbe_polys), "left")

    def _assert_golden_intercepts(
        self,
        index: int,
        golden: dict[str, tuple[tuple[float, float], tuple[float, float]]],
        tol: dict[str, tuple[float, float]],
    ) -> None:
        item = self.collection.get(index)
        assert item is not None
        for layer_name in ("mte", "mbe"):
            layer = item.mte if layer_name == "mte" else item.mbe
            assert layer is not None
            self.assertEqual(layer.status, "ok")
            self.assertEqual(layer.source, "geometry")
            golden_a, golden_b = golden[layer_name]
            tol_a, tol_b = tol[layer_name]
            assert layer.intercept_a is not None and layer.intercept_b is not None
            da_a = math.hypot(
                layer.intercept_a[0] - golden_a[0],
                layer.intercept_a[1] - golden_a[1],
            )
            da_b = math.hypot(
                layer.intercept_a[0] - golden_b[0],
                layer.intercept_a[1] - golden_b[1],
            )
            db_a = math.hypot(
                layer.intercept_b[0] - golden_a[0],
                layer.intercept_b[1] - golden_a[1],
            )
            db_b = math.hypot(
                layer.intercept_b[0] - golden_b[0],
                layer.intercept_b[1] - golden_b[1],
            )
            if da_a + db_b <= da_b + db_a:
                da, db = da_a, db_b
            else:
                da, db = da_b, db_a
            self.assertLessEqual(
                da,
                tol_a,
                msg=f"idx{index} {layer_name} A {layer.intercept_a} vs {golden_a} d={da:.2f}",
            )
            self.assertLessEqual(
                db,
                tol_b,
                msg=f"idx{index} {layer_name} B {layer.intercept_b} vs {golden_b} d={db:.2f}",
            )

    def test_index6_and_7_mte_intercepts_differ(self) -> None:
        mte6 = self.collection.get(6).mte
        mte7 = self.collection.get(7).mte
        assert mte6 is not None and mte7 is not None
        self.assertNotEqual(mte6.intercept_a, mte7.intercept_a)
        self.assertNotEqual(mte6.intercept_b, mte7.intercept_b)

    def test_local_intercepts_have_anchor_center(self) -> None:
        for item in self.collection.items:
            for layer in (item.mte, item.mbe):
                assert layer is not None
                self.assertEqual(layer.status, "ok")
                self.assertIsNotNone(layer.anchor_center)
                self.assertIsNotNone(layer.intercept_a_local)
                self.assertIsNotNone(layer.intercept_b_local)

    def test_die_routing_transforms_local_intercepts(self) -> None:
        die_routing = DieRoutingContext.from_lists(
            self.collection,
            self.res_list,
            self.frame_assemblies,
        )
        idx = 6
        die_mte = self.collection.get(idx).mte
        lip = die_routing.lip(idx, "mte")
        self.assertIsNotNone(die_mte)
        self.assertIsNotNone(lip)
        assert die_mte is not None and lip is not None
        local_pts = transform_local_intercept_to_rteg(
            die_mte, self.res_list[idx], self.frame_assemblies[idx]
        )
        assert local_pts is not None
        self.assertAlmostEqual(local_pts[0][0], lip.point_a[0], places=2)
        self.assertAlmostEqual(local_pts[0][1], lip.point_a[1], places=2)

    def test_steps_5_6_extensions_hit_die_intercepts(self) -> None:
        """MTE/MBE routing uses RTEG-frame mouth targets when die_routing is passed."""
        all_roles: dict = {}
        all_classify: dict = {}
        for asm, res in zip(
            self.frame_assemblies,
            self.res_list,
            strict=True,
        ):
            roles = collect_geometry_roles(
                asm, res, self.identification, self.layermap
            )
            orientation = collect_orientation_inputs(
                asm,
                res,
                self.identification,
                self.layermap,
                ground_plates=roles.ground_plates,
            )
            all_roles[asm.index] = roles
            all_classify[asm.index] = classify_nodes(
                roles.ground_plates,
                roles.preserved,
                orientation=orientation,
                res_type=res.res_type,
            )

        die_routing = DieRoutingContext.from_rteg_roles(
            all_roles,
            all_classify,
            self.layermap,
            res_list=self.res_list,
            assemblies=self.frame_assemblies,
            identification=self.identification,
            die_intercepts=self.collection,
        )
        all_mte = build_mte_extensions(
            all_roles,
            self.layermap,
            MteBuildConfig(),
            die_routing=die_routing,
        )
        for idx in (0, 3, 6):
            lip = die_routing.lip(idx, "mte")
            draw = all_mte[idx].extension_draw
            assert lip is not None and draw is not None
            for got, label in (
                (draw.collar_intercept_a, "A"),
                (draw.collar_intercept_b, "B"),
            ):
                exp = lip.point_a if label == "A" else lip.point_b
                d = math.hypot(got[0] - exp[0], got[1] - exp[1])
                tol = 15.0 if idx == 0 else 9.0
                self.assertLessEqual(
                    d,
                    tol,
                    msg=f"idx{idx} MTE {label} collar intercept d={d:.2f}",
                )

        all_mbe = build_mbe_extensions(
            all_roles,
            all_classify,
            self.layermap,
            MbeConnectionConfig(),
            die_routing=die_routing,
        )
        for idx in (0, 2, 5, 7):
            mouth = die_routing.collar_mouth(idx, "mbe")
            draw = all_mbe[idx].connection_draw
            assert mouth is not None and draw is not None
            exp_a, exp_b = mouth_hits_for_pad(mouth[0], mouth[1])
            for got, exp, label in (
                (draw.hit_a, exp_a, "A"),
                (draw.hit_b, exp_b, "B"),
            ):
                d = math.hypot(got[0] - exp[0], got[1] - exp[1])
                self.assertLessEqual(
                    d,
                    9.0,
                    msg=f"idx{idx} MBE hit {label} d={d:.2f}",
                )

    def test_local_transform_differs_from_origin_shift_when_centers_diverge(self) -> None:
        idx = 6
        die_mte = self.collection.get(idx).mte
        res = self.res_list[idx]
        asm = self.frame_assemblies[idx]
        assert die_mte is not None and die_mte.intercept_a is not None
        filter_center = resonator_anchor_center(res, 0.0, 0.0)
        shift = _resonator_shift(res, asm)
        rteg_center = resonator_anchor_center(res, shift[0], shift[1])
        center_delta = (
            rteg_center[0] - filter_center[0],
            rteg_center[1] - filter_center[1],
        )
        local_pts = transform_local_intercept_to_rteg(die_mte, res, asm)
        assert local_pts is not None
        origin_a = transform_point_to_rteg(die_mte.intercept_a, res, asm)
        if abs(center_delta[0] - shift[0]) > 0.01 or abs(center_delta[1] - shift[1]) > 0.01:
            self.assertNotAlmostEqual(local_pts[0][0], origin_a[0], places=1)

    def test_merge_rows_align_with_step23_index(self) -> None:
        merged = merge_resonator_intercept_rows(
            self.identification,
            self.layermap,
            die_intercepts=self.collection,
        )
        self.assertEqual(len(merged), 8)
        for row in merged:
            self.assertIn("mte_intercept_a", row)
            self.assertIn("mbe_entry_angle_deg", row)

    def test_die_intercept_rows_shape(self) -> None:
        rows = die_intercept_rows(self.collection)
        self.assertEqual(len(rows), 8)
        self.assertIn("mte_status", rows[0])
        self.assertIn("mbe_status", rows[0])


if __name__ == "__main__":
    unittest.main()
