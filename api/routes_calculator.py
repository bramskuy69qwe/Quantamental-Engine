from __future__ import annotations

import json
import logging
import math

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

from core.state import app_state
from core.risk_engine import run_risk_calculator
from core.event_bus import event_bus
from core.exchange import fetch_orderbook, fetch_ohlcv
from core import ws_manager
from core.database import db
from api.helpers import templates, _ctx

log = logging.getLogger("routes.calculator")
router = APIRouter()

# P8.T4c (spec §10.1 / §3 schema): TP-ladder cap. Each level is {price, size_pct}.
MAX_TP_LEVELS = 10


def _parse_model_id(raw: str) -> "int | None":
    """v2.7 5.2: picker value → int model id. Blank/0/negative → None
    (no model). Non-numeric → ValueError (the 400 error-fragment lane)."""
    s = (raw or "").strip()
    if not s:
        return None
    try:
        val = int(s)
    except ValueError:
        raise ValueError("model_id must be an integer")
    return val if val > 0 else None


def _parse_tp_levels(raw):
    """Parse + validate the TP-ladder JSON (P8.T4c).

    Returns a normalized ``list[{"price": float, "size_pct": float}]`` or None
    for a blank/empty ladder. Raises ValueError on any malformed / out-of-range
    input (the endpoint maps it to a 400). Rules: each level needs a numeric
    price > 0 and size_pct in (0, 100]; at most MAX_TP_LEVELS levels; the
    size_pct total must not exceed 100 (small tolerance for float entry).
    """
    if not raw or not str(raw).strip():
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("tp_levels must be valid JSON")
    if not isinstance(data, list):
        raise ValueError("tp_levels must be a JSON array")
    if not data:
        return None
    if len(data) > MAX_TP_LEVELS:
        raise ValueError(f"too many TP levels (max {MAX_TP_LEVELS})")
    out = []
    total = 0.0
    for i, lvl in enumerate(data, start=1):
        if not isinstance(lvl, dict):
            raise ValueError(f"TP level {i} must be an object")
        try:
            price = float(lvl.get("price"))
            pct = float(lvl.get("size_pct"))
        except (TypeError, ValueError):
            raise ValueError(f"TP level {i} price/size_pct must be numbers")
        # Reject non-finite (NaN/Infinity): Python's json.loads accepts the
        # NaN/Infinity literals and float("1e400") overflows to inf — both
        # slip past the `price <= 0` guard and would persist as INVALID JSON
        # (json.dumps emits bare NaN/Infinity tokens). (P8.T4c audit, MED.)
        if not math.isfinite(price) or not math.isfinite(pct):
            raise ValueError(f"TP level {i} price/size_pct must be finite")
        if price <= 0:
            raise ValueError(f"TP level {i} price must be > 0")
        if not (0 < pct <= 100):
            raise ValueError(f"TP level {i} size_pct must be in (0, 100]")
        total += pct
        out.append({"price": price, "size_pct": pct})
    if total > 100.01:
        raise ValueError(f"TP level size_pct total {total:.1f}% exceeds 100%")
    return out


@router.get("/calculator", response_class=HTMLResponse)
async def calculator_page(request: Request):
    # P8.T4a: surface the account-level match window so the dropdown shows the
    # current value selected. read_*_async returns the spec §3.3 default (300)
    # on any error, so the page never fails to render over this.
    from core.account_config import read_account_config_async
    cfg = await read_account_config_async(db, app_state.active_account_id)
    return templates.TemplateResponse(
        request, "calculator.html",
        _ctx(request, calc=None, window_seconds=cfg.window_seconds),
    )


