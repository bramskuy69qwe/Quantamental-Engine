"""Tests for core.migrations.runner — SQL migration runner for v2.4+."""
import os
import sqlite3

import pytest

from core.migrations.runner import (
    Migration,
    apply_one,
    discover,
    parse_header,
    run_all,
    run_pending_for_db,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_data_dir(tmp_path):
    """Minimal data dir with split marker, global.db, and one per-account DB."""
    data = tmp_path / "data"
    data.mkdir()
    (data / ".split-complete-v1").write_text("v1")

    # global.db
    conn = sqlite3.connect(str(data / "global.db"))
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()

    # per-account DB with accounts row (needed for seed INSERT)
    pa = data / "per_account"
    pa.mkdir()
    conn = sqlite3.connect(str(pa / "test__broker__1.db"))
    conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO accounts VALUES (1, 'Test Account')")
    conn.commit()
    conn.close()

    return data


def _make_migration_dir(tmp_path, files):
    """Create temp migration dir.  files = [(filename, sql_content), ...]."""
    d = tmp_path / "migrations"
    d.mkdir(exist_ok=True)
    for name, content in files:
        (d / name).write_text(content, encoding="utf-8")
    return d


def _tables(db_path):
    conn = sqlite3.connect(db_path)
    names = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]
    conn.close()
    return names


def _migration_names(db_path):
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM migrations_log ORDER BY applied_at"
        ).fetchall()
        return [r[0] for r in rows]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


# ── parse_header ──────────────────────────────────────────────────────────────


class TestParseHeader:
    def test_per_account(self):
        sql = "-- migration: per_account\n-- name: 001_test\n-- description: x\n"
        scope, name = parse_header(sql)
        assert scope == "per_account"
        assert name == "001_test"

    def test_global(self):
        sql = "-- migration: global\n-- name: 002_g\nSELECT 1;"
        scope, name = parse_header(sql)
        assert scope == "global"
        assert name == "002_g"

    def test_missing_scope_is_hard_error(self):
        with pytest.raises(ValueError, match="missing required"):
            parse_header("-- name: test\nCREATE TABLE x (id INT);")

    def test_missing_name_is_hard_error(self):
        with pytest.raises(ValueError, match="missing required"):
            parse_header("-- migration: global\nCREATE TABLE x (id INT);")

    def test_invalid_scope_is_hard_error(self):
        with pytest.raises(ValueError, match="missing required"):
            parse_header("-- migration: invalid_scope\n-- name: x\n")


# ── discover ──────────────────────────────────────────────────────────────────


