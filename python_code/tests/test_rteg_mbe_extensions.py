"""Step 6.1 ΓÇö MBE pad-to-collar connection."""
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
from rteg_classify import classify_nodes
from rteg_collect import TaggedPolygon, collect_geometry_roles, collect_orientation_inputs
from rteg_mbe_extensions import (
    MbeConnectionConfig,
    build_mbe_extensions,
    draw_mbe_pad_connection,
    mbe_extensions_overview_rows,
)
from rteg_mte_extensions import MteBuildConfig, build_mte_extensions, export_mte_extensions_gds

COLLAR_EXTEND_INDICES = (0, 2, 5, 7)
CENTER_PAD_INDICES = (1, 3, 4, 6)

# Golden collar hits after fillet-cluster detection + Y-sweep stretch (KB331).
KB331_EXPECTED_HITS: dict[int, tuple[tuple[float, float], tuple[float, float]]] = {
    0: ((172.422, 314.858), (151.486, 262.000)),
    2: ((186.731, 318.124), (148.844, 304.932)),
    5: ((193.239, 337.052), (159.797, 293.302)),
    7: ((157.084, 267.576), (176.857, 236.142)),
}


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


def _assert_hit_on_collar(
    test: unittest.TestCase,
    hit: tuple[float, float],
    collar: gdstk.Polygon,
    *,
    label: str,
) -> None:
    on_boundary = _dist_point_to_polygon(hit, collar) <= 0.01
    on_vertex = any(
        abs(float(v[0]) - hit[0]) < 0.01 and abs(float(v[1]) - hit[1]) < 0.01
        for v in collar.points
    )
    test.assertTrue(on_boundary or on_vertex, f"{label} {hit} should sit on collar")


def _assert_connection_draw(
    test: unittest.TestCase,
    draw,
    *,
    index: int | None = None,
) -> None:
    label = f"index {index}" if index is not None else "connection"
    test.assertGreater(draw.hit_a[1], draw.hit_b[1], label)
    test.assertGreater(draw.hit_a[0], draw.point_a[0] - 1.0, label)
    test.assertGreater(draw.hit_b[0], draw.point_b[0] - 1.0, label)
    test.assertGreater(
        math.hypot(draw.hit_a[0] - draw.hit_b[0], draw.hit_a[1] - draw.hit_b[1]),
        1.0,
        f"{label}: top and bottom collar bends should differ",
    )


class TestMbeConnectionSynthetic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.layermap = load_kb331_pipeline()["layermap"]
        cls.layer, cls.datatype = cls.layermap.pair("BAW_MBE")
        cls.cfg = MbeConnectionConfig()

    def _draw(self, collar: gdstk.Polygon, pad: gdstk.Polygon):
        return draw_mbe_pad_connection(
            TaggedPolygon("collar", "BAW_MBE", collar),
            [pad],
            self.layermap,
            self.cfg,
        )

    def test_rectangle_collar_fallback_hits(self):
        """No fillet clusters ΓÇö fallback ray picks pad-facing rectangle corners."""
        collar = gdstk.rectangle(
            (40.0, 45.0), (55.0, 55.0), layer=self.layer, datatype=self.datatype
        )
        pad = gdstk.rectangle(
            (10.0, 47.0), (38.0, 53.0), layer=self.layer, datatype=self.datatype
        )
        connection, draw = self._draw(collar, pad)

        self.assertGreaterEqual(len(connection.points), 4)
        self.assertEqual(draw.point_a, (38.0, 53.0))
        self.assertEqual(draw.point_b, (38.0, 47.0))
        self.assertAlmostEqual(draw.hit_a[0], 55.0, places=2)
        self.assertAlmostEqual(draw.hit_a[1], 55.0, places=2)
        self.assertAlmostEqual(draw.hit_b[0], 47.5, places=2)
        self.assertAlmostEqual(draw.hit_b[1], 50.0, places=2)
        _assert_connection_draw(self, draw)

    def test_filleted_collar_cluster_stretch_hits(self):
        """Fillet vertex cluster ΓÇö Y-sweep stretch reaches the inner mouth corner."""
        collar_pts = [
            (90.0, 320.0),
            (90.0, 255.0),
            (103.0, 273.0),
            (103.5, 273.5),
            (105.5, 268.0),
            (106.5, 267.0),
            (108.5, 266.4),
            (142.0, 266.3),
            (155.0, 266.3),
            (159.0, 262.0),
            (175.0, 248.0),
            (200.0, 240.0),
            (250.0, 240.0),
            (250.0, 320.0),
            (180.0, 320.0),
            (180.0, 315.0),
            (250.0, 315.0),
        ]
        collar = gdstk.Polygon(collar_pts, layer=self.layer, datatype=self.datatype)
        pad = gdstk.rectangle(
            (10.0, 255.0), (38.0, 285.0), layer=self.layer, datatype=self.datatype
        )
        _, draw = self._draw(collar, pad)

        self.assertAlmostEqual(draw.hit_a[0], 250.0, places=2)
        self.assertAlmostEqual(draw.hit_a[1], 320.0, places=2)
        self.assertAlmostEqual(draw.hit_b[0], 175.0, places=2)
        self.assertAlmostEqual(draw.hit_b[1], 248.0, places=2)
        _assert_connection_draw(self, draw)
        _assert_hit_on_collar(self, draw.hit_a, collar, label="hit_a")
        _assert_hit_on_collar(self, draw.hit_b, collar, label="hit_b")


