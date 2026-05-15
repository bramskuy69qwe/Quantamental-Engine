"""Tests for calc_id end-to-end wiring: enrichment + correlation + fill propagation."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from core.order_enrichment import enrich_order, enrich_fill


def _make_legacy_db(tmp_path, ptl_rows=None):
    """Simulate the legacy risk_engine.db with orders, fills, pre_trade_log."""
    db_path = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(db_path)
    conn.execute("""CREATE TABLE orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        exchange_order_id TEXT,
        symbol TEXT, side TEXT, order_type TEXT, status TEXT DEFAULT 'new',
        price REAL DEFAULT 0, stop_price REAL DEFAULT 0,
        quantity REAL DEFAULT 0, filled_qty REAL DEFAULT 0, avg_fill_price REAL DEFAULT 0,
        reduce_only INTEGER DEFAULT 0, time_in_force TEXT DEFAULT '',
        position_side TEXT DEFAULT '', exchange_position_id TEXT DEFAULT '',
        terminal_position_id TEXT DEFAULT '', terminal_order_id TEXT DEFAULT '',
        client_order_id TEXT DEFAULT '', source TEXT DEFAULT '',
        created_at_ms INTEGER DEFAULT 0, updated_at_ms INTEGER DEFAULT 0, last_seen_ms INTEGER DEFAULT 0,
        calc_id TEXT, tp_trigger_price REAL, sl_trigger_price REAL,
        UNIQUE(account_id, exchange_order_id)
    )""")
    conn.execute("""CREATE TABLE fills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL,
        exchange_fill_id TEXT, exchange_order_id TEXT DEFAULT '',
        symbol TEXT, side TEXT, direction TEXT DEFAULT '',
        price REAL DEFAULT 0, quantity REAL DEFAULT 0,
        fee REAL DEFAULT 0, fee_asset TEXT DEFAULT 'USDT',
        exchange_position_id TEXT DEFAULT '', terminal_position_id TEXT DEFAULT '',
        terminal_fill_id TEXT DEFAULT '',
        is_close INTEGER DEFAULT 0, realized_pnl REAL DEFAULT 0,
        role TEXT DEFAULT '', source TEXT DEFAULT '', timestamp_ms INTEGER DEFAULT 0,
        calc_id TEXT,
        UNIQUE(account_id, exchange_fill_id)
    )""")
    conn.execute("""CREATE TABLE pre_trade_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER DEFAULT 1,
        timestamp TEXT, ticker TEXT, side TEXT DEFAULT '',
        average REAL DEFAULT 0, effective_entry REAL DEFAULT 0,
        tp_price REAL DEFAULT 0, sl_price REAL DEFAULT 0,
        calc_id TEXT
    )""")
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO accounts VALUES (1, 'Test')")

    if ptl_rows:
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
    return db_path


RECENT = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


class TestTpSlPopulation:
    def test_entry_without_children_stays_null(self, tmp_path):
        db_path = _make_legacy_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, order_type, "
            "price, exchange_position_id) VALUES (1, 'ORD1', 'BTCUSDT', 'BUY', 'limit', 50000, 'POS1')"
        )
        conn.commit()
        conn.close()

        order = {"account_id": 1, "exchange_order_id": "ORD1", "symbol": "BTCUSDT",
                 "side": "BUY", "order_type": "limit", "exchange_position_id": "POS1"}
        enrich_order(order, db_path)

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT tp_trigger_price, sl_trigger_price FROM orders WHERE exchange_order_id='ORD1'").fetchone()
        conn.close()
        assert row[0] is None
        assert row[1] is None

    def test_children_populate_trigger_prices(self, tmp_path):
        db_path = _make_legacy_db(tmp_path)
        conn = sqlite3.connect(db_path)
        # Entry order
        conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, order_type, "
            "price, exchange_position_id, reduce_only) "
            "VALUES (1, 'ENTRY1', 'BTCUSDT', 'BUY', 'limit', 50000, 'POS1', 0)"
        )
        # TP child
        conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, order_type, "
            "stop_price, exchange_position_id, reduce_only) "
            "VALUES (1, 'TP1', 'BTCUSDT', 'SELL', 'take_profit_market', 55000, 'POS1', 1)"
        )
        # SL child
        conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, order_type, "
            "stop_price, exchange_position_id, reduce_only) "
            "VALUES (1, 'SL1', 'BTCUSDT', 'SELL', 'stop_market', 48000, 'POS1', 1)"
        )
        conn.commit()
        conn.close()

        order = {"account_id": 1, "exchange_order_id": "ENTRY1", "symbol": "BTCUSDT",
                 "side": "BUY", "order_type": "limit", "exchange_position_id": "POS1"}
        enrich_order(order, db_path)

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT tp_trigger_price, sl_trigger_price FROM orders WHERE exchange_order_id='ENTRY1'"
        ).fetchone()
        conn.close()
        assert row[0] == 55000.0
        assert row[1] == 48000.0


class TestCalcIdCorrelation:
    def test_triple_match_assigns_calc_id(self, tmp_path):
        db_path = _make_legacy_db(tmp_path, ptl_rows=[{
            "timestamp": RECENT, "ticker": "BTCUSDT", "side": "BUY",
            "effective_entry": 50000.0, "tp_price": 55000.0, "sl_price": 48000.0,
            "calc_id": "calc-ABC",
        }])
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, order_type, "
            "price, tp_trigger_price, sl_trigger_price, exchange_position_id) "
            "VALUES (1, 'ORD1', 'BTCUSDT', 'BUY', 'limit', 50000, 55000, 48000, 'POS1')"
        )
        conn.commit()
        conn.close()

        order = {"account_id": 1, "exchange_order_id": "ORD1", "symbol": "BTCUSDT",
                 "side": "BUY", "order_type": "limit", "exchange_position_id": "POS1"}
        enrich_order(order, db_path)

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT calc_id FROM orders WHERE exchange_order_id='ORD1'").fetchone()
        conn.close()
        assert row[0] == "calc-ABC"

    def test_no_match_leaves_null(self, tmp_path):
        db_path = _make_legacy_db(tmp_path)  # no pre_trade_log rows
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, order_type, "
            "price, tp_trigger_price, sl_trigger_price, exchange_position_id) "
            "VALUES (1, 'ORD1', 'BTCUSDT', 'BUY', 'limit', 50000, 55000, 48000, 'POS1')"
        )
        conn.commit()
        conn.close()

        order = {"account_id": 1, "exchange_order_id": "ORD1", "symbol": "BTCUSDT",
                 "side": "BUY", "order_type": "limit", "exchange_position_id": "POS1"}
        enrich_order(order, db_path)

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT calc_id FROM orders WHERE exchange_order_id='ORD1'").fetchone()
        conn.close()
        assert row[0] is None


class TestFillCalcIdPropagation:
    def test_fill_inherits_parent_calc_id(self, tmp_path):
        db_path = _make_legacy_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, calc_id) "
            "VALUES (1, 'ORD1', 'BTCUSDT', 'BUY', 'calc-XYZ')"
        )
        conn.execute(
            "INSERT INTO fills (account_id, exchange_fill_id, exchange_order_id, symbol, side) "
            "VALUES (1, 'FILL1', 'ORD1', 'BTCUSDT', 'BUY')"
        )
        conn.commit()
        conn.close()

        fill = {"account_id": 1, "exchange_fill_id": "FILL1", "exchange_order_id": "ORD1"}
        enrich_fill(fill, db_path)

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT calc_id FROM fills WHERE exchange_fill_id='FILL1'").fetchone()
        conn.close()
        assert row[0] == "calc-XYZ"

    def test_fill_no_parent_calc_id_stays_null(self, tmp_path):
        db_path = _make_legacy_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side) "
            "VALUES (1, 'ORD1', 'BTCUSDT', 'BUY')"
        )
        conn.execute(
            "INSERT INTO fills (account_id, exchange_fill_id, exchange_order_id, symbol, side) "
            "VALUES (1, 'FILL1', 'ORD1', 'BTCUSDT', 'BUY')"
        )
        conn.commit()
        conn.close()

        fill = {"account_id": 1, "exchange_fill_id": "FILL1", "exchange_order_id": "ORD1"}
        enrich_fill(fill, db_path)

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT calc_id FROM fills WHERE exchange_fill_id='FILL1'").fetchone()
        conn.close()
        assert row[0] is None

    def test_canceled_entry_still_correlates(self, tmp_path):
        """Canceled entries should still get calc_id for attribution."""
        db_path = _make_legacy_db(tmp_path, ptl_rows=[{
            "timestamp": RECENT, "ticker": "ETHUSDT", "side": "SELL",
            "effective_entry": 3000.0, "tp_price": 2800.0, "sl_price": 3100.0,
            "calc_id": "calc-CANC",
        }])
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, order_type, "
            "price, tp_trigger_price, sl_trigger_price, status, exchange_position_id) "
            "VALUES (1, 'ORD-C', 'ETHUSDT', 'SELL', 'limit', 3000, 2800, 3100, 'canceled', 'POS2')"
        )
        conn.commit()
        conn.close()

        order = {"account_id": 1, "exchange_order_id": "ORD-C", "symbol": "ETHUSDT",
                 "side": "SELL", "order_type": "limit", "exchange_position_id": "POS2"}
        enrich_order(order, db_path)

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT calc_id FROM orders WHERE exchange_order_id='ORD-C'").fetchone()
        conn.close()
        assert row[0] == "calc-CANC"
