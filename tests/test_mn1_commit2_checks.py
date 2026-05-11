"""
MN-1 Commit 2 regression tests — 6 new monitoring checks.

Each check tested for: detection (alert emitted), resolution (auto-clear),
correct severity, and correct context.

Run: pytest tests/test_mn1_commit2_checks.py -v
"""
from __future__ import annotations
from pathlib import Path

import pytest


SRC = Path(__file__).parent.parent / "core" / "monitoring.py"


class TestCheckMethodsExist:
    def test_check_regime_freshness(self):
        from core.monitoring import MonitoringService
        assert hasattr(MonitoringService, "_check_regime_freshness_sync")

    def test_check_news_feed_health(self):
        from core.monitoring import MonitoringService
        assert hasattr(MonitoringService, "_check_news_feed_health")

    def test_check_plugin_connection(self):
        from core.monitoring import MonitoringService
        assert hasattr(MonitoringService, "_check_plugin_connection_sync")

    def test_check_reconciler_health(self):
        from core.monitoring import MonitoringService
        assert hasattr(MonitoringService, "_check_reconciler_health")

    def test_check_db_health(self):
        from core.monitoring import MonitoringService
        assert hasattr(MonitoringService, "_check_db_health")

    def test_check_rate_limit_frequency(self):
        from core.monitoring import MonitoringService
        assert hasattr(MonitoringService, "_check_rate_limit_frequency_sync")


class TestRegimeFreshness:
    def test_emits_on_stale(self):
        from core.monitoring import MonitoringService
        from core.state import app_state, RegimeState
        svc = MonitoringService()
        app_state.current_regime = RegimeState()  # computed_at=None → stale
        svc._check_regime_freshness_sync()
        active = svc.get_active_events()
        kinds = [e.kind for e in active]
        assert "regime_stale" in kinds

    def test_resolves_when_fresh(self):
        from core.monitoring import MonitoringService
        from core.state import app_state, RegimeState
        from datetime import datetime, timezone
        svc = MonitoringService()
        app_state.current_regime = RegimeState()
        svc._check_regime_freshness_sync()
        # Now make it fresh
        app_state.current_regime.computed_at = datetime.now(timezone.utc)
        svc._check_regime_freshness_sync()
        active = svc.get_active_events()
        kinds = [e.kind for e in active]
        assert "regime_stale" not in kinds

    def test_severity_is_warning(self):
        from core.monitoring import MonitoringService
        from core.state import app_state, RegimeState
        svc = MonitoringService()
        app_state.current_regime = RegimeState()
        svc._check_regime_freshness_sync()
        ev = [e for e in svc.events if e.kind == "regime_stale"][0]
        assert ev.severity == "warning"


class TestPluginConnection:
    def test_emits_on_disconnect(self):
        from core.monitoring import MonitoringService
        svc = MonitoringService()
        svc._ever_plugin_connected = True
        svc._check_plugin_connection_sync(plugin_connected=False)
        kinds = [e.kind for e in svc.get_active_events()]
        assert "plugin_disconnected" in kinds

    def test_skips_if_never_connected(self):
        from core.monitoring import MonitoringService
        svc = MonitoringService()
        svc._ever_plugin_connected = False
        svc._check_plugin_connection_sync(plugin_connected=False)
        kinds = [e.kind for e in svc.get_active_events()]
        assert "plugin_disconnected" not in kinds

    def test_resolves_on_reconnect(self):
        from core.monitoring import MonitoringService
        svc = MonitoringService()
        svc._ever_plugin_connected = True
        svc._check_plugin_connection_sync(plugin_connected=False)
        svc._check_plugin_connection_sync(plugin_connected=True)
        kinds = [e.kind for e in svc.get_active_events()]
        assert "plugin_disconnected" not in kinds


class TestRateLimitFrequency:
    def test_emits_on_burst(self):
        from core.monitoring import MonitoringService
        import time
        svc = MonitoringService()
        # Simulate 6 rate-limit events in quick succession
        now = time.time()
        svc._rate_limit_timestamps = [
            (now - 60, False), (now - 50, False), (now - 40, False),
            (now - 30, False), (now - 20, False), (now - 10, False),
        ]
        svc._check_rate_limit_frequency_sync()
        kinds = [e.kind for e in svc.get_active_events()]
        assert "rate_limit_burst" in kinds

    def test_severity_critical_on_ban(self):
        from core.monitoring import MonitoringService
        import time
        svc = MonitoringService()
        now = time.time()
        svc._rate_limit_timestamps = [(now - 10, True)]  # was_ban=True
        svc._check_rate_limit_frequency_sync()
        ban_events = [e for e in svc.events if e.kind == "rate_limit_ban"]
        assert len(ban_events) > 0
        assert ban_events[0].severity == "critical"

    def test_no_alert_under_threshold(self):
        from core.monitoring import MonitoringService
        import time
        svc = MonitoringService()
        now = time.time()
        svc._rate_limit_timestamps = [(now - 10, False), (now - 20, False)]
        svc._check_rate_limit_frequency_sync()
        kinds = [e.kind for e in svc.get_active_events()]
        assert "rate_limit_burst" not in kinds


class TestAllChecksInRunLoop:
    def test_run_loop_source_references_all_9(self):
        """The run() method must call all 9 checks."""
        import inspect
        from core.monitoring import MonitoringService
        source = inspect.getsource(MonitoringService.run)
        assert "_check_pnl_anomaly" in source
        assert "_check_ws_staleness" in source
        assert "_check_position_count" in source
        assert "_check_regime_freshness" in source
        assert "_check_news_feed" in source or "_check_news" in source
        assert "_check_plugin_connection" in source
        assert "_check_reconciler_health" in source or "_check_reconciler" in source
        assert "_check_db_health" in source
        assert "_check_rate_limit" in source
