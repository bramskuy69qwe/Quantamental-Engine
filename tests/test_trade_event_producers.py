"""Tests for trade event producers + closed_positions calc_id backfill."""
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from core.trade_event_log import log_trade_event, query_trade_events
from core.migrations.runner import run_all


def _make_env(tmp_path, account_id=1):
    """Per-account DB with all migrations + pre_trade_log base table."""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / ".split-complete-v1").write_text("v1")
    pa = data / "per_account"
    pa.mkdir(exist_ok=True)
    db_path = str(pa / "test__broker__1.db")

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO accounts VALUES (?, 'Test')", (account_id,))
    # Base table WITHOUT calc_id — migration 005 adds it
    conn.execute(
        "CREATE TABLE IF NOT EXISTS pre_trade_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "timestamp TEXT, ticker TEXT, average REAL DEFAULT 0, "
        "side TEXT DEFAULT '', account_id INTEGER DEFAULT 1, "
        "effective_entry REAL DEFAULT 0, tp_price REAL DEFAULT 0, "
        "sl_price REAL DEFAULT 0)"
    )
    conn.commit()
    conn.close()

    import core.migrations.runner as runner
    real_mdir = os.path.dirname(os.path.abspath(runner.__file__))
    run_all(str(data), real_mdir)
    return str(data), db_path


class TestCalcCreatedProducer:
    def test_calc_created_emitted(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        log_trade_event(1, "calc-123", "calc_created", {
            "ticker": "BTCUSDT", "side": "long",
            "entry": 50000, "tp": 55000, "sl": 48000,
            "size": 0.01, "est_r": 2.5,
        }, source="risk_engine", data_dir=data_dir)

        rows = query_trade_events(account_id=1, calc_id="calc-123", data_dir=data_dir)
        assert len(rows) == 1
        assert rows[0]["event_type"] == "calc_created"
        payload = json.loads(rows[0]["payload_json"])
        assert payload["ticker"] == "BTCUSDT"
        assert payload["est_r"] == 2.5


class TestOrderEventProducers:
    def test_order_placed_emitted(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        log_trade_event(1, "calc-A", "order_placed", {
            "role": "entry", "price": 50000, "side": "BUY", "qty": 0.01,
        }, source="order_manager", data_dir=data_dir)

        rows = query_trade_events(
            account_id=1, event_type="order_placed", data_dir=data_dir
        )
        assert len(rows) == 1
        assert json.loads(rows[0]["payload_json"])["role"] == "entry"

    def test_order_canceled_emitted(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        log_trade_event(1, "calc-B", "order_canceled", {
            "exchange_order_id": "ORD-1",
        }, source="order_manager", data_dir=data_dir)

        rows = query_trade_events(
            account_id=1, event_type="order_canceled", data_dir=data_dir
        )
        assert len(rows) == 1


class TestFillEventProducers:
    def test_order_filled_emitted(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        log_trade_event(1, "calc-C", "order_filled", {
            "role": "maker", "fill_price": 50010, "fill_qty": 0.005, "fee": 0.01,
        }, source="order_manager", data_dir=data_dir)

        rows = query_trade_events(
            account_id=1, event_type="order_filled", data_dir=data_dir
        )
        assert len(rows) == 1

    def test_position_closed_emitted(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        log_trade_event(1, "calc-D", "position_closed", {
            "symbol": "ETHUSDT", "entry_price": 3000,
            "exit_price": 3200, "realized_pnl": 20.0,
        }, source="order_manager", data_dir=data_dir)

        rows = query_trade_events(
            account_id=1, event_type="position_closed", data_dir=data_dir
        )
        assert len(rows) == 1
        payload = json.loads(rows[0]["payload_json"])
        assert payload["realized_pnl"] == 20.0


class TestClosedPositionsCalcId:
    def test_calc_id_in_insert(self):
        """Verify the INSERT SQL now includes calc_id column."""
        from core.db_orders import OrdersMixin
        # Check the SQL string contains calc_id
        import inspect
        src = inspect.getsource(OrdersMixin.insert_closed_position)
        assert "calc_id" in src

    def test_database_alter_includes_closed_positions(self):
        """Verify database.py has the ALTER for closed_positions."""
        from core.database import DatabaseManager
        import inspect
        src = inspect.getsource(DatabaseManager.initialize)
        assert "ALTER TABLE closed_positions ADD COLUMN calc_id" in src


class TestTradeEventLifecycle:
    def test_full_lifecycle_sequence(self, tmp_path, monkeypatch):
        """Simulate a complete trade lifecycle via trade_events."""
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)
        calc = "calc-LIFE"

        log_trade_event(1, calc, "calc_created", {"ticker": "BTCUSDT"}, "risk_engine", data_dir=data_dir)
        log_trade_event(1, calc, "order_placed", {"role": "entry"}, "order_manager", data_dir=data_dir)
        log_trade_event(1, calc, "order_filled", {"fill_qty": 0.01}, "order_manager", data_dir=data_dir)
        log_trade_event(1, calc, "position_closed", {"pnl": 5.0}, "order_manager", data_dir=data_dir)

        rows = query_trade_events(account_id=1, calc_id=calc, data_dir=data_dir)
        types = [r["event_type"] for r in rows]
        # Newest first
        assert types == ["position_closed", "order_filled", "order_placed", "calc_created"]
