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
    "position_amended",  # P4.T4 (spec §9 position:amended): one per order_amendments insert
    "tp_modified",
    "sl_modified",
    "liquidated",
    "manual_close",
    "manual_link_added",
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

    Returns the row id, or -1 if the write was rejected by the T168
    pollution guard. Raises ValueError for unknown event_type.
    """
    if event_type not in _VALID_TRADE_EVENT_TYPES:
        raise ValueError(
            f"Unknown trade event_type {event_type!r}. "
            f"Valid: {sorted(_VALID_TRADE_EVENT_TYPES)}"
        )

    # Task 168 (FE-MED-017 defense-in-depth): pollution guard mirroring
    # the closed_positions write-path guard in db_orders. Real
    # position_closed events emitted by order_manager (line ~736) carry
    # entry_price from the canonical close-row computation and are
    # always positive. The 278 BTCUSDT pre-prod test fixtures had
    # entry_price=0.0 while exit_price > 0 — a shape that can't arise
    # from any real fill path. Reject + log.warning so future pollution
    # sources surface immediately rather than silently accumulating.
    if event_type == "position_closed":
        p = payload or {}
        entry = float(p.get("entry_price", 0) or 0)
        exit_p = float(p.get("exit_price", 0) or 0)
        if entry <= 0 and exit_p > 0:
            log.warning(
                "T168 FE-MED-017 reject: trade_event 'position_closed' "
                "has pollution shape (entry_price=%r, exit_price=%r, "
                "symbol=%r, calc_id=%r) — refusing write",
                entry, exit_p, p.get("symbol", ""), calc_id,
            )
            return -1

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
    symbol: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    data_dir: Optional[str] = None,
) -> tuple[list[dict], int]:
    """Query trade_events rows. Newest first. Returns (rows, total_count).

    ``symbol`` (#3, debug 2026-06-09) matches the payload's ``symbol`` field
    (``json_extract``) — the per-position drilldown attributes order-lifecycle
    events (order_placed / order_filled / order_canceled incl. TP/SL amends /
    partial_close) by symbol within the position's time-window, because on the
    observe-only Binance path those events carry no calc_id (market orders link
    post-fill) and bracket orders carry no calc_id or tpid at all."""
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
        if symbol:
            clauses.append("json_extract(payload_json, '$.symbol') = ?")
            params.append(symbol)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until:
            clauses.append("timestamp <= ?")
            params.append(until)
        where = " AND ".join(clauses)

        total = conn.execute(
            f"SELECT COUNT(*) FROM trade_events WHERE {where}", params,
        ).fetchone()[0]

        rows = conn.execute(
            f"SELECT * FROM trade_events WHERE {where} "
            f"ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        return [dict(r) for r in rows], total
    except sqlite3.OperationalError:
        return [], 0  # table may not exist yet
    finally:
        conn.close()
