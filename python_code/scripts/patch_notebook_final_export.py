"""Patch single_run.ipynb: remove intermediate GDS exports; add final export cell."""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parents[1] / "single_run.ipynb"

EXPORT_BLOCK = re.compile(
    r"\n\n(?:# .*export.*\n)?"
    r"(?:from src\.export_gds import export_summary_df\n)?"
    r"(?:from src\.rteg_mte_extensions import export_mte_extensions_gds\n\n)?"
    r"MTE_OUT = DRAFT / \"MTE_generated_deterministic\"\n"
    r"mte_export_df = export_summary_df\(\n"
    r"    export_mte_extensions_gds\([\s\S]*?\)\n"
    r"\)\n\n"
    r"print\(f\"Exported \{len\(mte_export_df\)\}[\s\S]*?"
    r"display\(mte_export_df\)\n?",
    re.MULTILINE,
)

STANDALONE_EXPORT_CELL = re.compile(
    r"^# 5\.3 export[\s\S]*display\(mte_export_df\)$",
    re.MULTILINE,
)

FINAL_MD = """## Final export — complete routed RTEG (steps 4–6.3)

**~30 s read**

**Call:** `export_full_rteg_gds(rteg_assemblies, all_mte, FINAL_OUT, layermap=..., parent=..., mbe_extensions=all_mbe, mbe_bodies=all_mbe_body)`

Run this cell **after** steps 6.2 and 6.3 so `all_mbe_body` includes both routing styles (collar_extend + center_pad).

**Output:** `draft_output/final_rteg/{parent}_RTEG1_{index:02d}_{inst_name}_routed.gds` — one file per resonator with die frame, PPD, resonator, MTE routes, and MBE signal/ground from every pipeline step. Open in KLayout with the sidecar `.lyp`.
"""

FINAL_CODE = """# Final export — all pipeline geometry in one GDS per resonator.

from src.export_gds import export_summary_df
from src.rteg_mte_extensions import export_full_rteg_gds

FINAL_OUT = DRAFT / "final_rteg"
final_export_df = export_summary_df(
    export_full_rteg_gds(
        rteg_assemblies,
        all_mte,
        FINAL_OUT,
        layermap=layermap,
        parent=parent,
        mbe_extensions=all_mbe,
        mbe_bodies=all_mbe_body,
    )
)

print(f"Exported {len(final_export_df)} complete RTEG GDS files to {FINAL_OUT}")
display(final_export_df)
"""


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def main() -> None:
    nb = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    cells = nb["cells"]

    for cell in cells:
        if cell.get("cell_type") != "code":
            continue
        src = "".join(cell.get("source", []))
        if "export_full_rteg_gds" in src:
            continue
        if STANDALONE_EXPORT_CELL.match(src.strip()):
            cell["cell_type"] = "markdown"
            cell["source"] = [
                "### 5.3 — Checkpoint\n\n"
                "MTE extensions are built in the previous cell. "
                "GDS export is deferred to **Final export** at the end of the notebook "
                "so every step (5.4–6.3) is included in one write.\n"
            ]
            cell.pop("outputs", None)
            cell.pop("execution_count", None)
            continue
        if "export_mte_extensions_gds" not in src:
            continue
        cleaned = EXPORT_BLOCK.sub("\n", src)
        cleaned = cleaned.replace(
            "from src.export_gds import export_summary_df\n", ""
        )
        cleaned = cleaned.replace(
            "from src.rteg_mte_extensions import export_mte_extensions_gds\n", ""
        )
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip() + "\n"
        cell["source"] = [cleaned]
        cell["outputs"] = []
        cell["execution_count"] = None

    if not any("export_full_rteg_gds" in "".join(c.get("source", [])) for c in cells):
        cells.append(
            {
                "cell_type": "markdown",
                "id": _new_id(),
                "metadata": {},
                "source": [FINAL_MD],
            }
        )
        cells.append(
            {
                "cell_type": "code",
                "id": _new_id(),
                "metadata": {},
                "execution_count": None,
                "outputs": [],
                "source": [FINAL_CODE],
            }
        )

    NOTEBOOK.write_text(json.dumps(nb, indent=2) + "\n", encoding="utf-8")
    print(f"Patched {NOTEBOOK}")


if __name__ == "__main__":
    main()
