# Step 5 — From RTEG frame to signal MTE (orientation-based)

This document explains how the notebook (`single_run.ipynb`) goes from a **step-4 framed RTEG assembly** to a **generated signal MTE net** (step 5.3). Signal terminal and pad band come from **collar orientation**, not `res_type`.

## Step → file → function map

| Step | Source file(s) | Primary functions |
|------|----------------|-------------------|
| 3 | `prep_resonator_ppd.py`, `rteg_orientation.py`, `rteg_collect.py` | `prep_resonator_ppd`, `analyze_orientation`, `preserved_collars_at_shift` |
| 5.1 | `rteg_collect.py` | `collect_geometry_roles` |
| 5.2 | `rteg_orientation.py`, `rteg_classify.py` | `collect_orientation_inputs`, `classify_nodes` |
| 5.3 | `rteg_mte_extensions.py` | `build_mte_extensions`, `find_collar_mouth_intercepts`, `draw_collar_extension` |
| export | `rteg_mte_extensions.py`, `export_gds.py` | `export_mte_extensions_gds` |

**Modules:** `rteg_collect.py` (5.1) · `rteg_orientation.py` + `rteg_classify.py` (5.2) · `rteg_mte_extensions.py` (5.3)

---

## What step 5 produces

For each resonator index, step 5 answers:

1. **Which terminal is signal — MTE or MBE?** (5.2, from collar facing)
2. **Which GSG pad band is signal?** (5.2, `top` / `center` / `bottom`)
3. **Where is the MTE extension?** (5.3, ~13 µm outward from preserved edge collar when `signal_drawable`)
4. **Is it attached to the collar?** (overlap ≥ 0.01 µm²; overlap/collar area < 50%)

Output is an `MteExtensionResult` per resonator. Export via `export_mte_extensions_gds` as `*_mte.gds`. All drawable MTE polygons must stay on `BAW_MTE` via `layermap.pair` (KB331: `(5, 0)`).

---

## Prerequisites (steps 1–4)

| Step | Module | What step 5 needs |
|------|--------|-------------------|
| 1–2 | `separate.py` | `IdentificationResult` — resonators + connect cells |
| 3 | `prep_resonator_ppd.py` | `ResonatorPpdAssembly` — GSG template + centered resonator + **orientation_shift** |
| 4 | `prep_rteg_frame.py` | `RtegFrameAssembly` — framed layout |
| — | `layermap` | `BAW_MBE`, `BAW_MTE`, `BAW_ReF`, `BAW_CAV`, … |

### Step 3 orientation placement

After centering and clearance nudges, `prep_resonator_ppd` optionally takes `identification` + `layermap`:

1. `preserved_collars_at_shift` — filter connect MTE/MBE in PPD placement space
2. `analyze_orientation` — collar axis, facing pad, recommended shift
3. Apply `orientation_shift` to final resonator placement

---

## 5.1 — Collect geometry roles (`rteg_collect.py`)

`collect_geometry_roles` returns:

- **ground plates** — GSG pad MBE by Y band (top / center / bottom) + filler
- **preserved metal** — filter `connectMTE` / `connectMBE` overlapping the resonator window
- **release holes** — `BAW_ReF` / `BAW_CAV` near the resonator
- **frame boundary** — inner cavity + die-frame ring

No net assignment in 5.1.

Shared helper: `preserved_collars_at_shift` (also used in step 3).

---

## 5.2 — Classify nodes (`rteg_classify.py`)

**Input:** `collect_orientation_inputs` → `OrientationAnalysis`

**Output:** `NodeClassification` with:

| Field | Meaning |
|-------|---------|
| `signal_terminal` | `MTE` if MTE collar faces the signal-side pad; else `MBE` |
| `signal_pad_band` | `top` / `center` / `bottom` — band the collar faces |
| `signal_drawable` | `True` only when `signal_terminal == "MTE"` |
| `method` | `"orientation"` |

Net rules:

- Signal pad band → **signal**; other GSG bands → **ground**; filler → ground
- `MBE` terminal: all pads ground; no MTE geometry in 5.3

`res_type` is logged only — not used for routing.

---

## 5.3 — MTE extensions (`rteg_mte_extensions.py`)

When `classification.signal_drawable`:

1. Resolve `mte_pair = layermap.pair("BAW_MTE")`
2. `select_edge_collar_mte` — smallest preserved MTE piece overlapping resonator-body MTE (edge collar, not stadium outline)
3. `find_collar_mouth_intercepts` — corner A, walk long-side lip to corner B
4. `draw_collar_extension` — extrude outward ~13 µm with cap parallel to mouth; inner edge inset 0.5 µm for merge overlap
5. `_validate_extension` — boolean AND with collar must be ≥ 0.01 µm² and overlap/collar area < 50%; failure skips export for that resonator
6. Frame cap-height shrink via `mte_extension_frame_obstacles` from `rteg_collect.py`

When `signal_terminal == "MBE"`: no extension (`n_extensions=0`).

### Layer enforcement

`assign_layer` in `rteg_utils.py` re-tags polygons after `gdstk.boolean` / `offset`. Tests assert every extension polygon is on `layermap.pair("BAW_MTE")`, never `(0, 0)`.

### Export

`export_mte_extensions_gds` writes framed assembly + preserved MTE + validated extensions only.

---

## Validation

- Unit tests: `tests/test_rteg_orientation.py`
- Integration: `tests/test_rteg_classify_orientation.py`, `tests/test_rteg_signal_mte.py`, `tests/test_rteg_mte_extensions_sweep.py`
- KB331 table: `python scripts/validate_kb331_orientation.py`

Columns: `index`, `res_type`, `signal_terminal`, `collar_axis`, `facing_pad`, `signal_pad_band`, `intercept_xy`, `drc_clean`, `min_spacing_um`, `placement_shift`, `mte_layer`
