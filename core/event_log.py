"""
Write-side API for the ``engine_events`` audit trail.

Records stateful engine behavior (dd_state transitions, calculator
blocks, manual overrides, enforcement-mode changes, equity deltas,
rate-limit pauses, shadow would-have-blocked events) into a per-account
``engine_events`` table.

Read/query API and ``/admin/events`` route are separate deliverables.

Uses sync sqlite3 with the same path-resolution pattern as
``core.db_account_settings``.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

import config
from core.db_router import PER_ACCOUNT_DIR, split_done

log = logging.getLogger("event_log")


# ── Event types ──────────────────────────────────────────────────────────────

EventType = Literal[
    "dd_state_transition",
    "calculator_blocked",
    "manual_override",
    "enforcement_mode_change",
    "equity_delta_warning",
    "rate_limit_pause",
    "would_have_blocked_dd",
    "would_have_blocked_weekly_pnl",
    "calc_blocked_contract",
]

_VALID_EVENT_TYPES: frozenset[str] = frozenset(EventType.__args__)  # type: ignore[attr-defined]


# ── Path resolution ──────────────────────────────────────────────────────────


def _resolve_db_path(account_id: int, data_dir: Optional[str] = None) -> str:
    """Locate the per-account DB that owns *account_id*."""
    ddir = data_dir or config.DATA_DIR

    if not split_done() or not os.path.exists(os.path.join(ddir, ".split-complete-v1")):
        return os.path.join(ddir, "risk_engine.db")

    pa_dir = os.path.join(ddir, "per_account")
    if os.path.isdir(pa_dir):
        for fname in sorted(os.listdir(pa_dir)):
            if not fname.endswith(".db"):
                continue
            path = os.path.join(pa_dir, fname)
            conn = sqlite3.connect(path)
            try:
                if conn.execute(
                    "SELECT 1 FROM accounts WHERE id = ?", (account_id,)
                ).fetchone():
                    return path
            finally:
                conn.close()

    raise KeyError(f"No per-account DB found for account_id={account_id}")


# ── Write API ────────────────────────────────────────────────────────────────


def log_event(
    account_id: int,
    event_type: EventType,
    payload: Dict[str, Any],
    source: str,
    *,
    timestamp: Optional[str] = None,
    data_dir: Optional[str] = None,
) -> int:
    """Insert one engine_events row.

    Args:
        account_id: Account this event belongs to.
        event_type: Must be one of the ``EventType`` literals.
        payload: Arbitrary dict — stored as JSON.
        source: Originating module/subsystem (e.g. ``"data_cache"``,
                ``"ready_state"``, ``"ui_override"``).
        timestamp: ISO-8601 string. Defaults to ``datetime.now(UTC)``.
        data_dir: Override for tests.

    Returns:
        The ``id`` (ROWID) of the inserted row.

    Raises:
        ValueError: Unknown *event_type*.
        KeyError: No per-account DB for *account_id*.
    """
    if event_type not in _VALID_EVENT_TYPES:
        raise ValueError(
            f"Unknown event_type {event_type!r}. "
            f"Valid: {sorted(_VALID_EVENT_TYPES)}"
        )

    ts = timestamp or datetime.now(timezone.utc).isoformat()
    payload_json = json.dumps(payload, default=str)

    db_path = _resolve_db_path(account_id, data_dir)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO engine_events "
            "(account_id, event_type, payload_json, timestamp, source) "
            "VALUES (?, ?, ?, ?, ?)",
            (account_id, event_type, payload_json, ts, source),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]
    finally:
        conn.close()


# ── Read API ─────────────────────────────────────────────────────────────────


def query_events(
    account_id: int,
    *,
    event_type: Optional[str] = None,
    from_ts: Optional[str] = None,
    to_ts: Optional[str] = None,
    limit: int = 100,
    data_dir: Optional[str] = None,
) -> list[dict]:
    """Query engine_events rows for *account_id*.

    Returns list of dicts (newest first). Filters by event_type and
    timestamp range when provided.
    """
    db_path = _resolve_db_path(account_id, data_dir)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        clauses = ["account_id = ?"]
        params: list = [account_id]
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if from_ts:
            clauses.append("timestamp >= ?")
            params.append(from_ts)
        if to_ts:
            clauses.append("timestamp <= ?")
            params.append(to_ts)
        where = " AND ".join(clauses)
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM engine_events WHERE {where} "
            f"ORDER BY timestamp DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
