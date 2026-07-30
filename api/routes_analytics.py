from __future__ import annotations

import asyncio
import calendar as _cal
import logging
from datetime import datetime, timedelta, timezone as _tz
from typing import Any, Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.state import app_state
from core.tz import get_account_tz, now_in_account_tz
from core.database import db
from core import analytics as an
from core.analytics import (
    build_calendar_grid, r_multiple_stats, r_multiple_histogram,
    compute_funding_exposure, compute_beta, daily_returns,
)
from core.exchange import fetch_funding_rates
from api.cache import _maybe_backfill_equity, _inject_live_equity

log = logging.getLogger("routes.analytics")
router = APIRouter()


def _analytics_json(payload: Dict[str, Any]) -> JSONResponse:
    """v3.0 P5 JSON-door envelope — every analytics door passes through the
    _json_safe non-finite guard (F2 discipline, both-doors rule)."""
    from api.routes_calculator import _json_safe
    return JSONResponse(_json_safe(payload))


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
        # all_time resolves start=datetime.min — a hugely NEGATIVE epoch. Windows'
        # gmtime() cannot represent it: utcfromtimestamp raised in get_r_multiples
        # (unguarded → the fragment 500'd) while the gathered stats calls degraded
        # SILENTLY to {}. Clamp to epoch 0 = the legacy all=1 semantics exactly.
        from_ms = max(0, int(start.timestamp() * 1000))
        to_ms   = max(0, int(end.timestamp() * 1000))
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


# (Jinja retirement 2026-07-30: GET /analytics + analytics.html retired —
# the React Analytics page is the twin. Fragments slim-down 2026-07-30:
# every /fragments/analytics/* door below is JSON-ONLY — the HTML twins are
# deleted; /fragments/analytics/equity_curve was removed outright (React
# reads /api/analytics/equity_ohlc instead).)


@router.get("/fragments/analytics/overview", response_class=JSONResponse)
async def frag_analytics_overview(request: Request, month: str = "", all: str = "",
                                   period: str = "", offset: int = 0,
                                   format: str = ""):
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

    # Fragments slim-down (2026-07-30): JSON-only — the HTML twin
    # (overview_stats.html) is retired; `format` stays accepted-and-inert.
    # Payload = the fragment context plus the route-computed daily_equity
    # series (already fetched above) so the React overview mini-curve needs
    # no second request.
    return _analytics_json({
        "stats": stats, "boundaries": boundaries, "top_pairs": top_pairs,
        "cumulative": cumulative, "ratios": ratios,
        # r_count lets the client tell "PF genuinely 0" from "no
        # R-linked closes at all" (audit L1 — 0.00-red vs em-dash).
        "r_count": len(r_vals),
        "trading_days": trading_days, "period_label": period_label,
        "month": month_s,
        "daily_equity": [
            {"day": r.get("day"), "total_equity": r.get("total_equity"),
             "daily_pnl": r.get("daily_pnl")}
            for r in equity_series
        ],
    })


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
    # v3.0 P5: _json_safe wrap added (F2 discipline) — this was the one
    # analytics JSON endpoint predating the both-doors non-finite guard.
    return _analytics_json({"candles": candles, "tf": tf})


@router.get("/fragments/analytics/calendar", response_class=JSONResponse)
async def frag_analytics_calendar(request: Request, month: str = "", all: str = "",
                                  format: str = ""):
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

    # Fragments slim-down (2026-07-30): JSON-only — the HTML twin
    # (calendar_pnl.html) is retired; `format` stays accepted-and-inert.
    # Grid cells carry day/date-string/pnl/trades/win_rate; the React
    # calendar renders heat client-side off max_abs_pnl.
    return _analytics_json({
        "calendar_grid": calendar_grid,
        "month_label": start.strftime("%B %Y"),
        # month/current_month are ACCOUNT-tz truths so the client's
        # Next-clamp can't drift across a tz month boundary (audit L7).
        "month": f"{y:04d}-{m:02d}",
        "current_month": f"{now.year:04d}-{now.month:02d}",
        "prev_month": prev_month, "next_month": next_month,
        "trading_days": trading_days, "avg_daily": avg_daily,
        "best_day": best_day, "worst_day": worst_day,
        "max_abs_pnl": max_abs_pnl if max_abs_pnl > 0 else 1.0,
    })


