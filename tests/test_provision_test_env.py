"""Tests for scripts/provision_test_env.py (fresh-worktree gate provisioning).

Scope: the safety-critical PURE logic — refusal guards, live-data
detection, the migration statement splitter (incl. the two fragilities
the 2026-07-21 independent audit flagged: unterminated-final-statement
drop and the ``BEGIN TRANSACTION`` spelling), credential scrub, and
credential-attr blanking.

Deliberately NOT covered: the end-to-end provision() sequence — it
needs a real repo layout + several DatabaseManager.initialize() rounds
(~15 s) and its effect is verified operationally by the full gate
(worktree gate == main-tree gate, 4092/7/3, 2026-07-21, re-verified
post-credential-scrub). The unit pins here are what keeps the tool's
SAFETY properties from regressing silently.
"""
import os
import sqlite3
import types

import pytest

from scripts.provision_test_env import (
    _statements,
    blank_config_credentials,
    guard_refusals,
    looks_live,
    scrub_credentials,
)


# ── _statements splitter ──────────────────────────────────────────────────────


class TestStatementsSplitter:
    def test_splits_multiple_statements(self):
        sql = "CREATE TABLE a (x INT);\nCREATE TABLE b (y INT);"
        stmts = list(_statements(sql))
        assert len(stmts) == 2
        assert stmts[0].startswith("CREATE TABLE a")
        assert stmts[1].startswith("CREATE TABLE b")

    def test_leading_comments_skipped(self):
        sql = "-- migration: per_account\n-- name: 001_x\nCREATE TABLE a (x INT);"
        stmts = list(_statements(sql))
        assert len(stmts) == 1
        assert "CREATE TABLE a" in stmts[0]

    def test_txn_markers_filtered_including_transaction_spelling(self):
        # Audit-flagged: the scratchpad version only filtered bare BEGIN/COMMIT
        sql = (
            "BEGIN;\nCREATE TABLE a (x INT);\nCOMMIT;\n"
            "BEGIN TRANSACTION;\nCREATE TABLE b (y INT);\nCOMMIT TRANSACTION;"
        )
        stmts = list(_statements(sql))
        assert len(stmts) == 2
        assert all(s.split()[0] == "CREATE" for s in stmts)

    def test_unterminated_final_statement_not_dropped(self):
        # Audit-flagged: sqlite3.complete_statement never confirms a statement
        # lacking ';' — the EOF flush must still yield it.
        sql = "CREATE TABLE a (x INT);\nINSERT INTO a VALUES (1)"
        stmts = list(_statements(sql))
        assert len(stmts) == 2
        assert stmts[1] == "INSERT INTO a VALUES (1)"

    def test_trailing_comment_only_tail_not_yielded(self):
        sql = "CREATE TABLE a (x INT);\n-- trailing note\n"
        stmts = list(_statements(sql))
        assert len(stmts) == 1

    def test_statements_execute_against_sqlite(self, tmp_path):
        # The splitter's output must be directly executable (integration pin
        # for the tolerant-reconcile loop that consumes it).
        sql = (
            "-- name: demo\nBEGIN;\nCREATE TABLE t (x INT);\n"
            "INSERT INTO t VALUES (1);\nCOMMIT;\nINSERT INTO t VALUES (2)"
        )
        conn = sqlite3.connect(str(tmp_path / "s.db"))
        for stmt in _statements(sql):
            conn.execute(stmt)
        assert conn.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
        conn.close()


# ── guard_refusals ────────────────────────────────────────────────────────────


class TestGuardRefusals:
    def test_primary_checkout_refused(self, tmp_path):
        (tmp_path / ".git").mkdir()
        reasons = guard_refusals(str(tmp_path))
        assert len(reasons) == 1
        assert "primary checkout" in reasons[0]

    def test_primary_checkout_allowed_with_flag(self, tmp_path):
        (tmp_path / ".git").mkdir()
        assert guard_refusals(str(tmp_path), allow_primary=True) == []

    def test_linked_worktree_allowed(self, tmp_path):
        # linked worktrees have a .git FILE (gitdir pointer)
        (tmp_path / ".git").write_text("gitdir: ../.git/worktrees/x\n")
        assert guard_refusals(str(tmp_path)) == []

    def test_non_repo_refused(self, tmp_path):
        reasons = guard_refusals(str(tmp_path))
        assert len(reasons) == 1
        assert "no .git" in reasons[0]


# ── looks_live ────────────────────────────────────────────────────────────────


def _make_db(path, table=None, rows=0):
    conn = sqlite3.connect(str(path))
    if table:
        conn.execute(f"CREATE TABLE {table} (x INT)")
        conn.executemany(f"INSERT INTO {table} VALUES (?)", [(i,) for i in range(rows)])
    conn.commit()
    conn.close()


