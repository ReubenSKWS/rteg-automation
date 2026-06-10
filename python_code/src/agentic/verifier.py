"""
Agentic step 5 — deterministic verifier (the checker, never the LLM).

Grades the agent's plate-merge choices by running the shared
``ground_merge`` pipeline and reading its ``GroundVerifyReport``. Success means a
single connected carved ground body touches **both** outer ground pads and the
preserved metal, with zero net-aware DRC violation. The agent's own claims are
ignored; only this result decides ``status == "routed"``.
"""
from __future__ import annotations

try:
    from ..ground_merge import GroundMergeResult
except ImportError:
    from ground_merge import GroundMergeResult

from .context import AgentGroundContext
from .routing_state import GroundMergeSession


def check_ground(
    context: AgentGroundContext,
    session: GroundMergeSession,
) -> GroundMergeResult:
    """Run the plate-merge pipeline with the session's choices and grade it."""
    return context.run_merge(session)
