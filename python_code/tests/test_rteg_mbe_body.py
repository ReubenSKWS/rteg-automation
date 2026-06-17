"""Step 6.2 / 6.3 — MBE ground body for collar_extend and center_pad resonators."""
from __future__ import annotations

import math
import sys
import tempfile
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
from prep_resonator_ppd import _grown_keepout_polys
from rteg_classify import classify_nodes
from rteg_collect import collect_geometry_roles, collect_orientation_inputs
from rteg_mbe_body import (
    MbeBodyConfig,
    _extension_outer_edge,
    build_mbe_bodies,
    build_mbe_body_filler,
    build_mbe_body_keepouts,
    draw_mbe_cap_on_mte_extension,
    mbe_body_applies,
    mbe_body_center_pad_applies,
    mbe_body_collar_extend_applies,
    mbe_body_overview_rows,
)
from rteg_mbe_body_center_pad import (
    MbeBodyCenterPadConfig,
    build_center_pad_keepouts,
    build_mbe_body_center_pads,
    _gds_polygon_count,
)
from rteg_mbe_body_common import base_filler_polygon
from rteg_mbe_extensions import (
    MbeConnectionConfig,
    build_mbe_extensions,
    select_extension_collar_mbe,
)
from rteg_mte_extensions import MteBuildConfig, build_mte_extensions, export_mte_extensions_gds
from rteg_mte_route import MteRouteConfig, build_mte_pad_routes

COLLAR_EXTEND_INDICES = (0, 2, 5, 7)
CENTER_PAD_INDICES = (1, 3, 4, 6)


def _dist_point_to_segment(
    point: tuple[float, float],
    p0: tuple[float, float],
    p1: tuple[float, float],
) -> float:
    px, py = point
    x0, y0 = p0
    x1, y1 = p1
    dx, dy = x1 - x0, y1 - y0
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-18:
        return math.hypot(px - x0, py - y0)
    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / length_sq))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def _dist_point_to_polygon(point: tuple[float, float], poly: gdstk.Polygon) -> float:
    pts = [(float(p[0]), float(p[1])) for p in poly.points]
    if not pts:
        return float("inf")
    n = len(pts)
    return min(
        _dist_point_to_segment(point, pts[i], pts[(i + 1) % n]) for i in range(n)
    )


def _min_gap_um(
    polys_a: list[gdstk.Polygon],
    polys_b: list[gdstk.Polygon],
) -> float:
    best = float("inf")
    for poly_a in polys_a:
        for x, y in poly_a.points:
            point = (float(x), float(y))
            for poly_b in polys_b:
                best = min(best, _dist_point_to_polygon(point, poly_b))
    return best


def _min_stadium_gap_outside_bridge(
    filler_polys: list[gdstk.Polygon],
    stadium_polys: list[gdstk.Polygon],
    bridge: gdstk.Polygon | None,
    *,
    precision: float = 1e-3,
) -> float:
    best = float("inf")
    for poly in filler_polys:
        for x, y in poly.points:
            point = (float(x), float(y))
            if bridge is not None:
                probe = gdstk.rectangle(
                    (point[0] - 0.05, point[1] - 0.05),
                    (point[0] + 0.05, point[1] + 0.05),
                )
                if gdstk.boolean(probe, bridge, "and", precision=precision):
                    continue
            for stadium in stadium_polys:
                best = min(best, _dist_point_to_polygon(point, stadium))
    return best


