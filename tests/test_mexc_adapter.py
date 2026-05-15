"""Tests for MEXC Futures adapter — capability flags + registration + parsing."""
import pytest

from core.adapters.mexc.rest_adapter import MexcLinearAdapter
from core.adapters.protocols import (
    CAPABILITY_KEYS,
    AdapterCapabilityError,
    require_capability,
)


class TestCapabilityFlags:
    def test_orders_false(self):
        assert MexcLinearAdapter.capabilities["orders"] is False

    def test_conditional_orders_false(self):
        assert MexcLinearAdapter.capabilities["conditional_orders"] is False

    def test_market_data_true(self):
        assert MexcLinearAdapter.capabilities["market_data"] is True

    def test_account_query_true(self):
        assert MexcLinearAdapter.capabilities["account_query"] is True

    def test_position_query_true(self):
        assert MexcLinearAdapter.capabilities["position_query"] is True

    def test_historical_equity_false(self):
        assert MexcLinearAdapter.capabilities["historical_equity"] is False

    def test_all_keys_present(self):
        missing = CAPABILITY_KEYS - set(MexcLinearAdapter.capabilities)
        assert not missing, f"Missing keys: {missing}"


class TestCalculatorGateBlock:
    def test_require_orders_raises(self):
        """Calculator gate blocks MEXC accounts with clear error."""
        adapter = MexcLinearAdapter("", "", "")
        with pytest.raises(AdapterCapabilityError, match="orders"):
            require_capability(adapter, "orders")

    def test_require_account_query_passes(self):
        adapter = MexcLinearAdapter("", "", "")
        require_capability(adapter, "account_query")  # should not raise


class TestRegistration:
    def test_registered_in_registry(self):
        from core.adapters.registry import list_registered
        registered = list_registered()
        assert "mexc:linear_perpetual" in registered["rest"]

    def test_get_adapter_returns_mexc(self):
        from core.adapters import get_adapter
        adapter = get_adapter("mexc", "linear_perpetual")
        assert isinstance(adapter, MexcLinearAdapter)
        assert adapter.exchange_id == "mexc"


class TestAdapterAttributes:
    def test_exchange_id(self):
        a = MexcLinearAdapter("", "", "")
        assert a.exchange_id == "mexc"

    def test_market_type(self):
        a = MexcLinearAdapter("", "", "")
        assert a.market_type == "linear_perpetual"

    def test_ohlcv_limit(self):
        a = MexcLinearAdapter("", "", "")
        assert a.ohlcv_limit == 2000

    def test_ccxt_instance_created(self):
        a = MexcLinearAdapter("test_key", "test_secret", "")
        ex = a.get_ccxt_instance()
        assert ex is not None
        assert ex.id == "mexc"


class TestWeightTrackerIntegration:
    def test_tracker_lazy_init(self):
        a = MexcLinearAdapter("", "", "")
        tracker = a._get_weight_tracker()
        assert tracker is not None
        assert tracker.adapter_name == "mexc"

    def test_priority_support(self):
        a = MexcLinearAdapter("", "", "")
        a.set_priority("background")
        assert a._current_priority == "background"


class TestNormalization:
    def test_normalize_symbol_passthrough(self):
        a = MexcLinearAdapter("", "", "")
        assert a.normalize_symbol("BTC/USDT:USDT") == "BTC/USDT:USDT"

    def test_precision_defaults(self):
        a = MexcLinearAdapter("", "", "")
        prec = a.get_precision("BTCUSDT")
        assert prec["price"] == 8  # default when markets not loaded
        assert prec["amount"] == 8
