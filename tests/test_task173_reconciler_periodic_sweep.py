"""
Task 173 regression tests — periodic closed_positions MFE/MAE backfill sweep.

Bug context: ReconcilerWorker._reconcile_closed_positions only ran at engine
startup (after backfill_all) and per-position on risk:position_closed events.
If fetch_hl_for_trade returned None (illiquid symbol, sparse kline coverage,
sub-1m trade with no kline bucket) or the startup sweep aborted on rate-limit
mid-loop, those rows stayed backfill_completed=0 indefinitely and rendered as
"—" in Position History's MFE/MAE columns.

Repro: 10 closed_positions rows stuck at backfill_completed=0 (7 BSBUSDT, 2
TRXUSDT, 1 NAORISUSDT) — all from 2026-05-19/20 cluster, persisting across
engine restarts because the startup sweep keeps failing on the same symbols
without a retry mechanism.

Fix: add _reconcile_closed_positions_periodic loop in core/schedulers.py that
calls reconciler._reconcile_closed_positions every interval_s (default 900s
= 15 min). Spawned from _startup_fetch alongside the existing
reconciler_backfill task.

These tests:
  1. Source-grep pin: function exists in schedulers.py and is spawned in
     _startup_fetch.
  2. Behavioral test: the loop actually calls
     reconciler._reconcile_closed_positions when its sleep elapses, and
     keeps looping (one tick → another tick → ...).
  3. Behavioral test: exceptions in _reconcile_closed_positions are caught
     so a transient failure doesn't kill the loop.

Run: pytest tests/test_task173_reconciler_periodic_sweep.py -v
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


SRC_SCHED = Path(__file__).parent.parent / "core" / "schedulers.py"


# ── Source-grep pins ─────────────────────────────────────────────────────────


class TestSourceGrepPins:
    def test_periodic_loop_function_exists(self):
        """_reconcile_closed_positions_periodic must be defined in schedulers."""
        content = SRC_SCHED.read_text()
        assert "_reconcile_closed_positions_periodic" in content, (
            "schedulers.py must define _reconcile_closed_positions_periodic to "
            "retry MFE/MAE backfill for stuck rows"
        )

    def test_periodic_loop_is_spawned_in_startup_fetch(self):
        """Loop must be spawned via _spawn() inside _startup_fetch so it runs
        for the lifetime of the engine."""
        content = SRC_SCHED.read_text()
        # The spawn call site is the relevant assertion.
        assert "_spawn(\n            _reconcile_closed_positions_periodic" in content \
            or "_spawn(_reconcile_closed_positions_periodic" in content, (
            "_reconcile_closed_positions_periodic must be spawned in _startup_fetch"
        )

    def test_periodic_loop_calls_reconcile_method(self):
        """The loop body must call reconciler._reconcile_closed_positions."""
        content = SRC_SCHED.read_text()
        idx = content.find("async def _reconcile_closed_positions_periodic")
        assert idx > 0, "function must exist"
        body = content[idx:idx + 2000]
        assert "_reconcile_closed_positions" in body, (
            "Loop must call reconciler._reconcile_closed_positions"
        )
        assert "asyncio.sleep" in body, (
            "Loop must sleep between sweeps"
        )

    def test_periodic_loop_handles_exceptions(self):
        """The loop must catch exceptions so one failure doesn't kill it."""
        content = SRC_SCHED.read_text()
        idx = content.find("async def _reconcile_closed_positions_periodic")
        body = content[idx:idx + 2000]
        assert "except" in body, (
            "Loop must catch exceptions so transient failures don't kill it"
        )


# ── Behavioral tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_periodic_loop_calls_reconcile_repeatedly():
    """Loop body fires _reconcile_closed_positions on each sleep cycle.

    Uses interval_s=0.01 (10ms) and cancels after a few ticks to assert
    the method was awaited multiple times.
    """
    from core.schedulers import _reconcile_closed_positions_periodic

    reconciler = MagicMock()
    reconciler._reconcile_closed_positions = AsyncMock()

    task = asyncio.create_task(
        _reconcile_closed_positions_periodic(reconciler, interval_s=0.01)
    )
    # Let it tick a few times.
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert reconciler._reconcile_closed_positions.await_count >= 2, (
        f"Expected loop to tick at least twice, got "
        f"{reconciler._reconcile_closed_positions.await_count}"
    )


@pytest.mark.asyncio
async def test_periodic_loop_survives_reconcile_exception():
    """A single _reconcile_closed_positions failure must not kill the loop.

    Simulates one tick raising, then assert subsequent ticks still fire.
    """
    from core.schedulers import _reconcile_closed_positions_periodic

    call_count = {"n": 0}

    async def flaky_reconcile():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated transient failure")

    reconciler = MagicMock()
    reconciler._reconcile_closed_positions = flaky_reconcile

    task = asyncio.create_task(
        _reconcile_closed_positions_periodic(reconciler, interval_s=0.01)
    )
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert call_count["n"] >= 2, (
        f"Loop must survive a single exception and continue ticking; "
        f"got call_count={call_count['n']}"
    )


@pytest.mark.asyncio
async def test_periodic_loop_exits_on_cancel():
    """asyncio.CancelledError must propagate out of the loop cleanly."""
    from core.schedulers import _reconcile_closed_positions_periodic

    reconciler = MagicMock()
    reconciler._reconcile_closed_positions = AsyncMock()

    task = asyncio.create_task(
        _reconcile_closed_positions_periodic(reconciler, interval_s=1.0)
    )
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
