"""Shared result types and filler-carve helpers for steps 6.2 and 6.3."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import gdstk

from rteg_classify import NodeClassification


@dataclass
class MbeBodyResult:
    cap: gdstk.Polygon | None
    filler: list[gdstk.Polygon]
    bridge: gdstk.Polygon | None
    routed_net: list[gdstk.Polygon]
    n_pieces: int
    drc_violations: list[str] = field(default_factory=list)
    absorbed_mbe: list[gdstk.Polygon] = field(default_factory=list)
    mte_extension: gdstk.Polygon | None = None
    replaced_mte_extension: gdstk.Polygon | None = None


def empty_mbe_body_result(*, violations: list[str] | None = None) -> MbeBodyResult:
    return MbeBodyResult(
        cap=None,
        filler=[],
        bridge=None,
        routed_net=[],
        n_pieces=0,
        drc_violations=list(violations or []),
    )


def base_filler_polygon(classification: NodeClassification) -> gdstk.Polygon | None:
    if not classification.filler:
        return None
    return classification.filler[0].polygon


def offset_polys(
    polys: Sequence[gdstk.Polygon],
    distance: float,
) -> list[gdstk.Polygon]:
    grown: list[gdstk.Polygon] = []
    for poly in polys:
        if distance <= 0:
            grown.append(poly)
            continue
        offset = gdstk.offset(poly, distance)
        if offset:
            grown.extend(offset)
        else:
            grown.append(poly)
    return grown


def carve_filler(
    base_filler: gdstk.Polygon,
    keepouts: Sequence[gdstk.Polygon],
    *,
    boolean_precision: float,
) -> tuple[list[gdstk.Polygon], list[str]]:
    """Carve keepouts from the step-4 filler and clip to the filler bbox."""
    violations: list[str] = []

    carved: list[gdstk.Polygon]
    if keepouts:
        result = gdstk.boolean(
            base_filler,
            list(keepouts),
            "not",
            precision=boolean_precision,
        )
        carved = result if result else []
    else:
        carved = [base_filler]

    if not carved:
        violations.append("carved filler is empty after keepout subtraction")
        return [], violations

    filler_bb = base_filler.bounding_box()
    if filler_bb is not None:
        clip_rect = gdstk.rectangle(filler_bb[0], filler_bb[1])
        clipped: list[gdstk.Polygon] = []
        for piece in carved:
            result = gdstk.boolean(
                piece,
                clip_rect,
                "and",
                precision=boolean_precision,
            )
            if result:
                clipped.extend(result)
        if clipped:
            carved = clipped

    return carved, violations


def _clip_polys_to_bbox(
    polys: Sequence[gdstk.Polygon],
    bbox_poly: gdstk.Polygon,
    *,
    boolean_precision: float,
) -> list[gdstk.Polygon]:
    clipped: list[gdstk.Polygon] = []
    for piece in polys:
        result = gdstk.boolean(
            piece,
            bbox_poly,
            "and",
            precision=boolean_precision,
        )
        if result:
            clipped.extend(result)
    return clipped if clipped else list(polys)


def mte_route_obstacle_polys(
    resonator_body_mte: Sequence[gdstk.Polygon],
    mte_extension: gdstk.Polygon | None = None,
    mte_routed_net: gdstk.Polygon | None = None,
) -> list[gdstk.Polygon]:
    """Resonator-body MTE plus step-5.3 extension and pad route polygons."""
    obstacles = list(resonator_body_mte)
    if mte_extension is not None:
        obstacles.append(mte_extension)
    if mte_routed_net is not None:
        obstacles.append(mte_routed_net)
    return obstacles


def trim_polygon_away_from_keepouts(
    poly: gdstk.Polygon,
    keepouts: Sequence[gdstk.Polygon],
    *,
    anchor: gdstk.Polygon | None = None,
    boolean_precision: float,
) -> gdstk.Polygon:
    """Boolean-subtract keepouts, keeping the piece connected to ``anchor`` when split."""
    if not keepouts:
        return poly
    carved = gdstk.boolean(poly, list(keepouts), "not", precision=boolean_precision)
    if not carved:
        return poly
    if len(carved) == 1:
        return carved[0]
    if anchor is not None:
        connected = [
            piece
            for piece in carved
            if gdstk.boolean(piece, anchor, "and", precision=boolean_precision)
        ]
        if connected:
            return max(connected, key=lambda p: abs(p.area()))
    return max(carved, key=lambda p: abs(p.area()))


def build_mte_trim_keepouts(
    obstacles: Sequence[gdstk.Polygon],
    clearance_um: float,
    *,
    extra_clearance_um: float = 0.0,
    boolean_precision: float = 1e-3,
) -> list[gdstk.Polygon]:
    """Offset-clearance keepouts for final MBE filler trim near MTE routes."""
    total = clearance_um + extra_clearance_um
    if not obstacles or total <= 0:
        return []
    united = gdstk.boolean(
        list(obstacles),
        [],
        "or",
        precision=boolean_precision,
    ) or list(obstacles)
    return offset_polys(united, total)


def merge_filler_with_bridge(
    carved: list[gdstk.Polygon],
    bridge: gdstk.Polygon | None,
    base_filler: gdstk.Polygon,
    *,
    boolean_precision: float,
) -> list[gdstk.Polygon]:
    if bridge is None:
        return carved
    merged = gdstk.boolean(
        carved,
        [bridge],
        "or",
        precision=boolean_precision,
    )
    if not merged:
        return carved
    filler_bb = base_filler.bounding_box()
    if filler_bb is None:
        return merged
    clip_rect = gdstk.rectangle(filler_bb[0], filler_bb[1])
    return _clip_polys_to_bbox(merged, clip_rect, boolean_precision=boolean_precision)


__all__ = [
    "MbeBodyResult",
    "base_filler_polygon",
    "build_mte_trim_keepouts",
    "carve_filler",
    "empty_mbe_body_result",
    "merge_filler_with_bridge",
    "mte_route_obstacle_polys",
    "offset_polys",
    "trim_polygon_away_from_keepouts",
]
