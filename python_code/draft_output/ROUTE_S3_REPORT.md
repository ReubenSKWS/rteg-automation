# Route S3 (v1) report

Standalone individual RTEG in its own GSG frame (`KB331_N_Frame`, 460x580) — not reintegrated into the die. Resonator index 06 routed against golden S3. Output is trimmed to the golden's layer set for a clean GSG look (no die-context BF/TSV/EM_VPT fill). This pass draws a simple signal connector, recuts the frame ground, and checks spacing per net. It does not generate the manual flow's fill/trim layers and does not claim parity with the golden.

## 0. What changed in this pass

- **Reverted** `ppd_1port` geometry placement: the output's GSG pads are `KB331_N_Frame`'s `BAW_MB2` bond pads only. `ppd_1port` is kept **only** as the signal-pad/orientation lookup for routing (`resolve_signal_pad`).
- **Trimmed** the entire assembled output (frame sub-cells + resonator + preserved metal) to a golden-derived layer allow-list (`trim_to_golden_layers=True`, v1 — NOT a general RTEG-layer spec). Drops frame BF1-8/TSV/EM_VPT and resonator H18/TCL over-carry.
- Standalone GSG-frame scope: clean orange GSG frame, three vertical `BAW_MB2` pads per side, resonator + routing — no die-like hatched border.
- Signal route draws inside a first-class routable region (straight / single 45 / one L-bend).
- Endpoints use the true minimum-distance pad-to-metal point pair (pad-facing edge).
- DRC self-check is connectivity-aware; spacing flagged only between different nets.
- Primary success metric is MBE/MTE overlap area vs golden; layer-count table is secondary.
- Ground region from real `KB331_N_Frame` `BAW_MBE` fill.

## 1. Signal route

- **drew** a `straight` connector on `BAW_MTE`.
- signal pad ref: `pad3_CDNS_780940566706`, launch layer `BAW_MBE`.
- via at transition: **needed** (pad and route on different layers) but no `vtb` master available in prepared input [flagged for SME].

### Route log
```
layer trim: golden-derived allow-list (83 pairs); prepared layers absent from golden: none
resonator world bbox: (176.3, 245.1)-(315.2, 354.1)
signal metal (MTE) polys: 4; outside clearance: 1
release-hole polys (BAW_REV, BAW_CAV, BAW_ReF, BAW_ReFneg): 12
signal pad: ppd_1port launch layer = BAW_MBE (differs from signal feed BAW_MTE -> via at transition)
signal pad: matched ppd_1port onto frame pad 'pad3_CDNS_780940566706' @ (73.5, 308.3) rot 4.71; launch metal 2 polys on BAW_MBE
endpoints: pad (50.5, 331.3) -> preserved metal (60.7, 331.8) (gap 10.2um)
routable: frame interior from BAW_EDGE (1 polys, (0.0, 0.0)-(460.0, 580.0))
routable region: 1 polys, area 170794
signal route drawn: straight, 1 polys on BAW_MTE
via needed at pad transition (BAW_MBE -> BAW_MTE) but no vtb master in prepared input [flagged for SME]
ground source: frame BAW_MBE ground fill
ground recut: 1 polys
layer trim emit: skipped 0 non-golden polys; routed layers absent from golden: none
net-aware DRC: 7 nets; signal-vs-ground spacing violations @ 14.0um: introduced=0, preserved-collar=1 (frame bonding pads excluded; collar = NPI-preserved metal, see signal/ground rule)
wrote KB331_N_01_RTEG1_S3_routed.gds
net overlay marker layers (not in layermap): SIGNAL=900/0, GROUND=901/0, OTHER=902/0
net overlay classification (same as DRC): 7 nets -> GROUND=1 net (1 marker polys, area 63552), SIGNAL=1 net(s) (1 marker polys), OTHER=5 net(s) (5 marker polys)
wrote KB331_N_01_RTEG1_S3_nets.gds (+ KB331_N_01_RTEG1_S3_nets.lyp)
```

## 2. Assumptions (RouteConfig)

| Parameter | Value | Status |
|---|---|---|
| signal_vs_ground_rule | `series_signal_on_mte_side` | **needs Brian/Jing** |
| signal_feed_layer | `BAW_MTE` | derived from rule |
| ground_layers | `BAW_MBE` | golden uses more fill layers — diverges |
| frame_interior_layer | `BAW_EDGE` | frame extent; bbox fallback |
| release_layers | `BAW_REV, BAW_CAV, BAW_ReF, BAW_ReFneg` | **assumed** from cell inventory |
| min_spacing_um | 14.0 | PDK6 DRC |
| safety_margin_um | 21.0 | 1.5x min |
| release_clearance_um | 6.0 | PDK6 DRC |
| resonator_clearance_um | 14.0 | routable-region grow |
| metal_width_um | 14.0 | v1 = min spacing |
| via_cell_prefix | `vtb` | from SKILL; not a layermap layer |
| trim_to_golden_layers | True | **golden-derived (v1)**; not a general RTEG spec |