@router.get("/fragments/analytics/pairs", response_class=JSONResponse)
async def frag_analytics_pairs(
    request: Request,
    month: str = "", all: str = "",
    sort_by: str = "total", sort_dir: str = "DESC",
    period: str = "", offset: int = 0,
    format: str = "",
):
    from_ms, to_ms, period_label, month_s = _analytics_range(month, all, period, offset)
    rows = await db.get_traded_pairs_stats(from_ms, to_ms, account_id=app_state.active_account_id)

    _allowed = {"symbol", "total", "longs", "shorts", "pnl_long", "pnl_short",
                "pnl_total", "win_rate", "avg_win", "avg_loss", "fees_total", "volume"}
    col = sort_by if sort_by in _allowed else "total"
    rev = sort_dir.upper() != "ASC"
    rows.sort(key=lambda r: (r.get(col) or 0), reverse=rev)

    # Fragments slim-down (2026-07-30): JSON-only — the HTML twin
    # (pairs_table.html) is retired; `format` stays accepted-and-inert.
    return _analytics_json({"rows": rows, "period_label": period_label,
                            "month": month_s, "sort_by": col,
                            "sort_dir": sort_dir.upper()})


@router.get("/fragments/analytics/excursions", response_class=JSONResponse)
async def frag_analytics_excursions(
    request: Request,
    month: str = "", all: str = "", dir: str = "all",
    period: str = "", offset: int = 0,
    format: str = "",
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

    # Fragments slim-down (2026-07-30): JSON-only — the HTML twin
    # (excursions.html) is retired; `format` stays accepted-and-inert.
    # dir filter applied server-side so the summary stats and the row set
    # stay consistent (the design filtered client-side).
    return _analytics_json({
        "trades": trades[:200], "scatter_data": scatter_data,
        "avg_mfe": round(avg_mfe, 2), "avg_mae_abs": round(avg_mae_abs, 2),
        "avg_mer": round(avg_mer, 2), "pct_favorable": pct_fav,
        "period_label": period_label, "filter_dir": dir, "month": month_s,
    })


@router.get("/fragments/analytics/r_multiples", response_class=JSONResponse)
async def frag_analytics_r_multiples(request: Request, month: str = "", all: str = "",
                                      period: str = "", offset: int = 0,
                                      format: str = ""):
    from_ms, to_ms, period_label, month_s = _analytics_range(month, all, period, offset)
    r_values  = await db.get_r_multiples(from_ms, to_ms, account_id=app_state.active_account_id)
    r_stats   = r_multiple_stats(r_values)
    histogram = r_multiple_histogram(r_values)

    # Fragments slim-down (2026-07-30): JSON-only — the HTML twin
    # (r_multiples.html) is retired; `format` stays accepted-and-inert.
    return _analytics_json({"r_values": r_values, "r_stats": r_stats,
                            "histogram": histogram,
                            "period_label": period_label, "month": month_s})


@router.get("/fragments/analytics/var", response_class=JSONResponse)
async def frag_analytics_var(request: Request, month: str = "", all: str = "",
                              period: str = "", offset: int = 0,
                              format: str = ""):
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

    # Fragments slim-down (2026-07-30): JSON-only — the HTML twin
    # (var_display.html) is retired; `format` stays accepted-and-inert.
    # has_data mirrors the ≥20-returns VaR guard.
    return _analytics_json({
        "var95": var95, "var99": var99, "cvar95": cvar95, "pvar95": pvar95,
        "cur_equity": cur_equity, "returns": returns, "hist_data": hist_data,
        "period_label": period_label, "month": month_s,
        "has_data": len(returns) >= 20,
    })


@router.get("/fragments/analytics/funding", response_class=JSONResponse)
async def frag_analytics_funding(request: Request, format: str = ""):
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

    # Fragments slim-down (2026-07-30): JSON-only — the HTML twin
    # (funding_tracker.html) is retired; `format` stays accepted-and-inert.
    # per_8h/per_day/per_week are UNSIGNED magnitudes
    # (compute_funding_exposure); the sign for display derives from the
    # `adverse` flag client-side. total_8h/total_day are magnitude sums
    # (/api/linkage/funding's net_next is the SIGNED twin).
    return _analytics_json({"rows": rows, "total_8h": total_8h,
                            "total_day": total_day})


@router.get("/fragments/analytics/beta", response_class=JSONResponse)
async def frag_analytics_beta(request: Request, format: str = ""):
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

    # Fragments slim-down (2026-07-30): JSON-only — the HTML twin
    # (beta_exposure.html) is retired; `format` stays accepted-and-inert.
    # beta_adj_exp is UNSIGNED (abs notional × beta, no SHORT sign flip —
    # the design mock's signed short exposure has no engine source).
    return _analytics_json({"rows": rows, "total_notional": total_notional,
                            "total_beta_exp": total_beta_exp,
                            "port_beta": port_beta,
                            "sector_totals": sector_totals})


# ─── v3.0 P5 (G-O4): Execution-Quality + Distributions JSON backends ────────
#
# Named deviation from the plan row ("add /fragments/analytics/execution +
# /distributions"): these ship as /api JSON endpoints, not HTML fragments —
# their only consumer is the React Analytics page and no Jinja twin exists
# to hold parity with (the same shape G-O6 took: /api/linkage/funding).
# Built from fills JOIN pre_trade_log per the P5 mechanism correction —
# NOT execution_log, which is the manual-UI journal (no calc_id / fill_type
# / slippage_actual).

_EXEC_LIMIT_MAX = 2000


@router.get("/api/analytics/execution")
async def api_analytics_execution(limit: int = 500):
    """Execution-quality per-fill rows + summary aggregates.

    Row semantics:
    - est_slippage: pre_trade_log.est_slippage — the UNSIGNED predicted
      market-impact fraction vs top-of-book at calc time. ENTRY FILLS ONLY
      (P5 audit L-2: a close fill's residual is measured vs its trigger,
      so pairing it with the entry impact estimate is axis salad); None
      when absent.
    - slippage_actual: fills.slippage_actual — RAW signed (fill−expected)/
      expected fraction (order_enrichment convention, not side-normalized).
      For entries `expected` is pre_trade_log.effective_entry — the
      IMPACT-ADJUSTED predicted fill — so this is a RESIDUAL vs the
      prediction, not total slippage (P5 audit H-1).
    - slippage_cost: side-normalized residual (+ = worse than the plan's
      predicted fill, − = better): BUY keeps the raw sign, SELL flips it.
      A perfectly calibrated model produces 0, NOT est_slippage.
    - time_to_fill_ms: fills.timestamp_ms − orders.created_at_ms (engine-
      observed order→fill elapsed). There is NO signal→fill latency source
      in the observe-only architecture — named deviation from the design's
      ms-scale "latency" pane; this is time-to-fill and can be hours for
      resting limit orders.
    - link_status: '' for close fills / fills without calc_id (P4 drawer
      parity), else get_exec_link_status ('linked'|'partial'|'unlinked');
      link_confirmed marks the operator-confirmed subset of 'linked'.

    Aggregates ride the SAME returned window (newest `limit` fills) — the
    summary is not an all-time scan (named residue: window == rows).
    """
    from core.exec_link import DEFAULT_LINK_WINDOW_SECONDS, get_exec_link_status
    from api.routes_orders import _pretrade_ts_to_ms

    aid = app_state.active_account_id
    limit = max(1, min(int(limit or 500), _EXEC_LIMIT_MAX))
    raw = await db.get_execution_quality(account_id=aid, limit=limit)

    window = await db.get_account_link_window_seconds(aid)
    if window is None:
        window = DEFAULT_LINK_WINDOW_SECONDS

    rows: List[Dict[str, Any]] = []
    for r in raw:
        side = (r.get("side") or "").upper()
        slip = r.get("slippage_actual")
        cost = None if slip is None else (slip if side == "BUY" else -slip)

        created = r.get("order_created_ms") or 0
        ts = r.get("timestamp_ms") or 0
        ttf = ts - created if (created > 0 and ts >= created) else None

        has_ptl = r.get("ptl_calc_id") is not None
        est = (r.get("est_slippage")
               if (has_ptl and r.get("fill_type") == "entry") else None)

        if r.get("is_close") or not r.get("calc_id"):
            status, count = "", 0
        else:
            fill_d = {"calc_id": r.get("calc_id"),
                      "exec_link_confirmed": r.get("exec_link_confirmed"),
                      "price": r.get("price")}
            ptl_d = None
            if has_ptl:
                ptl_d = {"effective_entry": r.get("est_entry"),
                         "average": r.get("est_average"),
                         "tp_price": r.get("plan_tp"),
                         "sl_price": r.get("plan_sl"),
                         "link_window_seconds_override": r.get("link_window_override")}
            pretrade_ts_ms = (
                _pretrade_ts_to_ms({"timestamp": r.get("pretrade_ts")})
                if has_ptl else None
            )
            status, count = get_exec_link_status(
                fill_d, ptl_d, r.get("order_type") or "",
                fill_ts_ms=r.get("timestamp_ms"),
                pretrade_ts_ms=pretrade_ts_ms,
                account_link_window_seconds=window,
            )

        rows.append({
            "fill_id": r.get("fill_id"),
            "exchange_fill_id": r.get("exchange_fill_id"),
            "time_ms": r.get("timestamp_ms"),
            "symbol": r.get("symbol"),
            "side": r.get("side"),
            "direction": r.get("direction"),
            "price": r.get("price"),
            "quantity": r.get("quantity"),
            "fee": r.get("fee"),
            "fee_asset": r.get("fee_asset"),
            "role": (r.get("role") or "").lower() or None,
            "is_close": bool(r.get("is_close")),
            "calc_id": r.get("calc_id"),
            "fill_type": r.get("fill_type"),
            "order_type": r.get("order_type"),
            "est_slippage": est,
            "slippage_actual": slip,
            "slippage_cost": cost,
            "time_to_fill_ms": ttf,
            "link_status": status,
            "link_confirmed": bool(r.get("exec_link_confirmed")),
            "match_count": count,
        })

    total = len(rows)
    by_fill_type: Dict[str, int] = {}
    by_order_type: Dict[str, int] = {}
    maker = taker = linked = confirmed = calc_backed = 0
    est_bps: List[float] = []
    cost_bps: List[float] = []
    ttfs: List[int] = []
    for row in rows:
        ft = row["fill_type"] or "unclassified"
        by_fill_type[ft] = by_fill_type.get(ft, 0) + 1
        ot = row["order_type"] or "unknown"
        by_order_type[ot] = by_order_type.get(ot, 0) + 1
        if row["role"] == "maker":
            maker += 1
        elif row["role"] == "taker":
            taker += 1
        if row["calc_id"]:
            calc_backed += 1
        if row["link_status"] == "linked":
            linked += 1
            if row["link_confirmed"]:
                confirmed += 1
        if row["time_to_fill_ms"] is not None:
            ttfs.append(row["time_to_fill_ms"])
        # Bias sample: entry fills carrying BOTH an estimate and an actual.
        if (row["fill_type"] == "entry" and row["est_slippage"] is not None
                and row["slippage_cost"] is not None):
            est_bps.append(row["est_slippage"] * 10000)
            cost_bps.append(row["slippage_cost"] * 10000)

    ttfs.sort()
    avg_est = sum(est_bps) / len(est_bps) if est_bps else None
    avg_cost = sum(cost_bps) / len(cost_bps) if cost_bps else None
    summary = {
        "total": total,
        "calc_backed": calc_backed,
        "linked": linked,
        "confirmed": confirmed,
        "by_fill_type": by_fill_type,
        "by_order_type": by_order_type,
        "maker": maker,
        "taker": taker,
        "entry_n": len(est_bps),
        "avg_est_bp": avg_est,
        "avg_cost_bp": avg_cost,
        # P5 audit H-1: slippage_cost is already the residual vs the
        # impact-adjusted prediction, so the calibration bias IS its mean —
        # subtracting avg_est would double-count the predicted impact
        # (perfect model → bias −avg_est instead of 0).
        "bias_bp": avg_cost,
        "ttf_n": len(ttfs),
        "ttf_avg_ms": (sum(ttfs) / len(ttfs)) if ttfs else None,
        "ttf_p95_ms": ttfs[min(len(ttfs) - 1, int(len(ttfs) * 0.95))] if ttfs else None,
        "ttf_max_ms": ttfs[-1] if ttfs else None,
    }
    return _analytics_json({"rows": rows, "summary": summary, "limit": limit})


@router.get("/api/analytics/distributions")
async def api_analytics_distributions(month: str = "", all: str = "",
                                      period: str = "", offset: int = 0):
    """v3.0 P5 (G-O4): per-trade tuples for the Distributions histograms.

    The client bins (design parity); hour/dow are bucketed server-side in
    the ACCOUNT timezone (hour 0-23; dow 0=Mon..6=Sun — Python weekday()).
    hold_min is None when open_time is unknown (pre-backfill rows).
    R-multiples ride along via the shared get_r_multiples +
    r_multiple_histogram (the R-Multiples tab's own 8-bin shape).
    """
    from_ms, to_ms, period_label, month_s = _analytics_range(month, all, period, offset)
    aid = app_state.active_account_id
    tz = get_account_tz(aid)

    series = await db.get_trade_distribution_series(from_ms, to_ms, account_id=aid)
    trades: List[Dict[str, Any]] = []
    for t in series:
        close_ms = t.get("time") or 0
        open_ms = t.get("open_time") or 0
        hold_min = None
        if open_ms > 0 and close_ms >= open_ms:
            hold_min = round((close_ms - open_ms) / 60000.0, 1)
        local = (datetime.fromtimestamp(close_ms / 1000, tz=tz)
                 if close_ms > 0 else None)
        trades.append({
            "symbol": t.get("symbol"),
            "direction": t.get("direction"),
            "pnl": t.get("income"),
            "hold_min": hold_min,
            "hour": local.hour if local else None,
            "dow": local.weekday() if local else None,
            "time_ms": close_ms or None,
        })

    r_values = await db.get_r_multiples(from_ms, to_ms, account_id=aid)
    return _analytics_json({
        "trades": trades,
        "count": len(trades),
        "r_values": r_values,
        "r_histogram": r_multiple_histogram(r_values),
        "period_label": period_label,
        "month": month_s,
    })
