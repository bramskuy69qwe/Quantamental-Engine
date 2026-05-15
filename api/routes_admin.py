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


# ── Manual calc_id link ─────────────────────────────────────────────────────


@router.get("/admin/calc_link", response_class=HTMLResponse)
async def calc_link_page(request: Request):
    """Table of uncorrelated entry orders for manual linking."""
    import sqlite3, config as _cfg
    from datetime import datetime, timedelta, timezone as _tz

    aid = app_state.active_account_id
    cutoff_ms = int((datetime.now(_tz.utc) - timedelta(hours=168)).timestamp() * 1000)

    orders = []
    try:
        conn = sqlite3.connect(_cfg.DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, exchange_order_id, symbol, side, order_type, price, "
            "tp_trigger_price, sl_trigger_price, created_at_ms "
            "FROM orders WHERE account_id = ? AND calc_id IS NULL "
            "AND reduce_only = 0 AND created_at_ms >= ? "
            "ORDER BY created_at_ms DESC LIMIT 50",
            (aid, cutoff_ms),
        ).fetchall()
        conn.close()
        now = datetime.now(_tz.utc)
        for r in rows:
            age_h = (now.timestamp() * 1000 - r["created_at_ms"]) / 3600000 if r["created_at_ms"] else 0
            orders.append({**dict(r), "age_hours": round(age_h, 1)})
    except Exception:
        log.debug("calc_link query failed", exc_info=True)

    return templates.TemplateResponse(
        request, "admin/calc_link.html",
        _ctx(request, orders=orders, order_count=len(orders), active_page="admin"),
    )


@router.get("/admin/calc_link/candidates", response_class=HTMLResponse)
async def calc_link_candidates(request: Request, order_id: int = 0):
    """Find candidate calcs for an uncorrelated order."""
    import sqlite3, config as _cfg
    from core.calc_correlation import find_candidate_calcs
    from dataclasses import asdict

    aid = app_state.active_account_id
    conn = sqlite3.connect(_cfg.DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM orders WHERE account_id = ? AND id = ?", (aid, order_id)
    ).fetchone()
    conn.close()

    if not row:
        return HTMLResponse('<div class="alert alert-error">Order not found.</div>')

    order = dict(row)
    candidates = find_candidate_calcs(order, db_path=_cfg.DB_PATH)

    return templates.TemplateResponse(
        request, "admin/_calc_link_candidates.html",
        {"request": request, "candidates": [asdict(c) for c in candidates],
         "order_id": order_id, "order": order},
    )


@router.post("/admin/calc_link/confirm", response_class=HTMLResponse)
async def calc_link_confirm(request: Request):
    """Confirm manual link: set calc_id on order + propagate to fills."""
    import sqlite3, config as _cfg

    try:
        body = await request.json()
    except Exception:
        body = {}

    order_id = body.get("order_id")
    calc_id = body.get("calc_id", "").strip()
    aid = app_state.active_account_id

    if not order_id or not calc_id:
        return HTMLResponse(
            '<div class="alert alert-error">Missing order_id or calc_id.</div>', status_code=400
        )

    conn = sqlite3.connect(_cfg.DB_PATH)
    conn.row_factory = sqlite3.Row

    row = conn.execute(
        "SELECT calc_id, exchange_order_id FROM orders WHERE account_id = ? AND id = ?",
        (aid, order_id),
    ).fetchone()
    if not row:
        conn.close()
        return HTMLResponse('<div class="alert alert-error">Order not found.</div>', status_code=400)
    if row["calc_id"]:
        conn.close()
        return HTMLResponse('<div class="alert alert-error">Order already linked.</div>', status_code=400)

    dup = conn.execute(
        "SELECT 1 FROM orders WHERE calc_id = ? AND account_id = ? LIMIT 1",
        (calc_id, aid),
    ).fetchone()
    if dup:
        conn.close()
        return HTMLResponse(
            '<div class="alert alert-error">calc_id already linked to another order.</div>',
            status_code=400,
        )

    eid = row["exchange_order_id"]
    conn.execute("UPDATE orders SET calc_id = ? WHERE account_id = ? AND id = ?", (calc_id, aid, order_id))
    conn.execute("UPDATE fills SET calc_id = ? WHERE account_id = ? AND exchange_order_id = ?", (calc_id, aid, eid))
    conn.commit()
    conn.close()

    try:
        from core.trade_event_log import log_trade_event
        log_trade_event(aid, calc_id, "manual_link_added", {
            "order_id": order_id, "exchange_order_id": eid,
        }, source="manual_link")
    except Exception:
        log.debug("manual_link_added event failed", exc_info=True)

    return HTMLResponse(
        '<div class="alert alert-success">Link confirmed. calc_id propagated to order + fills.</div>'
    )


# ── Equity backfill ──────────────────────────────────────────────────────────


@router.post("/admin/equity_backfill", response_class=HTMLResponse)
async def equity_backfill_trigger(request: Request):
    """Manually trigger equity backfill from exchange income history."""
    try:
        body = await request.json()
    except Exception:
        body = {}

    aid = body.get("account_id", app_state.active_account_id)
    since_hours = int(body.get("since_hours", 168))  # default 7 days

    from datetime import datetime, timedelta, timezone as _tz
    now_ms = int(datetime.now(_tz.utc).timestamp() * 1000)
    start_ms = now_ms - since_hours * 3600 * 1000

    try:
        from core.database import db
        from core.exchange import build_equity_backfill

        current_equity = app_state.account_state.total_equity
        if current_equity == 0:
            return HTMLResponse(
                '<div class="alert alert-error">Cannot backfill: current equity is 0.</div>',
                status_code=400,
            )

        # Get earliest real snapshot to avoid overlap
        earliest_ms = await db.get_earliest_snapshot_ms(account_id=aid)
        end_ms = earliest_ms if earliest_ms else now_ms

        records, cashflow = await build_equity_backfill(start_ms, end_ms, current_equity)
        inserted = 0
        if records:
            inserted = await db.insert_backfill_snapshots(records, end_ms, account_id=aid)

        return HTMLResponse(
            f'<div class="alert alert-success">Backfill complete: {inserted} snapshots inserted '
            f'covering {since_hours}h window.</div>'
        )
    except Exception as exc:
        log.error("equity_backfill failed", exc_info=True)
        return HTMLResponse(
            f'<div class="alert alert-error">Backfill failed: {exc}</div>',
            status_code=500,
        )


@router.get("/admin/equity_gaps", response_class=HTMLResponse)
async def equity_gaps_page(request: Request):
    """Show detected equity gaps for the active account."""
    from core.equity_gap_detector import detect_gaps
    from datetime import datetime, timedelta, timezone as _tz

    aid = app_state.active_account_id
    now_ms = int(datetime.now(_tz.utc).timestamp() * 1000)
    since_ms = now_ms - 30 * 24 * 3600 * 1000  # 30 days

    gaps = detect_gaps(aid, since_ms, now_ms)

    gap_rows = []
    for g in gaps:
        start = datetime.fromtimestamp(g.start_ms / 1000, tz=_tz.utc)
        end = datetime.fromtimestamp(g.end_ms / 1000, tz=_tz.utc)
        gap_rows.append({
            "start": start.strftime("%Y-%m-%d %H:%M"),
            "end": end.strftime("%Y-%m-%d %H:%M"),
            "hours": round(g.duration_ms / 3600000, 1),
        })

    return templates.TemplateResponse(
        request, "admin/equity_gaps.html",
        _ctx(request, gaps=gap_rows, gap_count=len(gaps), active_page="admin"),
    )
