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
from api.helpers import templates, _ctx
from api.cache import _ensure_funding_rates, get_funding_lines, _maybe_backfill_equity, _inject_live_equity

log = logging.getLogger("routes.dashboard")
router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "dashboard.html", _ctx(request))


@router.get("/fragments/dashboard", response_class=HTMLResponse)
async def frag_dashboard(request: Request):
    await _ensure_funding_rates()
    acc = app_state.account_state
    pf  = app_state.portfolio
    prm = app_state.params

    # Funding lines from cached rates + live positions (refreshes every render)
    funding_lines = get_funding_lines()

    # Sector exposure lines from open positions
    sector_totals: dict = {}
    for p in app_state.positions:
        if p.sector:
            sector_totals[p.sector] = sector_totals.get(p.sector, 0.0) + abs(p.position_value_usdt)
    sector_lines = [f"{s}: ${v:,.0f}" for s, v in sorted(sector_totals.items(), key=lambda x: -x[1])]

    # Working orders + recent order history for dashboard tabs
    working_orders = platform_bridge.order_manager.open_orders
    aid = app_state.active_account_id
    try:
        recent_orders, _ = await db.query_order_history(
            account_id=aid, page=1, per_page=20,
            sort_by="updated_at_ms", sort_dir="DESC",
        )
    except Exception:
        recent_orders = []

    return templates.TemplateResponse(
        request, "fragments/dashboard_body.html",
        _ctx(request,
             exposure_pct=pf.total_exposure * 100,
             max_exposure_pct=prm["max_exposure"] * 100,
             dd_state=pf.dd_state,
             drawdown_pct=pf.drawdown * 100,
             drawdown_state=pf.dd_state,
             max_dd_pct=prm["max_dd_percent"] * 100,
             weekly_pnl_state=pf.weekly_pnl_state,
             open_positions=app_state.positions,
             max_open_positions=prm["max_position_count"],
             funding_lines=funding_lines,
             sector_lines=sector_lines,
             working_orders=working_orders,
             recent_orders=recent_orders),
    )


@router.get("/fragments/dashboard/top", response_class=HTMLResponse)
async def frag_dashboard_top(request: Request):
    acc = app_state.account_state
    pf  = app_state.portfolio
    return templates.TemplateResponse(
        request, "fragments/dashboard_top.html",
        _ctx(request,
             total_equity=acc.total_equity,
             daily_pnl=acc.daily_pnl,
             daily_pnl_pct=acc.daily_pnl_percent * 100,
             weekly_pnl=pf.total_weekly_pnl,
             weekly_pnl_pct=pf.total_weekly_pnl_percent * 100,
             available_margin=acc.available_margin,
             margin_used=acc.total_margin_used,
             unrealized_pnl=acc.total_unrealized,
             bod_equity=acc.bod_equity),
    )


@router.get("/fragments/dashboard/exchange_info", response_class=HTMLResponse)
async def frag_dashboard_exchange_info(request: Request):
    ex = app_state.exchange_info
    return templates.TemplateResponse(
        request, "fragments/dashboard_exchange_info.html",
        _ctx(request,
             exchange_name=ex.name,
             server_time=ex.server_time or "—",
             latency_str=f"{ex.latency_ms:.0f}ms" if ex.latency_ms else "—",
             maker_fee_str=f"{ex.maker_fee*100:.4f}%" if ex.maker_fee else "—",
             taker_fee_str=f"{ex.taker_fee*100:.4f}%" if ex.taker_fee else "—"),
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
    _inject_live_equity(candles)
    return templates.TemplateResponse(
        request,
        "fragments/equity_ohlc.html",
        _ctx(request, candles=candles, active_tf=tf,
             eq_id="ohlc",
             eq_title="Equity Curve (OHLC)",
             eq_subtitle="Last 100 candles \u00b7 from account snapshots",
             eq_timeframes=[("1h","1H"),("4h","4H"),("1d","1D"),("1w","1W")],
             eq_fragment_url="/fragments/dashboard/equity_ohlc",
             eq_api_url="/api/dashboard/equity_ohlc"),
    )


@router.get("/api/dashboard/equity_ohlc")
async def api_dashboard_equity_ohlc(tf: str = "1h"):
    tf_map = {"1h": 60, "4h": 240, "1d": 1440, "1w": 10080}
    tf_minutes = tf_map.get(tf, 60)
    now_ms = int(_time.time() * 1000)
    needed_start_ms = now_ms - (100 * tf_minutes * 60 * 1000)
    aid = app_state.active_account_id
    await _maybe_backfill_equity(needed_start_ms, account_id=aid)
    candles = await db.get_equity_ohlc(tf_minutes=tf_minutes, limit=100, account_id=aid)
    _inject_live_equity(candles)
    return JSONResponse({"candles": candles, "tf": tf})


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

    # Compute flat vars the template expects
    initial_eq = boundaries.get("initial_equity", 0.0)
    final_eq   = boundaries.get("final_equity", 0.0)
    monthly_pnl = final_eq - initial_eq
    monthly_pnl_pct = (monthly_pnl / initial_eq * 100) if initial_eq > 0 else 0.0

    total_trades = int(stats.get("total_trades", 0))
    win_count    = int(stats.get("winning_trades", 0))
    loss_count   = int(stats.get("losing_trades", 0))
    win_rate     = (win_count / total_trades * 100) if total_trades > 0 else 0.0
    avg_profit   = stats.get("avg_profit", 0.0)
    avg_loss     = stats.get("avg_loss", 0.0)
    avg_rr       = round(abs(avg_profit / avg_loss), 2) if avg_loss and avg_loss != 0 else 0.0

    # Build params wrapper with the key names the template expects
    prm = app_state.params
    params_view = {
        "individual_risk_per_trade": prm.get("individual_risk_per_trade", 0.01),
        "max_weekly_loss_pct":       prm.get("max_w_loss_percent", 0.05),
        "max_drawdown_pct":          prm.get("max_dd_percent", 0.10),
        "max_exposure_multiple":     prm.get("max_exposure", 3.0),
        "max_open_positions":        prm.get("max_position_count", 10),
        "max_correlated_exposure":   prm.get("max_correlated_exposure", 0.5),
    }

    return templates.TemplateResponse(
        request,
        "fragments/dashboard_journal_stats.html",
        _ctx(request,
             month_label=period_label,
             monthly_pnl=monthly_pnl,
             monthly_pnl_pct=monthly_pnl_pct,
             win_rate=win_rate,
             trade_count=total_trades,
             win_count=win_count,
             loss_count=loss_count,
             avg_rr=avg_rr,
             avg_profit=avg_profit,
             avg_loss=avg_loss,
             max_dd_month=boundaries.get("max_drawdown", 0.0) * 100,
             monthly_volume=stats.get("trading_volume", 0.0),
             broker_fee=stats.get("total_fees", 0.0),
             long_count=int(stats.get("num_longs", 0)),
             short_count=int(stats.get("num_shorts", 0)),
             top_pairs=top_pairs,
             params=params_view),
    )


@router.get("/fragments/dashboard/secondary", response_class=HTMLResponse)
async def frag_dashboard_secondary(request: Request):
    return templates.TemplateResponse(
        request, "fragments/dashboard_secondary.html",
        _ctx(request, acc=app_state.account_state),
    )


@router.get("/fragments/ws_status", response_class=HTMLResponse)
async def frag_ws_status(request: Request):
    return templates.TemplateResponse(
        request, "fragments/ws_status.html",
        {"ws": app_state.ws_status, "ex": app_state.exchange_info},
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
