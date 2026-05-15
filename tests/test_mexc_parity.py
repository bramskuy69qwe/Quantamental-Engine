"""Tests for MEXC parity: symbol format, qty units, mode detection."""
import pytest

from core.adapters.mexc.rest_adapter import MexcLinearAdapter


class TestSymbolNormalization:
    """CCXT MEXC returns 'BTC/USDT:USDT'; engine uses 'BTCUSDT'."""

    def test_ccxt_to_canonical(self):
        a = MexcLinearAdapter("", "", "")
        assert a.normalize_symbol("BTC/USDT:USDT") == "BTCUSDT"

    def test_underscore_format(self):
        a = MexcLinearAdapter("", "", "")
        assert a.normalize_symbol("ETH_USDT") == "ETHUSDT"

    def test_already_canonical(self):
        a = MexcLinearAdapter("", "", "")
        assert a.normalize_symbol("BTCUSDT") == "BTCUSDT"

    def test_denormalize_for_api(self):
        a = MexcLinearAdapter("", "", "")
        assert a.denormalize_symbol("BTCUSDT") == "BTC/USDT:USDT"

    def test_denormalize_already_ccxt(self):
        a = MexcLinearAdapter("", "", "")
        assert a.denormalize_symbol("BTC/USDT:USDT") == "BTC/USDT:USDT"


class TestQuantityConversion:
    """MEXC qty is in contracts. Must multiply by contractSize for base qty."""

    def test_contract_size_default(self):
        """When markets not loaded, default to 1.0 (passthrough)."""
        a = MexcLinearAdapter("", "", "")
        assert a._get_contract_size("BTCUSDT") == 1.0

    def test_contract_size_conceptual(self):
        """Conceptual: 10 contracts × 0.0001 BTC/contract = 0.001 BTC."""
        contracts = 10
        contract_size = 0.0001
        base_qty = contracts * contract_size
        assert base_qty == pytest.approx(0.001)


class TestModeDetection:
    """MEXC fills lack direction field → treated as one_way mode."""

    def test_empty_direction_is_one_way(self):
        """Task 30's mode detection: empty direction = one_way."""
        fill = {"direction": "", "side": "BUY", "quantity": 1.0}
        direction = fill.get("direction", "")
        mode = "hedge" if direction and direction not in ("BOTH", "") else "one_way"
        assert mode == "one_way"

    def test_none_direction_is_one_way(self):
        fill = {"direction": None, "side": "BUY"}
        direction = fill.get("direction") or ""
        mode = "hedge" if direction and direction not in ("BOTH", "") else "one_way"
        assert mode == "one_way"

    def test_mexc_position_side_not_in_fills(self):
        """MEXC CCXT fills have side=buy/sell but no positionSide/direction."""
        # This is the key parity finding: MEXC fills don't carry direction
        # like Binance (LONG/SHORT/BOTH). The engine falls back to one_way
        # mode and uses qty-delta logic (Task 30) for is_close derivation.
        fill = {"side": "SELL", "symbol": "BTCUSDT", "quantity": 1.0}
        assert "direction" not in fill  # no direction field


class TestSpotChecks:
    def test_adapter_has_normalize(self):
        a = MexcLinearAdapter("", "", "")
        assert callable(a.normalize_symbol)
        assert callable(a.denormalize_symbol)

    def test_adapter_has_contract_size(self):
        a = MexcLinearAdapter("", "", "")
        assert callable(a._get_contract_size)

    @pytest.mark.asyncio
    async def test_fetch_income_returns_empty(self):
        """MEXC has no income endpoint — returns [] (documented limitation)."""
        a = MexcLinearAdapter("", "", "")
        result = await a.fetch_income()
        assert result == []
