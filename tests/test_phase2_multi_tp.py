"""Phase 2.11 — multi-TP partial-close lifecycle (spec §8 / §3.4).

Operator-confirmed model (Option A): per-partial closed_positions rows are
PRESERVED (one row per closing order). T2.11 adds, on top of that model:

  1. calc completion is DEFERRED to the FINAL close (size→0) — pre-T2.11 it
     fired on the first partial. Final-close is data-derived from fills
     (Σ closing qty ≥ Σ opening qty), not the racy ACCOUNT_UPDATE snapshot.
  2. the FINAL row's exit_reason is ladder-aware — TP_LADDER_COMPLETE
     (≥2 TP closing orders, no SL/manual) or MIXED (TP + SL/manual).
     Non-final partial rows keep their per-order reason.

Tests drive ``_build_close_row_for_fill`` / ``_classify_final_exit_reason``
directly on ``self._db`` (no config.DB_PATH patch needed — the close path
reads/writes only through the DatabaseManager).

Run: pytest tests/test_phase2_multi_tp.py -v
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


# ── seed / read helpers ────────────────────────────────────────────────


async def _seed_calc(db, calc_id, *, status="matched", ticker="BTCUSDT",
                     account_id=ACCOUNT_ID):
    await db._conn.execute(
        "INSERT INTO pre_trade_log (account_id, timestamp, ticker, calc_id, "
        " status) VALUES (?, '2026-05-29T00:00:00Z', ?, ?, ?)",
        (account_id, ticker, calc_id, status),
    )
    await db._conn.commit()


async def _seed_order(db, eoid, order_type, *, side="SELL", symbol="BTCUSDT",
                      status="filled", account_id=ACCOUNT_ID):
    await db._conn.execute(
        "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
        " order_type, status) VALUES (?, ?, ?, ?, ?, ?)",
        (account_id, eoid, symbol, side, order_type, status),
    )
    await db._conn.commit()


async def _seed_fill(db, fid, eoid, tpid, qty, *, is_close, calc_id=None,
                     ts=1000, price=50000.0, pnl=0.0, symbol="BTCUSDT",
                     direction="LONG", side=None, account_id=ACCOUNT_ID):
    # side is NOT NULL on fills; closing a LONG sells, opening a LONG buys.
    if side is None:
        side = "SELL" if is_close else "BUY"
    await db._conn.execute(
        "INSERT INTO fills (account_id, exchange_fill_id, exchange_order_id, "
        " terminal_position_id, symbol, side, direction, price, quantity, fee, "
        " is_close, realized_pnl, timestamp_ms, calc_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
        (account_id, fid, eoid, tpid, symbol, side, direction, price, qty,
         int(is_close), pnl, ts, calc_id),
    )
    await db._conn.commit()


def _close_fill(eoid, tpid, ts, symbol="BTCUSDT", direction="LONG"):
    return {
        "terminal_position_id": tpid,
        "symbol": symbol,
        "direction": direction,
        "exchange_order_id": eoid,
        "timestamp_ms": ts,
        "exchange_position_id": "",
        "source": "",
    }


async def _calc_status(db, calc_id, account_id=ACCOUNT_ID):
    async with db._conn.execute(
        "SELECT status FROM pre_trade_log WHERE account_id=? AND calc_id=?",
        (account_id, calc_id),
    ) as cur:
        r = await cur.fetchone()
    return r[0] if r else None


async def _closed_reason_at(db, tpid, exit_time, account_id=ACCOUNT_ID):
    async with db._conn.execute(
        "SELECT exit_reason FROM closed_positions "
        "WHERE account_id=? AND terminal_position_id=? AND exit_time_ms=?",
        (account_id, tpid, exit_time),
    ) as cur:
        r = await cur.fetchone()
    return r[0] if r else None


# ── _classify_final_exit_reason (unit) ─────────────────────────────────


class TestClassifyFinalExitReason:
    @pytest.mark.asyncio
    async def test_two_tp_orders_is_ladder_complete(self, db, om):
        await _seed_order(db, "TP1", "take_profit")
        await _seed_order(db, "TP2", "take_profit")
        await _seed_fill(db, "F1", "TP1", "POS-1", 0.5, is_close=True, ts=2000)
        await _seed_fill(db, "F2", "TP2", "POS-1", 0.5, is_close=True, ts=3000)
        r = await om._classify_final_exit_reason(
            ACCOUNT_ID, "POS-1", fallback="TP_PLANNED")
        assert r == "TP_LADDER_COMPLETE"

    @pytest.mark.asyncio
    async def test_tp_then_sl_is_mixed(self, db, om):
        await _seed_order(db, "TP1", "take_profit")
        await _seed_order(db, "SL1", "stop_loss")
        await _seed_fill(db, "F1", "TP1", "POS-1", 0.5, is_close=True, ts=2000)
        await _seed_fill(db, "F2", "SL1", "POS-1", 0.5, is_close=True, ts=3000)
        r = await om._classify_final_exit_reason(
            ACCOUNT_ID, "POS-1", fallback="SL_PLANNED")
        assert r == "MIXED"

    @pytest.mark.asyncio
    async def test_tp_then_manual_market_is_mixed(self, db, om):
        await _seed_order(db, "TP1", "take_profit")
        await _seed_order(db, "MK1", "market")
        await _seed_fill(db, "F1", "TP1", "POS-1", 0.5, is_close=True, ts=2000)
        await _seed_fill(db, "F2", "MK1", "POS-1", 0.5, is_close=True, ts=3000)
        r = await om._classify_final_exit_reason(
            ACCOUNT_ID, "POS-1", fallback="MANUAL_OTHER")
        assert r == "MIXED"

    @pytest.mark.asyncio
    async def test_single_tp_falls_back(self, db, om):
        await _seed_order(db, "TP1", "take_profit")
        await _seed_fill(db, "F1", "TP1", "POS-1", 1.0, is_close=True, ts=2000)
        r = await om._classify_final_exit_reason(
            ACCOUNT_ID, "POS-1", fallback="TP_PLANNED")
        assert r == "TP_PLANNED"   # one TP order is not a ladder

    @pytest.mark.asyncio
    async def test_two_sl_orders_fall_back_not_ladder(self, db, om):
        await _seed_order(db, "SL1", "stop_loss")
        await _seed_order(db, "SL2", "stop_loss")
        await _seed_fill(db, "F1", "SL1", "POS-1", 0.5, is_close=True, ts=2000)
        await _seed_fill(db, "F2", "SL2", "POS-1", 0.5, is_close=True, ts=3000)
        r = await om._classify_final_exit_reason(
            ACCOUNT_ID, "POS-1", fallback="SL_PLANNED")
        assert r == "SL_PLANNED"   # all-SL is not a TP ladder, not MIXED

    @pytest.mark.asyncio
    async def test_empty_pos_id_falls_back(self, db, om):
        r = await om._classify_final_exit_reason(
            ACCOUNT_ID, "", fallback="MANUAL_OTHER")
        assert r == "MANUAL_OTHER"

    @pytest.mark.asyncio
    async def test_no_closing_fills_falls_back(self, db, om):
        r = await om._classify_final_exit_reason(
            ACCOUNT_ID, "POS-NONE", fallback="TP_PLANNED")
        assert r == "TP_PLANNED"

    @pytest.mark.asyncio
    async def test_single_tp_multiple_partial_fills_not_ladder(self, db, om):
        # ONE take_profit order filling in two partial fills is NOT a ladder
        # (1 distinct closing order) → fallback.
        await _seed_order(db, "TP1", "take_profit")
        await _seed_fill(db, "F1", "TP1", "POS-1", 0.5, is_close=True, ts=2000)
        await _seed_fill(db, "F2", "TP1", "POS-1", 0.5, is_close=True, ts=2100)
        r = await om._classify_final_exit_reason(
            ACCOUNT_ID, "POS-1", fallback="TP_PLANNED")
        assert r == "TP_PLANNED"


# ── full close-row path: completion deferral + ladder exit_reason ──────


class TestMultiTpCloseRowPath:
    @pytest.mark.asyncio
    async def test_partial_then_final_defers_completion_and_marks_ladder(self, db, om):
        # REALISTIC deferred-build timing (T238 review F1 regression test):
        # both TP rungs fill within the 2s defer window, so BOTH closing
        # fills are on disk before EITHER deferred close-row build runs. The
        # is_final sum must be scoped to fills ≤ this build's exit_time, else
        # TP1's build sees the full qty and mis-stamps its partial row as
        # TP_LADDER_COMPLETE + completes the calc early. (The pre-fix test
        # seeded F2 only AFTER building TP1 — an ordering that never occurs
        # on the real hot path — and so masked the bug.)
        await _seed_calc(db, "C1", status="matched")
        await _seed_fill(db, "FO", "EO", "POS-1", 1.0, is_close=False,
                         calc_id="C1", ts=1000)
        await _seed_order(db, "TP1", "take_profit")
        await _seed_order(db, "TP2", "take_profit")
        await _seed_fill(db, "F1", "TP1", "POS-1", 0.5, is_close=True,
                         ts=2000, pnl=10.0)
        await _seed_fill(db, "F2", "TP2", "POS-1", 0.5, is_close=True,
                         ts=3000, pnl=12.0)   # ← already recorded before TP1's build

        # TP1's build runs FIRST, with BOTH fills already on disk.
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill("TP1", "POS-1", 2000))
        # Scoped to ts ≤ 2000 (=0.5 < 1.0) → NOT final: per-order TP_PLANNED,
        # calc stays matched (completion deferred).
        assert await _closed_reason_at(db, "POS-1", 2000) == "TP_PLANNED"
        assert await _calc_status(db, "C1") == "matched"

        # TP2's build (final).
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill("TP2", "POS-1", 3000))
        assert await _closed_reason_at(db, "POS-1", 3000) == "TP_LADDER_COMPLETE"
        assert await _closed_reason_at(db, "POS-1", 2000) == "TP_PLANNED"  # unchanged
        assert await _calc_status(db, "C1") == "completed_via_position"

    @pytest.mark.asyncio
    async def test_disappearance_backstop_completes_stranded_calc(self, db, om):
        # T238 review F1 backstop: a closing fill is MISSED (WS gap) — only
        # 0.5 of a 1.0 position is recorded, so is_final is NEVER True on the
        # per-fill builds and the calc would strand in `matched`. When the
        # position disappears, build_final_close_row's backstop
        # (_complete_position_calcs) force-completes contributing calcs.
        await _seed_calc(db, "C1", status="matched")
        await _seed_fill(db, "FO", "EO", "POS-9", 1.0, is_close=False,
                         calc_id="C1", ts=1000)
        await _seed_order(db, "MK1", "market")
        await _seed_fill(db, "F1", "MK1", "POS-9", 0.5, is_close=True, ts=2000)

        # The recorded partial's build is NOT final (0.5 < 1.0) → no completion.
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill("MK1", "POS-9", 2000))
        assert await _calc_status(db, "C1") == "matched"

        # Position gone → backstop completes (calc_ids resolved from opening
        # fills since no junction was seeded).
        await om._complete_position_calcs(ACCOUNT_ID, "POS-9")
        assert await _calc_status(db, "C1") == "completed_via_position"

    @pytest.mark.asyncio
    async def test_backstop_empty_pos_id_is_noop(self, db, om):
        await om._complete_position_calcs(ACCOUNT_ID, "")  # no raise

    @pytest.mark.asyncio
    async def test_tp_then_sl_final_is_mixed(self, db, om):
        await _seed_calc(db, "C1", status="matched")
        await _seed_fill(db, "FO", "EO", "POS-2", 1.0, is_close=False,
                         calc_id="C1", ts=1000)
        await _seed_order(db, "TP1", "take_profit")
        await _seed_fill(db, "F1", "TP1", "POS-2", 0.5, is_close=True, ts=2000)
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill("TP1", "POS-2", 2000))
        assert await _calc_status(db, "C1") == "matched"   # partial

        await _seed_order(db, "SL1", "stop_loss")
        await _seed_fill(db, "F2", "SL1", "POS-2", 0.5, is_close=True, ts=3000)
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill("SL1", "POS-2", 3000))

        assert await _calc_status(db, "C1") == "completed_via_position"
        assert await _closed_reason_at(db, "POS-2", 3000) == "MIXED"

    @pytest.mark.asyncio
    async def test_single_full_close_completes_immediately(self, db, om):
        # Common case: one close == full position → is_final immediately,
        # calc completes, exit_reason stays per-order (single TP → TP_PLANNED).
        await _seed_calc(db, "C1", status="matched")
        await _seed_fill(db, "FO", "EO", "POS-3", 1.0, is_close=False,
                         calc_id="C1", ts=1000)
        await _seed_order(db, "TP1", "take_profit")
        await _seed_fill(db, "F1", "TP1", "POS-3", 1.0, is_close=True, ts=2000)
        await om._build_close_row_for_fill(ACCOUNT_ID, _close_fill("TP1", "POS-3", 2000))

        assert await _calc_status(db, "C1") == "completed_via_position"
        assert await _closed_reason_at(db, "POS-3", 2000) == "TP_PLANNED"

    @pytest.mark.asyncio
    async def test_force_final_completes_on_disappearance(self, db, om):
        # build_final_close_row passes force_final=True (position gone from
        # snapshot) — completes even if a partial-qty close is all that's
        # recorded (e.g. a missed/over-counted fill).
        await _seed_calc(db, "C1", status="matched")
        await _seed_fill(db, "FO", "EO", "POS-4", 1.0, is_close=False,
                         calc_id="C1", ts=1000)
        await _seed_order(db, "MK1", "market")
        await _seed_fill(db, "F1", "MK1", "POS-4", 0.5, is_close=True, ts=2000)

        await om._build_close_row_for_fill(
            ACCOUNT_ID, _close_fill("MK1", "POS-4", 2000), force_final=True)

        assert await _calc_status(db, "C1") == "completed_via_position"
