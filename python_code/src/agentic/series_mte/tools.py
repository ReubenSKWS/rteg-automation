"""Agent-callable tools for series and shunt MTE geometry."""
from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from agentic.series_mte.context import SeriesMteContext
from agentic.series_mte.verifier import check_drc, check_invariants, check_shunt_drc
from rteg_series_mte import (
    SeriesStripBuildResult,
    build_series_strip,
    resonator_mbe_body,
    _hole_anchors,
    _perimeter_edges,
    _perimeter_length,
)
from rteg_signal import (
    SignalNetResult,
    build_shunt_signal_net_from_plate,
    enumerate_shunt_routes,
)


class MteToolSession:
    """Mutable session holding last build for one resonator (series or shunt)."""

    def __init__(self, ctx: SeriesMteContext) -> None:
        self.ctx = ctx
        self.last_result: SeriesStripBuildResult | None = None
        self.last_shunt_signal: SignalNetResult | None = None
        self._shunt_plates: list = []

    @property
    def is_series(self) -> bool:
        return self.ctx.res.res_type == "series"

    def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        handlers = {
            "get_resonator_body": self.get_resonator_body,
            "get_release_holes": self.get_release_holes,
            "get_ground_plates": self.get_ground_plates,
            "get_preserved_mte": self.get_preserved_mte,
            "build_offset_ring_strip": self.build_offset_ring_strip,
            "list_shunt_routes": self.list_shunt_routes,
            "build_shunt_route": self.build_shunt_route,
            "check_drc": self.check_drc_tool,
            "check_invariants": self.check_invariants_tool,
        }
        if name not in handlers:
            return {"error": f"unknown tool {name!r}"}
        return handlers[name](args)

    def get_resonator_body(self, _args: dict[str, Any]) -> dict[str, Any]:
        body = resonator_mbe_body(
            self.ctx.res, self.ctx.assembly, self.ctx.config.boolean_precision
        )
        bb = body.bounding_box()
        edges = _perimeter_edges(body)
        return {
            "bbox": bb,
            "perimeter_um": round(_perimeter_length(edges), 1),
            "vertices": len(body.points),
        }

    def get_release_holes(self, _args: dict[str, Any]) -> dict[str, Any]:
        if not self.is_series:
            return {"note": "shunt resonators use pad routing, not release-hole arc"}
        body = resonator_mbe_body(
            self.ctx.res, self.ctx.assembly, self.ctx.config.boolean_precision
        )
        anchors = _hole_anchors(
            body, self.ctx.roles.release_holes, self.ctx.config.boolean_precision
        )
        return {
            "total": len(self.ctx.roles.release_holes.all_items()),
            "touching": [
                {
                    "label": a.hole.label,
                    "area_um2": round(a.area_um2, 1),
                    "contact": (round(a.contact[0], 1), round(a.contact[1], 1)),
                }
                for a in anchors
            ],
        }

    def get_ground_plates(self, _args: dict[str, Any]) -> dict[str, Any]:
        filler = self.ctx.roles.ground_plates.filler
        return {
            "top": len(self.ctx.roles.ground_plates.top),
            "center": len(self.ctx.roles.ground_plates.center),
            "bottom": len(self.ctx.roles.ground_plates.bottom),
            "filler_bbox": filler[0].bbox if filler else None,
        }

    def get_preserved_mte(self, _args: dict[str, Any]) -> dict[str, Any]:
        return {
            "note": "hint only — filter connect MTE may not align with rotated instance",
            "items": [
                {"label": t.label, "bbox": t.bbox, "area_um2": round(t.area_um2, 1)}
                for t in self.ctx.roles.preserved.mte
            ],
        }

    def build_offset_ring_strip(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self.is_series:
            return {"error": "build_offset_ring_strip is for series resonators only"}
        margin = float(args["margin_um"])
        band = float(args["band_thickness_um"])
        apply_finalize = bool(args.get("apply_drc_finalize", False))
        try:
            result = build_series_strip(
                self.ctx.res,
                self.ctx.assembly,
                self.ctx.roles.release_holes,
                self.ctx.layermap,
                self.ctx.config,
                margin_um=margin,
                band_thickness_um=band,
                build_mode="offset_ring",
                apply_drc_finalize=apply_finalize,
                ground_obstacles=self.ctx.ground_obstacles,
                verify=True,
            )
        except ValueError as exc:
            return {"error": str(exc)}
        self.last_result = result
        return result.summary()

    def list_shunt_routes(self, _args: dict[str, Any]) -> dict[str, Any]:
        if self.is_series:
            return {"error": "list_shunt_routes is for shunt resonators only"}
        _, options, plates = enumerate_shunt_routes(
            self.ctx.roles.preserved,
            self.ctx.classification,
            self.ctx.roles.ground_plates,
            self.ctx.layermap,
            self.ctx.config,
        )
        self._shunt_plates = plates
        return {
            "count": len(options),
            "candidates": [asdict(o) for o in options[:20]],
            "note": "candidate_id indexes into ranked list (DRC-clean + shortest first)",
        }

    def build_shunt_route(self, args: dict[str, Any]) -> dict[str, Any]:
        if self.is_series:
            return {"error": "build_shunt_route is for shunt resonators only"}
        if not self._shunt_plates:
            self.list_shunt_routes({})
        candidate_id = int(args["candidate_id"])
        if candidate_id < 0 or candidate_id >= len(self._shunt_plates):
            return {
                "error": f"candidate_id {candidate_id} out of range (0..{len(self._shunt_plates) - 1})"
            }
        plate = self._shunt_plates[candidate_id]
        signal = build_shunt_signal_net_from_plate(
            self.ctx.roles.preserved,
            self.ctx.classification,
            self.ctx.roles.ground_plates,
            self.ctx.layermap,
            plate,
            self.ctx.config,
        )
        self.last_shunt_signal = signal
        return {
            "candidate_id": candidate_id,
            "shape_name": plate.shape_name,
            **signal.summary(),
            "drc_violations": signal.drc_violations,
        }

    def check_drc_tool(self, _args: dict[str, Any]) -> dict[str, Any]:
        if self.is_series:
            if self.last_result is None:
                return {"error": "no strip built yet — call build_offset_ring_strip first"}
            return check_drc(self.ctx, self.last_result)
        if self.last_shunt_signal is None:
            return {"error": "no route built yet — call build_shunt_route first"}
        return check_shunt_drc(self.ctx, self.last_shunt_signal)

    def check_invariants_tool(self, _args: dict[str, Any]) -> dict[str, Any]:
        if not self.is_series:
            return {
                "ok": self.last_shunt_signal is not None
                and self.last_shunt_signal.reaches_pad,
                "errors": []
                if self.last_shunt_signal and self.last_shunt_signal.reaches_pad
                else ["shunt route must reach signal pad"],
            }
        if self.last_result is None:
            return {"error": "no strip built yet — call build_offset_ring_strip first"}
        errors = check_invariants(self.ctx, self.last_result)
        return {"errors": errors, "ok": not errors}


SeriesMteToolSession = MteToolSession


SERIES_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_resonator_body",
        "description": "Resonator MBE body bbox and perimeter length in RTEG space.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_release_holes",
        "description": "Release holes touching the resonator body perimeter.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_ground_plates",
        "description": "GSG ground pad counts and MBE filler bbox.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_preserved_mte",
        "description": "Preserved filter MTE hint (may not align with instance).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "build_offset_ring_strip",
        "description": (
            "Build filled MTE ring offset outward from resonator body on release-hole arc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "margin_um": {
                    "type": "number",
                    "description": "Gap between body edge and inner MTE edge (1-5 um)",
                },
                "band_thickness_um": {
                    "type": "number",
                    "description": "Filled ring thickness outward from margin (1-4 um)",
                },
                "apply_drc_finalize": {
                    "type": "boolean",
                    "description": "Run margin increase + ground trim if DRC fails",
                },
            },
            "required": ["margin_um", "band_thickness_um"],
        },
    },
    {
        "name": "check_drc",
        "description": "Check MTE vs ground MBE spacing (14 um rule).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "check_invariants",
        "description": "Verify endpoints at holes, no hole overlap, ring outside body.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]

SHUNT_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_ground_plates",
        "description": "GSG ground pad counts and MBE filler bbox.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_preserved_mte",
        "description": "Preserved filter MTE polygons near the resonator.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_shunt_routes",
        "description": (
            "List ranked pad-route candidates (straight/L/45/Z) with DRC metadata."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "build_shunt_route",
        "description": "Build MTE connector plate for a candidate_id from list_shunt_routes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidate_id": {
                    "type": "integer",
                    "description": "Ranked route index from list_shunt_routes",
                },
            },
            "required": ["candidate_id"],
        },
    },
    {
        "name": "check_drc",
        "description": "Check connector vs ground MBE spacing (14 um rule).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "check_invariants",
        "description": "Verify connector reaches the center signal pad.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]

TOOL_DEFINITIONS = SERIES_TOOL_DEFINITIONS


def tool_definitions_for(ctx: SeriesMteContext) -> list[dict[str, Any]]:
    if ctx.res.res_type == "series":
        return SERIES_TOOL_DEFINITIONS
    return SHUNT_TOOL_DEFINITIONS


def tool_result_json(data: dict[str, Any]) -> str:
    return json.dumps(data, default=str)
