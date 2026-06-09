"""
Step 3 (future): place each PPD+resonator assembly inside the die frame.

Not implemented yet — stub for the modular notebook pipeline.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import gdstk

from prep_resonator_ppd import ResonatorPpdAssembly


@dataclass
class FrameAssembly:
    """In-memory die frame + PPD assembly (step 3)."""

    index: int
    inst_name: str
    top_cell: gdstk.Cell
    library: gdstk.Library
    frame_origin: tuple[float, float]
    ppd_assembly: ResonatorPpdAssembly


def prep_ppd_in_frame(
    assemblies: Sequence[ResonatorPpdAssembly],
    frame_gds: str | Path,
    *,
    frame_origin: tuple[float, float] = (0.0, 0.0),
) -> list[FrameAssembly]:
    """Place each PPD assembly in the die frame. Notebook section TBD."""
    raise NotImplementedError("Step 3 — prep_ppd_in_frame not implemented yet")
