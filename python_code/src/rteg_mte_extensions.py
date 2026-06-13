"""
Step 5.3 — MTE collar extensions (single module).

Draw one ~13 µm extension per resonator from the preserved edge collar that
overlaps resonator-body MTE. Corner A / corner B come from a long-side walk;
the polygon extrudes outward and must overlap the collar before export.
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
from rteg_collect import (
    GroundPlates,
    InnerFrameBoundary,
    PreservedMetal,
    TaggedPolygon,
    mte_extension_frame_obstacles,
    preserved_mte_overlap_with_body,
)
from rteg_utils import assign_layer

Point = tuple[float, float]
Edge = tuple[Point, Point]

_COLLAR_OVERLAP_UM = 0.5
_SEGMENT_TEST_HALF_WIDTH_UM = 0.05
_DEFAULT_FRAME_CLEARANCE_UM = 0.0
_MAX_OVERLAP_FRACTION = 0.5
_OUTLINE_AREA_RATIO = 2.0


@dataclass(frozen=True)
class MteBuildConfig:
    mte_layer: str = "BAW_MTE"
    collar_extension_um: float = 13.0
    min_extension_um: float = 1.0
    frame_clearance_um: float = 0.0
    boolean_precision: float = 1e-3
    min_collar_overlap_um2: float = 0.01


@dataclass
class MteExtensionResult:
    collar: TaggedPolygon | None
    extension: gdstk.Polygon | None
    preserved_collar_polygons: list[gdstk.Polygon]
    n_extensions: int
    is_connected: bool
    extension_draw: CollarExtensionDraw | None = None
    drc_violations: list[str] = field(default_factory=list)


class _HasPreserved(Protocol):
    preserved: PreservedMetal
    resonator_body_mte: Sequence[gdstk.Polygon]
    frame_boundary: InnerFrameBoundary
    ground_plates: GroundPlates


@dataclass(frozen=True)
class CollarMouthIntercepts:
    """Two end-cap edges and the outer-lip chain between them."""

    intercept_a: Point
    intercept_b: Point
    mouth_indices: list[int]
    outward_normal: tuple[float, float]
    facing_edge: Edge
    endcap_edge_a: Edge
    endcap_edge_b: Edge
    endcap_index_a: int
    endcap_index_b: int
    mouth_span_um: float


@dataclass(frozen=True)
class CollarExtensionDraw:
    """One collar MTE extension: inner chain + outward sides + horizontal cap."""

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


def _edge_midpoint(edge: Edge) -> Point:
    return (
        (edge[0][0] + edge[1][0]) / 2.0,
        (edge[0][1] + edge[1][1]) / 2.0,
    )


def _edge_length(edge: Edge) -> float:
    return math.hypot(edge[1][0] - edge[0][0], edge[1][1] - edge[0][1])


def _closest_on_segment(pt: Point, edge: Edge) -> Point:
    (x0, y0), (x1, y1) = edge
    dx, dy = x1 - x0, y1 - y0
    length_sq = dx * dx + dy * dy
    if length_sq < 1e-12:
        return edge[0]
    t = max(
        0.0,
        min(1.0, ((pt[0] - x0) * dx + (pt[1] - y0) * dy) / length_sq),
    )
    return (x0 + t * dx, y0 + t * dy)


def _polygon_centroid(poly: gdstk.Polygon) -> Point:
    pts = poly.points
    if len(pts) == 0:
        return (0.0, 0.0)
    return (
        sum(float(p[0]) for p in pts) / len(pts),
        sum(float(p[1]) for p in pts) / len(pts),
    )


def _outward_normal_from_target(collar_polygon: gdstk.Polygon, toward: Point) -> tuple[float, float]:
    """Unit normal from collar centroid toward the exterior reference point."""
    cx, cy = _polygon_centroid(collar_polygon)
    dx, dy = toward[0] - cx, toward[1] - cy
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return (0.0, 1.0)
    return (dx / length, dy / length)


def find_collar_facing_edge(
    collar_polygon: gdstk.Polygon,
    toward: Point,
    *,
    min_edge_um: float = 1.0,
    overlap_um: float = _COLLAR_OVERLAP_UM,
) -> Edge:
    """Outermost collar edge nearest ``toward`` on the exterior lip."""
    pts = list(collar_polygon.points)
    if len(pts) < 2:
        raise ValueError("collar polygon has fewer than 2 points")
    cx, cy = _polygon_centroid(collar_polygon)
    nx, ny = _outward_normal_from_target(collar_polygon, toward)
    best_edge: Edge | None = None
    best_score = float("inf")
    n = len(pts)
    for i in range(n):
        p0 = (float(pts[i][0]), float(pts[i][1]))
        p1 = (float(pts[(i + 1) % n][0]), float(pts[(i + 1) % n][1]))
        if _edge_length((p0, p1)) < min_edge_um:
            continue
        s0 = (p0[0] - cx) * nx + (p0[1] - cy) * ny
        s1 = (p1[0] - cx) * nx + (p1[1] - cy) * ny
        if s0 < -overlap_um or s1 < -overlap_um:
            continue
        mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
        d = math.hypot(mid[0] - toward[0], mid[1] - toward[1])
        if d < best_score:
            best_score = d
            best_edge = (p0, p1)
    if best_edge is None:
        best_edge = (
            (float(pts[0][0]), float(pts[0][1])),
            (float(pts[1][0]), float(pts[1][1])),
        )
    return best_edge


def find_intercept_point(
    collar_polygon: gdstk.Polygon,
    pad_inner_edge: Edge,
) -> Point:
    """Point on the collar perimeter closest to the pad inner edge."""
    target = _edge_midpoint(pad_inner_edge)
    pts = list(collar_polygon.points)
    if not pts:
        raise ValueError("collar polygon has no points")
    best = (float(pts[0][0]), float(pts[0][1]))
    best_d = float("inf")
    n = len(pts)
    for i in range(n):
        edge = (
            (float(pts[i][0]), float(pts[i][1])),
            (float(pts[(i + 1) % n][0]), float(pts[(i + 1) % n][1])),
        )
        candidate = _closest_on_segment(target, edge)
        d = math.hypot(candidate[0] - target[0], candidate[1] - target[1])
        if d < best_d:
            best_d = d
            best = candidate
    return best


def _outward_normal(edge: Edge, toward: Point) -> tuple[float, float]:
    (x0, y0), (x1, y1) = edge
    mid = _edge_midpoint(edge)
    tx, ty = x1 - x0, y1 - y0
    length = math.hypot(tx, ty)
    if length < 1e-9:
        dx, dy = toward[0] - mid[0], toward[1] - mid[1]
        length = math.hypot(dx, dy)
        return (dx / length, dy / length) if length > 1e-9 else (0.0, 1.0)
    nx, ny = -ty / length, tx / length
    if (toward[0] - mid[0]) * nx + (toward[1] - mid[1]) * ny < 0:
        nx, ny = -nx, -ny
    return nx, ny


def build_pad_linear_strip(
    pad_inner_edge: Edge,
    width_um: float,
    layer: int,
    datatype: int,
    *,
    toward: Point | None = None,
) -> gdstk.Polygon:
    if width_um <= 0:
        raise ValueError("width_um must be positive")
    if _edge_length(pad_inner_edge) < 1e-6:
        raise ValueError("pad_inner_edge is degenerate")
    mid = _edge_midpoint(pad_inner_edge)
    target = toward if toward is not None else mid
    nx, ny = _outward_normal(pad_inner_edge, target)
    (x0, y0), (x1, y1) = pad_inner_edge
    ox, oy = nx * width_um, ny * width_um
    pts = [
        (x0, y0),
        (x1, y1),
        (x1 + ox, y1 + oy),
        (x0 + ox, y0 + oy),
    ]
    return gdstk.Polygon(pts, layer=layer, datatype=datatype)


def build_linear_span(
    intercept_point: Point,
    pad_strip_polygon: gdstk.Polygon,
    width_um: float,
    layer: int,
    datatype: int,
    *,
    collar_polygon: gdstk.Polygon | None = None,
) -> gdstk.Polygon:
    """Straight metal from collar intercept to pad strip; start inside collar when given."""
    if width_um <= 0:
        raise ValueError("width_um must be positive")
    bb = pad_strip_polygon.bounding_box()
    if bb is None:
        raise ValueError("pad_strip_polygon has no bounding box")
    target = (
        (bb[0][0] + bb[1][0]) / 2.0,
        (bb[0][1] + bb[1][1]) / 2.0,
    )
    start = intercept_point
    if collar_polygon is not None:
        cx, cy = _polygon_centroid(collar_polygon)
        dx, dy = cx - intercept_point[0], cy - intercept_point[1]
        length = math.hypot(dx, dy)
        if length > 1e-9:
            inset = min(_COLLAR_OVERLAP_UM, length * 0.25)
            start = (
                intercept_point[0] + dx / length * inset,
                intercept_point[1] + dy / length * inset,
            )
    flex = gdstk.FlexPath([start, target], width_um, layer=layer, datatype=datatype)
    polys = flex.to_polygons()
    if not polys:
        raise ValueError("linear span produced no polygon")
    return polys[0]


def _outward_target(collar_polygon: gdstk.Polygon) -> Point:
    """Exterior reference point: farthest edge midpoint, tie-broken by edge length."""
    cx, cy = _polygon_centroid(collar_polygon)
    pts = collar_polygon.points
    n = len(pts)
    best_mid = (float(pts[0][0]), float(pts[0][1]))
    best_key = (-1.0, -1.0)
    for i in range(n):
        p0 = (float(pts[i][0]), float(pts[i][1]))
        p1 = (float(pts[(i + 1) % n][0]), float(pts[(i + 1) % n][1]))
        mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
        d_sq = (mid[0] - cx) ** 2 + (mid[1] - cy) ** 2
        length = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
        key = (d_sq, length)
        if key > best_key:
            best_key = key
            best_mid = mid
    return best_mid


def _mouth_tangent(facing: Edge) -> tuple[float, float]:
    dx = facing[1][0] - facing[0][0]
    dy = facing[1][1] - facing[0][1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return (1.0, 0.0)
    return (dx / length, dy / length)


def _edge_tangent(p0: Point, p1: Point) -> tuple[float, float]:
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return (0.0, 0.0)
    return (dx / length, dy / length)


def _tangent_turn_deg(
    t0: tuple[float, float],
    t1: tuple[float, float],
) -> float:
    dot = max(-1.0, min(1.0, t0[0] * t1[0] + t0[1] * t1[1]))
    return math.degrees(math.acos(dot))


def _continues_along_mouth(
    prev_tangent: tuple[float, float],
    p0: Point,
    p1: Point,
    *,
    max_turn_deg: float = 45.0,
    min_edge_um: float = 0.5,
) -> bool:
    """True when the next edge continues around a curved or straight collar lip."""
    if _edge_length((p0, p1)) < min_edge_um:
        return False
    tangent = _edge_tangent(p0, p1)
    if prev_tangent == (0.0, 0.0):
        return True
    reverse = (-prev_tangent[0], -prev_tangent[1])
    turn = min(
        _tangent_turn_deg(prev_tangent, tangent),
        _tangent_turn_deg(reverse, tangent),
    )
    return turn <= max_turn_deg


def _edge_parallel_to_mouth(
    p0: Point,
    p1: Point,
    mouth_tangent: tuple[float, float],
    *,
    min_align: float = 0.85,
) -> bool:
    """True when edge continues along the collar mouth rather than an end cap."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return False
    tx, ty = mouth_tangent
    align = abs((dx / length) * tx + (dy / length) * ty)
    return align >= min_align


