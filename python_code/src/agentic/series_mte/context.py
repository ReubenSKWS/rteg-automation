"""Per-resonator context for the series MTE experiment."""
from __future__ import annotations

from dataclasses import dataclass

from layermap import LayerMap
from prep_rteg_frame import RtegFrameAssembly
from rteg_classify import NodeClassification
from rteg_collect import RtegGeometryRoles, collect_geometry_roles
from rteg_signal import SignalBuildConfig, _ground_mbe_obstacles
from separate import IdentificationResult, Resonator

import gdstk


@dataclass
class SeriesMteContext:
    index: int
    res: Resonator
    assembly: RtegFrameAssembly
    roles: RtegGeometryRoles
    classification: NodeClassification
    layermap: LayerMap
    config: SignalBuildConfig
    ground_obstacles: list[gdstk.Polygon]


def build_series_mte_context(
    index: int,
    assembly: RtegFrameAssembly,
    res: Resonator,
    identification: IdentificationResult,
    classification: NodeClassification,
    layermap: LayerMap,
    config: SignalBuildConfig | None = None,
) -> SeriesMteContext:
    from rteg_collect import RtegCollectConfig

    cfg = config or SignalBuildConfig()
    roles = collect_geometry_roles(
        assembly, res, identification, layermap, RtegCollectConfig()
    )
    ground = list(
        _ground_mbe_obstacles(classification, roles.ground_plates, layermap, cfg)
    )
    return SeriesMteContext(
        index=index,
        res=res,
        assembly=assembly,
        roles=roles,
        classification=classification,
        layermap=layermap,
        config=cfg,
        ground_obstacles=ground,
    )
