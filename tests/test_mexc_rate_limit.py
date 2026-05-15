"""Tests for MEXC rate limit calibration + constants extraction."""
import asyncio

import pytest

from core.adapters.mexc.rest_adapter import MexcLinearAdapter
from core.adapters.mexc.constants import (
    MAX_REQUESTS_WINDOW,
    RATE_LIMIT_WINDOW_SECONDS,
    RATE_LIMIT_ERROR_CODE,
    OHLCV_LIMIT,
    BASE_URL,
)


class TestConstants:
    def test_max_requests(self):
        assert MAX_REQUESTS_WINDOW == 20

    def test_window_seconds(self):
        assert RATE_LIMIT_WINDOW_SECONDS == 2

    def test_error_code(self):
        assert RATE_LIMIT_ERROR_CODE == 510

    def test_ohlcv_limit(self):
        assert OHLCV_LIMIT == 2000

    def test_base_url(self):
        assert BASE_URL == "https://contract.mexc.com"


class TestTrackerCalibration:
    def test_tracker_uses_mexc_params(self):
        adapter = MexcLinearAdapter("", "", "")
        tracker = adapter._weight_tracker
        assert tracker is not None
        assert tracker.max_weight == 20
        assert tracker.window_seconds == 2

    @pytest.mark.asyncio
    async def test_16_requests_within_normal_budget(self):
        """Normal throttles at 85% of 20 = 17. First 16 (80%) pass clean."""
        adapter = MexcLinearAdapter("", "", "")
        tracker = adapter._weight_tracker
        for i in range(16):
            r = await tracker.reserve(1, priority="normal")
            assert r.ok is True, f"Request {i+1} should be ok"
            assert r.throttled is False, f"Request {i+1} shouldn't throttle"

    @pytest.mark.asyncio
    async def test_21st_normal_throttled(self):
        """21st request at normal priority should throttle (>85% = >17)."""
        adapter = MexcLinearAdapter("", "", "")
        tracker = adapter._weight_tracker
        for _ in range(17):
            await tracker.reserve(1)
        r = await tracker.reserve(1, priority="normal")
        assert r.throttled is True  # 18/20 = 90% > 85%

    @pytest.mark.asyncio
    async def test_21st_urgent_proceeds(self):
        """Even at 100%, urgent priority proceeds."""
        adapter = MexcLinearAdapter("", "", "")
        tracker = adapter._weight_tracker
        for _ in range(20):
            await tracker.reserve(1)
        r = await tracker.reserve(1, priority="urgent")
        assert r.ok is True
        assert r.blocked is False

    @pytest.mark.asyncio
    async def test_background_blocks_at_85pct(self):
        """Background blocks at 85% of 20 = 17."""
        adapter = MexcLinearAdapter("", "", "")
        tracker = adapter._weight_tracker
        for _ in range(17):
            await tracker.reserve(1)
        r = await tracker.reserve(1, priority="background")
        assert r.blocked is True  # 18/20 = 90% > 85%

    @pytest.mark.asyncio
    async def test_window_resets_after_2s(self):
        """Counter resets after 2-second window."""
        adapter = MexcLinearAdapter("", "", "")
        tracker = adapter._weight_tracker
        for _ in range(15):
            await tracker.reserve(1)
        assert tracker.current_weight == 15
        await asyncio.sleep(2.1)
        assert tracker.current_weight == 0


class TestEndpointCosts:
    def test_all_costs_default_to_1(self):
        """MEXC uses count-based limits — all endpoints cost 1."""
        adapter = MexcLinearAdapter("", "", "")
        tracker = adapter._weight_tracker
        for endpoint in ["fetch_balance", "fetch_positions", "fetch_open_orders",
                          "fetch_my_trades", "fetch_ohlcv", "load_markets"]:
            assert tracker.estimate_cost(endpoint) == 1
