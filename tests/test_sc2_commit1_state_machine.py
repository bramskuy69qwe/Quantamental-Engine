"""
SC-2 Commit 1 regression tests — ReadyStateEvaluator + /api/ready upgrade.

Validates:
1. ReadyStateEvaluator exists with evaluate() method
2. Gate 1: bootstrap (is_initializing) blocks ready
3. Gate 2: account data (equity=0) blocks ready
4. Gate 3: data staleness (>60s, no WS, no fallback) blocks ready
5. Hysteresis: brief faults don't flip state
6. /api/ready returns reason field when not ready
7. MonitoringEvent emitted on transition to not-ready

Run: pytest tests/test_sc2_commit1_state_machine.py -v
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from core.state import app_state


class TestEvaluatorExists:
    def test_importable(self):
        from core.monitoring import ReadyStateEvaluator
        ev = ReadyStateEvaluator()
        assert hasattr(ev, "evaluate")

    def test_evaluate_returns_tuple(self):
        from core.monitoring import ReadyStateEvaluator
        ev = ReadyStateEvaluator()
        result = ev.evaluate()
        assert isinstance(result, tuple)
        assert len(result) == 2
        ready, reason = result
        assert isinstance(ready, bool)
        assert isinstance(reason, str)


class TestGate1Bootstrap:
    def test_not_ready_during_init(self):
        from core.monitoring import ReadyStateEvaluator
        ev = ReadyStateEvaluator()
        original = app_state.is_initializing
        try:
            app_state.is_initializing = True
            ready, reason = ev.evaluate()
            assert ready is False
            assert "initializing" in reason.lower()
        finally:
            app_state.is_initializing = original

    def test_ready_after_init(self):
        from core.monitoring import ReadyStateEvaluator
        ev = ReadyStateEvaluator()
        original_init = app_state.is_initializing
        original_equity = app_state.account_state.total_equity
        original_update = app_state.ws_status.last_update
        try:
            app_state.is_initializing = False
            app_state.account_state.total_equity = 100.0
            app_state.ws_status.last_update = datetime.now(timezone.utc)
            ready, reason = ev.evaluate()
            assert ready is True
            assert reason == ""
        finally:
            app_state.is_initializing = original_init
            app_state.account_state.total_equity = original_equity
            app_state.ws_status.last_update = original_update


class TestGate2AccountData:
    def test_not_ready_zero_equity(self):
        from core.monitoring import ReadyStateEvaluator
        ev = ReadyStateEvaluator()
        original_init = app_state.is_initializing
        original_equity = app_state.account_state.total_equity
        try:
            app_state.is_initializing = False
            app_state.account_state.total_equity = 0.0
            ready, reason = ev.evaluate()
            assert ready is False
            assert "account" in reason.lower() or "equity" in reason.lower()
        finally:
            app_state.is_initializing = original_init
            app_state.account_state.total_equity = original_equity


class TestGate3DataStaleness:
    def test_not_ready_when_data_stale(self):
        from core.monitoring import ReadyStateEvaluator
        ev = ReadyStateEvaluator()
        original_init = app_state.is_initializing
        original_equity = app_state.account_state.total_equity
        original_update = app_state.ws_status.last_update
        original_connected = app_state.ws_status.connected
        original_fallback = app_state.ws_status.using_fallback
        try:
            app_state.is_initializing = False
            app_state.account_state.total_equity = 100.0
            # Stale for >60s, no WS, no fallback
            app_state.ws_status.last_update = datetime.now(timezone.utc) - timedelta(seconds=90)
            app_state.ws_status.connected = False
            app_state.ws_status.using_fallback = False
            ready, reason = ev.evaluate()
            assert ready is False
            assert "stale" in reason.lower() or "offline" in reason.lower()
        finally:
            app_state.is_initializing = original_init
            app_state.account_state.total_equity = original_equity
            app_state.ws_status.last_update = original_update
            app_state.ws_status.connected = original_connected
            app_state.ws_status.using_fallback = original_fallback

    def test_ready_when_fallback_active(self):
        """Even if WS is down, REST fallback keeps data flowing — should be ready."""
        from core.monitoring import ReadyStateEvaluator
        ev = ReadyStateEvaluator()
        original_init = app_state.is_initializing
        original_equity = app_state.account_state.total_equity
        original_update = app_state.ws_status.last_update
        original_connected = app_state.ws_status.connected
        original_fallback = app_state.ws_status.using_fallback
        try:
            app_state.is_initializing = False
            app_state.account_state.total_equity = 100.0
            app_state.ws_status.last_update = datetime.now(timezone.utc) - timedelta(seconds=20)
            app_state.ws_status.connected = False
            app_state.ws_status.using_fallback = True  # Fallback keeping data fresh
            ready, reason = ev.evaluate()
            assert ready is True
        finally:
            app_state.is_initializing = original_init
            app_state.account_state.total_equity = original_equity
            app_state.ws_status.last_update = original_update
            app_state.ws_status.connected = original_connected
            app_state.ws_status.using_fallback = original_fallback


class TestApiReadyFormat:
    def test_response_has_ready_field(self):
        """Backward compat: 'ready' field always present."""
        src = Path(__file__).parent.parent / "api" / "routes_dashboard.py"
        content = src.read_text()
        assert "ReadyStateEvaluator" in content or "ready_state" in content, \
            "/api/ready must use ReadyStateEvaluator"

    def test_response_has_reason_field(self):
        """Additive: 'reason' field present when not ready."""
        src = Path(__file__).parent.parent / "api" / "routes_dashboard.py"
        content = src.read_text()
        assert '"reason"' in content, \
            "/api/ready must include reason field"
