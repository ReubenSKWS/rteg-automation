"""
Step 5 — MBE ground-side as a boolean plate merge (shared by both paths).

The ground side of an rteg is not a thin wire: the outer GSG ground pads, the
right-hand MBE filler plate, and the resonator's preserved ground connector are
all wide MBE bodies that belong to **one** ground net. This module fuses them
into a single body, optionally bridges gaps and connects the preserved metal,
then carves the DRC keepouts (signal/MTE, resonator MBE, release holes) out of
the fused body and verifies the result is one connected, clean ground plane.

The same pipeline serves the deterministic router (auto bridge + auto connector)
and the agentic experiment (agent-supplied bridge / connector rectangles). Pure
geometry reuses :mod:`route_primitives`; this module imports no pipeline modules
besides it, so it can be a dependency of both ``route_rteg`` and ``agentic``
without a cycle (``pads`` is duck-typed: any object exposing ``top_ground`` /
``bottom_ground`` / ``center_signal`` polygon lists).

## Why release holes are filtered to the resonator neighborhood
``BAW_ReF`` / ``BAW_CAV`` carry large pad-cavity and resonator-cavity outlines as
well as true release holes. The pad cavities sit *under* the GSG ground pads by
design; carving them out of the ground body would sever every pad from the
plate. Callers therefore pass only release holes near the resonator (see
``route_rteg`` / ``agentic.context``); this module trusts that filtering.

## Skip reasons (feasibility_precheck, before any boolean)
``top_ground_arm_missing``, ``bottom_ground_arm_missing``,
``filler_plate_not_found``, ``ground_pad_arm_not_in_cavity``,
``preserved_no_body_facing_edge``.
"""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import gdstk

from route_primitives import grow_polygon, min_spacing, nearest_points

