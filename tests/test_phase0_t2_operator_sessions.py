"""
Phase 0 Task 2 (P0.T2) tests — operator_sessions scaffold.

Verifies:

  1. ``operator_sessions`` table exists with the expected columns +
     indexes (spec §3.1).
  2. ``AuthMixin`` CRUD round-trip:
     - start_operator_session: returns id; row visible in get_*
     - end_operator_session: sets session_end_ts; idempotent overwrite
     - get_active_operator_session: returns un-ended session only;
       returns None when no active session; most-recent wins when
       multiple active (Phase 9 will enforce single-active).
     - get_operator_session_history: ordered newest-first, limit
       respected.
  3. ``takeover_from_session_id`` FK self relationship: takeover row
     links back to the prior session.
  4. ``OperatorSession`` dataclass round-trip:
     - from_row builds correct dataclass
     - is_active reflects session_end_ts state
     - NULL fields (session_end_ts, takeover_from_session_id) become
       Python None

Run: pytest tests/test_phase0_t2_operator_sessions.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.auth_state import (
    OperatorSession,
    OPERATOR_SESSION_STARTED_TOPIC,
    OPERATOR_SESSION_ENDED_TOPIC,
    OPERATOR_TAKEOVER_TOPIC,
)


@pytest_asyncio.fixture
async def db():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    yield db
    await db.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


# ── 1. Schema ──────────────────────────────────────────────────────────


class TestSchema:
    @pytest.mark.asyncio
    async def test_columns_match_spec(self, db):
        async with db._conn.execute("PRAGMA table_info(operator_sessions)") as cur:
            cols = {row[1]: row[2] for row in await cur.fetchall()}
        expected = {
            "id", "account_id", "operator_id", "session_start_ts",
            "session_end_ts", "takeover_from_session_id",
            "last_seen_ts",  # P9.T4 (idle-timeout heartbeat)
        }
        assert set(cols.keys()) == expected

    @pytest.mark.asyncio
    async def test_indexes_present(self, db):
        async with db._conn.execute(
            "PRAGMA index_list(operator_sessions)"
        ) as cur:
            idxs = {row[1] for row in await cur.fetchall()}
        assert "idx_op_sess_account_start" in idxs
        assert "idx_op_sess_active" in idxs


# ── 2. CRUD round-trip ─────────────────────────────────────────────────


class TestStartAndRead:
    @pytest.mark.asyncio
    async def test_start_returns_id_and_round_trip(self, db):
        sid = await db.start_operator_session(
            account_id=1, operator_id="alice",
            start_ts_ms=1000,
        )
        assert sid > 0
        row = await db.get_operator_session(sid)
        assert row is not None
        assert row["account_id"] == 1
        assert row["operator_id"] == "alice"
        assert row["session_start_ts"] == 1000
        assert row["session_end_ts"] is None
        assert row["takeover_from_session_id"] is None

    @pytest.mark.asyncio
    async def test_start_default_start_ts_auto_fills_to_now(self, db):
        # Don't pass start_ts_ms — helper defaults to time.time() * 1000.
        sid = await db.start_operator_session(
            account_id=1, operator_id="bob",
        )
        row = await db.get_operator_session(sid)
        assert row["session_start_ts"] > 0   # auto-filled

    @pytest.mark.asyncio
    async def test_get_unknown_session_returns_none(self, db):
        assert await db.get_operator_session(99999) is None


class TestEnd:
    @pytest.mark.asyncio
    async def test_end_sets_session_end_ts(self, db):
        sid = await db.start_operator_session(
            account_id=1, operator_id="alice", start_ts_ms=1000,
        )
        ok = await db.end_operator_session(sid, end_ts_ms=2000)
        assert ok is True
        row = await db.get_operator_session(sid)
        assert row["session_end_ts"] == 2000

    @pytest.mark.asyncio
    async def test_end_unknown_session_returns_false(self, db):
        assert await db.end_operator_session(99999) is False

    @pytest.mark.asyncio
    async def test_end_idempotent_overwrites(self, db):
        # Phase 9 may add a "don't overwrite" guard; for scaffold,
        # second end_operator_session call overwrites the timestamp.
        sid = await db.start_operator_session(
            account_id=1, operator_id="alice", start_ts_ms=1000,
        )
        await db.end_operator_session(sid, end_ts_ms=2000)
        await db.end_operator_session(sid, end_ts_ms=3000)
        row = await db.get_operator_session(sid)
        assert row["session_end_ts"] == 3000


class TestActiveLookup:
    @pytest.mark.asyncio
    async def test_no_active_returns_none(self, db):
        assert await db.get_active_operator_session(1) is None

    @pytest.mark.asyncio
    async def test_active_returns_un_ended_session(self, db):
        sid = await db.start_operator_session(
            account_id=1, operator_id="alice", start_ts_ms=1000,
        )
        active = await db.get_active_operator_session(1)
        assert active is not None
        assert active["id"] == sid

    @pytest.mark.asyncio
    async def test_ended_session_not_returned_as_active(self, db):
        sid = await db.start_operator_session(
            account_id=1, operator_id="alice", start_ts_ms=1000,
        )
        await db.end_operator_session(sid, end_ts_ms=2000)
        assert await db.get_active_operator_session(1) is None

    @pytest.mark.asyncio
    async def test_most_recent_active_wins(self, db):
        # Phase 9 enforces single-active per account; until then,
        # this query returns the most recent un-ended session.
        await db.start_operator_session(
            account_id=1, operator_id="alice", start_ts_ms=1000,
        )
        sid2 = await db.start_operator_session(
            account_id=1, operator_id="bob", start_ts_ms=2000,
        )
        active = await db.get_active_operator_session(1)
        assert active["id"] == sid2
        assert active["operator_id"] == "bob"

    @pytest.mark.asyncio
    async def test_active_scoped_per_account(self, db):
        # Account-1 active session should not leak into account-2.
        await db.start_operator_session(
            account_id=1, operator_id="alice", start_ts_ms=1000,
        )
        assert await db.get_active_operator_session(2) is None


class TestHistory:
    @pytest.mark.asyncio
    async def test_history_newest_first(self, db):
        for ts in (1000, 3000, 2000):
            await db.start_operator_session(
                account_id=1, operator_id=f"op-{ts}", start_ts_ms=ts,
            )
        rows = await db.get_operator_session_history(1)
        assert [r["session_start_ts"] for r in rows] == [3000, 2000, 1000]

    @pytest.mark.asyncio
    async def test_history_limit_respected(self, db):
        for ts in range(1000, 1010):
            await db.start_operator_session(
                account_id=1, operator_id="op", start_ts_ms=ts,
            )
        rows = await db.get_operator_session_history(1, limit=3)
        assert len(rows) == 3


# ── 3. Takeover linkage ────────────────────────────────────────────────


class TestTakeoverLinkage:
    @pytest.mark.asyncio
    async def test_takeover_records_prior_session_id(self, db):
        prior = await db.start_operator_session(
            account_id=1, operator_id="alice", start_ts_ms=1000,
        )
        # Phase 9 will atomically end-prior + start-new with the
        # takeover flag; for scaffold, two-step is acceptable.
        await db.end_operator_session(prior, end_ts_ms=2000)
        new_sid = await db.start_operator_session(
            account_id=1, operator_id="bob",
            start_ts_ms=2000,
            takeover_from_session_id=prior,
        )
        row = await db.get_operator_session(new_sid)
        assert row["takeover_from_session_id"] == prior


# ── 4. OperatorSession dataclass round-trip ────────────────────────────


class TestOperatorSessionDataclass:
    @pytest.mark.asyncio
    async def test_from_row_active_session(self, db):
        sid = await db.start_operator_session(
            account_id=1, operator_id="alice", start_ts_ms=1000,
        )
        row = await db.get_operator_session(sid)
        sess = OperatorSession.from_row(row)
        assert sess.id == sid
        assert sess.account_id == 1
        assert sess.operator_id == "alice"
        assert sess.session_start_ts == 1000
        assert sess.session_end_ts is None
        assert sess.takeover_from_session_id is None
        assert sess.is_active is True

    @pytest.mark.asyncio
    async def test_from_row_ended_session(self, db):
        sid = await db.start_operator_session(
            account_id=1, operator_id="alice", start_ts_ms=1000,
        )
        await db.end_operator_session(sid, end_ts_ms=2000)
        row = await db.get_operator_session(sid)
        sess = OperatorSession.from_row(row)
        assert sess.session_end_ts == 2000
        assert sess.is_active is False

    @pytest.mark.asyncio
    async def test_from_row_takeover_session(self, db):
        prior = await db.start_operator_session(
            account_id=1, operator_id="alice", start_ts_ms=1000,
        )
        new = await db.start_operator_session(
            account_id=1, operator_id="bob", start_ts_ms=2000,
            takeover_from_session_id=prior,
        )
        row = await db.get_operator_session(new)
        sess = OperatorSession.from_row(row)
        assert sess.takeover_from_session_id == prior


# ── 5. Event topic constants reserved for Phase 9 ──────────────────────


class TestEventTopicConstants:
    def test_topic_constants_defined_and_unique(self):
        topics = {
            OPERATOR_SESSION_STARTED_TOPIC,
            OPERATOR_SESSION_ENDED_TOPIC,
            OPERATOR_TAKEOVER_TOPIC,
        }
        assert len(topics) == 3   # all distinct strings
        for t in topics:
            assert t.startswith("operator:")
