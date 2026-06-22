"""
Step 5.3 — MTE collar extensions.

1. select_extension_collar — smallest preserved BAW_MTE piece with body overlap;
   if only a large stadium piece overlaps, prefer the much smaller edge collar.
2. find_outward_lip_ab — long collar edge with best merge feasibility at both
   mouth corners A and B; tie-break by mouth width and body-overlap proximity.
3. draw_lip_extension — inward merge (default 4 µm), optional shift into the collar
   so edges meet in layout viewers, then 14 µm outward cap.
"""
from __future__ import annotations

import math
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import gdstk

from export_gds import ExportResult, export_gds
from layermap import LayerMap
from prep_rteg_frame import RtegFrameAssembly
from rteg_collect import (
    PreservedMetal,
    TaggedPolygon,
    _polygon_key,
    polys_touch,
    preserved_mte_overlap_with_body,
)
from rteg_utils import assign_layer

Point = tuple[float, float]
Edge = tuple[Point, Point]


@dataclass(frozen=True)
class MteBuildConfig:
    """Tunable parameters for step 5.3 MTE collar extensions."""

    mte_layer: str = "BAW_MTE"
    collar_extension_um: float = 14.0
    collar_merge_inset_um: float = 4.0
    collar_touch_overlap_um: float = 0.5
    min_collar_overlap_um2: float = 0.01
    stadium_collar_area_um2: float = 2500.0
    stadium_edge_area_ratio: float = 0.6
    lip_long_edge_peak_fraction: float = 0.15
    lip_long_edge_min_um: float = 8.0
    max_overlap_fraction: float = 0.99
    min_merge_inset_check_um: float = 0.5
    min_connection_overlap_fraction: float = 0.10
    min_connection_merge_um: float = 1.0
    min_mouth_coverage_fraction: float = 0.65
    min_mouth_coverage_shunt_fraction: float = 0.85
    collar_association_gap_um: float = 35.0
    max_edge_collar_area_um2: float = 800.0
    stadium_tab_mouth_min_um: float = 12.0
    stadium_tab_mouth_max_um: float = 45.0
    boolean_precision: float = 1e-3
    inside_probe_half_um: float = 0.25
    feasible_merge_search_iterations: int = 24
    pad_facing_min_edge_um: float = 5.0
    pad_facing_prefer_vertical_bonus: float = 0.05
    die_intercept_min_mouth_um: float = 50.0


@dataclass(frozen=True)
class LipIntercept:
    """Outward long-lip walk from corner A to corner B."""

    point_a: Point
    point_b: Point
    lip_vertex_indices: list[int]
    outward_normal: tuple[float, float]
    lip_edges: list[int]


@dataclass(frozen=True)
class CollarExtensionDraw:
    polygon: gdstk.Polygon
    intercept_a: Point
    intercept_b: Point
    outer_edge: Edge
    extension_um: float
    target_extension_um: float
    endcap_edge_a: Edge = ((0.0, 0.0), (0.0, 0.0))
    endcap_edge_b: Edge = ((0.0, 0.0), (0.0, 0.0))
    endcap_index_a: int = -1
    endcap_index_b: int = -1
    mouth_span_um: float = 0.0
    mouth_vertices: int = 0
    collar_intercept_a: Point = (0.0, 0.0)
    collar_intercept_b: Point = (0.0, 0.0)
    merge_inset_a_um: float = 0.0
    merge_inset_b_um: float = 0.0


@dataclass
class MteExtensionResult:
    collar: TaggedPolygon | None
    extension: gdstk.Polygon | None
    preserved_collar_polygons: list[gdstk.Polygon]
    n_extensions: int
    is_connected: bool
    collar_overlap_um2: float = 0.0
    extension_draw: CollarExtensionDraw | None = None
    route_draw: object | None = None  # MteRouteDraw when step 5.4 routed
    routed_net: gdstk.Polygon | None = None
    drc_violations: list[str] = field(default_factory=list)


class _HasPreserved(Protocol):
    preserved: PreservedMetal
    resonator_body_mte: Sequence[gdstk.Polygon]


def _polygon_centroid(poly: gdstk.Polygon) -> Point:
    pts = poly.points
    if len(pts) == 0:
        return (0.0, 0.0)
    cx = sum(float(p[0]) for p in pts) / len(pts)
    cy = sum(float(p[1]) for p in pts) / len(pts)
    return (cx, cy)


def _body_centroid(body_mte_polys: Sequence[gdstk.Polygon]) -> Point:
    total = 0.0
    cx = cy = 0.0
    for poly in body_mte_polys:
        area = abs(poly.area())
        if area < 1e-12:
            continue
        pcx, pcy = _polygon_centroid(poly)
        cx += pcx * area
        cy += pcy * area
        total += area
    if total > 1e-12:
        return (cx / total, cy / total)
    if not body_mte_polys:
        return (0.0, 0.0)
    xs: list[float] = []
    ys: list[float] = []
    for poly in body_mte_polys:
        for p in poly.points:
            xs.append(float(p[0]))
            ys.append(float(p[1]))
    return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)


def _edge_length(p0: Point, p1: Point) -> float:
    return math.hypot(p1[0] - p0[0], p1[1] - p0[1])


def _edge_points(pts: Sequence[Point], edge_idx: int) -> Edge:
    n = len(pts)
    return (
        (float(pts[edge_idx][0]), float(pts[edge_idx][1])),
        (float(pts[(edge_idx + 1) % n][0]), float(pts[(edge_idx + 1) % n][1])),
    )


def _long_edge_indices(
    lengths: Sequence[float],
    *,
    peak_fraction: float,
    min_um: float,
) -> set[int]:
    peak = max(lengths) if lengths else 0.0
    threshold = max(peak * peak_fraction, min_um)
    return {i for i, length in enumerate(lengths) if length > threshold}


