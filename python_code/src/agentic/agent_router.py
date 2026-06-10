"""
Agentic step 5 — the Anthropic tool-use loop for the ground plate merge.

The agent perceives the layout as text, calls plate-merge tools (union, bridge,
connect, carve, check), and receives the deterministic verifier result after
every change. It iterates until the carved ground body is one connected, clean
net touching both ground pads + the preserved metal, or the budget runs out.

On success the result is emitted exactly like the deterministic path (same
export surface). On budget exhaustion the full trace is logged and the resonator
is marked FAILED — a dirty ground body is never emitted as routed.

## Assumptions
- The verifier (``verifier.check_ground`` → ``ground_merge.verify_ground``) is the
  only judge of success; the agent's own claims are ignored.
- No ``temperature`` is sent — newer Anthropic models reject it; run-to-run
  variance is one of the measured quantities.
- The Anthropic SDK is imported lazily so the rest of the package works without it.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Sequence
from typing import Any

import pandas as pd

try:
    from ..layermap import LayerMap
    from ..prep_rteg_frame import RtegFrameAssembly
    from ..separate import IdentificationResult, Resonator
except ImportError:
    from layermap import LayerMap
    from prep_rteg_frame import RtegFrameAssembly
    from separate import IdentificationResult, Resonator

from .config import AgenticConfig
from .context import build_agent_context
from .emit import AgenticRoutedAssembly, build_routed_assembly
from .routing_state import GroundMergeSession
from .state_serializer import serialize_state
from .tools import TOOL_SCHEMAS, dispatch_tool
from .trace_logger import TraceLogger
from .verifier import check_ground

SYSTEM_PROMPT = """\
You are a precision layout agent for BAW filter test structures (R-tags).

TASK: build the MBE GROUND PLANE for one resonator by fusing wide MBE plates
into a single carved body. The ground side is NOT a wire — it is one boolean
body made of: the two outer GSG ground arms, the right-hand MBE filler plate,
and the resonator's preserved ground connector. The center pad is the SIGNAL pad
— it is a carve obstacle, NEVER fused.

WORKFLOW (use the tools; the deterministic verifier grades everything):
1. get_state — read the plates, union status, preserved metal, and rules.
2. union_ground — check how many components the plates form.
   - 1 component: no bridge needed.
   - >1 components: add bridge_gap rectangle(s) (axis-aligned, inside the
     cavity, at plate width) until they fuse.
3. If the preserved metal does NOT already overlap the body, add a
   connect_preserved rectangle that overlaps both.
4. carve_ground — union + carve the DRC keepouts.
5. check_drc — confirm PASS: one connected body touching BOTH ground pads AND
   the preserved metal, zero violations. STOP once it reports PASS.

HARD RULES (enforced by the verifier — you cannot bypass them):
- Never rotate/reshape the resonator. shift_assembly moves only the resonator +
  preserved metal, max +/-20um per axis, ABSOLUTE from nominal.
- Ground body must stay 14um from center signal / MTE / resonator MBE, and 6um
  from release holes (the carve enforces this; do not fight it).
- New bridge / connector rectangles must be axis-aligned and inside the cavity.
  The existing arms/filler may sit outside the cavity — that is expected.

