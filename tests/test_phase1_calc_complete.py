"""
Phase 1 Task 6 (P1.T6 / plan §1 task 1.8) — calc auto-complete on close.

Pins core.order_manager.OrderManager._complete_calcs_on_close:

- matched → completed_via_position, calc:completed event fires with
  position_id (spec §2[D/E] / §5 / §9).
- partially_actioned → completed_via_position (also a valid source edge).
- Multiple contributing calcs (scale-in) all completed in one close.
- Non-completable states (released / superseded / cancelled_by_operator /
  already-completed) are skipped — no transition, no event.
- Empty / None calc_ids skipped.

Tests the helper directly (the close-row builder's contributing-calc
extraction is thin glue over it).

Run: pytest tests/test_phase1_calc_complete.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from typing import List, Optional

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


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
        "INSERT OR IGNORE INTO accounts (id, name) VALUES (?, ?)", (1, "Test"),
    )
    await db._conn.commit()
    yield OrderManager(db), db
    await db.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


async def _insert_calc(db, *, calc_id: str, status: str = "matched") -> None:
    await db._conn.execute(
        "INSERT INTO pre_trade_log "
        "(account_id, timestamp, ticker, side, effective_entry, "
        " tp_price, sl_price, average, calc_id, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, datetime.now(timezone.utc).isoformat(), "BTCUSDT", "long",
         50000.0, 55000.0, 48000.0, 50000.0, calc_id, status),
    )
    await db._conn.commit()


async def _status(db, calc_id: str) -> Optional[str]:
    async with db._conn.execute(
        "SELECT status FROM pre_trade_log WHERE calc_id = ?", (calc_id,),
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


def _drain(channel: str | None = None) -> List[tuple]:
    from core.event_bus import event_bus
    evs = []
    while not event_bus._queue.empty():
        evs.append(event_bus._queue.get_nowait()[:2])  # CL.T2a: item is (ch, payload, corr_id)
    # P6.T3: calc:* events ride engine:account:{id}:calc:{event}; match by the
    # calc:{event} suffix ONLY (no flat fallback → a flat-topic regression FAILS
    # the test, Rule 8). Full per-account topic asserted in test_state_machines.
    if not channel:
        return evs
    return [(c, p) for c, p in evs if c.endswith(":" + channel)]


# ── Core flow ─────────────────────────────────────────────────────────


class TestCompleteOnClose:
    @pytest.mark.asyncio
    async def test_matched_calc_completed(self, om):
        o, db = om
        await _insert_calc(db, calc_id="m-1", status="matched")
        _drain()

        await o._complete_calcs_on_close(1, {"m-1"}, "POS-1")

        assert await _status(db, "m-1") == "completed_via_position"

    @pytest.mark.asyncio
    async def test_calc_completed_event_fires(self, om):
        """Spec §9: calc:completed carries calc_id + position_id."""
        o, db = om
        await _insert_calc(db, calc_id="m-2", status="matched")
        _drain()

        await o._complete_calcs_on_close(1, {"m-2"}, "POS-2")

        events = _drain("calc:completed")
        assert len(events) == 1
        _, payload = events[0]
        assert payload["calc_id"] == "m-2"
        assert payload["position_id"] == "POS-2"
        assert payload["from_status"] == "matched"
        assert payload["to_status"] == "completed_via_position"

    @pytest.mark.asyncio
    async def test_partially_actioned_calc_completed(self, om):
        """partially_actioned → completed_via_position is a valid edge."""
        o, db = om
        await _insert_calc(db, calc_id="pa-1", status="partially_actioned")
        await o._complete_calcs_on_close(1, {"pa-1"}, "POS-3")
        assert await _status(db, "pa-1") == "completed_via_position"

    @pytest.mark.asyncio
    async def test_multiple_contributing_calcs_all_completed(self, om):
        """Scale-in: several distinct calcs contributed to the position;
        all matched ones complete on close.
        """
        o, db = om
        await _insert_calc(db, calc_id="sc-1", status="matched")
        await _insert_calc(db, calc_id="sc-2", status="matched")
        _drain()

        await o._complete_calcs_on_close(1, {"sc-1", "sc-2"}, "POS-4")

        assert await _status(db, "sc-1") == "completed_via_position"
        assert await _status(db, "sc-2") == "completed_via_position"
        assert len(_drain("calc:completed")) == 2


# ── Guards: non-completable states skipped ────────────────────────────


class TestCompleteGuards:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [
        "released", "superseded", "cancelled_by_operator",
        "completed_via_position", "expired", "active",
    ])
    async def test_non_completable_states_skipped(self, om, status):
        """Only matched / partially_actioned are completable. Everything
        else (including already-completed and a never-matched 'active')
        is left untouched with no event.

        Why 'active' is skipped: a position close should only complete a
        calc that actually matched. An 'active' calc that never linked to
        an order has no business being completed by an unrelated close.
        """
        o, db = om
        await _insert_calc(db, calc_id="g-1", status=status)
        _drain()

        await o._complete_calcs_on_close(1, {"g-1"}, "POS-G")

        assert await _status(db, "g-1") == status  # unchanged
        assert _drain("calc:completed") == []

    @pytest.mark.asyncio
    async def test_empty_and_none_calc_ids_skipped(self, om):
        o, db = om
        # Should not raise on empty set, None, or empty string
        await o._complete_calcs_on_close(1, set(), "POS-E")
        await o._complete_calcs_on_close(1, {None, ""}, "POS-E")
        assert _drain("calc:completed") == []

    @pytest.mark.asyncio
    async def test_unknown_calc_id_skipped(self, om):
        o, db = om
        await o._complete_calcs_on_close(1, {"does-not-exist"}, "POS-U")
        assert _drain("calc:completed") == []

    @pytest.mark.asyncio
    async def test_mixed_completable_and_not(self, om):
        """A close touching one matched + one already-completed calc:
        the matched one completes, the other is a no-op.
        """
        o, db = om
        await _insert_calc(db, calc_id="mix-m", status="matched")
        await _insert_calc(db, calc_id="mix-done", status="completed_via_position")
        _drain()

        await o._complete_calcs_on_close(1, {"mix-m", "mix-done"}, "POS-MX")

        assert await _status(db, "mix-m") == "completed_via_position"
        assert await _status(db, "mix-done") == "completed_via_position"
        # Only ONE new event (for mix-m); mix-done was already terminal
        assert len(_drain("calc:completed")) == 1

    @pytest.mark.asyncio
    async def test_cross_account_skipped(self, om):
        """A calc on account 1 isn't completed by account 2's close."""
        o, db = om
        await _insert_calc(db, calc_id="acct1", status="matched")
        await o._complete_calcs_on_close(2, {"acct1"}, "POS-X")
        assert await _status(db, "acct1") == "matched"  # untouched
