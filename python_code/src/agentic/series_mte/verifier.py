"""Deterministic checks for series MTE experiment."""
from __future__ import annotations

from agentic.series_mte.context import SeriesMteContext
from rteg_series_mte import (
    SeriesStripBuildResult,
    _verify_series_boundary_invariants,
    check_series_strip_drc,
)
from rteg_signal import SignalNetResult


def check_invariants(ctx: SeriesMteContext, result: SeriesStripBuildResult) -> list[str]:
    errors: list[str] = []
    try:
        if result.body is None:
            errors.append("missing body polygon on result")
            return errors
        _verify_series_boundary_invariants(
            result.strip,
            result.centerline,
            result.body,
            result.hole_a,
            result.hole_b,
            ctx.roles.release_holes.all_items(),
            ctx.res,
            ctx.config,
            build_mode=result.build_mode,
        )
    except ValueError as exc:
        errors.append(str(exc))
    return errors


def check_drc(ctx: SeriesMteContext, result: SeriesStripBuildResult) -> dict[str, object]:
    min_clear, violations = check_series_strip_drc(
        result.strip,
        ctx.ground_obstacles,
        ctx.config.mbe_mte_spacing_um,
        ctx.config.boolean_precision,
    )
    return {
        "min_ground_spacing_um": min_clear,
        "violations": violations,
        "is_clean": not violations,
    }


def check_shunt_drc(ctx: SeriesMteContext, signal: SignalNetResult) -> dict[str, object]:
    return {
        "min_ground_spacing_um": signal.min_ground_spacing_um,
        "violations": signal.drc_violations,
        "is_clean": not signal.drc_violations,
        "reaches_pad": signal.reaches_pad,
    }
