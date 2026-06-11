"""
Step 5.1 — Collect framed-resonator geometry into typed roles.

Pulls polygons from a step-4 ``RtegFrameAssembly`` by **layermap name** (no
hardcoded layer numbers) and splits them into the sets downstream booleans need:

- **ground plates** — GSG pad / arm MBE + the step-4 width filler (not resonator)
- **preserved metal** — filter interconnect MBE/MTE from the connect cells
- **release holes** — ``BAW_ReF`` / ``BAW_CAV`` near the resonator
- **inner frame boundary** — inner cavity rectangle + die-frame MBE ring

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

from collections.abc import Sequence
from dataclasses import dataclass, field

import gdstk

from layermap import LayerMap
from prep_resonator_ppd import (
    ppd_pad_keepout_polys,
    resonator_metal_polys,
    resonator_release_hole_polys,
)
from prep_rteg_frame import RtegFrameAssembly
from rteg_utils import resonator_world_bbox
from separate import IdentificationResult, Resonator

Point = tuple[float, float]
Bbox = tuple[tuple[float, float], tuple[float, float]]


@dataclass(frozen=True)
class RtegCollectConfig:
    """Layer names and margins — resolved through ``LayerMap`` at runtime."""

    mbe_layer: str = "BAW_MBE"
    mte_layer: str = "BAW_MTE"
    release_hole_layers: tuple[str, ...] = ("BAW_ReF", "BAW_CAV")
    boundary_layer: str = "BAW_EDGE"

    preserved_overlap_margin_um: float = 10.0
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
        assembly.assembly_origin[0] + ppd.resonator_origin[0],
        assembly.assembly_origin[1] + ppd.resonator_origin[1],
    )
    return (rteg_origin[0] - res.origin[0], rteg_origin[1] - res.origin[1])


def resonator_placement_summary(
    res: Resonator, assembly: RtegFrameAssembly
) -> dict[str, object]:
    """Debug summary: filter vs RTEG placement for one resonator instance."""
    import math

    shift = _resonator_shift(res, assembly)
    ppd = assembly.ppd_assembly
    rteg_origin = (
        float(assembly.assembly_origin[0] + ppd.resonator_origin[0]),
        float(assembly.assembly_origin[1] + ppd.resonator_origin[1]),
    )
    return {
        "inst_name": res.inst_name,
        "master_name": res.master_name,
        "filter_origin": (round(res.origin[0], 3), round(res.origin[1], 3)),
        "rotation_deg": round(math.degrees(res.rotation), 1),
        "x_reflection": res.x_reflection,
        "magnification": res.magnification,
        "rteg_resonator_origin": (round(rteg_origin[0], 3), round(rteg_origin[1], 3)),
        "rteg_shift": (round(float(shift[0]), 3), round(float(shift[1]), 3)),
        "assembly_origin": (
            round(float(assembly.assembly_origin[0]), 3),
            round(float(assembly.assembly_origin[1]), 3),
        ),
        "ppd_resonator_origin": (
            round(float(ppd.resonator_origin[0]), 3),
            round(float(ppd.resonator_origin[1]), 3),
        ),
    }


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
    entries: list[tuple[float, gdstk.Polygon]] = []
    for poly in polys:
        bb = poly.bounding_box()
        if bb is None:
            continue
        cy = (bb[0][1] + bb[1][1]) / 2.0
        entries.append((cy, poly))
    if len(entries) < 3:
        tagged = [
            TaggedPolygon(f"{label_prefix}[{i}]", layer_name, p)
            for i, (_, p) in enumerate(entries)
        ]
        return tagged, [], []

    entries.sort(key=lambda item: item[0], reverse=True)
    ys = [cy for cy, _ in entries]
    gaps = [(ys[i] - ys[i + 1], i) for i in range(len(ys) - 1)]
    gaps.sort(reverse=True)
    split_a, split_b = sorted((gaps[0][1], gaps[1][1]))

    def tag_group(group: Sequence[gdstk.Polygon], band: str) -> list[TaggedPolygon]:
        return [
            TaggedPolygon(f"{label_prefix}_{band}[{i}]", layer_name, p)
            for i, p in enumerate(group)
        ]

    top = tag_group([p for _, p in entries[: split_a + 1]], "top")
    center = tag_group([p for _, p in entries[split_a + 1 : split_b + 1]], "center")
    bottom = tag_group([p for _, p in entries[split_b + 1 :]], "bottom")
    return top, center, bottom


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
    into RTEG world space.
    """
    cfg = config or RtegCollectConfig()
    margin = cfg.preserved_overlap_margin_um
    filter_bb = _expand_bbox(resonator_world_bbox(res), margin)

    out_mbe: list[TaggedPolygon] = []
    out_mte: list[TaggedPolygon] = []
    for suffix, layer_name in (
        ("connectMBE", cfg.mbe_layer),
        ("connectMTE", cfg.mte_layer),
    ):
        cell = _find_connect_cell(identification, suffix)
        if cell is None:
            continue
        pair = layermap.pair(layer_name)
        selected: list[gdstk.Polygon] = []
        for poly in cell.flatten().polygons:
            if (poly.layer, poly.datatype) != pair:
                continue
            if abs(poly.area()) < cfg.min_polygon_area_um2:
                continue
            bb = poly.bounding_box()
            if bb is None or not _bbox_overlap(bb, filter_bb):
                continue
            selected.append(poly)

        rteg_polys = _filter_to_rteg_world(selected, res, assembly)
        tagged = [
            TaggedPolygon(f"preserved_{layer_name}[{i}]", layer_name, p)
            for i, p in enumerate(rteg_polys)
        ]
        if layer_name == cfg.mbe_layer:
            out_mbe.extend(tagged)
        else:
            out_mte.extend(tagged)

    return PreservedMetal(mbe=out_mbe, mte=out_mte)


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
    )


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
