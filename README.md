# R-tag automation

Automates **R-tag (RTEG) test layouts** for Skyworks BAW filters: start from a clean filter GDS and produce per-resonator test structures in a GSG probe frame with MBE/MTE interconnect. Replaces the manual Virtuoso flow ([`rdsBawTEGAutoFromTemp.il`](rdsBawTEGAutoFromTemp.il)).

Domain rules and constraints: [`CLAUDE.md`](CLAUDE.md).

---

## Status (KB331 sample)

| Step | What | Status |
|------|------|--------|
| 1 | Inputs + layermap | Done |
| 2 | Identify resonators / vias | Done |
| 3 | Center resonator in GSG PPD | Done |
| 4 | Die frame placement + framed GDS export | Done |
| 5 | MTE signal (collect ΓåÆ classify ΓåÆ extend ΓåÆ pad route) | Done |
| 6.1 | MBE signal (`collar_extend`) | Done |
| 6.2 | MBE ground cap + filler (`collar_extend`) | Done |
| 6.3 | MBE ground filler (`center_pad`) | Done |
| ΓÇö | Full DRC sign-off / splits / batch production | Not yet |

**Demo:** run [`python_code/single_run.ipynb`](python_code/single_run.ipynb) top-to-bottom.

---

## Quick start

```powershell
cd python_code
pip install gdstk pandas ipykernel
jupyter notebook single_run.ipynb
```

Needs `python_code/input_files/` (filter, frame, PPD, layermap) and writes to `python_code/draft_output/`.

---

## Pipeline (one line per step)

1. **Inputs** ΓÇö validate GDS files and load layermap.
2. **Selection** ΓÇö find resonators (`series`/`shunt`/ΓÇª) and vias in the filter hierarchy.
3. **Separation** ΓÇö place each resonator in the GSG probe template with pad/release clearance.
4. **Setting up** ΓÇö place assembly in die frame; add right-side MBE filler; export framed GDS.
5. **MTE routing** ΓÇö classify signal path; draw 14 ┬╡m collar extensions; stretch to center pad when needed.
6. **MBE routing** ΓÇö MBE signal curves for side-facing collars; carve ground filler with MTE clearance.

```mermaid
flowchart LR
  filter[Filter GDS] --> identify[Step 2 identify]
  identify --> ppd[Step 3 PPD assembly]
  ppd --> frame[Step 4 die frame]
  frame --> mte[Step 5 MTE route]
  mte --> mbe[Step 6 MBE route]
  mbe --> gds[draft_output GDS]
```

---

## KB331 routing split (8 resonators)

| Strategy | Indices | Signal metal | Ground filler |
|----------|---------|--------------|---------------|
| `center_pad` | 1, 3, 4, 6 | MTE ΓåÆ center pad (5.4) | MBE filler carved around MTE (6.3) |
| `collar_extend` | 0, 2, 5, 7 | MBE pad ΓåÆ collar (6.1) | MBE cap + carved filler (6.2) |

---

## Key modules (`python_code/src/`)

| File | Role |
|------|------|
| `layermap.py` / `inspect_refs.py` | Step 1 ΓÇö layer names, hierarchy |
| `separate.py` | Step 2 ΓÇö `identify()` |
| `prep_resonator_ppd.py` | Step 3 ΓÇö PPD + resonator assembly |
| `prep_rteg_frame.py` | Step 4 ΓÇö die frame + filler placement |
| `export_gds.py` | GDS + `.lyp` export |
| `rteg_collect.py` | Step 5.1 ΓÇö geometry roles |
| `rteg_classify.py` / `rteg_orientation.py` | Step 5.2 ΓÇö node + route target |
| `rteg_mte_extensions.py` | Step 5.3 ΓÇö MTE lip extensions |
| `rteg_mte_route.py` | Step 5.4 ΓÇö pad stretch |
| `rteg_mbe_extensions.py` | Step 6.1 ΓÇö MBE signal |
| `rteg_mbe_body.py` | Step 6.2 ΓÇö MBE ground (`collar_extend`) |
| `rteg_mbe_body_center_pad.py` | Step 6.3 ΓÇö MBE ground (`center_pad`) |

Tests: `python_code/tests/` (KB331 fixtures in `kb331_pipeline.py`).

---

## Inputs & outputs

**Inputs** (`python_code/input_files/`): filter GDS, die frame, `GSG_frame.gds`, layermap.

**Outputs** (`python_code/draft_output/`):

- `original_rteg/` ΓÇö step-4 framed layouts (no routing).
- `MTE_generated_deterministic/` (notebook path) ΓÇö incremental exports with MTE/MBE routing.

Filenames: `{parent}_RTEG1_{index:02d}_{inst_name}_*.gds` + matching `.lyp`.

---

## Concepts

| Term | Meaning |
|------|---------|
| **R-tag / RTEG** | Per-resonator test layout in a GSG frame |
| **PPD** | Probe-pad device template |
| **Preserved metal** | Filter interconnect copied exactly near the resonator |
| **Filler plate** | Step-4 MBE rectangle on the right half of the die frame |

---

## Reference layouts

Manual/golden Virtuoso layouts (e.g. under `KB331_files/`) are reference only ΓÇö pipeline output is generated in `draft_output/` when you run the notebook.
