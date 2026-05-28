"""
Phase 1 Task 4 (P1.T4 / plan §1 task 1.6) — calc cancel by operator.

Pins core.handlers.cancel_calc_by_operator:

- active → cancelled_by_operator, cancelled_reason captured, calc:cancelled
  event fires (with reason + reason_note per spec §9 / T215 H1).
- released → cancelled_by_operator (RELEASED has the edge too).
- matched / expired / superseded / completed → 'not_cancellable'.
- unknown calc_id → 'not_found'.
- empty reason → cancelled_reason NULL.
- TOCTOU: status flipped between read and UPDATE → 'race_lost', no event.

Run: pytest tests/test_phase1_calc_cancel.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest_asyncio.fixture
async def wired(monkeypatch):
    """Tempfile DB with full schema; core.handlers.db pointed at it."""
    from core.database import DatabaseManager
    from core import handlers
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    await db._conn.execute(
        "INSERT OR IGNORE INTO accounts (id, name) VALUES (?, ?)", (1, "Test"),
    )
    await db._conn.commit()
    monkeypatch.setattr(handlers, "db", db)
    yield handlers, db
    await db.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


async def _insert_calc(db, *, calc_id: str, status: str = "active") -> None:
    await db._conn.execute(
        "INSERT INTO pre_trade_log "
        "(account_id, timestamp, ticker, side, effective_entry, "
        " tp_price, sl_price, average, calc_id, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, datetime.now(timezone.utc).isoformat(), "BTCUSDT", "long",
         50000.0, 55000.0, 48000.0, 50000.0, calc_id, status),
    )
    await db._conn.commit()


async def _read(db, calc_id: str) -> Optional[Tuple[str, Any]]:
    async with db._conn.execute(
        "SELECT status, cancelled_reason FROM pre_trade_log WHERE calc_id = ?",
        (calc_id,),
    ) as cur:
        return await cur.fetchone()


def _drain(channel: str | None = None) -> List[tuple]:
    from core.event_bus import event_bus
    evs = []
    while not event_bus._queue.empty():
        evs.append(event_bus._queue.get_nowait())
    return [(c, p) for c, p in evs if c == channel] if channel else evs


# ── Core flow ─────────────────────────────────────────────────────────


class TestCancelActive:
    @pytest.mark.asyncio
    async def test_active_cancelled_with_reason(self, wired):
        handlers, db = wired
        await _insert_calc(db, calc_id="c-1", status="active")
        _drain()

        result = await handlers.cancel_calc_by_operator(1, "c-1", "changed my mind")
        assert result == "cancelled"

        row = await _read(db, "c-1")
        assert row[0] == "cancelled_by_operator"
        assert row[1] == "changed my mind"

    @pytest.mark.asyncio
    async def test_calc_cancelled_event_fires(self, wired):
        """Spec §9: calc:cancelled carries calc_id + reason (+ reason_note
        alias from T215 H1).
        """
        handlers, db = wired
        await _insert_calc(db, calc_id="c-2", status="active")
        _drain()

        await handlers.cancel_calc_by_operator(1, "c-2", "duplicate setup")

        events = _drain("calc:cancelled")
        assert len(events) == 1
        _, payload = events[0]
        assert payload["calc_id"] == "c-2"
        assert payload["from_status"] == "active"
        assert payload["to_status"] == "cancelled_by_operator"
        assert payload["reason"] == "duplicate setup"
        assert payload["reason_note"] == "duplicate setup"

    @pytest.mark.asyncio
    async def test_empty_reason_stored_null(self, wired):
        handlers, db = wired
        await _insert_calc(db, calc_id="c-3", status="active")
        result = await handlers.cancel_calc_by_operator(1, "c-3", "")
        assert result == "cancelled"
        row = await _read(db, "c-3")
        assert row[0] == "cancelled_by_operator"
        assert row[1] is None  # empty reason → NULL, not ""

    @pytest.mark.asyncio
    async def test_whitespace_reason_stored_null(self, wired):
        handlers, db = wired
        await _insert_calc(db, calc_id="c-3b", status="active")
        await handlers.cancel_calc_by_operator(1, "c-3b", "   ")
        row = await _read(db, "c-3b")
        assert row[1] is None


class TestCancelReleased:
    @pytest.mark.asyncio
    async def test_released_is_cancellable(self, wired):
        """RELEASED → CANCELLED_BY_OPERATOR is a valid edge (spec §5).
        An operator can cancel a released calc (e.g., abandoning the
        re-match after an order cancel).
        """
        handlers, db = wired
        await _insert_calc(db, calc_id="c-4", status="released")
        result = await handlers.cancel_calc_by_operator(1, "c-4", "abandon")
        assert result == "cancelled"
        row = await _read(db, "c-4")
        assert row[0] == "cancelled_by_operator"


# ── Guards ────────────────────────────────────────────────────────────


class TestCancelGuards:
    @pytest.mark.asyncio
    async def test_matched_not_cancellable(self, wired):
        """A matched calc is linked to a working order — cancel the ORDER
        (which releases the calc), not the calc directly.
        """
        handlers, db = wired
        await _insert_calc(db, calc_id="c-5", status="matched")
        result = await handlers.cancel_calc_by_operator(1, "c-5", "")
        assert result == "not_cancellable"
        row = await _read(db, "c-5")
        assert row[0] == "matched"  # unchanged

    @pytest.mark.asyncio
    async def test_already_cancelled_not_cancellable(self, wired):
        handlers, db = wired
        await _insert_calc(db, calc_id="c-6", status="cancelled_by_operator")
        result = await handlers.cancel_calc_by_operator(1, "c-6", "")
        assert result == "not_cancellable"

    @pytest.mark.asyncio
    async def test_expired_not_cancellable(self, wired):
        handlers, db = wired
        await _insert_calc(db, calc_id="c-7", status="expired")
        result = await handlers.cancel_calc_by_operator(1, "c-7", "")
        assert result == "not_cancellable"

    @pytest.mark.asyncio
    async def test_unknown_calc_not_found(self, wired):
        handlers, db = wired
        result = await handlers.cancel_calc_by_operator(1, "does-not-exist", "")
        assert result == "not_found"

    @pytest.mark.asyncio
    async def test_empty_calc_id_not_found(self, wired):
        handlers, db = wired
        result = await handlers.cancel_calc_by_operator(1, "", "")
        assert result == "not_found"

    @pytest.mark.asyncio
    async def test_cross_account_not_found(self, wired):
        """A calc on account 1 isn't cancellable via account 2's request."""
        handlers, db = wired
        await _insert_calc(db, calc_id="c-8", status="active")
        result = await handlers.cancel_calc_by_operator(2, "c-8", "")
        assert result == "not_found"
        row = await _read(db, "c-8")
        assert row[0] == "active"  # untouched


# ── TOCTOU ────────────────────────────────────────────────────────────


class TestCancelRace:
    @pytest.mark.asyncio
    async def test_concurrent_flip_yields_race_lost(self, wired, monkeypatch):
        """If the calc is flipped out of 'active' between the status read
        and the UPDATE, the guarded UPDATE affects 0 rows → 'race_lost',
        no calc:cancelled event.
        """
        handlers, db = wired
        await _insert_calc(db, calc_id="c-9", status="active")
        _drain()

        from core import calc_state
        original = calc_state.transition

        async def racing_transition(calc_id, current_status, target_status, *, apply_fn, **kw):
            # Inject a concurrent supersede before apply_fn runs.
            await db._conn.execute(
                "UPDATE pre_trade_log SET status='superseded' WHERE calc_id=?",
                (calc_id,),
            )
            await db._conn.commit()
            await original(calc_id, current_status, target_status, apply_fn=apply_fn, **kw)

        # cancel_calc_by_operator does `from core.calc_state import
        # transition` at call time — patch the source module so the
        # local import picks up the racing version.
        monkeypatch.setattr("core.calc_state.transition", racing_transition)

        result = await handlers.cancel_calc_by_operator(1, "c-9", "race")
        assert result == "race_lost"

        # calc stayed superseded (the racing flip won), no cancel event
        row = await _read(db, "c-9")
        assert row[0] == "superseded"
        assert _drain("calc:cancelled") == []
