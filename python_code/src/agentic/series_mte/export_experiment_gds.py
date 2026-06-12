"""Export experimental series MTE strips to GDS."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from export_gds import ExportResult
from layermap import LayerMap
from prep_rteg_frame import RtegFrameAssembly
from rteg_classify import NodeClassification
from rteg_collect import PreservedMetal, RtegGeometryRoles
from rteg_series_mte import SeriesStripBuildResult
from rteg_signal import (
    SignalBuildConfig,
    SignalNetResult,
    SignalPlate,
    _series_signal_endpoints,
    build_signal_net,
    export_signal_rteg_gds,
)
from separate import Resonator


def strip_result_to_signal_net(
    result: SeriesStripBuildResult,
    preserved: PreservedMetal,
) -> SignalNetResult:
    endpoints = _series_signal_endpoints(
        preserved,
        result.centerline[0],
        result.centerline[-1],
    )
    connector = SignalPlate(
        polygon=result.strip,
        centerline=list(result.centerline),
        shape_name=result.shape_name,
    )
    return SignalNetResult(
        endpoints=endpoints,
        connector=connector,
        net_polygons=[result.strip],
        signal_pad_polygons=[],
        n_net_polygons=1,
        is_connected=True,
        reaches_pad=False,
        min_ground_spacing_um=result.min_ground_spacing_um,
        drc_violations=list(result.drc_violations),
    )


def build_shunt_signal_nets(
    indices: Sequence[int],
    *,
    resonators: Sequence[Resonator],
    roles_by_index: Mapping[int, RtegGeometryRoles],
    classifications: Mapping[int, NodeClassification],
    layermap: LayerMap,
    config: SignalBuildConfig | None = None,
) -> dict[int, SignalNetResult]:
    """Production shunt pad routing for center-band resonators."""
    cfg = config or SignalBuildConfig()
    out: dict[int, SignalNetResult] = {}
    for idx in indices:
        res = resonators[idx]
        if res.res_type != "shunt":
            continue
        roles = roles_by_index[idx]
        out[idx] = build_signal_net(
            roles.preserved,
            classifications[idx],
            roles.ground_plates,
            layermap,
            config=cfg,
        )
    return out


def assemble_experiment_signals(agent_runs: Mapping[int, object]) -> dict[int, SignalNetResult]:
    """Collect ``SignalNetResult`` from ``AgentRunResult`` objects keyed by index."""
    return {idx: run.signal for idx, run in agent_runs.items()}  # type: ignore[attr-defined]


def assemble_experiment_signals_legacy(
    series_chosen: Mapping[int, SeriesStripBuildResult],
    preserved_by_index: Mapping[int, PreservedMetal],
    shunt_signals: Mapping[int, SignalNetResult],
) -> dict[int, SignalNetResult]:
    """Merge experimental series strips with shunt pad routes."""
    signals = dict(shunt_signals)
    for idx, strip in series_chosen.items():
        signals[idx] = strip_result_to_signal_net(strip, preserved_by_index[idx])
    return signals


def export_all_mte_gds(
    frame_assemblies: Sequence[RtegFrameAssembly],
    signals: Mapping[int, SignalNetResult],
    *,
    layermap: LayerMap,
    output_dir: str | Path,
    parent: str | None = None,
) -> list[ExportResult]:
    """Export full framed RTEG layouts with MTE for all resonators."""
    return export_signal_rteg_gds(
        frame_assemblies,
        signals,
        output_dir,
        layermap=layermap,
        parent=parent,
        flatten=True,
        write_lyp=True,
    )
