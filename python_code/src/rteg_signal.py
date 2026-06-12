"""
Step 5.3 — Draw MTE extensions from preserved filter collars.

Draws one new ~13 µm extension from the preserved MTE collar that overlaps
resonator-body MTE (not the outline-only piece). Original preserved MTE in the
frame is never modified or removed.

Step 5.4 (classification / orientation) is separate — it does not gate this draw.

Public API
----------
``build_mte_extensions``           — step 5.3: one call for all resonators
``draw_mte_from_preserved_collar`` — basis draw: one extension per preserved collar
``export_signal_rteg_gds``         — write framed RTEG + new MTE polygons to GDS
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import gdstk

from export_gds import ExportResult, export_gds
from layermap import LayerMap
from prep_rteg_frame import RtegFrameAssembly
from rteg_classify import NodeClassification
from rteg_collect import (
    GroundPlates,
    PreservedMetal,
    ReleaseHoles,
    TaggedPolygon,
    select_preserved_collar_mte,
)
from rteg_mte_route import (
    check_mte_attached_to_collar,
    check_mte_vs_ground_drc,
    draw_preserved_mte_extension,
    find_collar_facing_edge,
)
from rteg_utils import assign_layer

Point = tuple[float, float]
Edge = tuple[Point, Point]


@dataclass(frozen=True)
class SignalBuildConfig:
    """Tunables for MTE connector geometry and DRC."""

    mte_layer: str = "BAW_MTE"
    mbe_layer: str = "BAW_MBE"
    mbe_mte_spacing_um: float = 14.0
    plate_width_um: float = 14.0
    collar_extension_um: float = 13.0
    boolean_precision: float = 1e-3
    release_hole_clearance_um: float = 6.0


@dataclass
class SignalEndpoints:
    """Launch info for the first preserved MTE collar extension."""

    preserved: TaggedPolygon
    metal_point: Point
    pad_point: Point
    metal_edge: Edge
    pad_edge: Edge
    clearance_um: float

    def summary(self) -> dict[str, object]:
        return {
            "preserved_label": self.preserved.label,
            "metal_point": (round(self.metal_point[0], 1), round(self.metal_point[1], 1)),
            "pad_point": (round(self.pad_point[0], 1), round(self.pad_point[1], 1)),
            "clearance_um": (
                round(self.clearance_um, 1)
                if not math.isnan(self.clearance_um)
                else None
            ),
        }


@dataclass
class SignalPlate:
    """Drawn extension geometry (first collar)."""

    polygon: gdstk.Polygon
    centerline: list[Point]
    shape_name: str


@dataclass
class SignalNetResult:
    """Drawn MTE extensions ready for export."""

    endpoints: SignalEndpoints
    connector: SignalPlate
    net_polygons: list[gdstk.Polygon]
    preserved_collar_polygons: list[gdstk.Polygon]
    n_net_polygons: int
    signal_terminal: str
    signal_drawable: bool
    is_connected: bool
    min_ground_spacing_um: float
    drc_violations: list[str] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        if not self.signal_drawable:
            return not self.drc_violations
        return self.is_connected and not self.drc_violations

    def summary(self) -> dict[str, object]:
        return {
            "n_net_polygons": self.n_net_polygons,
            "signal_terminal": self.signal_terminal,
            "signal_drawable": self.signal_drawable,
            "is_connected": self.is_connected,
            "is_success": self.is_success,
            "shape": self.connector.shape_name,
            "min_ground_spacing_um": round(self.min_ground_spacing_um, 1),
            "drc_violations": len(self.drc_violations),
            "clearance_um": round(self.endpoints.clearance_um, 1),
        }


def _edge_midpoint(edge: Edge) -> Point:
    return ((edge[0][0] + edge[1][0]) / 2.0, (edge[0][1] + edge[1][1]) / 2.0)


def draw_mte_from_preserved_collar(
    collar_tp: TaggedPolygon,
    layermap: LayerMap,
    cfg: SignalBuildConfig,
) -> tuple[gdstk.Polygon, Point, Point]:
    """
    Basis draw op: one new MTE polygon per preserved collar.

    Follows the collar outline; the open end is a straight line ~13 µm out.
    Original preserved metal is not modified.
    """
    mte_layer, mte_datatype = layermap.pair(cfg.mte_layer)
    extension = draw_preserved_mte_extension(
        collar_tp.polygon,
        cfg.collar_extension_um,
        mte_layer,
        mte_datatype,
    )
    extension = assign_layer(extension, layermap, cfg.mte_layer)
    cx = sum(float(p[0]) for p in collar_tp.polygon.points) / len(collar_tp.polygon.points)
    cy = sum(float(p[1]) for p in collar_tp.polygon.points) / len(collar_tp.polygon.points)
    toward = max(
        collar_tp.polygon.points,
        key=lambda p: (float(p[0]) - cx) ** 2 + (float(p[1]) - cy) ** 2,
    )
    toward_pt = (float(toward[0]), float(toward[1]))
    edge = find_collar_facing_edge(collar_tp.polygon, toward_pt)
    intercept = _edge_midpoint(edge)
    dx, dy = edge[1][0] - edge[0][0], edge[1][1] - edge[0][1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        nx, ny = 1.0, 0.0
    else:
        nx, ny = -dy / length, dx / length
    mid = intercept
    cx, cy = (edge[0][0] + edge[1][0]) / 2.0, (edge[0][1] + edge[1][1]) / 2.0
    if (toward_pt[0] - cx) * nx + (toward_pt[1] - cy) * ny < 0:
        nx, ny = -nx, -ny
    tip = (mid[0] + nx * cfg.collar_extension_um, mid[1] + ny * cfg.collar_extension_um)
    return extension, intercept, tip


def _preserved_mte_polys(preserved: PreservedMetal) -> list[gdstk.Polygon]:
    return [tp.polygon for tp in preserved.mte]


def _mte_extensions_from_preserved(
    preserved: PreservedMetal,
    layermap: LayerMap,
    cfg: SignalBuildConfig,
    *,
    body_mte_polys: Sequence[gdstk.Polygon] | None = None,
) -> SignalNetResult:
    """Draw one extension from the preserved collar overlapping resonator-body MTE."""
    preserved_polys = _preserved_mte_polys(preserved)
    collar_tp = select_preserved_collar_mte(
        preserved,
        body_mte_polys or [],
        min_overlap_um2=0.01,
        precision=cfg.boolean_precision,
    )
    if collar_tp is None:
        return SignalNetResult(
            endpoints=_empty_endpoints(preserved),
            connector=SignalPlate(
                polygon=gdstk.Polygon([(0.0, 0.0)], layer=0, datatype=0),
                centerline=[],
                shape_name="none",
            ),
            net_polygons=[],
            preserved_collar_polygons=preserved_polys,
            n_net_polygons=0,
            signal_terminal="MBE",
            signal_drawable=False,
            is_connected=False,
            min_ground_spacing_um=float("nan"),
            drc_violations=[],
        )

    mte_layer, mte_datatype = layermap.pair(cfg.mte_layer)
    extension, intercept, tip = draw_mte_from_preserved_collar(
        collar_tp, layermap, cfg
    )
    if (extension.layer, extension.datatype) != (mte_layer, mte_datatype):
        raise ValueError(
            f"extension on {(extension.layer, extension.datatype)}, "
            f"expected {(mte_layer, mte_datatype)}"
        )

    violations = check_mte_attached_to_collar(
        extension, collar_tp.polygon, cfg.boolean_precision
    )
    is_connected = not violations
    return SignalNetResult(
        endpoints=SignalEndpoints(
            preserved=collar_tp,
            metal_point=intercept,
            pad_point=tip,
            metal_edge=(intercept, intercept),
            pad_edge=(tip, tip),
            clearance_um=cfg.collar_extension_um,
        ),
        connector=SignalPlate(
            polygon=extension,
            centerline=[intercept, tip],
            shape_name="collar_extend",
        ),
        net_polygons=[extension],
        preserved_collar_polygons=preserved_polys,
        n_net_polygons=1,
        signal_terminal="MTE",
        signal_drawable=True,
        is_connected=is_connected,
        min_ground_spacing_um=float("nan"),
        drc_violations=violations,
    )


class _HasPreserved(Protocol):
    preserved: PreservedMetal
    resonator_body_mte: Sequence[gdstk.Polygon]


def build_mte_extensions(
    roles_by_index: Mapping[int, _HasPreserved],
    layermap: LayerMap,
    config: SignalBuildConfig | None = None,
) -> dict[int, SignalNetResult]:
    """
    Step 5.3 — draw one ~13 µm MTE extension per resonator.

    Selects the preserved collar that overlaps resonator-body MTE (typically one
    of two connectMTE pieces). Single entry point: pass ``all_roles`` from 5.1.
    """
    cfg = config or SignalBuildConfig()
    return {
        idx: _mte_extensions_from_preserved(
            roles.preserved,
            layermap,
            cfg,
            body_mte_polys=roles.resonator_body_mte,
        )
        for idx, roles in roles_by_index.items()
    }


def mte_extensions_overview_rows(
    extensions: Mapping[int, SignalNetResult],
    *,
    inst_names: Mapping[int, str] | None = None,
) -> list[dict[str, object]]:
    """Summary rows for notebook display after ``build_mte_extensions``."""
    rows: list[dict[str, object]] = []
    for idx in sorted(extensions):
        result = extensions[idx]
        rows.append(
            {
                "index": idx,
                "inst_name": inst_names.get(idx) if inst_names else None,
                "n_preserved_mte": len(result.preserved_collar_polygons),
                "n_extensions": result.n_net_polygons,
                "is_connected": result.is_connected,
            }
        )
    return rows


def _empty_endpoints(preserved: PreservedMetal) -> SignalEndpoints:
    pt = (0.0, 0.0)
    edge = (pt, pt)
    preserved_tp = preserved.mte[0] if preserved.mte else (
        preserved.mbe[0] if preserved.mbe else None
    )
    if preserved_tp is None:
        raise ValueError("no preserved metal for empty signal endpoints")
    return SignalEndpoints(
        preserved=preserved_tp,
        metal_point=pt,
        pad_point=pt,
        metal_edge=edge,
        pad_edge=edge,
        clearance_um=float("nan"),
    )


def _release_hole_violations(
    net_polys: Sequence[gdstk.Polygon],
    release_holes: ReleaseHoles | None,
    min_um: float,
) -> list[str]:
    if release_holes is None or min_um <= 0:
        return []
    violations: list[str] = []
    for net in net_polys:
        for hole in release_holes.all_items():
            if gdstk.boolean(net, hole.polygon, "and", precision=1e-3):
                violations.append(f"release hole {hole.label}: overlap with MTE net")
            else:
                bb_n = net.bounding_box()
                bb_h = hole.polygon.bounding_box()
                if bb_n and bb_h:
                    gap = _bbox_gap(bb_n, bb_h)
                    if gap < min_um:
                        violations.append(
                            f"release hole {hole.label}: clearance {gap:.2f} um < {min_um:.2f} um"
                        )
    return violations


def _bbox_gap(a: tuple[Point, Point], b: tuple[Point, Point]) -> float:
    dx = max(0.0, max(a[0][0] - b[1][0], b[0][0] - a[1][0]))
    dy = max(0.0, max(a[0][1] - b[1][1], b[0][1] - a[1][1]))
    return math.hypot(dx, dy)


def _ground_mbe_obstacles(
    ground_plates: GroundPlates,
    layermap: LayerMap,
    cfg: SignalBuildConfig,
) -> list[gdstk.Polygon]:
    mbe_pair = layermap.pair(cfg.mbe_layer)
    return [
        tp.polygon
        for tp in ground_plates.all_items()
        if (tp.polygon.layer, tp.polygon.datatype) == mbe_pair
    ]


def build_signal_net(
    preserved: PreservedMetal,
    classification: NodeClassification,
    ground_plates: GroundPlates,
    layermap: LayerMap,
    config: SignalBuildConfig | None = None,
    *,
    release_holes: ReleaseHoles | None = None,
    body_mte_polys: Sequence[gdstk.Polygon] | None = None,
) -> SignalNetResult:
    """Legacy wrapper: draw extensions plus optional ground/release DRC."""
    cfg = config or SignalBuildConfig()
    if not classification.signal_drawable or not preserved.mte:
        endpoints = _empty_endpoints(preserved)
        return SignalNetResult(
            endpoints=endpoints,
            connector=SignalPlate(
                polygon=gdstk.Polygon([(0.0, 0.0)], layer=0, datatype=0),
                centerline=[],
                shape_name="none",
            ),
            net_polygons=[],
            preserved_collar_polygons=[],
            n_net_polygons=0,
            signal_terminal=classification.signal_terminal,
            signal_drawable=False,
            is_connected=False,
            min_ground_spacing_um=float("nan"),
            drc_violations=[],
        )

    result = _mte_extensions_from_preserved(
        preserved, layermap, cfg, body_mte_polys=body_mte_polys
    )
    violations = list(result.drc_violations)
    min_clear = float("inf")
    for extension in result.net_polygons:
        d, drc_v = check_mte_vs_ground_drc(
            extension,
            _ground_mbe_obstacles(ground_plates, layermap, cfg),
            cfg.mbe_mte_spacing_um,
            cfg.boolean_precision,
        )
        if not math.isnan(d) and d < min_clear:
            min_clear = d
        violations.extend(drc_v)
    violations.extend(
        _release_hole_violations(
            result.net_polygons, release_holes, cfg.release_hole_clearance_um
        )
    )
    if min_clear == float("inf"):
        min_clear = float("nan")

    result.signal_terminal = classification.signal_terminal
    result.min_ground_spacing_um = min_clear
    result.drc_violations = violations
    result.is_connected = not any("not attached" in v for v in violations)
    return result


@dataclass
class SignalRtegAssembly:
    """Step-4 frame assembly with step-5.3 MTE extensions added for export."""

    frame: RtegFrameAssembly
    signal: SignalNetResult

    @property
    def index(self) -> int:
        return self.frame.index

    @property
    def inst_name(self) -> str:
        return self.frame.inst_name

    @property
    def top_cell(self) -> gdstk.Cell:
        return self.frame.top_cell

    @property
    def library(self) -> gdstk.Library:
        return self.frame.library

    def flatten(self) -> gdstk.Cell:
        """Full framed layout plus new drawn MTE polygons; frame metal unchanged."""
        cell = self.frame.flatten().copy(
            f"rteg_{self.index:02d}_{self.inst_name}_mte"
        )
        for poly in self.signal.net_polygons:
            cell.add(gdstk.Polygon(poly.points, poly.layer, poly.datatype))
        return cell


def build_signal_rteg_assemblies(
    frame_assemblies: Sequence[RtegFrameAssembly],
    signals: Mapping[int, SignalNetResult],
) -> list[SignalRtegAssembly]:
    return [
        SignalRtegAssembly(frame=asm, signal=signals[asm.index])
        for asm in frame_assemblies
    ]


def export_signal_rteg_gds(
    frame_assemblies: Sequence[RtegFrameAssembly],
    signals: Mapping[int, SignalNetResult],
    output_dir: str | Path,
    *,
    layermap: LayerMap,
    parent: str | None = None,
    flatten: bool = True,
    write_lyp: bool = True,
) -> list[ExportResult]:
    assemblies = build_signal_rteg_assemblies(frame_assemblies, signals)
    return export_gds(
        assemblies,
        output_dir,
        layermap=layermap,
        parent=parent,
        stage="mte",
        flatten=flatten,
        write_lyp=write_lyp,
    )


def signal_net_summary_table(result: SignalNetResult) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = [
        {"section": "summary", **result.summary()},
        {"section": "endpoints", **result.endpoints.summary()},
    ]
    for i, poly in enumerate(result.net_polygons):
        bb = poly.bounding_box()
        rows.append(
            {
                "section": "net_polygon",
                "index": i,
                "layer": (poly.layer, poly.datatype),
                "vertices": len(poly.points),
                "bbox": (
                    (round(bb[0][0], 1), round(bb[0][1], 1)),
                    (round(bb[1][0], 1), round(bb[1][1], 1)),
                )
                if bb
                else None,
            }
        )
    for v in result.drc_violations:
        rows.append({"section": "drc", "message": v})
    return rows


__all__ = [
    "SignalBuildConfig",
    "SignalNetResult",
    "SignalRtegAssembly",
    "build_mte_extensions",
    "build_signal_net",
    "build_signal_rteg_assemblies",
    "draw_mte_from_preserved_collar",
    "export_signal_rteg_gds",
    "mte_extensions_overview_rows",
    "signal_net_summary_table",
]
