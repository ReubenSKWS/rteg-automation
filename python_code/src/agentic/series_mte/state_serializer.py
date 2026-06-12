"""Text layout state for the MTE agent (series + shunt)."""
from __future__ import annotations

from agentic.series_mte.context import SeriesMteContext
from rteg_collect import resonator_placement_summary
from rteg_series_mte import SeriesStripBuildResult, resonator_mbe_body
from rteg_signal import SignalNetResult


def serialize_mte_state(
    ctx: SeriesMteContext,
    *,
    last_series: SeriesStripBuildResult | None = None,
    last_shunt: SignalNetResult | None = None,
) -> str:
    placement = resonator_placement_summary(ctx.res, ctx.assembly)
    filler_bb = (
        ctx.roles.ground_plates.filler[0].bbox
        if ctx.roles.ground_plates.filler
        else None
    )
    lines = [
        f"index={ctx.index} inst={ctx.res.inst_name} res_type={ctx.res.res_type}",
        f"rotation_deg={placement['rotation_deg']} filter_origin={placement['filter_origin']}",
        f"filler_bbox={filler_bb}",
        f"preserved_mte_count={len(ctx.roles.preserved.mte)}",
        f"DRC min spacing rule={ctx.config.mbe_mte_spacing_um}um",
    ]

    if ctx.res.res_type == "series":
        body = resonator_mbe_body(ctx.res, ctx.assembly, ctx.config.boolean_precision)
        lines.extend(
            [
                f"body_bbox={body.bounding_box()}",
                f"release_holes={len(ctx.roles.release_holes.all_items())}",
                "",
                "Goal: filled MTE ring offset OUTSIDE resonator body on release-hole arc.",
                "Parameters: margin_um (body→inner MTE gap, try 1-5um),",
                "band_thickness_um (ring thickness, try 1-4um).",
            ]
        )
        if last_series is not None:
            lines.extend(["", "Last attempt:", str(last_series.summary())])
    else:
        sig = ctx.classification.signal_polygons()
        lines.extend(
            [
                f"signal_pad_polygons={len(sig)}",
                "",
                "Goal: MTE connector plate from preserved filter MTE to center signal pad.",
                "Use list_shunt_routes then build_shunt_route(candidate_id).",
            ]
        )
        if last_shunt is not None:
            lines.extend(["", "Last attempt:", str(last_shunt.summary())])

    return "\n".join(lines)


serialize_series_mte_state = serialize_mte_state
