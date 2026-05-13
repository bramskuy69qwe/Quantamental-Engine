"""
Order Center API — HTMX fragment endpoints for order / fill / closed-position history.

All 4 endpoints follow the same pattern as routes_history.py:
paginated, sortable, searchable, date-filterable.  They read from the
3 new v2.2.2 tables via DatabaseManager (OrdersMixin).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
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
    page: int = 1, per_page: int = 25,
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
    page: int = 1, per_page: int = 25,
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
