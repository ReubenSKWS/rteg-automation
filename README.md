# Python pipeline — R-tag automation

This folder is the Python side of the R-tag project: automating per-resonator test layouts for BAW filters. The end goal is to take a filter GDS and output DRC-clean R-tag GDS files (probe pads + preserved metal + routing + vias). See `../CLAUDE.md` for full scope and constraints.

Today this folder handles **reading inputs, identifying resonators, SKILL-aligned RTEG preparation for all 8 resonators, and a frozen first-pass router** for golden S3. Full multi-resonator routing, fill-layer generation, and sign-off DRC are not implemented yet.

The Python logic is ported from Jing Yang's Cadence SKILL script [`../rdsBawTEGAutoFromTemp.il`](../rdsBawTEGAutoFromTemp.il) — especially the resonator-finding rules (lines 178–179) and split/cascade grouping (lines 216–267). That script runs inside Virtuoso and already creates full RTEG cells; Python is rebuilding the same pipeline outside Virtuoso.

---

## Setup

```powershell
cd python_code
pip install gdstk
```

---

## Inputs

| File | What it is |
|---|---|
| **`KB331_N_01_clean.gds`** | Filter layout exported from Virtuoso. Must be a **clean** (hierarchical) export — not dense/flattened. A sample copy lives in this folder. |
| **`KB331_N_Frame.gds`** | Full R-tag frame (460×580 µm, matches the golden). Frame template for `prepare_rteg.py` and the route pipeline. |
| **`ppd_1port.gds`** | Single-port probe-pad device (`ppd_1port`, 240×225 µm), same cell the SKILL flow uses. Included in prepared output; `route_rteg.py` uses it for signal-pad launch lookup. |
| **`resonator_inst_map.json`** | Optional index → instName overrides (e.g. `"6": "S3"` for golden anchor). Inferred names otherwise come from sorted filter placement. |
| **`layermap`** | Skyworks layer-name table. Maps names like `BAW_MBE` to GDS layer numbers `(2, 0)`. |

| Folder | What it is |
|---|---|
| **`example_output/`** | Ground truth reference layouts (read-only; never written by Python). Holds `KB331_N_01_RTEG1_S3.gds`, the golden the router is compared against. |
| **`draft_output/`** | Python-generated draft RTEG GDS files and the route report. |

---

## Run the scripts

All scripts default to the sample files above. Run from `python_code/`:

```powershell
python layermap.py
python inspect_refs.py
python separate.py
python build_rteg.py
```

| Script | What it does |
|---|---|
| `layermap.py` | Parses `layermap` into name ↔ (layer, datatype) lookups. Needed before any step that reads or writes geometry by layer name. |
| `inspect_refs.py` | Debug view of the GDS — lists every placed component (references), where it sits, and any labels. Use when counts look wrong or instance names are missing. |
| `separate.py` | Finds resonators, groups splits/cascades, and counts vias. This is the main identification step toward R-tag generation. |
| `rteg_skill.py` | Shared helpers: `build_foundation` (frame + centered ppd), resonator placement, inst-name inference, `connect_backup` loader. Used by `prepare_rteg.py` and `build_rteg.py`. |
| `build_rteg.py` | Exports one isolated resonator per GDS to `draft_output/` (frame + ppd + centered resonator) to verify separation. |

---

## SKILL-aligned prepare (all 8) + frozen routing (S3 v1)

Pre-routing assembly: template (frame + `ppd_1port`), resonator centered in the frame, preserved metal from `connect_backup` (MTE/MBE fallback). See [`workflow.md`](workflow.md) for the full flow.

```powershell
python prepare_rteg.py --all
python inspect_golden.py
```

Routing (`route_rteg.py`) is unchanged — pass the new prepared path when resuming:

```powershell
python route_rteg.py --prepared draft_output/KB331_N_01_RTEG1_S3_prepared.gds
```

