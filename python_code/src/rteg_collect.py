"""
Step 5.1 ΓÇö Collect framed-resonator geometry into typed roles.

Pulls polygons from a step-4 ``RtegFrameAssembly`` by **layermap name** (no
hardcoded layer numbers) and splits them into the sets downstream booleans need:

- **ground plates** ΓÇö GSG pad / arm MBE + the step-4 width filler (not resonator)
- **preserved metal** ΓÇö filter interconnect MBE/MTE from the connect cells
- **release holes** ΓÇö ``BAW_ReF`` / ``BAW_CAV`` near the resonator
- **inner frame boundary** ΓÇö inner cavity rectangle + die-frame MBE ring

Reference counts for KB331 resonator **index 05** (shunt):

| Role | Count |
|------|------:|
| ground plates (5 pad + 1 filler) | 6 |
| preserved MBE | 1 |
| preserved MTE | 2 |
| release holes (ReF + CAV near resonator) | 2 + 7 |
| frame boundary (cavity + ring) | 2 |
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import gdstk

from layermap import LayerMap
from prep_resonator_ppd import (
    ppd_pad_keepout_polys,
    resonator_metal_polys,
    resonator_release_hole_polys,
)
from prep_rteg_frame import RtegFrameAssembly
from rteg_orientation import OrientationAnalysis, analyze_orientation
from rteg_utils import polys_bbox, resonator_world_bbox, split_by_y_gaps
from separate import IdentificationResult, Resonator

Point = tuple[float, float]
Bbox = tuple[tuple[float, float], tuple[float, float]]


@dataclass(frozen=True)
class RtegCollectConfig:
    """Layer names and margins ΓÇö resolved through ``LayerMap`` at runtime."""

    mbe_layer: str = "BAW_MBE"
    mte_layer: str = "BAW_MTE"
    release_hole_layers: tuple[str, ...] = ("BAW_ReF", "BAW_CAV")
    boundary_layer: str = "BAW_EDGE"

    preserved_overlap_margin_um: float = 10.0
    collar_association_gap_um: float = 35.0
    stadium_collar_area_um2: float = 2500.0
    max_edge_collar_area_um2: float = 800.0
    min_body_interface_collar_area_um2: float = 100.0
    max_body_interface_collar_area_um2: float = 2000.0
    release_hole_margin_um: float = 10.0
    filler_bbox_tol_um: float = 1.0
    frame_ring_min_area_um2: float = 10_000.0
    min_polygon_area_um2: float = 1.0


@dataclass
class TaggedPolygon:
    """One polygon with a human-readable role label and layermap layer name."""

    label: str
    layer_name: str
    polygon: gdstk.Polygon

    @property
    def bbox(self) -> Bbox | None:
        return self.polygon.bounding_box()

    @property
    def area_um2(self) -> float:
        return abs(self.polygon.area())

    def summary(self) -> dict[str, object]:
        bb = self.bbox
        return {
            "label": self.label,
            "layer": self.layer_name,
            "vertices": len(self.polygon.points),
            "area_um2": round(self.area_um2, 1),
            "bbox": (
                (round(bb[0][0], 1), round(bb[0][1], 1)),
                (round(bb[1][0], 1), round(bb[1][1], 1)),
            )
            if bb
            else None,
        }


@dataclass
class GroundPlates:
    """GSG ground-side MBE plates before net classification (5.2)."""

    top: list[TaggedPolygon] = field(default_factory=list)
    center: list[TaggedPolygon] = field(default_factory=list)
    bottom: list[TaggedPolygon] = field(default_factory=list)
    filler: list[TaggedPolygon] = field(default_factory=list)

    def all_items(self) -> list[TaggedPolygon]:
        return [*self.top, *self.center, *self.bottom, *self.filler]

    def groups(self) -> dict[str, list[TaggedPolygon]]:
        return {
            "top_ground": self.top,
            "center_node": self.center,
            "bottom_ground": self.bottom,
            "filler_plate": self.filler,
        }


@dataclass
class PreservedMetal:
    """Filter interconnect metal carried into the RTEG world."""

    mbe: list[TaggedPolygon] = field(default_factory=list)
    mte: list[TaggedPolygon] = field(default_factory=list)

    def groups(self) -> dict[str, list[TaggedPolygon]]:
        return {"preserved_mbe": self.mbe, "preserved_mte": self.mte}


@dataclass
class ReleaseHoles:
    """Release-hole outlines near the resonator (not global pad cavities)."""

    by_layer: dict[str, list[TaggedPolygon]] = field(default_factory=dict)

    def all_items(self) -> list[TaggedPolygon]:
        out: list[TaggedPolygon] = []
        for items in self.by_layer.values():
            out.extend(items)
        return out

    def groups(self) -> dict[str, list[TaggedPolygon]]:
        return dict(self.by_layer)


@dataclass
class InnerFrameBoundary:
    """Inner die cavity (routable envelope) and the frame MBE ring polygon."""

    cavity: TaggedPolygon
    ring: TaggedPolygon | None = None

    def groups(self) -> dict[str, list[TaggedPolygon]]:
        items = [self.cavity]
        if self.ring is not None:
            items.append(self.ring)
        return {"inner_cavity": [self.cavity], "frame_ring": [self.ring] if self.ring else []}


@dataclass
class RtegGeometryRoles:
    """All step-5.1 geometry roles for one resonator."""

    index: int
    inst_name: str
    ground_plates: GroundPlates
    preserved: PreservedMetal
    release_holes: ReleaseHoles
    frame_boundary: InnerFrameBoundary
    resonator_body_mte: list[gdstk.Polygon] = field(default_factory=list)
    resonator_body_mbe: list[gdstk.Polygon] = field(default_factory=list)

    def group_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for name, items in self.ground_plates.groups().items():
            counts[name] = len(items)
        for name, items in self.preserved.groups().items():
            counts[name] = len(items)
        for name, items in self.release_holes.groups().items():
            counts[name] = len(items)
        for name, items in self.frame_boundary.groups().items():
            counts[name] = len(items)
        return counts


# --------------------------------------------------------------------------- #
# Coordinate helpers
# --------------------------------------------------------------------------- #
def _ppd_world_origin(assembly: RtegFrameAssembly) -> Point:
    ppd = assembly.ppd_assembly
    return (
        assembly.assembly_origin[0] + ppd.ppd_origin[0],
        assembly.assembly_origin[1] + ppd.ppd_origin[1],
    )


def _resonator_shift(res: Resonator, assembly: RtegFrameAssembly) -> Point:
    """Delta from filter placement to RTEG placement for ``resonator_metal_polys``."""
    ppd = assembly.ppd_assembly
    rteg_origin = (
        assembly.assembly_origin[0]
        + ppd.resonator_origin[0]
        + assembly.resonator_frame_shift[0],
        assembly.assembly_origin[1]
        + ppd.resonator_origin[1]
        + assembly.resonator_frame_shift[1],
    )
    return (rteg_origin[0] - res.origin[0], rteg_origin[1] - res.origin[1])


def _resonator_rteg_bbox(
    res: Resonator, assembly: RtegFrameAssembly
) -> Bbox:
    shift = _resonator_shift(res, assembly)
    metal = resonator_metal_polys(res, shift[0], shift[1])
    boxes = [bb for p in metal if (bb := p.bounding_box()) is not None]
    if not boxes:
        raise ValueError(f"Resonator {res.inst_name} has no metal bounding box in RTEG")
    return (
        (min(b[0][0] for b in boxes), min(b[0][1] for b in boxes)),
        (max(b[1][0] for b in boxes), max(b[1][1] for b in boxes)),
    )


def _expand_bbox(bbox: Bbox, margin: float) -> Bbox:
    (x0, y0), (x1, y1) = bbox
    return (x0 - margin, y0 - margin), (x1 + margin, y1 + margin)


def _bbox_overlap(a: Bbox, b: Bbox) -> bool:
    (ax0, ay0), (ax1, ay1) = a
    (bx0, by0), (bx1, by1) = b
    return ax0 <= bx1 and bx0 <= ax1 and ay0 <= by1 and by0 <= ay1


def _filter_to_rteg_world(
    polys: Sequence[gdstk.Polygon],
    res: Resonator,
    assembly: RtegFrameAssembly,
) -> list[gdstk.Polygon]:
    dx, dy = _resonator_shift(res, assembly)
    return [
        gdstk.Polygon(
            [(x + dx, y + dy) for x, y in p.points],
            layer=p.layer,
            datatype=p.datatype,
        )
        for p in polys
    ]


def _find_connect_cell(
    identification: IdentificationResult, suffix: str
) -> gdstk.Cell | None:
    parent = identification.parent
    for name in (f"{parent}_{suffix}", f"{parent}_connect_backup"):
        for cell in identification.library.cells:
            if cell.name == name:
                return cell
    return None


def _cluster_pad_polys_by_y(
    polys: Sequence[gdstk.Polygon],
    *,
    layer_name: str,
    label_prefix: str,
) -> tuple[list[TaggedPolygon], list[TaggedPolygon], list[TaggedPolygon]]:
    """Split pad polygons into top / center / bottom bands by Y-centroid gaps."""
    top_polys, center_polys, bottom_polys = split_by_y_gaps(polys)
    if not center_polys and not bottom_polys:
        tagged = [
            TaggedPolygon(f"{label_prefix}[{i}]", layer_name, p)
            for i, p in enumerate(top_polys)
        ]
        return tagged, [], []

    def tag_group(group: Sequence[gdstk.Polygon], band: str) -> list[TaggedPolygon]:
        return [
            TaggedPolygon(f"{label_prefix}_{band}[{i}]", layer_name, p)
            for i, p in enumerate(group)
        ]

    return (
        tag_group(top_polys, "top"),
        tag_group(center_polys, "center"),
        tag_group(bottom_polys, "bottom"),
    )


# --------------------------------------------------------------------------- #
# Public collectors
# --------------------------------------------------------------------------- #
def collect_ground_plates(
    assembly: RtegFrameAssembly,
    res: Resonator,
    layermap: LayerMap,
    config: RtegCollectConfig | None = None,
) -> GroundPlates:
    """
    GSG pad / arm MBE polygons and the step-4 width filler plate.

    Excludes resonator MBE (bbox overlap with the placed resonator metal).
  Net assignment (signal vs ground) is step 5.2; here we only split by Y band
    for display.
    """
    cfg = config or RtegCollectConfig()
    mbe_pair = layermap.pair(cfg.mbe_layer)
    layer_name = cfg.mbe_layer

    res_bb = _resonator_rteg_bbox(res, assembly)
    ppd_origin = _ppd_world_origin(assembly)
    pad_polys: list[gdstk.Polygon] = []
    for poly in ppd_pad_keepout_polys(assembly.ppd_assembly.top_cell, ppd_origin):
        if (poly.layer, poly.datatype) != mbe_pair:
            continue
        if abs(poly.area()) < cfg.min_polygon_area_um2:
            continue
        bb = poly.bounding_box()
        if bb is not None and _bbox_overlap(bb, res_bb):
            continue
        pad_polys.append(poly)

    top, center, bottom = _cluster_pad_polys_by_y(
        pad_polys, layer_name=layer_name, label_prefix="pad"
    )

    (fx0, fy0), (fx1, fy1) = assembly.mbe_filler_bbox
    tol = cfg.filler_bbox_tol_um
    filler: list[TaggedPolygon] = []
    for i, poly in enumerate(
        p
        for p in assembly.flatten().polygons
        if (p.layer, p.datatype) == mbe_pair
    ):
        bb = poly.bounding_box()
        if bb is None:
            continue
        if (
            abs(bb[0][0] - fx0) <= tol
            and abs(bb[0][1] - fy0) <= tol
            and abs(bb[1][0] - fx1) <= tol
            and abs(bb[1][1] - fy1) <= tol
        ):
            filler.append(TaggedPolygon(f"filler[{i}]", layer_name, poly))

    return GroundPlates(top=top, center=center, bottom=bottom, filler=filler)


def _bbox_gap(a: Bbox, b: Bbox) -> float:
    (ax0, ay0), (ax1, ay1) = a
    (bx0, by0), (bx1, by1) = b
    gap_x = max(0.0, max(ax0, bx0) - min(ax1, bx1))
    gap_y = max(0.0, max(ay0, by0) - min(ay1, by1))
    return max(gap_x, gap_y)


def polys_touch(
    poly_a: gdstk.Polygon,
    poly_b: gdstk.Polygon,
    *,
    precision: float = 1e-3,
    min_overlap_um2: float = 0.1,
) -> bool:
    """True when two polygons share a measurable boolean overlap."""
    inter = gdstk.boolean(poly_a, poly_b, "and", precision=precision)
    if not inter:
        return False
    return sum(abs(p.area()) for p in inter) >= min_overlap_um2


def polys_associated(
    poly_a: gdstk.Polygon,
    poly_b: gdstk.Polygon,
    *,
    gap_um: float,
    precision: float = 1e-3,
) -> bool:
    """True when two polygons touch or their bboxes are within ``gap_um``."""
    bb_a, bb_b = poly_a.bounding_box(), poly_b.bounding_box()
    if bb_a is None or bb_b is None:
        return False
    if _bbox_gap(bb_a, bb_b) <= gap_um:
        return True
    return bool(gdstk.boolean(poly_a, poly_b, "and", precision=precision))


def _polygon_key(poly: gdstk.Polygon) -> tuple[float, float, float, float, float]:
    bb = poly.bounding_box()
    if bb is None:
        return (0.0, 0.0, 0.0, 0.0, 0.0)
    (x0, y0), (x1, y1) = bb
    return (round(abs(poly.area()), 3), round(x0, 3), round(y0, 3), round(x1, 3), round(y1, 3))


def _associate_stadium_mte_collars(
    seeds: list[gdstk.Polygon],
    candidates: Sequence[gdstk.Polygon],
    cfg: RtegCollectConfig,
) -> list[gdstk.Polygon]:
    """
    When only a stadium-sized MTE piece is in ``seeds``, add nearby edge tabs.

    Edge collars can sit just outside the resonator bbox window (~31 ┬╡m from the
    stadium in KB331) while still belonging to the same resonator interconnect.
    """
    large = [p for p in seeds if abs(p.area()) >= cfg.stadium_collar_area_um2]
    small = [p for p in seeds if abs(p.area()) < cfg.stadium_collar_area_um2]
    if len(large) != 1 or small:
        return list(seeds)

    anchor_bb = _expand_bbox(large[0].bounding_box(), cfg.collar_association_gap_um)  # type: ignore[arg-type]
    seen = {_polygon_key(p) for p in seeds}
    collected = list(seeds)
    for poly in candidates:
        key = _polygon_key(poly)
        if key in seen:
            continue
        bb = poly.bounding_box()
        if bb is None or not _bbox_overlap(bb, anchor_bb):
            continue
        if abs(poly.area()) >= cfg.max_edge_collar_area_um2:
            continue
        if not polys_touch(poly, large[0], precision=1e-3):
            continue
        seen.add(key)
        collected.append(poly)
    return collected


def _stadium_mte_polys(
    mte_polys: Sequence[gdstk.Polygon], cfg: RtegCollectConfig
) -> list[gdstk.Polygon]:
    return [p for p in mte_polys if abs(p.area()) >= cfg.stadium_collar_area_um2]


def _has_stadium_touching_collar(
    mte_polys: Sequence[gdstk.Polygon], cfg: RtegCollectConfig
) -> bool:
    """True when a non-stadium preserved piece boolean-touches the stadium shell."""
    stadiums = _stadium_mte_polys(mte_polys, cfg)
    if not stadiums:
        return False
    stadium_keys = {_polygon_key(p) for p in stadiums}
    for poly in mte_polys:
        if _polygon_key(poly) in stadium_keys:
            continue
        if abs(poly.area()) >= cfg.stadium_collar_area_um2:
            continue
        if any(
            polys_touch(poly, stadium, precision=1e-3) for stadium in stadiums
        ):
            return True
    return False


def _augment_preserved_mte_interface_collars(
    mte_polys: list[gdstk.Polygon],
    body_mte_polys: Sequence[gdstk.Polygon],
    cfg: RtegCollectConfig,
) -> list[gdstk.Polygon]:
    """
  Add the body-side collar tab when connectMTE yields only the stadium shell.

    Series resonators often show a closed stadium outline plus a separate collar
    polygon in layout. The collar boolean-touches the body stadium and the filter
    connectMTE stadium at the interconnect mouth.
    """
    stadiums = _stadium_mte_polys(mte_polys, cfg)
    if not stadiums or _has_stadium_touching_collar(mte_polys, cfg):
        return mte_polys

    body_significant = [
        p
        for p in body_mte_polys
        if abs(p.area()) >= cfg.min_body_interface_collar_area_um2
    ]
    if len(body_significant) < 2:
        return mte_polys

    body_stadium = max(body_significant, key=lambda p: abs(p.area()))
    seen = {_polygon_key(p) for p in mte_polys}
    candidates = [
        p
        for p in body_significant
        if p is not body_stadium
        and abs(p.area()) <= cfg.max_body_interface_collar_area_um2
        and _polygon_key(p) not in seen
        and polys_touch(p, body_stadium, precision=1e-3)
        and any(polys_touch(p, stadium, precision=1e-3) for stadium in stadiums)
    ]
    if not candidates:
        return mte_polys
    collar = min(candidates, key=lambda p: abs(p.area()))
    return [*mte_polys, collar]


def preserved_collars_at_shift(
    res: Resonator,
    identification: IdentificationResult,
    layermap: LayerMap,
    *,
    shift: Point,
    config: RtegCollectConfig | None = None,
) -> tuple[list[gdstk.Polygon], list[gdstk.Polygon]]:
    """
    Preserved filter MTE / MBE collar polygons translated by ``shift``.

    Selects ``{parent}_connectMTE`` / ``{parent}_connectMBE`` polygons that
    overlap the resonator window (in filter coordinates), then offsets them by
    ``shift`` ΓÇö the delta from filter placement to the target placement. Shared
    by step 3 (PPD-space orientation) and step 5.1 (RTEG-world collection), so
    both see the same collar geometry. Returns ``(mte_polys, mbe_polys)``.
    """
    cfg = config or RtegCollectConfig()
    filter_bb = _expand_bbox(
        resonator_world_bbox(res), cfg.preserved_overlap_margin_um
    )
    dx, dy = shift

    out: dict[str, list[gdstk.Polygon]] = {cfg.mte_layer: [], cfg.mbe_layer: []}
    mte_candidates: list[gdstk.Polygon] = []
    mte_seeds_filter: list[gdstk.Polygon] = []
    for suffix, layer_name in (
        ("connectMTE", cfg.mte_layer),
        ("connectMBE", cfg.mbe_layer),
    ):
        cell = _find_connect_cell(identification, suffix)
        if cell is None:
            continue
        pair = layermap.pair(layer_name)
        for poly in cell.flatten().polygons:
            if (poly.layer, poly.datatype) != pair:
                continue
            if abs(poly.area()) < cfg.min_polygon_area_um2:
                continue
            if layer_name == cfg.mte_layer:
                mte_candidates.append(poly)
            bb = poly.bounding_box()
            if bb is None or not _bbox_overlap(bb, filter_bb):
                continue
            shifted = gdstk.Polygon(
                [(x + dx, y + dy) for x, y in poly.points],
                layer=poly.layer,
                datatype=poly.datatype,
            )
            out[layer_name].append(shifted)
            if layer_name == cfg.mte_layer:
                mte_seeds_filter.append(poly)

    if mte_candidates and mte_seeds_filter:
        associated = _associate_stadium_mte_collars(
            mte_seeds_filter, mte_candidates, cfg
        )
        if len(associated) > len(mte_seeds_filter):
            out[cfg.mte_layer] = [
                gdstk.Polygon(
                    [(x + dx, y + dy) for x, y in p.points],
                    layer=p.layer,
                    datatype=p.datatype,
                )
                for p in associated
            ]

    return out[cfg.mte_layer], out[cfg.mbe_layer]


def collect_preserved_metal(
    assembly: RtegFrameAssembly,
    res: Resonator,
    identification: IdentificationResult,
    layermap: LayerMap,
    config: RtegCollectConfig | None = None,
) -> PreservedMetal:
    """
    Preserved filter interconnect MBE/MTE overlapping the resonator window.

    Source cells: ``{parent}_connectMBE`` / ``{parent}_connectMTE`` (with
    ``connect_backup`` fallback), filtered in filter coordinates then translated
    into RTEG world space via the same shift as ``resonator_metal_polys``.
    """
    cfg = config or RtegCollectConfig()
    shift = _resonator_shift(res, assembly)
    mte_polys, mbe_polys = preserved_collars_at_shift(
        res,
        identification,
        layermap,
        shift=shift,
        config=cfg,
    )
    n_connect = len(mte_polys)
    body_mte = collect_resonator_body_mte(res, assembly, layermap, cfg)
    mte_polys = _augment_preserved_mte_interface_collars(mte_polys, body_mte, cfg)
    return PreservedMetal(
        mbe=[
            TaggedPolygon(f"preserved_{cfg.mbe_layer}[{i}]", cfg.mbe_layer, p)
            for i, p in enumerate(mbe_polys)
        ],
        mte=[
            TaggedPolygon(
                (
                    f"preserved_{cfg.mte_layer}[{i}]"
                    if i < n_connect
                    else f"preserved_{cfg.mte_layer}_interface[{i - n_connect}]"
                ),
                cfg.mte_layer,
                p,
            )
            for i, p in enumerate(mte_polys)
        ],
    )


def preserved_mte_overlap_with_body(
    preserved_mte: gdstk.Polygon,
    body_mte_polys: Sequence[gdstk.Polygon],
    *,
    precision: float = 1e-3,
) -> float:
    """Shared area between one preserved MTE collar and resonator-body MTE."""
    overlap = 0.0
    for body in body_mte_polys:
        inter = gdstk.boolean(preserved_mte, body, "and", precision=precision)
        if inter:
            overlap = max(overlap, sum(abs(p.area()) for p in inter))
    return overlap


def preserved_mbe_overlap_with_body(
    preserved_mbe: gdstk.Polygon,
    body_mbe_polys: Sequence[gdstk.Polygon],
    *,
    precision: float = 1e-3,
) -> float:
    """Shared area between one preserved MBE collar and resonator-body MBE."""
    overlap = 0.0
    for body in body_mbe_polys:
        inter = gdstk.boolean(preserved_mbe, body, "and", precision=precision)
        if inter:
            overlap = max(overlap, sum(abs(p.area()) for p in inter))
    return overlap


def collect_resonator_body_mte(
    res: Resonator,
    assembly: RtegFrameAssembly,
    layermap: LayerMap,
    config: RtegCollectConfig | None = None,
) -> list[gdstk.Polygon]:
    """Resonator-master MTE polygons in RTEG world space (not filter interconnect)."""
    cfg = config or RtegCollectConfig()
    dx, dy = _resonator_shift(res, assembly)
    mte_pair = layermap.pair(cfg.mte_layer)
    return [
        poly
        for poly in resonator_metal_polys(res, dx, dy)
        if (poly.layer, poly.datatype) == mte_pair
    ]


def collect_resonator_body_mbe(
    res: Resonator,
    assembly: RtegFrameAssembly,
    layermap: LayerMap,
    config: RtegCollectConfig | None = None,
) -> list[gdstk.Polygon]:
    """Resonator-master MBE polygons in RTEG world space (not filter interconnect)."""
    cfg = config or RtegCollectConfig()
    dx, dy = _resonator_shift(res, assembly)
    mbe_pair = layermap.pair(cfg.mbe_layer)
    return [
        poly
        for poly in resonator_metal_polys(res, dx, dy)
        if (poly.layer, poly.datatype) == mbe_pair
    ]


def collect_release_holes(
    assembly: RtegFrameAssembly,
    res: Resonator,
    layermap: LayerMap,
    config: RtegCollectConfig | None = None,
) -> ReleaseHoles:
    """
    ``BAW_ReF`` / ``BAW_CAV`` from the resonator master via the same RTEG shift
    and reference transform as ``resonator_metal_polys`` (rotation preserved).
    """
    cfg = config or RtegCollectConfig()
    dx, dy = _resonator_shift(res, assembly)
    pair_to_name = {layermap.pair(name): name for name in cfg.release_hole_layers}
    by_layer: dict[str, list[TaggedPolygon]] = {}
    for i, poly in enumerate(resonator_release_hole_polys(res, dx, dy)):
        layer_name = pair_to_name.get((poly.layer, poly.datatype))
        if layer_name is None:
            continue
        if abs(poly.area()) < cfg.min_polygon_area_um2:
            continue
        by_layer.setdefault(layer_name, []).append(
            TaggedPolygon(f"{layer_name}[{i}]", layer_name, poly)
        )
    return ReleaseHoles(by_layer=by_layer)


def get_inner_frame_boundary(
    assembly: RtegFrameAssembly,
    layermap: LayerMap,
    config: RtegCollectConfig | None = None,
) -> InnerFrameBoundary:
    """
    Inner die cavity (axis-aligned rectangle) and the die-frame MBE ring polygon.

    The cavity comes from ``assembly.inner_die_frame_bbox``. The ring is the
    largest MBE polygon in the frame master cell above ``frame_ring_min_area``.
    """
    cfg = config or RtegCollectConfig()
    mbe_pair = layermap.pair(cfg.mbe_layer)
    boundary_pair = layermap.pair(cfg.boundary_layer)

    (ix0, iy0), (ix1, iy1) = assembly.inner_die_frame_bbox
    cavity_poly = gdstk.rectangle(
        (ix0, iy0), (ix1, iy1), layer=boundary_pair[0], datatype=boundary_pair[1]
    )
    cavity = TaggedPolygon("inner_cavity", cfg.boundary_layer, cavity_poly)

    ring_poly: gdstk.Polygon | None = None
    frame_cell = None
    for ref in assembly.top_cell.references:
        if ref.cell is not None and ref.origin == assembly.frame_origin:
            frame_cell = ref.cell
            break
    if frame_cell is None:
        for cell in assembly.library.cells:
            if cell.name and "frame" in cell.name.lower():
                frame_cell = cell
                break

    if frame_cell is not None:
        candidates = [
            p
            for p in frame_cell.flatten().polygons
            if (p.layer, p.datatype) == mbe_pair
            and abs(p.area()) >= cfg.frame_ring_min_area_um2
        ]
        if candidates:
            ring_poly = max(candidates, key=lambda p: abs(p.area()))
            ring_poly = gdstk.Polygon(
                list(ring_poly.points),
                layer=ring_poly.layer,
                datatype=ring_poly.datatype,
            )
            # Translate ring to RTEG world if the frame reference is offset.
            ox, oy = assembly.frame_origin
            if ox or oy:
                ring_poly = gdstk.Polygon(
                    [(x + ox, y + oy) for x, y in ring_poly.points],
                    layer=ring_poly.layer,
                    datatype=ring_poly.datatype,
                )

    ring = (
        TaggedPolygon("frame_ring", cfg.mbe_layer, ring_poly)
        if ring_poly is not None
        else None
    )
    return InnerFrameBoundary(cavity=cavity, ring=ring)


def pad_bboxes_by_band(
    pad_polys: Sequence[gdstk.Polygon],
) -> dict[str, Bbox | None]:
    """Map top / center / bottom GSG pad bboxes from MBE pad polygons."""
    top, center, bottom = split_by_y_gaps(list(pad_polys))
    return {
        "top": polys_bbox(top),
        "center": polys_bbox(center),
        "bottom": polys_bbox(bottom),
    }


def pad_bboxes_from_ground_plates(
    ground_plates: GroundPlates,
) -> dict[str, Bbox | None]:
    """Union bbox per GSG band from step-5.1 ground plates."""
    return {
        "top": polys_bbox([tp.polygon for tp in ground_plates.top]),
        "center": polys_bbox([tp.polygon for tp in ground_plates.center]),
        "bottom": polys_bbox([tp.polygon for tp in ground_plates.bottom]),
    }


def collect_orientation_inputs(
    assembly: RtegFrameAssembly,
    res: Resonator,
    identification: IdentificationResult,
    layermap: LayerMap,
    *,
    ground_plates: GroundPlates | None = None,
    config: RtegCollectConfig | None = None,
) -> OrientationAnalysis:
    """
    Collar orientation analysis in RTEG world space (step 5.2 input).

    Reuses preserved collar geometry and either step-5.1 ground plates or PPD
    MBE pad bboxes when ``ground_plates`` is omitted.
    """
    cfg = config or RtegCollectConfig()
    shift = _resonator_shift(res, assembly)
    dx, dy = shift
    mte_polys, mbe_polys = preserved_collars_at_shift(
        res, identification, layermap, shift=shift, config=cfg
    )
    body_polys = resonator_metal_polys(res, dx, dy)

    if ground_plates is not None:
        pad_bboxes = pad_bboxes_from_ground_plates(ground_plates)
    else:
        ox, oy = _ppd_world_origin(assembly)
        keepouts = ppd_pad_keepout_polys(assembly.ppd_assembly.top_cell, (ox, oy))
        mbe_pair = layermap.pair(cfg.mbe_layer)
        mbe_pads = [
            p for p in keepouts if (p.layer, p.datatype) == mbe_pair
        ]
        pad_bboxes = pad_bboxes_by_band(mbe_pads)

    return analyze_orientation(body_polys, mte_polys, mbe_polys, pad_bboxes)


def collect_geometry_roles(
    assembly: RtegFrameAssembly,
    res: Resonator,
    identification: IdentificationResult,
    layermap: LayerMap,
    config: RtegCollectConfig | None = None,
) -> RtegGeometryRoles:
    """Run all step-5.1 collectors for one resonator."""
    cfg = config or RtegCollectConfig()
    return RtegGeometryRoles(
        index=assembly.index,
        inst_name=assembly.inst_name,
        ground_plates=collect_ground_plates(assembly, res, layermap, cfg),
        preserved=collect_preserved_metal(
            assembly, res, identification, layermap, cfg
        ),
        release_holes=collect_release_holes(assembly, res, layermap, cfg),
        frame_boundary=get_inner_frame_boundary(assembly, layermap, cfg),
        resonator_body_mte=collect_resonator_body_mte(res, assembly, layermap, cfg),
        resonator_body_mbe=collect_resonator_body_mbe(res, assembly, layermap, cfg),
    )


def attach_preserved_filter_interconnect(
    assembly: RtegFrameAssembly,
    res: Resonator,
    identification: IdentificationResult,
    layermap: LayerMap,
    config: RtegCollectConfig | None = None,
) -> PreservedMetal:
    """
    Copy filter ``connectMTE`` / ``connectMBE`` metal into the RTEG frame cell.

    Uses the same overlap + collar-association rules as step 5.1
    ``collect_preserved_metal``, but writes polygons directly onto
    ``assembly.top_cell`` so step-4 GDS export includes the preserved interconnect.
    """
    preserved = collect_preserved_metal(
        assembly, res, identification, layermap, config
    )
    for tp in preserved.mte:
        assembly.top_cell.add(tp.polygon)
    for tp in preserved.mbe:
        assembly.top_cell.add(tp.polygon)
    return preserved


def attach_preserved_filter_interconnect_all(
    assemblies: Sequence[RtegFrameAssembly],
    resonators: Sequence[Resonator],
    identification: IdentificationResult,
    layermap: LayerMap,
    config: RtegCollectConfig | None = None,
) -> dict[int, PreservedMetal]:
    """Attach preserved filter interconnect for every framed resonator index."""
    res_by_index = {i: r for i, r in enumerate(resonators)}
    out: dict[int, PreservedMetal] = {}
    for assembly in assemblies:
        res = res_by_index[assembly.index]
        out[assembly.index] = attach_preserved_filter_interconnect(
            assembly, res, identification, layermap, config
        )
    return out


def preserved_interconnect_attach_rows(
    preserved_by_index: Mapping[int, PreservedMetal],
    *,
    inst_names: Mapping[int, str] | None = None,
) -> list[dict[str, object]]:
    """Summary table for notebook display after attach step."""
    rows: list[dict[str, object]] = []
    for idx in sorted(preserved_by_index):
        preserved = preserved_by_index[idx]
        mte_areas = [round(abs(tp.polygon.area()), 1) for tp in preserved.mte]
        mbe_areas = [round(abs(tp.polygon.area()), 1) for tp in preserved.mbe]
        rows.append(
            {
                "index": idx,
                "inst_name": inst_names.get(idx) if inst_names else None,
                "n_preserved_mte": len(preserved.mte),
                "n_preserved_mbe": len(preserved.mbe),
                "mte_areas_um2": mte_areas,
                "mbe_areas_um2": mbe_areas,
            }
        )
    return rows


def geometry_roles_summary_table(roles: RtegGeometryRoles) -> list[dict[str, object]]:
    """Flat rows for a pandas DataFrame in the notebook."""
    rows: list[dict[str, object]] = []
    sections: list[tuple[str, dict[str, list[TaggedPolygon]]]] = [
        ("ground_plates", roles.ground_plates.groups()),
        ("preserved", roles.preserved.groups()),
        ("release_holes", roles.release_holes.groups()),
        ("frame_boundary", roles.frame_boundary.groups()),
    ]
    for section, groups in sections:
        for group_name, items in groups.items():
            if not items:
                continue
            for item in items:
                row = item.summary()
                row["section"] = section
                row["group"] = group_name
                row["index"] = roles.index
                row["inst_name"] = roles.inst_name
                rows.append(row)
    return rows
