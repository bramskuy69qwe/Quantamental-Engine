"""Tests for one-way mode is_close fix + position fill snapshots."""
from dataclasses import dataclass
from typing import Optional

import pytest

from core.position_snapshot import compute_fill_snapshot, FillSnapshot


# Mock position object matching app_state.positions interface
@dataclass
class MockPosition:
    ticker: str = ""
    direction: str = ""  # "LONG" | "SHORT"
    contract_amount: float = 0.0


class TestOneWayBuyWhenShort:
    """Buy fill when net short → is_close=True (reducing short)."""

    def test_full_close(self):
        pos = MockPosition(ticker="BTCUSDT", direction="SHORT", contract_amount=1.0)
        fill = {"exchange_fill_id": "F1", "symbol": "BTCUSDT", "side": "BUY",
                "quantity": 1.0, "timestamp_ms": 1000}
        snap = compute_fill_snapshot(fill, [pos])
        assert snap.is_close is True
        assert snap.qty_before == -1.0
        assert snap.qty_after == 0.0

    def test_partial_close(self):
        pos = MockPosition(ticker="BTCUSDT", direction="SHORT", contract_amount=1.0)
        fill = {"exchange_fill_id": "F2", "symbol": "BTCUSDT", "side": "BUY",
                "quantity": 0.5, "timestamp_ms": 1000}
        snap = compute_fill_snapshot(fill, [pos])
        assert snap.is_close is True
        assert snap.is_partial_close is True
        assert snap.qty_before == -1.0
        assert snap.qty_after == pytest.approx(-0.5)

    def test_overshoot_close_and_open(self):
        """Buy 1.5 when short 1.0 → closes short AND opens long."""
        pos = MockPosition(ticker="BTCUSDT", direction="SHORT", contract_amount=1.0)
        fill = {"exchange_fill_id": "F3", "symbol": "BTCUSDT", "side": "BUY",
                "quantity": 1.5, "timestamp_ms": 1000}
        snap = compute_fill_snapshot(fill, [pos])
        assert snap.is_close is True
        assert snap.is_open is True  # also opens in opposite direction
        assert snap.qty_after == pytest.approx(0.5)


class TestOneWayBuyWhenFlat:
    """Buy fill when net flat → is_close=False (opening long)."""

    def test_open_from_flat(self):
        fill = {"exchange_fill_id": "F4", "symbol": "BTCUSDT", "side": "BUY",
                "quantity": 1.0, "timestamp_ms": 1000}
        snap = compute_fill_snapshot(fill, [])  # no existing position
        assert snap.is_close is False
        assert snap.is_open is True
        assert snap.qty_before == 0.0
        assert snap.qty_after == 1.0


class TestOneWaySellWhenLong:
    """Sell fill when net long → is_close=True."""

    def test_full_close(self):
        pos = MockPosition(ticker="ETHUSDT", direction="LONG", contract_amount=2.0)
        fill = {"exchange_fill_id": "F5", "symbol": "ETHUSDT", "side": "SELL",
                "quantity": 2.0, "timestamp_ms": 2000}
        snap = compute_fill_snapshot(fill, [pos])
        assert snap.is_close is True
        assert snap.qty_before == 2.0
        assert snap.qty_after == 0.0


class TestOneWaySellWhenFlat:
    """Sell fill when flat → is_close=False (opening short)."""

    def test_open_short(self):
        fill = {"exchange_fill_id": "F6", "symbol": "BTCUSDT", "side": "SELL",
                "quantity": 0.5, "timestamp_ms": 1000}
        snap = compute_fill_snapshot(fill, [])
        assert snap.is_close is False
        assert snap.is_open is True
        assert snap.qty_after == -0.5


class TestOneWayAddToPosition:
    """Buy when already long → adding, not closing."""

    def test_add_to_long(self):
        pos = MockPosition(ticker="BTCUSDT", direction="LONG", contract_amount=1.0)
        fill = {"exchange_fill_id": "F7", "symbol": "BTCUSDT", "side": "BUY",
                "quantity": 0.5, "timestamp_ms": 1000}
        snap = compute_fill_snapshot(fill, [pos])
        assert snap.is_close is False
        assert snap.is_open is True
        assert snap.qty_after == 1.5


class TestHedgeMode:
    """Hedge mode: is_close comes from exchange (pass-through)."""

    def test_hedge_close(self):
        pos = MockPosition(ticker="BTCUSDT", direction="LONG", contract_amount=1.0)
        fill = {"exchange_fill_id": "F8", "symbol": "BTCUSDT", "side": "SELL",
                "direction": "LONG", "quantity": 1.0, "is_close": True,
                "timestamp_ms": 3000}
        snap = compute_fill_snapshot(fill, [pos], mode="hedge")
        assert snap.mode == "hedge"
        assert snap.is_close is True
        assert snap.position_side == "LONG"


class TestBreakEvenClose:
    """The bug case: realizedPnl=0 but position IS closing."""

    def test_breakeven_close_detected(self):
        """With position snapshot, break-even close is correctly identified."""
        pos = MockPosition(ticker="BTCUSDT", direction="LONG", contract_amount=1.0)
        fill = {"exchange_fill_id": "F-BE", "symbol": "BTCUSDT", "side": "SELL",
                "quantity": 1.0, "timestamp_ms": 4000,
                "realized_pnl": 0.0}  # break-even!
        snap = compute_fill_snapshot(fill, [pos])
        # Old heuristic would say is_close=False (pnl=0). Snapshot says True.
        assert snap.is_close is True
        assert snap.qty_before == 1.0
        assert snap.qty_after == 0.0
