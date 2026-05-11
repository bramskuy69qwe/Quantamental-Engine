"""
SR-4 Step 3 regression tests — singleton + pool removal.

Validates:
1. get_exchange, _make_exchange, _exchange, _REST_POOL removed from exchange.py
2. import ccxt removed from exchange.py (if no remaining usage)
3. Remaining facade functions still work (_get_adapter, handle_rate_limit_error,
   fetch_account, fetch_positions, create_listen_key, keepalive_listen_key)

Run: pytest tests/test_sr4_step3_singleton_removal.py -v
"""
from __future__ import annotations
from pathlib import Path

import pytest


SRC = Path(__file__).parent.parent / "core" / "exchange.py"


class TestSingletonRemoved:
    def test_no_get_exchange_function(self):
        content = SRC.read_text()
        # Should not contain the function definition
        assert "\ndef get_exchange(" not in content, \
            "get_exchange() function must be deleted from exchange.py"

    def test_no_make_exchange_function(self):
        content = SRC.read_text()
        assert "def _make_exchange(" not in content, \
            "_make_exchange() function must be deleted from exchange.py"

    def test_no_exchange_singleton(self):
        import core.exchange as ex
        assert not hasattr(ex, "_exchange"), \
            "_exchange singleton variable must be deleted"

    def test_no_rest_pool(self):
        import core.exchange as ex
        assert not hasattr(ex, "_REST_POOL"), \
            "_REST_POOL must be deleted from exchange.py"

    def test_no_ccxt_import(self):
        """exchange.py should not import ccxt directly after singleton removal."""
        content = SRC.read_text()
        assert "\nimport ccxt\n" not in content, \
            "exchange.py must not import ccxt after singleton removal"

    def test_no_thread_pool_import(self):
        content = SRC.read_text()
        assert "ThreadPoolExecutor" not in content, \
            "ThreadPoolExecutor import must be removed"


class TestFacadeStillWorks:
    def test_get_adapter_exists(self):
        import core.exchange as ex
        assert hasattr(ex, "_get_adapter")

    def test_handle_rate_limit_error_exists(self):
        import core.exchange as ex
        assert callable(ex.handle_rate_limit_error)

    def test_fetch_account_exists(self):
        import core.exchange as ex
        assert callable(ex.fetch_account)

    def test_fetch_positions_exists(self):
        import core.exchange as ex
        assert callable(ex.fetch_positions)

    def test_create_listen_key_exists(self):
        import core.exchange as ex
        assert callable(ex.create_listen_key)

    def test_keepalive_listen_key_exists(self):
        import core.exchange as ex
        assert callable(ex.keepalive_listen_key)

    def test_reexports_still_work(self):
        """Re-exported functions from exchange_market/exchange_income must still be importable."""
        from core.exchange import fetch_ohlcv, fetch_hl_for_trade, calc_mfe_mae
        from core.exchange import fetch_orderbook, fetch_mark_price
        from core.exchange import fetch_income_history, fetch_exchange_trade_history
        assert callable(fetch_ohlcv)
        assert callable(fetch_hl_for_trade)
