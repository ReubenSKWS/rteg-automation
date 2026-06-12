"""Regression: series on-resonator MTE vs shunt pad routing (KB331)."""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import gdstk
import pandas as pd

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from layermap import load_layermap
from prep_resonator_ppd import prep_resonator_ppd
from prep_rteg_frame import prep_rteg_in_frame
from rteg_collect import RtegCollectConfig, collect_geometry_roles
from rteg_classify import ClassifyNodesConfig, classify_nodes
from rteg_series_mte import _resonator_mbe_body
from rteg_signal import SignalBuildConfig, build_signal_net
from separate import identify

INPUT = Path(__file__).resolve().parents[1] / "input_files"
PAD_ROUTE_SHAPES = {"straight", "route_L", "route_45", "route_Z"}
KB331_SERIES_INDICES = (2, 3, 6, 7)


def _kb331_pipeline():
    layermap = load_layermap(INPUT / "layermap")
    id_result = identify(INPUT / "KB331_N_01.gds")
    df = pd.DataFrame(id_result.resonator_rows())
    ppd = prep_resonator_ppd(df, id_result.resonators, INPUT / "GSG_frame.gds")
    rteg = prep_rteg_in_frame(ppd, INPUT / "KB331_N_Frame.gds")
    return layermap, id_result, rteg


def _build_one(index: int):
    layermap, id_result, rteg = _kb331_pipeline()
    res = id_result.resonators[index]
    roles = collect_geometry_roles(
        rteg[index], res, id_result, layermap, RtegCollectConfig()
    )
    classification = classify_nodes(
        roles.ground_plates,
        roles.preserved,
        res_type=res.res_type,
        config=ClassifyNodesConfig(),
    )
    signal = build_signal_net(
        roles.preserved,
        classification,
        roles.ground_plates,
        layermap,
        config=SignalBuildConfig(),
        res=res,
        assembly=rteg[index],
        release_holes=roles.release_holes,
    )
    return res, roles, rteg[index], classification, signal


def _min_spacing(poly_a: gdstk.Polygon, poly_b: gdstk.Polygon) -> float:
    if gdstk.boolean(poly_a, poly_b, "and", precision=1e-3):
        return 0.0
    best = float("inf")
    for pa in poly_a.points:
        for pb in poly_b.points:
            best = min(best, math.hypot(pa[0] - pb[0], pa[1] - pb[1]))
    return best


