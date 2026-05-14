"""Tests for dd_state calculator gate in ReadyStateEvaluator."""
import json
import os
import sqlite3
from dataclasses import dataclass
from unittest.mock import patch, PropertyMock

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_env(tmp_path, account_id=1, dd_state="ok", enforcement_mode="advisory",
              dd_warning=0.04, dd_limit=0.08, drawdown=0.0):
    """Per-account DB + account_settings + fake AppState portfolio."""
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

    # Apply real migrations for account_settings schema
    import core.migrations.runner as runner
    real_mdir = os.path.dirname(os.path.abspath(runner.__file__))

    from core.migrations.runner import run_all
    run_all(str(data), real_mdir)

    # Set enforcement mode + thresholds
    conn = sqlite3.connect(db_path)
    conn.execute(
        "UPDATE account_settings SET dd_enforcement_mode=?, "
        "dd_warning_threshold=?, dd_limit_threshold=? WHERE account_id=?",
        (enforcement_mode, dd_warning, dd_limit, account_id),
    )
    # engine_events table exists from migration 003
    conn.commit()
    conn.close()

    return str(data), db_path


# ── Gate behavior tests ──────────────────────────────────────────────────────


class TestDDGateAdvisory:
    def test_ok_state_eligible(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path, enforcement_mode="advisory")
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        from core.state import app_state
        app_state.portfolio.dd_state = "ok"
        app_state.portfolio.drawdown = 0.01
        app_state.is_initializing = False
        app_state.account_state.total_equity = 10000.0
        app_state.dd_would_have_blocked_logged = set()

        from core.monitoring import ReadyStateEvaluator
        ready, reason = ReadyStateEvaluator().evaluate()
        # Might fail on Gate 3 (staleness) if WS not connected — that's expected
        # We only care that Gate 4 (DD) doesn't fire
        assert "dd_state" not in reason

    def test_warning_state_eligible(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path, enforcement_mode="advisory")
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        from core.state import app_state
        app_state.portfolio.dd_state = "warning"
        app_state.portfolio.drawdown = 0.05
        app_state.is_initializing = False
        app_state.account_state.total_equity = 10000.0
        app_state.dd_would_have_blocked_logged = set()

        from core.monitoring import ReadyStateEvaluator
        ready, reason = ReadyStateEvaluator().evaluate()
        assert "dd_state" not in reason

    def test_limit_advisory_still_eligible(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path, enforcement_mode="advisory")
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        from core.state import app_state
        app_state.portfolio.dd_state = "limit"
        app_state.portfolio.drawdown = 0.09
        app_state.is_initializing = False
        app_state.account_state.total_equity = 10000.0
        app_state.dd_would_have_blocked_logged = set()

        # Mock staleness gate to pass
        monkeypatch.setattr(
            "core.state.WSStatus.seconds_since_update",
            property(lambda self: 5.0),
        )

        from core.monitoring import ReadyStateEvaluator
        ready, reason = ReadyStateEvaluator().evaluate()
        assert ready is True

    def test_advisory_logs_shadow_event(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path, enforcement_mode="advisory")
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        from core.state import app_state
        app_state.portfolio.dd_state = "limit"
        app_state.portfolio.drawdown = 0.09
        app_state.is_initializing = False
        app_state.account_state.total_equity = 10000.0
        app_state.dd_would_have_blocked_logged = set()

        monkeypatch.setattr(
            "core.state.WSStatus.seconds_since_update",
            property(lambda self: 5.0),
        )

        from core.monitoring import ReadyStateEvaluator
        ReadyStateEvaluator().evaluate()

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT event_type, payload_json FROM engine_events "
            "WHERE event_type='would_have_blocked_dd'"
        ).fetchall()
        conn.close()
        assert len(rows) == 1
        payload = json.loads(rows[0][1])
        assert payload["gate"] == "dd_state"

    def test_advisory_dedup_no_double_log(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path, enforcement_mode="advisory")
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        from core.state import app_state
        app_state.portfolio.dd_state = "limit"
        app_state.portfolio.drawdown = 0.09
        app_state.is_initializing = False
        app_state.account_state.total_equity = 10000.0
        app_state.dd_would_have_blocked_logged = set()

        monkeypatch.setattr(
            "core.state.WSStatus.seconds_since_update",
            property(lambda self: 5.0),
        )

        from core.monitoring import ReadyStateEvaluator
        ev = ReadyStateEvaluator()
        ev.evaluate()
        ev.evaluate()  # second call

        conn = sqlite3.connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM engine_events "
            "WHERE event_type='would_have_blocked_dd'"
        ).fetchone()[0]
        conn.close()
        assert count == 1  # logged only once


class TestDDGateEnforced:
    def test_limit_enforced_blocks(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path, enforcement_mode="enforced")
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        from core.state import app_state
        app_state.portfolio.dd_state = "limit"
        app_state.portfolio.drawdown = 0.09
        app_state.is_initializing = False
        app_state.account_state.total_equity = 10000.0

        monkeypatch.setattr(
            "core.state.WSStatus.seconds_since_update",
            property(lambda self: 5.0),
        )

        from core.monitoring import ReadyStateEvaluator
        ready, reason = ReadyStateEvaluator().evaluate()
        assert ready is False
        assert "dd_state=limit" in reason
        assert "mode=enforced" in reason

    def test_enforced_logs_calculator_blocked(self, tmp_path, monkeypatch):
        data_dir, db_path = _make_env(tmp_path, enforcement_mode="enforced")
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        from core.state import app_state
        app_state.portfolio.dd_state = "limit"
        app_state.portfolio.drawdown = 0.09
        app_state.is_initializing = False
        app_state.account_state.total_equity = 10000.0

        monkeypatch.setattr(
            "core.state.WSStatus.seconds_since_update",
            property(lambda self: 5.0),
        )

        from core.monitoring import ReadyStateEvaluator
        ReadyStateEvaluator().evaluate()

        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT event_type, payload_json FROM engine_events "
            "WHERE event_type='calculator_blocked'"
        ).fetchall()
        conn.close()
        assert len(rows) >= 1
        payload = json.loads(rows[0][1])
        assert payload["gate"] == "dd_state"


class TestDDGateDedup:
    def test_transition_out_resets_dedup(self, tmp_path, monkeypatch):
        """After leaving limit and re-entering, shadow event should log again."""
        data_dir, db_path = _make_env(tmp_path, enforcement_mode="advisory")
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        from core.state import app_state
        app_state.is_initializing = False
        app_state.account_state.total_equity = 10000.0
        app_state.dd_would_have_blocked_logged = set()

        monkeypatch.setattr(
            "core.state.WSStatus.seconds_since_update",
            property(lambda self: 5.0),
        )

        from core.monitoring import ReadyStateEvaluator
        ev = ReadyStateEvaluator()

        # Enter limit
        app_state.portfolio.dd_state = "limit"
        app_state.portfolio.drawdown = 0.09
        ev.evaluate()

        # Simulate transition out (data_cache would do this)
        app_state.dd_would_have_blocked_logged.discard(1)

        # Re-enter limit
        ev.evaluate()

        conn = sqlite3.connect(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM engine_events "
            "WHERE event_type='would_have_blocked_dd'"
        ).fetchone()[0]
        conn.close()
        assert count == 2  # logged twice (once per episode)
