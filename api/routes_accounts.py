from __future__ import annotations

import asyncio
import concurrent.futures
import json as _json
import logging
import time
from typing import Optional

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse

from core.state import app_state
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
        app_state.reset_for_account_switch()
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
):
    try:
        new_id = await account_registry.add_account(name, exchange, market_type, api_key, api_secret)
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