## 2b. Layer trim — prepared / routed vs golden

- Prepared layers absent from golden: **none**.
- Routed layers absent from golden: **none**.
- Polygons skipped at routed emit (non-golden layers): 0.
- Target: ~0 absent layers; die fill (`BAW_BF*`, `BAW_TSV`, `EM_VPT`) and resonator extras (`BAW_H18`, `BAW_TCL`) should be gone.

## 3. Primary metric — MBE/MTE overlap area vs golden

| layer | golden area | routed area | intersection | overlap % of golden | sym-diff area |
|---|---|---|---|---|---|
| BAW_MBE | 157036 | 89446 | 64879 | 41.3% | 116726 |
| BAW_MTE | 12638 | 12059 | 8273 | 65.5% | 8152 |

Overlap % is intersection area as a fraction of the golden's area on that layer. This is the headline metric; high sym-diff means the routed shapes differ substantially from golden even where they overlap.

### GSG / pad-layer overlap vs golden

| layer | golden area | routed area | overlap % of golden | sym-diff area |
|---|---|---|---|---|
| BAW_MB2 | 39857 | 38109 | 95.6% | 1749 |
| BAW_M1 | 169131 | 100582 | 44.2% | 120185 |
| BAW_MB1 | 37801 | 53219 | 99.7% | 15655 |

`BAW_MB2` (the GSG bond pads) overlaps the golden because those pads come from `KB331_N_Frame`. `BAW_M1`/`BAW_MB1` are dominated by the golden's large ground planes.

## 4. DRC self-check (net-aware)

- Cross-net spacing violations introduced by routing/pads @ 14.0um: **0**.
- Preserved-collar violations (NPI metal, not introduced): **1** — filter metal reproduced exactly around the resonator; hinge on the unresolved signal/ground rule.
- Metal connected through the resonator is treated as one net, so preserved MBE meeting MTE at the resonator is otherwise not a false positive.

## 4b. Net overlay diagnostic (`_nets.gds`)

Every run also writes a **diagnostic overlay** (not a deliverable): `KB331_N_01_RTEG1_S3_nets.gds` plus `KB331_N_01_RTEG1_S3_nets.lyp` for KLayout. It contains the full routed geometry plus marker layers painted from the **same net builder and classification used by net-aware DRC**.

| bucket | marker layer | nets | marker polys |
|---|---|---|---|
| SIGNAL | 900/0 | 1 | 1 |
| GROUND | 901/0 | 1 | 1 |
| OTHER | 902/0 | 5 | 5 |

Classification follows `signal_vs_ground_rule` = `series_signal_on_mte_side` (**needs Brian/Jing**): SIGNAL = MTE-bearing net(s) excluding the largest-area ground net; GROUND = largest-area net; OTHER = remaining nets (e.g. frame bonding pads). Open `_nets.gds` with `_nets.lyp` in KLayout to visually validate this assumption before trusting the overlay.

## 5. Ground plane

- Ground region source: **frame BAW_MBE ground fill**.
- Recut ground polygons on `BAW_MBE`: 1 (clearance carved around signal net, resonator, release holes).

## NOTES — golden vs prepared

- golden:   `KB331_N_01_RTEG1_S3.gds` — 163 polys, 83 layer pairs
- prepared: `KB331_N_01_RTEG1_S3_prepared.gds` — 316 polys, 62 layer pairs
- golden bbox: (0.0, 0.0) - (460.0, 580.0)
- prepared bbox: (0.0, 0.0) - (460.0, 580.0)

### Metal extents (flattened)
- BAW_MBE: golden 3 polys (9.5, 9.5) - (450.5, 570.5) | prepared 19 polys (7.0, 7.0) - (450.5, 570.5)
- BAW_MTE: golden 1 polys (139.5, 232.3) - (288.0, 349.2) | prepared 4 polys (59.1, 234.9) - (289.1, 366.3)

### Layers in golden, absent from prepared (21)
These are routing/ground/fill layers the manual flow adds; v1 routes only MBE/MTE.

