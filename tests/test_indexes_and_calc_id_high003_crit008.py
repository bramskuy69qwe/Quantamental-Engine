"""
Regression tests for CRIT-008 (Task 88.1) and HIGH-003 (Task 88.1).

CRIT-008: pre_trade_log.calc_id column must exist on the legacy DB after
initialize(). Without it, Task 88's batch helper and several other
production query sites 500 on fresh installs.

HIGH-003: two indexes (idx_pretrade_calc_id, idx_orders_calc_id) speed up
hot calc_id lookups. orders.exchange_order_id is already covered by the
UNIQUE(account_id, exchange_order_id) auto-index — no third index here.

Run: pytest tests/test_indexes_and_calc_id_high003_crit008.py -v
"""
from __future__ import annotations

import pytest

from core.database import DatabaseManager


async def _make_init_db(tmp_path):
    """Spin up a real DatabaseManager against a tmp_path .db file.
    Returns the open manager; caller must close conn."""
    db_path = str(tmp_path / "legacy_test.db")
    mgr = DatabaseManager(path=db_path)
    await mgr.initialize()
    return mgr


async def _populate(mgr, n=200):
    """Seed pre_trade_log + orders with n rows each for EXPLAIN-plan stability."""
    for i in range(n):
        await mgr._conn.execute(
            "INSERT INTO pre_trade_log (timestamp, ticker, calc_id) VALUES (?, ?, ?)",
            (f"2026-05-18T00:00:{i:02d}", "BTCUSDT", f"c{i}"),
        )
        await mgr._conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, calc_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (1, f"O{i}", "BTCUSDT", "BUY", f"c{i}"),
        )
    await mgr._conn.execute("ANALYZE")
    await mgr._conn.commit()


# ── CRIT-008: column existence ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pretrade_log_has_calc_id_column_after_init(tmp_path):
    """CRIT-008 regression: pre_trade_log.calc_id must exist as queryable column."""
    mgr = await _make_init_db(tmp_path)
    try:
        async with mgr._conn.execute("PRAGMA table_info(pre_trade_log)") as cur:
            cols = await cur.fetchall()
        names = {row[1] for row in cols}
        assert "calc_id" in names, (
            "CRIT-008: pre_trade_log.calc_id missing — Task 88 batch helper "
            "and frag_position_fills will 500 on this DB."
        )
        # Type column (idx 2) should be TEXT
        calc_id_type = next(row[2] for row in cols if row[1] == "calc_id")
        assert calc_id_type.upper() == "TEXT"
        # Round-trip a real value
        await mgr._conn.execute(
            "INSERT INTO pre_trade_log (timestamp, ticker, calc_id) VALUES (?, ?, ?)",
            ("2026-05-18T00:00:00", "BTCUSDT", "round-trip"),
        )
        async with mgr._conn.execute(
            "SELECT calc_id FROM pre_trade_log WHERE calc_id=?", ("round-trip",)
        ) as cur:
            row = await cur.fetchone()
        assert row is not None and row[0] == "round-trip"
    finally:
        await mgr._conn.close()


@pytest.mark.asyncio
async def test_pretrade_calc_id_alter_idempotent_on_re_init(tmp_path):
    """CRIT-008 regression: re-running initialize() doesn't error on existing column."""
    db_path = str(tmp_path / "legacy_test.db")
    mgr1 = DatabaseManager(path=db_path)
    await mgr1.initialize()
    await mgr1._conn.close()
    # Second initialize() on the same path must not raise
    mgr2 = DatabaseManager(path=db_path)
    await mgr2.initialize()
    try:
        async with mgr2._conn.execute("PRAGMA table_info(pre_trade_log)") as cur:
            cols = await cur.fetchall()
        names = [row[1] for row in cols]
        assert names.count("calc_id") == 1
    finally:
        await mgr2._conn.close()


# ── HIGH-003: index existence ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_idx_pretrade_calc_id_exists_after_init(tmp_path):
    """HIGH-003 regression: idx_pretrade_calc_id is created on initialize()."""
    mgr = await _make_init_db(tmp_path)
    try:
        async with mgr._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_pretrade_calc_id'"
        ) as cur:
            rows = await cur.fetchall()
        assert len(rows) == 1
    finally:
        await mgr._conn.close()


@pytest.mark.asyncio
async def test_idx_orders_calc_id_exists_after_init(tmp_path):
    """HIGH-003 regression: idx_orders_calc_id is created on initialize()."""
    mgr = await _make_init_db(tmp_path)
    try:
        async with mgr._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_orders_calc_id'"
        ) as cur:
            rows = await cur.fetchall()
        assert len(rows) == 1
    finally:
        await mgr._conn.close()


# ── HIGH-003: EXPLAIN QUERY PLAN — indexes are actually used ─────────────────

@pytest.mark.asyncio
async def test_pretrade_calc_id_single_lookup_uses_index(tmp_path):
    """EXPLAIN QUERY PLAN proves idx_pretrade_calc_id is used for single-key lookup."""
    mgr = await _make_init_db(tmp_path)
    try:
        await _populate(mgr)
        async with mgr._conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM pre_trade_log WHERE calc_id = ?", ("c1",)
        ) as cur:
            plan = " ".join(str(tuple(row)) for row in await cur.fetchall())
        assert "idx_pretrade_calc_id" in plan, (
            f"Expected idx_pretrade_calc_id in plan; got: {plan}"
        )
    finally:
        await mgr._conn.close()


@pytest.mark.asyncio
async def test_pretrade_calc_id_in_clause_uses_index(tmp_path):
    """EXPLAIN QUERY PLAN for Task 88's batch shape (calc_id IN (...))."""
    mgr = await _make_init_db(tmp_path)
    try:
        await _populate(mgr)
        async with mgr._conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM pre_trade_log WHERE calc_id IN (?, ?, ?)",
            ("c1", "c2", "c3"),
        ) as cur:
            plan = " ".join(str(tuple(row)) for row in await cur.fetchall())
        assert "idx_pretrade_calc_id" in plan, (
            f"Task 88 batch shape must use the index; got: {plan}"
        )
    finally:
        await mgr._conn.close()


@pytest.mark.asyncio
async def test_orders_calc_id_lookup_uses_index(tmp_path):
    """EXPLAIN QUERY PLAN proves idx_orders_calc_id is used."""
    mgr = await _make_init_db(tmp_path)
    try:
        await _populate(mgr)
        async with mgr._conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM orders WHERE calc_id = ?", ("c1",)
        ) as cur:
            plan = " ".join(str(tuple(row)) for row in await cur.fetchall())
        assert "idx_orders_calc_id" in plan, (
            f"Expected idx_orders_calc_id in plan; got: {plan}"
        )
    finally:
        await mgr._conn.close()


@pytest.mark.asyncio
async def test_init_idempotent_on_existing_db(tmp_path):
    """initialize() runs cleanly twice; indexes still present exactly once."""
    db_path = str(tmp_path / "idempotent.db")
    mgr1 = DatabaseManager(path=db_path)
    await mgr1.initialize()
    await mgr1._conn.close()
    mgr2 = DatabaseManager(path=db_path)
    await mgr2.initialize()
    try:
        async with mgr2._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name IN ('idx_pretrade_calc_id', 'idx_orders_calc_id') ORDER BY name"
        ) as cur:
            rows = await cur.fetchall()
        names = [r[0] for r in rows]
        assert names == ["idx_orders_calc_id", "idx_pretrade_calc_id"]
    finally:
        await mgr2._conn.close()
