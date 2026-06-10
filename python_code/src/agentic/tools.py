"""
Agentic step 5 — agent tools wrapping the shared plate-merge pipeline.

The agent does not draw wires. It influences ``ground_merge.run_ground_merge`` by
choosing an NPI shift, bridge rectangles (to fuse disjoint plates), and a
connector rectangle (to join the preserved metal). Every state-changing tool
re-runs the deterministic pipeline and reports the verifier result, so the agent
always knows where it stands and can never bypass DRC.

Tools
-----
get_state()                       -> serialized plate-merge scene
union_ground()                    -> plate union status (needs bridging?)
bridge_gap(x0,y0,x1,y1)           -> add an axis-aligned bridge rectangle
connect_preserved(x0,y0,x1,y1)    -> set the connector rectangle
carve_ground()                    -> run the merge + carve, report
check_drc()                       -> full deterministic verifier report
shift_assembly(dx,dy)             -> translate resonator + preserved metal (NPI)
"""
from __future__ import annotations

from typing import Any

import gdstk

try:
    from ..ground_merge import union_ground_body
except ImportError:
    from ground_merge import union_ground_body

from .context import AgentGroundContext
from .routing_state import GroundMergeSession
from .state_serializer import serialize_state

Point = tuple[float, float]
Bbox = tuple[tuple[float, float], tuple[float, float]]

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "get_state",
        "description": (
            "Return the full serialized plate-merge state: pads, ground plates, "
            "union status, preserved metal, release holes, cavity, your current "
            "choices, and the latest merge result."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "union_ground",
        "description": (
            "Report how many connected components the ground plates form. If 1, "
            "no bridge is needed. If >1, you must add bridge_gap rectangles to "
            "fuse them before carving."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "bridge_gap",
        "description": (
            "Add an axis-aligned MBE bridge rectangle to fuse disjoint ground "
            "plates. Give the rectangle corners (x0,y0)-(x1,y1). It must lie "
            "inside the inner cavity and have non-zero area. Re-runs the merge."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "x0": {"type": "number"},
                "y0": {"type": "number"},
                "x1": {"type": "number"},
                "y1": {"type": "number"},
            },
            "required": ["x0", "y0", "x1", "y1"],
        },
    },
    {
        "name": "connect_preserved",
        "description": (
            "Set a connector rectangle (x0,y0)-(x1,y1) that joins the preserved "
            "metal to the ground body. Only needed when the preserved metal does "
            "NOT already overlap the body. Must overlap both. Re-runs the merge."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "x0": {"type": "number"},
                "y0": {"type": "number"},
                "x1": {"type": "number"},
                "y1": {"type": "number"},
            },
            "required": ["x0", "y0", "x1", "y1"],
        },
    },
    {
        "name": "carve_ground",
        "description": (
            "Run the full merge with your current choices: union plates, apply "
            "bridges/connector, then carve the DRC keepouts. Reports the carved "
            "result and any violations or severed fragments."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "check_drc",
        "description": (
            "Run the deterministic verifier on the current merge: connectivity "
            "(one body touching both ground pads AND preserved metal) plus "
            "net-aware DRC. Returns the full report. Stop once it reports PASS."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "shift_assembly",
        "description": (
            "Translate the resonator + preserved metal by (dx, dy) ABSOLUTE from "
            "nominal (not cumulative), limited to +/-20um per axis. Pads, filler, "
            "and frame never move. Re-runs the merge."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"dx": {"type": "number"}, "dy": {"type": "number"}},
            "required": ["dx", "dy"],
        },
    },
]


def _rect(args: dict[str, Any]) -> Bbox:
    x0, y0, x1, y1 = (
        float(args["x0"]),
        float(args["y0"]),
        float(args["x1"]),
        float(args["y1"]),
    )
    return ((min(x0, x1), min(y0, y1)), (max(x0, x1), max(y0, y1)))


def _inside_cavity(context: AgentGroundContext, rect: Bbox) -> str | None:
    (ix0, iy0), (ix1, iy1) = context.cavity_bbox
    (rx0, ry0), (rx1, ry1) = rect
    if not (ix0 - 1e-6 <= rx0 and rx1 <= ix1 + 1e-6 and iy0 - 1e-6 <= ry0 and ry1 <= iy1 + 1e-6):
        return (
            f"rectangle [({rx0:.1f}, {ry0:.1f}) .. ({rx1:.1f}, {ry1:.1f})] is not "
            f"inside the cavity [({ix0:.1f}, {iy0:.1f}) .. ({ix1:.1f}, {iy1:.1f})]"
        )
    return None


