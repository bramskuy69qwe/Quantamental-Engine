"""Tests for the state-machine test harness + fixture loader + TestClock."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from textwrap import dedent

import pytest

from core.test_clock import TestClock
from tests.state_machine.harness import Fixture, RunResult, load_fixture, run

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── Stub evaluator ───────────────────────────────────────────────────────────
# Simple threshold evaluator for harness validation.
# Does NOT model real DD policy — just validates harness mechanics.

def stub_evaluator(state: str, equity: float, _clock: TestClock) -> str:
    if equity < 8800:
        return "limit"
    if equity < 9300:
        return "warning"
    return "ok"


# ── TestClock ─────────────────────────────────────────────────────────────────


class TestTestClock:
    def test_default_start(self):
        c = TestClock()
        assert c.now() == datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_custom_start(self):
        dt = datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc)
        c = TestClock(start=dt)
        assert c.now() == dt

    def test_advance(self):
        c = TestClock()
        new = c.advance(3600)  # 1 hour
        assert new == datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
        assert c.now() == new

    def test_advance_fractional(self):
        c = TestClock()
        c.advance(1.5)
        expected = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=1.5)
        assert c.now() == expected

    def test_set(self):
        c = TestClock()
        target = datetime(2030, 12, 31, tzinfo=timezone.utc)
        c.set(target)
        assert c.now() == target


# ── Fixture loader ────────────────────────────────────────────────────────────


class TestLoadFixture:
    def test_parses_slow_drift(self):
        f = load_fixture(FIXTURES_DIR / "01_slow_drift.csv")
        assert len(f.equity_series) == 20
        assert f.equity_series[0][1] == 10000.0
        assert f.equity_series[-1][1] == 8500.0
        assert len(f.checkpoints) == 3
        assert len(f.overrides) == 0

    def test_parses_recovery(self):
        f = load_fixture(FIXTURES_DIR / "02_recovery.csv")
        assert len(f.equity_series) == 12
        assert len(f.checkpoints) == 2
        assert len(f.overrides) == 1
        assert f.overrides[0][1] == "manual_override"
        assert f.overrides[0][2] == {"reason": "tilt recovery"}

    def test_malformed_missing_section_header(self, tmp_path):
        bad = tmp_path / "bad.csv"
        bad.write_text("2026-01-01T00:00:00+00:00,10000\n")
        with pytest.raises(ValueError, match="data before first section"):
            load_fixture(bad)

    def test_malformed_unknown_section(self, tmp_path):
        bad = tmp_path / "bad.csv"
        bad.write_text("# nonsense\n2026-01-01,100\n")
        with pytest.raises(ValueError, match="unknown section"):
            load_fixture(bad)

    def test_malformed_bad_equity_value(self, tmp_path):
        bad = tmp_path / "bad.csv"
        bad.write_text("# equity\ntimestamp,equity\n2026-01-01,not_a_number\n")
        with pytest.raises(ValueError, match="bad.csv:3"):
            load_fixture(bad)

    def test_empty_equity_raises(self, tmp_path):
        bad = tmp_path / "bad.csv"
        bad.write_text("# equity\ntimestamp,equity\n# checkpoints\n")
        with pytest.raises(ValueError, match="no equity data"):
            load_fixture(bad)

    def test_overrides_optional(self, tmp_path):
        f = tmp_path / "minimal.csv"
        f.write_text(dedent("""\
            # equity
            timestamp,equity
            2026-01-01T00:00:00+00:00,10000
            # checkpoints
            timestamp,expected_state
            2026-01-01T00:00:00+00:00,ok
        """))
        fixture = load_fixture(f)
        assert len(fixture.overrides) == 0
        assert len(fixture.checkpoints) == 1


# ── Run: slow drift ──────────────────────────────────────────────────────────


class TestRunSlowDrift:
    @pytest.fixture
    def result(self):
        f = load_fixture(FIXTURES_DIR / "01_slow_drift.csv")
        clock = TestClock()
        return run(f, stub_evaluator, clock)

    def test_no_checkpoint_failures(self, result: RunResult):
        assert result.checkpoint_failures == []

    def test_final_state_is_limit(self, result: RunResult):
        assert result.final_state == "limit"

    def test_transitions_present(self, result: RunResult):
        # ok → warning → limit (two transitions)
        assert len(result.transitions) == 2
        _, from1, to1 = result.transitions[0]
        _, from2, to2 = result.transitions[1]
        assert (from1, to1) == ("ok", "warning")
        assert (from2, to2) == ("warning", "limit")

    def test_transition_timestamps_ordered(self, result: RunResult):
        ts_list = [t[0] for t in result.transitions]
        assert ts_list == sorted(ts_list)


# ── Run: recovery ─────────────────────────────────────────────────────────────


class TestRunRecovery:
    @pytest.fixture
    def result(self):
        f = load_fixture(FIXTURES_DIR / "02_recovery.csv")
        clock = TestClock()
        return run(f, stub_evaluator, clock)

    def test_no_checkpoint_failures(self, result: RunResult):
        assert result.checkpoint_failures == []

    def test_final_state_is_ok(self, result: RunResult):
        assert result.final_state == "ok"

    def test_recovers_through_warning(self, result: RunResult):
        # Should see: ok→warning→limit→warning→ok
        states = ["ok"]
        for _, _from, to in result.transitions:
            states.append(to)
        assert "limit" in states
        assert states[-1] == "ok"

    def test_override_event_recorded(self, result: RunResult):
        assert len(result.override_events) == 1
        ts, otype, payload = result.override_events[0]
        assert otype == "manual_override"
        assert payload["reason"] == "tilt recovery"
        assert ts == datetime(2026, 1, 8, tzinfo=timezone.utc)


# ── Checkpoint failure detection ──────────────────────────────────────────────


class TestCheckpointFailure:
    def test_detects_wrong_state(self, tmp_path):
        """Fixture expects 'limit' but stub returns 'ok' at high equity."""
        f_path = tmp_path / "wrong.csv"
        f_path.write_text(dedent("""\
            # equity
            timestamp,equity
            2026-01-01T00:00:00+00:00,10000.0
            # checkpoints
            timestamp,expected_state
            2026-01-01T00:00:00+00:00,limit
        """))
        fixture = load_fixture(f_path)
        clock = TestClock()
        result = run(fixture, stub_evaluator, clock)
        assert len(result.checkpoint_failures) == 1
        assert "expected 'limit'" in result.checkpoint_failures[0]
        assert "got 'ok'" in result.checkpoint_failures[0]
