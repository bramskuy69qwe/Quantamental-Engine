"""
SR-7 Step 2 regression tests — protocol dataclass changes.

Validates new/modified fields on normalized data models and new types.

Run: pytest tests/test_sr7_step2_dataclasses.py -v
"""
from __future__ import annotations

import pytest


class TestNormalizedAccountFields:
    def test_currency_field_exists(self):
        from core.adapters.protocols import NormalizedAccount
        acc = NormalizedAccount()
        assert hasattr(acc, "currency")
        assert acc.currency == "USDT"

    def test_fee_source_field_exists(self):
        from core.adapters.protocols import NormalizedAccount
        acc = NormalizedAccount()
        assert hasattr(acc, "fee_source")
        assert acc.fee_source == "default"


class TestNormalizedOrderOptionalFields:
    def test_reduce_only_is_optional(self):
        from core.adapters.protocols import NormalizedOrder
        order = NormalizedOrder()
        assert order.reduce_only is None

    def test_position_side_is_optional(self):
        from core.adapters.protocols import NormalizedOrder
        order = NormalizedOrder()
        assert order.position_side is None

    def test_parent_order_id_exists(self):
        from core.adapters.protocols import NormalizedOrder
        order = NormalizedOrder()
        assert hasattr(order, "parent_order_id")
        assert order.parent_order_id is None

    def test_oca_group_id_exists(self):
        from core.adapters.protocols import NormalizedOrder
        order = NormalizedOrder()
        assert hasattr(order, "oca_group_id")
        assert order.oca_group_id is None


class TestNormalizedTradeFields:
    def test_fee_asset_default_empty(self):
        from core.adapters.protocols import NormalizedTrade
        trade = NormalizedTrade()
        assert trade.fee_asset == ""

    def test_is_close_field_exists(self):
        """is_close must exist and default to False."""
        from core.adapters.protocols import NormalizedTrade
        trade = NormalizedTrade()
        assert trade.is_close is False


class TestNormalizedFundingRate:
    def test_dataclass_exists(self):
        from core.adapters.protocols import NormalizedFundingRate
        fr = NormalizedFundingRate()
        assert fr.symbol == ""
        assert fr.funding_rate == 0.0
        assert fr.next_funding_time_ms == 0
        assert fr.mark_price == 0.0

    def test_populated(self):
        from core.adapters.protocols import NormalizedFundingRate
        fr = NormalizedFundingRate(
            symbol="BTCUSDT",
            funding_rate=0.0001,
            next_funding_time_ms=1778184237076,
            mark_price=68000.0,
        )
        assert fr.symbol == "BTCUSDT"
        assert fr.funding_rate == 0.0001


class TestWSEventType:
    def test_constants_exist(self):
        from core.adapters.protocols import WSEventType
        assert WSEventType.ACCOUNT_UPDATE == "ACCOUNT_UPDATE"
        assert WSEventType.ORDER_UPDATE == "ORDER_TRADE_UPDATE"
        assert WSEventType.KLINE == "kline"
        assert WSEventType.MARK_PRICE == "markPriceUpdate"
        assert WSEventType.DEPTH == "depthUpdate"


class TestFundingRateReturnType:
    """fetch_current_funding_rates should return NormalizedFundingRate objects."""

    def test_protocol_signature_uses_normalized_type(self):
        """Protocol docstring or type hint should reference NormalizedFundingRate."""
        import inspect
        from core.adapters import protocols
        source = inspect.getsource(protocols.ExchangeAdapter.fetch_current_funding_rates)
        assert "NormalizedFundingRate" in source, (
            "fetch_current_funding_rates should reference NormalizedFundingRate in signature"
        )
