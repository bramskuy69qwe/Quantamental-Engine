"""Tests for parent re-enrichment on child arrival (production parity).

Note: ``enrich_order`` is async since P1.T1; tests wrap with
``asyncio.run``. Fixture schema extended with the columns the new
matcher reads (``status``, ``link_status``, ``calc_match_audit`` table).
"""
import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from core.order_enrichment import enrich_order


# Within new strict matcher's default 300s window (was 24h pre-P1.T1).
RECENT = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
# Epoch-ms of RECENT, for an order's created_at_ms. FLAKE FIX (2026-06-20):
# the matcher's in-window check compares order.created_at_ms against the calc
# timestamp; an order with created_at_ms=0 falls back to LIVE now(). RECENT is
# frozen at module import, so in a long full-suite run now()-RECENT drifts past
# the 300s window and the only match-dependent test (test_both_children_*) fails
# — passing solo (import≈exec) but flaking in the suite. Anchoring the order to
# RECENT_MS makes the window check frozen + deterministic and mirrors production
# (real adapter orders carry created_at_ms, so no now() fallback / warning).
RECENT_MS = int(datetime.fromisoformat(RECENT).timestamp() * 1000)


def _make_db(tmp_path, ptl_rows=None):
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE accounts (id INTEGER PRIMARY KEY, config_json TEXT DEFAULT NULL);
        INSERT INTO accounts (id) VALUES (1);

        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER, exchange_order_id TEXT,
            symbol TEXT, side TEXT, order_type TEXT,
            status TEXT DEFAULT 'new',
            price REAL DEFAULT 0, stop_price REAL DEFAULT 0,
            quantity REAL DEFAULT 0, reduce_only INTEGER DEFAULT 0,
            exchange_position_id TEXT DEFAULT '',
            calc_id TEXT, tp_trigger_price REAL, sl_trigger_price REAL,
            link_status TEXT DEFAULT NULL,
            avg_fill_price REAL DEFAULT 0,
            created_at_ms INTEGER DEFAULT 0, updated_at_ms INTEGER DEFAULT 0,
            last_seen_ms INTEGER DEFAULT 0,
            terminal_position_id TEXT DEFAULT '',
            lifecycle_id TEXT DEFAULT NULL,
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
            sl_price REAL DEFAULT 0, average REAL DEFAULT 0, calc_id TEXT,
            status TEXT DEFAULT NULL,
            window_seconds INTEGER DEFAULT NULL
        );

        CREATE TABLE calc_match_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER, calc_id TEXT, criterion TEXT,
            calc_value TEXT, order_value TEXT, tolerance_used REAL,
            matched INTEGER, ts_ms INTEGER, winning INTEGER
        );
    """)
    if ptl_rows:
        for r in ptl_rows:
            conn.execute(
                "INSERT INTO pre_trade_log "
                "(account_id, timestamp, ticker, side, effective_entry, "
                " tp_price, sl_price, average, calc_id, status) "
                "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (r["timestamp"], r["ticker"], r["side"],
                 r["effective_entry"], r["tp_price"], r["sl_price"],
                 r.get("average", r["effective_entry"]), r["calc_id"],
                 r.get("status", "active")),
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

        asyncio.run(enrich_order({"account_id": 1, "exchange_order_id": "ENTRY",
                       "symbol": "BTCUSDT", "side": "BUY", "order_type": "limit",
                       "exchange_position_id": "POS1"}, db_path))

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
        asyncio.run(enrich_order(dict(parent), db_path))

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
            "order_type, price, exchange_position_id, created_at_ms) "
            "VALUES (1, 'ENTRY', 'BTCUSDT', 'BUY', 'limit', 50000, 'POS1', ?)",
            (RECENT_MS,),
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
        asyncio.run(enrich_order(dict(parent), db_path))

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
        asyncio.run(enrich_order(dict(parent), db_path))

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
