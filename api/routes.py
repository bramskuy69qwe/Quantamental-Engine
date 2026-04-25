"""
FastAPI route handlers.
All fragment endpoints return HTML (Jinja2 partials) for HTMX swapping.
"""
from __future__ import annotations
import asyncio
import logging
import os
import json
import time as _time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

log = logging.getLogger("routes")

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates

import config
from core.state import app_state, TZ_LOCAL
from core.risk_engine import run_risk_calculator
from core.data_logger import (
    log_execution, log_trade_close,
    load_recent_history,
)
from core import ws_manager

router = APIRouter()

# ── Equity backfill (on-demand, from Binance income history) ──────────────────
_backfill_lock = asyncio.Lock()
# Per-account cache of the earliest snapshot epoch-ms we know exists in the DB.
# Keyed by account_id; missing key = not yet read for that account.
_backfill_earliest_ms: Dict[int, Optional[int]] = {}


def _debug_log(hypothesis_id: str, location: str, message: str, data: Dict[str, Any]) -> None:
    # #region agent log
    try:
        payload = {
            "sessionId": "3bf805",
            "runId": "equity-jump-debug",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(_time.time() * 1000),
        }
        with open("debug-3bf805.log", "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception:
        pass
    # #endregion


async def _maybe_backfill_equity(needed_start_ms: int, account_id: Optional[int] = None) -> None:
    """
    Backfill account_snapshots from Binance income history if the DB does not
    have data going back to needed_start_ms.  Safe to call on every request —
    after the first backfill the check is an in-memory integer comparison.
    """
    from core.database import db
    from core.exchange import build_equity_backfill

    aid = account_id if account_id is not None else app_state.active_account_id
    cached = _backfill_earliest_ms.get(aid)

    # Fast path: cached earliest is already before the needed window → nothing to do
    if cached is not None and cached <= needed_start_ms:
        return

    # Slow path: read DB once to populate / verify the cache
    earliest_ms = await db.get_earliest_snapshot_ms(account_id=aid)
    # Update cache to the true DB minimum (may be earlier than cached value)
    if earliest_ms is not None:
        if cached is None or earliest_ms < cached:
            _backfill_earliest_ms[aid] = earliest_ms
            cached = _backfill_earliest_ms[aid]

    if cached is not None and cached <= needed_start_ms:
        return  # DB already has enough history

    async with _backfill_lock:
        # Re-check after acquiring the lock (concurrent request may have already filled)
        cached = _backfill_earliest_ms.get(aid)
        if cached is not None and cached <= needed_start_ms:
            return

        current_equity = app_state.account_state.total_equity
        if current_equity == 0:
            return  # Cannot reconstruct without a known current equity

        # Clear stale backfill data so the improved gap-fill logic applies cleanly.
        # Only synthetic rows are deleted — real snapshots are never touched.
        await db.clear_backfill_snapshots(account_id=aid)
        await db.clear_cashflow_events(account_id=aid)

        # Re-read the real earliest snapshot now that backfill rows are gone.
        real_earliest_ms = await db.get_earliest_snapshot_ms(account_id=aid)
        end_for_backfill  = real_earliest_ms if real_earliest_ms else int(_time.time() * 1000)

        records, cashflow_records = await build_equity_backfill(
            needed_start_ms, end_for_backfill, current_equity
        )
        if records:
            count = await db.insert_backfill_snapshots(records, before_ms=end_for_backfill, account_id=aid)
            log.info("Equity backfill: inserted %d synthetic snapshots", count)
            _backfill_earliest_ms[aid] = records[0][0]
        else:
            # No income events found; reset cache so next request retries
            _backfill_earliest_ms[aid] = real_earliest_ms

        if cashflow_records:
            cf_count = await db.insert_cashflow_events(cashflow_records, account_id=aid)
            log.info("Equity backfill: inserted %d cashflow events", cf_count)
        _debug_log(
            "H3",
            "api/routes.py:_maybe_backfill_equity",
            "Backfill write summary",
            {
                "needed_start_ms": int(needed_start_ms),
                "real_earliest_ms": int(real_earliest_ms) if real_earliest_ms else None,
                "end_for_backfill": int(end_for_backfill),
                "records_count": len(records),
                "cashflow_count": len(cashflow_records),
                "cached_earliest_after": int(_backfill_earliest_ms[aid]) if _backfill_earliest_ms.get(aid) is not None else None,
            },
        )


# ── Funding rate cache ────────────────────────────────────────────────────────
# Binance funding rates change every 8h; we cache for 60s to avoid hammering
# the REST API on every 2s dashboard refresh.
_FUNDING_CACHE: Dict[str, Any] = {
    "total_8h": 0.0, "total_day": 0.0, "rows": [], "ts": 0.0,
}

async def _get_funding_cached() -> Dict[str, Any]:
    """Return cached funding totals; refreshes at most every 60 seconds."""
    if _time.monotonic() - _FUNDING_CACHE["ts"] < 60.0:
        return _FUNDING_CACHE
    positions = app_state.positions
    if not positions:
        _FUNDING_CACHE.update({"total_8h": 0.0, "total_day": 0.0, "rows": [], "ts": _time.monotonic()})
        return _FUNDING_CACHE
    symbols = [p.ticker for p in positions]
    try:
        from core.exchange import fetch_funding_rates
        funding_data = await fetch_funding_rates(symbols)
    except Exception:
        funding_data = {}
    from core.analytics import compute_funding_exposure
    from datetime import timezone as _tz
    total_8h = 0.0
    total_day = 0.0
    items: List[Dict[str, Any]] = []
    for p in positions:
        fd = funding_data.get(p.ticker, {})
        rate = fd.get("funding_rate", 0.0)
        nft  = fd.get("next_funding_time", 0)
        notional = abs(p.position_value_usdt)
        exp = compute_funding_exposure(notional, rate)
        adverse = (rate > 0) if p.direction == "LONG" else (rate < 0)
        nft_str = "—"
        if nft > 0:
            nft_dt = datetime.fromtimestamp(nft / 1000, tz=_tz.utc).astimezone(TZ_LOCAL)
            nft_str = nft_dt.strftime("%H:%M")
        total_8h  += exp["per_8h"]
        total_day += exp["per_day"]
        items.append({
            "ticker": p.ticker, "direction": p.direction,
            "rate": rate, "next": nft_str,
            "adverse": adverse, "per_8h": exp["per_8h"],
        })
    _FUNDING_CACHE.update({
        "total_8h": total_8h, "total_day": total_day,
        "rows": items, "ts": _time.monotonic(),
    })
    return _FUNDING_CACHE

# Absolute path — works regardless of CWD when uvicorn is launched
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(_BASE_DIR, "templates"))

# fmt registered as a Jinja2 global so every template can call it
def _fmt(val, decimals=2, suffix=""):
    try:
        return f"{float(val):,.{decimals}f}{suffix}"
    except Exception:
        return str(val)

templates.env.globals["fmt"] = _fmt


