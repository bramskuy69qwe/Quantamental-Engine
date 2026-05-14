"""Tests for core.dd_state — pure rolling DD state logic + fixture runs."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.dd_state import (
    compute_rolling_drawdown,
    dd_state_from_drawdown,
    dd_state_with_recovery,
    derive_dd_evaluator,
)
from core.test_clock import TestClock
from tests.state_machine.harness import load_fixture, run

FIXTURES = Path(__file__).parent / "state_machine" / "fixtures"

# Scalping preset thresholds (used by fixtures 03-07)
W = 0.04   # warning
L = 0.08   # limit
R = 0.50   # recovery


# ── compute_rolling_drawdown ─────────────────────────────────────────────────


class TestComputeRollingDrawdown:
    def test_no_drawdown_at_peak(self):
        now = datetime(2026, 1, 5, tzinfo=timezone.utc)
        series = [
            (datetime(2026, 1, 1, tzinfo=timezone.utc), 9000.0),
            (datetime(2026, 1, 2, tzinfo=timezone.utc), 9500.0),
            (datetime(2026, 1, 3, tzinfo=timezone.utc), 10000.0),
        ]
        dd, peak = compute_rolling_drawdown(series, 10000.0, 30, now)
        assert dd == 0.0
        assert peak == 10000.0

    def test_drawdown_from_peak(self):
        now = datetime(2026, 1, 5, tzinfo=timezone.utc)
        series = [
            (datetime(2026, 1, 1, tzinfo=timezone.utc), 10000.0),
            (datetime(2026, 1, 2, tzinfo=timezone.utc), 9500.0),
        ]
        dd, peak = compute_rolling_drawdown(series, 9500.0, 30, now)
        assert dd == pytest.approx(0.05)
        assert peak == 10000.0

    def test_window_filters_old_data(self):
        now = datetime(2026, 1, 15, tzinfo=timezone.utc)
        series = [
            (datetime(2026, 1, 1, tzinfo=timezone.utc), 20000.0),  # outside 7d window
            (datetime(2026, 1, 10, tzinfo=timezone.utc), 10000.0),  # inside
        ]
        dd, peak = compute_rolling_drawdown(series, 9500.0, 7, now)
        assert peak == 10000.0  # 20000 excluded by window
        assert dd == pytest.approx(0.05)

    def test_empty_series(self):
        now = datetime(2026, 1, 5, tzinfo=timezone.utc)
        dd, peak = compute_rolling_drawdown([], 10000.0, 30, now)
        assert dd == 0.0
        assert peak == 10000.0


# ── dd_state_from_drawdown ───────────────────────────────────────────────────


class TestStateMapping:
    def test_below_warning(self):
        assert dd_state_from_drawdown(0.03, W, L) == "ok"

    def test_at_warning(self):
        assert dd_state_from_drawdown(0.04, W, L) == "warning"

    def test_between_warning_and_limit(self):
        assert dd_state_from_drawdown(0.06, W, L) == "warning"

    def test_at_limit(self):
        assert dd_state_from_drawdown(0.08, W, L) == "limit"

    def test_above_limit(self):
        assert dd_state_from_drawdown(0.12, W, L) == "limit"

    def test_zero(self):
        assert dd_state_from_drawdown(0.0, W, L) == "ok"


# ── dd_state_with_recovery ───────────────────────────────────────────────────


class TestRecovery:
    def test_sufficient_recovery_unblocks(self):
        # Episode peak DD = 0.09, recovery = 0.50 → need DD ≤ 0.045
        state, ep = dd_state_with_recovery("limit", 0.04, 0.09, W, L, R)
        assert state == "ok"
        assert ep == 0.0  # episode reset

    def test_insufficient_recovery_stays_limit(self):
        # DD = 0.05, recovery level = 0.045 → 0.05 > 0.045
        state, ep = dd_state_with_recovery("limit", 0.05, 0.09, W, L, R)
        assert state == "limit"
        assert ep == 0.09

    def test_recovery_only_from_limit(self):
        # Previous = "warning", not "limit" → normal mapping
        state, ep = dd_state_with_recovery("warning", 0.04, 0.06, W, L, R)
        assert state == "warning"  # 0.04 ≥ W

    def test_episode_peak_tracks_worst(self):
        # Starting episode_peak = 0.05, current DD = 0.09 → peak becomes 0.09
        state, ep = dd_state_with_recovery("warning", 0.09, 0.05, W, L, R)
        assert state == "limit"
        assert ep == 0.09

    def test_episode_resets_on_ok_from_warning(self):
        # DD = 0.02 → ok, episode resets
        state, ep = dd_state_with_recovery("warning", 0.02, 0.06, W, L, R)
        assert state == "ok"
        assert ep == 0.0


# ── Fixture runs ─────────────────────────────────────────────────────────────


def _run_fixture(name):
    f = load_fixture(FIXTURES / name)
    evaluator = derive_dd_evaluator(W, L, R)
    clock = TestClock()
    return run(f, evaluator, clock)


class TestFixture03SharpDrop:
    @pytest.fixture
    def result(self):
        return _run_fixture("03_sharp_drop.csv")

    def test_checkpoints_pass(self, result):
        assert result.checkpoint_failures == []

    def test_final_state(self, result):
        assert result.final_state == "limit"

    def test_transitions(self, result):
        states = [t[2] for t in result.transitions]
        assert states == ["warning", "limit"]


class TestFixture04RecoveryWithUnblock:
    @pytest.fixture
    def result(self):
        return _run_fixture("04_recovery_with_unblock.csv")

    def test_checkpoints_pass(self, result):
        assert result.checkpoint_failures == []

    def test_final_state(self, result):
        assert result.final_state == "ok"

    def test_recovery_transition(self, result):
        states = [t[2] for t in result.transitions]
        assert "limit" in states
        assert states[-1] == "ok"


class TestFixture05RecoveryWithoutUnblock:
    @pytest.fixture
    def result(self):
        return _run_fixture("05_recovery_without_unblock.csv")

    def test_checkpoints_pass(self, result):
        assert result.checkpoint_failures == []

    def test_stays_limit(self, result):
        assert result.final_state == "limit"


class TestFixture06MultiCycle:
    @pytest.fixture
    def result(self):
        return _run_fixture("06_multi_cycle.csv")

    def test_checkpoints_pass(self, result):
        assert result.checkpoint_failures == []

    def test_two_limit_episodes(self, result):
        limit_count = sum(1 for _, _, to in result.transitions if to == "limit")
        assert limit_count == 2

    def test_two_ok_recoveries(self, result):
        ok_from_limit = sum(
            1 for _, fr, to in result.transitions if fr == "limit" and to == "ok"
        )
        assert ok_from_limit == 2


class TestFixture07ManualOverride:
    @pytest.fixture
    def result(self):
        return _run_fixture("07_manual_override.csv")

    def test_checkpoints_pass(self, result):
        assert result.checkpoint_failures == []

    def test_override_recorded(self, result):
        assert len(result.override_events) == 1
        _, otype, payload = result.override_events[0]
        assert otype == "manual_override"
        assert "reason" in payload

    def test_limit_persists(self, result):
        assert result.final_state == "limit"
