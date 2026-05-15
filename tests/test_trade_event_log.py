"""Tests for core.trade_event_log — trade lifecycle event log."""
import json
import os
import sqlite3

import pytest

from core.trade_event_log import (
    _VALID_TRADE_EVENT_TYPES,
    log_trade_event,
    query_trade_events,
)
from core.migrations.runner import run_all


def _make_env(tmp_path, account_id=1):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / ".split-complete-v1").write_text("v1")
    pa = data / "per_account"
    pa.mkdir(exist_ok=True)
    db_path = str(pa / "test__broker__1.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO accounts VALUES (?, 'Test')", (account_id,))
    # pre_trade_log needed for migration 005 (adds calc_id column)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS pre_trade_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "timestamp TEXT, ticker TEXT, average REAL DEFAULT 0, "
        "side TEXT DEFAULT '', account_id INTEGER DEFAULT 1)"
    )
    conn.commit()
    conn.close()

    import core.migrations.runner as runner
    real_mdir = os.path.dirname(os.path.abspath(runner.__file__))
    run_all(str(data), real_mdir)
    return str(data), db_path


class TestLogTradeEvent:
    def test_insert_returns_id(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        row_id = log_trade_event(
            1, "calc-abc", "calc_created",
            {"ticker": "BTCUSDT", "entry": 50000},
            "risk_engine",
            timestamp="2026-05-15T12:00:00+00:00",
            data_dir=data_dir,
        )
        assert isinstance(row_id, int)
        assert row_id >= 1

    def test_payload_roundtrip(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        payload = {"ticker": "ETHUSDT", "qty": 1.5, "nested": {"a": [1, 2]}}
        row_id = log_trade_event(
            1, "calc-xyz", "order_placed", payload, "test",
            data_dir=data_dir,
        )

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT payload_json FROM trade_events WHERE id = ?", (row_id,)
        ).fetchone()
        conn.close()
        assert json.loads(row[0]) == payload

    def test_unknown_event_type_raises(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        with pytest.raises(ValueError, match="Unknown trade event_type"):
            log_trade_event(1, "x", "fake_type", {}, "test", data_dir=data_dir)  # type: ignore[arg-type]

    def test_null_calc_id_allowed(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        row_id = log_trade_event(
            1, None, "manual_close", {"reason": "manual"}, "ui",
            data_dir=data_dir,
        )
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT calc_id FROM trade_events WHERE id = ?", (row_id,)
        ).fetchone()
        conn.close()
        assert row[0] is None

    def test_all_event_types_accepted(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        for et in sorted(_VALID_TRADE_EVENT_TYPES):
            log_trade_event(1, "x", et, {}, "test", data_dir=data_dir)  # type: ignore[arg-type]


class TestQueryTradeEvents:
    def test_query_by_calc_id(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        log_trade_event(1, "calc-A", "calc_created", {}, "test", data_dir=data_dir)
        log_trade_event(1, "calc-B", "calc_created", {}, "test", data_dir=data_dir)
        log_trade_event(1, "calc-A", "order_placed", {}, "test", data_dir=data_dir)

        rows = query_trade_events(account_id=1, calc_id="calc-A", data_dir=data_dir)
        assert len(rows) == 2
        assert all(r["calc_id"] == "calc-A" for r in rows)

    def test_query_no_filters_returns_latest(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        for i in range(5):
            log_trade_event(
                1, f"c{i}", "calc_created", {"i": i}, "test",
                timestamp=f"2026-05-15T{10+i:02d}:00:00+00:00",
                data_dir=data_dir,
            )
        rows = query_trade_events(account_id=1, limit=3, data_dir=data_dir)
        assert len(rows) == 3
        # Newest first
        assert json.loads(rows[0]["payload_json"])["i"] == 4

    def test_indexes_exist(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path)
        conn = sqlite3.connect(db_path)
        indexes = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name='trade_events'"
            ).fetchall()
        ]
        conn.close()
        assert "idx_trade_events_calc_id" in indexes
        assert "idx_trade_events_account_time" in indexes
        assert "idx_trade_events_type" in indexes
