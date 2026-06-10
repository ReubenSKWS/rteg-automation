"""
Write in-memory RTEG assemblies to standalone GDS files.

Works with any pipeline object that exposes ``index``, ``inst_name``,
``top_cell``, ``library``, and ``flatten()`` — e.g. ``ResonatorPpdAssembly``
(step 3) or ``RtegFrameAssembly`` (step 4), and future routed assemblies.

When a layermap is supplied, export keeps only geometry on mapped GDS pairs
and writes a matching KLayout ``.lyp`` sidecar with Skyworks layer names.
"""
from __future__ import annotations

import warnings
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import gdstk
import pandas as pd

try:
    from .layermap import LayerMap, load_layermap
except ImportError:
    from layermap import LayerMap, load_layermap

_LYP_PALETTE = (
    "#be0032",
    "#008856",
    "#0067a5",
    "#f38400",
    "#875692",
    "#654522",
    "#8db600",
    "#f99379",
    "#604e97",
    "#e25822",
)


class ExportableAssembly(Protocol):
    index: int
    inst_name: str
    top_cell: gdstk.Cell
    library: gdstk.Library

    def flatten(self) -> gdstk.Cell: ...


FilenameFn = Callable[[ExportableAssembly], str]


def _looks_like_layermap(obj: object) -> bool:
    """True for any loaded LayerMap instance (avoids dual-import isinstance bugs)."""
    if obj is None or isinstance(obj, (str, Path)):
        return False
    return (
        callable(getattr(obj, "pair", None))
        and callable(getattr(obj, "known_pairs", None))
        and callable(getattr(obj, "name", None))
    )


def _resolve_layermap(layermap: LayerMap | str | Path | None) -> LayerMap | None:
    if layermap is None:
        return None
    if _looks_like_layermap(layermap):
        return layermap  # type: ignore[return-value]
    if isinstance(layermap, (str, Path)):
        return load_layermap(layermap)
    raise TypeError(
        f"layermap must be a LayerMap, path, or None; got {type(layermap).__name__}"
    )


def _cells_reachable_from(top_cell: gdstk.Cell) -> set[str]:
    """Names of ``top_cell`` and every cell referenced beneath it."""
    needed: set[str] = set()

    def collect(cell: gdstk.Cell) -> None:
        if cell.name in needed:
            return
        needed.add(cell.name)
        for ref in cell.references:
            collect(ref.cell)

    collect(top_cell)
    return needed


def _path_pairs(path: gdstk.FlexPath | gdstk.RobustPath) -> set[tuple[int, int]]:
    return set(zip(path.layers, path.datatypes, strict=True))


def _path_allowed(
    path: gdstk.FlexPath | gdstk.RobustPath,
    allowed: frozenset[tuple[int, int]],
) -> bool:
    return _path_pairs(path).issubset(allowed)


def _pairs_in_cell(cell: gdstk.Cell) -> set[tuple[int, int]]:
    pairs: set[tuple[int, int]] = set()
    for poly in cell.polygons:
        pairs.add((poly.layer, poly.datatype))
    for path in cell.paths:
        pairs.update(_path_pairs(path))
    for label in cell.labels:
        pairs.add((label.layer, label.texttype))
    return pairs


def _filter_cell_to_layermap(cell: gdstk.Cell, allowed: frozenset[tuple[int, int]]) -> gdstk.Cell:
    """Copy ``cell`` keeping only geometry on layermap-defined layer pairs."""
    out = gdstk.Cell(cell.name)
    for poly in cell.polygons:
        if (poly.layer, poly.datatype) in allowed:
            out.add(poly)
    for path in cell.paths:
        if _path_allowed(path, allowed):
            out.add(path)
    for label in cell.labels:
        if (label.layer, label.texttype) in allowed:
            out.add(label)
    return out


def _copy_reference(ref: gdstk.Reference, cell_lookup: dict[str, gdstk.Cell]) -> gdstk.Reference:
    return gdstk.Reference(
        cell_lookup[ref.cell.name],
        origin=ref.origin,
        rotation=ref.rotation,
        magnification=ref.magnification,
        x_reflection=ref.x_reflection,
    )


