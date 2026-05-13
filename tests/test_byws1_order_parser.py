"""
BY-WS-1: Bybit WS order parser — parse_order_update on BybitWSAdapter.
Includes FE-13 reduceOnly classification from day 1.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Bybit V5 WS order event samples ─────────────────────────────────────────

SAMPLE_ORDER_PROTECTIVE_SL = {
    "topic": "order",
    "data": [{
        "orderId": "bybit_sl_001",
        "orderLinkId": "client_sl_001",
        "symbol": "BTCUSDT",
        "side": "Sell",
        "orderType": "StopLoss",
        "orderStatus": "New",
        "price": "0",
        "triggerPrice": "65000",
        "qty": "0.003",
        "cumExecQty": "0",
        "avgPrice": "0",
        "reduceOnly": True,
        "positionIdx": 1,
        "timeInForce": "GTC",
        "createdTime": "1747130943000",
        "updatedTime": "1747130943000",
    }],
}

SAMPLE_ORDER_ENTRY_STOP = {
    "topic": "order",
    "data": [{
        "orderId": "bybit_entry_002",
        "orderLinkId": "client_entry_002",
        "symbol": "SAGAUSDT",
        "side": "Sell",
        "orderType": "StopLoss",
        "orderStatus": "New",
        "price": "0",
        "triggerPrice": "0.45",
        "qty": "100",
        "cumExecQty": "0",
        "avgPrice": "0",
        "reduceOnly": False,
        "positionIdx": 0,
        "timeInForce": "GTC",
        "createdTime": "1747130943000",
        "updatedTime": "1747130943000",
    }],
}

SAMPLE_ORDER_FILLED = {
    "topic": "order",
    "data": [{
        "orderId": "bybit_fill_003",
        "orderLinkId": "",
        "symbol": "ETHUSDT",
        "side": "Buy",
        "orderType": "Market",
        "orderStatus": "Filled",
        "price": "3800",
        "triggerPrice": "0",
        "qty": "0.1",
        "cumExecQty": "0.1",
        "avgPrice": "3801.5",
        "reduceOnly": False,
        "positionIdx": 1,
        "timeInForce": "GTC",
        "createdTime": "1747130000000",
        "updatedTime": "1747131000000",
    }],
}


# ── Topic mapping ────────────────────────────────────────────────────────────

class TestTopicMapping:
    def test_order_topic_maps_to_order_trade_update(self):
        from core.adapters.bybit.ws_adapter import BybitWSAdapter
        adapter = BybitWSAdapter()
        assert adapter.get_event_type(SAMPLE_ORDER_PROTECTIVE_SL) == "ORDER_TRADE_UPDATE"

    def test_position_still_maps_to_account_update(self):
        from core.adapters.bybit.ws_adapter import BybitWSAdapter
        adapter = BybitWSAdapter()
        assert adapter.get_event_type({"topic": "position"}) == "ACCOUNT_UPDATE"


# ── Parser ───────────────────────────────────────────────────────────────────

class TestParseOrderUpdate:
    def test_protective_sl(self):
        from core.adapters.bybit.ws_adapter import BybitWSAdapter
        adapter = BybitWSAdapter()
        order = adapter.parse_order_update(SAMPLE_ORDER_PROTECTIVE_SL)

        assert order.exchange_order_id == "bybit_sl_001"
        assert order.symbol == "BTCUSDT"
        assert order.side == "SELL"
        assert order.order_type == "stop_loss"  # protective, no _entry suffix
        assert order.status == "new"
        assert order.stop_price == 65000.0
        assert order.quantity == 0.003
        assert order.position_side == "LONG"  # positionIdx=1
        assert order.reduce_only is True

    def test_entry_stop_gets_suffix(self):
        """FE-13: reduceOnly=false → stop_loss_entry from day 1."""
        from core.adapters.bybit.ws_adapter import BybitWSAdapter
        adapter = BybitWSAdapter()
        order = adapter.parse_order_update(SAMPLE_ORDER_ENTRY_STOP)

        assert order.order_type == "stop_loss_entry"
        assert order.reduce_only is False

    def test_filled_market_order(self):
        from core.adapters.bybit.ws_adapter import BybitWSAdapter
        adapter = BybitWSAdapter()
        order = adapter.parse_order_update(SAMPLE_ORDER_FILLED)

        assert order.order_type == "market"
        assert order.status == "filled"
        assert order.filled_qty == 0.1
        assert order.avg_fill_price == 3801.5
        assert order.position_side == "LONG"

    def test_canceled_status(self):
        from core.adapters.bybit.ws_adapter import BybitWSAdapter
        adapter = BybitWSAdapter()
        msg = {**SAMPLE_ORDER_PROTECTIVE_SL}
        msg["data"] = [{**msg["data"][0], "orderStatus": "Cancelled"}]
        order = adapter.parse_order_update(msg)
        assert order.status == "canceled"

    def test_has_parse_order_update_method(self):
        """ws_manager checks hasattr(ws_adapter, 'parse_order_update')."""
        from core.adapters.bybit.ws_adapter import BybitWSAdapter
        adapter = BybitWSAdapter()
        assert hasattr(adapter, "parse_order_update")
