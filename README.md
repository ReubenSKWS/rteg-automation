# rTEG automation — Python pipeline

Automates **R-tag (RTEG) test layouts** for BAW filters at Skyworks: take a clean filter GDS and produce per-resonator test structures inside a GSG probe frame. The manual flow today runs in **Cadence Virtuoso** via Jing Yang's SKILL script [`rdsBawTEGAutoFromTemp.il`](rdsBawTEGAutoFromTemp.il). This repo rebuilds that flow in Python.

For scope, constraints, and domain context see [`CLAUDE.md`](CLAUDE.md).

---

## Status

| Step | Notebook section | Status |
|---|---|---|
| 1. Process inputs | Layermap + GDS sanity checks | Done |
| 2. Selection | Identify resonators and vias | Done |
| 3. Separation | Center resonator in GSG PPD frame | Done |
| 4. Setting up | Place assembly in die frame + export GDS | Done |
| 5. Routing | MBE ground plate merge | Done (v1) |
| 6. Verification | DRC-clean layout | Planned |

Steps 1–5 run end-to-end in [`python_code/single_run.ipynb`](python_code/single_run.ipynb) (step 5 starts at resonator index 5 by default).

---

## Setup

```powershell
cd python_code
pip install gdstk pandas
```

Open `single_run.ipynb` and run all cells top-to-bottom. The notebook resolves paths from `python_code/` (needs `input_files/` and `src/`).

---

## How to run

**Primary entry point:** `python_code/single_run.ipynb`

Optional CLI checks (from `python_code/`, with `src/` on `PYTHONPATH` or run via notebook path setup):

```powershell
python src/separate.py input_files/KB331_N_01.gds
python src/inspect_refs.py input_files/KB331_N_01.gds input_files/KB331_N_Frame.gds
```

---

## Pipeline (matches the notebook)

```mermaid
flowchart LR
    subgraph inputs [Inputs]
        filter[KB331_N_01.gds]
        frame[KB331_N_Frame.gds]
        ppd[GSG_frame.gds]
        lm[layermap]
    end

    subgraph step1 [Step 1]
        layermap[layermap.py]
        inspect[inspect_refs.py]
    end

    subgraph step2 [Step 2]
        sep[separate.py]
    end

    subgraph step3 [Step 3]
        ppdprep[prep_resonator_ppd.py]
    end

    subgraph step4 [Step 4]
        frameprep[prep_rteg_frame.py]
        export[export_gds.py]
    end

    lm --> layermap
    filter --> inspect
    filter --> sep
    sep --> ppdprep
    ppd --> ppdprep
    ppdprep --> frameprep
    frame --> frameprep
    frameprep --> export
    frameprep --> route[route_rteg.py + ground_merge.py]
    lm --> export
    lm --> route
    route --> export
    export --> draft[draft_output/*.gds + .lyp]
```

### Step 1 — Process inputs

Load the Skyworks layermap and confirm GDS hierarchy looks correct.

| Module | Role |
|---|---|
| `src/layermap.py` | Parse `input_files/layermap` → name ↔ `(layer, datatype)` |
| `src/inspect_refs.py` | List references and labels in filter, frame, and PPD GDS |

### Step 2 — Selection

Find resonators and vias under the filter parent cell.

| Module | Role |
|---|---|
| `src/separate.py` | `identify(filter_gds)` → `res_df`, `res_list`, `via_df` |

Identification rules match the SKILL script: masters starting with `series`, `shunt`, `rcap`, `mimcap`; vias with `vtb`.

### Step 3 — Separation

For each resonator, build an in-memory **PPD + centered resonator** assembly.

| Module | Role |
|---|---|
| `src/prep_resonator_ppd.py` | `prep_resonator_ppd(res_df, res_list, ppd_gds)` → `ppd_assemblies` |
| `src/rteg_utils.py` | Shared bbox / top-cell helpers |

Centering uses bbox alignment only (no scale). A 10 µm axis-aligned nudge keeps resonator MBE/MTE clear of GSG pad metal.

### Step 4 — Setting up

Place each PPD assembly in the die frame and export GDS.

| Module | Role |
|---|---|
| `src/prep_rteg_frame.py` | `prep_rteg_in_frame(ppd_assemblies, frame_gds)` → `rteg_assemblies` |
| `src/export_gds.py` | `export_gds(..., layermap=layermap)` → one GDS + `.lyp` per resonator |

Placement rules (inner MBE ring cavity, not the outer 460×580 bbox):

- **X:** left-aligned at 4% margin inside the inner frame
- **Y:** assembly bbox centered at 7% margin band
- **MBE filler:** rectangle from inner-frame center to the margined right edge, height = placed assembly bbox

Export writes only the reachable cell hierarchy (single top cell) and filters layers to the layermap. Open each `.gds` in KLayout with its matching `.lyp` for Skyworks layer names.

### Step 5 — Routing (MBE ground plate merge, v1)

