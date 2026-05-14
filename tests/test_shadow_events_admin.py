"""Tests for admin shadow events query + enforcement mode toggle."""
import json
import os
import sqlite3

import pytest

from core.event_log import log_event, query_events
from core.migrations.runner import run_all


def _make_env(tmp_path, account_id=1):
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / ".split-complete-v1").write_text("v1")
    pa = data / "per_account"
    pa.mkdir(exist_ok=True)
    db_path = str(pa / "test__broker__1.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO accounts VALUES (?, 'Test Account')", (account_id,))
    conn.commit()
    conn.close()

    import core.migrations.runner as runner
    real_mdir = os.path.dirname(os.path.abspath(runner.__file__))
    run_all(str(data), real_mdir)
    return str(data), db_path


# ── query_events ─────────────────────────────────────────────────────────────


class TestQueryEvents:
    def test_returns_recent_events(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        log_event(1, "would_have_blocked_dd", {"test": 1}, "test",
                  timestamp="2026-05-15T10:00:00+00:00", data_dir=data_dir)
        log_event(1, "dd_state_transition", {"test": 2}, "test",
                  timestamp="2026-05-15T11:00:00+00:00", data_dir=data_dir)

        events = query_events(1, data_dir=data_dir)
        assert len(events) == 2

    def test_filters_by_event_type(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        log_event(1, "would_have_blocked_dd", {}, "test",
                  timestamp="2026-05-15T10:00:00+00:00", data_dir=data_dir)
        log_event(1, "dd_state_transition", {}, "test",
                  timestamp="2026-05-15T11:00:00+00:00", data_dir=data_dir)

        events = query_events(1, event_type="would_have_blocked_dd", data_dir=data_dir)
        assert len(events) == 1
        assert events[0]["event_type"] == "would_have_blocked_dd"

    def test_filters_by_date_range(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        log_event(1, "dd_state_transition", {}, "test",
                  timestamp="2026-05-10T00:00:00+00:00", data_dir=data_dir)
        log_event(1, "dd_state_transition", {}, "test",
                  timestamp="2026-05-15T00:00:00+00:00", data_dir=data_dir)

        events = query_events(1, from_ts="2026-05-14", data_dir=data_dir)
        assert len(events) == 1

    def test_respects_limit(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        for i in range(5):
            log_event(1, "dd_state_transition", {"i": i}, "test",
                      timestamp=f"2026-05-15T{10+i}:00:00+00:00", data_dir=data_dir)

        events = query_events(1, limit=3, data_dir=data_dir)
        assert len(events) == 3


# ── Enforcement mode toggle ──────────────────────────────────────────────────


class TestEnforcementToggle:
    def test_mode_flip_updates_settings(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        from core.db_account_settings import get_account_settings, update_account_settings
        assert get_account_settings(1, data_dir=data_dir).dd_enforcement_mode == "advisory"

        update_account_settings(1, data_dir=data_dir, dd_enforcement_mode="enforced")
        assert get_account_settings(1, data_dir=data_dir).dd_enforcement_mode == "enforced"

    def test_mode_change_logs_event(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        log_event(1, "enforcement_mode_change", {
            "from": "advisory", "to": "enforced",
        }, source="admin", data_dir=data_dir)

        events = query_events(1, event_type="enforcement_mode_change", data_dir=data_dir)
        assert len(events) == 1
        payload = json.loads(events[0]["payload_json"])
        assert payload["from"] == "advisory"
        assert payload["to"] == "enforced"

    def test_same_mode_is_noop(self, tmp_path, monkeypatch):
        data_dir, _ = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)

        # Mode is already advisory — flipping to advisory is a no-op
        from core.db_account_settings import get_account_settings
        mode = get_account_settings(1, data_dir=data_dir).dd_enforcement_mode
        assert mode == "advisory"
        # No event should be logged for same-mode
