"""
Order Center API — HTMX fragment endpoints for order / fill / closed-position history.

All 4 endpoints follow the same pattern as routes_history.py:
paginated, sortable, searchable, date-filterable.  They read from the
3 new v2.2.2 tables via DatabaseManager (OrdersMixin).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse

from fastapi.responses import JSONResponse

from core.state import app_state
from core.database import db
from core.sql_safety import validate_sort_params
from api.helpers import templates, _table_ctx

log = logging.getLogger("routes.orders")
router = APIRouter()


def _iso_to_ms(iso: str) -> int | None:
    """Convert ISO-8601 datetime string to epoch milliseconds, or None."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return None


# ── Open Orders ──────────────────────────────────────────────────────────────

@router.get("/fragments/history/open_orders", response_class=HTMLResponse)
async def frag_open_orders(
    request: Request,
    page: int = 1, per_page: int = 20,
    sort_by: str = "created_at_ms", sort_dir: str = "DESC",
    search: str = "",
):
    # MED-003 (Task 101): route-level defense-in-depth for sort_by/sort_dir.
    sort_by, sort_dir = validate_sort_params(sort_by, sort_dir, db._ORDERS_SORT_COLS)
    rows, total = await db.query_open_orders(
        account_id=app_state.active_account_id,
        page=page, per_page=per_page,
        sort_by=sort_by, sort_dir=sort_dir, search=search,
    )
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(
        request, "fragments/history/open_orders_table.html",
        _table_ctx(request, rows=rows, total=total, page=page,
                   per_page=per_page, total_pages=total_pages,
                   sort_by=sort_by, sort_dir=sort_dir, search=search),
    )


# ── Order History ────────────────────────────────────────────────────────────

@router.get("/fragments/history/order_history", response_class=HTMLResponse)
async def frag_order_history(
    request: Request,
    page: int = 1, per_page: int = 20,
    sort_by: str = "updated_at_ms", sort_dir: str = "DESC",
    search: str = "",
    date_from: str = "", date_to: str = "",
):
    # MED-003 (Task 101): route-level defense-in-depth for sort_by/sort_dir.
    sort_by, sort_dir = validate_sort_params(sort_by, sort_dir, db._ORDERS_SORT_COLS)
    rows, total = await db.query_order_history(
        account_id=app_state.active_account_id,
        page=page, per_page=per_page,
        sort_by=sort_by, sort_dir=sort_dir, search=search,
        date_from_ms=_iso_to_ms(date_from), date_to_ms=_iso_to_ms(date_to),
    )
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(
        request, "fragments/history/order_history_table.html",
        _table_ctx(request, rows=rows, total=total, page=page,
                   per_page=per_page, total_pages=total_pages,
                   sort_by=sort_by, sort_dir=sort_dir, search=search,
                   date_from=date_from, date_to=date_to),
    )


# ── Trade History (fills) ────────────────────────────────────────────────────

@router.get("/fragments/history/fills", response_class=HTMLResponse)
async def frag_fills(
    request: Request,
    page: int = 1, per_page: int = 20,
    sort_by: str = "timestamp_ms", sort_dir: str = "DESC",
    search: str = "",
    date_from: str = "", date_to: str = "",
):
    # MED-003 (Task 101): route-level defense-in-depth for sort_by/sort_dir.
    sort_by, sort_dir = validate_sort_params(sort_by, sort_dir, db._FILLS_SORT_COLS)
    rows, total = await db.query_fills(
        account_id=app_state.active_account_id,
        page=page, per_page=per_page,
        sort_by=sort_by, sort_dir=sort_dir, search=search,
        date_from_ms=_iso_to_ms(date_from), date_to_ms=_iso_to_ms(date_to),
    )
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(
        request, "fragments/history/fills_table.html",
        _table_ctx(request, rows=rows, total=total, page=page,
                   per_page=per_page, total_pages=total_pages,
                   sort_by=sort_by, sort_dir=sort_dir, search=search,
                   date_from=date_from, date_to=date_to),
    )


# ── Position History (closed positions) ──────────────────────────────────────

