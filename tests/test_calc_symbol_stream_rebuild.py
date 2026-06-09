"""
Follow-up #4 (debug 2026-06-08): calculator ticker-switch WS subscription leak.

Changing the calculator symbol updates `_calculator_symbol` (which feeds
`_build_market_streams`), but the market WS was only ever rebuilt on POSITION
symbol changes — so the OLD calculator symbol's depth/ticker kept streaming and
repopulating its caches. Operator symptom: switching VELVETUSDT → BSBUSDT left
BOTH symbols' prices + orderbooks live, and the cmd kept "subscribing to
velvetusdt ticker".

Fix: `set_calculator_symbol` schedules `restart_market_streams()` when the symbol
actually changes (gated so the 1 Hz /api/price poll for the same symbol doesn't
thrash the WS), with a no-running-loop guard for sync/test/startup callers.

Intent (Rule 8):
  - an ACTUAL symbol change schedules a stream rebuild;
  - the SAME symbol does NOT (no WS thrash on the repeated price poll);
  - the old symbol's orderbook cache is evicted on change;
  - no running loop → no crash (sync / pre-startup path).

Run: pytest tests/test_calc_symbol_stream_rebuild.py -v
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.mark.asyncio
async def test_change_schedules_restart(monkeypatch):
    import core.ws_manager as wm
    called = []

    async def fake_restart():
        called.append(True)

    monkeypatch.setattr(wm, "restart_market_streams", fake_restart)
    monkeypatch.setattr(wm, "_calculator_symbol", "VELVETUSDT")
    wm.set_calculator_symbol("BSBUSDT")
    await asyncio.sleep(0)            # let the scheduled task run
    assert called == [True]
    assert wm._calculator_symbol == "BSBUSDT"


@pytest.mark.asyncio
async def test_same_symbol_no_restart(monkeypatch):
    import core.ws_manager as wm
    called = []

    async def fake_restart():
        called.append(True)

    monkeypatch.setattr(wm, "restart_market_streams", fake_restart)
    monkeypatch.setattr(wm, "_calculator_symbol", "BSBUSDT")
    wm.set_calculator_symbol("bsbusdt")   # same after .upper() — no rebuild
    await asyncio.sleep(0)
    assert called == []


@pytest.mark.asyncio
async def test_old_orderbook_evicted_on_change(monkeypatch):
    import core.ws_manager as wm
    from core.state import app_state

    async def fake_restart():
        pass

    monkeypatch.setattr(wm, "restart_market_streams", fake_restart)
    monkeypatch.setattr(wm, "_calculator_symbol", "VELVETUSDT")
    app_state.orderbook_cache["VELVETUSDT"] = {"bids": [[1, 1]], "asks": [[2, 1]]}
    try:
        wm.set_calculator_symbol("BSBUSDT")
        await asyncio.sleep(0)
        assert "VELVETUSDT" not in app_state.orderbook_cache
    finally:
        app_state.orderbook_cache.pop("VELVETUSDT", None)
        app_state.orderbook_cache.pop("BSBUSDT", None)


def test_no_running_loop_no_crash(monkeypatch):
    # Sync caller / pre-startup: no running loop → guard returns cleanly, the
    # symbol is still set (the next restart_market_streams applies it).
    import core.ws_manager as wm
    monkeypatch.setattr(wm, "_calculator_symbol", "AAAUSDT")
    monkeypatch.setattr(wm, "restart_market_streams",
                        lambda: pytest.fail("must not be called without a loop"))
    wm.set_calculator_symbol("BBBUSDT")
    assert wm._calculator_symbol == "BBBUSDT"


def test_clear_to_none_schedules_restart_via_caller(monkeypatch):
    # Clearing (symbol="") sets None; with no loop this is the sync path and must
    # not crash. (Clear-then-reselect is the operator's "click clear first" flow.)
    import core.ws_manager as wm
    monkeypatch.setattr(wm, "_calculator_symbol", "BBBUSDT")
    monkeypatch.setattr(wm, "restart_market_streams", lambda: None)
    wm.set_calculator_symbol("")
    assert wm._calculator_symbol is None