The ground side is built as a **boolean plate merge**, not a wire. The outer GSG ground arms, the right-hand MBE filler plate, and the resonator's preserved `connectMBE` connector are all one ground net: the pipeline unions them, auto-bridges any residual gap, fuses the preserved metal, then carves the DRC keepouts (center signal + MTE at 14 µm, resonator MBE at 14 µm, resonator-neighborhood release holes at 6 µm) and verifies one connected, clean ground body touching both ground pads. The center signal pad (`BAW_MTE`) is a carve obstacle, never fused.

| Module | Role |
|---|---|
| `src/ground_merge.py` | Shared plate-merge pipeline: collect/precheck/union/bridge/connect/carve/verify (`GroundMergeConfig`, `run_ground_merge`) |
| `src/route_primitives.py` | Pure geometry: grow/boolean/spacing helpers (and route shapes, kept for signal pass) |
| `src/route_rteg.py` | `route_rteg_assemblies()` → `RtegRoutedAssembly` (carved `ground_body` + summary) |
| `src/route_search.py` | `RouteSearchConfig` + candidate search — **retained for the future signal/MTE pass**, not used by the ground merge |
| `src/agentic/` | Experimental LLM-driven plate merge over the same pipeline (see [`artifacts/AGENTIC_COMPARISON.md`](python_code/artifacts/AGENTIC_COMPARISON.md)) |

**Assumption register** — enforced in code and documented in module docstrings:

| ID | Assumption |
|---|---|
| A1 | GSG: outer top/bottom = ground (MBE), center = signal (MTE) |
| A2 | Ground v1 merges plates only; center signal pad is a carve obstacle, never fused |
| A3 | Preserved metal from `connectMBE` / `connect_backup`, `BAW_MBE` layer |
| A4 | Overlap window = resonator filter bbox + `preserved_overlap_margin_um` |
| A5 | Shifts translate resonator + preserved metal only (no rotation) |
| A6 | PPD, die frame, and filler plate fixed |
| A7 | Carve keepouts: signal/MTE +14 µm, resonator MBE +14 µm, release holes +6 µm (release holes filtered to the resonator neighborhood so pad-cavity `BAW_CAV` outlines are not carved) |
| A10 | Ground collar not inferred — preserved MBE fused directly into the body |
| A11 | Via at center pad flagged via `via_at_center_flag` (carved ground must not overlap the center signal pad) |
| A14 | Layer numbers from layermap names only |

Success = one connected carved component touches both ground pads **and** the preserved metal with zero net-aware DRC violations; `ground_body_hash` is a stable fingerprint of the carved body. Notebook section 5 has a reader-facing assumptions markdown cell and an explicit `GroundMergeConfig` before any routing code.

### Step 6 — Verification (not implemented)

Sign-off DRC and golden-layout comparison remain future work.

---

## Inputs (`python_code/input_files/`)

| File | Role |
|---|---|
| `KB331_N_01.gds` | Clean hierarchical filter layout |
| `KB331_N_Frame.gds` | Die frame template (460×580 µm outer bbox) |
| `GSG_frame.gds` | GSG PPD / probe-pad reference |
| `layermap` | Skyworks layer-name table |

---

## Outputs (`python_code/draft_output/`)

After the export cell in the notebook:

- `{parent}_RTEG1_{index:02d}_{inst_name}_framed.gds` — step 4 frame assemblies
- `{parent}_RTEG1_{index:02d}_{inst_name}_routed.gds` — step 5 routed assemblies (`status == "routed"` only)
- Matching `.lyp` — KLayout layer properties from the layermap

---

## Source layout (`python_code/src/`)

| File | Step |
|---|---|
| `layermap.py` | 1 |
| `inspect_refs.py` | 1 |
| `separate.py` | 2 |
| `prep_resonator_ppd.py` | 3 |
| `prep_rteg_frame.py` | 4 |
| `export_gds.py` | 4–5 (export) |
| `ground_merge.py` | 5 (ground plate merge) |
| `route_primitives.py` | 5 |
| `route_search.py` | 5 (retained for future signal pass) |
| `route_rteg.py` | 5 |
| `agentic/` | 5 (experimental LLM plate merge) |
| `rteg_utils.py` | shared geometry helpers |

---

## Concepts

| Term | Meaning |
|---|---|
| **R-tag / RTEG** | Per-resonator test layout in a GSG frame |
| **PPD** | Probe-pad device (`GSG_frame.gds`) |
| **Preserved metal** | Filter interconnect kept exact near the resonator (step 5+) |
| **Layermap** | Maps `BAW_MBE`, `BAW_MTE`, … to GDS layer/datatype pairs |

---

## Reference layouts

Golden/manual layouts live outside this pipeline (e.g. Virtuoso exports under `KB331_files/`). They are reference only — step 4 output is generated in-memory and written to `draft_output/` when you run export.
