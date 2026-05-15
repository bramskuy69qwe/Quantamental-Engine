from __future__ import annotations

import asyncio
import calendar as _cal
import logging
from datetime import datetime, timedelta, timezone as _tz
from typing import Any, Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from core.state import app_state
from core.tz import get_account_tz, now_in_account_tz
from core.database import db
from core import analytics as an
from core.analytics import (
    build_calendar_grid, r_multiple_stats, r_multiple_histogram,
    compute_funding_exposure, compute_beta, daily_returns,
)
from core.exchange import fetch_funding_rates
from api.helpers import templates, _ctx
from api.cache import _maybe_backfill_equity, _inject_live_equity

log = logging.getLogger("routes.analytics")
router = APIRouter()


def _shift_date(dt: datetime, period: str, offset: int) -> datetime:
    """Shift *dt* by *offset* units of *period* for navigation."""
    if period == "weekly":
        return dt + timedelta(weeks=offset)
    if period == "monthly":
        m = dt.month + offset
        y = dt.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        day = min(dt.day, _cal.monthrange(y, m)[1])
        return dt.replace(year=y, month=m, day=day)
    if period == "quarterly":
        return _shift_date(dt, "monthly", offset * 3)
    if period == "yearly":
        day = min(dt.day, _cal.monthrange(dt.year + offset, dt.month)[1])
        return dt.replace(year=dt.year + offset, day=day)
    return dt  # rolling / all_time don't shift


def _period_label(period: str, start: datetime, end: datetime) -> str:
    """Human-friendly label for the resolved period range."""
    if period == "weekly":
        return f"Week of {start.strftime('%b %d')}"
    if period == "monthly":
        return start.strftime("%B %Y")
    if period == "quarterly":
        q = (start.month - 1) // 3 + 1
        return f"Q{q} {start.year}"
    if period == "yearly":
        return str(start.year)
    if period == "rolling_30d":
        return "Rolling 30 Days"
    if period == "rolling_90d":
        return "Rolling 90 Days"
    return "All Time"


def _analytics_range(month: str = "", all: str = "",
                     period: str = "", offset: int = 0) -> tuple:
    """Return (from_ms, to_ms, period_label, period_or_month_str).

    Accepts either legacy month/all params OR new period+offset params.
    period+offset takes precedence when present.
    """
    from core.period_resolver import resolve_period, VALID_PERIODS
    from core.db_account_settings import get_account_settings

    tz = get_account_tz(app_state.active_account_id)
    now = datetime.now(tz)

    # New period-based path
    if period and period in VALID_PERIODS:
        anchor = _shift_date(now, period, offset)
        try:
            settings = get_account_settings(app_state.active_account_id)
            week_dow = settings.week_start_dow
        except Exception:
            week_dow = 1
        start, end = resolve_period(period, tz, now=anchor, week_start_dow=week_dow)
        from_ms = int(start.timestamp() * 1000)
        to_ms   = int(end.timestamp() * 1000)
        label   = _period_label(period, start, end)
        return from_ms, to_ms, label, period

    # Legacy paths (backward compat)
    if all == "1":
        from_ms = 0
        to_ms   = int(now.timestamp() * 1000)
        return from_ms, to_ms, "All Time", "All Time"

    if month:
        try:
            y, m = int(month[:4]), int(month[5:7])
        except (ValueError, IndexError):
            y, m = now.year, now.month
        start = datetime(y, m, 1, tzinfo=tz)
        _, ndays = _cal.monthrange(y, m)
        end = datetime(y, m, ndays, 23, 59, 59, tzinfo=tz)
        from_ms = int(start.timestamp() * 1000)
        to_ms   = int(end.timestamp() * 1000)
        label   = start.strftime("%B %Y")
        month_s = f"{y:04d}-{m:02d}"
        return from_ms, to_ms, label, month_s

    # Default: current month
    y, m = now.year, now.month
    start = datetime(y, m, 1, tzinfo=tz)
    from_ms = int(start.timestamp() * 1000)
    to_ms   = int(now.timestamp() * 1000)
    return from_ms, to_ms, start.strftime("%B %Y"), f"{y:04d}-{m:02d}"


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    now = now_in_account_tz(app_state.active_account_id)
    current_month = f"{now.year:04d}-{now.month:02d}"
    # Read saved default period preference
    try:
        from core.db_account_settings import get_account_settings
        default_period = get_account_settings(
            app_state.active_account_id
        ).analytics_default_period
    except Exception:
        default_period = "monthly"
    return templates.TemplateResponse(
        request,
        "analytics.html",
        _ctx(request, active_page="analytics",
             current_month=current_month,
             default_period=default_period),
    )


