from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

from core.state import app_state
from core.risk_engine import run_risk_calculator
from core.event_bus import event_bus
from core.exchange import fetch_orderbook, fetch_ohlcv
from core import ws_manager
from api.helpers import templates, _ctx

log = logging.getLogger("routes.calculator")
router = APIRouter()


@router.get("/calculator", response_class=HTMLResponse)
async def calculator_page(request: Request):
    return templates.TemplateResponse(request, "calculator.html", _ctx(request, calc=None))


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
    # HIGH-027 (Task 104b): optional per-calc override of the account
    # link window. Blank/omitted → use account default. Validated below.
    link_window_seconds_override: str = Form(""),
):
    ticker = ticker.upper().strip()
    ws_manager.set_calculator_symbol(ticker)

    # HIGH-027 (Task 104b): parse + validate override before any work.
    # Blank / 0 / negative → treat as "no override" (None in DB).
    # Beyond MAX_LINK_WINDOW_SECONDS → error fragment.
    override_int: int | None = None
    if link_window_seconds_override.strip():
        from core.exec_link import MAX_LINK_WINDOW_SECONDS
        try:
            parsed = int(link_window_seconds_override.strip())
        except ValueError:
            return HTMLResponse(
                '<div class="alert alert-error">link_window_seconds_override '
                'must be an integer.</div>',
                status_code=400,
            )
        if parsed <= 0:
            override_int = None
        elif parsed > MAX_LINK_WINDOW_SECONDS:
            return HTMLResponse(
                f'<div class="alert alert-error">link_window_seconds_override '
                f'must be ≤ {MAX_LINK_WINDOW_SECONDS} s (24 h); got '
                f'{parsed}.</div>',
                status_code=400,
            )
        else:
            override_int = parsed

    try:
        await fetch_orderbook(ticker)
        if ticker not in app_state.ohlcv_cache:
            await fetch_ohlcv(ticker)
    except Exception as e:
        return HTMLResponse(f'<div class="alert alert-error">Data fetch error: {e}</div>')

    calc = run_risk_calculator(
        ticker=ticker, average=average, sl_price=sl_price,
        tp_price=tp_price, tp_amount_pct=tp_amount_pct,
        sl_amount_pct=sl_amount_pct, model_name=model_name, model_desc=model_desc,
        order_type=order_type,
        apply_regime_multiplier=(apply_regime_multiplier == "1"),
    )
    # HIGH-027 (Task 104b): attach override to the calc dict before publish.
    # handle_risk_calculated forwards the dict to insert_pre_trade_log, which
    # now persists link_window_seconds_override. None → DB default NULL →
    # compute_exec_match uses account default at fill time.
    calc["link_window_seconds_override"] = override_int

    if auto_refresh != "1":
        await event_bus.publish("risk:risk_calculated", calc)

    return templates.TemplateResponse(
        request, "fragments/calc_result.html",
        _ctx(request, calc=calc),
    )


@router.get("/calculator/link-window-status/{calc_id}", response_class=HTMLResponse)
async def calculator_link_window_status(request: Request, calc_id: str):
    """HIGH-027 (Task 104b): countdown fragment renderer.

    Polled at 5 s by the calculator result template. Looks up the pretrade
    row by calc_id, reads the account default + per-calc override, computes
    state via core.exec_link.compute_link_window_status, and returns the
    rendered countdown fragment.

    Path: /calculator/link-window-status/{calc_id} — calc_id is opaque
    string the calculator already generates; no further validation needed
    (a bad/unknown calc_id renders the 'unknown calc' fragment branch).
    """
    from core.database import db as _db
    from core.exec_link import (
        DEFAULT_LINK_WINDOW_SECONDS, compute_link_window_status,
    )
    from datetime import datetime, timezone

    aid = app_state.active_account_id

    pretrade: dict | None = None
    async with _db._conn.execute(
        "SELECT timestamp, link_window_seconds_override FROM pre_trade_log "
        "WHERE calc_id=? AND account_id=? LIMIT 1",
        (calc_id, aid),
    ) as cur:
        row = await cur.fetchone()
        if row:
            pretrade = dict(row)

    # Account link window
    account_window = DEFAULT_LINK_WINDOW_SECONDS
    async with _db._conn.execute(
        "SELECT link_window_seconds FROM accounts WHERE id=?", (aid,),
    ) as cur:
        row = await cur.fetchone()
        if row and row[0] is not None:
            account_window = int(row[0])

    # exec_link_confirmed: any fill for this calc_id confirmed?
    confirmed = False
    async with _db._conn.execute(
        "SELECT 1 FROM fills WHERE calc_id=? AND account_id=? "
        "AND exec_link_confirmed=1 LIMIT 1",
        (calc_id, aid),
    ) as cur:
        confirmed = (await cur.fetchone()) is not None

    # FE-HIGH-009 + FE-MED-030 (Task 139): PENDING short-circuit for the
    # event-bus-publish-vs-htmx-load race. event_bus.publish() only
    # enqueues; htmx fires the first poll before insert_pre_trade_log
    # commits. Previously the missing row fell through to
    # compute_link_window_status(None) → EXPIRED (terminal, no
    # hx-trigger) → polling stopped → widget stuck on PLAN EXPIRED.
    # Returning PENDING here keeps polling at 1s; once the INSERT
    # commits, the next poll picks up the real state.
    if pretrade is None:
        return templates.TemplateResponse(
            request, "fragments/link_window_countdown.html",
            _ctx(request, calc_id=calc_id, lw={
                "status": "PENDING",
                "effective_window_s": account_window,
                "remaining_s": 0,
                "expires_at_ms": None,
            }),
        )

    pretrade_ts_ms: int | None = None
    if pretrade.get("timestamp"):
        try:
            dt = datetime.fromisoformat(pretrade["timestamp"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            pretrade_ts_ms = int(dt.timestamp() * 1000)
        except (ValueError, TypeError):
            pretrade_ts_ms = None

    status = compute_link_window_status(
        pretrade_ts_ms=pretrade_ts_ms,
        account_link_window_seconds=account_window,
        override_seconds=pretrade.get("link_window_seconds_override"),
        exec_link_confirmed=confirmed,
    )

    return templates.TemplateResponse(
        request, "fragments/link_window_countdown.html",
        _ctx(request, calc_id=calc_id, lw=status),
    )


@router.get("/calculator/refresh/{ticker}", response_class=HTMLResponse)
async def calculator_refresh(request: Request, ticker: str):
    ticker = ticker.upper()
    try:
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