| Script | What it does | Output |
|---|---|---|
| `prepare_rteg.py` | Builds standalone RTEGs for all 8 resonators (or `--index N`). Resonator centered in frame, preserved metal, vias, golden layer trim. | `draft_output/KB331_N_01_RTEG1_{instName}_prepared.gds` |
| `inspect_golden.py` | Read-only diff of golden vs prepared. | prints NOTES; `--prepared` / `--golden` flags |
| `geometry.py` | Helper library (not run directly): booleans, routable region, nets, golden metrics. | — |
| `route_rteg.py` | **Frozen v1** — signal route, ground recut, net-aware DRC, report. Defaults still reference old `06_series` paths. | `*_routed.gds`, `ROUTE_S3_REPORT.md` |

**Scope of v1 (read `ROUTE_S3_REPORT.md` for the full picture):** the router
draws a simple signal connector, recuts the real `KB331_N_Frame` ground, and
checks signal-vs-ground spacing per net. The **headline metric is MBE/MTE
overlap area vs the golden** (not layer-count match, which is dominated by fill
layers v1 does not generate). It does not claim parity with the golden. The
signal connector is limited to straight / single-45° / one L-bend — anything
harder is logged as "needs real router" rather than detoured. Several inputs are
assumptions flagged for SME review: the signal-vs-ground side rule for series
resonators, the release-hole layer set, the `ppd_1port`-to-pad mapping, and
whether index 06 is exactly the Virtuoso `S3` instance. The golden's fill/`BAW_H*`/TF
layers are inventoried (grouped, tagged) for SME follow-up but never synthesized.

---

## Example output — how to read it

### `layermap.py`

```
Loaded 155 layers
  BAW_MBE: (2, 0)
  BAW_MTE: (5, 0)
  BAW_LABEL: (100, 0)
```

| Line | Meaning |
|---|---|
| `Loaded 155 layers` | Parsed 155 entries from `layermap` |
| `BAW_MBE: (2, 0)` | Layer name `BAW_MBE` = GDS layer **2**, datatype **0** |
| `BAW_MTE: (5, 0)` | Top-metal layer MTE is GDS layer 5 |

When you later copy or check metal polygons, you'll use these numbers to know which GDS layer is MBE vs MTE.

---

### `inspect_refs.py`

```
KB331_N_01: 17 references
   -> shuntq3_CDNS_780903262810 @ (282.6, 183.1)  rot=0.0  props=—
   -> seriesq3_CDNS_780903262811 @ (95.8, 145.1)  rot=1.57  props=—
   -> vtb3_CDNS_780903262813   @ (208.6, 127.4)  rot=4.71  props=—
   -> KB331_N_01_connectMTE    @ (0.0, 0.0)  rot=0.0  props=—
```

| Part | Meaning |
|---|---|
| `KB331_N_01: 17 references` | The filter cell has 17 placed sub-components |
| `-> shuntq3_...` | A **shunt resonator** placed at (282.6, 183.1) µm |
| `-> seriesq3_...` | A **series resonator** |
| `-> vtb3_...` | A **via** connecting MBE ↔ MTE |
| `-> KB331_N_01_connectMTE` | The filter's **interconnect metal** |
| `rot=1.57` | Rotation in radians (~90°). `0` = none, `3.14` ≈ 180°, `4.71` ≈ 270° |
| `props=—` | No Virtuoso instance name survived export (no `S1A`, `P3`, etc.) |

The cell you care about most is **`KB331_N_01`** — that's the filter die. Other cells like `KB331_N_Frame` are the probe-pad template frame.

---

### `separate.py`

```
GDS: ...\KB331_N_01_clean.gds
Cells with resonators: 1

KB331_N_01: 8 resonators, 6 groups, 4 vias
  shuntq3_CDNS_780903262810      shunt    @ (282.6, 183.1)
  seriesq3_CDNS_780903262811     series   @ (95.8, 145.1)
  ...
```

