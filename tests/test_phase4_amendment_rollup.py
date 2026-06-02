"""
Phase 4 Task 2 (P4.T2) tests — cumulative_amendment_count rollup at close.

Verifies:
  - ``Database.count_amendments_for_calcs`` counts order_amendments rows by
    calc_id (the basis: a position's contributing calcs — entry legs carry the
    matcher calc_id, protective TP/SL legs carry the T2.9-inherited calc_id, and
    both denormalize calc_id onto the amendment row).
  - ``insert_closed_position`` persists ``cumulative_amendment_count`` AND
    preserves it across an INSERT OR REPLACE that omits it (a non-computing
    backfill/rebuild must not wipe a live-built count — same _CLOSED_POS_DELTA_COLS
    preserve pattern as the T2.5 deltas).
  - ``_build_close_row_for_fill`` writes the count for the position's
    contributing calcs (Rule-8 intent test through the real close path).

Run: pytest tests/test_phase4_amendment_rollup.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

ACCOUNT_ID = 1


@pytest_asyncio.fixture
async def db():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    database = DatabaseManager(path=tmp.name)
    await database.initialize()
    yield database
    await database.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


@pytest_asyncio.fixture
async def om(db):
    from core.order_manager import OrderManager
    return OrderManager(db)


async def _amend(db, calc_id, field, old, new, ts, order_id=1):
    await db.insert_order_amendment({
        "order_id": order_id, "calc_id": calc_id, "field": field,
        "old_value": old, "new_value": new, "ts_ms": ts,
        "operator_id": None,
        "deviation_pct": (new - old) / old * 100.0 if old else None,
        "lifecycle_id": None,
    })


async def _closed_row(db, tpid, exit_time, account_id=ACCOUNT_ID):
    async with db._conn.execute(
        "SELECT * FROM closed_positions WHERE account_id=? "
        "AND terminal_position_id=? AND exit_time_ms=?",
        (account_id, tpid, exit_time),
    ) as cur:
        r = await cur.fetchone()
    return dict(r) if r else None


def _closed_row_input(**over):
    row = {
        "account_id": ACCOUNT_ID, "terminal_position_id": "P", "exit_time_ms": 100,
        "symbol": "BTCUSDT", "direction": "LONG", "quantity": 1.0,
        "entry_price": 50000.0, "exit_price": 51000.0,
    }
    row.update(over)
    return row


# ── 1. count_amendments_for_calcs ───────────────────────────────────────


class TestCountAmendmentsForCalcs:
    @pytest.mark.asyncio
    async def test_counts_rows_for_a_calc(self, db):
        await _amend(db, "C1", "entry_price", 50000, 50100, 100)
        await _amend(db, "C1", "sl_price", 48000, 47000, 200)
        await _amend(db, "C2", "tp_price", 55000, 56000, 300)
        assert await db.count_amendments_for_calcs(["C1"]) == 2

    @pytest.mark.asyncio
    async def test_counts_across_multiple_calcs(self, db):
        await _amend(db, "C1", "entry_price", 50000, 50100, 100)
        await _amend(db, "C2", "tp_price", 55000, 56000, 300)
        assert await db.count_amendments_for_calcs(["C1", "C2"]) == 2

    @pytest.mark.asyncio
    async def test_empty_set_is_zero(self, db):
        await _amend(db, "C1", "entry_price", 50000, 50100, 100)
        assert await db.count_amendments_for_calcs([]) == 0
        assert await db.count_amendments_for_calcs(None) == 0

    @pytest.mark.asyncio
    async def test_falsy_ids_dropped(self, db):
        await _amend(db, "C1", "entry_price", 50000, 50100, 100)
        # a set with only None/"" → 0 (no spurious all-rows match)
        assert await db.count_amendments_for_calcs([None, ""]) == 0

    @pytest.mark.asyncio
    async def test_unknown_calc_is_zero(self, db):
        await _amend(db, "C1", "entry_price", 50000, 50100, 100)
        assert await db.count_amendments_for_calcs(["NOPE"]) == 0


# ── 2. insert_closed_position persist + REPLACE-preserve ────────────────


class TestClosedPositionPersistAndPreserve:
    @pytest.mark.asyncio
    async def test_count_persisted(self, db):
        await db.insert_closed_position(
            _closed_row_input(calc_id="C1", cumulative_amendment_count=3))
        row = await _closed_row(db, "P", 100)
        assert row["cumulative_amendment_count"] == 3

    @pytest.mark.asyncio
    async def test_replace_omitting_count_preserves_it(self, db):
        # Live builder writes 3; a later backfill REPLACE that omits the column
        # must NOT wipe it (the _CLOSED_POS_DELTA_COLS preserve pattern).
        await db.insert_closed_position(
            _closed_row_input(calc_id="C1", cumulative_amendment_count=3))
        await db.insert_closed_position(_closed_row_input(calc_id="C1"))  # no count
        row = await _closed_row(db, "P", 100)
        assert row["cumulative_amendment_count"] == 3

    @pytest.mark.asyncio
    async def test_recompute_value_wins(self, db):
        await db.insert_closed_position(
            _closed_row_input(calc_id="C1", cumulative_amendment_count=3))
        await db.insert_closed_position(
            _closed_row_input(calc_id="C1", cumulative_amendment_count=5))
        row = await _closed_row(db, "P", 100)
        assert row["cumulative_amendment_count"] == 5


# ── 3. close-row integration (Rule-8) ──────────────────────────────────


async def _seed_calc(db, calc_id, status="matched", ticker="BTCUSDT"):
    await db._conn.execute(
        "INSERT INTO pre_trade_log (account_id, timestamp, ticker, calc_id, status) "
        "VALUES (?, '2026-05-29T00:00:00Z', ?, ?, ?)",
        (ACCOUNT_ID, ticker, calc_id, status),
    )
    await db._conn.commit()


async def _seed_order(db, eoid, order_type, side, status="filled"):
    await db._conn.execute(
        "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
        " order_type, status) VALUES (?, ?, 'BTCUSDT', ?, ?, ?)",
        (ACCOUNT_ID, eoid, side, order_type, status),
    )
    await db._conn.commit()


async def _seed_fill(db, fid, eoid, tpid, qty, is_close, calc_id, ts, price):
    await db._conn.execute(
        "INSERT INTO fills (account_id, exchange_fill_id, exchange_order_id, "
        " terminal_position_id, symbol, side, direction, price, quantity, fee, "
        " is_close, realized_pnl, timestamp_ms, calc_id) "
        "VALUES (?, ?, ?, ?, 'BTCUSDT', ?, 'LONG', ?, ?, 0, ?, 0, ?, ?)",
        (ACCOUNT_ID, fid, eoid, tpid, "SELL" if is_close else "BUY",
         price, qty, int(is_close), ts, calc_id),
    )
    await db._conn.commit()


def _close_fill(eoid, tpid, ts):
    return {
        "terminal_position_id": tpid, "symbol": "BTCUSDT", "direction": "LONG",
        "exchange_order_id": eoid, "timestamp_ms": ts,
        "exchange_position_id": "", "source": "",
    }


class TestCloseRowAmendmentRollup:
    @pytest.mark.asyncio
    async def test_close_row_carries_contributing_calc_amendment_count(self, db, om):
        await _seed_calc(db, "C1")
        await _seed_order(db, "EO", "limit", "BUY")
        await _seed_fill(db, "FO", "EO", "POS-1", 1.0, False, "C1", 1000, 50000.0)
        # two amendments on C1's orders (entry move + SL move)
        await _amend(db, "C1", "entry_price", 50000, 50100, 1100)
        await _amend(db, "C1", "sl_price", 48000, 47000, 1200)
        # full close → final close row
        await _seed_order(db, "XO", "market", "SELL")
        await _seed_fill(db, "FX", "XO", "POS-1", 1.0, True, "C1", 2000, 51000.0)
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill("XO", "POS-1", 2000))

        row = await _closed_row(db, "POS-1", 2000)
        assert row is not None
        assert row["cumulative_amendment_count"] == 2

    @pytest.mark.asyncio
    async def test_close_row_zero_when_no_amendments(self, db, om):
        await _seed_calc(db, "C1")
        await _seed_order(db, "EO", "limit", "BUY")
        await _seed_fill(db, "FO", "EO", "POS-1", 1.0, False, "C1", 1000, 50000.0)
        await _seed_order(db, "XO", "market", "SELL")
        await _seed_fill(db, "FX", "XO", "POS-1", 1.0, True, "C1", 2000, 51000.0)
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill("XO", "POS-1", 2000))

        row = await _closed_row(db, "POS-1", 2000)
        assert row["cumulative_amendment_count"] == 0
