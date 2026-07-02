"""Shared KB331 fixture for integration tests."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from layermap import load_layermap
from prep_resonator_ppd import prep_resonator_ppd
from prep_rteg_frame import prep_rteg_in_frame
from separate import identify

INPUT = Path(__file__).resolve().parents[1] / "input_files"
FILTER = INPUT / "KB331_N_01.gds"
PPD = INPUT / "GSG_frame.gds"
FRAME = INPUT / "KB331_N_Frame.gds"
LAYERMAP = INPUT / "layermap"


def load_kb331_pipeline(*, with_orientation: bool = True):
    """Run steps 2ΓÇô4 for all KB331 resonators."""
    if not FILTER.is_file():
        raise FileNotFoundError(FILTER)
    layermap = load_layermap(LAYERMAP)
    identification = identify(FILTER)
    res_df = pd.DataFrame(identification.resonator_rows())
    res_list = identification.resonators
    kwargs: dict = {}
    if with_orientation:
        kwargs["identification"] = identification
        kwargs["layermap"] = layermap
    ppd_assemblies = prep_resonator_ppd(res_df, res_list, PPD, **kwargs)
    frame_assemblies = prep_rteg_in_frame(ppd_assemblies, FRAME)
    return {
        "layermap": layermap,
        "identification": identification,
        "res_df": res_df,
        "res_list": res_list,
        "ppd_assemblies": ppd_assemblies,
        "frame_assemblies": frame_assemblies,
    }
