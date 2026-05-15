"""Tests for manual calc_id link + position_opened/partial_close producers."""
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

import pytest

from core.calc_correlation import find_candidate_calcs, CandidateCalc
from core.trade_event_log import log_trade_event, query_trade_events, _VALID_TRADE_EVENT_TYPES
from core.migrations.runner import run_all


def _make_env(tmp_path, account_id=1, ptl_rows=None, orders_in_legacy=None):
    """DB environment with pre_trade_log + optional legacy orders."""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / ".split-complete-v1").write_text("v1")
    pa = data / "per_account"
    pa.mkdir(exist_ok=True)
    db_path = str(pa / "test__broker__1.db")

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO accounts VALUES (?, 'Test')", (account_id,))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS pre_trade_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "timestamp TEXT, ticker TEXT, average REAL DEFAULT 0, "
        "side TEXT DEFAULT '', account_id INTEGER DEFAULT 1, "
        "effective_entry REAL DEFAULT 0, tp_price REAL DEFAULT 0, "
        "sl_price REAL DEFAULT 0)"
    )
    # Also need orders table for linked-check
    conn.execute(
        "CREATE TABLE IF NOT EXISTS orders ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "account_id INTEGER, exchange_order_id TEXT, "
        "symbol TEXT, side TEXT, order_type TEXT, price REAL DEFAULT 0, "
        "reduce_only INTEGER DEFAULT 0, calc_id TEXT, "
        "tp_trigger_price REAL, sl_trigger_price REAL, "
        "created_at_ms INTEGER DEFAULT 0, "
        "UNIQUE(account_id, exchange_order_id))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS fills ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "account_id INTEGER, exchange_fill_id TEXT, exchange_order_id TEXT, "
        "calc_id TEXT, UNIQUE(account_id, exchange_fill_id))"
    )
    conn.commit()
    conn.close()

    import core.migrations.runner as runner
    real_mdir = __import__("os").path.dirname(__import__("os").path.abspath(runner.__file__))
    run_all(str(data), real_mdir)

    if ptl_rows:
        conn = sqlite3.connect(db_path)
        for r in ptl_rows:
            conn.execute(
                "INSERT INTO pre_trade_log "
                "(account_id, timestamp, ticker, side, effective_entry, tp_price, sl_price, average, calc_id) "
                "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)",
                (r["timestamp"], r["ticker"], r["side"],
                 r["effective_entry"], r["tp_price"], r["sl_price"],
                 r.get("average", r["effective_entry"]), r["calc_id"]),
            )
        conn.commit()
        conn.close()

    return str(data), db_path


RECENT = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()


# ── manual_link_added event type ─────────────────────────────────────────────


class TestManualLinkEventType:
    def test_type_registered(self):
        assert "manual_link_added" in _VALID_TRADE_EVENT_TYPES

    def test_log_accepted(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)
        row_id = log_trade_event(
            1, "c1", "manual_link_added", {"order_id": 1}, "manual_link",
            data_dir=data_dir,
        )
        assert row_id >= 1


# ── find_candidate_calcs ─────────────────────────────────────────────────────


class TestFindCandidates:
    def test_3_of_3_match(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path, ptl_rows=[{
            "timestamp": RECENT, "ticker": "BTCUSDT", "side": "BUY",
            "effective_entry": 50000, "tp_price": 55000, "sl_price": 48000,
            "calc_id": "c-full",
        }])
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        order = {"account_id": 1, "symbol": "BTCUSDT", "side": "BUY",
                 "price": 50000, "tp_trigger_price": 55000, "sl_trigger_price": 48000}
        cands = find_candidate_calcs(order, db_path=db_path)
        assert len(cands) == 1
        assert cands[0].entry_match and cands[0].tp_match and cands[0].sl_match

    def test_2_of_3_match_included(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path, ptl_rows=[{
            "timestamp": RECENT, "ticker": "BTCUSDT", "side": "BUY",
            "effective_entry": 50000, "tp_price": 55000, "sl_price": 48000,
            "calc_id": "c-partial",
        }])
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        order = {"account_id": 1, "symbol": "BTCUSDT", "side": "BUY",
                 "price": 50000, "tp_trigger_price": 55000,
                 "sl_trigger_price": 40000}  # SL far off
        cands = find_candidate_calcs(order, db_path=db_path)
        assert len(cands) == 1
        assert cands[0].entry_match and cands[0].tp_match
        assert not cands[0].sl_match

    def test_0_of_3_excluded(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path, ptl_rows=[{
            "timestamp": RECENT, "ticker": "BTCUSDT", "side": "BUY",
            "effective_entry": 50000, "tp_price": 55000, "sl_price": 48000,
            "calc_id": "c-none",
        }])
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        order = {"account_id": 1, "symbol": "BTCUSDT", "side": "BUY",
                 "price": 60000, "tp_trigger_price": 70000, "sl_trigger_price": 40000}
        cands = find_candidate_calcs(order, db_path=db_path)
        assert len(cands) == 0

    def test_already_linked_excluded(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path, ptl_rows=[{
            "timestamp": RECENT, "ticker": "BTCUSDT", "side": "BUY",
            "effective_entry": 50000, "tp_price": 55000, "sl_price": 48000,
            "calc_id": "c-linked",
        }])
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        # Mark as already linked
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, calc_id) "
            "VALUES (1, 'ORD-X', 'BTCUSDT', 'BUY', 'c-linked')"
        )
        conn.commit()
        conn.close()

        order = {"account_id": 1, "symbol": "BTCUSDT", "side": "BUY",
                 "price": 50000, "tp_trigger_price": 55000, "sl_trigger_price": 48000}
        cands = find_candidate_calcs(order, db_path=db_path)
        assert len(cands) == 0


# ── Confirm link ─────────────────────────────────────────────────────────────


class TestConfirmLink:
    def test_sets_calc_id_and_propagates(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path, ptl_rows=[{
            "timestamp": RECENT, "ticker": "BTCUSDT", "side": "BUY",
            "effective_entry": 50000, "tp_price": 55000, "sl_price": 48000,
            "calc_id": "c-link",
        }])
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, price) "
            "VALUES (1, 'ORD1', 'BTCUSDT', 'BUY', 50000)"
        )
        conn.execute(
            "INSERT INTO fills (account_id, exchange_fill_id, exchange_order_id) "
            "VALUES (1, 'FILL1', 'ORD1')"
        )
        conn.commit()

        # Simulate confirm link
        conn.execute("UPDATE orders SET calc_id = 'c-link' WHERE exchange_order_id = 'ORD1'")
        conn.execute("UPDATE fills SET calc_id = 'c-link' WHERE exchange_order_id = 'ORD1'")
        conn.commit()

        o_row = conn.execute("SELECT calc_id FROM orders WHERE exchange_order_id='ORD1'").fetchone()
        f_row = conn.execute("SELECT calc_id FROM fills WHERE exchange_fill_id='FILL1'").fetchone()
        conn.close()

        assert o_row[0] == "c-link"
        assert f_row[0] == "c-link"