def _find_edge_index(pts: Sequence[Point], edge: Edge, tol: float = 0.05) -> int:
    """Index ``i`` where polygon edge ``(pts[i], pts[i+1])`` matches ``edge``."""
    n = len(pts)
    (ex0, ey0), (ex1, ey1) = edge

    def close(a: Point, b: Point) -> bool:
        return math.hypot(a[0] - b[0], a[1] - b[1]) <= tol

    for i in range(n):
        p0 = (float(pts[i][0]), float(pts[i][1]))
        p1 = (float(pts[(i + 1) % n][0]), float(pts[(i + 1) % n][1]))
        if close(p0, (ex0, ey0)) and close(p1, (ex1, ey1)):
            return i
        if close(p0, (ex1, ey1)) and close(p1, (ex0, ey0)):
            return i
    fmid = _edge_midpoint(edge)
    best_i = 0
    best_d = float("inf")
    for i in range(n):
        p0 = (float(pts[i][0]), float(pts[i][1]))
        p1 = (float(pts[(i + 1) % n][0]), float(pts[(i + 1) % n][1]))
        d = math.hypot(_edge_midpoint((p0, p1))[0] - fmid[0], _edge_midpoint((p0, p1))[1] - fmid[1])
        if d < best_d:
            best_d = d
            best_i = i
    return best_i


def _edge_is_end_cap(
    p0: Point,
    p1: Point,
    mouth_tangent: tuple[float, float],
) -> bool:
    """True when edge is a mouth end cap (perpendicular to the facing tangent)."""
    return not _edge_parallel_to_mouth(p0, p1, mouth_tangent)


