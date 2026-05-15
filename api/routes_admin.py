"""Admin routes — shadow events viewer + enforcement mode toggle + trade events."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from core.state import app_state
from core.event_log import query_events, log_event
from core.db_account_settings import get_account_settings, update_account_settings
from api.helpers import templates, _ctx

log = logging.getLogger("routes.admin")
router = APIRouter()


# ── Shadow events ────────────────────────────────────────────────────────────


@router.get("/admin/shadow_events", response_class=HTMLResponse)
async def shadow_events_page(
    request: Request,
    event_type: str = "would_have_blocked_dd",
    date_from: str = "",
    date_to: str = "",
    limit: int = 100,
):
    aid = app_state.active_account_id
    events = query_events(
        aid,
        event_type=event_type or None,
        from_ts=date_from or None,
        to_ts=date_to or None,
        limit=limit,
    )
    # Parse payload_json for template rendering
    for e in events:
        try:
            e["payload"] = json.loads(e.get("payload_json", "{}"))
        except (json.JSONDecodeError, TypeError):
            e["payload"] = {}

    return templates.TemplateResponse(
        request,
        "admin/shadow_events.html",
        _ctx(
            request,
            events=events,
            event_type=event_type,
            date_from=date_from,
            date_to=date_to,
            event_count=len(events),
            active_page="admin",
        ),
    )


# ── Enforcement mode toggle ──────────────────────────────────────────────────


@router.get("/admin/dd_enforcement", response_class=HTMLResponse)
async def dd_enforcement_page(request: Request):
    aid = app_state.active_account_id
    settings = get_account_settings(aid)
    from core.account_registry import account_registry
    accounts = account_registry.list_accounts_sync()
    account_name = next(
        (a["name"] for a in accounts if a["id"] == aid), f"Account {aid}"
    )
    return templates.TemplateResponse(
        request,
        "admin/dd_enforcement.html",
        _ctx(
            request,
            current_mode=settings.dd_enforcement_mode,
            account_name=account_name,
            account_id=aid,
            active_page="admin",
        ),
    )


@router.post("/admin/dd_enforcement", response_class=HTMLResponse)
async def dd_enforcement_toggle(request: Request):
    aid = app_state.active_account_id
    try:
        body = await request.json()
    except Exception:
        body = {}

    new_mode = body.get("mode", "").strip()
    confirm_name = body.get("account_name_confirm", "").strip()

    if new_mode not in ("advisory", "enforced"):
        return HTMLResponse(
            '<div class="alert alert-error">Invalid mode.</div>',
            status_code=400,
        )

    # Get account name for confirmation
    from core.account_registry import account_registry
    accounts = account_registry.list_accounts_sync()
    account_name = next(
        (a["name"] for a in accounts if a["id"] == aid), ""
    )
    if confirm_name != account_name:
        return HTMLResponse(
            '<div class="alert alert-error">Account name does not match. '
            f'Type "{account_name}" to confirm.</div>',
            status_code=400,
        )

    settings = get_account_settings(aid)
    prev_mode = settings.dd_enforcement_mode

    if prev_mode == new_mode:
        return HTMLResponse(
            f'<div class="alert alert-warning">Mode is already {new_mode}.</div>'
        )

    update_account_settings(aid, dd_enforcement_mode=new_mode)
    log_event(aid, "enforcement_mode_change", {
        "from": prev_mode, "to": new_mode,
    }, source="admin")

    return HTMLResponse(
        f'<div class="alert alert-success">Enforcement mode changed: '
        f'{prev_mode} &rarr; {new_mode}</div>'
    )


# ── Trade events viewer ─────────────────────────────────────────────────────


@router.get("/admin/trade_events", response_class=HTMLResponse)
async def trade_events_page(
    request: Request,
    event_type: str = "",
    calc_id: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
):
    from core.trade_event_log import query_trade_events

    aid = app_state.active_account_id
    events = query_trade_events(
        account_id=aid,
        calc_id=calc_id or None,
        event_type=event_type or None,
        since=date_from or None,
        until=date_to or None,
        limit=limit,
    )
    for e in events:
        try:
            e["payload"] = json.loads(e.get("payload_json", "{}"))
        except (json.JSONDecodeError, TypeError):
            e["payload"] = {}

    return templates.TemplateResponse(
        request,
        "admin/trade_events.html",
        _ctx(
            request,
            events=events,
            event_type=event_type,
            calc_id_filter=calc_id,
            date_from=date_from,
            date_to=date_to,
            event_count=len(events),
            active_page="admin",
        ),
    )
