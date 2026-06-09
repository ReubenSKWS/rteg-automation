"""
Side-by-side inspection of the golden RTEG and our prepared routing input.

This is a read-only diagnostic: it answers "what differs" before any routing
logic is written. It emits a NOTES block (printed, and reused verbatim by the
route report) covering layer inventory, MBE/MTE metal extents, and frame bbox.

  golden   = example_output/KB331_N_01_RTEG1_S3.gds   (read-only ground truth)
  prepared = draft_output/KB331_N_01_RTEG1_S3_prepared.gds
"""
from __future__ import annotations

import argparse
from pathlib import Path

import gdstk

from layermap import LayerMap, load_layermap
from paths import DEFAULT_LAYERMAP

GOLDEN = Path(__file__).parent / "example_output" / "KB331_N_01_RTEG1_S3.gds"
PREPARED = (
    Path(__file__).parent / "draft_output" / "KB331_N_01_RTEG1_S3_prepared.gds"
)


def _find_prepared_top(prep_lib: gdstk.Library, prepared_path: Path) -> gdstk.Cell:
    """Resolve the prepared top cell from filename or RTEG1 cell name."""
    stem = prepared_path.stem
    if stem.endswith("_prepared"):
        expected = stem[: -len("_prepared")]
        match = next((c for c in prep_lib.cells if c.name == expected), None)
        if match is not None:
            return match
    rteg_cells = [c for c in prep_lib.cells if "_RTEG1_" in c.name]
    if len(rteg_cells) == 1:
        return rteg_cells[0]
    if rteg_cells:
        return max(rteg_cells, key=lambda c: len(c.references))
    raise ValueError(f"No prepared top cell found in {prepared_path}")


def layer_pair_counts(cell: gdstk.Cell) -> dict[tuple[int, int], int]:
    """(layer, datatype) -> polygon count, flattening all references."""
    counts: dict[tuple[int, int], int] = {}
    for poly in cell.get_polygons():
        key = (poly.layer, poly.datatype)
        counts[key] = counts.get(key, 0) + 1
    return counts


def metal_bbox(
    cell: gdstk.Cell, layermap: LayerMap, name: str
) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """Combined bounding box of all polygons on a named layer (flattened)."""
    if name not in layermap:
        return None
    layer, datatype = layermap.pair(name)
    polys = cell.get_polygons(layer=layer, datatype=datatype)
    if not polys:
        return None
    xs0 = min(p.bounding_box()[0][0] for p in polys)
    ys0 = min(p.bounding_box()[0][1] for p in polys)
    xs1 = max(p.bounding_box()[1][0] for p in polys)
    ys1 = max(p.bounding_box()[1][1] for p in polys)
    return (xs0, ys0), (xs1, ys1)


def _fmt_bbox(bbox) -> str:
    if bbox is None:
        return "none"
    (x0, y0), (x1, y1) = bbox
    return f"({x0:.1f}, {y0:.1f}) - ({x1:.1f}, {y1:.1f})"


def build_notes(golden_path: Path = GOLDEN, prepared_path: Path = PREPARED) -> str:
    """Build the NOTES block as a markdown-ish string."""
    layermap = load_layermap(DEFAULT_LAYERMAP)
    golden = gdstk.read_gds(golden_path).cells[0]
    prep_lib = gdstk.read_gds(prepared_path)
    prepared = _find_prepared_top(prep_lib, prepared_path)

    g_counts = layer_pair_counts(golden)
    p_counts = layer_pair_counts(prepared)
    only_golden = sorted(set(g_counts) - set(p_counts))
    only_prepared = sorted(set(p_counts) - set(g_counts))

    lines: list[str] = []
    lines.append("## NOTES — golden vs prepared")
    lines.append("")
    lines.append(f"- golden:   `{golden_path.name}` — {len(golden.get_polygons())} polys, {len(g_counts)} layer pairs")
    lines.append(f"- prepared: `{prepared_path.name}` — {len(prepared.get_polygons())} polys, {len(p_counts)} layer pairs")
    lines.append(f"- golden bbox: {_fmt_bbox(golden.bounding_box())}")
    lines.append(f"- prepared bbox: {_fmt_bbox(prepared.bounding_box())}")
    lines.append("")

    lines.append("### Metal extents (flattened)")
    for nm in ("BAW_MBE", "BAW_MTE"):
        g_n = g_counts.get(layermap.pair(nm), 0) if nm in layermap else 0
        p_n = p_counts.get(layermap.pair(nm), 0) if nm in layermap else 0
        lines.append(
            f"- {nm}: golden {g_n} polys {_fmt_bbox(metal_bbox(golden, layermap, nm))}"
            f" | prepared {p_n} polys {_fmt_bbox(metal_bbox(prepared, layermap, nm))}"
        )
    lines.append("")

    lines.append(f"### Layers in golden, absent from prepared ({len(only_golden)})")
    lines.append("These are routing/ground/fill layers the manual flow adds; v1 routes only MBE/MTE.")
    lines.append("")
    lines.append(_layer_table(only_golden, g_counts, layermap))
    lines.append("")

    lines.append(f"### Layers in prepared, absent from golden ({len(only_prepared)})")
    lines.append(_layer_table(only_prepared, p_counts, layermap) if only_prepared else "(none)")
    return "\n".join(lines)