def _filter_library_to_layermap(
    assembly: ExportableAssembly,
    layermap: LayerMap,
) -> tuple[gdstk.Library, set[tuple[int, int]]]:
    """
    Reachable hierarchy with layermap-only geometry and a single top cell.

    Returns the export library and the set of GDS pairs present after filtering.
    """
    allowed = layermap.known_pairs()
    needed = _cells_reachable_from(assembly.top_cell)
    source = {cell.name: cell for cell in assembly.library.cells}
    missing = needed - source.keys()
    if missing:
        raise ValueError(f"Assembly library missing cells: {sorted(missing)}")

    copied: dict[str, gdstk.Cell] = {}

    def build(name: str) -> gdstk.Cell:
        if name in copied:
            return copied[name]
        filtered = _filter_cell_to_layermap(source[name], allowed)
        for ref in source[name].references:
            build(ref.cell.name)
            filtered.add(_copy_reference(ref, copied))
        copied[name] = filtered
        return filtered

    build(assembly.top_cell.name)

    out = gdstk.Library()
    for name in needed:
        out.add(copied[name])

    used_pairs: set[tuple[int, int]] = set()
    for name in needed:
        used_pairs.update(_pairs_in_cell(copied[name]))

    dropped = used_pairs - allowed
    if dropped:
        warnings.warn(
            f"Dropped unmapped layer pairs during export: {sorted(dropped)}",
            stacklevel=3,
        )
    return out, used_pairs


def _export_library(
    assembly: ExportableAssembly,
    layermap: LayerMap | None = None,
) -> tuple[gdstk.Library, set[tuple[int, int]] | None]:
    """
    Library containing only the assembly top cell and its hierarchy.

    Writing ``assembly.library`` verbatim leaves orphan frame/pad cells from
    the source GDS as extra top-level cells; layout viewers then open one of
    those fragments instead of the full RTEG.
    """
    if layermap is not None:
        return _filter_library_to_layermap(assembly, layermap)

    needed = _cells_reachable_from(assembly.top_cell)
    out = gdstk.Library()
    for cell in assembly.library.cells:
        if cell.name in needed:
            out.add(cell)
    if assembly.top_cell.name not in {c.name for c in out.cells}:
        out.add(assembly.top_cell)
    return out, None


def _layer_color(layer: int, datatype: int) -> str:
    idx = (layer * 17 + datatype * 31) % len(_LYP_PALETTE)
    return _LYP_PALETTE[idx]


