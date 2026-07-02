"""Step 5.5 — right-edge bridge for split MBE rectangle filler."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import gdstk

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for p in (str(SRC), str(TESTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from kb331_pipeline import load_kb331_pipeline
from rteg_classify import classify_nodes
from rteg_collect import (
    RtegCollectConfig,
    attach_preserved_filter_interconnect_all,
    collect_geometry_roles,
    collect_orientation_inputs,
)
from rteg_filler_bridge import (
    DEFAULT_FILLER_BRIDGE_WIDTH_UM,
    DEFAULT_FRAME_CAP_OVERLAP_UM,
    apply_filler_bridge_all_routes,
    filler_bridge_applies,
    filler_bridge_overview_rows,
    gsg_frame_y_span,
    right_edge_bridge_polygon,
    right_frame_cap_polygon,
    split_rectangle_plate_detected,
)
from rteg_route_new import build_all_routes, ground_filler_frame_mask
from rteg_route_clean import _interior_angle_deg


def _mock_ground_plates(*, y_lo: float, y_hi: float) -> SimpleNamespace:
    return SimpleNamespace(
        top=[SimpleNamespace(polygon=gdstk.Polygon([(0.0, y_hi - 20.0), (0.0, y_hi), (50.0, y_hi), (50.0, y_hi - 20.0)], 2, 0))],
        bottom=[SimpleNamespace(polygon=gdstk.Polygon([(0.0, y_lo), (0.0, y_lo + 20.0), (50.0, y_lo + 20.0), (50.0, y_lo)], 2, 0))],
    )


class TestFillerBridgeSynthetic(unittest.TestCase):
    def test_detects_two_disconnected_plate_fragments(self):
        plate = [gdstk.Polygon([(100.0, 0.0), (100.0, 100.0), (200.0, 100.0), (200.0, 0.0)], 2, 0)]
        bottom = gdstk.Polygon([(100.0, 0.0), (100.0, 40.0), (200.0, 40.0), (200.0, 0.0)], 2, 0)
        top = gdstk.Polygon([(100.0, 60.0), (100.0, 100.0), (200.0, 100.0), (200.0, 60.0)], 2, 0)
        detected, pieces = split_rectangle_plate_detected([bottom, top], plate)
        self.assertTrue(detected)
        self.assertEqual(len(pieces), 2)

    def test_right_edge_bridge_matches_gsg_frame_height(self):
        plate = [gdstk.Polygon([(100.0, -10.0), (100.0, 110.0), (200.0, 110.0), (200.0, -10.0)], 2, 0)]
        ground_plates = _mock_ground_plates(y_lo=10.0, y_hi=90.0)
        result = right_edge_bridge_polygon(
            plate, ground_plates, width_um=1.0, layer=2, datatype=0,
        )
        self.assertIsNotNone(result)
        assert result is not None
        poly, top_right, bottom_right = result
        self.assertEqual(top_right, (200.0, 90.0))
        self.assertEqual(bottom_right, (200.0, 10.0))
        self.assertAlmostEqual(abs(poly.area()), 80.0, places=1)


class TestFillerBridgeKb331(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = load_kb331_pipeline()
        layermap = cls.ctx["layermap"]
        identification = cls.ctx["identification"]
        res_list = cls.ctx["res_list"]
        rteg = cls.ctx["frame_assemblies"]
        attach_preserved_filter_interconnect_all(rteg, res_list, identification, layermap)
        cfg = RtegCollectConfig()
        cls.all_roles = {}
        cls.all_classify = {}
        for idx in range(len(res_list)):
            res = res_list[idx]
            roles = collect_geometry_roles(rteg[idx], res, identification, layermap, config=cfg)
            orient = collect_orientation_inputs(
                rteg[idx], res, identification, layermap,
                ground_plates=roles.ground_plates, config=cfg,
            )
            cls.all_roles[idx] = roles
            cls.all_classify[idx] = classify_nodes(
                roles.ground_plates, roles.preserved, orientation=orient, res_type=res.res_type,
            )
        cls.routes = build_all_routes(cls.all_roles, cls.all_classify, layermap)
        cls.layermap = layermap

    def test_index0_split_plate_detected(self):
        roles = self.all_roles[0]
        filler_plate = [tp.polygon for tp in roles.ground_plates.filler]
        detected, pieces = split_rectangle_plate_detected(self.routes[0].filler_nets, filler_plate)
        self.assertTrue(detected)
        self.assertEqual(len(pieces), 2)
        self.assertTrue(filler_bridge_applies(self.routes[0], roles, self.all_classify[0]))

    def test_index2_single_plate_not_bridged(self):
        roles = self.all_roles[2]
        filler_plate = [tp.polygon for tp in roles.ground_plates.filler]
        detected, _ = split_rectangle_plate_detected(self.routes[2].filler_nets, filler_plate)
        self.assertFalse(detected)
        self.assertFalse(filler_bridge_applies(self.routes[2], roles, self.all_classify[2]))

    def test_index0_bridge_reunites_rectangle_plate(self):
        updated = apply_filler_bridge_all_routes(
            self.routes, self.all_roles, self.all_classify, self.layermap, indices=(0,),
        )
        roles = self.all_roles[0]
        filler_plate = [tp.polygon for tp in roles.ground_plates.filler]
        detected, _ = split_rectangle_plate_detected(updated[0].filler_nets, filler_plate)
        self.assertFalse(detected)
        self.assertEqual(len(updated[0].filler_nets), 2)

    def test_index0_frame_cap_is_independent_polygon(self):
        updated = apply_filler_bridge_all_routes(
            self.routes, self.all_roles, self.all_classify, self.layermap, indices=(0,),
        )
        roles = self.all_roles[0]
        filler_right = roles.ground_plates.filler[0].polygon.bounding_box()[1][0]
        y_lo, y_hi = gsg_frame_y_span(roles.ground_plates)
        assert y_lo is not None
        plate_overlap = [
            p for p in updated[0].filler_nets
            if p.bounding_box()[1][0] <= filler_right + 0.02
        ]
        cap_pieces = [
            p for p in updated[0].filler_nets
            if p.bounding_box()[0][0] >= filler_right - 0.02
        ]
        self.assertEqual(len(updated[0].filler_nets), 2)
        self.assertEqual(len(plate_overlap), 1)
        self.assertEqual(len(cap_pieces), 1)
        cap_bb = cap_pieces[0].bounding_box()
        self.assertAlmostEqual(cap_bb[0][0], filler_right, places=2)
        self.assertEqual(len(cap_pieces[0].points), 4)
        self.assertNotEqual(id(plate_overlap[0]), id(cap_pieces[0]))

    def test_index0_bridge_matches_gsg_frame_height(self):
        rows = filler_bridge_overview_rows(
            self.routes, self.all_roles, self.all_classify, self.layermap, indices=(0,),
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertTrue(row["applied"])
        self.assertEqual(row["bridge_width_um"], DEFAULT_FILLER_BRIDGE_WIDTH_UM)

        roles = self.all_roles[0]
        y_span = gsg_frame_y_span(roles.ground_plates)
        self.assertIsNotNone(y_span)
        assert y_span is not None
        y_lo, y_hi = y_span
        mask = ground_filler_frame_mask(roles.ground_plates, roles.frame_boundary)
        self.assertIsNotNone(mask)
        assert mask is not None
        mask_bb = mask.bounding_box()
        x1 = mask_bb[1][0]

        self.assertAlmostEqual(row["bridge_from_x"], x1, places=2)
        self.assertAlmostEqual(row["bridge_from_y"], y_hi, places=2)
        self.assertAlmostEqual(row["bridge_to_x"], x1, places=2)
        self.assertAlmostEqual(row["bridge_to_y"], y_lo, places=2)
        self.assertAlmostEqual(row["bridge_length_um"], y_hi - y_lo, places=2)
        self.assertAlmostEqual(row["bridge_length_um"], mask_bb[1][1] - mask_bb[0][1], places=2)

    def test_index0_frame_cap_overlaps_die_frame(self):
        rows = filler_bridge_overview_rows(
            self.routes, self.all_roles, self.all_classify, self.layermap, indices=(0,),
        )
        row = rows[0]
        self.assertTrue(row["frame_cap_applied"])
        self.assertEqual(row["frame_cap_overlap_um"], DEFAULT_FRAME_CAP_OVERLAP_UM)

        roles = self.all_roles[0]
        cavity_right = roles.frame_boundary.cavity.polygon.bounding_box()[1][0]
        filler_right = roles.ground_plates.filler[0].polygon.bounding_box()[1][0]
        y_lo, y_hi = gsg_frame_y_span(roles.ground_plates)
        assert y_lo is not None

        self.assertAlmostEqual(row["frame_cap_x0"], filler_right, places=2)
        self.assertAlmostEqual(row["frame_cap_x1"], cavity_right + DEFAULT_FRAME_CAP_OVERLAP_UM, places=2)

        updated = apply_filler_bridge_all_routes(
            self.routes, self.all_roles, self.all_classify, self.layermap, indices=(0,),
        )
        cap_pieces = [
            p for p in updated[0].filler_nets
            if p.bounding_box()[0][0] >= filler_right - 0.02
        ]
        self.assertEqual(len(cap_pieces), 1)
        cap_band = gdstk.rectangle(
            (filler_right, y_lo),
            (cavity_right + DEFAULT_FRAME_CAP_OVERLAP_UM + 0.01, y_hi),
            2, 0,
        )
        overlap = gdstk.boolean([cap_pieces[0]], [cap_band], "and", precision=1e-3) or []
        cap_area = sum(abs(p.area()) for p in overlap)
        expected = (cavity_right + DEFAULT_FRAME_CAP_OVERLAP_UM - filler_right) * (y_hi - y_lo)
        self.assertAlmostEqual(cap_area, expected, delta=5.0)

    def test_index0_bridge_has_no_union_spikes(self):
        updated = apply_filler_bridge_all_routes(
            self.routes, self.all_roles, self.all_classify, self.layermap, indices=(0,),
        )
        roles = self.all_roles[0]
        filler_right = roles.ground_plates.filler[0].polygon.bounding_box()[1][0]
        plate_piece = max(
            updated[0].filler_nets,
            key=lambda p: abs(p.area()),
        )
        self.assertLessEqual(plate_piece.bounding_box()[1][0], filler_right + 0.02)
        pts = [(float(x), float(y)) for x, y in plate_piece.points]
        acute = [_interior_angle_deg(pts, i) for i in range(len(pts))]
        self.assertFalse(
            any(ang < 45.0 for ang in acute),
            msg="bridged filler should have no acute union spikes",
        )

    def test_center_pad_indices_unchanged(self):
        updated = apply_filler_bridge_all_routes(
            self.routes, self.all_roles, self.all_classify, self.layermap,
        )
        for idx in (1, 3, 4, 6):
            before = self.routes[idx].filler_nets
            after = updated[idx].filler_nets
            self.assertEqual(len(before), len(after))
            self.assertAlmostEqual(
                sum(abs(p.area()) for p in before),
                sum(abs(p.area()) for p in after),
            )

    def test_index7_split_plate_bridged(self):
        roles = self.all_roles[7]
        filler_plate = [tp.polygon for tp in roles.ground_plates.filler]
        detected, _ = split_rectangle_plate_detected(self.routes[7].filler_nets, filler_plate)
        self.assertTrue(detected)
        updated = apply_filler_bridge_all_routes(
            self.routes, self.all_roles, self.all_classify, self.layermap, indices=(7,),
        )
        detected_after, _ = split_rectangle_plate_detected(updated[7].filler_nets, filler_plate)
        self.assertFalse(detected_after)
        self.assertEqual(len(updated[7].filler_nets), 2)


if __name__ == "__main__":
    unittest.main()
