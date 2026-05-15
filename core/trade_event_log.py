"""
Write + read API for the ``trade_events`` per-trade lifecycle log.

Mirrors ``core.event_log`` (engine-level audit trail) but covers
per-trade events: order placement, cancellation, fills, position
open/close, TP/SL modifications, liquidations.

Higher volume than engine_events; retained indefinitely (feeds v2.6
backtest slippage model). calc_id is the primary lookup key.
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

log = logging.getLogger("trade_event_log")


# ── Event types ──────────────────────────────────────────────────────────────

TradeEventType = Literal[
    "calc_created",
    "order_placed",
    "order_canceled",
    "order_filled",
    "position_opened",
    "position_closed",
    "partial_close",
    "tp_modified",
    "sl_modified",
    "liquidated",
    "manual_close",
]

_VALID_TRADE_EVENT_TYPES: frozenset[str] = frozenset(
    TradeEventType.__args__  # type: ignore[attr-defined]
)


# ── Path resolution ──────────────────────────────────────────────────────────


def _resolve_db_path(account_id: int, data_dir: Optional[str] = None) -> str:
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


def log_trade_event(
    account_id: int,
    calc_id: Optional[str],
    event_type: TradeEventType,
    payload: Dict[str, Any],
    source: str,
    *,
    timestamp: Optional[str] = None,
    data_dir: Optional[str] = None,
) -> int:
    """Insert one trade_events row.

    Returns the row id. Raises ValueError for unknown event_type.
    """
    if event_type not in _VALID_TRADE_EVENT_TYPES:
        raise ValueError(
            f"Unknown trade event_type {event_type!r}. "
            f"Valid: {sorted(_VALID_TRADE_EVENT_TYPES)}"
        )

    ts = timestamp or datetime.now(timezone.utc).isoformat()
    payload_json = json.dumps(payload, default=str)

    db_path = _resolve_db_path(account_id, data_dir)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO trade_events "
            "(account_id, calc_id, event_type, payload_json, source, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (account_id, calc_id, event_type, payload_json, source, ts),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]
    finally:
        conn.close()


# ── Read API ─────────────────────────────────────────────────────────────────


def query_trade_events(
    *,
    account_id: int,
    calc_id: Optional[str] = None,
    event_type: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 100,
    data_dir: Optional[str] = None,
) -> list[dict]:
    """Query trade_events rows. Newest first. Filters by calc_id, type, time."""
    db_path = _resolve_db_path(account_id, data_dir)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        clauses = ["account_id = ?"]
        params: list = [account_id]
        if calc_id is not None:
            clauses.append("calc_id = ?")
            params.append(calc_id)
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until:
            clauses.append("timestamp <= ?")
            params.append(until)
        where = " AND ".join(clauses)
        params.append(limit)
        rows = conn.execute(
            f"SELECT * FROM trade_events WHERE {where} "
            f"ORDER BY timestamp DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
