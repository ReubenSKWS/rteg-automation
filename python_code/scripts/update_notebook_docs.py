#!/usr/bin/env python3
"""Refresh single_run.ipynb markdown cells to match implemented pipeline."""
from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parents[1] / "single_run.ipynb"

MARKDOWN: dict[int, str] = {
    0: """# R-tag pipeline — single run walkthrough

End-to-end **KB331** sample: filter GDS → per-resonator RTEG layouts with MBE/MTE routing.

**Docs:** [README](../README.md) · [CLAUDE](../CLAUDE.md) · run top-to-bottom from `python_code/`.

| Step | What it does | Main call |
|------|----------------|-----------|
| 1 | Validate inputs | layermap + file check |
| 2 | Find resonators / vias | `identify` |
| 3 | Center resonator in GSG PPD | `prep_resonator_ppd` |
| 4 | Place in die frame + export framed GDS | `prep_rteg_in_frame`, `export_gds` |
| 5.1–5.4 | MTE signal: collect → classify → extend → pad stretch | see §5 cells |
| 6.1–6.3 | MBE signal + ground filler | see §6 cells |

**KB331 split (8 resonators):** `center_pad` MTE route → indices **1, 3, 4, 6** · `collar_extend` MBE signal → **0, 2, 5, 7**.
""",
    2: """## Define inputs

Set paths to the filter GDS, die frame, GSG probe template, and Skyworks layermap. All paths are under `input_files/`. The next code cell assigns `FILTER`, `FRAME`, `PPD`, `LAYERMAP`.
""",
    4: """## 1. Process inputs

**~30 s read**

Confirms all four input files exist and prints a short inventory (size + role). Also reads the frame template bbox so you know the probe window size before placement.

**Output:** sanity-check table — aborts if anything is missing.
""",
    6: """## 2. Selection

**~30 s read**

Prepare for resonator extraction: load the layermap, inspect GDS hierarchy, then identify which instances in the filter become R-tags.

| Sub-step | Module | Purpose |
|----------|--------|---------|
| 2.1 | `layermap.py` | Name ↔ GDS layer/datatype |
| 2.2 | `inspect_refs.py` | Hierarchy / reference listing |
| 2.3 | `separate.py` | Resonator + via identification |

**Output:** `layermap`, `res_df`, `res_list`, `via_df`, `identification`.
""",
    7: """### 2.1 — `layermap.py`

**~30 s read**

Loads `input_files/layermap` so later steps refer to layers by Skyworks names (`BAW_MBE`, `BAW_MTE`, …) instead of raw GDS numbers.

**Call:** `load_layermap(LAYERMAP)` → `layermap` object with `.pair(name)` lookups.
""",
    9: """### 2.2 — `inspect_refs.py`

**~30 s read**

Walks the filter GDS hierarchy: cell references, labels, and bounding boxes. Quick sanity check that resonator masters and parent cells look like the expected KB331 structure before automated identification.

**Call:** `inspect_gds(FILTER)` (optional for frame/PPD too).
""",
    11: """### 2.3 — `separate.py`

**~30 s read**

Finds placed resonators under the filter parent (`series*`, `shunt*`, `rcap*`, `mimcap*` masters) and `vtb` vias. Returns dataframe rows plus live `Resonator` objects with placement transform preserved.

**Call:** `identify(FILTER)` → `identification` with `.resonator_rows()`, `.resonators`, `.via_rows()`.

**Output:** `res_df`, `res_list` — one row/object per R-tag candidate (KB331: 8).
""",
    14: """## 3. Separation

**~30 s read**

For each identified resonator, build an in-memory **PPD + resonator** assembly: GSG probe frame from `GSG_frame.gds` with the resonator centered and clearance-adjusted inside it. No die frame yet — that is step 4.

**Output:** `ppd_assemblies` — one per resonator, ready for frame placement.
""",
    15: """### 3 — PPD + orientation placement

**~30 s read**

**Calls:** `prep_resonator_ppd` (with `identification` + `layermap`) → optional orientation analysis.

1. **Center** resonator bbox on the PPD template.
2. **Clearance nudge** — ≥10 µm to GSG pad metal, ≥6 µm to release holes.
3. **Orientation shift** — small search to maximize pad clearance while keeping DRC-friendly placement.

**Output:** `ppd_assemblies[index].top_cell` — PPD ref + resonator ref in a scratch cell.
""",
    17: """### 3 — Preview (optional)

**~30 s read**

Optional SVG grid of each PPD+resonator assembly. Use to spot bad centering or pad collisions before die-frame placement. Code is commented out by default.
""",
    19: """## 4. Setting up

**~30 s read**

Place each PPD assembly into the **die frame template** (`KB331_N_Frame.gds`) and add the right-side MBE width filler. Margins are measured from the inner MBE ring cavity (not the outer 460×580 µm bbox).

- **X:** PPD/GSG frame left-aligned at 4% inner margin; wide resonators may get a **resonator-only** left shift (5 µm clearance to filler right edge).
- **Y:** assembly centered in 7% vertical margin band.
- **Filler:** MBE rectangle from inner-frame center line → right margin, full assembly height.

**Output:** `rteg_assemblies` — frame + placed PPD/resonator + filler per index.
""",
    20: """### 4 — Die frame placement

**~30 s read**

**Call:** `prep_rteg_in_frame(ppd_assemblies, FRAME)` → `rteg_assemblies`

PPD and resonator are placed as **separate references** so only the resonator moves when enforcing filler clearance (`resonator_frame_shift` on the assembly object).

Also exports **framed-only** GDS to `draft_output/original_rteg/` via `export_gds` (geometry through step 4, no routing metal yet).
""",
    24: """---

## 5. Routing (MTE signal)

**~30 s read**

Build per-resonator **MTE (layer 5/0)** signal paths: collect layout roles, decide routing strategy, draw collar lip extensions, then stretch to the center pad when applicable. Exports incremental GDS after major substeps.
""",
    25: """## 5. Routing — overview

| Step | Module | What you get |
|------|--------|--------------|
| 5.1 | `rteg_collect` | Ground plates, preserved filter metal, release holes, body MTE |
| 5.2 | `rteg_classify` | Signal vs ground nodes; `mte_route_target` |
| 5.3 | `rteg_mte_extensions` | 14 µm lip extension from collar mouth |
| 5.4 | `rteg_mte_route` | Pad stretch for `center_pad` only |
| export | `export_mte_extensions_gds` | Combined MTE (+ later MBE) GDS per index |

**Routing split:** indices **1, 3, 4, 6** → MTE to center pad · **0, 2, 5, 7** → MTE extension only (MBE signal in step 6).
""",
    26: """### 5.1 — Collect geometry roles

**~30 s read**

**Call:** `collect_geometry_roles(assembly, res, identification, layermap)` → `all_roles[index]`

Snapshots everything routing needs in **RTEG world coordinates**: GSG pad MBE, step-4 filler plate, preserved filter interconnect (MBE/MTE), resonator body metal, release holes, inner frame boundary.

Preserved MTE includes `connectMTE` tabs; series parts may also retain the stadium-adjacent collar (e.g. index 6 → areas 911 + 5191 µm²).
""",
    28: """### 5.2 — Classify GSG nodes

**~30 s read**

**Calls:** `collect_orientation_inputs` → `classify_nodes` → `all_classify[index]`

Labels top/center/bottom GSG nodes as signal or ground and sets **`mte_route_target`**:

- **`center_pad`** — mouth tab is closer to the center signal pad than the body center is (route MTE to pad in 5.4).
- **`collar_extend`** — otherwise (MBE signal route in 6.1).

KB331: indices 1, 3, 4, 6 = `center_pad`; 0, 2, 5, 7 = `collar_extend`.
""",
    30: """### 5.3 — MTE extensions

**~30 s read**

**Call:** `build_mte_extensions(all_roles, layermap, mte_cfg)` → one 14 µm lip extension per resonator.

Pipeline per index: pick mouth collar tab → find outward lip edge → extrude rectangle merged into collar. **`is_connected`** checks overlap + mouth coverage.

Golden baseline: **index 6** — extension on collar 911, stadium 5191. Shunt tabs: indices 0/1.

**Output:** `all_mte[index].extension` on MTE layer; tables show intercepts and connection status.
""",
    32: """### 5.3 — Export MTE extensions

**~30 s read**

**Call:** `export_mte_extensions_gds(rteg_assemblies, all_mte, MTE_OUT, layermap=...)`

Writes one GDS + `.lyp` per resonator with frame, placed geometry, and 5.3 MTE extensions (no pad stretch yet). Open in KLayout with the matching `.lyp` for layer names.

Later exports (after 5.4 / 6.x) pass `mbe_extensions` and `mbe_bodies` to add routing metal incrementally.
""",
    34: """### 5.4 — Stretch MTE to center signal pad

**~30 s read**

**Call:** `build_mte_pad_routes(all_roles, all_classify, all_mte, layermap, mte_route_cfg)`

**Gate:** `mte_route_target == "center_pad"` only (KB331 indices **1, 3, 4, 6**).

Morphs the 5.3 extension outward cap to span the center signal pad height while keeping collar mouth vertices fixed. Re-export GDS in the next cell to see full MTE signal paths.

**Config:** `MteRouteConfig` — `pad_touch_overlap_um`, `min_pad_overlap_um2`.
""",
    36: """## Step 6 — MBE routing

**~30 s read**

When MTE does **not** face the center pad (`collar_extend`), **MBE (layer 2/0)** carries signal (6.1) and ground filler (6.2). When MTE routes to the pad (`center_pad`), step **6.3** routes the step-4 ground filler around MTE keepouts instead.

| Step | Applies to | Purpose |
|------|------------|---------|
| 6.1 | 0, 2, 5, 7 | MBE curve from signal pad → preserved collar |
| 6.2 | 0, 2, 5, 7 | MBE cap + carved ground filler bridge |
| 6.3 | 1, 3, 4, 6 | Carve/route ground filler with MTE clearance |

### 6.1 — MBE signal route (pad → collar)

**Gate:** `mbe_extension_applies` → `build_mbe_extensions`

Select preserved MBE collar, ray-cast from pad corners, trace collar mouth fillet, draw `BAW_MBE` connector (`all_mbe[index].routed_net`). Re-export GDS to add MBE signal polys.
""",
    38: """## Step 6.2 — MBE ground body (`collar_extend` only)

**~30 s read**

**Gate:** `mbe_body_collar_extend_applies` → `build_mbe_body_collar_extends` — KB331 indices **0, 2, 5, 7**.

1. **MBE cap** on outer half of 5.3 MTE extension (shifted 3.5 µm outward onto filler).
2. **Keepouts** — body MTE stadium, release holes, 5.3 MTE extension, 6.1 MBE signal; boolean-carve step-4 filler.
3. **Bridge** — reconnect carved filler to cap across stadium gap.
4. **Export** — cap + filler pieces as separate `BAW_MBE` polygons; raw step-4 rectangle stripped.

Re-export GDS after 6.2 to refresh routed output folder.
""",
    40: """## Step 6.3 — MBE ground filler (`center_pad` only)

**~30 s read**

**Gate:** `mbe_body_center_pad_applies` → `build_mbe_body_center_pads` — KB331 indices **1, 3, 4, 6**.

Carves the step-4 **MBE width filler** with clearance to MTE body, 5.3 extension, and pad route (layer 5/0). Left edge follows the preserved MBE collar; top/right/bottom are trimmed back from MTE routes (~2 µm + 1 µm trim margin) so no pinch corners sit on the extension-to-pad junction.

**Output:** one connected `BAW_MBE` filler polygon per index (collar metal absorbed into filler export). Re-export GDS after 6.3.
""",
}


def main() -> None:
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    for idx, text in MARKDOWN.items():
        if idx >= len(nb["cells"]):
            raise IndexError(f"Cell {idx} out of range ({len(nb['cells'])} cells)")
        if nb["cells"][idx]["cell_type"] != "markdown":
            raise TypeError(f"Cell {idx} is {nb['cells'][idx]['cell_type']!r}, expected markdown")
        nb["cells"][idx]["source"] = text.splitlines(keepends=True)
        nb["cells"][idx].pop("outputs", None)
        nb["cells"][idx].pop("execution_count", None)
    NOTEBOOK.write_text(json.dumps(nb, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Updated {len(MARKDOWN)} markdown cells in {NOTEBOOK.name}")


if __name__ == "__main__":
    main()
