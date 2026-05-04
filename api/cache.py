"""
Mutable caching state for API routes.

Equity backfill cache   — avoids re-fetching income history on every page load.
Funding rate cache      — background-refreshed every 60 s while positions are open.
"""
from __future__ import annotations

import asyncio
import logging
import time as _time
from typing import Dict, List, Optional

from core.state import app_state
from core.database import db
from core.exchange import build_equity_backfill, fetch_funding_rates

log = logging.getLogger("routes")

# ── Equity backfill cache ────────────────────────────────────────────────────
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


# ── Funding rate cache ───────────────────────────────────────────────────────
# Raw rates from REST (refresh every 60s). Exposure computed at render time
# from cached rates + live notional so the dashboard gets 0.5 Hz updates.
_FUNDING_RATES: Dict[str, Dict] = {}   # symbol -> {funding_rate, next_funding_time}
_FUNDING_RATES_TS: float = 0.0
_FUNDING_REFRESHING = False


async def _ensure_funding_rates() -> None:
    """Trigger background funding rate refresh if stale. Non-blocking."""
    global _FUNDING_REFRESHING
    if _time.monotonic() - _FUNDING_RATES_TS >= 60.0 and not _FUNDING_REFRESHING:
        _FUNDING_REFRESHING = True
        asyncio.create_task(_refresh_funding_rates_bg())


async def _refresh_funding_rates_bg() -> None:
    global _FUNDING_REFRESHING, _FUNDING_RATES, _FUNDING_RATES_TS
    try:
        positions = app_state.positions
        if not positions:
            return
        data = await fetch_funding_rates([p.ticker for p in positions])
        _FUNDING_RATES = data
        _FUNDING_RATES_TS = _time.monotonic()
    except Exception:
        pass
    finally:
        _FUNDING_REFRESHING = False


def get_funding_lines() -> List[str]:
    """Build funding lines from cached rates + live positions. O(n), no I/O."""
    lines = []
    for p in app_state.positions:
        rate = _FUNDING_RATES.get(p.ticker, {}).get("funding_rate", 0.0)
        sign = "+" if rate >= 0 else ""
        lines.append(f"{p.ticker} {sign}{rate * 100:.4f}%")
    return lines
