"""
SR-7 Step 4 regression tests — fetch_price_extremes.

Tests:
1. Protocol method exists on ExchangeAdapter with correct signature
2. Both adapters implement fetch_price_extremes
3. Behavioral equivalence: same mock data → same (max, min) as pre-migration
4. _agg_extremes removed from codebase
5. fetch_hl_for_trade delegates to adapter.fetch_price_extremes

Run: pytest tests/test_sr7_step4_price_extremes.py -v
"""
from __future__ import annotations

import asyncio
from typing import Literal, Optional, Tuple
from unittest.mock import patch, AsyncMock, MagicMock

import pytest


# ── Behavioral equivalence fixtures ─────────────────────────────────────────
# Pre-computed expected values from current code with known mock data.
# These were computed by running the current _agg_extremes and _ohlcv_hl
# logic against the fixture data below.

# Fixture 1: Short trade (< 3 min), exercises aggTrades path
FIXTURE_AGG_TRADES_SHORT = [
    {"p": "68000.5", "T": 1000100},
    {"p": "68050.0", "T": 1000200},
    {"p": "67980.0", "T": 1000300},
    {"p": "68020.0", "T": 1000400},
    {"p": "68100.0", "T": 1000500},  # max
    {"p": "67950.0", "T": 1000600},  # min
    {"p": "68010.0", "T": 1000700},
]
EXPECTED_SHORT_TRADE = (68100.0, 67950.0)  # (max, min) from aggTrades

# Fixture 2: Medium trade (5 min), exercises Tier 2 (agg + 1m OHLCV + agg)
FIXTURE_AGG_ENTRY = [
    {"p": "4500.0", "T": 2000050},
    {"p": "4510.0", "T": 2000100},  # entry section max
    {"p": "4495.0", "T": 2000150},  # entry section min
]
FIXTURE_OHLCV_BODY = [
    [2060000, 4505.0, 4520.0, 4490.0, 4510.0, 100.0],  # high=4520, low=4490
    [2120000, 4510.0, 4515.0, 4492.0, 4512.0, 80.0],   # high=4515, low=4492
    [2180000, 4512.0, 4530.0, 4500.0, 4525.0, 120.0],  # high=4530, low=4500
]
FIXTURE_AGG_EXIT = [
    {"p": "4525.0", "T": 2299900},
    {"p": "4535.0", "T": 2299950},  # exit section max
    {"p": "4518.0", "T": 2299980},
]
# Merged: entry(4510, 4495) + body(4530, 4490) + exit(4535, 4518)
# max = max(4510, 4530, 4535) = 4535
# min = min(4495, 4490, 4518) = 4490
EXPECTED_MEDIUM_TRADE = (4535.0, 4490.0)

# Fixture 3: Very short trade (30s), single aggTrades page
FIXTURE_VERY_SHORT = [
    {"p": "0.7850", "T": 3000010},
    {"p": "0.7860", "T": 3000020},  # max
    {"p": "0.7840", "T": 3000025},  # min
    {"p": "0.7855", "T": 3000028},
]
EXPECTED_VERY_SHORT = (0.786, 0.784)

# Fixture 4: Trade where aggTrades returns empty (OHLCV fallback)
EXPECTED_EMPTY_AGG_FALLBACK_OHLCV = [
    [4000000, 100.0, 105.0, 98.0, 102.0, 50.0],  # high=105, low=98
]
EXPECTED_FALLBACK = (105.0, 98.0)

# Fixture 5: Long trade (13 hr), exercises Tier 3 (5-section)
FIXTURE_TIER3_ENTRY_AGG = [{"p": "610.0", "T": 5000050}, {"p": "612.0", "T": 5000100}]
FIXTURE_TIER3_ENTRY_1M = [
    [5060000, 611.0, 614.0, 609.0, 613.0, 200.0],
    [5120000, 613.0, 615.0, 610.0, 612.0, 180.0],
]
FIXTURE_TIER3_MIDDLE_1H = [
    [5_400_000, 612.0, 620.0, 605.0, 618.0, 1000.0],  # high=620, low=605
    [9_000_000, 618.0, 625.0, 608.0, 622.0, 900.0],   # high=625, low=608
]
FIXTURE_TIER3_EXIT_1M = [
    [51_700_000, 622.0, 624.0, 619.0, 621.0, 150.0],
]
FIXTURE_TIER3_EXIT_AGG = [{"p": "621.5", "T": 51799950}, {"p": "623.0", "T": 51799980}]
# Merged: entry_agg(612,610) + entry_1m(615,609) + middle_1h(625,605) + exit_1m(624,619) + exit_agg(623,621.5)
# max = max(612, 615, 625, 624, 623) = 625
# min = min(610, 609, 605, 619, 621.5) = 605
EXPECTED_TIER3 = (625.0, 605.0)


