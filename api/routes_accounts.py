from __future__ import annotations

import asyncio
import concurrent.futures
import json as _json
import logging
import time
from typing import Optional

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse

from core.state import app_state, validate_params
from core.crypto import safe_exchange_error
from core.database import db
from core.account_registry import account_registry
from core.exchange_factory import exchange_factory, _make_ccxt_instance
from core.security import SensitiveStr
from core.exchange import (
    fetch_exchange_info, fetch_account, fetch_positions,
    fetch_ohlcv, create_listen_key, fetch_bod_sow_equity,
    fetch_exchange_trade_history,
)
from core import ws_manager
from api.helpers import templates, _ctx
from api.cache import _backfill_earliest_ms

log = logging.getLogger("routes.accounts")
router = APIRouter()

_switch_lock = asyncio.Lock()


def _validate_exchange(exchange: str, market_type: str) -> str:
    """MED-048 (Task 114): server-side whitelist for client-supplied
    ``exchange`` form fields. Returns an empty string on success, or an
    operator-friendly error message on rejection.

    Strict case-sensitive — registry keys are lowercase by convention,
    and any case variation from the dropdown means the frontend was
    tampered with. ``market_type`` is mapped through ``map_market_type``
    (the DB stores ``future``; the registry keys on ``linear_perpetual``)
    before lookup so the same caller form values used elsewhere apply
    here unchanged.
    """
    from core.adapters import map_market_type
    from core.adapters.registry import (
        is_valid_rest_exchange, get_supported_rest_exchanges,
    )
    mapped = map_market_type(exchange, market_type)
    if is_valid_rest_exchange(exchange, mapped):
        return ""
    supported = ", ".join(get_supported_rest_exchanges(mapped)) or "(none registered)"
    return (
        f"Unknown exchange: '{exchange}'. Supported: {supported}."
    )


def _validate_market_type(market_type: str) -> str:
    """MED-049 (Task 119): server-side whitelist for client-supplied
    ``market_type`` form fields. Returns an empty string on success,
    or an operator-friendly error message on rejection.

    Strict case-sensitive. Symmetric to `_validate_exchange` — closes
    the gap where a market_type-only edit on `update_account_detail`
    skipped re-validation (since MED-048's check only fires when
    `exchange` is also supplied).
    """
    from core.adapters.registry import (
        is_valid_market_type, get_supported_market_types,
    )
    if is_valid_market_type(market_type):
        return ""
    supported = ", ".join(get_supported_market_types()) or "(none registered)"
    return f"Unknown market_type: '{market_type}'. Supported: {supported}."


@router.get("/accounts", response_class=JSONResponse)
async def list_accounts(request: Request):
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
    err = _validate_exchange(exchange, market_type)
    if err:
        return JSONResponse({"status": "error", "error": err}, status_code=400)
    # HIGH-029 (Task 116): wrap form-received credentials so an exception
    # during add_account (encrypt, DB insert, cache write) masks the raw
    # value in stack frames. account_registry unwraps at the cache
    # boundary; encrypt() goes through .encode() (C-slot safe).
    api_key = SensitiveStr(api_key)
    api_secret = SensitiveStr(api_secret)
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
    broker_account_id: Optional[str] = Form(None),
):
    # HIGH-029 (Task 116): wrap form-received credentials (see create_account).
    if api_key is not None:
        api_key = SensitiveStr(api_key)
    if api_secret is not None:
        api_secret = SensitiveStr(api_secret)
    await account_registry.update_account(
        account_id, name=name, api_key=api_key, api_secret=api_secret,
        broker_account_id=broker_account_id,
    )
    return JSONResponse({"status": "ok"})


@router.delete("/accounts/{account_id}", response_class=HTMLResponse)
async def delete_account(account_id: int, request: Request):
    if account_id == app_state.active_account_id:
        return HTMLResponse(
            "Cannot delete the active account. Switch to another account first.",
            status_code=409,
        )
    await account_registry.delete_account(account_id)
    exchange_factory.invalidate(account_id)
    accounts = await account_registry.list_accounts()
    return templates.TemplateResponse(
        request, "fragments/accounts.html",
        _ctx(request, accounts=accounts),
    )


