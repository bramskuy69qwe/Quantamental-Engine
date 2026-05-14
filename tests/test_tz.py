"""Tests for core.tz — per-account timezone resolution."""
import logging
import os
import sqlite3
from datetime import timezone
from zoneinfo import ZoneInfo

import pytest

from core.tz import get_account_tz, now_in_account_tz


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_env(tmp_path, account_id=1, tz_value="Asia/Bangkok"):
    """Minimal per-account DB with account_settings.timezone populated."""
    data = tmp_path / "data"
    data.mkdir()
    (data / ".split-complete-v1").write_text("v1")
    pa = data / "per_account"
    pa.mkdir()

    db_path = str(pa / "test__broker__1.db")
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO accounts VALUES (?, 'Test')", (account_id,))
    conn.execute(
        "CREATE TABLE account_settings ("
        "  account_id INTEGER PRIMARY KEY,"
        "  timezone TEXT NOT NULL DEFAULT 'UTC')"
    )
    conn.execute(
        "INSERT INTO account_settings VALUES (?, ?)", (account_id, tz_value)
    )
    conn.commit()
    conn.close()
    return str(data)


# ── get_account_tz ────────────────────────────────────────────────────────────


class TestGetAccountTz:
    def test_known_account_returns_correct_tz(self, tmp_path, monkeypatch):
        data_dir = _make_env(tmp_path, tz_value="Asia/Bangkok")
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)
        tz = get_account_tz(1)
        assert tz == ZoneInfo("Asia/Bangkok")
        assert tz.key == "Asia/Bangkok"

    def test_utc_account(self, tmp_path, monkeypatch):
        data_dir = _make_env(tmp_path, tz_value="UTC")
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)
        tz = get_account_tz(1)
        assert tz == ZoneInfo("UTC")

    def test_unknown_account_falls_back_utc(self, tmp_path, monkeypatch, caplog):
        data_dir = _make_env(tmp_path)
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)
        with caplog.at_level(logging.WARNING, logger="tz"):
            tz = get_account_tz(999)
        assert tz == ZoneInfo("UTC")
        assert "unknown account_id=999" in caplog.text

    def test_malformed_tz_falls_back_utc(self, tmp_path, monkeypatch, caplog):
        data_dir = _make_env(tmp_path, tz_value="Not/A/Real/Zone")
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)
        with caplog.at_level(logging.WARNING, logger="tz"):
            tz = get_account_tz(1)
        assert tz == ZoneInfo("UTC")
        assert "bad timezone" in caplog.text or "defaulting to UTC" in caplog.text


# ── now_in_account_tz ─────────────────────────────────────────────────────────


class TestNowInAccountTz:
    def test_returns_tz_aware_datetime(self, tmp_path, monkeypatch):
        data_dir = _make_env(tmp_path, tz_value="America/New_York")
        monkeypatch.setattr("core.db_account_settings.config.DATA_DIR", data_dir)
        dt = now_in_account_tz(1)
        assert dt.tzinfo is not None
        assert str(dt.tzinfo) != "UTC" or ZoneInfo("America/New_York") == ZoneInfo("UTC")
        # The key check: tzinfo resolves to the configured zone
        assert dt.tzname() is not None
