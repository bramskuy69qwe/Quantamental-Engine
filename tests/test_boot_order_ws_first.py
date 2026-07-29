"""E2E-P6-004 pins — the user-data stream must bind BEFORE the boot backfills.

INCIDENT (live, 2026-07-29): four engine boots in eight minutes each logged

    WS startup failed: Weight budget exceeded (106% … 117%, priority=urgent)

and the stream needed up to THREE retries (~2 min) to bind. Root cause is
ordering, not priority: `_startup_fetch` acquired the listen key LAST — after
BOD/SOW equity, the full exchange trade history, a 90-day offline recovery, and
one OHLCV fetch PER OPEN POSITION. The engine spent its own weight budget and
then asked for the single most important call it makes. Raising the priority
(E2E-P5-001) decides who wins a CONTENDED budget; it cannot help once the budget
is already over 100 %.

Fix: bind the stream immediately after the essential account/position state and
before the historical work.

Ordering constraints pinned here (both are correctness-relevant):
  * AFTER fetch_positions — `_create_fill_from_ws` resolves
    terminal_position_id from app_state.positions (ws_manager.py:438-442), so an
    early fill would otherwise carry an empty tpid and break linkage;
  * BEFORE fetch_exchange_trade_history / recover_offline_trades / fetch_ohlcv —
    deferrable, idempotent work that can absorb throttling instead.
"""
import inspect

import core.schedulers as sched


SRC = inspect.getsource(sched._startup_fetch)


def _pos(needle: str) -> int:
    i = SRC.find(needle)
    assert i >= 0, f"boot sequence no longer contains {needle!r} — re-verify this pin"
    return i


class TestListenKeyBindsEarly:
    def test_stream_start_is_extracted_to_one_helper(self):
        assert hasattr(sched, "_start_user_data_stream")
        helper = inspect.getsource(sched._start_user_data_stream)
        assert "create_listen_key" in helper and "ws_manager.start" in helper
        assert "_ws_startup_retry_loop" in helper, "a boot failure must never be terminal"

    def test_boot_calls_the_helper_exactly_once(self):
        assert SRC.count("_start_user_data_stream()") == 1

    def test_stream_starts_AFTER_positions_are_loaded(self):
        """Early fills need app_state.positions to resolve terminal_position_id."""
        assert _pos("fetch_positions") < _pos("_start_user_data_stream()"), (
            "binding before positions load would leave early fills with an empty tpid"
        )

    def test_stream_starts_BEFORE_the_expensive_backfills(self):
        start = _pos("_start_user_data_stream()")
        for later in (
            "fetch_bod_sow_equity",
            "fetch_exchange_trade_history",
            "recover_offline_trades",
            "fetch_ohlcv",
        ):
            assert start < _pos(later), (
                f"{later} must not precede the listen key — it spends the same weight "
                "budget the stream then needs (live: 106%→117% rejections)"
            )

    def test_raw_listen_key_call_no_longer_sits_at_the_tail(self):
        """The old inline block is gone; only the helper owns the call."""
        assert "create_listen_key()" not in SRC, "boot must go through _start_user_data_stream"


class TestRetryContractIntact:
    def test_retry_loop_still_exists_and_is_tick_scoped(self):
        loop = inspect.getsource(sched._ws_startup_retry_loop)
        assert "correlation_log.tick(" in loop, "spawned loops mint a per-iteration scope"
        assert "ws_manager.stop" in loop and "ws_manager.start" in loop
        assert "ws_status.connected" in loop, "must exit once the stream is up"
