"""
Step 5.2 — Classify GSG node blocks as signal or ground (resonator-type rule).

**Shunt:** center GSG pad = **signal**; top and bottom = ground.

**Series:** all GSG pads = **ground**; signal lives on the resonator body
(``signal_band = "on_resonator"``), not on a probe pad.

``filler_plate`` is always ground and is not a GSG probe node.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from rteg_collect import GroundPlates, PreservedMetal, TaggedPolygon

NodeBand = Literal["top", "center", "bottom"]
NodeNet = Literal["signal", "ground"]
SignalBand = NodeBand | Literal["on_resonator"]
ClassifyMethod = Literal["res_type"]
ResType = Literal["shunt", "series"]

_BAND_ORDER: tuple[NodeBand, ...] = ("top", "center", "bottom")


@dataclass(frozen=True)
class ClassifyNodesConfig:
    """Reserved for future tunables (no geometry thresholds today)."""


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

    signal_band: SignalBand
    nodes: list[ClassifiedNode] = field(default_factory=list)
    filler: list[TaggedPolygon] = field(default_factory=list)
    method: ClassifyMethod = "res_type"
    res_type: str = ""
    note: str = ""

    @property
    def ground_bands(self) -> list[NodeBand]:
        return [n.band for n in self.nodes if n.net == "ground"]

    def by_band(self) -> dict[NodeBand, ClassifiedNode]:
        return {n.band: n for n in self.nodes}

    def signal_polygons(self) -> list[TaggedPolygon]:
        if self.signal_band == "on_resonator":
            return []
        node = self.by_band()[self.signal_band]
        return list(node.polygons)

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


def _signal_band_for_res_type(res_type: str) -> tuple[SignalBand, str]:
    """Return (signal_band, note) for a shunt or series resonator."""
    if res_type == "shunt":
        return "center", "shunt — center GSG pad is signal"
    if res_type == "series":
        return (
            "on_resonator",
            "series — signal on resonator body; all GSG pads ground",
        )
    raise ValueError(
        f"unsupported res_type {res_type!r}; expected 'shunt' or 'series'"
    )


def classify_nodes(
    ground_plates: GroundPlates,
    preserved: PreservedMetal,
    *,
    res_type: str,
    config: ClassifyNodesConfig | None = None,
) -> NodeClassification:
    """
    Assign signal vs ground to each GSG node band from resonator type.

    Parameters
    ----------
    ground_plates
        Step-5.1 ``GroundPlates`` (top / center / bottom / filler).
    preserved
        Step-5.1 ``PreservedMetal`` (accepted for pipeline symmetry; unused).
    res_type
        ``"shunt"`` or ``"series"`` from step 2 ``identification``.
    config
        Optional placeholder config.

    Returns
    -------
    NodeClassification
        Signal band, per-band nets, filler (always ground), and method used.
    """
    _ = preserved
    _ = config
    bands = _band_items(ground_plates)
    signal_band, note = _signal_band_for_res_type(res_type)

    nodes: list[ClassifiedNode] = []
    for band in _BAND_ORDER:
        if signal_band == "on_resonator":
            net: NodeNet = "ground"
        else:
            net = "signal" if band == signal_band else "ground"
        nodes.append(
            ClassifiedNode(
                band=band,
                net=net,
                polygons=list(bands[band]),
            )
        )

    return NodeClassification(
        signal_band=signal_band,
        nodes=nodes,
        filler=list(ground_plates.filler),
        method="res_type",
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
        row["signal_band"] = classification.signal_band
        rows.append(row)
    return rows
