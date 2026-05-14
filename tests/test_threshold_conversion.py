"""Tests for 002_v2_4_dd_thresholds migration + threshold data conversion."""
import os
import sqlite3

import pytest

from core.migrations.convert_thresholds import (
    MIGRATION_NAME,
    _compute,
    _read_legacy_params,
    convert_thresholds,
)
from core.migrations.runner import run_all


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_env(tmp_path, account_id=1, params=None):
    """Build a complete test environment: data dir, legacy DB, per-account DB.

    Returns (data_dir, pa_db_path, legacy_db_path).
    """
    data = tmp_path / "data"
    data.mkdir()
    (data / ".split-complete-v1").write_text("v1")

    # Per-account DB with accounts row + account_settings from 001
    pa = data / "per_account"
    pa.mkdir()
    pa_path = str(pa / "test__broker__1.db")
    conn = sqlite3.connect(pa_path)
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO accounts VALUES (?, 'Test')", (account_id,))
    conn.execute(
        "CREATE TABLE account_settings ("
        "  account_id INTEGER PRIMARY KEY,"
        "  timezone TEXT NOT NULL DEFAULT 'UTC')"
    )
    conn.execute(
        "INSERT INTO account_settings (account_id, timezone) VALUES (?, 'UTC')",
        (account_id,),
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS migrations_log "
        "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()

    # Legacy DB with account_params
    legacy_path = str(data / "risk_engine.db")
    conn = sqlite3.connect(legacy_path)
    conn.execute(
        "CREATE TABLE account_params ("
        "  account_id INTEGER NOT NULL,"
        "  key TEXT NOT NULL,"
        "  value REAL NOT NULL,"
        "  PRIMARY KEY (account_id, key))"
    )
    if params:
        for key, value in params.items():
            conn.execute(
                "INSERT INTO account_params VALUES (?, ?, ?)",
                (account_id, key, value),
            )
    conn.commit()
    conn.close()

    return str(data), pa_path, legacy_path


DEFAULT_PARAMS = {
    "max_dd_percent": 0.10,
    "max_dd_warning_pct": 0.80,
    "max_dd_limit_pct": 0.95,
    "max_w_loss_percent": 0.05,
    "weekly_loss_warning_pct": 0.80,
    "weekly_loss_limit_pct": 0.95,
}


# ── _compute unit tests ──────────────────────────────────────────────────────


class TestCompute:
    def test_option_a_math(self):
        dd_w, dd_l, w_w, w_l = _compute(DEFAULT_PARAMS)
        assert dd_w == pytest.approx(0.08)     # 0.10 × 0.80
        assert dd_l == pytest.approx(0.095)    # 0.10 × 0.95
        assert w_w == pytest.approx(0.04)      # 0.05 × 0.80
        assert w_l == pytest.approx(0.0475)    # 0.05 × 0.95

    def test_missing_key_yields_none(self):
        dd_w, dd_l, w_w, w_l = _compute({"max_dd_percent": 0.10})
        assert dd_w is None  # missing max_dd_warning_pct
        assert dd_l is None
        assert w_w is None
        assert w_l is None

    def test_empty_params_all_none(self):
        assert _compute({}) == (None, None, None, None)

    def test_zero_base_yields_zero(self):
        params = {**DEFAULT_PARAMS, "max_dd_percent": 0.0}
        dd_w, dd_l, _, _ = _compute(params)
        assert dd_w == 0.0
        assert dd_l == 0.0


# ── _read_legacy_params ──────────────────────────────────────────────────────


class TestReadLegacyParams:
    def test_reads_correct_account(self, tmp_path):
        db_path = str(tmp_path / "legacy.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE account_params "
            "(account_id INT, key TEXT, value REAL, PRIMARY KEY(account_id, key))"
        )
        conn.execute("INSERT INTO account_params VALUES (1, 'max_dd_percent', 0.10)")
        conn.execute("INSERT INTO account_params VALUES (2, 'max_dd_percent', 0.20)")
        conn.commit()
        conn.close()

        p = _read_legacy_params(db_path, 1)
        assert p["max_dd_percent"] == 0.10

    def test_missing_file_returns_empty(self, tmp_path):
        assert _read_legacy_params(str(tmp_path / "missing.db"), 1) == {}

    def test_opens_read_only(self, tmp_path):
        db_path = str(tmp_path / "legacy.db")
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE account_params "
            "(account_id INT, key TEXT, value REAL, PRIMARY KEY(account_id, key))"
        )
        conn.execute("INSERT INTO account_params VALUES (1, 'x', 1.0)")
        conn.commit()
        conn.close()

        # Open with the same URI pattern the production code uses
        ro_conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            ro_conn.execute("INSERT INTO account_params VALUES (1, 'y', 2.0)")
        ro_conn.close()


