"""
Optional MTE extension simplification helpers (not used in the current pipeline).

``simplify_mte_extension`` and ``retrace_mte_extension_along_collar`` reshape the
preserved filter MTE extension stub only — collar and resonator body MTE are
never modified.
"""
from __future__ import annotations

import math
from collections.abc import Sequence

import gdstk

from layermap import LayerMap
from rteg_mte_extensions import CollarExtensionDraw
from rteg_mte_route import (
    PreservedMteParts,
    _point_on_polygon_boundary,
    identify_preserved_mte_parts,
)
from rteg_utils import assign_layer

Point = tuple[float, float]


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _dedupe_vertices(points: Sequence[Point], tol_um: float) -> list[Point]:
    if not points:
        return []
    out = [points[0]]
    for pt in points[1:]:
        if _dist(pt, out[-1]) > tol_um:
            out.append(pt)
    if len(out) > 1 and _dist(out[0], out[-1]) <= tol_um:
        out.pop()
    return out


def _nearest_vertex(point: Point, pts: Sequence[Point]) -> int:
    return min(range(len(pts)), key=lambda i: _dist(point, pts[i]))


def _on_collar(point: Point, collar: gdstk.Polygon, tol_um: float) -> bool:
    return _point_on_polygon_boundary(point, collar, tol_um)


def _segment_overlaps_body(
    start: Point,
    end: Point,
    body_mte_polys: Sequence[gdstk.Polygon],
    *,
    boolean_precision: float,
    half_width_um: float = 0.05,
) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 1e-9:
        return 0.0
    nx, ny = -dy / length * half_width_um, dx / length * half_width_um
    strip = gdstk.Polygon(
        [
            start,
            (start[0] + nx, start[1] + ny),
            end,
            (end[0] - nx, end[1] - ny),
        ],
        layer=5,
        datatype=0,
    )
    overlap = 0.0
    for body in body_mte_polys:
        inter = gdstk.boolean(strip, body, "and", precision=boolean_precision)
        if inter:
            overlap += sum(abs(p.area()) for p in inter)
    return overlap


def _first_outward_vertex(
    pts: Sequence[Point],
    attach_idx: int,
    collar: gdstk.Polygon | None,
    *,
    boundary_tol_um: float,
    mode: str,
    exclude_indices: set[int] | None = None,
) -> Point:
    """First boundary step outward from a collar attachment vertex."""
    n = len(pts)
    exclude = exclude_indices or set()
    neighbor_specs = (
        (1, pts[(attach_idx + 1) % n]),
        (-1, pts[(attach_idx - 1) % n]),
    )
    neighbors = [
        pt
        for step, pt in neighbor_specs
        if (attach_idx + step) % n not in exclude
    ]
    if not neighbors:
        neighbors = [pt for _, pt in neighbor_specs]

    on_collar = [
        pt
        for pt in neighbors
        if collar is None or _on_collar(pt, collar, boundary_tol_um)
    ]
    if mode == "right":
        candidates = on_collar or neighbors
        return max(candidates, key=lambda p: p[0])
    candidates = on_collar or neighbors
    return max(candidates, key=lambda p: (p[1], p[0]))


def _right_side_attach(
    pts: Sequence[Point],
    collar: gdstk.Polygon | None,
    *,
    boundary_tol_um: float,
) -> int:
    """Extension vertex on the collar with largest X (right-side stub)."""
    if collar is None:
        return max(range(len(pts)), key=lambda i: pts[i][0])
    on_collar = [i for i, pt in enumerate(pts) if _on_collar(pt, collar, boundary_tol_um)]
    if not on_collar:
        return max(range(len(pts)), key=lambda i: pts[i][0])
    return max(on_collar, key=lambda i: pts[i][0])


def _right_angle_close(
    side_a: Point,
    side_b: Point,
    body_mte_polys: Sequence[gdstk.Polygon],
    *,
    boolean_precision: float,
    max_body_overlap_um2: float,
) -> tuple[Point, Point, Point, float]:
    """Return ``(corner, leg_a, leg_b, overlap)`` for an axis-aligned outer L."""
    corner_a = (side_b[0], side_a[1])
    corner_b = (side_a[0], side_b[1])
    overlap_a = _segment_overlaps_body(
        side_a, corner_a, body_mte_polys, boolean_precision=boolean_precision
    ) + _segment_overlaps_body(
        corner_a, side_b, body_mte_polys, boolean_precision=boolean_precision
    )
    overlap_b = _segment_overlaps_body(
        side_a, corner_b, body_mte_polys, boolean_precision=boolean_precision
    ) + _segment_overlaps_body(
        corner_b, side_b, body_mte_polys, boolean_precision=boolean_precision
    )
    if overlap_a <= overlap_b:
        return corner_a, side_a, side_b, overlap_a
    return corner_b, side_a, side_b, overlap_b


