"""
RL-4: Trade-event burst serialization — semaphore + rate-limit guards.
Verifies that concurrent burst callers are serialized and skipped when
rate-limited.
"""
import asyncio
import os
import sys
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timezone, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Semaphore exists ─────────────────────────────────────────────────────────

def test_trade_event_semaphore_exists():
    """Shared trade-event semaphore is defined in exchange module."""
    from core.exchange import trade_event_sem
    assert isinstance(trade_event_sem, asyncio.Semaphore)


def test_trade_event_semaphore_size():
    """Semaphore allows 2 concurrent callers (per Phase 2 design)."""
    from core.exchange import trade_event_sem
    # Semaphore(2) starts with _value=2
    assert trade_event_sem._value == 2


# ── Rate-limit guard presence ────────────────────────────────────────────────

def test_on_trade_closed_has_rate_limit_guard():
    """reconciler.on_trade_closed checks is_rate_limited."""
    import inspect
    from core.reconciler import ReconcilerWorker
    src = inspect.getsource(ReconcilerWorker.on_trade_closed)
    assert "is_rate_limited" in src

def test_refresh_positions_has_rate_limit_guard():
    """ws_manager._refresh_positions_after_fill checks is_rate_limited."""
    import inspect
    from core.ws_manager import _refresh_positions_after_fill
    src = inspect.getsource(_refresh_positions_after_fill)
    assert "is_rate_limited" in src

def test_on_new_position_has_rate_limit_guard():
    """ws_manager._on_new_position checks is_rate_limited."""
    import inspect
    from core.ws_manager import _on_new_position
    src = inspect.getsource(_on_new_position)
    assert "is_rate_limited" in src


# ── Semaphore presence ───────────────────────────────────────────────────────

def test_on_trade_closed_uses_semaphore():
    """reconciler.on_trade_closed acquires trade_event_sem."""
    import inspect
    from core.reconciler import ReconcilerWorker
    src = inspect.getsource(ReconcilerWorker.on_trade_closed)
    assert "trade_event_sem" in src

def test_refresh_positions_uses_semaphore():
    """ws_manager._refresh_positions_after_fill acquires trade_event_sem."""
    import inspect
    from core.ws_manager import _refresh_positions_after_fill
    src = inspect.getsource(_refresh_positions_after_fill)
    assert "trade_event_sem" in src

def test_on_new_position_uses_semaphore():
    """ws_manager._on_new_position acquires trade_event_sem."""
    import inspect
    from core.ws_manager import _on_new_position
    src = inspect.getsource(_on_new_position)
    assert "trade_event_sem" in src


# ── Concurrency limiting ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_semaphore_limits_concurrency():
    """Semaphore(2) allows max 2 concurrent tasks, queues the rest."""
    sem = asyncio.Semaphore(2)
    running = []
    max_concurrent = [0]

    async def worker(id):
        async with sem:
            running.append(id)
            max_concurrent[0] = max(max_concurrent[0], len(running))
            await asyncio.sleep(0.05)
            running.remove(id)

    # Fire 6 workers simultaneously (simulates burst)
    await asyncio.gather(*[worker(i) for i in range(6)])

    assert max_concurrent[0] == 2, f"Expected max 2 concurrent, got {max_concurrent[0]}"
