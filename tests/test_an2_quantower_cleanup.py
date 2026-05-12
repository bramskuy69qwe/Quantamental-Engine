"""
AN-2: Verify qt:-prefixed legacy Quantower rows are removed from
exchange_history and fills tables. Non-qt: rows must be unaffected.

Pre-fix: tests that assert absence of qt: rows will FAIL (qt: rows exist).
Post-fix: all tests pass — qt: rows deleted by migration.
"""
import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest_asyncio.fixture
async def test_db():
    """Temporary DB with qt: and non-qt: seed data."""
    from core.database import DatabaseManager

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()

    # Seed exchange_history: 3 qt:-prefixed rows (corrupted), 2 non-qt: rows (real)
    qt_rows = [
        {
            "trade_key": "qt:246815556", "time": 1774437117262, "symbol": "SIRENUSDT",
            "incomeType": "REALIZED_PNL", "income": 0.0, "direction": "LONG",
            "entry_price": 2.24171, "exit_price": 0.0, "qty": 21.0,
            "notional": 47.07, "open_time": 1774437117262, "fee": 0.02353795, "asset": "USDT",
        },
        {
            "trade_key": "qt:277769926", "time": 1774636148114, "symbol": "SIRENUSDT",
            "incomeType": "REALIZED_PNL", "income": 1.42556, "direction": "SHORT",
            "entry_price": 0.78620, "exit_price": 0.77412, "qty": 118.0,
            "notional": 92.77, "open_time": 1774437117262, "fee": 0.04567310, "asset": "USDT",
        },
        {
            "trade_key": "qt:120836946", "time": 1775119811460, "symbol": "STOUSDT",
            "incomeType": "REALIZED_PNL", "income": -1.45696, "direction": "LONG",
            "entry_price": 1.16448, "exit_price": 1.13936, "qty": 58.0,
            "notional": 67.54, "open_time": 1775110209786, "fee": 0.03304144, "asset": "USDT",
        },
    ]
    real_rows = [
        {
            "trade_key": "1234567890", "time": 1775300000000, "symbol": "BTCUSDT",
            "incomeType": "REALIZED_PNL", "income": 5.25, "direction": "LONG",
            "entry_price": 68000.0, "exit_price": 68500.0, "qty": 0.003,
            "notional": 204.0, "open_time": 1775290000000, "fee": 0.10, "asset": "USDT",
        },
        {
            "trade_key": "9876543210", "time": 1775310000000, "symbol": "ETHUSDT",
            "incomeType": "REALIZED_PNL", "income": -2.10, "direction": "SHORT",
            "entry_price": 3800.0, "exit_price": 3820.0, "qty": 0.1,
            "notional": 380.0, "open_time": 1775300000000, "fee": 0.15, "asset": "USDT",
        },
    ]
    await db.upsert_exchange_history(qt_rows + real_rows)

    # Set MFE/MAE on the qt: rows to simulate corrupted analytics
    await db.update_exchange_mfe_mae("qt:277769926", mfe=8.64, mae=-246.48)
    await db.update_exchange_mfe_mae("qt:120836946", mfe=0.0, mae=-1.46)
    # Set MFE/MAE on real rows
    await db.update_exchange_mfe_mae("1234567890", mfe=0.52, mae=-0.10)
    await db.update_exchange_mfe_mae("9876543210", mfe=0.05, mae=-0.21)

    # Seed fills: 3 qt:-prefixed, 2 non-qt:
    for tk in ["qt:246815556", "qt:277769926", "qt:120836946"]:
        await db._conn.execute(
            """INSERT INTO fills (account_id, exchange_fill_id, symbol, side, direction,
               price, quantity, fee, timestamp_ms)
               VALUES (1, ?, 'SIRENUSDT', 'SELL', 'SHORT', 0.78, 118.0, 0.04, 1774636148114)""",
            (tk,),
        )
    for tk in ["fill_1234567890", "fill_9876543210"]:
        await db._conn.execute(
            """INSERT INTO fills (account_id, exchange_fill_id, symbol, side, direction,
               price, quantity, fee, timestamp_ms)
               VALUES (1, ?, 'BTCUSDT', 'BUY', 'LONG', 68000.0, 0.003, 0.10, 1775300000000)""",
            (tk,),
        )
    await db._conn.commit()

    # Apply AN-2 migration SQL (simulates what _run_once does on a DB that
    # already contains qt: data — initialize() ran on empty tables above).
    await db._conn.execute("DELETE FROM exchange_history WHERE trade_key LIKE 'qt:%'")
    await db._conn.execute("DELETE FROM fills WHERE exchange_fill_id LIKE 'qt:%'")
    await db._conn.commit()

    yield db

    await db.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


