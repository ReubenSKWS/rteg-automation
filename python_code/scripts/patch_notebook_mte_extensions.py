"""One-off patch: point single_run.ipynb step 5.3 at rteg_mte_extensions."""
from __future__ import annotations

import json
from pathlib import Path

NB = Path(__file__).resolve().parents[1] / "single_run.ipynb"


def main() -> None:
    nb = json.loads(NB.read_text(encoding="utf-8"))
    for cell in nb["cells"]:
        src = cell.get("source", [])
        text = "".join(src)
        if not text:
            continue
        if "| 5.3 | MTE extensions |" in text:
            cell["source"] = [
                line.replace(
                    "`rteg_signal.py`, `rteg_mte_route.py`",
                    "`rteg_mte_extensions.py`",
                ).replace(
                    "`rteg_signal.py`, `export_gds.py` | `export_signal_rteg_gds`",
                    "`rteg_mte_extensions.py`, `export_gds.py` | `export_mte_extensions_gds`",
                )
                for line in src
            ]
        if "**Files:** `src/rteg_signal.py`, `src/rteg_mte_route.py`" in text:
            cell["source"] = [
                line.replace(
                    "**Files:** `src/rteg_signal.py`, `src/rteg_mte_route.py`",
                    "**Files:** `src/rteg_mte_extensions.py`",
                )
                for line in src
            ]
        if "from rteg_signal import" in text and "build_mte_extensions" in text:
            cell["source"] = [
                "from export_gds import export_summary_df\n",
                "from rteg_mte_extensions import (\n",
                "    build_mte_extensions,\n",
                "    export_mte_extensions_gds,\n",
                "    mte_extensions_overview_rows,\n",
                "    mte_intercept_breakdown_rows,\n",
                ")\n",
                "\n",
                "all_mte = build_mte_extensions(all_roles, layermap)\n",
                "\n",
                "inst_names = {idx: roles.inst_name for idx, roles in all_roles.items()}\n",
                "\n",
                "mte_overview_df = pd.DataFrame(\n",
                "    mte_extensions_overview_rows(all_mte, inst_names=inst_names)\n",
                ").sort_values(\"index\")\n",
                "\n",
                "display(mte_overview_df)\n",
                "print(f\"Drew MTE extensions for {len(all_mte)} resonators\")\n",
                "\n",
                "mte_intercept_df = pd.DataFrame(\n",
                "    mte_intercept_breakdown_rows(all_mte, inst_names=inst_names)\n",
                ").sort_values(\"index\")\n",
                "\n",
                "print(\"Intercept breakdown (two end-cap edges on preserved collar):\")\n",
                "display(mte_intercept_df)\n",
                "\n",
                "MTE_OUT = DRAFT / \"MTE_generated_deterministic\"\n",
                "mte_export_df = export_summary_df(\n",
                "    export_mte_extensions_gds(\n",
                "        rteg_assemblies,\n",
                "        all_mte,\n",
                "        MTE_OUT,\n",
                "        layermap=layermap,\n",
                "        parent=parent,\n",
                "    )\n",
                ")\n",
                "\n",
                "print(f\"Exported {len(mte_export_df)} MTE GDS files to {MTE_OUT}\")\n",
            ]
    NB.write_text(json.dumps(nb, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Patched {NB}")


if __name__ == "__main__":
    main()
