"""Rewrite single_run.ipynb to the 8-step intercept routing flow."""
from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK = Path(__file__).resolve().parents[1] / "single_run.ipynb"

CELLS = [
    (
        "markdown",
        "# KB331 single-run — SKILL intercept routing\n\n"
        "Linear pipeline through step 8. Final GDS only: "
        "`draft_output/{parent}_RTEG1_{inst}.gds`.",
    ),
    (
        "code",
        "from pathlib import Path\n\n"
        "ROOT = Path.cwd()\n"
        "SRC = ROOT / 'src'\n"
        "INPUT = ROOT / 'input_files'\n"
        "DRAFT = ROOT / 'draft_output'\n"
        "DRAFT.mkdir(exist_ok=True)\n\n"
        "FILTER = INPUT / 'KB331_N_01.gds'\n"
        "PPD = INPUT / 'GSG_frame.gds'\n"
        "FRAME = INPUT / 'KB331_N_Frame.gds'\n"
        "LAYERMAP = INPUT / 'layermap'\n",
    ),
    ("markdown", "## 1 — Inputs"),
    (
        "code",
        "import sys\n"
        "sys.path.insert(0, str(SRC))\n\n"
        "from layermap import load_layermap\n\n"
        "layermap = load_layermap(LAYERMAP)\n"
        "for path in (FILTER, PPD, FRAME):\n"
        "    assert path.is_file(), path\n"
        "print('layermap pairs:', len(layermap.known_pairs()))\n",
    ),
    ("markdown", "## 2 — Identify"),
    (
        "code",
        "import pandas as pd\n"
        "from separate import identify\n\n"
        "identification = identify(FILTER)\n"
        "parent = identification.parent\n"
        "res_list = identification.resonators\n"
        "res_df = pd.DataFrame(identification.resonator_rows())\n"
        "display(res_df)\n",
    ),
    ("markdown", "## 3 — PPD placement"),
    (
        "code",
        "from prep_resonator_ppd import prep_resonator_ppd\n\n"
        "ppd_assemblies = prep_resonator_ppd(\n"
        "    res_df, res_list, PPD, identification=identification, layermap=layermap\n"
        ")\n"
        "len(ppd_assemblies)\n",
    ),
    ("markdown", "## 4 — Die frame (no GDS export)"),
    (
        "code",
        "from prep_rteg_frame import prep_rteg_in_frame, assemblies_summary_df\n\n"
        "frame_assemblies = prep_rteg_in_frame(ppd_assemblies, FRAME, parent=parent)\n"
        "display(assemblies_summary_df(frame_assemblies))\n",
    ),
    ("markdown", "## 5 — Collect + classify"),
    (
        "code",
        "from rteg_classify import classify_nodes, classification_summary_table\n"
        "from rteg_collect import collect_geometry_roles, collect_orientation_inputs\n\n"
        "roles_by_index = {}\n"
        "classify_by_index = {}\n"
        "summary_rows = []\n"
        "for asm, res in zip(frame_assemblies, res_list, strict=True):\n"
        "    roles = collect_geometry_roles(asm, res, identification, layermap)\n"
        "    orientation = collect_orientation_inputs(\n"
        "        asm, res, identification, layermap, ground_plates=roles.ground_plates\n"
        "    )\n"
        "    classification = classify_nodes(\n"
        "        roles.ground_plates, roles.preserved, orientation=orientation, res_type=res.res_type\n"
        "    )\n"
        "    roles_by_index[asm.index] = roles\n"
        "    classify_by_index[asm.index] = classification\n"
        "    summary_rows.extend(\n"
        "        classification_summary_table(\n"
        "            classification, index=asm.index, inst_name=asm.inst_name, res_type=res.res_type\n"
        "        )\n"
        "    )\n"
        "display(pd.DataFrame(summary_rows))\n",
    ),
    ("markdown", "## 6 — Signal routes (die intercepts)"),
    (
        "code",
        "from rteg_route import build_signal_routes, route_overview_rows\n\n"
        "routes = build_signal_routes(roles_by_index, classify_by_index, layermap)\n"
        "display(pd.DataFrame(route_overview_rows(routes)))\n",
    ),
    ("markdown", "## 7 — MBE ground filler"),
    (
        "code",
        "from rteg_mbe_body import (\n"
        "    build_mbe_body_collar_extends,\n"
        "    merge_mbe_bodies,\n"
        "    mbe_body_overview_rows,\n"
        ")\n"
        "from rteg_mbe_body_center_pad import build_mbe_body_center_pads\n\n"
        "collar_bodies = build_mbe_body_collar_extends(\n"
        "    roles_by_index, classify_by_index, routes, layermap\n"
        ")\n"
        "center_bodies = build_mbe_body_center_pads(\n"
        "    roles_by_index, classify_by_index, routes, layermap\n"
        ")\n"
        "mbe_bodies = merge_mbe_bodies(collar_bodies, center_bodies)\n"
        "display(pd.DataFrame(mbe_body_overview_rows(mbe_bodies)))\n",
    ),
    ("markdown", "## 8 — Export"),
    (
        "code",
        "from export_gds import export_rteg_gds, export_summary_df\n\n"
        "results = export_rteg_gds(\n"
        "    frame_assemblies,\n"
        "    routes,\n"
        "    mbe_bodies,\n"
        "    DRAFT,\n"
        "    layermap=layermap,\n"
        "    parent=parent,\n"
        ")\n"
        "display(export_summary_df(results))\n",
    ),
]


def main() -> None:
    nb = {
        "cells": [
            {
                "cell_type": cell_type,
                "metadata": {},
                "source": [text] if isinstance(text, str) else text,
                **(
                    {"outputs": [], "execution_count": None}
                    if cell_type == "code"
                    else {}
                ),
            }
            for cell_type, text in CELLS
        ],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    NOTEBOOK.write_text(json.dumps(nb, indent=1), encoding="utf-8")
    print(f"Wrote {NOTEBOOK}")


if __name__ == "__main__":
    main()