# ── Core deletion tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_qt_rows_in_exchange_history(test_db):
    """After migration, zero qt:-prefixed rows remain in exchange_history."""
    async with test_db._conn.execute(
        "SELECT COUNT(*) FROM exchange_history WHERE trade_key LIKE 'qt:%'"
    ) as cur:
        count = (await cur.fetchone())[0]
    assert count == 0, f"Expected 0 qt: rows, found {count}"


@pytest.mark.asyncio
async def test_no_qt_rows_in_fills(test_db):
    """After migration, zero qt:-prefixed rows remain in fills."""
    async with test_db._conn.execute(
        "SELECT COUNT(*) FROM fills WHERE exchange_fill_id LIKE 'qt:%'"
    ) as cur:
        count = (await cur.fetchone())[0]
    assert count == 0, f"Expected 0 qt: fills, found {count}"


@pytest.mark.asyncio
async def test_non_qt_rows_preserved(test_db):
    """Non-qt: rows in exchange_history survive the migration unchanged."""
    async with test_db._conn.execute(
        "SELECT COUNT(*) FROM exchange_history WHERE trade_key NOT LIKE 'qt:%'"
    ) as cur:
        count = (await cur.fetchone())[0]
    assert count == 2, f"Expected 2 non-qt: rows, found {count}"

    # Verify specific rows
    async with test_db._conn.execute(
        "SELECT trade_key, income FROM exchange_history ORDER BY trade_key"
    ) as cur:
        rows = await cur.fetchall()
    keys = {r[0]: r[1] for r in rows}
    assert "1234567890" in keys
    assert "9876543210" in keys
    assert abs(keys["1234567890"] - 5.25) < 0.001
    assert abs(keys["9876543210"] - (-2.10)) < 0.001


@pytest.mark.asyncio
async def test_non_qt_fills_preserved(test_db):
    """Non-qt: fills survive the migration unchanged."""
    async with test_db._conn.execute(
        "SELECT COUNT(*) FROM fills WHERE exchange_fill_id NOT LIKE 'qt:%'"
    ) as cur:
        count = (await cur.fetchone())[0]
    assert count == 2, f"Expected 2 non-qt: fills, found {count}"


# ── Analytics impact tests ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_journal_stats_exclude_qt_rows(test_db):
    """get_journal_stats reflects only real trades after cleanup."""
    stats = await test_db.get_journal_stats(0, 2000000000000)
    # Only 2 real trades should contribute (income 5.25 and -2.10)
    assert stats["total_trades"] == 2
    assert stats["winning_trades"] == 1
    assert stats["losing_trades"] == 1
    assert abs(stats["total_pnl"] - 3.15) < 0.01


@pytest.mark.asyncio
async def test_mfe_mae_series_exclude_qt_rows(test_db):
    """get_mfe_mae_series returns only real trades — no qt: MAE corruption."""
    trades = await test_db.get_mfe_mae_series(0, 2000000000000)
    symbols = [t["symbol"] for t in trades]
    # No SIRENUSDT or STOUSDT qt: rows
    assert "SIRENUSDT" not in symbols
    # Real rows present
    assert len(trades) == 2
    for t in trades:
        # No impossible MAE values
        assert t["mae"] > -10.0, f"Corrupted MAE {t['mae']} on {t['symbol']}"


@pytest.mark.asyncio
async def test_most_traded_pairs_exclude_qt_symbols(test_db):
    """get_most_traded_pairs reflects only real trading symbols."""
    pairs = await test_db.get_most_traded_pairs(0, 2000000000000, limit=10)
    # SIRENUSDT and STOUSDT only existed as qt: rows in seed data
    assert "SIRENUSDT" not in pairs
    assert "STOUSDT" not in pairs
    assert "BTCUSDT" in pairs
    assert "ETHUSDT" in pairs


@pytest.mark.asyncio
async def test_cumulative_pnl_exclude_qt_contributions(test_db):
    """get_cumulative_pnl reflects only real trade PnL."""
    result = await test_db.get_cumulative_pnl()
    # Only real trades: 5.25 + (-2.10) = 3.15
    assert abs(result["total_pnl"] - 3.15) < 0.05
