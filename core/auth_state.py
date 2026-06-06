"""
Operator session business-layer scaffold — Phase 0 (P0.T2).

Phase 0 scope (this module): data type + event topic constants. The
table CRUD lives in :mod:`core.db_auth` (mixed into DatabaseManager).

Phase 9 will wire:

  - Single-operator-per-account LOCK enforcement (check active session
    on every action-row write).
  - Takeover UI prompt: "Operator X is active. Take over?" with ack
    flow that calls :func:`takeover_session` (atomic end-prior +
    start-new).
  - ``operator_id`` propagation onto ``pre_trade_log.operator_id``,
    ``orders.operator_id``, ``order_amendments.operator_id``, and any
    manual-link or manual-close audit rows.
  - Session timeout + idle cleanup (background job).
  - Read-only mode for non-active operators in the UI.

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