class TestDiscover:
    def test_empty_dir(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        assert discover(str(d)) == []

    def test_numeric_order(self, tmp_path):
        d = _make_migration_dir(
            tmp_path,
            [
                ("002_b.sql", "-- migration: global\n-- name: 002_b\nSELECT 1;"),
                ("001_a.sql", "-- migration: per_account\n-- name: 001_a\nSELECT 1;"),
            ],
        )
        ms = discover(str(d))
        assert [m.name for m in ms] == ["001_a", "002_b"]
        assert ms[0].scope == "per_account"
        assert ms[1].scope == "global"

    def test_ignores_non_sql_and_non_numeric(self, tmp_path):
        d = _make_migration_dir(
            tmp_path,
            [("001_a.sql", "-- migration: global\n-- name: 001_a\nSELECT 1;")],
        )
        (d / "README.md").write_text("ignore")
        (d / "000_split.py").write_text("# python")
        (d / "notes.sql").write_text("-- no numeric prefix")
        assert len(discover(str(d))) == 1

    def test_bad_header_raises_during_discovery(self, tmp_path):
        d = _make_migration_dir(
            tmp_path,
            [("001_bad.sql", "CREATE TABLE x (id INT);")],  # no header
        )
        with pytest.raises(ValueError, match="missing required"):
            discover(str(d))


# ── apply_one ─────────────────────────────────────────────────────────────────


class TestApplyOne:
    def _fresh_db(self, tmp_path, name="test.db", with_accounts=False):
        path = str(tmp_path / name)
        conn = sqlite3.connect(path)
        if with_accounts:
            conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
            conn.execute("INSERT INTO accounts VALUES (1, 'Acc')")
            conn.commit()
        conn.close()
        return path

    def test_creates_table_and_records(self, tmp_path):
        db = self._fresh_db(tmp_path)
        m = Migration("f.sql", "001_x", "per_account",
                       "-- migration: per_account\n-- name: 001_x\n"
                       "CREATE TABLE IF NOT EXISTS foo (id INTEGER);")
        assert apply_one(db, m) is True
        assert "foo" in _tables(db)
        assert "001_x" in _migration_names(db)

    def test_idempotent_second_call(self, tmp_path):
        db = self._fresh_db(tmp_path)
        m = Migration("f.sql", "001_x", "per_account",
                       "-- migration: per_account\n-- name: 001_x\n"
                       "CREATE TABLE IF NOT EXISTS foo (id INTEGER);")
        assert apply_one(db, m) is True
        assert apply_one(db, m) is False

    def test_bad_sql_raises_and_not_recorded(self, tmp_path):
        db = self._fresh_db(tmp_path)
        m = Migration("f.sql", "bad", "per_account",
                       "-- migration: per_account\n-- name: bad\n"
                       "INVALID SQL STATEMENT;")
        with pytest.raises(sqlite3.Error):
            apply_one(db, m)
        assert "bad" not in _migration_names(db)

    def test_creates_migrations_log_if_absent(self, tmp_path):
        db = self._fresh_db(tmp_path)
        assert "migrations_log" not in _tables(db)
        m = Migration("f.sql", "001_x", "per_account",
                       "-- migration: per_account\n-- name: 001_x\n"
                       "CREATE TABLE IF NOT EXISTS bar (id INTEGER);")
        apply_one(db, m)
        assert "migrations_log" in _tables(db)


# ── run_all ───────────────────────────────────────────────────────────────────


class TestRunAll:
    def test_empty_migrations_dir(self, tmp_path):
        data = _make_data_dir(tmp_path)
        mdir = _make_migration_dir(tmp_path, [])
        assert run_all(str(data), str(mdir)) == 0

    def test_no_split_marker_is_noop(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        # No .split-complete-v1 marker
        mdir = _make_migration_dir(
            tmp_path,
            [("001_a.sql", "-- migration: global\n-- name: 001_a\n"
              "CREATE TABLE IF NOT EXISTS foo (id INTEGER);")],
        )
        assert run_all(str(data), str(mdir)) == 0

    def test_per_account_applies_to_every_db(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        (data / ".split-complete-v1").write_text("v1")
        pa = data / "per_account"
        pa.mkdir()

        for name in ["acct_a.db", "acct_b.db"]:
            conn = sqlite3.connect(str(pa / name))
            conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO accounts VALUES (1)")
            conn.commit()
            conn.close()

        mdir = _make_migration_dir(
            tmp_path,
            [("001_x.sql", "-- migration: per_account\n-- name: 001_x\n"
              "CREATE TABLE IF NOT EXISTS new_tbl (id INTEGER);")],
        )
        assert run_all(str(data), str(mdir)) == 2  # both DBs
        assert "new_tbl" in _tables(str(pa / "acct_a.db"))
        assert "new_tbl" in _tables(str(pa / "acct_b.db"))

    def test_global_applies_once(self, tmp_path):
        data = _make_data_dir(tmp_path)
        mdir = _make_migration_dir(
            tmp_path,
            [("001_g.sql", "-- migration: global\n-- name: 001_g\n"
              "CREATE TABLE IF NOT EXISTS gtbl (id INTEGER);")],
        )
        assert run_all(str(data), str(mdir)) == 1
        assert "gtbl" in _tables(str(data / "global.db"))

    def test_rerun_idempotent(self, tmp_path):
        data = _make_data_dir(tmp_path)
        mdir = _make_migration_dir(
            tmp_path,
            [("001_a.sql", "-- migration: per_account\n-- name: 001_a\n"
              "CREATE TABLE IF NOT EXISTS t (id INTEGER);")],
        )
        assert run_all(str(data), str(mdir)) == 1
        assert run_all(str(data), str(mdir)) == 0  # nothing to do

    def test_two_migrations_in_numeric_order(self, tmp_path):
        data = _make_data_dir(tmp_path)
        mdir = _make_migration_dir(
            tmp_path,
            [
                ("002_second.sql", "-- migration: per_account\n-- name: 002_second\n"
                 "CREATE TABLE IF NOT EXISTS second (id INTEGER);"),
                ("001_first.sql", "-- migration: per_account\n-- name: 001_first\n"
                 "CREATE TABLE IF NOT EXISTS first (id INTEGER);"),
            ],
        )
        assert run_all(str(data), str(mdir)) == 2  # both applied to 1 DB

        pa_db = str(data / "per_account" / "test__broker__1.db")
        names = _migration_names(pa_db)
        # 001 should precede 002 in applied_at order
        assert names.index("001_first") < names.index("002_second")

    def test_bad_sql_blocks_subsequent_on_same_target(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        (data / ".split-complete-v1").write_text("v1")
        pa = data / "per_account"
        pa.mkdir()

        for name in ["good.db", "bad.db"]:
            conn = sqlite3.connect(str(pa / name))
            conn.close()

        # 001 has bad SQL — will fail on both targets.
        # 002 should be skipped for both (both targets failed).
        mdir = _make_migration_dir(
            tmp_path,
            [
                ("001_fail.sql", "-- migration: per_account\n-- name: 001_fail\n"
                 "INVALID SQL;"),
                ("002_ok.sql", "-- migration: per_account\n-- name: 002_ok\n"
                 "CREATE TABLE IF NOT EXISTS ok_tbl (id INTEGER);"),
            ],
        )
        assert run_all(str(data), str(mdir)) == 0
        assert "ok_tbl" not in _tables(str(pa / "good.db"))
        assert "ok_tbl" not in _tables(str(pa / "bad.db"))

    def test_missing_header_is_hard_error(self, tmp_path):
        data = _make_data_dir(tmp_path)
        mdir = _make_migration_dir(
            tmp_path,
            [("001_no_header.sql", "CREATE TABLE foo (id INTEGER);")],
        )
        with pytest.raises(ValueError, match="missing required"):
            run_all(str(data), str(mdir))


# ── run_pending_for_db ────────────────────────────────────────────────────────


class TestRunPendingForDb:
    def test_applies_per_account_skips_global(self, tmp_path):
        db_path = str(tmp_path / "new.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO accounts VALUES (42)")
        conn.commit()
        conn.close()

        mdir = _make_migration_dir(
            tmp_path,
            [
                ("001_pa.sql", "-- migration: per_account\n-- name: 001_pa\n"
                 "CREATE TABLE IF NOT EXISTS pa_tbl (id INTEGER);"),
                ("002_gl.sql", "-- migration: global\n-- name: 002_gl\n"
                 "CREATE TABLE IF NOT EXISTS gl_tbl (id INTEGER);"),
            ],
        )
        assert run_pending_for_db(db_path, str(mdir)) == 1
        assert "pa_tbl" in _tables(db_path)
        assert "gl_tbl" not in _tables(db_path)

    def test_stops_on_first_failure(self, tmp_path):
        db_path = str(tmp_path / "new.db")
        sqlite3.connect(db_path).close()

        mdir = _make_migration_dir(
            tmp_path,
            [
                ("001_bad.sql", "-- migration: per_account\n-- name: 001_bad\n"
                 "INVALID;"),
                ("002_ok.sql", "-- migration: per_account\n-- name: 002_ok\n"
                 "CREATE TABLE IF NOT EXISTS ok_tbl (id INTEGER);"),
            ],
        )
        assert run_pending_for_db(db_path, str(mdir)) == 0
        assert "ok_tbl" not in _tables(db_path)


# ── Integration: 001_v2_4_account_tz.sql ─────────────────────────────────────


class TestAccountTzMigration:
    """Smoke-test the real 001 migration file against a synthetic DB."""

    def test_creates_account_settings_with_seed(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        (data / ".split-complete-v1").write_text("v1")
        pa = data / "per_account"
        pa.mkdir()

        db_path = str(pa / "test__broker__1.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO accounts VALUES (7, 'My Account')")
        conn.commit()
        conn.close()

        # Use the REAL migrations dir (all numbered .sql files)
        import core.migrations.runner as runner

        real_mdir = os.path.dirname(os.path.abspath(runner.__file__))
        applied = run_all(str(data), real_mdir)
        assert applied >= 1  # 001 + any later migrations

        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT account_id, timezone FROM account_settings"
        ).fetchone()
        assert row == (7, "UTC")
        conn.close()