def _walk_mouth_indices(
    pts: Sequence[Point],
    facing_idx: int,
    facing: Edge,
    normal: tuple[float, float],
    cx: float,
    cy: float,
) -> list[int]:
    """
    Walk from the facing edge along the collar mouth, stopping at end caps.

    Keeps the outward-facing lip (including curved segments) without swallowing
    the whole collar polygon.
    """
    n = len(pts)
    nx, ny = normal
    facing_tangent = _edge_tangent(
        (float(pts[facing_idx][0]), float(pts[facing_idx][1])),
        (float(pts[(facing_idx + 1) % n][0]), float(pts[(facing_idx + 1) % n][1])),
    )

    def vert_ok(i: int) -> bool:
        p = pts[i]
        return (float(p[0]) - cx) * nx + (float(p[1]) - cy) * ny >= -_COLLAR_OVERLAP_UM

    indices = [facing_idx, (facing_idx + 1) % n]
    seen = set(indices)

    i = (facing_idx + 1) % n
    prev_t = facing_tangent
    for _ in range(n):
        nxt = (i + 1) % n
        p0 = (float(pts[i][0]), float(pts[i][1]))
        p1 = (float(pts[nxt][0]), float(pts[nxt][1]))
        if not vert_ok(nxt):
            break
        if not _continues_along_mouth(prev_t, p0, p1):
            break
        if nxt not in seen:
            indices.append(nxt)
            seen.add(nxt)
        prev_t = _edge_tangent(p0, p1)
        i = nxt
        if i == facing_idx:
            break

    i = facing_idx
    prev_t = facing_tangent
    prepend: list[int] = []
    for _ in range(n):
        prev = (i - 1) % n
        p0 = (float(pts[prev][0]), float(pts[prev][1]))
        p1 = (float(pts[i][0]), float(pts[i][1]))
        if not vert_ok(prev):
            break
        if not _continues_along_mouth(prev_t, p0, p1):
            break
        if prev not in seen:
            prepend.append(prev)
            seen.add(prev)
        prev_t = _edge_tangent(p0, p1)
        i = prev
        if i == (facing_idx + 1) % n:
            break

    ordered = prepend + indices
    if len(ordered) < 2:
        raise ValueError("mouth chain has fewer than 2 vertices")

    start = ordered[0]
    out: list[int] = []
    i = start
    for _ in range(n + 1):
        if i in seen and (not out or out[-1] != i):
            out.append(i)
        i = (i + 1) % n
        if i == start and out:
            break
    return out if len(out) >= 2 else ordered


def _mouth_vertex_indices(
    pts: Sequence[Point],
    facing_idx: int,
    facing: Edge,
    nx: float,
    ny: float,
    cx: float,
    cy: float,
) -> list[int]:
    """Outward-facing collar vertices between end caps, anchored on the facing edge."""
    return _walk_mouth_indices(pts, facing_idx, facing, (nx, ny), cx, cy)


def _outward_distance(point: Point, ref: Point, normal: tuple[float, float]) -> float:
    nx, ny = normal
    return (point[0] - ref[0]) * nx + (point[1] - ref[1]) * ny


def _vertex_outward_score(
    point: Point,
    normal: tuple[float, float],
    centroid: Point,
) -> float:
    nx, ny = normal
    cx, cy = centroid
    return (point[0] - cx) * nx + (point[1] - cy) * ny