@router.post("/calculator/window", response_class=HTMLResponse)
async def set_account_window(window_seconds: int = Form(...)):
    """P8.T4a (plan §8 row 8.4): set the account-level calc-linkage match
    window (``config_json.window_seconds``) — the default the matcher freezes
    onto each new calc (P1.T2/T3). Distinct from the per-calc
    ``link_window_seconds_override`` form field (which overrides one calc).

    Returns 200 + a tiny inline confirmation so htmx swaps it; a non-2xx body
    would be swallowed by the global htmx error handler (base.html), so the
    out-of-range case returns 200 with an error-styled span instead.
    """
    from core.exec_link import MAX_LINK_WINDOW_SECONDS
    if window_seconds <= 0 or window_seconds > MAX_LINK_WINDOW_SECONDS:
        return HTMLResponse(
            f'<span class="text-red">invalid (1–{MAX_LINK_WINDOW_SECONDS}s)</span>'
        )
    from core.account_config import write_account_config
    try:
        await write_account_config(
            db, app_state.active_account_id, {"window_seconds": window_seconds},
        )
    except Exception:
        log.exception("set_account_window write failed")
        return HTMLResponse('<span class="text-red">save failed</span>')
    return HTMLResponse('<span class="text-green">saved ✓</span>')


@router.post("/calculator/clear", response_class=HTMLResponse)
async def calculator_clear():
    """Drop the active calculator symbol's market-data subscription on Clear.

    The Clear button stops the front-end 1 Hz price poll, but that poll
    (`/api/price/{ticker}`) is what sets `_calculator_symbol` on the backend —
    so without this, the LAST symbol stays subscribed and its `@depth20` +
    ticker keep streaming after Clear (operator: Clear doesn't unsubscribe →
    the live data flickers between the old + new symbol when you then
    calculate a new one). `set_calculator_symbol("")` → `None` → rebuilds the
    market streams without the calc symbol. A symbol that is ALSO an open
    position stays subscribed (position symbols are in the stream set too);
    only the calc-only subscription is dropped.
    """
    ws_manager.set_calculator_symbol("")
    return HTMLResponse("")


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
    # P8.T4b (spec §10.1): optional operator size override (contracts).
    # Blank → use the engine-recommended size. Parsed + validated below.
    size_override: str = Form(""),
    # P8.T4c (spec §10.1): optional multi-TP ladder, a JSON array of
    # {price, size_pct}. Blank → single-TP (tp_price). Validated below.
    tp_levels: str = Form(""),
    # v2.7 5.2: the model-library picker (a regular persistent form field
    # — re-rides every recalc so a superseding calc keeps its model).
    # Blank → no model selected.
    model_id: str = Form(""),
):
    ticker = ticker.upper().strip()
    ws_manager.set_calculator_symbol(ticker)

    # Phase 8 audit (HIGH): float("nan")/float("inf")/"1e400" parse cleanly via
    # Form(float) but slip EVERY downstream `<= 0` / range guard (all NaN
    # comparisons are False), poisoning the calc (NaN size/notional persisted as
    # eligible) + emitting bare NaN tokens into JSON columns. Reject non-finite
    # price/percent inputs at the door. (calculate_position_size also guards
    # average/sl_price as defense-in-depth for non-route callers.)
    for _name, _v in (("average", average), ("sl_price", sl_price),
                      ("tp_price", tp_price), ("tp_amount_pct", tp_amount_pct),
                      ("sl_amount_pct", sl_amount_pct)):
        if not math.isfinite(_v):
            return HTMLResponse(
                f'<div class="alert alert-error">{_name} must be a finite '
                f'number.</div>',
                status_code=400,
            )

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

    # P8.T4b (spec §10.1): parse the optional size override. Blank / 0 /
    # negative → no override (engine recommendation). Non-numeric → 400.
    size_override_val: "float | None" = None
    if size_override.strip():
        try:
            parsed_sz = float(size_override.strip())
        except ValueError:
            return HTMLResponse(
                '<div class="alert alert-error">size_override must be a '
                'number.</div>',
                status_code=400,
            )
        # math.isfinite: +inf parses and passes `> 0`, so it would persist as a
        # live override (overridden_size=inf). NaN/-inf already fail `> 0`.
        if math.isfinite(parsed_sz) and parsed_sz > 0:
            size_override_val = parsed_sz

    # P8.T4c: parse + validate the optional TP ladder before any work.
    try:
        tp_levels_parsed = _parse_tp_levels(tp_levels)
    except ValueError as exc:
        return HTMLResponse(
            f'<div class="alert alert-error">{exc}</div>', status_code=400,
        )

    # v2.7 5.2: parse the optional model picker value before any work.
    try:
        model_id_val = _parse_model_id(model_id)
    except ValueError as exc:
        return HTMLResponse(
            f'<div class="alert alert-error">{exc}</div>', status_code=400,
        )

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
        size_override=size_override_val,
    )
    # HIGH-027 (Task 104b): attach override to the calc dict before publish.
    # handle_risk_calculated forwards the dict to insert_pre_trade_log, which
    # now persists link_window_seconds_override. None → DB default NULL →
    # compute_exec_match uses account default at fill time.
    calc["link_window_seconds_override"] = override_int
    # P8.T4c: attach the validated TP ladder (list[{price, size_pct}] or None).
    # insert_pre_trade_log JSON-serializes it to pre_trade_log.tp_levels;
    # calc_result.html renders it. tp_levels is recorded metadata — the matcher
    # + est_profit use the single tp_price (the UI feeds TP1 there if the
    # single TP field is blank). Per-rung analytics are a later phase.
    calc["tp_levels"] = tp_levels_parsed
    # v2.7 5.2: attach the model-library FK (the tp_levels post-attach
    # idiom — run_risk_calculator's signature stays untouched by design;
    # plan rev 2). insert_pre_trade_log persists pre_trade_log.model_id;
    # None = no model selected.
    calc["model_id"] = model_id_val

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

    # Auto-link surfaced (debug 2026-06-08): once the matcher links this calc its
    # status flips to 'matched'/'linked'. Show a terminal LINKED state instead of
    # the bare time-window countdown — which an auto-matched calc would otherwise
    # keep showing ("Linkable for:" → EXPIRED) until the window elapses, so the
    # operator never sees the link land. (LINKED_CONFIRMED above is a DIFFERENT
    # signal: an exec-link-confirmed fill, not the matcher's auto-link.)
    if (await _db.get_calc_status(calc_id=calc_id, account_id=aid)) in ("matched", "linked"):
        return templates.TemplateResponse(
            request, "fragments/link_window_countdown.html",
            _ctx(request, calc_id=calc_id, lw={
                "status": "LINKED",
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
    ``core.handlers.cancel_calc_by_operator``. Returns a small htmx alert
    fragment.

    Wired to the cockpit active-calcs pane's per-calc Cancel button (P8.T3),
    which swaps this response into ``#ck-calc-alert``. htmx does NOT swap
    non-2xx response bodies — the global ``htmx:responseError`` handler
    (base.html) instead shows a generic toast + a "Couldn't load this
    section." retry fragment, swallowing the specific outcome. So this
    endpoint returns **200 for every outcome** with a status-discriminated
    alert body (success / warning / error) — option (a) from the original
    T219 docstring, chosen now that the button is wired (Phase-8 deferred
    #3b). The semantic outcome lives in the alert class + text, not the HTTP
    status. (The same htmx swallow still affects calculate_risk's 400
    validation bodies — a separate, codebase-wide pattern.)
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
            '<div class="alert alert-error">Calc not found.</div>'
        )
    if result == "not_cancellable":
        return HTMLResponse(
            '<div class="alert alert-warning">Calc is no longer cancellable '
            '(already matched, expired, superseded, or cancelled).</div>'
        )
    if result == "race_lost":
        return HTMLResponse(
            '<div class="alert alert-warning">Calc state changed during '
            'cancel — please refresh.</div>'
        )
    return HTMLResponse(
        '<div class="alert alert-error">Cancel failed — see engine logs.</div>'
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
