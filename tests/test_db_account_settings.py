"""Tests for core.db_account_settings — AccountSettings accessor layer."""
import sqlite3

import pytest

from core.db_account_settings import (
    AccountSettings,
    get_account_settings,
    update_account_settings,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_env(tmp_path, account_id=1, settings_row=None):
    """Create a data dir with split marker and one per-account DB.

    settings_row: dict of column overrides for the account_settings INSERT.
    Returns data_dir as str.
    """
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
        """CREATE TABLE account_settings (
            account_id                   INTEGER PRIMARY KEY,
            timezone                     TEXT    NOT NULL DEFAULT 'UTC',
            dd_rolling_window_days       INTEGER NOT NULL DEFAULT 30,
            dd_warning_threshold         REAL,
            dd_limit_threshold           REAL,
            dd_recovery_threshold        REAL    NOT NULL DEFAULT 0.50,
            dd_enforcement_mode          TEXT    NOT NULL DEFAULT 'advisory',
            weekly_pnl_warning_threshold REAL,
            weekly_pnl_limit_threshold   REAL,
            weekly_pnl_enforcement_mode  TEXT    NOT NULL DEFAULT 'advisory'
        )"""
    )

    defaults = {
        "account_id": account_id,
        "timezone": "UTC",
        "dd_rolling_window_days": 30,
        "dd_warning_threshold": 0.08,
        "dd_limit_threshold": 0.095,
        "dd_recovery_threshold": 0.50,
        "dd_enforcement_mode": "advisory",
        "weekly_pnl_warning_threshold": 0.04,
        "weekly_pnl_limit_threshold": 0.0475,
        "weekly_pnl_enforcement_mode": "advisory",
    }
    if settings_row:
        defaults.update(settings_row)

    cols = ", ".join(defaults.keys())
    placeholders = ", ".join(["?"] * len(defaults))
    conn.execute(
        f"INSERT INTO account_settings ({cols}) VALUES ({placeholders})",
        list(defaults.values()),
    )
    conn.commit()
    conn.close()
    return str(data)


# ── get_account_settings ─────────────────────────────────────────────────────


class TestGet:
    def test_returns_populated_dataclass(self, tmp_path):
        data_dir = _make_env(tmp_path)
        s = get_account_settings(1, data_dir=data_dir)
        assert isinstance(s, AccountSettings)
        assert s.account_id == 1
        assert s.timezone == "UTC"
        assert s.dd_warning_threshold == pytest.approx(0.08)
        assert s.dd_limit_threshold == pytest.approx(0.095)
        assert s.dd_recovery_threshold == pytest.approx(0.50)
        assert s.dd_enforcement_mode == "advisory"
        assert s.dd_rolling_window_days == 30
        assert s.weekly_pnl_warning_threshold == pytest.approx(0.04)
        assert s.weekly_pnl_limit_threshold == pytest.approx(0.0475)
        assert s.weekly_pnl_enforcement_mode == "advisory"

    def test_raises_keyerror_unknown_account(self, tmp_path):
        data_dir = _make_env(tmp_path, account_id=1)
        with pytest.raises(KeyError):
            get_account_settings(999, data_dir=data_dir)

    def test_null_columns_surface_as_none(self, tmp_path):
        data_dir = _make_env(
            tmp_path,
            settings_row={
                "dd_warning_threshold": None,
                "dd_limit_threshold": None,
                "weekly_pnl_warning_threshold": None,
                "weekly_pnl_limit_threshold": None,
            },
        )
        s = get_account_settings(1, data_dir=data_dir)
        assert s.dd_warning_threshold is None
        assert s.dd_limit_threshold is None
        assert s.weekly_pnl_warning_threshold is None
        assert s.weekly_pnl_limit_threshold is None

    def test_frozen_dataclass_immutable(self, tmp_path):
        data_dir = _make_env(tmp_path)
        s = get_account_settings(1, data_dir=data_dir)
        with pytest.raises(AttributeError):
            s.timezone = "Asia/Bangkok"  # type: ignore[misc]


# ── update_account_settings ──────────────────────────────────────────────────


class TestUpdate:
    def test_single_field(self, tmp_path):
        data_dir = _make_env(tmp_path)
        s = update_account_settings(1, data_dir=data_dir, timezone="Asia/Bangkok")
        assert s.timezone == "Asia/Bangkok"

        # Persistent — survives re-read
        s2 = get_account_settings(1, data_dir=data_dir)
        assert s2.timezone == "Asia/Bangkok"

    def test_multiple_fields(self, tmp_path):
        data_dir = _make_env(tmp_path)
        s = update_account_settings(
            1,
            data_dir=data_dir,
            dd_enforcement_mode="enforced",
            dd_rolling_window_days=14,
        )
        assert s.dd_enforcement_mode == "enforced"
        assert s.dd_rolling_window_days == 14

    def test_unknown_field_raises_valueerror(self, tmp_path):
        data_dir = _make_env(tmp_path)
        with pytest.raises(ValueError, match="Unknown or non-updatable"):
            update_account_settings(1, data_dir=data_dir, nonexistent_field=42)

    def test_account_id_not_updatable(self, tmp_path):
        data_dir = _make_env(tmp_path)
        # account_id is a positional param — passing it as kwarg via dict
        # unpacking raises TypeError from Python itself
        with pytest.raises(TypeError):
            update_account_settings(1, data_dir=data_dir, **{"account_id": 999})

    def test_unknown_account_raises_keyerror(self, tmp_path):
        data_dir = _make_env(tmp_path, account_id=1)
        with pytest.raises(KeyError):
            update_account_settings(999, data_dir=data_dir, timezone="UTC")

    def test_noop_returns_current_state(self, tmp_path):
        data_dir = _make_env(tmp_path)
        s = update_account_settings(1, data_dir=data_dir)  # no kwargs
        assert s.account_id == 1
        assert s.dd_warning_threshold == pytest.approx(0.08)

    def test_set_to_none(self, tmp_path):
        data_dir = _make_env(tmp_path)
        s = update_account_settings(
            1, data_dir=data_dir, dd_warning_threshold=None
        )
        assert s.dd_warning_threshold is None
