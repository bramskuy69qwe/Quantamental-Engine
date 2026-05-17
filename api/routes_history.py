from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from markupsafe import escape

import config
from core.state import app_state
from core.tz import get_account_tz, now_in_account_tz
from core.database import db
from core.data_logger import log_execution, log_trade_close
from api.helpers import templates, _ctx, _table_ctx

log = logging.getLogger("routes.history")
router = APIRouter()


@router.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    """Render the history page shell — all table data loads via HTMX."""
    return templates.TemplateResponse(
        request, "history.html", _ctx(request),
    )


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
async def frag_history_open_positions(request: Request):
    from core.platform_bridge import platform_bridge
    prm = app_state.params
    return templates.TemplateResponse(
        request, "fragments/history/open_positions.html",
        _ctx(request,
             positions=app_state.positions,
             max_positions=prm["max_position_count"],
             working_orders=platform_bridge.order_manager.open_orders),
    )


@router.get("/fragments/history/pre_trade", response_class=HTMLResponse)
async def frag_history_pre_trade(
    request: Request,
    page: int = 1, per_page: int = 20,
    sort_by: str = "timestamp", sort_dir: str = "DESC",
    search: str = "", ticker: str = "", side: str = "",
    date_from: str = "", date_to: str = "",
):
    rows, total = await db.query_pre_trade_log(
        date_from=date_from or None, date_to=date_to or None,
        search=search or None, ticker=ticker or None, side=side or None,
        sort_by=sort_by, sort_dir=sort_dir, page=page, per_page=per_page,
        account_id=app_state.active_account_id,
    )
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
