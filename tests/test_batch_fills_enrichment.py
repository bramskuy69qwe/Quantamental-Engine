"""
Regression tests for CRIT-001 — batch-fetch in position_fills enrichment.

Pins the two batch helpers added in Task 88:
  - core.db_orders.OrdersMixin.get_pretrade_logs_by_calc_ids
  - core.db_orders.OrdersMixin.get_order_types_by_ids

Plus query-count regression assertions that fail loudly if a future
refactor reintroduces the N+1 pattern in either helper.

The route handler at api/routes_orders.py::frag_position_fills is exercised
manually + by the existing template/integration surface. This file pins the
batch contract that route depends on; if the helpers stay O(1) in query
count regardless of input size, the route is safe.

Run: pytest tests/test_batch_fills_enrichment.py -v
"""
from __future__ import annotations

import aiosqlite
import pytest

from core.db_orders import OrdersMixin


class _DB(OrdersMixin):
    """Minimal test harness; only needs _conn for the batch methods."""

    def __init__(self, conn):
        self._conn = conn


async def _make_db():
    """In-memory aiosqlite DB with just the schema the batch helpers need."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript("""
        CREATE TABLE pre_trade_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            calc_id TEXT,
            average REAL,
            tp_price REAL,
            sl_price REAL
        );
        CREATE TABLE orders (
            account_id INTEGER,
            exchange_order_id TEXT,
            order_type TEXT
        );
    """)
    return _DB(conn), conn


def _install_select_counter(conn):
    """Wrap conn.execute so SELECT queries are counted. Returns the list."""
    queries = []
    real_execute = conn.execute

    def counting_execute(sql, *args, **kwargs):
        if sql.strip().upper().startswith("SELECT"):
            queries.append(sql)
        return real_execute(sql, *args, **kwargs)

    conn.execute = counting_execute
    return queries


# ── get_pretrade_logs_by_calc_ids ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_batch_pretrade_returns_dict_keyed_by_calc_id():
    db, conn = await _make_db()
    try:
        await conn.execute(
            "INSERT INTO pre_trade_log (calc_id, average, tp_price, sl_price) VALUES (?, ?, ?, ?)",
            ("c1", 100, 110, 95),
        )
        await conn.execute(
            "INSERT INTO pre_trade_log (calc_id, average, tp_price, sl_price) VALUES (?, ?, ?, ?)",
            ("c2", 200, 220, 190),
        )
        out = await db.get_pretrade_logs_by_calc_ids(["c1", "c2", "missing"])
        assert set(out.keys()) == {"c1", "c2"}, "missing calc_ids should be absent"
        assert out["c1"]["average"] == 100
        assert out["c2"]["tp_price"] == 220
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_batch_pretrade_empty_input_no_query():
    """Defensive: empty input returns {} without firing a SELECT."""
    db, conn = await _make_db()
    queries = _install_select_counter(conn)
    try:
        out = await db.get_pretrade_logs_by_calc_ids([])
        assert out == {}
        assert len(queries) == 0, "Empty input must short-circuit before SQL"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_batch_pretrade_50_fills_fires_one_query():
    """CRIT-001 pin: 50 calc_ids → 1 batched SELECT (was 50 individual queries pre-fix)."""
    db, conn = await _make_db()
    for i in range(50):
        await conn.execute(
            "INSERT INTO pre_trade_log (calc_id, average, tp_price, sl_price) VALUES (?, ?, ?, ?)",
            (f"c{i}", 100 + i, 110 + i, 95 + i),
        )
    queries = _install_select_counter(conn)
    try:
        out = await db.get_pretrade_logs_by_calc_ids([f"c{i}" for i in range(50)])
        assert len(out) == 50
        assert len(queries) == 1, (
            f"Expected 1 SELECT for 50 IDs (CRIT-001 batch); got {len(queries)}. "
            "N+1 pattern reintroduced?"
        )
    finally:
        await conn.close()


# ── get_order_types_by_ids ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_batch_order_types_returns_dict_keyed_by_order_id():
    db, conn = await _make_db()
    try:
        await conn.execute("INSERT INTO orders VALUES (?, ?, ?)", (1, "O1", "LIMIT"))
        await conn.execute("INSERT INTO orders VALUES (?, ?, ?)", (1, "O2", "MARKET"))
        out = await db.get_order_types_by_ids(1, ["O1", "O2", "missing"])
        assert out == {"O1": "LIMIT", "O2": "MARKET"}
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_batch_order_types_scoped_to_account():
    """Account isolation: same exchange_order_id under a different account must not leak."""
    db, conn = await _make_db()
    try:
        await conn.execute("INSERT INTO orders VALUES (?, ?, ?)", (1, "O1", "LIMIT"))
        await conn.execute("INSERT INTO orders VALUES (?, ?, ?)", (2, "O1", "MARKET"))
        out = await db.get_order_types_by_ids(1, ["O1"])
        assert out == {"O1": "LIMIT"}, "Account 2's row must not bleed into account 1"
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_batch_order_types_50_ids_fires_one_query():
    """CRIT-001 pin: 50 order_ids → 1 batched SELECT (was 50 pre-fix)."""
    db, conn = await _make_db()
    for i in range(50):
        await conn.execute(
            "INSERT INTO orders VALUES (?, ?, ?)",
            (1, f"O{i}", "LIMIT"),
        )
    queries = _install_select_counter(conn)
    try:
        out = await db.get_order_types_by_ids(1, [f"O{i}" for i in range(50)])
        assert len(out) == 50
        assert len(queries) == 1, (
            f"Expected 1 SELECT for 50 IDs (CRIT-001 batch); got {len(queries)}. "
            "N+1 pattern reintroduced?"
        )
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_batch_order_types_empty_input_no_query():
    db, conn = await _make_db()
    queries = _install_select_counter(conn)
    try:
        out = await db.get_order_types_by_ids(1, [])
        assert out == {}
        assert len(queries) == 0
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_batch_order_types_null_order_type_coerced_to_empty_string():
    """Per pre-fix per-fill code: `order_type = orow['order_type'] or ''`.
    Batch helper must preserve that contract (NULL → '')."""
    db, conn = await _make_db()
    try:
        await conn.execute("INSERT INTO orders VALUES (?, ?, ?)", (1, "O1", None))
        out = await db.get_order_types_by_ids(1, ["O1"])
        assert out == {"O1": ""}
    finally:
        await conn.close()
