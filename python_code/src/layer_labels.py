"""Map GDS geometry layer pairs to Skyworks layer names (uses a loaded LayerMap)."""
from __future__ import annotations

import gdstk

from layermap import LayerMap


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
