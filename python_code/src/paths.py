"""Default paths for CLI scripts (notebook uses the same filenames under INPUT_FILES)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INPUT_FILES = ROOT / "input_files"
DEFAULT_LAYERMAP = INPUT_FILES / "layermap"

# Same GDS inputs as single_run.ipynb (Define Inputs cell)
FILTER_GDS = INPUT_FILES / "KB331_N_01.gds"
FRAME_GDS = INPUT_FILES / "KB331_N_Frame.gds"
PPD_GDS = INPUT_FILES / "GSG_frame.gds"

NOTEBOOK_INPUT_GDS = (FILTER_GDS, FRAME_GDS, PPD_GDS)
