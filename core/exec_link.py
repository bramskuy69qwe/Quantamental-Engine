"""
Exec Link — tolerance-based matching of entry fills against pre_trade_log.

Compares actual fill price + TP/SL against planned values. Three criteria:
  1. Entry price (skipped for market orders)
  2. TP price
  3. SL price

Match result: 3/3 auto-linked, 1-2/3 partial, 0/3 unlinked.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import config


@dataclass
class ExecMatchResult:
    pretrade_id: Optional[int]
    entry_match: bool
    tp_match: bool
    sl_match: bool
    match_count: int
    auto_link: bool
    is_market: bool
    pretrade_entry: Optional[float]
    pretrade_tp: Optional[float]
    pretrade_sl: Optional[float]
    fill_price: float


def price_near(a: Optional[float], b: Optional[float]) -> bool:
    """True if a and b are within EXEC_LINK_PRICE_TOL relative tolerance."""
    if a is None or b is None:
        return False
    if a == 0 and b == 0:
        return True
    tol = config.EXEC_LINK_PRICE_TOL
    return abs(a - b) <= max(abs(a), abs(b)) * tol


def compute_exec_match(
    fill: dict, pretrade: dict, order_type: str = ""
) -> ExecMatchResult:
    """Match a fill against its pre_trade_log entry."""
    is_market = order_type.upper() in ("MARKET", "STOP_MARKET")

    entry_match = True if is_market else price_near(
        pretrade.get("effective_entry") or pretrade.get("average"),
        fill.get("price"),
    )

    tp_match = price_near(pretrade.get("tp_price"), pretrade.get("tp_price"))
    sl_match = price_near(pretrade.get("sl_price"), pretrade.get("sl_price"))

    count = sum([entry_match, tp_match, sl_match])

    return ExecMatchResult(
        pretrade_id=pretrade.get("id"),
        entry_match=entry_match,
        tp_match=tp_match,
        sl_match=sl_match,
        match_count=count,
        auto_link=(count == 3),
        is_market=is_market,
        pretrade_entry=pretrade.get("effective_entry") or pretrade.get("average"),
        pretrade_tp=pretrade.get("tp_price"),
        pretrade_sl=pretrade.get("sl_price"),
        fill_price=fill.get("price", 0),
    )


def get_exec_link_status(fill: dict, pretrade: Optional[dict], order_type: str = "") -> tuple[str, int]:
    """Returns (status, match_count). Status: 'linked' | 'partial' | 'unlinked'."""
    if not fill.get("calc_id"):
        return "unlinked", 0
    if fill.get("exec_link_confirmed"):
        return "linked", 3
    if not pretrade:
        return "unlinked", 0
    result = compute_exec_match(fill, pretrade, order_type)
    if result.auto_link:
        return "linked", result.match_count
    elif result.match_count > 0:
        return "partial", result.match_count
    return "unlinked", 0
