"""
Operator session business-layer scaffold — Phase 0 (P0.T2).

Phase 0 scope (this module): data type + event topic constants. The
table CRUD lives in :mod:`core.db_auth` (mixed into DatabaseManager).

SHIPPED:

  - P9.T1 (minimal): seat-session register / takeover orchestration
    (:func:`register_session` / :func:`takeover_session`) backing the
    advisory multi-session banner. No hard lock.
  - P9.T3: ``operator_id`` propagation onto the three action-row tables
    that carry the column — ``pre_trade_log.operator_id`` (calc creation,
    via :func:`current_operator_id`), ``orders.operator_id`` and
    ``order_amendments.operator_id`` (WS arrival, via
    :func:`cached_operator_id`) — plus the ``calc:created`` /
    ``position:amended`` event payloads.
  - P9.T4: idle session timeout — the heartbeat
    (:func:`heartbeat_session`) bumps ``last_seen_ts`` while a page is
    open; the background reaper (:func:`reap_idle_sessions`, run by
    ``schedulers._operator_session_reaper_loop``) ends sessions quiet
    beyond :data:`OPERATOR_SESSION_IDLE_SEC` and invalidates the T3 cache.

STILL DEFERRED (later Phase-9 tasks):

  - Single-operator-per-account hard LOCK + read-only mode for
    non-active operators in the UI (full P9.T1 UI).
  - ``operator_id`` on manual-link / manual-close audit rows — those
    tables have NO ``operator_id`` column today, so this is a future
    schema column-add, NOT part of the P9.T3 three-table sweep.

Spec reference: docs/design/calc_linkage_spec.md §3.1 (table) + §12.1
(multi-operator semantics) + §3.6 (state-machine discipline).
Implementation plan: §14.3 P0.T2 + Phase 9 (P9.T1..T4).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class OperatorSession:
    """One row from ``operator_sessions``.

    Field names mirror the SQL columns 1:1 for round-trip clarity.
    ``session_end_ts`` is ``None`` for the currently-active session.
    ``takeover_from_session_id`` is ``None`` unless this session was
    started by a takeover flow displacing a prior active session.
    """

    id: int
    account_id: int
    operator_id: str
    session_start_ts: int
    session_end_ts: Optional[int] = None
    takeover_from_session_id: Optional[int] = None

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "OperatorSession":
        """Build from a raw DB row dict."""
        return cls(
            id=int(row["id"]),
            account_id=int(row["account_id"]),
            operator_id=str(row["operator_id"]),
            session_start_ts=int(row["session_start_ts"]),
            session_end_ts=(
                int(row["session_end_ts"])
                if row.get("session_end_ts") is not None
                else None
            ),
            takeover_from_session_id=(
                int(row["takeover_from_session_id"])
                if row.get("takeover_from_session_id") is not None
                else None
            ),
        )

    @property
    def is_active(self) -> bool:
        """True if ``session_end_ts`` is unset."""
        return self.session_end_ts is None


# ── Event topics (reserved for Phase 9 publisher) ──────────────────────
#
# Phase 9 emits these on the per-account event bus (per spec §9 +
# Phase 6 hierarchical topic format). Reserved here so callers + tests
# import from a single canonical location and Phase 9 only needs to
# wire publishers, not invent topic names.

OPERATOR_SESSION_STARTED_TOPIC = "operator:session_started"
OPERATOR_SESSION_ENDED_TOPIC   = "operator:session_ended"
OPERATOR_TAKEOVER_TOPIC        = "operator:takeover"

# P9.T4: a session with no heartbeat for this long is auto-ended by the
# background reaper (plan §9 row 9.4 "default 30 [min]"). The banner IIFE
# heartbeats every ~60s while the page is open, so only a closed/asleep
# browser crosses this threshold.
OPERATOR_SESSION_IDLE_SEC = 30 * 60


# ── Phase-9 P9.T1 (minimal seat-session register + takeover) ───────────
#
# Single-tenant localhost has no auth — an "operator" is a per-browser
# SEAT token (a localStorage UUID the frontend mints). These two helpers
# orchestrate the operator_sessions scaffold CRUD (AuthMixin) into the
# flows the minimal multi-session BANNER needs. There is NO hard lock:
# the result is advisory (the UI shows a "another session is active —
# take over?" banner). Single-active-per-account is best-effort — a
# register/register race can leave two actives, and the next register or
# takeover converges. Idle-timeout cleanup of stale active rows SHIPPED in
# P9.T4 (the reaper below); event emission on the reserved operator:*
# topics is deferred to the full P9.T1. ``db`` is the DatabaseManager
# singleton (AuthMixin).


async def register_session(db: Any, account_id: int, operator_id: str) -> Dict[str, Any]:
    """Report whether this seat owns the account's session, starting one if
    none is active. Returns one of:

      ``{"state": "owner", "session_id": N}`` — no session was active, so a
        new row was started for this seat; OR this seat's own row was
        already active (``"reused": True``) — either way this seat owns it.
      ``{"state": "foreign", "active_session_id": N, "foreign_operator_id":
        "...", "since_ms": T}`` — a DIFFERENT seat is active. This seat is
        NOT registered (no row started); the UI shows the takeover banner,
        and only an explicit :func:`takeover_session` starts a row here.
    """
    active = await db.get_active_operator_session(account_id)
    if active is None:
        sid = await db.start_operator_session(account_id, operator_id)
        return {"state": "owner", "session_id": sid}
    if active.get("operator_id") == operator_id:
        # P9.T4: a (re)register is activity — bump last_seen so the idle
        # reaper keeps this seat's session alive (best-effort; no-op fault).
        await db.touch_operator_session(int(active["id"]))
        return {"state": "owner", "session_id": int(active["id"]), "reused": True}
    return {
        "state": "foreign",
        "active_session_id": int(active["id"]),
        "foreign_operator_id": active.get("operator_id"),
        "since_ms": active.get("session_start_ts"),
    }


async def takeover_session(db: Any, account_id: int, operator_id: str) -> Dict[str, Any]:
    """Displace the foreign active session (if any) and start one for this
    seat, linked via ``takeover_from_session_id``. Idempotent for the
    already-owner case (no new row written). Returns
    ``{"state": "owner", "session_id": N, "took_over_from": prior|None}``.
    """
    active = await db.get_active_operator_session(account_id)
    if active is not None and active.get("operator_id") == operator_id:
        return {"state": "owner", "session_id": int(active["id"]),
                "took_over_from": None}
    prior_id = int(active["id"]) if active is not None else None
    if prior_id is not None:
        await db.end_operator_session(prior_id)
    sid = await db.start_operator_session(
        account_id, operator_id, takeover_from_session_id=prior_id,
    )
    return {"state": "owner", "session_id": sid, "took_over_from": prior_id}


# ── Phase-9 P9.T3 (operator_id propagation onto action rows) ───────────
#
# Two read paths for "who is the operator on duty?", per the HANDOFF
# P9.T3 hot-path note:
#
#   - current_operator_id() — authoritative DB resolve (one
#     get_active_operator_session SELECT). Used by the NON-hot
#     calc-creation path, where attribution is HIGH VALUE ("who created
#     this calc") and must be correct even when the cache is cold (e.g.
#     right after an engine restart, before any browser has registered).
#   - cached_operator_id() — O(1) read of the app_state write-through
#     cache (set on register/takeover in api/routes_auth). Used by the
#     HOT WS order/amendment write sites to avoid a per-write DB read;
#     returns None when no seat has registered since boot, which is
#     acceptable there (weak, best-effort "operator on duty at
#     observation time" attribution — spec §9 / HANDOFF caveat (a)).
#
# Both are best-effort and never raise: a resolver fault must not break
# the calc/order/amendment write it decorates. Caveat (b): a FOREIGN seat
# (one showing the takeover banner, never registered) that submits a calc
# mis-attributes to the active owner — acceptable at single-tenant
# localhost (CLAUDE.md Task 163 deployment context). The cache is keyed
# by account_id so an account switch can't surface a stale owner. It is
# invalidated by a later register/takeover (write-through) and by the P9.T4
# idle reaper (which clears the entry for a reaped seat — see
# :func:`reap_idle_sessions`).


async def current_operator_id(db: Any, account_id: int) -> Optional[str]:
    """Resolve the active ``operator_session``'s ``operator_id`` for an
    account from the DB (authoritative, freshest). Best-effort: returns
    ``None`` on no active session or any error. Use on the non-hot
    calc-creation path; hot WS sites use :func:`cached_operator_id`."""
    try:
        active = await db.get_active_operator_session(account_id)
    except Exception:  # noqa: BLE001 — attribution is non-blocking
        return None
    if not active:
        return None
    op = active.get("operator_id")
    return op if op else None


def cached_operator_id(account_id: int) -> Optional[str]:
    """O(1) read of the operator on duty (active seat) for an account from
    the ``app_state`` write-through cache (populated by the register /
    takeover endpoints). Returns ``None`` when no seat has registered for
    this account since boot — the WS hot path accepts that (weak,
    best-effort attribution). An empty/falsy cached seat also coerces to
    ``None`` so this matches :func:`current_operator_id` (which does the
    same) and never stamps an empty string; today the register/takeover
    endpoints 400-reject empty seats before the cache write, so this is
    defense-in-depth for any future cache-writer (e.g. P9.T4). Lazy
    app_state import avoids an import cycle."""
    try:
        from core.state import app_state
        return app_state.operator_id_by_account.get(account_id) or None
    except Exception:  # noqa: BLE001 — attribution is non-blocking
        return None


# ── Phase-9 P9.T4 (idle session timeout) ──────────────────────────────
#
# A closed/asleep browser leaves an active operator_sessions row forever
# (HANDOFF P9.T4). The fix: the page heartbeats while open (bumping
# last_seen_ts), and a background reaper ends sessions that have gone
# quiet beyond OPERATOR_SESSION_IDLE_SEC. "Idle" is heartbeat-driven (not
# max-age), so an actively-open page is never reaped.


async def heartbeat_session(
    db: Any, account_id: int, operator_id: str,
) -> Dict[str, Any]:
    """P9.T4: if this seat OWNS the account's active session, bump its
    ``last_seen_ts`` so the idle reaper keeps it alive. A foreign/absent seat
    is a NO-OP (it must not claim ownership — only register/takeover do that).
    Returns ``{"ok": True, "bumped": bool}`` (``bumped`` True iff this seat's
    active session was touched)."""
    active = await db.get_active_operator_session(account_id)
    if active and active.get("operator_id") == operator_id:
        await db.touch_operator_session(int(active["id"]))
        return {"ok": True, "bumped": True}
    return {"ok": True, "bumped": False}


async def reap_idle_sessions(
    db: Any, *, idle_sec: Optional[int] = None, now_ms: Optional[int] = None,
) -> int:
    """P9.T4 idle reaper (called by the background loop). Ends active sessions
    idle longer than ``idle_sec`` (default :data:`OPERATOR_SESSION_IDLE_SEC`)
    across ALL accounts, and invalidates the T3 operator-on-duty cache for
    each reaped ``(account, seat)`` so WS orders/amendments stop being stamped
    with a gone operator. Best-effort: returns 0 on any fault. Returns the
    number of sessions reaped."""
    if idle_sec is None:
        idle_sec = OPERATOR_SESSION_IDLE_SEC
    try:
        reaped = await db.reap_idle_operator_sessions(
            idle_ms=int(idle_sec) * 1000, now_ms=now_ms,
        )
    except Exception:  # noqa: BLE001 — reaping is non-blocking hygiene
        return 0
    if not reaped:
        return 0
    # Invalidate the T3 cache for reaped seats (match account AND seat — a
    # takeover may have already moved the cache to a still-active new owner).
    try:
        from core.state import app_state
        cache = app_state.operator_id_by_account
        for r in reaped:
            aid = r.get("account_id")
            if aid in cache and cache.get(aid) == r.get("operator_id"):
                cache.pop(aid, None)
    except Exception:  # noqa: BLE001 — cache invalidation is best-effort
        pass
    return len(reaped)
