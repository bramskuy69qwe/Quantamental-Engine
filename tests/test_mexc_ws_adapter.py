"""Tests for MEXC WebSocket adapter — auth, subscribe, parsing, heartbeat."""
import hashlib
import hmac

import pytest

from core.adapters.mexc.ws_adapter import (
    MexcWSAdapter,
    _sign_login,
    _normalize_symbol,
)


class TestAuthHandshake:
    def test_sign_login_deterministic(self):
        """Known inputs produce expected signature."""
        key = "test_api_key"
        secret = "test_secret"
        ts = 1611038237237
        expected = hmac.new(
            secret.encode(), f"{key}{ts}".encode(), hashlib.sha256
        ).hexdigest()
        assert _sign_login(key, secret, ts) == expected

    def test_build_auth_payload_structure(self):
        ws = MexcWSAdapter()
        payload = ws.build_auth_payload("mykey", "mysecret")
        assert payload["method"] == "login"
        assert payload["param"]["apiKey"] == "mykey"
        assert "signature" in payload["param"]
        assert "reqTime" in payload["param"]
        # Verify signature is hex string
        assert len(payload["param"]["signature"]) == 64

    def test_requires_post_connect_auth(self):
        ws = MexcWSAdapter()
        assert ws.requires_post_connect_auth() is True


class TestSubscribePayload:
    def test_subscribe_has_all_channels(self):
        ws = MexcWSAdapter()
        payload = ws.build_subscribe_payload([])
        filters = payload["param"]["filters"]
        names = {f["filter"] for f in filters}
        assert "position" in names
        assert "order" in names
        assert "order.deal" in names
        assert "asset" in names

    def test_subscribe_method(self):
        ws = MexcWSAdapter()
        payload = ws.build_subscribe_payload([])
        assert payload["method"] == "personal.filter"


class TestHeartbeat:
    def test_build_ping(self):
        assert MexcWSAdapter.build_ping() == {"method": "ping"}

    def test_is_pong(self):
        assert MexcWSAdapter.is_pong({"channel": "pong", "data": 123456}) is True
        assert MexcWSAdapter.is_pong({"channel": "push.ticker"}) is False


class TestSymbolNormalization:
    def test_mexc_native_format(self):
        assert _normalize_symbol("BTC_USDT") == "BTCUSDT"

    def test_ccxt_format(self):
        assert _normalize_symbol("BTC/USDT:USDT") == "BTCUSDT"


class TestPositionParsing:
    def test_position_update(self):
        ws = MexcWSAdapter()
        msg = {
            "channel": "push.personal.position",
            "data": {
                "positionId": "12345",
                "symbol": "BTC_USDT",
                "holdVol": "10",
                "holdAvgPrice": "50000",
                "positionType": "1",
                "liquidatePrice": "45000",
            },
            "ts": 1611038237237,
        }
        balances, positions = ws.parse_account_update(msg)
        assert len(positions) == 1
        p = positions[0]
        assert p.symbol == "BTCUSDT"  # normalized
        assert p.side == "LONG"
        assert p.size == 10.0  # raw contracts (caller applies contractSize)
        assert p.entry_price == 50000.0

    def test_asset_update(self):
        ws = MexcWSAdapter()
        msg = {
            "channel": "push.personal.asset",
            "data": {"equity": "10000", "availableBalance": "5000", "unrealized": "500"},
            "ts": 1611038237237,
        }
        balances, positions = ws.parse_account_update(msg)
        assert balances["total_equity"] == 10000.0
        assert balances["available_margin"] == 5000.0
        assert len(positions) == 0


class TestFillParsing:
    def test_deal_message(self):
        ws = MexcWSAdapter()
        msg = {
            "channel": "push.personal.order.deal",
            "data": {
                "id": "fill-001",
                "orderId": "ord-001",
                "symbol": "ETH_USDT",
                "T": "1",  # buy
                "p": "3000",
                "v": "5",
                "fee": "0.15",
                "t": 1611038237237,
            },
            "symbol": "ETH_USDT",
        }
        fill = ws.parse_fill(msg)
        assert fill is not None
        assert fill["symbol"] == "ETHUSDT"
        assert fill["side"] == "BUY"
        assert fill["price"] == 3000.0
        assert fill["quantity"] == 5.0
        assert fill["fee"] == 0.15
        assert fill["source"] == "mexc_ws"

    def test_non_deal_returns_none(self):
        ws = MexcWSAdapter()
        assert ws.parse_fill({"channel": "push.ticker"}) is None


class TestOrderParsing:
    def test_order_update(self):
        ws = MexcWSAdapter()
        msg = {
            "channel": "push.personal.order",
            "data": {
                "orderId": "ord-002",
                "symbol": "BTC_USDT",
                "side": "1",
                "state": "2",  # filled
                "price": "50000",
                "vol": "10",
                "dealVol": "10",
                "dealAvgPrice": "50010",
            },
        }
        order = ws.parse_order_update(msg)
        assert order is not None
        assert order["symbol"] == "BTCUSDT"
        assert order["side"] == "BUY"
        assert order["status"] == "filled"
        assert order["filled_qty"] == 10.0


class TestEventTypeMapping:
    def test_position_channel(self):
        ws = MexcWSAdapter()
        assert ws.get_event_type({"channel": "push.personal.position"}) == "ACCOUNT_UPDATE"

    def test_order_channel(self):
        ws = MexcWSAdapter()
        assert ws.get_event_type({"channel": "push.personal.order"}) == "ORDER_TRADE_UPDATE"

    def test_deal_channel(self):
        ws = MexcWSAdapter()
        assert ws.get_event_type({"channel": "push.personal.order.deal"}) == "ORDER_TRADE_UPDATE"

    def test_pong(self):
        ws = MexcWSAdapter()
        assert ws.get_event_type({"channel": "pong"}) == "pong"


class TestRegistration:
    def test_ws_registered(self):
        from core.adapters.registry import list_registered
        registered = list_registered()
        assert "mexc:linear_perpetual" in registered["ws"]
