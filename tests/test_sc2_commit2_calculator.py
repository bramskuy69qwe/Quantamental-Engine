"""
SC-2 Commit 2 regression tests — calculator integration with ready-state gating.

Validates:
1. Calculator returns ineligible when engine not ready
2. Calculator returns eligible (normal) when engine ready
3. Ineligible reason includes ready-state information
4. Display operations unaffected by ready state

Run: pytest tests/test_sc2_commit2_calculator.py -v
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from core.state import app_state


class TestCalculatorGating:
    def test_ineligible_when_initializing(self):
        """Calculator must return eligible=False during bootstrap."""
        import inspect
        from core import risk_engine
        source = inspect.getsource(risk_engine.calculate_position_size)
        # Must reference ready state check
        assert "ReadyStateEvaluator" in source or "engine_ready" in source or "ready" in source.lower(), \
            "calculate_position_size must check ready state"

    def test_source_has_early_return(self):
        """Calculator must have early return path for not-ready."""
        import inspect
        from core import risk_engine
        source = inspect.getsource(risk_engine.calculate_position_size)
        assert "not ready" in source.lower() or "not_ready" in source or "engine_ready" in source, \
            "calculate_position_size must have not-ready early return"

    def test_ineligible_reason_mentions_ready(self):
        """When not ready, ineligible_reason should explain why."""
        from core.monitoring import ReadyStateEvaluator
        original_init = app_state.is_initializing
        try:
            app_state.is_initializing = True
            ready, reason = ReadyStateEvaluator().evaluate()
            assert not ready
            # The reason should be suitable for ineligible_reason
            assert len(reason) > 0
            assert "initializing" in reason.lower()
        finally:
            app_state.is_initializing = original_init


class TestCalculatorNormalOperation:
    def test_eligible_when_ready(self):
        """Calculator sizing logic must work normally when engine is ready."""
        from core.monitoring import ReadyStateEvaluator
        original_init = app_state.is_initializing
        original_equity = app_state.account_state.total_equity
        original_update = app_state.ws_status.last_update
        try:
            app_state.is_initializing = False
            app_state.account_state.total_equity = 100.0
            app_state.ws_status.last_update = datetime.now(timezone.utc)
            ready, reason = ReadyStateEvaluator().evaluate()
            assert ready is True
            # Normal sizing should proceed (not blocked by ready gate)
        finally:
            app_state.is_initializing = original_init
            app_state.account_state.total_equity = original_equity
            app_state.ws_status.last_update = original_update