@router.get("/fragments/history/closed_positions", response_class=HTMLResponse)
async def frag_closed_positions(
    request: Request,
    page: int = 1, per_page: int = 20,
    sort_by: str = "exit_time_ms", sort_dir: str = "DESC",
    search: str = "",
    date_from: str = "", date_to: str = "",
):
    # MED-003 (Task 101): route-level defense-in-depth for sort_by/sort_dir.
    sort_by, sort_dir = validate_sort_params(sort_by, sort_dir, db._CLOSED_POS_SORT_COLS)
    rows, total = await db.query_closed_positions(
        account_id=app_state.active_account_id,
        page=page, per_page=per_page,
        sort_by=sort_by, sort_dir=sort_dir, search=search,
        date_from_ms=_iso_to_ms(date_from), date_to_ms=_iso_to_ms(date_to),
    )
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(
        request, "fragments/history/closed_positions_table.html",
        _table_ctx(request, rows=rows, total=total, page=page,
                   per_page=per_page, total_pages=total_pages,
                   sort_by=sort_by, sort_dir=sort_dir, search=search,
                   date_from=date_from, date_to=date_to),
    )


# ── Fill Drawer (Position History row expand) ────────────────────────────────

async def _account_link_window_seconds(account_id: int) -> int:
    """HIGH-027 (Task 104a): one-shot lookup of the per-account link window
    (accounts.link_window_seconds). Returns DEFAULT_LINK_WINDOW_SECONDS if
    the account row is missing (defensive — shouldn't happen at runtime,
    but a deleted account shouldn't crash the history fragment).

    HIGH-002 (Task 142, Phase 6 routes): refactored to use
    `db.get_account_link_window_seconds` helper instead of `db._conn`
    direct access. The helper returns None for both "row missing" and
    "column NULL"; this wrapper applies the DEFAULT fallback.
    """
    from core.exec_link import DEFAULT_LINK_WINDOW_SECONDS
    value = await db.get_account_link_window_seconds(account_id)
    if value is None:
        return DEFAULT_LINK_WINDOW_SECONDS
    return int(value)


def _pretrade_ts_to_ms(pretrade: dict) -> int | None:
    """HIGH-027 (Task 104a): convert pre_trade_log.timestamp (ISO string)
    to epoch milliseconds. Returns None on parse failure — caller skips
    the window check in that case, which falls through to the pre-fix
    behavior (no reject). Defensive against malformed legacy rows."""
    ts = pretrade.get("timestamp")
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return None


@router.get("/fragments/history/position_fills", response_class=HTMLResponse)
async def frag_position_fills(request: Request, position_id: int = 0):
    """Return fills for a single closed position (lazy-loaded drawer)."""
    from api.helpers import _ctx
    from core.exec_link import get_exec_link_status

    fills = []
    if position_id:
        aid = app_state.active_account_id
        # HIGH-002 (Task 142): db._conn direct access replaced by helper.
        pos = await db.get_closed_position_terminal_key(position_id)
        if pos:
            # Phase 0.0.5 (T188) note: get_position_fills is now STRICT —
            # if pos["terminal_position_id"] is empty (Binance one-way
            # path where the engine WS never populates pos_id), this
            # returns []. The position-fills drawer will show no fills
            # for such rows until Phase 0.0.6's rebuild script
            # backfills terminal_position_id on existing closed_positions.
            # For Quantower-plugin users (pos_id always populated by the
            # plugin), this path is unchanged.
            fills = await db.get_position_fills(
                aid, pos["terminal_position_id"], pos["symbol"], pos["direction"],
            )
            # CRIT-001 fix: batch-fetch pre_trade_log and order_types instead of
            # per-fill queries. Previously: 2 queries per entry fill (~100 for
            # 50 fills). Now: 1 batched pre_trade_log + 1 batched orders, then
            # in-memory lookup during enrichment.
            entry_fills = [
                f for f in fills
                if not f.get("is_close") and f.get("calc_id")
            ]
            calc_ids = [f["calc_id"] for f in entry_fills]
            ex_order_ids = [
                f["exchange_order_id"] for f in entry_fills
                if f.get("exchange_order_id")
            ]
            ptl_by_id = await db.get_pretrade_logs_by_calc_ids(calc_ids)
            order_types = await db.get_order_types_by_ids(aid, ex_order_ids)
            # HIGH-027 (Task 104a): one-shot account link-window lookup;
            # reused for every fill in this position's drawer.
            account_link_window = await _account_link_window_seconds(aid)

            for f in fills:
                if f.get("is_close") or not f.get("calc_id"):
                    f["exec_link_status"] = ""
                    f["exec_match_count"] = 0
                    continue
                ptl = ptl_by_id.get(f["calc_id"])
                order_type = order_types.get(f.get("exchange_order_id", ""), "")
                pretrade_ts_ms = _pretrade_ts_to_ms(ptl) if ptl else None
                status, count = get_exec_link_status(
                    f, ptl, order_type,
                    fill_ts_ms=f.get("timestamp_ms"),
                    pretrade_ts_ms=pretrade_ts_ms,
                    account_link_window_seconds=account_link_window,
                )
                f["exec_link_status"] = status
                f["exec_match_count"] = count

    return templates.TemplateResponse(
        request, "fragments/history/position_fills.html",
        _ctx(request, fills=fills),
    )


