"""Tests for slippage_actual computation + fill_type classification + market correlation."""
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from core.order_enrichment import classify_fill_type, compute_slippage_actual
from core.calc_correlation import correlate_order_to_calc


RECENT = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()


def _make_db(tmp_path, ptl_rows=None):
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO accounts VALUES (1)")
    conn.execute("""CREATE TABLE pre_trade_log (
        id INTEGER PRIMARY KEY, account_id INTEGER DEFAULT 1,
        timestamp TEXT, ticker TEXT, side TEXT, effective_entry REAL,
        tp_price REAL, sl_price REAL, average REAL, calc_id TEXT
    )""")
    conn.execute("""CREATE TABLE orders (
        id INTEGER PRIMARY KEY, account_id INTEGER,
        exchange_order_id TEXT, symbol TEXT, side TEXT, order_type TEXT,
        price REAL DEFAULT 0, stop_price REAL DEFAULT 0,
        reduce_only INTEGER DEFAULT 0, calc_id TEXT,
        tp_trigger_price REAL, sl_trigger_price REAL,
        UNIQUE(account_id, exchange_order_id)
    )""")
    conn.execute("""CREATE TABLE fills (
        id INTEGER PRIMARY KEY, account_id INTEGER,
        exchange_fill_id TEXT, exchange_order_id TEXT,
        price REAL DEFAULT 0, quantity REAL DEFAULT 0,
        is_close INTEGER DEFAULT 0, calc_id TEXT,
        fill_type TEXT, slippage_actual REAL,
        UNIQUE(account_id, exchange_fill_id)
    )""")
    if ptl_rows:
        for r in ptl_rows:
            conn.execute(
                "INSERT INTO pre_trade_log (account_id, timestamp, ticker, side, "
                "effective_entry, tp_price, sl_price, average, calc_id) "
                "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)",
                (r["timestamp"], r["ticker"], r["side"],
                 r["effective_entry"], r["tp_price"], r["sl_price"],
                 r.get("average", r["effective_entry"]), r["calc_id"]),
            )
    conn.commit()
    conn.close()
    return db_path


class TestClassifyFillType:
    def test_entry(self):
        assert classify_fill_type({"is_close": False}, {"order_type": "limit"}) == "entry"

    def test_tp(self):
        assert classify_fill_type({}, {"order_type": "take_profit_market"}) == "tp"

    def test_sl(self):
        assert classify_fill_type({}, {"order_type": "stop_market"}) == "sl"

    def test_manual_close(self):
        assert classify_fill_type({"is_close": True}, {"order_type": "limit"}) == "manual"

    def test_reduce_only(self):
        assert classify_fill_type({}, {"order_type": "limit", "reduce_only": True}) == "reduce_only"


class TestSlippageActual:
    def test_entry_slippage_zero_at_exact(self, tmp_path):
        db_path = _make_db(tmp_path, ptl_rows=[{
            "timestamp": RECENT, "ticker": "BTCUSDT", "side": "BUY",
            "effective_entry": 50000, "tp_price": 55000, "sl_price": 48000,
            "calc_id": "c1",
        }])
        fill = {"price": 50000, "calc_id": "c1", "account_id": 1}
        slip = compute_slippage_actual(fill, None, "entry", db_path)
        assert slip == 0.0

    def test_entry_slippage_positive(self, tmp_path):
        db_path = _make_db(tmp_path, ptl_rows=[{
            "timestamp": RECENT, "ticker": "BTCUSDT", "side": "BUY",
            "effective_entry": 50000, "tp_price": 55000, "sl_price": 48000,
            "calc_id": "c2",
        }])
        fill = {"price": 50050, "calc_id": "c2", "account_id": 1}
        slip = compute_slippage_actual(fill, None, "entry", db_path)
        assert slip == pytest.approx(0.001)

    def test_tp_uses_parent_order_trigger(self):
        parent = {"stop_price": 55000, "order_type": "take_profit_market"}
        fill = {"price": 54950, "account_id": 1}
        slip = compute_slippage_actual(fill, parent, "tp", "")
        assert slip == pytest.approx((54950 - 55000) / 55000)

    def test_sl_uses_parent_order_trigger(self):
        parent = {"stop_price": 48000, "order_type": "stop_market"}
        fill = {"price": 47950, "account_id": 1}
        slip = compute_slippage_actual(fill, parent, "sl", "")
        assert slip == pytest.approx((47950 - 48000) / 48000)

    def test_manual_returns_none(self):
        assert compute_slippage_actual({"price": 50000}, None, "manual", "") is None

    def test_no_calc_id_returns_none(self, tmp_path):
        db_path = _make_db(tmp_path)
        fill = {"price": 50000, "account_id": 1}  # no calc_id
        assert compute_slippage_actual(fill, None, "entry", db_path) is None


class TestMarketOrderCorrelation:
    def test_market_matches_on_tp_sl_only(self, tmp_path):
        db_path = _make_db(tmp_path, ptl_rows=[{
            "timestamp": RECENT, "ticker": "BTCUSDT", "side": "BUY",
            "effective_entry": 50000, "tp_price": 55000, "sl_price": 48000,
            "calc_id": "c-mkt",
        }])
        order = {
            "account_id": 1, "symbol": "BTCUSDT", "side": "BUY",
            "order_type": "market", "price": 50500,  # entry is wildcard
            "tp_trigger_price": 55000, "sl_trigger_price": 48000,
        }
        result = correlate_order_to_calc(order, tick_size=0.1, db_path=db_path)
        assert result == "c-mkt"

    def test_market_missing_tp_returns_none(self, tmp_path):
        db_path = _make_db(tmp_path, ptl_rows=[{
            "timestamp": RECENT, "ticker": "BTCUSDT", "side": "BUY",
            "effective_entry": 50000, "tp_price": 55000, "sl_price": 48000,
            "calc_id": "c-mkt2",
        }])
        order = {
            "account_id": 1, "symbol": "BTCUSDT", "side": "BUY",
            "order_type": "market", "price": 50500,
            "sl_trigger_price": 48000,  # tp missing
        }
        result = correlate_order_to_calc(order, tick_size=0.1, db_path=db_path)
        assert result is None
