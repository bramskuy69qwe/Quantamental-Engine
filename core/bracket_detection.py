"""TP/SL bracket detection (Phase 2.8, spec §4.5).

A *bracket* is an entry order plus the TP/SL (protective) orders placed
together with it as one venue-native bracket. Detecting the sibling set
lets Phase 2.9 propagate the entry's ``calc_id`` onto its TP/SL orders
without re-running the matcher on them.

This module is the venue-agnostic detection ENGINE. Each adapter exposes
a thin ``detect_bracket()`` that calls :func:`detect_brackets` with its
venue-native shared-link field (if any):

  - Binance: no shared bracket id on the order record (clientOrderId is
    unique per order, exchange_position_id is empty on the observe-only
    WS path) → ``link_field=None`` → falls to (symbol, position_side) +
    time-window clustering. positionSide is populated, so it is the
    direction key.
  - Bybit: ``orderLinkId`` (stored in ``client_order_id``) — a venue
    shared id when the platform sets the same value across bracket legs
    → ``link_field="client_order_id"`` (with the same time-window
    fallback for any legs that don't share it).
  - MEXC: no shared id AND no position_side / reduce_only on the order
    record → ``link_field=None`` → (symbol, <none>) + time-window only;
    entry-vs-protective discrimination is by ``order_type``.

OKX is named in earlier spec drafts (algoOrdId) but there is no OKX
adapter; MT4/MT5 (forex) brokers are forward-looking. Both out of scope.

SCOPE (T2.8 = DETECT ONLY): this module groups orders into brackets. It
performs NO ``calc_id`` writes — propagation is Phase 2.9. Standalone /
post-entry TP-SL (placed separately, or a protective stop on an
already-open position) is NOT a bracket (spec §15 R2 / removed T2.10) and
goes through the standard matcher; a bracket here requires BOTH an entry
leg and a protective leg placed together.

Input shape: order DICTS (the engine's stored order shape) carrying
``symbol``, ``position_side``, ``order_type``, ``reduce_only``,
``created_at_ms``, and the chosen ``link_field``. The two-tier heuristic
is best-effort: the time-window tier can mis-group two entries placed on
the same (symbol, side) within the window — Phase 2.9 only propagates
from an entry that actually carries a calc_id, which bounds the impact.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# order_type values that denote a protective EXIT leg (TP or SL).
_PROTECTIVE_TYPES = frozenset({
    "take_profit", "take_profit_market", "take_profit_limit",
    "stop_loss", "stop_market", "stop_loss_limit", "trailing_stop",
})
# order_type values that denote an ENTRY leg.
_ENTRY_TYPES = frozenset({"limit", "market"})

DEFAULT_WINDOW_MS = 2000


def _otype(o: Dict[str, Any]) -> str:
    return (o.get("order_type") or "").lower()


def is_protective_leg(o: Dict[str, Any]) -> bool:
    """True if the order is a TP/SL (protective exit) leg.

    Keyed on ``order_type`` (universal across adapters — MEXC carries no
    ``reduce_only``), with ``reduce_only`` as a secondary signal for a
    plain market/limit reduce-only close. The FE-13 ``_entry`` suffix
    marks a non-reduce-only stop used as an ENTRY (e.g. ``stop_loss_entry``)
    — that is an entry leg, not protective.
    """
    ot = _otype(o)
    if ot.endswith("_entry"):
        return False
    if ot in _PROTECTIVE_TYPES:
        return True
    return bool(o.get("reduce_only"))


def is_entry_leg(o: Dict[str, Any]) -> bool:
    """True if the order is an entry leg (opens/adds to a position)."""
    ot = _otype(o)
    if ot.endswith("_entry"):
        return True
    if ot in _PROTECTIVE_TYPES:
        return False
    return ot in _ENTRY_TYPES and not o.get("reduce_only")


def _is_bracket(group: List[Dict[str, Any]]) -> bool:
    """A bracket needs ≥2 legs including at least one entry AND at least
    one protective leg (spec §4.5: entry + TP/SL placed together). A
    cluster of only-entries or only-protective (standalone TP/SL) is not
    a bracket."""
    if len(group) < 2:
        return False
    return (any(is_entry_leg(o) for o in group)
            and any(is_protective_leg(o) for o in group))


def detect_brackets(
    orders: List[Dict[str, Any]],
    *,
    link_field: Optional[str] = None,
    window_ms: int = DEFAULT_WINDOW_MS,
) -> List[List[Dict[str, Any]]]:
    """Group ``orders`` into brackets (entry + its TP/SL siblings).

    Two-tier (spec §4.5):
      1. Venue-native: if ``link_field`` is given, orders sharing the same
         non-empty value of that field are siblings (e.g. Bybit
         orderLinkId). Singletons fall through to tier 2.
      2. Fallback: cluster the remaining orders by (symbol, position_side)
         where orders within ``window_ms`` of the cluster's first leg are
         siblings (cluster span ≤ window_ms) — "placed together" detection.

    Returns the list of detected brackets (each a list of the sibling
    order dicts, ordered by ``created_at_ms``). Only clusters that satisfy
    :func:`_is_bracket` (≥1 entry + ≥1 protective leg) are returned;
    singletons and non-bracket clusters are dropped. Input is never
    mutated.
    """
    if not orders:
        return []

    groups: List[List[Dict[str, Any]]] = []
    remaining = list(orders)

    # ── Tier 1: venue-native shared link id ─────────────────────────────
    if link_field:
        by_link: Dict[str, List[Dict[str, Any]]] = {}
        rest: List[Dict[str, Any]] = []
        for o in remaining:
            key = str(o.get(link_field) or "")
            if key:
                by_link.setdefault(key, []).append(o)
            else:
                rest.append(o)
        for grp in by_link.values():
            if len(grp) >= 2:
                groups.append(sorted(grp, key=_ts))
            else:
                rest.extend(grp)   # lone shared-id → retry in tier 2
        remaining = rest

    # ── Tier 2: (symbol, position_side) + time-window clustering ────────
    cohorts: Dict[tuple, List[Dict[str, Any]]] = {}
    for o in remaining:
        ck = (o.get("symbol", ""), str(o.get("position_side") or ""))
        cohorts.setdefault(ck, []).append(o)
    for cohort in cohorts.values():
        cohort = sorted(cohort, key=_ts)
        cluster = [cohort[0]]
        anchor = _ts(cohort[0])
        for cur in cohort[1:]:
            # ANCHOR-bounded (not predecessor-bounded): a leg joins only if
            # within window_ms of the cluster's FIRST order, so a cluster's
            # total span never exceeds window_ms. This is the spec's "within
            # N seconds of each other" (§4.5) and avoids transitive
            # over-grouping — a drip of orders each <window_ms from the
            # previous would otherwise chain into one oversized bracket
            # spanning >> window_ms (T236 review). Conservative by design:
            # a legitimately slow-staggered bracket spanning >window_ms
            # splits and its legs fall to the standard matcher (T2.10),
            # which is safer than merging two distinct trades' legs.
            if _ts(cur) - anchor <= window_ms:
                cluster.append(cur)
            else:
                groups.append(cluster)
                cluster = [cur]
                anchor = _ts(cur)
        groups.append(cluster)

    return [g for g in groups if _is_bracket(g)]


def _ts(o: Dict[str, Any]) -> int:
    return int(o.get("created_at_ms", 0) or 0)
