"""
Order lifecycle state machine — status enum, valid transitions, terminal mappings.

No behavior change: consumed by OrderManager (Phase 6) and platform_bridge (Phase 8).
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, Set


class OrderStatus(str, Enum):
    NEW              = "new"
    PARTIALLY_FILLED = "partially_filled"
    FILLED           = "filled"
    CANCELED         = "canceled"
    EXPIRED          = "expired"
    REJECTED         = "rejected"


VALID_TRANSITIONS: Dict[OrderStatus, Set[OrderStatus]] = {
    OrderStatus.NEW:              {OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED,
                                   OrderStatus.CANCELED, OrderStatus.EXPIRED, OrderStatus.REJECTED},
    OrderStatus.PARTIALLY_FILLED: {OrderStatus.FILLED, OrderStatus.CANCELED},
    # Terminal states — no transitions out
    OrderStatus.FILLED:           set(),
    OrderStatus.CANCELED:         set(),
    OrderStatus.EXPIRED:          set(),
    OrderStatus.REJECTED:         set(),
}

TERMINAL_STATES = {OrderStatus.FILLED, OrderStatus.CANCELED, OrderStatus.EXPIRED, OrderStatus.REJECTED}
ACTIVE_STATES   = {OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED}


def validate_transition(current: str, target: str) -> bool:
    """Return True if current → target is a valid order status transition."""
    try:
        return OrderStatus(target) in VALID_TRANSITIONS[OrderStatus(current)]
    except (ValueError, KeyError):
        return False


# ── Quantower terminal → engine status mapping ─────────────────────────────

QT_STATUS_MAP: Dict[str, str] = {
    "Opened":          OrderStatus.NEW,
    "PartiallyFilled": OrderStatus.PARTIALLY_FILLED,
    "Filled":          OrderStatus.FILLED,
    "Cancelled":       OrderStatus.CANCELED,
    "Refused":         OrderStatus.REJECTED,
    "Inactive":        OrderStatus.EXPIRED,
    "Unspecified":     OrderStatus.NEW,
}


# ── Quantower terminal → engine order type mapping ─────────────────────────

QT_ORDER_TYPE_MAP: Dict[str, str] = {
    "Limit":              "limit",
    "Market":             "market",
    "StopMarket":         "stop_loss",
    "StopLimit":          "stop_loss",
    "TakeProfitMarket":   "take_profit",
    "TakeProfitLimit":    "take_profit",
    "TrailingStop":       "trailing_stop",
}