def _endcap_edge_candidates(
    pts: Sequence[Point],
    normal: tuple[float, float],
    centroid: Point,
    *,
    min_edge_um: float = 0.5,
) -> list[tuple[int, float, float, float, Point, Point]]:
    """Short collar edges perpendicular to the outward normal (true mouth end caps)."""
    nx, ny = normal
    n = len(pts)
    lengths: list[float] = []
    edges: list[tuple[int, float, float, float, Point, Point]] = []
    for i in range(n):
        p0 = (float(pts[i][0]), float(pts[i][1]))
        p1 = (float(pts[(i + 1) % n][0]), float(pts[(i + 1) % n][1]))
        length = _edge_length((p0, p1))
        if length < min_edge_um:
            continue
        lengths.append(length)
        tx, ty = (p1[0] - p0[0]) / length, (p1[1] - p0[1]) / length
        align = abs(tx * nx + ty * ny)
        perp = abs(tx * (-ny) + ty * nx)
        mid = ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
        outward = _vertex_outward_score(mid, normal, centroid)
        edges.append((i, length, perp, outward, p0, p1, align))

    if not edges:
        return []

    max_len = max(lengths)
    cap_max_len = max(max_len * 0.25, 20.0)
    caps = [
        (i, length, perp, outward, p0, p1)
        for i, length, perp, outward, p0, p1, align in edges
        if perp >= 0.85 and align <= 0.5 and length <= cap_max_len
    ]
    if len(caps) >= 2:
        return caps

    # Fallback: best perpendicular edges, still excluding long collar sides.
    median_len = sorted(lengths)[len(lengths) // 2]
    side_max = max(median_len * 4.0, 15.0)
    fallback = [
        (i, length, perp, outward, p0, p1)
        for i, length, perp, outward, p0, p1, align in edges
        if perp >= 0.7 and length <= side_max
    ]
    if len(fallback) >= 2:
        return sorted(fallback, key=lambda item: item[2], reverse=True)[:6]
    return sorted(edges, key=lambda item: item[2], reverse=True)[:4]


def _pick_endcap_edge_pair(
    caps: Sequence[tuple[int, float, float, float, Point, Point]],
) -> tuple[tuple[int, float, float, float, Point, Point], tuple[int, float, float, float, Point, Point]]:
    """The two end-cap edges farthest apart in Euclidean distance (legacy helper)."""
    best_pair = (caps[0], caps[1 if len(caps) > 1 else 0])
    best_span = -1.0
    for i in range(len(caps)):
        for j in range(i + 1, len(caps)):
            m0 = (
                (caps[i][4][0] + caps[i][5][0]) / 2.0,
                (caps[i][4][1] + caps[i][5][1]) / 2.0,
            )
            m1 = (
                (caps[j][4][0] + caps[j][5][0]) / 2.0,
                (caps[j][4][1] + caps[j][5][1]) / 2.0,
            )
            span = math.hypot(m1[0] - m0[0], m1[1] - m0[1])
            if span > best_span:
                best_span = span
                best_pair = (caps[i], caps[j])
    return best_pair


def _pick_cap_a_edge(
    caps: Sequence[tuple[int, float, float, float, Point, Point]],
) -> tuple[int, float, float, float, Point, Point]:
    """First end-cap corner on the preserved collar (lowest polygon edge index)."""
    return min(caps, key=lambda cap: cap[0])


def _short_endcap_edge_candidates(
    pts: Sequence[Point],
    lengths: Sequence[float],
    long_edges: set[int],
    *,
    min_edge_um: float = 0.5,
) -> list[tuple[int, float, float, float, Point, Point]]:
    """Short collar edges that are not part of the long sides (mouth end caps)."""
    n = len(pts)
    caps: list[tuple[int, float, float, float, Point, Point]] = []
    for i in range(n):
        if i in long_edges:
            continue
        length = lengths[i]
        if length < min_edge_um:
            continue
        p0 = (float(pts[i][0]), float(pts[i][1]))
        p1 = (float(pts[(i + 1) % n][0]), float(pts[(i + 1) % n][1]))
        caps.append((i, length, 0.0, 0.0, p0, p1))
    return caps


def _resolve_endcap_candidates(
    pts: Sequence[Point],
    normal: tuple[float, float],
    centroid: Point,
    lengths: Sequence[float],
    long_edges: set[int],
) -> list[tuple[int, float, float, float, Point, Point]]:
    """Short perpendicular end caps; fall back to long/short split when needed."""
    caps = _endcap_edge_candidates(pts, normal, centroid)
    if len(caps) >= 2:
        return caps
    return _short_endcap_edge_candidates(pts, lengths, long_edges)


def _walk_start_corner(cap_a_idx: int, step: int, n: int) -> int:
    """Corner vertex where the long-side walk leaves end cap ``cap_a``."""
    return (cap_a_idx + step) % n if step > 0 else cap_a_idx


def _walk_end_corner(last_edge_idx: int, step: int, n: int) -> int:
    """Corner vertex where the long-side walk meets the opposite end cap."""
    return (last_edge_idx + 1) % n if step > 0 else last_edge_idx


def _mouth_vertex_indices_from_lip(
    cap_a_idx: int,
    lip_edges: Sequence[int],
    step: int,
    n: int,
) -> list[int]:
    """Outer-lip vertex indices from one mouth corner to the other."""
    if not lip_edges:
        return [_walk_start_corner(cap_a_idx, step, n)]
    verts = [_walk_start_corner(cap_a_idx, step, n)]
    for edge in lip_edges:
        end = _walk_end_corner(edge, step, n)
        if verts[-1] != end:
            verts.append(end)
    return verts


def _mouth_edge_chain_between_caps(
    cap_a_idx: int,
    cap_b_idx: int,
    n: int,
) -> tuple[list[int], int]:
    """Shortest edge chain along the collar mouth from ``cap_a`` to ``cap_b``."""
    best_chain: list[int] = []
    best_step = +1
    best_len = float("inf")
    for step in (+1, -1):
        chain = _edge_chain_to_cap(cap_a_idx, cap_b_idx, step, n)
        if chain and len(chain) < best_len:
            best_len = len(chain)
            best_chain = chain
            best_step = step
    return best_chain, best_step


def _mouth_lip_edges(
    edge_chain: Sequence[int],
    cap_b_idx: int,
) -> list[int]:
    """Mouth lip edges between corner end caps (exclude the terminal end-cap edge)."""
    if not edge_chain:
        return []
    if edge_chain[-1] == cap_b_idx:
        return list(edge_chain[:-1])
    return list(edge_chain)


def _mouth_corner_endcaps(
    caps: Sequence[tuple[int, float, float, float, Point, Point]],
    long_edges: set[int],
    n: int,
) -> list[tuple[int, float, float, float, Point, Point]]:
    """True mouth corners: short end caps where the collar meets a long side."""
    cap_set = {cap[0] for cap in caps}
    corners = [
        cap
        for cap in caps
        if _is_mouth_corner_cap(cap[0], cap_set, long_edges, n)
    ]
    return corners if len(corners) >= 2 else list(caps)


def _long_edge_indices(
    lengths: Sequence[float],
    *,
    max_len: float | None = None,
) -> set[int]:
    peak = max_len if max_len is not None else max(lengths)
    threshold = max(peak * 0.15, 8.0)
    return {i for i, length in enumerate(lengths) if length > threshold}


def _edge_chain_to_cap(
    cap_a_idx: int,
    cap_b_idx: int,
    step: int,
    n: int,
) -> list[int]:
    """Edge indices from ``cap_a_idx`` to ``cap_b_idx`` in one direction."""
    edge = (cap_a_idx + step) % n
    chain: list[int] = []
    while edge != cap_a_idx:
        chain.append(edge)
        if edge == cap_b_idx:
            break
        edge = (edge + step) % n
        if len(chain) > n:
            break
    return chain if chain and chain[-1] == cap_b_idx else []


def _cap_leads_to_long_edge(
    edge_idx: int,
    step: int,
    cap_set: set[int],
    long_edges: set[int],
    n: int,
    *,
    max_hops: int = 12,
) -> bool:
    """True when ``step`` from ``edge_idx`` reaches a long edge before another end cap."""
    edge = (edge_idx + step) % n
    for _ in range(max_hops):
        if edge in long_edges:
            return True
        if edge in cap_set and edge != edge_idx:
            return False
        edge = (edge + step) % n
    return False


def _is_mouth_corner_cap(
    edge_idx: int,
    cap_set: set[int],
    long_edges: set[int],
    n: int,
) -> bool:
    """End-cap edge at a mouth corner (short edge where the collar meets a long side)."""
    if edge_idx not in cap_set:
        return False
    return _cap_leads_to_long_edge(
        edge_idx, +1, cap_set, long_edges, n
    ) or _cap_leads_to_long_edge(edge_idx, -1, cap_set, long_edges, n)


def _long_side_step_from_cap_a(
    cap_a_idx: int,
    cap_set: set[int],
    lengths: Sequence[float],
    long_edges: set[int],
    n: int,
) -> int:
    """Polygon walk direction from ``cap_a`` onto the nearest opposite mouth corner."""
    prev = (cap_a_idx - 1) % n
    nxt = (cap_a_idx + 1) % n
    perimeter = sum(lengths)

    def long_is_shortcut(edge_idx: int, step: int) -> bool:
        if edge_idx not in long_edges:
            return False
        return (edge_idx + step) % n in cap_set

    if nxt in long_edges and not long_is_shortcut(nxt, +1):
        return +1
    if prev in long_edges and not long_is_shortcut(prev, -1):
        return -1

    best_step = +1
    best_total = float("inf")
    for step in (+1, -1):
        edge = (cap_a_idx + step) % n
        total = 0.0
        found = False
        for _ in range(n):
            total += lengths[edge]
            if (
                edge in cap_set
                and edge != cap_a_idx
                and _is_mouth_corner_cap(edge, cap_set, long_edges, n)
            ):
                found = True
                break
            edge = (edge + step) % n
        if not found or total > perimeter * 0.55:
            continue
        if total < best_total:
            best_total = total
            best_step = step
    return best_step


def _walk_long_side_to_corner_cap(
    cap_a_idx: int,
    cap_set: set[int],
    lengths: Sequence[float],
    long_edges: set[int],
    n: int,
) -> tuple[int | None, list[int], int | None]:
    """
    Trace the long side from ``cap_a`` until the opposite mouth corner end cap.

    Walks one direction along long edges and stops at the first end-cap corner
    reached after leaving ``cap_a`` along a long edge.
    """
    step = _long_side_step_from_cap_a(
        cap_a_idx, cap_set, lengths, long_edges, n
    )
    edge = (cap_a_idx + step) % n
    edge_chain: list[int] = []
    seen_long = False
    for _ in range(n):
        edge_chain.append(edge)
        if edge in long_edges:
            seen_long = True
        if (
            seen_long
            and edge in cap_set
            and edge != cap_a_idx
            and _is_mouth_corner_cap(edge, cap_set, long_edges, n)
        ):
            return edge, edge_chain, step
        edge = (edge + step) % n
    return None, [], step


def _trace_cap_b_from_a(
    cap_a: tuple[int, float, float, float, Point, Point],
    caps: Sequence[tuple[int, float, float, float, Point, Point]],
    lengths: Sequence[float],
    long_edges: set[int],
    pts: Sequence[Point],
    normal: tuple[float, float],
    centroid: Point,
) -> tuple[int, float, float, float, Point, Point]:
    """Trace the long side from ``cap_a`` until the first mouth corner end cap."""
    del pts, normal, centroid
    cap_set = {cap[0] for cap in caps}
    cap_by_idx = {cap[0]: cap for cap in caps}
    cap_b_idx, _, _ = _walk_long_side_to_corner_cap(
        cap_a[0],
        cap_set,
        lengths,
        long_edges,
        len(lengths),
    )
    if cap_b_idx is None:
        others = [cap for cap in caps if cap[0] != cap_a[0]]
        if not others:
            raise ValueError("no opposite end cap on preserved collar")
        return max(others, key=lambda cap: cap[0])
    return cap_by_idx[cap_b_idx]


def _vertex_indices_from_edges(edge_chain: Sequence[int], n: int) -> list[int]:
    """Convert a consecutive edge-index walk to polygon vertex indices."""
    if not edge_chain:
        return []
    verts = [edge_chain[0]]
    for edge in edge_chain:
        end = (edge + 1) % n
        if verts[-1] != end:
            verts.append(end)
    return verts


def _mouth_chain_from_cap_walk(
    cap_a: tuple[int, float, float, float, Point, Point],
    cap_b: tuple[int, float, float, float, Point, Point],
    lengths: Sequence[float],
    n: int,
    pts: Sequence[Point],
    normal: tuple[float, float],
    centroid: Point,
) -> list[int]:
    """Outer-lip vertex chain from ``cap_a`` to ``cap_b`` on the long side."""
    perimeter = sum(lengths)
    best_chain: list[int] = []
    best_total = -1.0

    for step in (+1, -1):
        edge_chain = _edge_chain_to_cap(cap_a[0], cap_b[0], step, n)
        if not edge_chain:
            continue
        total = sum(lengths[edge] for edge in edge_chain)
        if total > perimeter * 0.55:
            continue
        if total > best_total:
            best_total = total
            best_chain = edge_chain

    if best_chain:
        return _vertex_indices_from_edges(best_chain, n)

    corner_a = _outer_vertex_on_endcap(cap_a[4], cap_a[5], normal, centroid)
    corner_b = _outer_vertex_on_endcap(cap_b[4], cap_b[5], normal, centroid)
    idx_a = _vertex_index_near(pts, corner_a)
    idx_b = _vertex_index_near(pts, corner_b)
    return _mouth_chain_between(pts, idx_a, idx_b, normal, centroid)


def _mouth_outward_normal(
    pts: Sequence[Point],
    mouth_indices: Sequence[int],
    centroid: Point,
    normal: tuple[float, float],
    *,
    intercept_a: Point | None = None,
    intercept_b: Point | None = None,
) -> tuple[float, float]:
    """Unit normal pointing from the collar interior toward the mouth exterior."""
    if intercept_a is not None and intercept_b is not None:
        tx = intercept_b[0] - intercept_a[0]
        ty = intercept_b[1] - intercept_a[1]
        length = math.hypot(tx, ty)
        if length >= 1e-9:
            tx /= length
            ty /= length
            mid = (
                (intercept_a[0] + intercept_b[0]) / 2.0,
                (intercept_a[1] + intercept_b[1]) / 2.0,
            )
            for nx, ny in ((-ty, tx), (ty, -tx)):
                if (mid[0] - centroid[0]) * nx + (mid[1] - centroid[1]) * ny > 1e-6:
                    return (nx, ny)
    if not mouth_indices:
        return normal
    mx = sum(float(pts[i][0]) for i in mouth_indices) / len(mouth_indices)
    my = sum(float(pts[i][1]) for i in mouth_indices) / len(mouth_indices)
    dx, dy = mx - centroid[0], my - centroid[1]
    if dx * normal[0] + dy * normal[1] < 0.0:
        return (-normal[0], -normal[1])
    return normal


def _outer_vertex_on_endcap(
    p0: Point,
    p1: Point,
    normal: tuple[float, float],
    centroid: Point,
) -> Point:
    """Corner on the outer lip where an end cap meets the long collar edge."""
    if _vertex_outward_score(p0, normal, centroid) >= _vertex_outward_score(
        p1, normal, centroid
    ):
        return p0
    return p1


def _vertex_index_near(pts: Sequence[Point], target: Point, tol: float = 0.05) -> int:
    best_i = 0
    best_d = float("inf")
    for i, p in enumerate(pts):
        d = math.hypot(float(p[0]) - target[0], float(p[1]) - target[1])
        if d < best_d:
            best_d = d
            best_i = i
    if best_d > tol:
        raise ValueError(f"vertex near {target} not found (best {best_d:.3f} um)")
    return best_i


def _mouth_chain_between(
    pts: Sequence[Point],
    start_idx: int,
    end_idx: int,
    normal: tuple[float, float],
    centroid: Point,
) -> list[int]:
    """Vertex indices along the outer lip from one end cap to the other."""
    n = len(pts)

    def mean_outward(idxs: list[int]) -> float:
        return sum(_vertex_outward_score(pts[i], normal, centroid) for i in idxs) / len(
            idxs
        )

    forward: list[int] = []
    i = start_idx
    for _ in range(n + 1):
        forward.append(i)
        if i == end_idx:
            break
        i = (i + 1) % n
    backward: list[int] = []
    i = start_idx
    for _ in range(n + 1):
        backward.append(i)
        if i == end_idx:
            break
        i = (i - 1) % n
    return forward if mean_outward(forward) >= mean_outward(backward) else backward


def _pick_best_mouth_intercepts(
    pts: Sequence[Point],
    normal: tuple[float, float],
    centroid: Point,
    lengths: Sequence[float],
    long_edges: set[int],
    *,
    max_lip_fraction: float = 0.55,
) -> CollarMouthIntercepts:
    """Pick the shortest outer-lip walk between two mouth-corner end caps."""
    n = len(pts)
    perimeter = sum(lengths)
    caps = _resolve_endcap_candidates(pts, normal, centroid, lengths, long_edges)
    if len(caps) < 2:
        raise ValueError("preserved collar has fewer than two end-cap edges")

    corners = _mouth_corner_endcaps(caps, long_edges, n)
    if len(corners) < 2:
        corners = list(caps)

    best: tuple[
        tuple[float, float],
        tuple[int, float, float, float, Point, Point],
        tuple[int, float, float, float, Point, Point],
        list[int],
        int,
        Point,
        Point,
    ] | None = None

    for i in range(len(corners)):
        for j in range(i + 1, len(corners)):
            cap_a, cap_b = corners[i], corners[j]
            for step in (+1, -1):
                chain = _edge_chain_to_cap(cap_a[0], cap_b[0], step, n)
                if not chain:
                    continue
                lip_edges = _mouth_lip_edges(chain, cap_b[0])
                if not lip_edges:
                    continue
                lip_len = sum(lengths[edge] for edge in chain)
                if lip_len > perimeter * max_lip_fraction:
                    continue
                intercept_a = pts[_walk_start_corner(cap_a[0], step, n)]
                intercept_b = pts[_walk_end_corner(lip_edges[-1], step, n)]
                span = math.hypot(
                    intercept_b[0] - intercept_a[0], intercept_b[1] - intercept_a[1]
                )
                key = (lip_len, span)
                if best is None or key < best[0]:
                    best = (key, cap_a, cap_b, lip_edges, step, intercept_a, intercept_b)

    if best is None:
        raise ValueError("could not find mouth lip between end-cap corners")

    _, cap_a, cap_b, lip_edges, step, intercept_a, intercept_b = best
    mouth_indices = _mouth_vertex_indices_from_lip(cap_a[0], lip_edges, step, n)
    outward_normal = _mouth_outward_normal(
        pts,
        mouth_indices,
        centroid,
        normal,
        intercept_a=intercept_a,
        intercept_b=intercept_b,
    )
    mouth_span = math.hypot(
        intercept_b[0] - intercept_a[0], intercept_b[1] - intercept_a[1]
    )
    return CollarMouthIntercepts(
        intercept_a=intercept_a,
        intercept_b=intercept_b,
        mouth_indices=mouth_indices,
        outward_normal=outward_normal,
        facing_edge=(intercept_a, intercept_b),
        endcap_edge_a=(cap_a[4], cap_a[5]),
        endcap_edge_b=(cap_b[4], cap_b[5]),
        endcap_index_a=cap_a[0],
        endcap_index_b=cap_b[0],
        mouth_span_um=mouth_span,
    )


def find_collar_mouth_intercepts(
    preserved_collar: gdstk.Polygon,
    *,
    overlap_um: float = _COLLAR_OVERLAP_UM,
) -> CollarMouthIntercepts:
    """
    Two intercept points at the corners of the collared MTE mouth.

    Enumerate mouth-corner end-cap pairs and keep the shortest outer-lip walk
    (not the farthest-apart caps, which can trace a stadium interior band).
    """
    del overlap_um
    pts_in = list(preserved_collar.points)
    if len(pts_in) < 4:
        raise ValueError("preserved collar must have at least 4 vertices")
    pts = [(float(p[0]), float(p[1])) for p in pts_in]
    toward = _outward_target(preserved_collar)
    normal = _outward_normal_from_target(preserved_collar, toward)
    centroid = _polygon_centroid(preserved_collar)
    n = len(pts)
    lengths = [_edge_length((pts[i], pts[(i + 1) % n])) for i in range(n)]
    long_edges = _long_edge_indices(lengths)
    return _pick_best_mouth_intercepts(pts, normal, centroid, lengths, long_edges)


def _collar_inner_chain(
    pts: Sequence[Point],
    mouth_indices: Sequence[int],
    normal: tuple[float, float],
    *,
    overlap_um: float,
) -> list[Point]:
    """Collar outline between intercepts, nudged slightly into the collar for overlap."""
    nx, ny = normal
    return [
        (float(pts[i][0]) - nx * overlap_um, float(pts[i][1]) - ny * overlap_um)
        for i in mouth_indices
    ]


def _extension_builds_outward(
    inner_chain: Sequence[Point],
    normal: tuple[float, float],
    extension_um: float,
) -> bool:
    """True when extruding by ``normal`` places the cap outside the inner chain."""
    if len(inner_chain) < 2:
        return True
    ref = inner_chain[0]
    nx, ny = normal
    inner_far = max(
        (p[0] - ref[0]) * nx + (p[1] - ref[1]) * ny for p in inner_chain
    )
    outer_test = (
        inner_chain[-1][0] + nx * extension_um,
        inner_chain[-1][1] + ny * extension_um,
    )
    outer_dist = (outer_test[0] - ref[0]) * nx + (outer_test[1] - ref[1]) * ny
    return outer_dist > inner_far + 1e-6


def _offset_outward(point: Point, ref: Point, normal: tuple[float, float], height_um: float) -> Point:
    nx, ny = normal
    dist = _outward_distance(point, ref, normal)
    return (
        point[0] + nx * (height_um - dist),
        point[1] + ny * (height_um - dist),
    )


def _build_extension_from_intercepts(
    inner_chain: Sequence[Point],
    ref: Point,
    normal: tuple[float, float],
    extension_um: float,
    layer: int,
    datatype: int,
) -> CollarExtensionDraw:
    """Inner collar chain + outward sides + one horizontal cap edge."""
    if len(inner_chain) < 2:
        raise ValueError("mouth chain needs at least 2 intercept points")
    intercept_a, intercept_b = inner_chain[0], inner_chain[-1]
    d_far = max(_outward_distance(p, ref, normal) for p in inner_chain) + extension_um
    outer_a = _offset_outward(intercept_a, ref, normal, d_far)
    outer_b = _offset_outward(intercept_b, ref, normal, d_far)
    polygon = gdstk.Polygon(
        list(inner_chain) + [outer_b, outer_a],
        layer=layer,
        datatype=datatype,
    )
    return CollarExtensionDraw(
        polygon=polygon,
        intercept_a=intercept_a,
        intercept_b=intercept_b,
        outer_edge=(outer_b, outer_a),
        extension_um=extension_um,
        target_extension_um=extension_um,
    )


def _extension_draw_from_mouth(
    mouth: CollarMouthIntercepts,
    inner_chain: Sequence[Point],
    ref: Point,
    extension_um: float,
    layer: int,
    datatype: int,
    *,
    target_extension_um: float | None = None,
) -> CollarExtensionDraw:
    draw = _build_extension_from_intercepts(
        inner_chain, ref, mouth.outward_normal, extension_um, layer, datatype
    )
    target = target_extension_um if target_extension_um is not None else extension_um
    return CollarExtensionDraw(
        polygon=draw.polygon,
        intercept_a=draw.intercept_a,
        intercept_b=draw.intercept_b,
        outer_edge=draw.outer_edge,
        extension_um=draw.extension_um,
        target_extension_um=target,
        endcap_edge_a=mouth.endcap_edge_a,
        endcap_edge_b=mouth.endcap_edge_b,
        endcap_index_a=mouth.endcap_index_a,
        endcap_index_b=mouth.endcap_index_b,
        mouth_span_um=mouth.mouth_span_um,
        mouth_vertices=len(mouth.mouth_indices),
        collar_intercept_a=mouth.intercept_a,
        collar_intercept_b=mouth.intercept_b,
    )


def _segment_hits_polys(
    p0: Point,
    p1: Point,
    obstacles: Sequence[gdstk.Polygon],
    precision: float,
    *,
    half_width_um: float = _SEGMENT_TEST_HALF_WIDTH_UM,
    clearance_um: float = 0.0,
) -> bool:
    """True when a segment (optionally buffered) intersects any obstacle polygon."""
    if not obstacles:
        return False
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return False
    nx, ny = -dy / length, dx / length
    pad = half_width_um + max(clearance_um, 0.0)
    ox, oy = nx * pad, ny * pad
    seg_poly = gdstk.Polygon(
        [
            (p0[0] - ox, p0[1] - oy),
            (p1[0] - ox, p1[1] - oy),
            (p1[0] + ox, p1[1] + oy),
            (p0[0] + ox, p0[1] + oy),
        ]
    )
    for obstacle in obstacles:
        if gdstk.boolean(seg_poly, obstacle, "and", precision=precision):
            return True
    return False


def _fit_horizontal_cap_height(
    mouth: CollarMouthIntercepts,
    inner_chain: Sequence[Point],
    ref: Point,
    target_um: float,
    layer: int,
    datatype: int,
    obstacles: Sequence[gdstk.Polygon],
    *,
    min_um: float = 1.0,
    precision: float = 1e-3,
    frame_clearance_um: float = _DEFAULT_FRAME_CLEARANCE_UM,
) -> CollarExtensionDraw:
    """Reduce outward height until the horizontal cap clears die-frame obstacles."""
    best: CollarExtensionDraw | None = None
    step = 0.5
    height = target_um
    while height >= min_um - 1e-9:
        draw = _extension_draw_from_mouth(
            mouth,
            inner_chain,
            ref,
            height,
            layer,
            datatype,
            target_extension_um=target_um,
        )
        if not _segment_hits_polys(
            draw.outer_edge[0],
            draw.outer_edge[1],
            obstacles,
            precision,
            clearance_um=frame_clearance_um,
        ):
            return draw
        best = draw
        height -= step
    if best is None:
        raise ValueError("could not build collar extension at minimum height")
    return CollarExtensionDraw(
        polygon=best.polygon,
        intercept_a=best.intercept_a,
        intercept_b=best.intercept_b,
        outer_edge=best.outer_edge,
        extension_um=min_um,
        target_extension_um=target_um,
        endcap_edge_a=mouth.endcap_edge_a,
        endcap_edge_b=mouth.endcap_edge_b,
        endcap_index_a=mouth.endcap_index_a,
        endcap_index_b=mouth.endcap_index_b,
        mouth_span_um=mouth.mouth_span_um,
        mouth_vertices=len(mouth.mouth_indices),
        collar_intercept_a=mouth.intercept_a,
        collar_intercept_b=mouth.intercept_b,
    )


def draw_preserved_mte_extension(
    preserved_collar: gdstk.Polygon,
    extension_um: float,
    layer: int,
    datatype: int,
    *,
    overlap_um: float = _COLLAR_OVERLAP_UM,
    frame_obstacles: Sequence[gdstk.Polygon] | None = None,
    min_extension_um: float = 1.0,
    boolean_precision: float = 1e-3,
    frame_clearance_um: float = _DEFAULT_FRAME_CLEARANCE_UM,
) -> CollarExtensionDraw:
    """
    Draw one new MTE polygon from a preserved collar.

    1. Find two intercept points on the collar mouth.
    2. Trace the collar outline between them for the inner edge.
    3. Extrude outward with straight sides and one horizontal cap edge.
    4. Shrink outward height if the cap intersects die-frame obstacles.
    """
    if extension_um <= 0:
        raise ValueError("extension_um must be positive")
    mouth = find_collar_mouth_intercepts(preserved_collar, overlap_um=overlap_um)
    pts = [(float(p[0]), float(p[1])) for p in preserved_collar.points]
    ref = _edge_midpoint(mouth.facing_edge)
    normal = mouth.outward_normal
    if not _extension_builds_outward(
        _collar_inner_chain(pts, mouth.mouth_indices, normal, overlap_um=overlap_um),
        normal,
        extension_um,
    ):
        normal = (-normal[0], -normal[1])
        mouth = CollarMouthIntercepts(
            intercept_a=mouth.intercept_a,
            intercept_b=mouth.intercept_b,
            mouth_indices=mouth.mouth_indices,
            outward_normal=normal,
            facing_edge=mouth.facing_edge,
            endcap_edge_a=mouth.endcap_edge_a,
            endcap_edge_b=mouth.endcap_edge_b,
            endcap_index_a=mouth.endcap_index_a,
            endcap_index_b=mouth.endcap_index_b,
            mouth_span_um=mouth.mouth_span_um,
        )
    inner_chain = _collar_inner_chain(
        pts, mouth.mouth_indices, normal, overlap_um=overlap_um
    )
    obstacles = list(frame_obstacles or [])
    if obstacles:
        return _fit_horizontal_cap_height(
            mouth,
            inner_chain,
            ref,
            extension_um,
            layer,
            datatype,
            obstacles,
            min_um=min_extension_um,
            precision=boolean_precision,
            frame_clearance_um=frame_clearance_um,
        )
    return _extension_draw_from_mouth(
        mouth, inner_chain, ref, extension_um, layer, datatype
    )


def _collar_overlap_area(ext: gdstk.Polygon, collar: gdstk.Polygon, precision: float) -> float:
    inter = gdstk.boolean(ext, collar, "and", precision=precision)
    return sum(abs(p.area()) for p in inter) if inter else 0.0


def _validate_extension(
    ext: gdstk.Polygon,
    collar: gdstk.Polygon,
    *,
    precision: float,
    min_overlap_um2: float,
    resonator_index: int | None = None,
) -> None:
    overlap = _collar_overlap_area(ext, collar, precision)
    collar_area = abs(collar.area())
    ext_area = abs(ext.area())
    prefix = f"resonator {resonator_index}: " if resonator_index is not None else ""
    if overlap < min_overlap_um2:
        raise ValueError(
            f"{prefix}MTE extension not attached to collar "
            f"(overlap {overlap:.2f} um² < {min_overlap_um2:.2f} um²)"
        )
    if collar_area > 1e-6 and overlap / collar_area > _MAX_OVERLAP_FRACTION:
        raise ValueError(
            f"{prefix}MTE extension covers too much of collar "
            f"(overlap/collar = {overlap / collar_area:.2f} > {_MAX_OVERLAP_FRACTION})"
        )


def draw_collar_extension(
    collar_tp: TaggedPolygon,
    layermap: LayerMap,
    cfg: MteBuildConfig,
    *,
    frame_obstacles: Sequence[gdstk.Polygon] | None = None,
    resonator_index: int | None = None,
) -> CollarExtensionDraw:
    layer, datatype = layermap.pair(cfg.mte_layer)
    draw = draw_preserved_mte_extension(
        collar_tp.polygon,
        cfg.collar_extension_um,
        layer,
        datatype,
        frame_obstacles=frame_obstacles,
        min_extension_um=cfg.min_extension_um,
        boolean_precision=cfg.boolean_precision,
        frame_clearance_um=cfg.frame_clearance_um,
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
    )
    _validate_extension(
        draw.polygon,
        collar_tp.polygon,
        precision=cfg.boolean_precision,
        min_overlap_um2=cfg.min_collar_overlap_um2,
        resonator_index=resonator_index,
    )
    return draw


def select_edge_collar_mte(
    preserved: PreservedMetal,
    body_mte_polys: Sequence[gdstk.Polygon],
    *,
    min_overlap_um2: float = 0.01,
    precision: float = 1e-3,
) -> TaggedPolygon | None:
    """Pick the edge collar: smallest body-overlapping piece, or the small leg of a pair."""
    if not preserved.mte:
        return None
    pieces = list(preserved.mte)
    overlaps = [
        (tp, preserved_mte_overlap_with_body(tp.polygon, body_mte_polys, precision=precision))
        for tp in pieces
    ]
    overlapping = [tp for tp, ov in overlaps if ov >= min_overlap_um2]
    if len(pieces) == 2 and len(overlapping) == 1:
        big = overlapping[0]
        small = next(tp for tp in pieces if tp is not big)
        if abs(small.polygon.area()) * _OUTLINE_AREA_RATIO < abs(big.polygon.area()):
            return small
    if not overlapping:
        return min(pieces, key=lambda tp: abs(tp.polygon.area()))
    return min(overlapping, key=lambda tp: abs(tp.polygon.area()))


def _extension_for_roles(
    roles: _HasPreserved,
    layermap: LayerMap,
    cfg: MteBuildConfig,
    *,
    resonator_index: int,
) -> MteExtensionResult:
    preserved_polys = [tp.polygon for tp in roles.preserved.mte]
    collar_tp = select_edge_collar_mte(
        roles.preserved,
        roles.resonator_body_mte,
        min_overlap_um2=cfg.min_collar_overlap_um2,
        precision=cfg.boolean_precision,
    )
    if collar_tp is None:
        raise ValueError(
            f"resonator {resonator_index}: no preserved MTE collar to extend"
        )
    draw = draw_collar_extension(
        collar_tp,
        layermap,
        cfg,
        frame_obstacles=mte_extension_frame_obstacles(roles, layermap),
        resonator_index=resonator_index,
    )
    return MteExtensionResult(
        collar=collar_tp,
        extension=draw.polygon,
        preserved_collar_polygons=preserved_polys,
        n_extensions=1,
        is_connected=True,
        extension_draw=draw,
    )


def build_mte_extensions(
    roles_by_index: Mapping[int, _HasPreserved],
    layermap: LayerMap,
    config: MteBuildConfig | None = None,
) -> dict[int, MteExtensionResult]:
    cfg = config or MteBuildConfig()
    return {
        idx: _extension_for_roles(roles, layermap, cfg, resonator_index=idx)
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
        cell = self.frame.flatten().copy(f"rteg_{self.index:02d}_{self.inst_name}_mte")
        if self.extension.extension is not None:
            p = self.extension.extension
            cell.add(gdstk.Polygon(p.points, p.layer, p.datatype))
        return cell


def export_mte_extensions_gds(
    frame_assemblies: Sequence[RtegFrameAssembly],
    extensions: Mapping[int, MteExtensionResult],
    output_dir: str | Path,
    *,
    layermap: LayerMap,
    parent: str | None = None,
    flatten: bool = True,
    write_lyp: bool = True,
) -> list[ExportResult]:
    assemblies = [
        MteRtegAssembly(frame=asm, extension=extensions[asm.index])
        for asm in frame_assemblies
        if asm.index in extensions and extensions[asm.index].n_extensions > 0
    ]
    return export_gds(
        assemblies,
        output_dir,
        layermap=layermap,
        parent=parent,
        stage="mte",
        flatten=flatten,
        write_lyp=write_lyp,
    )


__all__ = [
    "CollarExtensionDraw",
    "CollarMouthIntercepts",
    "MteBuildConfig",
    "MteExtensionResult",
    "MteRtegAssembly",
    "build_mte_extensions",
    "draw_collar_extension",
    "export_mte_extensions_gds",
    "find_collar_mouth_intercepts",
    "mte_extensions_overview_rows",
    "mte_intercept_breakdown_rows",
    "select_edge_collar_mte",
]
