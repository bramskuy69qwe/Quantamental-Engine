from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Form
from fastapi.responses import JSONResponse

from core.state import app_state
from core.database import db
from core.sql_safety import validate_sort_params

log = logging.getLogger("routes.history")
router = APIRouter()


# (Jinja retirement 2026-07-30: GET /history + history.html retired — the
# React History page is the twin. The /fragments/history/* doors + the
# notes/close_reason writers below SURVIVE.)
#
# Retired 2026-07-30 (operator call): `POST /history/log_execution` and
# `POST /history/log_close`, the two manual-entry form writers. Both had been
# UI-orphaned since the retirement deleted their forms, and the tables they
# wrote (`execution_log`, `trade_history`) have no reader left either —
# `db.query_execution_log` and `db.query_trade_history` are caller-less, so the
# rows could be created but never displayed. `docs/archive/v2.4.md` had kept
# them "for off-engine manual logging"; that decision is superseded here.
# Their CSV side-loggers (`core.data_logger.log_execution` /
# `log_trade_close`) went with them. The INSERT helpers and both TABLES are
# KEPT — retiring an API is not a data migration.


@router.get("/fragments/history/pre_trade", response_class=JSONResponse)
async def frag_history_pre_trade(
    request: Request,
    page: int = 1, per_page: int = 20,
    sort_by: str = "timestamp", sort_dir: str = "DESC",
    search: str = "", ticker: str = "", side: str = "",
    date_from: str = "", date_to: str = "",
    format: str = "",
):
    # MED-003 (Task 101): route-level defense-in-depth for sort_by/sort_dir.
    sort_by, sort_dir = validate_sort_params(sort_by, sort_dir, db._PRE_TRADE_SORT_COLS)
    rows, total = await db.query_pre_trade_log(
        date_from=date_from or None, date_to=date_to or None,
        search=search or None, ticker=ticker or None, side=side or None,
        sort_by=sort_by, sort_dir=sort_dir, page=page, per_page=per_page,
        account_id=app_state.active_account_id,
    )
    # v2.7 Task D (holistic-audit F11): the Model column read free text
    # only, so picker-tagged calcs (model_id FK set, free text empty)
    # rendered "—" — plan-time surface disagreed with the close-time
    # stamp. Resolve display names with the SAME precedence as the
    # close-row stamp (get_model_stamp_for_calc): row free text wins →
    # FK-join library name → "(deleted model)" for dangling ids (FK
    # policy: ids dangle by design after a model delete).
    fk_ids = {
        r["model_id"] for r in rows
        if r.get("model_id") is not None
        and not (r.get("model_name") or "").strip()
    }
    fk_names = await db.get_model_names_by_ids(fk_ids) if fk_ids else {}
    for r in rows:
        free_text = (r.get("model_name") or "").strip()
        if free_text:
            r["model_display"] = free_text
        elif r.get("model_id") is not None:
            r["model_display"] = fk_names.get(r["model_id"], "(deleted model)")
        else:
            r["model_display"] = ""
    # Fragments slim-down (2026-07-30): JSON-only — the HTML twin
    # (pre_trade_table.html) is retired; `format` stays accepted-and-inert.
    # Rows carry the resolved model_display (F11 precedence) so the React
    # column needs no re-resolution.
    from api.routes_orders import _rows_json
    return _rows_json(rows, total, page, per_page)


@router.get("/fragments/history/trade_events", response_class=JSONResponse)
async def frag_history_trade_events(
    request: Request,
    page: int = 1, per_page: int = 20,
    event_type: str = "", search: str = "",
    date_from: str = "", date_to: str = "",
    format: str = "",
):
    """Trade Events Log tab — reads from trade_events table (sync query)."""
    import asyncio
    import json as _json
    from core.trade_event_log import query_trade_events

    aid = app_state.active_account_id
    offset = (max(page, 1) - 1) * per_page
    rows, total = await asyncio.to_thread(
        query_trade_events,
        account_id=aid,
        event_type=event_type or None,
        since=date_from or None,
        until=date_to or None,
        limit=per_page,
        offset=offset,
    )

    # Parse payload_json and extract symbol for display + filtering
    for r in rows:
        try:
            r["_payload"] = _json.loads(r.get("payload_json") or "{}")
        except (ValueError, TypeError):
            r["_payload"] = {}
        r["_symbol"] = r["_payload"].get("symbol") or r["_payload"].get("ticker") or ""

    if search:
        _s = search.upper()
        rows = [r for r in rows if _s in r["_symbol"].upper()]
        total = len(rows)  # approximate after client-side filter

    # Fragments slim-down (2026-07-30): JSON-only — the HTML twin
    # (trade_events_table.html) is retired; `format` stays accepted-and-inert.
    # Rows carry the parsed _payload + _symbol the route already extracted.
    from api.routes_orders import _rows_json
    return _rows_json(rows, total, page, per_page)