# ── Test 1: Protocol method exists ──────────────────────────────────────────

class TestProtocolMethod:
    def test_fetch_price_extremes_on_protocol(self):
        import inspect
        from core.adapters.protocols import ExchangeAdapter
        source = inspect.getsource(ExchangeAdapter)
        assert "fetch_price_extremes" in source

    def test_signature_has_precision_param(self):
        import inspect
        from core.adapters.protocols import ExchangeAdapter
        source = inspect.getsource(ExchangeAdapter.fetch_price_extremes)
        assert "precision" in source
        assert "auto" in source

    def test_fetch_agg_trades_removed_from_protocol(self):
        import inspect
        from core.adapters.protocols import ExchangeAdapter
        source = inspect.getsource(ExchangeAdapter)
        assert "fetch_agg_trades" not in source, \
            "fetch_agg_trades must be removed from ExchangeAdapter protocol"


# ── Test 2: Both adapters implement ─────────────────────────────────────────

class TestAdapterImplementation:
    def test_binance_has_method(self):
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
        assert hasattr(BinanceUSDMAdapter, "fetch_price_extremes")

    def test_bybit_has_method(self):
        from core.adapters.bybit.rest_adapter import BybitLinearAdapter
        assert hasattr(BybitLinearAdapter, "fetch_price_extremes")


# ── Test 3: Behavioral equivalence ──────────────────────────────────────────

def _make_test_adapter(mock_ex=None):
    """Create a BinanceUSDMAdapter via __new__ with base-class attrs set."""
    from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
    adapter = BinanceUSDMAdapter.__new__(BinanceUSDMAdapter)
    adapter._ex = mock_ex or MagicMock()
    adapter._markets_loaded = True
    adapter._weight_tracker = None
    adapter._current_priority = "normal"
    return adapter


@pytest.mark.asyncio
async def test_equivalence_short_trade():
    """Tier 1 (<3 min): aggTrades → (max, min)."""
    adapter = _make_test_adapter()

    # Mock aggTrades to return fixture data
    adapter._ex.fapiPublicGetAggTrades = MagicMock(return_value=FIXTURE_AGG_TRADES_SHORT)

    result = await adapter.fetch_price_extremes("BTCUSDT", 1000000, 1000800)
    assert result == EXPECTED_SHORT_TRADE, f"Expected {EXPECTED_SHORT_TRADE}, got {result}"


@pytest.mark.asyncio
async def test_equivalence_very_short_trade():
    """Very short trade (30s): single aggTrades page."""
    adapter = _make_test_adapter()

    adapter._ex.fapiPublicGetAggTrades = MagicMock(return_value=FIXTURE_VERY_SHORT)

    result = await adapter.fetch_price_extremes("SIRENUSDT", 3000000, 3000030)
    assert result == EXPECTED_VERY_SHORT, f"Expected {EXPECTED_VERY_SHORT}, got {result}"


@pytest.mark.asyncio
async def test_equivalence_empty_agg_ohlcv_fallback():
    """aggTrades returns empty → OHLCV fallback."""
    adapter = _make_test_adapter()

    adapter._ex.fapiPublicGetAggTrades = MagicMock(return_value=[])
    adapter._ex.fetch_ohlcv = MagicMock(return_value=EXPECTED_EMPTY_AGG_FALLBACK_OHLCV)

    result = await adapter.fetch_price_extremes("TOKENUSDT", 4000000, 4100000)
    assert result == EXPECTED_FALLBACK, f"Expected {EXPECTED_FALLBACK}, got {result}"


# ── Test 4: _agg_extremes removed ───────────────────────────────────────────

class TestAggExtremesRemoved:
    def test_not_in_exchange_market(self):
        """_agg_extremes must be deleted from exchange_market.py source file."""
        from pathlib import Path
        src = Path(__file__).parent.parent / "core" / "exchange_market.py"
        content = src.read_text()
        assert "_agg_extremes" not in content, \
            "_agg_extremes must be deleted from exchange_market.py"

    def test_not_importable(self):
        """_agg_extremes must not be importable from anywhere."""
        from core.exchange import fetch_hl_for_trade  # triggers full import chain
        assert not hasattr(fetch_hl_for_trade, "_agg_extremes")
        # Also verify it's not on the exchange_market module
        import core.exchange_market as em
        assert not hasattr(em, "_agg_extremes")


# ── Test 5: fetch_hl_for_trade delegates to adapter ─────────────────────────

class TestFetchHlDelegation:
    def test_uses_fetch_price_extremes(self):
        from pathlib import Path
        src = Path(__file__).parent.parent / "core" / "exchange_market.py"
        content = src.read_text()
        assert "fetch_price_extremes" in content, \
            "fetch_hl_for_trade must delegate to adapter.fetch_price_extremes"
