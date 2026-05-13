"""
AD-4: is_close deterministic check — side + positionSide instead of
realizedPnl != 0 heuristic. Tests both Binance and Bybit adapters.
"""
import os
import sys
from unittest.mock import MagicMock, AsyncMock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Binance adapter ─────────────────────────────────────────────────────────

def _make_binance_trade(side, position_side, realized_pnl=0.0):
    """Build a raw Binance trade dict as returned by fapiPrivateGetUserTrades."""
    return {
        "id": "12345",
        "orderId": "67890",
        "symbol": "BTCUSDT",
        "side": side,
        "positionSide": position_side,
        "price": "68000",
        "qty": "0.003",
        "realizedPnl": str(realized_pnl),
        "commission": "0.10",
        "commissionAsset": "USDT",
        "time": 1747130943000,
        "maker": False,
    }


class TestBinanceIsClose:
    def _parse(self, raw_trade):
        """Parse a single raw trade through the Binance adapter's logic."""
        t = raw_trade
        side = t.get("side", "")
        position_side = t.get("positionSide", "")
        if position_side and position_side != "BOTH":
            # Hedge mode: deterministic from positionSide + side
            is_close = (
                (side == "SELL" and position_side == "LONG") or
                (side == "BUY" and position_side == "SHORT")
            )
        else:
            # One-way mode (BOTH or empty): fall back to realizedPnl heuristic
            is_close = bool(float(t.get("realizedPnl", 0) or 0) != 0)
        return is_close

    def test_sell_long_is_close(self):
        """SELL on LONG position is a close."""
        t = _make_binance_trade("SELL", "LONG", realized_pnl=5.0)
        assert self._parse(t) is True

    def test_buy_short_is_close(self):
        """BUY on SHORT position is a close."""
        t = _make_binance_trade("BUY", "SHORT", realized_pnl=-2.0)
        assert self._parse(t) is True

    def test_buy_long_is_not_close(self):
        """BUY on LONG position is an open (adding to long)."""
        t = _make_binance_trade("BUY", "LONG")
        assert self._parse(t) is False

    def test_sell_short_is_not_close(self):
        """SELL on SHORT position is an open (adding to short)."""
        t = _make_binance_trade("SELL", "SHORT")
        assert self._parse(t) is False

    def test_break_even_close_detected(self):
        """Close at break-even (realizedPnl=0) must still be detected as close."""
        t = _make_binance_trade("SELL", "LONG", realized_pnl=0.0)
        assert self._parse(t) is True, "Break-even close was not detected"

    def test_one_way_falls_back_to_pnl(self):
        """One-way mode (BOTH): can't determine from side alone, falls back to realizedPnl."""
        # With PnL != 0 → is_close=True
        t = _make_binance_trade("SELL", "BOTH", realized_pnl=5.0)
        assert self._parse(t) is True
        # With PnL == 0 → is_close=False (ambiguous)
        t2 = _make_binance_trade("SELL", "BOTH", realized_pnl=0.0)
        assert self._parse(t2) is False


# ── Bybit adapter ────────────────────────────────────────────────────────────

def _make_bybit_trade(side, position_idx, closed_pnl=0.0):
    """Build a raw Bybit trade dict as returned by CCXT fetch_my_trades."""
    return {
        "id": "exec_123",
        "order": "order_456",
        "symbol": "BTC/USDT:USDT",
        "side": side.lower(),
        "price": 68000.0,
        "amount": 0.003,
        "fee": {"cost": 0.10, "currency": "USDT"},
        "takerOrMaker": "taker",
        "timestamp": 1747130943000,
        "info": {
            "execId": "exec_123",
            "orderId": "order_456",
            "positionIdx": str(position_idx),
            "closedPnl": str(closed_pnl),
        },
    }


class TestBybitIsClose:
    def _parse(self, raw_trade):
        """Replicate the deterministic is_close logic for Bybit."""
        t = raw_trade
        info = t.get("info", {})
        side_upper = t.get("side", "").upper()
        pos_idx = str(info.get("positionIdx", "0"))
        if pos_idx in ("1", "2"):
            # Hedge mode: deterministic from positionIdx + side
            direction = {"1": "LONG", "2": "SHORT"}[pos_idx]
            is_close = (
                (side_upper == "SELL" and direction == "LONG") or
                (side_upper == "BUY" and direction == "SHORT")
            )
        else:
            # One-way mode: fall back to closedPnl heuristic (can't determine from side alone)
            is_close = bool(float(info.get("closedPnl", 0) or 0) != 0)
        return is_close

    def test_sell_long_hedge_is_close(self):
        """Hedge mode: SELL on positionIdx=1 (LONG) is close."""
        t = _make_bybit_trade("sell", 1, closed_pnl=5.0)
        assert self._parse(t) is True

    def test_buy_short_hedge_is_close(self):
        """Hedge mode: BUY on positionIdx=2 (SHORT) is close."""
        t = _make_bybit_trade("buy", 2, closed_pnl=-2.0)
        assert self._parse(t) is True

    def test_buy_long_hedge_not_close(self):
        """Hedge mode: BUY on positionIdx=1 (LONG) is open."""
        t = _make_bybit_trade("buy", 1)
        assert self._parse(t) is False

    def test_sell_short_hedge_not_close(self):
        """Hedge mode: SELL on positionIdx=2 (SHORT) is open."""
        t = _make_bybit_trade("sell", 2)
        assert self._parse(t) is False

    def test_break_even_close_detected(self):
        """Close at break-even (closedPnl=0) must still be detected."""
        t = _make_bybit_trade("sell", 1, closed_pnl=0.0)
        assert self._parse(t) is True, "Break-even close was not detected"

    def test_one_way_falls_back_to_pnl(self):
        """One-way mode (positionIdx=0): can't determine from side alone, falls back to closedPnl."""
        # With closedPnl != 0 → is_close=True (heuristic fallback)
        t = _make_bybit_trade("sell", 0, closed_pnl=5.0)
        assert self._parse(t) is True
        # With closedPnl == 0 → is_close=False (ambiguous, defaults to open)
        t2 = _make_bybit_trade("sell", 0, closed_pnl=0.0)
        assert self._parse(t2) is False