# ── Row notes (JSON; ported to React 2026-07-30) ─────────────────────────────
# All three used to answer with an HTML `<span onclick="editNote(...)">` cell
# for the Jinja tables' inline editor. That editor (base.html `editNote`) was
# deleted in the fragments slim-down, so the markup referenced a function that
# no longer exists. The one that survives now answers JSON; the caller
# re-renders from its own rows.
#
# SURFACE STATUS — `pre_trade` is the ONLY row-note surface. The sibling
# `trade_history` and `position` note writers were RETIRED 2026-07-30 (operator
# call): the tables they annotated lost their last reader in the fragments
# slim-down, so the notes could be written but never displayed anywhere. Their
# DB helpers went with them (`update_trade_history_notes`, `upsert_position_note`
# and the already-caller-less `get_position_notes`).
#
# DATA IS PRESERVED, deliberately: the `position_history_notes` table and
# `trade_history.notes` column stay in the schema (and in the split migration),
# so any note the operator wrote survives. Re-exposing them is a matter of
# adding a reader, not recovering data.

@router.put("/history/notes/pre_trade/{row_id}", response_class=JSONResponse)
async def update_pre_trade_note(row_id: int, notes: str = Form("")):
    ok = await db.update_pre_trade_notes(
        row_id, notes, account_id=app_state.active_account_id,
    )
    if not ok:
        # A stale row id (the operator's page is older than the data) must not
        # report success — the cell would close on a write that never landed.
        return JSONResponse({"error": "pre-trade row not found"}, status_code=404)
    return JSONResponse({"status": "ok", "row_id": row_id, "notes": notes})


# P8.T6 (spec §10.5): manual-close reason. The pre-submission modal is
# impossible (observe-only), but a manual close IS detectable post-WS — the
# engine classifies it MANUAL_OTHER (order_manager._determine_exit_reason).
# This lets the operator refine the reason (MANUAL_* subtype) + add a note on
# a closed position. Returns a JSON ok (fragments slim-down 2026-07-30 — the
# React modal checks response.ok and re-fetches the table).
_MANUAL_EXIT_REASONS = frozenset({
    "MANUAL_INTERVENTION", "MANUAL_DISCIPLINE_BREAK",
    "MANUAL_NEW_OPPORTUNITY", "MANUAL_OTHER",
})


@router.put("/history/close_reason/{closed_pos_id}", response_class=JSONResponse)
async def update_close_reason(
    closed_pos_id: int, exit_reason: str = Form(...), close_note: str = Form(""),
):
    # JSON on every lane (2026-07-30): these two were the last HTML spans behind
    # a `response_class=JSONResponse` decorator, so the React caller's `jsonOk`
    # mode fell back to HTML-stripping to recover the message — it worked, but
    # only by accident.
    if exit_reason not in _MANUAL_EXIT_REASONS:
        return JSONResponse({"error": "invalid reason"}, status_code=400)
    ok = await db.update_close_reason(
        app_state.active_account_id, closed_pos_id, exit_reason, close_note,
    )
    if not ok:
        return JSONResponse({"error": "close not found"}, status_code=404)
    # Fragments slim-down (2026-07-30): the htmx cell re-render
    # (close_reason_cell.html) is retired with the Jinja History page; the
    # React modal only checks response.ok and re-fetches the table JSON.
    return JSONResponse({"status": "ok", "exit_reason": exit_reason,
                         "close_note": close_note, "row_id": closed_pos_id})
