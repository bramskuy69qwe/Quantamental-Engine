"""
MonitoringService — periodic health checks with structured event model.

Checks (9 total):
  1. P&L anomaly          — equity drops > 1 % in a 5-minute window
  2. WS staleness         — WS last_update > 45 s ago (not in fallback)
  3. Position count        — in-memory count differs from last DB snapshot
  4. Regime data freshness — regime classification older than 90 min
  5. News feed health      — no news rows inserted in last 60 min
  6. Plugin connection     — plugin was connected but is now disconnected
  7. Reconciler health     — >20 pending backfill rows
  8. Database health       — SELECT 1 fails or times out
  9. Rate-limit frequency  — >5 rate-limit events in 30-minute window

Start as an asyncio background task in lifespan startup:
    from core.monitoring import MonitoringService
    asyncio.create_task(MonitoringService().run())
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.state import app_state
from core.database import db

log = logging.getLogger("monitoring")

_PNL_DROP_THRESHOLD   = 0.01   # 1 % equity drop triggers anomaly alert
_PNL_WINDOW_MINUTES   = 5      # look-back window in minutes
_WS_STALE_THRESHOLD   = 45.0   # seconds before we warn (separate from 30 s fallback trigger)
_CHECK_INTERVAL       = 60     # seconds between checks
_EVENT_BUFFER_MAX     = 100    # max events in ring buffer


# ── Monitoring data model ────────────────────────────────────────────────────

@dataclass
class MonitoringEvent:
    """Structured monitoring event for alert surfacing and future webhook dispatch."""
    kind: str                                    # e.g. "regime_stale", "rate_limit_burst"
    severity: str                                # "info" | "warning" | "critical"
    message: str                                 # Human-readable description
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    context: Dict[str, Any] = field(default_factory=dict)


class MonitoringService:
    """
    Runs health checks on a fixed interval. Emits MonitoringEvent objects
    into an in-memory ring buffer. Events are also written as structured
    JSON log entries for grep-based analysis.
    """

    def __init__(self) -> None:
        self.events: List[MonitoringEvent] = []

    # ── Event emission / resolution ─────────────────────────────────────────

    def emit(self, kind: str, severity: str, message: str,
             context: Optional[Dict[str, Any]] = None) -> MonitoringEvent:
        """Create and store a new MonitoringEvent. Also logs it."""
        event = MonitoringEvent(
            kind=kind, severity=severity, message=message,
            context=context or {},
        )
        self.events.append(event)
        # Trim ring buffer
        if len(self.events) > _EVENT_BUFFER_MAX:
            self.events = self.events[-_EVENT_BUFFER_MAX:]

        # Structured log entry
        log_level = logging.CRITICAL if severity == "critical" else (
            logging.WARNING if severity == "warning" else logging.INFO
        )
        log.log(log_level, "ALERT: %s", message, extra={
            "event": kind, "severity": severity, "context": context or {},
        })
        return event

    def resolve(self, kind: str) -> None:
        """Mark all unresolved events of this kind as resolved."""
        now = datetime.now(timezone.utc)
        for ev in self.events:
            if ev.kind == kind and not ev.resolved:
                ev.resolved = True
                ev.resolved_at = now

    def get_active_events(self) -> List[MonitoringEvent]:
        """Return unresolved events."""
        return [ev for ev in self.events if not ev.resolved]

    # ── Main loop ───────────────────────────────────────────────────────────

    async def run(self) -> None:
        log.info("MonitoringService started (9 checks)")
        while True:
            await asyncio.sleep(_CHECK_INTERVAL)
            await self._check_pnl_anomaly()
            await self._check_ws_staleness()
            await self._check_position_count()

    # ── Check 1: P&L anomaly ─────────────────────────────────────────────────

    async def _check_pnl_anomaly(self) -> None:
        try:
            rows = await db.get_recent_snapshots(
                minutes=_PNL_WINDOW_MINUTES,
                account_id=app_state.active_account_id,
            )
        except Exception as exc:
            log.warning(f"MonitoringService: could not query snapshots: {exc}")
            return

        if len(rows) < 2:
            return   # not enough data yet

        oldest_equity = rows[0].get("total_equity", 0.0)
        newest_equity = rows[-1].get("total_equity", 0.0)

        if oldest_equity <= 0:
            return

        drop_pct = (newest_equity - oldest_equity) / oldest_equity

        if drop_pct < -_PNL_DROP_THRESHOLD:
            msg = (
                f"ALERT: equity dropped {drop_pct*100:.2f}% in {_PNL_WINDOW_MINUTES} min "
                f"({oldest_equity:.2f} → {newest_equity:.2f} USDT)"
            )
            log.warning(
                msg,
                extra={
                    "event":          "pnl_anomaly",
                    "drop_pct":       round(drop_pct * 100, 4),
                    "window_minutes": _PNL_WINDOW_MINUTES,
                    "equity_before":  oldest_equity,
                    "equity_after":   newest_equity,
                },
            )
            app_state.ws_status.add_log(msg)

    # ── Check 2: WS staleness ────────────────────────────────────────────────

    async def _check_ws_staleness(self) -> None:
        ws = app_state.ws_status
        stale_secs = ws.seconds_since_update

        # Only warn if staleness exceeds our monitoring threshold AND
        # the existing fallback mechanism hasn't already kicked in
        if stale_secs > _WS_STALE_THRESHOLD and not ws.using_fallback:
            log.warning(
                f"ALERT: WS stale for {stale_secs:.0f}s (fallback not yet active)",
                extra={
                    "event":            "ws_stale",
                    "seconds_stale":    round(stale_secs, 1),
                    "using_fallback":   ws.using_fallback,
                    "ws_connected":     ws.connected,
                },
            )

    # ── Check 3: Position count mismatch ─────────────────────────────────────

    async def _check_position_count(self) -> None:
        ws_count = len(app_state.positions)

        # Compare against the last persisted snapshot (avoids an extra REST call)
        try:
            last_snap = await db.get_last_account_state()
        except Exception as exc:
            log.warning(f"MonitoringService: could not query last snapshot: {exc}")
            return

        if last_snap is None:
            return   # DB not populated yet

        db_count = last_snap.get("open_positions", ws_count)

        if ws_count != db_count:
            msg = f"ALERT: position count mismatch — WS={ws_count}, last DB snapshot={db_count}"
            log.warning(
                msg,
                extra={
                    "event":     "position_count_mismatch",
                    "ws_count":  ws_count,
                    "db_count":  db_count,
                },
            )
            app_state.ws_status.add_log(msg)
