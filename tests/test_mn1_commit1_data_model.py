"""
MN-1 Commit 1 regression tests — MonitoringEvent data model + infrastructure.

Validates:
1. MonitoringEvent dataclass exists with correct fields
2. MonitoringService has event ring buffer + emit/resolve API
3. API endpoint /api/monitoring/events exists
4. Existing 3 checks still work (backward compat)

Run: pytest tests/test_mn1_commit1_data_model.py -v
"""
from __future__ import annotations
from pathlib import Path

import pytest


class TestMonitoringEventDataclass:
    def test_importable(self):
        from core.monitoring import MonitoringEvent
        ev = MonitoringEvent(
            kind="test", severity="warning", message="test msg",
        )
        assert ev.kind == "test"
        assert ev.severity == "warning"
        assert ev.resolved is False

    def test_has_context_field(self):
        from core.monitoring import MonitoringEvent
        ev = MonitoringEvent(kind="t", severity="info", message="m",
                             context={"key": "val"})
        assert ev.context["key"] == "val"

    def test_default_context_empty(self):
        from core.monitoring import MonitoringEvent
        ev = MonitoringEvent(kind="t", severity="info", message="m")
        assert ev.context == {}

    def test_has_timestamp(self):
        from core.monitoring import MonitoringEvent
        from datetime import datetime, timezone
        ev = MonitoringEvent(kind="t", severity="info", message="m",
                             timestamp=datetime.now(timezone.utc))
        assert ev.timestamp is not None

    def test_resolved_at_field(self):
        from core.monitoring import MonitoringEvent
        ev = MonitoringEvent(kind="t", severity="info", message="m")
        assert ev.resolved_at is None


class TestEventBuffer:
    def test_service_has_events_list(self):
        from core.monitoring import MonitoringService
        svc = MonitoringService()
        assert hasattr(svc, "events")
        assert isinstance(svc.events, list)

    def test_emit_adds_event(self):
        from core.monitoring import MonitoringService
        svc = MonitoringService()
        svc.emit("test_kind", "warning", "test message")
        assert len(svc.events) == 1
        assert svc.events[0].kind == "test_kind"
        assert svc.events[0].severity == "warning"

    def test_buffer_max_size(self):
        from core.monitoring import MonitoringService
        svc = MonitoringService()
        for i in range(150):
            svc.emit(f"kind_{i}", "info", f"msg {i}")
        assert len(svc.events) <= 100

    def test_resolve_by_kind(self):
        from core.monitoring import MonitoringService
        svc = MonitoringService()
        svc.emit("stale_check", "warning", "stale")
        assert not svc.events[0].resolved
        svc.resolve("stale_check")
        assert svc.events[0].resolved
        assert svc.events[0].resolved_at is not None

    def test_active_events(self):
        from core.monitoring import MonitoringService
        svc = MonitoringService()
        svc.emit("a", "warning", "active")
        svc.emit("b", "info", "also active")
        svc.emit("c", "warning", "will resolve")
        svc.resolve("c")
        active = svc.get_active_events()
        kinds = [e.kind for e in active]
        assert "a" in kinds
        assert "b" in kinds
        assert "c" not in kinds


class TestExistingChecksBackwardCompat:
    def test_pnl_check_exists(self):
        from core.monitoring import MonitoringService
        assert hasattr(MonitoringService, "_check_pnl_anomaly")

    def test_ws_stale_check_exists(self):
        from core.monitoring import MonitoringService
        assert hasattr(MonitoringService, "_check_ws_staleness")

    def test_position_count_check_exists(self):
        from core.monitoring import MonitoringService
        assert hasattr(MonitoringService, "_check_position_count")


class TestApiEndpoint:
    def test_monitoring_events_route_exists(self):
        src = Path(__file__).parent.parent / "api"
        # Check any route file or the router for /api/monitoring
        found = False
        for py in src.glob("*.py"):
            if "monitoring" in py.read_text():
                found = True
                break
        # Also check core/monitoring.py for route registration
        mon_src = Path(__file__).parent.parent / "core" / "monitoring.py"
        if "monitoring/events" in mon_src.read_text():
            found = True
        assert found, "/api/monitoring/events endpoint must be defined"
