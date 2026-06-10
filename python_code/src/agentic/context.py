"""
Agentic step 5 — per-resonator plate-merge context (immutable setup).

Builds the same geometric world the deterministic plate merge sees, using the
public helpers from ``route_rteg`` (pad classification, preserved-metal
extraction, world transforms) and ``ground_merge`` (plate collection, feasibility
precheck, the full merge pipeline). A few tiny private helpers from ``route_rteg``
are re-implemented here so this experiment never couples to private API.

The agent does **not** draw wires. It influences the shared boolean pipeline by
supplying bridge rectangles, a connector rectangle, and an NPI shift; this
context runs ``ground_merge.run_ground_merge`` with those choices and returns the
carved, verified result.

## Boundary note (why pad arms are "outside" looks fine)
The GSG ground arms are wide MBE plates that legitimately span the frame wall;
the cavity constraint only applies to **new** bridge / connector rectangles the
agent adds, never to the existing arms or filler.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import gdstk

try:
    from ..ground_merge import (
        GroundMergeConfig,
        GroundMergeResult,
        GroundPlates,
        collect_ground_plates,
        feasibility_precheck,
        run_ground_merge,
    )
    from ..layermap import LayerMap
    from ..prep_rteg_frame import RtegFrameAssembly
    from ..route_rteg import (
        GsgPadRoles,
        classify_gsg_pads,
        extract_preserved_metal,
        filter_to_rteg_world,
        resonator_metal_rteg,
    )
    from ..separate import IdentificationResult, Resonator
except ImportError:
    from ground_merge import (
        GroundMergeConfig,
        GroundMergeResult,
        GroundPlates,
        collect_ground_plates,
        feasibility_precheck,
        run_ground_merge,
    )
    from layermap import LayerMap
    from prep_rteg_frame import RtegFrameAssembly
    from route_rteg import (
        GsgPadRoles,
        classify_gsg_pads,
        extract_preserved_metal,
        filter_to_rteg_world,
        resonator_metal_rteg,
    )
    from separate import IdentificationResult, Resonator

from .config import AgenticConfig

Point = tuple[float, float]
Bbox = tuple[tuple[float, float], tuple[float, float]]


# --- small helpers mirrored from route_rteg privates (kept local on purpose) ---


def _expand_bbox(bbox: Bbox, margin: float) -> Bbox:
    (x0, y0), (x1, y1) = bbox
    return (x0 - margin, y0 - margin), (x1 + margin, y1 + margin)


def _bbox_overlap(a: Bbox, b: Bbox) -> bool:
    (ax0, ay0), (ax1, ay1) = a
    (bx0, by0), (bx1, by1) = b
    return ax0 <= bx1 and bx0 <= ax1 and ay0 <= by1 and by0 <= ay1


def _polys_near_bbox(polys: Sequence[gdstk.Polygon], bbox: Bbox) -> list[gdstk.Polygon]:
    return [
        poly
        for poly in polys
        if (bb := poly.bounding_box()) is not None and _bbox_overlap(bb, bbox)
    ]


def _layer_polys(
    assembly: RtegFrameAssembly, pairs: set[tuple[int, int]]
) -> list[gdstk.Polygon]:
    return [
        poly
        for poly in assembly.flatten().polygons
        if (poly.layer, poly.datatype) in pairs
    ]


def _group_bbox(polys: Sequence[gdstk.Polygon]) -> Bbox | None:
    boxes = [bb for p in polys if (bb := p.bounding_box()) is not None]
    if not boxes:
        return None
    return (
        (min(b[0][0] for b in boxes), min(b[0][1] for b in boxes)),
        (max(b[1][0] for b in boxes), max(b[1][1] for b in boxes)),
    )


# --- context ---


@dataclass
class AgentGroundContext:
    """Everything fixed for one resonator's agentic plate merge."""

    assembly: RtegFrameAssembly
    res: Resonator
    layermap: LayerMap
    config: AgenticConfig
    gcfg: GroundMergeConfig

    pads: GsgPadRoles
    plates: GroundPlates
    filter_preserved: list[gdstk.Polygon]

    center_obstacles: list[gdstk.Polygon]
    mte_obstacles: list[gdstk.Polygon]
    release_holes: list[gdstk.Polygon]

    mbe_pair: tuple[int, int]
    signal_pair: tuple[int, int]
    cavity_bbox: Bbox
    filler_bbox: Bbox | None
    plate_width_um: float

    def preserved_at(self, dx: float, dy: float) -> list[gdstk.Polygon]:
        return filter_to_rteg_world(
            self.filter_preserved, self.res, self.assembly, extra_shift=(dx, dy)
        )

    def res_mbe_at(self, dx: float, dy: float) -> list[gdstk.Polygon]:
        return [
            p
            for p in resonator_metal_rteg(self.res, self.assembly, extra_shift=(dx, dy))
            if (p.layer, p.datatype) == self.mbe_pair
        ]

    def spacing_obstacles_at(self, dx: float, dy: float) -> list[gdstk.Polygon]:
        """Other-net keepouts for the 14 µm carve: center signal + MTE + resonator MBE."""
        return self.center_obstacles + self.mte_obstacles + self.res_mbe_at(dx, dy)

    def run_merge(self, session) -> GroundMergeResult:
        """
        Run the shared plate-merge pipeline with the agent's current choices and
        cache the result on the session.
        """
        dx, dy = session.placement_shift
        preserved = self.preserved_at(dx, dy)
        spacing = self.spacing_obstacles_at(dx, dy)
        result = run_ground_merge(
            assembly=self.assembly,
            layermap=self.layermap,
            pads=self.pads,
            preserved=preserved,
            spacing_obstacles=spacing,
            release_holes=self.release_holes,
            config=self.gcfg,
            bridges=session.bridges or None,
            connector_rect=session.connector_rect,
        )
        session.preserved = preserved
        session.res_mbe = self.res_mbe_at(dx, dy)
        session.last_result = result
        return result


