"""
Equity gap detection for account_snapshots.

Identifies time windows where no snapshots exist, indicating engine
downtime or data loss. Called at analytics query time to flag degraded
results.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

log = logging.getLogger("equity_gap_detector")


@dataclass
class Gap:
    start_ms: int
    end_ms: int
    duration_ms: int


def detect_gaps(
    account_id: int,
    since_ms: int,
    until_ms: int,
    *,
    expected_interval_seconds: int = 600,
    db_path: Optional[str] = None,
) -> List[Gap]:
    """Detect gaps in account_snapshots within the given window.

    A gap is any interval between consecutive snapshots that exceeds
    2x the expected_interval. Returns sorted list of Gap objects.

    Args:
        account_id: Account to check.
        since_ms: Window start (epoch ms).
        until_ms: Window end (epoch ms).
        expected_interval_seconds: Normal snapshot cadence (default 10 min).
        db_path: Override for testing.
    """
    if db_path is None:
        try:
            from core.db_account_settings import _resolve_db_path
            db_path = _resolve_db_path(account_id)
        except Exception:
            return []

    threshold_ms = expected_interval_seconds * 2 * 1000

    since_iso = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc).isoformat()
    until_iso = datetime.fromtimestamp(until_ms / 1000, tz=timezone.utc).isoformat()

    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT snapshot_ts FROM account_snapshots "
            "WHERE account_id = ? AND snapshot_ts >= ? AND snapshot_ts <= ? "
            "ORDER BY snapshot_ts ASC",
            (account_id, since_iso, until_iso),
        ).fetchall()
        conn.close()
    except Exception:
        return []

    if len(rows) < 2:
        return []

    # Convert ISO timestamps to epoch ms for gap math
    timestamps_ms: List[int] = []
    for (ts_str,) in rows:
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            timestamps_ms.append(int(dt.timestamp() * 1000))
        except Exception:
            continue

    gaps: List[Gap] = []
    for i in range(1, len(timestamps_ms)):
        delta_ms = timestamps_ms[i] - timestamps_ms[i - 1]
        if delta_ms > threshold_ms:
            gaps.append(Gap(
                start_ms=timestamps_ms[i - 1],
                end_ms=timestamps_ms[i],
                duration_ms=delta_ms,
            ))

    return gaps
