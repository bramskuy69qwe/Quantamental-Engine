from __future__ import annotations

import asyncio
import logging
import time as _time
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

import config
from core.state import app_state
from core.tz import get_account_tz, now_in_account_tz
from core import ws_manager
from core.database import db
from core import order_manager_singleton
from api.helpers import templates, _ctx
from api.cache import _ensure_funding_rates, get_funding_lines, _maybe_backfill_equity, _inject_live_equity

log = logging.getLogger("routes.dashboard")
router = APIRouter()

# v3.0 P2 (G-O8): process start for /api/system uptime (captured at import).
_PROCESS_START_MONO = _time.monotonic()
_PROCESS_START_WALL = _time.time()

# ── Cached recent orders (avoid DB query every 1s dashboard poll) ─────────
_recent_orders_cache: list = []
_recent_orders_ts: float = 0.0
_RECENT_ORDERS_TTL = 5.0  # seconds


async def _get_cached_recent_orders(aid: int) -> list:
    global _recent_orders_cache, _recent_orders_ts
    now = _time.monotonic()
    if now - _recent_orders_ts >= _RECENT_ORDERS_TTL:
        try:
            _recent_orders_cache, _ = await db.query_order_history(
                account_id=aid, page=1, per_page=20,
                sort_by="updated_at_ms", sort_dir="DESC",
            )
        except Exception:
            pass
        _recent_orders_ts = now
    return _recent_orders_cache


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

    # Working orders (in-memory cache) + recent order history (5s TTL cache)
    working_orders = order_manager_singleton.order_manager.open_orders
    aid = app_state.active_account_id
    recent_orders = await _get_cached_recent_orders(aid)

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


@router.get("/fragments/dashboard/risk", response_class=HTMLResponse)
async def frag_dashboard_risk(request: Request):
    """Risk panel fragment (DD gauge, exposure, weekly PnL, funding, sectors)."""
    await _ensure_funding_rates()
    pf  = app_state.portfolio
    prm = app_state.params

    funding_lines = get_funding_lines()
    sector_totals: dict = {}
    for p in app_state.positions:
        if p.sector:
            sector_totals[p.sector] = sector_totals.get(p.sector, 0.0) + abs(p.position_value_usdt)
    sector_lines = [f"{s}: ${v:,.0f}" for s, v in sorted(sector_totals.items(), key=lambda x: -x[1])]

    return templates.TemplateResponse(
        request, "fragments/dashboard_risk.html",
        _ctx(request,
             exposure_pct=pf.total_exposure * 100,
             max_exposure_pct=prm["max_exposure"] * 100,
             dd_state=pf.dd_state,
             drawdown_pct=pf.drawdown * 100,
             drawdown_state=pf.dd_state,
             max_dd_pct=prm["max_dd_percent"] * 100,
             weekly_pnl_state=pf.weekly_pnl_state,
             funding_lines=funding_lines,
             sector_lines=sector_lines),
    )


@router.get("/fragments/dashboard/positions", response_class=HTMLResponse)
async def frag_dashboard_positions(request: Request):
    """Positions + orders tabbed panel fragment."""
    prm = app_state.params
    working_orders = order_manager_singleton.order_manager.open_orders
    aid = app_state.active_account_id
    recent_orders = await _get_cached_recent_orders(aid)

    return templates.TemplateResponse(
        request, "fragments/dashboard_positions.html",
        _ctx(request,
             open_positions=app_state.positions,
             max_open_positions=prm["max_position_count"],
             working_orders=working_orders,
             recent_orders=recent_orders),
    )


