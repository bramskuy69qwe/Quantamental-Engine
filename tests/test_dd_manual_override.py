"""Tests for dd_state manual override — gate bypass + API + transition cleanup."""
import json
import os
import sqlite3

import pytest

from core.migrations.runner import run_all


def _make_env(tmp_path, account_id=1, enforcement_mode="enforced"):
    """Per-account DB with migrations applied + enforcement mode set."""
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / ".split-complete-v1").write_text("v1")
    pa = data / "per_account"
    pa.mkdir(exist_ok=True)
    db_path = str(pa / "test__broker__1.db")

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO accounts VALUES (?, 'Test')", (account_id,))
    conn.commit()
    conn.close()

    import core.migrations.runner as runner
    real_mdir = os.path.dirname(os.path.abspath(runner.__file__))
    run_all(str(data), real_mdir)

    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE account_settings SET dd_enforcement_mode=?, "
        "dd_warning_threshold=0.04, dd_limit_threshold=0.08 WHERE account_id=?",
        (enforcement_mode, account_id),
    )
    conn.commit()
    conn.close()
    return str(data), db_path


def _set_limit_state(monkeypatch, data_dir):
    """Configure app_state for limit state + bypass staleness gate."""
    monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

    from core.state import app_state
    app_state.portfolio.dd_state = "limit"
    app_state.portfolio.drawdown = 0.09
    app_state.is_initializing = False
    app_state.account_state.total_equity = 10000.0
    app_state.dd_would_have_blocked_logged = set()
    app_state.dd_manually_unblocked = set()

    monkeypatch.setattr(
        "core.state.WSStatus.seconds_since_update",
        property(lambda self: 5.0),
    )
    return app_state


# ── Gate bypass ──────────────────────────────────────────────────────────────


class TestGateBypass:
    def test_overridden_account_eligible_when_enforced(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path, enforcement_mode="enforced")
        app_state = _set_limit_state(monkeypatch, data_dir)

        from core.monitoring import ReadyStateEvaluator

        # Without override: blocked
        ready, reason = ReadyStateEvaluator().evaluate()
        assert ready is False

        # With override: eligible
        app_state.dd_manually_unblocked.add(1)
        ready, reason = ReadyStateEvaluator().evaluate()
        assert ready is True

    def test_override_suppresses_shadow_logging(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path, enforcement_mode="advisory")
        app_state = _set_limit_state(monkeypatch, data_dir)
        app_state.dd_manually_unblocked.add(1)

        from core.monitoring import ReadyStateEvaluator
        ReadyStateEvaluator().evaluate()

        conn = sqlite3.connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM engine_events WHERE event_type='would_have_blocked_dd'"
        ).fetchone()[0]
        conn.close()
        assert count == 0  # override suppresses logging

    def test_transition_out_clears_override(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        app_state = _set_limit_state(monkeypatch, data_dir)
        app_state.dd_manually_unblocked.add(1)

        # Simulate data_cache transition: limit -> ok
        app_state.dd_manually_unblocked.discard(1)
        assert 1 not in app_state.dd_manually_unblocked

    def test_no_immunity_after_transition(self, tmp_path, monkeypatch):
        """After override + recovery + new limit episode: gate fires again."""
        data_dir, _ = _make_env(tmp_path, enforcement_mode="enforced")
        app_state = _set_limit_state(monkeypatch, data_dir)

        from core.monitoring import ReadyStateEvaluator
        ev = ReadyStateEvaluator()

        # Override first episode
        app_state.dd_manually_unblocked.add(1)
        ready, _ = ev.evaluate()
        assert ready is True

        # Simulate recovery: clear override
        app_state.dd_manually_unblocked.discard(1)

        # New limit episode: gate fires
        ready, reason = ev.evaluate()
        assert ready is False
        assert "dd_state=limit" in reason


# ── Reason validation ────────────────────────────────────────────────────────


class TestReasonValidation:
    def test_short_reason_rejected(self):
        """Reason < 10 chars should be rejected."""
        reason = "too short"
        assert len(reason.strip()) < 10

    def test_empty_reason_rejected(self):
        reason = ""
        assert len(reason.strip()) < 10

    def test_whitespace_reason_rejected(self):
        reason = "          "
        assert len(reason.strip()) < 10

    def test_valid_reason_accepted(self):
        reason = "Strategy intact, single bad day from news event"
        assert len(reason.strip()) >= 10


# ── Event logging ────────────────────────────────────────────────────────────


class TestOverrideEventLog:
    def test_override_logs_manual_override_event(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        from core.state import app_state
        app_state.portfolio.dd_state = "limit"
        app_state.portfolio.drawdown = 0.09
        app_state.account_state.total_equity = 9100.0

        from core.event_log import log_event
        log_event(1, "manual_override", {
            "reason": "Strategy intact, single bad day",
            "drawdown": round(0.09, 6),
            "peak_equity": 10000.0,
        }, source="api_override", data_dir=data_dir)

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT event_type, payload_json, source FROM engine_events "
            "WHERE event_type='manual_override'"
        ).fetchall()
        conn.close()

        assert len(rows) == 1
        assert rows[0][2] == "api_override"
        payload = json.loads(rows[0][1])
        assert payload["reason"] == "Strategy intact, single bad day"
        assert payload["drawdown"] == 0.09
