"""
Parse Skyworks's layermap file into lookups between layer names and
(layer_number, datatype) GDS pairs.

The layermap format is whitespace-separated columns:

    BAW_MBE     drawing 2  0
    BAW_MTE     drawing 5  0
    <name>      <purpose> <layer_number> <datatype>

Blank lines are ignored.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import gdstk

LAYERMAP_PATH = Path(__file__).parent / "layermap"


@dataclass(frozen=True)
class LayerEntry:
    name: str
    purpose: str
    layer: int
    datatype: int

    @property
    def gds_pair(self) -> tuple[int, int]:
        return (self.layer, self.datatype)


class LayerMap:
    def __init__(self, entries: list[LayerEntry]) -> None:
        self._by_name: dict[str, LayerEntry] = {e.name: e for e in entries}
        # (layer, datatype) -> entry. First definition wins on collisions.
        self._by_pair: dict[tuple[int, int], LayerEntry] = {}
        for e in entries:
            self._by_pair.setdefault(e.gds_pair, e)

    @classmethod
    def from_file(cls, path: str | Path) -> "LayerMap":
        entries: list[LayerEntry] = []
        for lineno, raw in enumerate(Path(path).read_text().splitlines(), start=1):
            line = raw.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 4:
                raise ValueError(
                    f"{path}:{lineno}: expected 4 columns, got {len(parts)}: {raw!r}"
                )
            name, purpose, layer_s, datatype_s = parts
            try:
                entries.append(
                    LayerEntry(name, purpose, int(layer_s), int(datatype_s))
                )
            except ValueError as exc:
                raise ValueError(f"{path}:{lineno}: bad number in {raw!r}") from exc
        return cls(entries)

    def pair(self, name: str) -> tuple[int, int]:
        """(layer, datatype) for a layer name, e.g. 'BAW_MBE' -> (2, 0)."""
        return self._by_name[name].gds_pair

    def name(self, layer: int, datatype: int = 0) -> str | None:
        """Layer name for a (layer, datatype) pair, or None if unmapped."""
        entry = self._by_pair.get((layer, datatype))
        return entry.name if entry else None

    def __contains__(self, name: str) -> bool:
        return name in self._by_name

    def __len__(self) -> int:
        return len(self._by_name)


def load_layermap(path: str | Path | None = None) -> LayerMap:
    """Load the Skyworks layermap; defaults to ``LAYERMAP_PATH``."""
    return LayerMap.from_file(path or LAYERMAP_PATH)


def gds_pairs_in_cell(cell: gdstk.Cell) -> set[tuple[int, int]]:
    """All (layer, datatype) pairs used by geometry in a cell."""
    pairs: set[tuple[int, int]] = set()
    for poly in cell.polygons:
        pairs.add((poly.layer, poly.datatype))
    for path in cell.paths:
        layers = getattr(path, "layers", None)
        datatypes = getattr(path, "datatypes", None)
        if layers is not None and datatypes is not None:
            for layer, datatype in zip(layers, datatypes):
                pairs.add((layer, datatype))
        else:
            pairs.add((path.layer, path.datatype))
    for label in cell.labels:
        pairs.add((label.layer, label.texttype))
    return pairs


def describe_layers(pairs: set[tuple[int, int]], layermap: LayerMap) -> list[str]:
    """Human-readable layer list, e.g. 'BAW_MBE (2/0)'."""
    lines: list[str] = []
    for layer, datatype in sorted(pairs):
        name = layermap.name(layer, datatype)
        label = name if name else "?"
        lines.append(f"{label} ({layer}/{datatype})")
    return lines


if __name__ == "__main__":
    import sys

    lm = load_layermap(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"Loaded {len(lm)} layers")
    for nm in ("BAW_MBE", "BAW_MTE", "BAW_LABEL"):
        if nm in lm:
            print(f"  {nm}: {lm.pair(nm)}")
    # print(f"  (2, 0) -> {lm.name(2, 0)}")