@router.post("/accounts/{account_id}/test", response_class=JSONResponse)
async def test_account_connection(account_id: int, request: Request):
    result = await account_registry.test_connection(account_id)
    return JSONResponse(result)


@router.post("/accounts/{account_id}/activate", response_class=JSONResponse)
async def activate_account(account_id: int, request: Request):
    """Switch active account — full teardown/reinit flow."""
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

        app_state.is_initializing = True
        await ws_manager.stop()
        app_state.reset_for_account_switch(new_account_id=account_id)
        exchange_factory.invalidate(old_account_id)
        _backfill_earliest_ms.pop(old_account_id, None)

        await account_registry.set_active(account_id)
        # SR-2: app_state.active_account_id is a read-through property —
        # no manual sync needed after set_active().

        # SR-3: shared 8-field restore (fixes MP-2 — was only 4 fields)
        last_snap = await db.get_last_account_state(account_id=account_id)
        if last_snap:
            app_state.restore_from_snapshot(last_snap)

        async def _reinit():
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
            # SR-3/F4: route through DataCache (sole recalculation path)
            if app_state._data_cache is not None:
                app_state._data_cache._recalculate_portfolio()
            listen_key = await create_listen_key()
            await ws_manager.start(listen_key)

        try:
            await _reinit()
        except Exception as exc:
            log.error("Reinit failed for account %d, rolling back to %d: %s",
                      account_id, old_account_id, safe_exchange_error(exc))
            app_state.ws_status.add_log(f"SWITCH FAILED: {safe_exchange_error(exc)}")
            await account_registry.set_active(old_account_id)
            # SR-2: read-through property, no manual sync needed.
            app_state.reset_for_account_switch(new_account_id=old_account_id)
            exchange_factory.invalidate(account_id)
            try:
                await _reinit()
            except Exception:
                log.critical("Rollback reinit also failed — entering degraded mode")
                app_state.is_initializing = False
            return JSONResponse({"status": "error", "error": f"Switch failed: {safe_exchange_error(exc)}"}, status_code=500)
        finally:
            app_state.is_initializing = False
            app_state.ws_status.add_log(f"Switched to account {account_id}.")

        from core.event_bus import event_bus
        await event_bus.publish("risk:params_updated", {"ts": "account_switch"})

    acct_info = next((a for a in accounts if a["id"] == account_id), {})
    return JSONResponse({
        "status":     "ok",
        "account_id": account_id,
        "name":       acct_info.get("name", ""),
    })


@router.post("/accounts/activate-selected", response_class=HTMLResponse)
async def activate_selected_account(request: Request, account_id: int = Form(...)):
    result = await activate_account(account_id, request)
    data = _json.loads(result.body)
    if data.get("status") == "ok":
        return HTMLResponse('<span class="text-green" style="font-size:.65rem;">Switched</span>')
    return HTMLResponse(f'<span class="text-red" style="font-size:.65rem;">{data.get("error","Error")}</span>')


@router.post("/accounts/{account_id}/activate-frag", response_class=HTMLResponse)
async def activate_account_frag(account_id: int, request: Request):
    await activate_account(account_id, request)
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
    environment: str = Form("live"),
    params_source: str = Form("defaults"),
):
    err = _validate_exchange(exchange, market_type)
    if err:
        return HTMLResponse(
            f'<span class="text-red" style="font-size:.65rem;">Error: {err}</span>',
            status_code=400,
        )
    # HIGH-029 (Task 116): wrap form-received credentials (see create_account).
    api_key = SensitiveStr(api_key)
    api_secret = SensitiveStr(api_secret)
    try:
        # Resolve params template
        params_template = None
        if params_source.startswith("copy_"):
            try:
                source_id = int(params_source.split("_", 1)[1])
                params_template = account_registry.get_account_params(source_id)
            except (ValueError, IndexError):
                pass

        new_id = await account_registry.add_account(
            name, exchange, market_type, api_key, api_secret,
            environment=environment,
            params_template=params_template,
        )
        return HTMLResponse(
            f'<span class="text-green" style="font-size:.65rem;">Account "{name}" added (id={new_id}). Reloading...</span>'
            '<script>setTimeout(function(){window.location.reload();},800);</script>'
        )
    except Exception as exc:
        return HTMLResponse(f'<span class="text-red" style="font-size:.65rem;">Error: {exc}</span>')


