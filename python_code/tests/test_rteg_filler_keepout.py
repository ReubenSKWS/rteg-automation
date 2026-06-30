"""Step 5.3b — MBE rectangle filler keepout vs resonator outline."""
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
from rteg_collect import (
    RtegCollectConfig,
    attach_preserved_filter_interconnect_all,
    collect_geometry_roles,
    collect_orientation_inputs,
)
from rteg_filler_keepout import (
    FillerKeepoutConfig,
    _intersection_x_span,
    _keepout_cut_zones,
    _mte_attachment_zone,
    _mte_extension_polys,
    _resonator_keepout_zone,
    apply_filler_keepout_all_routes,
    carve_rectangle_filler_outside_intersection,
    center_pad_indices,
    center_pad_keepout_check_rows,
    collar_extend_indices,
    filler_keepout_applies,
    filler_keepout_overview_rows,
)
from rteg_route_clean import _interior_angle_deg
from rteg_route_new import build_all_routes, extract_collar_contact, ground_filler_frame_mask


def _min_dist_point_to_polys(point: tuple[float, float], polys: list[gdstk.Polygon]) -> float:
    px, py = point
    best = float("inf")
    for poly in polys:
        pts = poly.points
        n = len(pts)
        for i in range(n):
            x0, y0 = float(pts[i][0]), float(pts[i][1])
            x1, y1 = float(pts[(i + 1) % n][0]), float(pts[(i + 1) % n][1])
            dx, dy = x1 - x0, y1 - y0
            ll = dx * dx + dy * dy
            if ll < 1e-18:
                d = math.hypot(px - x0, py - y0)
            else:
                t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / ll))
                d = math.hypot(px - x0 - t * dx, py - y0 - t * dy)
            best = min(best, d)
    return best

COLLAR_EXTEND_INDICES = (0, 2, 5, 7)
CENTER_PAD_INDICES = (1, 3, 4, 6)


def _min_distance_between(poly_a: gdstk.Polygon, poly_b: gdstk.Polygon) -> float:
    best = float("inf")
    for ax, ay in poly_a.points:
        for bx, by in poly_b.points:
            best = min(best, math.hypot(float(ax) - float(bx), float(ay) - float(by)))
    return best


def _min_distance_to_polys(poly: gdstk.Polygon, others: list[gdstk.Polygon]) -> float:
    return min(_min_distance_between(poly, other) for other in others)


class TestFillerKeepoutSynthetic(unittest.TestCase):
    def test_carves_rectangle_using_resonator_outline_keepout(self):
        filler = [gdstk.Polygon([(0.0, 0.0), (0.0, 100.0), (200.0, 100.0), (200.0, 0.0)], 2, 0)]
        body = [gdstk.Polygon([(30.0, 35.0), (30.0, 65.0), (70.0, 65.0), (70.0, 35.0)], 3, 0)]
        mte_ext = [gdstk.Polygon([(80.0, 40.0), (80.0, 60.0), (120.0, 60.0), (120.0, 40.0)], 4, 0)]
        carved, result = carve_rectangle_filler_outside_intersection(
            filler, mte_ext, body, cfg=FillerKeepoutConfig(clearance_um=20.0),
        )
        self.assertTrue(result.applied)
        self.assertEqual(result.intersection_x_span, (80.0, 120.0))
        self.assertLess(sum(abs(p.area()) for p in carved), sum(abs(p.area()) for p in filler))
        left_band = gdstk.Polygon([(-10.0, 35.0), (-10.0, 65.0), (60.0, 65.0), (60.0, 35.0)], 2, 0)
        left_metal = gdstk.boolean(carved, [left_band], "and", precision=1e-3) or []
        keepout = _resonator_keepout_zone(body, 20.0, precision=1e-3)
        if left_metal:
            for piece in left_metal:
                overlap = gdstk.boolean([piece], keepout, "and", precision=1e-3)
                self.assertFalse(overlap)


