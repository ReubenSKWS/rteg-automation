"""
Agentic step 5 — render the plate-merge state as text the LLM can reason about.

The agent never sees raw GDS. It sees a compact textual scene: the labelled
ground plates (GSG arms + filler), the preserved connector, the union/component
status, the carve obstacles, the clearance rules, and the latest merge result.

## Assumptions
- Coordinates are RTEG world micrometres rounded to 0.1 um.
- Polygons are summarized as bbox + a small vertex subsample, never raw dumps;
  the verifier (not the agent) owns exact geometry.
- The GSG ground arms are wide MBE plates that legitimately span the frame wall
  — they are NOT constrained to the inner cavity; only new bridge / connector
  rectangles are.
"""
from __future__ import annotations

import gdstk

try:
    from ..ground_merge import union_ground_body
except ImportError:
    from ground_merge import union_ground_body

from .context import AgentGroundContext
from .routing_state import GroundMergeSession

Point = tuple[float, float]
_MAX_POLY_POINTS = 6


def _r(value: float) -> float:
    return round(float(value), 1)


def _fmt_pt(pt: Point) -> str:
    return f"({_r(pt[0])}, {_r(pt[1])})"


def _fmt_bbox(bb: tuple[Point, Point] | None) -> str:
    if bb is None:
        return "(empty)"
    return f"[{_fmt_pt(bb[0])} .. {_fmt_pt(bb[1])}]"


def _group_bbox(polys: list[gdstk.Polygon]) -> tuple[Point, Point] | None:
    boxes = [bb for p in polys if (bb := p.bounding_box()) is not None]
    if not boxes:
        return None
    return (
        (min(b[0][0] for b in boxes), min(b[0][1] for b in boxes)),
        (max(b[1][0] for b in boxes), max(b[1][1] for b in boxes)),
    )


def _poly_summary(poly: gdstk.Polygon) -> str:
    bb = poly.bounding_box()
    pts = list(poly.points)
    if len(pts) > _MAX_POLY_POINTS:
        step = len(pts) / _MAX_POLY_POINTS
        pts = [pts[int(i * step)] for i in range(_MAX_POLY_POINTS)]
    pts_s = ", ".join(_fmt_pt((p[0], p[1])) for p in pts)
    return f"bbox {_fmt_bbox(bb)}, boundary sample: {pts_s}"


