"""Anthropic tool-use agent for series and shunt MTE routing."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Any

from agentic.series_mte.config import (
    SeriesMteExperimentConfig,
    default_env_file,
    env_file_candidates,
    load_agent_env,
)
from agentic.series_mte.context import SeriesMteContext
from agentic.series_mte.export_experiment_gds import strip_result_to_signal_net
from agentic.series_mte.state_serializer import serialize_mte_state
from agentic.series_mte.tools import (
    MteToolSession,
    tool_definitions_for,
    tool_result_json,
)
from agentic.series_mte.trace_logger import SeriesMteTraceLogger
from agentic.series_mte.width_sweep import pick_sweep_best, sweep_result_from_row
from rteg_series_mte import SeriesStripBuildResult
from rteg_signal import SignalNetResult, build_signal_net

SERIES_SYSTEM_PROMPT = """You are an RF layout assistant building series resonator MTE signal strips.

Target: a FILLED thin ring offset OUTWARD from the resonator body — a visible gap
(margin_um) then a red MTE band (band_thickness_um). The ring sits entirely outside
the body and spans only the arc between two release-hole anchors.

Rules:
- margin_um: gap body→MTE inner edge — try 1–5 µm
- band_thickness_um: filled ring thickness — try 1–4 µm
- apply_drc_finalize=false first; only enable if DRC fails without trim
- Must pass check_invariants and check_drc (14 µm vs ground MBE)

When satisfied, respond with JSON only:
{"done": true, "margin_um": <float>, "band_thickness_um": <float>,
 "apply_drc_finalize": <bool>, "reason": "<short explanation>"}
"""

SHUNT_SYSTEM_PROMPT = """You are an RF layout assistant routing shunt resonator MTE to the center signal pad.

Target: a stroked MTE connector plate from preserved filter MTE to the GSG signal pad.
Routes are orthogonal / 45° only (straight, L, 45, Z jog variants).

Workflow:
1. Call list_shunt_routes to see ranked candidates (DRC-clean + shortest first).
2. build_shunt_route with a candidate_id that is DRC-clean and reaches_pad.
3. Confirm with check_drc and check_invariants.

Prefer the shortest DRC-clean route that reaches the pad. If none are DRC-clean,
pick the best available and explain the tradeoff.

