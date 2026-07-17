"""Tests for scripts/clean_test_pollution.py.

Encode the load-bearing intent: REAL rows (uuid4().hex calc_created,
numeric/algo venue orders, real ~$82 dd transitions, startup equity
warnings) are PRESERVED; TEST fixtures (named calc_ids, synthetic order
ids, fixture-price closes, peak_equity 10500/1000 dd, POS-1 close
failures) are DELETED; the run is idempotent; the symbol safety net
prevents real-symbol deletion.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from scripts.clean_test_pollution import (
    classify_trade_event,
    classify_engine_event,
    classify_position_fill_snapshot,
    run_clean,
    REAL_EQUITY_MAX,
)


# ── classify_trade_event ─────────────────────────────────────────────────────


class TestClassifyTradeEvent:
    def test_hex_calc_id_is_real(self):
        assert classify_trade_event(
            "f76b9f51692f4502b23962d4efe3535f", "calc_created",
            {"ticker": "BNBUSDT"},
        ) == "REAL"

    def test_null_calc_numeric_order_is_real(self):
        assert classify_trade_event(
            None, "order_placed", {"exchange_order_id": "868514674", "symbol": "BSBUSDT"},
        ) == "REAL"

    def test_null_calc_algo_order_is_real(self):
        assert classify_trade_event(
            None, "order_placed", {"exchange_order_id": "algo:3000001545568176"},
        ) == "REAL"

    @pytest.mark.parametrize("cid", ["calc-a", "C1", "lc-1", "cr-1", "calc-early"])
    def test_named_calc_id_is_test(self, cid):
        assert classify_trade_event(
            cid, "order_filled", {"symbol": "BTCUSDT", "exchange_order_id": "O-A"},
        ) == "TEST"

    @pytest.mark.parametrize("oid", ["O-C", "O-CLOSE", "ord-1", "binance-order-1", "OID-1", "POS-1"])
    def test_null_calc_synthetic_order_is_test(self, oid):
        assert classify_trade_event(
            None, "order_filled", {"symbol": "BTCUSDT", "exchange_order_id": oid},
        ) == "TEST"

    def test_null_calc_empty_oid_close_is_test(self):
        assert classify_trade_event(
            None, "position_closed",
            {"symbol": "BTCUSDT", "entry_price": 100.0, "exit_price": 110.0},
        ) == "TEST"

    def test_null_calc_empty_oid_partial_close_is_test(self):
        assert classify_trade_event(
            None, "partial_close", {"symbol": "ETHUSDT", "fill_price": 3000.0},
        ) == "TEST"

    def test_safety_net_real_symbol_downgrades_to_unknown(self):
        """A row matching a TEST signature but on a genuinely-traded real
        symbol must NOT be deleted (downgrade to UNKNOWN)."""
        # synthetic-looking oid but a real traded symbol -> keep
        assert classify_trade_event(
            None, "order_filled", {"symbol": "STOUSDT", "exchange_order_id": "O-C"},
        ) == "UNKNOWN"
        # empty-oid close on a real symbol -> keep
        assert classify_trade_event(
            None, "position_closed", {"symbol": "SIRENUSDT"},
        ) == "UNKNOWN"

    def test_null_calc_empty_oid_order_filled_is_unknown(self):
        """order_filled is NOT in the empty-oid TEST rule (only
        position_closed/partial_close are) -> kept."""
        assert classify_trade_event(
            None, "order_filled", {"symbol": "BTCUSDT"},
        ) == "UNKNOWN"

    def test_uppercase_hexlike_calc_id_is_not_real(self):
        """HEX32 is lowercase-only (uuid4().hex). 'CG'/'C1' and uppercase
        strings are fixtures, not real calc_ids."""
        # 32 chars but uppercase -> not the real format -> TEST
        assert classify_trade_event("A" * 32, "calc_created", {}) == "TEST"


# ── classify_position_fill_snapshot (v2.7 Task E) ────────────────────────────


class TestClassifyPositionFillSnapshot:
    @pytest.mark.parametrize("fid", ["70695852", "3383993467", "12345678"])
    def test_numeric_fill_id_is_real(self, fid):
        # real Binance tradeId — even on a test-set symbol
        assert classify_position_fill_snapshot(fid, "BTCUSDT") == "REAL"

    @pytest.mark.parametrize("fid", [
        "tid-100", "tid-RL", "tid-partial", "binance-trade-99",
        "O-CLOSE", "ord-1", "OID-7", "POS-old", "binance-order-1",
    ])
    def test_test_prefix_on_test_symbol_is_test(self, fid):
        assert classify_position_fill_snapshot(fid, "BTCUSDT") == "TEST"
        assert classify_position_fill_snapshot(fid, "ETHUSDT") == "TEST"
        assert classify_position_fill_snapshot(fid, "") == "TEST"

    @pytest.mark.parametrize("sym", ["SPCXUSDT", "VELVETUSDT", "XAUUSDT"])
    def test_safety_net_real_symbol_downgrades_to_unknown(self, sym):
        # a test-prefixed id on a genuinely-traded symbol is NEVER deleted
        assert classify_position_fill_snapshot("tid-100", sym) == "UNKNOWN"

    def test_production_synth_open_leg_is_kept(self):
        # position_snapshot.py emits synth:<tradeId>:open for REAL reversal
        # legs — must NOT be a delete signature
        assert classify_position_fill_snapshot("synth:3383993467:open", "BTCUSDT") == "UNKNOWN"
        assert classify_position_fill_snapshot("synth:70695852:open", "SPCXUSDT") == "UNKNOWN"

    def test_empty_and_unknown_shapes_kept(self):
        assert classify_position_fill_snapshot("", "BTCUSDT") == "UNKNOWN"
        assert classify_position_fill_snapshot(None, "BTCUSDT") == "UNKNOWN"
        assert classify_position_fill_snapshot("weird_id", "BTCUSDT") == "UNKNOWN"


# ── classify_engine_event ────────────────────────────────────────────────────


class TestClassifyEngineEvent:
    def test_dd_test_equity_is_test(self):
        assert classify_engine_event(
            "dd_state_transition", {"peak_equity": 10500.0, "from": "limit", "to": "ok"},
        ) == "TEST"

    def test_dd_round_thousand_is_test(self):
        assert classify_engine_event(
            "dd_state_transition", {"peak_equity": 1000.0},
        ) == "TEST"

    def test_dd_real_equity_is_real(self):
        assert classify_engine_event(
            "dd_state_transition", {"peak_equity": 82.2, "drawdown": 1.0},
        ) == "REAL"

    def test_dd_boundary(self):
        assert classify_engine_event("dd_state_transition", {"peak_equity": REAL_EQUITY_MAX}) == "REAL"
        assert classify_engine_event("dd_state_transition", {"peak_equity": REAL_EQUITY_MAX + 0.01}) == "TEST"

    def test_close_row_build_failed_synthetic_is_test(self):
        assert classify_engine_event(
            "close_row_build_failed",
            {"terminal_position_id": "POS-1", "exchange_order_id": "OID-1"},
        ) == "TEST"

    def test_close_row_build_failed_real_is_unknown(self):
        assert classify_engine_event(
            "close_row_build_failed",
            {"terminal_position_id": "binance-pos-998877", "exchange_order_id": "5512390765"},
        ) == "UNKNOWN"

    def test_equity_delta_warning_is_real(self):
        assert classify_engine_event(
            "equity_delta_warning", {"live": 85.27, "snapshot": 82.19},
        ) == "REAL"

    def test_calc_blocked_contract_is_real(self):
        assert classify_engine_event(
            "calc_blocked_contract", {"ticker": "BTCUSDT", "reason": "below_min_qty"},
        ) == "REAL"


# ── Integration against a synthetic DB ───────────────────────────────────────


def _make_db(tmp_path):
    db = str(tmp_path / "per_account.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE trade_events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "account_id INTEGER, calc_id TEXT, event_type TEXT, payload_json TEXT, "
        "source TEXT, timestamp TEXT)"
    )
    conn.execute(
        "CREATE TABLE engine_events (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "account_id INTEGER, event_type TEXT, payload_json TEXT, timestamp TEXT, source TEXT)"
    )
    return db, conn


def _te(conn, calc_id, et, payload):
    conn.execute(
        "INSERT INTO trade_events (account_id, calc_id, event_type, payload_json, source, timestamp) "
        "VALUES (1, ?, ?, ?, 'order_manager', '2026-05-20T00:00:00+00:00')",
        (calc_id, et, json.dumps(payload)),
    )


def _ee(conn, et, payload):
    conn.execute(
        "INSERT INTO engine_events (account_id, event_type, payload_json, timestamp, source) "
        "VALUES (1, ?, ?, '2026-05-20T00:00:00+00:00', 'data_cache')",
        (et, json.dumps(payload)),
    )


@pytest.fixture
def seeded_db(tmp_path):
    db, conn = _make_db(tmp_path)
    # REAL trade_events (must survive)
    _te(conn, "f76b9f51692f4502b23962d4efe3535f", "calc_created", {"ticker": "BNBUSDT", "side": "long"})
    _te(conn, None, "order_placed", {"exchange_order_id": "868514674"})
    _te(conn, None, "order_canceled", {"exchange_order_id": "algo:3000001545568176"})
    # TEST trade_events (must be deleted)
    _te(conn, "calc-a", "order_filled", {"symbol": "BTCUSDT", "exchange_order_id": "O-A"})
    _te(conn, "C1", "position_closed", {"symbol": "BTCUSDT", "entry_price": 50000.0, "exit_price": 50000.0})
    _te(conn, None, "order_filled", {"symbol": "BTCUSDT", "exchange_order_id": "ord-1"})
    _te(conn, None, "position_closed", {"symbol": "BTCUSDT", "entry_price": 100.0, "exit_price": 110.0})
    _te(conn, None, "partial_close", {"symbol": "ETHUSDT", "fill_price": 3000.0})
    # SAFETY-NET trade_event (TEST-looking but real symbol -> kept as UNKNOWN)
    _te(conn, None, "position_closed", {"symbol": "STOUSDT"})

    # REAL engine_events (survive)
    _ee(conn, "dd_state_transition", {"peak_equity": 82.2, "drawdown": 1.0, "window_days": 30})
    _ee(conn, "equity_delta_warning", {"live": 85.27, "snapshot": 82.19})
    _ee(conn, "calc_blocked_contract", {"ticker": "BTCUSDT", "reason": "below_min_qty"})
    # TEST engine_events (deleted)
    _ee(conn, "dd_state_transition", {"peak_equity": 10500.0, "window_days": 30})
    _ee(conn, "dd_state_transition", {"peak_equity": 1000.0})
    _ee(conn, "close_row_build_failed", {"terminal_position_id": "POS-1", "exchange_order_id": "OID-1"})
    conn.commit()
    conn.close()
    return db


def _count(db, table):
    c = sqlite3.connect(db)
    n = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    c.close()
    return n


def test_dry_run_changes_nothing(seeded_db):
    before_te, before_ee = _count(seeded_db, "trade_events"), _count(seeded_db, "engine_events")
    s = run_clean(seeded_db, apply=False, verbose=False)
    assert s["applied"] is False
    assert s["tables"]["trade_events"]["test"] == 5
    assert s["tables"]["trade_events"]["real"] == 3
    assert s["tables"]["trade_events"]["unknown"] == 1  # STOUSDT safety net
    assert s["tables"]["engine_events"]["test"] == 3
    assert s["tables"]["engine_events"]["real"] == 3
    # nothing deleted
    assert _count(seeded_db, "trade_events") == before_te
    assert _count(seeded_db, "engine_events") == before_ee


def test_apply_deletes_test_keeps_real(seeded_db):
    run_clean(seeded_db, apply=True, verbose=False)
    conn = sqlite3.connect(seeded_db)
    conn.row_factory = sqlite3.Row
    te = conn.execute("SELECT calc_id, event_type, payload_json FROM trade_events").fetchall()
    ee = conn.execute("SELECT event_type, payload_json FROM engine_events").fetchall()
    conn.close()

    # trade_events: 3 real + 1 unknown(STOUSDT) survive; 5 test gone
    assert len(te) == 4
    surviving_calc = {r["calc_id"] for r in te}
    assert "f76b9f51692f4502b23962d4efe3535f" in surviving_calc
    assert "calc-a" not in surviving_calc and "C1" not in surviving_calc
    # the real venue orders survive
    oids = {json.loads(r["payload_json"]).get("exchange_order_id") for r in te}
    assert "868514674" in oids and "algo:3000001545568176" in oids
    # the safety-net STOUSDT close survives
    syms = {json.loads(r["payload_json"]).get("symbol") for r in te}
    assert "STOUSDT" in syms

    # engine_events: 3 real survive; 3 test gone
    assert len(ee) == 3
    peaks = {json.loads(r["payload_json"]).get("peak_equity") for r in ee if r["event_type"] == "dd_state_transition"}
    assert peaks == {82.2}  # 10500 + 1000 deleted
    assert any(r["event_type"] == "equity_delta_warning" for r in ee)
    assert any(r["event_type"] == "calc_blocked_contract" for r in ee)
    assert not any(r["event_type"] == "close_row_build_failed" for r in ee)


def test_idempotent(seeded_db):
    run_clean(seeded_db, apply=True, verbose=False)
    s2 = run_clean(seeded_db, apply=True, verbose=False)
    assert s2["tables"]["trade_events"]["deleted"] == 0
    assert s2["tables"]["engine_events"]["deleted"] == 0


def test_table_filter(seeded_db):
    s = run_clean(seeded_db, apply=True, tables=["engine_events"], verbose=False)
    assert "trade_events" not in s["tables"]
    # trade_events untouched
    assert _count(seeded_db, "trade_events") == 9


def test_missing_table_is_skipped(tmp_path):
    db = str(tmp_path / "empty.db")
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE trade_events (id INTEGER PRIMARY KEY, calc_id TEXT, event_type TEXT, payload_json TEXT)")
    conn.commit()
    conn.close()
    # engine_events absent -> skipped, no crash
    s = run_clean(db, apply=True, verbose=False)
    assert "engine_events" not in s["tables"]
