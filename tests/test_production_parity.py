"""Tests for parent re-enrichment on child arrival (production parity)."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from core.order_enrichment import enrich_order


RECENT = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


def _make_db(tmp_path, ptl_rows=None):
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE accounts (id INTEGER PRIMARY KEY);
        INSERT INTO accounts VALUES (1);

        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER, exchange_order_id TEXT,
            symbol TEXT, side TEXT, order_type TEXT,
            status TEXT DEFAULT 'new',
            price REAL DEFAULT 0, stop_price REAL DEFAULT 0,
            quantity REAL DEFAULT 0, reduce_only INTEGER DEFAULT 0,
            exchange_position_id TEXT DEFAULT '',
            calc_id TEXT, tp_trigger_price REAL, sl_trigger_price REAL,
            created_at_ms INTEGER DEFAULT 0, updated_at_ms INTEGER DEFAULT 0,
            last_seen_ms INTEGER DEFAULT 0,
            UNIQUE(account_id, exchange_order_id)
        );

        CREATE TABLE fills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER, exchange_fill_id TEXT,
            exchange_order_id TEXT, calc_id TEXT,
            UNIQUE(account_id, exchange_fill_id)
        );

        CREATE TABLE pre_trade_log (
            id INTEGER PRIMARY KEY, account_id INTEGER DEFAULT 1,
            timestamp TEXT, ticker TEXT, side TEXT DEFAULT '',
            effective_entry REAL DEFAULT 0, tp_price REAL DEFAULT 0,
            sl_price REAL DEFAULT 0, average REAL DEFAULT 0, calc_id TEXT
        );
    """)
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


class TestParentReEnrichment:
    def test_entry_no_children_stays_null(self, tmp_path):
        """Entry persisted alone — no trigger prices, no correlation."""
        db_path = _make_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
            "order_type, price, exchange_position_id) "
            "VALUES (1, 'ENTRY', 'BTCUSDT', 'BUY', 'limit', 50000, 'POS1')"
        )
        conn.commit()
        conn.close()

        enrich_order({"account_id": 1, "exchange_order_id": "ENTRY",
                       "symbol": "BTCUSDT", "side": "BUY", "order_type": "limit",
                       "exchange_position_id": "POS1"}, db_path)

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT tp_trigger_price, sl_trigger_price, calc_id FROM orders WHERE exchange_order_id='ENTRY'").fetchone()
        conn.close()
        assert row[0] is None  # no TP child yet
        assert row[1] is None  # no SL child yet
        assert row[2] is None  # no correlation possible

    def test_tp_child_populates_trigger(self, tmp_path):
        """TP child arrives → parent's tp_trigger_price populated."""
        db_path = _make_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
            "order_type, price, exchange_position_id) "
            "VALUES (1, 'ENTRY', 'BTCUSDT', 'BUY', 'limit', 50000, 'POS1')"
        )
        conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
            "order_type, stop_price, exchange_position_id, reduce_only) "
            "VALUES (1, 'TP1', 'BTCUSDT', 'SELL', 'take_profit_market', 55000, 'POS1', 1)"
        )
        conn.commit()
        conn.close()

        # Re-enrich parent (simulates what _re_enrich_parent_on_child_arrival does)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        parent = conn.execute("SELECT * FROM orders WHERE exchange_order_id='ENTRY'").fetchone()
        conn.close()
        enrich_order(dict(parent), db_path)

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT tp_trigger_price FROM orders WHERE exchange_order_id='ENTRY'").fetchone()
        conn.close()
        assert row[0] == 55000.0

    def test_both_children_trigger_correlation(self, tmp_path):
        """Both TP+SL children arrive → trigger prices populated → correlation runs."""
        db_path = _make_db(tmp_path, ptl_rows=[{
            "timestamp": RECENT, "ticker": "BTCUSDT", "side": "BUY",
            "effective_entry": 50000, "tp_price": 55000, "sl_price": 48000,
            "calc_id": "calc-parity",
        }])
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
            "order_type, price, exchange_position_id) "
            "VALUES (1, 'ENTRY', 'BTCUSDT', 'BUY', 'limit', 50000, 'POS1')"
        )
        conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
            "order_type, stop_price, exchange_position_id, reduce_only) "
            "VALUES (1, 'TP1', 'BTCUSDT', 'SELL', 'take_profit_market', 55000, 'POS1', 1)"
        )
        conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
            "order_type, stop_price, exchange_position_id, reduce_only) "
            "VALUES (1, 'SL1', 'BTCUSDT', 'SELL', 'stop_market', 48000, 'POS1', 1)"
        )
        conn.commit()
        conn.close()

        # Re-enrich parent after SL child
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        parent = conn.execute("SELECT * FROM orders WHERE exchange_order_id='ENTRY'").fetchone()
        conn.close()
        enrich_order(dict(parent), db_path)

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT calc_id, tp_trigger_price, sl_trigger_price FROM orders WHERE exchange_order_id='ENTRY'").fetchone()
        conn.close()
        assert row[0] == "calc-parity"
        assert row[1] == 55000.0
        assert row[2] == 48000.0

    def test_idempotent_reenrich(self, tmp_path):
        """Re-enriching parent that already has calc_id doesn't overwrite."""
        db_path = _make_db(tmp_path, ptl_rows=[{
            "timestamp": RECENT, "ticker": "ETHUSDT", "side": "BUY",
            "effective_entry": 3000, "tp_price": 3300, "sl_price": 2900,
            "calc_id": "calc-idem",
        }])
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
            "order_type, price, exchange_position_id, calc_id, "
            "tp_trigger_price, sl_trigger_price) "
            "VALUES (1, 'ENTRY', 'ETHUSDT', 'BUY', 'limit', 3000, 'POS2', "
            "'calc-idem', 3300, 2900)"
        )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        parent = conn.execute("SELECT * FROM orders WHERE exchange_order_id='ENTRY'").fetchone()
        conn.close()
        enrich_order(dict(parent), db_path)

        conn = sqlite3.connect(db_path)
        row = conn.execute("SELECT calc_id FROM orders WHERE exchange_order_id='ENTRY'").fetchone()
        conn.close()
        assert row[0] == "calc-idem"  # unchanged

    def test_orphan_child_no_crash(self, tmp_path):
        """TP/SL child with no matching parent → graceful skip."""
        db_path = _make_db(tmp_path)
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
            "order_type, stop_price, exchange_position_id, reduce_only) "
            "VALUES (1, 'ORPHAN-TP', 'BTCUSDT', 'SELL', 'take_profit_market', 55000, 'POS-NONE', 1)"
        )
        conn.commit()
        conn.close()

        # Simulate the hook: look for parent
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        parent = conn.execute(
            "SELECT * FROM orders WHERE account_id = 1 AND exchange_position_id = 'POS-NONE' "
            "AND reduce_only = 0 LIMIT 1"
        ).fetchone()
        conn.close()
        assert parent is None  # no parent → skip gracefully