def simplify_mte_extension(
    source_extension: gdstk.Polygon,
    body_mte_polys: Sequence[gdstk.Polygon],
    layermap: LayerMap,
    *,
    extension_draw: CollarExtensionDraw | None = None,
    preserved_parts: PreservedMteParts | None = None,
    boolean_precision: float = 1e-3,
    boundary_tol_um: float = 0.5,
    vertex_merge_um: float = 0.5,
    max_body_overlap_um2: float = 0.05,
    mte_layer: str = "BAW_MTE",
) -> tuple[gdstk.Polygon | None, list[str]]:
    """
    Collar-attachment trace: inner mouth straight between intercepts, outer L
    through the first vertices traced outward from the mouth and right-side stubs.
    """
    violations: list[str] = []
    if extension_draw is None:
        violations.append("missing extension draw metadata for MTE reshape")
        return None, violations

    collar = preserved_parts.collar if preserved_parts is not None else None
    pts = _dedupe_vertices(
        [(float(p[0]), float(p[1])) for p in source_extension.points],
        vertex_merge_um,
    )
    if len(pts) < 4:
        violations.append("MTE extension has fewer than 4 vertices after cleanup")
        return None, violations

    attach_up = _nearest_vertex(extension_draw.collar_intercept_a, pts)
    attach_dn = _nearest_vertex(extension_draw.collar_intercept_b, pts)
    mouth_up = pts[attach_up]
    mouth_dn = pts[attach_dn]

    outer_from_mouth = _first_outward_vertex(
        pts,
        attach_up,
        collar,
        boundary_tol_um=boundary_tol_um,
        mode="mouth",
        exclude_indices={attach_dn},
    )
    outer_from_dn = _first_outward_vertex(
        pts,
        attach_dn,
        collar,
        boundary_tol_um=boundary_tol_um,
        mode="mouth",
        exclude_indices={attach_up},
    )
    right_idx = _right_side_attach(pts, collar, boundary_tol_um=boundary_tol_um)
    outer_from_right = _first_outward_vertex(
        pts,
        right_idx,
        collar,
        boundary_tol_um=boundary_tol_um,
        mode="right",
        exclude_indices={attach_up, attach_dn},
    )
    if outer_from_right[0] > outer_from_mouth[0] + vertex_merge_um:
        outer_far = outer_from_right
    elif outer_from_dn[0] > outer_from_mouth[0] + vertex_merge_um:
        outer_far = outer_from_dn
    else:
        outer_far = max(
            (outer_from_dn, outer_from_right),
            key=lambda p: _dist(outer_from_mouth, p),
        )
    if _dist(outer_from_mouth, outer_far) < vertex_merge_um:
        violations.append("collar-traced outer legs collapsed to the same point")
        return None, violations

    corner, leg_mouth, leg_far, overlap = _right_angle_close(
        outer_from_mouth,
        outer_far,
        body_mte_polys,
        boolean_precision=boolean_precision,
        max_body_overlap_um2=max_body_overlap_um2,
    )

    ring = _dedupe_vertices(
        [mouth_dn, mouth_up, leg_mouth, corner, leg_far],
        vertex_merge_um,
    )
    if len(ring) < 4:
        violations.append("could not build collar-traced MTE extension ring")
        return None, violations

    if overlap > max_body_overlap_um2:
        violations.append(
            "outer right-angle corner overlaps resonator body MTE "
            f"(overlap={overlap:.4f} um²)"
        )

    layer, datatype = source_extension.layer, source_extension.datatype
    reshaped = gdstk.Polygon(ring, layer=layer, datatype=datatype)
    if reshaped.area() * source_extension.area() < 0:
        reshaped = gdstk.Polygon(list(reversed(ring)), layer=layer, datatype=datatype)

    tagged = assign_layer(reshaped, layermap, mte_layer)
    return tagged, violations


def retrace_mte_extension_along_collar(
    parts: PreservedMteParts | None,
    extension_draw: CollarExtensionDraw | None,
    body_mte_polys: Sequence[gdstk.Polygon],
    source_extension: gdstk.Polygon,
    layermap: LayerMap,
    *,
    route_cfg: object | None = None,
    mte_build_cfg: object | None = None,
) -> tuple[gdstk.Polygon | None, list[str]]:
    _ = mte_build_cfg
    precision = getattr(route_cfg, "boolean_precision", 1e-3)
    boundary_tol = getattr(route_cfg, "boundary_tolerance_um", 0.5)
    return simplify_mte_extension(
        source_extension,
        body_mte_polys,
        layermap,
        extension_draw=extension_draw,
        preserved_parts=parts,
        boolean_precision=precision,
        boundary_tol_um=boundary_tol,
    )


__all__ = [
    "identify_preserved_mte_parts",
    "retrace_mte_extension_along_collar",
    "simplify_mte_extension",
]
