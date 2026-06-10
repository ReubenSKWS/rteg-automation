"""
Agentic step 5 — emit a routed assembly with the same export surface as the
deterministic ``RtegRoutedAssembly``.

``AgenticRoutedAssembly`` exposes ``index``, ``inst_name``, ``top_cell``,
``library``, and ``flatten()`` so the existing ``export_gds`` works unchanged
(``stage="routed"``). The top cell is the flattened frame with the consumed MBE
plates removed, plus the carved ground body and the exact preserved metal — the
same emit shape as the deterministic plate merge.

## Assumptions
- Only verifier-passing sessions are exported (the loop enforces this); a failed
  result still carries a top cell for preview, but the notebook filters
  ``status == "routed"`` before export — same convention as the deterministic path.
"""
from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import gdstk

try:
    from ..ground_merge import GroundMergeResult
except ImportError:
    from ground_merge import GroundMergeResult

from .context import AgentGroundContext
from .routing_state import GroundMergeSession

Point = tuple[float, float]
Bbox = tuple[tuple[float, float], tuple[float, float]]


@dataclass
class AgenticRoutedAssembly:
    """Step-5 agentic output, export-compatible with ``export_gds``."""

    index: int
    inst_name: str
    status: str  # "routed" | "failed" | "skipped"
    skip_reason: str | None
    placement_shift: Point
    ground_body: list[gdstk.Polygon]
    bridges_applied: int
    connector_used: bool
    n_severed_fragments: int
    mbe_area_um2: float
    ground_body_hash: str
    pads_connected: tuple[str, ...]
    drc_violations: int
    tool_calls_used: int
    llm_turns_used: int
    input_tokens: int
    output_tokens: int
    wall_time_s: float
    top_cell: gdstk.Cell
    library: gdstk.Library

    def flatten(self) -> gdstk.Cell:
        return self.top_cell.flatten()

    def summary_row(self) -> dict[str, object]:
        return {
            "index": self.index,
            "inst_name": self.inst_name,
            "status": self.status,
            "skip_reason": self.skip_reason or "",
            "bridges": self.bridges_applied,
            "connector": self.connector_used,
            "severed": self.n_severed_fragments,
            "pads_connected": ",".join(sorted(self.pads_connected)),
            "mbe_area_um2": round(self.mbe_area_um2, 1),
            "ground_body_hash": self.ground_body_hash,
            "shift_x": round(self.placement_shift[0], 1),
            "shift_y": round(self.placement_shift[1], 1),
            "drc_violations": self.drc_violations,
            "tool_calls": self.tool_calls_used,
            "llm_turns": self.llm_turns_used,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "wall_time_s": round(self.wall_time_s, 1),
        }


def _bbox_close(a: Bbox, b: Bbox, tol: float = 1.0) -> bool:
    return (
        abs(a[0][0] - b[0][0]) <= tol
        and abs(a[0][1] - b[0][1]) <= tol
        and abs(a[1][0] - b[1][0]) <= tol
        and abs(a[1][1] - b[1][1]) <= tol
    )


def _build_top_cell(
    assembly,
    preserved,
    ground_body,
    consumed_bboxes,
    mbe_pair: tuple[int, int],
) -> tuple[gdstk.Cell, gdstk.Library]:
    top = gdstk.Cell(f"agentic_routed_{assembly.index}_{assembly.inst_name}")
    for poly in assembly.flatten().polygons:
        if (poly.layer, poly.datatype) == mbe_pair:
            bb = poly.bounding_box()
            if bb is not None and any(_bbox_close(bb, cb) for cb in consumed_bboxes):
                continue
        top.add(poly)
    for poly in ground_body:
        top.add(gdstk.Polygon(poly.points, layer=mbe_pair[0], datatype=mbe_pair[1]))
    for poly in preserved:
        top.add(poly)

    out_lib = gdstk.Library()
    for cell in assembly.library.cells:
        out_lib.add(cell)
    out_lib.add(top)
    return top, out_lib


def build_routed_assembly(
    context: AgentGroundContext,
    session: GroundMergeSession,
    result: GroundMergeResult | None,
    *,
    status: str,
    skip_reason: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    wall_time_s: float = 0.0,
) -> AgenticRoutedAssembly:
    """Assemble the output object (geometry included regardless of status)."""
    assembly = context.assembly
    mbe_pair = getattr(context, "mbe_pair", (2, 0))
    preserved = list(session.preserved)

    if result is not None and result.skip_reason is None:
        ground_body = list(result.carved_body)
        consumed = [bb for p in result.plates.all() if (bb := p.bounding_box()) is not None]
        rep = result.report
        bridges = len(result.bridges)
        connector_used = result.connector_rect is not None
        severed = len(rep.split_locations)
        mbe_area = rep.mbe_area_um2
        body_hash = rep.ground_body_hash
        pads_connected = tuple(sorted(rep.pads_connected))
        drc_violations = len(rep.violations)
    else:
        ground_body, consumed = [], []
        bridges, connector_used, severed = 0, False, 0
        mbe_area, body_hash = 0.0, "(empty)"
        pads_connected, drc_violations = (), 0

    top, out_lib = _build_top_cell(assembly, preserved, ground_body, consumed, mbe_pair)

    return AgenticRoutedAssembly(
        index=assembly.index,
        inst_name=assembly.inst_name,
        status=status,
        skip_reason=skip_reason,
        placement_shift=session.placement_shift,
        ground_body=ground_body,
        bridges_applied=bridges,
        connector_used=connector_used,
        n_severed_fragments=severed,
        mbe_area_um2=mbe_area,
        ground_body_hash=body_hash,
        pads_connected=pads_connected,
        drc_violations=drc_violations,
        tool_calls_used=session.tool_calls_used,
        llm_turns_used=session.llm_turns_used,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        wall_time_s=wall_time_s,
        top_cell=top,
        library=out_lib,
    )


def preview_agentic_svg(assembly: AgenticRoutedAssembly) -> str:
    flat = assembly.flatten()
    with tempfile.TemporaryDirectory() as tmp:
        svg_path = Path(tmp) / f"{assembly.top_cell.name}.svg"
        flat.write_svg(str(svg_path))
        return svg_path.read_text(encoding="utf-8")
