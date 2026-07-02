"""
Step 5.2c — Normalize preserved MTE and MBE for collar_extend resonators.

For collar_extend resonators (mte_route_target == 'collar_extend') both the
preserved connectMTE and connectMBE pieces can include the full filter interconnect
bus, which has irregular wild edges far from the resonator body.

MTE: wild outer edges cause split_bridging_orphans to produce a wild-shaped
grounded cap, which blocks the MBE rectangle filler from connecting.

MBE: the large single-piece filter bus (low overlap fraction with body) is
classified as an extension by _split_collar_extensions. _find_upstream_knee then
picks a vertex from the wild polygon as the approach-angle knee, producing a
complex signal route shape instead of a clean direct path.

Both layers are clipped to a bounding box around the resonator body + collar_margin_um.
After clipping the pieces are small and tightly overlapping the body, so they are
classified as collar (not extension), leaving ext_polys empty for build_signal_route
and giving a clean, unconstrained route to the pad.

Only collar_extend resonators are processed; center_pad resonators are skipped.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import gdstk

from layermap import LayerMap
from prep_rteg_frame import RtegFrameAssembly
from rteg_classify import NodeClassification
from rteg_collect import (
    RtegGeometryRoles,
    TaggedPolygon,
    _polygon_key,
)

Point = tuple[float, float]


@dataclass(frozen=True)
class MteNormalizeConfig:
    """Tunable parameters for step 5.2c MTE normalization."""

    collar_margin_um: float = 20.0
    boolean_precision: float = 1e-3
    min_area_um2: float = 5.0


def _body_bbox_expanded(
    body_mte_polys: Sequence[gdstk.Polygon],
    margin_um: float,
) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    for poly in body_mte_polys:
        for pt in poly.points:
            xs.append(float(pt[0]))
            ys.append(float(pt[1]))
    if not xs:
        return None
    return (
        min(xs) - margin_um,
        min(ys) - margin_um,
        max(xs) + margin_um,
        max(ys) + margin_um,
    )


def _clip_tagged_polys(
    preserved: Sequence[TaggedPolygon],
    body_polys: Sequence[gdstk.Polygon],
    cfg: MteNormalizeConfig,
) -> list[TaggedPolygon]:
    expanded = _body_bbox_expanded(body_polys, cfg.collar_margin_um)
    if expanded is None:
        return list(preserved)
    x0, y0, x1, y1 = expanded
    clip_box = gdstk.rectangle((x0, y0), (x1, y1))
    result: list[TaggedPolygon] = []
    for tp in preserved:
        clipped = gdstk.boolean(tp.polygon, clip_box, "and", precision=cfg.boolean_precision)
        for piece in clipped:
            if abs(piece.area()) >= cfg.min_area_um2:
                result.append(
                    TaggedPolygon(
                        label=tp.label,
                        layer_name=tp.layer_name,
                        polygon=gdstk.Polygon(
                            piece.points,
                            layer=tp.polygon.layer,
                            datatype=tp.polygon.datatype,
                        ),
                    )
                )
    return result


def normalize_mte_for_collar_extend(
    preserved_mte: Sequence[TaggedPolygon],
    body_mte_polys: Sequence[gdstk.Polygon],
    cfg: MteNormalizeConfig | None = None,
) -> list[TaggedPolygon]:
    """
    Clip wild preserved MTE to a bounding box around the resonator body MTE.

    The inner face (collar-to-body intercept points A/B) is preserved.
    Outer wild edges are replaced by flat cuts at body bbox + collar_margin_um.
    """
    return _clip_tagged_polys(preserved_mte, body_mte_polys, cfg or MteNormalizeConfig())


def normalize_mbe_for_collar_extend(
    preserved_mbe: Sequence[TaggedPolygon],
    body_mbe_polys: Sequence[gdstk.Polygon],
    cfg: MteNormalizeConfig | None = None,
) -> list[TaggedPolygon]:
    """
    Clip wild preserved MBE to a bounding box around the resonator body MBE.

    For collar_extend resonators the signal route is on MBE. A single large
    filter-bus MBE piece has low body-overlap fraction → _split_collar_extensions
    classifies it as an extension → _find_upstream_knee inserts a wild vertex as a
    knee into the signal route ring → complex route shape. Clipping to body bbox +
    collar_margin_um makes the piece small enough that its overlap fraction is high,
    so it is classified as collar, ext_polys is empty, and the route is unconstrained
    and clean.
    """
    return _clip_tagged_polys(preserved_mbe, body_mbe_polys, cfg or MteNormalizeConfig())


def normalize_mte_collar_extent_all(
    roles_by_index: Mapping[int, RtegGeometryRoles],
    assemblies: Sequence[RtegFrameAssembly],
    classifications: Mapping[int, NodeClassification],
    layermap: LayerMap,
    cfg: MteNormalizeConfig | None = None,
) -> dict[int, dict[str, int]]:
    """
    Step 5.2c: normalize preserved MTE and MBE in-place for all collar_extend resonators.

    For each qualifying resonator:
    1. Clips preserved MTE to body MTE bbox + collar_margin_um (flat outer face for
       clean grounded cap in split_bridging_orphans).
    2. Clips preserved MBE to body MBE bbox + collar_margin_um (removes wild filter
       bus piece so _split_collar_extensions sees no extensions → ext_polys empty →
       no knee constraint → clean signal route).
    3. Removes old wild polygons from the frame assembly top_cell and adds clipped.
    4. Replaces roles.preserved.mte and roles.preserved.mbe in-place.

    Returns ``{index: {"mte_removed": n, "mbe_removed": m}}`` for reporting.
    """
    c = cfg or MteNormalizeConfig()
    mte_pair = layermap.pair("BAW_MTE")
    mbe_pair = layermap.pair("BAW_MBE")
    report: dict[int, dict[str, int]] = {}

    for idx, roles in roles_by_index.items():
        classification = classifications[idx]
        if classification.mte_route_target != "collar_extend":
            report[idx] = {"mte_removed": 0, "mbe_removed": 0}
            continue

        # ---- MTE ----
        old_mte_tp = list(roles.preserved.mte)
        new_mte_tp = normalize_mte_for_collar_extend(old_mte_tp, roles.resonator_body_mte, c)

        # ---- MBE ----
        old_mbe_tp = list(roles.preserved.mbe)
        new_mbe_tp = normalize_mbe_for_collar_extend(old_mbe_tp, roles.resonator_body_mbe, c)

        # Update frame cell: remove old wild MTE + MBE, add normalized.
        assembly = assemblies[idx]
        old_mte_keys = {_polygon_key(tp.polygon) for tp in old_mte_tp}
        old_mbe_keys = {_polygon_key(tp.polygon) for tp in old_mbe_tp}

        keep: list[gdstk.Polygon] = []
        mte_removed = 0
        mbe_removed = 0
        for poly in assembly.top_cell.polygons:
            layer_dt = (poly.layer, poly.datatype)
            if layer_dt == mte_pair and _polygon_key(poly) in old_mte_keys:
                mte_removed += 1
                continue
            if layer_dt == mbe_pair and _polygon_key(poly) in old_mbe_keys:
                mbe_removed += 1
                continue
            keep.append(poly)

        assembly.top_cell.remove(*assembly.top_cell.polygons)
        assembly.top_cell.add(*keep)
        for tp in new_mte_tp:
            assembly.top_cell.add(
                gdstk.Polygon(tp.polygon.points, layer=tp.polygon.layer, datatype=tp.polygon.datatype)
            )
        for tp in new_mbe_tp:
            assembly.top_cell.add(
                gdstk.Polygon(tp.polygon.points, layer=tp.polygon.layer, datatype=tp.polygon.datatype)
            )

        roles.preserved.mte = new_mte_tp
        roles.preserved.mbe = new_mbe_tp
        report[idx] = {"mte_removed": mte_removed, "mbe_removed": mbe_removed}

    return report


__all__ = [
    "MteNormalizeConfig",
    "normalize_mte_for_collar_extend",
    "normalize_mbe_for_collar_extend",
    "normalize_mte_collar_extent_all",
]
