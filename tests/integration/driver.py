"""
Integration test driver — replays scenarios through real order_manager.

Creates an ephemeral SQLite DB per run, applies all migrations, then
processes events sequentially. Returns final DB state for assertion.
"""
from __future__ import annotations

import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

from tests.integration.scenario import (
    ExpectedEvent, ExpectedFill, ExpectedOrder, ExpectedState, Scenario,
)


def _create_test_db(db_path: str) -> None:
    """Create the legacy-style DB schema needed by order_manager."""
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY, name TEXT
        );
        INSERT OR IGNORE INTO accounts VALUES (1, 'Test');

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            exchange_order_id TEXT,
            terminal_order_id TEXT DEFAULT '',
            client_order_id TEXT DEFAULT '',
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            order_type TEXT DEFAULT '',
            status TEXT DEFAULT 'new',
            price REAL DEFAULT 0,
            stop_price REAL DEFAULT 0,
            quantity REAL DEFAULT 0,
            filled_qty REAL DEFAULT 0,
            avg_fill_price REAL DEFAULT 0,
            reduce_only INTEGER DEFAULT 0,
            time_in_force TEXT DEFAULT '',
            position_side TEXT DEFAULT '',
            exchange_position_id TEXT DEFAULT '',
            terminal_position_id TEXT DEFAULT '',
            source TEXT DEFAULT '',
            created_at_ms INTEGER DEFAULT 0,
            updated_at_ms INTEGER DEFAULT 0,
            last_seen_ms INTEGER DEFAULT 0,
            calc_id TEXT,
            tp_trigger_price REAL,
            sl_trigger_price REAL,
            UNIQUE(account_id, exchange_order_id)
        );

        CREATE TABLE IF NOT EXISTS fills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            exchange_fill_id TEXT,
            terminal_fill_id TEXT DEFAULT '',
            exchange_order_id TEXT DEFAULT '',
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            direction TEXT DEFAULT '',
            price REAL DEFAULT 0,
            quantity REAL DEFAULT 0,
            fee REAL DEFAULT 0,
            fee_asset TEXT DEFAULT 'USDT',
            exchange_position_id TEXT DEFAULT '',
            terminal_position_id TEXT DEFAULT '',
            is_close INTEGER DEFAULT 0,
            realized_pnl REAL DEFAULT 0,
            role TEXT DEFAULT '',
            source TEXT DEFAULT '',
            timestamp_ms INTEGER DEFAULT 0,
            calc_id TEXT,
            fill_type TEXT,
            slippage_actual REAL,
            UNIQUE(account_id, exchange_fill_id)
        );

        CREATE TABLE IF NOT EXISTS pre_trade_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER DEFAULT 1,
            timestamp TEXT, ticker TEXT, side TEXT DEFAULT '',
            average REAL DEFAULT 0, effective_entry REAL DEFAULT 0,
            tp_price REAL DEFAULT 0, sl_price REAL DEFAULT 0,
            one_percent_depth REAL DEFAULT 0, individual_risk REAL DEFAULT 0,
            tp_amount_pct REAL DEFAULT 0, tp_usdt REAL DEFAULT 0,
            sl_amount_pct REAL DEFAULT 0, sl_usdt REAL DEFAULT 0,
            model_name TEXT DEFAULT '', model_desc TEXT DEFAULT '',
            risk_usdt REAL DEFAULT 0, atr_c TEXT DEFAULT '',
            atr_category TEXT DEFAULT '', est_slippage REAL DEFAULT 0,
            size REAL DEFAULT 0, notional REAL DEFAULT 0,
            est_profit REAL DEFAULT 0, est_loss REAL DEFAULT 0,
            est_r REAL DEFAULT 0, est_exposure REAL DEFAULT 0,
            eligible INTEGER DEFAULT 0, notes TEXT DEFAULT '',
            calc_id TEXT
        );

        CREATE TABLE IF NOT EXISTS closed_positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER, exchange_position_id TEXT,
            terminal_position_id TEXT DEFAULT '',
            symbol TEXT, direction TEXT DEFAULT '',
            quantity REAL DEFAULT 0, entry_price REAL DEFAULT 0,
            exit_price REAL DEFAULT 0, entry_time_ms INTEGER DEFAULT 0,
            exit_time_ms INTEGER DEFAULT 0, realized_pnl REAL DEFAULT 0,
            total_fees REAL DEFAULT 0, net_pnl REAL DEFAULT 0,
            funding_fees REAL DEFAULT 0, mfe REAL DEFAULT 0,
            mae REAL DEFAULT 0, hold_time_ms INTEGER DEFAULT 0,
            exit_reason TEXT DEFAULT '', model_name TEXT DEFAULT '',
            notes TEXT DEFAULT '', shortfall_entry REAL DEFAULT 0,
            shortfall_exit REAL DEFAULT 0, source TEXT DEFAULT '',
            backfill_completed INTEGER DEFAULT 0, calc_id TEXT,
            UNIQUE(account_id, terminal_position_id, exit_time_ms)
        );
    """)
    conn.commit()
    conn.close()


def _create_per_account_db(data_dir: str) -> None:
    """Create per-account DB with migrations for trade_events + engine_events."""
    pa_dir = os.path.join(data_dir, "per_account")
    os.makedirs(pa_dir, exist_ok=True)
    db_path = os.path.join(pa_dir, "test__broker__1.db")

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO accounts VALUES (1, 'Test')")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS pre_trade_log ("
        "id INTEGER PRIMARY KEY, timestamp TEXT, ticker TEXT, "
        "average REAL DEFAULT 0, side TEXT DEFAULT '', "
        "account_id INTEGER DEFAULT 1)"
    )
    conn.commit()
    conn.close()

    # Apply all migrations (creates trade_events, engine_events, account_settings)
    from core.migrations.runner import run_all as _run_migrations
    import core.migrations.runner as _runner_mod
    real_mdir = os.path.dirname(os.path.abspath(_runner_mod.__file__))

    marker = os.path.join(data_dir, ".split-complete-v1")
    with open(marker, "w") as f:
        f.write("v1")

    _run_migrations(data_dir, real_mdir)


def run_scenario_sync(
    scenario: Scenario,
    tmp_path: str,
    account_id: int = 1,
) -> Dict[str, Any]:
    """Replay scenario events and return final DB state.

    Returns dict with keys: orders, fills, trade_events.
    """
    import config as _cfg

    data_dir = os.path.join(tmp_path, "data")
    os.makedirs(data_dir, exist_ok=True)
    db_path = os.path.join(data_dir, "legacy.db")

    _create_test_db(db_path)
    _create_per_account_db(data_dir)

    # Process events
    for event in sorted(scenario.events, key=lambda e: e.t_ms):
        p = event.payload

        if event.type == "calc_created":
            conn = sqlite3.connect(db_path)
            conn.execute(
                "INSERT INTO pre_trade_log "
                "(account_id, timestamp, ticker, side, effective_entry, "
                "tp_price, sl_price, average, calc_id, eligible) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                (account_id, p.get("timestamp", ""), p["ticker"], p["side"],
                 p["effective_entry"], p["tp_price"], p["sl_price"],
                 p.get("average", p["effective_entry"]), p["calc_id"]),
            )
            conn.commit()
            conn.close()

        elif event.type == "order_persisted":
            _upsert_order_sync(db_path, account_id, p)
            _enrich_order_sync(db_path, p, account_id)
            # When a child (TP/SL) arrives, re-enrich the parent entry —
            # mirrors production where repeated order updates trigger enrichment
            if p.get("reduce_only"):
                _re_enrich_parent_entry(db_path, account_id, p.get("exchange_position_id", ""))

        elif event.type == "fill_received":
            _upsert_fill_sync(db_path, account_id, p)
            _enrich_fill_sync(db_path, p, account_id)

        elif event.type == "order_modified":
            _upsert_order_sync(db_path, account_id, p)
            _enrich_order_sync(db_path, p, account_id)
            # Do NOT re-enrich parent on modification — that would overwrite
            # trigger prices with modified values before correlation runs.
            # In production, correlation already ran on an earlier update.

        elif event.type == "order_canceled":
            p.setdefault("status", "canceled")
            _upsert_order_sync(db_path, account_id, p)

    # Read final state
    return _read_final_state(db_path, data_dir, account_id)


def _upsert_order_sync(db_path: str, aid: int, p: dict) -> None:
    conn = sqlite3.connect(db_path)
    now_ms = int(time.time() * 1000)
    conn.execute("""
        INSERT INTO orders (
            account_id, exchange_order_id, symbol, side, order_type, status,
            price, stop_price, quantity, reduce_only, exchange_position_id,
            created_at_ms, updated_at_ms, last_seen_ms
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id, exchange_order_id) DO UPDATE SET
            status = excluded.status,
            price = excluded.price,
            stop_price = excluded.stop_price,
            quantity = excluded.quantity,
            updated_at_ms = excluded.updated_at_ms,
            last_seen_ms = excluded.last_seen_ms
    """, (
        aid, p.get("exchange_order_id", ""), p.get("symbol", ""),
        p.get("side", ""), p.get("order_type", ""), p.get("status", "new"),
        p.get("price", 0), p.get("stop_price", 0), p.get("quantity", 0),
        int(p.get("reduce_only", False)), p.get("exchange_position_id", ""),
        p.get("created_at_ms", now_ms), p.get("updated_at_ms", now_ms), now_ms,
    ))
    conn.commit()
    conn.close()


def _enrich_order_sync(db_path: str, p: dict, aid: int) -> None:
    try:
        from core.order_enrichment import enrich_order
        order = {**p, "account_id": aid}
        enrich_order(order, db_path)
    except Exception:
        pass


def _upsert_fill_sync(db_path: str, aid: int, p: dict) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO fills (
            account_id, exchange_fill_id, exchange_order_id, symbol, side,
            direction, price, quantity, fee, is_close, realized_pnl,
            role, source, timestamp_ms, exchange_position_id,
            terminal_position_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_id, exchange_fill_id) DO UPDATE SET
            price = excluded.price, quantity = excluded.quantity
    """, (
        aid, p.get("exchange_fill_id", ""), p.get("exchange_order_id", ""),
        p.get("symbol", ""), p.get("side", ""), p.get("direction", ""),
        p.get("price", 0), p.get("quantity", 0), p.get("fee", 0),
        int(p.get("is_close", False)), p.get("realized_pnl", 0),
        p.get("role", ""), p.get("source", ""), p.get("timestamp_ms", 0),
        p.get("exchange_position_id", ""), p.get("terminal_position_id", ""),
    ))
    conn.commit()
    conn.close()


