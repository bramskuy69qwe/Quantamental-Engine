"""
Database integration tests — runs against a temporary in-memory SQLite DB.
Covers: initialization, migrations, snapshot upserts, regime queries.
"""
import asyncio
import os
import tempfile
import pytest
import pytest_asyncio

# Ensure project root on path
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest_asyncio.fixture
async def test_db():
    """Create a temporary DatabaseManager connected to a file-based SQLite DB."""
    from core.database import DatabaseManager

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    yield db
    await db.close()
    try:
        os.unlink(tmp.name)
        # Clean up WAL/SHM files too
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


# ── Initialization ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_initialize_creates_tables(test_db):
    """All expected tables exist after initialize()."""
    expected_tables = [
        "account_snapshots", "pre_trade_log", "execution_log",
        "trade_history", "position_changes", "exchange_history",
    ]
    async with test_db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ) as cur:
        rows = await cur.fetchall()
    table_names = {r[0] for r in rows}
    for t in expected_tables:
        assert t in table_names, f"Table '{t}' not created by initialize()"


@pytest.mark.asyncio
async def test_wal_mode_enabled(test_db):
    """WAL journal mode is active."""
    async with test_db._conn.execute("PRAGMA journal_mode") as cur:
        row = await cur.fetchone()
    assert row[0].lower() == "wal"


# ── Snapshots ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_insert_and_query_snapshot(test_db):
    """Can insert an account snapshot and read it back."""
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()
    await test_db._conn.execute(
        "INSERT INTO account_snapshots (snapshot_ts, total_equity, balance_usdt) VALUES (?, ?, ?)",
        (ts, 1000.0, 950.0),
    )
    await test_db._conn.commit()

    async with test_db._conn.execute(
        "SELECT total_equity, balance_usdt FROM account_snapshots WHERE snapshot_ts=?", (ts,)
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert float(row[0]) == 1000.0
    assert float(row[1]) == 950.0


# ── Pre-trade log ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_insert_pre_trade_log(test_db):
    """Can insert into pre_trade_log."""
    await test_db._conn.execute(
        "INSERT INTO pre_trade_log (timestamp, ticker) VALUES (?, ?)",
        ("2026-01-01T00:00:00", "BTCUSDT"),
    )
    await test_db._conn.commit()

    async with test_db._conn.execute("SELECT COUNT(*) FROM pre_trade_log") as cur:
        row = await cur.fetchone()
    assert row[0] == 1


# ── Exchange history upsert ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_exchange_history_upsert_idempotent(test_db):
    """Upserting the same trade_key twice does not create duplicates."""
    row = {
        "trade_key": "test_key_1",
        "time": 1700000000000,
        "symbol": "BTCUSDT",
        "incomeType": "REALIZED_PNL",
        "income": 50.0,
        "direction": "LONG",
        "entry_price": 40000.0,
        "exit_price": 40500.0,
        "qty": 0.01,
        "notional": 405.0,
        "open_time": 1699999000000,
        "fee": 0.2,
        "asset": "USDT",
    }
    # Insert twice
    await test_db.upsert_exchange_history([row])
    await test_db.upsert_exchange_history([row])

    async with test_db._conn.execute(
        "SELECT COUNT(*) FROM exchange_history WHERE trade_key=?", ("test_key_1",)
    ) as cur:
        count = (await cur.fetchone())[0]
    assert count == 1


# ── Settings ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_settings_roundtrip(test_db):
    """Can set and get a setting."""
    await test_db.set_setting("test_key", "test_value")
    val = await test_db.get_setting("test_key")
    assert val == "test_value"


@pytest.mark.asyncio
async def test_settings_missing_returns_none(test_db):
    """Getting a non-existent setting returns None."""
    val = await test_db.get_setting("nonexistent_key_xyz")
    assert val is None