@router.get("/fragments/analytics/overview", response_class=HTMLResponse)
async def frag_analytics_overview(request: Request, month: str = "", all: str = "",
                                   period: str = "", offset: int = 0):
    from_ms, to_ms, period_label, month_s = _analytics_range(month, all, period, offset)
    aid = app_state.active_account_id

    stats, boundaries, top_pairs, cumulative, equity_series = await asyncio.gather(
        db.get_journal_stats(from_ms, to_ms, account_id=aid),
        db.get_equity_period_boundaries(from_ms, to_ms, account_id=aid),
        db.get_most_traded_pairs(from_ms, to_ms, limit=5, account_id=aid),
        db.get_cumulative_pnl(account_id=aid),
        db.get_daily_equity_series(from_ms, to_ms, account_id=aid),
        return_exceptions=True,
    )
    if isinstance(stats, Exception):         stats = {}
    if isinstance(boundaries, Exception):    boundaries = {"initial_equity": 0.0, "final_equity": 0.0, "max_drawdown": 0.0}
    if isinstance(top_pairs, Exception):     top_pairs = []
    if isinstance(cumulative, Exception):    cumulative = {"total_pnl": 0.0, "total_deposits": 0.0, "total_withdrawals": 0.0}
    if isinstance(equity_series, Exception): equity_series = []

    trading_days = len(equity_series)
    equity_vals  = [r["total_equity"] for r in equity_series if r.get("total_equity")]
    returns      = an.daily_returns(equity_vals)

    mfe_mae_trades = await db.get_mfe_mae_series(from_ms, to_ms, account_id=aid)
    r_vals         = await db.get_r_multiples(from_ms, to_ms, account_id=aid)
    r_stats        = an.r_multiple_stats(r_vals)

    ratios = {
        "sharpe":        round(an.sharpe(returns),             2),
        "sortino":       round(an.sortino(returns),            2),
        "sharpe_mfe":    round(an.sharpe_mfe(mfe_mae_trades),  2),
        "sortino_mae":   round(an.sortino_mae(mfe_mae_trades), 2),
        "profit_factor": round(r_stats.get("profit_factor", 0.0), 2),
        "expectancy":    round(r_stats.get("expectancy", 0.0), 3),
    }

    return templates.TemplateResponse(
        request,
        "fragments/analytics/overview_stats.html",
        _ctx(request,
             stats=stats, boundaries=boundaries, top_pairs=top_pairs,
             cumulative=cumulative, ratios=ratios, trading_days=trading_days,
             period_label=period_label, month=month_s),
    )


@router.get("/fragments/analytics/equity_curve", response_class=HTMLResponse)
async def frag_analytics_equity(request: Request, tf: str = "1M", log: str = "", dd: str = ""):
    now = now_in_account_tz(app_state.active_account_id)
    tf_ohlc_map = {
        "1W":  (1440,   7,   7),
        "2W":  (1440,  14,  14),
        "1M":  (1440,  30,  30),
        "3M":  (1440,  91,  91),
        "6M":  (1440, 182, 182),
        "1Y":  (10080, 52, 365),
        "all": (10080, 260, 730),
    }
    tf_minutes, limit, backfill_days = tf_ohlc_map.get(tf, (1440, 30, 30))
    period_label = "All Time" if tf == "all" else f"Last {tf}"

    aid = app_state.active_account_id
    from_ms = int((now - timedelta(days=backfill_days)).timestamp() * 1000)
    await _maybe_backfill_equity(from_ms, account_id=aid)
    candles = await db.get_equity_ohlc(tf_minutes=tf_minutes, limit=limit, account_id=aid)
    _inject_live_equity(candles)

    return templates.TemplateResponse(
        request,
        "fragments/equity_ohlc.html",
        _ctx(request, candles=candles, active_tf=tf,
             eq_id="equity",
             eq_title=f"Equity Curve \u2014 {period_label}",
             eq_height="360px",
             eq_timeframes=[("1W","1W"),("2W","2W"),("1M","1M"),("3M","3M"),("6M","6M"),("1Y","1Y"),("all","All")],
             eq_show_controls=True,
             eq_show_dd=bool(dd),
             eq_log_scale=bool(log),
             eq_fragment_url="/fragments/analytics/equity_curve",
             eq_api_url="/api/analytics/equity_ohlc",
             eq_reload_target="#analytics-content",
             eq_reload_swap="innerHTML"),
    )


