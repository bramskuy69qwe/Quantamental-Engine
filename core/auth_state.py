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

STILL DEFERRED (later Phase-9 tasks):

  - Single-operator-per-account hard LOCK + read-only mode for
    non-active operators in the UI (full P9.T1 / P9.T4 UI).
  - Session timeout + idle cleanup (background job — P9.T4).
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


# ── Phase-9 P9.T1 (minimal seat-session register + takeover) ───────────
#
# Single-tenant localhost has no auth — an "operator" is a per-browser
# SEAT token (a localStorage UUID the frontend mints). These two helpers
# orchestrate the operator_sessions scaffold CRUD (AuthMixin) into the
# flows the minimal multi-session BANNER needs. There is NO hard lock:
# the result is advisory (the UI shows a "another session is active —
# take over?" banner). Single-active-per-account is best-effort — a
# register/register race can leave two actives, and the next register or
# takeover converges. Idle-timeout cleanup of stale active rows is P9.T4;
# event emission on the reserved operator:* topics is deferred to the
# full P9.T1. ``db`` is the DatabaseManager singleton (AuthMixin).


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
# by account_id so an account switch can't surface a stale owner, and is
# only invalidated by a later register/takeover (no logout/idle-timeout
# in P9.T1/T3 — idle cleanup is P9.T4).


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
