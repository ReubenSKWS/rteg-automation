# R-tag Automation — Project Context

> **For coding agents:** This file describes *what* this project does and *why*. It deliberately does **not** prescribe how to build it (architecture, libraries, algorithms). Treat the constraints below as hard requirements on any output. Treat the manual process as domain knowledge — the existing reality this codebase must reproduce — not as an algorithm to follow literally.

---

## What this project is

This codebase automates the generation of **R-tag test structures** for **BAW (Bulk Acoustic Wave) filters** at Skyworks (filters team).

R-tags are per-resonator test layouts used by NPI and modeling teams to characterize individual resonators (and small combinations of them) and compare measured behavior against the modeled full-filter behavior.

Today, R-tag generation is a manual layout task performed in **Cadence Virtuoso** by a layout engineer. For a filter with 60–70 resonators it consumes roughly a full engineer-day. This project replaces that manual work with code that reproduces the same engineering decisions automatically.

**Implementation status:** Steps 1–6 (through MBE ground filler) run on the KB331 sample in [`python_code/single_run.ipynb`](python_code/single_run.ipynb). See [`README.md`](README.md) for the current pipeline map and module list.

---

## Domain primer

- **BAW filter** — an RF filter built from many bulk-acoustic-wave resonators.
- **Resonator** — the basic active element. Each filter contains many. Each has a fixed orientation, release-hole positions, and defined interconnect entry points (**"collars"**).
- **MBE / MTE** — the two top-metal layers used for interconnect.
- **R-tag** — a test structure for a single resonator (or a small split/cascade), framed by probe pads, suitable for direct measurement.
- **F-tag** — a related, filter-level test structure. R-tags must remain consistent with F-tag probing conventions where relevant.
- **Via** — vertical connection between metal layers.
- **Release hole** — process feature with fixed position; routing must keep clearance.
- **PDK6** — the Skyworks process design kit this work targets.

---

## What the manual process currently does

A layout engineer (Brian is the SME) takes a clean filter layout and, for each resonator (and required split/cascade), produces an R-tag by:

1. Copying the die to a scratch area and placing the R-tag template (probe pad frame).
2. Positioning the resonator near the center of the template, carrying along the filter's existing metal that belongs to that resonator.
3. Identifying which side of the resonator is signal and which is ground.
4. Routing the signal connection first — from the probe pad to the preserved resonator metal — choosing whether the signal pad lands on MBE or MTE based on resonator orientation, available connection points, and via accessibility.
5. Preserving the exact filter interconnect metal near the resonator (per NPI mandate) until "clear" of it, then drawing custom polygons back to the pad.
6. Placing vias (preferring placement on the signal-pad side).
7. Cutting and rebuilding ground-plane metal as needed around the resonator.
8. Repeating for splits, cascades, and port-connected combinations.

This is documented as **reality to reproduce**, not as an algorithm to mimic line-for-line. The code can encode these decisions however it makes sense, so long as the output satisfies the constraints below.

---

## Hard constraints (output must satisfy)

**NPI mandate**
- Resonator orientation cannot change.
- Interconnect entry points ("collars") into the resonator must be preserved.
- Release-hole positions are fixed.
- Filter metal must be reproduced exactly until sufficiently clear of the resonator.

**DRC (PDK6)**
- Minimum **14 µm** spacing between unconnected MBE/MTE.
- Practical safety margin: **1.5–3×** the DRC minimum where space allows.
- Minimum **6 µm** clearance from release holes.

**Geometry style**
- No acute angles. Prefer orthogonal and 45° transitions; obtuse entries into collars.
- Routes should align cleanly with pad launches.
- Polygons should start from existing metal edges where possible.

**Probing**
- Template orientation: top-bottom preferred, left-right acceptable when space-constrained.
- Stay consistent with related F-tag probing conventions.

---

## Scope

**In scope**
- Generating R-tags for individual resonators.
- Generating R-tags for splits, cascades, and port-connected combinations.
- Producing DRC-clean GDS output compatible with PDK6.
- Consuming the layer mapping defined by Skyworks tooling.
- Maintaining probing conventions consistent with related F-tags.

**Out of scope** (for now)
- Generating F-tags or any other test structures besides R-tags.
- Modifying or optimizing the parent filter layout itself.
- Choosing *which* resonators get R-tags (that selection is provided as input).
- Relaxing the NPI exact-metal-replication rule (may become possible later via de-embedding, but assume the rule holds today).

---

## Inputs and outputs

**Inputs**
- A clean filter GDS file.
- The Skyworks layer mapping (owned by Jing Yang).
- An R-tag template (probe pad frame).
- A list of which resonators (and which splits/cascades) to generate R-tags for.

**Outputs**
- A GDS file containing the generated R-tag structures, fully DRC-clean, ready for downstream interconnect-layer generation.

---

## People and roles

- **Brian** — layout SME; source of the manual decision process being encoded.
- **Jing Yang** — owns the layer mapping table and a semi-automation script that extracts resonators into their own cells (upstream dependency).
- **Alex** — layout, sample files and reference layouts.
- **Matt** — manager.
- **Dan** — tooling, GitHub access, AI coding tools.
- **Reuben** — software engineer building this system (intern).

---

## Open / pending information

These are unresolved and may affect implementation decisions. Flag rather than assume when they come up:

- Confirm meaning of **"Shot A" / "Shot B"** (likely lithography multi-patterning exposure passes).
- Acquire NPI mandate documentation and sample before/after layouts from Brian/Alex.
- Pin down a quantitative definition of **"clear of the resonator"** (how far is far enough before custom routing can take over from preserved filter metal?).
- Determine whether signal/ground identification is encoded in source GDS metadata (net names, labels, layer assignment) or must be inferred from geometry.
- Confirm the exact format and contents of Jing Yang's layer mapping table.
