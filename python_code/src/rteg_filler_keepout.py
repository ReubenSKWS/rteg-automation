"""
Step 5.3b — MBE width-filler keepout vs resonator outline.

For ``collar_extend`` resonators (MTE does not face the center pad), the step-4
MBE rectangle filler can intersect the grounded MTE extension. Filler metal
outside the horizontal span of that intersection is carved back using a
``clearance_um`` keepout that follows the resonator body outline (MBE + MTE).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

import gdstk

from layermap import LayerMap
from rteg_classify import NodeClassification
from rteg_route_new import ResonatorRoute, _overlap_area, split_bridging_orphans

Point = tuple[float, float]
_BIG = 1e5

DEFAULT_FILLER_KEEPOUT_CLEARANCE_UM = 20.0
DEFAULT_FILLER_MTE_CLEARANCE_UM = DEFAULT_FILLER_KEEPOUT_CLEARANCE_UM


@dataclass(frozen=True)
class FillerKeepoutConfig:
    clearance_um: float = DEFAULT_FILLER_KEEPOUT_CLEARANCE_UM
    boolean_precision: float = 1e-3
    mbe_body_overlap_frac: float = 0.4


@dataclass(frozen=True)
class FillerKeepoutResult:
    applied: bool
    intersection_x_span: tuple[float, float] | None
    intersection_area_um2: float
    filler_area_before_um2: float
    filler_area_after_um2: float
    n_body_pieces: int

    def summary_row(
        self,
        *,
        index: int,
        inst_name: str,
        mte_route_target: str,
    ) -> dict[str, object]:
        x_lo, x_hi = self.intersection_x_span or (None, None)
        return {
            "index": index,
            "inst_name": inst_name,
            "mte_route_target": mte_route_target,
            "applied": self.applied,
            "intersect_x_lo": round(x_lo, 2) if x_lo is not None else None,
            "intersect_x_hi": round(x_hi, 2) if x_hi is not None else None,
            "intersect_area_um2": round(self.intersection_area_um2, 1),
            "filler_area_before_um2": round(self.filler_area_before_um2, 1),
            "filler_area_after_um2": round(self.filler_area_after_um2, 1),
            "area_removed_um2": round(self.filler_area_before_um2 - self.filler_area_after_um2, 1),
            "n_body_pieces": self.n_body_pieces,
        }


def filler_keepout_applies(classification: NodeClassification) -> bool:
    """Only when MTE does not face the center pad."""
    return classification.mte_route_target == "collar_extend"


def collar_extend_indices(
    classifications: dict[int, NodeClassification],
    *,
    indices: Sequence[int] | None = None,
) -> list[int]:
    """Pipeline indices that qualify for step 5.3b (``collar_extend`` only)."""
    keys = indices if indices is not None else sorted(classifications)
    return [
        idx for idx in keys
        if idx in classifications and filler_keepout_applies(classifications[idx])
    ]


def center_pad_indices(
    classifications: dict[int, NodeClassification],
    *,
    indices: Sequence[int] | None = None,
) -> list[int]:
    """Pipeline indices skipped by step 5.3b (``center_pad``)."""
    keys = indices if indices is not None else sorted(classifications)
    return [
        idx for idx in keys
        if idx in classifications and not filler_keepout_applies(classifications[idx])
    ]


def _filler_nets_signature(route: ResonatorRoute) -> tuple[tuple[int, float, tuple[float, ...]], ...]:
    """Comparable fingerprint for ``route.filler_nets`` geometry."""
    pieces: list[tuple[int, float, tuple[float, ...]]] = []
    for poly in route.filler_nets:
        bb = poly.bounding_box()
        flat_bb = (
            round(bb[0][0], 3), round(bb[0][1], 3),
            round(bb[1][0], 3), round(bb[1][1], 3),
        ) if bb else (0.0, 0.0, 0.0, 0.0)
        pieces.append((len(poly.points), round(abs(poly.area()), 3), flat_bb))
    return tuple(sorted(pieces))


def center_pad_keepout_check_rows(
    routes_before: dict[int, ResonatorRoute],
    routes_after: dict[int, ResonatorRoute],
    classifications: dict[int, NodeClassification],
    *,
    area_tol_um2: float = 0.01,
) -> list[dict[str, object]]:
    """One row per ``center_pad`` index confirming filler nets were not modified."""
    rows: list[dict[str, object]] = []
    for idx in center_pad_indices(classifications, indices=sorted(routes_before)):
        if idx not in routes_after:
            continue
        before = routes_before[idx]
        after = routes_after[idx]
        area_before = sum(abs(p.area()) for p in before.filler_nets)
        area_after = sum(abs(p.area()) for p in after.filler_nets)
        sig_match = _filler_nets_signature(before) == _filler_nets_signature(after)
        unchanged = sig_match and abs(area_after - area_before) <= area_tol_um2
        rows.append({
            "index": idx,
            "mte_route_target": classifications[idx].mte_route_target,
            "unchanged": unchanged,
            "filler_pieces_before": len(before.filler_nets),
            "filler_pieces_after": len(after.filler_nets),
            "filler_area_delta_um2": round(area_after - area_before, 4),
        })
    return rows


def assert_center_pad_routes_unchanged(
    routes_before: dict[int, ResonatorRoute],
    routes_after: dict[int, ResonatorRoute],
    classifications: dict[int, NodeClassification],
    *,
    area_tol_um2: float = 0.01,
) -> None:
    """Raise if any ``center_pad`` route filler geometry changed."""
    for row in center_pad_keepout_check_rows(
        routes_before, routes_after, classifications, area_tol_um2=area_tol_um2,
    ):
        if not row["unchanged"]:
            raise ValueError(
                f"step 5.3b must not modify center_pad index {row['index']}: "
                f"filler area delta {row['filler_area_delta_um2']} µm²"
            )


def _poly_points(poly: gdstk.Polygon) -> list[Point]:
    return [(float(x), float(y)) for x, y in poly.points]


def _resonator_body_polys(roles: object) -> list[gdstk.Polygon]:
    return [*roles.resonator_body_mte, *roles.resonator_body_mbe]


def _mte_extension_polys(roles: object, cfg: FillerKeepoutConfig) -> list[gdstk.Polygon]:
    """Grounded MTE extension used only to locate the filler intersection x-span."""
    all_mte = [tp.polygon for tp in roles.preserved.mte]
    body_mte = list(roles.resonator_body_mte)
    body_mbe = list(roles.resonator_body_mbe)
    precision = cfg.boolean_precision
    g_bridging, _orphans = split_bridging_orphans(all_mte, body_mte, precision=precision)
    ext = [
        p for p in g_bridging
        if _overlap_area(p, body_mbe, precision=precision)
        < cfg.mbe_body_overlap_frac * abs(p.area())
    ]
    if ext:
        return ext

    filler = [tp.polygon for tp in roles.ground_plates.filler]
    if not filler:
        return []
    touching: list[gdstk.Polygon] = []
    for p in all_mte:
        if gdstk.boolean(filler, [p], "and", precision=precision):
            touching.append(p)
    return touching


def _intersection_x_span(
    filler: Sequence[gdstk.Polygon],
    mte: Sequence[gdstk.Polygon],
    *,
    precision: float,
) -> tuple[tuple[float, float] | None, float]:
    inter = gdstk.boolean(list(filler), list(mte), "and", precision=precision)
    if not inter:
        return None, 0.0
    xs: list[float] = []
    area = 0.0
    for p in inter:
        area += abs(p.area())
        bb = p.bounding_box()
        if bb:
            xs.extend([bb[0][0], bb[1][0]])
    if not xs:
        return None, area
    return (min(xs), max(xs)), area


def _outside_x_masks(x_lo: float, x_hi: float, y_lo: float, y_hi: float) -> list[gdstk.Polygon]:
    return [
        gdstk.Polygon([(-_BIG, y_lo), (-_BIG, y_hi), (x_lo, y_hi), (x_lo, y_lo)]),
        gdstk.Polygon([(x_hi, y_lo), (x_hi, y_hi), (_BIG, y_hi), (_BIG, y_lo)]),
    ]


def _resonator_keepout_zone(
    body_polys: Sequence[gdstk.Polygon],
    clearance_um: float,
    *,
    precision: float,
) -> list[gdstk.Polygon]:
    """Grow a keepout ring that outlines the resonator body shape."""
    if not body_polys or clearance_um <= 0:
        return []
    merged = gdstk.boolean(list(body_polys), [], "or", precision=precision)
    source = merged if merged else list(body_polys)
    return gdstk.offset(source, clearance_um, join="round", precision=precision)


def _keepout_cut_outside_span(
    body_polys: Sequence[gdstk.Polygon],
    x_span: tuple[float, float],
    y_span: tuple[float, float],
    *,
    clearance_um: float,
    precision: float,
) -> list[gdstk.Polygon]:
    keepout = _resonator_keepout_zone(body_polys, clearance_um, precision=precision)
    if not keepout:
        return []
    x_lo, x_hi = x_span
    y_lo, y_hi = y_span
    cut: list[gdstk.Polygon] = []
    for mask in _outside_x_masks(x_lo, x_hi, y_lo, y_hi):
        cut.extend(gdstk.boolean(keepout, [mask], "and", precision=precision))
    return cut


def _carve_polys(
    polys: Sequence[gdstk.Polygon],
    cut: Sequence[gdstk.Polygon],
    *,
    precision: float,
) -> list[gdstk.Polygon]:
    if not polys:
        return []
    if not cut:
        return list(polys)
    out: list[gdstk.Polygon] = []
    for poly in polys:
        carved = gdstk.boolean([poly], list(cut), "not", precision=precision)
        if carved:
            out.extend(carved)
    return out


def carve_rectangle_filler_outside_intersection(
    filler_plate: Sequence[gdstk.Polygon],
    mte_polys: Sequence[gdstk.Polygon],
    resonator_body_polys: Sequence[gdstk.Polygon],
    *,
    cfg: FillerKeepoutConfig | None = None,
) -> tuple[list[gdstk.Polygon], FillerKeepoutResult]:
    """Carve the MBE rectangle plate outside the MTE intersection x-span."""
    cfg = cfg or FillerKeepoutConfig()
    precision = cfg.boolean_precision
    plate = list(filler_plate)
    mte = list(mte_polys)
    body = list(resonator_body_polys)
    area_before = sum(abs(p.area()) for p in plate)

    span, inter_area = _intersection_x_span(plate, mte, precision=precision)
    if span is None or not mte or not plate or not body:
        return plate, FillerKeepoutResult(
            applied=False,
            intersection_x_span=span,
            intersection_area_um2=inter_area,
            filler_area_before_um2=area_before,
            filler_area_after_um2=area_before,
            n_body_pieces=len(body),
        )

    ys: list[float] = []
    for p in plate:
        bb = p.bounding_box()
        if bb:
            ys.extend([bb[0][1], bb[1][1]])
    if not ys:
        return plate, FillerKeepoutResult(
            applied=False,
            intersection_x_span=span,
            intersection_area_um2=inter_area,
            filler_area_before_um2=area_before,
            filler_area_after_um2=area_before,
            n_body_pieces=len(body),
        )

    cut = _keepout_cut_outside_span(
        body, span, (min(ys), max(ys)),
        clearance_um=cfg.clearance_um, precision=precision,
    )
    carved = _carve_polys(plate, cut, precision=precision) or plate
    area_after = sum(abs(p.area()) for p in carved)
    return carved, FillerKeepoutResult(
        applied=True,
        intersection_x_span=span,
        intersection_area_um2=inter_area,
        filler_area_before_um2=area_before,
        filler_area_after_um2=area_after,
        n_body_pieces=len(body),
    )


def apply_filler_keepout_to_route(
    route: ResonatorRoute,
    roles: object,
    classification: NodeClassification,
    layermap: LayerMap,
    *,
    cfg: FillerKeepoutConfig | None = None,
) -> tuple[ResonatorRoute, FillerKeepoutResult]:
    """Apply resonator-outline filler keepout to one routed resonator."""
    _ = layermap
    cfg = cfg or FillerKeepoutConfig()
    precision = cfg.boolean_precision
    empty = FillerKeepoutResult(False, None, 0.0, 0.0, 0.0, 0)

    if not filler_keepout_applies(classification):
        area = sum(abs(p.area()) for p in route.filler_nets)
        return route, FillerKeepoutResult(
            applied=False,
            intersection_x_span=None,
            intersection_area_um2=0.0,
            filler_area_before_um2=area,
            filler_area_after_um2=area,
            n_body_pieces=0,
        )

    filler_plate = [tp.polygon for tp in roles.ground_plates.filler]
    if not filler_plate or not route.filler_nets:
        return route, empty

    body_polys = _resonator_body_polys(roles)
    mte_polys = _mte_extension_polys(roles, cfg)
    span, inter_area = _intersection_x_span(filler_plate, mte_polys, precision=precision)
    if span is None or not mte_polys or not body_polys:
        area = sum(abs(p.area()) for p in route.filler_nets)
        return route, FillerKeepoutResult(
            applied=False,
            intersection_x_span=span,
            intersection_area_um2=inter_area,
            filler_area_before_um2=area,
            filler_area_after_um2=area,
            n_body_pieces=len(body_polys),
        )

    area_before = sum(abs(p.area()) for p in route.filler_nets)
    ys: list[float] = []
    for p in filler_plate:
        bb = p.bounding_box()
        if bb:
            ys.extend([bb[0][1], bb[1][1]])
    cut = _keepout_cut_outside_span(
        body_polys, span, (min(ys), max(ys)),
        clearance_um=cfg.clearance_um, precision=precision,
    )

    new_nets: list[gdstk.Polygon] = []
    for net_poly in route.filler_nets:
        plate_parts = gdstk.boolean([net_poly], filler_plate, "and", precision=precision) or []
        other_parts = gdstk.boolean([net_poly], filler_plate, "not", precision=precision) or []
        carved_plate = _carve_polys(plate_parts, cut, precision=precision)
        merged = gdstk.boolean([*carved_plate, *other_parts], [], "or", precision=precision) or []
        if not merged:
            new_nets.append(net_poly)
            continue
        for piece in merged:
            new_nets.append(
                gdstk.Polygon(_poly_points(piece), net_poly.layer, net_poly.datatype)
            )

    area_after = sum(abs(p.area()) for p in new_nets)
    result = FillerKeepoutResult(
        applied=True,
        intersection_x_span=span,
        intersection_area_um2=inter_area,
        filler_area_before_um2=area_before,
        filler_area_after_um2=area_after,
        n_body_pieces=len(body_polys),
    )
    return replace(route, filler_nets=new_nets), result


def apply_filler_keepout_all_routes(
    routes: dict[int, ResonatorRoute],
    roles_by_index: dict[int, object],
    classifications: dict[int, NodeClassification],
    layermap: LayerMap,
    *,
    indices: Sequence[int] | None = None,
    cfg: FillerKeepoutConfig | None = None,
) -> dict[int, ResonatorRoute]:
    """Apply step 5.3b filler keepout to ``collar_extend`` resonators only."""
    out = dict(routes)
    for idx in collar_extend_indices(classifications, indices=indices):
        if idx not in routes or idx not in roles_by_index:
            continue
        cleaned, _ = apply_filler_keepout_to_route(
            routes[idx],
            roles_by_index[idx],
            classifications[idx],
            layermap,
            cfg=cfg,
        )
        out[idx] = cleaned
    assert_center_pad_routes_unchanged(routes, out, classifications)
    return out


def filler_keepout_overview_rows(
    routes: dict[int, ResonatorRoute],
    roles_by_index: dict[int, object],
    classifications: dict[int, NodeClassification],
    layermap: LayerMap,
    *,
    indices: Sequence[int] | None = None,
    cfg: FillerKeepoutConfig | None = None,
    include_skipped: bool = False,
) -> list[dict[str, object]]:
    """Preview keepout stats without mutating routes."""
    keys = indices if indices is not None else sorted(routes)
    rows: list[dict[str, object]] = []
    for idx in keys:
        if idx not in routes or idx not in roles_by_index or idx not in classifications:
            continue
        classification = classifications[idx]
        if not include_skipped and not filler_keepout_applies(classification):
            continue
        roles = roles_by_index[idx]
        _, result = apply_filler_keepout_to_route(
            routes[idx], roles, classification, layermap, cfg=cfg,
        )
        rows.append(
            result.summary_row(
                index=idx,
                inst_name=roles.inst_name,
                mte_route_target=classification.mte_route_target,
            )
        )
    return rows


__all__ = [
    "DEFAULT_FILLER_KEEPOUT_CLEARANCE_UM",
    "DEFAULT_FILLER_MTE_CLEARANCE_UM",
    "FillerKeepoutConfig",
    "FillerKeepoutResult",
    "apply_filler_keepout_all_routes",
    "apply_filler_keepout_to_route",
    "assert_center_pad_routes_unchanged",
    "carve_rectangle_filler_outside_intersection",
    "center_pad_indices",
    "center_pad_keepout_check_rows",
    "collar_extend_indices",
    "filler_keepout_applies",
    "filler_keepout_overview_rows",
]
