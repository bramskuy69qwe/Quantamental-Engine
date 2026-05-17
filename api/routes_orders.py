"""
Order Center API — HTMX fragment endpoints for order / fill / closed-position history.

All 4 endpoints follow the same pattern as routes_history.py:
paginated, sortable, searchable, date-filterable.  They read from the
3 new v2.2.2 tables via DatabaseManager (OrdersMixin).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

from fastapi.responses import JSONResponse

from core.state import app_state
from core.database import db
from api.helpers import templates, _table_ctx

log = logging.getLogger("routes.orders")
router = APIRouter()


def _iso_to_ms(iso: str) -> int | None:
    """Convert ISO-8601 datetime string to epoch milliseconds, or None."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return None


# ── Open Orders ──────────────────────────────────────────────────────────────

@router.get("/fragments/history/open_orders", response_class=HTMLResponse)
async def frag_open_orders(
    request: Request,
    page: int = 1, per_page: int = 20,
    sort_by: str = "created_at_ms", sort_dir: str = "DESC",
    search: str = "",
):
    rows, total = await db.query_open_orders(
        account_id=app_state.active_account_id,
        page=page, per_page=per_page,
        sort_by=sort_by, sort_dir=sort_dir, search=search,
    )
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(
        request, "fragments/history/open_orders_table.html",
        _table_ctx(request, rows=rows, total=total, page=page,
                   per_page=per_page, total_pages=total_pages,
                   sort_by=sort_by, sort_dir=sort_dir, search=search),
    )


# ── Order History ────────────────────────────────────────────────────────────

@router.get("/fragments/history/order_history", response_class=HTMLResponse)
async def frag_order_history(
    request: Request,
    page: int = 1, per_page: int = 20,
    sort_by: str = "updated_at_ms", sort_dir: str = "DESC",
    search: str = "",
    date_from: str = "", date_to: str = "",
):
    rows, total = await db.query_order_history(
        account_id=app_state.active_account_id,
        page=page, per_page=per_page,
        sort_by=sort_by, sort_dir=sort_dir, search=search,
        date_from_ms=_iso_to_ms(date_from), date_to_ms=_iso_to_ms(date_to),
    )
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(
        request, "fragments/history/order_history_table.html",
        _table_ctx(request, rows=rows, total=total, page=page,
                   per_page=per_page, total_pages=total_pages,
                   sort_by=sort_by, sort_dir=sort_dir, search=search,
                   date_from=date_from, date_to=date_to),
    )


# ── Trade History (fills) ────────────────────────────────────────────────────

@router.get("/fragments/history/fills", response_class=HTMLResponse)
async def frag_fills(
    request: Request,
    page: int = 1, per_page: int = 20,
    sort_by: str = "timestamp_ms", sort_dir: str = "DESC",
    search: str = "",
    date_from: str = "", date_to: str = "",
):
    rows, total = await db.query_fills(
        account_id=app_state.active_account_id,
        page=page, per_page=per_page,
        sort_by=sort_by, sort_dir=sort_dir, search=search,
        date_from_ms=_iso_to_ms(date_from), date_to_ms=_iso_to_ms(date_to),
    )
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(
        request, "fragments/history/fills_table.html",
        _table_ctx(request, rows=rows, total=total, page=page,
                   per_page=per_page, total_pages=total_pages,
                   sort_by=sort_by, sort_dir=sort_dir, search=search,
                   date_from=date_from, date_to=date_to),
    )


# ── Position History (closed positions) ──────────────────────────────────────

@router.get("/fragments/history/closed_positions", response_class=HTMLResponse)
async def frag_closed_positions(
    request: Request,
    page: int = 1, per_page: int = 20,
    sort_by: str = "exit_time_ms", sort_dir: str = "DESC",
    search: str = "",
    date_from: str = "", date_to: str = "",
):
    rows, total = await db.query_closed_positions(
        account_id=app_state.active_account_id,
        page=page, per_page=per_page,
        sort_by=sort_by, sort_dir=sort_dir, search=search,
        date_from_ms=_iso_to_ms(date_from), date_to_ms=_iso_to_ms(date_to),
    )
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(
        request, "fragments/history/closed_positions_table.html",
        _table_ctx(request, rows=rows, total=total, page=page,
                   per_page=per_page, total_pages=total_pages,
                   sort_by=sort_by, sort_dir=sort_dir, search=search,
                   date_from=date_from, date_to=date_to),
    )


# ── Fill Drawer (Position History row expand) ────────────────────────────────

