"""
KB331 MTE connection baseline ΓÇö golden layout contract for step 5.1 + 5.3.

Every resonator has two preserved MTE roles:
  - **Stadium** ΓÇö closed outline polygon (connectMTE stadium shell, ~5191 ┬╡m┬▓ on series parts).
  - **Collar** ΓÇö separate polygon boolean-touching the stadium (extension builds here).

Golden references (KB331):
  - **Shunt** indices 0/1 ΓÇö two small connectMTE tabs; extension on tab with body overlap.
  - **Series** index 6 ΓÇö stadium [5191] + interface collar [911]; extension on 911 only.

Any change to collection, collar selection, lip tracing, or ``is_connected`` must keep
these contracts green. Visual KLayout sign-off for index 6 is the authoritative check.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for p in (str(SRC), str(TESTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from kb331_pipeline import load_kb331_pipeline
from rteg_collect import PreservedMetal, collect_geometry_roles, polys_touch
from rteg_mte_extensions import (
    MteBuildConfig,
    _collar_overlap_area,
    _is_stadium_collar,
    build_mte_extensions,
    extension_is_connected,
    select_extension_collar,
)

# KB331 index 6 ΓÇö approved MTE connection baseline (series / stadium + collar).
SERIES_GOLDEN_INDEX = 6
SERIES_GOLDEN_PRESERVED_AREAS = [911, 5191]
SERIES_GOLDEN_COLLAR_AREA = 911.0
SERIES_GOLDEN_MIN_MOUTH_COVERAGE = 0.65

# KB331 indices 0/1 ΓÇö approved shunt-tab baseline.
SHUNT_GOLDEN_INDICES = (0, 1)
SHUNT_GOLDEN_MAX_COLLAR_AREA = 700.0
SHUNT_GOLDEN_MIN_MOUTH_COVERAGE = 0.85


def stadium_pieces(preserved: PreservedMetal, cfg: MteBuildConfig) -> list:
    return [tp for tp in preserved.mte if _is_stadium_collar(tp.polygon, cfg)]


def collar_touches_stadium(
    collar_poly: gdstk.Polygon,
    preserved: PreservedMetal,
    cfg: MteBuildConfig,
) -> bool:
    for tp in stadium_pieces(preserved, cfg):
        if polys_touch(collar_poly, tp.polygon, precision=cfg.boolean_precision):
            return True
    return False


def mouth_coverage_ratio(
    draw_mouth_span_um: float,
    collar_poly: gdstk.Polygon,
) -> float:
    bb = collar_poly.bounding_box()
    if bb is None:
        return 0.0
    (x0, y0), (x1, y1) = bb
    collar_width = max(x1 - x0, y1 - y0)
    if collar_width < 1e-6:
        return 0.0
    return draw_mouth_span_um / collar_width


class TestMtePlacementKB331(unittest.TestCase):
    """MTE connection and placement baseline tests (KB331)."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.ctx = load_kb331_pipeline()
        except FileNotFoundError:
            raise unittest.SkipTest("KB331 input files not available")
        cls.cfg = MteBuildConfig()

    def _build(self, index: int):
        roles = collect_geometry_roles(
            self.ctx["frame_assemblies"][index],
            self.ctx["res_list"][index],
            self.ctx["identification"],
            self.ctx["layermap"],
        )
        result = build_mte_extensions({index: roles}, self.ctx["layermap"], self.cfg)[index]
        return result, roles

    def _assert_series_baseline(
        self,
        index: int,
        roles,
        result,
        collar,
    ) -> None:
        assert result.extension is not None and result.extension_draw is not None
        assert collar is not None
        self.assertLess(
            collar.area_um2, self.cfg.stadium_collar_area_um2, msg=f"index {index}"
        )
        self.assertTrue(
            collar_touches_stadium(collar.polygon, roles.preserved, self.cfg),
            msg=f"index {index}: collar must touch stadium",
        )
        self.assertGreaterEqual(
            _collar_overlap_area(
                result.extension, collar.polygon, self.cfg.boolean_precision
            ),
            self.cfg.min_collar_overlap_um2,
            msg=f"index {index}",
        )
        self.assertTrue(
            extension_is_connected(
                result.extension, collar.polygon, result.extension_draw, self.cfg
            ),
            msg=f"index {index}: is_connected must match geometry",
        )
        self.assertTrue(result.is_connected, msg=f"index {index}")
        self.assertGreaterEqual(
            mouth_coverage_ratio(result.extension_draw.mouth_span_um, collar.polygon),
            SERIES_GOLDEN_MIN_MOUTH_COVERAGE,
            msg=f"index {index}",
        )

    def test_index6_golden_baseline_full_contract(self):
        """
        Primary MTE validation baseline ΓÇö resonator 6 (KB331 series).

        Collection: stadium [5191] + collar [911], collar touches stadium.
        Extension: on collar only, materially merged, mouth coverage >= 0.65.
        """
        result, roles = self._build(SERIES_GOLDEN_INDEX)
        areas = sorted(round(tp.area_um2) for tp in roles.preserved.mte)
        self.assertEqual(areas, SERIES_GOLDEN_PRESERVED_AREAS)

        collar = select_extension_collar(
            roles.preserved, roles.resonator_body_mte, self.cfg
        )
        assert collar is not None
        self.assertAlmostEqual(collar.area_um2, SERIES_GOLDEN_COLLAR_AREA, delta=5.0)
        self.assertEqual(result.collar, collar)

        self._assert_series_baseline(SERIES_GOLDEN_INDEX, roles, result, collar)

        bus_overlap = sum(
            _collar_overlap_area(result.extension, tp.polygon, self.cfg.boolean_precision)
            for tp in roles.preserved.mte
            if 1500.0 <= tp.area_um2 <= 2500.0
        )
        self.assertAlmostEqual(bus_overlap, 0.0, places=2)

    def test_series_indices_match_index6_baseline_contract(self):
        for index in (5, 6, 7):
            result, roles = self._build(index)
            collar = select_extension_collar(
                roles.preserved, roles.resonator_body_mte, self.cfg
            )
            assert collar is not None
            self._assert_series_baseline(index, roles, result, collar)

    def test_golden_shunt_indices_0_and_1(self):
        for index in SHUNT_GOLDEN_INDICES:
            result, roles = self._build(index)
            assert result.extension_draw is not None and result.collar is not None
            collar_area = abs(result.collar.polygon.area())
            self.assertLess(collar_area, SHUNT_GOLDEN_MAX_COLLAR_AREA)
            mouth = mouth_coverage_ratio(
                result.extension_draw.mouth_span_um, result.collar.polygon
            )
            self.assertGreaterEqual(mouth, SHUNT_GOLDEN_MIN_MOUTH_COVERAGE)
            self.assertTrue(
                extension_is_connected(
                    result.extension,
                    result.collar.polygon,
                    result.extension_draw,
                    self.cfg,
                ),
                msg=f"index {index}",
            )
            self.assertTrue(result.is_connected, msg=f"index {index}")


if __name__ == "__main__":
    unittest.main()