| Part | Meaning |
|---|---|
| `Cells with resonators: 1` | One filter-variant cell contains resonators |
| `8 resonators` | 8 testable pieces found (masters starting with `series`, `shunt`, `rcap`, or `mimcap`) |
| `6 groups` | Split/cascade families. Here mostly one resonator per group because instance names didn't survive GDS export |
| `4 vias` | Four `vtb` structures in that cell |
| Each line | Instance name (or master fallback) · type · position on the die |

This is the list the SKILL script uses to decide which RTEG cells to create (e.g. `KB331_N_01_RTEG1_S1A`).

---

### `build_rteg.py`

```
Filter: ...\KB331_N_01_clean.gds
Output: ...\draft_output

Exported 8 resonator(s):

  KB331_N_01_RTEG1_00_shunt.gds
    type=shunt  master=shuntq3_CDNS_780903262810
    filter@=(282.6, 183.1)  rotation=0.0 deg
  ...
```

| Part | Meaning |
|---|---|
| `Exported 8 resonator(s)` | One GDS per resonator: frame at top-left, ppd centered in frame, resonator at assembly center |
| `inst=S3` | Inferred or overridden Virtuoso-style instance name |
| `filter@=(282.6, 183.1)` | Where it sat on the original filter die |
| `rteg@=(228.2, 290.0)` | Resonator origin after placement shift (bbox center -> assembly center) |

Open each `.gds` in a layout viewer and confirm the ppd sits in the middle of the die frame and the resonator is centered in the overall cell.

---

### `route_rteg.py`

```
=== Route log ===
  resonator world bbox: (160.5, 235.5)-(299.5, 344.5)
  signal metal (BAW_MTE) polys near resonator: 4
  recut ground plane: 1 polys
  DRC self-check MBE vs MTE @ 14.0um: 3 violation polys
Golden diff: 26/95 layers match on count
```

| Part | Meaning |
|---|---|
| `resonator world bbox` | Where resonator 06 lands inside the frame |
| `recut ground plane: 1 polys` | The frame's full ground fill, carved back around the resonator/signal/release holes |
| `DRC self-check ... 3 violation polys` | MBE/MTE overlaps — here all within the connected resonator net (same net), not unconnected-spacing failures |
| `Golden diff: 26/95 layers match` | How many layers match the golden on polygon count; large mismatch is expected since v1 omits fill layers |

The detailed assumptions, golden NOTES, and per-layer diff table are written to `draft_output/ROUTE_S3_REPORT.md`.

---

## Where this fits in the project

```
Filter GDS + frame template + layermap
        │
        ├── layermap.py      → layer name lookups
        ├── inspect_refs.py  → sanity-check the GDS export
        ├── separate.py      → resonator / via identification
        ├── rteg_skill.py    → build_foundation, placement, naming, connect_backup
        ├── build_rteg.py    → draft RTEG per resonator → draft_output/
        │
        └── prepare_rteg.py --all → frame + ppd + resonator + metal + vias
                │            (geometry.py = boolean/offset/DRC helpers)
                ├── inspect_golden.py → golden vs prepared NOTES
                ▼
            route_rteg.py    → frozen v1 on S3 (pass --prepared for new names)
                ▼
        [future] fill layers, multi-resonator routing, sign-off DRC
```

| Done today | Not built yet |
|---|---|
| Read GDS and layermap | Fill/`BAW_H*`/TF layer generation |
| Identify resonators, vias, splits | Multi-resonator + split/cascade routing |
| Export isolated resonator GDS per piece | Split/cascade / Infra35 RTEGs |
| SKILL-aligned prepare for all 8 resonators | Confirmed signal/ground rule per resonator type |
| connect_backup path + MTE/MBE fallback | Full `{filter}_connect_backup` export from Virtuoso |
| Recut ground plane, naive signal route, DRC (S3 v1, frozen) | Multi-resonator routing + updated route defaults |

The SKILL script (`rdsBawTEGAutoFromTemp.il`) already does the full flow in Virtuoso — copy template, place resonator, copy metal/vias, update labels. Python will eventually replace that end-to-end.
