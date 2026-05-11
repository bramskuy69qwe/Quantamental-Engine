"""
SR-4 Step 2 regression tests — SR-6a adapter method wiring.

Validates:
1. Protocol has fetch_orderbook, fetch_mark_price, fetch_server_time
2. Both adapters implement all 3 methods
3. exchange_market.py no longer references get_exchange or _REST_POOL
4. exchange_income.py no longer references get_exchange or _REST_POOL
5. ws_manager.py no longer imports _REST_POOL

Run: pytest tests/test_sr4_step2_adapter_methods.py -v
"""
from __future__ import annotations
from pathlib import Path

import pytest


# ── Protocol method existence ────────────────────────────────────────────────

class TestProtocolMethods:
    def test_fetch_orderbook_on_protocol(self):
        import inspect
        from core.adapters.protocols import ExchangeAdapter
        source = inspect.getsource(ExchangeAdapter)
        assert "fetch_orderbook" in source

    def test_fetch_mark_price_on_protocol(self):
        import inspect
        from core.adapters.protocols import ExchangeAdapter
        source = inspect.getsource(ExchangeAdapter)
        assert "fetch_mark_price" in source

    def test_fetch_server_time_on_protocol(self):
        import inspect
        from core.adapters.protocols import ExchangeAdapter
        source = inspect.getsource(ExchangeAdapter)
        assert "fetch_server_time" in source


# ── Adapter implementations ─────────────────────────────────────────────────

class TestAdapterImplementations:
    def test_binance_has_fetch_orderbook(self):
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
        assert hasattr(BinanceUSDMAdapter, "fetch_orderbook")

    def test_binance_has_fetch_mark_price(self):
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
        assert hasattr(BinanceUSDMAdapter, "fetch_mark_price")

    def test_binance_has_fetch_server_time(self):
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
        assert hasattr(BinanceUSDMAdapter, "fetch_server_time")

    def test_bybit_has_fetch_orderbook(self):
        from core.adapters.bybit.rest_adapter import BybitLinearAdapter
        assert hasattr(BybitLinearAdapter, "fetch_orderbook")

    def test_bybit_has_fetch_mark_price(self):
        from core.adapters.bybit.rest_adapter import BybitLinearAdapter
        assert hasattr(BybitLinearAdapter, "fetch_mark_price")

    def test_bybit_has_fetch_server_time(self):
        from core.adapters.bybit.rest_adapter import BybitLinearAdapter
        assert hasattr(BybitLinearAdapter, "fetch_server_time")


# ── Dead import verification ─────────────────────────────────────────────────

class TestDeadImportsRemoved:
    def test_exchange_market_no_get_exchange(self):
        src = Path(__file__).parent.parent / "core" / "exchange_market.py"
        content = src.read_text()
        assert "get_exchange" not in content, \
            "exchange_market.py must not reference get_exchange"

    def test_exchange_market_no_rest_pool(self):
        src = Path(__file__).parent.parent / "core" / "exchange_market.py"
        content = src.read_text()
        assert "_REST_POOL" not in content, \
            "exchange_market.py must not reference _REST_POOL"

    def test_exchange_income_no_get_exchange(self):
        src = Path(__file__).parent.parent / "core" / "exchange_income.py"
        content = src.read_text()
        assert "get_exchange" not in content, \
            "exchange_income.py must not reference get_exchange"

    def test_exchange_income_no_rest_pool(self):
        src = Path(__file__).parent.parent / "core" / "exchange_income.py"
        content = src.read_text()
        assert "_REST_POOL" not in content, \
            "exchange_income.py must not reference _REST_POOL"

    def test_ws_manager_no_rest_pool(self):
        src = Path(__file__).parent.parent / "core" / "ws_manager.py"
        content = src.read_text()
        assert "_REST_POOL" not in content, \
            "ws_manager.py must not reference _REST_POOL"

    def test_ws_manager_no_get_exchange(self):
        src = Path(__file__).parent.parent / "core" / "ws_manager.py"
        content = src.read_text()
        assert "get_exchange" not in content, \
            "ws_manager.py must not reference get_exchange"