# P8.T9: per-calc cap on the position-events drilldown. Generous for a single
# position's lifecycle; the endpoint flags + logs when a calc exceeds it rather
# than silently truncating (CLAUDE.md "No silent caps").
_POSITION_EVENTS_CAP = 500


@router.get("/fragments/history/position_events", response_class=HTMLResponse)
async def frag_position_events(request: Request, position_id: int = 0):
    """P8.T9 (plan §8.10): per-position trade-events timeline for the Position
    History drawer — lazy-loaded as a second section beside the fills sub-table.

    Reuses ``core.trade_event_log.query_trade_events`` (sync → ``to_thread``),
    scoped to the position's OWN calc_id(s), which are resolved from the
    ``positions_calcs`` junction by ``terminal_position_id``. A position can
    scale in from several calcs, so we union the events across all its calc_ids
    and merge them chronologically. Because each query filters ``calc_id`` to one
    of THIS position's calcs, a sibling position's events can never leak in.

    Positions with no calc_id — legacy rows + Phase-0.0.6/0.0.7 rebuilt rows
    that pre-date the calculator workflow (empty ``terminal_position_id`` or no
    junction rows) — render an EMPTY-STATE explaining the gap, NOT an error.
    """
    from api.helpers import _ctx
    from core.trade_event_log import query_trade_events
    import asyncio
    import json as _json

    events: list = []
    calc_ids: list = []
    truncated = False
    if position_id:
        aid = app_state.active_account_id
        pos = await db.get_closed_position_terminal_key(position_id)
        tpid = (pos or {}).get("terminal_position_id") or ""
        if tpid:
            # Distinct calc_ids in first-fill order (a scale-in position has
            # several junction rows; one calc may also appear on >1 order).
            seen = set()
            for link in await db.get_position_calc_links(tpid):
                cid = link.get("calc_id")
                if cid and cid not in seen:
                    seen.add(cid)
                    calc_ids.append(cid)
            for cid in calc_ids:
                rows, total = await asyncio.to_thread(
                    query_trade_events,
                    account_id=aid, calc_id=cid, limit=_POSITION_EVENTS_CAP,
                )
                # No silent caps (CLAUDE.md): query_trade_events returns the
                # NEWEST _POSITION_EVENTS_CAP rows; if a calc has more, the
                # OLDEST are dropped. Log it + flag the UI rather than implying
                # completeness with a partial "N events" count.
                if total > len(rows):
                    truncated = True
                    log.warning(
                        "position_events: calc %s has %d trade_events; showing "
                        "newest %d (oldest omitted)", cid, total, len(rows),
                    )
                events.extend(rows)
            # query_trade_events returns newest-first per calc; merge the unioned
            # rows oldest-first (ISO-8601 timestamps sort lexically == chrono).
            events.sort(key=lambda e: e.get("timestamp") or "")
            for e in events:                          # pre-parse for the summary
                try:
                    e["_payload"] = _json.loads(e.get("payload_json") or "{}")
                except (ValueError, TypeError):
                    e["_payload"] = {}

    return templates.TemplateResponse(
        request, "fragments/history/position_events.html",
        # position_id is the closed_positions PK — the same key the P7.T4/T5
        # export endpoint takes. Threaded through so the drawer can render the
        # Export-Audit buttons (Phase-8 deferred #2).
        _ctx(request, events=events, has_calc=bool(calc_ids),
             truncated=truncated, events_cap=_POSITION_EVENTS_CAP,
             position_id=position_id),
    )