def _re_enrich_parent_entry(db_path: str, aid: int, pos_id: str) -> None:
    """Re-enrich the entry order for a position after a child arrives."""
    if not pos_id:
        return
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM orders WHERE account_id = ? AND exchange_position_id = ? "
            "AND reduce_only = 0 LIMIT 1",
            (aid, pos_id),
        ).fetchone()
        conn.close()
        if row:
            from core.order_enrichment import enrich_order
            enrich_order(dict(row), db_path)
    except Exception:
        pass


def _enrich_fill_sync(db_path: str, p: dict, aid: int) -> None:
    try:
        from core.order_enrichment import enrich_fill
        fill = {**p, "account_id": aid}
        enrich_fill(fill, db_path)
    except Exception:
        pass



def _read_final_state(db_path: str, data_dir: str, aid: int) -> Dict[str, Any]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    orders = [dict(r) for r in conn.execute(
        "SELECT * FROM orders WHERE account_id = ? ORDER BY created_at_ms", (aid,)
    ).fetchall()]

    fills = [dict(r) for r in conn.execute(
        "SELECT * FROM fills WHERE account_id = ? ORDER BY timestamp_ms", (aid,)
    ).fetchall()]
    conn.close()

    # Read trade_events from per-account DB
    trade_events: List[Dict] = []
    pa_path = os.path.join(data_dir, "per_account", "test__broker__1.db")
    if os.path.exists(pa_path):
        conn = sqlite3.connect(pa_path)
        conn.row_factory = sqlite3.Row
        try:
            trade_events = [dict(r) for r in conn.execute(
                "SELECT * FROM trade_events WHERE account_id = ? ORDER BY timestamp ASC",
                (aid,),
            ).fetchall()]
        except Exception:
            pass
        conn.close()

    return {"orders": orders, "fills": fills, "trade_events": trade_events}