@router.get("/fragments/history/position_fills", response_class=HTMLResponse)
async def frag_position_fills(request: Request, position_id: int = 0):
    """Return fills for a single closed position (lazy-loaded drawer)."""
    from api.helpers import _ctx
    from core.exec_link import get_exec_link_status

    fills = []
    if position_id:
        aid = app_state.active_account_id
        async with db._conn.execute(
            "SELECT terminal_position_id, symbol, direction FROM closed_positions WHERE id=?",
            (position_id,),
        ) as cur:
            pos = await cur.fetchone()
        if pos:
            fills = await db.get_position_fills(
                aid, pos["terminal_position_id"], pos["symbol"], pos["direction"],
            )
            # CRIT-001 fix: batch-fetch pre_trade_log and order_types instead of
            # per-fill queries. Previously: 2 queries per entry fill (~100 for
            # 50 fills). Now: 1 batched pre_trade_log + 1 batched orders, then
            # in-memory lookup during enrichment.
            entry_fills = [
                f for f in fills
                if not f.get("is_close") and f.get("calc_id")
            ]
            calc_ids = [f["calc_id"] for f in entry_fills]
            ex_order_ids = [
                f["exchange_order_id"] for f in entry_fills
                if f.get("exchange_order_id")
            ]
            ptl_by_id = await db.get_pretrade_logs_by_calc_ids(calc_ids)
            order_types = await db.get_order_types_by_ids(aid, ex_order_ids)

            for f in fills:
                if f.get("is_close") or not f.get("calc_id"):
                    f["exec_link_status"] = ""
                    f["exec_match_count"] = 0
                    continue
                ptl = ptl_by_id.get(f["calc_id"])
                order_type = order_types.get(f.get("exchange_order_id", ""), "")
                status, count = get_exec_link_status(f, ptl, order_type)
                f["exec_link_status"] = status
                f["exec_match_count"] = count

    return templates.TemplateResponse(
        request, "fragments/history/position_fills.html",
        _ctx(request, fills=fills),
    )


@router.get("/fragments/history/exec_link", response_class=HTMLResponse)
async def frag_exec_link(request: Request, fill_id: int = 0):
    """Exec link comparison panel for a single fill."""
    from api.helpers import _ctx
    from core.exec_link import compute_exec_match

    fill = ptl = match = None
    order_type = ""
    has_modifications = False

    if fill_id:
        aid = app_state.active_account_id
        async with db._conn.execute(
            "SELECT * FROM fills WHERE id=? AND account_id=?", (fill_id, aid),
        ) as cur:
            row = await cur.fetchone()
            if row:
                fill = dict(row)

        if fill and fill.get("calc_id"):
            async with db._conn.execute(
                "SELECT * FROM pre_trade_log WHERE calc_id=? LIMIT 1",
                (fill["calc_id"],),
            ) as cur:
                row = await cur.fetchone()
                if row:
                    ptl = dict(row)

            if fill.get("exchange_order_id"):
                async with db._conn.execute(
                    "SELECT order_type FROM orders WHERE exchange_order_id=? AND account_id=? LIMIT 1",
                    (fill["exchange_order_id"], aid),
                ) as cur:
                    orow = await cur.fetchone()
                    if orow:
                        order_type = orow["order_type"] or ""

            # Check for TP/SL modifications on this calc_id
            try:
                from core.trade_event_log import query_trade_events
                import asyncio
                evts, _ = await asyncio.to_thread(
                    query_trade_events,
                    account_id=aid,
                    calc_id=fill["calc_id"],
                    event_type=None,
                    limit=100,
                )
                has_modifications = any(
                    e["event_type"] in ("tp_modified", "sl_modified") for e in evts
                )
            except Exception:
                pass

            if ptl:
                match = compute_exec_match(fill, ptl, order_type)

    return templates.TemplateResponse(
        request, "fragments/history/exec_link_panel.html",
        _ctx(request, fill=fill, ptl=ptl, match=match,
             has_modifications=has_modifications),
    )


@router.post("/history/exec_link/confirm", response_class=HTMLResponse)
async def confirm_exec_link(request: Request, fill_id: int = Form(0)):
    """Persist user-confirmed exec link on a fill."""
    if fill_id:
        await db._conn.execute(
            "UPDATE fills SET exec_link_confirmed=1, "
            "exec_link_confirmed_at=datetime('now'), exec_link_confirmed_by='user' "
            "WHERE id=?",
            (fill_id,),
        )
        await db._conn.commit()
    return await frag_exec_link(request, fill_id=fill_id)


# ── Backfill + consistency ───────────────────────────────────────────────────

@router.post("/api/orders/backfill")
async def backfill_from_exchange_history(days: int = 30):
    """One-time migration: populate fills + closed_positions from exchange_history."""
    result = await db.backfill_fills_from_exchange_history(
        account_id=app_state.active_account_id, days=days,
    )
    return JSONResponse(result)


@router.get("/api/orders/consistency")
async def check_data_consistency():
    """Run data consistency checks on order-domain tables."""
    result = await db.validate_order_data_consistency(
        account_id=app_state.active_account_id,
    )
    return JSONResponse(result)
