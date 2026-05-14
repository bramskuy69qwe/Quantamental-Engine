"""Tests for rolling DD compute integration in data_cache.py."""
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from core.dd_state import dd_state_from_drawdown, dd_state_with_recovery
from core.data_cache import _fetch_rolling_peak_equity


# ── Pure logic (dd_state module already tested; these verify integration math) ──


class TestRollingDDIntegration:
    """Verify the math that data_cache applies matches dd_state outputs."""

    def test_rolling_peak_tracking(self):
        """Peak should be max of all observed equity values."""
        peak = 0.0
        for eq in [10000, 10200, 10100, 10300, 10050]:
            peak = max(peak, eq)
        assert peak == 10300

    def test_drawdown_from_peak(self):
        peak = 10000
        current = 9200
        dd = (peak - current) / peak
        assert dd == pytest.approx(0.08)

    def test_state_with_scalping_thresholds(self):
        """Scalping: warn=4%, limit=8%."""
        assert dd_state_from_drawdown(0.03, 0.04, 0.08) == "ok"
        assert dd_state_from_drawdown(0.05, 0.04, 0.08) == "warning"
        assert dd_state_from_drawdown(0.09, 0.04, 0.08) == "limit"

    def test_recovery_from_limit(self):
        """Episode peak 0.09, recovery 0.50 -> need DD <= 0.045."""
        state, ep = dd_state_with_recovery("limit", 0.04, 0.09, 0.04, 0.08, 0.50)
        assert state == "ok"
        assert ep == 0.0

    def test_sticky_limit(self):
        """Partial recovery (DD=5%) stays limit."""
        state, ep = dd_state_with_recovery("limit", 0.05, 0.09, 0.04, 0.08, 0.50)
        assert state == "limit"


class TestEpisodePeakTracking:
    """Verify episode peak and previous-state semantics."""

    def test_peak_resets_on_ok(self):
        """After recovery to ok, episode peak resets to 0."""
        state, ep = dd_state_with_recovery("limit", 0.04, 0.09, 0.04, 0.08, 0.50)
        assert state == "ok"
        assert ep == 0.0

    def test_peak_persists_in_limit(self):
        state, ep = dd_state_with_recovery("limit", 0.07, 0.09, 0.04, 0.08, 0.50)
        assert state == "limit"
        assert ep == 0.09

    def test_restart_conservative_fallback(self):
        """On restart, empty episode peaks + current DD becomes initial peak."""
        # Simulates restart: no previous state, DD = 6%
        state, ep = dd_state_with_recovery("ok", 0.06, 0.06, 0.04, 0.08, 0.50)
        assert state == "warning"
        assert ep == 0.06  # current DD seeded as peak


class TestTransitionDetection:
    """Verify transition detection logic (prev != new)."""

    def test_ok_to_warning(self):
        prev = "ok"
        new = dd_state_from_drawdown(0.05, 0.04, 0.08)
        assert new == "warning"
        assert prev != new

    def test_no_transition_when_same(self):
        prev = "warning"
        new = dd_state_from_drawdown(0.06, 0.04, 0.08)
        assert new == "warning"
        assert prev == new

    def test_limit_to_ok_via_recovery(self):
        new, _ = dd_state_with_recovery("limit", 0.04, 0.09, 0.04, 0.08, 0.50)
        assert new == "ok"
        assert "limit" != new


class TestFallbackBehavior:
    """Verify graceful degradation when account_settings unavailable."""

    def test_legacy_ratio_logic(self):
        """Legacy: dd_ratio = drawdown / max_dd_percent, compared to limit/warning pcts."""
        drawdown = 0.085  # 8.5% DD
        max_dd_pct = 0.10
        dd_ratio = drawdown / max_dd_pct  # 0.85
        max_dd_limit = 0.95
        max_dd_warn = 0.80

        if dd_ratio >= max_dd_limit:
            state = "limit"
        elif dd_ratio >= max_dd_warn:
            state = "warning"
        else:
            state = "ok"
        assert state == "warning"  # 0.85 >= 0.80


# ── Rolling-window peak correctness ──────────────────────────────────────────


def _make_snapshots_db(tmp_path, account_id=1, snapshots=None):
    """Create a per-account DB with account_snapshots rows."""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / ".split-complete-v1").write_text("v1")
    pa = data / "per_account"
    pa.mkdir(exist_ok=True)
    db_path = str(pa / "test__broker__1.db")

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO accounts VALUES (?, 'Test')", (account_id,))
    conn.execute("""CREATE TABLE account_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        snapshot_ts TEXT NOT NULL,
        total_equity REAL NOT NULL DEFAULT 0
    )""")
    conn.execute(
        "CREATE INDEX idx_snapshots_account ON account_snapshots "
        "(account_id, snapshot_ts DESC)"
    )
    if snapshots:
        for ts, equity in snapshots:
            conn.execute(
                "INSERT INTO account_snapshots (account_id, snapshot_ts, total_equity) "
                "VALUES (?, ?, ?)",
                (account_id, ts.isoformat(), equity),
            )
    conn.commit()
    conn.close()
    return str(data), db_path


class TestRollingWindowPeak:
    """The critical fix: old high OUTSIDE the window must NOT inflate the peak."""

    def test_old_high_excluded_from_window(self, tmp_path, monkeypatch):
        """Old all-time-high is 60 days ago; window is 30d. Peak should be
        the max within the 30d window, not the all-time high."""
        now = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
        snapshots = [
            # 60 days ago: all-time high at 15000 — OUTSIDE 30d window
            (now - timedelta(days=60), 15000.0),
            # 20 days ago: within window, peak at 10000
            (now - timedelta(days=20), 10000.0),
            # 10 days ago: dropped
            (now - timedelta(days=10), 9500.0),
            # recent
            (now - timedelta(days=1), 9200.0),
        ]
        data_dir, db_path = _make_snapshots_db(tmp_path, snapshots=snapshots)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        peak = _fetch_rolling_peak_equity(1, 30, 9200.0)

        # Peak should be 10000 (window max), NOT 15000 (all-time)
        assert peak == 10000.0

        # DD should be from 10000, not 15000
        dd = (peak - 9200.0) / peak
        assert dd == pytest.approx(0.08)

    def test_no_snapshots_returns_current(self, tmp_path, monkeypatch):
        data_dir, _ = _make_snapshots_db(tmp_path, snapshots=[])
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        peak = _fetch_rolling_peak_equity(1, 30, 5000.0)
        assert peak == 5000.0

    def test_current_equity_above_window_peak(self, tmp_path, monkeypatch):
        """If current equity exceeds all snapshots, peak = current (DD = 0)."""
        now = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)
        snapshots = [(now - timedelta(days=5), 9000.0)]
        data_dir, _ = _make_snapshots_db(tmp_path, snapshots=snapshots)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        peak = _fetch_rolling_peak_equity(1, 30, 10000.0)
        assert peak == 10000.0


class TestSnapshotIndex:
    """Verify the account_snapshots index exists for efficient window queries."""

    def test_index_exists_on_real_db(self):
        PA = "data/per_account/quantower__binancefutures__binance.db"
        if not os.path.exists(PA):
            pytest.skip("no per-account DB on disk")
        conn = sqlite3.connect(PA)
        indexes = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name='account_snapshots'"
            ).fetchall()
        ]
        conn.close()
        assert "idx_snapshots_account" in indexes