def assert_scenario_state(scenario: Scenario, actual: Dict[str, Any]) -> None:
    """Assert final state matches expected. Raises AssertionError with context."""
    _assert_orders(scenario.expected.orders, actual["orders"])
    _assert_fills(scenario.expected.fills, actual["fills"])
    _assert_events(scenario.expected.trade_events, actual["trade_events"])


def _assert_orders(expected: List[ExpectedOrder], actual: List[Dict]) -> None:
    actual_map = {o["exchange_order_id"]: o for o in actual}
    for exp in expected:
        assert exp.exchange_order_id in actual_map, (
            f"Order {exp.exchange_order_id} not found in DB"
        )
        row = actual_map[exp.exchange_order_id]
        if exp.calc_id == "*":
            assert row["calc_id"] is not None, (
                f"Order {exp.exchange_order_id}: expected calc_id non-NULL, got NULL"
            )
        elif exp.calc_id is not None:
            assert row["calc_id"] == exp.calc_id, (
                f"Order {exp.exchange_order_id}: calc_id={row['calc_id']}, expected={exp.calc_id}"
            )
        if exp.tp_trigger_price is not None:
            assert row["tp_trigger_price"] == exp.tp_trigger_price, (
                f"Order {exp.exchange_order_id}: tp_trigger={row['tp_trigger_price']}, expected={exp.tp_trigger_price}"
            )
        if exp.sl_trigger_price is not None:
            assert row["sl_trigger_price"] == exp.sl_trigger_price, (
                f"Order {exp.exchange_order_id}: sl_trigger={row['sl_trigger_price']}, expected={exp.sl_trigger_price}"
            )