def _has_tpsl_modification(events: list) -> bool:
    """True if any trade-event row marks a TP/SL price modification.

    Forward signal: P4.T4 ``position_amended`` rows whose ``field`` is
    ``tp_price``/``sl_price`` — the live source since the dead
    ``_detect_modification_events`` (which emitted ``tp_modified``/
    ``sl_modified``) was removed. Historical: legacy ``tp_modified``/
    ``sl_modified`` rows, now producerless but still present in older
    per-account DBs. Rows come from ``query_trade_events`` (raw dicts with
    ``event_type`` + unparsed ``payload_json``).
    """
    import json
    for e in events:
        et = e.get("event_type")
        if et in ("tp_modified", "sl_modified"):
            return True
        if et == "position_amended":
            try:
                fld = json.loads(e.get("payload_json") or "{}").get("field")
            except Exception:
                fld = None
            if fld in ("tp_price", "sl_price"):
                return True
    return False


@router.get("/fragments/history/exec_link", response_class=HTMLResponse)
async def frag_exec_link(request: Request, fill_id: int = 0):
    """Exec link comparison panel for a single fill."""
    from api.helpers import _ctx
    from core.exec_link import compute_exec_match

    fill = ptl = match = None
    order_type = ""
    has_modifications = False

    if fill_id:
        aid = app_state.active_account_id
        # HIGH-002 (Task 142): db._conn direct access replaced by helpers.
        # L271's order_type lookup reuses the existing
        # `get_order_by_exchange_id` (returns full row; we pull
        # `order_type` field) instead of a new field-specific helper.
        fill = await db.get_fill_by_id(fill_id, aid)

        if fill and fill.get("calc_id"):
            ptl = await db.get_pretrade_log_by_calc_id(fill["calc_id"])

            if fill.get("exchange_order_id"):
                orow = await db.get_order_by_exchange_id(aid, fill["exchange_order_id"])
                if orow:
                    order_type = orow.get("order_type") or ""

            # Check for TP/SL modifications on this calc_id
            try:
                from core.trade_event_log import query_trade_events
                import asyncio
                evts, _ = await asyncio.to_thread(
                    query_trade_events,
                    account_id=aid,
                    calc_id=fill["calc_id"],
                    event_type=None,
                    limit=100,
                )
                has_modifications = _has_tpsl_modification(evts)
            except Exception:
                pass

            if ptl:
                # HIGH-027 (Task 104a): pass timestamps + account window so
                # the comparison panel reflects window-rejection (a past-
                # window match shows as None here, which the template will
                # render as 'unlinked' or 'expired' once Task 104b lands).
                account_link_window = await _account_link_window_seconds(aid)
                pretrade_ts_ms = _pretrade_ts_to_ms(ptl)
                match = compute_exec_match(
                    fill, ptl, order_type,
                    fill_ts_ms=fill.get("timestamp_ms"),
                    pretrade_ts_ms=pretrade_ts_ms,
                    account_link_window_seconds=account_link_window,
                )

    return templates.TemplateResponse(
        request, "fragments/history/exec_link_panel.html",
        _ctx(request, fill=fill, ptl=ptl, match=match,
             has_modifications=has_modifications),
    )


@router.post("/history/exec_link/confirm", response_class=HTMLResponse)
async def confirm_exec_link(request: Request, fill_id: int = Form(0)):
    """Persist user-confirmed exec link on a fill."""
    # HIGH-002 (Task 142): db._conn UPDATE+commit replaced by helper.
    # No-op on fill_id=0 lives in the helper itself.
    await db.confirm_fill_exec_link(fill_id)
    return await frag_exec_link(request, fill_id=fill_id)


# ── Manual-link operator actions (P3.T2 / spec §6, §10.3) ────────────────────

# result string → (alert css class, operator-facing message). The handlers
# in core.link_actions funnel every link_status write through the
# core.link_state choke-point (spec §3.6). All branches return HTTP 200 so
# htmx swaps the discriminated body into the target — base.html's
# htmx:responseError handler swallows non-2xx bodies (T219 audit note).
_LINK_ACTION_MSG = {
    "linked":             ("alert-success", "Order linked to calc."),
    "marked":             ("alert-success", "Order marked unplanned."),
    "missing_calc_id":    ("alert-error",   "No calc selected."),
    "order_not_found":    ("alert-error",   "Order not found."),
    "already_linked":     ("alert-error",   "Order is already linked."),
    "calc_not_found":     ("alert-error",   "Calc not found."),
    "invalid_transition": ("alert-error",   "Order is not in a linkable state "
                                            "(only needs-review / unlinked orders)."),
    "race_lost":          ("alert-warning", "Order changed concurrently — refresh and retry."),
    "error":              ("alert-error",   "Action failed — see logs."),
}


