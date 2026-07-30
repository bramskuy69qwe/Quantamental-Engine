from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from markupsafe import escape

import config
from core.state import app_state
from core.tz import get_account_tz, now_in_account_tz
from core.database import db
from core.data_logger import log_execution, log_trade_close
from core.sql_safety import validate_sort_params
from api.helpers import templates, _ctx, _table_ctx

log = logging.getLogger("routes.history")
router = APIRouter()


# (Jinja retirement 2026-07-30: GET /history + history.html retired — the
# React History page is the twin. The /fragments/history/* doors + the
# notes/close_reason writers below SURVIVE.)


@router.post("/history/log_execution", response_class=HTMLResponse)
async def post_execution(
    request:            Request,
    ticker:             str   = Form(...),
    side:               str   = Form(...),
    entry_price_actual: float = Form(...),
    size_filled:        float = Form(...),
    slippage:           float = Form(0.0),
    order_type:         str   = Form("limit"),
    latency_snapshot:   float = Form(0.0),
):
    row = {
        "account_id": app_state.active_account_id,
        "ticker": ticker.upper(), "side": side,
        "entry_price_actual": entry_price_actual, "size_filled": size_filled,
        "slippage": slippage, "order_type": order_type,
        "maker_fee": app_state.exchange_info.maker_fee,
        "taker_fee": app_state.exchange_info.taker_fee,
        "latency_snapshot": latency_snapshot, "orderbook_depth_snapshot": "",
        "source_terminal": "manual",
    }
    try:
        await db.insert_execution_log(row)
    except Exception as exc:
        log.error("insert_execution_log failed: %r", exc)
        return HTMLResponse('<div class="alert alert-error">Failed to log execution — database error.</div>')
    log_execution(row)
    return HTMLResponse('<div class="alert alert-success">Execution logged.</div>')


@router.post("/history/log_close", response_class=HTMLResponse)
async def post_trade_close(
    request:               Request,
    ticker:                str   = Form(...),
    direction:             str   = Form(...),
    entry_price:           float = Form(...),
    exit_price:            float = Form(...),
    individual_realized:   float = Form(0.0),
    individual_realized_r: float = Form(0.0),
    total_funding_fees:    float = Form(0.0),
    total_fees:            float = Form(0.0),
    slippage_exit:         float = Form(0.0),
    holding_time:          str   = Form(""),
    notes:                 str   = Form(""),
):
    row = {
        "account_id": app_state.active_account_id,
        "ticker": ticker.upper(), "direction": direction,
        "entry_price": entry_price, "exit_price": exit_price,
        "individual_realized": individual_realized,
        "individual_realized_r": individual_realized_r,
        "total_funding_fees": total_funding_fees, "total_fees": total_fees,
        "slippage_exit": slippage_exit, "holding_time": holding_time, "notes": notes,
    }
    try:
        await db.insert_trade_history(row)
    except Exception as exc:
        log.error("insert_trade_history failed: %r", exc)
        return HTMLResponse('<div class="alert alert-error">Failed to log trade close — database error.</div>')
    log_trade_close(row)
    return HTMLResponse('<div class="alert alert-success">Trade close logged.</div>')