| layer | gds | polys |
|---|---|---|
| BAW_MF3 | 42/0 | 1 |
| BAW_MF4 | 43/0 | 1 |
| BAW_MF5 | 44/0 | 1 |
| BAW_MF6 | 45/0 | 1 |
| BAW_MF7 | 46/0 | 1 |
| BAW_MF8 | 47/0 | 1 |
| BAW_H4 | 201/0 | 1 |
| BAW_H6 | 203/0 | 13 |
| BAW_H7 | 204/0 | 3 |
| BAW_H17 | 217/0 | 3 |
| BAW_H21 | 221/0 | 3 |
| BAW_H22 | 222/0 | 3 |
| BAW_NoTF1 | 227/0 | 1 |
| BAW_NoTF4 | 230/0 | 1 |
| BAW_NoTF5 | 231/0 | 1 |
| BAW_NoTF6 | 232/0 | 1 |
| BAW_NoTFS | 239/0 | 1 |
| BAW_TEG | 243/0 | 1 |
| BAW_ORF | 245/0 | 2 |
| BAW_NoTF7 | 257/0 | 1 |
| BAW_NoTF8 | 258/0 | 1 |

### Layers in prepared, absent from golden (0)
(none)

## 6. Missing-layer inventory (NOT generated — SME tee-up)

Golden carries layers v1 does not synthesize. Grouped below with a provisional origin tag for Brian / Jing Yang to confirm. These are fill / trim / hole layers; v1 intentionally does not invent them.

| group | layers | total polys | provisional origin |
|---|---|---|---|
| H-series (hole/fill) | BAW_H17, BAW_H21, BAW_H22, BAW_H4, BAW_H6, BAW_H7 | 26 | likely derived (fill/trim/hole) |
| No-series (mask exclusions) | BAW_NoTF1, BAW_NoTF4, BAW_NoTF5, BAW_NoTF6, BAW_NoTF7, BAW_NoTF8, BAW_NoTFS | 7 | likely derived |
| MF-series (metal fill) | BAW_MF3, BAW_MF4, BAW_MF5, BAW_MF6, BAW_MF7, BAW_MF8 | 6 | likely copied from source / derived |
| TEG/ORF/label | BAW_ORF, BAW_TEG | 3 | unknown -- SME |
| other | y1 | 1 | unknown -- SME |

## 7. Secondary diagnostic — per-layer polygon counts

Dominated by fill layers v1 does not generate; not a success metric. Provided for completeness.