def serialize_state(
    context: AgentGroundContext,
    session: GroundMergeSession,
) -> str:
    """Full textual scene for the agent (also returned by the get_state tool)."""
    cfg = context.config
    lines: list[str] = []

    lines.append("=== GROUND PLATE-MERGE STATE (um, RTEG world space) ===")

    # Rules
    lines.append("")
    lines.append("RULES:")
    lines.append(
        "- The ground side is ONE fused MBE body, not a wire: outer GSG ground "
        "arms + filler plate + preserved connector."
    )
    lines.append(
        f"- Carve keepouts: center signal + MTE at {cfg.mbe_mte_spacing_um:.0f}um, "
        f"resonator MBE at {cfg.mbe_mte_spacing_um:.0f}um, release holes at "
        f"{cfg.release_hole_clearance_um:.0f}um."
    )
    lines.append(
        "- New bridge / connector rectangles must be axis-aligned (45/90 edges) "
        "and lie inside the inner cavity. The existing arms/filler may sit "
        "outside it — that is expected."
    )
    lines.append(
        f"- shift_assembly is NPI-bounded to +/-{cfg.max_shift_um:.0f}um per axis "
        "and moves ONLY the resonator + preserved metal."
    )
    lines.append(
        "- GOAL: one connected carved ground body touching BOTH ground pads AND "
        "the preserved metal, with zero DRC violations (check with check_drc)."
    )

    # Pads
    lines.append("")
    lines.append("PADS (fixed, never move):")
    lines.append(
        f"- top_ground (GROUND, MBE): {_fmt_bbox(_group_bbox(context.pads.top_ground))}"
    )
    lines.append(
        f"- center_signal (SIGNAL — carve obstacle, never fused): "
        f"{_fmt_bbox(_group_bbox(context.pads.center_signal))}"
    )
    lines.append(
        f"- bottom_ground (GROUND, MBE): {_fmt_bbox(_group_bbox(context.pads.bottom_ground))}"
    )

    # Plates
    lines.append("")
    lines.append("GROUND PLATES (sources fused into the body):")
    lines.append(
        f"- top_ground_arm: {_fmt_bbox(_group_bbox(context.plates.top_ground))}"
    )
    lines.append(
        f"- bottom_ground_arm: {_fmt_bbox(_group_bbox(context.plates.bottom_ground))}"
    )
    lines.append(
        f"- filler_plate: {_fmt_bbox(context.filler_bbox)} "
        f"(plate width ~{context.plate_width_um:.0f}um)"
    )

    # Union status (plates only, before preserved / carve)
    union = union_ground_body(context.plates.all(), context.gcfg)
    if union.n_components <= 1:
        lines.append(
            f"- union status: {union.n_components} component — plates already "
            "fused, no bridge needed."
        )
    else:
        lines.append(
            f"- union status: {union.n_components} components — a bridge_gap "
            "rectangle is needed to fuse them. Component bboxes:"
        )
        for bb in union.component_bboxes:
            lines.append(f"    {_fmt_bbox(bb)}")

    # Preserved metal
    lines.append("")
    dx, dy = session.placement_shift
    lines.append(
        f"PRESERVED METAL (ground net, MBE — moves with shift; current shift "
        f"({_r(dx)}, {_r(dy)})):"
    )
    preserved = session.preserved or context.preserved_at(dx, dy)
    for i, poly in enumerate(preserved):
        lines.append(f"- preserved[{i}]: {_poly_summary(poly)}")
    pres_bb = _group_bbox(list(preserved))
    filler_bb = context.filler_bbox
    if pres_bb is not None and filler_bb is not None and _overlap(pres_bb, filler_bb):
        lines.append(
            "- preserved already overlaps the filler plate — connect_preserved "
            "may not be needed."
        )

    # Release holes
    lines.append("")
    if context.release_holes:
        lines.append(f"RELEASE HOLES near resonator ({len(context.release_holes)} fixed):")
        for poly in context.release_holes[:12]:
            lines.append(f"- {_fmt_bbox(poly.bounding_box())}")
        if len(context.release_holes) > 12:
            lines.append(f"- ... {len(context.release_holes) - 12} more")
    else:
        lines.append("RELEASE HOLES near resonator: none")

    # Cavity
    lines.append("")
    lines.append(f"INNER FRAME CAVITY: {_fmt_bbox(context.cavity_bbox)}")

    # Agent choices so far
    lines.append("")
    lines.append("YOUR CHOICES:")
    lines.append(f"- placement_shift: ({_r(dx)}, {_r(dy)})")
    if session.bridges:
        lines.append(f"- bridges ({len(session.bridges)}):")
        for b in session.bridges:
            lines.append(f"    {_fmt_bbox(b)}")
    else:
        lines.append("- bridges: none")
    lines.append(
        f"- connector_rect: {_fmt_bbox(session.connector_rect) if session.connector_rect else 'none'}"
    )

    # Latest merge result
    lines.append("")
    if session.last_result is not None:
        lines.append("LATEST MERGE RESULT:")
        lines.append("  " + session.last_result.report.to_text().replace("\n", "\n  "))
    else:
        lines.append("LATEST MERGE RESULT: none yet — call carve_ground or check_drc.")

    return "\n".join(lines)


def _overlap(a: tuple[Point, Point], b: tuple[Point, Point]) -> bool:
    (ax0, ay0), (ax1, ay1) = a
    (bx0, by0), (bx1, by1) = b
    return ax0 <= bx1 and bx0 <= ax1 and ay0 <= by1 and by0 <= ay1
