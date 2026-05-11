"""
SR-4 Step 1 regression test — fetch_ohlcv_window dead-code deletion.

Verifies fetch_ohlcv_window is removed from exchange_market.py and
no longer re-exported from exchange.py.

Run: pytest tests/test_sr4_step1_ohlcv_window.py -v
"""
from __future__ import annotations
from pathlib import Path

import pytest


class TestFetchOhlcvWindowRemoved:
    def test_not_in_exchange_market_source(self):
        """fetch_ohlcv_window must not appear in exchange_market.py source."""
        src = Path(__file__).parent.parent / "core" / "exchange_market.py"
        content = src.read_text()
        assert "fetch_ohlcv_window" not in content, \
            "fetch_ohlcv_window must be deleted from exchange_market.py"

    def test_not_in_exchange_reexport(self):
        """fetch_ohlcv_window must not appear in exchange.py re-export block."""
        src = Path(__file__).parent.parent / "core" / "exchange.py"
        content = src.read_text()
        assert "fetch_ohlcv_window" not in content, \
            "fetch_ohlcv_window must be removed from exchange.py re-exports"

    def test_not_importable(self):
        """fetch_ohlcv_window must not be importable from core.exchange."""
        import core.exchange as ex
        assert not hasattr(ex, "fetch_ohlcv_window"), \
            "fetch_ohlcv_window must not be importable from core.exchange"