class TestMbeBodySynthetic(unittest.TestCase):
    def test_cap_is_outer_half_shifted_outward(self):
        # ``draw_lip_extension`` order: inner_a, inner_b, outer_b, outer_a; depth = 14 µm in +y
        mte_ext = gdstk.Polygon([(0, 0), (8, 0), (8, 14), (0, 14)], layer=5, datatype=0)
        cfg = MbeBodyConfig(cap_shift_um=3.5)
        cap = draw_mbe_cap_on_mte_extension(
            mte_ext,
            None,
            __import__("layermap").load_layermap(ROOT / "input_files" / "layermap"),
            cfg,
        )
        ext_area = abs(mte_ext.area())
        cap_area = abs(cap.area())
        self.assertAlmostEqual(cap_area, ext_area / 2.0, delta=0.5)

        overlap = gdstk.boolean(cap, mte_ext, "and", precision=1e-3)
        self.assertTrue(overlap)
        overlap_area = sum(abs(p.area()) for p in overlap)
        self.assertGreater(overlap_area, 0.0)
        self.assertLess(overlap_area, ext_area * 0.45)

        cap_bb = cap.bounding_box()
        self.assertIsNotNone(cap_bb)
        self.assertAlmostEqual(cap_bb[1][1], 17.5, places=2)
        self.assertAlmostEqual(cap_bb[0][1], 10.5, places=2)

    def test_keepout_offsets_stadium(self):
        stadium = gdstk.rectangle((0, 0), (100, 40), layer=5, datatype=0)
        roles = type(
            "Roles",
            (),
            {
                "resonator_body_mte": [stadium],
                "release_holes": type(
                    "RH",
                    (),
                    {"all_items": lambda self: []},
                )(),
            },
        )()
        keepouts = build_mbe_body_keepouts(roles, None, MbeBodyConfig(stadium_clearance_factor=1.0))
        self.assertTrue(keepouts)
        bb = keepouts[0].bounding_box()
        self.assertIsNotNone(bb)
        self.assertLess(bb[0][0], -1.0)
        self.assertGreater(bb[1][0], 101.0)


