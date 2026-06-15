#!/usr/bin/env python3
"""Restore step 5.2 (classify) in single_run.ipynb; keep 5.3 MTE + 5.4 routing stub."""
from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parents[1] / "single_run.ipynb"


def main() -> None:
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    cells = nb["cells"]

    # Current order after prior patch: 28=5.3 md, 29=5.3 code, 30=5.4 classify md, 31=5.4 classify code, 32=export
    md_53, code_53 = cells[28], cells[29]
    md_classify, code_classify = cells[30], cells[31]
    export_cell = cells[32]

    # Renumber classify back to 5.2
    src_classify_md = "".join(md_classify["source"]).replace("### 5.4 —", "### 5.2 —")
    md_classify["source"] = src_classify_md.splitlines(keepends=True)

    # 5.4 stub for future orientation-based routing (uses 5.2 classification + 5.3 extensions)
    md_54 = {
        "cell_type": "markdown",
        "metadata": {},
        "source": (
            "### 5.4 — Route MTE (future)\n\n"
            "**Files:** `src/rteg_signal.py` (TBD)\n\n"
            "Uses **5.2** classification (`mte_route_target`, collar axis, `facing_pad`) to decide "
            "how each **5.3** extension connects — e.g. center pad vs ground-only extend.\n\n"
            "Not implemented yet; 5.3 draws the baseline ~13 µm extension for every preserved collar.\n"
        ).splitlines(keepends=True),
    }

    cells[28] = md_classify
    cells[29] = code_classify
    cells[30] = md_53
    cells[31] = code_53
    cells[32] = md_54
    cells[33] = export_cell

    # Overview table
    src0 = "".join(cells[0]["source"])
    src0 = src0.replace(
        "| 5.1 | Collect roles | `rteg_collect.py` | `collect_geometry_roles` |\n"
        "| 5.3 | MTE extensions | `rteg_signal.py`, `rteg_mte_route.py` | "
        "`build_mte_extensions` |\n"
        "| 5.4 | Classify / orientation | `rteg_orientation.py`, `rteg_classify.py` | "
        "`collect_orientation_inputs`, `classify_nodes` |\n",
        "| 5.1 | Collect roles | `rteg_collect.py` | `collect_geometry_roles` |\n"
        "| 5.2 | Classify / orientation | `rteg_orientation.py`, `rteg_classify.py` | "
        "`collect_orientation_inputs`, `classify_nodes` |\n"
        "| 5.3 | MTE extensions | `rteg_signal.py`, `rteg_mte_route.py` | "
        "`build_mte_extensions` |\n"
        "| 5.4 | Route MTE (future) | `rteg_signal.py` | TBD |\n",
    )
    cells[0]["source"] = src0.splitlines(keepends=True)

    cells[25]["source"] = (
        "## 5. Routing - solving interconnect algorithm\n\n"
        "**Goal:** turn a framed resonator into a DRC-clean RTEG — one fused MBE "
        "ground body with two pockets carved out (resonator + signal)\n\n"
        "steps to solve this \n\n"
        "1. **Collect (5.1)** — pull ground plates, preserved MBE/MTE, release "
        "holes, frame boundary by layermap (`rteg_collect.py`).\n"
        "2. **Classify (5.2)** — collar orientation, axis, signal vs ground "
        "(`rteg_classify.py`).\n"
        "3. **MTE extensions (5.3)** — draw ~13 µm extension from every preserved "
        "MTE collar (`build_mte_extensions`).\n"
        "4. **Route MTE (5.4)** — use 5.2 classification to connect extensions "
        "(center pad vs ground); not implemented yet.\n"
        "5. **Union ground (5.5)** — OR ground node blocks + filler + preserved MBE.\n"
        "6. **Carve pockets (5.6)** — subtract signal net, resonator keep-out, release holes.\n"
        "7. **Reconnect (5.7)** — union preserved ground metal back; drop slivers.\n"
    ).splitlines(keepends=True)

    cells[26]["source"] = (
        "### 5.1 — Collect geometry roles\n\n"
        "**Files:** `src/rteg_collect.py`\n\n"
        "**Entry points:** `collect_geometry_roles`\n\n"
        "Splits the framed layout into typed polygon sets (ground plates, "
        "preserved metal, release holes, frame boundary). Step 5.2 assigns "
        "signal vs ground from collar orientation.\n"
    ).splitlines(keepends=True)

    NOTEBOOK.write_text(json.dumps(nb, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Restored 5.2 in {NOTEBOOK}")


if __name__ == "__main__":
    main()
