"""
SR-6 regression tests — WS adapter routing for market handlers + execution_type.

WS-1: Market handlers must use adapter parse methods, not raw Binance fields.
WS-2: execution_type must be an explicit field on NormalizedOrder.

Run: pytest tests/test_sr6_ws_adapter_routing.py -v
"""
from __future__ import annotations
from pathlib import Path

import pytest


# ── WS-1: Raw Binance field access removed from ws_manager ──────────────────

class TestRawFieldsRemoved:
    def test_no_standalone_apply_mark_price(self):
        src = Path(__file__).parent.parent / "core" / "ws_manager.py"
        content = src.read_text()
        assert "\ndef _apply_mark_price(" not in content, \
            "_apply_mark_price standalone function must be deleted"

    def test_no_standalone_apply_kline(self):
        src = Path(__file__).parent.parent / "core" / "ws_manager.py"
        content = src.read_text()
        assert "\ndef _apply_kline(" not in content, \
            "_apply_kline standalone function must be deleted"

    def test_no_standalone_apply_depth(self):
        src = Path(__file__).parent.parent / "core" / "ws_manager.py"
        content = src.read_text()
        assert "\ndef _apply_depth(" not in content, \
            "_apply_depth standalone function must be deleted"

    def test_dispatch_uses_parse_kline(self):
        src = Path(__file__).parent.parent / "core" / "ws_manager.py"
        content = src.read_text()
        assert "parse_kline" in content, \
            "dispatch must call ws_adapter.parse_kline()"

    def test_dispatch_uses_parse_mark_price(self):
        src = Path(__file__).parent.parent / "core" / "ws_manager.py"
        content = src.read_text()
        assert "parse_mark_price" in content, \
            "dispatch must call ws_adapter.parse_mark_price()"

    def test_dispatch_uses_parse_depth(self):
        src = Path(__file__).parent.parent / "core" / "ws_manager.py"
        content = src.read_text()
        assert "parse_depth" in content, \
            "dispatch must call ws_adapter.parse_depth()"


# ── WS-1: Adapter parse methods produce correct shapes ──────────────────────

class TestBinanceParseShapes:
    """Verify Binance adapter parse methods return shapes matching DataCache."""

    def test_parse_mark_price_valid(self):
        from core.adapters.binance.ws_adapter import BinanceWSAdapter
        ws = BinanceWSAdapter()
        msg = {"s": "BTCUSDT", "p": "68000.5", "e": "markPriceUpdate"}
        result = ws.parse_mark_price(msg)
        assert result is not None
        assert result["symbol"] == "BTCUSDT"
        assert result["mark_price"] == 68000.5

    def test_parse_mark_price_missing_price(self):
        from core.adapters.binance.ws_adapter import BinanceWSAdapter
        ws = BinanceWSAdapter()
        result = ws.parse_mark_price({"s": "BTCUSDT"})
        assert result is None

    def test_parse_kline_closed(self):
        from core.adapters.binance.ws_adapter import BinanceWSAdapter
        ws = BinanceWSAdapter()
        msg = {
            "s": "ETHUSDT",
            "k": {"t": 1000, "o": "4500", "h": "4520", "l": "4490",
                   "c": "4510", "v": "100", "x": True},
        }
        result = ws.parse_kline(msg)
        assert result is not None
        assert result["symbol"] == "ETHUSDT"
        assert len(result["candle"]) == 6
        assert result["candle"][2] == 4520.0  # high

    def test_parse_kline_open_returns_none(self):
        from core.adapters.binance.ws_adapter import BinanceWSAdapter
        ws = BinanceWSAdapter()
        msg = {"s": "ETHUSDT", "k": {"t": 1000, "o": "4500", "h": "4520",
               "l": "4490", "c": "4510", "v": "100", "x": False}}
        result = ws.parse_kline(msg)
        assert result is None

    def test_parse_depth_valid(self):
        from core.adapters.binance.ws_adapter import BinanceWSAdapter
        ws = BinanceWSAdapter()
        msg = {"s": "BTCUSDT", "b": [["68000", "1.5"]], "a": [["68001", "2.0"]]}
        result = ws.parse_depth(msg)
        assert result is not None
        assert result["symbol"] == "BTCUSDT"
        assert result["bids"] == [[68000.0, 1.5]]
        assert result["asks"] == [[68001.0, 2.0]]

    def test_parse_depth_missing_symbol(self):
        from core.adapters.binance.ws_adapter import BinanceWSAdapter
        ws = BinanceWSAdapter()
        result = ws.parse_depth({"b": [], "a": []})
        assert result is None


# ── WS-2: execution_type on NormalizedOrder ──────────────────────────────────

class TestExecutionType:
    def test_field_exists_on_normalized_order(self):
        from core.adapters.protocols import NormalizedOrder
        order = NormalizedOrder()
        assert hasattr(order, "execution_type")
        assert order.execution_type is None

    def test_binance_parse_order_populates_execution_type(self):
        from core.adapters.binance.ws_adapter import BinanceWSAdapter
        ws = BinanceWSAdapter()
        msg = {
            "o": {
                "i": 12345, "c": "client1", "s": "BTCUSDT", "S": "BUY",
                "o": "LIMIT", "ot": "LIMIT", "X": "NEW", "x": "NEW",
                "p": "68000", "sp": "0", "q": "0.01", "z": "0",
                "ap": "0", "f": "GTC", "R": False, "ps": "LONG",
                "T": 1000, "t": 0,
            },
            "T": 1000,
        }
        order = ws.parse_order_update(msg)
        assert order.execution_type == "NEW"

    def test_binance_trade_execution_type(self):
        from core.adapters.binance.ws_adapter import BinanceWSAdapter
        ws = BinanceWSAdapter()
        msg = {
            "o": {
                "i": 12345, "c": "c1", "s": "BTCUSDT", "S": "SELL",
                "o": "MARKET", "ot": "MARKET", "X": "FILLED", "x": "TRADE",
                "p": "0", "sp": "0", "q": "0.01", "z": "0.01",
                "ap": "68000", "f": "GTC", "R": False, "ps": "LONG",
                "T": 2000, "t": 1,
            },
            "T": 2000,
        }
        order = ws.parse_order_update(msg)
        assert order.execution_type == "TRADE"

    def test_ws_manager_reads_execution_type_from_order(self):
        """ws_manager must read execution_type from NormalizedOrder, not raw msg."""
        src = Path(__file__).parent.parent / "core" / "ws_manager.py"
        content = src.read_text()
        # Should NOT contain the raw Binance field access pattern
        assert 'msg.get("o", {}).get("x"' not in content, \
            "ws_manager must not read execution_type from raw msg"
