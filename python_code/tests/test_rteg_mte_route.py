"""Step 5.4 — MTE pad routing from 5.3 extensions."""
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
from rteg_classify import classify_nodes
from rteg_collect import collect_geometry_roles, collect_orientation_inputs
from rteg_mte_extensions import MteBuildConfig, build_mte_extensions
from rteg_mte_route import (
    MteRouteConfig,
    build_corridor_route,
    build_mte_pad_route,
    build_mte_pad_routes,
    pick_pad_entry,
    pick_route_start,
    union_mte_net,
)


class TestMteRouteSynthetic(unittest.TestCase):
    def test_straight_corridor_reaches_pad(self):
        cfg = MteRouteConfig()
        route, waypoints = build_corridor_route(
            (50.0, 50.0),
            (10.0, 50.0),
            6.0,
            [],
            5,
            0,
            cfg,
        )
        pad = gdstk.rectangle((0.0, 40.0), (12.0, 60.0), layer=2, datatype=0)
        entry = pick_pad_entry([pad], (50.0, 50.0), touch_overlap_um=0.5)
        self.assertLess(entry[0], 12.0)
        self.assertGreaterEqual(len(waypoints), 2)
        inter = gdstk.boolean(route, pad, "and", precision=cfg.boolean_precision)
        self.assertTrue(inter)
        self.assertGreater(sum(abs(p.area()) for p in inter), 0.01)

    def test_union_covers_extension_and_route(self):
        ext = gdstk.rectangle((40.0, 47.0), (60.0, 53.0), layer=5, datatype=0)
        cfg = MteRouteConfig()
        route, _ = build_corridor_route(
            (50.0, 50.0), (15.0, 50.0), 6.0, [], 5, 0, cfg
        )
        net = union_mte_net(ext, route, precision=cfg.boolean_precision)
        self.assertTrue(gdstk.boolean(net, ext, "and", precision=cfg.boolean_precision))
        self.assertTrue(gdstk.boolean(net, route, "and", precision=cfg.boolean_precision))


class TestMteRouteKB331(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ctx = load_kb331_pipeline()
        except FileNotFoundError:
            raise unittest.SkipTest("KB331 input files not available")
        cls.mte_cfg = MteBuildConfig()
        cls.route_cfg = MteRouteConfig()
        cls.all_roles: dict = {}
        cls.all_classify: dict = {}
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
            classification = classify_nodes(
                roles.ground_plates,
                roles.preserved,
                orientation=orientation,
                res_type=res.res_type,
            )
            cls.all_roles[asm.index] = roles
            cls.all_classify[asm.index] = classification
        cls.extensions = build_mte_extensions(
            cls.all_roles, cls.ctx["layermap"], cls.mte_cfg
        )
        cls.routed = build_mte_pad_routes(
            cls.all_roles,
            cls.all_classify,
            cls.extensions,
            cls.ctx["layermap"],
            cls.route_cfg,
        )

    def test_center_pad_indices_routed(self):
        for index in (4, 6):
            result = self.routed[index]
            classification = self.all_classify[index]
            self.assertEqual(classification.mte_route_target, "center_pad")
            self.assertTrue(classification.collar_orientation.mte_faces_center)
            self.assertIsNotNone(result.route_draw)
            self.assertIsNotNone(result.routed_net)
            assert result.route_draw is not None
            self.assertGreaterEqual(
                result.route_draw.pad_overlap_um2,
                self.route_cfg.min_pad_overlap_um2,
            )
            pads = [tp.polygon for tp in classification.signal_polygons()]
            self.assertTrue(
                gdstk.boolean(
                    result.routed_net, pads, "and", precision=self.route_cfg.boolean_precision
                )
            )

    def test_collar_extend_indices_unchanged(self):
        for index in (0, 1, 2, 3, 5, 7):
            base = self.extensions[index]
            result = self.routed[index]
            self.assertEqual(self.all_classify[index].mte_route_target, "collar_extend")
            self.assertIsNone(result.route_draw)
            self.assertIsNone(result.routed_net)
            self.assertEqual(result.extension, base.extension)

    def test_pick_route_start_uses_outer_edge_when_cap_faces_pad(self):
        index = 4
        draw = self.extensions[index].extension_draw
        assert draw is not None
        classification = self.all_classify[index]
        pad_bb = classification.signal_polygons()[0].polygon.bounding_box()
        pad_ref = (
            (pad_bb[0][0] + pad_bb[1][0]) / 2.0,
            (pad_bb[0][1] + pad_bb[1][1]) / 2.0,
        )
        start = pick_route_start(draw, toward_point=pad_ref)
        self.assertGreater(start.width_um, 0.0)
        mid = (
            (draw.outer_edge[0][0] + draw.outer_edge[1][0]) / 2.0,
            (draw.outer_edge[0][1] + draw.outer_edge[1][1]) / 2.0,
        )
        self.assertAlmostEqual(start.center[0], mid[0], places=3)
        self.assertAlmostEqual(start.center[1], mid[1], places=3)

    def test_pick_route_start_uses_mouth_edge_when_cap_faces_away(self):
        index = 6
        draw = self.extensions[index].extension_draw
        assert draw is not None
        classification = self.all_classify[index]
        pad_bb = classification.signal_polygons()[0].polygon.bounding_box()
        pad_ref = (
            (pad_bb[0][0] + pad_bb[1][0]) / 2.0,
            (pad_bb[0][1] + pad_bb[1][1]) / 2.0,
        )
        start = pick_route_start(draw, toward_point=pad_ref)
        inner_mid = (
            (draw.intercept_a[0] + draw.intercept_b[0]) / 2.0,
            (draw.intercept_a[1] + draw.intercept_b[1]) / 2.0,
        )
        outer_mid = (
            (draw.outer_edge[0][0] + draw.outer_edge[1][0]) / 2.0,
            (draw.outer_edge[0][1] + draw.outer_edge[1][1]) / 2.0,
        )
        self.assertAlmostEqual(start.center[0], inner_mid[0], places=3)
        self.assertAlmostEqual(start.center[1], inner_mid[1], places=3)
        self.assertGreater(
            (start.center[0] - outer_mid[0]) ** 2
            + (start.center[1] - outer_mid[1]) ** 2,
            1.0,
        )

    def test_build_mte_pad_route_none_for_collar_extend(self):
        index = 0
        route = build_mte_pad_route(
            self.all_roles[index],
            self.all_classify[index],
            self.extensions[index],
            self.ctx["layermap"],
            self.route_cfg,
            resonator_index=index,
        )
        self.assertIsNone(route)


if __name__ == "__main__":
    unittest.main()
