#!/usr/bin/env python3
"""Reorder single_run.ipynb: 5.3 MTE extensions before 5.4 classify."""
from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parents[1] / "single_run.ipynb"


def main() -> None:
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    cells = nb["cells"]

    c28, c29, c30, c31 = cells[28], cells[29], cells[30], cells[31]
    cells[28], cells[29], cells[30], cells[31] = c30, c31, c28, c29

    src0 = "".join(cells[0]["source"])
    src0 = src0.replace(
        "| 5.2 | Classify | `rteg_orientation.py`, `rteg_classify.py` | "
        "`collect_orientation_inputs`, `classify_nodes` |\n"
        "| 5.3 | Build MTE signal | `rteg_signal.py`, `rteg_mte_route.py` | "
        "`build_signal_net`, `find_intercept_point`, `union_mte_net` |\n",
        "| 5.3 | MTE extensions | `rteg_signal.py`, `rteg_mte_route.py` | "
        "`build_mte_extensions` |\n"
        "| 5.4 | Classify / orientation | `rteg_orientation.py`, `rteg_classify.py` | "
        "`collect_orientation_inputs`, `classify_nodes` |\n",
    )
    cells[0]["source"] = src0.splitlines(keepends=True)

    cells[25]["source"] = (
        "## 5. Routing - solving interconnect algorithm\n\n"
        "**Goal:** turn a framed resonator into a DRC-clean RTEG — one fused MBE "
        "ground body with two pockets carved out (resonator + signal)\n\n"
        "steps to solve this \n\n"
        "1. **Collect (5.1)** — pull ground plates, preserved MBE/MTE, release "
        "holes, frame boundary by layermap (`rteg_collect.py`).\n"
        "2. **MTE extensions (5.3)** — draw ~13 µm extension from every preserved "
        "MTE collar (`build_mte_extensions`).\n"
        "3. **Classify (5.4)** — collar orientation, axis, signal vs ground "
        "(`rteg_classify.py`).\n"
        "4. **Union ground (5.5)** — OR the ground node blocks + filler + "
        "preserved MBE into one body (bridge gaps if needed).\n"
        "5. **Carve pockets (5.6)** — subtract signal net (+14µm), resonator "
        "keep-out, and release holes (+6µm) from the body.\n"
        "6. **Reconnect (5.7)** — union preserved ground metal back into the "
        "carved body; drop slivers.\n"
    ).splitlines(keepends=True)

    cells[26]["source"] = (
        "### 5.1 — Collect geometry roles\n\n"
        "**Files:** `src/rteg_collect.py`\n\n"
        "**Entry points:** `collect_geometry_roles`\n\n"
        "Splits the framed layout into typed polygon sets (ground plates, "
        "preserved metal, release holes, frame boundary). No net assignment "
        "here — step 5.4 classifies signal vs ground from collar orientation.\n"
    ).splitlines(keepends=True)

    cells[28]["source"] = (
        "### 5.3 — MTE extensions (one step)\n\n"
        "**Files:** `src/rteg_signal.py`, `src/rteg_mte_route.py`\n\n"
        "**Single call:** `build_mte_extensions(all_roles, layermap)`\n\n"
        "For every preserved MTE collar in each resonator, draws one new polygon "
        "that follows the collar outline and extends ~13 µm outward with a "
        "straight open end. Original preserved MTE is not modified.\n\n"
        "| Column | Meaning |\n"
        "|--------|---------|\n"
        "| `n_preserved_mte` | Preserved MTE collar count from step 5.1 |\n"
        "| `n_extensions` | Drawn extension polygons (one per collar) |\n"
        "| `is_connected` | Each extension overlaps its collar |\n"
    ).splitlines(keepends=True)

    cells[29]["cell_type"] = "code"
    cells[29]["source"] = (
        "from src.rteg_signal import build_mte_extensions, mte_extensions_overview_rows\n\n"
        "all_mte = build_mte_extensions(all_roles, layermap)\n\n"
        "mte_overview_df = pd.DataFrame(\n"
        "    mte_extensions_overview_rows(\n"
        "        all_mte,\n"
        "        inst_names={idx: roles.inst_name for idx, roles in all_roles.items()},\n"
        "    )\n"
        ").sort_values(\"index\")\n\n"
        "display(mte_overview_df)\n"
        "print(f\"Drew MTE extensions for {len(all_mte)} resonators\")\n"
    ).splitlines(keepends=True)
    cells[29].pop("outputs", None)
    cells[29].pop("execution_count", None)

    src30 = "".join(cells[30]["source"])
    src30 = src30.replace("### 5.2 —", "### 5.4 —")
    src30 = src30.replace(
        "step 5.3 may connect to center signal pad",
        "later routing may connect to center signal pad",
    )
    src30 = src30.replace(
        "step 5.3 extends preserved MTE ~13 µm only (no pad connection)",
        "later routing may extend further toward pads",
    )
    src30 = src30.replace(
        "(step 5.3 will draw one polygon)",
        "(used by later routing steps)",
    )
    cells[30]["source"] = src30.splitlines(keepends=True)

    src32 = "".join(cells[32]["source"]).replace("all_signal", "all_mte")
    cells[32]["source"] = src32.splitlines(keepends=True)

    NOTEBOOK.write_text(json.dumps(nb, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Patched {NOTEBOOK}")


if __name__ == "__main__":
    main()
