"""Step 5.4 — straighten release-hole keepout curves on MBE routes."""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import gdstk

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(SRC),):
    if p not in sys.path:
        sys.path.insert(0, p)

from prep_resonator_ppd import MIN_RELEASE_HOLE_CLEARANCE_UM  # noqa: E402
from rteg_route_clean import (  # noqa: E402
    RouteCleanConfig,
    clean_route_polygon_curves,
    find_release_keepout_notch_runs,
    rev_circle_specs,
)


def _arc_points(
    center: tuple[float, float],
    radius: float,
    a0_deg: float,
    a1_deg: float,
    n: int,
) -> list[tuple[float, float]]:
    cx, cy = center
    pts: list[tuple[float, float]] = []
    for i in range(n):
        t = a0_deg + (a1_deg - a0_deg) * i / (n - 1)
        rad = math.radians(t)
        pts.append((cx + radius * math.cos(rad), cy + radius * math.sin(rad)))
    return pts


def _rev_circle_at(center: tuple[float, float], radius: float = 7.5) -> gdstk.Polygon:
    return gdstk.Polygon(_arc_points(center, radius, 0.0, 360.0, 24), layer=37, datatype=0)


def _route_with_keepout_notch(
    center: tuple[float, float],
    *,
    rev_radius: float = 7.5,
    clearance_um: float = MIN_RELEASE_HOLE_CLEARANCE_UM,
) -> tuple[gdstk.Polygon, gdstk.Polygon]:
    zone_r = rev_radius + clearance_um
    notch = _arc_points(center, zone_r, 210.0, 330.0, 18)
    poly = gdstk.Polygon(
        [
            (center[0] - 60.0, center[1] - 20.0),
            (center[0] + 60.0, center[1] - 20.0),
            (center[0] + 60.0, center[1] + 40.0),
            *reversed(notch),
            (center[0] - 60.0, center[1] + 40.0),
        ],
        layer=2,
        datatype=0,
    )
    return poly, _rev_circle_at(center, rev_radius)


class RouteCleanTests(unittest.TestCase):
    def test_detects_keepout_ring_notch(self):
        center = (200.0, 200.0)
        route_poly, rev_poly = _route_with_keepout_notch(center)
        specs = rev_circle_specs([rev_poly])
        cfg = RouteCleanConfig()
        pts = [(float(x), float(y)) for x, y in route_poly.points]
        runs = find_release_keepout_notch_runs(
            pts, specs, MIN_RELEASE_HOLE_CLEARANCE_UM, cfg,
        )
        self.assertEqual(len(runs), 1)
        start, end = runs[0]
        self.assertGreaterEqual(end - start + 1, cfg.min_arc_vertices)

    def test_ignores_large_filler_arc_without_rev_anchor(self):
        filler_arc = _arc_points((0.0, 0.0), 50.0, 200.0, 340.0, 32)
        poly = gdstk.Polygon(
            [*filler_arc, (80.0, 0.0), (80.0, 80.0)],
            layer=2,
            datatype=0,
        )
        rev = _rev_circle_at((500.0, 500.0))
        runs = find_release_keepout_notch_runs(
            [(float(x), float(y)) for x, y in poly.points],
            rev_circle_specs([rev]),
            MIN_RELEASE_HOLE_CLEARANCE_UM,
        )
        self.assertEqual(runs, [])

    def test_straighten_keepout_notch_reduces_vertices(self):
        route_poly, rev_poly = _route_with_keepout_notch((150.0, 150.0))
        cleaned, res = clean_route_polygon_curves(
            route_poly, rev_circles=[rev_poly], clearance_um=MIN_RELEASE_HOLE_CLEARANCE_UM,
        )
        self.assertEqual(res.arcs_straightened, 1)
        self.assertLess(len(cleaned.points), len(route_poly.points))
        self.assertLessEqual(len(cleaned.points), 9)

    def test_skips_without_rev_circles(self):
        route_poly, _ = _route_with_keepout_notch((100.0, 100.0))
        cleaned, res = clean_route_polygon_curves(route_poly)
        self.assertEqual(len(cleaned.points), len(route_poly.points))
        self.assertEqual(res.arcs_straightened, 0)

    def test_skips_non_mbe_layer(self):
        route_poly, rev_poly = _route_with_keepout_notch((100.0, 100.0))
        route_poly = gdstk.Polygon(route_poly.points, layer=3, datatype=0)
        cleaned, res = clean_route_polygon_curves(
            route_poly, rev_circles=[rev_poly],
        )
        self.assertEqual(len(cleaned.points), len(route_poly.points))
        self.assertEqual(res.arcs_straightened, 0)


if __name__ == "__main__":
    unittest.main()
