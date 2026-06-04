"""Audit export endpoints (Phase 7.4, spec §10.6 / §11.2).

``POST /export/closed_position/{id}`` → a signed JSON audit bundle (the full
causal graph for the closed position + a signed-timestamp envelope). Thin
wrapper over :func:`core.audit_export.build_closed_position_export`. PDF +
batch export are Phase 7.5/7.6.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse, Response

from core.database import db
from core.audit_export import build_closed_position_export, render_export_pdf

log = logging.getLogger("routes.export")
router = APIRouter()


@router.post("/export/closed_position/{closed_position_id}")
async def export_closed_position(
    closed_position_id: int,
    fmt: str = Query("json", alias="format"),
):
    """Generate the signed audit bundle for one closed_positions row (by integer
    PK). ``?format=json`` (default) → the signed JSON envelope; ``?format=pdf``
    → a paginated PDF carrying the SAME signature in a footer (P7.T5). 404 if
    the row does not exist."""
    envelope = await build_closed_position_export(db, closed_position_id)
    if envelope is None:
        return JSONResponse(
            {"error": f"closed_position {closed_position_id} not found"}, status_code=404,
        )
    if fmt == "pdf":
        pdf = render_export_pdf(envelope)
        return Response(
            content=pdf, media_type="application/pdf",
            headers={"Content-Disposition":
                     f'attachment; filename="audit_closed_position_{closed_position_id}.pdf"'},
        )
    return JSONResponse(envelope)
