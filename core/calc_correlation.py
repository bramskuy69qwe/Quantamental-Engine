"""
Calculator-to-order correlation via triple-match.

Matches an entry order to the calculator recommendation that produced it
by comparing (entry_price, tp_price, sl_price) within tick-size tolerance.

This is the heuristic fallback; a future Quantower plugin may supply
calc_id directly via clientOrderId prefix.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("calc_correlation")

_MATCH_WINDOW_HOURS = 24


def correlate_order_to_calc(
    order: Dict[str, Any],
    *,
    tick_size: float,
    db_path: Optional[str] = None,
    data_dir: Optional[str] = None,
) -> Optional[str]:
    """Attempt to match *order* to a pre_trade_log entry via triple-match.

    Returns the ``calc_id`` if a match is found, else ``None``.

    Skips (returns None) when:
    - Order is a market order (no intent entry price).
    - Order is missing tp_trigger_price or sl_trigger_price (strict match).
    - No unmatched pre_trade_log entry within tolerance + time window.

    On multiple matches, returns the most recent (by timestamp).
    """
    # Skip market orders — no reliable entry price intent
    order_type = (order.get("order_type") or "").lower()
    is_market = order_type == "market"

    entry_price = order.get("price")
    tp_price = order.get("tp_trigger_price")
    sl_price = order.get("sl_trigger_price")

    # Market orders: match on tp+sl only (entry is wildcard)
    # Limit orders: strict triple-match (all three required)
    if is_market:
        if not tp_price or not sl_price:
            return None  # need both TP/SL for market correlation
    else:
        if not entry_price or not tp_price or not sl_price:
            return None

    ticker = order.get("symbol", "")
    side = order.get("side", "")
    if not ticker or not side:
        return None

    # Resolve DB path
    if db_path is None:
        try:
            from core.db_account_settings import _resolve_db_path
            account_id = order.get("account_id", 1)
            db_path = _resolve_db_path(account_id, data_dir)
        except Exception:
            return None

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=_MATCH_WINDOW_HOURS)).isoformat()

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT calc_id, effective_entry, tp_price, sl_price, timestamp "
            "FROM pre_trade_log "
            "WHERE ticker = ? AND side = ? AND timestamp >= ? "
            "AND calc_id IS NOT NULL "
            "AND calc_id NOT IN (SELECT calc_id FROM pre_trade_log "
            "  WHERE calc_id IS NOT NULL "
            "  GROUP BY calc_id HAVING COUNT(*) > 0 "
            "  INTERSECT "
            "  SELECT DISTINCT calc_id FROM pre_trade_log WHERE calc_id IS NOT NULL) "
            "ORDER BY timestamp DESC",
            (ticker, side, cutoff),
        ).fetchall()
        conn.close()
    except Exception:
        log.warning("calc correlation query failed", exc_info=True)
        return None

    # Simple approach: query all recent candidates and filter in Python
    # (avoids complex SQL for float tolerance)
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT calc_id, effective_entry, tp_price, sl_price, timestamp "
            "FROM pre_trade_log "
            "WHERE ticker = ? AND side = ? AND timestamp >= ? "
            "AND calc_id IS NOT NULL "
            "ORDER BY timestamp DESC",
            (ticker, side, cutoff),
        ).fetchall()
        conn.close()
    except Exception:
        log.warning("calc correlation query failed", exc_info=True)
        return None

    for row in rows:
        calc_id = row["calc_id"]
        if not calc_id:
            continue

        # Match within tick tolerance
        # Market orders: tp+sl only (entry is wildcard)
        # Limit orders: all three legs
        tp_ok = abs(row["tp_price"] - tp_price) <= tick_size
        sl_ok = abs(row["sl_price"] - sl_price) <= tick_size
        entry_ok = is_market or (entry_price and abs(row["effective_entry"] - entry_price) <= tick_size)
        if entry_ok and tp_ok and sl_ok:
            # Check this calc_id isn't already used by another order
            try:
                conn = sqlite3.connect(db_path)
                used = conn.execute(
                    "SELECT 1 FROM orders WHERE calc_id = ? LIMIT 1",
                    (calc_id,),
                ).fetchone()
                conn.close()
                if used:
                    continue  # already linked
            except Exception:
                pass  # orders table may not exist in per-account DB

            return calc_id

    return None  # no match found


# ── Manual link candidate finder ─────────────────────────────────────────────


@dataclass
class CandidateCalc:
    calc_id: str
    ticker: str
    side: str
    effective_entry: float
    entry_drift_pct: float
    entry_match: bool
    tp_price: float
    tp_drift_pct: float
    tp_match: bool
    sl_price: float
    sl_drift_pct: float
    sl_match: bool
    timestamp: str
    age_hours: float


def find_candidate_calcs(
    order: Dict[str, Any],
    *,
    max_drift_pct: float = 0.05,
    within_hours: int = 168,
    db_path: Optional[str] = None,
    data_dir: Optional[str] = None,
) -> List[CandidateCalc]:
    """Find pre_trade_log entries that might match *order* within drift tolerance.

    Includes candidates where at least ONE leg matches within max_drift_pct.
    Sorted by: count-of-matching-legs DESC, drift sum ASC, timestamp DESC.
    """
    entry_price = order.get("price", 0)
    tp_price = order.get("tp_trigger_price", 0)
    sl_price = order.get("sl_trigger_price", 0)
    ticker = order.get("symbol", "")
    side = order.get("side", "")

    if not ticker or not entry_price:
        return []

    if db_path is None:
        try:
            from core.db_account_settings import _resolve_db_path
            db_path = _resolve_db_path(order.get("account_id", 1), data_dir)
        except Exception:
            return []

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=within_hours)).isoformat()
    now = datetime.now(timezone.utc)

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT calc_id, effective_entry, tp_price, sl_price, timestamp "
            "FROM pre_trade_log "
            "WHERE ticker = ? AND side = ? AND timestamp >= ? "
            "AND calc_id IS NOT NULL "
            "ORDER BY timestamp DESC",
            (ticker, side, cutoff),
        ).fetchall()
        conn.close()
    except Exception:
        return []

    # Filter out already-linked calc_ids
    linked: set = set()
    try:
        conn = sqlite3.connect(db_path)
        for r in conn.execute(
            "SELECT DISTINCT calc_id FROM orders WHERE calc_id IS NOT NULL"
        ).fetchall():
            linked.add(r[0])
        conn.close()
    except Exception:
        pass

    candidates: List[CandidateCalc] = []
    for row in rows:
        cid = row["calc_id"]
        if not cid or cid in linked:
            continue

        eff = row["effective_entry"] or 0
        tp = row["tp_price"] or 0
        sl = row["sl_price"] or 0

        e_drift = abs(entry_price - eff) / eff if eff else 1.0
        t_drift = abs(tp_price - tp) / tp if tp and tp_price else 1.0
        s_drift = abs(sl_price - sl) / sl if sl and sl_price else 1.0

        e_match = e_drift <= max_drift_pct
        t_match = t_drift <= max_drift_pct
        s_match = s_drift <= max_drift_pct

        if not (e_match or t_match or s_match):
            continue

        try:
            ts = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_h = (now - ts).total_seconds() / 3600
        except Exception:
            age_h = 0

        candidates.append(CandidateCalc(
            calc_id=cid, ticker=ticker, side=side,
            effective_entry=eff, entry_drift_pct=round(e_drift, 6), entry_match=e_match,
            tp_price=tp, tp_drift_pct=round(t_drift, 6), tp_match=t_match,
            sl_price=sl, sl_drift_pct=round(s_drift, 6), sl_match=s_match,
            timestamp=row["timestamp"], age_hours=round(age_h, 1),
        ))

    candidates.sort(key=lambda c: (
        -(int(c.entry_match) + int(c.tp_match) + int(c.sl_match)),
        c.entry_drift_pct + c.tp_drift_pct + c.sl_drift_pct,
        c.timestamp,
    ))
    return candidates
