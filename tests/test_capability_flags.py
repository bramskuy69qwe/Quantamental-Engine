"""Tests for adapter capability flags + require_capability gate."""
import pytest

from core.adapters.protocols import (
    CAPABILITY_KEYS,
    AdapterCapabilityError,
    require_capability,
)
from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
from core.adapters.bybit.rest_adapter import BybitLinearAdapter


# ── Capability key coverage ───────────────────────────────────────────────────


class TestCapabilityKeys:
    @pytest.mark.parametrize("cls", [BinanceUSDMAdapter, BybitLinearAdapter],
                             ids=["binance", "bybit"])
    def test_adapter_has_all_capability_keys(self, cls):
        caps = cls.capabilities
        missing = CAPABILITY_KEYS - set(caps)
        assert not missing, f"{cls.__name__} missing keys: {missing}"

    @pytest.mark.parametrize("cls", [BinanceUSDMAdapter, BybitLinearAdapter],
                             ids=["binance", "bybit"])
    def test_no_extra_keys(self, cls):
        extra = set(cls.capabilities) - CAPABILITY_KEYS
        assert not extra, f"{cls.__name__} has undeclared keys: {extra}"

    @pytest.mark.parametrize("cls", [BinanceUSDMAdapter, BybitLinearAdapter],
                             ids=["binance", "bybit"])
    def test_orders_true(self, cls):
        assert cls.capabilities["orders"] is True

    @pytest.mark.parametrize("cls", [BinanceUSDMAdapter, BybitLinearAdapter],
                             ids=["binance", "bybit"])
    def test_historical_equity_false(self, cls):
        assert cls.capabilities["historical_equity"] is False


# ── require_capability ────────────────────────────────────────────────────────


class _MockAdapter:
    capabilities = {"orders": True, "market_data": True, "historical_equity": False}


class _NoCapAdapter:
    pass


class TestRequireCapability:
    def test_passes_when_true(self):
        require_capability(_MockAdapter(), "orders")  # should not raise

    def test_raises_when_false(self):
        with pytest.raises(AdapterCapabilityError, match="historical_equity"):
            require_capability(_MockAdapter(), "historical_equity")

    def test_raises_when_key_missing(self):
        with pytest.raises(AdapterCapabilityError, match="position_query"):
            require_capability(_MockAdapter(), "position_query")

    def test_raises_when_no_capabilities_attr(self):
        with pytest.raises(AdapterCapabilityError):
            require_capability(_NoCapAdapter(), "orders")

    def test_error_message_includes_class_name(self):
        with pytest.raises(AdapterCapabilityError, match="_MockAdapter"):
            require_capability(_MockAdapter(), "historical_equity")


# ── Calculator gate (unit-level mock) ─────────────────────────────────────────


class _ReadOnlyAdapter:
    """Simulates a MEXC-style read-only adapter."""
    capabilities = {
        "orders": False, "conditional_orders": False,
        "market_data": True, "account_query": True,
        "position_query": True, "historical_equity": False,
    }


class _FullAdapter:
    capabilities = {
        "orders": True, "conditional_orders": True,
        "market_data": True, "account_query": True,
        "position_query": True, "historical_equity": False,
    }


class TestCalculatorGate:
    def test_full_adapter_passes_gate(self):
        require_capability(_FullAdapter(), "orders")

    def test_read_only_adapter_blocked(self):
        with pytest.raises(AdapterCapabilityError, match="orders"):
            require_capability(_ReadOnlyAdapter(), "orders")
