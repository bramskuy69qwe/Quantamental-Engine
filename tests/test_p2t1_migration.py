"""P2.T1 positions_calcs.position_id INTEGER→TEXT migration tests.

The migration in core/database.py (one-shot block) recreates
positions_calcs with a TEXT position_id, but ONLY when the table is
still INTEGER AND empty; a NON-empty INTEGER table is left untouched
with a loud error (data-loss guard). Both branches are otherwise
unexercised by the normal fresh-DB test path (the canonical schema
already declares TEXT), so per CLAUDE.md destructive-operation
discipline they get explicit regression pins here.

The GUARD-branch test (test_nonempty_integer_table_not_dropped) is the
load-bearing pin: it fails loudly if a future refactor removes the
`COUNT(*) == 0` empty-table guard before the DROP TABLE.

Run: pytest tests/test_p2t1_migration.py -v
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# The legacy P0.T1 shape: position_id INTEGER (pre-P2.T1).
_LEGACY_INTEGER_DDL = """
CREATE TABLE positions_calcs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id     INTEGER NOT NULL,
    calc_id         TEXT    NOT NULL,
    order_id        INTEGER NOT NULL,
    account_id      INTEGER NOT NULL,
    contributed_qty REAL    NOT NULL DEFAULT 0,
    first_fill_ts   INTEGER NOT NULL DEFAULT 0,
    last_fill_ts    INTEGER NOT NULL DEFAULT 0,
    planned_size    REAL    DEFAULT NULL,
    size_delta_pct  REAL    DEFAULT NULL,
    planned_tp      REAL    DEFAULT NULL,
    planned_sl      REAL    DEFAULT NULL,
    lifecycle_id    TEXT    DEFAULT NULL,
    UNIQUE (position_id, calc_id, order_id)
)
"""


def _make_legacy_db(rows=0):
    """Create a tmpfile DB with a legacy INTEGER positions_calcs table,
    optionally pre-seeded with `rows` junction rows, BEFORE DatabaseManager
    sees it — so initialize()'s migration runs against the legacy shape."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.execute(_LEGACY_INTEGER_DDL)
    for i in range(rows):
        conn.execute(
            "INSERT INTO positions_calcs "
            "(position_id, calc_id, order_id, account_id, contributed_qty) "
            "VALUES (?, ?, ?, 1, 1.0)",
            (i + 1, f"calc-{i}", 100 + i),
        )
    conn.commit()
    conn.close()
    return tmp.name


def _cleanup(path):
    try:
        os.unlink(path)
        for ext in ("-wal", "-shm"):
            if os.path.exists(path + ext):
                os.unlink(path + ext)
    except OSError:
        pass


def _position_id_type(path):
    conn = sqlite3.connect(path)
    try:
        return next(
            (r[2] for r in conn.execute("PRAGMA table_info(positions_calcs)").fetchall()
             if r[1] == "position_id"), None,
        )
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_empty_integer_table_recreated_as_text():
    # RECREATE branch: empty legacy INTEGER table → migrated to TEXT,
    # all 5 idx_pc_* indexes present.
    from core.database import DatabaseManager
    path = _make_legacy_db(rows=0)
    assert _position_id_type(path) == "INTEGER"   # precondition
    db = DatabaseManager(path=path)
    await db.initialize()
    try:
        async with db._conn.execute("PRAGMA table_info(positions_calcs)") as cur:
            cols = {r[1]: r[2] for r in await cur.fetchall()}
        assert cols["position_id"] == "TEXT"
        # R4: the recreate runs AFTER the ALTER migration list, so its DDL
        # must carry sealed_ts itself or a legacy-DB migration drops the
        # column the lifecycle mint/reuse lookup now reads.
        assert "sealed_ts" in cols
        async with db._conn.execute("PRAGMA index_list(positions_calcs)") as cur:
            idx = {r[1] for r in await cur.fetchall()}
        for name in ("idx_pc_position", "idx_pc_calc", "idx_pc_order",
                     "idx_pc_account", "idx_pc_lifecycle"):
            assert name in idx, f"missing index {name}"
    finally:
        await db.close()
        _cleanup(path)


@pytest.mark.asyncio
async def test_nonempty_integer_table_not_dropped():
    # GUARD branch (load-bearing): a NON-empty INTEGER table must NOT be
    # dropped — the row survives and the type stays INTEGER (migration
    # skipped to avoid data loss). Fails loudly if the empty-table guard
    # before DROP TABLE is ever removed.
    from core.database import DatabaseManager
    path = _make_legacy_db(rows=2)
    assert _position_id_type(path) == "INTEGER"
    db = DatabaseManager(path=path)
    await db.initialize()
    try:
        async with db._conn.execute(
            "SELECT COUNT(*) FROM positions_calcs") as cur:
            n = (await cur.fetchone())[0]
        assert n == 2, "rows were destroyed by the migration — data-loss guard failed"
        async with db._conn.execute("PRAGMA table_info(positions_calcs)") as cur:
            pid = next((r for r in await cur.fetchall() if r[1] == "position_id"))
        assert pid[2] == "INTEGER", "table was migrated despite holding rows"
    finally:
        await db.close()
        _cleanup(path)


@pytest.mark.asyncio
async def test_fresh_db_is_text_and_idempotent():
    # Fresh DB: canonical schema already TEXT; re-initialize is a no-op.
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    try:
        async with db._conn.execute("PRAGMA table_info(positions_calcs)") as cur:
            cols = {r[1]: r[2] for r in await cur.fetchall()}
        assert cols["position_id"] == "TEXT"
    finally:
        await db.close()
        _cleanup(tmp.name)