def _link_action_fragment(result: str) -> HTMLResponse:
    cls, msg = _LINK_ACTION_MSG.get(result, ("alert-error", "Action failed."))
    return HTMLResponse(f'<div class="alert {cls}">{msg}</div>')


@router.post("/orders/{order_id}/manual_link", response_class=HTMLResponse)
async def manual_link(order_id: int, calc_id: str = Form("")):
    """P3.T2 (plan §3 task 3.3): operator links an order to a calc.

    Routes the order NEEDS_MANUAL_REVIEW|UNLINKED → LINKED transition through
    the core.link_state choke-point and flips the calc active|released →
    matched (via core.link_actions.manual_link_order). Returns a 200
    status-discriminated HTML fragment (htmx swaps it; see _LINK_ACTION_MSG).
    """
    from core.link_actions import manual_link_order
    result = await manual_link_order(app_state.active_account_id, order_id, calc_id)
    return _link_action_fragment(result)


@router.post("/orders/{order_id}/mark_unplanned", response_class=HTMLResponse)
async def mark_unplanned(order_id: int):
    """P3.T2 (plan §3 task 3.4): operator downgrades an order to UNPLANNED
    (NEEDS_MANUAL_REVIEW|UNLINKED → UNPLANNED via the choke-point)."""
    from core.link_actions import mark_order_unplanned
    result = await mark_order_unplanned(app_state.active_account_id, order_id)
    return _link_action_fragment(result)


@router.get("/orders/needs_review")
async def needs_review():
    """P3.T2 (plan §3 task 3.5): the manual-link review queue —
    NEEDS_MANUAL_REVIEW + UNLINKED orders with per-order candidate calcs +
    per-criterion diff. Returns JSON data; the needs-link tab UI (P3.T3)
    renders it."""
    from core.link_actions import list_needs_review
    orders = await list_needs_review(app_state.active_account_id)
    return JSONResponse({"orders": orders, "count": len(orders)})


@router.get("/orders/needs_link", response_class=HTMLResponse)
async def needs_link_page(request: Request):
    """P3.T3 (plan §3 task 3.6): the needs-link tab page. Thin shell that
    lazy-loads the queue fragment (GET /fragments/needs_link)."""
    from api.helpers import _ctx
    return templates.TemplateResponse(
        request, "orders/needs_link.html", _ctx(request, active_page="needs_link"),
    )


@router.get("/fragments/needs_link", response_class=HTMLResponse)
async def frag_needs_link(request: Request):
    """P3.T3: the manual-link review queue fragment — NEEDS_MANUAL_REVIEW +
    UNLINKED orders, each with its candidate calcs + per-criterion diff and
    Link / Mark-UNPLANNED action buttons (POSTing to the choke-pointed P3.T2
    endpoints). Server-side render of core.link_actions.list_needs_review —
    the same data the JSON GET /orders/needs_review returns."""
    from core.link_actions import list_needs_review
    orders = await list_needs_review(app_state.active_account_id)
    return templates.TemplateResponse(
        request, "fragments/needs_link_queue.html",
        _table_ctx(request, orders=orders),
    )


@router.get("/fragments/needs_link_count", response_class=HTMLResponse)
async def frag_needs_link_count():
    """P3.T4 (plan §3 task 3.8): live nav-badge counter for the Needs Link
    tab — count of NEEDS_MANUAL_REVIEW + UNLINKED orders for the active
    account. Returns an amber count badge, or EMPTY when the queue is clear
    (so the nav shows no '0' badge). Polled by the nav span every 5s."""
    count = await db.count_needs_link(app_state.active_account_id)
    if not count:
        return HTMLResponse("")
    return HTMLResponse(
        f'<span class="badge badge-yellow" style="margin-left:5px;">{count}</span>'
    )


# ── Backfill + consistency ───────────────────────────────────────────────────

@router.post("/api/orders/backfill")
async def backfill_from_exchange_history(days: int = 30):
    """One-time migration: populate fills + closed_positions from exchange_history."""
    result = await db.backfill_fills_from_exchange_history(
        account_id=app_state.active_account_id, days=days,
    )
    return JSONResponse(result)


@router.get("/api/orders/consistency")
async def check_data_consistency():
    """Run data consistency checks on order-domain tables."""
    result = await db.validate_order_data_consistency(
        account_id=app_state.active_account_id,
    )
    return JSONResponse(result)
