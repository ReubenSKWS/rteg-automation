"""
Agentic step 5 (experiment) — LLM-driven MBE ground routing.

A parallel, experimental alternative to the deterministic candidate search in
``route_rteg`` / ``route_search``. An Anthropic tool-use agent perceives the
layout state as text, draws routes by calling the existing geometry primitives
as tools, and iterates on deterministic verifier feedback until the layout is
clean and connected or the budget is exhausted.

The verifier is never the LLM: DRC, connectivity, and NPI checks stay 100%
deterministic. The agent proposes; the checker disposes.

This package does not modify any existing pipeline module.
"""
from .config import AgenticConfig

__all__ = [
    "AgenticConfig",
    "route_agentic_assembly",
    "route_agentic_assemblies",
    "run_comparison",
]


def __getattr__(name: str):
    # Lazy imports keep `import agentic.config` usable without the anthropic
    # package installed; the LLM loop is only loaded when actually used.
    if name in ("route_agentic_assembly", "route_agentic_assemblies"):
        from .agent_router import route_agentic_assemblies, route_agentic_assembly

        return {
            "route_agentic_assembly": route_agentic_assembly,
            "route_agentic_assemblies": route_agentic_assemblies,
        }[name]
    if name == "run_comparison":
        from .comparison import run_comparison

        return run_comparison
    raise AttributeError(name)
