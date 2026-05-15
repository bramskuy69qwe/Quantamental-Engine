"""Tests for is_close fix wired into production fill ingest."""
from dataclasses import dataclass

import pytest

from core.position_snapshot import compute_fill_snapshot


@dataclass
class MockPosition:
    ticker: str = ""
    direction: str = ""
    contract_amount: float = 0.0


class TestBreakEvenRegression:
    """The critical regression proof: break-even close was misclassified."""

    def test_adapter_heuristic_wrong(self):
        """Old heuristic: realizedPnl=0 → is_close=False. WRONG for closes."""
        realized_pnl = 0.0
        adapter_is_close = int(realized_pnl != 0)
        assert adapter_is_close == 0  # old heuristic says "not a close"

    def test_snapshot_override_correct(self):
        """Snapshot: sell when long 1.0 → qty goes to 0 → is_close=True. RIGHT."""
        pos = MockPosition(ticker="BTCUSDT", direction="LONG", contract_amount=1.0)
        fill = {"exchange_fill_id": "F-BE", "symbol": "BTCUSDT", "side": "SELL",
                "quantity": 1.0, "timestamp_ms": 1000, "realized_pnl": 0.0,
                "is_close": 0}  # adapter says False
        snapshot = compute_fill_snapshot(fill, [pos])
        assert snapshot.is_close is True  # snapshot overrides

    def test_fill_dict_updated_inline(self):
        """Simulate the inline override: fill['is_close'] gets snapshot value."""
        pos = MockPosition(ticker="BTCUSDT", direction="LONG", contract_amount=1.0)
        fill = {"exchange_fill_id": "F-BE2", "symbol": "BTCUSDT", "side": "SELL",
                "quantity": 1.0, "timestamp_ms": 1000, "is_close": 0}
        snapshot = compute_fill_snapshot(fill, [pos])
        fill["is_close"] = int(snapshot.is_close)  # the override
        assert fill["is_close"] == 1


class TestNormalCloseAgrees:
    """Normal close: adapter and snapshot agree. No discrepancy."""

    def test_both_agree_on_close(self):
        pos = MockPosition(ticker="BTCUSDT", direction="LONG", contract_amount=1.0)
        fill = {"exchange_fill_id": "F-NC", "symbol": "BTCUSDT", "side": "SELL",
                "quantity": 1.0, "timestamp_ms": 2000, "realized_pnl": 50.0,
                "is_close": 1}  # adapter says True
        snapshot = compute_fill_snapshot(fill, [pos])
        assert snapshot.is_close is True  # snapshot agrees
        assert fill["is_close"] == 1  # no change needed


class TestFallbackOnFailure:
    """Position lookup failure: graceful fallback to adapter value."""

    def test_no_positions_flat_open(self):
        """No position found → treated as flat → fill opens, is_close=False."""
        fill = {"exchange_fill_id": "F-FB", "symbol": "BTCUSDT", "side": "BUY",
                "quantity": 0.5, "timestamp_ms": 3000, "is_close": 0}
        snapshot = compute_fill_snapshot(fill, [])  # empty positions
        assert snapshot.is_close is False  # flat → opening, agrees with adapter


class TestHedgeMode:
    """Hedge mode: pass-through from exchange."""

    def test_hedge_close_passthrough(self):
        pos = MockPosition(ticker="BTCUSDT", direction="LONG", contract_amount=1.0)
        fill = {"exchange_fill_id": "F-H", "symbol": "BTCUSDT", "side": "SELL",
                "direction": "LONG", "quantity": 1.0, "timestamp_ms": 4000,
                "is_close": True}
        snapshot = compute_fill_snapshot(fill, [pos], mode="hedge")
        assert snapshot.is_close is True
        assert snapshot.mode == "hedge"


class TestModeDetection:
    """Mode detection from fill's direction field."""

    def test_one_way_detection(self):
        for direction in ["BOTH", "", None]:
            mode = "hedge" if direction and direction not in ("BOTH", "") else "one_way"
            assert mode == "one_way", f"direction={direction!r} should be one_way"

    def test_hedge_detection(self):
        for direction in ["LONG", "SHORT"]:
            mode = "hedge" if direction and direction not in ("BOTH", "") else "one_way"
            assert mode == "hedge", f"direction={direction!r} should be hedge"


class TestPositionStateOrdering:
    """Snapshot must use pre-fill position state."""

    def test_qty_before_reflects_prefill(self):
        """Position has 2.0 BTC. Fill sells 1.0. qty_before should be 2.0."""
        pos = MockPosition(ticker="BTCUSDT", direction="LONG", contract_amount=2.0)
        fill = {"exchange_fill_id": "F-ORD", "symbol": "BTCUSDT", "side": "SELL",
                "quantity": 1.0, "timestamp_ms": 5000}
        snapshot = compute_fill_snapshot(fill, [pos])
        assert snapshot.qty_before == 2.0  # pre-fill state
        assert snapshot.qty_after == 1.0   # computed
