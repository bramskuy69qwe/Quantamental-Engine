"""
Exec Link — tolerance-based matching of entry fills against pre_trade_log.

Match criteria currently considered (1/1 semantics):
  1. Entry price (skipped — auto-pass — for market orders)

TP/SL fields are computed and returned on ExecMatchResult for informational
display, but DO NOT contribute to match_count or auto_link decisions. The
TP/SL match logic in compute_exec_match currently self-compares the pretrade
plan against itself and always returns True for non-None values — this is a
known stub pending Phase 9 (TP/SL modification tracking), which will introduce
plan-vs-actual comparison by threading placed TP/SL order data through the
caller. Until that lands, only entry-price matching is meaningful, and the
badge displays 1/1 LINKED rather than misleading 3/3.

See: docs/audits/2026-05-17-v2.4-backend-audit.md [CRIT-004]
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


DEFAULT_LINK_WINDOW_SECONDS = 21600  # 6 h — matches accounts.link_window_seconds default


def compute_exec_match(
    fill: dict,
    pretrade: dict,
    order_type: str = "",
    fill_ts_ms: Optional[int] = None,
    pretrade_ts_ms: Optional[int] = None,
    account_link_window_seconds: int = DEFAULT_LINK_WINDOW_SECONDS,
) -> Optional[ExecMatchResult]:
    """Match a fill against its pre_trade_log entry.

    1/1 semantics: only entry_match contributes to match_count and auto_link.
    tp_match and sl_match are informational stubs (always True for non-None
    pretrade values) pending Phase 9 plan-vs-actual implementation.

    HIGH-027 (Task 104a): when both fill_ts_ms and pretrade_ts_ms are
    supplied, the candidate is hard-rejected (return None) if the elapsed
    time exceeds the effective link window. Effective window =
    pretrade['link_window_seconds_override'] (if set, non-NULL) else
    account_link_window_seconds. Callers that don't pass timestamps skip
    the window check entirely — additive, not breaking.

    Window rejection shape: Option A (hard reject → None). Caller treats
    None as "no candidate" rather than "candidate with window_match=False".
    Simpler caller contract; matches the audit's "reject" framing.
    """
    if fill_ts_ms is not None and pretrade_ts_ms is not None:
        override = pretrade.get("link_window_seconds_override")
        effective_window_s = (
            override if override is not None else account_link_window_seconds
        )
        # int division by 1000 — sub-second precision is irrelevant here
        elapsed_s = (fill_ts_ms - pretrade_ts_ms) / 1000.0
        if elapsed_s > effective_window_s:
            return None

    is_market = order_type.upper() in ("MARKET", "STOP_MARKET")

    entry_match = True if is_market else price_near(
        pretrade.get("effective_entry") or pretrade.get("average"),
        fill.get("price"),
    )

    # CRIT-004 stub: TP/SL self-compare always returns True for non-None values.
    # Informational only — does NOT contribute to match_count/auto_link.
    # Real plan-vs-actual comparison: Phase 9 (TP/SL modification tracking).
    tp_match = price_near(pretrade.get("tp_price"), pretrade.get("tp_price"))
    sl_match = price_near(pretrade.get("sl_price"), pretrade.get("sl_price"))

    # 1/1 semantics: only entry_match counts toward linkage.
    count = 1 if entry_match else 0
    auto_link = bool(entry_match)

    return ExecMatchResult(
        pretrade_id=pretrade.get("id"),
        entry_match=entry_match,
        tp_match=tp_match,
        sl_match=sl_match,
        match_count=count,
        auto_link=auto_link,
        is_market=is_market,
        pretrade_entry=pretrade.get("effective_entry") or pretrade.get("average"),
        pretrade_tp=pretrade.get("tp_price"),
        pretrade_sl=pretrade.get("sl_price"),
        fill_price=fill.get("price", 0),
    )


def get_exec_link_status(
    fill: dict,
    pretrade: Optional[dict],
    order_type: str = "",
    fill_ts_ms: Optional[int] = None,
    pretrade_ts_ms: Optional[int] = None,
    account_link_window_seconds: int = DEFAULT_LINK_WINDOW_SECONDS,
) -> tuple[str, int]:
    """Returns (status, match_count). Status: 'linked' | 'partial' | 'unlinked'.

    Under 1/1 semantics, "partial" is currently unreachable (match_count is
    0 or 1 only). The branch is preserved for forward compatibility — Phase 9
    will restore TP/SL contributions and reactivate the partial state.

    HIGH-027 (Task 104a): forwards timestamps + account window to
    compute_exec_match. A past-window candidate comes back as None and is
    reported as 'unlinked' here. The exec_link_confirmed fast-path is
    preserved: once an operator has confirmed a linkage, the window check
    no longer matters (the confirmation is authoritative).
    """
    if not fill.get("calc_id"):
        return "unlinked", 0
    if fill.get("exec_link_confirmed"):
        return "linked", 1  # was 3 pre-CRIT-004 fix
    if not pretrade:
        return "unlinked", 0
    result = compute_exec_match(
        fill, pretrade, order_type,
        fill_ts_ms=fill_ts_ms,
        pretrade_ts_ms=pretrade_ts_ms,
        account_link_window_seconds=account_link_window_seconds,
    )
    if result is None:
        # HIGH-027: past-window candidate — treat as no link.
        return "unlinked", 0
    if result.auto_link:
        return "linked", result.match_count
    elif result.match_count > 0:
        # Currently unreachable; reserved for Phase 9.
        return "partial", result.match_count
    return "unlinked", 0
