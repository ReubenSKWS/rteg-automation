"""
Step 5.2 — Classify GSG node blocks as signal or ground from collar orientation.

MTE routing has two modes only:
- **center pad** — when preserved MTE faces center, route to center signal pad
- **collar extend** — otherwise extend preserved MTE ~14 µm (no pad connection)

``filler_plate`` is always ground and is not a GSG probe node.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from rteg_collect import GroundPlates, PreservedMetal, TaggedPolygon
from rteg_orientation import CollarOrientation, MteRouteTarget, OrientationAnalysis

NodeBand = Literal["top", "center", "bottom"]
NodeNet = Literal["signal", "ground"]
SignalTerminal = Literal["MTE", "MBE"]
ClassifyMethod = Literal["orientation"]

_BAND_ORDER: tuple[NodeBand, ...] = ("top", "center", "bottom")


@dataclass
class ClassifiedNode:
    """One GSG band (top / center / bottom) with net assignment."""

    band: NodeBand
    net: NodeNet
    polygons: list[TaggedPolygon]

    def summary(self) -> dict[str, object]:
        return {
            "band": self.band,
            "net": self.net,
            "n_polygons": len(self.polygons),
            "labels": [p.label for p in self.polygons],
        }


@dataclass
class NodeClassification:
    """Result of ``classify_nodes`` for one resonator."""

    signal_terminal: SignalTerminal
    collar_orientation: CollarOrientation
    mte_route_target: MteRouteTarget
    signal_pad_band: NodeBand
    signal_drawable: bool
    nodes: list[ClassifiedNode] = field(default_factory=list)
    filler: list[TaggedPolygon] = field(default_factory=list)
    method: ClassifyMethod = "orientation"
    res_type: str = ""
    note: str = ""

    @property
    def ground_bands(self) -> list[NodeBand]:
        return [n.band for n in self.nodes if n.net == "ground"]

    def by_band(self) -> dict[NodeBand, ClassifiedNode]:
        return {n.band: n for n in self.nodes}

    def signal_polygons(self) -> list[TaggedPolygon]:
        if self.mte_route_target != "center_pad":
            return []
        return list(self.by_band()["center"].polygons)

    def center_pad_polygons(self) -> list[TaggedPolygon]:
        """Center GSG band geometry regardless of MTE route target (Step 6.1 MBE pad route)."""
        return list(self.by_band()["center"].polygons)

    def ground_node_polygons(self) -> list[TaggedPolygon]:
        out: list[TaggedPolygon] = []
        for node in self.nodes:
            if node.net == "ground":
                out.extend(node.polygons)
        return out


def _band_items(ground_plates: GroundPlates) -> dict[NodeBand, list[TaggedPolygon]]:
    return {
        "top": list(ground_plates.top),
        "center": list(ground_plates.center),
        "bottom": list(ground_plates.bottom),
    }


def classify_nodes(
    ground_plates: GroundPlates,
    preserved: PreservedMetal,
    *,
    orientation: OrientationAnalysis,
    res_type: str = "",
) -> NodeClassification:
    """
    Assign signal vs ground to each GSG band from collar orientation.

    MTE drawable when preserved filter MTE exists. Route target is center pad
    when MTE faces center; otherwise extend preserved MTE at the collar only.
    """
    bands = _band_items(ground_plates)
    collar = orientation.collar
    route = collar.mte_route_target
    has_mte = bool(preserved.mte)
    signal_drawable = has_mte
    signal_terminal: SignalTerminal = "MTE" if has_mte else "MBE"
    signal_pad_band: NodeBand = "center"

    if not has_mte:
        note = "no preserved MTE — nothing to draw"
    elif route == "center_pad":
        note = "preserved MTE faces center pad — route MTE to center signal pad"
    else:
        note = (
            "preserved MTE not facing center — extend preserved MTE at collar only; "
            "MBE signal route (Step 6.1)"
        )

    nodes: list[ClassifiedNode] = []
    for band in _BAND_ORDER:
        if route == "center_pad" and has_mte:
            net: NodeNet = "signal" if band == "center" else "ground"
        else:
            net = "ground"
        nodes.append(
            ClassifiedNode(
                band=band,
                net=net,
                polygons=list(bands[band]),
            )
        )

    return NodeClassification(
        signal_terminal=signal_terminal,
        collar_orientation=collar,
        mte_route_target=route,
        signal_pad_band=signal_pad_band,
        signal_drawable=signal_drawable,
        nodes=nodes,
        filler=list(ground_plates.filler),
        method="orientation",
        res_type=res_type,
        note=note,
    )


def classification_summary_table(
    classification: NodeClassification,
    *,
    index: int | None = None,
    inst_name: str | None = None,
    res_type: str | None = None,
) -> list[dict[str, object]]:
    """Rows for a pandas DataFrame in the notebook."""
    rows: list[dict[str, object]] = []
    for node in classification.nodes:
        row = node.summary()
        if index is not None:
            row["index"] = index
        if inst_name is not None:
            row["inst_name"] = inst_name
        if res_type is not None:
            row["res_type"] = res_type
        row["method"] = classification.method
        row["signal_terminal"] = classification.signal_terminal
        row["mte_route_target"] = classification.mte_route_target
        row["signal_pad_band"] = classification.signal_pad_band
        row["signal_drawable"] = classification.signal_drawable
        row["mte_faces_center"] = classification.collar_orientation.mte_faces_center
        row["facing_pad"] = classification.collar_orientation.facing_pad
        row["collar_axis"] = classification.collar_orientation.axis
        rows.append(row)
    return rows
