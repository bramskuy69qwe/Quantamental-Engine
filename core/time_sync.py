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

WARN_THRESHOLD_MS = 500
CRITICAL_THRESHOLD_MS = 2000


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
    """Record a new offset measurement."""
    s = _statuses.get(exchange_id)
    if s is None:
        s = SyncStatus(exchange_id=exchange_id)
        _statuses[exchange_id] = s
    s.offset_ms = offset_ms
    s.last_synced = time.monotonic()
    s.sync_failed = False
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
