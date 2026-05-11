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

import time as _time

_PNL_DROP_THRESHOLD          = 0.01   # 1 % equity drop triggers anomaly alert
_PNL_WINDOW_MINUTES          = 5      # look-back window in minutes
_WS_STALE_THRESHOLD          = 45.0   # seconds before we warn (separate from 30 s fallback trigger)
_CHECK_INTERVAL              = 60     # seconds between checks
_EVENT_BUFFER_MAX            = 100    # max events in ring buffer
_NEWS_STALE_MINUTES          = 60     # no news rows in 60 min → alert (observed 5-15 min cadence)
_RECONCILER_PENDING_THRESHOLD = 20    # >20 uncalculated rows → alert (AN-1 data)
_DB_HEALTH_TIMEOUT           = 5.0    # seconds for SELECT 1
_RATE_LIMIT_BURST_THRESHOLD  = 5      # events in window → alert
_RATE_LIMIT_BURST_WINDOW     = 30 * 60  # 30 minutes (from RL-4 May 10 pattern)


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


# ── SC-2: Ready-state evaluator ──────────────────────────────────────────────

_STALE_GATE_SECONDS = 60   # sustained data staleness before not-ready (hysteresis)


class ReadyStateEvaluator:
    """Bidirectional ready-state with hysteresis.

    Evaluates three gates:
      1. Bootstrap complete (sticky-once-achieved)
      2. Account data present (equity > 0)
      3. Data flowing (WS or REST fallback, with 60s sustained-fault hysteresis)

    Rate-limit alone does NOT gate — only when co-occurring with sustained
    data staleness (rate-limited AND stale for the full hysteresis window).
    This is sustained conjunction, not point-in-time: both conditions must
    persist for the entire _STALE_GATE_SECONDS window.
    """

    def evaluate(self) -> tuple:
        """Return (ready: bool, reason: str). Empty reason when ready."""
        # Gate 1: Bootstrap must be complete (sticky-once-achieved)
        if app_state.is_initializing:
            return False, "Engine initializing"

        # Gate 2: Account data must be present (hard fault)
        if app_state.account_state.total_equity <= 0:
            return False, "Account data not loaded (equity=0)"

        # Gate 3: Data must be flowing — sustained staleness gate
        # WS fallback keeps seconds_since_update <15s even when WS is down.
        # Only gate when BOTH WS and REST have failed for >60s.
        ws = app_state.ws_status
        stale_s = ws.seconds_since_update
        if stale_s > _STALE_GATE_SECONDS:
            return False, f"Exchange data offline ({stale_s:.0f}s stale)"

        return True, ""


