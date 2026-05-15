"""Tests for equity gap detection."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from core.equity_gap_detector import Gap, detect_gaps


def _make_db(tmp_path, snapshots=None):
    """Create a DB with account_snapshots rows."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO accounts VALUES (1)")
    conn.execute("""CREATE TABLE account_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        snapshot_ts TEXT NOT NULL,
        total_equity REAL NOT NULL DEFAULT 0
    )""")
    if snapshots:
        for ts_ms, equity in snapshots:
            dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            conn.execute(
                "INSERT INTO account_snapshots (account_id, snapshot_ts, total_equity) "
                "VALUES (1, ?, ?)",
                (dt.isoformat(), equity),
            )
    conn.commit()
    conn.close()
    return db_path


_BASE = int(datetime(2026, 5, 15, tzinfo=timezone.utc).timestamp() * 1000)
_MIN = 60_000  # 1 minute in ms


class TestGapDetection:
    def test_no_gaps_regular_interval(self, tmp_path):
        """5 snapshots at 5-minute intervals → no gaps (threshold = 10 min)."""
        snapshots = [(_BASE + i * 5 * _MIN, 10000) for i in range(5)]
        db_path = _make_db(tmp_path, snapshots)
        gaps = detect_gaps(1, _BASE, _BASE + 25 * _MIN,
                           expected_interval_seconds=300, db_path=db_path)
        assert gaps == []

    def test_one_gap_in_middle(self, tmp_path):
        """Snapshot at 0, 5, 35, 40 min → gap between 5 and 35 (30 min)."""
        snapshots = [
            (_BASE, 10000),
            (_BASE + 5 * _MIN, 10000),
            (_BASE + 35 * _MIN, 9800),  # 30-min gap
            (_BASE + 40 * _MIN, 9800),
        ]
        db_path = _make_db(tmp_path, snapshots)
        gaps = detect_gaps(1, _BASE, _BASE + 45 * _MIN,
                           expected_interval_seconds=300, db_path=db_path)
        assert len(gaps) == 1
        assert gaps[0].start_ms == _BASE + 5 * _MIN
        assert gaps[0].end_ms == _BASE + 35 * _MIN
        assert gaps[0].duration_ms == 30 * _MIN

    def test_multiple_gaps(self, tmp_path):
        """Two gaps detected separately."""
        snapshots = [
            (_BASE, 10000),
            (_BASE + 5 * _MIN, 10000),
            # gap 1: 5min → 25min
            (_BASE + 25 * _MIN, 9900),
            (_BASE + 30 * _MIN, 9900),
            # gap 2: 30min → 60min
            (_BASE + 60 * _MIN, 9800),
        ]
        db_path = _make_db(tmp_path, snapshots)
        gaps = detect_gaps(1, _BASE, _BASE + 65 * _MIN,
                           expected_interval_seconds=300, db_path=db_path)
        assert len(gaps) == 2
        assert gaps[0].start_ms < gaps[1].start_ms

    def test_empty_window(self, tmp_path):
        """No snapshots in window → no gaps (can't compute)."""
        db_path = _make_db(tmp_path, [])
        gaps = detect_gaps(1, _BASE, _BASE + 60 * _MIN, db_path=db_path)
        assert gaps == []

    def test_single_snapshot(self, tmp_path):
        """Only one snapshot → no gaps (need at least 2)."""
        db_path = _make_db(tmp_path, [(_BASE, 10000)])
        gaps = detect_gaps(1, _BASE, _BASE + 60 * _MIN, db_path=db_path)
        assert gaps == []

    def test_threshold_boundary(self, tmp_path):
        """Delta exactly at 2x threshold → not a gap; just above → gap."""
        # expected_interval=300s → threshold=600s=10min
        snapshots = [
            (_BASE, 10000),
            (_BASE + 10 * _MIN, 10000),  # exactly 10 min = threshold → not a gap
        ]
        db_path = _make_db(tmp_path, snapshots)
        gaps = detect_gaps(1, _BASE, _BASE + 15 * _MIN,
                           expected_interval_seconds=300, db_path=db_path)
        assert len(gaps) == 0  # exactly at threshold, not above

        # 10 min + 1 ms → gap
        snapshots2 = [
            (_BASE, 10000),
            (_BASE + 10 * _MIN + 1, 10000),
        ]
        sub = tmp_path / "sub"
        sub.mkdir()
        db_path2 = _make_db(sub, snapshots2)
        gaps2 = detect_gaps(1, _BASE, _BASE + 15 * _MIN,
                            expected_interval_seconds=300, db_path=db_path2)
        assert len(gaps2) == 1
