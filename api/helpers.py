"""
Shared helpers for all API route modules.

Exports: templates, _fmt, _fmt_duration, _ctx, _paginate_list, _table_ctx,
         _maybe_backfill_equity, _get_funding_cached,
         _backfill_lock, _backfill_earliest_ms, _FUNDING_CACHE
"""
from __future__ import annotations

import asyncio
import logging
import os
import time as _time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import Request
from fastapi.templating import Jinja2Templates

from core.state import app_state, TZ_LOCAL
from core.database import db
from core.exchange import build_equity_backfill, fetch_funding_rates
from core.analytics import compute_funding_exposure
from core.account_registry import account_registry

log = logging.getLogger("routes")

# ── Equity backfill cache ─────────────────────────────────────────────────────
_backfill_lock = asyncio.Lock()
_backfill_earliest_ms: Dict[int, Optional[int]] = {}


async def _maybe_backfill_equity(needed_start_ms: int, account_id: Optional[int] = None) -> None:
    aid = account_id if account_id is not None else app_state.active_account_id
    cached = _backfill_earliest_ms.get(aid)

    if cached is not None and cached <= needed_start_ms:
        return

    earliest_ms = await db.get_earliest_snapshot_ms(account_id=aid)
    if earliest_ms is not None:
        if cached is None or earliest_ms < cached:
            _backfill_earliest_ms[aid] = earliest_ms
            cached = _backfill_earliest_ms[aid]

    if cached is not None and cached <= needed_start_ms:
        return

    async with _backfill_lock:
        cached = _backfill_earliest_ms.get(aid)
        if cached is not None and cached <= needed_start_ms:
            return

        current_equity = app_state.account_state.total_equity
        if current_equity == 0:
            return

        await db.clear_backfill_snapshots(account_id=aid)
        await db.clear_cashflow_events(account_id=aid)

        real_earliest_ms = await db.get_earliest_snapshot_ms(account_id=aid)
        end_for_backfill = real_earliest_ms if real_earliest_ms else int(_time.time() * 1000)

        records, cashflow_records = await build_equity_backfill(
            needed_start_ms, end_for_backfill, current_equity
        )
        if records:
            count = await db.insert_backfill_snapshots(records, before_ms=end_for_backfill, account_id=aid)
            log.info("Equity backfill: inserted %d synthetic snapshots", count)
            _backfill_earliest_ms[aid] = records[0][0]
        else:
            _backfill_earliest_ms[aid] = real_earliest_ms

        if cashflow_records:
            cf_count = await db.insert_cashflow_events(cashflow_records, account_id=aid)
            log.info("Equity backfill: inserted %d cashflow events", cf_count)


# ── Funding rate cache ────────────────────────────────────────────────────────
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
        funding_data = await fetch_funding_rates(symbols)
    except Exception:
        funding_data = {}
    from datetime import timezone as _tz
    total_8h = 0.0
    total_day = 0.0
    items: List[Dict[str, Any]] = []
    for p in positions:
        fd = funding_data.get(p.ticker, {})
        rate = fd.get("funding_rate", 0.0)
        nft = fd.get("next_funding_time", 0)
        notional = abs(p.position_value_usdt)
        exp = compute_funding_exposure(notional, rate)
        adverse = (rate > 0) if p.direction == "LONG" else (rate < 0)
        nft_str = "—"
        if nft > 0:
            nft_dt = datetime.fromtimestamp(nft / 1000, tz=_tz.utc).astimezone(TZ_LOCAL)
            nft_str = nft_dt.strftime("%H:%M")
        total_8h += exp["per_8h"]
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


# ── Templates ─────────────────────────────────────────────────────────────────
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(_BASE_DIR, "templates"))


def _fmt(val, decimals=2, suffix=""):
    try:
        return f"{float(val):,.{decimals}f}{suffix}"
    except (TypeError, ValueError):
        return str(val)


def _fmt_duration(ms) -> str:
    """Format a millisecond duration as a compact hold-time string."""
    try:
        total_s = max(0, int(float(ms)) // 1000)
    except (TypeError, ValueError):
        return "—"
    d = total_s // 86400
    h = (total_s % 86400) // 3600
    m = (total_s % 3600) // 60
    s = total_s % 60
    parts = []
    if d:
        parts.append(f"{d}d")
    if d or h:
        parts.append(f"{h:02d}h")
    if d or h or m:
        parts.append(f"{m:02d}m")
    parts.append(f"{s:02d}s")
    return " ".join(parts)


templates.env.globals["fmt"] = _fmt
templates.env.globals["fmt_duration"] = _fmt_duration


def _ctx(request: Request, **extra) -> dict:
    """Base template context for every page render."""
    from core.platform_bridge import platform_bridge
    return {
        "now":               datetime.now(TZ_LOCAL).strftime("%Y-%m-%d %H:%M:%S"),
        "ws_status":         app_state.ws_status,
        "plugin_connected":  platform_bridge.is_connected,
        "params":            app_state.params,
        "is_initializing":   app_state.is_initializing,
        "active_account_id": app_state.active_account_id,
        "active_platform":   app_state.active_platform,
        "accounts":          account_registry.list_accounts_sync(),
        **extra,
    }


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
    """In-memory pagination/sort/filter for list-backed tables."""
    if search:
        term = search.lower()
        data = [r for r in data if any(
            term in str(r.get(f, "")).lower() for f in search_fields
        )]
    if filters:
        for col, val in filters.items():
            if val:
                data = [r for r in data if str(r.get(col, "")).lower() == val.lower()]
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
    """Minimal context for table fragments — no full _ctx overhead needed."""
    return {**kw}
