"""Unit tests for rteg_orientation geometry helpers (synthetic polygons)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import gdstk

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rteg_orientation import (
    analyze_orientation,
    bbox_summary,
    collar_axis,
    mte_faces_center_pad,
    mte_faces_signal_pad,
    mte_opposite_center_pad_east_west,
    pad_facing_direction,
    recommend_placement_shift,
)


def _rect(x0: float, y0: float, x1: float, y1: float) -> gdstk.Polygon:
    return gdstk.rectangle((x0, y0), (x1, y1), layer=5, datatype=0)


# Three GSG pads stacked along Y at x ~ 200, resonator body near origin.
PADS = {
    "top": ((180.0, 300.0), (220.0, 340.0)),
    "center": ((180.0, 140.0), (220.0, 180.0)),
    "bottom": ((180.0, -40.0), (220.0, 0.0)),
}


class TestBboxSummary(unittest.TestCase):
    def test_summary_fields(self):
        s = bbox_summary(_rect(0.0, 0.0, 10.0, 4.0))
        assert s is not None
        self.assertEqual(s.center, (5.0, 2.0))
        self.assertEqual(s.width, 10.0)
        self.assertEqual(s.height, 4.0)

    def test_summary_sequence_union(self):
        s = bbox_summary([_rect(0.0, 0.0, 2.0, 2.0), _rect(8.0, 6.0, 10.0, 10.0)])
        assert s is not None
        self.assertEqual(s.min_xy, (0.0, 0.0))
        self.assertEqual(s.max_xy, (10.0, 10.0))

    def test_summary_empty(self):
        self.assertIsNone(bbox_summary([]))


class TestCollarAxis(unittest.TestCase):
    def test_wide_collar_is_east_west(self):
        mte = bbox_summary(_rect(0.0, 0.0, 40.0, 10.0))
        body = bbox_summary(_rect(0.0, 0.0, 50.0, 50.0))
        self.assertEqual(collar_axis(mte, None, body), "east_west")

    def test_tall_collar_is_north_south(self):
        mte = bbox_summary(_rect(0.0, 0.0, 10.0, 40.0))
        body = bbox_summary(_rect(0.0, 0.0, 50.0, 50.0))
        self.assertEqual(collar_axis(mte, None, body), "north_south")


class TestPadFacing(unittest.TestCase):
    def test_collar_near_top_pad(self):
        collar = bbox_summary(_rect(150.0, 305.0, 175.0, 335.0))
        self.assertEqual(pad_facing_direction(collar, PADS), "top")

    def test_collar_near_bottom_pad(self):
        collar = bbox_summary(_rect(150.0, -35.0, 175.0, -5.0))
        self.assertEqual(pad_facing_direction(collar, PADS), "bottom")

    def test_mte_faces_center_rejects_when_closer_to_body(self):
        """MTE near body center but Y aligns with center band → collar_extend."""
        body = bbox_summary(_rect(140.0, 250.0, 260.0, 330.0))
        mte = bbox_summary(_rect(200.0, 300.0, 245.0, 318.0))
        assert body is not None and mte is not None
        self.assertTrue(
            mte_opposite_center_pad_east_west(mte, body, PADS["center"])
        )
        self.assertFalse(
            mte_faces_center_pad(
                mte, PADS, body_bbox=body, axis="east_west"
            )
        )

    def test_mte_faces_center_when_closer_to_pad_than_body(self):
        body = bbox_summary(_rect(140.0, 250.0, 260.0, 330.0))
        pads = {
            "top": ((80.0, 300.0), (120.0, 340.0)),
            "center": ((80.0, 278.0), (120.0, 302.0)),
            "bottom": ((80.0, 100.0), (120.0, 140.0)),
        }
        mte = bbox_summary(_rect(125.0, 283.0, 148.0, 297.0))
        assert body is not None and mte is not None
        self.assertTrue(
            mte_faces_center_pad(
                mte, pads, body_bbox=body, axis="east_west"
            )
        )

    def test_mte_faces_center_distance_rule_synthetic(self):
        body = bbox_summary(_rect(100.0, 100.0, 200.0, 200.0))
        mte = bbox_summary(_rect(175.0, 155.0, 195.0, 165.0))
        assert body is not None and mte is not None
        self.assertTrue(
            mte_faces_center_pad(mte, PADS, body_bbox=body)
        )

    def test_mte_faces_signal_pad_alias(self):
        toward_top = bbox_summary(_rect(150.0, 305.0, 175.0, 335.0))
        self.assertFalse(
            mte_faces_signal_pad(toward_top, "top", PADS, mte_polys=[_rect(150.0, 305.0, 175.0, 335.0)])
        )


class TestPlacementShift(unittest.TestCase):
    def test_east_west_no_shift(self):
        collar = bbox_summary(_rect(150.0, 150.0, 190.0, 165.0))
        body = bbox_summary(_rect(100.0, 140.0, 180.0, 180.0))
        self.assertEqual(
            recommend_placement_shift("east_west", collar, PADS["center"], body),
            (0.0, 0.0),
        )

    def test_north_south_aligns_collar_to_pad_center(self):
        collar = bbox_summary(_rect(150.0, 100.0, 165.0, 140.0))  # center y = 120
        body = bbox_summary(_rect(100.0, 90.0, 180.0, 170.0))
        dx, dy = recommend_placement_shift(
            "north_south", collar, PADS["center"], body
        )
        self.assertEqual(dx, 0.0)
        self.assertAlmostEqual(dy, 160.0 - 120.0)  # pad center y 160


class TestAnalyzeOrientation(unittest.TestCase):
    def test_end_to_end_top_facing_ground_route(self):
        body = [_rect(120.0, 120.0, 200.0, 200.0)]
        mte = [_rect(150.0, 305.0, 175.0, 335.0)]  # toward top pad
        mbe = [_rect(150.0, -35.0, 175.0, -5.0)]
        analysis = analyze_orientation(body, mte, mbe, PADS)
        self.assertEqual(analysis.collar.facing_pad, "top")
        self.assertFalse(analysis.collar.mte_faces_center)
        self.assertEqual(analysis.collar.mte_route_target, "collar_extend")


if __name__ == "__main__":
    unittest.main()
