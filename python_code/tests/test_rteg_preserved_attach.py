"""Step 4 — attach preserved filter interconnect to RTEG frames."""
from __future__ import annotations

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
from rteg_collect import (
    attach_preserved_filter_interconnect_all,
    preserved_interconnect_attach_rows,
)


class TestPreservedInterconnectAttachKB331(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.ctx = load_kb331_pipeline()
        except FileNotFoundError:
            raise unittest.SkipTest("KB331 input files not available")
        cls.preserved = attach_preserved_filter_interconnect_all(
            cls.ctx["frame_assemblies"],
            cls.ctx["res_list"],
            cls.ctx["identification"],
            cls.ctx["layermap"],
        )

    def test_all_indices_have_preserved_metal(self):
        self.assertEqual(len(self.preserved), 8)
        for index, preserved in self.preserved.items():
            self.assertGreaterEqual(len(preserved.mte), 1, msg=f"index {index}")
            self.assertGreaterEqual(len(preserved.mbe), 1, msg=f"index {index}")

    def test_polygons_on_top_cell(self):
        mte_pair = self.ctx["layermap"].pair("BAW_MTE")
        mbe_pair = self.ctx["layermap"].pair("BAW_MBE")
        for asm in self.ctx["frame_assemblies"]:
            preserved = self.preserved[asm.index]
            flat = asm.flatten()
            mte_polys = [
                p for p in flat.polygons if (p.layer, p.datatype) == mte_pair
            ]
            mbe_polys = [
                p for p in flat.polygons if (p.layer, p.datatype) == mbe_pair
            ]
            self.assertGreaterEqual(
                len(mte_polys),
                len(preserved.mte),
                msg=f"index {asm.index} missing attached MTE",
            )
            self.assertGreaterEqual(
                len(mbe_polys),
                len(preserved.mbe),
                msg=f"index {asm.index} missing attached MBE",
            )

    def test_export_includes_preserved_metal(self):
        from export_gds import export_gds_one

        asm = self.ctx["frame_assemblies"][6]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.gds"
            export_gds_one(asm, path=path, layermap=self.ctx["layermap"], flatten=True)
            lib = gdstk.read_gds(path)
            flat = lib.cells[0].flatten()
            mte_pair = self.ctx["layermap"].pair("BAW_MTE")
            n_mte = sum(
                1 for p in flat.polygons if (p.layer, p.datatype) == mte_pair
            )
            self.assertGreater(n_mte, 2, msg="flattened export should include filter MTE")

    def test_summary_rows(self):
        rows = preserved_interconnect_attach_rows(self.preserved)
        self.assertEqual(len(rows), 8)
        self.assertIn("n_preserved_mte", rows[0])


if __name__ == "__main__":
    unittest.main()
