"""Geometry checks for preserved-collar MTE extension drawing."""
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
from rteg_collect import TaggedPolygon
from rteg_mte_extensions import (
    MteBuildConfig,
    draw_collar_extension,
    find_outward_lip_ab,
)


def _body_below_collar(collar: gdstk.Polygon) -> list[gdstk.Polygon]:
    """Synthetic resonator-body MTE under the collar (for unit tests)."""
    xmin, ymin = collar.bounding_box()[0]
    xmax, ymax = collar.bounding_box()[1]
    return [
        gdstk.Polygon(
            [
                (xmin, ymin - 20.0),
                (xmax, ymin - 20.0),
                (xmax, ymin),
                (xmin, ymin),
            ],
            layer=collar.layer,
            datatype=collar.datatype,
        )
    ]


def _outer_edge_is_straight(poly: gdstk.Polygon) -> bool:
    pts = poly.points
    if len(pts) < 4:
        return False
    o0 = (float(pts[-1][0]), float(pts[-1][1]))
    o1 = (float(pts[-2][0]), float(pts[-2][1]))
    return math.hypot(o1[0] - o0[0], o1[1] - o0[1]) > 1e-6


class TestPreservedMteExtensionShape(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.layermap = load_kb331_pipeline()["layermap"]
        except FileNotFoundError:
            raise unittest.SkipTest("KB331 input files not available")

    def test_rectangular_collar_intercepts_at_mouth_corners(self):
        collar = gdstk.Polygon(
            [(0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0)],
            layer=5,
            datatype=0,
        )
        body = _body_below_collar(collar)
        lip = find_outward_lip_ab(collar, body)
        self.assertAlmostEqual(lip.point_a[0], 20.0)
        self.assertAlmostEqual(lip.point_a[1], 10.0)
        self.assertAlmostEqual(lip.point_b[0], 0.0)
        self.assertAlmostEqual(lip.point_b[1], 10.0)
        self.assertAlmostEqual(lip.outward_normal[1], 1.0, places=3)
        merge = MteBuildConfig().collar_merge_inset_um
        for pt in (
            (lip.point_a[0], lip.point_a[1] - merge),
            (lip.point_b[0], lip.point_b[1] - merge),
        ):
            probe = gdstk.rectangle(
                (pt[0] - 0.25, pt[1] - 0.25), (pt[0] + 0.25, pt[1] + 0.25)
            )
            self.assertTrue(gdstk.boolean(probe, collar, "and", precision=1e-3))

    def test_rectangular_collar_has_four_sided_extension(self):
        collar = gdstk.Polygon(
            [(0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0)],
            layer=5,
            datatype=0,
        )
        body = _body_below_collar(collar)
        tp = TaggedPolygon("test", "BAW_MTE", collar)
        ext = draw_collar_extension(
            tp, self.layermap, MteBuildConfig(), body_mte_polys=body
        ).polygon
        self.assertGreaterEqual(len(ext.points), 4)
        self.assertTrue(gdstk.boolean(ext, collar, "and", precision=1e-3))
        self.assertTrue(_outer_edge_is_straight(ext))

    def test_curved_collar_inner_chain_on_boundary(self):
        collar = gdstk.Polygon(
            [
                (100.0, 0.0),
                (110.0, 5.0),
                (120.0, 0.0),
                (120.0, -3.0),
                (100.0, -3.0),
            ],
            layer=5,
            datatype=0,
        )
        body = _body_below_collar(collar)
        tp = TaggedPolygon("test", "BAW_MTE", collar)
        ext = draw_collar_extension(
            tp, self.layermap, MteBuildConfig(), body_mte_polys=body
        ).polygon
        self.assertGreaterEqual(len(ext.points), 4)
        self.assertTrue(gdstk.boolean(ext, collar, "and", precision=1e-3))
        self.assertTrue(_outer_edge_is_straight(ext))


if __name__ == "__main__":
    unittest.main()
