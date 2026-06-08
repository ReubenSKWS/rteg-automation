# Python pipeline — R-tag automation

This folder is the Python side of the R-tag project: automating per-resonator test layouts for BAW filters. The end goal is to take a filter GDS and output DRC-clean R-tag GDS files (probe pads + preserved metal + routing + vias). See `../CLAUDE.md` for full scope and constraints.

Today this folder handles **reading inputs, identifying resonators, and exporting draft RTEG layouts** (one GDS per resonator). Frame manipulation, routing, and DRC are not implemented yet.

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
| **`KB331_N_Frame.gds`** | R-tag frame template (probe pads + frame). Used by `build_rteg.py`. |
| **`layermap`** | Skyworks layer-name table. Maps names like `BAW_MBE` to GDS layer numbers `(2, 0)`. |

| Folder | What it is |
|---|---|
| **`example_output/`** | Ground truth reference layouts (read-only; never written by Python). |
| **`draft_output/`** | Python-generated draft RTEG GDS files (one per resonator). |

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
| `build_rteg.py` | Exports one isolated resonator per GDS to `draft_output/` (no frame/vias/metal yet) to verify separation is correct. |

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
| `Exported 8 resonator(s)` | One GDS per resonator in `draft_output/` — resonator only, at origin |
| `master=...` | Which resonator cell was extracted |
| `filter@=(282.6, 183.1)` | Where it sat on the original filter die |
| `rotation=... deg` | Orientation preserved from the filter placement |

Open each `.gds` in a layout viewer and confirm you see a single resonator geometry (no frame or metal).

---

## Where this fits in the project

```
Filter GDS + frame template + layermap
        │
        ├── layermap.py      → layer name lookups
        ├── inspect_refs.py  → sanity-check the GDS export
        ├── separate.py      → resonator / via identification
        └── build_rteg.py    → draft RTEG per resonator → draft_output/
                │
                ▼
        [future] frame/metal manipulation, routing, DRC
```

| Done today | Not built yet |
|---|---|
| Read GDS and layermap | Frame trim properties and probe-pad labels |
| Identify resonators, vias, splits | Custom signal/ground routing |
| Export isolated resonator GDS per piece | Frame, vias, metal, routing, DRC |

The SKILL script (`rdsBawTEGAutoFromTemp.il`) already does the full flow in Virtuoso — copy template, place resonator, copy metal/vias, update labels. Python will eventually replace that end-to-end.
