"""
Order lifecycle state machine — status enum, valid transitions, terminal mappings.

Consumed by OrderManager and the WS/exchange order pipeline.
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


# ── TP/SL order direction resolution (hedge + one-way modes) ───────────────

def resolve_tpsl_direction(position_side: str | None, side: str) -> str:
    """Resolve position direction for TP/SL order matching.

    In hedge mode, position_side is 'LONG'/'SHORT' — use directly.
    In one-way mode, position_side is 'BOTH' — infer from order side
    using close-order semantics (TP/SL are reduceOnly):
      SELL reduces LONG → direction is LONG
      BUY  reduces SHORT → direction is SHORT

    Scope: TP/SL matching only. Do NOT apply to entry-order matching
    where the side-to-direction mapping inverts.
    """
    if position_side and position_side != "BOTH":
        return position_side
    return "LONG" if side == "SELL" else "SHORT"
