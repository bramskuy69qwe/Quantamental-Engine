"""Tests for core.event_log — engine_events write-side API."""
import json
import os
import sqlite3

import pytest

from core.event_log import _VALID_EVENT_TYPES, log_event
from core.migrations.runner import run_all


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_env(tmp_path, account_id=1):
    """Data dir with split marker, per-account DB, and 003 migration applied."""
    data = tmp_path / "data"
    data.mkdir()
    (data / ".split-complete-v1").write_text("v1")

    pa = data / "per_account"
    pa.mkdir()
    db_path = str(pa / "test__broker__1.db")

    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO accounts VALUES (?, 'Test')", (account_id,))
    conn.commit()
    conn.close()

    # Apply all real migrations (001, 002, 003) via the runner
    import core.migrations.runner as runner
    real_mdir = os.path.dirname(os.path.abspath(runner.__file__))
    run_all(str(data), real_mdir)

    return str(data), db_path


def _read_events(db_path, account_id=1):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM engine_events WHERE account_id = ? ORDER BY id",
        (account_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── log_event ─────────────────────────────────────────────────────────────────


class TestLogEvent:
    def test_insert_and_read_back(self, tmp_path):
        data_dir, db_path = _make_env(tmp_path)
        row_id = log_event(
            1,
            "dd_state_transition",
            {"old": "ok", "new": "warning", "value": 0.06},
            "data_cache",
            timestamp="2026-05-14T00:00:00+00:00",
            data_dir=data_dir,
        )
        assert row_id >= 1

        events = _read_events(db_path)
        assert len(events) == 1
        e = events[0]
        assert e["account_id"] == 1
        assert e["event_type"] == "dd_state_transition"
        assert e["source"] == "data_cache"
        assert e["timestamp"] == "2026-05-14T00:00:00+00:00"
        payload = json.loads(e["payload_json"])
        assert payload == {"old": "ok", "new": "warning", "value": 0.06}

    def test_invalid_event_type_rejected(self, tmp_path):
        data_dir, _ = _make_env(tmp_path)
        with pytest.raises(ValueError, match="Unknown event_type"):
            log_event(1, "not_a_real_type", {}, "test", data_dir=data_dir)  # type: ignore[arg-type]

    def test_all_defined_types_accepted(self, tmp_path):
        data_dir, db_path = _make_env(tmp_path)
        for et in sorted(_VALID_EVENT_TYPES):
            log_event(1, et, {"test": True}, "test_suite", data_dir=data_dir)  # type: ignore[arg-type]

        events = _read_events(db_path)
        assert len(events) == len(_VALID_EVENT_TYPES)

    def test_payload_stored_as_json(self, tmp_path):
        data_dir, db_path = _make_env(tmp_path)
        payload = {"nested": {"key": [1, 2, 3]}, "flag": True}
        log_event(1, "calculator_blocked", payload, "risk_engine", data_dir=data_dir)

        events = _read_events(db_path)
        assert json.loads(events[0]["payload_json"]) == payload

    def test_default_timestamp_is_utc(self, tmp_path):
        data_dir, db_path = _make_env(tmp_path)
        log_event(1, "rate_limit_pause", {}, "ws_manager", data_dir=data_dir)

        events = _read_events(db_path)
        ts = events[0]["timestamp"]
        assert "+00:00" in ts or ts.endswith("Z")

    def test_multiple_events_ordered(self, tmp_path):
        data_dir, db_path = _make_env(tmp_path)
        for i in range(5):
            log_event(
                1,
                "dd_state_transition",
                {"seq": i},
                "test",
                timestamp=f"2026-05-14T00:00:0{i}+00:00",
                data_dir=data_dir,
            )

        events = _read_events(db_path)
        assert len(events) == 5
        seqs = [json.loads(e["payload_json"])["seq"] for e in events]
        assert seqs == [0, 1, 2, 3, 4]

    def test_unknown_account_raises_keyerror(self, tmp_path):
        data_dir, _ = _make_env(tmp_path)
        with pytest.raises(KeyError):
            log_event(999, "dd_state_transition", {}, "test", data_dir=data_dir)

    def test_empty_payload(self, tmp_path):
        data_dir, db_path = _make_env(tmp_path)
        log_event(1, "enforcement_mode_change", {}, "ui", data_dir=data_dir)

        events = _read_events(db_path)
        assert json.loads(events[0]["payload_json"]) == {}

    def test_schema_has_expected_indexes(self, tmp_path):
        _, db_path = _make_env(tmp_path)
        conn = sqlite3.connect(db_path)
        indexes = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND tbl_name='engine_events' ORDER BY name"
            ).fetchall()
        ]
        conn.close()
        assert "idx_engine_events_account_time" in indexes
        assert "idx_engine_events_type" in indexes