class TestFillerKeepoutKb331(unittest.TestCase):
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
        cls.routes = build_all_routes(
            cls.all_roles, cls.all_classify, layermap, apply_filler_keepout=False,
        )
        cls.layermap = layermap

    def test_center_pad_indices_skip_keepout(self):
        for idx in CENTER_PAD_INDICES:
            self.assertFalse(filler_keepout_applies(self.all_classify[idx]))
        self.assertNotIn(6, collar_extend_indices(self.all_classify))

    def test_index1_filler_unchanged_by_keepout(self):
        self.assertIn(1, center_pad_indices(self.all_classify))
        before = self.routes[1].filler_nets
        updated = apply_filler_keepout_all_routes(
            self.routes, self.all_roles, self.all_classify, self.layermap,
        )
        after = updated[1].filler_nets
        self.assertEqual(len(before), len(after))
        self.assertAlmostEqual(
            sum(abs(p.area()) for p in before),
            sum(abs(p.area()) for p in after),
        )
        checks = center_pad_keepout_check_rows(self.routes, updated, self.all_classify)
        row1 = next(row for row in checks if row["index"] == 1)
        self.assertTrue(row1["unchanged"])
        self.assertEqual(row1["filler_area_delta_um2"], 0.0)

    def test_index6_filler_unchanged_by_keepout(self):
        before = self.routes[6].filler_nets
        updated = apply_filler_keepout_all_routes(
            self.routes, self.all_roles, self.all_classify, self.layermap,
        )
        after = updated[6].filler_nets
        self.assertEqual(len(before), len(after))
        self.assertAlmostEqual(
            sum(abs(p.area()) for p in before),
            sum(abs(p.area()) for p in after),
        )
        preview = filler_keepout_overview_rows(
            self.routes, self.all_roles, self.all_classify, self.layermap,
        )
        self.assertTrue(all(row["index"] in COLLAR_EXTEND_INDICES for row in preview))
        self.assertNotIn(6, [row["index"] for row in preview])

    def test_center_pad_ground_filler_touches_mbe_collar(self):
        """Ground filler must close to the MBE collar mouth after preserved MBE is stripped."""
        for idx in CENTER_PAD_INDICES:
            roles = self.all_roles[idx]
            route = self.routes[idx]
            self.assertTrue(route.filler_nets, msg=f"index {idx}: no filler")
            mbe = [tp.polygon for tp in roles.preserved.mbe]
            contact = extract_collar_contact(
                mbe,
                roles.resonator_body_mbe,
                signal_pad_polys=[tp.polygon for tp in roles.ground_plates.center],
            )
            self.assertIsNotNone(contact, msg=f"index {idx}: no MBE collar contact")
            assert contact is not None
            for label, pt in (("A", contact.intercept_a), ("B", contact.intercept_b)):
                dist = _min_dist_point_to_polys(pt, route.filler_nets)
                self.assertLessEqual(
                    dist, 0.5,
                    msg=f"index {idx} intercept {label}: filler gap {dist:.2f} µm",
                )

    def test_ground_filler_stays_inside_gsg_and_filler_frame(self):
        """MBE filler nets must not extend past GSG height or the rectangle filler right edge."""
        for idx in sorted(self.routes):
            roles = self.all_roles[idx]
            mask = ground_filler_frame_mask(roles.ground_plates, roles.frame_boundary)
            self.assertIsNotNone(mask, msg=f"index {idx}: no frame mask")
            assert mask is not None
            (mx0, my0), (mx1, my1) = mask.bounding_box()
            for piece in self.routes[idx].filler_nets:
                bb = piece.bounding_box()
                self.assertIsNotNone(bb)
                assert bb is not None
                (x0, y0), (x1, y1) = bb
                self.assertGreaterEqual(x0, mx0 - 0.01, msg=f"index {idx}: left of cavity")
                self.assertLessEqual(x1, mx1 + 0.01, msg=f"index {idx}: right of filler")
                self.assertGreaterEqual(y0, my0 - 0.01, msg=f"index {idx}: below bottom GSG")
                self.assertLessEqual(y1, my1 + 0.01, msg=f"index {idx}: above top GSG")

    def test_collar_extend_indices_apply_keepout(self):
        updated = apply_filler_keepout_all_routes(
            self.routes, self.all_roles, self.all_classify, self.layermap,
            indices=COLLAR_EXTEND_INDICES,
            cfg=FillerKeepoutConfig(clearance_um=20.0),
        )
        for idx in COLLAR_EXTEND_INDICES:
            before = sum(abs(p.area()) for p in self.routes[idx].filler_nets)
            after = sum(abs(p.area()) for p in updated[idx].filler_nets)
            self.assertLess(after, before, f"index {idx} should lose filler area outside intersection span")

    def test_index2_filler_stays_one_polygon_through_mte_extension(self):
        """Series index 2 (S1B): carved filler remains one net through the MTE mouth."""
        before = self.routes[2].filler_nets
        self.assertEqual(len(before), 1)
        updated = apply_filler_keepout_all_routes(
            self.routes, self.all_roles, self.all_classify, self.layermap,
            indices=(2,),
            cfg=FillerKeepoutConfig(clearance_um=20.0),
        )
        self.assertEqual(len(updated[2].filler_nets), 1)

    def test_index2_filler_has_no_internal_spikes(self):
        """Keepout carve + spike clean removes inward notches at the MTE mouth."""
        updated = apply_filler_keepout_all_routes(
            self.routes, self.all_roles, self.all_classify, self.layermap,
            indices=(2,),
        )
        pts = [(float(x), float(y)) for x, y in updated[2].filler_nets[0].points]
        acute = [_interior_angle_deg(pts, i) for i in range(len(pts))]
        self.assertFalse(
            any(ang < 45.0 for ang in acute),
            msg="filler should have no acute inward spikes after keepout",
        )

    def test_index2_filler_does_not_wrap_outside_mte_intersection(self):
        """Series index 2 (S1B): rectangle filler attaches only through MTE extension stub."""
        roles = self.all_roles[2]
        body = [*roles.resonator_body_mte, *roles.resonator_body_mbe]
        filler_plate = [tp.polygon for tp in roles.ground_plates.filler]
        cfg = FillerKeepoutConfig(clearance_um=20.0)
        mte = _mte_extension_polys(roles, cfg)
        span, _ = _intersection_x_span(filler_plate, mte, precision=cfg.boolean_precision)
        self.assertIsNotNone(span)
        assert span is not None
        x_lo, x_hi = span

        updated = apply_filler_keepout_all_routes(
            self.routes, self.all_roles, self.all_classify, self.layermap,
            indices=(2,),
            cfg=cfg,
        )
        ys: list[float] = []
        for p in filler_plate:
            bb = p.bounding_box()
            if bb:
                ys.extend([bb[0][1], bb[1][1]])
        cut = _keepout_cut_zones(
            body, mte, span, (min(ys), max(ys)),
            clearance_um=cfg.clearance_um,
            attachment_margin_um=cfg.attachment_margin_um,
            precision=cfg.boolean_precision,
        )
        for piece in updated[2].filler_nets:
            overlap = gdstk.boolean([piece], cut, "and", precision=cfg.boolean_precision) or []
            overlap_area = sum(abs(p.area()) for p in overlap)
            self.assertLess(
                overlap_area,
                25.0,
                msg="filler keepout overlap should be negligible after spike clean",
            )

        # Within the intersection x-span, filler must not hug the body off-extension.
        keepout = _resonator_keepout_zone(body, cfg.clearance_um, precision=cfg.boolean_precision)
        attach = _mte_attachment_zone(
            mte, margin_um=cfg.attachment_margin_um, precision=cfg.boolean_precision,
        )
        mouth_band = gdstk.Polygon([(x_lo, 250.0), (x_lo, 335.0), (x_hi, 335.0), (x_hi, 250.0)])
        in_band = gdstk.boolean(updated[2].filler_nets, [mouth_band], "and", precision=cfg.boolean_precision) or []
        off_ext = gdstk.boolean(in_band, attach, "not", precision=cfg.boolean_precision) or []
        near_body = gdstk.boolean(off_ext, keepout, "and", precision=cfg.boolean_precision) or []
        self.assertFalse(near_body, msg="in-span filler tabs near MBE intercepts must be carved")

    def test_build_all_routes_applies_filler_keepout_by_default(self):
        routes = build_all_routes(self.all_roles, self.all_classify, self.layermap)
        manual = apply_filler_keepout_all_routes(
            self.routes, self.all_roles, self.all_classify, self.layermap,
        )
        for idx in COLLAR_EXTEND_INDICES:
            self.assertAlmostEqual(
                sum(abs(p.area()) for p in routes[idx].filler_nets),
                sum(abs(p.area()) for p in manual[idx].filler_nets),
                places=2,
            )

    def test_outside_band_respects_resonator_outline_keepout(self):
        updated = apply_filler_keepout_all_routes(
            self.routes, self.all_roles, self.all_classify, self.layermap,
            indices=(0,),
            cfg=FillerKeepoutConfig(clearance_um=20.0),
        )
        roles = self.all_roles[0]
        body = [*roles.resonator_body_mte, *roles.resonator_body_mbe]
        filler_plate = [tp.polygon for tp in roles.ground_plates.filler]
        mte = [tp.polygon for tp in roles.preserved.mte]
        inter = gdstk.boolean(filler_plate, mte, "and", precision=1e-3)
        xs = []
        for p in inter:
            bb = p.bounding_box()
            if bb:
                xs.extend([bb[0][0], bb[1][0]])
        x_hi = max(xs)
        right_probe = gdstk.Polygon(
            [(x_hi + 30.0, 200.0), (x_hi + 30.0, 400.0), (500.0, 400.0), (500.0, 200.0)], 2, 0,
        )
        right_filler = gdstk.boolean(updated[0].filler_nets, [right_probe], "and", precision=1e-3) or []
        keepout = _resonator_keepout_zone(body, 20.0, precision=1e-3)
        for piece in right_filler:
            overlap = gdstk.boolean([piece], keepout, "and", precision=1e-3)
            self.assertFalse(overlap)
            dist = _min_distance_to_polys(piece, body)
            self.assertGreaterEqual(dist, 18.0)


if __name__ == "__main__":
    unittest.main()
