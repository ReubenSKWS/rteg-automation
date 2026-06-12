"""Smoke test for series MTE margin/band sweep."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agentic.series_mte.config import SeriesMteExperimentConfig
from agentic.series_mte.context import build_series_mte_context
from agentic.series_mte.width_sweep import pick_sweep_best, run_width_sweep
from layermap import load_layermap
from prep_resonator_ppd import prep_resonator_ppd
from prep_rteg_frame import prep_rteg_in_frame
from rteg_classify import ClassifyNodesConfig, classify_nodes
from rteg_collect import RtegCollectConfig, collect_geometry_roles
from separate import identify

INPUT = Path(__file__).resolve().parents[1] / "input_files"


class TestSeriesMteSweep(unittest.TestCase):
    def test_sweep_smoke_idx3(self):
        layermap = load_layermap(INPUT / "layermap")
        id_result = identify(INPUT / "KB331_N_01.gds")
        import pandas as pd

        df = pd.DataFrame(id_result.resonator_rows())
        ppd = prep_resonator_ppd(df, id_result.resonators, INPUT / "GSG_frame.gds")
        rteg = prep_rteg_in_frame(ppd, INPUT / "KB331_N_Frame.gds")
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
        ctx = build_series_mte_context(
            idx, rteg[idx], res, id_result, classification, layermap
        )
        cfg = SeriesMteExperimentConfig(
            margin_candidates=(2.0, 3.0),
            band_candidates=(2.0,),
            series_indices=(idx,),
            artifacts_dir=Path("artifacts/mte_experiment_test"),
        )
        sweep_df = run_width_sweep({idx: ctx}, cfg)
        self.assertFalse(sweep_df.empty)
        picks = pick_sweep_best(sweep_df)
        self.assertIn(idx, picks)


if __name__ == "__main__":
    unittest.main()
