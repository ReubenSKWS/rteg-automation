"""Step 5.4 — MTE pad stretch to preserved extension corners."""
from __future__ import annotations

import math
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
from rteg_mte_extensions import MteBuildConfig, CollarExtensionDraw, build_mte_extensions
from rteg_mte_route import (
    MteRouteConfig,
    PreservedMteParts,
    build_mte_pad_route,
    build_mte_pad_routes,
    collar_extension_junction_corners,
    identify_preserved_mte_parts,
    merge_mte_route_with_extensions,
    pick_pad_attachment_edge,
    pick_route_start,
    preserved_extension_attach_corners,
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
        body_mte = [gdstk.rectangle((60.0, 35.0), (80.0, 65.0), layer=5, datatype=0)]
        collar = gdstk.rectangle((54.0, 35.0), (80.0, 65.0), layer=5, datatype=0)
        extension = gdstk.Polygon(
            [(50.0, 40.0), (50.0, 60.0), (54.0, 60.0), (54.0, 40.0)],
            layer=5,
            datatype=0,
        )
        parts = PreservedMteParts(
            collar=collar,
            extension=extension,
            merge_polys=(extension,),
        )
        draw = CollarExtensionDraw(
            polygon=extension,
            intercept_a=(54.0, 60.0),
            intercept_b=(54.0, 40.0),
            outer_edge=((54.0, 40.0), (54.0, 60.0)),
            extension_um=0.0,
            target_extension_um=0.0,
            mouth_span_um=20.0,
        )
        stretched, _attachment = stretch_extension_to_pad(
            draw,
            [pad],
            cfg,
            5,
            0,
            body_mte_polys=body_mte,
            parts=parts,
        )
        pad_x = 12.0 - cfg.pad_touch_overlap_um
        self.assertAlmostEqual(stretched.points[0][0], pad_x, places=3)
        self.assertAlmostEqual(stretched.points[1][0], pad_x, places=3)
        self.assertAlmostEqual(stretched.points[0][1], 40.0, places=3)
        self.assertAlmostEqual(stretched.points[1][1], 60.0, places=3)
        self.assertAlmostEqual(stretched.points[2][0], 54.0, places=3)
        self.assertAlmostEqual(stretched.points[2][1], 60.0, places=3)
        self.assertAlmostEqual(stretched.points[3][0], 54.0, places=3)
        self.assertAlmostEqual(stretched.points[3][1], 40.0, places=3)
        inter = gdstk.boolean(stretched, pad, "and", precision=cfg.boolean_precision)
        self.assertTrue(inter)
        self.assertGreater(sum(abs(p.area()) for p in inter), 0.01)

    def test_merge_uses_extension_stub_not_collar(self):
        cfg = MteRouteConfig()
        pad = gdstk.rectangle((0.0, 40.0), (12.0, 60.0), layer=2, datatype=0)
        collar = gdstk.rectangle((54.0, 35.0), (80.0, 65.0), layer=5, datatype=0)
        extension = gdstk.Polygon(
            [(50.0, 40.0), (50.0, 60.0), (54.0, 60.0), (54.0, 40.0)],
            layer=5,
            datatype=0,
        )
        route = gdstk.Polygon(
            [(12.0, 40.0), (12.0, 60.0), (54.0, 60.0), (54.0, 40.0)],
            layer=5,
            datatype=0,
        )
        merged_ext = merge_mte_route_with_extensions(
            route, [extension], boolean_precision=cfg.boolean_precision
        )
        merged_both = merge_mte_route_with_extensions(
            route,
            [collar, extension],
            boolean_precision=cfg.boolean_precision,
        )
        collar_area = abs(collar.area())
        ext_only_overlap = gdstk.boolean(
            merged_ext, collar, "and", precision=cfg.boolean_precision
        )
        both_overlap = gdstk.boolean(
            merged_both, collar, "and", precision=cfg.boolean_precision
        )
        ext_frac = (
            sum(abs(p.area()) for p in ext_only_overlap) / collar_area
            if ext_only_overlap
            else 0.0
        )
        both_frac = (
            sum(abs(p.area()) for p in both_overlap) / collar_area
            if both_overlap
            else 0.0
        )
        self.assertLess(ext_frac, 0.1)
        self.assertGreater(both_frac, 0.9)
        self.assertGreater(abs(merged_both.area()), abs(merged_ext.area()))


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

    def _route_quad(self, index: int) -> gdstk.Polygon:
        result = self.routed[index]
        assert result.route_draw is not None
        return result.route_draw.route_polygon

    def _assert_stretch_to_pad_corners(self, index: int) -> None:
        result = self.routed[index]
        classification = self.all_classify[index]
        assert result.route_draw is not None

        pads = [tp.polygon for tp in classification.signal_polygons()]
        x0, y0, x1, y1 = _pad_bbox_corners(pads)
        overlap_x = x1 - self.route_cfg.pad_touch_overlap_um
        pad_pts = self._route_quad(index).points[:2]
        ys = sorted(p[1] for p in pad_pts)
        xs = [p[0] for p in pad_pts]
        self.assertAlmostEqual(min(xs), overlap_x, places=1)
        self.assertAlmostEqual(max(xs), overlap_x, places=1)
        self.assertAlmostEqual(ys[0], y0, places=1)
        self.assertAlmostEqual(ys[1], y1, places=1)

    def _mte_parts(self, index: int) -> PreservedMteParts:
        return identify_preserved_mte_parts(
            self.extensions[index].preserved_collar_polygons,
            self.all_roles[index].resonator_body_mte,
            mte_build_cfg=self.mte_cfg,
            boolean_precision=self.route_cfg.boolean_precision,
        )

    def _assert_junction_attach(self, index: int) -> None:
        parts = self._mte_parts(index)
        body_mte = self.all_roles[index].resonator_body_mte
        mte_up, mte_dn = preserved_extension_attach_corners(
            parts, body_mte, self.route_cfg
        )
        expected = collar_extension_junction_corners(parts, body_mte, self.route_cfg)
        self.assertAlmostEqual(mte_up[0], expected[0][0], places=2)
        self.assertAlmostEqual(mte_up[1], expected[0][1], places=2)
        self.assertAlmostEqual(mte_dn[0], expected[1][0], places=2)
        self.assertAlmostEqual(mte_dn[1], expected[1][1], places=2)
        self._assert_extension_attach_corners(index)

    def _assert_extension_attach_corners(self, index: int) -> None:
        parts = self._mte_parts(index)
        body_mte = self.all_roles[index].resonator_body_mte
        mte_up, mte_dn = preserved_extension_attach_corners(
            parts, body_mte, self.route_cfg
        )
        net = self._route_quad(index)
        self.assertAlmostEqual(net.points[2][0], mte_up[0], places=2)
        self.assertAlmostEqual(net.points[2][1], mte_up[1], places=2)
        self.assertAlmostEqual(net.points[3][0], mte_dn[0], places=2)
        self.assertAlmostEqual(net.points[3][1], mte_dn[1], places=2)

    def test_center_pad_indices_routed(self):
        for index in (1, 3, 4, 6):
            result = self.routed[index]
            classification = self.all_classify[index]
            self.assertEqual(classification.mte_route_target, "center_pad")
            self.assertTrue(classification.collar_orientation.mte_faces_center)
            self.assertIsNotNone(result.route_draw)
            self.assertIsNotNone(result.routed_net)
            self.assertEqual(result.n_extensions, 1)
            assert result.route_draw is not None
            assert result.routed_net is not None
            self.assertGreaterEqual(
                result.route_draw.pad_overlap_um2,
                self.route_cfg.min_pad_overlap_um2,
            )
            pads = [tp.polygon for tp in classification.signal_polygons()]
            quad = result.route_draw.route_polygon
            self.assertTrue(
                gdstk.boolean(
                    quad, pads, "and", precision=self.route_cfg.boolean_precision
                )
            )
            parts = identify_preserved_mte_parts(
                self.extensions[index].preserved_collar_polygons,
                self.all_roles[index].resonator_body_mte,
                boolean_precision=self.route_cfg.boolean_precision,
            )
            self.assertEqual(
                parts.merge_polys,
                (parts.extension,),
                msg=f"index {index}: only extension stub may boolean-merge",
            )

    def test_index1_extension_corner_attach(self):
        result = self.routed[1]
        base = self.extensions[1]
        assert result.route_draw is not None and base.extension is not None
        net = self._route_quad(1)
        collar_pts = net.points[2:]
        y_span = abs(collar_pts[0][1] - collar_pts[1][1])
        self.assertGreater(y_span, 10.0, msg="junction attach span too narrow")
        ext_pts = [(float(p[0]), float(p[1])) for p in base.extension.points]
        for pt in collar_pts:
            self.assertTrue(
                any(math.hypot(pt[0] - q[0], pt[1] - q[1]) < 0.15 for q in ext_pts),
                msg=f"attach point {pt} is not an extension vertex",
            )
        merged = merge_mte_route_with_extensions(
            result.route_draw.route_polygon,
            [base.extension],
            boolean_precision=self.route_cfg.boolean_precision,
        )
        inter = gdstk.boolean(
            merged, base.extension, "and", precision=self.route_cfg.boolean_precision
        )
        self.assertTrue(inter, msg="merged route must overlap preserved extension")
        self.assertGreater(sum(abs(p.area()) for p in inter), 0.1)
        self._assert_stretch_to_pad_corners(1)
        self._assert_junction_attach(1)

    def test_index3_stretch_reaches_pad_corners(self):
        self._assert_stretch_to_pad_corners(3)
        self._assert_junction_attach(3)

    def test_index4_stretch_reaches_pad_corners(self):
        self._assert_stretch_to_pad_corners(4)
        self._assert_junction_attach(4)

    def test_index6_stretch_reaches_pad_corners(self):
        self._assert_stretch_to_pad_corners(6)
        self._assert_junction_attach(6)

    def test_index6_attach_corners_have_y_separation(self):
        net = self._route_quad(6)
        collar_pts = net.points[2:]
        self.assertGreater(abs(collar_pts[0][1] - collar_pts[1][1]), 10.0)

    def test_collar_extend_indices_unchanged(self):
        for index in (0, 2, 5, 7):
            base = self.extensions[index]
            result = self.routed[index]
            self.assertEqual(self.all_classify[index].mte_route_target, "collar_extend")
            self.assertIsNone(result.route_draw)
            self.assertIsNone(result.routed_net)
            self.assertEqual(result.n_extensions, 0)
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
