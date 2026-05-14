"""Tests for calc_id triple-match correlation."""
import os
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from core.calc_correlation import correlate_order_to_calc
from core.migrations.runner import run_all


def _make_env(tmp_path, account_id=1, ptl_rows=None):
    """Per-account DB with pre_trade_log rows for correlation testing."""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / ".split-complete-v1").write_text("v1")
    pa = data / "per_account"
    pa.mkdir(exist_ok=True)
    db_path = str(pa / "test__broker__1.db")

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO accounts VALUES (?, 'Test')", (account_id,))
    # Base pre_trade_log schema (normally from database.py _CREATE_STATEMENTS)
    conn.execute("""CREATE TABLE IF NOT EXISTS pre_trade_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL, ticker TEXT NOT NULL,
        average REAL NOT NULL DEFAULT 0, side TEXT NOT NULL DEFAULT '',
        one_percent_depth REAL DEFAULT 0, individual_risk REAL DEFAULT 0,
        tp_price REAL DEFAULT 0, tp_amount_pct REAL DEFAULT 0, tp_usdt REAL DEFAULT 0,
        sl_price REAL DEFAULT 0, sl_amount_pct REAL DEFAULT 0, sl_usdt REAL DEFAULT 0,
        model_name TEXT DEFAULT '', model_desc TEXT DEFAULT '',
        risk_usdt REAL DEFAULT 0, atr_c TEXT DEFAULT '', atr_category TEXT DEFAULT '',
        est_slippage REAL DEFAULT 0, effective_entry REAL DEFAULT 0,
        size REAL DEFAULT 0, notional REAL DEFAULT 0,
        est_profit REAL DEFAULT 0, est_loss REAL DEFAULT 0,
        est_r REAL DEFAULT 0, est_exposure REAL DEFAULT 0,
        eligible INTEGER DEFAULT 0, notes TEXT DEFAULT '', account_id INTEGER DEFAULT 1
    )""")
    conn.commit()
    conn.close()

    import core.migrations.runner as runner
    real_mdir = os.path.dirname(os.path.abspath(runner.__file__))
    run_all(str(data), real_mdir)

    if ptl_rows:
        conn = sqlite3.connect(db_path)
        for r in ptl_rows:
            conn.execute(
                "INSERT INTO pre_trade_log "
                "(account_id, timestamp, ticker, side, effective_entry, tp_price, sl_price, "
                " average, calc_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (account_id, r["timestamp"], r["ticker"], r["side"],
                 r["effective_entry"], r["tp_price"], r["sl_price"],
                 r.get("average", r["effective_entry"]), r["calc_id"]),
            )
        conn.commit()
        conn.close()

    return str(data), db_path


NOW = datetime.now(timezone.utc).isoformat()
RECENT = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
OLD = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()


class TestTripleMatch:
    def test_exact_match(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path, ptl_rows=[{
            "timestamp": RECENT, "ticker": "BTCUSDT", "side": "long",
            "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
            "calc_id": "abc123",
        }])
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        order = {
            "account_id": 1, "symbol": "BTCUSDT", "side": "long",
            "order_type": "limit", "price": 50000.0,
            "tp_trigger_price": 55000.0, "sl_trigger_price": 48000.0,
        }
        result = correlate_order_to_calc(order, tick_size=0.1, data_dir=data_dir)
        assert result == "abc123"

    def test_within_tick_tolerance(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path, ptl_rows=[{
            "timestamp": RECENT, "ticker": "BTCUSDT", "side": "long",
            "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
            "calc_id": "abc123",
        }])
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        order = {
            "account_id": 1, "symbol": "BTCUSDT", "side": "long",
            "order_type": "limit", "price": 50000.05,  # within 0.1 tick
            "tp_trigger_price": 54999.95, "sl_trigger_price": 48000.05,
        }
        result = correlate_order_to_calc(order, tick_size=0.1, data_dir=data_dir)
        assert result == "abc123"

    def test_one_tick_over_no_match(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path, ptl_rows=[{
            "timestamp": RECENT, "ticker": "BTCUSDT", "side": "long",
            "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
            "calc_id": "abc123",
        }])
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        order = {
            "account_id": 1, "symbol": "BTCUSDT", "side": "long",
            "order_type": "limit", "price": 50000.0,
            "tp_trigger_price": 55000.0, "sl_trigger_price": 48000.2,  # > 0.1 tick
        }
        result = correlate_order_to_calc(order, tick_size=0.1, data_dir=data_dir)
        assert result is None

    def test_market_order_skipped(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path, ptl_rows=[{
            "timestamp": RECENT, "ticker": "BTCUSDT", "side": "long",
            "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
            "calc_id": "abc123",
        }])
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        order = {
            "account_id": 1, "symbol": "BTCUSDT", "side": "long",
            "order_type": "market", "price": 50000.0,
            "tp_trigger_price": 55000.0, "sl_trigger_price": 48000.0,
        }
        result = correlate_order_to_calc(order, tick_size=0.1, data_dir=data_dir)
        assert result is None

    def test_missing_tp_trigger_no_match(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path, ptl_rows=[{
            "timestamp": RECENT, "ticker": "BTCUSDT", "side": "long",
            "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
            "calc_id": "abc123",
        }])
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        order = {
            "account_id": 1, "symbol": "BTCUSDT", "side": "long",
            "order_type": "limit", "price": 50000.0,
            "sl_trigger_price": 48000.0,
            # tp_trigger_price missing → strict: no match
        }
        result = correlate_order_to_calc(order, tick_size=0.1, data_dir=data_dir)
        assert result is None

    def test_outside_24h_window(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path, ptl_rows=[{
            "timestamp": OLD, "ticker": "BTCUSDT", "side": "long",
            "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
            "calc_id": "abc123",
        }])
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        order = {
            "account_id": 1, "symbol": "BTCUSDT", "side": "long",
            "order_type": "limit", "price": 50000.0,
            "tp_trigger_price": 55000.0, "sl_trigger_price": 48000.0,
        }
        result = correlate_order_to_calc(order, tick_size=0.1, data_dir=data_dir)
        assert result is None

    def test_multiple_matches_returns_most_recent(self, tmp_path, monkeypatch):
        older = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        data_dir, _ = _make_env(tmp_path, ptl_rows=[
            {
                "timestamp": older, "ticker": "BTCUSDT", "side": "long",
                "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
                "calc_id": "older_id",
            },
            {
                "timestamp": RECENT, "ticker": "BTCUSDT", "side": "long",
                "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
                "calc_id": "newer_id",
            },
        ])
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        order = {
            "account_id": 1, "symbol": "BTCUSDT", "side": "long",
            "order_type": "limit", "price": 50000.0,
            "tp_trigger_price": 55000.0, "sl_trigger_price": 48000.0,
        }
        result = correlate_order_to_calc(order, tick_size=0.1, data_dir=data_dir)
        assert result == "newer_id"
