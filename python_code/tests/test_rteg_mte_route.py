"""Step 5.4 — MTE pad stretch routing from 5.3 extensions."""
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
    build_mte_pad_route,
    build_mte_pad_routes,
    pick_pad_attachment_edge,
    pick_route_start,
    stretch_extension_to_pad,
)


def _pad_bbox_corners(signal_polys: list[gdstk.Polygon]) -> tuple[float, float, float, float]:
    bb = signal_polys[0].bounding_box()
    assert bb is not None
    (x0, y0), (x1, y1) = bb
    return x0, y0, x1, y1


class TestMteRouteSynthetic(unittest.TestCase):
    def test_pick_pad_attachment_edge_right_side(self):
        pad = gdstk.rectangle((0.0, 40.0), (12.0, 60.0), layer=2, datatype=0)
        attachment = pick_pad_attachment_edge(
            [pad], (50.0, 50.0), touch_overlap_um=0.5
        )
        self.assertAlmostEqual(attachment.corner_low[0], 11.5, places=3)
        self.assertAlmostEqual(attachment.corner_high[0], 11.5, places=3)
        self.assertAlmostEqual(attachment.corner_low[1], 40.0, places=3)
        self.assertAlmostEqual(attachment.corner_high[1], 60.0, places=3)
        self.assertGreater(attachment.span_um, 19.0)

    def test_stretch_reaches_pad_corners(self):
        cfg = MteRouteConfig()
        pad = gdstk.rectangle((0.0, 40.0), (12.0, 60.0), layer=2, datatype=0)
        inner_a = (50.0, 48.0)
        inner_b = (50.0, 52.0)
        outer_b = (40.0, 48.0)
        outer_a = (40.0, 52.0)
        from rteg_mte_extensions import CollarExtensionDraw

        draw = CollarExtensionDraw(
            polygon=gdstk.Polygon([inner_a, inner_b, outer_b, outer_a], layer=5, datatype=0),
            intercept_a=inner_a,
            intercept_b=inner_b,
            outer_edge=(outer_b, outer_a),
            extension_um=14.0,
            target_extension_um=14.0,
            mouth_span_um=4.0,
        )
        stretched, attachment = stretch_extension_to_pad(
            draw, [pad], cfg, 5, 0, from_point=(45.0, 50.0)
        )
        self.assertAlmostEqual(stretched.points[0][0], inner_a[0], places=3)
        self.assertAlmostEqual(stretched.points[1][0], inner_b[0], places=3)
        self.assertAlmostEqual(stretched.points[2][0], 11.5, places=3)
        self.assertAlmostEqual(stretched.points[3][0], 11.5, places=3)
        self.assertAlmostEqual(stretched.points[2][1], 40.0, places=3)
        self.assertAlmostEqual(stretched.points[3][1], 60.0, places=3)
        inter = gdstk.boolean(stretched, pad, "and", precision=cfg.boolean_precision)
        self.assertTrue(inter)
        self.assertGreater(sum(abs(p.area()) for p in inter), 0.01)


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

    def _assert_stretch_to_pad_corners(self, index: int) -> None:
        base = self.extensions[index]
        result = self.routed[index]
        classification = self.all_classify[index]
        assert base.extension_draw is not None
        assert result.route_draw is not None
        assert result.routed_net is not None

        pads = [tp.polygon for tp in classification.signal_polygons()]
        x0, y0, x1, y1 = _pad_bbox_corners(pads)
        overlap_x = x1 - self.route_cfg.pad_touch_overlap_um
        outer_pts = result.routed_net.points[2:]
        ys = sorted(p[1] for p in outer_pts)
        xs = [p[0] for p in outer_pts]
        self.assertAlmostEqual(min(xs), overlap_x, places=1)
        self.assertAlmostEqual(max(xs), overlap_x, places=1)
        self.assertAlmostEqual(ys[0], y0, places=1)
        self.assertAlmostEqual(ys[1], y1, places=1)

    def _assert_53_mouth_preserved(self, index: int) -> None:
        draw = self.extensions[index].extension_draw
        routed_draw = self.routed[index].route_draw
        assert draw is not None and routed_draw is not None
        net = routed_draw.routed_net_polygon
        self.assertAlmostEqual(net.points[0][0], draw.intercept_a[0], places=3)
        self.assertAlmostEqual(net.points[0][1], draw.intercept_a[1], places=3)
        self.assertAlmostEqual(net.points[1][0], draw.intercept_b[0], places=3)
        self.assertAlmostEqual(net.points[1][1], draw.intercept_b[1], places=3)

    def test_center_pad_indices_routed(self):
        for index in (1, 3, 4, 6):
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

    def test_index3_stretch_reaches_pad_corners(self):
        self._assert_stretch_to_pad_corners(3)

    def test_index3_stretch_uses_collar_pad_facing_mouth(self):
        draw = self.extensions[3].extension_draw
        result = self.routed[3]
        assert draw is not None and result.routed_net is not None
        inner_pts = result.routed_net.points[:2]
        inner_y_span = abs(inner_pts[0][1] - inner_pts[1][1])
        self.assertGreater(inner_y_span, 15.0)
        self.assertAlmostEqual(draw.intercept_a[1], draw.intercept_b[1], places=1)
        self.assertLess(abs(draw.intercept_a[1] - draw.intercept_b[1]), 1.0)

    def test_index4_stretch_reaches_pad_corners(self):
        self._assert_stretch_to_pad_corners(4)
        self._assert_53_mouth_preserved(4)

    def test_index6_stretch_reaches_pad_corners(self):
        self._assert_stretch_to_pad_corners(6)
        self._assert_53_mouth_preserved(6)

    def test_index6_collar_mouth_unchanged(self):
        self._assert_53_mouth_preserved(6)

    def test_collar_extend_indices_unchanged(self):
        for index in (0, 2, 5, 7):
            base = self.extensions[index]
            result = self.routed[index]
            self.assertEqual(self.all_classify[index].mte_route_target, "collar_extend")
            self.assertIsNone(result.route_draw)
            self.assertIsNone(result.routed_net)
            self.assertEqual(result.extension, base.extension)

    def test_pick_route_start_index4_uses_outer_edge_when_cap_faces_pad(self):
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
        outer_mid = (
            (draw.outer_edge[0][0] + draw.outer_edge[1][0]) / 2.0,
            (draw.outer_edge[0][1] + draw.outer_edge[1][1]) / 2.0,
        )
        self.assertAlmostEqual(start.center[0], outer_mid[0], places=3)
        self.assertAlmostEqual(start.center[1], outer_mid[1], places=3)

    def test_pick_route_start_index6_uses_outer_edge_when_cap_faces_pad(self):
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
        outer_mid = (
            (draw.outer_edge[0][0] + draw.outer_edge[1][0]) / 2.0,
            (draw.outer_edge[0][1] + draw.outer_edge[1][1]) / 2.0,
        )
        self.assertAlmostEqual(start.center[0], outer_mid[0], places=3)
        self.assertAlmostEqual(start.center[1], outer_mid[1], places=3)

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