def _merge_feedback(session: GroundMergeSession) -> str:
    result = session.last_result
    if result is None:
        return "no merge run yet"
    if result.skip_reason is not None:
        return f"merge skipped: {result.skip_reason}"
    rep = result.report
    if rep.is_success:
        return "verifier: PASS — one clean connected ground body"
    bits = [f"{len(rep.violations)} violation(s)"]
    missing = [p for p in ("top_ground", "bottom_ground") if p not in rep.pads_connected]
    if missing:
        bits.append(f"unconnected: {', '.join(missing)}")
    if not rep.preserved_connected:
        bits.append("preserved not connected")
    head = rep.violations[0] if rep.violations else ""
    return "verifier: " + "; ".join(bits) + (f" | first: {head}" if head else "")


def _overlaps(rect: Bbox, polys, precision: float) -> bool:
    (x0, y0), (x1, y1) = rect
    r = gdstk.rectangle((x0, y0), (x1, y1))
    return any(gdstk.boolean(r, p, "and", precision=precision) for p in polys)


def dispatch_tool(
    name: str,
    args: dict[str, Any],
    context: AgentGroundContext,
    session: GroundMergeSession,
) -> dict[str, Any]:
    """Execute one tool call; always returns a JSON-serializable dict with ok."""
    try:
        return _dispatch(name, args, context, session)
    except (ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "error": str(exc)}


def _dispatch(
    name: str,
    args: dict[str, Any],
    context: AgentGroundContext,
    session: GroundMergeSession,
) -> dict[str, Any]:
    cfg = context.config

    if name == "get_state":
        return {"ok": True, "state": serialize_state(context, session)}

    if name == "union_ground":
        union = union_ground_body(context.plates.all(), context.gcfg)
        return {
            "ok": True,
            "n_components": union.n_components,
            "bridging_needed": union.n_components > 1,
            "component_bboxes": [
                [round(b[0][0], 1), round(b[0][1], 1), round(b[1][0], 1), round(b[1][1], 1)]
                for b in union.component_bboxes
            ],
        }

    if name == "bridge_gap":
        rect = _rect(args)
        if (err := _inside_cavity(context, rect)) is not None:
            return {"ok": False, "error": err}
        if (rect[1][0] - rect[0][0]) < 1e-6 or (rect[1][1] - rect[0][1]) < 1e-6:
            return {"ok": False, "error": "bridge rectangle has zero area"}
        session.add_bridge(rect)
        context.run_merge(session)
        return {"ok": True, "bridges": len(session.bridges), "feedback": _merge_feedback(session)}

    if name == "connect_preserved":
        rect = _rect(args)
        if (err := _inside_cavity(context, rect)) is not None:
            return {"ok": False, "error": err}
        prec = context.gcfg.boolean_precision
        preserved = session.preserved or context.preserved_at(*session.placement_shift)
        if not _overlaps(rect, preserved, prec):
            return {"ok": False, "error": "connector rectangle does not overlap the preserved metal"}
        if not _overlaps(rect, context.plates.all(), prec):
            return {"ok": False, "error": "connector rectangle does not overlap any ground plate"}
        session.connector_rect = rect
        context.run_merge(session)
        return {"ok": True, "feedback": _merge_feedback(session)}

    if name == "carve_ground":
        context.run_merge(session)
        result = session.last_result
        return {
            "ok": True,
            "carved_components": len(result.carved_body) if result else 0,
            "feedback": _merge_feedback(session),
        }

    if name == "check_drc":
        result = context.run_merge(session)
        return {
            "ok": True,
            "is_success": result.is_success,
            "report": result.report.to_text(),
        }

    if name == "shift_assembly":
        dx, dy = args.get("dx"), args.get("dy")
        if not isinstance(dx, (int, float)) or not isinstance(dy, (int, float)):
            return {"ok": False, "error": "dx and dy must be numbers"}
        dx, dy = float(dx), float(dy)
        if abs(dx) > cfg.max_shift_um or abs(dy) > cfg.max_shift_um:
            return {
                "ok": False,
                "error": f"shift ({dx:.1f}, {dy:.1f}) exceeds the +/-{cfg.max_shift_um:.0f}um NPI limit",
            }
        session.placement_shift = (dx, dy)
        context.run_merge(session)
        return {
            "ok": True,
            "placement_shift": [dx, dy],
            "feedback": _merge_feedback(session),
        }

    return {"ok": False, "error": f"unknown tool {name!r}"}
