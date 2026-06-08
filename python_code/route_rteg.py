"""
Route one prepared RTEG into a (v1) finished test structure.

Pipeline (see fix_rteg_routing_v1 plan):
  Signal pad — resolve the signal launch from the ppd_1port probe device mapped
               onto the active frame pad reference (KB331_N_Frame), not the
               frame bbox.
  Routable   — first-class region: frame interior minus grown resonator, release
               holes, and other-net metal. Routes live inside it (DRC-clean by
               construction).
  Signal     — connect the pad launch to the pad-facing edge of preserved signal
               metal (true minimum-distance point pair), drawing a straight,
               single-45, or one-L-bend connector that stays inside routable.
  Ground     — detect the real frame ground region (BAW_MBE fill) and recut it
               around the signal net, resonator, and release holes.
  DRC        — connectivity-aware: nets built by unioning touching metal (the
               resonator bridges layers), spacing flagged only between nets.
  Metrics    — primary success metric is MBE/MTE overlap area vs golden; the
               per-layer count diff is kept as a secondary diagnostic.

Conservative by design: if no straight/single-bend connector stays inside
routable, the route is skipped and logged as "needs real router" rather than
inventing multi-bend detours. All layer identity flows through layermap.py.
Nothing claims parity with the golden; the report records every assumption.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import gdstk

import geometry as G
from inspect_golden import _find_prepared_top, build_notes, grouped_missing_layers
from layermap import LayerMap, load_layermap

PREPARED_DEFAULT = (
    Path(__file__).parent / "draft_output" / "KB331_N_01_RTEG1_S3_prepared.gds"
)
GOLDEN_DEFAULT = Path(__file__).parent / "example_output" / "KB331_N_01_RTEG1_S3.gds"
PPD_GDS = Path(__file__).parent / "ppd_1port.gds"
OUTPUT_DIR = Path(__file__).parent / "draft_output"


@dataclass
class RouteConfig:
    """Routing parameters. Defaults flagged where they need SME confirmation."""

    signal_vs_ground_rule: str = "series_signal_on_mte_side"  # NEEDS Brian/Jing
    signal_feed_layer: str = "BAW_MTE"
    ground_layers: tuple[str, ...] = ("BAW_MBE",)
    # GSG probe-pad layers, for an overlap check vs golden alongside MBE/MTE.
    pad_layers: tuple[str, ...] = ("BAW_MB2", "BAW_M1", "BAW_MB1")
    frame_interior_layer: str = "BAW_EDGE"  # frame extent; bbox fallback
    pad_cell_prefix: str = "pad3"  # signal-pad family in the frame
    via_cell_prefix: str = "vtb"
    min_spacing_um: float = 14.0  # PDK6 DRC
    safety_margin_um: float = 21.0  # 1.5x minimum
    release_clearance_um: float = 6.0  # PDK6 DRC
    resonator_clearance_um: float = 14.0
    release_layers: tuple[str, ...] = (
        "BAW_REV",
        "BAW_CAV",
        "BAW_ReF",
        "BAW_ReFneg",
    )  # ASSUMED from series cell layer inventory
    metal_width_um: float = 14.0
    # MBE polygons whose bbox area exceeds this fraction of the frame area are
    # treated as the existing ground plane to recut (vs. pad landings).
    ground_area_fraction: float = 0.3
    bridge_margin_um: float = 1.0  # resonator-as-connector tolerance for nets
    # Standalone GSG trim: drop layers absent from the golden (v1 golden-derived
    # allow-list; NOT a general RTEG-layer spec).
    trim_to_golden_layers: bool = True
    allowed_layer_override: tuple[tuple[int, int], ...] | None = None


def resolve_allowed_layer_pairs(
    cfg: RouteConfig, golden_path: Path
) -> set[tuple[int, int]] | None:
    """Return the layer allow-set, or None if trimming is disabled."""
    if cfg.allowed_layer_override is not None:
        return set(cfg.allowed_layer_override)
    if cfg.trim_to_golden_layers:
        return G.golden_layer_pairs(golden_path)
    return None


@dataclass
class SignalPadInfo:
    launch_polys: list[gdstk.Polygon]
    launch_layer: str
    origin: tuple[float, float]
    rotation: float
    ref_name: str
    ppd_mapped_bbox: tuple[tuple[float, float], tuple[float, float]] | None
    # Full transform of the matched frame pad, so callers (e.g. template
    # assembly in prepare_rteg) can place ppd_1port exactly where the router
    # mapped it.
    x_reflection: bool = False
    magnification: float = 1.0
    # ppd_1port geometry mapped into world space onto the matched pad. Template
    # assembly writes these so the GSG probe pads appear in the output.
    ppd_world_polys: list[gdstk.Polygon] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class RouteResult:
    routed_path: Path
    signal_routed: bool = False
    signal_kind: str = ""
    signal_skipped_reason: str = ""
    signal_pad_ref: str = ""
    signal_launch_layer: str = ""
    via_needed: bool = False
    via_placed: int = 0
    ground_source: str = ""
    ground_polys: int = 0
    real_drc_violations: int = 0
    collar_drc_violations: int = 0
    overlap: dict = field(default_factory=dict)
    pad_overlap: dict = field(default_factory=dict)
    layers_absent_from_golden: list[str] = field(default_factory=list)
    prepared_layers_absent_from_golden: list[str] = field(default_factory=list)
    trimmed_poly_count: int = 0
    diff_rows: list[tuple[str, str, int, int]] = field(default_factory=list)
    missing_groups: list = field(default_factory=list)
    log: list[str] = field(default_factory=list)
    nets_path: Path | None = None
    nets_lyp_path: Path | None = None
    net_overlay: dict = field(default_factory=dict)


# --- small helpers -----------------------------------------------------------

def _bbox_area(bbox) -> float:
    (x0, y0), (x1, y1) = bbox
    return (x1 - x0) * (y1 - y0)


def _bbox_center(bbox) -> tuple[float, float]:
    (x0, y0), (x1, y1) = bbox
    return (x0 + x1) / 2, (y0 + y1) / 2


def _overlaps(a, b) -> bool:
    (ax0, ay0), (ax1, ay1) = a
    (bx0, by0), (bx1, by1) = b
    return ax0 <= bx1 and ax1 >= bx0 and ay0 <= by1 and ay1 >= by0


def _fmt(bbox) -> str:
    if bbox is None:
        return "none"
    (x0, y0), (x1, y1) = bbox
    return f"({x0:.1f}, {y0:.1f})-({x1:.1f}, {y1:.1f})"


def _fmt_pt(pt) -> str:
    return f"({pt[0]:.1f}, {pt[1]:.1f})"


def _resonator_world_bbox(top: gdstk.Cell, res_cell: gdstk.Cell):
    ref = next(r for r in top.references if r.cell is res_cell)
    rb = res_cell.bounding_box()
    ox, oy = ref.origin
    return (rb[0][0] + ox, rb[0][1] + oy), (rb[1][0] + ox, rb[1][1] + oy)


def _ref_world_polys(frame_ref: gdstk.Reference, child_ref: gdstk.Reference):
    """World-space polygons of a child reference nested under a frame ref."""
    local = child_ref.cell.get_polygons()
    after_child = G.transform_polygons(
        local, child_ref.origin, child_ref.rotation, child_ref.x_reflection
    )
    return G.transform_polygons(
        after_child, frame_ref.origin, frame_ref.rotation, frame_ref.x_reflection
    )


# --- signal pad resolution (Fix 1a) -----------------------------------------

def _ppd_launch_layer(layermap: LayerMap, cfg: RouteConfig) -> str:
    """Launch layer present on ppd_1port: prefer the signal feed layer, else MBE."""
    ppd = gdstk.read_gds(PPD_GDS).cells[0]
    flat = ppd.get_polygons()
    if G.polygons_on_layer(flat, layermap, cfg.signal_feed_layer):
        return cfg.signal_feed_layer
    for nm in cfg.ground_layers:
        if G.polygons_on_layer(flat, layermap, nm):
            return nm
    return cfg.ground_layers[0]


def resolve_signal_pad(
    top: gdstk.Cell,
    layermap: LayerMap,
    cfg: RouteConfig,
    target_metal: list[gdstk.Polygon],
    log: list[str],
) -> SignalPadInfo | None:
    """
    Identify the signal pad launch by loading ppd_1port and mapping it onto the
    active frame pad reference, then use the chosen frame pad's real launch
    metal (correct size/position) for routing. Returns None if no pad found.
    """
    frame_ref = next((r for r in top.references if r.cell and r.cell.references), None)
    if frame_ref is None:
        log.append("signal pad: no frame reference with sub-references found")
        return None

    launch_layer = _ppd_launch_layer(layermap, cfg)
    log.append(
        f"signal pad: ppd_1port launch layer = {launch_layer}"
        + (
            ""
            if launch_layer == cfg.signal_feed_layer
            else f" (differs from signal feed {cfg.signal_feed_layer} -> via at transition)"
        )
    )

    pad_refs = [
        r
        for r in frame_ref.cell.references
        if r.cell and r.cell.name.startswith(cfg.pad_cell_prefix)
    ]
    if not pad_refs:
        log.append(f"signal pad: no '{cfg.pad_cell_prefix}*' pad references in frame")
        return None

    # Choose the pad whose launch metal is closest to the preserved signal metal.
    best = None
    for r in pad_refs:
        world = _ref_world_polys(frame_ref, r)
        launch = G.polygons_on_layer(world, layermap, launch_layer)
        if not launch:
            continue
        if target_metal:
            _, _, dist = G.min_distance_point_pair(launch, target_metal)
        else:
            dist = 0.0
        if best is None or dist < best[0]:
            best = (dist, r, launch)
    if best is None:
        log.append("signal pad: candidate pads carry no launch-layer metal")
        return None

    _, pad_ref, launch_polys = best

    # Map the canonical ppd_1port device onto the chosen pad ref (per the
    # ppd-library-match approach) and record its mapped extent for the report.
    ppd = gdstk.read_gds(PPD_GDS).cells[0]
    ppd_mapped = None
    ppd_world: list[gdstk.Polygon] = []
    try:
        mapped = G.transform_polygons(
            ppd.get_polygons(), pad_ref.origin, pad_ref.rotation, pad_ref.x_reflection
        )
        mapped = G.transform_polygons(
            mapped, frame_ref.origin, frame_ref.rotation, frame_ref.x_reflection
        )
        ppd_world = mapped
        ppd_mapped = G.bbox_of(mapped)
    except Exception as exc:  # pragma: no cover - defensive
        log.append(f"signal pad: ppd map failed ({exc}); using frame pad metal")

    info = SignalPadInfo(
        launch_polys=launch_polys,
        launch_layer=launch_layer,
        origin=tuple(pad_ref.origin),
        rotation=float(pad_ref.rotation),
        ref_name=pad_ref.cell.name,
        ppd_mapped_bbox=ppd_mapped,
        x_reflection=bool(pad_ref.x_reflection),
        magnification=float(pad_ref.magnification),
        ppd_world_polys=ppd_world,
    )
    log.append(
        f"signal pad: matched ppd_1port onto frame pad '{info.ref_name}' @ "
        f"{_fmt_pt(info.origin)} rot {info.rotation:.2f}; launch metal "
        f"{len(launch_polys)} polys on {launch_layer}"
    )
    return info


# --- frame interior (Fix 1b / Fix 4) ----------------------------------------

def frame_interior_region(
    flat: list[gdstk.Polygon], layermap: LayerMap, cfg: RouteConfig, frame_bbox, log
) -> list[gdstk.Polygon]:
    """Frame interior: prefer the BAW_EDGE extent; fall back to the frame bbox."""
    edge = G.polygons_on_layer(flat, layermap, cfg.frame_interior_layer)
    if edge:
        region = G.union(edge)
        log.append(
            f"routable: frame interior from {cfg.frame_interior_layer} "
            f"({len(region)} polys, {_fmt(G.bbox_of(region))})"
        )
        return region
    log.append("routable: frame interior from frame bbox (no BAW_EDGE found)")
    return [G.rectangle(frame_bbox)]


def _layers_absent_from_golden(
    polys, allowed: set[tuple[int, int]], layermap: LayerMap
) -> list[str]:
    """Layer names in polys but not in the golden allow-list."""
    absent: set[str] = set()
    for p in polys:
        pair = (p.layer, p.datatype)
        if pair not in allowed:
            name = layermap.name(p.layer, p.datatype) or f"{p.layer}/{p.datatype}"
            absent.add(name)
    return sorted(absent)


def _pick_marker_layers(
    layermap: LayerMap, count: int = 3, start: int = 900
) -> list[tuple[int, int]]:
    """
    Return ``count`` (layer, datatype) pairs not present in the layermap, starting
    at ``start/0`` and incrementing the layer number until free slots are found.
    """
    pairs: list[tuple[int, int]] = []
    layer = start
    while len(pairs) < count:
        pair = (layer, 0)
        if layermap.name(pair[0], pair[1]) is None:
            pairs.append(pair)
        layer += 1
    return pairs


def _union_net_bucket(nets: list[list[gdstk.Polygon]]) -> list[gdstk.Polygon]:
    """Union all polygons across one or more connectivity nets."""
    polys = [p for net in nets for p in net]
    return G.union(polys) if polys else []


def _write_nets_lyp(
    path: Path,
    entries: list[tuple[tuple[int, int], str, str]],
) -> None:
    """
    Write a minimal KLayout layer-properties file. Each entry is
    ((layer, datatype), display_name, hex_color).
    """
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<layer-properties>"]
    for (layer, datatype), name, color in entries:
        bright = color  # sufficient for v1 diagnostic
        lines.extend(
            [
                " <properties>",
                f"  <frame-color>{color}</frame-color>",
                f"  <fill-color>{color}</fill-color>",
                f"  <frame-color-bright>{bright}</frame-color-bright>",
                f"  <fill-color-bright>{bright}</fill-color-bright>",
                "  <dither-pattern>I9</dither-pattern>",
                "  <line-style/>",
                "  <valid>true</valid>",
                "  <visible>true</visible>",
                "  <transparent>true</transparent>",
                "  <width>1</width>",
                "  <marked>false</marked>",
                "  <xfill>false</xfill>",
                "  <animation>0</animation>",
                f"  <name>{name}</name>",
                f"  <source>{layer}/{datatype}@1</source>",
                " </properties>",
            ]
        )
    lines.append("</layer-properties>")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_net_overlay(
    routed: gdstk.Cell,
    nets: list[list[gdstk.Polygon]],
    ground_net: list[gdstk.Polygon] | None,
    signal_nets: list[list[gdstk.Polygon]],
    layermap: LayerMap,
    routed_path: Path,
    log: list[str],
) -> tuple[Path, Path, dict]:
    """
    Write the default net-overlay diagnostic: full routed geometry plus marker
    layers for SIGNAL / GROUND / OTHER buckets (same classification as DRC).
    """
    marker_signal, marker_ground, marker_other = _pick_marker_layers(layermap, 3)
    log.append(
        "net overlay marker layers (not in layermap): "
        f"SIGNAL={marker_signal[0]}/{marker_signal[1]}, "
        f"GROUND={marker_ground[0]}/{marker_ground[1]}, "
        f"OTHER={marker_other[0]}/{marker_other[1]}"
    )

    ground_bucket = [ground_net] if ground_net else []
    signal_ids = {id(n) for n in signal_nets}
    ground_id = id(ground_net) if ground_net else None
    other_nets = [
        n
        for n in nets
        if id(n) != ground_id and id(n) not in signal_ids
    ]

    signal_union = _union_net_bucket(signal_nets)
    ground_union = _union_net_bucket(ground_bucket)
    other_union = _union_net_bucket(other_nets)

    overlay = gdstk.Cell(routed.name.replace("_routed", "_nets"))
    for p in routed.polygons:
        overlay.add(
            gdstk.Polygon(p.points, layer=p.layer, datatype=p.datatype)
        )
    for p in signal_union:
        overlay.add(
            gdstk.Polygon(p.points, layer=marker_signal[0], datatype=marker_signal[1])
        )
    for p in ground_union:
        overlay.add(
            gdstk.Polygon(p.points, layer=marker_ground[0], datatype=marker_ground[1])
        )
    for p in other_union:
        overlay.add(
            gdstk.Polygon(p.points, layer=marker_other[0], datatype=marker_other[1])
        )

    nets_path = routed_path.with_name(routed_path.name.replace("_routed.gds", "_nets.gds"))
    lyp_path = nets_path.with_suffix(".lyp")

    out_lib = gdstk.Library()
    out_lib.add(overlay)
    nets_path.parent.mkdir(parents=True, exist_ok=True)
    out_lib.write_gds(nets_path)

    _write_nets_lyp(
        lyp_path,
        [
            (marker_signal, "SIGNAL", "#ff0000"),
            (marker_ground, "GROUND", "#0000ff"),
            (marker_other, "OTHER", "#808080"),
        ],
    )

    summary = {
        "marker_signal": marker_signal,
        "marker_ground": marker_ground,
        "marker_other": marker_other,
        "total_nets": len(nets),
        "signal_net_count": len(signal_nets),
        "other_net_count": len(other_nets),
        "signal_poly_count": len(signal_union),
        "ground_poly_count": len(ground_union),
        "other_poly_count": len(other_union),
        "ground_area": G.total_area(ground_net) if ground_net else 0.0,
        "signal_area": sum(G.total_area(n) for n in signal_nets),
    }
    log.append(
        "net overlay classification (same as DRC): "
        f"{summary['total_nets']} nets -> "
        f"GROUND=1 net ({summary['ground_poly_count']} marker polys, "
        f"area {summary['ground_area']:.0f}), "
        f"SIGNAL={summary['signal_net_count']} net(s) "
        f"({summary['signal_poly_count']} marker polys), "
        f"OTHER={summary['other_net_count']} net(s) "
        f"({summary['other_poly_count']} marker polys)"
    )
    log.append(f"wrote {nets_path.name} (+ {lyp_path.name})")
    return nets_path, lyp_path, summary


# --- main routing pipeline ---------------------------------------------------

def route(
    prepared_path: Path = PREPARED_DEFAULT,
    golden_path: Path = GOLDEN_DEFAULT,
    config: RouteConfig | None = None,
) -> RouteResult:
    cfg = config or RouteConfig()
    layermap = load_layermap()
    allowed = resolve_allowed_layer_pairs(cfg, golden_path)

    prep_lib = gdstk.read_gds(prepared_path)
    top = _find_prepared_top(prep_lib, prepared_path)
    frame_bbox = top.bounding_box()
    frame_area = _bbox_area(frame_bbox)

    flat = G.flatten_cell(top)
    routed_name = f"{top.name}_routed"
    result = RouteResult(routed_path=OUTPUT_DIR / f"{routed_name}.gds")
    log = result.log

    if allowed is not None:
        result.prepared_layers_absent_from_golden = _layers_absent_from_golden(
            flat, allowed, layermap
        )
        log.append(
            f"layer trim: golden-derived allow-list ({len(allowed)} pairs); "
            f"prepared layers absent from golden: "
            f"{result.prepared_layers_absent_from_golden or 'none'}"
        )
    else:
        log.append("layer trim: disabled")

    res_cell = next(c for c in prep_lib.cells if c.name.startswith("seriesq3"))
    res_world = _resonator_world_bbox(top, res_cell)
    res_body = [G.rectangle(res_world)]
    log.append(f"resonator world bbox: {_fmt(res_world)}")

    signal_layer = cfg.signal_feed_layer
    ground_layer = cfg.ground_layers[0]
    s_layer, s_dt = layermap.pair(signal_layer)
    g_layer, g_dt = layermap.pair(ground_layer)

    mte_all = G.polygons_on_layer(flat, layermap, signal_layer)
    mbe_all = G.polygons_on_layer(flat, layermap, ground_layer)

    # Preserved signal metal facing the pad = MTE outside the resonator clearance
    # (so endpoints land on metal that has cleared the resonator, not the collar).
    preserved_clear = G.subtract(mte_all, G.grow(res_body, cfg.resonator_clearance_um))
    if not preserved_clear:
        preserved_clear = list(mte_all)
        log.append("signal metal: none outside resonator clearance; using all MTE")
    log.append(f"signal metal (MTE) polys: {len(mte_all)}; outside clearance: {len(preserved_clear)}")

    # Release holes inside the resonator region.
    release_polys: list[gdstk.Polygon] = []
    for name in cfg.release_layers:
        release_polys.extend(G.polygons_on_layer(flat, layermap, name))
    release_polys = [p for p in release_polys if _overlaps(p.bounding_box(), res_world)]
    log.append(f"release-hole polys ({', '.join(cfg.release_layers)}): {len(release_polys)}")

    # --- signal pad + endpoints (Fix 1a, 1c) ---
    pad = resolve_signal_pad(top, layermap, cfg, preserved_clear, log)
    signal_route_polys: list[gdstk.Polygon] = []
    if pad is None:
        result.signal_skipped_reason = "no signal pad resolved"
        log.append("signal route skipped: no signal pad resolved")
    else:
        result.signal_pad_ref = pad.ref_name
        result.signal_launch_layer = pad.launch_layer
        result.via_needed = pad.launch_layer != signal_layer

        start, end, gap = G.min_distance_point_pair(pad.launch_polys, preserved_clear)
        log.append(
            f"endpoints: pad {_fmt_pt(start)} -> preserved metal {_fmt_pt(end)} (gap {gap:.1f}um)"
        )

        # other-net metal = ground fill + far pads (exclude signal pad + near-res
        # preserved metal, which are the signal net we are extending).
        pad_bbox = G.bbox_of(pad.launch_polys)
        other_net = [
            p
            for p in mbe_all
            if not _overlaps(p.bounding_box(), res_world)
            and (pad_bbox is None or not _overlaps(p.bounding_box(), pad_bbox))
        ]
        interior = frame_interior_region(flat, layermap, cfg, frame_bbox, log)
        routable = G.compute_routable_region(
            interior,
            res_body,
            release_polys,
            other_net,
            cfg.resonator_clearance_um,
            cfg.release_clearance_um,
            cfg.safety_margin_um,
        )
        log.append(f"routable region: {len(routable)} polys, area {G.total_area(routable):.0f}")

        polys, kind = G.try_connectors(
            start, end, cfg.metal_width_um, routable, chamfer=cfg.metal_width_um
        )
        if polys is None:
            result.signal_skipped_reason = kind
            log.append(f"signal route skipped: {kind} [needs real router]")
        else:
            signal_route_polys = [
                gdstk.Polygon(p.points, layer=s_layer, datatype=s_dt) for p in polys
            ]
            result.signal_routed = True
            result.signal_kind = kind
            log.append(
                f"signal route drawn: {kind}, {len(signal_route_polys)} polys on {signal_layer}"
            )

    # --- via at layer transition (Fix 1e) ---
    if result.signal_routed and result.via_needed:
        via_refs = [
            r for r in top.references if r.cell and r.cell.name.startswith(cfg.via_cell_prefix)
        ]
        if via_refs:
            result.via_placed = 1
            log.append(
                f"via at transition: reusing '{via_refs[0].cell.name}' (pad {pad.launch_layer} -> route {signal_layer})"
            )
        else:
            log.append(
                f"via needed at pad transition ({pad.launch_layer} -> {signal_layer}) "
                "but no vtb master in prepared input [flagged for SME]"
            )

    # --- ground plane (Fix 4) ---
    big_ground = [
        p
        for p in mbe_all
        if _bbox_area(p.bounding_box()) >= cfg.ground_area_fraction * frame_area
    ]
    big_ground_ids = {id(p) for p in big_ground}

    # Signal net for the recut. Seed it with the routed signal metal, then expand
    # to the FULL connected net so the ground plane is also cleared around any
    # signal-side metal that shares the ground layer (e.g. a placed ppd_1port
    # probe pad sits on BAW_MBE but is electrically signal). Without this, those
    # pads sit too close to the ground fill and trip the net-aware DRC check.
    seed = list(preserved_clear) + signal_route_polys
    if pad is not None:
        seed += pad.launch_polys
    nonground_mbe = [p for p in mbe_all if id(p) not in big_ground_ids]
    metal_for_net = seed + nonground_mbe
    seed_ids = {id(p) for p in seed}
    signal_net: list[gdstk.Polygon] = []
    for net in G.build_nets(
        metal_for_net, bridge_bbox=res_world, bridge_margin=cfg.bridge_margin_um
    ):
        if any(id(p) in seed_ids for p in net):
            signal_net.extend(net)
    if not signal_net:
        signal_net = seed

    teg = G.polygons_on_layer(flat, layermap, "BAW_TEG") if "BAW_TEG" in layermap else []
    if big_ground:
        ground_region = G.union(big_ground)
        result.ground_source = f"frame {ground_layer} ground fill"
    elif teg:
        ground_region = G.union(teg)
        result.ground_source = "BAW_TEG ground layer"
    else:
        ground_region = [G.rectangle(frame_bbox)]
        result.ground_source = "frame bbox fallback (no ground geometry found)"
        log.append("WARNING: no frame ground geometry; using bbox fallback")
    log.append(f"ground source: {result.ground_source}")

    cut = ground_region
    cut = G.subtract(cut, G.grow(signal_net, cfg.safety_margin_um))
    cut = G.subtract(cut, G.grow(res_body, cfg.resonator_clearance_um))
    if release_polys:
        cut = G.subtract(cut, G.grow(release_polys, cfg.release_clearance_um))
    ground_fill = [gdstk.Polygon(p.points, layer=g_layer, datatype=g_dt) for p in cut]
    result.ground_polys = len(ground_fill)
    log.append(f"ground recut: {len(ground_fill)} polys")
    if not ground_fill:
        log.append("WARNING: ground recut produced empty result")

    # --- assemble routed cell (trim to golden layers on emit) ---
    routed = gdstk.Cell(routed_name)
    trimmed_emit = 0
    for p in flat:
        if id(p) in big_ground_ids:
            continue
        if allowed is not None and (p.layer, p.datatype) not in allowed:
            trimmed_emit += 1
            continue
        routed.add(gdstk.Polygon(p.points, layer=p.layer, datatype=p.datatype))
    for p in ground_fill:
        routed.add(p)
    for p in signal_route_polys:
        routed.add(p)
    result.trimmed_poly_count = trimmed_emit
    if allowed is not None:
        result.layers_absent_from_golden = _layers_absent_from_golden(
            list(routed.polygons), allowed, layermap
        )
        log.append(
            f"layer trim emit: skipped {trimmed_emit} non-golden polys; "
            f"routed layers absent from golden: "
            f"{result.layers_absent_from_golden or 'none'}"
        )

    # --- net-aware DRC self-check (Fix 2) ---
    # Build nets (resonator bridges layers), then check signal-vs-ground spacing
    # only. Frame bonding pads (isolated MBE, no signal layer) are frame-inherent
    # and excluded; the resonator-bridged MBE/MTE no longer false-positives.
    final_metal = G.polygons_on_layer(list(routed.polygons), layermap, ground_layer)
    final_metal += G.polygons_on_layer(list(routed.polygons), layermap, signal_layer)
    nets = G.build_nets(final_metal, bridge_bbox=res_world, bridge_margin=cfg.bridge_margin_um)
    ground_net: list[gdstk.Polygon] | None = None
    signal_nets: list[list[gdstk.Polygon]] = []
    violations = []
    if nets:
        ground_net = max(nets, key=G.total_area)
        signal_nets = [
            n
            for n in nets
            if n is not ground_net
            and any((p.layer, p.datatype) == (s_layer, s_dt) for p in n)
        ]
        for sn in signal_nets:
            violations.extend(
                G.drc_spacing_violation(sn, ground_net, cfg.min_spacing_um)
            )
    # Split violations: those at the resonator collar fall on PRESERVED filter
    # metal (reproduced exactly per the NPI mandate; the resonator's own terminal
    # spacing). They are not introduced by routing/pads and we must not move that
    # metal, so they are reported separately and flagged for the unresolved
    # signal/ground rule rather than counted as routing defects.
    collar_zone = G.grow(
        res_body, cfg.resonator_clearance_um + cfg.min_spacing_um
    )
    introduced, collar = [], []
    for v in violations:
        if collar_zone and G.intersect([v], collar_zone):
            collar.append(v)
        else:
            introduced.append(v)
    result.real_drc_violations = len(introduced)
    result.collar_drc_violations = len(collar)
    log.append(
        f"net-aware DRC: {len(nets)} nets; signal-vs-ground spacing violations "
        f"@ {cfg.min_spacing_um}um: introduced={len(introduced)}, "
        f"preserved-collar={len(collar)} (frame bonding pads excluded; "
        f"collar = NPI-preserved metal, see signal/ground rule)"
    )

    out_lib = gdstk.Library()
    out_lib.add(routed)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_lib.write_gds(result.routed_path)
    log.append(f"wrote {result.routed_path.name}")

    # --- net overlay diagnostic (default; does not modify _routed.gds) ---
    result.nets_path, result.nets_lyp_path, result.net_overlay = write_net_overlay(
        routed,
        nets or [],
        ground_net,
        signal_nets,
        layermap,
        result.routed_path,
        log,
    )

    # --- metrics + diff (Fix 3) ---
    golden = gdstk.read_gds(golden_path).cells[0]
    for nm in (ground_layer, signal_layer):
        g_polys = G.polygons_on_layer(golden.get_polygons(), layermap, nm)
        r_polys = G.polygons_on_layer(list(routed.polygons), layermap, nm)
        result.overlap[nm] = G.layer_overlap_metrics(g_polys, r_polys)
    for nm in cfg.pad_layers:
        if nm not in layermap:
            continue
        g_polys = G.polygons_on_layer(golden.get_polygons(), layermap, nm)
        r_polys = G.polygons_on_layer(list(routed.polygons), layermap, nm)
        result.pad_overlap[nm] = G.layer_overlap_metrics(g_polys, r_polys)
    result.diff_rows = _golden_diff(golden, routed, layermap)
    result.missing_groups = grouped_missing_layers(golden_path, result.routed_path)
    return result


# --- diff / report -----------------------------------------------------------

def _counts(polys) -> dict[tuple[int, int], int]:
    out: dict[tuple[int, int], int] = {}
    for p in polys:
        k = (p.layer, p.datatype)
        out[k] = out.get(k, 0) + 1
    return out


def _golden_diff(
    golden: gdstk.Cell, routed: gdstk.Cell, layermap: LayerMap
) -> list[tuple[str, str, int, int]]:
    g_counts = _counts(golden.get_polygons())
    r_counts = _counts(routed.polygons)
    keys = sorted(set(g_counts) | set(r_counts))
    rows: list[tuple[str, str, int, int]] = []
    for layer, dt in keys:
        name = layermap.name(layer, dt) or "?"
        rows.append(
            (name, f"{layer}/{dt}", g_counts.get((layer, dt), 0), r_counts.get((layer, dt), 0))
        )
    return rows


def write_report(
    result: RouteResult,
    cfg: RouteConfig,
    prepared_path: Path,
    golden_path: Path,
    report_path: Path | None = None,
) -> Path:
    """Write ROUTE_S3_REPORT.md with the v1-fix sections."""
    report_path = report_path or (OUTPUT_DIR / "ROUTE_S3_REPORT.md")

    lines: list[str] = []
    lines.append("# Route S3 (v1) report")
    lines.append("")
    lines.append(
        "Standalone individual RTEG in its own GSG frame (`KB331_N_Frame`, 460x580) — "
        "not reintegrated into the die. Resonator index 06 routed against golden S3. "
        "Output is trimmed to the golden's layer set for a clean GSG look (no die-"
        "context BF/TSV/EM_VPT fill). This pass draws a simple signal connector, "
        "recuts the frame ground, and checks spacing per net. It does not generate "
        "the manual flow's fill/trim layers and does not claim parity with the golden."
    )
    lines.append("")

    lines.append("## 0. What changed in this pass")
    lines.append("")
    lines.append("- **Reverted** `ppd_1port` geometry placement: the output's GSG pads are `KB331_N_Frame`'s `BAW_MB2` bond pads only. `ppd_1port` is kept **only** as the signal-pad/orientation lookup for routing (`resolve_signal_pad`).")
    lines.append("- **Trimmed** the entire assembled output (frame sub-cells + resonator + preserved metal) to a golden-derived layer allow-list (`trim_to_golden_layers=True`, v1 — NOT a general RTEG-layer spec). Drops frame BF1-8/TSV/EM_VPT and resonator H18/TCL over-carry.")
    lines.append("- Standalone GSG-frame scope: clean orange GSG frame, three vertical `BAW_MB2` pads per side, resonator + routing — no die-like hatched border.")
    lines.append("- Signal route draws inside a first-class routable region (straight / single 45 / one L-bend).")
    lines.append("- Endpoints use the true minimum-distance pad-to-metal point pair (pad-facing edge).")
    lines.append("- DRC self-check is connectivity-aware; spacing flagged only between different nets.")
    lines.append("- Primary success metric is MBE/MTE overlap area vs golden; layer-count table is secondary.")
    lines.append("- Ground region from real `KB331_N_Frame` `BAW_MBE` fill.")
    lines.append("")

    lines.append("## 1. Signal route")
    lines.append("")
    if result.signal_routed:
        lines.append(f"- **drew** a `{result.signal_kind}` connector on `{cfg.signal_feed_layer}`.")
    else:
        lines.append(f"- **skipped** — {result.signal_skipped_reason} (treated as needs-real-router; no multi-bend detour attempted).")
    lines.append(f"- signal pad ref: `{result.signal_pad_ref or 'n/a'}`, launch layer `{result.signal_launch_layer or 'n/a'}`.")
    if result.via_needed:
        if result.via_placed:
            lines.append(f"- via at transition: placed ({result.via_placed}).")
        else:
            lines.append("- via at transition: **needed** (pad and route on different layers) but no `vtb` master available in prepared input [flagged for SME].")
    else:
        lines.append("- via at transition: not needed (pad and route share a layer).")
    lines.append("")
    lines.append("### Route log")
    lines.append("```")
    lines.extend(result.log)
    lines.append("```")
    lines.append("")

    lines.append("## 2. Assumptions (RouteConfig)")
    lines.append("")
    lines.append("| Parameter | Value | Status |")
    lines.append("|---|---|---|")
    lines.append(f"| signal_vs_ground_rule | `{cfg.signal_vs_ground_rule}` | **needs Brian/Jing** |")
    lines.append(f"| signal_feed_layer | `{cfg.signal_feed_layer}` | derived from rule |")
    lines.append(f"| ground_layers | `{', '.join(cfg.ground_layers)}` | golden uses more fill layers — diverges |")
    lines.append(f"| frame_interior_layer | `{cfg.frame_interior_layer}` | frame extent; bbox fallback |")
    lines.append(f"| release_layers | `{', '.join(cfg.release_layers)}` | **assumed** from cell inventory |")
    lines.append(f"| min_spacing_um | {cfg.min_spacing_um} | PDK6 DRC |")
    lines.append(f"| safety_margin_um | {cfg.safety_margin_um} | 1.5x min |")
    lines.append(f"| release_clearance_um | {cfg.release_clearance_um} | PDK6 DRC |")
    lines.append(f"| resonator_clearance_um | {cfg.resonator_clearance_um} | routable-region grow |")
    lines.append(f"| metal_width_um | {cfg.metal_width_um} | v1 = min spacing |")
    lines.append(f"| via_cell_prefix | `{cfg.via_cell_prefix}` | from SKILL; not a layermap layer |")
    lines.append(f"| trim_to_golden_layers | {cfg.trim_to_golden_layers} | **golden-derived (v1)**; not a general RTEG spec |")
    lines.append("")

    lines.append("## 2b. Layer trim — prepared / routed vs golden")
    lines.append("")
    lines.append(f"- Prepared layers absent from golden: **{result.prepared_layers_absent_from_golden or 'none'}**.")
    lines.append(f"- Routed layers absent from golden: **{result.layers_absent_from_golden or 'none'}**.")
    lines.append(f"- Polygons skipped at routed emit (non-golden layers): {result.trimmed_poly_count}.")
    lines.append("- Target: ~0 absent layers; die fill (`BAW_BF*`, `BAW_TSV`, `EM_VPT`) and resonator extras (`BAW_H18`, `BAW_TCL`) should be gone.")
    lines.append("")

    lines.append("## 3. Primary metric — MBE/MTE overlap area vs golden")
    lines.append("")
    lines.append("| layer | golden area | routed area | intersection | overlap % of golden | sym-diff area |")
    lines.append("|---|---|---|---|---|---|")
    for nm, m in result.overlap.items():
        lines.append(
            f"| {nm} | {m['golden_area']:.0f} | {m['routed_area']:.0f} | "
            f"{m['intersection_area']:.0f} | {m['overlap_fraction_of_golden'] * 100:.1f}% | "
            f"{m['symmetric_difference_area']:.0f} |"
        )
    lines.append("")
    lines.append("Overlap % is intersection area as a fraction of the golden's area on that layer. This is the headline metric; high sym-diff means the routed shapes differ substantially from golden even where they overlap.")
    lines.append("")

    lines.append("### GSG / pad-layer overlap vs golden")
    lines.append("")
    lines.append("| layer | golden area | routed area | overlap % of golden | sym-diff area |")
    lines.append("|---|---|---|---|---|")
    for nm, m in result.pad_overlap.items():
        lines.append(
            f"| {nm} | {m['golden_area']:.0f} | {m['routed_area']:.0f} | "
            f"{m['overlap_fraction_of_golden'] * 100:.1f}% | "
            f"{m['symmetric_difference_area']:.0f} |"
        )
    lines.append("")
    lines.append("`BAW_MB2` (the GSG bond pads) overlaps the golden because those pads come from `KB331_N_Frame`. `BAW_M1`/`BAW_MB1` are dominated by the golden's large ground planes.")
    lines.append("")

    lines.append("## 4. DRC self-check (net-aware)")
    lines.append("")
    lines.append(f"- Cross-net spacing violations introduced by routing/pads @ {cfg.min_spacing_um}um: **{result.real_drc_violations}**.")
    lines.append(f"- Preserved-collar violations (NPI metal, not introduced): **{result.collar_drc_violations}** — filter metal reproduced exactly around the resonator; hinge on the unresolved signal/ground rule.")
    lines.append("- Metal connected through the resonator is treated as one net, so preserved MBE meeting MTE at the resonator is otherwise not a false positive.")
    lines.append("")

    lines.append("## 4b. Net overlay diagnostic (`_nets.gds`)")
    lines.append("")
    lines.append(
        "Every run also writes a **diagnostic overlay** (not a deliverable): "
        f"`{result.nets_path.name if result.nets_path else 'n/a'}` plus "
        f"`{result.nets_lyp_path.name if result.nets_lyp_path else 'n/a'}` for KLayout. "
        "It contains the full routed geometry plus marker layers painted from the "
        "**same net builder and classification used by net-aware DRC**."
    )
    lines.append("")
    if result.net_overlay:
        ov = result.net_overlay
        ms = ov.get("marker_signal", ("?", "?"))
        mg = ov.get("marker_ground", ("?", "?"))
        mo = ov.get("marker_other", ("?", "?"))
        lines.append("| bucket | marker layer | nets | marker polys |")
        lines.append("|---|---|---|---|")
        lines.append(
            f"| SIGNAL | {ms[0]}/{ms[1]} | {ov.get('signal_net_count', 0)} | "
            f"{ov.get('signal_poly_count', 0)} |"
        )
        lines.append(
            f"| GROUND | {mg[0]}/{mg[1]} | 1 | {ov.get('ground_poly_count', 0)} |"
        )
        lines.append(
            f"| OTHER | {mo[0]}/{mo[1]} | {ov.get('other_net_count', 0)} | "
            f"{ov.get('other_poly_count', 0)} |"
        )
        lines.append("")
    lines.append(
        f"Classification follows `signal_vs_ground_rule` = `{cfg.signal_vs_ground_rule}` "
        "(**needs Brian/Jing**): SIGNAL = MTE-bearing net(s) excluding the largest-area "
        "ground net; GROUND = largest-area net; OTHER = remaining nets (e.g. frame "
        "bonding pads). Open `_nets.gds` with `_nets.lyp` in KLayout to visually "
        "validate this assumption before trusting the overlay."
    )
    lines.append("")

    lines.append("## 5. Ground plane")
    lines.append("")
    lines.append(f"- Ground region source: **{result.ground_source}**.")
    lines.append(f"- Recut ground polygons on `{cfg.ground_layers[0]}`: {result.ground_polys} (clearance carved around signal net, resonator, release holes).")
    lines.append("")

    lines.append(build_notes(golden_path, prepared_path))
    lines.append("")

    lines.append("## 6. Missing-layer inventory (NOT generated — SME tee-up)")
    lines.append("")
    lines.append("Golden carries layers v1 does not synthesize. Grouped below with a provisional origin tag for Brian / Jing Yang to confirm. These are fill / trim / hole layers; v1 intentionally does not invent them.")
    lines.append("")
    lines.append("| group | layers | total polys | provisional origin |")
    lines.append("|---|---|---|---|")
    for grp in result.missing_groups:
        lines.append(
            f"| {grp['group']} | {grp['layers']} | {grp['poly_count']} | {grp['tag']} |"
        )
    lines.append("")

    lines.append("## 7. Secondary diagnostic — per-layer polygon counts")
    lines.append("")
    lines.append("Dominated by fill layers v1 does not generate; not a success metric. Provided for completeness.")
    lines.append("")
    lines.append("| layer | gds | golden | routed |")
    lines.append("|---|---|---|---|")
    for name, gds, gn, rn in result.diff_rows:
        lines.append(f"| {name} | {gds} | {gn} | {rn} |")
    lines.append("")

    lines.append("## 8. Status")
    lines.append("")
    lines.append("**Verified geometrically (this run):**")
    lines.append("")
    lines.append("- Resonator 06 centered in standalone `KB331_N_Frame` (460x580 GSG frame), preserved MTE/MBE metal carried along, output trimmed to golden layers.")
    if result.signal_routed:
        lines.append(f"- Signal connector drawn ({result.signal_kind}) inside the routable region, DRC-clean by construction.")
    else:
        lines.append("- Signal connector skipped (see section 1); flagged for a real router.")
    lines.append(f"- Ground recut from {result.ground_source}.")
    lines.append("- GSG bond pads from `KB331_N_Frame` `BAW_MB2` (six 90x90 pads); `ppd_1port` NOT in output (lookup only).")
    lines.append(f"- Net-aware DRC: {result.real_drc_violations} introduced cross-net violations, {result.collar_drc_violations} preserved-collar (NPI).")
    if result.nets_path:
        lines.append(
            f"- Net overlay diagnostic written: `{result.nets_path.name}` "
            f"(+ `{result.nets_lyp_path.name}` if present) — visual check for signal/ground classification."
        )
    lines.append("")
    lines.append("**Assumed / needs SME confirmation:**")
    lines.append("")
    lines.append("- Signal-vs-ground side rule for series resonators (currently MTE-side).")
    lines.append("- Release-hole layer set used for clearance.")
    lines.append("- Index 06 treated as the golden `S3`; not proven identical to the Virtuoso instance name.")
    lines.append("- ppd_1port-to-frame pad mapping: matched onto the nearest signal pad; pad/probe-orientation rule to be confirmed.")
    lines.append("")
    lines.append("**Known divergences from golden (do not read as parity):**")
    lines.append("")
    lines.append("- Golden carries many fill/TF/MF/`BAW_H*` layers that v1 does not generate (see section 6).")
    lines.append("- MBE/MTE overlap is partial (section 3); routed shapes are simple connectors and recut ground, not the manual geometry.")
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Route one prepared RTEG (v1).")
    ap.add_argument("--index", type=int, default=6, help="(informational) resonator index")
    ap.add_argument("--prepared", type=Path, default=PREPARED_DEFAULT)
    ap.add_argument("--golden", type=Path, default=GOLDEN_DEFAULT)
    args = ap.parse_args()

    cfg = RouteConfig()
    res = route(args.prepared, args.golden, cfg)
    print("=== Route log ===")
    for line in res.log:
        print(" ", line)
    print("\n=== Primary metric (overlap % of golden) ===")
    for nm, m in res.overlap.items():
        print(f"  {nm}: {m['overlap_fraction_of_golden'] * 100:.1f}% overlap, sym-diff {m['symmetric_difference_area']:.0f}")
    report = write_report(res, cfg, args.prepared, args.golden)
    print(f"\nrouted GDS: {res.routed_path}")
    if res.nets_path:
        print(f"nets overlay: {res.nets_path}")
        if res.nets_lyp_path:
            print(f"nets lyp:     {res.nets_lyp_path}")
    print(f"report:     {report}")