class TestMbeBodyKB331(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ctx = load_kb331_pipeline()
        except FileNotFoundError:
            raise unittest.SkipTest("KB331 input files not available")
        cls.mte_cfg = MteBuildConfig()
        cls.mte_route_cfg = MteRouteConfig()
        cls.mbe_cfg = MbeConnectionConfig()
        cls.body_cfg = MbeBodyConfig()
        cls.center_pad_cfg = MbeBodyCenterPadConfig()
        cls.all_roles = {}
        cls.all_classify = {}
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
        cls.all_mte = build_mte_extensions(cls.all_roles, cls.ctx["layermap"], cls.mte_cfg)
        cls.all_mte = build_mte_pad_routes(
            cls.all_roles,
            cls.all_classify,
            cls.all_mte,
            cls.ctx["layermap"],
            cls.mte_route_cfg,
        )
        cls.all_mbe = build_mbe_extensions(
            cls.all_roles,
            cls.all_classify,
            cls.ctx["layermap"],
            cls.mbe_cfg,
        )
        cls.all_body = build_mbe_bodies(
            cls.all_roles,
            cls.all_classify,
            cls.all_mte,
            cls.all_mbe,
            cls.ctx["layermap"],
            cls.body_cfg,
        )
        cls.center_pad_body = build_mbe_body_center_pads(
            cls.all_roles,
            cls.all_classify,
            cls.all_mte,
            cls.ctx["layermap"],
            cls.center_pad_cfg,
        )

    def test_gate_center_pad_drawn(self):
        for index in CENTER_PAD_INDICES:
            self.assertTrue(mbe_body_center_pad_applies(self.all_classify[index]))
            body = self.center_pad_body[index]
            self.assertGreater(body.n_pieces, 0, msg=f"index {index}")
            self.assertIsNone(body.cap, msg=f"index {index}")
            self.assertIsNone(body.bridge, msg=f"index {index}")
            self.assertTrue(body.filler, msg=f"index {index}")

    def test_gate_collar_extend_drawn(self):
        for index in COLLAR_EXTEND_INDICES:
            self.assertTrue(mbe_body_collar_extend_applies(self.all_classify[index]))
            body = self.all_body[index]
            self.assertGreater(body.n_pieces, 0, msg=f"index {index}")
            self.assertIsNotNone(body.cap, msg=f"index {index}")
            self.assertTrue(body.filler, msg=f"index {index}")

    def test_center_pad_no_cap(self):
        for index in CENTER_PAD_INDICES:
            body = self.center_pad_body[index]
            self.assertIsNone(body.cap, msg=f"index {index}")
            self.assertEqual(body.routed_net, body.filler, msg=f"index {index}")

    def test_center_pad_filler_single_closed_polygon(self):
        """MBE ground filler must be one GDS-safe closed polygon."""
        for index in CENTER_PAD_INDICES:
            body = self.center_pad_body[index]
            self.assertEqual(len(body.filler), 1, msg=f"index {index}")
            filler = body.filler[0]
            gds_count = _gds_polygon_count(
                filler,
                boolean_precision=self.center_pad_cfg.boolean_precision,
            )
            self.assertEqual(
                gds_count,
                1,
                msg=f"index {index}: filler must export as one GDS polygon",
            )
            overlap = gdstk.boolean(
                filler,
                body.absorbed_mbe[0],
                "and",
                precision=self.center_pad_cfg.boolean_precision,
            )
            self.assertTrue(
                overlap and sum(abs(p.area()) for p in overlap) > 1e-6,
                msg=f"index {index}: filler must overlap MBE collar",
            )
            base = base_filler_polygon(self.all_classify[index])
            self.assertIsNotNone(base, msg=f"index {index}")
            base_bb = base.bounding_box()
            filler_bb = filler.bounding_box()
            assert base_bb is not None and filler_bb is not None
            self.assertAlmostEqual(
                filler_bb[0][1],
                base_bb[0][1],
                places=2,
                msg=f"index {index}: filler should span full step-4 height",
            )
            self.assertAlmostEqual(
                filler_bb[1][1],
                base_bb[1][1],
                places=2,
                msg=f"index {index}: filler should span full step-4 height",
            )

    def test_center_pad_filler_touches_collar(self):
        for index in CENTER_PAD_INDICES:
            body = self.center_pad_body[index]
            roles = self.all_roles[index]
            classification = self.all_classify[index]
            signal_polys = [tp.polygon for tp in classification.center_pad_polygons()]
            collar_tp = select_extension_collar_mbe(
                roles.preserved,
                roles.resonator_body_mbe,
                self.mbe_cfg,
                signal_polys=signal_polys or None,
            )
            self.assertIsNotNone(collar_tp, msg=f"index {index}")
            gap = _min_gap_um(body.filler, [collar_tp.polygon])
            self.assertLess(
                gap,
                1.0,
                msg=f"index {index}: filler should reach MBE collar (gap={gap:.3f} µm)",
            )

    def test_center_pad_filler_respects_center_pad_keepouts(self):
        for index in CENTER_PAD_INDICES:
            body = self.center_pad_body[index]
            roles = self.all_roles[index]
            classification = self.all_classify[index]
            signal_polys = [tp.polygon for tp in classification.center_pad_polygons()]
            collar_tp = select_extension_collar_mbe(
                roles.preserved,
                roles.resonator_body_mbe,
                self.mbe_cfg,
                signal_polys=signal_polys or None,
            )
            self.assertIsNotNone(collar_tp, msg=f"index {index}")
            keepouts = build_center_pad_keepouts(
                roles,
                self.all_mte[index],
                collar_tp.polygon,
                self.center_pad_cfg,
            )
            clearance_poly = body.filler[0]
            for absorbed in body.absorbed_mbe:
                trimmed = gdstk.boolean(
                    clearance_poly,
                    absorbed,
                    "not",
                    precision=self.center_pad_cfg.boolean_precision,
                )
                if trimmed:
                    clearance_poly = max(trimmed, key=lambda p: abs(p.area()))
            overlap = gdstk.boolean(
                [clearance_poly],
                keepouts,
                "and",
                precision=self.center_pad_cfg.boolean_precision,
            )
            if overlap:
                hits = [
                    (float(x), float(y))
                    for x, y in clearance_poly.points
                    if abs(float(x) - clearance_poly.bounding_box()[0][0]) <= 0.1
                ]
                if len(hits) >= 2:
                    hit_bot = min(hits, key=lambda p: p[1])
                    hit_top = max(hits, key=lambda p: p[1])
                    filler_bb = body.filler[0].bounding_box()
                    assert filler_bb is not None
                    allowed_band = gdstk.rectangle(
                        (filler_bb[0][0], hit_bot[1] - 2.0),
                        (filler_bb[1][0], hit_top[1] + 2.0),
                    )
                    trimmed: list[gdstk.Polygon] = []
                    for piece in overlap:
                        outside = gdstk.boolean(
                            piece,
                            allowed_band,
                            "not",
                            precision=self.center_pad_cfg.boolean_precision,
                        )
                        if outside:
                            trimmed.extend(outside)
                    overlap = trimmed
            self.assertFalse(
                overlap,
                msg=(
                    f"index {index}: center-pad filler should trace keepouts and only "
                    "enter the exempt collar-access band"
                ),
            )

    def test_center_pad_export_merges_absorbed_collar(self):
        merged_body = {**self.all_body, **self.center_pad_body}
        with tempfile.TemporaryDirectory() as tmp:
            results = export_mte_extensions_gds(
                self.ctx["frame_assemblies"],
                self.all_mte,
                tmp,
                layermap=self.ctx["layermap"],
                mbe_extensions=self.all_mbe,
                mbe_bodies=merged_body,
            )
            mbe_pair = self.ctx["layermap"].pair("BAW_MBE")
            by_index = {r.index: r for r in results}
            for index in CENTER_PAD_INDICES:
                body = self.center_pad_body[index]
                self.assertTrue(body.absorbed_mbe, msg=f"index {index}")
                collar = body.absorbed_mbe[0]
                lib = gdstk.read_gds(by_index[index].path)
                mbe_polys = [
                    p
                    for cell in lib.cells
                    for p in cell.flatten().polygons
                    if (p.layer, p.datatype) == mbe_pair
                ]
                collar_area = abs(collar.area())
                standalone_collar = 0
                for poly in mbe_polys:
                    overlap = gdstk.boolean(
                        poly,
                        collar,
                        "and",
                        precision=self.center_pad_cfg.boolean_precision,
                    )
                    if not overlap:
                        continue
                    overlap_area = sum(abs(p.area()) for p in overlap)
                    poly_area = abs(poly.area())
                    if (
                        collar_area > 1e-6
                        and overlap_area / collar_area >= 0.85
                        and poly_area > 1e-6
                        and overlap_area / poly_area >= 0.85
                    ):
                        standalone_collar += 1
                self.assertEqual(
                    standalone_collar,
                    0,
                    msg=f"index {index}: preserved collar should not export separately",
                )

    def test_export_center_pad_includes_filler(self):
        merged_body = {**self.all_body, **self.center_pad_body}
        with tempfile.TemporaryDirectory() as tmp:
            results = export_mte_extensions_gds(
                self.ctx["frame_assemblies"],
                self.all_mte,
                tmp,
                layermap=self.ctx["layermap"],
                mbe_extensions=self.all_mbe,
                mbe_bodies=merged_body,
            )
            mbe_pair = self.ctx["layermap"].pair("BAW_MBE")
            by_index = {r.index: r for r in results}
            for index in CENTER_PAD_INDICES:
                lib = gdstk.read_gds(by_index[index].path)
                mbe_polys = [
                    p
                    for cell in lib.cells
                    for p in cell.flatten().polygons
                    if (p.layer, p.datatype) == mbe_pair
                ]
                self.assertGreater(len(mbe_polys), 1, msg=f"index {index}")

    def test_cap_overlaps_mte_extension(self):
        for index in COLLAR_EXTEND_INDICES:
            cap = self.all_body[index].cap
            mte_ext = self.all_mte[index].extension
            self.assertIsNotNone(cap)
            self.assertIsNotNone(mte_ext)
            overlap = gdstk.boolean(cap, mte_ext, "and", precision=1e-3)
            self.assertTrue(overlap, msg=f"index {index}")
            overlap_area = sum(abs(p.area()) for p in overlap)
            ext_area = abs(mte_ext.area())
            self.assertGreater(overlap_area, 0.0, msg=f"index {index}")
            self.assertLess(
                overlap_area,
                ext_area * 0.45,
                msg=f"index {index} overlap={overlap_area:.1f} ext={ext_area:.1f}",
            )

    def test_cap_is_outer_half_of_extension(self):
        for index in COLLAR_EXTEND_INDICES:
            cap = self.all_body[index].cap
            mte_ext = self.all_mte[index].extension
            self.assertIsNotNone(cap)
            self.assertIsNotNone(mte_ext)
            ext_area = abs(mte_ext.area())
            cap_area = abs(cap.area())
            self.assertAlmostEqual(
                cap_area,
                ext_area / 2.0,
                delta=ext_area * 0.08,
                msg=f"index {index}",
            )

    def test_cap_has_outward_lip_beyond_mte(self):
        for index in COLLAR_EXTEND_INDICES:
            cap = self.all_body[index].cap
            mte_ext = self.all_mte[index].extension
            draw = self.all_mte[index].extension_draw
            self.assertIsNotNone(cap)
            self.assertIsNotNone(mte_ext)
            self.assertIsNotNone(draw)
            _, _, outward = _extension_outer_edge(mte_ext, draw)
            ox, oy = outward
            shift = self.body_cfg.cap_shift_um
            cap_pts = [(float(p[0]), float(p[1])) for p in cap.points]
            mte_pts = [(float(p[0]), float(p[1])) for p in mte_ext.points]
            cap_out = max(p[0] * ox + p[1] * oy for p in cap_pts)
            mte_out = max(p[0] * ox + p[1] * oy for p in mte_pts)
            self.assertAlmostEqual(
                cap_out - mte_out,
                shift,
                delta=0.15,
                msg=f"index {index}",
            )

    def test_filler_touches_cap_at_bridge(self):
        for index in COLLAR_EXTEND_INDICES:
            body = self.all_body[index]
            cap = body.cap
            self.assertIsNotNone(cap)
            self.assertTrue(
                gdstk.boolean(body.filler, cap, "and", precision=1e-3),
                msg=f"index {index}: filler should touch MBE cap",
            )

    def test_stadium_clearance_on_filler(self):
        cfg = self.body_cfg
        min_required = cfg.mbe_mte_min_spacing_um * cfg.stadium_clearance_factor - 0.5
        for index in COLLAR_EXTEND_INDICES:
            roles = self.all_roles[index]
            body = self.all_body[index]
            gap = _min_stadium_gap_outside_bridge(
                body.filler,
                roles.resonator_body_mte,
                body.bridge,
            )
            self.assertGreaterEqual(gap, min_required, msg=f"index {index} gap={gap:.2f}")

    def test_signal_route_separation(self):
        min_required = self.body_cfg.mbe_mte_min_spacing_um - 0.5
        for index in COLLAR_EXTEND_INDICES:
            signal = self.all_mbe[index].routed_net or self.all_mbe[index].extension
            self.assertIsNotNone(signal)
            gap = _min_gap_um(self.all_body[index].filler, [signal])
            self.assertGreaterEqual(gap, min_required, msg=f"index {index} gap={gap:.2f}")

    def test_cap_and_filler_are_separate_polygons(self):
        for index in COLLAR_EXTEND_INDICES:
            body = self.all_body[index]
            cap = body.cap
            self.assertIsNotNone(cap)
            self.assertTrue(body.filler, msg=f"index {index}")
            self.assertEqual(len(body.routed_net), len(body.filler) + 1, msg=f"index {index}")
            self.assertIs(body.routed_net[-1], cap, msg=f"index {index}")
            self.assertEqual(body.routed_net[:-1], body.filler, msg=f"index {index}")

    def test_export_body_includes_cap_and_filler(self):
        for index in COLLAR_EXTEND_INDICES:
            body = self.all_body[index]
            self.assertIsNotNone(body.cap)
            self.assertTrue(body.filler, msg=f"index {index}")
            self.assertEqual(
                len(body.routed_net),
                len(body.filler) + 1,
                msg=f"index {index}",
            )

    def test_export_includes_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = export_mte_extensions_gds(
                self.ctx["frame_assemblies"],
                self.all_mte,
                tmp,
                layermap=self.ctx["layermap"],
                mbe_extensions=self.all_mbe,
                mbe_bodies=self.all_body,
            )
            self.assertEqual(len(results), 8)
            mbe_pair = self.ctx["layermap"].pair("BAW_MBE")
            by_index = {r.index: r for r in results}
            for index in COLLAR_EXTEND_INDICES:
                gds_path = by_index[index].path
                lib = gdstk.read_gds(gds_path)
                mbe_polys = [
                    p
                    for cell in lib.cells
                    for p in cell.flatten().polygons
                    if (p.layer, p.datatype) == mbe_pair
                ]
                self.assertGreater(len(mbe_polys), 2, msg=f"index {index}")

    def test_overview_rows(self):
        inst_names = {i: r.inst_name for i, r in enumerate(self.ctx["res_list"])}
        rows = mbe_body_overview_rows(self.all_body, inst_names=inst_names)
        self.assertEqual(len(rows), 8)
        drawn = [r for r in rows if r["n_pieces"] > 0]
        self.assertEqual(len(drawn), 8)


if __name__ == "__main__":
    unittest.main()