def write_klayout_lyp(
    layermap: LayerMap,
    pairs: set[tuple[int, int]] | frozenset[tuple[int, int]],
    path: str | Path,
) -> Path:
    """Write a KLayout layer-properties file for ``pairs`` using layermap names."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    root = ET.Element("layer-properties")
    for entry in layermap.entries_for_pairs(pairs):
        props = ET.SubElement(root, "properties")
        color = _layer_color(entry.layer, entry.datatype)
        display = f"{entry.name}.{entry.purpose} ({entry.layer}/{entry.datatype})"
        ET.SubElement(props, "name").text = display
        ET.SubElement(props, "source").text = f"{entry.layer}/{entry.datatype}@1"
        ET.SubElement(props, "frame-color").text = color
        ET.SubElement(props, "fill-color").text = color
        ET.SubElement(props, "dither-pattern").text = "I0"
        ET.SubElement(props, "line-style").text = "I0"
        ET.SubElement(props, "visible").text = "true"
        ET.SubElement(props, "transparent").text = "false"

    tree = ET.ElementTree(root)
    if hasattr(ET, "indent"):
        ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return path


@dataclass(frozen=True)
class ExportResult:
    index: int
    inst_name: str
    cell_name: str
    path: Path
    lyp_path: Path | None = None

    @property
    def size_bytes(self) -> int:
        return self.path.stat().st_size

    def summary_row(self) -> dict[str, object]:
        return {
            "index": self.index,
            "inst_name": self.inst_name,
            "cell_name": self.cell_name,
            "path": str(self.path),
            "lyp_path": str(self.lyp_path) if self.lyp_path else None,
            "size_bytes": self.size_bytes,
        }


def default_gds_filename(
    assembly: ExportableAssembly,
    *,
    parent: str | None = None,
    stage: str = "",
) -> str:
    """
    Build a GDS filename for one assembly.

    When ``parent`` is set (filter parent cell name), uses the SKILL-style
    ``{parent}_RTEG1_{inst_name}[_stage].gds`` pattern. Otherwise uses the
    assembly top cell name.
    """
    if parent:
        suffix = f"_{stage}" if stage else ""
        return f"{parent}_RTEG1_{assembly.inst_name}{suffix}.gds"
    return f"{assembly.top_cell.name}.gds"


def export_gds_one(
    assembly: ExportableAssembly,
    *,
    path: str | Path,
    layermap: LayerMap | str | Path | None = None,
    flatten: bool = False,
    write_lyp: bool = True,
) -> ExportResult:
    """Write a single assembly to ``path``."""
    if isinstance(path, LayerMap) or _looks_like_layermap(path):
        raise TypeError(
            "path must be a file path; got LayerMap. "
            "Use export_gds_one(assembly, path=..., layermap=...)."
        )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lm = _resolve_layermap(layermap)
    lyp_path: Path | None = None

    if flatten:
        allowed = lm.known_pairs() if lm is not None else None
        flat = assembly.flatten()
        if allowed is not None:
            flat = _filter_cell_to_layermap(flat, allowed)
            used_pairs = _pairs_in_cell(flat)
        else:
            used_pairs = None
        lib = gdstk.Library()
        lib.add(flat)
        lib.write_gds(str(path))
    else:
        lib, used_pairs = _export_library(assembly, lm)
        lib.write_gds(str(path))

    if lm is not None and write_lyp:
        if used_pairs is None:
            used_pairs = _pairs_in_cell(assembly.flatten())
        lyp_path = write_klayout_lyp(lm, used_pairs, path.with_suffix(".lyp"))

    return ExportResult(
        index=assembly.index,
        inst_name=assembly.inst_name,
        cell_name=assembly.top_cell.name,
        path=path,
        lyp_path=lyp_path,
    )


def export_gds(
    assemblies: Sequence[ExportableAssembly],
    output_dir: str | Path,
    *,
    layermap: LayerMap | str | Path | None = None,
    parent: str | None = None,
    stage: str = "",
    flatten: bool = False,
    write_lyp: bool = True,
    filename_fn: FilenameFn | None = None,
) -> list[ExportResult]:
    """
    Export each assembly to its own GDS file under ``output_dir``.

    Parameters
    ----------
    assemblies
        In-memory assemblies from any pipeline step.
    output_dir
        Directory to create/write files into.
    layermap
        Skyworks layermap used to filter geometry and name layers in ``.lyp``.
    parent
        Optional filter parent name for SKILL-style filenames.
    stage
        Optional stage tag appended when ``parent`` is set (e.g. ``"ppd"``,
        ``"framed"``, ``"routed"``).
    flatten
        When True, write a single flattened top cell instead of hierarchy.
    write_lyp
        When True and ``layermap`` is set, write a ``.lyp`` beside each GDS.
    filename_fn
        Override filename logic entirely. Receives each assembly; must return
        the filename only (not a full path).
    """
    if not assemblies:
        return []

    if isinstance(output_dir, LayerMap) or _looks_like_layermap(output_dir):
        raise TypeError(
            "output_dir must be a directory path; got LayerMap. "
            "Pass layermap=... as a keyword argument."
        )

    lm = _resolve_layermap(layermap)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    resolve_name = filename_fn or (
        lambda asm: default_gds_filename(asm, parent=parent, stage=stage)
    )

    results: list[ExportResult] = []
    for assembly in assemblies:
        filename = resolve_name(assembly)
        path = out_dir / filename
        results.append(
            export_gds_one(
                assembly,
                path=path,
                layermap=lm,
                flatten=flatten,
                write_lyp=write_lyp,
            )
        )
    return results


def export_summary_df(results: Sequence[ExportResult]) -> pd.DataFrame:
    return pd.DataFrame([r.summary_row() for r in results])
