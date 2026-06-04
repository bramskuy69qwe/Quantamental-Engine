"""Reverse-query context endpoints (Phase 7, spec §11.1).

Read-only JSON endpoints that return the full causal graph for one calc, one
trade lifecycle, or one position, for downstream model feedback + the audit UI.
Thin wrappers over ``core.context_query`` (which holds the cross-DB assembly).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from core.database import db
from core.context_query import (
    assemble_calc_context,
    assemble_lifecycle_context,
    assemble_position_context,
    json_safe,
)

log = logging.getLogger("routes.context")
router = APIRouter()


@router.get("/context/calc/{calc_id}")
async def context_calc(calc_id: str):
    """Full causal graph for one calc (spec §11.1): calc + orders + fills +
    amendments + junction + position + funding + deviations + events."""
    graph = await assemble_calc_context(db, calc_id)
    if graph is None:
        return JSONResponse({"error": f"calc {calc_id!r} not found"}, status_code=404)
    return JSONResponse(json_safe(graph))


@router.get("/context/lifecycle/{lifecycle_id}")
async def context_lifecycle(lifecycle_id: str):
    """Full causal graph for one trade lifecycle (spec §3.5 single-key audit):
    all contributing calcs + orders + fills + amendments + junction + position
    + closed rows + funding + deviations + events."""
    graph = await assemble_lifecycle_context(db, lifecycle_id)
    if graph is None:
        return JSONResponse(
            {"error": f"lifecycle {lifecycle_id!r} not found"}, status_code=404,
        )
    return JSONResponse(json_safe(graph))


@router.get("/context/position/{position_id}")
async def context_position(position_id: str):
    """Full causal graph for one position (spec §11.1, keyed on
    ``terminal_position_id``): all contributing calcs + orders + fills +
    amendments + junction + position + closed rows + funding + deviations +
    events. Works for junction-less / UNPLANNED positions too."""
    graph = await assemble_position_context(db, position_id)
    if graph is None:
        return JSONResponse(
            {"error": f"position {position_id!r} not found"}, status_code=404,
        )
    return JSONResponse(json_safe(graph))