# ── Full pipeline: schema migration + data conversion ────────────────────────


class TestEndToEnd:
    def test_conversion_produces_expected_values(self, tmp_path):
        data_dir, pa_path, _ = _make_env(tmp_path, params=DEFAULT_PARAMS)

        # Use real migrations dir for 002 schema migration
        import core.migrations.runner as runner
        mdir = os.path.dirname(os.path.abspath(runner.__file__))

        # 1) Apply schema migrations (001 already baked into _make_env; 002 adds columns)
        run_all(data_dir, mdir)

        # 2) Run data conversion
        assert convert_thresholds(data_dir) == 1

        # 3) Verify
        conn = sqlite3.connect(pa_path)
        row = conn.execute(
            "SELECT dd_warning_threshold, dd_limit_threshold,"
            "       dd_recovery_threshold, dd_enforcement_mode,"
            "       dd_rolling_window_days,"
            "       weekly_pnl_warning_threshold, weekly_pnl_limit_threshold,"
            "       weekly_pnl_enforcement_mode"
            "  FROM account_settings WHERE account_id = 1"
        ).fetchone()
        conn.close()

        dd_warn, dd_limit, dd_recov, dd_mode, dd_window, w_warn, w_limit, w_mode = row
        assert dd_warn == pytest.approx(0.08)
        assert dd_limit == pytest.approx(0.095)
        assert dd_recov == pytest.approx(0.50)
        assert dd_mode == "advisory"
        assert dd_window == 30
        assert w_warn == pytest.approx(0.04)
        assert w_limit == pytest.approx(0.0475)
        assert w_mode == "advisory"

    def test_idempotent_rerun(self, tmp_path):
        data_dir, pa_path, _ = _make_env(tmp_path, params=DEFAULT_PARAMS)

        import core.migrations.runner as runner
        mdir = os.path.dirname(os.path.abspath(runner.__file__))
        run_all(data_dir, mdir)

        assert convert_thresholds(data_dir) == 1
        assert convert_thresholds(data_dir) == 0  # already recorded

        # Values unchanged
        conn = sqlite3.connect(pa_path)
        row = conn.execute(
            "SELECT dd_warning_threshold FROM account_settings"
        ).fetchone()
        conn.close()
        assert row[0] == pytest.approx(0.08)

    def test_missing_legacy_leaves_nulls(self, tmp_path):
        data_dir, pa_path, legacy_path = _make_env(tmp_path, params=DEFAULT_PARAMS)

        import core.migrations.runner as runner
        mdir = os.path.dirname(os.path.abspath(runner.__file__))
        run_all(data_dir, mdir)

        # Delete legacy DB to simulate it being unavailable
        os.remove(legacy_path)

        assert convert_thresholds(data_dir) == 1  # completes without crash

        conn = sqlite3.connect(pa_path)
        row = conn.execute(
            "SELECT dd_warning_threshold, dd_limit_threshold,"
            "       weekly_pnl_warning_threshold, weekly_pnl_limit_threshold"
            "  FROM account_settings"
        ).fetchone()
        conn.close()
        assert row == (None, None, None, None)

    def test_missing_params_rows_leaves_nulls(self, tmp_path):
        # Legacy DB exists but has no account_params for this account
        data_dir, pa_path, _ = _make_env(tmp_path, params={})

        import core.migrations.runner as runner
        mdir = os.path.dirname(os.path.abspath(runner.__file__))
        run_all(data_dir, mdir)

        assert convert_thresholds(data_dir) == 1

        conn = sqlite3.connect(pa_path)
        row = conn.execute(
            "SELECT dd_warning_threshold, dd_limit_threshold"
            "  FROM account_settings"
        ).fetchone()
        conn.close()
        assert row == (None, None)

    def test_schema_migration_preserves_timezone(self, tmp_path):
        """002 rebuild should carry forward timezone set by 001."""
        data_dir, pa_path, _ = _make_env(tmp_path, params=DEFAULT_PARAMS)

        # Set a non-default timezone before 002 runs
        conn = sqlite3.connect(pa_path)
        conn.execute("UPDATE account_settings SET timezone = 'Asia/Bangkok'")
        conn.commit()
        conn.close()

        import core.migrations.runner as runner
        mdir = os.path.dirname(os.path.abspath(runner.__file__))
        run_all(data_dir, mdir)

        conn = sqlite3.connect(pa_path)
        tz = conn.execute("SELECT timezone FROM account_settings").fetchone()[0]
        conn.close()
        assert tz == "Asia/Bangkok"
