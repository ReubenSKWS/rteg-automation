#!/usr/bin/env python3
"""One-shot patch for single_run.ipynb orientation-based step 5 rebuild."""
from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parents[1] / "single_run.ipynb"


def set_cell(nb: dict, idx: int, source: str, cell_type: str = "markdown") -> None:
    nb["cells"][idx]["cell_type"] = cell_type
    nb["cells"][idx]["source"] = source.splitlines(keepends=True)
    nb["cells"][idx].pop("outputs", None)
    nb["cells"][idx].pop("execution_count", None)


def main() -> None:
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))

    set_cell(
        nb,
        0,
        """# R-tag pipeline — single run walkthrough

This notebook runs the **Python R-tag (RTEG) workflow** for the KB331 sample filter.

**Manual reference:** Jing Yang's SKILL flow in [`../rdsBawTEGAutoFromTemp.il`](../rdsBawTEGAutoFromTemp.il)  
**Documentation:** [`../README.md`](../README.md) · [`../CLAUDE.md`](../CLAUDE.md)

Run all cells top-to-bottom from the `python_code/` directory.

| Step | Section | Source file(s) | Primary functions |
|------|---------|----------------|-------------------|
| 1 | Setup / inputs | `layermap.py` | `load_layermap` |
| 2.1 | Layermap | `layermap.py` | `load_layermap` |
| 2.2 | Inspect refs | `inspect_refs.py` | `inspect_gds` |
| 2.3 | Identify | `separate.py` | `identify` |
| 3 | PPD + orientation placement | `prep_resonator_ppd.py`, `rteg_orientation.py`, `rteg_collect.py` | `prep_resonator_ppd`, `analyze_orientation`, `preserved_collars_at_shift` |
| 4 | Die frame | `prep_rteg_frame.py`, `export_gds.py` | `prep_rteg_in_frame`, `export_gds` |
| 5.1 | Collect roles | `rteg_collect.py` | `collect_geometry_roles` |
| 5.2 | Classify | `rteg_orientation.py`, `rteg_classify.py` | `collect_orientation_inputs`, `classify_nodes` |
| 5.3 | Build MTE signal | `rteg_signal.py`, `rteg_mte_route.py` | `build_signal_net`, `find_intercept_point`, `union_mte_net` |
| 5 export | MTE GDS | `rteg_signal.py`, `export_gds.py` | `export_signal_rteg_gds` |
""",
    )

    set_cell(
        nb,
        5,
        """# Ensure all referenced input files exist; abort on missing inputs

input_files = {
    "Filter layout": FILTER,
    "Frame template": FRAME,
    "Probe device": PPD,
    "Layer table": LAYERMAP,
}

input_roles = {
    "Filter layout": "Clean hierarchical filter GDS — resonators + connect metal",
    "Frame template": None,
    "Probe device": "ppd_1port — GSG pad reference",
    "Layer table": "Skyworks name → GDS (layer, datatype)",
}

rows = []
frame_size_str = "unknown size"

for label, path in input_files.items():
    if not path.exists():
        raise FileNotFoundError(f"Missing required input: {label} ({path})")
    size = f"{path.stat().st_size:,} B"
    rows.append({"file": label, "path": path.name, "exists": True, "size": size, "role": input_roles[label]})

frame_lib = gdstk.read_gds(FRAME)
frame_cell = frame_lib.top_level()[0]
frame_bb = frame_cell.bounding_box()
if frame_bb is not None:
    (fx0, fy0), (fx1, fy1) = frame_bb
    frame_size_str = f"{fx1 - fx0:.1f}×{fy1 - fy0:.1f} µm"

for row in rows:
    if row["file"] == "Frame template":
        row["role"] = f"{frame_size_str} GSG probe frame (six BAW_MB2 pads)"

display(pd.DataFrame(rows))
""",
        "code",
    )

    set_cell(
        nb,
        15,
        """### 3 — PPD + orientation placement

**Files:** `src/prep_resonator_ppd.py`, `src/rteg_orientation.py`, `src/rteg_collect.py`

**Entry points:** `prep_resonator_ppd` (with `identification` + `layermap`) → `preserved_collars_at_shift` → `analyze_orientation` → extra `orientation_shift` on placement.

For each row in `res_df`, combine the resonator with the GSG PPD frame (`GSG_frame.gds`):
center on the template, nudge for pad / release-hole clearance, then apply collar-orientation shift.
""",
    )

    set_cell(
        nb,
        16,
        """from IPython.display import HTML, display

from src.prep_resonator_ppd import (
    MIN_RELEASE_HOLE_CLEARANCE_UM,
    assemblies_summary_df,
    prep_resonator_ppd,
)

ppd_assemblies = prep_resonator_ppd(
    res_df,
    res_list,
    PPD,
    identification=identification,
    layermap=layermap,
)
display(assemblies_summary_df(ppd_assemblies))
""",
        "code",
    )

    set_cell(
        nb,
        26,
        """### 5.1 — Collect geometry roles

**Files:** `src/rteg_collect.py`

**Entry points:** `collect_geometry_roles`

Splits the framed layout into typed polygon sets (ground plates, preserved metal, release holes, frame boundary). No net assignment here — step 5.2 classifies signal vs ground from collar orientation.
""",
    )

    set_cell(
        nb,
        28,
        """### 5.2 — Classify GSG nodes by collar orientation

**Files:** `src/rteg_orientation.py`, `src/rteg_classify.py`, `src/rteg_collect.py`

**Entry points:** `collect_orientation_inputs` → `classify_nodes`

Signal terminal (**MTE** vs **MBE**) and signal pad band come from where preserved collar metal faces the GSG pads — not from `res_type`.

| Field | Meaning |
|-------|---------|
| `signal_terminal` | `MTE` when MTE collar faces the signal pad; else `MBE` (no MTE draw) |
| `signal_pad_band` | GSG band the collar faces |
| `signal_drawable` | `True` only when `signal_terminal == "MTE"` |
| `method` | always `orientation` |
""",
    )

    set_cell(
        nb,
        29,
        """from src.rteg_classify import classify_nodes, classification_summary_table
from src.rteg_collect import collect_orientation_inputs

all_classify: dict[int, object] = {}
classify_overview_rows: list[dict[str, object]] = []
classify_detail_rows: list[dict[str, object]] = []

for idx, roles in all_roles.items():
    res = identification.resonators[idx]
    orientation = collect_orientation_inputs(
        rteg_assemblies[idx],
        res,
        identification,
        layermap,
        ground_plates=roles.ground_plates,
        config=COLLECT_CONFIG,
    )
    classification = classify_nodes(
        roles.ground_plates,
        roles.preserved,
        orientation=orientation,
        res_type=res.res_type,
    )
    all_classify[idx] = classification
    collar = classification.collar_orientation
    by_band = classification.by_band()
    classify_overview_rows.append(
        {
            "index": idx,
            "inst_name": roles.inst_name,
            "res_type": res.res_type,
            "method": classification.method,
            "signal_terminal": classification.signal_terminal,
            "signal_pad_band": classification.signal_pad_band,
            "signal_drawable": classification.signal_drawable,
            "collar_axis": collar.axis,
            "facing_pad": collar.facing_pad,
            "top": by_band["top"].net,
            "center": by_band["center"].net,
            "bottom": by_band["bottom"].net,
            "note": classification.note,
        }
    )
    classify_detail_rows.extend(
        classification_summary_table(
            classification,
            index=idx,
            inst_name=roles.inst_name,
            res_type=res.res_type,
        )
    )

classify_overview_df = pd.DataFrame(classify_overview_rows).sort_values("index")
classify_df = pd.DataFrame(classify_detail_rows)

print(f"Classified {len(all_classify)} resonators\\n")
display(classify_overview_df)
print("\\nPer-band detail (all resonators):")
display(classify_df)

for idx, classification in all_classify.items():
    assert classification.method == "orientation"
    assert classification.signal_terminal in ("MTE", "MBE")
    assert classification.signal_drawable == (classification.signal_terminal == "MTE")

print(f"\\nOrientation classification checks passed for all {len(all_classify)} resonators")
""",
        "code",
    )

    set_cell(
        nb,
        30,
        """### 5.3 — Build signal MTE net

**Files:** `src/rteg_signal.py` (orchestrator), `src/rteg_mte_route.py` (intercept / span / union)

**Entry points:** `build_signal_net` → `find_intercept_point`, `build_pad_linear_strip`, `build_linear_span`, `union_mte_net`, `check_mte_vs_ground_drc`

**Layer:** all new MTE on `BAW_MTE` via `layermap.pair(config.mte_layer)` — typically `(5, 0)` for KB331.

When `signal_drawable` is True: span preserved MTE to the classified signal pad with a full-width pad strip and straight connector (`shape_name = linear_span`). MBE-terminal indices produce an empty net (classification only).
""",
    )

    set_cell(
        nb,
        31,
        """from src.rteg_signal import (
    SignalBuildConfig,
    build_signal_net,
    signal_net_summary_table,
)

SIGNAL_CONFIG = SignalBuildConfig()
mte_pair = layermap.pair(SIGNAL_CONFIG.mte_layer)

all_signal: dict[int, object] = {}
signal_overview_rows: list[dict[str, object]] = []
signal_detail_rows: list[dict[str, object]] = []

for idx, roles in all_roles.items():
    res = identification.resonators[idx]
    classification = all_classify[idx]
    signal = build_signal_net(
        roles.preserved,
        classification,
        roles.ground_plates,
        layermap,
        config=SIGNAL_CONFIG,
        release_holes=roles.release_holes,
    )
    all_signal[idx] = signal
    intercept = signal.endpoints.metal_point
    mte_layers = {(p.layer, p.datatype) for p in signal.net_polygons}
    summary = signal.summary()
    signal_overview_rows.append(
        {
            "index": idx,
            "inst_name": roles.inst_name,
            "res_type": res.res_type,
            "signal_terminal": classification.signal_terminal,
            "collar_axis": classification.collar_orientation.axis,
            "facing_pad": classification.collar_orientation.facing_pad,
            "signal_pad_band": classification.signal_pad_band,
            "intercept_xy": f"({intercept[0]:.1f},{intercept[1]:.1f})",
            "shape": summary["shape"],
            "drc_clean": summary["is_success"],
            "min_spacing_um": summary["min_ground_spacing_um"],
            "mte_layer": str(next(iter(mte_layers))) if mte_layers else str(mte_pair),
            "n_net_polygons": summary["n_net_polygons"],
            "reaches_pad": summary["reaches_pad"],
            "drc_violations": summary["drc_violations"],
        }
    )
    for row in signal_net_summary_table(signal):
        row["index"] = idx
        row["inst_name"] = roles.inst_name
        row["res_type"] = res.res_type
        signal_detail_rows.append(row)

signal_overview_df = pd.DataFrame(signal_overview_rows).sort_values("index")
signal_detail_df = pd.DataFrame(signal_detail_rows)

print(f"Built signal (MTE) nets for {len(all_signal)} resonators\\n")
display(signal_overview_df)
print("\\nSignal net detail (all resonators):")
display(signal_detail_df)

for idx, signal in all_signal.items():
    classification = all_classify[idx]
    if not classification.signal_drawable:
        assert signal.net_polygons == []
        assert signal.connector.shape_name == "none"
        continue
    assert signal.connector.shape_name == "linear_span"
    assert signal.n_net_polygons > 0
    for poly in signal.net_polygons:
        assert (poly.layer, poly.datatype) == mte_pair, (
            f"[{idx}] net polygon on {(poly.layer, poly.datatype)}, expected {mte_pair}"
        )

drc_flags = signal_overview_df[~signal_overview_df["drc_clean"]]
print(f"\\nLayer + connectivity checks passed for all {len(all_signal)} resonators")
if not drc_flags.empty:
    print(f"DRC flags on {len(drc_flags)} resonator(s) (MTE vs ground MBE):")
    display(
        drc_flags[
            ["index", "inst_name", "res_type", "shape", "min_spacing_um", "drc_violations"]
        ]
    )
else:
    print("No MTE/ground DRC flags")
""",
        "code",
    )

    NOTEBOOK.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Patched {NOTEBOOK}")


if __name__ == "__main__":
    main()
