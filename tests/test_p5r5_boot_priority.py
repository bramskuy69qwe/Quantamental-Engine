"""P5-R5 pins — post-restart weight saturation must not starve Pre-Trade.

Filed (phase-5 ledger): every Pre-Trade pane rendered "Weight budget
exceeded (95%, priority=normal)" for minutes after a restart; /api/price
returned no price and Calculate refused to size. Investigated mechanism —
two compounding causes, both fixed WITHOUT touching the priority table
(the listen key's exclusive 95-101% band is the E2E-P5-001 guarantee and
must stay listen-key-only):

1. CACHE EVICTION DEFEATED THE CACHES: evict_symbol_caches runs from
   fetch_positions on every accepted REST snapshot (~30 s) and a Pre-Trade
   calc ticker is by definition not yet a position — its ohlcv/orderbook/
   mark caches were wiped on a 30 s cycle, forcing the interactive doors
   down the REST path exactly while the boot burst shed normal-tier calls.
   Fix: the calculator symbol is exempt.
2. THE HEAVY BOOT BACKFILLS RAN UNTIERED (normal): fetch_exchange_trade_
   history (3 windowed income sweeps + per-symbol userTrades),
   fetch_bod_sow_equity, and the boot OHLCV sweep now run background —
   they self-shed at 70% instead of contending with interactive calls at
   95%, and all three are re-run by the 300 s history refresh loop.
   Companion: _account_refresh_loop's urgent covered only the order
   snapshot by intent but leaked into the per-position fill sync via the
   sticky adapter priority — restored to normal before the sync.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(*parts):
    with open(os.path.join(_ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


class TestCalculatorCacheExemption:
    def test_calc_symbol_survives_eviction(self, monkeypatch):
        import core.ws_manager as wsm
        from core.data_cache import DataCache
        from core.event_bus import EventBus
        from core.state import app_state

        monkeypatch.setattr(wsm, "_calculator_symbol", "NEWUSDT")
        monkeypatch.setattr(app_state, "ohlcv_cache",
                            {"NEWUSDT": [1], "GONEUSDT": [2]})
        monkeypatch.setattr(app_state, "orderbook_cache",
                            {"NEWUSDT": {"bids": []}, "GONEUSDT": {"bids": []}})
        monkeypatch.setattr(app_state, "mark_price_cache",
                            {"NEWUSDT": 1.0, "GONEUSDT": 2.0})
        monkeypatch.setattr(app_state, "mark_price_timestamps", {})

        DataCache(EventBus()).evict_symbol_caches(active_tickers=set())

        assert "NEWUSDT" in app_state.ohlcv_cache, (
            "P5-R5 regressed: the 30 s eviction cycle wipes the calculator "
            "symbol's caches and forces the interactive doors onto REST"
        )
        assert "NEWUSDT" in app_state.orderbook_cache
        assert "NEWUSDT" in app_state.mark_price_cache
        assert "GONEUSDT" not in app_state.ohlcv_cache
        assert "GONEUSDT" not in app_state.orderbook_cache

    def test_no_calc_symbol_evicts_normally(self, monkeypatch):
        import core.ws_manager as wsm
        from core.data_cache import DataCache
        from core.event_bus import EventBus
        from core.state import app_state

        monkeypatch.setattr(wsm, "_calculator_symbol", None)
        monkeypatch.setattr(app_state, "ohlcv_cache", {"GONEUSDT": [2]})
        monkeypatch.setattr(app_state, "orderbook_cache", {})
        monkeypatch.setattr(app_state, "mark_price_cache", {})
        monkeypatch.setattr(app_state, "mark_price_timestamps", {})
        DataCache(EventBus()).evict_symbol_caches(active_tickers=set())
        assert app_state.ohlcv_cache == {}


class TestBootBackfillTiering:
    def test_trade_history_is_background_with_restore(self):
        src = _src("core", "exchange_income.py")
        body = src.split("async def fetch_exchange_trade_history")[1] \
                  .split("async def fetch_all_user_trades")[0]
        assert 'set_priority("background")' in body
        assert 'set_priority("normal")' in body

    def test_bod_sow_is_background_with_restore(self):
        src = _src("core", "exchange_income.py")
        body = src.split("async def fetch_bod_sow_equity")[1] \
                  .split("async def fetch_income_for_backfill")[0]
        assert 'set_priority("background")' in body
        assert 'set_priority("normal")' in body

    def test_boot_ohlcv_sweep_is_background(self):
        src = _src("core", "schedulers.py")
        i = src.index("boot OHLCV sweep")
        blk = src[i - 400:i + 900]
        assert 'set_priority("background")' in blk
        assert 'set_priority("normal")' in blk

    def test_fill_sync_no_longer_inherits_urgent(self):
        # The urgent set for the order snapshot must be restored to normal
        # BEFORE the per-position fill sync (which otherwise spends the
        # listen key's reserved band every 30 s).
        src = _src("core", "schedulers.py")
        loop = src.split("async def _account_refresh_loop")[1] \
                  .split("\nasync def ")[0]
        i_urgent = loop.index('set_priority("urgent")  # WS fallback order sync')
        i_sync = loop.index("Also sync fills for open position symbols")
        between = loop[i_urgent:i_sync]
        assert 'set_priority("normal")' in between, (
            "P5-R5 companion regressed: the fill sync inherits urgent via "
            "the sticky adapter priority"
        )

    def test_interactive_ohlcv_stays_untiered(self):
        # The module-level wrapper serves routes_calculator's interactive
        # fetch — it must NOT be background-tiered.
        src = _src("core", "exchange_market.py")
        body = src.split("async def fetch_ohlcv")[1].split("\nasync def ")[0]
        assert "set_priority" not in body
