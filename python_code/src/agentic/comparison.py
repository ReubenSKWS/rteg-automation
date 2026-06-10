"""
Agentic step 5 — honest side-by-side evaluation vs the deterministic plate merge.

Both paths now drive the **same** ``ground_merge`` pipeline, so this is a
like-for-like comparison (no golden GDS, no one-pad/two-pad asymmetry). Runs the
deterministic merge once and the agentic merge N times on the same resonator(s)
and writes a markdown record.

## Measured quantities
- success per path (and the failure / skip reason when not routed)
- carved ground area (``mbe_area_um2``) and severed-fragment count
- determinism: ``ground_body_hash`` of the deterministic body vs the N agentic
  bodies — do they all match?
- cost: wall time, and tokens for the agentic path
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

try:
    from ..layermap import LayerMap
    from ..prep_rteg_frame import RtegFrameAssembly
    from ..route_rteg import route_rteg_assemblies
    from ..separate import IdentificationResult
except ImportError:
    from layermap import LayerMap
    from prep_rteg_frame import RtegFrameAssembly
    from route_rteg import route_rteg_assemblies
    from separate import IdentificationResult

from .agent_router import route_agentic_assemblies
from .config import AgenticConfig


def run_comparison(
    assemblies: Sequence[RtegFrameAssembly],
    identification: IdentificationResult,
    layermap: LayerMap,
    *,
    config: AgenticConfig | None = None,
    indices: Sequence[int] | None = None,
    output_path: str | Path | None = None,
) -> tuple[pd.DataFrame, Path]:
    """
    Run deterministic once + agentic N times per resonator; write the report.

    Returns the comparison DataFrame and the path of the markdown file.
    """
    cfg = config or AgenticConfig()
    idx_list = list(indices) if indices is not None else list(cfg.validation_indices)
    out_path = Path(output_path) if output_path is not None else Path(cfg.comparison_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Deterministic baseline (timed)
    t0 = time.monotonic()
    det_results, _det_df = route_rteg_assemblies(
        assemblies,
        identification,
        layermap,
        config=cfg.to_ground_merge_config(),
        indices=idx_list,
    )
    det_wall_s = time.monotonic() - t0
    det_by_index = {r.index: r for r in det_results}

    # Agentic runs (N per resonator for the determinism question)
    n_runs = cfg.agentic_runs_for_determinism
    agentic_runs = []
    for run_n in range(n_runs):
        run_id = f"cmp_{uuid.uuid4().hex[:6]}_r{run_n + 1}"
        results, _df = route_agentic_assemblies(
            assemblies, identification, layermap,
            config=cfg, indices=idx_list, run_id=run_id,
        )
        agentic_runs.append(results)

    rows: list[dict[str, object]] = []
    for idx in sorted(set(idx_list)):
        det = det_by_index.get(idx)
        if det is not None:
            rows.append(
                {
                    "index": idx,
                    "path": "deterministic",
                    "run": 1,
                    "success": det.status == "routed",
                    "pads_connected": ",".join(det.pads_connected),
                    "mbe_area_um2": round(det.mbe_area_um2, 1),
                    "ground_body_hash": det.ground_body_hash,
                    "bridges": det.bridges_applied,
                    "connector": det.connector_used,
                    "severed": det.n_severed_fragments,
                    "drc_violations": det.drc_violations,
                    "wall_time_s": round(det_wall_s / max(1, len(idx_list)), 3),
                    "tokens": 0,
                    "failure_mode": det.skip_reason or "",
                }
            )

        for run_n, run in enumerate(agentic_runs, start=1):
            a = next((x for x in run if x.index == idx), None)
            if a is None:
                continue
            rows.append(
                {
                    "index": idx,
                    "path": "agentic",
                    "run": run_n,
                    "success": a.status == "routed",
                    "pads_connected": ",".join(sorted(a.pads_connected)),
                    "mbe_area_um2": round(a.mbe_area_um2, 1),
                    "ground_body_hash": a.ground_body_hash,
                    "bridges": a.bridges_applied,
                    "connector": a.connector_used,
                    "severed": a.n_severed_fragments,
                    "drc_violations": a.drc_violations,
                    "wall_time_s": round(a.wall_time_s, 1),
                    "tokens": a.input_tokens + a.output_tokens,
                    "failure_mode": a.skip_reason or "",
                }
            )

    df = pd.DataFrame(rows)
    _write_markdown(df, out_path, cfg, n_runs)
    return df, out_path


def _df_to_markdown(df: pd.DataFrame) -> str:
    """Plain markdown table without the optional tabulate dependency."""
    cols = [str(c) for c in df.columns]
    rows = [
        ["" if pd.isna(v) else str(v) for v in record]
        for record in df.itertuples(index=False)
    ]
    widths = [
        max(len(cols[i]), *(len(r[i]) for r in rows)) if rows else len(cols[i])
        for i in range(len(cols))
    ]
    header = "| " + " | ".join(c.ljust(w) for c, w in zip(cols, widths)) + " |"
    sep = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
    body = [
        "| " + " | ".join(v.ljust(w) for v, w in zip(r, widths)) + " |" for r in rows
    ]
    return "\n".join([header, sep, *body])


def _write_markdown(
    df: pd.DataFrame, out_path: Path, cfg: AgenticConfig, n_runs: int
) -> None:
    lines: list[str] = []
    lines.append("# Agentic vs deterministic step-5 ground plate merge — comparison")
    lines.append("")
    lines.append(
        "Generated by `src/agentic/comparison.py`. Both paths drive the same "
        "`ground_merge` pipeline; the agentic path lets an LLM choose bridge / "
        "connector rectangles and an NPI shift, the deterministic path uses the "
        "automatic bridge + connector. This is an experiment record, not an "
        "endorsement of either path."
    )
    lines.append("")
    lines.append(
        f"Model: `{cfg.model}` · agentic runs per resonator: {n_runs} · "
        f"budgets: {cfg.max_tool_calls} tool calls / {cfg.max_llm_turns} LLM turns"
    )
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append(_df_to_markdown(df))
    lines.append("")
    lines.append("## Determinism (ground_body_hash)")
    lines.append("")
    for idx in sorted(df["index"].unique()):
        sub = df[df["index"] == idx]
        det_hash = sub.loc[sub["path"] == "deterministic", "ground_body_hash"].tolist()
        ag_hashes = sub.loc[sub["path"] == "agentic", "ground_body_hash"].tolist()
        all_hashes = det_hash + ag_hashes
        unique = sorted(set(all_hashes))
        if len(unique) == 1:
            verdict = f"identical across deterministic + {len(ag_hashes)} agentic runs"
        else:
            verdict = f"{len(unique)} distinct bodies"
        det_str = det_hash[0] if det_hash else "—"
        lines.append(
            f"- resonator {idx}: {verdict} "
            f"(deterministic `{det_str}`; agentic {', '.join(f'`{h}`' for h in ag_hashes)})"
        )
    lines.append("")
    lines.append("## Observations")
    lines.append("")
    lines.append(
        "_Fill in after reviewing: did the agent need bridges/connector or did "
        "the auto path already fuse the plates? Did agentic bodies match the "
        "deterministic body? Cost difference (wall time, tokens), and whether the "
        "agentic path added value over the automatic merge on this input._"
    )
    lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
