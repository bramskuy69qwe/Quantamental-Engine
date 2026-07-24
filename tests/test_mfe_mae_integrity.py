"""
v3.0 MFE/MAE-integrity — get_mfe_mae_series sources from closed_positions.

Operator-reported: the Analytics MFE/MAE tab showed SPCX MAE -284/-270 the
operator never actually lost. Root cause: exchange_history stores excursions
PER income-row (per partial close), and the reconciler computes ONE high/low
over the whole position's window, assigning it to EVERY partial scaled by qty
— so a scale-in/out position over-attributes the full-position excursion to
each row. closed_positions (rebuilt from the real Binance userTrades) carries
ONE correct excursion per position.

Fix: get_mfe_mae_series reads closed_positions. This pins that the corrupt
exchange_history value can never reach the scatter, using the exact live
shapes (SPCX -284 in exchange_history vs -111 in closed_positions).
"""
from __future__ import annotations

import os
import tempfile

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def db():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    d = DatabaseManager(path=tmp.name)
    await d.initialize()
    yield d
    await d.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            if os.path.exists(tmp.name + ext):
                os.unlink(tmp.name + ext)
    except OSError:
        pass


async def _seed_exchange_history_overattributed(d):
    """An over-attributed SPCX row: MAE -284 over the whole-position window."""
    await d.upsert_exchange_history([{
        "trade_key": "eh-spcx", "time": 1749758000000, "symbol": "SPCXUSDT",
        "incomeType": "REALIZED_PNL", "income": -6.96, "direction": "SHORT",
        "entry_price": 161.0595, "exit_price": 161.0, "qty": 18.28,
        "notional": 2951.12, "open_time": 1749744971000, "fee": 1.0, "asset": "USDT",
    }])
    await d.update_exchange_mfe_mae("eh-spcx", mfe=92.12, mae=-284.26)


async def _seed_closed_position_correct(d):
    """The SAME position, rebuilt from userTrades: correct MAE -111."""
    await d._conn.execute(
        """INSERT INTO closed_positions
           (account_id, exchange_position_id, symbol, direction, quantity,
            entry_price, exit_price, entry_time_ms, exit_time_ms,
            realized_pnl, net_pnl, mfe, mae, hold_time_ms, source)
           VALUES (1, 'cp-spcx', 'SPCXUSDT', 'LONG', 67.67, 165.47, 166.22,
                   1749744971000, 1749758000000, 50.35, 49.0, 101.9, -111.2,
                   13029000, 'rebuilt_from_fills')""")
    await d._conn.commit()


class TestExcursionSourceIsClosedPositions:
    @pytest.mark.asyncio
    async def test_returns_closed_position_value_not_overattributed(self, db):
        await _seed_exchange_history_overattributed(db)
        await _seed_closed_position_correct(db)

        trades = await db.get_mfe_mae_series(0, 2_000_000_000_000)
        assert len(trades) == 1
        t = trades[0]
        # the CORRECT closed_positions excursion, NOT the -284 over-attribution
        assert t["mae"] == pytest.approx(-111.2)
        assert t["mae"] != pytest.approx(-284.26)
        assert t["symbol"] == "SPCXUSDT"
        assert str(t["trade_key"]).startswith("cp-")

    @pytest.mark.asyncio
    async def test_exchange_history_alone_yields_nothing(self, db):
        """With only the corrupt exchange_history row (no closed_position), the
        scatter shows NOTHING rather than the -284 garbage."""
        await _seed_exchange_history_overattributed(db)
        trades = await db.get_mfe_mae_series(0, 2_000_000_000_000)
        assert trades == []

    @pytest.mark.asyncio
    async def test_field_shape_preserved_for_consumers(self, db):
        """The scatter route + sharpe_mfe/sortino_mae read these keys — they
        must survive the source swap."""
        await _seed_closed_position_correct(db)
        t = (await db.get_mfe_mae_series(0, 2_000_000_000_000))[0]
        for k in ("trade_key", "symbol", "direction", "income", "notional",
                  "mfe", "mae", "entry_price", "qty", "hold_ms"):
            assert k in t, f"missing {k}"
        # notional = qty × entry, income = net_pnl
        assert t["notional"] == pytest.approx(67.67 * 165.47)
        assert t["income"] == pytest.approx(49.0)

    @pytest.mark.asyncio
    async def test_flat_excursion_rows_excluded(self, db):
        """mfe==0 AND mae==0 rows are not excursions — excluded (parity with
        the old query's (mfe!=0 OR mae!=0) filter)."""
        await db._conn.execute(
            """INSERT INTO closed_positions
               (account_id, exchange_position_id, symbol, direction, quantity,
                entry_price, exit_price, entry_time_ms, exit_time_ms,
                realized_pnl, net_pnl, mfe, mae, hold_time_ms, source)
               VALUES (1, 'cp-flat', 'ETHUSDT', 'LONG', 1.0, 3000.0, 3000.0,
                       1, 1749758000000, 0.0, 0.0, 0.0, 0.0, 1000, 'rebuilt_from_fills')""")
        await db._conn.commit()
        assert await db.get_mfe_mae_series(0, 2_000_000_000_000) == []

    @pytest.mark.asyncio
    async def test_window_filter_on_exit_time(self, db):
        await _seed_closed_position_correct(db)   # exit_time_ms = 1749758000000
        assert len(await db.get_mfe_mae_series(0, 1749757999999)) == 0   # before
        assert len(await db.get_mfe_mae_series(1749758000001, 2_000_000_000_000)) == 0  # after
        assert len(await db.get_mfe_mae_series(1749758000000, 1749758000000)) == 1  # inclusive