def _assert_fills(expected: List[ExpectedFill], actual: List[Dict]) -> None:
    actual_map = {f["exchange_fill_id"]: f for f in actual}
    for exp in expected:
        assert exp.fill_id in actual_map, (
            f"Fill {exp.fill_id} not found in DB"
        )
        row = actual_map[exp.fill_id]
        if exp.calc_id == "*":
            assert row["calc_id"] is not None, (
                f"Fill {exp.fill_id}: expected calc_id non-NULL"
            )
        elif exp.calc_id is not None:
            assert row["calc_id"] == exp.calc_id, (
                f"Fill {exp.fill_id}: calc_id={row['calc_id']}, expected={exp.calc_id}"
            )
        if exp.fill_type:
            assert row["fill_type"] == exp.fill_type, (
                f"Fill {exp.fill_id}: fill_type={row['fill_type']}, expected={exp.fill_type}"
            )
        if exp.slippage_actual is not None:
            assert row["slippage_actual"] is not None, (
                f"Fill {exp.fill_id}: slippage_actual is NULL, expected {exp.slippage_actual}"
            )
            assert abs(row["slippage_actual"] - exp.slippage_actual) <= exp.slippage_tolerance, (
                f"Fill {exp.fill_id}: slippage={row['slippage_actual']}, "
                f"expected={exp.slippage_actual} ±{exp.slippage_tolerance}"
            )


def _assert_events(expected: List[ExpectedEvent], actual: List[Dict]) -> None:
    actual_types = [e["event_type"] for e in actual]
    for i, exp in enumerate(expected):
        matching = [e for e in actual if e["event_type"] == exp.type]
        assert matching, (
            f"Expected event [{i}] type={exp.type} not found. "
            f"Actual types: {actual_types}"
        )
        if exp.payload_includes:
            import json
            found = False
            for m in matching:
                try:
                    payload = json.loads(m.get("payload_json", "{}"))
                    if all(payload.get(k) == v for k, v in exp.payload_includes.items()):
                        found = True
                        break
                except Exception:
                    continue
            assert found, (
                f"Expected event [{i}] type={exp.type} with payload "
                f"including {exp.payload_includes} not found in matching events"
            )