@router.post("/accounts/test-preview", response_class=HTMLResponse)
async def test_account_preview(
    request: Request,
    api_key: str = Form(...),
    api_secret: str = Form(...),
    exchange: str = Form("binance"),
    market_type: str = Form("future"),
):
    err = _validate_exchange(exchange, market_type)
    if err:
        return HTMLResponse(
            f'<span class="text-red" style="font-size:.65rem;">Failed: {err}</span>',
            status_code=400,
        )
    # HIGH-029 (Task 116): direct-CCXT shape. The credentials never reach
    # account_registry's cache — they pass straight into _make_ccxt_instance.
    # Wrap on receipt, then unwrap immediately before ccxt construction so
    # ccxt's internal URL / header serialization receives raw strings.
    api_key = SensitiveStr(api_key)
    api_secret = SensitiveStr(api_secret)
    try:
        ex = _make_ccxt_instance(api_key.unwrap(), api_secret.unwrap(), exchange, market_type)
        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            t0 = time.monotonic()
            await loop.run_in_executor(pool, ex.fetch_time)
            latency = round((time.monotonic() - t0) * 1000, 1)
        return HTMLResponse(f'<span class="text-green" style="font-size:.65rem;">Connection OK — {latency}ms</span>')
    except Exception as exc:
        return HTMLResponse(f'<span class="text-red" style="font-size:.65rem;">Failed: {exc}</span>')


@router.get("/api/settings/platform", response_class=JSONResponse)
async def get_platform(request: Request):
    return JSONResponse({"platform": app_state.active_platform})


@router.post("/api/settings/platform", response_class=JSONResponse)
async def set_platform(request: Request, platform: str = Form(...)):
    if platform not in ("standalone", "quantower"):
        return JSONResponse({"status": "error", "error": "Unknown platform"}, status_code=400)
    app_state.active_platform = platform
    await db.set_setting("active_platform", platform)
    return JSONResponse({"status": "ok", "platform": platform})


@router.get("/fragments/accounts", response_class=HTMLResponse)
async def frag_accounts(request: Request):
    accounts = await account_registry.list_accounts()
    return templates.TemplateResponse(
        request, "fragments/accounts.html",
        _ctx(request, accounts=accounts),
    )


# ── Config page fragments ────────────────────────────────────────────────────

@router.get("/fragments/account-list", response_class=HTMLResponse)
async def frag_account_list(request: Request):
    accounts = await account_registry.list_accounts()
    return templates.TemplateResponse(
        request, "fragments/account_list.html",
        _ctx(request, accounts=accounts),
    )


@router.get("/fragments/account-detail/{account_id}", response_class=HTMLResponse)
async def frag_account_detail(account_id: int, request: Request):
    accts = await account_registry.list_accounts()
    acct = next((a for a in accts if a["id"] == account_id), None)
    if not acct:
        return HTMLResponse('<div style="color:var(--red);">Account not found.</div>')
    params = account_registry.get_account_params(account_id)
    try:
        from core.db_account_settings import get_account_settings
        settings = get_account_settings(account_id)
    except Exception:
        settings = None
    return templates.TemplateResponse(
        request, "fragments/account_detail.html",
        _ctx(request, acct=acct, params=params, settings=settings),
    )