def _fmt_duration(ms) -> str:
    """
    Format a millisecond duration as a compact hold time string.
    Leading zero-value units are omitted; always shows at least seconds.
      6_000        → "06s"
      403_000      → "06m 43s"
      8_123_000    → "2h 15m 03s"
      90_061_000   → "1d 01h 01m 01s"
    """
    try:
        total_s = max(0, int(float(ms)) // 1000)
    except (TypeError, ValueError):
        return "—"
    d =  total_s // 86400
    h = (total_s % 86400) // 3600
    m = (total_s % 3600)  // 60
    s =  total_s % 60
    parts = []
    if d:
        parts.append(f"{d}d")
    if d or h:
        parts.append(f"{h:02d}h")
    if d or h or m:
        parts.append(f"{m:02d}m")
    parts.append(f"{s:02d}s")
    return " ".join(parts)


templates.env.globals["fmt_duration"] = _fmt_duration


# ── Context helper ────────────────────────────────────────────────────────────

def _ctx(request: Request, **extra) -> dict:
    """Base context for every template (Starlette 0.41+ new-style: no 'request' key)."""
    from core.account_registry import account_registry
    return {
        "now":               datetime.now(TZ_LOCAL).strftime("%Y-%m-%d %H:%M:%S"),
        "ws_status":         app_state.ws_status,
        "params":            app_state.params,
        "is_initializing":   app_state.is_initializing,
        "active_account_id": app_state.active_account_id,
        "active_platform":   app_state.active_platform,
        "accounts":          account_registry.list_accounts_sync(),
        **extra,
    }


# ── Pages ─────────────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    from fastapi.responses import FileResponse
    return FileResponse("static/index.html")


@router.get("/calculator", response_class=HTMLResponse)
async def calculator_page(request: Request):
    return templates.TemplateResponse(request, "calculator.html", _ctx(request, calc=None))


@router.get("/history", response_class=HTMLResponse)
async def history_page(request: Request):
    from datetime import timedelta
    from core.database import db as _db

    now       = datetime.now(TZ_LOCAL)
    date_from = (now - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00")
    date_to   = now.strftime("%Y-%m-%dT23:59:59")

    # Pre-fetch first page of each table (matches JS 30-day default).
    # SQLite queries are local and fast; total latency is negligible.
    aid = app_state.active_account_id
    ex_rows, ex_total = await _db.query_exchange_history(
        date_from=date_from, date_to=date_to, tz_local=TZ_LOCAL, account_id=aid,
    )
    ex_notes = await _db.get_position_notes([r["trade_key"] for r in ex_rows])
    ex_pages  = max(1, (ex_total + 19) // 20)

    pt_rows, pt_total = await _db.query_pre_trade_log(
        date_from=date_from, date_to=date_to, account_id=aid,
    )
    pt_pages = max(1, (pt_total + 19) // 20)

    el_rows, el_total = await _db.query_execution_log(
        date_from=date_from, date_to=date_to, account_id=aid,
    )
    el_pages = max(1, (el_total + 19) // 20)

    return templates.TemplateResponse(
        request, "history.html",
        _ctx(request,
             _init_date_from=date_from,
             _init_date_to=date_to,
             _init_ex_rows=ex_rows,   _init_ex_total=ex_total,
             _init_ex_pages=ex_pages, _init_ex_notes=ex_notes,
             _init_pt_rows=pt_rows,   _init_pt_total=pt_total,
             _init_pt_pages=pt_pages,
             _init_el_rows=el_rows,   _init_el_total=el_total,
             _init_el_pages=el_pages,
        ),
    )


@router.get("/params", response_class=HTMLResponse)
async def params_page(request: Request):
    return templates.TemplateResponse(request, "params.html", _ctx(request))


# ── Dashboard fragments ───────────────────────────────────────────────────────

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
    from core.database import db
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
    from core.database import db
    from core import analytics as an
    now = datetime.now(TZ_LOCAL)
    # Current month range
    import calendar as _cal
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
        {"ws": app_state.ws_status, "ex": app_state.exchange_info},
    )


# ── Risk Calculator ───────────────────────────────────────────────────────────

@router.post("/calculator/calculate", response_class=HTMLResponse)
async def calculate_risk(
    request:                 Request,
    ticker:                  str   = Form(...),
    average:                 float = Form(...),
    sl_price:                float = Form(...),
    tp_price:                float = Form(0.0),
    tp_amount_pct:           float = Form(100.0),
    sl_amount_pct:           float = Form(100.0),
    model_name:              str   = Form(""),
    model_desc:              str   = Form(""),
    order_type:              str   = Form("market"),
    auto_refresh:            str   = Form("0"),
    apply_regime_multiplier: str   = Form("1"),
):
    ticker = ticker.upper().strip()
    from core.exchange import fetch_orderbook, fetch_ohlcv
    ws_manager.set_calculator_symbol(ticker)

    try:
        await fetch_orderbook(ticker)
        if ticker not in app_state.ohlcv_cache:
            await fetch_ohlcv(ticker)
    except Exception as e:
        return HTMLResponse(f'<div class="alert-error p-3 rounded">Data fetch error: {e}</div>')

    calc = run_risk_calculator(
        ticker=ticker, average=average, sl_price=sl_price,
        tp_price=tp_price, tp_amount_pct=tp_amount_pct,
        sl_amount_pct=sl_amount_pct, model_name=model_name, model_desc=model_desc,
        order_type=order_type,
        apply_regime_multiplier=(apply_regime_multiplier == "1"),
    )

    # Publish to event bus — skip on auto-refresh to avoid flooding DB
    if auto_refresh != "1":
        from core.event_bus import event_bus
        await event_bus.publish("risk:risk_calculated", calc)

    return templates.TemplateResponse(
        request, "fragments/calc_result.html",
        _ctx(request, calc=calc),
    )


@router.get("/calculator/refresh/{ticker}", response_class=HTMLResponse)
async def calculator_refresh(request: Request, ticker: str):
    ticker = ticker.upper()
    try:
        from core.exchange import fetch_orderbook
        await fetch_orderbook(ticker)
    except Exception:
        pass

    ob   = app_state.orderbook_cache.get(ticker, {})
    bids = ob.get("bids", [])[:5]
    asks = ob.get("asks", [])[:5]
    return templates.TemplateResponse(
        request, "fragments/orderbook.html",
        {"ticker": ticker, "bids": bids, "asks": asks},
    )


# ── History ───────────────────────────────────────────────────────────────────

@router.get("/fragments/history", response_class=HTMLResponse)
async def frag_history(request: Request):
    try:
        from core.database import db
        pre_trade_rows = await db.get_all_pre_trade_log(days=30)
        execution_rows = await db.get_all_execution_log(days=30)
        history_rows   = await db.get_all_trade_history(days=30)
        # live_trades still uses CSV (no DB table in Phase 1)
        live_trades    = load_recent_history(config.LIVE_TRADES)

        return templates.TemplateResponse(
            request, "fragments/history_tables.html",
            _ctx(request,
                 pre_trade_log=pre_trade_rows,
                 execution_log=execution_rows,
                 live_trades=live_trades,
                 trade_history=history_rows,
                 exchange_trades=app_state.exchange_trade_history),
        )
    except Exception as e:
        return HTMLResponse(
            f'<div class="alert-error p-4 rounded">History load error: {e} &mdash; '
            f'<button class="ml-2 btn btn-secondary btn-sm text-xs" '
            f'hx-get="/fragments/history" hx-target="#history-tables" hx-swap="innerHTML">Retry</button></div>'
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
        "maker_fee": config.MAKER_FEE, "taker_fee": config.TAKER_FEE,
        "latency_snapshot": latency_snapshot, "orderbook_depth_snapshot": "",
    }
    from core.database import db
    try:
        await db.insert_execution_log(row)
    except Exception as exc:
        log.error("insert_execution_log failed: %r", exc)
        return HTMLResponse('<div class="alert-error p-2 rounded">Failed to log execution — database error.</div>')
    log_execution(row)   # secondary CSV backup after DB succeeds
    return HTMLResponse('<div class="alert-success p-2 rounded">Execution logged.</div>')


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
    from core.database import db
    try:
        await db.insert_trade_history(row)
    except Exception as exc:
        log.error("insert_trade_history failed: %r", exc)
        return HTMLResponse('<div class="alert-error p-2 rounded">Failed to log trade close — database error.</div>')
    log_trade_close(row)   # secondary CSV backup after DB succeeds
    return HTMLResponse('<div class="alert-success p-2 rounded">Trade close logged.</div>')


# ── Per-table history fragments ──────────────────────────────────────────

def _paginate_list(
    data: List[Dict[str, Any]],
    page: int,
    per_page: int,
    sort_key: str,
    sort_dir: str,
    search: str = "",
    search_fields: tuple = ("symbol", "ticker"),
    filters: Optional[Dict[str, str]] = None,
) -> tuple:
    """In-memory pagination/sort/filter for exchange_trades and live_trades."""
    # Apply search
    if search:
        term = search.lower()
        data = [r for r in data if any(
            term in str(r.get(f, "")).lower() for f in search_fields
        )]
    # Apply filters
    if filters:
        for col, val in filters.items():
            if val:
                data = [r for r in data if str(r.get(col, "")).lower() == val.lower()]
    # Sort — coerce numeric strings (e.g. "50.25", ms timestamps) to float
    reverse = sort_dir.upper() == "DESC"
    def _key(r):
        v = r.get(sort_key, "")
        try:
            return (0, float(v))
        except (ValueError, TypeError):
            return (1, str(v).lower() if v is not None else "")
    try:
        data = sorted(data, key=_key, reverse=reverse)
    except TypeError:
        pass
    total = len(data)
    offset = (max(page, 1) - 1) * per_page
    return data[offset:offset + per_page], total


def _table_ctx(request, **kw):
    """Minimal context for table fragments — no need for full _ctx."""
    return {**kw}


@router.get("/fragments/history/exchange", response_class=HTMLResponse)
async def frag_history_exchange(
    request: Request,
    page: int = 1, per_page: int = 20,
    sort_by: str = "time", sort_dir: str = "DESC",
    search: str = "", date_from: str = "", date_to: str = "",
):
    from core.database import db as _db
    rows, total = await _db.query_exchange_history(
        page=page, per_page=per_page,
        sort_by=sort_by, sort_dir=sort_dir,
        search=search, date_from=date_from, date_to=date_to,
        tz_local=TZ_LOCAL,
        account_id=app_state.active_account_id,
    )
    total_pages = max(1, (total + per_page - 1) // per_page)
    notes_map = await _db.get_position_notes([r["trade_key"] for r in rows])
    return templates.TemplateResponse(
        request, "fragments/history/exchange_table.html",
        _table_ctx(request, rows=rows, total=total, page=page,
                   per_page=per_page, total_pages=total_pages,
                   sort_by=sort_by, sort_dir=sort_dir, search=search,
                   date_from=date_from, date_to=date_to, notes_map=notes_map),
    )


@router.get("/fragments/history/pre_trade", response_class=HTMLResponse)
async def frag_history_pre_trade(
    request: Request,
    page: int = 1, per_page: int = 20,
    sort_by: str = "timestamp", sort_dir: str = "DESC",
    search: str = "", ticker: str = "", side: str = "",
    date_from: str = "", date_to: str = "",
):
    from core.database import db
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


@router.get("/fragments/history/execution", response_class=HTMLResponse)
async def frag_history_execution(
    request: Request,
    page: int = 1, per_page: int = 20,
    sort_by: str = "entry_timestamp", sort_dir: str = "DESC",
    search: str = "", ticker: str = "", side: str = "",
    date_from: str = "", date_to: str = "",
):
    from core.database import db
    rows, total = await db.query_execution_log(
        date_from=date_from or None, date_to=date_to or None,
        search=search or None, ticker=ticker or None, side=side or None,
        sort_by=sort_by, sort_dir=sort_dir, page=page, per_page=per_page,
        account_id=app_state.active_account_id,
    )
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(
        request, "fragments/history/execution_table.html",
        _table_ctx(request, rows=rows, total=total, page=page,
                   per_page=per_page, total_pages=total_pages,
                   sort_by=sort_by, sort_dir=sort_dir, search=search,
                   ticker=ticker, side=side,
                   date_from=date_from, date_to=date_to),
    )


@router.get("/fragments/history/live_trades", response_class=HTMLResponse)
async def frag_history_live_trades(
    request: Request,
    page: int = 1, per_page: int = 20,
    sort_by: str = "entry_timestamp", sort_dir: str = "DESC",
    search: str = "", date_from: str = "", date_to: str = "",
):
    data = load_recent_history(config.LIVE_TRADES)
    # Date filter
    if date_from:
        data = [r for r in data if str(r.get("entry_timestamp", "")) >= date_from]
    if date_to:
        data = [r for r in data if str(r.get("entry_timestamp", "")) <= date_to]
    rows, total = _paginate_list(
        data, page, per_page, sort_by, sort_dir,
        search=search, search_fields=("ticker",),
    )
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(
        request, "fragments/history/live_trades_table.html",
        _table_ctx(request, rows=rows, total=total, page=page,
                   per_page=per_page, total_pages=total_pages,
                   sort_by=sort_by, sort_dir=sort_dir, search=search,
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
    from core.database import db
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


# ── Note updates ─────────────────────────────────────────────────────────

@router.put("/history/notes/pre_trade/{row_id}", response_class=HTMLResponse)
async def update_pre_trade_note(row_id: int, notes: str = Form("")):
    from core.database import db
    await db.update_pre_trade_notes(row_id, notes)
    from markupsafe import escape
    safe = escape(notes)
    return HTMLResponse(
        f'<span class="text-slate-400 cursor-pointer" '
        f'onclick="editNote(this,{row_id},\'pre_trade\')" '
        f'title="Click to edit">{safe or "+ Add note"}</span>'
    )


@router.put("/history/notes/trade_history/{row_id}", response_class=HTMLResponse)
async def update_trade_history_note(row_id: int, notes: str = Form("")):
    from core.database import db
    await db.update_trade_history_notes(row_id, notes)
    from markupsafe import escape
    safe = escape(notes)
    return HTMLResponse(
        f'<span class="text-slate-400 cursor-pointer" '
        f'onclick="editNote(this,{row_id},\'trade_history\')" '
        f'title="Click to edit">{safe or "+ Add note"}</span>'
    )


@router.put("/history/notes/position", response_class=HTMLResponse)
async def update_position_note(trade_key: str = Form(""), notes: str = Form("")):
    from core.database import db
    await db.upsert_position_note(trade_key, notes)
    from markupsafe import escape
    safe_notes = escape(notes)
    safe_key   = escape(trade_key)
    return HTMLResponse(
        f'<span class="text-slate-400 cursor-pointer" '
        f'onclick="editNote(this,\'{safe_key}\',\'position\')" '
        f'title="Click to edit">{safe_notes or "+ Add note"}</span>'
    )


# ── Params ────────────────────────────────────────────────────────────────────

@router.post("/params/update", response_class=HTMLResponse)
async def update_params(
    request:                   Request,
    individual_risk_per_trade: float = Form(...),
    max_w_loss_percent:        float = Form(...),
    max_dd_percent:            float = Form(...),
    max_exposure:              float = Form(...),
    max_position_count:        int   = Form(...),
    max_correlated_exposure:   float = Form(...),
    auto_export_hours:         int   = Form(24),
    weekly_loss_warning_pct:   float = Form(0.80),
    weekly_loss_limit_pct:     float = Form(0.95),
    max_dd_warning_pct:        float = Form(0.80),
    max_dd_limit_pct:          float = Form(0.95),
):
    app_state.params.update({
        "individual_risk_per_trade": individual_risk_per_trade,
        "max_w_loss_percent":        max_w_loss_percent,
        "max_dd_percent":            max_dd_percent,
        "max_exposure":              max_exposure,
        "max_position_count":        max_position_count,
        "max_correlated_exposure":   max_correlated_exposure,
        "auto_export_hours":         auto_export_hours,
        "weekly_loss_warning_pct":   weekly_loss_warning_pct,
        "weekly_loss_limit_pct":     weekly_loss_limit_pct,
        "max_dd_warning_pct":        max_dd_warning_pct,
        "max_dd_limit_pct":          max_dd_limit_pct,
    })
    await app_state.save_params_async()
    from core.event_bus import event_bus
    await event_bus.publish(
        "risk:params_updated",
        {"ts": datetime.now(TZ_LOCAL).isoformat()},
    )
    return HTMLResponse('<div class="alert-success p-2 rounded">Parameters saved.</div>')


# ── Export ────────────────────────────────────────────────────────────────────

@router.get("/export")
async def manual_export():
    from core.data_logger import export_all_to_excel
    path = await export_all_to_excel()
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=os.path.basename(path),
    )


# ── JSON API ──────────────────────────────────────────────────────────────────

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
        # No cached data yet — fetch orderbook via REST and register WS stream
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


# ══════════════════════════════════════════════════════════════════════════════
# ANALYTICS PAGE
# ══════════════════════════════════════════════════════════════════════════════

def _analytics_range(month: str = "", all: str = "") -> tuple:
    """
    Return (from_ms, to_ms, period_label, current_month_str).
    'month' = "YYYY-MM", 'all' = "1" for all-time, else current month.
    """
    import calendar as _cal
    now = datetime.now(TZ_LOCAL)

    if all == "1":
        from_ms = 0
        to_ms   = int(now.timestamp() * 1000)
        label   = "All Time"
        month_s = "All Time"
    elif month:
        try:
            y, m = int(month[:4]), int(month[5:7])
        except (ValueError, IndexError):
            y, m = now.year, now.month
        start = datetime(y, m, 1, tzinfo=TZ_LOCAL)
        _, ndays = _cal.monthrange(y, m)
        end = datetime(y, m, ndays, 23, 59, 59, tzinfo=TZ_LOCAL)
        from_ms = int(start.timestamp() * 1000)
        to_ms   = int(end.timestamp() * 1000)
        label   = start.strftime("%B %Y")
        month_s = f"{y:04d}-{m:02d}"
    else:
        y, m = now.year, now.month
        start = datetime(y, m, 1, tzinfo=TZ_LOCAL)
        from_ms = int(start.timestamp() * 1000)
        to_ms   = int(now.timestamp() * 1000)
        label   = start.strftime("%B %Y")
        month_s = f"{y:04d}-{m:02d}"

    return from_ms, to_ms, label, month_s


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request):
    now = datetime.now(TZ_LOCAL)
    current_month = f"{now.year:04d}-{now.month:02d}"
    return templates.TemplateResponse(
        request,
        "analytics.html",
        _ctx(request, active_page="analytics", current_month=current_month),
    )


@router.get("/fragments/analytics/overview", response_class=HTMLResponse)
async def frag_analytics_overview(
    request: Request,
    month: str = "",
    all:   str = "",
):
    from core.database import db
    from core import analytics as an

    from_ms, to_ms, period_label, month_s = _analytics_range(month, all)
    aid = app_state.active_account_id

    stats, boundaries, top_pairs, cumulative, equity_series = await asyncio.gather(
        db.get_journal_stats(from_ms, to_ms, account_id=aid),
        db.get_equity_period_boundaries(from_ms, to_ms, account_id=aid),
        db.get_most_traded_pairs(from_ms, to_ms, limit=5, account_id=aid),
        db.get_cumulative_pnl(account_id=aid),
        db.get_daily_equity_series(from_ms, to_ms, account_id=aid),
        return_exceptions=True,
    )
    # Guard: replace exceptions with safe defaults
    if isinstance(stats, Exception):         stats = {}
    if isinstance(boundaries, Exception):    boundaries = {"initial_equity": 0.0, "final_equity": 0.0, "max_drawdown": 0.0}
    if isinstance(top_pairs, Exception):     top_pairs = []
    if isinstance(cumulative, Exception):    cumulative = {"total_pnl": 0.0, "total_deposits": 0.0, "total_withdrawals": 0.0}
    if isinstance(equity_series, Exception): equity_series = []

    # Compute trading days
    trading_days = len(equity_series)

    # Daily returns for ratios
    equity_vals = [r["total_equity"] for r in equity_series if r.get("total_equity")]
    returns     = an.daily_returns(equity_vals)

    # MFE/MAE trades for excursion ratios
    mfe_mae_trades = await db.get_mfe_mae_series(from_ms, to_ms, account_id=aid)
    r_vals         = await db.get_r_multiples(from_ms, to_ms, account_id=aid)
    r_stats        = an.r_multiple_stats(r_vals)

    ratios = {
        "sharpe":       round(an.sharpe(returns),            2),
        "sortino":      round(an.sortino(returns),           2),
        "sharpe_mfe":   round(an.sharpe_mfe(mfe_mae_trades), 2),
        "sortino_mae":  round(an.sortino_mae(mfe_mae_trades), 2),
        "profit_factor": round(r_stats.get("profit_factor", 0.0), 2),
        "expectancy":   round(r_stats.get("expectancy", 0.0), 3),
    }

    return templates.TemplateResponse(
        request,
        "fragments/analytics/overview_stats.html",
        _ctx(
            request,
            stats=stats,
            boundaries=boundaries,
            top_pairs=top_pairs,
            cumulative=cumulative,
            ratios=ratios,
            trading_days=trading_days,
            period_label=period_label,
            month=month_s,
        ),
    )


@router.get("/fragments/analytics/equity_curve", response_class=HTMLResponse)
async def frag_analytics_equity(
    request: Request,
    tf:  str = "1M",
    log: str = "",
    dd:  str = "",
):
    from core.database import db

    now = datetime.now(TZ_LOCAL)

    # Map analytics TF → (ohlc_tf_minutes, candle_limit, approx_days_for_backfill)
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

    return templates.TemplateResponse(
        request,
        "fragments/analytics/equity_curve.html",
        _ctx(
            request,
            candles=candles,
            active_tf=tf,
            log_scale=bool(log),
            show_dd=bool(dd),
            period_label=period_label,
        ),
    )


@router.get("/fragments/analytics/calendar", response_class=HTMLResponse)
async def frag_analytics_calendar(
    request: Request,
    month: str = "",
    all:   str = "",
):
    from core.database import db
    from core.analytics import build_calendar_grid
    import calendar as _cal

    now = datetime.now(TZ_LOCAL)
    if month:
        try:
            y, m = int(month[:4]), int(month[5:7])
        except (ValueError, IndexError):
            y, m = now.year, now.month
    else:
        y, m = now.year, now.month

    # Prev / next months
    prev_d = datetime(y, m, 1, tzinfo=TZ_LOCAL) - timedelta(days=1)
    next_d = datetime(y, m, _cal.monthrange(y, m)[1], tzinfo=TZ_LOCAL) + timedelta(days=1)
    prev_month = f"{prev_d.year:04d}-{prev_d.month:02d}"
    next_month = f"{next_d.year:04d}-{next_d.month:02d}"

    _, ndays = _cal.monthrange(y, m)
    start = datetime(y, m, 1, tzinfo=TZ_LOCAL)
    end   = datetime(y, m, ndays, 23, 59, 59, tzinfo=TZ_LOCAL)
    from_ms = int(start.timestamp() * 1000)
    to_ms   = int(end.timestamp() * 1000)

    aid = app_state.active_account_id
    series = await db.get_daily_equity_series(from_ms, to_ms, account_id=aid)
    daily_pnl = {r["day"]: r["daily_pnl"] for r in series if r.get("daily_pnl") is not None}
    daily_stats = await db.get_daily_trade_stats(from_ms, to_ms, account_id=aid)
    calendar_grid = build_calendar_grid(y, m, daily_pnl, daily_stats)

    pnl_vals   = [v for v in daily_pnl.values() if v is not None]
    trading_days = len(pnl_vals)
    avg_daily  = sum(pnl_vals) / trading_days if trading_days else 0.0
    best_day   = max(pnl_vals) if pnl_vals else 0.0
    worst_day  = min(pnl_vals) if pnl_vals else 0.0
    max_abs_pnl = max(abs(v) for v in pnl_vals) if pnl_vals else 1.0

    return templates.TemplateResponse(
        request,
        "fragments/analytics/calendar_pnl.html",
        _ctx(
            request,
            calendar_grid=calendar_grid,
            month_label=start.strftime("%B %Y"),
            prev_month=prev_month,
            next_month=next_month,
            daily_pnl=daily_pnl,
            trading_days=trading_days,
            avg_daily=avg_daily,
            best_day=best_day,
            worst_day=worst_day,
            max_abs_pnl=max_abs_pnl if max_abs_pnl > 0 else 1.0,
        ),
    )


@router.get("/fragments/analytics/pairs", response_class=HTMLResponse)
async def frag_analytics_pairs(
    request: Request,
    month:    str = "",
    all:      str = "",
    sort_by:  str = "total",
    sort_dir: str = "DESC",
):
    from core.database import db

    from_ms, to_ms, period_label, month_s = _analytics_range(month, all)
    rows = await db.get_traded_pairs_stats(from_ms, to_ms, account_id=app_state.active_account_id)

    _allowed = {"symbol","total","longs","shorts","pnl_long","pnl_short",
                "pnl_total","win_rate","avg_win","avg_loss","fees_total","volume"}
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
    month:  str = "",
    all:    str = "",
    dir:    str = "all",
):
    from core.database import db

    from_ms, to_ms, period_label, month_s = _analytics_range(month, all)
    trades = await db.get_mfe_mae_series(from_ms, to_ms, account_id=app_state.active_account_id)

    if dir in ("LONG", "SHORT"):
        trades = [t for t in trades if t.get("direction") == dir]

    # Stats
    mfe_vals   = [t["mfe"]        for t in trades if t.get("mfe")]
    mae_vals   = [abs(t["mae"])   for t in trades if t.get("mae")]
    avg_mfe    = sum(mfe_vals) / len(mfe_vals) if mfe_vals else 0.0
    avg_mae_abs = sum(mae_vals) / len(mae_vals) if mae_vals else 0.0
    mer_vals   = [t["mfe"] / abs(t["mae"]) for t in trades if t.get("mae") and t["mae"] != 0]
    avg_mer    = sum(mer_vals) / len(mer_vals) if mer_vals else 0.0
    fav_count  = sum(1 for t in trades if t.get("mae") and t["mae"] != 0 and t["mfe"] / abs(t["mae"]) > 2)
    pct_fav    = round(fav_count / len(trades) * 100, 1) if trades else 0.0

    scatter_data = [
        {"x": t["mfe"], "y": t["mae"], "z": t["income"], "sym": t["symbol"]}
        for t in trades
    ]

    return templates.TemplateResponse(
        request,
        "fragments/analytics/excursions.html",
        _ctx(
            request,
            trades=trades[:200],   # cap table rows
            scatter_data=scatter_data,
            avg_mfe=round(avg_mfe, 2),
            avg_mae_abs=round(avg_mae_abs, 2),
            avg_mer=round(avg_mer, 2),
            pct_favorable=pct_fav,
            period_label=period_label,
            filter_dir=dir,
            month=month_s,
        ),
    )


@router.get("/fragments/analytics/r_multiples", response_class=HTMLResponse)
async def frag_analytics_r_multiples(
    request: Request,
    month: str = "",
    all:   str = "",
):
    from core.database import db
    from core.analytics import r_multiple_stats, r_multiple_histogram

    from_ms, to_ms, period_label, month_s = _analytics_range(month, all)
    r_values   = await db.get_r_multiples(from_ms, to_ms, account_id=app_state.active_account_id)
    r_stats    = r_multiple_stats(r_values)
    histogram  = r_multiple_histogram(r_values)

    return templates.TemplateResponse(
        request,
        "fragments/analytics/r_multiples.html",
        _ctx(request, r_values=r_values, r_stats=r_stats,
             histogram=histogram, period_label=period_label, month=month_s),
    )


@router.get("/fragments/analytics/var", response_class=HTMLResponse)
async def frag_analytics_var(
    request: Request,
    month: str = "",
    all:   str = "",
):
    from core.database import db
    from core import analytics as an

    from_ms, to_ms, period_label, month_s = _analytics_range(month, all)
    series  = await db.get_daily_equity_series(from_ms, to_ms, account_id=app_state.active_account_id)
    equities = [r["total_equity"] for r in series if r.get("total_equity")]
    returns  = an.daily_returns(equities)
    cur_equity = app_state.account_state.total_equity or 1.0

    var95  = an.historical_var(returns, 0.95)
    var99  = an.historical_var(returns, 0.99)
    cvar95 = an.conditional_var(returns, 0.95)
    pvar95 = an.parametric_var(returns, 0.95)

    # Daily return histogram buckets for chart
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
        _ctx(
            request,
            var95=var95,   var99=var99,
            cvar95=cvar95, pvar95=pvar95,
            cur_equity=cur_equity,
            returns=returns,
            hist_data=hist_data,
            period_label=period_label,
            month=month_s,
            has_data=len(returns) >= 20,
        ),
    )


@router.get("/fragments/analytics/funding", response_class=HTMLResponse)
async def frag_analytics_funding(request: Request):
    positions = app_state.positions
    rows: List[Dict[str, Any]] = []

    if positions:
        symbols = [p.ticker for p in positions]
        try:
            from core.exchange import fetch_funding_rates
            funding_data = await fetch_funding_rates(symbols)
        except Exception:
            funding_data = {}

        from core.analytics import compute_funding_exposure
        from datetime import timezone as _tz

        for p in positions:
            fd = funding_data.get(p.ticker, {})
            rate = fd.get("funding_rate", 0.0)
            nft  = fd.get("next_funding_time", 0)
            notional = abs(p.position_value_usdt)
            exp = compute_funding_exposure(notional, rate)

            # Is rate favourable (trader earns) or adverse?
            # LONG pays when rate > 0, earns when rate < 0; SHORT is inverse
            if p.direction == "LONG":
                adverse = rate > 0
            else:
                adverse = rate < 0

            # Format next funding time
            if nft > 0:
                nft_dt = datetime.fromtimestamp(nft / 1000, tz=_tz.utc).astimezone(TZ_LOCAL)
                nft_str = nft_dt.strftime("%H:%M:%S")
            else:
                nft_str = "—"

            rows.append({
                "ticker":        p.ticker,
                "direction":     p.direction,
                "notional":      notional,
                "funding_rate":  rate,
                "per_8h":        exp["per_8h"],
                "per_day":       exp["per_day"],
                "per_week":      exp["per_week"],
                "next_funding":  nft_str,
                "adverse":       adverse,
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
    from core.analytics import compute_beta, daily_returns

    positions = app_state.positions

    # BTC daily returns from OHLCV cache
    btc_ohlcv = app_state.ohlcv_cache.get("BTCUSDT", [])
    btc_closes = [float(c[4]) for c in btc_ohlcv[-31:] if len(c) >= 5]
    btc_returns = daily_returns(btc_closes)

    # Sector preset betas (fallback when OHLCV unavailable)
    SECTOR_BETA = {"big_two_crypto": 1.0, "top_twenty_alts": 1.5,
                   "commodities": 0.4, "other_alts": 2.0}

    rows: List[Dict[str, Any]] = []
    for p in positions:
        pos_ohlcv  = app_state.ohlcv_cache.get(p.ticker, [])
        pos_closes = [float(c[4]) for c in pos_ohlcv[-31:] if len(c) >= 5]
        pos_returns = daily_returns(pos_closes)

        if len(pos_returns) >= 10 and len(btc_returns) >= 10:
            beta = round(compute_beta(pos_returns, btc_returns), 2)
        else:
            beta = SECTOR_BETA.get(p.sector, 1.5)

        notional = abs(p.position_value_usdt)
        rows.append({
            "ticker":       p.ticker,
            "direction":    p.direction,
            "sector":       p.sector or "—",
            "notional":     notional,
            "beta":         beta,
            "beta_adj_exp": round(notional * beta, 2),
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


# ── Account management ────────────────────────────────────────────────────────

_switch_lock = asyncio.Lock()


@router.get("/accounts", response_class=JSONResponse)
async def list_accounts(request: Request):
    """Return all accounts (no secrets)."""
    from core.account_registry import account_registry
    return JSONResponse(await account_registry.list_accounts())


@router.post("/accounts", response_class=JSONResponse)
async def create_account(
    request: Request,
    name: str = Form(...),
    exchange: str = Form("binance"),
    market_type: str = Form("future"),
    api_key: str = Form(...),
    api_secret: str = Form(...),
):
    from core.account_registry import account_registry
    try:
        new_id = await account_registry.add_account(name, exchange, market_type, api_key, api_secret)
        return JSONResponse({"status": "ok", "id": new_id, "name": name})
    except Exception as exc:
        log.error("create_account failed: %r", exc)
        return JSONResponse({"status": "error", "error": str(exc)}, status_code=500)


@router.put("/accounts/{account_id}", response_class=JSONResponse)
async def update_account(
    account_id: int,
    request: Request,
    name: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    api_secret: Optional[str] = Form(None),
):
    from core.account_registry import account_registry
    await account_registry.update_account(account_id, name=name, api_key=api_key, api_secret=api_secret)
    return JSONResponse({"status": "ok"})


@router.delete("/accounts/{account_id}", response_class=HTMLResponse)
async def delete_account(account_id: int, request: Request):
    if account_id == app_state.active_account_id:
        # Return 409 so HTMX does not swap content — table stays intact
        return HTMLResponse(
            "Cannot delete the active account. Switch to another account first.",
            status_code=409,
        )
    from core.account_registry import account_registry
    await account_registry.delete_account(account_id)
    from core.exchange_factory import exchange_factory
    exchange_factory.invalidate(account_id)
    accounts = await account_registry.list_accounts()
    return templates.TemplateResponse(
        request, "fragments/accounts.html",
        _ctx(request, accounts=accounts),
    )


@router.post("/accounts/{account_id}/test", response_class=JSONResponse)
async def test_account_connection(account_id: int, request: Request):
    from core.account_registry import account_registry
    result = await account_registry.test_connection(account_id)
    return JSONResponse(result)


@router.post("/accounts/{account_id}/activate", response_class=JSONResponse)
async def activate_account(account_id: int, request: Request):
    """Switch active account — full teardown/reinit flow."""
    from core.account_registry import account_registry
    from core.exchange_factory import exchange_factory
    from core.exchange import (
        fetch_exchange_info, fetch_account, fetch_positions,
        fetch_ohlcv, create_listen_key, fetch_bod_sow_equity,
        fetch_exchange_trade_history,
    )
    from core import ws_manager
    from core.database import db

    if account_id == app_state.active_account_id:
        return JSONResponse({"status": "ok", "account_id": account_id, "message": "already active"})

    accounts = await account_registry.list_accounts()
    if not any(a["id"] == account_id for a in accounts):
        return JSONResponse({"status": "error", "error": "Account not found"}, status_code=404)

    if _switch_lock.locked():
        return JSONResponse({"status": "error", "error": "Account switch already in progress"}, status_code=409)

    async with _switch_lock:
        old_account_id = app_state.active_account_id
        log.info("Account switch: %d → %d", old_account_id, account_id)

        # 1. Freeze UI with startup overlay
        app_state.is_initializing = True

        # 2. Stop WS streams
        await ws_manager.stop()

        # 3. Clear runtime state
        app_state.reset_for_account_switch()
        exchange_factory.invalidate(old_account_id)
        # Reset backfill cache for old account so it re-validates on next visit
        _backfill_earliest_ms.pop(old_account_id, None)

        # 4. Activate new account
        await account_registry.set_active(account_id)
        app_state.active_account_id = account_id

        # 5. Restore last known equity for new account (crash recovery)
        last_snap = await db.get_last_account_state(account_id=account_id)
        if last_snap:
            acc = app_state.account_state
            acc.total_equity     = last_snap.get("total_equity", 0.0)
            acc.bod_equity       = last_snap.get("bod_equity", 0.0)
            acc.sow_equity       = last_snap.get("sow_equity", 0.0)
            acc.max_total_equity = last_snap.get("max_total_equity", 0.0)

        # 6. Re-init exchange + WS in background (unblocks the HTTP response quickly)
        async def _reinit():
            try:
                await fetch_exchange_info()
                await fetch_account()
                await fetch_positions()
                await fetch_bod_sow_equity()
                await fetch_exchange_trade_history()
                for pos in app_state.positions:
                    try:
                        await fetch_ohlcv(pos.ticker)
                    except Exception:
                        pass
                app_state.recalculate_portfolio()
                listen_key = await create_listen_key()
                await ws_manager.start(listen_key)
            except Exception as exc:
                log.error("Account switch reinit failed: %r", exc)
                app_state.ws_status.add_log(f"SWITCH ERROR: {exc}")
            finally:
                app_state.is_initializing = False
                app_state.ws_status.add_log(f"Switched to account {account_id}.")

        asyncio.create_task(_reinit())

    acct_info = next((a for a in accounts if a["id"] == account_id), {})
    return JSONResponse({
        "status":     "ok",
        "account_id": account_id,
        "name":       acct_info.get("name", ""),
    })


@router.post("/accounts/activate-selected", response_class=HTMLResponse)
async def activate_selected_account(request: Request, account_id: int = Form(...)):
    """HTMX-friendly wrapper for the account dropdown select change."""
    result = await activate_account(account_id, request)
    import json as _json
    data = _json.loads(result.body)
    if data.get("status") == "ok":
        return HTMLResponse('<span class="text-green-400 text-xs">Switched</span>')
    return HTMLResponse(f'<span class="text-red-400 text-xs">{data.get("error","Error")}</span>')


@router.post("/accounts/{account_id}/activate-frag", response_class=HTMLResponse)
async def activate_account_frag(account_id: int, request: Request):
    """HTMX-friendly activate that returns the refreshed accounts fragment."""
    await activate_account(account_id, request)
    from core.account_registry import account_registry
    accounts = await account_registry.list_accounts()
    return templates.TemplateResponse(
        request, "fragments/accounts.html",
        _ctx(request, accounts=accounts),
    )


@router.post("/accounts/add-and-reload", response_class=HTMLResponse)
async def add_account_modal(
    request: Request,
    name: str = Form(...),
    exchange: str = Form("binance"),
    market_type: str = Form("future"),
    api_key: str = Form(...),
    api_secret: str = Form(...),
):
    """Create account from modal form and return a status fragment with HX-Trigger."""
    from core.account_registry import account_registry
    from fastapi.responses import HTMLResponse as _HR
    try:
        new_id = await account_registry.add_account(name, exchange, market_type, api_key, api_secret)
        response = _HR(
            f'<span class="text-green-400 text-xs">Account "{name}" added (id={new_id}). Reloading...</span>'
            '<script>setTimeout(function(){window.location.reload();},800);</script>'
        )
        return response
    except Exception as exc:
        return _HR(f'<span class="text-red-400 text-xs">Error: {exc}</span>')


@router.post("/accounts/test-preview", response_class=HTMLResponse)
async def test_account_preview(
    request: Request,
    api_key: str = Form(...),
    api_secret: str = Form(...),
    exchange: str = Form("binance"),
    market_type: str = Form("future"),
):
    """Test API credentials from the add-account modal without saving."""
    from core.exchange_factory import exchange_factory as _ef, _make_ccxt_instance
    import asyncio as _asyncio
    import concurrent.futures as _cf
    import time as _t

    try:
        ex = _make_ccxt_instance(api_key, api_secret, exchange, market_type)
        loop = _asyncio.get_event_loop()
        with _cf.ThreadPoolExecutor(max_workers=1) as pool:
            t0 = _t.monotonic()
            await loop.run_in_executor(pool, ex.fetch_time)
            latency = round((_t.monotonic() - t0) * 1000, 1)
        return HTMLResponse(f'<span class="text-green-400 text-xs">Connection OK — {latency}ms</span>')
    except Exception as exc:
        return HTMLResponse(f'<span class="text-red-400 text-xs">Failed: {exc}</span>')


# ── Platform settings ─────────────────────────────────────────────────────────

@router.get("/api/settings/platform", response_class=JSONResponse)
async def get_platform(request: Request):
    return JSONResponse({"platform": app_state.active_platform})


@router.post("/api/settings/platform", response_class=JSONResponse)
async def set_platform(request: Request, platform: str = Form(...)):
    if platform not in ("standalone", "quantower"):
        return JSONResponse({"status": "error", "error": "Unknown platform"}, status_code=400)
    from core.database import db
    app_state.active_platform = platform
    await db.set_setting("active_platform", platform)
    return JSONResponse({"status": "ok", "platform": platform})


# ── Accounts fragment (HTMX) ──────────────────────────────────────────────────

@router.get("/fragments/accounts", response_class=HTMLResponse)
async def frag_accounts(request: Request):
    from core.account_registry import account_registry
    accounts = await account_registry.list_accounts()
    return templates.TemplateResponse(
        request, "fragments/accounts.html",
        _ctx(request, accounts=accounts),
    )


# ── Quantower platform bridge ─────────────────────────────────────────────────

@router.get("/api/platform/state", response_class=JSONResponse)
async def platform_state(request: Request):
    """JSON risk state snapshot for external consumers (Quantower plugin)."""
    from core.platform_bridge import platform_bridge
    return JSONResponse(platform_bridge.get_state_json())


@router.post("/api/platform/event", response_class=JSONResponse)
async def platform_event(request: Request):
    """REST fallback: Quantower plugin POSTs fill events here."""
    from core.platform_bridge import platform_bridge
    try:
        body = await request.json()
        await platform_bridge._dispatch(body)
        return JSONResponse({"status": "ok"})
    except Exception as exc:
        return JSONResponse({"status": "error", "error": str(exc)}, status_code=400)


@router.post("/api/platform/positions", response_class=JSONResponse)
async def platform_positions(request: Request):
    """REST fallback: Quantower plugin pushes position snapshot here."""
    from core.platform_bridge import platform_bridge
    try:
        body = await request.json()
        await platform_bridge._handle_position_snapshot(body)
        return JSONResponse({"status": "ok"})
    except Exception as exc:
        return JSONResponse({"status": "error", "error": str(exc)}, status_code=400)


from fastapi import WebSocket, WebSocketDisconnect


@router.websocket("/ws/platform")
async def ws_platform(websocket: WebSocket):
    """Persistent WebSocket for the Quantower plugin."""
    from core.platform_bridge import platform_bridge
    await platform_bridge.handle_ws(websocket)


# ── Backtesting ───────────────────────────────────────────────────────────────

# In-memory map of running backtest tasks: {session_id: asyncio.Task}
_backtest_tasks: Dict[int, asyncio.Task] = {}

# In-memory map of running OHLCV fetch jobs: {job_id: {task, status, detail, symbols}}
_fetch_jobs: Dict[int, Dict[str, Any]] = {}
_fetch_job_counter = 0


@router.get("/backtest", response_class=HTMLResponse)
async def backtest_page(request: Request):
    return templates.TemplateResponse(
        request, "backtest.html", _ctx(request, active_page="backtest")
    )


@router.get("/fragments/backtest/sessions", response_class=HTMLResponse)
async def frag_backtest_sessions(request: Request):
    from core.database import db
    sessions = await db.list_backtest_sessions(limit=30)
    return templates.TemplateResponse(
        request, "fragments/backtest/sessions_list.html",
        _ctx(request, sessions=sessions),
    )


@router.get("/fragments/backtest/results/{session_id}", response_class=HTMLResponse)
async def frag_backtest_results(request: Request, session_id: int):
    from core.database import db
    session = await db.get_backtest_session(session_id)
    if not session:
        return HTMLResponse("<p class='text-red-400'>Session not found.</p>", status_code=404)
    trades  = await db.get_backtest_trades(session_id)
    equity  = await db.get_backtest_equity(session_id)
    return templates.TemplateResponse(
        request, "fragments/backtest/results.html",
        _ctx(request, session=session, trades=trades, equity=equity),
    )


@router.post("/api/backtest/fetch-ohlcv", response_class=JSONResponse)
async def api_fetch_ohlcv(request: Request):
    """
    Trigger background OHLCV ingestion for a list of symbols.
    Body: {"symbols": ["BTCUSDT", ...], "timeframe": "4h", "days": 365}
    Returns {job_id} for polling via GET /api/backtest/fetch-status/{job_id}.
    """
    global _fetch_job_counter
    from core.ohlcv_fetcher import OHLCVFetcher

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    symbols   = body.get("symbols", [])
    timeframe = body.get("timeframe", "4h")
    days      = int(body.get("days", 365))

    if not symbols:
        return JSONResponse({"error": "No symbols provided"}, status_code=400)

    _fetch_job_counter += 1
    job_id = _fetch_job_counter
    job: Dict[str, Any] = {
        "status": "running",
        "symbols": symbols,
        "timeframe": timeframe,
        "days": days,
        "detail": f"Starting fetch for {len(symbols)} symbol(s)…",
        "results": {},
    }
    _fetch_jobs[job_id] = job

    async def _run():
        fetcher = OHLCVFetcher()
        try:
            for i, sym in enumerate(symbols):
                job["detail"] = f"Fetching {sym} ({i + 1}/{len(symbols)})…"
                count = await fetcher.fetch_and_store(sym, timeframe, days)
                job["results"][sym] = count
            job["status"] = "completed"
            total = sum(job["results"].values())
            job["detail"] = f"Done — {total} candles across {len(symbols)} symbol(s)"
        except Exception as exc:
            job["status"] = "failed"
            job["detail"] = str(exc)
        finally:
            await fetcher.close()

    asyncio.create_task(_run())
    return JSONResponse({"status": "started", "job_id": job_id, "symbols": symbols, "timeframe": timeframe, "days": days})


@router.get("/api/backtest/fetch-status/{job_id}", response_class=JSONResponse)
async def api_fetch_status(job_id: int):
    """Poll the status of an OHLCV fetch job."""
    job = _fetch_jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return JSONResponse({
        "job_id": job_id,
        "status": job["status"],
        "detail": job["detail"],
        "results": job["results"],
    })


@router.post("/api/backtest/run", response_class=JSONResponse)
async def api_backtest_run(request: Request):
    """
    Start a backtest session.
    Body: strategy config dict (see backtest_runner.py docstring).
    Returns {session_id} immediately; run executes in background.
    """
    from core.database import db
    from core.backtest_runner import BacktestRunner

    try:
        cfg = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    name      = cfg.get("name", f"Backtest {datetime.now(TZ_LOCAL).strftime('%Y-%m-%d %H:%M')}")
    date_from = cfg.get("date_from", "")
    date_to   = cfg.get("date_to", "")

    session_id = await db.create_backtest_session(
        name=name,
        session_type="macro",
        date_from=date_from,
        date_to=date_to,
        config=cfg,
    )

    async def _run_backtest():
        runner = BacktestRunner(cfg)
        try:
            await runner.run(session_id)
        except Exception as exc:
            log.error("Backtest session %d failed: %s", session_id, exc)
            await db.finish_backtest_session(session_id, "failed", {"error": str(exc)})
        finally:
            _backtest_tasks.pop(session_id, None)

    task = asyncio.create_task(_run_backtest())
    _backtest_tasks[session_id] = task

    return JSONResponse({"session_id": session_id, "status": "running"})


@router.get("/api/backtest/sessions", response_class=JSONResponse)
async def api_backtest_sessions():
    from core.database import db
    sessions = await db.list_backtest_sessions(limit=50)
    # Strip large json blobs for the list view
    for s in sessions:
        s.pop("config_json", None)
    return JSONResponse(sessions)


@router.get("/api/backtest/sessions/{session_id}", response_class=JSONResponse)
async def api_backtest_session_detail(session_id: int):
    from core.database import db
    session = await db.get_backtest_session(session_id)
    if not session:
        return JSONResponse({"error": "Not found"}, status_code=404)
    trades = await db.get_backtest_trades(session_id)
    equity = await db.get_backtest_equity(session_id)
    session.pop("config_json", None)
    return JSONResponse({"session": session, "trades": trades, "equity": equity})


@router.delete("/api/backtest/sessions/{session_id}", response_class=JSONResponse)
async def api_backtest_session_delete(session_id: int):
    from core.database import db
    task = _backtest_tasks.get(session_id)
    if task and not task.done():
        task.cancel()
        _backtest_tasks.pop(session_id, None)
    await db.delete_backtest_session(session_id)
    return JSONResponse({"status": "deleted"})


@router.post("/api/backtest/qt-import", response_class=JSONResponse)
async def api_qt_import(request: Request):
    """
    Import Quantower microstructure backtest results.

    Expects JSON body:
    {
      "session_name": str,
      "strategy":     str,
      "date_from":    "YYYY-MM-DD",
      "date_to":      "YYYY-MM-DD",
      "trades": [
        {"symbol": str, "entry_dt": str, "exit_dt": str,
         "pnl_r": float, "slippage_bps": float, "exec_quality": float,
         "side": str, "entry_price": float, "exit_price": float, "size_usdt": float}
      ],
      "summary": {"total_r": float, "win_rate": float, "avg_slippage_bps": float}
    }
    """
    from core.database import db

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    session_name = body.get("session_name", "Quantower Import")
    date_from    = body.get("date_from", "")
    date_to      = body.get("date_to", "")
    raw_trades   = body.get("trades", [])
    qt_summary   = body.get("summary", {})

    session_id = await db.create_backtest_session(
        name=session_name,
        session_type="microstructure",
        date_from=date_from,
        date_to=date_to,
        config={"source": "quantower", "strategy": body.get("strategy", "")},
    )

    # Normalise trade dicts to our backtest_trades schema
    trades = [
        {
            "symbol":       t.get("symbol", ""),
            "side":         t.get("side", ""),
            "entry_dt":     t.get("entry_dt", ""),
            "exit_dt":      t.get("exit_dt", ""),
            "entry_price":  float(t.get("entry_price", 0)),
            "exit_price":   float(t.get("exit_price", 0)),
            "size_usdt":    float(t.get("size_usdt", 0)),
            "r_multiple":   float(t.get("pnl_r", 0)),
            "pnl_usdt":     float(t.get("pnl_usdt", t.get("size_usdt", 0) * t.get("pnl_r", 0))),
            "regime_label": "",
            "exit_reason":  t.get("exit_reason", ""),
        }
        for t in raw_trades
    ]

    r_vals = [t["r_multiple"] for t in trades]
    from core import analytics as _an
    r_stats = _an.r_multiple_stats(r_vals)

    summary = {
        "source":           "quantower",
        "total_trades":     len(trades),
        "win_rate":         float(qt_summary.get("win_rate", r_stats.get("win_rate", 0))),
        "total_r":          float(qt_summary.get("total_r", sum(r_vals))),
        "avg_slippage_bps": float(qt_summary.get("avg_slippage_bps", 0)),
        "r_stats":          r_stats,
    }

    await db.insert_backtest_trades(session_id, trades)
    await db.finish_backtest_session(session_id, "completed", summary)

    return JSONResponse({"session_id": session_id, "status": "imported", "trade_count": len(trades)})


# ── Potential Models ─────────────────────────────────────────────────────────

@router.get("/api/models", response_class=JSONResponse)
async def api_list_models():
    from core.database import db
    models = await db.list_potential_models()
    for m in models:
        m.pop("config_json", None)
    return JSONResponse(models)


@router.get("/api/models/{model_id}", response_class=JSONResponse)
async def api_get_model(model_id: int):
    from core.database import db
    model = await db.get_potential_model(model_id)
    if not model:
        return JSONResponse({"error": "Not found"}, status_code=404)
    model.pop("config_json", None)
    return JSONResponse(model)


@router.post("/api/models", response_class=JSONResponse)
async def api_create_model(request: Request):
    """
    Create a potential model definition.
    Body: {
      "name": str,
      "type": "macro" | "micro" | "both",
      "description": str,
      "config": {
        "signals": {...},     // entry signals config (macro)
        "risk": {...},        // risk parameters
        "micro": {...},       // microstructure params (micro)
        "regime": {...},      // regime filters
      }
    }
    """
    from core.database import db
    body = await request.json()
    name        = body.get("name", "").strip()
    model_type  = body.get("type", "both")
    description = body.get("description", "").strip()
    config      = body.get("config", {})

    if not name:
        return JSONResponse({"error": "Name is required"}, status_code=400)
    if model_type not in ("macro", "micro", "both"):
        return JSONResponse({"error": "Type must be macro, micro, or both"}, status_code=400)

    model_id = await db.create_potential_model(name, model_type, description, config)
    return JSONResponse({"model_id": model_id, "status": "created"})


@router.put("/api/models/{model_id}", response_class=JSONResponse)
async def api_update_model(request: Request, model_id: int):
    from core.database import db
    body = await request.json()
    name        = body.get("name", "").strip()
    model_type  = body.get("type", "both")
    description = body.get("description", "").strip()
    config      = body.get("config", {})

    if not name:
        return JSONResponse({"error": "Name is required"}, status_code=400)

    await db.update_potential_model(model_id, name, model_type, description, config)
    return JSONResponse({"status": "updated"})


@router.delete("/api/models/{model_id}", response_class=JSONResponse)
async def api_delete_model(model_id: int):
    from core.database import db
    await db.delete_potential_model(model_id)
    return JSONResponse({"status": "deleted"})


# ── Regime Classifier ────────────────────────────────────────────────────────

_regime_jobs: Dict[int, Dict[str, Any]] = {}
_regime_job_counter = 0


@router.get("/regime", response_class=HTMLResponse)
async def regime_page(request: Request):
    return templates.TemplateResponse(
        request, "regime.html", _ctx(request, active_page="regime")
    )


@router.get("/api/regime/current", response_class=JSONResponse)
async def api_regime_current():
    # Prefer the live in-memory regime (updated every 10 min by background loop)
    regime = app_state.current_regime
    if regime:
        return JSONResponse({
            "label":          regime.label,
            "multiplier":     regime.multiplier,
            "confidence":     regime.confidence,
            "stability_bars": regime.stability_bars,
            "mode":           regime.mode,
            "computed_at":    regime.computed_at.isoformat() if regime.computed_at else None,
            "signals":        regime.signals,
            "source":         "live",
        })
    # Fallback: most recent backfilled DB label
    from core.database import db
    label = await db.get_latest_regime_label()
    if not label:
        return JSONResponse({"label": None, "multiplier": 1.0, "source": "none"})
    import config as _cfg
    return JSONResponse({
        **label,
        "multiplier": _cfg.REGIME_MULTIPLIERS.get(label["label"], 1.0),
        "source": "db",
    })


@router.post("/api/regime/backfill", response_class=JSONResponse)
async def api_regime_backfill(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    since_date = body.get("since_date", "2020-01-01")
    until_date = body.get("until_date", datetime.now().strftime("%Y-%m-%d"))
    mode = body.get("mode", "macro_only")

    global _regime_job_counter
    _regime_job_counter += 1
    job_id = _regime_job_counter
    job: Dict[str, Any] = {
        "status": "running",
        "detail": "Starting backfill...",
        "pct": 0,
        "results": {},
    }
    _regime_jobs[job_id] = job

    async def _run():
        from core.regime_fetcher import RegimeFetcher
        from core.regime_classifier import classify_range
        try:
            fetcher = RegimeFetcher()
            async def progress(pct, msg):
                job["pct"] = pct * 0.8  # 80% for fetching
                job["detail"] = msg

            results = await fetcher.fetch_all(since_date, until_date, mode=mode, progress_cb=progress)
            job["results"] = results
            await fetcher.close()

            # Classify after fetching
            job["detail"] = "Classifying regimes..."
            job["pct"] = 82
            async def classify_progress(p, m):
                job["pct"] = 82 + p * 0.18
                job["detail"] = m

            count = await classify_range(
                since_date, until_date,
                progress_cb=classify_progress,
            )
            job["results"]["labels_classified"] = count
            job["status"] = "completed"
            job["detail"] = f"Done — {count} dates classified"
            job["pct"] = 100
        except Exception as e:
            log.error("Regime backfill failed: %s", e, exc_info=True)
            job["status"] = "failed"
            job["detail"] = str(e)

    asyncio.create_task(_run())
    return JSONResponse({"job_id": job_id, "status": "running"})


@router.get("/api/regime/backfill-status/{job_id}", response_class=JSONResponse)
async def api_regime_backfill_status(job_id: int):
    job = _regime_jobs.get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    return JSONResponse({
        "job_id": job_id,
        "status": job["status"],
        "detail": job["detail"],
        "pct": round(job.get("pct", 0), 1),
        "results": job.get("results", {}),
    })


@router.get("/api/regime/timeline", response_class=JSONResponse)
async def api_regime_timeline(from_date: str = "", to_date: str = ""):
    from core.database import db
    labels = await db.get_regime_labels(from_date, to_date)
    return JSONResponse(labels)


@router.get("/api/regime/signals", response_class=JSONResponse)
async def api_regime_signals(signal_name: str = "", from_date: str = "", to_date: str = ""):
    from core.database import db
    if not signal_name:
        return JSONResponse({"error": "signal_name required"}, status_code=400)
    data = await db.get_regime_signals([signal_name], from_date, to_date)
    return JSONResponse(data.get(signal_name, []))


@router.get("/api/regime/coverage", response_class=JSONResponse)
async def api_regime_coverage():
    from core.database import db
    coverage = await db.get_all_signal_coverage()
    return JSONResponse(coverage)


@router.post("/api/regime/reclassify", response_class=JSONResponse)
async def api_regime_reclassify(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    from_date = body.get("from_date", "")
    to_date = body.get("to_date", "")

    from core.regime_classifier import classify_range
    from core.database import db

    # Delete existing labels in range first
    if from_date or to_date:
        await db.delete_regime_labels(from_date, to_date)

    count = await classify_range(from_date, to_date)
    return JSONResponse({"status": "completed", "labels_classified": count})


@router.get("/api/regime/thresholds", response_class=JSONResponse)
async def api_regime_thresholds():
    return JSONResponse(config.REGIME_THRESHOLDS)


# ── News & Economic Calendar ─────────────────────────────────────────────────

@router.get("/api/news/feed", response_class=JSONResponse)
async def api_news_feed(limit: int = 50, since: str = "", source: str = ""):
    from core.database import db
    limit = max(1, min(int(limit), 200))
    items = await db.get_news_feed(limit=limit, since=since, source=source)
    return JSONResponse(items)


@router.get("/api/news/{item_id}", response_class=JSONResponse)
async def api_news_item(item_id: int):
    from core.database import db
    item = await db.get_news_by_id(item_id)
    if not item:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(item)


@router.get("/api/calendar", response_class=JSONResponse)
async def api_calendar(from_date: str = "", to_date: str = "", impact: str = ""):
    from core.database import db
    events = await db.get_calendar_events(from_date=from_date, to_date=to_date, impact=impact)
    return JSONResponse(events)


@router.post("/api/news/refresh", response_class=JSONResponse)
async def api_news_refresh():
    """Manual trigger: pull Finnhub news + calendar immediately."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from core.news_fetcher import FinnhubFetcher
    fetcher = FinnhubFetcher()
    today = _dt.now(_tz.utc).strftime("%Y-%m-%d")
    plus7 = (_dt.now(_tz.utc) + _td(days=7)).strftime("%Y-%m-%d")
    news_count = await fetcher.fetch_news(category="general")
    cal_count  = await fetcher.fetch_calendar(today, plus7)
    return JSONResponse({"news_added": news_count, "calendar_added": cal_count})

