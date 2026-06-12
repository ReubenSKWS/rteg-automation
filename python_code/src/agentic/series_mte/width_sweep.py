"""Deterministic margin/band sweep for series MTE experiment."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from agentic.series_mte.config import SeriesMteExperimentConfig
from agentic.series_mte.context import SeriesMteContext
from rteg_series_mte import SeriesStripBuildResult, build_series_strip


def run_width_sweep(
    contexts: dict[int, SeriesMteContext],
    config: SeriesMteExperimentConfig | None = None,
) -> pd.DataFrame:
    cfg = config or SeriesMteExperimentConfig()
    rows: list[dict[str, Any]] = []
    artifacts_root = cfg.artifacts_dir

    for idx in cfg.series_indices:
        ctx = contexts[idx]
        for margin in cfg.margin_candidates:
            for band in cfg.band_candidates:
                for apply_finalize in (False, True):
                    row: dict[str, Any] = {
                        "index": idx,
                        "inst_name": ctx.res.inst_name,
                        "margin_um": margin,
                        "band_thickness_um": band,
                        "apply_drc_finalize": apply_finalize,
                    }
                    try:
                        result = build_series_strip(
                            ctx.res,
                            ctx.assembly,
                            ctx.roles.release_holes,
                            ctx.layermap,
                            ctx.config,
                            margin_um=margin,
                            band_thickness_um=band,
                            build_mode="offset_ring",
                            apply_drc_finalize=apply_finalize,
                            ground_obstacles=ctx.ground_obstacles,
                            verify=True,
                        )
                        row.update(result.summary())
                        row["build_ok"] = True
                        row["build_error"] = None
                    except ValueError as exc:
                        row["build_ok"] = False
                        row["build_error"] = str(exc)
                        row["is_drc_clean"] = False
                    rows.append(row)

    df = pd.DataFrame(rows)
    out_csv = artifacts_root / "margin_band_sweep.csv"
    artifacts_root.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    return df


def pick_sweep_best(df: pd.DataFrame) -> dict[int, dict[str, Any]]:
    """Per index: smallest band with DRC clean and no finalize, else best available."""
    chosen: dict[int, dict[str, Any]] = {}
    for idx in df["index"].unique():
        sub = df[(df["index"] == idx) & (df["build_ok"] == True)]  # noqa: E712
        if sub.empty:
            continue
        clean = sub[sub["is_drc_clean"] == True]  # noqa: E712
        no_finalize = clean[clean["apply_drc_finalize"] == False]  # noqa: E712
        pool = no_finalize if not no_finalize.empty else clean
        if pool.empty:
            pool = sub
        pool = pool.sort_values(
            ["band_thickness_um", "margin_um", "body_overlap_fraction"]
        )
        chosen[int(idx)] = pool.iloc[0].to_dict()
    return chosen


def sweep_result_from_row(ctx: SeriesMteContext, row: dict[str, Any]) -> SeriesStripBuildResult:
    return build_series_strip(
        ctx.res,
        ctx.assembly,
        ctx.roles.release_holes,
        ctx.layermap,
        ctx.config,
        margin_um=float(row["margin_um"]),
        band_thickness_um=float(row["band_thickness_um"]),
        build_mode="offset_ring",
        apply_drc_finalize=bool(row["apply_drc_finalize"]),
        ground_obstacles=ctx.ground_obstacles,
        verify=True,
    )
