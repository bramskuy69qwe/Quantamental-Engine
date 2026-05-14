"""Tests for startup equity delta warning (v2.4 Priority 2d)."""
import os
import sqlite3
from datetime import datetime, timezone

import pytest

from core.event_log import query_events
from core.migrations.runner import run_all


def _make_env(tmp_path, account_id=1, snap_equity=None, snap_ts=None):
    """Per-account DB with optional snapshot row."""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / ".split-complete-v1").write_text("v1")
    pa = data / "per_account"
    pa.mkdir(exist_ok=True)
    db_path = str(pa / "test__broker__1.db")

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO accounts VALUES (?, 'Test')", (account_id,))
    conn.execute("""CREATE TABLE IF NOT EXISTS account_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        snapshot_ts TEXT NOT NULL,
        total_equity REAL NOT NULL DEFAULT 0
    )""")
    conn.commit()
    conn.close()

    import core.migrations.runner as runner
    real_mdir = os.path.dirname(os.path.abspath(runner.__file__))
    run_all(str(data), real_mdir)

    if snap_equity is not None:
        conn = sqlite3.connect(db_path)
        ts = snap_ts or datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO account_snapshots (account_id, snapshot_ts, total_equity) "
            "VALUES (?, ?, ?)",
            (account_id, ts, snap_equity),
        )
        conn.commit()
        conn.close()

    return str(data), db_path


class TestEquityDeltaStartup:
    def test_large_delta_logs_warning(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path, snap_equity=10000.0)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        from core.state import app_state
        app_state.account_state.total_equity = 9800.0  # 2% delta

        from core.schedulers import _check_startup_equity_delta
        _check_startup_equity_delta()

        events = query_events(1, event_type="equity_delta_warning", data_dir=data_dir)
        assert len(events) == 1
        import json
        payload = json.loads(events[0]["payload_json"])
        assert payload["live"] == 9800.0
        assert payload["snapshot"] == 10000.0
        assert payload["delta_pct"] == pytest.approx(0.02)

    def test_small_delta_no_log(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path, snap_equity=10000.0)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        from core.state import app_state
        app_state.account_state.total_equity = 9950.0  # 0.5% delta

        from core.schedulers import _check_startup_equity_delta
        _check_startup_equity_delta()

        events = query_events(1, event_type="equity_delta_warning", data_dir=data_dir)
        assert len(events) == 0

    def test_no_prior_snapshot_no_error(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)  # no snapshot
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        from core.state import app_state
        app_state.account_state.total_equity = 10000.0

        from core.schedulers import _check_startup_equity_delta
        _check_startup_equity_delta()  # should not raise

        events = query_events(1, event_type="equity_delta_warning", data_dir=data_dir)
        assert len(events) == 0

    def test_zero_equity_no_check(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path, snap_equity=10000.0)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        from core.state import app_state
        app_state.account_state.total_equity = 0.0

        from core.schedulers import _check_startup_equity_delta
        _check_startup_equity_delta()  # should not raise or log

        events = query_events(1, event_type="equity_delta_warning", data_dir=data_dir)
        assert len(events) == 0
