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
        app_state.active_account_id = account_id

        last_snap = await db.get_last_account_state(account_id=account_id)
        if last_snap:
            acc = app_state.account_state
            acc.total_equity     = last_snap.get("total_equity", 0.0)
            acc.bod_equity       = last_snap.get("bod_equity", 0.0)
            acc.sow_equity       = last_snap.get("sow_equity", 0.0)
            acc.max_total_equity = last_snap.get("max_total_equity", 0.0)

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
            app_state.recalculate_portfolio()
            listen_key = await create_listen_key()
            await ws_manager.start(listen_key)

        try:
            await _reinit()
        except Exception as exc:
            log.error("Reinit failed for account %d, rolling back to %d: %s",
                      account_id, old_account_id, safe_exchange_error(exc))
            app_state.ws_status.add_log(f"SWITCH FAILED: {safe_exchange_error(exc)}")
            await account_registry.set_active(old_account_id)
            app_state.active_account_id = old_account_id
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
    try:
        ex = _make_ccxt_instance(api_key, api_secret, exchange, market_type)
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
    return templates.TemplateResponse(
        request, "fragments/account_detail.html",
        _ctx(request, acct=acct, params=params),
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
):
    """Save credentials + params + fees for an account in one request."""
    # Update credentials
    cred_kwargs = {}
    if api_key:
        cred_kwargs["api_key"] = api_key
    if api_secret:
        cred_kwargs["api_secret"] = api_secret
    if broker_account_id is not None:
        cred_kwargs["broker_account_id"] = broker_account_id
    if cred_kwargs:
        await account_registry.update_account(account_id, **cred_kwargs)

    # Update exchange/market_type/environment via DB directly
    db_kwargs = {}
    if exchange is not None:
        db_kwargs["exchange"] = exchange
    if market_type is not None:
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

    return HTMLResponse('<span style="color:var(--green);font-size:.65rem;">Saved.</span>')
