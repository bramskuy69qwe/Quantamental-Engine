"""
operator_sessions CRUD — Phase 0 (P0.T2) scaffold.

Mixed into :class:`core.database.DatabaseManager`. Backs the
multi-operator handoff audit per spec §3.1 + §12.1. P0.T2 ships only
the table CRUD; the lock-enforcement + takeover-prompt flow + the
``operator_id`` propagation across action rows are deferred to
Phase 9 per implementation_plan.md §14.3 P0.T2.

The business-layer scaffold (data type + event topic constants) lives
in :mod:`core.auth_state`; this module is the SQL surface only.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("db_auth")


class AuthMixin:
    """``operator_sessions`` CRUD on :class:`DatabaseManager`."""

    async def start_operator_session(
        self,
        account_id: int,
        operator_id: str,
        *,
        takeover_from_session_id: Optional[int] = None,
        start_ts_ms: Optional[int] = None,
    ) -> int:
        """INSERT a new ``operator_sessions`` row. Returns the row id.

        ``start_ts_ms`` defaults to ``time.time() * 1000`` if omitted.
        ``takeover_from_session_id`` is set when this session displaces
        a prior active session for the same account (Phase 9 takeover
        flow). Caller is responsible for ending the prior session via
        :meth:`end_operator_session` — this helper does NOT auto-end
        the displaced session. (P9.T1-minimal's
        ``core.auth_state.takeover_session`` does the end-prior +
        start-new as two separate self-committing writes, NOT one
        transaction; the atomic acquire under a lock-acquire check is
        the FULL P9.T1.)
        """
        if start_ts_ms is None:
            start_ts_ms = int(time.time() * 1000)
        sql = (
            "INSERT INTO operator_sessions "
            "(account_id, operator_id, session_start_ts, last_seen_ts, "
            " takeover_from_session_id) "
            "VALUES (?, ?, ?, ?, ?)"
        )
        try:
            cur = await self._conn.execute(
                sql,
                # P9.T4: seed last_seen_ts = start so a brand-new session is
                # treated as just-active by the idle reaper.
                (account_id, operator_id, start_ts_ms, start_ts_ms,
                 takeover_from_session_id),
            )
            await self._conn.commit()
            return int(cur.lastrowid or 0)
        except Exception:
            log.exception("start_operator_session failed")
            return 0

    async def end_operator_session(
        self,
        session_id: int,
        *,
        end_ts_ms: Optional[int] = None,
    ) -> bool:
        """Set ``session_end_ts`` on the row. Returns True on success.

        Idempotent — if the row is already ended, UPDATE still succeeds
        and overwrites the end_ts. (Phase 9 may add a "don't overwrite
        if already ended" guard; for scaffold purposes, overwrite is
        acceptable since the audit table preserves the start_ts.)
        """
        if end_ts_ms is None:
            end_ts_ms = int(time.time() * 1000)
        try:
            cur = await self._conn.execute(
                "UPDATE operator_sessions SET session_end_ts = ? "
                "WHERE id = ?",
                (end_ts_ms, session_id),
            )
            await self._conn.commit()
            return (cur.rowcount or 0) > 0
        except Exception:
            log.exception("end_operator_session failed")
            return False

    async def touch_operator_session(
        self,
        session_id: int,
        *,
        last_seen_ms: Optional[int] = None,
    ) -> bool:
        """P9.T4: bump ``last_seen_ts`` on an ACTIVE session (the heartbeat
        signal). No-op on an already-ended row (``session_end_ts IS NULL``
        guard). Returns True iff a row was updated. Best-effort."""
        if last_seen_ms is None:
            last_seen_ms = int(time.time() * 1000)
        try:
            cur = await self._conn.execute(
                "UPDATE operator_sessions SET last_seen_ts = ? "
                "WHERE id = ? AND session_end_ts IS NULL",
                (last_seen_ms, session_id),
            )
            await self._conn.commit()
            return (cur.rowcount or 0) > 0
        except Exception:
            log.exception("touch_operator_session failed")
            return False

    async def reap_idle_operator_sessions(
        self,
        *,
        idle_ms: int,
        now_ms: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """P9.T4: end active sessions idle longer than ``idle_ms``. "Idle" =
        ``now - COALESCE(last_seen_ts, session_start_ts) > idle_ms`` (the
        COALESCE reaps pre-T4 rows on their age, since last_seen_ts is NULL
        there). Global — sweeps every account in one pass. Returns the reaped
        rows' ``{id, account_id, operator_id}`` so the caller can invalidate
        any matching operator-on-duty cache entry. Best-effort: returns ``[]``
        on error."""
        if now_ms is None:
            now_ms = int(time.time() * 1000)
        idle_expr = "(? - COALESCE(last_seen_ts, session_start_ts)) > ?"
        try:
            async with self._conn.execute(
                "SELECT id, account_id, operator_id FROM operator_sessions "
                "WHERE session_end_ts IS NULL AND " + idle_expr,
                (now_ms, idle_ms),
            ) as cur:
                rows = [dict(r) for r in await cur.fetchall()]
            if not rows:
                return []
            ids = [r["id"] for r in rows]
            qmarks = ",".join("?" for _ in ids)
            # Re-check the idle predicate in the UPDATE so a session
            # heartbeated between the SELECT and here is NOT reaped. The rare
            # interleave only over-reports in the returned snapshot, which
            # merely clears a cache entry the next heartbeat repopulates.
            await self._conn.execute(
                "UPDATE operator_sessions SET session_end_ts = ? "
                "WHERE id IN (" + qmarks + ") AND session_end_ts IS NULL "
                "  AND " + idle_expr,
                (now_ms, *ids, now_ms, idle_ms),
            )
            await self._conn.commit()
            return rows
        except Exception:
            log.exception("reap_idle_operator_sessions failed")
            return []

    async def get_active_operator_session(
        self,
        account_id: int,
    ) -> Optional[Dict[str, Any]]:
        """Return the most recent un-ended session for an account, or None.

        Phase 9's single-operator lock will enforce that at most one
        active session exists per account; for scaffold purposes,
        multiple actives can coexist (the most recent wins this query).
        """
        async with self._conn.execute(
            "SELECT * FROM operator_sessions "
            "WHERE account_id = ? AND session_end_ts IS NULL "
            "ORDER BY session_start_ts DESC, id DESC LIMIT 1",
            (account_id,),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def get_operator_session(
        self,
        session_id: int,
    ) -> Optional[Dict[str, Any]]:
        """Return one session row by id, or None if not found."""
        async with self._conn.execute(
            "SELECT * FROM operator_sessions WHERE id = ?",
            (session_id,),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def get_operator_session_history(
        self,
        account_id: int,
        *,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Return recent sessions for an account, newest first."""
        async with self._conn.execute(
            "SELECT * FROM operator_sessions "
            "WHERE account_id = ? "
            "ORDER BY session_start_ts DESC, id DESC LIMIT ?",
            (account_id, max(1, int(limit))),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
