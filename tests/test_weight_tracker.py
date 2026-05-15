"""Tests for proactive API weight tracker."""
import asyncio
import time

import pytest

from core.rate_limit.weight_tracker import WeightTracker, ReserveResult


@pytest.fixture
def tracker():
    return WeightTracker(
        adapter_name="test",
        max_weight=1200,
        window_seconds=60,
    )


class TestReserveWithinBudget:
    @pytest.mark.asyncio
    async def test_ok_increments_counter(self, tracker):
        result = await tracker.reserve(10)
        assert result.ok is True
        assert result.throttled is False
        assert result.blocked is False
        assert tracker.current_weight == 10

    @pytest.mark.asyncio
    async def test_multiple_reserves_accumulate(self, tracker):
        await tracker.reserve(100)
        await tracker.reserve(200)
        assert tracker.current_weight == 300


class TestThresholds:
    @pytest.mark.asyncio
    async def test_warn_threshold(self, tracker):
        """70% of 1200 = 840. Reserve 850 → above warn, below throttle."""
        result = await tracker.reserve(850)
        assert result.ok is True
        assert result.current_pct == pytest.approx(850 / 1200, abs=0.01)

    @pytest.mark.asyncio
    async def test_throttle_threshold(self, tracker):
        """85% of 1200 = 1020. Reserve to cross it."""
        await tracker.reserve(500)
        result = await tracker.reserve(530)  # total 1030 = 85.8%
        assert result.ok is True
        assert result.throttled is True
        assert result.delay_ms > 0

    @pytest.mark.asyncio
    async def test_block_threshold(self, tracker):
        """95% of 1200 = 1140. Reserve to cross it."""
        await tracker.reserve(500)
        await tracker.reserve(500)
        result = await tracker.reserve(150)  # total would be 1150 = 95.8%
        assert result.ok is False
        assert result.blocked is True


class TestReconcile:
    @pytest.mark.asyncio
    async def test_reconcile_updates_weight(self, tracker):
        await tracker.reserve(100)
        assert tracker.current_weight == 100
        tracker.reconcile(50)
        assert tracker.current_weight == 50


class TestWindowReset:
    @pytest.mark.asyncio
    async def test_window_expires_resets_counter(self):
        tracker = WeightTracker(
            adapter_name="test", max_weight=1200, window_seconds=1,
        )
        await tracker.reserve(1000)
        assert tracker.current_weight == 1000
        await asyncio.sleep(1.1)  # wait for window to expire
        assert tracker.current_weight == 0


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_reserves_safe(self, tracker):
        """Multiple concurrent reserves should sum correctly."""
        results = await asyncio.gather(*[tracker.reserve(10) for _ in range(50)])
        assert tracker.current_weight == 500
        assert all(r.ok or r.throttled or r.blocked for r in results)


class TestEstimateCost:
    def test_known_endpoint(self, tracker):
        assert tracker.estimate_cost("fetch_account") == 5
        assert tracker.estimate_cost("load_markets") == 40

    def test_unknown_endpoint_defaults_to_1(self, tracker):
        assert tracker.estimate_cost("some_unknown_method") == 1


class TestEventTypes:
    def test_event_types_registered(self):
        from core.event_log import _VALID_EVENT_TYPES
        assert "rate_limit_throttle" in _VALID_EVENT_TYPES
        assert "rate_limit_block" in _VALID_EVENT_TYPES