@router.get("/api/analytics/equity_ohlc")
async def api_analytics_equity_ohlc(tf: str = "1M"):
    now = now_in_account_tz(app_state.active_account_id)
    tf_ohlc_map = {
        "1W":  (1440,   7,   7),
        "2W":  (1440,  14,  14),
        "1M":  (1440,  30,  30),
        "3M":  (1440,  91,  91),
        "6M":  (1440, 182, 182),
        "1Y":  (10080, 52, 365),
        "all": (10080, 260, 730),
    }
    tf_minutes, limit, backfill_days = tf_ohlc_map.get(tf, (1440, 30, 30))
    aid = app_state.active_account_id
    from_ms = int((now - timedelta(days=backfill_days)).timestamp() * 1000)
    await _maybe_backfill_equity(from_ms, account_id=aid)
    candles = await db.get_equity_ohlc(tf_minutes=tf_minutes, limit=limit, account_id=aid)
    _inject_live_equity(candles)
    return JSONResponse({"candles": candles, "tf": tf})


@router.get("/fragments/analytics/calendar", response_class=HTMLResponse)
async def frag_analytics_calendar(request: Request, month: str = "", all: str = ""):
    aid = app_state.active_account_id
    tz = get_account_tz(aid)
    now = datetime.now(tz)
    if month:
        try:
            y, m = int(month[:4]), int(month[5:7])
        except (ValueError, IndexError):
            y, m = now.year, now.month
    else:
        y, m = now.year, now.month

    prev_d = datetime(y, m, 1, tzinfo=tz) - timedelta(days=1)
    next_d = datetime(y, m, _cal.monthrange(y, m)[1], tzinfo=tz) + timedelta(days=1)
    prev_month = f"{prev_d.year:04d}-{prev_d.month:02d}"
    next_month = f"{next_d.year:04d}-{next_d.month:02d}"

    _, ndays = _cal.monthrange(y, m)
    start = datetime(y, m, 1, tzinfo=tz)
    end   = datetime(y, m, ndays, 23, 59, 59, tzinfo=tz)
    from_ms = int(start.timestamp() * 1000)
    to_ms   = int(end.timestamp() * 1000)

    aid = app_state.active_account_id
    series     = await db.get_daily_equity_series(from_ms, to_ms, account_id=aid)
    daily_pnl  = {r["day"]: r["daily_pnl"] for r in series if r.get("daily_pnl") is not None}
    daily_stats = await db.get_daily_trade_stats(from_ms, to_ms, account_id=aid)
    calendar_grid = build_calendar_grid(y, m, daily_pnl, daily_stats)

    pnl_vals     = [v for v in daily_pnl.values() if v is not None]
    trading_days = len(pnl_vals)
    avg_daily    = sum(pnl_vals) / trading_days if trading_days else 0.0
    best_day     = max(pnl_vals) if pnl_vals else 0.0
    worst_day    = min(pnl_vals) if pnl_vals else 0.0
    max_abs_pnl  = max(abs(v) for v in pnl_vals) if pnl_vals else 1.0

    return templates.TemplateResponse(
        request,
        "fragments/analytics/calendar_pnl.html",
        _ctx(request,
             calendar_grid=calendar_grid, month_label=start.strftime("%B %Y"),
             prev_month=prev_month, next_month=next_month,
             daily_pnl=daily_pnl, trading_days=trading_days,
             avg_daily=avg_daily, best_day=best_day, worst_day=worst_day,
             max_abs_pnl=max_abs_pnl if max_abs_pnl > 0 else 1.0),
    )


