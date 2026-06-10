"""
Agentic step 5 — single configuration dataclass.

All tunables for the experiment live here (model, budgets, clearances, shift
limits, paths). No other agentic module defines magic numbers.

## Assumptions
- Clearance values mirror the deterministic ``RouteSearchConfig`` so both paths
  are graded against the same PDK6 rules (14 µm MBE/MTE, 6 µm release holes).
- ``route_width_um`` matches the deterministic notebook input so route-quality
  metrics are comparable.
- The API key is read from an environment variable, never stored in config.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    from ..ground_merge import GroundMergeConfig
    from ..route_search import RouteSearchConfig
except ImportError:
    from ground_merge import GroundMergeConfig
    from route_search import RouteSearchConfig


@dataclass(frozen=True)
class AgenticConfig:
    """
    Tunables for the agentic routing experiment.

    LLM
    ---
    model / api_key_env / max_response_tokens: Anthropic API settings.

    Budgets (hard — the loop stops when either is hit)
    --------------------------------------------------
    max_tool_calls: total tool executions per resonator.
    max_llm_turns: total assistant turns per resonator.

    Geometry rules (same as deterministic; the agent does not get to break them)
    ----------------------------------------------------------------------------
    mbe_mte_spacing_um: minimum spacing route vs other-net metal (PDK6: 14).
    release_hole_clearance_um: minimum route vs release holes (PDK6: 6).
    max_shift_um: |dx| and |dy| limit for shift_assembly (axis-aligned).
    route_width_um: stroke width for all route tools.
    connect_tolerance_um: max gap for a route to count as connected to metal.

    Evaluation
    ----------
    validation_indices: resonators to run (start with index 5).
    agentic_runs_for_determinism: repeated agentic runs per resonator in the
        comparison (do outputs differ run-to-run?).
    """

    # LLM
    model: str = "claude-opus-4-8"
    api_key_env: str = "ANTHROPIC_API_KEY"
    max_response_tokens: int = 100_000

    # Budgets (plate merge needs far fewer steps than wire drawing)
    max_tool_calls: int = 15
    max_llm_turns: int = 8

    # Layers (layermap names only — resolved at runtime, A14)
    target_route_layer: str = "BAW_MBE"
    obstacle_layers: tuple[str, ...] = ("BAW_MTE",)
    release_hole_layers: tuple[str, ...] = ("BAW_ReF", "BAW_CAV")
    signal_layer: str = "BAW_MTE"

    # Geometry rules
    mbe_mte_spacing_um: float = 14.0
    release_hole_clearance_um: float = 6.0
    preserved_overlap_margin_um: float = 10.0
    max_shift_um: float = 20.0
    route_width_um: float = 14.0
    connect_tolerance_um: float = 0.5

    # Evaluation
    validation_indices: tuple[int, ...] = (5,)
    agentic_runs_for_determinism: int = 3

    # Paths (resolved relative to python_code/ by the notebook)
    log_dir: Path = field(default_factory=lambda: Path("artifacts/agentic_logs"))
    comparison_path: Path = field(
        default_factory=lambda: Path("artifacts/AGENTIC_COMPARISON.md")
    )

    def to_route_search_config(self) -> RouteSearchConfig:
        """
        Equivalent deterministic config for the shared step-5 helpers
        (preserved-metal extraction, routable region, DRC self-check) and for
        the deterministic baseline in the comparison.
        """
        return RouteSearchConfig(
            target_route_layer=self.target_route_layer,
            obstacle_layers=self.obstacle_layers,
            release_hole_layers=self.release_hole_layers,
            mbe_mte_spacing_um=self.mbe_mte_spacing_um,
            release_hole_clearance_um=self.release_hole_clearance_um,
            route_width_um=self.route_width_um,
            preserved_overlap_margin_um=self.preserved_overlap_margin_um,
            signal_layer=self.signal_layer,
        )

    def to_ground_merge_config(self) -> GroundMergeConfig:
        """Equivalent plate-merge config — the agent is graded against these rules."""
        return GroundMergeConfig(
            target_route_layer=self.target_route_layer,
            signal_layer=self.signal_layer,
            obstacle_layers=self.obstacle_layers,
            release_hole_layers=self.release_hole_layers,
            mbe_mte_spacing_um=self.mbe_mte_spacing_um,
            release_hole_clearance_um=self.release_hole_clearance_um,
            preserved_overlap_margin_um=self.preserved_overlap_margin_um,
            connect_tolerance_um=self.connect_tolerance_um,
        )
