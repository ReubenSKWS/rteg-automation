"""
Separate individual resonators out of a filter-variant layout.

Ports the identification logic from Jing Yang's SKILL script
(rdsBawTEGAutoFromTemp.il). The key facts encoded there:

lines 178–179, 311

- A "resonator" is a *placed instance* whose referenced cell (master) name
  starts with one of: series, shunt, rcap, mimcap.
  (SKILL lines 178-179, 311.)
- Via structures that travel with resonators have masters starting with 'vtb'.
- Filter-variant top cells follow a naming convention: the name splits into
  exactly 3 parts on '_' and ends in two digits, e.g. 'AAA_BBB_07'.
  (SKILL lines 34-35.)
- Splits/cascades are instances named S1A, S1B... or P1A, P1B...; they group
  by stripping the trailing letter. (SKILL lines 216-267.)

This module only does *identification and separation* — it does not build
RTEG templates, route metal, or place vias. That is downstream work.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import gdstk

from layermap import LAYERMAP_PATH, describe_layers, gds_pairs_in_cell, load_layermap

# Master-name prefixes that mark a placed instance as a resonator.
RESONATOR_PREFIXES = ("series", "shunt", "rcap", "mimcap")
VIA_PREFIX = "vtb"

# Filter-variant top-cell convention: 3 underscore-parts, ending in 2 digits.
_VARIANT_RE = re.compile(r"^[^_]+_[^_]+_.*\d\d$")
# Split/cascade instance names: S1A / P1A / S2B ... -> base 'S1', 'P1', 'S2'.
_SPLIT_RE = re.compile(r"^([SP]\d+)[A-Z]$")


@dataclass
class Resonator:
    """One resonator instance found inside a parent variant cell."""

    inst_name: str          # the instance's own name (e.g. 'S1A', 'P3')
    master_name: str        # the referenced cell name (e.g. 'series_v3')
    res_type: str           # 'series' | 'shunt' | 'rcap' | 'mimcap'
    origin: tuple[float, float]   # placement (x, y) in microns
    rotation: float
    magnification: float
    x_reflection: bool
    reference: gdstk.Reference = field(repr=False)

    @property
    def split_base(self) -> str | None:
        """'S1' for an instance named 'S1A', else None (not a split)."""
        m = _SPLIT_RE.match(self.inst_name)
        return m.group(1) if m else None


def _classify(master_name: str) -> str | None:
    for prefix in RESONATOR_PREFIXES:
        if master_name.startswith(prefix):
            return prefix
    return None


def is_variant_cell(cell_name: str) -> bool:
    """True if the cell name matches the filter-variant naming convention."""
    return bool(_VARIANT_RE.match(cell_name))


def find_resonators(cell: gdstk.Cell) -> list[Resonator]:
    """All resonator instances directly placed in `cell`."""
    found: list[Resonator] = []
    for ref in cell.references:
        master = ref.cell.name if ref.cell is not None else ""
        res_type = _classify(master)
        if res_type is None:
            continue
        # gdstk arrays: a single reference may represent repetitions, but
        # resonators in these layouts are singular placements. Use origin.
        ox, oy = ref.origin
        # Recover the instance's own name from a property if present;
        # gdstk has no native instance name, so fall back to the master.
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
    """All vtb (via) instances directly placed in `cell`."""
    return [
        ref
        for ref in cell.references
        if ref.cell is not None and ref.cell.name.startswith(VIA_PREFIX)
    ]


def _instance_name(ref: gdstk.Reference) -> str | None:
    """
    GDSII references carry no instance name natively. Some flows stash it in
    a property; check the common slots. Returns None if not found.
    """
    props = getattr(ref, "properties", None)
    if not props:
        return None
    for p in props:
        # gdstk properties are [name, value, ...]; names vary by flow.
        if p and isinstance(p[0], str) and p[0].lower() in {"name", "instname"}:
            val = p[1]
            return val.decode() if isinstance(val, bytes) else str(val)
    return None


def vias_near(
    res: Resonator, vias: list[gdstk.Reference], margin: float = 10.0
) -> list[gdstk.Reference]:
    """
    Vias whose placement falls within the resonator's bbox expanded by
    `margin` microns. Mirrors the SKILL bbox+10 overlap test (lines 543-553).
    Uses the referenced cell bounding box translated to the instance origin.
    """
    rb = res.reference.cell.bounding_box()
    if rb is None:
        return []
    (rx0, ry0), (rx1, ry1) = rb
    ox, oy = res.origin
    x0, y0 = rx0 + ox - margin, ry0 + oy - margin
    x1, y1 = rx1 + ox + margin, ry1 + oy + margin
    out = []
    for v in vias:
        vx, vy = v.origin
        if x0 <= vx <= x1 and y0 <= vy <= y1:
            out.append(v)
    return out


def group_splits(resonators: list[Resonator]) -> dict[str, list[Resonator]]:
    """
    Group split/cascade resonators by base name. 'S1A','S1B' -> {'S1': [...]}.
    Non-split resonators are returned keyed by their own instance name.
    """
    groups: dict[str, list[Resonator]] = {}
    for r in resonators:
        key = r.split_base or r.inst_name
        groups.setdefault(key, []).append(r)
    return groups


def separate(
    lib: gdstk.Library, variant_only: bool = True
) -> dict[str, list[Resonator]]:
    """
    Walk a library and return {parent_cell_name: [Resonator, ...]}.

    If variant_only is True, only cells matching the filter-variant naming
    convention are searched (matches the SKILL cell-selection filter).
    """
    result: dict[str, list[Resonator]] = {}
    for cell in lib.cells:
        if variant_only and not is_variant_cell(cell.name):
            continue
        res = find_resonators(cell)
        if res:
            result[cell.name] = res
    return result


if __name__ == "__main__":
    from pathlib import Path

    gds_path = Path(__file__).parent / "KB331_N_01_clean.gds"
    layermap = load_layermap()
    lib = gdstk.read_gds(gds_path)
    result = separate(lib)

    print(f"GDS: {gds_path}")
    print(f"Layermap: {LAYERMAP_PATH} ({len(layermap)} layers)")
    print(f"Cells with resonators: {len(result)}")
    for cell_name, res_list in result.items():
        cell = next(c for c in lib.cells if c.name == cell_name)
        groups = group_splits(res_list)
        vias = find_vias(cell)
        print(
            f"\n{cell_name}: {len(res_list)} resonators, "
            f"{len(groups)} groups, {len(vias)} vias"
        )
        for r in res_list:
            xy = tuple(round(x, 1) for x in r.origin)
            layers = describe_layers(
                gds_pairs_in_cell(r.reference.cell), layermap
            )
            print(f"  {r.inst_name:30s} {r.res_type:8s} @ {xy}")
            print(f"    layers: {', '.join(layers[:6])}", end="")
            if len(layers) > 6:
                print(f" ... +{len(layers) - 6} more", end="")
            print()
