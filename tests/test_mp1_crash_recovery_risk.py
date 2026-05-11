"""
MP-1 regression tests — dd_state + weekly_pnl_state survive restart.

Validates:
1. restore_from_snapshot() restores dd_state and weekly_pnl_state
2. Backward compat: missing/NULL values default to "ok"
3. Pre-fix failure mode: dd_state defaults to "ok" instead of DB value

Run: pytest tests/test_mp1_crash_recovery_risk.py -v
"""
from __future__ import annotations

import pytest

from core.state import app_state


class TestRestoreGateStates:
    def test_dd_state_restored_from_snapshot(self):
        """dd_state must be restored from snapshot, not default to 'ok'."""
        original = app_state.portfolio.dd_state
        try:
            app_state.restore_from_snapshot({
                "total_equity": 100.0,
                "balance_usdt": 100.0,
                "bod_equity": 105.0,
                "sow_equity": 110.0,
                "max_total_equity": 115.0,
                "min_total_equity": 95.0,
                "drawdown": 5.0,
                "dd_state": "limit",
                "weekly_pnl_state": "ok",
            })
            assert app_state.portfolio.dd_state == "limit", \
                "dd_state must be restored from snapshot"
        finally:
            app_state.portfolio.dd_state = original

    def test_weekly_pnl_state_restored_from_snapshot(self):
        """weekly_pnl_state must be restored from snapshot."""
        original = app_state.portfolio.weekly_pnl_state
        try:
            app_state.restore_from_snapshot({
                "total_equity": 100.0,
                "balance_usdt": 100.0,
                "bod_equity": 105.0,
                "sow_equity": 110.0,
                "max_total_equity": 115.0,
                "min_total_equity": 95.0,
                "drawdown": 3.0,
                "dd_state": "ok",
                "weekly_pnl_state": "warning",
            })
            assert app_state.portfolio.weekly_pnl_state == "warning", \
                "weekly_pnl_state must be restored from snapshot"
        finally:
            app_state.portfolio.weekly_pnl_state = original

    def test_both_states_restored_together(self):
        """Both gate states restored in one call."""
        orig_dd = app_state.portfolio.dd_state
        orig_wp = app_state.portfolio.weekly_pnl_state
        try:
            app_state.restore_from_snapshot({
                "total_equity": 80.0,
                "balance_usdt": 80.0,
                "bod_equity": 90.0,
                "sow_equity": 95.0,
                "max_total_equity": 100.0,
                "min_total_equity": 75.0,
                "drawdown": 10.0,
                "dd_state": "warning",
                "weekly_pnl_state": "limit",
            })
            assert app_state.portfolio.dd_state == "warning"
            assert app_state.portfolio.weekly_pnl_state == "limit"
        finally:
            app_state.portfolio.dd_state = orig_dd
            app_state.portfolio.weekly_pnl_state = orig_wp


class TestBackwardCompat:
    def test_missing_dd_state_defaults_ok(self):
        """Old snapshots without dd_state should default to 'ok'."""
        original = app_state.portfolio.dd_state
        try:
            app_state.restore_from_snapshot({
                "total_equity": 100.0,
                "balance_usdt": 100.0,
                # dd_state and weekly_pnl_state NOT in dict
            })
            assert app_state.portfolio.dd_state == "ok"
        finally:
            app_state.portfolio.dd_state = original

    def test_missing_weekly_pnl_state_defaults_ok(self):
        """Old snapshots without weekly_pnl_state should default to 'ok'."""
        original = app_state.portfolio.weekly_pnl_state
        try:
            app_state.restore_from_snapshot({
                "total_equity": 100.0,
                "balance_usdt": 100.0,
            })
            assert app_state.portfolio.weekly_pnl_state == "ok"
        finally:
            app_state.portfolio.weekly_pnl_state = original


class TestSourceInspection:
    def test_restore_function_references_dd_state(self):
        """restore_from_snapshot source must reference dd_state."""
        import inspect
        source = inspect.getsource(app_state.restore_from_snapshot)
        assert "dd_state" in source, \
            "restore_from_snapshot must restore dd_state"

    def test_restore_function_references_weekly_pnl_state(self):
        """restore_from_snapshot source must reference weekly_pnl_state."""
        import inspect
        source = inspect.getsource(app_state.restore_from_snapshot)
        assert "weekly_pnl_state" in source, \
            "restore_from_snapshot must restore weekly_pnl_state"
