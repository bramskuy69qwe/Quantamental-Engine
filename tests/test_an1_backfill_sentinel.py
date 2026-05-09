"""
AN-1 regression tests — backfill_completed sentinel fix.

Validates that MFE/MAE=0.0 rows with backfill_completed=1 are NOT
reprocessed on startup. The bug: mfe=0 and mae=0 are valid computed
results for tight trades, but were used as "not yet computed" sentinels.

Pre-fix:  tests FAIL — queries use mfe=0/mae=0 sentinel, reprocessing
          valid zero-MFE/MAE rows on every startup.
Post-fix: tests PASS — queries use backfill_completed boolean column.

Run: pytest tests/test_an1_backfill_sentinel.py -v
"""
from __future__ import annotations

import asyncio

import aiosqlite
import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _in_memory_db():
    """Create an in-memory SQLite DB with both affected tables."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("""
        CREATE TABLE exchange_history (
            trade_key   TEXT PRIMARY KEY,
            time        INTEGER NOT NULL,
            symbol      TEXT NOT NULL DEFAULT '',
            income_type TEXT NOT NULL DEFAULT '',
            income      REAL NOT NULL DEFAULT 0.0,
            direction   TEXT NOT NULL DEFAULT '',
            entry_price REAL NOT NULL DEFAULT 0.0,
            exit_price  REAL NOT NULL DEFAULT 0.0,
            qty         REAL NOT NULL DEFAULT 0.0,
            notional    REAL NOT NULL DEFAULT 0.0,
            open_time   INTEGER NOT NULL DEFAULT 0,
            fee         REAL NOT NULL DEFAULT 0.0,
            asset       TEXT NOT NULL DEFAULT '',
            mfe         REAL NOT NULL DEFAULT 0.0,
            mae         REAL NOT NULL DEFAULT 0.0,
            backfill_completed INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute("""
        CREATE TABLE closed_positions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id   INTEGER NOT NULL,
            symbol       TEXT NOT NULL,
            direction    TEXT NOT NULL DEFAULT '',
            quantity     REAL NOT NULL DEFAULT 0,
            entry_price  REAL NOT NULL DEFAULT 0,
            exit_price   REAL NOT NULL DEFAULT 0,
            entry_time_ms INTEGER NOT NULL DEFAULT 0,
            exit_time_ms  INTEGER NOT NULL DEFAULT 0,
            mfe          REAL NOT NULL DEFAULT 0,
            mae          REAL NOT NULL DEFAULT 0,
            backfill_completed INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.commit()
    return conn


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exchange_history_zero_mfe_not_reprocessed():
    """A row with mfe=0, mae=0, backfill_completed=1 must NOT appear
    in get_uncalculated_exchange_rows results."""
    conn = await _in_memory_db()
    # Insert a tight trade: legitimately computed mfe=0, mae=0
    await conn.execute(
        "INSERT INTO exchange_history "
        "(trade_key, time, symbol, open_time, mfe, mae, backfill_completed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("tight_trade_1", 1000, "BTCUSDT", 900, 0.0, 0.0, 1),
    )
    # Insert a genuinely uncalculated row
    await conn.execute(
        "INSERT INTO exchange_history "
        "(trade_key, time, symbol, open_time, mfe, mae, backfill_completed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("needs_calc_1", 2000, "BTCUSDT", 1900, 0.0, 0.0, 0),
    )
    await conn.commit()

    from core.db_exchange import ExchangeMixin

    class FakeDB(ExchangeMixin):
        def __init__(self, c):
            self._conn = c

    db = FakeDB(conn)
    rows = await db.get_uncalculated_exchange_rows("BTCUSDT")
    keys = [r["trade_key"] for r in rows]

    assert "needs_calc_1" in keys, "Genuinely uncalculated row should be returned"
    assert "tight_trade_1" not in keys, (
        "Row with backfill_completed=1 and mfe=0 should NOT be reprocessed"
    )
    await conn.close()


@pytest.mark.asyncio
async def test_closed_positions_zero_mfe_not_reprocessed():
    """A closed_positions row with mfe=0, mae=0, backfill_completed=1
    must NOT appear in get_uncalculated_closed_positions results."""
    conn = await _in_memory_db()
    # Tight trade — completed backfill, legitimate mfe=0
    await conn.execute(
        "INSERT INTO closed_positions "
        "(account_id, symbol, entry_time_ms, exit_time_ms, mfe, mae, backfill_completed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "BTCUSDT", 1000, 2000, 0.0, 0.0, 1),
    )
    # Genuinely uncalculated
    await conn.execute(
        "INSERT INTO closed_positions "
        "(account_id, symbol, entry_time_ms, exit_time_ms, mfe, mae, backfill_completed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "ETHUSDT", 3000, 4000, 0.0, 0.0, 0),
    )
    await conn.commit()

    from core.db_orders import OrdersMixin

    class FakeDB(OrdersMixin):
        def __init__(self, c):
            self._conn = c

    db = FakeDB(conn)
    rows = await db.get_uncalculated_closed_positions(account_id=1)
    syms = [r["symbol"] for r in rows]

    assert "ETHUSDT" in syms, "Genuinely uncalculated row should be returned"
    assert "BTCUSDT" not in syms, (
        "Row with backfill_completed=1 and mfe=0 should NOT be reprocessed"
    )
    await conn.close()


@pytest.mark.asyncio
async def test_update_exchange_mfe_mae_sets_backfill_completed():
    """update_exchange_mfe_mae must set backfill_completed=1."""
    conn = await _in_memory_db()
    await conn.execute(
        "INSERT INTO exchange_history "
        "(trade_key, time, symbol, open_time, mfe, mae, backfill_completed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("trade_1", 1000, "BTCUSDT", 900, 0.0, 0.0, 0),
    )
    await conn.commit()

    from core.db_exchange import ExchangeMixin

    class FakeDB(ExchangeMixin):
        def __init__(self, c):
            self._conn = c

    db = FakeDB(conn)
    await db.update_exchange_mfe_mae("trade_1", 0.05, -0.02)

    async with conn.execute(
        "SELECT mfe, mae, backfill_completed FROM exchange_history WHERE trade_key=?",
        ("trade_1",),
    ) as cur:
        row = await cur.fetchone()
    assert row["mfe"] == 0.05
    assert row["mae"] == -0.02
    assert row["backfill_completed"] == 1
    await conn.close()


@pytest.mark.asyncio
async def test_update_closed_position_mfe_mae_sets_backfill_completed():
    """update_closed_position_mfe_mae must set backfill_completed=1."""
    conn = await _in_memory_db()
    await conn.execute(
        "INSERT INTO closed_positions "
        "(account_id, symbol, entry_time_ms, exit_time_ms, mfe, mae, backfill_completed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "BTCUSDT", 1000, 2000, 0.0, 0.0, 0),
    )
    await conn.commit()

    from core.db_orders import OrdersMixin

    class FakeDB(OrdersMixin):
        def __init__(self, c):
            self._conn = c

    db = FakeDB(conn)
    await db.update_closed_position_mfe_mae(1, 0.0, 0.0)

    async with conn.execute(
        "SELECT mfe, mae, backfill_completed FROM closed_positions WHERE id=1",
    ) as cur:
        row = await cur.fetchone()
    assert row["mfe"] == 0.0
    assert row["mae"] == 0.0
    assert row["backfill_completed"] == 1, (
        "backfill_completed must be 1 even when mfe=mae=0 (valid result)"
    )
    await conn.close()


@pytest.mark.asyncio
async def test_reconciler_backfill_query_uses_backfill_completed():
    """The reconciler backfill_all query must use backfill_completed,
    not mfe=0/mae=0 as sentinel."""
    import inspect
    from core import reconciler
    source = inspect.getsource(reconciler.ReconcilerWorker.backfill_all)
    assert "backfill_completed" in source, (
        "backfill_all query must use backfill_completed column"
    )
    assert "mfe=0" not in source and "mae=0" not in source, (
        "backfill_all must NOT use mfe=0/mae=0 as sentinel"
    )


@pytest.mark.asyncio
async def test_consistency_check_uses_backfill_completed():
    """validate_order_data_consistency must use backfill_completed."""
    import inspect
    from core import db_orders
    source = inspect.getsource(db_orders.OrdersMixin.validate_order_data_consistency)
    assert "backfill_completed" in source, (
        "consistency check must use backfill_completed column"
    )


@pytest.mark.asyncio
async def test_migration_marks_existing_computed_rows():
    """Post-migration UPDATE must mark rows where mfe or mae is nonzero
    as backfill_completed=1, leaving genuinely uncomputed rows pending."""
    conn = await _in_memory_db()

    # Row 1: computed, mfe=0.05, mae=-0.02 → should be marked complete
    await conn.execute(
        "INSERT INTO exchange_history "
        "(trade_key, time, symbol, open_time, mfe, mae, backfill_completed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("computed_1", 1000, "BTCUSDT", 900, 0.05, -0.02, 0),
    )
    # Row 2: computed with negative mae only → should be marked complete
    await conn.execute(
        "INSERT INTO exchange_history "
        "(trade_key, time, symbol, open_time, mfe, mae, backfill_completed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("computed_2", 2000, "ETHUSDT", 1900, 0.0, -0.03, 0),
    )
    # Row 3: genuinely uncomputed (both zero) → should stay pending
    await conn.execute(
        "INSERT INTO exchange_history "
        "(trade_key, time, symbol, open_time, mfe, mae, backfill_completed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("uncomputed_1", 3000, "BTCUSDT", 2900, 0.0, 0.0, 0),
    )
    # Row 4: already marked complete → should stay complete
    await conn.execute(
        "INSERT INTO exchange_history "
        "(trade_key, time, symbol, open_time, mfe, mae, backfill_completed) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("already_done", 4000, "BTCUSDT", 3900, 0.1, -0.05, 1),
    )
    await conn.commit()

    # Run the migration UPDATE (same SQL as database.py initialize)
    await conn.execute(
        "UPDATE exchange_history SET backfill_completed=1"
        " WHERE backfill_completed=0 AND (mfe != 0 OR mae != 0)"
    )
    await conn.commit()

    async with conn.execute(
        "SELECT trade_key, backfill_completed FROM exchange_history ORDER BY time"
    ) as cur:
        rows = {r["trade_key"]: r["backfill_completed"] for r in await cur.fetchall()}

    assert rows["computed_1"] == 1, "Nonzero mfe+mae should be marked complete"
    assert rows["computed_2"] == 1, "Nonzero mae alone should be marked complete"
    assert rows["uncomputed_1"] == 0, "Both-zero row should stay pending"
    assert rows["already_done"] == 1, "Already-complete row should stay complete"

    # Verify: only the genuinely uncomputed row is returned by the query
    from core.db_exchange import ExchangeMixin

    class FakeDB(ExchangeMixin):
        def __init__(self, c):
            self._conn = c

    db = FakeDB(conn)
    pending = await db.get_uncalculated_exchange_rows("BTCUSDT")
    pending_keys = [r["trade_key"] for r in pending]
    assert pending_keys == ["uncomputed_1"], (
        f"Only genuinely uncomputed row should be pending, got: {pending_keys}"
    )
    await conn.close()
