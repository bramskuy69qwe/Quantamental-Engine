"""
Shared dd_state gate logic for calculator and order placement paths.

Pure check function — returns (eligible, reason). Callers handle their
own event logging to preserve dedup semantics (ReadyStateEvaluator logs
would_have_blocked / calculator_blocked; order_manager would log its own).

Per v2.4.md 1c: limit blocks new entries only. TP/SL modifications and
reduce-only closes always pass regardless of dd_state.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger("dd_gate")


def dd_gate_allows_new_entry(account_id: int) -> Tuple[bool, Optional[str]]:
    """Check whether a new entry is allowed for *account_id*.

    Returns ``(True, None)`` if allowed.
    Returns ``(False, reason_string)`` if blocked by dd_state.

    Allowed when:
    - dd_state is not "limit"
    - enforcement_mode is "advisory" (limit logged, not enforced)
    - account is in the manual-override set
    """
    from core.state import app_state

    pf = app_state.portfolio
    if pf.dd_state != "limit":
        return True, None

    # Manual override bypass
    if account_id in app_state.dd_manually_unblocked:
        return True, None

    # Read enforcement mode
    try:
        from core.db_account_settings import get_account_settings
        settings = get_account_settings(account_id)
        mode = settings.dd_enforcement_mode
        limit_t = settings.dd_limit_threshold or 0
    except Exception:
        return True, None  # can't read settings → don't block

    if mode != "enforced":
        return True, None  # advisory: allowed (caller may log shadow event)

    dd_pct = pf.drawdown
    reason = (
        f"dd_state=limit (drawdown={dd_pct:.2%}, "
        f"threshold={limit_t:.2%}, mode=enforced)"
    )
    return False, reason


def is_new_entry(order: Dict[str, Any]) -> bool:
    """Classify whether an order opens new position exposure.

    Returns True for new entries. Returns False for:
    - reduce_only orders (closing existing exposure)
    - TP/SL modifications (attached to existing position)
    - Orders with close_position flag

    Order types that are NOT new entries:
    - stop_loss, take_profit, trailing_stop (modifications)
    - Any order with reduce_only=True
    """
    # Explicit reduce-only flag
    if order.get("reduce_only"):
        return False

    # Close-position flag
    if order.get("close_position"):
        return False

    # TP/SL order types are modifications, not new entries
    order_type = (order.get("order_type") or "").lower()
    if order_type in ("stop_loss", "take_profit", "trailing_stop",
                      "stop_loss_limit", "take_profit_limit",
                      "stop_market", "take_profit_market"):
        return False

    return True