def build_agent_context(
    assembly: RtegFrameAssembly,
    res: Resonator,
    identification: IdentificationResult,
    layermap: LayerMap,
    config: AgenticConfig,
) -> tuple[AgentGroundContext | None, str | None]:
    """
    Build the plate-merge context, or return ``(None, skip_reason)``.

    Skip reasons match the deterministic path plus the feasibility-precheck
    reasons from ``ground_merge``.
    """
    gcfg = config.to_ground_merge_config()

    pads = classify_gsg_pads(assembly)
    if pads is None:
        return None, "pad_classification_failed"

    filter_preserved = extract_preserved_metal(identification, res, layermap, gcfg)
    if not filter_preserved:
        return None, "no_preserved_metal"
    preserved_nominal = filter_to_rteg_world(filter_preserved, res, assembly)

    mbe_pair = layermap.pair(config.target_route_layer)
    signal_pair = layermap.pair(config.signal_layer)

    plates = collect_ground_plates(assembly, layermap, pads, gcfg)
    skip = feasibility_precheck(plates, preserved_nominal, assembly, gcfg)
    if skip is not None:
        return None, skip

    center_obstacles = [
        p for p in pads.center_signal if (p.layer, p.datatype) == signal_pair
    ] or list(pads.center_signal)
    mte_obstacles = _layer_polys(assembly, {layermap.pair(n) for n in config.obstacle_layers})

    # Release holes limited to the resonator neighborhood — pad-cavity outlines
    # elsewhere sit under the GSG pads by design and must not be carved out.
    rh_pairs = {layermap.pair(n) for n in config.release_hole_layers}
    res_mbe_nominal = [
        p for p in resonator_metal_rteg(res, assembly) if (p.layer, p.datatype) == mbe_pair
    ]
    res_bb = _group_bbox(res_mbe_nominal)
    if res_bb is not None:
        near = _expand_bbox(res_bb, config.preserved_overlap_margin_um)
        release_holes = _polys_near_bbox(_layer_polys(assembly, rh_pairs), near)
    else:
        release_holes = []

    return (
        AgentGroundContext(
            assembly=assembly,
            res=res,
            layermap=layermap,
            config=config,
            gcfg=gcfg,
            pads=pads,
            plates=plates,
            filter_preserved=filter_preserved,
            center_obstacles=center_obstacles,
            mte_obstacles=mte_obstacles,
            release_holes=release_holes,
            mbe_pair=mbe_pair,
            signal_pair=signal_pair,
            cavity_bbox=assembly.inner_die_frame_bbox,
            filler_bbox=_group_bbox(plates.filler),
            plate_width_um=plates.plate_width_um(),
        ),
        None,
    )
