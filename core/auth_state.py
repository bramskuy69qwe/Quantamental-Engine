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
