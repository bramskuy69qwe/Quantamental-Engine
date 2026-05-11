"""
SR-8 regression tests — regime_fetcher adapter migration.

Validates:
1. Raw ccxt singleton (_get_ccxt, self._ccxt_exchange) removed
2. Dual-catch TODO(SR-8) sites collapsed to single RateLimitError
3. isinstance guards for SupportsOpenInterest / SupportsFundingRates
4. Adapter methods used instead of raw ccxt calls

Run: pytest tests/test_sr8_regime_adapter.py -v
"""
from __future__ import annotations
from pathlib import Path

import pytest


SRC = Path(__file__).parent.parent / "core" / "regime_fetcher.py"


class TestSingletonRemoved:
    def test_no_get_ccxt_method(self):
        content = SRC.read_text()
        assert "def _get_ccxt(" not in content, \
            "_get_ccxt() must be deleted from regime_fetcher.py"

    def test_no_ccxt_exchange_instance(self):
        content = SRC.read_text()
        assert "self._ccxt_exchange" not in content, \
            "self._ccxt_exchange must be deleted"

    def test_no_ccxt_async_support_import(self):
        content = SRC.read_text()
        assert "ccxt.async_support" not in content, \
            "ccxt.async_support must not be imported"

    def test_no_aiohttp_import(self):
        """aiohttp session management was part of _get_ccxt — should be gone."""
        content = SRC.read_text()
        assert "aiohttp" not in content, \
            "aiohttp session management must be removed with _get_ccxt"


class TestDualCatchCollapsed:
    def test_no_todo_sr8_comments(self):
        content = SRC.read_text()
        assert "TODO(SR-8)" not in content, \
            "TODO(SR-8) comments must be removed after migration"

    def test_no_ccxt_isinstance_check(self):
        """Dual-catch isinstance(e, (_ccxt.DDoSProtection, ...)) must be gone."""
        content = SRC.read_text()
        assert "_ccxt.DDoSProtection" not in content, \
            "ccxt.DDoSProtection isinstance check must be collapsed"
        assert "_ccxt.RateLimitExceeded" not in content, \
            "ccxt.RateLimitExceeded isinstance check must be collapsed"

    def test_uses_rate_limit_error(self):
        content = SRC.read_text()
        assert "RateLimitError" in content, \
            "regime_fetcher must catch RateLimitError (neutral type)"


class TestIsinstanceGuards:
    def test_supports_open_interest_guard(self):
        content = SRC.read_text()
        assert "SupportsOpenInterest" in content, \
            "fetch_binance_oi must guard with isinstance(adapter, SupportsOpenInterest)"

    def test_supports_funding_rates_guard(self):
        content = SRC.read_text()
        assert "SupportsFundingRates" in content, \
            "fetch_binance_funding must guard with isinstance(adapter, SupportsFundingRates)"


class TestAdapterInjection:
    def test_constructor_accepts_adapter(self):
        """RegimeFetcher constructor must accept an adapter parameter."""
        from core.regime_fetcher import RegimeFetcher
        # Should not raise — adapter is optional (TradFi path doesn't need one)
        fetcher = RegimeFetcher()
        assert fetcher._adapter is None

    def test_constructor_stores_adapter(self):
        from core.regime_fetcher import RegimeFetcher
        from unittest.mock import MagicMock
        mock_adapter = MagicMock()
        fetcher = RegimeFetcher(adapter=mock_adapter)
        assert fetcher._adapter is mock_adapter


class TestAdapterMethodsUsed:
    def test_fetch_open_interest_hist_referenced(self):
        content = SRC.read_text()
        assert "fetch_open_interest_hist" in content, \
            "fetch_binance_oi must call adapter.fetch_open_interest_hist()"

    def test_fetch_funding_rates_referenced(self):
        content = SRC.read_text()
        assert "fetch_funding_rates" in content, \
            "fetch_binance_funding must call adapter.fetch_funding_rates()"

    def test_no_fapiPublicGetOpenInterestHist(self):
        content = SRC.read_text()
        assert "fapiPublicGetOpenInterestHist" not in content, \
            "Raw ccxt fapiPublicGetOpenInterestHist must be replaced"

    def test_no_fapiPublicGetFundingRate(self):
        content = SRC.read_text()
        assert "fapiPublicGetFundingRate" not in content, \
            "Raw ccxt fapiPublicGetFundingRate must be replaced"