You have a small tool budget. Often the plates are already fused and the
preserved metal already overlaps — in that case just carve_ground and check_drc.
Be deliberate: think briefly, then act.
"""


def _require_client(config: AgenticConfig):
    api_key = os.environ.get(config.api_key_env)
    if not api_key:
        raise RuntimeError(
            f"Environment variable {config.api_key_env} is not set. "
            "Set it before running the agentic router."
        )
    try:
        import anthropic
    except ImportError as exc:
        raise RuntimeError(
            "The 'anthropic' package is not installed. Run: pip install anthropic"
        ) from exc
    return anthropic.Anthropic(api_key=api_key)


def route_agentic_assembly(
    assembly: RtegFrameAssembly,
    res: Resonator,
    identification: IdentificationResult,
    layermap: LayerMap,
    config: AgenticConfig,
    *,
    run_id: str | None = None,
    client: Any | None = None,
) -> AgenticRoutedAssembly:
    """
    Build one resonator's ground plane with the LLM agent.

    ``status`` is ``"routed"`` only when the deterministic verifier passed;
    ``"failed"`` on budget exhaustion / API errors; ``"skipped"`` when context
    setup failed.
    """
    run_id = run_id or uuid.uuid4().hex[:8]
    tracer = TraceLogger(config.log_dir, run_id, assembly.index)
    t_start = time.monotonic()

    context, skip_reason = build_agent_context(
        assembly, res, identification, layermap, config
    )
    if context is None:
        tracer.log("skip", reason=skip_reason)
        empty_session = GroundMergeSession()
        dummy_context = _FrameOnlyContext(assembly)
        return build_routed_assembly(
            dummy_context,  # type: ignore[arg-type]
            empty_session,
            None,
            status="skipped",
            skip_reason=skip_reason,
            wall_time_s=time.monotonic() - t_start,
        )

    session = GroundMergeSession(
        preserved=context.preserved_at(0.0, 0.0),
        res_mbe=context.res_mbe_at(0.0, 0.0),
    )

    if client is None:
        client = _require_client(config)

    input_tokens = 0
    output_tokens = 0
    status = "failed"
    fail_note: str | None = None

    initial_state = serialize_state(context, session)
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": (
                "Build this resonator's ground plane. Initial state:\n\n"
                + initial_state
                + "\n\nBegin. Both outer ground pads and the preserved metal must "
                "end up in one clean connected ground body (check_drc must PASS)."
            ),
        }
    ]
    tracer.log("start", system=SYSTEM_PROMPT, first_user=messages[0]["content"])

    try:
        while session.llm_turns_used < config.max_llm_turns:
            response = client.messages.create(
                model=config.model,
                max_tokens=config.max_response_tokens,
                system=SYSTEM_PROMPT,
                tools=TOOL_SCHEMAS,
                messages=messages,
            )
            session.llm_turns_used += 1
            usage = getattr(response, "usage", None)
            if usage is not None:
                input_tokens += getattr(usage, "input_tokens", 0) or 0
                output_tokens += getattr(usage, "output_tokens", 0) or 0
            tracer.log(
                "llm_response",
                turn=session.llm_turns_used,
                stop_reason=response.stop_reason,
                content=response.content,
                usage=usage,
            )

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                break  # agent stopped talking; final grade decides

            messages.append({"role": "assistant", "content": response.content})
            results_content: list[dict[str, Any]] = []
            success_now = False

            for block in tool_uses:
                if session.tool_calls_used >= config.max_tool_calls:
                    results_content.append(
                        _tool_result(block.id, {"ok": False, "error": "tool budget exhausted"})
                    )
                    continue
                session.tool_calls_used += 1
                result = dispatch_tool(
                    block.name, dict(block.input or {}), context, session
                )
                tracer.log(
                    "tool_call",
                    n=session.tool_calls_used,
                    tool=block.name,
                    args=block.input,
                    result=result,
                )
                results_content.append(_tool_result(block.id, result))
                if session.last_result is not None and session.last_result.is_success:
                    success_now = True
                    break

            messages.append({"role": "user", "content": results_content})

            if success_now:
                break
            if session.tool_calls_used >= config.max_tool_calls:
                fail_note = "tool budget exhausted"
                break
        else:
            fail_note = "LLM turn budget exhausted"
    except Exception as exc:  # API/network errors must not crash the batch
        fail_note = f"agent error: {exc}"
        tracer.log("error", error=str(exc))

    final = check_ground(context, session)
    if final.is_success:
        status = "routed"
        fail_note = None
    elif fail_note is None:
        fail_note = "agent stopped before verifier pass"
    wall_time = time.monotonic() - t_start
    tracer.log(
        "end",
        status=status,
        fail_note=fail_note,
        verifier=final.report.to_text(),
        tool_calls=session.tool_calls_used,
        llm_turns=session.llm_turns_used,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        wall_time_s=round(wall_time, 1),
    )

    return build_routed_assembly(
        context,
        session,
        final,
        status=status,
        skip_reason=fail_note,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        wall_time_s=wall_time,
    )


def route_agentic_assemblies(
    assemblies: Sequence[RtegFrameAssembly],
    identification: IdentificationResult,
    layermap: LayerMap,
    *,
    config: AgenticConfig | None = None,
    indices: Sequence[int] | None = None,
    run_id: str | None = None,
) -> tuple[list[AgenticRoutedAssembly], pd.DataFrame]:
    """Run the agentic plate merge for selected frame assemblies."""
    cfg = config or AgenticConfig()
    selected = list(indices) if indices is not None else list(cfg.validation_indices)
    run_id = run_id or uuid.uuid4().hex[:8]
    client = _require_client(cfg)

    by_index = {a.index: a for a in assemblies}
    resonators = identification.resonators

    results: list[AgenticRoutedAssembly] = []
    for idx in sorted(set(selected)):
        if idx not in by_index or idx >= len(resonators):
            continue
        results.append(
            route_agentic_assembly(
                by_index[idx],
                resonators[idx],
                identification,
                layermap,
                cfg,
                run_id=run_id,
                client=client,
            )
        )
    return results, pd.DataFrame([r.summary_row() for r in results])


def _tool_result(tool_use_id: str, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps(result, ensure_ascii=False),
        "is_error": not result.get("ok", False),
    }


class _FrameOnlyContext:
    """Duck-typed stand-in for emit when context setup was skipped."""

    def __init__(self, assembly: RtegFrameAssembly) -> None:
        self.assembly = assembly
        self.mbe_pair = (2, 0)