@router.post("/accounts/{account_id}/update", response_class=HTMLResponse)
async def update_account_detail(
    account_id: int,
    request: Request,
    # Credentials
    exchange: Optional[str] = Form(None),
    market_type: Optional[str] = Form(None),
    environment: Optional[str] = Form(None),
    api_key: Optional[str] = Form(None),
    api_secret: Optional[str] = Form(None),
    broker_account_id: Optional[str] = Form(None),
    # Fees
    maker_fee: Optional[float] = Form(None),
    taker_fee: Optional[float] = Form(None),
    # Params
    individual_risk_per_trade: Optional[float] = Form(None),
    max_w_loss_percent: Optional[float] = Form(None),
    max_dd_percent: Optional[float] = Form(None),
    max_exposure: Optional[float] = Form(None),
    max_position_count: Optional[int] = Form(None),
    max_correlated_exposure: Optional[float] = Form(None),
    auto_export_hours: Optional[int] = Form(None),
    weekly_loss_warning_pct: Optional[float] = Form(None),
    weekly_loss_limit_pct: Optional[float] = Form(None),
    max_dd_warning_pct: Optional[float] = Form(None),
    max_dd_limit_pct: Optional[float] = Form(None),
    # Preferences (account_settings table)
    timezone: Optional[str] = Form(None),
    analytics_default_period: Optional[str] = Form(None),
    # HIGH-027 (Task 104b): per-account default link window. Bounded
    # 1..MAX_LINK_WINDOW_SECONDS (24h).
    link_window_seconds: Optional[int] = Form(None),
):
    """Save credentials + params + fees for an account in one request."""
    # Update credentials
    # HIGH-029 (Task 116): wrap form-received credentials (see create_account).
    cred_kwargs = {}
    if api_key:
        cred_kwargs["api_key"] = SensitiveStr(api_key)
    if api_secret:
        cred_kwargs["api_secret"] = SensitiveStr(api_secret)
    if broker_account_id is not None:
        cred_kwargs["broker_account_id"] = broker_account_id
    # HIGH-027 (Task 104b): validate + thread the link-window setting.
    # Reject negative or excessive values with a 400-style error fragment
    # rather than silently clamping — operator should see when input was bad.
    if link_window_seconds is not None:
        from core.exec_link import MAX_LINK_WINDOW_SECONDS
        if link_window_seconds < 1:
            return HTMLResponse(
                '<span style="color:var(--red);font-size:.65rem;">'
                'Link window must be at least 1 second.</span>',
                status_code=400,
            )
        if link_window_seconds > MAX_LINK_WINDOW_SECONDS:
            return HTMLResponse(
                f'<span style="color:var(--red);font-size:.65rem;">'
                f'Link window must be ≤ {MAX_LINK_WINDOW_SECONDS} s '
                f'(24 h); got {link_window_seconds}.</span>',
                status_code=400,
            )
        cred_kwargs["link_window_seconds"] = link_window_seconds
    if cred_kwargs:
        await account_registry.update_account(account_id, **cred_kwargs)

    # Update exchange/market_type/environment via DB directly
    db_kwargs = {}
    if exchange is not None:
        # MED-048 (Task 114): whitelist the new exchange against the
        # adapter registry. If market_type wasn't also supplied, fall back
        # to the account's current market_type so the validation key is
        # complete.
        effective_mt = market_type
        if effective_mt is None:
            cur = next((a for a in await account_registry.list_accounts() if a["id"] == account_id), None)
            effective_mt = (cur or {}).get("market_type", "future")
        err = _validate_exchange(exchange, effective_mt)
        if err:
            return HTMLResponse(
                f'<span style="color:var(--red);font-size:.65rem;">{err}</span>',
                status_code=400,
            )
        db_kwargs["exchange"] = exchange
    if market_type is not None:
        # MED-049 (Task 119): whitelist the new market_type. Symmetric to
        # MED-048's exchange check — closes the gap for market_type-only
        # edits that previously bypassed re-validation.
        mt_err = _validate_market_type(market_type)
        if mt_err:
            return HTMLResponse(
                f'<span style="color:var(--red);font-size:.65rem;">{mt_err}</span>',
                status_code=400,
            )
        db_kwargs["market_type"] = market_type
    if environment is not None:
        db_kwargs["environment"] = environment
    if db_kwargs:
        await db.update_account(account_id, **db_kwargs)
        # Sync cache
        async with account_registry._lock:
            if account_id in account_registry._cache:
                account_registry._cache[account_id].update(db_kwargs)

    # Update fees
    if maker_fee is not None and taker_fee is not None:
        await account_registry.update_account_fees(account_id, maker_fee, taker_fee)

    # Update params
    new_params = {}
    param_fields = {
        "individual_risk_per_trade": individual_risk_per_trade,
        "max_w_loss_percent": max_w_loss_percent,
        "max_dd_percent": max_dd_percent,
        "max_exposure": max_exposure,
        "max_position_count": max_position_count,
        "max_correlated_exposure": max_correlated_exposure,
        "auto_export_hours": auto_export_hours,
        "weekly_loss_warning_pct": weekly_loss_warning_pct,
        "weekly_loss_limit_pct": weekly_loss_limit_pct,
        "max_dd_warning_pct": max_dd_warning_pct,
        "max_dd_limit_pct": max_dd_limit_pct,
    }
    for k, v in param_fields.items():
        if v is not None:
            new_params[k] = float(v)

    if new_params:
        # Validate bounds
        errors = validate_params(new_params)
        if errors:
            return HTMLResponse(
                f'<span style="color:var(--red);font-size:.65rem;">Validation error: {"; ".join(errors)}</span>'
            )
        # Merge with existing params
        existing = account_registry.get_account_params(account_id)
        existing.update(new_params)
        await account_registry.update_account_params(account_id, existing)

        # If this is the active account, update live state
        if account_id == app_state.active_account_id:
            app_state.params.update(new_params)
            if maker_fee is not None and taker_fee is not None:
                app_state.exchange_info.maker_fee = maker_fee
                app_state.exchange_info.taker_fee = taker_fee
            from core.event_bus import event_bus
            await event_bus.publish("risk:params_updated", {"ts": "config_save"})

    # Update account_settings preferences
    settings_updates = {}
    if analytics_default_period is not None:
        from core.period_resolver import VALID_PERIODS
        if analytics_default_period in VALID_PERIODS:
            settings_updates["analytics_default_period"] = analytics_default_period
    if timezone is not None:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(timezone)  # validate
            settings_updates["timezone"] = timezone
        except (ZoneInfoNotFoundError, KeyError):
            pass
    if settings_updates:
        from core.db_account_settings import update_account_settings
        try:
            update_account_settings(account_id, **settings_updates)
        except Exception:
            pass

    return HTMLResponse('<span style="color:var(--green);font-size:.65rem;">Saved.</span>')