class MonitoringService:
    """
    Runs health checks on a fixed interval. Emits MonitoringEvent objects
    into an in-memory ring buffer. Events are also written as structured
    JSON log entries for grep-based analysis.
    """

    def __init__(self) -> None:
        self.events: List[MonitoringEvent] = []
        self._ever_plugin_connected: bool = False
        self._rate_limit_timestamps: List[tuple] = []  # [(epoch_s, was_ban), ...]
        self._cycle_count: int = 0

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
            self._cycle_count += 1
            # Original 3 checks (every cycle)
            await self._check_pnl_anomaly()
            await self._check_ws_staleness()
            await self._check_position_count()
            # New checks 4-7 (every cycle — fast, in-memory reads)
            self._check_regime_freshness_sync()
            self._check_plugin_connection_sync()
            self._check_rate_limit_frequency_sync()
            # Check 5: news feed (every cycle, lightweight DB query)
            await self._check_news_feed_health()
            # Check 7: reconciler health (every 5th cycle = 5 min)
            if self._cycle_count % 5 == 0:
                await self._check_reconciler_health()
            # Check 8: DB health (every 2nd cycle = 2 min)
            if self._cycle_count % 2 == 0:
                await self._check_db_health()

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

    # ── Check 4: Regime data freshness ───────────────────────────────────────

    def _check_regime_freshness_sync(self) -> None:
        regime = app_state.current_regime
        if regime is None or regime.is_stale:
            if not any(e.kind == "regime_stale" and not e.resolved for e in self.events):
                age = "unknown"
                if regime and regime.computed_at:
                    age_min = (datetime.now(timezone.utc) - regime.computed_at).total_seconds() / 60
                    age = f"{age_min:.0f} min"
                self.emit("regime_stale", "warning",
                          f"Regime data stale ({age} since last classification)",
                          {"age": age})
        else:
            self.resolve("regime_stale")

    # ── Check 5: News feed health ────────────────────────────────────────────

    async def _check_news_feed_health(self) -> None:
        try:
            async with db._conn.execute(
                "SELECT MAX(published_at) FROM news"
            ) as cur:
                row = await cur.fetchone()
                latest_ts = row[0] if row else None
        except Exception:
            return  # News table may not exist or DB unavailable

        if latest_ts is None:
            return  # No news data yet

        try:
            if isinstance(latest_ts, (int, float)):
                latest = datetime.fromtimestamp(latest_ts / 1000, tz=timezone.utc)
            else:
                latest = datetime.fromisoformat(str(latest_ts).replace("Z", "+00:00"))
            age_min = (datetime.now(timezone.utc) - latest).total_seconds() / 60
        except Exception:
            return

        if age_min > _NEWS_STALE_MINUTES:
            if not any(e.kind == "news_stale" and not e.resolved for e in self.events):
                self.emit("news_stale", "info",
                          f"No news data in {age_min:.0f} min (threshold: {_NEWS_STALE_MINUTES})",
                          {"age_minutes": round(age_min, 1), "threshold": _NEWS_STALE_MINUTES})
        else:
            self.resolve("news_stale")

    # ── Check 6: Plugin connection health ────────────────────────────────────

    def _check_plugin_connection_sync(self, plugin_connected: Optional[bool] = None) -> None:
        if plugin_connected is None:
            try:
                from core.platform_bridge import platform_bridge
                plugin_connected = platform_bridge.is_connected
            except Exception:
                return

        if plugin_connected:
            self._ever_plugin_connected = True
            self.resolve("plugin_disconnected")
            return

        if not self._ever_plugin_connected:
            return  # Standalone mode — don't alert

        if not any(e.kind == "plugin_disconnected" and not e.resolved for e in self.events):
            self.emit("plugin_disconnected", "warning",
                      "Plugin was connected but is now disconnected — using exchange fallback")

    # ── Check 7: Reconciler health ───────────────────────────────────────────

    async def _check_reconciler_health(self) -> None:
        try:
            async with db._conn.execute(
                "SELECT COUNT(*) FROM exchange_history"
                " WHERE NOT backfill_completed AND open_time>0"
                " AND trade_key NOT LIKE 'qt:%'"
            ) as cur:
                row = await cur.fetchone()
                pending = row[0] if row else 0
        except Exception:
            return

        if pending > _RECONCILER_PENDING_THRESHOLD:
            if not any(e.kind == "reconciler_backlog" and not e.resolved for e in self.events):
                self.emit("reconciler_backlog", "warning",
                          f"Reconciler has {pending} pending rows (threshold: {_RECONCILER_PENDING_THRESHOLD})",
                          {"pending_rows": pending, "threshold": _RECONCILER_PENDING_THRESHOLD})
        else:
            self.resolve("reconciler_backlog")

    # ── Check 8: Database health ─────────────────────────────────────────────

    async def _check_db_health(self) -> None:
        try:
            async with db._conn.execute("SELECT 1") as cur:
                await asyncio.wait_for(cur.fetchone(), timeout=_DB_HEALTH_TIMEOUT)
            self.resolve("db_unreachable")
        except Exception:
            if not any(e.kind == "db_unreachable" and not e.resolved for e in self.events):
                self.emit("db_unreachable", "critical",
                          "Database health check failed (SELECT 1 timeout or error)",
                          {"timeout_s": _DB_HEALTH_TIMEOUT})

    # ── Check 9: Rate-limit frequency ────────────────────────────────────────

    def record_rate_limit_event(self, was_ban: bool = False) -> None:
        """Called by handle_rate_limit_error() to record a rate-limit event."""
        self._rate_limit_timestamps.append((_time.time(), was_ban))

    def _check_rate_limit_frequency_sync(self) -> None:
        now = _time.time()
        cutoff = now - _RATE_LIMIT_BURST_WINDOW
        self._rate_limit_timestamps = [
            (ts, ban) for ts, ban in self._rate_limit_timestamps if ts >= cutoff
        ]

        bans = [ts for ts, ban in self._rate_limit_timestamps if ban]
        if bans:
            if not any(e.kind == "rate_limit_ban" and not e.resolved for e in self.events):
                self.emit("rate_limit_ban", "critical",
                          "IP ban (418) detected in rate-limit window",
                          {"ban_count": len(bans), "window_minutes": _RATE_LIMIT_BURST_WINDOW // 60})
        else:
            self.resolve("rate_limit_ban")

        count = len(self._rate_limit_timestamps)
        if count >= _RATE_LIMIT_BURST_THRESHOLD:
            if not any(e.kind == "rate_limit_burst" and not e.resolved for e in self.events):
                self.emit("rate_limit_burst", "warning",
                          f"{count} rate-limit events in {_RATE_LIMIT_BURST_WINDOW // 60} min "
                          f"(threshold: {_RATE_LIMIT_BURST_THRESHOLD})",
                          {"count": count, "window_minutes": _RATE_LIMIT_BURST_WINDOW // 60,
                           "threshold": _RATE_LIMIT_BURST_THRESHOLD})
        else:
            self.resolve("rate_limit_burst")