@router.get("/fragments/analytics/pairs", response_class=HTMLResponse)
async def frag_analytics_pairs(
    request: Request,
    month: str = "", all: str = "",
    sort_by: str = "total", sort_dir: str = "DESC",
    period: str = "", offset: int = 0,
):
    from_ms, to_ms, period_label, month_s = _analytics_range(month, all, period, offset)
    rows = await db.get_traded_pairs_stats(from_ms, to_ms, account_id=app_state.active_account_id)

    _allowed = {"symbol", "total", "longs", "shorts", "pnl_long", "pnl_short",
                "pnl_total", "win_rate", "avg_win", "avg_loss", "fees_total", "volume"}
    col = sort_by if sort_by in _allowed else "total"
    rev = sort_dir.upper() != "ASC"
    rows.sort(key=lambda r: (r.get(col) or 0), reverse=rev)

    return templates.TemplateResponse(
        request,
        "fragments/analytics/pairs_table.html",
        _ctx(request, rows=rows, period_label=period_label,
             month=month_s, sort_by=col, sort_dir=sort_dir.upper()),
    )


@router.get("/fragments/analytics/excursions", response_class=HTMLResponse)
async def frag_analytics_excursions(
    request: Request,
    month: str = "", all: str = "", dir: str = "all",
    period: str = "", offset: int = 0,
):
    from_ms, to_ms, period_label, month_s = _analytics_range(month, all, period, offset)
    trades = await db.get_mfe_mae_series(from_ms, to_ms, account_id=app_state.active_account_id)

    if dir in ("LONG", "SHORT"):
        trades = [t for t in trades if t.get("direction") == dir]

    mfe_vals    = [t["mfe"]        for t in trades if t.get("mfe")]
    mae_vals    = [abs(t["mae"])   for t in trades if t.get("mae")]
    avg_mfe     = sum(mfe_vals) / len(mfe_vals) if mfe_vals else 0.0
    avg_mae_abs = sum(mae_vals) / len(mae_vals) if mae_vals else 0.0
    mer_vals    = [t["mfe"] / abs(t["mae"]) for t in trades if t.get("mae") and t["mae"] != 0]
    avg_mer     = sum(mer_vals) / len(mer_vals) if mer_vals else 0.0
    fav_count   = sum(1 for t in trades if t.get("mae") and t["mae"] != 0 and t["mfe"] / abs(t["mae"]) > 2)
    pct_fav     = round(fav_count / len(trades) * 100, 1) if trades else 0.0

    scatter_data = [
        {"x": t["mfe"], "y": t["mae"], "z": t["income"], "sym": t["symbol"]}
        for t in trades
    ]

    return templates.TemplateResponse(
        request,
        "fragments/analytics/excursions.html",
        _ctx(request,
             trades=trades[:200], scatter_data=scatter_data,
             avg_mfe=round(avg_mfe, 2), avg_mae_abs=round(avg_mae_abs, 2),
             avg_mer=round(avg_mer, 2), pct_favorable=pct_fav,
             period_label=period_label, filter_dir=dir, month=month_s),
    )


@router.get("/fragments/analytics/r_multiples", response_class=HTMLResponse)
async def frag_analytics_r_multiples(request: Request, month: str = "", all: str = "",
                                      period: str = "", offset: int = 0):
    from_ms, to_ms, period_label, month_s = _analytics_range(month, all, period, offset)
    r_values  = await db.get_r_multiples(from_ms, to_ms, account_id=app_state.active_account_id)
    r_stats   = r_multiple_stats(r_values)
    histogram = r_multiple_histogram(r_values)

    return templates.TemplateResponse(
        request,
        "fragments/analytics/r_multiples.html",
        _ctx(request, r_values=r_values, r_stats=r_stats,
             histogram=histogram, period_label=period_label, month=month_s),
    )