class TestMbeExtensionsKB331(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ctx = load_kb331_pipeline()
        except FileNotFoundError:
            raise unittest.SkipTest("KB331 input files not available")
        cls.cfg = MbeConnectionConfig()
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
            cls.all_roles[asm.index] = roles
            cls.all_classify[asm.index] = classify_nodes(
                roles.ground_plates,
                roles.preserved,
                orientation=orientation,
                res_type=res.res_type,
            )
        cls.extensions = build_mbe_extensions(
            cls.all_roles,
            cls.all_classify,
            cls.ctx["layermap"],
            cls.cfg,
        )
        cls.all_mte = build_mte_extensions(
            cls.all_roles,
            cls.ctx["layermap"],
            MteBuildConfig(),
        )

    def test_collar_extend_indices_have_connection(self):
        mbe_pair = self.ctx["layermap"].pair("BAW_MBE")
        for index in COLLAR_EXTEND_INDICES:
            result = self.extensions[index]
            classification = self.all_classify[index]
            self.assertFalse(classification.collar_orientation.mte_faces_center)
            self.assertEqual(result.n_extensions, 1, f"index {index}")
            assert result.extension is not None
            assert result.collar is not None
            assert result.connection_draw is not None

            self.assertGreaterEqual(len(result.extension.points), 4)
            if index == 0:
                self.assertGreater(
                    len(result.extension.points),
                    10,
                    "index 0 mouth should trace the filleted collar edge",
                )
            self.assertEqual(
                (result.extension.layer, result.extension.datatype),
                mbe_pair,
            )
            _assert_connection_draw(self, result.connection_draw, index=index)

    def test_center_pad_indices_not_routed(self):
        for index in CENTER_PAD_INDICES:
            result = self.extensions[index]
            classification = self.all_classify[index]
            self.assertTrue(classification.collar_orientation.mte_faces_center)
            self.assertEqual(classification.mte_route_target, "center_pad")
            self.assertEqual(result.n_extensions, 0, f"index {index}")
            self.assertIsNone(result.extension)
            self.assertIsNone(result.connection_draw)

    def test_kb331_collar_extend_hits(self):
        for index, (expected_a, expected_b) in KB331_EXPECTED_HITS.items():
            result = self.extensions[index]
            assert result.collar is not None
            draw = result.connection_draw
            assert draw is not None

            self.assertAlmostEqual(draw.hit_a[0], expected_a[0], places=2, msg=f"index {index}")
            self.assertAlmostEqual(draw.hit_a[1], expected_a[1], places=2, msg=f"index {index}")
            self.assertAlmostEqual(draw.hit_b[0], expected_b[0], places=2, msg=f"index {index}")
            self.assertAlmostEqual(draw.hit_b[1], expected_b[1], places=1, msg=f"index {index}")

            _assert_hit_on_collar(
                self, draw.hit_a, result.collar.polygon, label=f"index {index} hit_a"
            )
            _assert_hit_on_collar(
                self, draw.hit_b, result.collar.polygon, label=f"index {index} hit_b"
            )

    def test_combined_mte_mbe_gds_export(self):
        with tempfile.TemporaryDirectory() as td:
            results = export_mte_extensions_gds(
                self.ctx["frame_assemblies"],
                self.all_mte,
                td,
                layermap=self.ctx["layermap"],
                mbe_extensions=self.extensions,
            )
            self.assertGreaterEqual(len(results), 4)
            by_idx = {r.index: r.path for r in results}
            lib = gdstk.read_gds(str(by_idx[0]))
            flat = lib.top_level()[0].flatten()
            pairs = {(p.layer, p.datatype) for p in flat.polygons}
            self.assertIn(self.ctx["layermap"].pair("BAW_MTE"), pairs)
            self.assertIn(self.ctx["layermap"].pair("BAW_MBE"), pairs)

    def test_overview_rows_have_connection_fields(self):
        rows = mbe_extensions_overview_rows(self.extensions)
        active = [r for r in rows if r["n_extensions"] == 1]
        self.assertEqual(len(active), len(COLLAR_EXTEND_INDICES))
        for row in active:
            self.assertIsNotNone(row["point_a"])
            self.assertIsNotNone(row["point_b"])
            self.assertIsNotNone(row["hit_a"])
            self.assertIsNotNone(row["hit_b"])
            self.assertGreater(row["area_um2"], 0.0)


if __name__ == "__main__":
    unittest.main()
