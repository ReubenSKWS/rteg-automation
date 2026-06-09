"""
Identify resonators and vtb vias in a filter-variant GDS layout.

Ports identification rules from Jing Yang's SKILL script (rdsBawTEGAutoFromTemp.il):
- Resonator masters start with: series, shunt, rcap, mimcap
- Via masters start with: vtb

This module only identifies instances — no layermap, routing, or RTEG assembly.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import gdstk

RESONATOR_PREFIXES = ("series", "shunt", "rcap", "mimcap")
VIA_PREFIX = "vtb"

_VARIANT_RE = re.compile(r"^[^_]+_[^_]+_.*\d\d$")
_SPLIT_RE = re.compile(r"^([SP]\d+)[A-Z]$")


@dataclass
class Resonator:
    """One resonator instance found inside a parent variant cell."""

    inst_name: str
    master_name: str
    res_type: str
    origin: tuple[float, float]
    rotation: float
    magnification: float
    x_reflection: bool
    reference: gdstk.Reference = field(repr=False)

    @property
    def split_base(self) -> str | None:
        m = _SPLIT_RE.match(self.inst_name)
        return m.group(1) if m else None


@dataclass
class IdentificationResult:
    """Resonators and vtb vias found under one filter-variant parent cell."""

    parent: str
    library: gdstk.Library
    resonators: list[Resonator]
    vias: list[gdstk.Reference]

    @property
    def filter_cell(self) -> gdstk.Cell:
        return next(c for c in self.library.cells if c.name == self.parent)

    def resonator_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for i, r in enumerate(self.resonators):
            rows.append(
                {
                    "index": i,
                    "inst_name": r.inst_name,
                    "master_name": r.master_name,
                    "type": r.res_type,
                    "origin_x": round(r.origin[0], 1),
                    "origin_y": round(r.origin[1], 1),
                    "rotation_deg": round(r.rotation * 180 / 3.141592653589793, 1),
                    "split_base": r.split_base,
                }
            )
        return rows

    def via_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for i, v in enumerate(self.vias):
            master = v.cell.name if v.cell is not None else "?"
            rows.append(
                {
                    "index": i,
                    "master_name": master,
                    "origin_x": round(v.origin[0], 1),
                    "origin_y": round(v.origin[1], 1),
                    "rotation_deg": round(v.rotation * 180 / 3.141592653589793, 1),
                }
            )
        return rows


def _classify(master_name: str) -> str | None:
    for prefix in RESONATOR_PREFIXES:
        if master_name.startswith(prefix):
            return prefix
    return None


def is_variant_cell(cell_name: str) -> bool:
    return bool(_VARIANT_RE.match(cell_name))


def _instance_name(ref: gdstk.Reference) -> str | None:
    props = getattr(ref, "properties", None)
    if not props:
        return None
    for p in props:
        if p and isinstance(p[0], str) and p[0].lower() in {"name", "instname"}:
            val = p[1]
            return val.decode() if isinstance(val, bytes) else str(val)
    return None


def find_resonators(cell: gdstk.Cell) -> list[Resonator]:
    found: list[Resonator] = []
    for ref in cell.references:
        master = ref.cell.name if ref.cell is not None else ""
        res_type = _classify(master)
        if res_type is None:
            continue
        ox, oy = ref.origin
        inst_name = _instance_name(ref) or master
        found.append(
            Resonator(
                inst_name=inst_name,
                master_name=master,
                res_type=res_type,
                origin=(float(ox), float(oy)),
                rotation=float(ref.rotation),
                magnification=float(ref.magnification),
                x_reflection=bool(ref.x_reflection),
                reference=ref,
            )
        )
    return found


def find_vias(cell: gdstk.Cell) -> list[gdstk.Reference]:
    return [
        ref
        for ref in cell.references
        if ref.cell is not None and ref.cell.name.startswith(VIA_PREFIX)
    ]


def group_splits(resonators: list[Resonator]) -> dict[str, list[Resonator]]:
    groups: dict[str, list[Resonator]] = {}
    for r in resonators:
        key = r.split_base or r.inst_name
        groups.setdefault(key, []).append(r)
    return groups


def vias_near(
    res: Resonator, vias: list[gdstk.Reference], margin: float = 10.0
) -> list[gdstk.Reference]:
    rb = res.reference.cell.bounding_box()
    if rb is None:
        return []
    (rx0, ry0), (rx1, ry1) = rb
    ox, oy = res.origin
    x0, y0 = rx0 + ox - margin, ry0 + oy - margin
    x1, y1 = rx1 + ox + margin, ry1 + oy + margin
    return [v for v in vias if x0 <= v.origin[0] <= x1 and y0 <= v.origin[1] <= y1]


def separate(
    lib: gdstk.Library, variant_only: bool = True
) -> dict[str, list[Resonator]]:
    result: dict[str, list[Resonator]] = {}
    for cell in lib.cells:
        if variant_only and not is_variant_cell(cell.name):
            continue
        res = find_resonators(cell)
        if res:
            result[cell.name] = res
    return result


def identify(
    gds: str | Path | gdstk.Library,
    *,
    parent_cell: str | None = None,
    variant_only: bool = True,
) -> IdentificationResult:
    """
    Load (if needed) and identify resonators + vtb vias under one parent cell.

    Returns tabular rows via ``resonator_rows()`` / ``via_rows()`` and keeps
    ``Resonator`` / ``Reference`` objects for downstream geometry code.
    """
    if isinstance(gds, gdstk.Library):
        lib = gds
    else:
        lib = gdstk.read_gds(Path(gds))

    by_parent = separate(lib, variant_only=variant_only)
    if not by_parent:
        raise ValueError("No resonators found in GDS")

    if parent_cell is None:
        parent = sorted(by_parent.keys())[0]
    else:
        if parent_cell not in by_parent:
            raise ValueError(f"No resonators under parent cell {parent_cell!r}")
        parent = parent_cell

    cell = next(c for c in lib.cells if c.name == parent)
    return IdentificationResult(
        parent=parent,
        library=lib,
        resonators=by_parent[parent],
        vias=find_vias(cell),
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python separate.py <filter.gds> [parent_cell]", file=sys.stderr)
        sys.exit(1)

    result = identify(sys.argv[1], parent_cell=sys.argv[2] if len(sys.argv) > 2 else None)
    print(f"Parent: {result.parent}")
    print(f"Resonators: {len(result.resonators)}  |  Vias: {len(result.vias)}")
    for row in result.resonator_rows():
        print(
            f"  [{row['index']}] {row['inst_name']:30s} {row['type']:8s} "
            f"@ ({row['origin_x']}, {row['origin_y']})"
        )