class TestLooksLive:
    def test_rows_in_trading_table_flagged(self, tmp_path):
        data = tmp_path / "data"
        (data / "per_account").mkdir(parents=True)
        _make_db(data / "per_account" / "acct.db", "fills", rows=3)
        evidence = looks_live(str(data))
        assert len(evidence) == 1
        assert evidence[0].endswith("fills:3")

    def test_zero_rows_clean(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        _make_db(data / "engine.db", "fills", rows=0)
        assert looks_live(str(data)) == []

    def test_non_trading_tables_ignored(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        _make_db(data / "engine.db", "account_settings", rows=5)
        assert looks_live(str(data)) == []

    def test_pre_split_backup_scanned(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        _make_db(data / "risk_engine.db.pre-split-backup", "trade_history", rows=2)
        evidence = looks_live(str(data))
        assert len(evidence) == 1
        assert "trade_history:2" in evidence[0]


# ── scrub_credentials ─────────────────────────────────────────────────────────


class TestScrubCredentials:
    def _cred_db(self, path, key="v2:gAAAAfakeblob", n_conn=1):
        conn = sqlite3.connect(str(path))
        conn.execute(
            "CREATE TABLE accounts (id INTEGER PRIMARY KEY, "
            "api_key_enc TEXT, api_secret_enc TEXT)"
        )
        conn.execute("INSERT INTO accounts VALUES (1, ?, ?)", (key, key))
        conn.execute(
            "CREATE TABLE connections (provider TEXT, label TEXT, api_key_enc TEXT)"
        )
        for i in range(n_conn):
            conn.execute(
                "INSERT INTO connections VALUES (?, 'X', ?)", (f"p{i}", key)
            )
        conn.commit()
        conn.close()

    def test_scrubs_accounts_and_connections(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        self._cred_db(data / "risk_engine.db")
        scrubbed, residual = scrub_credentials(str(data))
        assert residual == 0
        assert any("accounts:1" in s for s in scrubbed)
        assert any("connections:1" in s for s in scrubbed)
        conn = sqlite3.connect(str(data / "risk_engine.db"))
        assert conn.execute(
            "SELECT api_key_enc, api_secret_enc FROM accounts"
        ).fetchone() == ("", "")
        assert conn.execute("SELECT COUNT(*) FROM connections").fetchone()[0] == 0
        conn.close()

    def test_clean_db_reports_nothing(self, tmp_path):
        data = tmp_path / "data"
        data.mkdir()
        _make_db(data / "clean.db", "accounts", rows=0)
        # accounts table without cred columns → scrub must not crash;
        # actually build the real shape with empty creds:
        os.remove(data / "clean.db")
        conn = sqlite3.connect(str(data / "clean.db"))
        conn.execute(
            "CREATE TABLE accounts (id INTEGER PRIMARY KEY, "
            "api_key_enc TEXT, api_secret_enc TEXT)"
        )
        conn.execute("INSERT INTO accounts VALUES (1, '', '')")
        conn.commit()
        conn.close()
        scrubbed, residual = scrub_credentials(str(data))
        assert scrubbed == []
        assert residual == 0

    def test_v2_prefixed_blob_detected_by_probe(self, tmp_path):
        # Audit-flagged: the app prefixes tokens with 'v2:' — an anchored
        # 'gAAAA%' LIKE misses them; the scrub probe must use '%gAAAA%'.
        data = tmp_path / "data"
        data.mkdir()
        self._cred_db(data / "risk_engine.db", key="v2:gAAAAsecret")
        scrubbed, residual = scrub_credentials(str(data))
        assert residual == 0  # scrub caught + blanked it
        assert any("accounts:1" in s for s in scrubbed)


# ── blank_config_credentials ─────────────────────────────────────────────────


class TestBlankConfigCredentials:
    def test_blanks_all_seed_read_attrs(self):
        fake = types.SimpleNamespace(
            BINANCE_API_KEY="k",
            BINANCE_API_SECRET="s",
            FRED_API_KEY="f",
            FINNHUB_API_KEY="fh",
            COINGECKO_API_KEY="cg",
        )
        blanked = blank_config_credentials(fake)
        assert sorted(blanked) == [
            "BINANCE_API_KEY",
            "BINANCE_API_SECRET",
            "COINGECKO_API_KEY",
            "FINNHUB_API_KEY",
            "FRED_API_KEY",
        ]
        assert all(
            getattr(fake, a) == ""
            for a in blanked
        )

    def test_absent_attrs_created_empty_not_reported(self):
        fake = types.SimpleNamespace()
        blanked = blank_config_credentials(fake)
        assert blanked == []
        assert fake.BINANCE_API_KEY == ""

    def test_covers_every_seed_attr_database_py_reads(self):
        # Source pin: if core/database.py's seed paths grow a new config
        # credential read, CREDENTIAL_ATTRS must grow with it. This greps the
        # seed functions' source for config.<ATTR> reads and asserts coverage.
        import inspect

        from core.database import DatabaseManager
        from scripts.provision_test_env import CREDENTIAL_ATTRS

        src = inspect.getsource(DatabaseManager.initialize) + inspect.getsource(
            DatabaseManager._migrate_env_connections
        )
        import re

        reads = set(re.findall(r"config\.([A-Z_]*(?:KEY|SECRET|TOKEN)[A-Z_]*)", src))
        reads |= set(
            re.findall(r'getattr\(config,\s*"([A-Z_]+)"', src)
        )
        missing = reads - set(CREDENTIAL_ATTRS)
        assert not missing, (
            f"core/database.py seed paths read config attrs not covered by "
            f"provision_test_env.CREDENTIAL_ATTRS: {missing}"
        )
