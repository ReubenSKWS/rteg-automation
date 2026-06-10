"""
Step 5 — Deterministic MBE ground-route candidate search.

## Assumptions
- ``RoutingContext`` is fully built by ``route_rteg`` (endpoints, region, obstacles).
- Candidate geometry is limited to straight / single-45 / L-bend (two corner choices).
- All tunables live in ``RouteSearchConfig``; filter/score logic uses no magic numbers.
- PPD and die frame stay fixed; only resonator + preserved metal shift per candidate.
- Ground routes target outer GSG pads only; center signal pad metal is an obstacle.
- Lower ``RouteCandidate.score`` is better.

## Scoring
``score = weight_length * length_um - weight_min_clearance * min_clearance_um
         + weight_bends * n_bends + weight_shift * shift_magnitude_um``

## Rejection categories (``RouteResult.rejection_tallies``)
``outside_region``, ``spacing``, ``release_hole``, ``overlap_route``
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import gdstk

from route_primitives import (
    l_route_corners,
    min_spacing_to_many,
    polygon_inside_region,
    polyline_length,
    route_45,
    route_L,
    route_straight,
    translate_polygons,
)

Point = tuple[float, float]


@dataclass(frozen=True)
class RouteSearchConfig:
    """
    All step-5 routing tunables. Layer fields are layermap names resolved at runtime.

    Assumption A12: ``route_width_um`` is an operator input (golden/SME measurement).
    """


    target_route_layer: str = "BAW_MBE"
    obstacle_layers: tuple[str, ...] = ("BAW_MTE",)
    release_hole_layers: tuple[str, ...] = ("BAW_ReF", "BAW_CAV")

    mbe_mte_spacing_um: float = 14.0
    release_hole_clearance_um: float = 6.0
    safety_margin_um: float = 21.0
    route_width_um: float = 14.0
    preserved_overlap_margin_um: float = 10.0

    placement_shifts_um: tuple[tuple[float, float], ...] = (
        (0.0, 0.0),
        (10.0, 0.0),
        (-10.0, 0.0),
        (0.0, 10.0),
        (0.0, -10.0),
        (20.0, 0.0),
        (-20.0, 0.0),
        (0.0, 20.0),
        (0.0, -20.0),
        (10.0, 10.0),
        (-10.0, 10.0),
        (10.0, -10.0),
        (-10.0, -10.0),
    )

    weight_length: float = 1.0
    weight_min_clearance: float = 2.0
    weight_bends: float = 5.0
    weight_shift: float = 0.5

    signal_pad_position: str = "center"
    signal_layer: str = "BAW_MTE"
    ground_pad_positions: tuple[str, ...] = ("outer",)
    ground_layer: str = "BAW_MBE"


@dataclass
class RouteCandidate:
    route_polygon: gdstk.Polygon
    placement_shift: tuple[float, float]
    shape_name: str
    pad_label: str
    score: float
    length_um: float
    min_clearance_um: float
    n_bends: int


@dataclass
class RouteResult:
    """Best survivor or ``None`` with categorized rejection counts."""

    candidate: RouteCandidate | None
    n_candidates: int = 0
    n_clean: int = 0
    rejection_tallies: dict[str, int] = field(default_factory=dict)


@dataclass
class RoutingContext:
    """
    Per-resonator search state built by ``route_rteg``.

    ``shifted_geometry_fn(dx, dy)`` returns
    ``(preserved_mbe, resonator_mbe, ground_endpoint, pad_endpoint)``.
    """

    fixed_spacing_obstacles: list[gdstk.Polygon]
    release_hole_obstacles: list[gdstk.Polygon]
    routable_region_fn: Callable[[Sequence[gdstk.Polygon]], list[gdstk.Polygon]]
    ground_pads: list[tuple[str, gdstk.Polygon]]
    shifted_geometry_fn: Callable[
        [float, float],
        tuple[
            list[gdstk.Polygon],
            list[gdstk.Polygon],
            Point,
            dict[str, Point],
        ],
    ]
    route_layer: int
    route_datatype: int
    config: RouteSearchConfig


def _shift_magnitude(shift: tuple[float, float]) -> float:
    return abs(shift[0]) + abs(shift[1])


def _score_candidate(
    *,
    length_um: float,
    min_clearance_um: float,
    n_bends: int,
    shift: tuple[float, float],
    config: RouteSearchConfig,
) -> float:
    return (
        config.weight_length * length_um
        - config.weight_min_clearance * min_clearance_um
        + config.weight_bends * n_bends
        + config.weight_shift * _shift_magnitude(shift)
    )


def _route_specs(
    pad_pt: Point,
    metal_pt: Point,
    width: float,
) -> list[tuple[str, gdstk.Polygon, int, list[Point]]]:
    """Shape family × centerline metadata for scoring."""
    specs: list[tuple[str, gdstk.Polygon, int, list[Point]]] = []
    specs.append(
        (
            "straight",
            route_straight(pad_pt, metal_pt, width),
            0,
            [pad_pt, metal_pt],
        )
    )
    specs.append(
        (
            "route_45",
            route_45(pad_pt, metal_pt, width),
            1,
            [pad_pt, metal_pt],
        )
    )
    for corner in l_route_corners(pad_pt, metal_pt):
        specs.append(
            (
                "route_L",
                route_L(pad_pt, metal_pt, width, corner=corner),
                2,
                [pad_pt, corner, metal_pt],
            )
        )
    return specs


def _passes_filters(
    route: gdstk.Polygon,
    context: RoutingContext,
    preserved: Sequence[gdstk.Polygon],
    spacing_obstacles: Sequence[gdstk.Polygon],
    routable_region: Sequence[gdstk.Polygon],
    tallies: dict[str, int],
) -> bool:
    cfg = context.config
    if not polygon_inside_region(route, routable_region):
        tallies["outside_region"] = tallies.get("outside_region", 0) + 1
        return False

    min_space = min_spacing_to_many(route, spacing_obstacles)
    if min_space < cfg.mbe_mte_spacing_um - 1e-6:
        tallies["spacing"] = tallies.get("spacing", 0) + 1
        return False

    rh_space = min_spacing_to_many(route, context.release_hole_obstacles)
    if rh_space < cfg.release_hole_clearance_um - 1e-6:
        tallies["release_hole"] = tallies.get("release_hole", 0) + 1
        return False

    # Preserved MBE is the same net as the route (A3); connection overlap is allowed.

    return True


def search_route(context: RoutingContext) -> RouteResult:
    """
    Deterministic candidate search: placements × shapes × outer ground pads.

    Returns the lowest-score DRC-clean candidate or ``None``.
    """
    cfg = context.config
    tallies: dict[str, int] = {}
    survivors: list[RouteCandidate] = []
    n_candidates = 0

    for shift in cfg.placement_shifts_um:
        preserved, res_mbe, _ground_pt, pad_pts = context.shifted_geometry_fn(*shift)
        if not preserved:
            tallies["no_endpoint"] = tallies.get("no_endpoint", 0) + 1
            continue

        spacing_obstacles = list(context.fixed_spacing_obstacles) + list(res_mbe)
        routable_region = context.routable_region_fn(res_mbe)

        for pad_label, pad_poly in context.ground_pads:
            pad_pt = pad_pts.get(pad_label)
            if pad_pt is None:
                tallies["no_endpoint"] = tallies.get("no_endpoint", 0) + 1
                continue

            metal_pt = _ground_pt
            for shape_name, route_poly, n_bends, centerline in _route_specs(
                pad_pt, metal_pt, cfg.route_width_um
            ):
                n_candidates += 1
                route = gdstk.Polygon(
                    route_poly.points,
                    layer=context.route_layer,
                    datatype=context.route_datatype,
                )
                if not _passes_filters(
                    route,
                    context,
                    preserved,
                    spacing_obstacles,
                    routable_region,
                    tallies,
                ):
                    continue

                length_um = polyline_length(centerline)
                min_clear = min_spacing_to_many(route, spacing_obstacles)
                score = _score_candidate(
                    length_um=length_um,
                    min_clearance_um=min_clear,
                    n_bends=n_bends,
                    shift=shift,
                    config=cfg,
                )
                survivors.append(
                    RouteCandidate(
                        route_polygon=route,
                        placement_shift=shift,
                        shape_name=shape_name,
                        pad_label=pad_label,
                        score=score,
                        length_um=length_um,
                        min_clearance_um=min_clear,
                        n_bends=n_bends,
                    )
                )

    if not survivors:
        return RouteResult(
            candidate=None,
            n_candidates=n_candidates,
            n_clean=0,
            rejection_tallies=tallies,
        )

    best = min(survivors, key=lambda c: c.score)
    return RouteResult(
        candidate=best,
        n_candidates=n_candidates,
        n_clean=len(survivors),
        rejection_tallies=tallies,
    )


def shift_preserved_polys(
    polys: Sequence[gdstk.Polygon],
    dx: float,
    dy: float,
) -> list[gdstk.Polygon]:
    """Rigid XY translate for candidate placement shifts."""
    return translate_polygons(polys, dx, dy)
