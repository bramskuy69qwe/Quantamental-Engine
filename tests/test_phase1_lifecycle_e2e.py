"""
Phase 1 — calc lifecycle END-TO-END through the real handlers (T225).

The Phase-1 holistic audit (M1) found the "calc state machine
transitions verified end-to-end" acceptance criterion was overstated:
the integration driver only drove active→matched e2e, and never
asserted pre_trade_log.status. The non-matched edges were covered only
by isolated component calls.

This file closes that gap: each LIVE transition is driven through the
ACTUAL production handler and pre_trade_log.status is asserted at every
step:

  created     → handle_risk_calculated            (status='active')
  matched     → enrich_order (the matcher)         ('active'→'matched')
  completed   → _build_close_row_for_fill          ('matched'→'completed_via_position')
  released    → _release_calc_on_operator_cancel   ('matched'→'released')
  cancelled   → cancel_calc_by_operator            ('active'→'cancelled_by_operator')
  superseded  → handle_risk_calculated (recalc)    ('active'→'superseded')
  expired     → sweep_expired_calcs                ('active'→'expired')

All three DB handles (handlers.db singleton, the matcher's config.DB_PATH,
OrderManager.self._db) point at the same tmpfile so the real chain works.

Run: pytest tests/test_phase1_lifecycle_e2e.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest_asyncio.fixture
async def e2e(monkeypatch):
    """Wire handlers.db, config.DB_PATH, and an OrderManager all to one
    tmpfile DB so the real handler chain operates on a single store."""
    from core.database import DatabaseManager
    from core.order_manager import OrderManager
    from core import handlers
    import config

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    await db._conn.execute(
        "INSERT OR IGNORE INTO accounts (id, name, config_json) "
        "VALUES (?, ?, ?)",
        (1, "Test", '{"window_seconds": 300, "clock_skew_tolerance_sec": 10}'),
    )
    await db._conn.commit()

    monkeypatch.setattr(handlers, "db", db)
    monkeypatch.setattr(config, "DB_PATH", tmp.name)
    om = OrderManager(db)

    yield handlers, om, db, tmp.name
    await db.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


async def _status(db, calc_id) -> Optional[str]:
    async with db._conn.execute(
        "SELECT status FROM pre_trade_log WHERE calc_id = ?", (calc_id,),
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


def _calc_payload(calc_id="lc-1", ticker="BTCUSDT", side="long",
                  entry=50000.0, tp=55000.0, sl=48000.0):
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker, "side": side, "effective_entry": entry,
        "tp_price": tp, "sl_price": sl, "calc_id": calc_id, "eligible": True,
    }


async def _insert_order(db, *, eid="o-1", symbol="BTCUSDT", side="BUY",
                        price=50000.0, tp=55000.0, sl=48000.0,
                        filled_qty=0.0, pos_id="POS-1"):
    await db._conn.execute(
        "INSERT INTO orders "
        "(account_id, exchange_order_id, symbol, side, order_type, status, "
        " price, tp_trigger_price, sl_trigger_price, avg_fill_price, "
        " filled_qty, exchange_position_id, terminal_position_id, created_at_ms) "
        "VALUES (1, ?, ?, ?, 'limit', 'new', ?, ?, ?, 0, ?, ?, ?, ?)",
        (eid, symbol, side, price, tp, sl, filled_qty, pos_id, pos_id,
         int(time.time() * 1000)),
    )
    await db._conn.commit()


async def _insert_fill(db, *, fid, eid, pos_id="POS-1", symbol="BTCUSDT",
                       direction="long", price=50000.0, qty=0.01,
                       is_close=0, calc_id=None):
    await db._conn.execute(
        "INSERT INTO fills "
        "(account_id, exchange_fill_id, exchange_order_id, symbol, side, "
        " direction, price, quantity, is_close, calc_id, "
        " exchange_position_id, terminal_position_id, timestamp_ms) "
        "VALUES (1, ?, ?, ?, 'BUY', ?, ?, ?, ?, ?, ?, ?, ?)",
        (fid, eid, symbol, direction, price, qty, is_close, calc_id,
         pos_id, pos_id, int(time.time() * 1000)),
    )
    await db._conn.commit()


async def _match_order(handlers_mod, db, *, calc_id="lc-1", eid="o-1"):
    """Create calc (active) + order, run the real matcher, assert matched."""
    await handlers_mod.handle_risk_calculated(_calc_payload(calc_id))
    assert await _status(db, calc_id) == "active"

    await _insert_order(db, eid=eid)
    from core.order_enrichment import enrich_order
    import config
    await enrich_order(
        {"account_id": 1, "exchange_order_id": eid,
         "symbol": "BTCUSDT", "side": "BUY", "order_type": "limit"},
        config.DB_PATH,
    )
    assert await _status(db, calc_id) == "matched", "matcher didn't link the calc"


# ── Full lifecycle paths ──────────────────────────────────────────────


class TestLifecycleE2E:
    @pytest.mark.asyncio
    async def test_active_matched_completed(self, e2e):
        """created → matched → completed_via_position, all real handlers."""
        handlers, om, db, _ = e2e
        await _match_order(handlers, db, calc_id="lc-1", eid="o-1")

        # Real close path: opening fill (carries calc_id) + closing fill,
        # then the production _build_close_row_for_fill.
        await _insert_fill(db, fid="f-open", eid="o-1", is_close=0, calc_id="lc-1")
        await _insert_fill(db, fid="f-close", eid="o-close", is_close=1,
                           price=55000.0)
        closing_fill = {
            "account_id": 1, "exchange_fill_id": "f-close",
            "exchange_order_id": "o-close", "symbol": "BTCUSDT",
            "direction": "long", "terminal_position_id": "POS-1",
            "exchange_position_id": "POS-1", "price": 55000.0,
            "quantity": 0.01, "is_close": 1,
            "timestamp_ms": int(time.time() * 1000),
        }
        await om._build_close_row_for_fill(1, closing_fill)

        assert await _status(db, "lc-1") == "completed_via_position"

    @pytest.mark.asyncio
    async def test_active_matched_released(self, e2e):
        """created → matched → released (operator cancels the working order)."""
        handlers, om, db, _ = e2e
        await _match_order(handlers, db, calc_id="lc-2", eid="o-2")

        # Real release path: operator cancel of the unfilled working order.
        await db._conn.execute(
            "UPDATE orders SET status='canceled' WHERE exchange_order_id='o-2'")
        await db._conn.commit()
        await om._release_calc_on_operator_cancel(
            1, {"exchange_order_id": "o-2", "status": "canceled"})

        assert await _status(db, "lc-2") == "released"

    @pytest.mark.asyncio
    async def test_active_cancelled(self, e2e):
        """created → cancelled_by_operator (real endpoint helper)."""
        handlers, om, db, _ = e2e
        await handlers.handle_risk_calculated(_calc_payload("lc-3"))
        assert await _status(db, "lc-3") == "active"

        result = await handlers.cancel_calc_by_operator(1, "lc-3", "changed mind")
        assert result == "cancelled"
        assert await _status(db, "lc-3") == "cancelled_by_operator"

    @pytest.mark.asyncio
    async def test_active_superseded(self, e2e):
        """created → superseded (recalc for same key, real handler)."""
        handlers, om, db, _ = e2e
        await handlers.handle_risk_calculated(_calc_payload("lc-4a"))
        assert await _status(db, "lc-4a") == "active"

        # Recalc same (account, ticker, side) → supersedes the first.
        await handlers.handle_risk_calculated(_calc_payload("lc-4b"))
        assert await _status(db, "lc-4a") == "superseded"
        assert await _status(db, "lc-4b") == "active"

    @pytest.mark.asyncio
    async def test_active_expired(self, e2e):
        """created (backdated) → expired (real sweeper).

        handle_risk_calculated stamps 'now', so to exercise expiry we
        backdate the timestamp past the window, then run the real
        sweep_expired_calcs handler.
        """
        handlers, om, db, _ = e2e
        await handlers.handle_risk_calculated(_calc_payload("lc-5"))
        assert await _status(db, "lc-5") == "active"

        # Backdate 400s (window 300 + skew 10 = 310 → lapsed)
        old_ts = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        await db._conn.execute(
            "UPDATE pre_trade_log SET timestamp=? WHERE calc_id='lc-5'", (old_ts,))
        await db._conn.commit()

        n = await handlers.sweep_expired_calcs(1)
        assert n == 1
        assert await _status(db, "lc-5") == "expired"

    @pytest.mark.asyncio
    async def test_matched_released_rematched(self, e2e):
        """The full re-match loop: matched → released → matched again
        (a replacement order re-links the released calc). Exercises the
        RELEASED→MATCHED edge end-to-end.
        """
        handlers, om, db, _ = e2e
        await _match_order(handlers, db, calc_id="lc-6", eid="o-6")

        # Cancel the working order → release the calc
        await db._conn.execute(
            "UPDATE orders SET status='canceled' WHERE exchange_order_id='o-6'")
        await db._conn.commit()
        await om._release_calc_on_operator_cancel(
            1, {"exchange_order_id": "o-6", "status": "canceled"})
        assert await _status(db, "lc-6") == "released"

        # Replacement order arrives → matcher re-links the released calc
        await _insert_order(db, eid="o-6b")
        from core.order_enrichment import enrich_order
        import config
        await enrich_order(
            {"account_id": 1, "exchange_order_id": "o-6b",
             "symbol": "BTCUSDT", "side": "BUY", "order_type": "limit"},
            config.DB_PATH,
        )
        assert await _status(db, "lc-6") == "matched", "released calc didn't re-match"
