"""
MN-1a regression test — wire record_rate_limit_event into handle_rate_limit_error.

Validates:
1. handle_rate_limit_error() calls record_rate_limit_event()
2. Check #9 fires when enough events recorded

Run: pytest tests/test_mn1a_rate_limit_wiring.py -v
"""
from __future__ import annotations
from pathlib import Path

import pytest


class TestWiringExists:
    def test_handle_rate_limit_error_calls_record(self):
        """handle_rate_limit_error source must reference record_rate_limit_event."""
        import inspect
        from core.exchange import handle_rate_limit_error
        source = inspect.getsource(handle_rate_limit_error)
        assert "record_rate_limit_event" in source, \
            "handle_rate_limit_error must call record_rate_limit_event"

    def test_record_called_on_429(self):
        """When handle_rate_limit_error fires, monitoring service records the event."""
        from core.state import app_state
        from core.monitoring import MonitoringService
        from core.adapters.errors import RateLimitError

        svc = MonitoringService()
        app_state._monitoring_service = svc

        original_rl = app_state.ws_status.rate_limited_until
        try:
            from core.exchange import handle_rate_limit_error
            exc = RateLimitError("429 test")
            handle_rate_limit_error(exc)

            assert len(svc._rate_limit_timestamps) >= 1, \
                "record_rate_limit_event must be called on 429"
        finally:
            app_state.ws_status.rate_limited_until = original_rl
            app_state._monitoring_service = None

    def test_record_ban_on_418(self):
        """418 with retry_after_ms should record was_ban=True."""
        from core.state import app_state
        from core.monitoring import MonitoringService
        from core.adapters.errors import RateLimitError

        svc = MonitoringService()
        app_state._monitoring_service = svc

        original_rl = app_state.ws_status.rate_limited_until
        try:
            from core.exchange import handle_rate_limit_error
            exc = RateLimitError("418 banned until 9999999999999", retry_after_ms=9999999999999)
            handle_rate_limit_error(exc)

            assert len(svc._rate_limit_timestamps) >= 1
            _, was_ban = svc._rate_limit_timestamps[-1]
            assert was_ban is True, \
                "418 (with retry_after_ms) must record was_ban=True"
        finally:
            app_state.ws_status.rate_limited_until = original_rl
            app_state._monitoring_service = None


class TestCheck9Fires:
    def test_burst_detection_with_wiring(self):
        """Check #9 fires when record_rate_limit_event provides enough events."""
        import time
        from core.monitoring import MonitoringService

        svc = MonitoringService()
        now = time.time()
        # Simulate 6 events via the public API
        for i in range(6):
            svc.record_rate_limit_event(was_ban=False)

        svc._check_rate_limit_frequency_sync()
        kinds = [e.kind for e in svc.get_active_events()]
        assert "rate_limit_burst" in kinds, \
            "Check #9 must fire after 5+ rate-limit events"
