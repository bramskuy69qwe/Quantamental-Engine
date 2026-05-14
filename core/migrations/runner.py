"""
SQL migration runner for v2.4+.

Reads *.sql files from core/migrations/ in numeric-prefix order.
Each file declares scope via a header comment block:

    -- migration: per_account
    -- name: 001_v2_4_account_tz
    -- description: Add account_settings table with timezone column

Scope values:
    global       — apply once to data/global.db
    per_account  — apply to every data/per_account/*.db file

Applied migrations are recorded in each target DB's existing
migrations_log table.  Idempotent: already-applied migrations are
silently skipped.
"""
from __future__ import annotations

import glob
import logging
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import List, NamedTuple, Optional, Set

log = logging.getLogger("migration_runner")

_DIR = os.path.dirname(os.path.abspath(__file__))

_SCOPE_RE = re.compile(r"^\s*--\s*migration:\s*(global|per_account)\s*$", re.MULTILINE)
_NAME_RE = re.compile(r"^\s*--\s*name:\s*(\S+)\s*$", re.MULTILINE)


class Migration(NamedTuple):
    path: str
    name: str
    scope: str  # "global" | "per_account"
    sql: str


# ── Header parsing ────────────────────────────────────────────────────────────


def parse_header(sql: str, filepath: str = "<unknown>") -> tuple:
    """Return (scope, name).  Raises ValueError on missing / invalid header."""
    scope_m = _SCOPE_RE.search(sql)
    name_m = _NAME_RE.search(sql)
    if not scope_m:
        raise ValueError(
            f"{filepath}: missing required '-- migration: global|per_account' header"
        )
    if not name_m:
        raise ValueError(
            f"{filepath}: missing required '-- name: <name>' header"
        )
    return scope_m.group(1), name_m.group(1)


# ── Discovery ─────────────────────────────────────────────────────────────────


def discover(migrations_dir: Optional[str] = None) -> List[Migration]:
    """Find all *.sql files with a numeric prefix, sorted by filename."""
    d = migrations_dir or _DIR
    pattern = os.path.join(d, "[0-9]*.sql")
    results: List[Migration] = []
    for fpath in sorted(glob.glob(pattern)):
        with open(fpath, encoding="utf-8") as f:
            sql = f.read()
        scope, name = parse_header(sql, fpath)
        results.append(Migration(path=fpath, name=name, scope=scope, sql=sql))
    return results


# ── Single-target application ─────────────────────────────────────────────────


def _ensure_log_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS migrations_log "
        "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    conn.commit()


def _is_applied(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute("SELECT 1 FROM migrations_log WHERE name=?", (name,)).fetchone()
        is not None
    )


def apply_one(db_path: str, migration: Migration) -> bool:
    """Apply a single migration to one DB file.

    Returns True if newly applied, False if already recorded.
    Raises sqlite3.Error on failure (partial DDL may persist — migrations
    must use IF NOT EXISTS / OR IGNORE for safe re-runnability).
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _ensure_log_table(conn)

        if _is_applied(conn, migration.name):
            return False

        # executescript() handles multi-statement SQL.  DDL is auto-committed
        # by SQLite so true rollback of CREATE TABLE is not possible —
        # all migrations MUST be written with IF NOT EXISTS / OR IGNORE.
        conn.executescript(migration.sql)

        # Record successful completion
        conn.execute(
            "INSERT INTO migrations_log (name, applied_at) VALUES (?, ?)",
            (migration.name, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return True
    except sqlite3.Error:
        log.error("[runner] FAILED %s on %s", migration.name, db_path, exc_info=True)
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


# ── Target resolution ─────────────────────────────────────────────────────────


def _find_targets(data_dir: str, scope: str) -> List[str]:
    """Return list of DB file paths for a given scope."""
    if scope == "global":
        p = os.path.join(data_dir, "global.db")
        return [p] if os.path.exists(p) else []
    if scope == "per_account":
        pa = os.path.join(data_dir, "per_account")
        if not os.path.isdir(pa):
            return []
        return sorted(
            os.path.join(pa, f) for f in os.listdir(pa) if f.endswith(".db")
        )
    raise ValueError(f"Unknown scope: {scope!r}")


# ── Main entry points ────────────────────────────────────────────────────────


def run_all(
    data_dir: Optional[str] = None,
    migrations_dir: Optional[str] = None,
) -> int:
    """Apply all pending migrations to appropriate DB targets.

    Only runs when ``data/.split-complete-v1`` marker exists.
    Returns total number of (migration x target) applications.
    """
    if data_dir is None:
        import config

        data_dir = config.DATA_DIR

    if not os.path.exists(os.path.join(data_dir, ".split-complete-v1")):
        log.debug("[runner] split marker absent — skipping")
        return 0

    migrations = discover(migrations_dir)
    if not migrations:
        return 0

    applied = 0
    failed_targets: Set[str] = set()

    for m in migrations:
        targets = _find_targets(data_dir, m.scope)
        if not targets:
            log.warning("[runner] no targets for %s (scope=%s)", m.name, m.scope)
            continue
        for db_path in targets:
            if db_path in failed_targets:
                log.warning(
                    "[runner] skipping %s on %s (prior failure)", m.name, db_path
                )
                continue
            try:
                if apply_one(db_path, m):
                    log.info("[runner] applied %s to %s", m.name, db_path)
                    applied += 1
            except sqlite3.Error:
                failed_targets.add(db_path)

    if applied == 0:
        log.debug("[runner] nothing to do")
    return applied


def run_pending_for_db(
    db_path: str,
    migrations_dir: Optional[str] = None,
) -> int:
    """Apply all per_account migrations to a single DB file.

    Use when provisioning a new per-account database so it starts with
    all schema additions up to the current version.
    Returns number of migrations applied.
    """
    applied = 0
    for m in discover(migrations_dir):
        if m.scope != "per_account":
            continue
        try:
            if apply_one(db_path, m):
                log.info("[runner] applied %s to %s", m.name, db_path)
                applied += 1
        except sqlite3.Error:
            break  # stop on first failure for this DB
    return applied