@router.get("/fragments/analytics/var", response_class=HTMLResponse)
async def frag_analytics_var(request: Request, month: str = "", all: str = "",
                              period: str = "", offset: int = 0):
    from_ms, to_ms, period_label, month_s = _analytics_range(month, all, period, offset)
    series   = await db.get_daily_equity_series(from_ms, to_ms, account_id=app_state.active_account_id)
    equities = [r["total_equity"] for r in series if r.get("total_equity")]
    returns  = an.daily_returns(equities)
    cur_equity = app_state.account_state.total_equity or 1.0

    var95  = an.historical_var(returns, 0.95)
    var99  = an.historical_var(returns, 0.99)
    cvar95 = an.conditional_var(returns, 0.95)
    pvar95 = an.parametric_var(returns, 0.95)

    if returns:
        mn = min(returns)
        mx = max(returns)
        step = (mx - mn) / 20 if mx != mn else 0.01
        buckets: dict = {}
        for r in returns:
            b = round((r - mn) // step * step + mn, 4)
            buckets[b] = buckets.get(b, 0) + 1
        hist_data = sorted([{"x": round(k * 100, 2), "y": v} for k, v in buckets.items()],
                           key=lambda d: d["x"])
    else:
        hist_data = []

    return templates.TemplateResponse(
        request,
        "fragments/analytics/var_display.html",
        _ctx(request,
             var95=var95, var99=var99, cvar95=cvar95, pvar95=pvar95,
             cur_equity=cur_equity, returns=returns, hist_data=hist_data,
             period_label=period_label, month=month_s, has_data=len(returns) >= 20),
    )


@router.get("/fragments/analytics/funding", response_class=HTMLResponse)
async def frag_analytics_funding(request: Request):
    positions = app_state.positions
    rows: List[Dict[str, Any]] = []

    if positions:
        symbols = [p.ticker for p in positions]
        try:
            funding_data = await fetch_funding_rates(symbols)
        except Exception:
            funding_data = {}

        for p in positions:
            fd = funding_data.get(p.ticker, {})
            rate     = fd.get("funding_rate", 0.0)
            nft      = fd.get("next_funding_time", 0)
            notional = abs(p.position_value_usdt)
            exp      = compute_funding_exposure(notional, rate)
            adverse  = rate > 0 if p.direction == "LONG" else rate < 0
            nft_str  = "—"
            if nft > 0:
                nft_dt  = datetime.fromtimestamp(nft / 1000, tz=_tz.utc).astimezone(get_account_tz(app_state.active_account_id))
                nft_str = nft_dt.strftime("%H:%M:%S")
            rows.append({
                "ticker": p.ticker, "direction": p.direction,
                "notional": notional, "funding_rate": rate,
                "per_8h": exp["per_8h"], "per_day": exp["per_day"],
                "per_week": exp["per_week"], "next_funding": nft_str, "adverse": adverse,
            })

    total_8h  = sum(r["per_8h"]  for r in rows)
    total_day = sum(r["per_day"] for r in rows)

    return templates.TemplateResponse(
        request,
        "fragments/analytics/funding_tracker.html",
        _ctx(request, rows=rows, total_8h=total_8h, total_day=total_day),
    )


@router.get("/fragments/analytics/beta", response_class=HTMLResponse)
async def frag_analytics_beta(request: Request):
    positions  = app_state.positions
    btc_ohlcv  = app_state.ohlcv_cache.get("BTCUSDT", [])
    btc_closes = [float(c[4]) for c in btc_ohlcv[-31:] if len(c) >= 5]
    btc_returns = daily_returns(btc_closes)

    SECTOR_BETA = {"big_two_crypto": 1.0, "top_twenty_alts": 1.5,
                   "commodities": 0.4, "other_alts": 2.0}

    rows: List[Dict[str, Any]] = []
    for p in positions:
        pos_ohlcv   = app_state.ohlcv_cache.get(p.ticker, [])
        pos_closes  = [float(c[4]) for c in pos_ohlcv[-31:] if len(c) >= 5]
        pos_returns = daily_returns(pos_closes)

        if len(pos_returns) >= 10 and len(btc_returns) >= 10:
            beta = round(compute_beta(pos_returns, btc_returns), 2)
        else:
            beta = SECTOR_BETA.get(p.sector, 1.5)

        notional = abs(p.position_value_usdt)
        rows.append({
            "ticker": p.ticker, "direction": p.direction,
            "sector": p.sector or "—", "notional": notional,
            "beta": beta, "beta_adj_exp": round(notional * beta, 2),
        })

    total_notional = sum(r["notional"]     for r in rows)
    total_beta_exp = sum(r["beta_adj_exp"] for r in rows)
    port_beta      = round(total_beta_exp / total_notional, 2) if total_notional > 0 else 0.0

    sector_totals: Dict[str, float] = {}
    for r in rows:
        s = r["sector"] or "unknown"
        sector_totals[s] = sector_totals.get(s, 0.0) + r["beta_adj_exp"]

    return templates.TemplateResponse(
        request,
        "fragments/analytics/beta_exposure.html",
        _ctx(request, rows=rows, total_notional=total_notional,
             total_beta_exp=total_beta_exp, port_beta=port_beta,
             sector_totals=sector_totals),
    )
