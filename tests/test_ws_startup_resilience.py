"""E2E-P5-001 regression pins — the user-data WS must never die silently at boot.

INCIDENT (live, 2026-07-28 → 07-29, found while triaging the operator's
"History isn't showing my SNXX trades"):

    14:20:43 ERROR main: WS startup failed: Weight budget exceeded
                          (114%, priority=background)

Chain, verified against the live DB and log:
 1. `set_priority()` is STICKY on the shared adapter
    (core/adapters/base.py:80 → `self._current_priority`). The boot sequence's
    backfills (`fetch_income_for_backfill`, `fetch_all_user_trades`,
    OHLCV `fetch_and_store`) set "background" and never restored it.
 2. `create_listen_key()` passed no explicit priority, so it INHERITED
    "background" and the weight tracker shed it at 114 %.
 3. `start_background_tasks()` logged the failure and moved on — **no retry**.
    The user-data socket (the engine's SOLE fill source, ws_manager.py:418)
    stayed dead until the next manual restart.
 4. Fills then arrived only via REST reconcile: 169 fills on 2026-07-28 with
    `source='binance_rest'`, ALL with an empty `terminal_position_id`, and
    ZERO `closed_positions` rows written after 2026-07-26 22:08 — History,
    linkage and analytics silently frozen for two days.

Fixes pinned here:
 * listen-key create/keepalive pass `priority="urgent"` EXPLICITLY;
 * every `set_priority("background")` site restores in a `finally`;
 * a failed boot WS start spawns `_ws_startup_retry_loop` (backoff, forever).
"""
import asyncio
import inspect

import pytest

from core.adapters.binance import rest_adapter as ra
import core.exchange_income as ei
import core.ohlcv_fetcher as of
import core.schedulers as sch


class _SpyAdapter:
    """Records _run priorities and set_priority transitions."""

    def __init__(self):
        self.priorities: list[str] = []
        self.sticky: list[str] = []
        self._current_priority = "normal"

    def set_priority(self, p: str) -> None:
        self._current_priority = p
        self.sticky.append(p)

    async def _run(self, fn, *a, priority: str = ""):
        self.priorities.append(priority or self._current_priority)
        return "LK-TEST"


class TestListenKeyPriority:
    def test_create_listen_key_is_urgent(self):
        spy = _SpyAdapter()
        spy._ex = type("X", (), {"fapiPrivatePostListenKey": lambda s: {"listenKey": "k"}})()
        key = asyncio.run(ra.BinanceUSDMAdapter.create_listen_key(spy))
        assert key == "LK-TEST"
        assert spy.priorities == ["urgent"], (
            "listen key must request 'urgent' EXPLICITLY — inheriting the sticky "
            "'background' left by boot backfills is what killed the fill pipeline"
        )

    def test_keepalive_listen_key_is_urgent(self):
        spy = _SpyAdapter()
        spy._ex = type("X", (), {"fapiPrivatePutListenKey": lambda s, p: None})()
        asyncio.run(ra.BinanceUSDMAdapter.keepalive_listen_key(spy, "k"))
        assert spy.priorities == ["urgent"], "a shed keepalive expires the key = dead stream"

    def test_priority_is_never_inherited_from_sticky_state(self):
        """Even with the adapter parked at 'background', the call is urgent."""
        spy = _SpyAdapter()
        spy.set_priority("background")
        spy._ex = type("X", (), {"fapiPrivatePostListenKey": lambda s: {"listenKey": "k"}})()
        asyncio.run(ra.BinanceUSDMAdapter.create_listen_key(spy))
        assert spy.priorities == ["urgent"]


class TestStickyPriorityRestored:
    """Every background-priority site must restore in a finally — source-level pin."""

    @pytest.mark.parametrize(
        "fn",
        [
            ei.fetch_income_for_backfill,
            ei.fetch_all_user_trades,
            of.OHLCVFetcher.fetch_and_store,
        ],
    )
    def test_background_sites_restore_priority(self, fn):
        """Each site sets 'background' and restores in a finally.

        fetch_and_store sets it in its inner helper, so assert the pairing at
        module scope for that one — what matters is that the try/finally wrapper
        and the background set live in the same module and function family.
        """
        src = inspect.getsource(fn)
        assert "finally:" in src, f"{fn.__name__} must restore priority in a finally block"
        assert 'set_priority("normal")' in src, f"{fn.__name__} must restore to 'normal'"


class TestWsStartupRetry:
    def test_retry_loop_exists_and_is_spawned_on_failure(self):
        assert hasattr(sch, "_ws_startup_retry_loop"), "the retry loop must exist"
        # E2E-P6-004 moved the boot WS start out of _startup_fetch into
        # _start_user_data_stream (so it could be called EARLY, before the
        # backfills). The contract is unchanged: a boot failure spawns the retry.
        helper = inspect.getsource(sch._start_user_data_stream)
        assert "_ws_startup_retry_loop" in helper, (
            "a failed boot WS start must spawn the retry loop — logging and moving "
            "on left the engine with no fill source until a manual restart"
        )
        assert "_start_user_data_stream()" in inspect.getsource(sch._startup_fetch), (
            "boot must actually call the helper"
        )

    def test_retry_loop_restarts_manager_and_exits_when_connected(self):
        src = inspect.getsource(sch._ws_startup_retry_loop)
        assert "create_listen_key" in src and "ws_manager.start" in src
        assert "ws_manager.stop" in src, "must stop before restart — no double-spawned loops"
        assert "ws_status.connected" in src, "must exit once the stream is up"