def grouped_missing_layers(
    golden_path: Path = GOLDEN, prepared_or_routed_path: Path = PREPARED
) -> list[dict]:
    """
    Cluster golden-only layers (absent from the comparison file) into families
    with a provisional origin tag for SME review. Inventory only -- v1 does not
    generate these layers.
    """
    layermap = load_layermap(DEFAULT_LAYERMAP)
    golden = gdstk.read_gds(golden_path).cells[0]
    other = gdstk.read_gds(prepared_or_routed_path)
    other_cell = _find_prepared_top(other, prepared_or_routed_path)

    g_counts = layer_pair_counts(golden)
    o_counts = layer_pair_counts(other_cell)
    only_golden = sorted(set(g_counts) - set(o_counts))

    families: dict[str, dict] = {}
    for layer, dt in only_golden:
        name = layermap.name(layer, dt) or f"?({layer}/{dt})"
        group, tag = _classify_layer(name)
        fam = families.setdefault(group, {"group": group, "names": [], "poly_count": 0, "tag": tag})
        fam["names"].append(name)
        fam["poly_count"] += g_counts[(layer, dt)]

    out = []
    for fam in families.values():
        out.append(
            {
                "group": fam["group"],
                "layers": ", ".join(sorted(fam["names"])),
                "poly_count": fam["poly_count"],
                "tag": fam["tag"],
            }
        )
    return sorted(out, key=lambda f: (-f["poly_count"], f["group"]))


def _classify_layer(name: str) -> tuple[str, str]:
    """(group, provisional-origin-tag) for a golden-only layer name."""
    if name.startswith("BAW_NoMF") or name.startswith("BAW_NoTF"):
        return "No-series (mask exclusions)", "likely derived"
    if name.startswith("BAW_H"):
        return "H-series (hole/fill)", "likely derived (fill/trim/hole)"
    if name.startswith("BAW_MF"):
        return "MF-series (metal fill)", "likely copied from source / derived"
    if name.startswith("BAW_TF"):
        return "TF-series (trim fill)", "likely copied from source / derived"
    if name in ("BAW_TEG", "BAW_ORF", "BAW_LABEL") or name.endswith("LABEL"):
        return "TEG/ORF/label", "unknown -- SME"
    return "other", "unknown -- SME"


def _layer_table(
    pairs: list[tuple[int, int]],
    counts: dict[tuple[int, int], int],
    layermap: LayerMap,
) -> str:
    if not pairs:
        return "(none)"
    rows = ["| layer | gds | polys |", "|---|---|---|"]
    for layer, datatype in pairs:
        nm = layermap.name(layer, datatype) or "?"
        rows.append(f"| {nm} | {layer}/{datatype} | {counts[(layer, datatype)]} |")
    return "\n".join(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Compare golden vs prepared RTEG.")
    ap.add_argument("--golden", type=Path, default=GOLDEN)
    ap.add_argument("--prepared", type=Path, default=PREPARED)
    args = ap.parse_args()
    print(build_notes(args.golden, args.prepared))