# ── DD manual override ───────────────────────────────────────────────────────


@router.post("/account/{account_id}/dd_override", response_class=HTMLResponse)
async def dd_override(account_id: int, request: Request):
    """Manually override the dd_state gate for an account in limit state.

    Requires a reason (min 10 chars). Override persists until dd_state
    transitions out of limit; next limit episode re-engages the gate.
    """
    try:
        body = await request.json()
    except Exception:
        body = {}
    reason = (body.get("reason") or "").strip()

    # Validate reason
    if len(reason) < 10:
        return HTMLResponse(
            '<div class="alert alert-error">Reason must be at least 10 characters.</div>',
            status_code=400,
        )

    # Validate account is in limit
    pf = app_state.portfolio
    if pf.dd_state != "limit":
        return HTMLResponse(
            '<div class="alert alert-error">Account is not in limit state — override not needed.</div>',
            status_code=400,
        )

    # Already overridden?
    if account_id in app_state.dd_manually_unblocked:
        return HTMLResponse(
            '<div class="alert alert-warning">Override already active.</div>',
        )

    # Apply override
    app_state.dd_manually_unblocked.add(account_id)

    # Log event
    try:
        from core.event_log import log_event
        log_event(account_id, "manual_override", {
            "reason": reason,
            "drawdown": round(pf.drawdown, 6),
            "peak_equity": round(app_state.account_state.total_equity, 2),
        }, source="api_override")
    except Exception:
        log.warning("manual_override event log failed", exc_info=True)

    return HTMLResponse(
        '<div class="alert alert-success">DD gate overridden. Calculator unblocked until next recovery.</div>'
    )
