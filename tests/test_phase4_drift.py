"""
Phase 4 Task 5 (P4.T5) tests — tp_drift_pct / sl_drift_pct at close.

Verifies ``OrderManager._compute_close_deltas`` populates the spec §3.2 /
plan §4.6 drift columns:

  - ``tp_drift_pct`` / ``sl_drift_pct`` = (final amended TP/SL − the primary
    calc's planned value) / planned * 100. "Final" is the LATEST
    ``order_amendments.new_value`` for that field on the primary calc's legs
    (the orders row goes stale post-amendment, so the ledger is the
    authoritative chain — P4.T1). Last-wins across multiple amendments.
  - Omitted (→ NULL) when the leg was never amended (drift is populated only
    for an AMENDED stop — the plan §4 acceptance criterion) OR the planned
    denominator is missing/zero.
  - Scoped to the PRIMARY (most-contributing) calc — same §3.2 basis as the
    planned_tp/sl the drift is measured against. An amendment under a
    non-primary calc_id does not contribute.
  - Persisted on ``closed_positions`` via ``_build_close_row_for_fill`` and
    preserved across an INSERT OR REPLACE that omits them (the
    ``_CLOSED_POS_DELTA_COLS`` preserve pattern — a non-computing
    backfill/rebuild must not wipe a live-built drift).

Run: pytest tests/test_phase4_drift.py -v
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


# ── seeding helpers ─────────────────────────────────────────────────────


async def _amend(db, calc_id, field, old, new, ts, order_id=1):
    await db.insert_order_amendment({
        "order_id": order_id, "calc_id": calc_id, "field": field,
        "old_value": old, "new_value": new, "ts_ms": ts,
        "operator_id": None,
        "deviation_pct": (new - old) / old * 100.0 if old else None,
        "lifecycle_id": None,
    })


async def _seed_junction(db, pos_id, calc_id, *, order_id=100, qty=10.0,
                         ts=1000, lifecycle_id="lc-1", planned_size=None,
                         planned_tp=None, planned_sl=None):
    await db.upsert_position_calc_link({
        "position_id": pos_id, "calc_id": calc_id, "order_id": order_id,
        "account_id": ACCOUNT_ID, "contributed_qty": qty,
        "first_fill_ts": ts, "last_fill_ts": ts, "lifecycle_id": lifecycle_id,
        "planned_size": planned_size, "planned_tp": planned_tp,
        "planned_sl": planned_sl,
    })


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


# helper: run _compute_close_deltas with the common close args
async def _deltas(om, pos_id="POS-1", exit_price=54000.0):
    return await om._compute_close_deltas(
        ACCOUNT_ID, pos_id,
        entry_price=50500.0, actual_size=10.0, exit_price=exit_price,
        entry_time=1000, exit_time=2000,
    )


# ── 1. drift computation (unit, via _compute_close_deltas) ──────────────


class TestComputeTpSlDrift:
    @pytest.mark.asyncio
    async def test_tp_amended_computes_drift(self, db, om):
        await _seed_junction(db, "POS-1", "calc-a",
                             planned_tp=55000.0, planned_sl=48000.0)
        await _amend(db, "calc-a", "tp_price", 55000.0, 56100.0, 1500)
        out = await _deltas(om)
        # (56100 - 55000) / 55000 * 100 = +2.0
        assert out["tp_drift_pct"] == pytest.approx(2.0)
        assert "sl_drift_pct" not in out          # SL never amended

    @pytest.mark.asyncio
    async def test_sl_amended_computes_signed_drift(self, db, om):
        await _seed_junction(db, "POS-1", "calc-a",
                             planned_tp=55000.0, planned_sl=48000.0)
        await _amend(db, "calc-a", "sl_price", 48000.0, 47040.0, 1500)
        out = await _deltas(om)
        # (47040 - 48000) / 48000 * 100 = -2.0 (signed — tightened stop)
        assert out["sl_drift_pct"] == pytest.approx(-2.0)
        assert "tp_drift_pct" not in out

    @pytest.mark.asyncio
    async def test_no_amendment_omits_both(self, db, om):
        await _seed_junction(db, "POS-1", "calc-a",
                             planned_tp=55000.0, planned_sl=48000.0)
        out = await _deltas(om)
        assert "tp_drift_pct" not in out
        assert "sl_drift_pct" not in out

    @pytest.mark.asyncio
    async def test_final_amended_value_wins(self, db, om):
        # Chained amendments — drift measures the LAST (final) trigger.
        await _seed_junction(db, "POS-1", "calc-a", planned_tp=55000.0)
        await _amend(db, "calc-a", "tp_price", 55000.0, 56000.0, 1500)
        await _amend(db, "calc-a", "tp_price", 56000.0, 57200.0, 1600)
        out = await _deltas(om)
        # final = 57200 → (57200 - 55000) / 55000 * 100 = +4.0
        assert out["tp_drift_pct"] == pytest.approx(4.0)

    @pytest.mark.asyncio
    async def test_planned_missing_omits_drift(self, db, om):
        # Amendment present but no planned denominator on the junction → NULL.
        await _seed_junction(db, "POS-1", "calc-a",
                             planned_tp=None, planned_sl=48000.0)
        await _amend(db, "calc-a", "tp_price", 55000.0, 56100.0, 1500)
        await _amend(db, "calc-a", "sl_price", 48000.0, 47040.0, 1500)
        out = await _deltas(om)
        assert "tp_drift_pct" not in out          # planned_tp NULL
        assert out["sl_drift_pct"] == pytest.approx(-2.0)

    @pytest.mark.asyncio
    async def test_entry_size_amendments_do_not_drift(self, db, om):
        # Only tp_price/sl_price fields feed drift — entry_price/size don't.
        await _seed_junction(db, "POS-1", "calc-a",
                             planned_tp=55000.0, planned_sl=48000.0)
        await _amend(db, "calc-a", "entry_price", 50000.0, 50100.0, 1500)
        await _amend(db, "calc-a", "size", 10.0, 12.0, 1500)
        out = await _deltas(om)
        assert "tp_drift_pct" not in out
        assert "sl_drift_pct" not in out

    @pytest.mark.asyncio
    async def test_drift_scoped_to_primary_calc(self, db, om):
        # The primary calc is calc-a (it contributed); an amendment under a
        # DIFFERENT calc must not bleed into this position's drift.
        await _seed_junction(db, "POS-1", "calc-a", qty=10.0,
                             planned_tp=55000.0)
        await _amend(db, "calc-OTHER", "tp_price", 55000.0, 60000.0, 1500)
        out = await _deltas(om)
        assert "tp_drift_pct" not in out

    @pytest.mark.asyncio
    async def test_no_junction_returns_empty(self, db, om):
        # UNPLANNED / binance empty-tpid: no junction → no primary → {} (the
        # whole deltas dict is empty, drift included).
        await _amend(db, "calc-a", "tp_price", 55000.0, 56100.0, 1500)
        out = await _deltas(om)
        assert out == {}

    @pytest.mark.asyncio
    async def test_amendment_after_exit_time_excluded(self, db, om):
        # P4-CLOSE-001: an amendment timestamped AFTER this close's exit_time
        # (a later multi-TP rung, or out-of-order WS delivery) must NOT affect
        # this row's drift — the drift is as-of exit_time.
        await _seed_junction(db, "POS-1", "calc-a", planned_tp=55000.0)
        await _amend(db, "calc-a", "tp_price", 55000.0, 56100.0, 1500)  # ≤ exit
        await _amend(db, "calc-a", "tp_price", 56100.0, 60000.0, 2500)  # > exit (2000)
        out = await _deltas(om)  # exit_time=2000
        # final_tp = 56100 (the ts=2500 amendment is excluded), not 60000.
        assert out["tp_drift_pct"] == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_only_post_exit_amendment_omits_drift(self, db, om):
        # If the ONLY amendment post-dates exit_time, this row saw no amendment.
        await _seed_junction(db, "POS-1", "calc-a", planned_tp=55000.0)
        await _amend(db, "calc-a", "tp_price", 55000.0, 56000.0, 2500)  # > exit
        out = await _deltas(om)
        assert "tp_drift_pct" not in out


# ── 2. preserve across INSERT OR REPLACE ────────────────────────────────


class TestDriftPreserve:
    def test_drift_cols_in_preserve_set(self):
        from core.db_orders import _CLOSED_POS_DELTA_COLS
        assert "tp_drift_pct" in _CLOSED_POS_DELTA_COLS
        assert "sl_drift_pct" in _CLOSED_POS_DELTA_COLS

    @pytest.mark.asyncio
    async def test_replace_omitting_drift_preserves_it(self, db):
        # Live builder writes drift; a later backfill REPLACE that omits the
        # columns must NOT wipe them.
        await db.insert_closed_position(
            _closed_row_input(calc_id="C1", tp_drift_pct=2.0, sl_drift_pct=-2.0))
        await db.insert_closed_position(_closed_row_input(calc_id="C1"))  # no drift
        row = await _closed_row(db, "P", 100)
        assert row["tp_drift_pct"] == pytest.approx(2.0)
        assert row["sl_drift_pct"] == pytest.approx(-2.0)

    @pytest.mark.asyncio
    async def test_recompute_value_wins(self, db):
        await db.insert_closed_position(
            _closed_row_input(calc_id="C1", tp_drift_pct=2.0))
        await db.insert_closed_position(
            _closed_row_input(calc_id="C1", tp_drift_pct=5.0))
        row = await _closed_row(db, "P", 100)
        assert row["tp_drift_pct"] == pytest.approx(5.0)


# ── 3. real close path (Rule-8 intent) ──────────────────────────────────


class TestDriftRealClosePath:
    @pytest.mark.asyncio
    async def test_sl_drift_persisted_via_close_path(self, db, om):
        # Junction (planned snapshot) + opening fill + an SL amendment, then a
        # full close → closed_positions.sl_drift_pct computed + persisted.
        await _seed_junction(db, "POS-1", "C1", order_id=1, qty=1.0,
                             planned_tp=55000.0, planned_sl=48000.0)
        await _seed_order(db, "EO", "limit", "BUY")
        await _seed_fill(db, "FO", "EO", "POS-1", 1.0, False, "C1", 1000, 50000.0)
        await _amend(db, "C1", "sl_price", 48000.0, 47040.0, 1200)
        await _seed_order(db, "XO", "market", "SELL")
        await _seed_fill(db, "FX", "XO", "POS-1", 1.0, True, "C1", 2000, 51000.0)
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill("XO", "POS-1", 2000))

        row = await _closed_row(db, "POS-1", 2000)
        assert row is not None
        assert row["sl_drift_pct"] == pytest.approx(-2.0)
        assert row["tp_drift_pct"] is None            # TP never amended

    @pytest.mark.asyncio
    async def test_no_amendment_leaves_drift_null(self, db, om):
        await _seed_junction(db, "POS-1", "C1", order_id=1, qty=1.0,
                             planned_tp=55000.0, planned_sl=48000.0)
        await _seed_order(db, "EO", "limit", "BUY")
        await _seed_fill(db, "FO", "EO", "POS-1", 1.0, False, "C1", 1000, 50000.0)
        await _seed_order(db, "XO", "market", "SELL")
        await _seed_fill(db, "FX", "XO", "POS-1", 1.0, True, "C1", 2000, 51000.0)
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill("XO", "POS-1", 2000))

        row = await _closed_row(db, "POS-1", 2000)
        assert row["tp_drift_pct"] is None
        assert row["sl_drift_pct"] is None
