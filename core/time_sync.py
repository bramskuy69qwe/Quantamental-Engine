"""
Exchange server-time sync — caches local-vs-exchange clock offset.

Offset = exchange_time_ms - local_time_ms.  Adding offset to local time
gives (approximate) exchange time.  Used to correct WS latency calc and
surface clock-skew warnings.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

log = logging.getLogger("time_sync")

# v3.0 operator clock-drift bug: CRITICAL lowered 2000 → 1000 to match the
# Binance HARD limit. Binance rejects any SIGNED request whose timestamp is
# more than 1000ms AHEAD of server time with error -1021 ("Timestamp for this
# request was 1000ms ahead of the server's time"), REGARDLESS of recvWindow —
# recvWindow only tolerates being LATE. So a +1000ms local drift breaks every
# account/funding/positions read (the operator's "no proper data showed"),
# yet the old 2000ms critical bar rendered it as merely "warn". 500ms stays
# the early-warning bar; ≥1000ms is now correctly critical.
#
# NB the threshold is on abs(offset): a drift the other way (local BEHIND) is
# tolerated by recvWindow up to ~10s, so ≥1000ms behind is over-flagged — but
# over-warning about an unreliable OS clock is the safe direction.
WARN_THRESHOLD_MS = 500
CRITICAL_THRESHOLD_MS = 1000


@dataclass
class SyncStatus:
    exchange_id: str
    offset_ms: float = 0.0
    last_synced: float = 0.0     # monotonic timestamp of last successful sync
    sync_failed: bool = False

    @property
    def severity(self) -> str:
        """'ok' | 'warn' | 'critical' | 'failed'."""
        if self.sync_failed:
            return "failed"
        a = abs(self.offset_ms)
        if a >= CRITICAL_THRESHOLD_MS:
            return "critical"
        if a >= WARN_THRESHOLD_MS:
            return "warn"
        return "ok"


_statuses: Dict[str, SyncStatus] = {}


def update(exchange_id: str, offset_ms: float) -> None:
    """Record a new offset measurement.

    Emits an honest WARNING on the TRANSITION into warn/critical drift (and an
    INFO when it clears). This is the operator-visible fix for "the terminal
    says synced but throws timestamp errors below": the server-time fetch is
    UNSIGNED (/fapi/v1/time works with any local clock, so the sync itself
    'succeeds'), while SIGNED reads fail with -1021 — so a silent debug line
    plus cryptic -1021s gave no clear cause. Transition-only so a persistently
    drifted clock does not spam every poll (the UI banner is the standing
    reminder).
    """
    s = _statuses.get(exchange_id)
    prev_sev = s.severity if s is not None else "ok"
    if s is None:
        s = SyncStatus(exchange_id=exchange_id)
        _statuses[exchange_id] = s
    s.offset_ms = offset_ms
    s.last_synced = time.monotonic()
    s.sync_failed = False
    new_sev = s.severity
    if new_sev in ("warn", "critical") and new_sev != prev_sev:
        # offset = server - local, so local drift = -offset (positive ⇒ ahead).
        log.warning(
            "CLOCK DRIFT: local clock is %+.0fms vs %s server (severity=%s). "
            "Binance rejects SIGNED requests >1000ms AHEAD with -1021 "
            "(account/funding/positions reads fail) — sync the OS clock.",
            -offset_ms, exchange_id, new_sev,
        )
    elif new_sev == "ok" and prev_sev in ("warn", "critical"):
        log.info("Clock drift cleared for %s (offset %+.0fms).", exchange_id, offset_ms)
    else:
        log.debug("Time sync %s: offset %.1fms", exchange_id, offset_ms)


def mark_failed(exchange_id: str) -> None:
    """Mark sync as failed (keeps last known offset)."""
    s = _statuses.get(exchange_id)
    if s is None:
        s = SyncStatus(exchange_id=exchange_id, sync_failed=True)
        _statuses[exchange_id] = s
    else:
        s.sync_failed = True


def get_offset_ms(exchange_id: str) -> float:
    """Current offset; 0.0 if never synced."""
    s = _statuses.get(exchange_id)
    return s.offset_ms if s else 0.0


def get_status(exchange_id: str) -> Optional[SyncStatus]:
    return _statuses.get(exchange_id)


def get_all() -> Dict[str, SyncStatus]:
    return dict(_statuses)


def worst_severity() -> str:
    """Return the worst severity across all exchanges."""
    if not _statuses:
        return "ok"
    levels = {"ok": 0, "warn": 1, "critical": 2, "failed": 3}
    worst = max(_statuses.values(), key=lambda s: levels.get(s.severity, 0))
    return worst.severity
