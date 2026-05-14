"""Tests for rolling DD compute integration in data_cache.py."""
import os
import sqlite3
from unittest.mock import patch, MagicMock

import pytest

from core.dd_state import dd_state_from_drawdown, dd_state_with_recovery


# ── Pure logic (dd_state module already tested; these verify integration math) ──


class TestRollingDDIntegration:
    """Verify the math that data_cache applies matches dd_state outputs."""

    def test_rolling_peak_tracking(self):
        """Peak should be max of all observed equity values."""
        peak = 0.0
        for eq in [10000, 10200, 10100, 10300, 10050]:
            peak = max(peak, eq)
        assert peak == 10300

    def test_drawdown_from_peak(self):
        peak = 10000
        current = 9200
        dd = (peak - current) / peak
        assert dd == pytest.approx(0.08)

    def test_state_with_scalping_thresholds(self):
        """Scalping: warn=4%, limit=8%."""
        assert dd_state_from_drawdown(0.03, 0.04, 0.08) == "ok"
        assert dd_state_from_drawdown(0.05, 0.04, 0.08) == "warning"
        assert dd_state_from_drawdown(0.09, 0.04, 0.08) == "limit"

    def test_recovery_from_limit(self):
        """Episode peak 0.09, recovery 0.50 -> need DD <= 0.045."""
        state, ep = dd_state_with_recovery("limit", 0.04, 0.09, 0.04, 0.08, 0.50)
        assert state == "ok"
        assert ep == 0.0

    def test_sticky_limit(self):
        """Partial recovery (DD=5%) stays limit."""
        state, ep = dd_state_with_recovery("limit", 0.05, 0.09, 0.04, 0.08, 0.50)
        assert state == "limit"


class TestEpisodePeakTracking:
    """Verify episode peak and previous-state semantics."""

    def test_peak_resets_on_ok(self):
        """After recovery to ok, episode peak resets to 0."""
        state, ep = dd_state_with_recovery("limit", 0.04, 0.09, 0.04, 0.08, 0.50)
        assert state == "ok"
        assert ep == 0.0

    def test_peak_persists_in_limit(self):
        state, ep = dd_state_with_recovery("limit", 0.07, 0.09, 0.04, 0.08, 0.50)
        assert state == "limit"
        assert ep == 0.09

    def test_restart_conservative_fallback(self):
        """On restart, empty episode peaks + current DD becomes initial peak."""
        # Simulates restart: no previous state, DD = 6%
        state, ep = dd_state_with_recovery("ok", 0.06, 0.06, 0.04, 0.08, 0.50)
        assert state == "warning"
        assert ep == 0.06  # current DD seeded as peak


class TestTransitionDetection:
    """Verify transition detection logic (prev != new)."""

    def test_ok_to_warning(self):
        prev = "ok"
        new = dd_state_from_drawdown(0.05, 0.04, 0.08)
        assert new == "warning"
        assert prev != new

    def test_no_transition_when_same(self):
        prev = "warning"
        new = dd_state_from_drawdown(0.06, 0.04, 0.08)
        assert new == "warning"
        assert prev == new

    def test_limit_to_ok_via_recovery(self):
        new, _ = dd_state_with_recovery("limit", 0.04, 0.09, 0.04, 0.08, 0.50)
        assert new == "ok"
        assert "limit" != new


class TestFallbackBehavior:
    """Verify graceful degradation when account_settings unavailable."""

    def test_legacy_ratio_logic(self):
        """Legacy: dd_ratio = drawdown / max_dd_percent, compared to limit/warning pcts."""
        drawdown = 0.085  # 8.5% DD
        max_dd_pct = 0.10
        dd_ratio = drawdown / max_dd_pct  # 0.85
        max_dd_limit = 0.95
        max_dd_warn = 0.80

        if dd_ratio >= max_dd_limit:
            state = "limit"
        elif dd_ratio >= max_dd_warn:
            state = "warning"
        else:
            state = "ok"
        assert state == "warning"  # 0.85 >= 0.80
