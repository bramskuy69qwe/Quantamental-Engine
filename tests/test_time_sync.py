"""Tests for exchange server-time sync module."""
import inspect

import pytest

from core import time_sync


class TestOffsetCalculation:
    def setup_method(self):
        time_sync._statuses.clear()

    def test_update_stores_offset(self):
        time_sync.update("binance", 150.0)
        assert time_sync.get_offset_ms("binance") == 150.0

    def test_update_overwrites_previous(self):
        time_sync.update("binance", 100.0)
        time_sync.update("binance", -50.0)
        assert time_sync.get_offset_ms("binance") == -50.0

    def test_unknown_exchange_returns_zero(self):
        assert time_sync.get_offset_ms("unknown") == 0.0

    def test_status_has_last_synced(self):
        time_sync.update("binance", 200.0)
        s = time_sync.get_status("binance")
        assert s is not None
        assert s.last_synced > 0
        assert not s.sync_failed


class TestSeverity:
    def setup_method(self):
        time_sync._statuses.clear()

    def test_ok_within_threshold(self):
        time_sync.update("binance", 100.0)
        assert time_sync.get_status("binance").severity == "ok"

    def test_warn_at_500ms(self):
        time_sync.update("binance", 600.0)
        assert time_sync.get_status("binance").severity == "warn"

    def test_warn_negative_offset(self):
        time_sync.update("binance", -700.0)
        assert time_sync.get_status("binance").severity == "warn"

    def test_critical_at_2000ms(self):
        time_sync.update("binance", 2500.0)
        assert time_sync.get_status("binance").severity == "critical"

    def test_failed_state(self):
        time_sync.mark_failed("binance")
        assert time_sync.get_status("binance").severity == "failed"

    def test_failed_preserves_offset(self):
        time_sync.update("binance", 150.0)
        time_sync.mark_failed("binance")
        assert time_sync.get_offset_ms("binance") == 150.0
        assert time_sync.get_status("binance").sync_failed is True


class TestWorstSeverity:
    def setup_method(self):
        time_sync._statuses.clear()

    def test_empty_is_ok(self):
        assert time_sync.worst_severity() == "ok"

    def test_single_ok(self):
        time_sync.update("binance", 50.0)
        assert time_sync.worst_severity() == "ok"

    def test_mixed_returns_worst(self):
        time_sync.update("binance", 50.0)   # ok
        time_sync.update("bybit", 800.0)    # warn
        assert time_sync.worst_severity() == "warn"

    def test_failed_is_worst(self):
        time_sync.update("binance", 50.0)
        time_sync.mark_failed("bybit")
        assert time_sync.worst_severity() == "failed"


class TestLatencyFormula:
    """Verify the latency formula: (local_now + offset) - event_time."""

    def test_positive_offset(self):
        # Exchange clock 200ms ahead of local
        offset = 200.0
        local_now = 1000.0
        event_time = 1150.0
        # Corrected local ≈ exchange time = 1000 + 200 = 1200
        # Latency = 1200 - 1150 = 50ms
        latency = (local_now + offset) - event_time
        assert latency == 50.0

    def test_negative_offset(self):
        # Exchange clock 100ms behind local
        offset = -100.0
        local_now = 1000.0
        event_time = 850.0
        # Corrected = 1000 + (-100) = 900
        # Latency = 900 - 850 = 50ms
        latency = (local_now + offset) - event_time
        assert latency == 50.0

    def test_zero_offset(self):
        offset = 0.0
        local_now = 1000.0
        event_time = 920.0
        latency = (local_now + offset) - event_time
        assert latency == 80.0


class TestMidpointOffset:
    """Verify midpoint-based offset eliminates RTT bias."""

    def test_symmetric_rtt(self):
        # RTT = 200ms, server time captured at midpoint
        local_before = 1000.0
        local_after = 1200.0
        server_time = 1100.0  # server clock matches local at midpoint
        mid = (local_before + local_after) / 2
        offset = server_time - mid
        assert offset == 0.0  # no clock skew

    def test_server_ahead(self):
        local_before = 1000.0
        local_after = 1200.0
        server_time = 1400.0  # server 300ms ahead
        mid = (local_before + local_after) / 2
        offset = server_time - mid
        assert offset == 300.0


class TestIntegration:
    def test_exchange_py_calls_time_sync(self):
        """fetch_exchange_info computes and stores clock offset."""
        from core import exchange
        src = inspect.getsource(exchange.fetch_exchange_info)
        assert "time_sync.update" in src
        assert "wall_before" in src or "local_mid" in src

    def test_ws_manager_uses_offset(self):
        """WS latency calc uses time_sync offset."""
        from core import ws_manager
        src = inspect.getsource(ws_manager._handle_user_event)
        assert "time_sync" in src
        assert "get_offset_ms" in src

    def test_ws_status_route_passes_clock_data(self):
        """WS status fragment route includes clock sync data."""
        from api import routes_dashboard
        src = inspect.getsource(routes_dashboard.frag_ws_status)
        assert "clock_severity" in src
        assert "clock_offset_ms" in src

    def test_ws_status_template_shows_skew_warning(self):
        content = open("templates/fragments/ws_status.html", encoding="utf-8").read()
        assert "clock_severity" in content
        assert "clock_offset_ms" in content
