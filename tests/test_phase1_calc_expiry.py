"""
Phase 1.8 (audit follow-up T224) — live calc-expiry sweeper.

Closes the Phase-1 holistic-audit gap (H1/H2/L2): before this, the only
producer of `expired` was a one-shot NULL backfill that bypassed
transition() — so calc:expired never fired live and window-lapsed calcs
lingered as candidates forever.

Pins core.handlers.sweep_expired_calcs:
- active calc past its window → expired + calc:expired event (carrying
  age_seconds/ticker/direction/model_name per spec §9).
- released calc past its window → expired (RELEASED→EXPIRED edge).
- in-window calc NOT expired.
- per-calc frozen window_seconds honored (a calc with a longer frozen
  window survives even when the account default would expire it).
- matched / terminal calcs not swept.
- clock_skew_tolerance padding respected at the boundary.
- TOCTOU: status flipped between read and UPDATE → no expire, no event.
- the periodic loop is registered in start_background_tasks.

Run: pytest tests/test_phase1_calc_expiry.py -v
"""
from __future__ import annotations

import inspect
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest_asyncio.fixture
async def wired(monkeypatch):
    from core.database import DatabaseManager
    from core import handlers
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


def _iso(age_sec: float) -> str:
    """Timestamp age_sec seconds in the past."""
    return (datetime.now(timezone.utc) - timedelta(seconds=age_sec)).isoformat()


async def _insert_calc(db, *, calc_id, status="active", age_sec=0.0,
                       window_seconds=None, ticker="BTCUSDT", side="long",
                       model_name="momentum"):
    await db._conn.execute(
        "INSERT INTO pre_trade_log "
        "(account_id, timestamp, ticker, side, effective_entry, tp_price, "
        " sl_price, average, calc_id, status, window_seconds, model_name) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, _iso(age_sec), ticker, side, 50000.0, 55000.0, 48000.0, 50000.0,
         calc_id, status, window_seconds, model_name),
    )
    await db._conn.commit()


