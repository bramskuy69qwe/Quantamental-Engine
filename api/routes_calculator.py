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
async def calculator_link_window_status(
    request: Request, calc_id: str, t0: int = 0,
):
    """HIGH-027 (Task 104b): countdown fragment renderer.

    Polled at 5 s by the calculator result template. Looks up the pretrade
    row by calc_id, reads the account default + per-calc override, computes
    state via core.exec_link.compute_link_window_status, and returns the
    rendered countdown fragment.

    Path: /calculator/link-window-status/{calc_id} — calc_id is opaque
    string the calculator already generates; no further validation needed
    (a bad/unknown calc_id renders the 'unknown calc' fragment branch).

    FE-MED-032 (Task 146): `t0` query param tracks the epoch-ms of the
    first PENDING poll for this calc_id. The PENDING template echoes
    it on subsequent polls (preserves across the 1Hz polling chain).
    When `now - t0 > PENDING_TIMEOUT_MS` and the pretrade row STILL
    isn't in DB, the route returns the ERROR state (terminal, no
    hx-trigger) so the operator sees a friendly "Submission failed to
    record — please retry" message instead of polling forever. Default
    t0=0 means "first poll" — the route sets t0 to now and echoes it.
    """
    import time as _time
    from core.database import db as _db
    from core.exec_link import (
        DEFAULT_LINK_WINDOW_SECONDS, compute_link_window_status,
    )
    from datetime import datetime, timezone

    # FE-MED-032 (Task 146): cap PENDING at 5s. Per Task 139's analysis
    # the race window is sub-second; 5s = 5 polling cycles at 1Hz which
    # is a generous buffer for transient slow. Past 5s, the failure is
    # genuinely something the user should see (consumer crash, DB lock,
    # disk error) — better visible-broken than silent-broken.
    PENDING_TIMEOUT_MS = 5000

    aid = app_state.active_account_id

    # HIGH-002 (Task 144) — refactored to db.get_pretrade_timestamp_for_link_window.
    pretrade = await _db.get_pretrade_timestamp_for_link_window(
        calc_id=calc_id, account_id=aid,
    )

    # Account link window
    # HIGH-002 (Task 144) — refactored to db.get_account_link_window_seconds
    # (helper added by Task 142; cross-task reuse).
    account_window_value = await _db.get_account_link_window_seconds(aid)
    account_window = (
        int(account_window_value) if account_window_value is not None
        else DEFAULT_LINK_WINDOW_SECONDS
    )

    # exec_link_confirmed: any fill for this calc_id confirmed?
    # HIGH-002 (Task 144) — refactored to db.has_confirmed_fill_for_calc.
    confirmed = await _db.has_confirmed_fill_for_calc(
        calc_id=calc_id, account_id=aid,
    )

    # FE-HIGH-009 + FE-MED-030 (Task 139): PENDING short-circuit for the
    # event-bus-publish-vs-htmx-load race. event_bus.publish() only
    # enqueues; htmx fires the first poll before insert_pre_trade_log
    # commits. Previously the missing row fell through to
    # compute_link_window_status(None) → EXPIRED (terminal, no
    # hx-trigger) → polling stopped → widget stuck on PLAN EXPIRED.
    # Returning PENDING here keeps polling at 1s; once the INSERT
    # commits, the next poll picks up the real state.
    #
    # FE-MED-032 (Task 146): cap PENDING at PENDING_TIMEOUT_MS (5s).
    # Without the cap, a consumer crash / INSERT failure leaves the
    # widget polling PENDING forever (silent-broken). With the cap,
    # the route transitions to ERROR state after the timeout —
    # operator sees a friendly retry prompt instead of an indefinite
    # spinner.
    if pretrade is None:
        now_ms = int(_time.time() * 1000)
        if t0 <= 0:
            # First PENDING poll — start the clock.
            t0_to_echo = now_ms
        elif now_ms - t0 > PENDING_TIMEOUT_MS:
            # Exceeded timeout — surface as ERROR. Terminal state
            # (no hx-trigger); polling stops; user retries via the
            # Calculate button.
            return templates.TemplateResponse(
                request, "fragments/link_window_countdown.html",
                _ctx(request, calc_id=calc_id, lw={
                    "status": "ERROR",
                    "effective_window_s": account_window,
                    "remaining_s": 0,
                    "expires_at_ms": None,
                }),
            )
        else:
            # Within timeout window — preserve t0 for the next poll.
            t0_to_echo = t0
        return templates.TemplateResponse(
            request, "fragments/link_window_countdown.html",
            _ctx(request, calc_id=calc_id, t0=t0_to_echo, lw={
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


@router.post("/calculator/cancel/{calc_id}", response_class=HTMLResponse)
async def cancel_calc(request: Request, calc_id: str, reason: str = Form("")):
    """T219 (P1.T4 / plan §1 task 1.6): operator cancels a live calc.

    Transitions the calc active|released → cancelled_by_operator (with an
    optional reason note) and emits ``calc:cancelled`` — all via the
    ``core.calc_state.transition`` choke-point inside
    ``core.handlers.cancel_calc_by_operator``. Returns a small htmx
    fragment + a meaningful HTTP status.

    T4 scope is endpoint + transition only — there is NO "Cancel calc"
    button wired yet (spec §10.1 calculator-tab UI is a later task).

    htmx-display caveat (T219 audit, base.html:996-1008): htmx does NOT
    swap non-2xx response bodies into the target — the global
    ``htmx:responseError`` handler shows a GENERIC toast +
    "Couldn't load this section." EmptyState instead. So the specific
    404/409/500 bodies below will NOT reach the operator as-is. The
    status codes are kept because they're semantically honest for any
    non-htmx caller (tests, scripts). When the cancel button is wired,
    that task must either (a) return 200 with a status-discriminated
    body so htmx swaps it, or (b) add per-element
    ``hx-target-4*`` / ``htmx:beforeSwap`` handling to surface the
    specific outcome. Same swallow already affects calculate_risk's
    400 validation bodies — it's a codebase-wide htmx-error pattern,
    not T219-specific.
    """
    from core.handlers import cancel_calc_by_operator

    aid = app_state.active_account_id
    result = await cancel_calc_by_operator(aid, calc_id, reason)

    if result == "cancelled":
        return HTMLResponse(
            '<div class="alert alert-success">Calc cancelled.</div>'
        )
    if result == "not_found":
        return HTMLResponse(
            '<div class="alert alert-error">Calc not found.</div>',
            status_code=404,
        )
    if result == "not_cancellable":
        return HTMLResponse(
            '<div class="alert alert-warning">Calc is no longer cancellable '
            '(already matched, expired, superseded, or cancelled).</div>',
            status_code=409,
        )
    if result == "race_lost":
        return HTMLResponse(
            '<div class="alert alert-warning">Calc state changed during '
            'cancel — please refresh.</div>',
            status_code=409,
        )
    return HTMLResponse(
        '<div class="alert alert-error">Cancel failed — see engine logs.</div>',
        status_code=500,
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
