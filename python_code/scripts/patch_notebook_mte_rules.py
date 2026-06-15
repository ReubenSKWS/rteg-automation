#!/usr/bin/env python3
import json
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parents[1] / "single_run.ipynb"
nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))


def set_cell(idx: int, src: str, typ: str = "markdown") -> None:
    nb["cells"][idx]["cell_type"] = typ
    nb["cells"][idx]["source"] = src.splitlines(keepends=True)
    nb["cells"][idx].pop("outputs", None)
    nb["cells"][idx].pop("execution_count", None)


set_cell(
    28,
    """### 5.2 — Classify GSG nodes by collar orientation

**Files:** `src/rteg_orientation.py`, `src/rteg_classify.py`, `src/rteg_collect.py`

MTE routing has **two targets only**:
- **center pad** (signal) when preserved MTE faces the **center** GSG pad
- **ground** (top/bottom pad) when preserved MTE does not face center

All MTE geometry must launch from **preserved filter MTE** — never from arbitrary resonator metal.
""",
)

set_cell(
    29,
    '''from src.rteg_classify import ClassifyNodesConfig, classify_nodes, classification_summary_table
from src.rteg_collect import collect_orientation_inputs

CLASSIFY_CONFIG = ClassifyNodesConfig()

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
        config=CLASSIFY_CONFIG,
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
            "mte_route_target": classification.mte_route_target,
            "mte_faces_center": collar.mte_faces_center,
            "signal_terminal": classification.signal_terminal,
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

for idx, classification in all_classify.items():
    assert classification.method == "orientation"
    assert classification.mte_route_target in ("center_pad", "ground")
    assert classification.signal_drawable == bool(all_roles[idx].preserved.mte)
    if classification.mte_route_target == "center_pad":
        assert classification.by_band()["center"].net == "signal"

print(f"\\nOrientation classification checks passed for all {len(all_classify)} resonators")
''',
    "code",
)

set_cell(
    30,
    """### 5.3 — Build signal MTE net

**Files:** `src/rteg_signal.py`, `src/rteg_mte_route.py`

Routes always start from **preserved MTE**:
- `linear_span_center` → center signal pad
- `linear_span_ground` → nearest top/bottom ground pad

Step 3 orientation placement searches up/down/left/right for max GSG pad clearance (>= 14 um).
""",
)

set_cell(
    31,
    '''from src.rteg_signal import (
    SignalBuildConfig,
    build_signal_net,
    signal_net_summary_table,
)

SIGNAL_CONFIG = SignalBuildConfig()
mte_pair = layermap.pair(SIGNAL_CONFIG.mte_layer)

all_signal: dict[int, object] = {}
signal_overview_rows: list[dict[str, object]] = []

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
            "mte_route_target": classification.mte_route_target,
            "signal_terminal": classification.signal_terminal,
            "collar_axis": classification.collar_orientation.axis,
            "facing_pad": classification.collar_orientation.facing_pad,
            "intercept_xy": f"({intercept[0]:.1f},{intercept[1]:.1f})",
            "shape": summary["shape"],
            "drc_clean": summary["is_success"],
            "min_spacing_um": summary["min_ground_spacing_um"],
            "mte_layer": str(next(iter(mte_layers))) if mte_layers else str(mte_pair),
            "preserved_mte": signal.endpoints.preserved.label,
            "n_net_polygons": summary["n_net_polygons"],
        }
    )

signal_overview_df = pd.DataFrame(signal_overview_rows).sort_values("index")
display(signal_overview_df)

for idx, signal in all_signal.items():
    c = all_classify[idx]
    if not c.signal_drawable:
        assert signal.net_polygons == []
        continue
    assert signal.endpoints.preserved.label.startswith("preserved_")
    assert signal.connector.shape_name in ("linear_span_center", "linear_span_ground")
    for poly in signal.net_polygons:
        assert (poly.layer, poly.datatype) == mte_pair

print(f"Signal MTE checks passed for {len(all_signal)} resonators")
''',
    "code",
)

NOTEBOOK.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Patched {NOTEBOOK}")