class TestRtegSignalSeries(unittest.TestCase):
    def test_series_on_resonator_no_pad_connector(self):
        """Series must not build a pad-directed connector (regression)."""
        res, _, _, classification, signal = _build_one(2)

        self.assertEqual(res.res_type, "series")
        self.assertEqual(classification.signal_band, "on_resonator")
        self.assertTrue(all(n.net == "ground" for n in classification.nodes))
        self.assertEqual(signal.connector.shape_name, "on_resonator")
        self.assertGreaterEqual(len(signal.connector.centerline), 2)
        self.assertTrue(signal.is_connected)
        self.assertGreater(signal.n_net_polygons, 0)
        self.assertFalse(signal.reaches_pad)
        self.assertEqual(signal.signal_pad_polygons, [])

    def test_series_boundary_strip(self):
        """Series strip is thin, has an arc centerline, and avoids release holes."""
        res, roles, assembly, _, signal = _build_one(2)
        cfg = SignalBuildConfig()
        body = _resonator_mbe_body(res, assembly, cfg.boolean_precision)
        strip = signal.net_polygons[0]
        strip_area = abs(strip.area())

        self.assertLess(strip_area, 2000.0)
        self.assertLess(strip_area, 0.1 * abs(body.area()))
        self.assertGreaterEqual(len(signal.connector.centerline), 2)
        for tagged in roles.release_holes.all_items():
            self.assertFalse(
                gdstk.boolean(strip, tagged.polygon, "and", precision=cfg.boolean_precision),
                f"strip overlaps {tagged.label}",
            )

    def test_series_endpoints_at_holes(self):
        """Strip centerline endpoints sit on the two anchor release holes."""
        _, roles, _, _, signal = _build_one(2)
        strip = signal.net_polygons[0]
        cl = signal.connector.centerline
        touching = []
        for tagged in roles.release_holes.all_items():
            if gdstk.boolean(
                strip,
                tagged.polygon,
                "and",
                precision=SignalBuildConfig().boolean_precision,
            ):
                continue
            d0 = _min_spacing(
                gdstk.rectangle(
                    (cl[0][0] - 1.0, cl[0][1] - 1.0),
                    (cl[0][0] + 1.0, cl[0][1] + 1.0),
                    layer=strip.layer,
                    datatype=strip.datatype,
                ),
                tagged.polygon,
            )
            d1 = _min_spacing(
                gdstk.rectangle(
                    (cl[-1][0] - 1.0, cl[-1][1] - 1.0),
                    (cl[-1][0] + 1.0, cl[-1][1] + 1.0),
                    layer=strip.layer,
                    datatype=strip.datatype,
                ),
                tagged.polygon,
            )
            if d0 <= 1.0:
                touching.append((0, tagged.label, d0))
            if d1 <= 1.0:
                touching.append((-1, tagged.label, d1))
        self.assertTrue(touching, "no release hole within 1um of strip endpoints")
        start_holes = [t for t in touching if t[0] == 0]
        end_holes = [t for t in touching if t[0] == -1]
        self.assertTrue(start_holes)
        self.assertTrue(end_holes)

    def test_shunt_pad_route_unchanged(self):
        """Shunt still routes to center signal pad."""
        res, _, _, classification, signal = _build_one(0)

        self.assertEqual(res.res_type, "shunt")
        self.assertEqual(classification.signal_band, "center")
        self.assertIn(signal.connector.shape_name, PAD_ROUTE_SHAPES)
        self.assertGreaterEqual(len(signal.connector.centerline), 2)
        self.assertTrue(signal.is_connected)
        self.assertTrue(signal.reaches_pad)

    def test_all_kb331_series_build(self):
        """All KB331 series resonators build a perimeter strip without error."""
        for index in KB331_SERIES_INDICES:
            with self.subTest(index=index):
                res, _, _, _, signal = _build_one(index)
                self.assertEqual(res.res_type, "series")
                self.assertEqual(signal.connector.shape_name, "on_resonator")
                self.assertGreaterEqual(len(signal.connector.centerline), 2)
                self.assertGreater(signal.n_net_polygons, 0)

    def test_series_narrow_width_builds(self):
        """2 µm outward offset ring builds and passes invariants on KB331 index 3."""
        layermap, id_result, rteg = _kb331_pipeline()
        idx = 3
        res = id_result.resonators[idx]
        roles = collect_geometry_roles(
            rteg[idx], res, id_result, layermap, RtegCollectConfig()
        )
        classification = classify_nodes(
            roles.ground_plates,
            roles.preserved,
            res_type=res.res_type,
            config=ClassifyNodesConfig(),
        )
        from rteg_signal import _ground_mbe_obstacles
        from rteg_series_mte import build_series_strip, _verify_series_boundary_invariants

        cfg = SignalBuildConfig()
        ground = list(
            _ground_mbe_obstacles(classification, roles.ground_plates, layermap, cfg)
        )
        result = build_series_strip(
            res,
            rteg[idx],
            roles.release_holes,
            layermap,
            cfg,
            margin_um=2.0,
            band_thickness_um=2.0,
            build_mode="offset_ring",
            apply_drc_finalize=True,
            ground_obstacles=ground,
            verify=True,
        )
        self.assertAlmostEqual(result.band_thickness_um, 2.0)
        self.assertEqual(result.build_mode, "offset_ring")
        self.assertLess(result.body_overlap_fraction, 0.05)
        _verify_series_boundary_invariants(
            result.strip,
            result.centerline,
            result.body,
            result.hole_a,
            result.hole_b,
            roles.release_holes.all_items(),
            res,
            cfg,
            build_mode="offset_ring",
        )

    def test_series_narrow_width_drc_idx2(self):
        """2 µm ring on idx 2 may still violate filler-side DRC without finalize."""
        layermap, id_result, rteg = _kb331_pipeline()
        idx = 2
        res = id_result.resonators[idx]
        roles = collect_geometry_roles(
            rteg[idx], res, id_result, layermap, RtegCollectConfig()
        )
        classification = classify_nodes(
            roles.ground_plates,
            roles.preserved,
            res_type=res.res_type,
            config=ClassifyNodesConfig(),
        )
        from rteg_signal import _ground_mbe_obstacles
        from rteg_series_mte import build_series_strip

        cfg = SignalBuildConfig()
        ground = list(
            _ground_mbe_obstacles(classification, roles.ground_plates, layermap, cfg)
        )
        result = build_series_strip(
            res,
            rteg[idx],
            roles.release_holes,
            layermap,
            cfg,
            margin_um=2.0,
            band_thickness_um=2.0,
            build_mode="offset_ring",
            apply_drc_finalize=True,
            ground_obstacles=ground,
            verify=True,
        )
        self.assertLess(result.body_overlap_fraction, 0.05)
        self.assertTrue(result.is_drc_clean)


if __name__ == "__main__":
    unittest.main()