When satisfied, respond with JSON only:
{"done": true, "candidate_id": <int>, "reason": "<short explanation>"}
"""


@dataclass
class AgentRunResult:
    index: int
    res_type: str
    signal: SignalNetResult
    reasoning: str
    source: str  # "agent" | "sweep_fallback" | "production_fallback"
    series_result: SeriesStripBuildResult | None = None

    @property
    def result(self) -> SeriesStripBuildResult:
        """Backward compat — series runs only."""
        if self.series_result is None:
            raise AttributeError(f"index {self.index} is {self.res_type}, not series")
        return self.series_result


def _series_sweep_fallback(
    ctx: SeriesMteContext, sweep_df, reasoning: str
) -> AgentRunResult:
    picks = pick_sweep_best(sweep_df)
    row = picks[ctx.index]
    strip = sweep_result_from_row(ctx, row)
    return AgentRunResult(
        index=ctx.index,
        res_type="series",
        signal=strip_result_to_signal_net(strip, ctx.roles.preserved),
        reasoning=reasoning,
        source="sweep_fallback",
        series_result=strip,
    )


def _shunt_production_fallback(ctx: SeriesMteContext, reasoning: str) -> AgentRunResult:
    signal = build_signal_net(
        ctx.roles.preserved,
        ctx.classification,
        ctx.roles.ground_plates,
        ctx.layermap,
        config=ctx.config,
    )
    return AgentRunResult(
        index=ctx.index,
        res_type="shunt",
        signal=signal,
        reasoning=reasoning,
        source="production_fallback",
    )


def _finalize_series(session: MteToolSession, ctx: SeriesMteContext) -> AgentRunResult:
    assert session.last_result is not None
    strip = session.last_result
    return AgentRunResult(
        index=ctx.index,
        res_type="series",
        signal=strip_result_to_signal_net(strip, ctx.roles.preserved),
        reasoning="",
        source="agent",
        series_result=strip,
    )


def _finalize_shunt(session: MteToolSession, ctx: SeriesMteContext) -> AgentRunResult:
    assert session.last_shunt_signal is not None
    return AgentRunResult(
        index=ctx.index,
        res_type="shunt",
        signal=session.last_shunt_signal,
        reasoning="",
        source="agent",
    )


def run_mte_agent(
    ctx: SeriesMteContext,
    config: SeriesMteExperimentConfig | None = None,
    *,
    sweep_df=None,
) -> AgentRunResult:
    """Run the MTE agent for one resonator (series offset ring or shunt pad route)."""
    is_series = ctx.res.res_type == "series"
    env_file = load_agent_env(env_file=default_env_file())
    cfg = config or SeriesMteExperimentConfig()
    run_id = f"idx{ctx.index:02d}_{uuid.uuid4().hex[:8]}"
    logger = SeriesMteTraceLogger(run_id, cfg.artifacts_dir / "traces")
    session = MteToolSession(ctx)
    tools = tool_definitions_for(ctx)
    system = SERIES_SYSTEM_PROMPT if is_series else SHUNT_SYSTEM_PROMPT

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.log(
            "skip",
            reason="ANTHROPIC_API_KEY not set",
            res_type=ctx.res.res_type,
            env_file=str(env_file) if env_file else None,
            env_candidates=[str(p) for p in env_file_candidates()],
        )
        if is_series and sweep_df is not None:
            return _series_sweep_fallback(
                ctx, sweep_df, "ANTHROPIC_API_KEY unset — used sweep best"
            )
        return _shunt_production_fallback(
            ctx, "ANTHROPIC_API_KEY unset — used production shunt route"
        )

    try:
        import anthropic
    except ImportError as exc:
        if is_series and sweep_df is not None:
            return _series_sweep_fallback(
                ctx, sweep_df, f"anthropic not installed ({exc}) — used sweep best"
            )
        return _shunt_production_fallback(
            ctx, f"anthropic not installed ({exc}) — used production shunt route"
        )

    client = anthropic.Anthropic(api_key=api_key)
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": serialize_mte_state(ctx)}
    ]
    logger.log(
        "start",
        model=cfg.model,
        index=ctx.index,
        res_type=ctx.res.res_type,
        env_file=str(env_file) if env_file else None,
    )

    for turn in range(cfg.max_turns):
        response = client.messages.create(
            model=cfg.model,
            max_tokens=2048,
            system=system,
            tools=tools,
            messages=messages,
        )
        logger.log("turn", turn=turn, stop_reason=response.stop_reason)

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        text_blocks = [b.text for b in response.content if hasattr(b, "text")]

        if not tool_uses:
            text = "\n".join(text_blocks)
            try:
                payload = json.loads(text.strip())
                if payload.get("done"):
                    if is_series:
                        session.dispatch(
                            "build_offset_ring_strip",
                            {
                                "margin_um": float(payload["margin_um"]),
                                "band_thickness_um": float(payload["band_thickness_um"]),
                                "apply_drc_finalize": bool(
                                    payload.get("apply_drc_finalize", False)
                                ),
                            },
                        )
                        assert session.last_result is not None
                        out = _finalize_series(session, ctx)
                        out.reasoning = str(payload.get("reason", text))
                        return out
                    session.dispatch(
                        "build_shunt_route",
                        {"candidate_id": int(payload["candidate_id"])},
                    )
                    assert session.last_shunt_signal is not None
                    out = _finalize_shunt(session, ctx)
                    out.reasoning = str(payload.get("reason", text))
                    return out
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                pass

            if is_series and session.last_result and session.last_result.is_drc_clean:
                out = _finalize_series(session, ctx)
                out.reasoning = text or "agent stopped with clean strip"
                return out
            if (
                not is_series
                and session.last_shunt_signal
                and not session.last_shunt_signal.drc_violations
                and session.last_shunt_signal.reaches_pad
            ):
                out = _finalize_shunt(session, ctx)
                out.reasoning = text or "agent stopped with clean shunt route"
                return out
            break

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in tool_uses:
            out = session.dispatch(block.name, block.input)
            logger.log("tool", name=block.name, input=block.input, output=out)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": tool_result_json(out),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    if is_series and session.last_result is not None:
        out = _finalize_series(session, ctx)
        out.reasoning = "max turns — using last built strip"
        return out
    if not is_series and session.last_shunt_signal is not None:
        out = _finalize_shunt(session, ctx)
        out.reasoning = "max turns — using last built shunt route"
        return out

    if is_series and sweep_df is not None:
        return _series_sweep_fallback(ctx, sweep_df, "agent exhausted — sweep best")
    return _shunt_production_fallback(ctx, "agent exhausted — production shunt route")


run_series_mte_agent = run_mte_agent


def run_agents_for_indices(
    contexts: dict[int, SeriesMteContext],
    config: SeriesMteExperimentConfig | None = None,
    *,
    sweep_df=None,
) -> dict[int, AgentRunResult]:
    cfg = config or SeriesMteExperimentConfig()
    agent_indices = tuple(dict.fromkeys((*cfg.series_indices, *cfg.shunt_indices)))
    out: dict[int, AgentRunResult] = {}
    for idx in agent_indices:
        if idx not in contexts:
            raise KeyError(f"missing context for index {idx}")
        sweep = sweep_df if idx in cfg.series_indices else None
        out[idx] = run_mte_agent(contexts[idx], cfg, sweep_df=sweep)
    return out
