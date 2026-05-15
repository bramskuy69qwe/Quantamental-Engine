"""Tests for priority-aware fan-out coordination."""
import asyncio

import pytest

from core.rate_limit.weight_tracker import WeightTracker


@pytest.fixture
def tracker():
    return WeightTracker(adapter_name="test", max_weight=1200, window_seconds=60)


class TestUrgentPriority:
    @pytest.mark.asyncio
    async def test_urgent_at_96pct_proceeds(self, tracker):
        """Urgent never blocks — warns but ok=True."""
        await tracker.reserve(1150)  # 95.8%
        result = await tracker.reserve(2, priority="urgent")
        assert result.ok is True
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_urgent_at_extreme_still_proceeds(self, tracker):
        """Even at 100%+ urgent proceeds (block threshold > 100%)."""
        await tracker.reserve(1190)
        result = await tracker.reserve(20, priority="urgent")  # 100.8%
        assert result.ok is True


class TestNormalPriority:
    @pytest.mark.asyncio
    async def test_normal_at_96pct_blocked(self, tracker):
        """Normal blocks at 95%."""
        await tracker.reserve(1100)  # pre-fill
        result = await tracker.reserve(50, priority="normal")  # 95.8%
        assert result.blocked is True
        assert result.ok is False

    @pytest.mark.asyncio
    async def test_normal_at_75pct_ok(self, tracker):
        """Normal passes below 85%."""
        result = await tracker.reserve(900, priority="normal")  # 75%
        assert result.ok is True
        assert result.throttled is False

    @pytest.mark.asyncio
    async def test_normal_at_88pct_throttled(self, tracker):
        """Normal throttles between 85–95%."""
        await tracker.reserve(1000)
        result = await tracker.reserve(60, priority="normal")  # 88.3%
        assert result.ok is True
        assert result.throttled is True
        assert result.delay_ms > 0


class TestBackgroundPriority:
    @pytest.mark.asyncio
    async def test_background_at_88pct_blocked(self, tracker):
        """Background blocks at 85%."""
        await tracker.reserve(1000)
        result = await tracker.reserve(60, priority="background")  # 88.3%
        assert result.blocked is True

    @pytest.mark.asyncio
    async def test_background_at_75pct_throttled(self, tracker):
        """Background throttles at 70%."""
        result = await tracker.reserve(900, priority="background")  # 75%
        assert result.ok is True
        assert result.throttled is True
        assert result.delay_ms > 0

    @pytest.mark.asyncio
    async def test_background_at_60pct_ok(self, tracker):
        """Background passes below 70%."""
        result = await tracker.reserve(720, priority="background")  # 60%
        assert result.ok is True
        assert result.throttled is False


class TestConcurrentPriorities:
    @pytest.mark.asyncio
    async def test_mixed_priorities_at_92pct(self, tracker):
        """At 92%: urgent proceeds, normal throttles, background blocks."""
        await tracker.reserve(1100)  # pre-fill to ~91.7%

        urgent_r = await tracker.reserve(5, priority="urgent")
        assert urgent_r.ok is True
        assert urgent_r.blocked is False

        normal_r = await tracker.reserve(5, priority="normal")
        # 1110/1200 = 92.5% → normal throttles (85-95 range)
        assert normal_r.ok is True
        assert normal_r.throttled is True

        bg_r = await tracker.reserve(5, priority="background")
        # 1115/1200 = 92.9% → background blocks (>85%)
        assert bg_r.ok is False
        assert bg_r.blocked is True


class TestPriorityDefault:
    @pytest.mark.asyncio
    async def test_default_is_normal(self, tracker):
        result = await tracker.reserve(100)  # no priority arg
        assert result.priority == "normal"


class TestReserveResultIncludesPriority:
    @pytest.mark.asyncio
    async def test_priority_in_result(self, tracker):
        r = await tracker.reserve(10, priority="background")
        assert r.priority == "background"

    @pytest.mark.asyncio
    async def test_urgent_in_result(self, tracker):
        r = await tracker.reserve(10, priority="urgent")
        assert r.priority == "urgent"


class TestBackwardCompatibility:
    @pytest.mark.asyncio
    async def test_existing_tests_still_work(self, tracker):
        """Original reserve behavior preserved when priority=normal."""
        r1 = await tracker.reserve(10)
        assert r1.ok is True
        assert tracker.current_weight == 10

        tracker.reconcile(50)
        assert tracker.current_weight == 50

        assert tracker.estimate_cost("fetch_account") == 5
        assert tracker.estimate_cost("unknown") == 1
