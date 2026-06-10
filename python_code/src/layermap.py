"""
Parse the Skyworks layermap file into layer name <-> (layer, datatype) lookups.

Format (whitespace-separated):

    BAW_MBE     drawing 2  0
    BAW_MTE     drawing 5  0
    <name>      <purpose> <layer_number> <datatype>
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
        self._by_pair: dict[tuple[int, int], LayerEntry] = {}
        for e in entries:
            self._by_pair.setdefault(e.gds_pair, e)

    @classmethod
    def from_file(cls, path: str | Path) -> "LayerMap":
        entries: list[LayerEntry] = []
        path = Path(path)
        for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
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

    def entry(self, layer: int, datatype: int) -> LayerEntry | None:
        """Full layermap row for a GDS pair, if mapped."""
        return self._by_pair.get((layer, datatype))

    def is_mapped(self, layer: int, datatype: int) -> bool:
        return (layer, datatype) in self._by_pair

    def known_pairs(self) -> frozenset[tuple[int, int]]:
        """All ``(layer, datatype)`` pairs defined in the layermap."""
        return frozenset(self._by_pair)

    def entries_for_pairs(
        self, pairs: set[tuple[int, int]] | frozenset[tuple[int, int]]
    ) -> list[LayerEntry]:
        """Layermap rows for the given GDS pairs, sorted by layer/datatype."""
        out = [self._by_pair[p] for p in pairs if p in self._by_pair]
        return sorted(out, key=lambda e: (e.layer, e.datatype))

    def __contains__(self, name: str) -> bool:
        return name in self._by_name

    def __len__(self) -> int:
        return len(self._by_name)


def load_layermap(path: str | Path) -> LayerMap:
    """Load the Skyworks layermap from ``path``."""
    return LayerMap.from_file(path)
