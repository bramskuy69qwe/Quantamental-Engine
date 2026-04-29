from __future__ import annotations

import asyncio
import logging
import time as _time
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

import config
from core.state import app_state, TZ_LOCAL
from core import ws_manager
from core.database import db
from core.platform_bridge import platform_bridge
from api.helpers import templates, _ctx, _get_funding_cached, _maybe_backfill_equity

log = logging.getLogger("routes.dashboard")
router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", _ctx(request))


@router.get("/fragments/dashboard", response_class=HTMLResponse)
async def frag_dashboard(request: Request):
    funding = await _get_funding_cached()
    return templates.TemplateResponse(
        request, "fragments/dashboard_body.html",
        _ctx(request,
             acc=app_state.account_state,
             pf=app_state.portfolio,
             ex=app_state.exchange_info,
             positions=app_state.positions,
             funding=funding),
    )


@router.get("/fragments/dashboard/top", response_class=HTMLResponse)
async def frag_dashboard_top(request: Request):
    return templates.TemplateResponse(
        request, "fragments/dashboard_top.html",
        _ctx(request,
             acc=app_state.account_state,
             pf=app_state.portfolio),
    )


@router.get("/fragments/dashboard/exchange_info", response_class=HTMLResponse)
async def frag_dashboard_exchange_info(request: Request):
    return templates.TemplateResponse(
        request, "fragments/dashboard_exchange_info.html",
        _ctx(request, ex=app_state.exchange_info),
    )


@router.get("/fragments/dashboard/equity_ohlc", response_class=HTMLResponse)
async def frag_dashboard_equity_ohlc(request: Request, tf: str = "1h"):
    tf_map = {"1h": 60, "4h": 240, "1d": 1440, "1w": 10080}
    tf_minutes = tf_map.get(tf, 60)
    now_ms = int(_time.time() * 1000)
    needed_start_ms = now_ms - (100 * tf_minutes * 60 * 1000)
    aid = app_state.active_account_id
    await _maybe_backfill_equity(needed_start_ms, account_id=aid)
    candles = await db.get_equity_ohlc(tf_minutes=tf_minutes, limit=100, account_id=aid)
    return templates.TemplateResponse(
        request,
        "fragments/dashboard_ohlc.html",
        _ctx(request, candles=candles, active_tf=tf),
    )


@router.get("/fragments/dashboard/journal_stats", response_class=HTMLResponse)
async def frag_dashboard_journal_stats(request: Request):
    import calendar as _cal
    now = datetime.now(TZ_LOCAL)
    _, ndays = _cal.monthrange(now.year, now.month)
    start = datetime(now.year, now.month, 1, tzinfo=TZ_LOCAL)
    end   = datetime(now.year, now.month, ndays, 23, 59, 59, tzinfo=TZ_LOCAL)
    from_ms = int(start.timestamp() * 1000)
    to_ms   = int(end.timestamp() * 1000)

    aid = app_state.active_account_id
    stats, boundaries, top_pairs = await asyncio.gather(
        db.get_journal_stats(from_ms, to_ms, account_id=aid),
        db.get_equity_period_boundaries(from_ms, to_ms, account_id=aid),
        db.get_most_traded_pairs(from_ms, to_ms, limit=3, account_id=aid),
        return_exceptions=True,
    )
    if isinstance(stats, Exception):      stats = {}
    if isinstance(boundaries, Exception): boundaries = {"initial_equity": 0.0, "final_equity": 0.0, "max_drawdown": 0.0}
    if isinstance(top_pairs, Exception):  top_pairs = []

    period_label = start.strftime("%B %Y")
    return templates.TemplateResponse(
        request,
        "fragments/dashboard_journal_stats.html",
        _ctx(request, stats=stats, boundaries=boundaries,
             top_pairs=top_pairs, period_label=period_label),
    )


@router.get("/fragments/ws_status", response_class=HTMLResponse)
async def frag_ws_status(request: Request):
    return templates.TemplateResponse(
        request, "fragments/ws_status.html",
        {"ws": app_state.ws_status, "ex": app_state.exchange_info,
         "plugin_connected": platform_bridge.is_connected},
    )


@router.get("/api/price/{ticker}")
async def api_price(ticker: str):
    ticker = ticker.upper()
    price = app_state.mark_price_cache.get(ticker, 0)
    if not price:
        ob = app_state.orderbook_cache.get(ticker, {})
        asks = ob.get("asks", [])
        bids = ob.get("bids", [])
        if asks and bids:
            price = (float(asks[0][0]) + float(bids[0][0])) / 2
        elif asks:
            price = float(asks[0][0])
        elif bids:
            price = float(bids[0][0])
    if not price:
        try:
            from core.exchange import fetch_orderbook
            ws_manager.set_calculator_symbol(ticker)
            await fetch_orderbook(ticker)
            ob = app_state.orderbook_cache.get(ticker, {})
            asks = ob.get("asks", [])
            bids = ob.get("bids", [])
            if asks and bids:
                price = (float(asks[0][0]) + float(bids[0][0])) / 2
            elif asks:
                price = float(asks[0][0])
            elif bids:
                price = float(bids[0][0])
        except Exception:
            pass
    return {"ticker": ticker, "price": price}


@router.get("/api/ready")
async def api_ready():
    return JSONResponse({"ready": not app_state.is_initializing})


@router.get("/api/state")
async def api_state():
    acc = app_state.account_state
    pf  = app_state.portfolio
    return {
        "total_equity":     acc.total_equity,
        "available_margin": acc.available_margin,
        "total_unrealized": acc.total_unrealized,
        "total_exposure":   pf.total_exposure,
        "drawdown":         pf.drawdown,
        "weekly_pnl_state": pf.weekly_pnl_state,
        "dd_state":         pf.dd_state,
        "position_count":   len(app_state.positions),
    }
