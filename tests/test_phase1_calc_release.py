"""
Phase 1 Task 5 (P1.T5 / plan §1 task 1.7) — calc release on operator cancel.

Pins the matched → released transition when a working entry order is
cancelled:

- Working (unfilled, non-reduce-only) entry cancel with a matched calc
  → calc released, cancel_reason_category='OPERATOR' + raw + ts captured.
- Filled entry cancel (position opened) → calc NOT released.
- Reduce-only (TP/SL) cancel → no-op.
- Order with no linked calc → no-op.
- Calc not in 'matched' (already released / completed) → graceful no-op
  via the TOCTOU guard.
- After release, the calc is matcher-eligible again (status='released'
  is in the candidate filter).

Cancel-reason classification is DEFAULT-OPERATOR (T216 decision): the
engine is observe-only and can't distinguish operator vs venue cancels
without venue-specific reason mapping, so a working-entry cancel
defaults to OPERATOR (the dominant case in the copy-paste workflow).

Run: pytest tests/test_phase1_calc_release.py -v
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def om():
    """OrderManager wired to a tempfile DB with the full schema."""
    from core.database import DatabaseManager
    from core.order_manager import OrderManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    await db._conn.execute(
        "INSERT OR IGNORE INTO accounts (id, name) VALUES (?, ?)",
        (1, "Test"),
    )
    await db._conn.commit()
    om = OrderManager(db)
    yield om, db
    await db.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


def _now_iso(offset_sec: float = 0.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_sec)).isoformat()


async def _insert_calc(db, *, calc_id: str, status: str = "matched",
                       ticker: str = "BTCUSDT", side: str = "long") -> None:
    await db._conn.execute(
        "INSERT INTO pre_trade_log "
        "(account_id, timestamp, ticker, side, effective_entry, "
        " tp_price, sl_price, average, calc_id, status, window_seconds) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, _now_iso(-30.0), ticker, side, 50000.0, 55000.0, 48000.0,
         50000.0, calc_id, status, 300),
    )
    await db._conn.commit()


async def _insert_order(db, *, eid: str, calc_id: Optional[str],
                        status: str = "new", reduce_only: int = 0,
                        filled_qty: float = 0.0,
                        symbol: str = "BTCUSDT", side: str = "BUY") -> None:
    await db._conn.execute(
        "INSERT INTO orders "
        "(account_id, exchange_order_id, symbol, side, order_type, "
        " status, price, quantity, filled_qty, reduce_only, calc_id, "
        " created_at_ms) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, eid, symbol, side, "limit", status, 50000.0, 0.01,
         filled_qty, reduce_only, calc_id, int(time.time() * 1000)),
    )
    await db._conn.commit()


async def _calc_status(db, calc_id: str) -> Optional[str]:
    async with db._conn.execute(
        "SELECT status FROM pre_trade_log WHERE calc_id = ?", (calc_id,),
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


async def _order_cancel_fields(db, eid: str) -> Dict[str, Any]:
    async with db._conn.execute(
        "SELECT cancel_reason_category, cancel_reason_raw, cancel_ts_ms "
        "FROM orders WHERE exchange_order_id = ?", (eid,),
    ) as cur:
        row = await cur.fetchone()
    return {
        "category": row[0], "raw": row[1], "ts_ms": row[2],
    } if row else {}


# ── 1. The core release flow ──────────────────────────────────────────


class TestReleaseOnOperatorCancel:
    @pytest.mark.asyncio
    async def test_unfilled_cancel_releases_matched_calc(self, om):
        o, db = om
        await _insert_calc(db, calc_id="rel-1", status="matched")
        await _insert_order(db, eid="o-rel-1", calc_id="rel-1",
                            status="canceled", filled_qty=0.0)

        await o._release_calc_on_operator_cancel(
            1, {"exchange_order_id": "o-rel-1", "status": "canceled"},
        )

        assert await _calc_status(db, "rel-1") == "released"

    @pytest.mark.asyncio
    async def test_cancel_reason_captured(self, om):
        """cancel_reason_category='OPERATOR' + raw venue status + ts."""
        o, db = om
        await _insert_calc(db, calc_id="rel-2", status="matched")
        await _insert_order(db, eid="o-rel-2", calc_id="rel-2",
                            status="canceled", filled_qty=0.0)

        before_ms = int(time.time() * 1000)
        await o._release_calc_on_operator_cancel(
            1, {"exchange_order_id": "o-rel-2", "status": "canceled"},
        )

        fields = await _order_cancel_fields(db, "o-rel-2")
        assert fields["category"] == "OPERATOR"
        assert fields["raw"] == "canceled"
        assert fields["ts_ms"] >= before_ms

    @pytest.mark.asyncio
    async def test_order_cancelled_event_emitted(self, om):
        # P6 (spec §9 calc:order_cancelled): a SUCCESSFUL release emits the event
        # on the per-account topic. RELEASED itself has no transition event, so
        # this is the ONLY event on the release path.
        o, db = om
        from core.event_bus import event_bus
        await _insert_calc(db, calc_id="rel-e", status="matched")
        await _insert_order(db, eid="o-rel-e", calc_id="rel-e",
                            status="canceled", filled_qty=0.0)
        while not event_bus._queue.empty():
            event_bus._queue.get_nowait()

        await o._release_calc_on_operator_cancel(
            1, {"exchange_order_id": "o-rel-e", "status": "canceled"},
        )

        events = []
        while not event_bus._queue.empty():
            events.append(event_bus._queue.get_nowait()[:2])  # CL.T2a: item is (ch, payload, corr_id)
        cancelled = [
            (c, p) for c, p in events
            if c == "engine:account:1:calc:order_cancelled"
        ]
        assert len(cancelled) == 1, f"expected 1 calc:order_cancelled, got {events!r}"
        _, payload = cancelled[0]
        assert payload["calc_id"] == "rel-e"
        assert payload["cancel_reason_category"] == "OPERATOR"
        assert payload["raw"] == "canceled"
        assert isinstance(payload["order_id"], int)   # internal order id

    @pytest.mark.asyncio
    async def test_no_event_when_release_is_noop(self, om):
        # Rule 8: the event fires ONLY on a successful release. A non-matched
        # calc (already released) → TOCTOU no-op → NO calc:order_cancelled.
        o, db = om
        from core.event_bus import event_bus
        await _insert_calc(db, calc_id="rel-n", status="released")
        await _insert_order(db, eid="o-rel-n", calc_id="rel-n",
                            status="canceled", filled_qty=0.0)
        while not event_bus._queue.empty():
            event_bus._queue.get_nowait()

        await o._release_calc_on_operator_cancel(
            1, {"exchange_order_id": "o-rel-n", "status": "canceled"},
        )

        events = [
            c for c, *_ in (
                event_bus._queue.get_nowait()
                for _ in range(event_bus._queue.qsize())
            )
        ]
        assert not any(c.endswith(":calc:order_cancelled") for c in events)

    @pytest.mark.asyncio
    async def test_released_calc_is_matcher_eligible_again(self, om):
        """After release, the calc's status='released' is in the matcher's
        candidate filter (spec §4.3). Verify a fresh order re-links it.

        Why this matters: the whole point of release-on-cancel is that
        the operator can place a replacement order and have it re-link
        to the same calc. If released calcs weren't matcher-eligible,
        the release would be a dead end.
        """
        from core.calc_correlation import correlate_order_to_calc, LINK_STATUS_LINKED
        o, db = om
        await _insert_calc(db, calc_id="rel-3", status="matched")
        await _insert_order(db, eid="o-rel-3", calc_id="rel-3",
                            status="canceled", filled_qty=0.0)
        await o._release_calc_on_operator_cancel(
            1, {"exchange_order_id": "o-rel-3", "status": "canceled"},
        )
        assert await _calc_status(db, "rel-3") == "released"

        # A replacement order arrives — matcher should find the released
        # calc as a candidate and re-link it.
        result = correlate_order_to_calc(
            {"account_id": 1, "symbol": "BTCUSDT", "side": "BUY",
             "order_type": "limit", "price": 50000.0,
             "tp_trigger_price": 55000.0, "sl_trigger_price": 48000.0,
             "created_at_ms": int(time.time() * 1000)},
            order_id=999,
            tick_size=0.1,
            db_path=db.path,
        )
        assert result.calc_id == "rel-3"
        assert result.link_status == LINK_STATUS_LINKED
        assert result.matched_from_status == "released"


# ── 2. Guards: when NOT to release ────────────────────────────────────


class TestReleaseGuards:
    @pytest.mark.asyncio
    async def test_filled_order_does_not_release(self, om):
        """A partially/fully filled order opened a position — the calc is
        matched + contributing and must NOT be released.
        """
        o, db = om
        await _insert_calc(db, calc_id="g-1", status="matched")
        await _insert_order(db, eid="o-g-1", calc_id="g-1",
                            status="canceled", filled_qty=0.005)  # partial fill

        await o._release_calc_on_operator_cancel(
            1, {"exchange_order_id": "o-g-1", "status": "canceled"},
        )

        assert await _calc_status(db, "g-1") == "matched"  # unchanged

    @pytest.mark.asyncio
    async def test_reduce_only_cancel_is_noop(self, om):
        """A reduce-only (TP/SL) order cancel is not an entry cancel."""
        o, db = om
        await _insert_calc(db, calc_id="g-2", status="matched")
        await _insert_order(db, eid="o-g-2", calc_id="g-2",
                            status="canceled", reduce_only=1, filled_qty=0.0)

        await o._release_calc_on_operator_cancel(
            1, {"exchange_order_id": "o-g-2", "status": "canceled",
                "reduce_only": 1},
        )

        assert await _calc_status(db, "g-2") == "matched"
        # No cancel reason captured either (early return before capture)
        fields = await _order_cancel_fields(db, "o-g-2")
        assert fields["category"] is None

    @pytest.mark.asyncio
    async def test_no_calc_id_is_noop(self, om):
        """An UNPLANNED / unlinked order cancel has no calc to release."""
        o, db = om
        await _insert_order(db, eid="o-g-3", calc_id=None,
                            status="canceled", filled_qty=0.0)

        # Should not raise
        await o._release_calc_on_operator_cancel(
            1, {"exchange_order_id": "o-g-3", "status": "canceled"},
        )
        fields = await _order_cancel_fields(db, "o-g-3")
        assert fields["category"] is None  # no capture without calc

    @pytest.mark.asyncio
    async def test_non_canceled_status_is_noop(self, om):
        """'expired' is venue-initiated (GTC expiry), not an operator
        cancel — don't release.
        """
        o, db = om
        await _insert_calc(db, calc_id="g-4", status="matched")
        await _insert_order(db, eid="o-g-4", calc_id="g-4",
                            status="expired", filled_qty=0.0)

        await o._release_calc_on_operator_cancel(
            1, {"exchange_order_id": "o-g-4", "status": "expired"},
        )
        assert await _calc_status(db, "g-4") == "matched"

    @pytest.mark.asyncio
    async def test_non_matched_calc_graceful_noop(self, om):
        """If the linked calc isn't 'matched' (e.g., already completed via
        position), the TOCTOU-guarded UPDATE affects 0 rows and the
        transition is skipped without error.
        """
        o, db = om
        await _insert_calc(db, calc_id="g-5", status="completed_via_position")
        await _insert_order(db, eid="o-g-5", calc_id="g-5",
                            status="canceled", filled_qty=0.0)

        # Should not raise; calc stays completed
        await o._release_calc_on_operator_cancel(
            1, {"exchange_order_id": "o-g-5", "status": "canceled"},
        )
        assert await _calc_status(db, "g-5") == "completed_via_position"

    @pytest.mark.asyncio
    async def test_idempotent_repeat_cancel(self, om):
        """A repeat WS cancel for the same order is a no-op (calc already
        released). Pins the idempotency guarantee.
        """
        o, db = om
        await _insert_calc(db, calc_id="g-6", status="matched")
        await _insert_order(db, eid="o-g-6", calc_id="g-6",
                            status="canceled", filled_qty=0.0)

        await o._release_calc_on_operator_cancel(
            1, {"exchange_order_id": "o-g-6", "status": "canceled"},
        )
        assert await _calc_status(db, "g-6") == "released"

        # Second invocation — calc is already 'released', UPDATE is a no-op
        await o._release_calc_on_operator_cancel(
            1, {"exchange_order_id": "o-g-6", "status": "canceled"},
        )
        assert await _calc_status(db, "g-6") == "released"