Point = tuple[float, float]
Bbox = tuple[tuple[float, float], tuple[float, float]]


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class GroundMergeConfig:
    """Tunables for the plate-merge pipeline (layer fields are layermap names)."""

    target_route_layer: str = "BAW_MBE"
    signal_layer: str = "BAW_MTE"
    obstacle_layers: tuple[str, ...] = ("BAW_MTE",)
    release_hole_layers: tuple[str, ...] = ("BAW_ReF", "BAW_CAV")

    mbe_mte_spacing_um: float = 14.0
    release_hole_clearance_um: float = 6.0
    preserved_overlap_margin_um: float = 10.0
    connect_tolerance_um: float = 0.5
    boolean_precision: float = 1e-3

    # Exclude the die-frame MBE ring (large hollow rectangle) from plate
    # collection; the filler is identified by bbox match, not area, so this is
    # only a guard for the fallback path.
    frame_ring_min_area: float = 10_000.0
    # Drop carved fragments smaller than this (numerical slivers / pinched bits).
    min_fragment_area_um2: float = 5.0
    # Tolerance when matching the filler plate to ``assembly.mbe_filler_bbox``.
    filler_bbox_tol_um: float = 1.0


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #
@dataclass
class GroundPlates:
    """Labelled source plates for the ground body (each label may be >1 poly)."""

    top_ground: list[gdstk.Polygon] = field(default_factory=list)
    bottom_ground: list[gdstk.Polygon] = field(default_factory=list)
    filler: list[gdstk.Polygon] = field(default_factory=list)

    def all(self) -> list[gdstk.Polygon]:
        return [*self.top_ground, *self.bottom_ground, *self.filler]

    def plate_width_um(self) -> float:
        """Representative plate thickness — the median short bbox side of arms."""
        widths: list[float] = []
        for poly in (*self.top_ground, *self.bottom_ground):
            bb = poly.bounding_box()
            if bb is None:
                continue
            widths.append(min(bb[1][0] - bb[0][0], bb[1][1] - bb[0][1]))
        if not widths:
            return 14.0
        widths.sort()
        return widths[len(widths) // 2]


@dataclass
class UnionResult:
    body_polys: list[gdstk.Polygon]
    n_components: int
    component_bboxes: list[Bbox]


@dataclass(frozen=True)
class BridgeOp:
    """One axis-aligned rectangle added to fuse plates (45/90 edges only)."""

    bbox: Bbox

    def polygon(self) -> gdstk.Polygon:
        (x0, y0), (x1, y1) = self.bbox
        return gdstk.rectangle((x0, y0), (x1, y1))


@dataclass
class GroundVerifyReport:
    is_success: bool
    violations: list[str] = field(default_factory=list)
    split_locations: list[Bbox] = field(default_factory=list)
    pads_connected: set[str] = field(default_factory=set)
    preserved_connected: bool = False
    mbe_area_um2: float = 0.0
    ground_body_hash: str = "(empty)"

    def to_text(self) -> str:
        lines: list[str] = []
        lines.append(
            "GROUND VERIFIER: "
            + ("PASS — one clean connected ground body" if self.is_success else "NOT PASSING")
        )
        pads = ", ".join(sorted(self.pads_connected)) or "none"
        lines.append(f"pads connected: {pads}; preserved connected: {self.preserved_connected}")
        lines.append(f"ground MBE area: {self.mbe_area_um2:.0f} um^2; body hash {self.ground_body_hash}")
        if self.violations:
            lines.append(f"violations ({len(self.violations)}):")
            lines.extend(f"  - {v}" for v in self.violations)
        else:
            lines.append("violations: none")
        if self.split_locations:
            lines.append(f"severed fragments ({len(self.split_locations)}):")
            lines.extend(
                f"  - bbox [({b[0][0]:.1f}, {b[0][1]:.1f}) .. ({b[1][0]:.1f}, {b[1][1]:.1f})]"
                for b in self.split_locations
            )
        return "\n".join(lines)


@dataclass
class GroundMergeResult:
    plates: GroundPlates
    union: UnionResult
    bridges: list[BridgeOp]
    connector_rect: Bbox | None
    carved_body: list[gdstk.Polygon]
    report: GroundVerifyReport
    skip_reason: str | None = None

    @property
    def is_success(self) -> bool:
        return self.skip_reason is None and self.report.is_success


# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #
def _bbox_of(polys: Sequence[gdstk.Polygon]) -> Bbox | None:
    boxes = [bb for p in polys if (bb := p.bounding_box()) is not None]
    if not boxes:
        return None
    return (
        (min(b[0][0] for b in boxes), min(b[0][1] for b in boxes)),
        (max(b[1][0] for b in boxes), max(b[1][1] for b in boxes)),
    )


def _bbox_overlap(a: Bbox, b: Bbox) -> bool:
    (ax0, ay0), (ax1, ay1) = a
    (bx0, by0), (bx1, by1) = b
    return ax0 <= bx1 and bx0 <= ax1 and ay0 <= by1 and by0 <= ay1


def _union(
    polys: Sequence[gdstk.Polygon], config: GroundMergeConfig
) -> list[gdstk.Polygon]:
    if not polys:
        return []
    return list(gdstk.boolean(list(polys), [], "or", precision=config.boolean_precision))


def _touches(
    poly: gdstk.Polygon,
    targets: Sequence[gdstk.Polygon],
    config: GroundMergeConfig,
) -> bool:
    for t in targets:
        if gdstk.boolean(poly, t, "and", precision=config.boolean_precision):
            return True
        if min_spacing(poly, t) <= config.connect_tolerance_um:
            return True
    return False


def _body_hash(polys: Sequence[gdstk.Polygon]) -> str:
    if not polys:
        return "(empty)"
    canonical = sorted(
        tuple((round(x, 2), round(y, 2)) for x, y in p.points) for p in polys
    )
    return hashlib.sha256(repr(canonical).encode()).hexdigest()[:12]


# --------------------------------------------------------------------------- #
# Pipeline stages
# --------------------------------------------------------------------------- #
def collect_ground_plates(
    assembly: Any,
    layermap: Any,
    pads: Any,
    config: GroundMergeConfig,
) -> GroundPlates:
    """
    Labelled ground plates: top/bottom GSG ground arms + the MBE filler plate.

    Arms come from the classified GSG pads (MBE layer; falls back to all pad
    polys when pad metal carries unexpected layer numbers). The filler is the
    flattened-frame MBE polygon whose bbox matches ``assembly.mbe_filler_bbox``
    — this excludes the die-frame ring and resonator MBE without an area guess.
    """
    mbe_pair = layermap.pair(config.target_route_layer)

    def _arms(group: Sequence[gdstk.Polygon]) -> list[gdstk.Polygon]:
        mbe = [p for p in group if (p.layer, p.datatype) == mbe_pair]
        return mbe if mbe else list(group)

    top = _arms(pads.top_ground)
    bottom = _arms(pads.bottom_ground)

    (fx0, fy0), (fx1, fy1) = assembly.mbe_filler_bbox
    tol = config.filler_bbox_tol_um
    filler: list[gdstk.Polygon] = []
    for poly in assembly.flatten().polygons:
        if (poly.layer, poly.datatype) != mbe_pair:
            continue
        bb = poly.bounding_box()
        if bb is None:
            continue
        if (
            abs(bb[0][0] - fx0) <= tol
            and abs(bb[0][1] - fy0) <= tol
            and abs(bb[1][0] - fx1) <= tol
            and abs(bb[1][1] - fy1) <= tol
        ):
            filler.append(poly)

    return GroundPlates(top_ground=top, bottom_ground=bottom, filler=filler)


def feasibility_precheck(
    plates: GroundPlates,
    preserved: Sequence[gdstk.Polygon],
    assembly: Any,
    config: GroundMergeConfig,
) -> str | None:
    """
    Cheap structural validation before any boolean. Returns a named skip reason
    or ``None`` when the merge is geometrically possible.
    """
    if not plates.top_ground:
        return "top_ground_arm_missing"
    if not plates.bottom_ground:
        return "bottom_ground_arm_missing"
    if not plates.filler:
        return "filler_plate_not_found"

    cavity = assembly.inner_die_frame_bbox
    for arm in (plates.top_ground, plates.bottom_ground):
        bb = _bbox_of(arm)
        if bb is None or not _bbox_overlap(bb, cavity):
            return "ground_pad_arm_not_in_cavity"

    if not preserved:
        return "preserved_no_body_facing_edge"
    pres_bb = _bbox_of(preserved)
    filler_bb = _bbox_of(plates.filler)
    # Preserved must present a face toward the body (its left/min-x edge sits at
    # or left of the filler's right edge, i.e. there is room to fuse them).
    if pres_bb is None or filler_bb is None or pres_bb[0][0] > filler_bb[1][0]:
        return "preserved_no_body_facing_edge"
    return None


def union_ground_body(
    plates: Sequence[gdstk.Polygon], config: GroundMergeConfig
) -> UnionResult:
    body = _union(plates, config)
    boxes = [bb for p in body if (bb := p.bounding_box()) is not None]
    return UnionResult(body_polys=body, n_components=len(body), component_bboxes=boxes)


def bridge_gap(
    body: Sequence[gdstk.Polygon],
    rect: Bbox,
    config: GroundMergeConfig,
) -> list[gdstk.Polygon]:
    """Union one axis-aligned bridge rectangle into the body and re-union."""
    (x0, y0), (x1, y1) = rect
    bridge = gdstk.rectangle((x0, y0), (x1, y1))
    return _union([*body, bridge], config)


def _l_bridge_rects(a: Bbox, b: Bbox, width: float) -> list[Bbox]:
    """Axis-aligned L (or single rect) joining the centers of two bboxes."""
    acx = (a[0][0] + a[1][0]) / 2.0
    acy = (a[0][1] + a[1][1]) / 2.0
    bcx = (b[0][0] + b[1][0]) / 2.0
    bcy = (b[0][1] + b[1][1]) / 2.0
    half = width / 2.0
    rects: list[Bbox] = []
    # horizontal leg at acy from acx -> bcx
    hx0, hx1 = sorted((acx, bcx))
    rects.append(((hx0, acy - half), (hx1, acy + half)))
    # vertical leg at bcx from acy -> bcy
    vy0, vy1 = sorted((acy, bcy))
    rects.append(((bcx - half, vy0), (bcx + half, vy1)))
    return rects


def auto_bridge_gaps(
    body: Sequence[gdstk.Polygon],
    plate_width: float,
    config: GroundMergeConfig,
    *,
    max_bridges: int = 6,
) -> tuple[list[gdstk.Polygon], list[BridgeOp]]:
    """
    Deterministically fuse a multi-component body by bridging the closest
    component pair repeatedly with axis-aligned (L) rectangles.
    """
    current = list(body)
    bridges: list[BridgeOp] = []
    for _ in range(max_bridges):
        if len(current) <= 1:
            break
        # closest component pair by boundary distance
        best: tuple[float, int, int] | None = None
        for i in range(len(current)):
            for j in range(i + 1, len(current)):
                d = min_spacing(current[i], current[j])
                if best is None or d < best[0]:
                    best = (d, i, j)
        if best is None:
            break
        _d, i, j = best
        bi = current[i].bounding_box()
        bj = current[j].bounding_box()
        if bi is None or bj is None:
            break
        for rect in _l_bridge_rects(bi, bj, plate_width):
            current = bridge_gap(current, rect, config)
            bridges.append(BridgeOp(bbox=rect))
    return current, bridges


def auto_connect_preserved(
    body: Sequence[gdstk.Polygon],
    preserved: Sequence[gdstk.Polygon],
    config: GroundMergeConfig,
) -> tuple[list[gdstk.Polygon], Bbox | None]:
    """
    Fuse the preserved metal into the body. If it already touches the body no
    connector is needed; otherwise add a rectangle from the preserved
    body-facing edge to the nearest body component (v1 axis-aligned rule).
    """
    body = list(body)
    if not preserved:
        return body, None
    pres_union = _union(preserved, config)
    if any(_touches(p, body, config) for p in pres_union):
        return _union([*body, *preserved], config), None

    # Connector: span preserved Y extent, extend toward the nearest body comp.
    pres_bb = _bbox_of(pres_union)
    body_bb = _bbox_of(body)
    if pres_bb is None or body_bb is None:
        return _union([*body, *preserved], config), None
    pa, pb = _closest_points(pres_union, body)
    x0, x1 = sorted((pa[0], pb[0]))
    rect: Bbox = ((x0, pres_bb[0][1]), (x1, pres_bb[1][1]))
    fused = bridge_gap(body, rect, config)
    return _union([*fused, *preserved], config), rect


def connect_preserved(
    body: Sequence[gdstk.Polygon],
    preserved: Sequence[gdstk.Polygon],
    connector_rect: Bbox | None,
    config: GroundMergeConfig,
) -> list[gdstk.Polygon]:
    """Union preserved metal (and an explicit connector rect) into the body."""
    polys = [*body, *preserved]
    if connector_rect is not None:
        (x0, y0), (x1, y1) = connector_rect
        polys.append(gdstk.rectangle((x0, y0), (x1, y1)))
    return _union(polys, config)


def _closest_points(
    a: Sequence[gdstk.Polygon], b: Sequence[gdstk.Polygon]
) -> tuple[Point, Point]:
    best: tuple[float, Point, Point] | None = None
    for pa in a:
        for pb in b:
            ua, ub = nearest_points(pa, pb)
            d = (ua[0] - ub[0]) ** 2 + (ua[1] - ub[1]) ** 2
            if best is None or d < best[0]:
                best = (d, ua, ub)
    if best is None:
        return (0.0, 0.0), (0.0, 0.0)
    return best[1], best[2]


def carve_ground(
    body: Sequence[gdstk.Polygon],
    *,
    spacing_obstacles: Sequence[gdstk.Polygon],
    release_holes: Sequence[gdstk.Polygon],
    config: GroundMergeConfig,
) -> list[gdstk.Polygon]:
    """
    Subtract grown keepouts from the fused body: signal/MTE + resonator MBE at
    ``mbe_mte_spacing_um``, release holes at ``release_hole_clearance_um``.
    Drops carved fragments below ``min_fragment_area_um2``.
    """
    if not body:
        return []
    keepouts: list[gdstk.Polygon] = []
    for poly in spacing_obstacles:
        keepouts.extend(grow_polygon(poly, config.mbe_mte_spacing_um))
    for poly in release_holes:
        keepouts.extend(grow_polygon(poly, config.release_hole_clearance_um))
    if not keepouts:
        carved = list(body)
    else:
        ko = _union(keepouts, config)
        carved = list(
            gdstk.boolean(list(body), ko, "not", precision=config.boolean_precision)
        )
    return [p for p in carved if abs(p.area()) >= config.min_fragment_area_um2]


def verify_ground(
    carved: Sequence[gdstk.Polygon],
    *,
    top_ground: Sequence[gdstk.Polygon],
    bottom_ground: Sequence[gdstk.Polygon],
    preserved: Sequence[gdstk.Polygon],
    spacing_obstacles: Sequence[gdstk.Polygon],
    release_holes: Sequence[gdstk.Polygon],
    config: GroundMergeConfig,
) -> GroundVerifyReport:
    """
    Grade the carved body: one connected component must touch both ground pads
    and the preserved metal, with no net-aware DRC violation. Severed fragments
    are reported (informational), not counted as DRC failures.
    """
    report = GroundVerifyReport(is_success=False)
    report.mbe_area_um2 = sum(abs(p.area()) for p in carved)
    report.ground_body_hash = _body_hash(carved)

    if not carved:
        report.violations.append("carve produced no ground body")
        return report

    # Connectivity: find a component touching all of top, bottom, preserved.
    primary_idx: int | None = None
    for i, comp in enumerate(carved):
        t = _touches(comp, top_ground, config)
        b = _touches(comp, bottom_ground, config)
        p = _touches(comp, preserved, config)
        if t:
            report.pads_connected.add("top_ground")
        if b:
            report.pads_connected.add("bottom_ground")
        if p:
            report.preserved_connected = True
        if t and b and p and primary_idx is None:
            primary_idx = i

    if primary_idx is None:
        report.violations.append(
            "no single ground component touches both pads and the preserved metal "
            f"(top={'top_ground' in report.pads_connected}, "
            f"bottom={'bottom_ground' in report.pads_connected}, "
            f"preserved={report.preserved_connected})"
        )

    # Severed fragments = every component other than the primary one.
    for i, comp in enumerate(carved):
        if i == primary_idx:
            continue
        bb = comp.bounding_box()
        if bb is not None:
            report.split_locations.append(bb)

    # Net-aware DRC on the carved result.
    for poly in carved:
        for obs in spacing_obstacles:
            d = min_spacing(poly, obs)
            if d < config.mbe_mte_spacing_um - 1e-6:
                bb = obs.bounding_box()
                loc = f"({bb[0][0]:.1f}, {bb[0][1]:.1f})" if bb else "?"
                report.violations.append(
                    f"ground spacing {d:.1f}um < {config.mbe_mte_spacing_um:.0f}um "
                    f"vs other-net metal near {loc}"
                )
                break
        for hole in release_holes:
            d = min_spacing(poly, hole)
            if d < config.release_hole_clearance_um - 1e-6:
                bb = hole.bounding_box()
                loc = f"({bb[0][0]:.1f}, {bb[0][1]:.1f})" if bb else "?"
                report.violations.append(
                    f"ground clearance {d:.1f}um < {config.release_hole_clearance_um:.0f}um "
                    f"vs release hole near {loc}"
                )
                break

    report.is_success = primary_idx is not None and not report.violations
    return report


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run_ground_merge(
    *,
    assembly: Any,
    layermap: Any,
    pads: Any,
    preserved: Sequence[gdstk.Polygon],
    spacing_obstacles: Sequence[gdstk.Polygon],
    release_holes: Sequence[gdstk.Polygon],
    config: GroundMergeConfig,
    bridges: Sequence[Bbox] | None = None,
    connector_rect: Bbox | None = None,
) -> GroundMergeResult:
    """
    Full plate-merge for one resonator.

    Deterministic callers pass ``bridges=None`` / ``connector_rect=None`` to get
    automatic bridging + connector. Agentic callers pass explicit rectangles the
    agent chose. Geometry inputs (preserved, obstacles, release holes) are built
    by the caller in RTEG world space; release holes must already be limited to
    the resonator neighborhood (see module docstring).
    """
    plates = collect_ground_plates(assembly, layermap, pads, config)
    skip = feasibility_precheck(plates, preserved, assembly, config)
    if skip is not None:
        empty = UnionResult(body_polys=[], n_components=0, component_bboxes=[])
        return GroundMergeResult(
            plates=plates,
            union=empty,
            bridges=[],
            connector_rect=None,
            carved_body=[],
            report=GroundVerifyReport(is_success=False, violations=[skip]),
            skip_reason=skip,
        )

    union = union_ground_body(plates.all(), config)
    body = union.body_polys
    applied_bridges: list[BridgeOp] = []

    if bridges:
        for rect in bridges:
            body = bridge_gap(body, rect, config)
            applied_bridges.append(BridgeOp(bbox=rect))
    elif union.n_components > 1:
        body, applied_bridges = auto_bridge_gaps(
            body, plates.plate_width_um(), config
        )

    if connector_rect is not None:
        body = connect_preserved(body, preserved, connector_rect, config)
        used_connector = connector_rect
    else:
        body, used_connector = auto_connect_preserved(body, preserved, config)

    carved = carve_ground(
        body,
        spacing_obstacles=spacing_obstacles,
        release_holes=release_holes,
        config=config,
    )
    report = verify_ground(
        carved,
        top_ground=plates.top_ground,
        bottom_ground=plates.bottom_ground,
        preserved=preserved,
        spacing_obstacles=spacing_obstacles,
        release_holes=release_holes,
        config=config,
    )
    return GroundMergeResult(
        plates=plates,
        union=union,
        bridges=applied_bridges,
        connector_rect=used_connector,
        carved_body=carved,
        report=report,
    )
