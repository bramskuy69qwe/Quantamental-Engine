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
from core.state import app_state
from core.audit_export import (
    build_closed_position_export,
    render_export_pdf,
    build_batch_export,
    render_batch_zip,
)

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
    if fmt.lower() == "pdf":          # case-insensitive: ?format=PDF works too
        pdf = render_export_pdf(envelope)
        return Response(
            content=pdf, media_type="application/pdf",
            headers={"Content-Disposition":
                     f'attachment; filename="audit_closed_position_{closed_position_id}.pdf"'},
        )
    # Attachment disposition so the native-form download button (Phase-8 #2,
    # position_events.html) downloads the bundle instead of navigating the SPA
    # to a raw JSON page — matches the PDF branch. The header is advisory and
    # does not affect programmatic ``json.loads(resp.body)`` consumers.
    return JSONResponse(
        envelope,
        headers={"Content-Disposition":
                 f'attachment; filename="audit_closed_position_{closed_position_id}.json"'},
    )


@router.post("/export/closed_positions")
async def export_closed_positions_batch(
    account_id: int = Query(None),
    from_ms: int = Query(0),
    to_ms: int = Query((1 << 63) - 1),
    fmt: str = Query("json", alias="format"),
):
    """Per-account compliance batch export (P7.T6, spec §7.7): a ZIP of one
    signed bundle per closed position whose ``exit_time_ms`` is in
    ``[from_ms, to_ms]`` (epoch ms; omitted → all), plus a signed
    ``manifest.json``. ``?format=json`` (default) packs the signed envelopes;
    ``?format=pdf`` packs the rendered PDFs. Defaults to the active account."""
    aid = account_id if account_id is not None else app_state.active_account_id
    batch = await build_batch_export(db, aid, from_ms, to_ms)
    blob = render_batch_zip(batch, fmt.lower())
    fname = f"audit_batch_account{aid}_{from_ms}_{to_ms}.zip"
    return Response(
        content=blob, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )
