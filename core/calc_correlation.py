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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

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
    if order_type == "market":
        return None

    entry_price = order.get("price")
    tp_price = order.get("tp_trigger_price")
    sl_price = order.get("sl_trigger_price")

    # Strict: all three legs required
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

        # Check triple-match within tick tolerance
        if (abs(row["effective_entry"] - entry_price) <= tick_size
                and abs(row["tp_price"] - tp_price) <= tick_size
                and abs(row["sl_price"] - sl_price) <= tick_size):
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

    return None