@router.get("/fragments/dashboard/positions/rows", response_class=HTMLResponse)
async def frag_dashboard_positions_rows(request: Request, tab: str = "positions"):
    """Row-only fragment for positions/orders/history tbodies (SSE-driven)."""
    if tab == "orders":
        working_orders = order_manager_singleton.order_manager.open_orders
        return templates.TemplateResponse(
            request, "fragments/dashboard_orders_rows.html",
            _ctx(request, working_orders=working_orders),
        )
    if tab == "history":
        aid = app_state.active_account_id
        recent_orders = await _get_cached_recent_orders(aid)
        return templates.TemplateResponse(
            request, "fragments/dashboard_history_rows.html",
            _ctx(request, recent_orders=recent_orders),
        )
    # Default: positions
    prm = app_state.params
    return templates.TemplateResponse(
        request, "fragments/dashboard_positions_rows.html",
        _ctx(request,
             open_positions=app_state.positions,
             max_open_positions=prm["max_position_count"]),
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
    ws = app_state.ws_status
    # Prefer WS latency (updates at sub-second rate) over REST ping (10s)
    live_ms = ws.latency_ms if ws.connected else ex.latency_ms
    return templates.TemplateResponse(
        request, "fragments/dashboard_exchange_info.html",
        _ctx(request,
             exchange_name=ex.name,
             server_time=ex.server_time or "—",
             latency_str=f"{live_ms:.0f}ms" if live_ms else "—",
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


async def _journal_stats_context(aid: int, tz) -> dict:
    """Shared builder for the monthly / QTD / YTD journal stats + the params
    view (v3.0 P1). Consumed by BOTH the HTML fragment and
    /api/dashboard/snapshot so the Jinja and React dashboards stay at parity.
    Returns a JSON-serializable context dict (the exact keys the template reads)."""
    import calendar as _cal
    from core.period_resolver import resolve_period
    now = datetime.now(tz)
    _, ndays = _cal.monthrange(now.year, now.month)
    start = datetime(now.year, now.month, 1, tzinfo=tz)
    end   = datetime(now.year, now.month, ndays, 23, 59, 59, tzinfo=tz)
    from_ms = int(start.timestamp() * 1000)
    to_ms   = int(end.timestamp() * 1000)

    # Quarter + year boundaries for QTD / YTD
    q_start, q_end = resolve_period("quarterly", tz, now=now)
    y_start, y_end = resolve_period("yearly", tz, now=now)
    q_from_ms = int(q_start.timestamp() * 1000)
    q_to_ms   = int(q_end.timestamp() * 1000)
    y_from_ms = int(y_start.timestamp() * 1000)
    y_to_ms   = int(y_end.timestamp() * 1000)

    stats, boundaries, top_pairs, q_boundaries, y_boundaries, daily_series = await asyncio.gather(
        db.get_journal_stats(from_ms, to_ms, account_id=aid),
        db.get_equity_period_boundaries(from_ms, to_ms, account_id=aid),
        db.get_most_traded_pairs(from_ms, to_ms, limit=3, account_id=aid),
        db.get_equity_period_boundaries(q_from_ms, q_to_ms, account_id=aid),
        db.get_equity_period_boundaries(y_from_ms, y_to_ms, account_id=aid),
        # v3.0 P8 wave 2 (audit L1-F1): the month's per-day PnL for the
        # Monthly tile's daily bar chart — same source the Analytics
        # calendar reads (last snapshot per LOCAL day).
        db.get_daily_equity_series(from_ms, to_ms, account_id=aid),
        return_exceptions=True,
    )
    if isinstance(stats, Exception):        stats = {}
    if isinstance(boundaries, Exception):   boundaries = {"initial_equity": 0.0, "final_equity": 0.0, "max_drawdown": 0.0}
    if isinstance(top_pairs, Exception):    top_pairs = []
    if isinstance(q_boundaries, Exception): q_boundaries = {"initial_equity": 0.0, "final_equity": 0.0}
    if isinstance(y_boundaries, Exception): y_boundaries = {"initial_equity": 0.0, "final_equity": 0.0}
    if isinstance(daily_series, Exception): daily_series = []

    period_label = start.strftime("%B %Y")

    # Compute flat vars the template expects
    initial_eq = boundaries.get("initial_equity", 0.0)
    final_eq   = boundaries.get("final_equity", 0.0)
    monthly_pnl = final_eq - initial_eq
    monthly_pnl_pct = (monthly_pnl / initial_eq * 100) if initial_eq > 0 else 0.0

    # Quarter-to-date
    q_init = q_boundaries.get("initial_equity", 0.0)
    q_fin  = q_boundaries.get("final_equity", 0.0)
    quarterly_pnl = q_fin - q_init
    quarterly_pnl_pct = (quarterly_pnl / q_init * 100) if q_init > 0 else 0.0
    q_num = (q_start.month - 1) // 3 + 1
    quarter_label = f"Q{q_num} {q_start.year}"

    # Year-to-date
    y_init = y_boundaries.get("initial_equity", 0.0)
    y_fin  = y_boundaries.get("final_equity", 0.0)
    yearly_pnl = y_fin - y_init
    yearly_pnl_pct = (yearly_pnl / y_init * 100) if y_init > 0 else 0.0
    year_label = f"{y_start.year} YTD"

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

    return {
        "month_label":       period_label,
        "monthly_pnl":       monthly_pnl,
        "monthly_pnl_pct":   monthly_pnl_pct,
        "win_rate":          win_rate,
        "trade_count":       total_trades,
        "win_count":         win_count,
        "loss_count":        loss_count,
        "avg_rr":            avg_rr,
        "avg_profit":        avg_profit,
        "avg_loss":          avg_loss,
        "max_dd_month":      boundaries.get("max_drawdown", 0.0) * 100,
        "monthly_volume":    stats.get("trading_volume", 0.0),
        "broker_fee":        stats.get("total_fees", 0.0),
        "long_count":        int(stats.get("num_longs", 0)),
        "short_count":       int(stats.get("num_shorts", 0)),
        "top_pairs":         top_pairs,
        "params":            params_view,
        "quarterly_pnl":     quarterly_pnl,
        "quarterly_pnl_pct": quarterly_pnl_pct,
        "quarter_label":     quarter_label,
        "yearly_pnl":        yearly_pnl,
        "yearly_pnl_pct":    yearly_pnl_pct,
        "year_label":        year_label,
        # v3.0 P8 wave 2 (L1-F1): day-bucketed PnL for the month (bar chart).
        "daily_pnl": [
            {"d": r.get("day"), "pnl": r.get("daily_pnl")}
            for r in daily_series if r.get("daily_pnl") is not None
        ],
    }


@router.get("/fragments/dashboard/journal_stats", response_class=HTMLResponse)
async def frag_dashboard_journal_stats(request: Request):
    aid = app_state.active_account_id
    tz = get_account_tz(aid)
    ctx = await _journal_stats_context(aid, tz)
    return templates.TemplateResponse(
        request, "fragments/dashboard_journal_stats.html", _ctx(request, **ctx),
    )


@router.get("/fragments/dashboard/secondary", response_class=HTMLResponse)
async def frag_dashboard_secondary(request: Request):
    return templates.TemplateResponse(
        request, "fragments/dashboard_secondary.html",
        _ctx(request, acc=app_state.account_state),
    )


# ── Consolidated JSON snapshot for the v3.0 React Dashboard (v3.0 P1) ─────
def _serialize_positions(positions) -> list:
    """Serialize live positions → JSON rows for the Open-Positions tile. Field
    names match the SSE position_update payload + the Jinja rows; `pct` is uPnL
    over notional."""
    out = []
    for p in positions:
        notional = getattr(p, "position_value_usdt", 0.0) or 0.0
        upnl = getattr(p, "individual_unrealized", 0.0) or 0.0
        pct = (upnl / abs(notional) * 100) if notional else 0.0
        out.append({
            "sym":             getattr(p, "ticker", ""),
            "side":            getattr(p, "direction", ""),
            "size":            getattr(p, "contract_amount", 0.0) or 0.0,
            "entry":           getattr(p, "average", 0.0) or 0.0,
            "mark":            getattr(p, "fair_price", 0.0) or 0.0,
            "notional":        notional,
            "upnl":            upnl,
            "pct":             round(pct, 2),
            # 0.0 means "unset" for a price field (a price can't be 0) → null it
            # so the React tile renders a dash, matching Jinja. [P1 audit LOW-2]
            "tp":              (getattr(p, "individual_tp_price", None) or None),
            "sl":              (getattr(p, "individual_sl_price", None) or None),
            "mfe":             getattr(p, "session_mfe", None),
            "mae":             getattr(p, "session_mae", None),
            "fees":            getattr(p, "individual_fees", 0.0),
            "funding":         getattr(p, "individual_funding_fees", 0.0),
            "entry_ms":        getattr(p, "entry_timestamp", None),
            "deviation_badge": getattr(p, "deviation_badge", None),
            "size_delta_pct":  getattr(p, "size_delta_pct", None),
            "amendment_count": getattr(p, "amendment_count", 0),
            "tpsl_amended":    getattr(p, "tpsl_amended", 0),
        })
    return out


@router.get("/api/dashboard/snapshot")
async def api_dashboard_snapshot():
    """Consolidated JSON snapshot for the v3.0 React Dashboard's initial render.
    Aggregates the same per-tile data the Jinja fragments compute (journal via
    the shared _journal_stats_context builder); SSE (/stream/account/{id}) drives
    live updates on top. Equity curve stays on /api/dashboard/equity_ohlc; macro
    on /api/regime/signals/latest; engine log on /api/engine/log; halt state on
    /api/state."""
    acc = app_state.account_state
    pf  = app_state.portfolio
    prm = app_state.params
    aid = app_state.active_account_id
    tz  = get_account_tz(aid)

    await _ensure_funding_rates()
    funding_lines = get_funding_lines()
    sector_totals: dict = {}
    for p in app_state.positions:
        if getattr(p, "sector", None):
            sector_totals[p.sector] = sector_totals.get(p.sector, 0.0) + abs(p.position_value_usdt)
    sector_lines = [f"{s}: ${v:,.0f}" for s, v in sorted(sector_totals.items(), key=lambda x: -x[1])]

    journal = await _journal_stats_context(aid, tz)

    regime = app_state.current_regime
    regime_out = None
    if regime:
        regime_out = {
            "label":          regime.label,
            "multiplier":     regime.multiplier,
            "confidence":     regime.confidence,
            "stability_bars": regime.stability_bars,
            "mode":           regime.mode,
        }

    return JSONResponse({
        "equity": {
            "total_equity":     acc.total_equity,
            "daily_pnl":        acc.daily_pnl,
            "daily_pnl_pct":    acc.daily_pnl_percent * 100,
            "weekly_pnl":       pf.total_weekly_pnl,
            "weekly_pnl_pct":   pf.total_weekly_pnl_percent * 100,
            "available_margin": acc.available_margin,
            "margin_used":      acc.total_margin_used,
            "unrealized_pnl":   acc.total_unrealized,
            "bod_equity":       acc.bod_equity,
            "sow_equity":       getattr(acc, "sow_equity", 0.0),
            "max_equity":       getattr(acc, "max_total_equity", 0.0),
            "min_equity":       getattr(acc, "min_total_equity", 0.0),
        },
        "risk": {
            "exposure_pct":     pf.total_exposure * 100,
            "max_exposure_pct": prm["max_exposure"] * 100,
            "drawdown_pct":     pf.drawdown * 100,
            "max_dd_pct":       prm["max_dd_percent"] * 100,
            "dd_state":         pf.dd_state,
            "weekly_pnl_state": pf.weekly_pnl_state,
            "positions_open":   len(app_state.positions),
            "positions_max":    prm["max_position_count"],
            "funding_lines":    funding_lines,
            "sector_lines":     sector_lines,
        },
        "positions": _serialize_positions(app_state.positions),
        "journal":   journal,
        "regime":    regime_out,
    })


@router.get("/fragments/ws_status", response_class=HTMLResponse)
async def frag_ws_status(request: Request):
    from core import time_sync
    return templates.TemplateResponse(
        request, "fragments/ws_status.html",
        {"ws": app_state.ws_status, "ex": app_state.exchange_info,
         "clock_severity": time_sync.worst_severity(),
         "clock_offset_ms": next(
             (s.offset_ms for s in time_sync.get_all().values()), 0.0,
         )},
    )


@router.get("/api/price/{ticker}")
async def api_price(ticker: str):
    ticker = ticker.upper()
    # #2 (debug 2026-06-08): the calculator polls this every 1s for the DISPLAYED
    # ticker, so set_calculator_symbol must run on EVERY poll — not just the
    # cache-miss fallback below. Otherwise, once the orderbook cache is warm (a
    # liquid symbol like BTCUSDT, populated within ~2s by the separate
    # /calculator/refresh poll), the price is served from cache, the fallback
    # never runs, set_calculator_symbol is skipped, and the market WS is never
    # rebuilt — so the OLD symbol's @depth20 keeps streaming ("still subscribing
    # to <old>"). A thinner symbol (slower/empty orderbook fetch) hit the
    # fallback and worked, which is why the leak looked symbol-specific. The call
    # is gated internally on an ACTUAL symbol change, so the 1 Hz same-symbol
    # poll does not thrash the WS.
    ws_manager.set_calculator_symbol(ticker)
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
    from core.monitoring import ReadyStateEvaluator
    ready, reason = ReadyStateEvaluator().evaluate()
    response = {"ready": ready}
    if reason:
        response["reason"] = reason
    return JSONResponse(response)


@router.get("/api/monitoring/events")
async def api_monitoring_events():
    """Return active (unresolved) monitoring events as JSON array."""
    from core.monitoring import MonitoringEvent
    svc = getattr(app_state, "_monitoring_service", None)
    if svc is None:
        return JSONResponse([])
    return JSONResponse([
        {
            "kind": ev.kind,
            "severity": ev.severity,
            "message": ev.message,
            "timestamp": ev.timestamp.isoformat() if ev.timestamp else None,
            "context": ev.context,
        }
        for ev in svc.get_active_events()
    ])


@router.get("/api/system")
async def api_system():
    """Engine identity + runtime facts for the Config System tab (v3.0 P2, G-O8);
    also feeds the StatusFooter uptime (G-O9). Uptime is process-import-relative —
    acceptable for a localhost single-tenant footer (CLAUDE.md Task 163)."""
    return JSONResponse({
        "name":        config.PROJECT_NAME_,
        "short_name":  config.PROJECT_SHORT_NAME,
        "version":     config.PROJECT_VERSION_,
        "description": config.PROJECT_DESCRIPTION,
        "bus_backend": config.PUBSUB_BACKEND,
        "uptime_s":    round(_time.monotonic() - _PROCESS_START_MONO, 1),
        "started_at":  _PROCESS_START_WALL,
        "cadences": {
            "dashboard_poll_s":  config.DASHBOARD_POLL_INTERVAL,
            "calculator_poll_s": config.CALCULATOR_POLL_INTERVAL,
            "history_poll_s":    config.HISTORY_POLL_INTERVAL,
            "ws_status_poll_s":  config.WS_STATUS_POLL_INTERVAL,
            "ws_ping_s":         config.WS_PING_INTERVAL,
        },
    })


@router.get("/api/state")
async def api_state():
    acc = app_state.account_state
    pf  = app_state.portfolio
    aid = app_state.active_account_id
    # G-O2 (v3.0 P1): expose the REAL hard-halt so the React cockpit drives the
    # Pre-Trade freeze overlay + banner (plan §1.3) without a second call. The
    # ONLY engine gate is DD (core/dd_gate) — weekly_pnl has no enforcement gate,
    # so weekly "limit" is advisory-only. This CORRECTS the plan's proposed
    # `(dd OR weekly) AND enforced` formula (plan §2 G-O2): `halted` is the true
    # block (DD enforced + at-limit + not manually overridden; also fail-closed
    # on a settings-read error, per dd_gate); `blocked` = either state at limit
    # (advisory "at cap").
    from core.dd_gate import dd_gate_allows_new_entry
    from core.db_account_settings import get_account_settings
    allowed, halt_reason = dd_gate_allows_new_entry(aid)
    try:
        _s = get_account_settings(aid)
        dd_mode, wk_mode = _s.dd_enforcement_mode, _s.weekly_pnl_enforcement_mode
    except Exception:
        # Settings unreadable: dd_gate has already fail-closed to halted=True, so
        # report "unknown" rather than "advisory" (which would contradict the
        # halt). [P1 audit LOW-1]
        dd_mode = wk_mode = "unknown"
    return {
        "total_equity":     acc.total_equity,
        "available_margin": acc.available_margin,
        "total_unrealized": acc.total_unrealized,
        "total_exposure":   pf.total_exposure,
        "drawdown":         pf.drawdown,
        "weekly_pnl_state": pf.weekly_pnl_state,
        "dd_state":         pf.dd_state,
        "position_count":   len(app_state.positions),
        # G-O2 halt surface
        "halted":           not allowed,
        "blocked":          pf.dd_state == "limit" or pf.weekly_pnl_state == "limit",
        "halt_reason":      halt_reason or "",
        "dd_enforcement_mode":         dd_mode,
        "weekly_pnl_enforcement_mode": wk_mode,
        "dd_manually_unblocked":       aid in app_state.dd_manually_unblocked,
    }


# ── Engine-Log tile feed (v3.0 P1, G-O1) ─────────────────────────────────
# engine_events event_type → (tag, tone) for the Engine-Log tile. Unknown
# types fall back to ("ENG", "sub").
_ENGINE_LOG_TAGS = {
    "dd_state_transition":           ("DD",   "info"),
    "calculator_blocked":            ("BLK",  "warn"),
    "calc_blocked_contract":         ("BLK",  "warn"),
    "manual_override":               ("OVR",  "info"),
    "enforcement_mode_change":       ("CFG",  "info"),
    "equity_delta_warning":          ("EQ",   "warn"),
    "rate_limit_pause":              ("RATE", "warn"),
    "rate_limit_throttle":           ("RATE", "warn"),
    "rate_limit_block":              ("RATE", "err"),
    "would_have_blocked_dd":         ("SHDW", "warn"),
    "would_have_blocked_weekly_pnl": ("SHDW", "warn"),
    "webhook_dispatch_failed":       ("HOOK", "err"),
    "close_row_build_failed":        ("ERR",  "err"),
}


def _engine_log_line(row: dict, tz=None) -> dict:
    """Map an engine_events row → the Engine-Log tile shape {id,t,tag,msg,tone}."""
    import json as _json
    et = row.get("event_type", "") or ""
    tag, tone = _ENGINE_LOG_TAGS.get(et, ("ENG", "sub"))
    try:
        payload = _json.loads(row.get("payload_json") or "{}")
    except (ValueError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {"value": payload}
    ts = row.get("timestamp") or ""
    try:
        dt = datetime.fromisoformat(ts)
        if tz is not None:
            dt = dt.astimezone(tz)
        t = dt.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        t = ts[11:19] if len(ts) >= 19 else ts
    if et == "dd_state_transition":
        msg = f"DD {payload.get('from', '?')} → {payload.get('to', '?')}"
        dd = payload.get("drawdown")
        if isinstance(dd, (int, float)):
            msg += f" (dd {dd:.2%})"
    elif et == "enforcement_mode_change":
        # producer writes {from, to} (routes_admin.py) — [P1 audit LOW-3]
        msg = f"enforcement {payload.get('from', '?')} → {payload.get('to', '?')}"
    else:
        kv = " · ".join(f"{k}={v}" for k, v in list(payload.items())[:4])
        msg = et.replace("_", " ") + (f" · {kv}" if kv else "")
    return {"id": row.get("id"), "t": t, "tag": tag, "msg": msg, "tone": tone}


@router.get("/api/engine/log")
async def api_engine_log(since: int = 0, limit: int = 60):
    """Engine-Log tile feed (v3.0 P1, G-O1): id-cursor tail of engine_events for
    the active account. Returns lines oldest-first + latest_id. The client seeds
    with since=0 (newest N, chronological) then polls ?since=latest_id and
    prepends. Fails soft to an empty page (never a 500 in the poll loop)."""
    from core.event_log import query_events_since
    aid = app_state.active_account_id
    limit = max(1, min(int(limit or 60), 500))
    try:
        rows = query_events_since(aid, since_id=int(since or 0), limit=limit)
    except Exception as e:
        log.warning("[api_engine_log] query failed: %s", e)
        return JSONResponse({"lines": [], "latest_id": int(since or 0)})
    tz = get_account_tz(aid)
    lines = [_engine_log_line(r, tz) for r in rows]
    latest_id = lines[-1]["id"] if lines else int(since or 0)
    return JSONResponse({"lines": lines, "latest_id": latest_id})
