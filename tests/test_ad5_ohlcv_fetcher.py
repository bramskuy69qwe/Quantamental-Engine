"""
AD-5 regression tests — ohlcv_fetcher adapter migration.

Validates:
1. No direct ccxt.async_support or aiohttp usage
2. Constructor accepts adapter parameter
3. Exception types are neutral (no ccxt error types)
4. Retry logic preserved
5. No custom session management

Run: pytest tests/test_ad5_ohlcv_fetcher.py -v
"""
from __future__ import annotations
from pathlib import Path

import pytest


SRC = Path(__file__).parent.parent / "core" / "ohlcv_fetcher.py"


class TestDirectCcxtRemoved:
    def test_no_ccxt_async_support(self):
        content = SRC.read_text()
        assert "ccxt.async_support" not in content, \
            "ohlcv_fetcher must not import ccxt.async_support"

    def test_no_aiohttp_import(self):
        content = SRC.read_text()
        assert "import aiohttp" not in content, \
            "ohlcv_fetcher must not import aiohttp"

    def test_no_threaded_resolver(self):
        content = SRC.read_text()
        assert "ThreadedResolver" not in content, \
            "ThreadedResolver workaround must be deleted"

    def test_no_get_exchange_method(self):
        content = SRC.read_text()
        assert "def _get_exchange(" not in content, \
            "_get_exchange() must be deleted"

    def test_no_own_session(self):
        content = SRC.read_text()
        assert "own_session" not in content, \
            "own_session pattern must be deleted"


class TestAdapterInjection:
    def test_constructor_accepts_adapter(self):
        from core.ohlcv_fetcher import OHLCVFetcher
        from unittest.mock import MagicMock
        adapter = MagicMock()
        fetcher = OHLCVFetcher(adapter=adapter)
        assert fetcher._adapter is adapter

    def test_constructor_without_adapter(self):
        """OHLCVFetcher without adapter should not crash on init."""
        from core.ohlcv_fetcher import OHLCVFetcher
        fetcher = OHLCVFetcher()
        assert fetcher._adapter is None


class TestNeutralExceptions:
    def test_no_ccxt_network_error(self):
        content = SRC.read_text()
        assert "ccxt.NetworkError" not in content, \
            "Must use AdapterConnectionError, not ccxt.NetworkError"

    def test_no_ccxt_bad_symbol(self):
        content = SRC.read_text()
        assert "ccxt.BadSymbol" not in content, \
            "Must use neutral error type, not ccxt.BadSymbol"

    def test_uses_adapter_errors(self):
        content = SRC.read_text()
        assert "from core.adapters.errors import" in content, \
            "Must import neutral error types from adapters.errors"


class TestRetryPreserved:
    def test_max_retries_constant(self):
        from core.ohlcv_fetcher import _MAX_RETRIES
        assert _MAX_RETRIES == 5

    def test_retry_logic_in_source(self):
        content = SRC.read_text()
        assert "retries" in content and "_MAX_RETRIES" in content, \
            "Retry logic must be preserved"


class TestNoCloseMethod:
    def test_no_exchange_close(self):
        """close() should not reference self._exchange (deleted)."""
        content = SRC.read_text()
        assert "self._exchange" not in content, \
            "self._exchange must be deleted — adapter manages lifecycle"
