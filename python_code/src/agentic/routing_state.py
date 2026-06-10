"""
Agentic step 5 — mutable per-resonator plate-merge session.

Holds everything the agent changes while building one resonator's ground plane:
the NPI placement shift, any bridge rectangles and the connector rectangle the
agent placed, and budget counters. The immutable setup (collected plates, pads,
obstacles) lives in ``context.AgentGroundContext``.

## Assumptions
- Only the resonator + preserved metal move with ``placement_shift`` (NPI A5);
  pads, frame, filler plate, and release holes are fixed (A6).
- ``bridges`` / ``connector_rect`` are agent-supplied axis-aligned rectangles fed
  straight into ``ground_merge.run_ground_merge``; the same deterministic
  pipeline carves and verifies them, so the agent cannot bypass DRC.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import gdstk

try:
    from ..ground_merge import GroundMergeResult
except ImportError:
    from ground_merge import GroundMergeResult

Point = tuple[float, float]
Bbox = tuple[tuple[float, float], tuple[float, float]]


@dataclass
class GroundMergeSession:
    """Mutable agent state for one resonator's ground plate merge."""

    placement_shift: Point = (0.0, 0.0)
    preserved: list[gdstk.Polygon] = field(default_factory=list)
    res_mbe: list[gdstk.Polygon] = field(default_factory=list)

    bridges: list[Bbox] = field(default_factory=list)
    connector_rect: Bbox | None = None

    # Latest pipeline result (recomputed after every state-changing tool).
    last_result: GroundMergeResult | None = None

    tool_calls_used: int = 0
    llm_turns_used: int = 0

    @property
    def carved_body(self) -> list[gdstk.Polygon]:
        return list(self.last_result.carved_body) if self.last_result else []

    def add_bridge(self, rect: Bbox) -> None:
        self.bridges.append(rect)

    def clear_bridges(self) -> None:
        self.bridges.clear()