| layer | gds | golden | routed |
|---|---|---|---|
| BAW_SCL | 1/0 | 1 | 7 |
| BAW_MBE | 2/0 | 3 | 19 |
| BAW_MRaF | 3/0 | 2 | 1 |
| BAW_MF1 | 4/0 | 2 | 1 |
| BAW_MTE | 5/0 | 1 | 5 |
| BAW_PZL | 6/0 | 1 | 4 |
| BAW_SV | 7/0 | 9 | 19 |
| BAW_M1 | 8/0 | 3 | 19 |
| BAW_EDGE | 9/0 | 1 | 1 |
| BAW_MB1 | 10/0 | 1 | 10 |
| BAW_MB2 | 12/0 | 6 | 6 |
| BAW_ReFneg | 13/0 | 1 | 3 |
| BAW_ChipB | 20/0 | 1 | 1 |
| BAW_BET | 21/0 | 2 | 6 |
| BAW_ORaF | 23/0 | 1 | 1 |
| BAW_TFS | 25/0 | 2 | 9 |
| BAW_TFP | 26/0 | 1 | 14 |
| BAW_TF1 | 27/0 | 2 | 9 |
| BAW_TF2 | 28/0 | 1 | 10 |
| BAW_TF3 | 29/0 | 1 | 10 |
| BAW_TF4 | 30/0 | 2 | 9 |
| BAW_TF5 | 31/0 | 2 | 9 |
| BAW_TF6 | 32/0 | 2 | 9 |
| BAW_ReF | 33/0 | 5 | 8 |
| EM_HPT | 34/0 | 1 | 1 |
| BAW_CAV | 36/0 | 1 | 5 |
| BAW_REV | 37/0 | 1 | 5 |
| BAW_H1 | 39/0 | 2 | 4 |
| BAW_H2 | 40/0 | 2 | 2 |
| BAW_MF2 | 41/0 | 2 | 1 |
| BAW_MF3 | 42/0 | 1 | 0 |
| BAW_MF4 | 43/0 | 1 | 0 |
| BAW_MF5 | 44/0 | 1 | 0 |
| BAW_MF6 | 45/0 | 1 | 0 |
| BAW_MF7 | 46/0 | 1 | 0 |
| BAW_MF8 | 47/0 | 1 | 0 |
| BAW_TF7 | 48/0 | 3 | 9 |
| BAW_TF8 | 49/0 | 3 | 9 |
| BAW_STE | 50/0 | 1 | 1 |
| BAW_BMF | 55/0 | 1 | 10 |
| BAW_RSE | 59/0 | 1 | 3 |
| BAW_XeF | 80/0 | 2 | 4 |
| BAW_LABEL | 100/0 | 2 | 2 |
| y2 | 101/0 | 2 | 1 |
| y1 | 102/0 | 1 | 1 |
| y0 | 103/0 | 1 | 1 |
| BAW_H3 | 200/0 | 4 | 4 |
| BAW_H4 | 201/0 | 1 | 0 |
| BAW_H5 | 202/0 | 3 | 10 |
| BAW_H6 | 203/0 | 13 | 0 |
| BAW_H7 | 204/0 | 3 | 0 |
| BAW_H10 | 207/0 | 1 | 1 |
| BAW_H11 | 208/0 | 4 | 4 |
| BAW_H12 | 212/0 | 1 | 1 |
| BAW_H13 | 213/0 | 1 | 1 |
| BAW_H14 | 214/0 | 1 | 1 |
| BAW_H16 | 216/0 | 1 | 1 |
| BAW_H17 | 217/0 | 3 | 0 |
| BAW_H21 | 221/0 | 3 | 0 |
| BAW_H22 | 222/0 | 3 | 0 |
| BAW_NoTF1 | 227/0 | 1 | 0 |
| BAW_NoTF4 | 230/0 | 1 | 0 |
| BAW_NoTF5 | 231/0 | 1 | 0 |
| BAW_NoTF6 | 232/0 | 1 | 0 |
| BAW_NoMF1 | 233/0 | 2 | 2 |
| BAW_NoMF2 | 234/0 | 2 | 2 |
| BAW_NoMF3 | 235/0 | 2 | 4 |
| BAW_NoMF4 | 236/0 | 4 | 4 |
| BAW_NoTFS | 239/0 | 1 | 0 |
| BAW_TEG | 243/0 | 1 | 0 |
| BAW_SOW | 244/0 | 1 | 1 |
| BAW_ORF | 245/0 | 2 | 0 |
| BAW_TF1neg | 250/0 | 1 | 1 |
| BAW_TF4neg | 253/0 | 1 | 1 |
| BAW_TF5neg | 254/0 | 1 | 1 |
| BAW_TF6neg | 255/0 | 1 | 1 |
| BAW_ORFneg | 256/0 | 1 | 3 |
| BAW_NoTF7 | 257/0 | 1 | 0 |
| BAW_NoTF8 | 258/0 | 1 | 0 |
| BAW_TF7neg | 261/0 | 1 | 1 |
| BAW_TF8neg | 262/0 | 1 | 1 |
| BAW_PZLneg | 264/0 | 5 | 16 |
| BAW_SVpos | 265/0 | 3 | 7 |

## 8. Status

**Verified geometrically (this run):**

- Resonator 06 centered in standalone `KB331_N_Frame` (460x580 GSG frame), preserved MTE/MBE metal carried along, output trimmed to golden layers.
- Signal connector drawn (straight) inside the routable region, DRC-clean by construction.
- Ground recut from frame BAW_MBE ground fill.
- GSG bond pads from `KB331_N_Frame` `BAW_MB2` (six 90x90 pads); `ppd_1port` NOT in output (lookup only).
- Net-aware DRC: 0 introduced cross-net violations, 1 preserved-collar (NPI).
- Net overlay diagnostic written: `KB331_N_01_RTEG1_S3_nets.gds` (+ `KB331_N_01_RTEG1_S3_nets.lyp` if present) — visual check for signal/ground classification.

**Assumed / needs SME confirmation:**

- Signal-vs-ground side rule for series resonators (currently MTE-side).
- Release-hole layer set used for clearance.
- Index 06 treated as the golden `S3`; not proven identical to the Virtuoso instance name.
- ppd_1port-to-frame pad mapping: matched onto the nearest signal pad; pad/probe-orientation rule to be confirmed.

**Known divergences from golden (do not read as parity):**

- Golden carries many fill/TF/MF/`BAW_H*` layers that v1 does not generate (see section 6).
- MBE/MTE overlap is partial (section 3); routed shapes are simple connectors and recut ground, not the manual geometry.