async def _status(db, calc_id) -> Optional[str]:
    async with db._conn.execute(
        "SELECT status FROM pre_trade_log WHERE calc_id = ?", (calc_id,),
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


def _drain(channel: str | None = None) -> List[tuple]:
    from core.event_bus import event_bus
    evs = []
    while not event_bus._queue.empty():
        evs.append(event_bus._queue.get_nowait())
    # P6.T3: calc:* events ride engine:account:{id}:calc:{event}; match by the
    # calc:{event} suffix ONLY (no flat fallback → a flat-topic regression FAILS
    # the test, Rule 8). Full per-account topic asserted in test_state_machines.
    if not channel:
        return evs
    return [(c, p) for c, p in evs if c.endswith(":" + channel)]


# ── Core expiry ───────────────────────────────────────────────────────


class TestExpirySweep:
    @pytest.mark.asyncio
    async def test_lapsed_active_expired(self, wired):
        handlers, db = wired
        # 400s old, window 300 + skew 10 = 310 → lapsed
        await _insert_calc(db, calc_id="e-1", status="active", age_sec=400)
        _drain()

        n = await handlers.sweep_expired_calcs(1)
        assert n == 1
        assert await _status(db, "e-1") == "expired"

    @pytest.mark.asyncio
    async def test_calc_expired_event_fires(self, wired):
        """Spec §9 calc:expired carries age_seconds + ticker/direction/model_name."""
        handlers, db = wired
        await _insert_calc(db, calc_id="e-2", status="active", age_sec=500,
                           ticker="ETHUSDT", side="short", model_name="trend_v1")
        _drain()

        await handlers.sweep_expired_calcs(1)

        events = _drain("calc:expired")
        assert len(events) == 1
        _, p = events[0]
        assert p["calc_id"] == "e-2"
        assert p["from_status"] == "active"
        assert p["to_status"] == "expired"
        assert p["age_seconds"] >= 490
        assert p["ticker"] == "ETHUSDT"
        assert p["direction"] == "short"
        assert p["model_name"] == "trend_v1"

    @pytest.mark.asyncio
    async def test_in_window_not_expired(self, wired):
        handlers, db = wired
        # 100s old, window 300 + skew 10 = 310 → still in window
        await _insert_calc(db, calc_id="e-3", status="active", age_sec=100)
        _drain()

        n = await handlers.sweep_expired_calcs(1)
        assert n == 0
        assert await _status(db, "e-3") == "active"
        assert _drain("calc:expired") == []

    @pytest.mark.asyncio
    async def test_released_calc_expired(self, wired):
        """RELEASED → EXPIRED is a valid edge — a released calc that's
        never re-matched within its window expires too.
        """
        handlers, db = wired
        await _insert_calc(db, calc_id="e-4", status="released", age_sec=400)
        n = await handlers.sweep_expired_calcs(1)
        assert n == 1
        assert await _status(db, "e-4") == "expired"

    @pytest.mark.asyncio
    async def test_per_calc_frozen_window_honored(self, wired):
        """A calc with a longer FROZEN window survives past the account
        default. 400s old, but frozen window=900 (+10 skew=910) → not
        expired, even though the account default 300 would expire it.
        """
        handlers, db = wired
        await _insert_calc(db, calc_id="e-5", status="active", age_sec=400,
                           window_seconds=900)
        n = await handlers.sweep_expired_calcs(1)
        assert n == 0
        assert await _status(db, "e-5") == "active"

    @pytest.mark.asyncio
    async def test_clock_skew_padding_at_boundary(self, wired):
        """305s old: past window (300) but within window+skew (310) →
        NOT expired (matches the matcher's in-window gate exactly).
        """
        handlers, db = wired
        await _insert_calc(db, calc_id="e-6", status="active", age_sec=305)
        n = await handlers.sweep_expired_calcs(1)
        assert n == 0
        assert await _status(db, "e-6") == "active"


# ── Guards ────────────────────────────────────────────────────────────


class TestExpiryGuards:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [
        "matched", "superseded", "cancelled_by_operator",
        "completed_via_position", "expired",
    ])
    async def test_non_live_states_not_swept(self, wired, status):
        """Only active/released are swept. matched (working order),
        terminal states — all left alone even if old.
        """
        handlers, db = wired
        await _insert_calc(db, calc_id="g-1", status=status, age_sec=9999)
        _drain()
        n = await handlers.sweep_expired_calcs(1)
        assert n == 0
        assert await _status(db, "g-1") == status
        assert _drain("calc:expired") == []

    @pytest.mark.asyncio
    async def test_cross_account_not_swept(self, wired):
        handlers, db = wired
        await _insert_calc(db, calc_id="g-2", status="active", age_sec=400)
        # Sweep account 2 — account 1's calc untouched
        n = await handlers.sweep_expired_calcs(2)
        assert n == 0
        assert await _status(db, "g-2") == "active"

    @pytest.mark.asyncio
    async def test_multiple_lapsed_all_expired(self, wired):
        handlers, db = wired
        await _insert_calc(db, calc_id="m-1", status="active", age_sec=400)
        await _insert_calc(db, calc_id="m-2", status="released", age_sec=500)
        await _insert_calc(db, calc_id="m-3", status="active", age_sec=100)  # in window
        _drain()
        n = await handlers.sweep_expired_calcs(1)
        assert n == 2
        assert await _status(db, "m-1") == "expired"
        assert await _status(db, "m-2") == "expired"
        assert await _status(db, "m-3") == "active"  # in window, survives


# ── TOCTOU ────────────────────────────────────────────────────────────


class TestExpiryRace:
    @pytest.mark.asyncio
    async def test_concurrent_flip_skips_expire(self, wired, monkeypatch):
        handlers, db = wired
        await _insert_calc(db, calc_id="r-1", status="active", age_sec=400)
        _drain()

        from core import calc_state
        original = calc_state.transition

        async def racing(calc_id, current_status, target_status, *, apply_fn, **kw):
            # Concurrent match flips active→matched before apply_fn runs.
            await db._conn.execute(
                "UPDATE pre_trade_log SET status='matched' WHERE calc_id=?",
                (calc_id,),
            )
            await db._conn.commit()
            await original(calc_id, current_status, target_status, apply_fn=apply_fn, **kw)

        monkeypatch.setattr("core.calc_state.transition", racing)

        n = await handlers.sweep_expired_calcs(1)
        assert n == 0  # lost the race
        assert await _status(db, "r-1") == "matched"  # racing flip won
        assert _drain("calc:expired") == []


# ── Scheduler wiring ──────────────────────────────────────────────────


class TestSchedulerWiring:
    def test_expiry_loop_registered(self):
        """The periodic _calc_expiry_loop must be spawned by
        start_background_tasks — else the sweeper never runs in prod.
        """
        from core import schedulers
        src = inspect.getsource(schedulers.start_background_tasks)
        assert "_calc_expiry_loop" in src, (
            "calc-expiry sweeper not registered in start_background_tasks — "
            "the live expiry mechanism would never run."
        )

    def test_expiry_loop_calls_sweep(self):
        from core import schedulers
        src = inspect.getsource(schedulers._calc_expiry_loop)
        assert "sweep_expired_calcs" in src