@router.get("/fragments/history/exchange", response_class=HTMLResponse)
async def frag_history_exchange(
    request: Request,
    page: int = 1, per_page: int = 20,
    sort_by: str = "time", sort_dir: str = "DESC",
    search: str = "", date_from: str = "", date_to: str = "",
):
    # MED-003 (Task 101): route-level defense-in-depth for sort_by/sort_dir.
    sort_by, sort_dir = validate_sort_params(sort_by, sort_dir, db._EXCHANGE_HISTORY_SORT_COLS)
    rows, total = await db.query_exchange_history(
        page=page, per_page=per_page,
        sort_by=sort_by, sort_dir=sort_dir,
        search=search, date_from=date_from, date_to=date_to,
        tz_local=get_account_tz(app_state.active_account_id),
        account_id=app_state.active_account_id,
    )
    total_pages = max(1, (total + per_page - 1) // per_page)
    notes_map = await db.get_position_notes([r["trade_key"] for r in rows])
    return templates.TemplateResponse(
        request, "fragments/history/exchange_table.html",
        _table_ctx(request, rows=rows, total=total, page=page,
                   per_page=per_page, total_pages=total_pages,
                   sort_by=sort_by, sort_dir=sort_dir, search=search,
                   date_from=date_from, date_to=date_to, notes_map=notes_map),
    )


@router.get("/fragments/history/open_positions", response_class=HTMLResponse)
async def frag_history_open_positions(request: Request, format: str = ""):
    from core.order_manager_singleton import order_manager
    prm = app_state.params
    if format == "json":
        # v3.0 P4 JSON door: live positions (the shared serializer incl. the
        # G-O7 fields) + working orders + the header cap.
        from api.routes_calculator import _json_safe
        from api.routes_cockpit import _position_row
        return JSONResponse(_json_safe({
            "positions":      [_position_row(p) for p in app_state.positions],
            "working_orders": list(order_manager.open_orders or []),
            "max_positions":  prm["max_position_count"],
        }))
    return templates.TemplateResponse(
        request, "fragments/history/open_positions.html",
        _ctx(request,
             positions=app_state.positions,
             max_positions=prm["max_position_count"],
             working_orders=order_manager.open_orders),
    )


@router.get("/fragments/history/pre_trade", response_class=HTMLResponse)
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
    if format == "json":
        # v3.0 P4 JSON door — rows carry the resolved model_display (F11
        # precedence) so the React column needs no re-resolution.
        from api.routes_orders import _rows_json
        return _rows_json(rows, total, page, per_page)
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(
        request, "fragments/history/pre_trade_table.html",
        _table_ctx(request, rows=rows, total=total, page=page,
                   per_page=per_page, total_pages=total_pages,
                   sort_by=sort_by, sort_dir=sort_dir, search=search,
                   ticker=ticker, side=side,
                   date_from=date_from, date_to=date_to),
    )


@router.get("/fragments/history/trade_history", response_class=HTMLResponse)
async def frag_history_trade_history(
    request: Request,
    page: int = 1, per_page: int = 20,
    sort_by: str = "exit_timestamp", sort_dir: str = "DESC",
    search: str = "", ticker: str = "", direction: str = "",
    date_from: str = "", date_to: str = "",
):
    # MED-003 (Task 101): route-level defense-in-depth for sort_by/sort_dir.
    sort_by, sort_dir = validate_sort_params(sort_by, sort_dir, db._TRADE_HISTORY_SORT_COLS)
    rows, total = await db.query_trade_history(
        date_from=date_from or None, date_to=date_to or None,
        search=search or None, ticker=ticker or None, direction=direction or None,
        sort_by=sort_by, sort_dir=sort_dir, page=page, per_page=per_page,
        account_id=app_state.active_account_id,
    )
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(
        request, "fragments/history/trade_history_table.html",
        _table_ctx(request, rows=rows, total=total, page=page,
                   per_page=per_page, total_pages=total_pages,
                   sort_by=sort_by, sort_dir=sort_dir, search=search,
                   ticker=ticker, direction=direction,
                   date_from=date_from, date_to=date_to),
    )


@router.get("/fragments/history/trade_events", response_class=HTMLResponse)
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

    if format == "json":
        # v3.0 P4 JSON door — rows carry the parsed _payload + _symbol the
        # route already extracted (same post-filter set the fragment renders).
        from api.routes_orders import _rows_json
        return _rows_json(rows, total, page, per_page)
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(
        request, "fragments/history/trade_events_table.html",
        _ctx(request, rows=rows, total=total, page=page,
             per_page=per_page, total_pages=total_pages,
             event_type=event_type, search=search,
             date_from=date_from, date_to=date_to),
    )


@router.put("/history/notes/pre_trade/{row_id}", response_class=HTMLResponse)
async def update_pre_trade_note(row_id: int, notes: str = Form("")):
    await db.update_pre_trade_notes(row_id, notes)
    safe = escape(notes)
    return HTMLResponse(
        f'<span class="text-sub cursor-pointer" '
        f'onclick="editNote(this,{row_id},\'pre_trade\')" '
        f'title="Click to edit">{safe or "+ Add note"}</span>'
    )


@router.put("/history/notes/trade_history/{row_id}", response_class=HTMLResponse)
async def update_trade_history_note(row_id: int, notes: str = Form("")):
    await db.update_trade_history_notes(row_id, notes)
    safe = escape(notes)
    return HTMLResponse(
        f'<span class="text-sub cursor-pointer" '
        f'onclick="editNote(this,{row_id},\'trade_history\')" '
        f'title="Click to edit">{safe or "+ Add note"}</span>'
    )


@router.put("/history/notes/position", response_class=HTMLResponse)
async def update_position_note(trade_key: str = Form(""), notes: str = Form("")):
    await db.upsert_position_note(trade_key, notes)
    safe_notes = escape(notes)
    safe_key   = escape(trade_key)
    return HTMLResponse(
        f'<span class="text-sub cursor-pointer" '
        f'onclick="editNote(this,\'{safe_key}\',\'position\')" '
        f'title="Click to edit">{safe_notes or "+ Add note"}</span>'
    )


# P8.T6 (spec §10.5): manual-close reason. The pre-submission modal is
# impossible (observe-only), but a manual close IS detectable post-WS — the
# engine classifies it MANUAL_OTHER (order_manager._determine_exit_reason).
# This lets the operator refine the reason (MANUAL_* subtype) + add a note on
# a closed position. Returns the re-rendered badge cell for the table swap.
_MANUAL_EXIT_REASONS = frozenset({
    "MANUAL_INTERVENTION", "MANUAL_DISCIPLINE_BREAK",
    "MANUAL_NEW_OPPORTUNITY", "MANUAL_OTHER",
})


@router.put("/history/close_reason/{closed_pos_id}", response_class=HTMLResponse)
async def update_close_reason(
    closed_pos_id: int, exit_reason: str = Form(...), close_note: str = Form(""),
):
    if exit_reason not in _MANUAL_EXIT_REASONS:
        return HTMLResponse(
            '<span class="text-red">invalid reason</span>', status_code=400,
        )
    ok = await db.update_close_reason(
        app_state.active_account_id, closed_pos_id, exit_reason, close_note,
    )
    if not ok:
        return HTMLResponse(
            '<span class="text-red">close not found</span>', status_code=404,
        )
    html = templates.env.get_template(
        "fragments/history/close_reason_cell.html"
    ).render(exit_reason=exit_reason, close_note=close_note, row_id=closed_pos_id)
    return HTMLResponse(html)
