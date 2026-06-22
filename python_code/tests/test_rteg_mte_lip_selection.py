"""Unit tests for MTE lip edge selection and collar picking heuristics."""
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

from rteg_collect import PreservedMetal, TaggedPolygon
from rteg_mte_extensions import (
    MteBuildConfig,
    _feasible_merge_um,
    find_outward_lip_ab,
    select_extension_collar,
)


class TestLipSelectionSynthetic(unittest.TestCase):
    def test_lip_prefers_merge_feasible_bottom_edge_over_vertical(self):
        """
        Collar tab with a short exterior vertical edge and a wider bottom edge
        toward the body ΓÇö merge scoring must pick the bottom mouth.
        """
        collar = gdstk.Polygon(
            [
                (200.0, 316.0),
                (245.0, 304.0),
                (242.0, 321.0),
                (208.0, 321.0),
            ],
            layer=5,
            datatype=0,
        )
        body = [
            gdstk.Polygon(
                [(150.0, 268.0), (250.0, 268.0), (250.0, 316.0), (150.0, 316.0)],
                layer=5,
                datatype=0,
            )
        ]
        signal = [
            gdstk.rectangle((80.0, 280.0), (170.0, 320.0), layer=5, datatype=0)
        ]
        cfg = MteBuildConfig()
        lip = find_outward_lip_ab(collar, body, cfg, signal_polys=signal)
        outward = lip.outward_normal
        merge_a = _feasible_merge_um(
            lip.point_a,
            outward,
            collar,
            cfg.collar_merge_inset_um,
            precision=cfg.boolean_precision,
            probe_half_um=cfg.inside_probe_half_um,
            search_iterations=cfg.feasible_merge_search_iterations,
        )
        merge_b = _feasible_merge_um(
            lip.point_b,
            outward,
            collar,
            cfg.collar_merge_inset_um,
            precision=cfg.boolean_precision,
            probe_half_um=cfg.inside_probe_half_um,
            search_iterations=cfg.feasible_merge_search_iterations,
        )
        self.assertGreaterEqual(min(merge_a, merge_b), cfg.min_connection_merge_um)
        self.assertGreater(lip.point_a[1], lip.point_b[1])

    def test_stadium_swap_requires_edge_collar_body_overlap(self):
        """Unassociated edge tabs without body overlap must not displace the stadium."""
        stadium = gdstk.Polygon(
            [(0.0, 0.0), (100.0, 0.0), (100.0, 60.0), (0.0, 60.0)],
            layer=5,
            datatype=0,
        )
        orphan = gdstk.Polygon(
            [(200.0, 10.0), (220.0, 10.0), (220.0, 30.0), (200.0, 30.0)],
            layer=5,
            datatype=0,
        )
        body = [
            gdstk.Polygon(
                [(10.0, 10.0), (90.0, 10.0), (90.0, 50.0), (10.0, 50.0)],
                layer=5,
                datatype=0,
            )
        ]
        preserved = PreservedMetal(
            mte=[
                TaggedPolygon("orphan", "BAW_MTE", orphan),
                TaggedPolygon("stadium", "BAW_MTE", stadium),
            ],
            mbe=[],
        )
        cfg = MteBuildConfig(
            stadium_collar_area_um2=2500.0,
            stadium_edge_area_ratio=0.6,
            collar_association_gap_um=35.0,
        )
        collar = select_extension_collar(preserved, body, cfg)
        assert collar is not None
        self.assertAlmostEqual(abs(collar.polygon.area()), 6000.0, delta=1.0)

    def test_touching_small_tab_preferred_over_stadium(self):
        stadium = gdstk.Polygon(
            [(0.0, 0.0), (100.0, 0.0), (100.0, 60.0), (0.0, 60.0)],
            layer=5,
            datatype=0,
        )
        edge_tab = gdstk.Polygon(
            [(99.0, 20.0), (115.0, 20.0), (115.0, 35.0), (99.0, 35.0)],
            layer=5,
            datatype=0,
        )
        body = [
            gdstk.Polygon(
                [(10.0, 10.0), (90.0, 10.0), (90.0, 50.0), (10.0, 50.0)],
                layer=5,
                datatype=0,
            )
        ]
        preserved = PreservedMetal(
            mte=[
                TaggedPolygon("edge", "BAW_MTE", edge_tab),
                TaggedPolygon("stadium", "BAW_MTE", stadium),
            ],
            mbe=[],
        )
        collar = select_extension_collar(preserved, body, MteBuildConfig())
        assert collar is not None
        self.assertAlmostEqual(abs(collar.polygon.area()), 240.0, delta=5.0)

    def test_disjoint_bus_near_stadium_falls_back_to_stadium(self):
        stadium = gdstk.Polygon(
            [(0.0, 0.0), (100.0, 0.0), (100.0, 60.0), (0.0, 60.0)],
            layer=5,
            datatype=0,
        )
        bus = gdstk.Polygon(
            [(30.0, 91.0), (70.0, 91.0), (70.0, 111.0), (30.0, 111.0)],
            layer=5,
            datatype=0,
        )
        body = [
            gdstk.Polygon(
                [(10.0, 10.0), (90.0, 10.0), (90.0, 50.0), (10.0, 50.0)],
                layer=5,
                datatype=0,
            )
        ]
        preserved = PreservedMetal(
            mte=[
                TaggedPolygon("bus", "BAW_MTE", bus),
                TaggedPolygon("stadium", "BAW_MTE", stadium),
            ],
            mbe=[],
        )
        collar = select_extension_collar(
            preserved,
            body,
            MteBuildConfig(stadium_collar_area_um2=2500.0),
        )
        assert collar is not None
        self.assertAlmostEqual(abs(collar.polygon.area()), 6000.0, delta=1.0)


if __name__ == "__main__":
    unittest.main()