def _dist(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _edge_outward_normal(edge: Edge, body_centroid: Point) -> tuple[float, float]:
    p0, p1 = edge
    mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
    tx, ty = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(tx, ty)
    if length < 1e-9:
        dx, dy = mid[0] - body_centroid[0], mid[1] - body_centroid[1]
        length = math.hypot(dx, dy)
        return (dx / length, dy / length) if length > 1e-9 else (0.0, 1.0)
    tx, ty = tx / length, ty / length
    for nx, ny in ((-ty, tx), (ty, -tx)):
        if (mid[0] - body_centroid[0]) * nx + (mid[1] - body_centroid[1]) * ny > 1e-6:
            return (nx, ny)
    return (-ty, tx)


def _vertices_from_edge_chain(chain: Sequence[int], n: int) -> list[int]:
    if not chain:
        return []
    verts = [chain[0]]
    for edge in chain:
        end = (edge + 1) % n
        if verts[-1] != end:
            verts.append(end)
    return verts


def _is_stadium_collar(poly: gdstk.Polygon, cfg: MteBuildConfig) -> bool:
    return abs(poly.area()) >= cfg.stadium_collar_area_um2


def _is_edge_collar_tab(poly: gdstk.Polygon, cfg: MteBuildConfig) -> bool:
    """Separate collar piece — smaller than the closed stadium shell."""
    return abs(poly.area()) < cfg.stadium_collar_area_um2


def _is_extension_collar_candidate(poly: gdstk.Polygon, cfg: MteBuildConfig) -> bool:
    """Only small tabs or the stadium shell — never the die-wide interconnect bus."""
    return _is_edge_collar_tab(poly, cfg) or _is_stadium_collar(poly, cfg)


def _associated_edge_collars_from_pieces(
    pieces: Sequence[TaggedPolygon],
    cfg: MteBuildConfig,
) -> list[TaggedPolygon]:
    """Small edge tabs that boolean-touch a stadium piece in the same preserved set."""
    stadium_pieces = [
        tp for tp in pieces if _is_stadium_collar(tp.polygon, cfg)
    ]
    if not stadium_pieces:
        return []
    edge_tabs = [tp for tp in pieces if _is_edge_collar_tab(tp.polygon, cfg)]
    associated: list[TaggedPolygon] = []
    stadium_keys = {_polygon_key(stadium.polygon) for stadium in stadium_pieces}
    for tp in edge_tabs:
        if _polygon_key(tp.polygon) in stadium_keys:
            continue
        if any(
            polys_touch(
                tp.polygon,
                stadium.polygon,
                precision=cfg.boolean_precision,
            )
            for stadium in stadium_pieces
            if _polygon_key(stadium.polygon) != _polygon_key(tp.polygon)
        ):
            associated.append(tp)
    return associated


def _associated_edge_collars(
    preserved: PreservedMetal,
    cfg: MteBuildConfig,
) -> list[TaggedPolygon]:
    return _associated_edge_collars_from_pieces(preserved.mte, cfg)


def select_extension_collar_from_pieces(
    pieces: Sequence[TaggedPolygon],
    body_polys: Sequence[gdstk.Polygon],
    overlap_with_body,
    cfg: MteBuildConfig | None = None,
) -> TaggedPolygon | None:
    """
    Pick the extension collar from a preserved metal set.

    Prefer the small edge collar tab over the stadium shell when both are
    present. Collect often yields two pieces — resonator outline plus edge
    collar; the extension collar is the smaller piece at the interconnect mouth.
    """
    c = cfg or MteBuildConfig()
    if not pieces:
        return None

    associated_edges = _associated_edge_collars_from_pieces(pieces, c)
    if associated_edges:
        with_body = [
            tp
            for tp in associated_edges
            if overlap_with_body(tp.polygon, body_polys, precision=c.boolean_precision)
            >= c.min_collar_overlap_um2
        ]
        if with_body:
            return min(with_body, key=lambda tp: abs(tp.polygon.area()))
        return min(associated_edges, key=lambda tp: abs(tp.polygon.area()))

    overlapping = [
        tp
        for tp in pieces
        if _is_extension_collar_candidate(tp.polygon, c)
        and overlap_with_body(tp.polygon, body_polys, precision=c.boolean_precision)
        >= c.min_collar_overlap_um2
    ]
    if overlapping:
        smallest_overlap = min(overlapping, key=lambda tp: abs(tp.polygon.area()))
        smallest_all = min(pieces, key=lambda tp: abs(tp.polygon.area()))
        overlap_area = abs(smallest_overlap.polygon.area())
        edge_overlap = overlap_with_body(
            smallest_all.polygon, body_polys, precision=c.boolean_precision
        )
        stadium_targets = [
            tp for tp in overlapping if _is_stadium_collar(tp.polygon, c)
        ]
        if (
            overlap_area >= c.stadium_collar_area_um2
            and _is_edge_collar_tab(smallest_all.polygon, c)
            and smallest_all not in overlapping
            and edge_overlap >= c.min_collar_overlap_um2
            and stadium_targets
            and any(
                polys_touch(
                    smallest_all.polygon,
                    stadium.polygon,
                    precision=c.boolean_precision,
                )
                for stadium in stadium_targets
            )
        ):
            return smallest_all
        return smallest_overlap

    stadium_pieces = [tp for tp in pieces if _is_stadium_collar(tp.polygon, c)]
    if stadium_pieces:
        return min(stadium_pieces, key=lambda tp: abs(tp.polygon.area()))

    return min(pieces, key=lambda tp: abs(tp.polygon.area()))


def select_extension_collar(
    preserved: PreservedMetal,
    body_mte_polys: Sequence[gdstk.Polygon],
    cfg: MteBuildConfig | None = None,
) -> TaggedPolygon | None:
    """Pick the extension collar on ``BAW_MTE`` (layermap 5/0)."""
    return select_extension_collar_from_pieces(
        preserved.mte,
        body_mte_polys,
        preserved_mte_overlap_with_body,
        cfg,
    )


def _collar_body_overlap_centroid(
    collar: gdstk.Polygon,
    body_mte_polys: Sequence[gdstk.Polygon],
    *,
    precision: float,
) -> Point | None:
    """Area-weighted centroid of ``collar ∩ body``; ``None`` when disjoint."""
    total = 0.0
    cx = cy = 0.0
    for body in body_mte_polys:
        inter = gdstk.boolean(collar, body, "and", precision=precision)
        if not inter:
            continue
        for piece in inter:
            area = abs(piece.area())
            if area < 1e-12:
                continue
            pcx, pcy = _polygon_centroid(piece)
            cx += pcx * area
            cy += pcy * area
            total += area
    if total < 1e-12:
        return None
    return (cx / total, cy / total)


def _lip_candidate_score(
    collar: gdstk.Polygon,
    pts: Sequence[Point],
    edge_idx: int,
    body_mte_polys: Sequence[gdstk.Polygon],
    body_centroid: Point,
    body_overlap_centroid: Point | None,
    cfg: MteBuildConfig,
) -> tuple[float, float, float]:
    """
    Rank key for one lip edge: ``(min_merge_um, edge_length_um, body_proximity)``.
    """
    p0, p1 = _edge_points(pts, edge_idx)
    outward = _edge_outward_normal((p0, p1), body_centroid)
    merge_a = _feasible_merge_um(
        p0,
        outward,
        collar,
        cfg.collar_merge_inset_um,
        precision=cfg.boolean_precision,
        probe_half_um=cfg.inside_probe_half_um,
        search_iterations=cfg.feasible_merge_search_iterations,
    )
    merge_b = _feasible_merge_um(
        p1,
        outward,
        collar,
        cfg.collar_merge_inset_um,
        precision=cfg.boolean_precision,
        probe_half_um=cfg.inside_probe_half_um,
        search_iterations=cfg.feasible_merge_search_iterations,
    )
    min_merge = min(merge_a, merge_b)
    edge_len = _edge_length(p0, p1)
    mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
    ref = body_overlap_centroid if body_overlap_centroid is not None else body_centroid
    body_proximity = 1.0 / (_dist(mid, ref) + 1e-3)
    return (min_merge, edge_len, body_proximity)


def find_outward_lip_ab(
    collar: gdstk.Polygon,
    body_mte_polys: Sequence[gdstk.Polygon],
    cfg: MteBuildConfig | None = None,
) -> LipIntercept:
    """
    Find intercept corners A and B on the extension collar mouth.

    Picks the long edge that allows the deepest symmetric inward merge at both
    corners, then prefers a wider mouth and proximity to the collar/body overlap.
    """
    c = cfg or MteBuildConfig()
    pts = [(float(p[0]), float(p[1])) for p in collar.points]
    if len(pts) < 4:
        raise ValueError("collar must have at least 4 vertices")

    body_centroid = _body_centroid(body_mte_polys)
    body_overlap_centroid = _collar_body_overlap_centroid(
        collar, body_mte_polys, precision=c.boolean_precision
    )

    n = len(pts)
    lengths = [_edge_length(pts[i], pts[(i + 1) % n]) for i in range(n)]

    def score_edge(edge_idx: int) -> tuple[float, float, float]:
        return _lip_candidate_score(
            collar,
            pts,
            edge_idx,
            body_mte_polys,
            body_centroid,
            body_overlap_centroid,
            c,
        )

    collar_area = abs(collar.area())
    if collar_area >= c.stadium_collar_area_um2:
        tab_edges = [
            i
            for i in range(n)
            if c.stadium_tab_mouth_min_um <= lengths[i] <= c.stadium_tab_mouth_max_um
        ]
        viable_tabs = [
            edge_idx
            for edge_idx in tab_edges
            if score_edge(edge_idx)[0] >= c.min_merge_inset_check_um * 0.6
        ]
        if viable_tabs:
            best_seed = max(viable_tabs, key=score_edge)
            lip_edges = [best_seed]
            lip_vertices = _vertices_from_edge_chain(lip_edges, n)
            point_a = (pts[lip_vertices[0]][0], pts[lip_vertices[0]][1])
            point_b = (pts[lip_vertices[-1]][0], pts[lip_vertices[-1]][1])
            seed_edge = _edge_points(pts, best_seed)
            outward_normal = _edge_outward_normal(seed_edge, body_centroid)
            return LipIntercept(
                point_a=point_a,
                point_b=point_b,
                lip_vertex_indices=lip_vertices,
                outward_normal=outward_normal,
                lip_edges=lip_edges,
            )

    long_edges = _long_edge_indices(
        lengths,
        peak_fraction=c.lip_long_edge_peak_fraction,
        min_um=c.lip_long_edge_min_um,
    )
    if not long_edges:
        raise ValueError("collar has no long edges")

    collar_bb = collar.bounding_box()
    collar_width = 0.0
    if collar_bb is not None:
        (x0, y0), (x1, y1) = collar_bb
        collar_width = max(x1 - x0, y1 - y0)
    min_merge_floor = c.min_merge_inset_check_um * 0.6

    wide_edges = [
        edge_idx
        for edge_idx in long_edges
        if collar_width > 1e-6
        and lengths[edge_idx] / collar_width >= c.min_mouth_coverage_fraction
        and score_edge(edge_idx)[0] >= min_merge_floor
    ]
    if wide_edges:
        best_seed = max(
            wide_edges,
            key=lambda edge_idx: (
                lengths[edge_idx] / collar_width,
                score_edge(edge_idx),
            ),
        )
    else:
        best_seed = max(long_edges, key=score_edge)

    lip_edges = [best_seed]
    lip_vertices = _vertices_from_edge_chain(lip_edges, n)
    if len(lip_vertices) < 2:
        raise ValueError("outward lip chain is degenerate")

    point_a = (pts[lip_vertices[0]][0], pts[lip_vertices[0]][1])
    point_b = (pts[lip_vertices[-1]][0], pts[lip_vertices[-1]][1])
    seed_edge = _edge_points(pts, best_seed)
    outward_normal = _edge_outward_normal(seed_edge, body_centroid)

    return LipIntercept(
        point_a=point_a,
        point_b=point_b,
        lip_vertex_indices=lip_vertices,
        outward_normal=outward_normal,
        lip_edges=lip_edges,
    )


def infer_probe_reference(body_polys: Sequence[gdstk.Polygon]) -> Point:
    """
    Filter-die probe direction for left-side (center-pad) probing.

    Without RTEG pad geometry, assume the signal pad lies far to the left (-x)
    of the resonator body centroid — consistent with KB331 center-pad series.
    """
    cx, cy = _body_centroid(body_polys)
    return (cx - 500.0, cy)


def find_pad_facing_mouth_lip(
    collar: gdstk.Polygon,
    body_polys: Sequence[gdstk.Polygon],
    cfg: MteBuildConfig | None = None,
    *,
    probe_ref: Point | None = None,
) -> LipIntercept:
    """
    Pad-facing collar mouth for die intercept capture.

    Picks the longest edge whose outward normal best aligns with the probe pad,
    preferring vertical mouths (reference layouts use ~81 µm vertical strips).
    """
    c = cfg or MteBuildConfig()
    pad_ref = probe_ref if probe_ref is not None else infer_probe_reference(body_polys)
    pts = [(float(p[0]), float(p[1])) for p in collar.points]
    if len(pts) < 4:
        raise ValueError("collar must have at least 4 vertices")

    body_centroid = _body_centroid(body_polys)
    n = len(pts)
    best: tuple[tuple[float, float, float], int, Edge, tuple[float, float]] | None = None
    for edge_idx in range(n):
        p0, p1 = _edge_points(pts, edge_idx)
        edge_len = _edge_length(p0, p1)
        if edge_len < c.pad_facing_min_edge_um:
            continue
        outward = _edge_outward_normal((p0, p1), body_centroid)
        mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
        to_pad = (pad_ref[0] - mid[0], pad_ref[1] - mid[1])
        to_pad_len = math.hypot(to_pad[0], to_pad[1])
        if to_pad_len < 1e-9:
            continue
        alignment = (
            outward[0] * to_pad[0] / to_pad_len + outward[1] * to_pad[1] / to_pad_len
        )
        vertical_bonus = (
            c.pad_facing_prefer_vertical_bonus
            if abs(p0[0] - p1[0]) <= 0.5
            else 0.0
        )
        score = (alignment + vertical_bonus, edge_len, -abs(edge_len - 81.0))
        if best is None or score > best[0]:
            best = (score, edge_idx, (p0, p1), outward)

    if best is None:
        raise ValueError("collar has no edge facing the probe pad")

    edge_idx, (p0, p1), outward = best[1], best[2], best[3]
    return LipIntercept(
        point_a=(p0[0], p0[1]),
        point_b=(p1[0], p1[1]),
        lip_vertex_indices=[edge_idx, (edge_idx + 1) % n],
        outward_normal=outward,
        lip_edges=[edge_idx],
    )


def select_die_intercept_collar_from_pieces(
    pieces: Sequence[TaggedPolygon],
    body_polys: Sequence[gdstk.Polygon],
    overlap_with_body,
    cfg: MteBuildConfig | None = None,
    *,
    layer: str = "mte",
) -> TaggedPolygon | None:
    """
    Pick the connect collar whose pad-facing mouth best matches reference layouts.

    For MTE, prefer the stadium shell over the augmented edge tab when both are
    present — reference RTEG mouths sit on the stadium vertical edge. For MBE,
    score all candidates by pad-facing vertical mouth quality, not only body
    overlap (ground collars may not overlap resonator body MBE).
    """
    c = cfg or MteBuildConfig()
    if not pieces:
        return None

    probe_ref = infer_probe_reference(body_polys)
    candidates = list(pieces)
    if layer == "mte":
        stadiums = [tp for tp in pieces if _is_stadium_collar(tp.polygon, c)]
        if stadiums:
            candidates = stadiums

    scored: list[tuple[tuple[float, float, float], TaggedPolygon]] = []
    for tp in candidates:
        try:
            lip = find_pad_facing_mouth_lip(
                tp.polygon, body_polys, c, probe_ref=probe_ref
            )
        except ValueError:
            continue
        span = _dist(lip.point_a, lip.point_b)
        if span < c.die_intercept_min_mouth_um:
            continue
        overlap = overlap_with_body(
            tp.polygon, body_polys, precision=c.boolean_precision
        )
        vertical = abs(lip.point_a[0] - lip.point_b[0]) <= 0.5
        score = (
            1.0 if vertical else 0.0,
            span,
            overlap,
            -abs(tp.polygon.area()),
        )
        scored.append((score, tp))

    if scored:
        return max(scored, key=lambda item: item[0])[1]

    return select_extension_collar_from_pieces(
        pieces, body_polys, overlap_with_body, c
    )


def _point_inside_polygon(
    point: Point,
    polygon: gdstk.Polygon,
    *,
    precision: float,
    probe_half_um: float,
) -> bool:
    probe = gdstk.rectangle(
        (point[0] - probe_half_um, point[1] - probe_half_um),
        (point[0] + probe_half_um, point[1] + probe_half_um),
    )
    return bool(gdstk.boolean(probe, polygon, "and", precision=precision))


def _feasible_merge_um(
    point: Point,
    outward: tuple[float, float],
    collar: gdstk.Polygon,
    target_um: float,
    *,
    precision: float,
    probe_half_um: float,
    search_iterations: int,
) -> float:
    """Largest inward merge (toward body, ``-outward``) that stays inside the collar."""
    ix, iy = -outward[0], -outward[1]
    lo, hi = 0.0, target_um
    best = 0.0
    for _ in range(search_iterations):
        mid = (lo + hi) / 2.0
        test = (point[0] + ix * mid, point[1] + iy * mid)
        if _point_inside_polygon(
            test, collar, precision=precision, probe_half_um=probe_half_um
        ):
            best = mid
            lo = mid
        else:
            hi = mid
    return best


def draw_lip_extension(
    collar: gdstk.Polygon,
    lip: LipIntercept,
    body_mte_polys: Sequence[gdstk.Polygon],
    cfg: MteBuildConfig,
    layer: int,
    datatype: int,
) -> CollarExtensionDraw:
    """
    Draw one new MTE polygon extruding outward from intercepts A and B.

    Inset and extrusion use the outward normal from ``find_outward_lip_ab``
    (perpendicular to the lip, away from resonator-body MTE). The inner edge is
    shifted ``merge_um`` toward the body; the whole rectangle is then shifted a
    little further into the collar (``touch_overlap_um``) so it meets preserved
    metal in layout viewers. The outer edge is ``collar_extension_um`` from the mouth.
    """
    extension_um = cfg.collar_extension_um
    merge_um = cfg.collar_merge_inset_um
    touch_overlap_um = cfg.collar_touch_overlap_um
    boolean_precision = cfg.boolean_precision

    if extension_um <= 0:
        raise ValueError("extension_um must be positive")
    if merge_um <= 0:
        raise ValueError("merge_um must be positive")
    if touch_overlap_um < 0:
        raise ValueError("touch_overlap_um must be non-negative")

    _ = body_mte_polys  # lip.outward_normal already encodes body-relative direction
    ox, oy = lip.outward_normal
    olen = math.hypot(ox, oy)
    if olen < 1e-9:
        raise ValueError("lip outward_normal is degenerate")
    ox, oy = ox / olen, oy / olen

    merge_a = _feasible_merge_um(
        lip.point_a,
        (ox, oy),
        collar,
        merge_um,
        precision=boolean_precision,
        probe_half_um=cfg.inside_probe_half_um,
        search_iterations=cfg.feasible_merge_search_iterations,
    )
    merge_b = _feasible_merge_um(
        lip.point_b,
        (ox, oy),
        collar,
        merge_um,
        precision=boolean_precision,
        probe_half_um=cfg.inside_probe_half_um,
        search_iterations=cfg.feasible_merge_search_iterations,
    )

    inner_a = (
        lip.point_a[0] - ox * merge_a,
        lip.point_a[1] - oy * merge_a,
    )
    inner_b = (
        lip.point_b[0] - ox * merge_b,
        lip.point_b[1] - oy * merge_b,
    )
    outer_a = (
        lip.point_a[0] + ox * extension_um,
        lip.point_a[1] + oy * extension_um,
    )
    outer_b = (
        lip.point_b[0] + ox * extension_um,
        lip.point_b[1] + oy * extension_um,
    )

    # Shift the whole extension into the collar (−outward) to close sub-µm viewer gaps.
    if touch_overlap_um > 0:
        total_a = _feasible_merge_um(
            lip.point_a,
            (ox, oy),
            collar,
            merge_um + touch_overlap_um,
            precision=boolean_precision,
            probe_half_um=cfg.inside_probe_half_um,
            search_iterations=cfg.feasible_merge_search_iterations,
        )
        total_b = _feasible_merge_um(
            lip.point_b,
            (ox, oy),
            collar,
            merge_um + touch_overlap_um,
            precision=boolean_precision,
            probe_half_um=cfg.inside_probe_half_um,
            search_iterations=cfg.feasible_merge_search_iterations,
        )
        shift = min(
            touch_overlap_um,
            max(0.0, total_a - merge_a),
            max(0.0, total_b - merge_b),
        )
        if shift > 0:
            sx, sy = -ox * shift, -oy * shift
            inner_a = (inner_a[0] + sx, inner_a[1] + sy)
            inner_b = (inner_b[0] + sx, inner_b[1] + sy)
            outer_a = (outer_a[0] + sx, outer_a[1] + sy)
            outer_b = (outer_b[0] + sx, outer_b[1] + sy)
            merge_a += shift
            merge_b += shift

    polygon = gdstk.Polygon(
        [inner_a, inner_b, outer_b, outer_a],
        layer=layer,
        datatype=datatype,
    )
    span = _dist(lip.point_a, lip.point_b)
    pts = [(float(p[0]), float(p[1])) for p in collar.points]
    if lip.lip_edges:
        edge_a = _edge_points(pts, lip.lip_edges[0])
        edge_b = _edge_points(pts, lip.lip_edges[-1])
        endcap_index_a = lip.lip_edges[0]
        endcap_index_b = lip.lip_edges[-1]
    else:
        edge_a = (lip.point_a, lip.point_b)
        edge_b = edge_a
        endcap_index_a = -1
        endcap_index_b = -1

    return CollarExtensionDraw(
        polygon=polygon,
        intercept_a=inner_a,
        intercept_b=inner_b,
        outer_edge=(outer_b, outer_a),
        extension_um=extension_um,
        target_extension_um=extension_um,
        endcap_edge_a=edge_a,
        endcap_edge_b=edge_b,
        endcap_index_a=endcap_index_a,
        endcap_index_b=endcap_index_b,
        mouth_span_um=span,
        mouth_vertices=2,
        collar_intercept_a=lip.point_a,
        collar_intercept_b=lip.point_b,
        merge_inset_a_um=merge_a,
        merge_inset_b_um=merge_b,
    )


def _collar_overlap_area(
    ext: gdstk.Polygon, collar: gdstk.Polygon, precision: float
) -> float:
    inter = gdstk.boolean(ext, collar, "and", precision=precision)
    return sum(abs(p.area()) for p in inter) if inter else 0.0


def extension_is_connected(
    ext: gdstk.Polygon,
    collar: gdstk.Polygon,
    draw: CollarExtensionDraw,
    cfg: MteBuildConfig,
) -> bool:
    """
    True when the extension is materially merged into the collar, not merely
    touching at a boolean sliver.

    Requires meaningful overlap area, both mouth corners merged into the collar
    by at least ``min_connection_merge_um``, and overlap covering at least
    ``min_connection_overlap_fraction`` of the extension polygon.
    """
    overlap = _collar_overlap_area(ext, collar, cfg.boolean_precision)
    if overlap < cfg.min_collar_overlap_um2:
        return False
    ext_area = abs(ext.area())
    if ext_area > 1e-6 and overlap / ext_area < cfg.min_connection_overlap_fraction:
        return False
    min_merge = min(draw.merge_inset_a_um, draw.merge_inset_b_um)
    collar_area = abs(collar.area())

    if collar_area < cfg.stadium_collar_area_um2:
        if collar_area < 700.0:
            min_merge_req = cfg.min_connection_merge_um
        else:
            min_merge_req = cfg.min_merge_inset_check_um * 0.6
        min_mouth_req = cfg.min_mouth_coverage_fraction
        collar_bb = collar.bounding_box()
        mouth_coverage = 0.0
        if collar_bb is not None:
            (x0, y0), (x1, y1) = collar_bb
            collar_width = max(x1 - x0, y1 - y0)
            if collar_width > 1e-6:
                mouth_coverage = draw.mouth_span_um / collar_width
        if min_merge < min_merge_req:
            return False
        if mouth_coverage < min_mouth_req:
            return False
        return True

    min_merge_req = cfg.min_merge_inset_check_um * 0.6
    if min_merge < min_merge_req:
        return False
    return (
        cfg.stadium_tab_mouth_min_um
        <= draw.mouth_span_um
        <= cfg.stadium_tab_mouth_max_um
    )


def _validate_extension(
    ext: gdstk.Polygon,
    collar: gdstk.Polygon,
    cfg: MteBuildConfig,
    *,
    resonator_index: int | None = None,
    merge_inset_points: Sequence[Point] | None = None,
    merge_inset_um: Sequence[float] | None = None,
) -> None:
    overlap = _collar_overlap_area(ext, collar, cfg.boolean_precision)
    collar_area = abs(collar.area())
    prefix = f"resonator {resonator_index}: " if resonator_index is not None else ""
    if merge_inset_points and merge_inset_um:
        for idx, (pt, merge) in enumerate(zip(merge_inset_points, merge_inset_um, strict=True)):
            if merge >= cfg.min_merge_inset_check_um and not _point_inside_polygon(
                pt,
                collar,
                precision=cfg.boolean_precision,
                probe_half_um=cfg.inside_probe_half_um,
            ):
                raise ValueError(
                    f"{prefix}MTE extension merge inset {idx} is not inside collar "
                    f"(placement error, not overlap area)"
                )
    if overlap < cfg.min_collar_overlap_um2:
        raise ValueError(
            f"{prefix}MTE extension not attached to collar "
            f"(overlap {overlap:.2f} um² < {cfg.min_collar_overlap_um2:.2f} um²)"
        )
    if collar_area > 1e-6 and overlap / collar_area > cfg.max_overlap_fraction:
        raise ValueError(
            f"{prefix}MTE extension covers too much of collar "
            f"(overlap/collar = {overlap / collar_area:.2f} > {cfg.max_overlap_fraction})"
        )


def _nearest_boundary_point_on_collar(
    collar: gdstk.Polygon,
    target: Point,
) -> Point:
    """Closest point on the collar ring to ``target``."""
    tx, ty = target
    best_d = float("inf")
    best_pt: Point = target
    pts = [(float(x), float(y)) for x, y in collar.points]
    for i in range(len(pts)):
        p0, p1 = pts[i], pts[(i + 1) % len(pts)]
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        el2 = dx * dx + dy * dy
        if el2 < 1e-9:
            continue
        t = max(0.0, min(1.0, ((tx - p0[0]) * dx + (ty - p0[1]) * dy) / el2))
        pt = (p0[0] + t * dx, p0[1] + t * dy)
        d = math.hypot(pt[0] - tx, pt[1] - ty)
        if d < best_d:
            best_d = d
            best_pt = pt
    return best_pt


def _outward_normal_from_mouth(
    point_a: Point,
    point_b: Point,
    body_polys: Sequence[gdstk.Polygon],
) -> tuple[float, float]:
    """Unit normal perpendicular to the mouth, pointing away from body metal."""
    body_c = _body_centroid(body_polys)
    ax, ay = point_a
    bx, by = point_b
    tx, ty = bx - ax, by - ay
    tlen = math.hypot(tx, ty)
    if tlen < 1e-9:
        return (0.0, 1.0)
    tx, ty = tx / tlen, ty / tlen
    nx, ny = -ty, tx
    mid = ((ax + bx) / 2.0, (ay + by) / 2.0)
    vx, vy = mid[0] - body_c[0], mid[1] - body_c[1]
    if nx * vx + ny * vy < 0.0:
        return (-nx, -ny)
    return (nx, ny)


def _die_lip_collar_score(
    collar: gdstk.Polygon,
    die_lip: LipIntercept,
) -> tuple[float, float, float]:
    """Return (snap score, mouth span on collar, span delta from die mouth)."""
    sa = _nearest_boundary_point_on_collar(collar, die_lip.point_a)
    sb = _nearest_boundary_point_on_collar(collar, die_lip.point_b)
    span = _dist(sa, sb)
    die_span = _dist(die_lip.point_a, die_lip.point_b)
    score = _dist(sa, die_lip.point_a) + _dist(sb, die_lip.point_b)
    return score, span, abs(span - die_span)


def select_collar_for_die_lip(
    pieces: Sequence[TaggedPolygon],
    die_lip: LipIntercept,
    *,
    min_mouth_um: float = 5.0,
) -> TaggedPolygon | None:
    """Pick preserved MTE collar whose boundary best matches die mouth targets."""
    best: TaggedPolygon | None = None
    best_key: tuple[float, bool, float] | None = None
    for tp in pieces:
        score, span, span_delta = _die_lip_collar_score(tp.polygon, die_lip)
        key = (score, span >= min_mouth_um, -span_delta)
        if best_key is None or key < best_key:
            best_key = key
            best = tp
    return best


def _rank_collars_for_die_lip(
    pieces: Sequence[TaggedPolygon],
    die_lip: LipIntercept,
) -> list[TaggedPolygon]:
    """Order preserved MTE collars from best to worst die-mouth snap fit."""
    return sorted(
        pieces,
        key=lambda tp: _die_lip_collar_score(tp.polygon, die_lip),
    )


def _snap_lip_to_collar(collar: gdstk.Polygon, lip: LipIntercept) -> LipIntercept:
    """Snap die mouth targets onto the preserved RTEG collar boundary."""
    point_a = _nearest_boundary_point_on_collar(collar, lip.point_a)
    point_b = _nearest_boundary_point_on_collar(collar, lip.point_b)
    return LipIntercept(
        point_a=point_a,
        point_b=point_b,
        lip_vertex_indices=[],
        outward_normal=lip.outward_normal,
        lip_edges=[],
    )


def _lip_for_collar(
    collar: gdstk.Polygon,
    die_lip: LipIntercept,
    body_polys: Sequence[gdstk.Polygon],
    *,
    max_snap_um: float = 15.0,
) -> LipIntercept:
    """Snap routing mouth targets onto the selected collar boundary."""
    point_a = _nearest_boundary_point_on_collar(collar, die_lip.point_a)
    point_b = _nearest_boundary_point_on_collar(collar, die_lip.point_b)
    return LipIntercept(
        point_a=point_a,
        point_b=point_b,
        lip_vertex_indices=[],
        outward_normal=_outward_normal_from_mouth(
            point_a, point_b, body_polys
        ),
        lip_edges=[],
    )


def draw_collar_extension(
    collar_tp: TaggedPolygon,
    layermap: LayerMap,
    cfg: MteBuildConfig,
    *,
    body_mte_polys: Sequence[gdstk.Polygon],
    resonator_index: int | None = None,
    lip: LipIntercept | None = None,
) -> CollarExtensionDraw:
    layer, datatype = layermap.pair(cfg.mte_layer)
    if lip is not None:
        lip = _lip_for_collar(collar_tp.polygon, lip, body_mte_polys)
    if lip is None:
        lip = find_outward_lip_ab(collar_tp.polygon, body_mte_polys, cfg)
    draw = draw_lip_extension(
        collar_tp.polygon,
        lip,
        body_mte_polys,
        cfg,
        layer,
        datatype,
    )
    ext = assign_layer(draw.polygon, layermap, cfg.mte_layer)
    draw = CollarExtensionDraw(
        polygon=ext,
        intercept_a=draw.intercept_a,
        intercept_b=draw.intercept_b,
        outer_edge=draw.outer_edge,
        extension_um=draw.extension_um,
        target_extension_um=draw.target_extension_um,
        endcap_edge_a=draw.endcap_edge_a,
        endcap_edge_b=draw.endcap_edge_b,
        endcap_index_a=draw.endcap_index_a,
        endcap_index_b=draw.endcap_index_b,
        mouth_span_um=draw.mouth_span_um,
        mouth_vertices=draw.mouth_vertices,
        collar_intercept_a=draw.collar_intercept_a,
        collar_intercept_b=draw.collar_intercept_b,
        merge_inset_a_um=draw.merge_inset_a_um,
        merge_inset_b_um=draw.merge_inset_b_um,
    )
    _validate_extension(
        draw.polygon,
        collar_tp.polygon,
        cfg,
        resonator_index=resonator_index,
        merge_inset_points=(draw.intercept_a, draw.intercept_b),
        merge_inset_um=(draw.merge_inset_a_um, draw.merge_inset_b_um),
    )
    return draw


def _extension_for_roles(
    roles: _HasPreserved,
    layermap: LayerMap,
    cfg: MteBuildConfig,
    *,
    resonator_index: int,
    die_lip: LipIntercept | None = None,
    die_routing: object | None = None,
) -> MteExtensionResult:
    preserved_polys = [tp.polygon for tp in roles.preserved.mte]
    lip: LipIntercept | None = die_lip
    mte_pieces = list(roles.preserved.mte)
    if die_routing is not None and die_lip is not None:
        mte_pieces.extend(die_routing.extra_collars(resonator_index, "mte"))
    if die_lip is not None:
        collar_candidates = _rank_collars_for_die_lip(
            mte_pieces,
            die_lip,
        )
    else:
        collar_candidates = []
        collar_tp = select_extension_collar(
            roles.preserved,
            roles.resonator_body_mte,
            cfg,
        )
        if collar_tp is not None:
            collar_candidates = [collar_tp]

    draw: CollarExtensionDraw | None = None
    collar_tp: TaggedPolygon | None = None
    for candidate in collar_candidates:
        try:
            draw = draw_collar_extension(
                candidate,
                layermap,
                cfg,
                body_mte_polys=roles.resonator_body_mte,
                resonator_index=resonator_index,
                lip=lip,
            )
            collar_tp = candidate
            break
        except ValueError:
            continue

    if draw is None or collar_tp is None:
        collar_tp = select_extension_collar(
            roles.preserved,
            roles.resonator_body_mte,
            cfg,
        )
        if collar_tp is None:
            raise ValueError(
                f"resonator {resonator_index}: no preserved MTE collar to extend"
            )
        lip = None
        draw = draw_collar_extension(
            collar_tp,
            layermap,
            cfg,
            body_mte_polys=roles.resonator_body_mte,
            resonator_index=resonator_index,
            lip=None,
        )
    overlap = _collar_overlap_area(
        draw.polygon, collar_tp.polygon, cfg.boolean_precision
    )
    connected = extension_is_connected(
        draw.polygon, collar_tp.polygon, draw, cfg
    )
    return MteExtensionResult(
        collar=collar_tp,
        extension=draw.polygon,
        preserved_collar_polygons=preserved_polys,
        n_extensions=1,
        is_connected=connected,
        collar_overlap_um2=overlap,
        extension_draw=draw,
    )


def build_mte_extensions(
    roles_by_index: Mapping[int, _HasPreserved],
    layermap: LayerMap,
    config: MteBuildConfig | None = None,
    *,
    die_routing: object | None = None,
) -> dict[int, MteExtensionResult]:
    cfg = config or MteBuildConfig()
    return {
        idx: _extension_for_roles(
            roles,
            layermap,
            cfg,
            resonator_index=idx,
            die_lip=(
                die_routing.lip(idx, "mte")
                if die_routing is not None
                else None
            ),
            die_routing=die_routing,
        )
        for idx, roles in roles_by_index.items()
    }


def mte_extensions_overview_rows(
    extensions: Mapping[int, MteExtensionResult],
    *,
    inst_names: Mapping[int, str] | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx in sorted(extensions):
        result = extensions[idx]
        rows.append(
            {
                "index": idx,
                "inst_name": inst_names.get(idx) if inst_names else None,
                "n_preserved_mte": len(result.preserved_collar_polygons),
                "n_extensions": result.n_extensions,
                "collar_overlap_um2": round(result.collar_overlap_um2, 2),
                "is_connected": result.is_connected,
            }
        )
    return rows


def _fmt_point(pt: Point) -> str:
    return f"({pt[0]:.2f}, {pt[1]:.2f})"


def _fmt_edge(edge: Edge) -> str:
    return f"{_fmt_point(edge[0])} -> {_fmt_point(edge[1])}"


def mte_intercept_breakdown_rows(
    extensions: Mapping[int, MteExtensionResult],
    *,
    inst_names: Mapping[int, str] | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for idx in sorted(extensions):
        result = extensions[idx]
        draw = result.extension_draw
        row: dict[str, object] = {
            "index": idx,
            "inst_name": inst_names.get(idx) if inst_names else None,
            "n_extensions": result.n_extensions,
        }
        if draw is None:
            row.update(
                {
                    "collar_intercept_a": None,
                    "collar_intercept_b": None,
                    "endcap_edge_a": None,
                    "endcap_edge_b": None,
                    "endcap_index_a": None,
                    "endcap_index_b": None,
                    "lip_edge_index": None,
                    "merge_inset_a_um": None,
                    "merge_inset_b_um": None,
                    "min_merge_um": None,
                    "mouth_span_um": None,
                    "mouth_vertices": None,
                    "extension_um": None,
                    "target_extension_um": None,
                }
            )
        else:
            row.update(
                {
                    "collar_intercept_a": _fmt_point(draw.collar_intercept_a),
                    "collar_intercept_b": _fmt_point(draw.collar_intercept_b),
                    "endcap_edge_a": _fmt_edge(draw.endcap_edge_a),
                    "endcap_edge_b": _fmt_edge(draw.endcap_edge_b),
                    "endcap_index_a": draw.endcap_index_a,
                    "endcap_index_b": draw.endcap_index_b,
                    "lip_edge_index": draw.endcap_index_a,
                    "merge_inset_a_um": round(draw.merge_inset_a_um, 2),
                    "merge_inset_b_um": round(draw.merge_inset_b_um, 2),
                    "min_merge_um": round(
                        min(draw.merge_inset_a_um, draw.merge_inset_b_um), 2
                    ),
                    "mouth_span_um": round(draw.mouth_span_um, 2),
                    "mouth_vertices": draw.mouth_vertices,
                    "extension_um": round(draw.extension_um, 2),
                    "target_extension_um": round(draw.target_extension_um, 2),
                }
            )
        rows.append(row)
    return rows


@dataclass
class MteRtegAssembly:
    frame: RtegFrameAssembly
    extension: MteExtensionResult
    layermap: LayerMap | None = None
    mbe_extension: object | None = None
    mbe_body: object | None = None

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

    def _strip_raw_filler(self, cell: gdstk.Cell) -> None:
        """Remove the step-4 width filler rectangle before writing the carved body."""
        if self.layermap is None:
            return
        mbe_pair = self.layermap.pair("BAW_MBE")
        (fx0, fy0), (fx1, fy1) = self.frame.mbe_filler_bbox
        tol = 1.0
        keep: list[gdstk.Polygon] = []
        for poly in cell.polygons:
            if (poly.layer, poly.datatype) != mbe_pair:
                keep.append(poly)
                continue
            bb = poly.bounding_box()
            if bb is None:
                keep.append(poly)
                continue
            if (
                abs(bb[0][0] - fx0) <= tol
                and abs(bb[0][1] - fy0) <= tol
                and abs(bb[1][0] - fx1) <= tol
                and abs(bb[1][1] - fy1) <= tol
            ):
                continue
            keep.append(poly)
        cell.remove(*cell.polygons)
        cell.add(*keep)

    def _strip_absorbed_mbe(
        self,
        cell: gdstk.Cell,
        absorbed: Sequence[gdstk.Polygon],
        *,
        overlap_fraction: float = 0.85,
        boolean_precision: float = 1e-3,
    ) -> None:
        """Drop preserved MBE polygons already merged into the center-pad filler."""
        if not absorbed or self.layermap is None:
            return
        mbe_pair = self.layermap.pair("BAW_MBE")
        keep: list[gdstk.Polygon] = []
        for poly in cell.polygons:
            if (poly.layer, poly.datatype) != mbe_pair:
                keep.append(poly)
                continue
            drop = False
            poly_area = abs(poly.area())
            for target in absorbed:
                overlap = gdstk.boolean(
                    poly,
                    target,
                    "and",
                    precision=boolean_precision,
                )
                if not overlap:
                    continue
                overlap_area = sum(abs(p.area()) for p in overlap)
                if poly_area > 1e-6 and overlap_area / poly_area >= overlap_fraction:
                    drop = True
                    break
            if not drop:
                keep.append(poly)
        cell.remove(*cell.polygons)
        cell.add(*keep)

    def _strip_mbe_inside_filler_bbox(
        self,
        cell: gdstk.Cell,
        filler: gdstk.Polygon,
        *,
        tol: float = 1.0,
    ) -> None:
        """Clear frame MBE inside the step-4 filler window before writing the body."""
        if self.layermap is None:
            return
        mbe_pair = self.layermap.pair("BAW_MBE")
        fbb = filler.bounding_box()
        if fbb is None:
            return
        (fx0, fy0), (fx1, fy1) = fbb
        keep: list[gdstk.Polygon] = []
        for poly in cell.polygons:
            if (poly.layer, poly.datatype) != mbe_pair:
                keep.append(poly)
                continue
            bb = poly.bounding_box()
            if bb is None:
                keep.append(poly)
                continue
            inside = (
                bb[0][0] >= fx0 - tol
                and bb[0][1] >= fy0 - tol
                and bb[1][0] <= fx1 + tol
                and bb[1][1] <= fy1 + tol
            )
            if inside:
                continue
            keep.append(poly)
        cell.remove(*cell.polygons)
        cell.add(*keep)

    def _strip_overlapping_mbe_in_filler(
        self,
        cell: gdstk.Cell,
        filler_polys: Sequence[gdstk.Polygon],
        *,
        overlap_fraction: float = 0.85,
        boolean_precision: float = 1e-3,
    ) -> None:
        """Remove frame MBE that substantially duplicates generated filler metal."""
        if not filler_polys or self.layermap is None:
            return
        mbe_pair = self.layermap.pair("BAW_MBE")
        keep: list[gdstk.Polygon] = []
        for poly in cell.polygons:
            if (poly.layer, poly.datatype) != mbe_pair:
                keep.append(poly)
                continue
            poly_area = abs(poly.area())
            drop = False
            for filler in filler_polys:
                overlap = gdstk.boolean(
                    poly,
                    filler,
                    "and",
                    precision=boolean_precision,
                )
                if not overlap:
                    continue
                overlap_area = sum(abs(p.area()) for p in overlap)
                if (
                    poly_area > 1e-6
                    and overlap_area / poly_area >= overlap_fraction
                ):
                    drop = True
                    break
            if not drop:
                keep.append(poly)
        cell.remove(*cell.polygons)
        cell.add(*keep)

    def flatten(self) -> gdstk.Cell:
        cell = self.frame.flatten().copy(f"rteg_{self.index:02d}_{self.inst_name}_mte")
        if self.mbe_body is not None and getattr(self.mbe_body, "n_pieces", 0) > 0:
            self._strip_raw_filler(cell)
            absorbed = getattr(self.mbe_body, "absorbed_mbe", None) or []
            if absorbed:
                self._strip_absorbed_mbe(cell, absorbed)
        net = self.extension.routed_net or self.extension.extension
        if net is not None:
            cell.add(gdstk.Polygon(net.points, net.layer, net.datatype))
        if self.layermap is not None and self.mbe_extension is not None:
            mbe_net = self.mbe_extension.routed_net or self.mbe_extension.extension
            if mbe_net is not None and self.mbe_extension.n_extensions > 0:
                tagged = assign_layer(mbe_net, self.layermap, "BAW_MBE")
                cell.add(gdstk.Polygon(tagged.points, tagged.layer, tagged.datatype))
        if self.layermap is not None and self.mbe_body is not None:
            body = self.mbe_body
            if getattr(body, "cap", None) is not None:
                tagged = assign_layer(body.cap, self.layermap, "BAW_MBE")
                cell.add(gdstk.Polygon(tagged.points, tagged.layer, tagged.datatype))
            filler_polys = getattr(body, "filler", []) or []
            if len(filler_polys) == 1:
                self._strip_mbe_inside_filler_bbox(cell, filler_polys[0])
            elif filler_polys:
                self._strip_overlapping_mbe_in_filler(cell, filler_polys)
            for poly in filler_polys:
                tagged = assign_layer(poly, self.layermap, "BAW_MBE")
                cell.add(gdstk.Polygon(tagged.points, tagged.layer, tagged.datatype))
        return cell


def export_mte_extensions_gds(
    frame_assemblies: Sequence[RtegFrameAssembly],
    extensions: Mapping[int, MteExtensionResult],
    output_dir: str | Path,
    *,
    layermap: LayerMap,
    mbe_extensions: Mapping[int, object] | None = None,
    mbe_bodies: Mapping[int, object] | None = None,
    parent: str | None = None,
    stage: str = "mte",
    flatten: bool = True,
    write_lyp: bool = True,
) -> list[ExportResult]:
    """
    Export one GDS per resonator: frame + MTE route/extension (+ optional MBE).

    Pass ``mbe_extensions`` from step 6.1 and ``mbe_bodies`` from steps 6.2/6.3
    to write MTE (5/0) and MBE (2/0) into the same file under ``output_dir``.

    For the complete pipeline output (steps 4–6.3), prefer
    :func:`export_full_rteg_gds` which validates all indices and uses the
    ``routed`` filename suffix.
    """
    mbe_map = mbe_extensions or {}
    body_map = mbe_bodies or {}
    assemblies: list[MteRtegAssembly] = []
    for asm in frame_assemblies:
        if asm.index not in extensions:
            continue
        mte = extensions[asm.index]
        mbe = mbe_map.get(asm.index)
        body = body_map.get(asm.index)
        has_mte = mte.n_extensions > 0
        has_mbe = mbe is not None and mbe.n_extensions > 0
        has_body = body is not None and body.n_pieces > 0
        if not has_mte and not has_mbe and not has_body:
            continue
        assemblies.append(
            MteRtegAssembly(
                frame=asm,
                extension=mte,
                layermap=layermap,
                mbe_extension=mbe if has_mbe else None,
                mbe_body=body if has_body else None,
            )
        )
    return export_gds(
        assemblies,
        output_dir,
        layermap=layermap,
        parent=parent,
        stage=stage,
        flatten=flatten,
        write_lyp=write_lyp,
    )


def export_full_rteg_gds(
    frame_assemblies: Sequence[RtegFrameAssembly],
    extensions: Mapping[int, MteExtensionResult],
    output_dir: str | Path,
    *,
    layermap: LayerMap,
    mbe_extensions: Mapping[int, object],
    mbe_bodies: Mapping[int, object],
    parent: str | None = None,
    flatten: bool = True,
    write_lyp: bool = True,
) -> list[ExportResult]:
    """
    Export the complete routed RTEG (steps 4–6.3) — one GDS per resonator.

    Each file includes the die frame, PPD, resonator placement (including any
    step-4 resonator-only shift), MTE collar extension and pad routes (5.3–5.4),
    MBE signal routes where applicable (6.1), and carved MBE ground filler
    (6.2 for ``collar_extend``, 6.3 for ``center_pad``).

    ``mbe_bodies`` must be the merged dict from steps 6.2 and 6.3, e.g.
    ``merge_mbe_bodies(collar_extend_body, center_pad_body)`` — each builder
    returns only the indices it applies to.
    """
    expected = {asm.index for asm in frame_assemblies}
    missing_mte = expected - set(extensions)
    if missing_mte:
        raise ValueError(
            "Full RTEG export requires MTE extensions for every framed resonator; "
            f"missing indices: {sorted(missing_mte)}"
        )

    results = export_mte_extensions_gds(
        frame_assemblies,
        extensions,
        output_dir,
        layermap=layermap,
        mbe_extensions=mbe_extensions,
        mbe_bodies=mbe_bodies,
        parent=parent,
        stage="routed",
        flatten=flatten,
        write_lyp=write_lyp,
    )
    exported = {r.index for r in results}
    if exported != expected:
        missing = sorted(expected - exported)
        warnings.warn(
            "Full RTEG export did not write GDS for indices "
            f"{missing}. Confirm steps 5.3–6.3 ran and routing applied.",
            stacklevel=2,
        )
    return results


__all__ = [
    "CollarExtensionDraw",
    "LipIntercept",
    "MteBuildConfig",
    "MteExtensionResult",
    "MteRtegAssembly",
    "build_mte_extensions",
    "draw_collar_extension",
    "draw_lip_extension",
    "export_full_rteg_gds",
    "export_mte_extensions_gds",
    "extension_is_connected",
    "find_outward_lip_ab",
    "mte_extensions_overview_rows",
    "mte_intercept_breakdown_rows",
    "select_extension_collar",
    "select_extension_collar_from_pieces",
]
