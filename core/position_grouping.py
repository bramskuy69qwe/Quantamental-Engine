"""
Canonical "fills → position records" helper (Phase 0.0.1, T182).

Establishes a single source of truth for grouping fills into closed
position rows. Replaces three duplicated grouping paths that diverged:

1. ``order_manager._build_close_row_for_fill`` (live close-row builder,
   uses the broken ``get_position_fills`` ``(symbol, direction)``
   fallback when ``terminal_position_id`` is empty)
2. ``db_orders.exchange_history_backfill`` (ad-hoc
   ``(symbol, direction, open_time)`` grouping + synthetic fill
   duplication — T178 Layers 1 & 3)
3. One-off rebuild scripts (the T177 dryrun draft and the future
   ``scripts/rebuild_closed_positions.py``)

T178 audit reference:
``docs/audits/2026-05-25-t178-fills-data-quality.md`` — five corruption
layers identified in the existing fills + closed_positions data.

Grouping rule (no pos_id required):
  Walk fills chronologically, per-``(account_id, symbol, direction)``.
  Track net open quantity. A logical position OPENS on the first
  non-close fill when net qty was 0. Subsequent fills ADD
  (``is_close=0``) or REDUCE (``is_close=1``) the qty. When qty
  returns to 0 (within ``_QTY_EPS``), the position is CLOSED and a
  ``PositionRecord`` is emitted. A new position can then open on the
  next non-close fill.

Why this is correct: fills represent actual order executions in
chronological order. A position's lifecycle is fully defined by its
fills — opens add, closes subtract, until qty hits 0. Cross-position
contamination is impossible because each position's fills are
contiguous in the qty-tracked stream (a new position can't open
while qty > 0 for the same symbol/direction in one-way mode).

Caveats:
  - Hedge mode (LONG + SHORT positions simultaneously on the same
    symbol) is handled because we key on (account_id, symbol,
    direction). The LONG and SHORT positions have independent qty
    tracks.
  - If qty goes NEGATIVE (overfill — close qty > open qty), we
    flush the current position at qty=0 and log a warning. The
    reversal-split fix (Phase 0.0.4) will pre-process such events
    into two separate fill rows before they reach this helper, so
    this branch is a defensive fallback for pre-0.0.4 historical
    data.
  - Fills MUST be sorted chronologically AND deduplicated by the
    ``is_same_fill`` rule before being fed in. Duplicate fills
    (e.g., WS + REST or backfill-synthetic reporting the same trade)
    would double-count qty. Phase 0.0.2 stops new dups at the write
    path; Phase 0.0.3's ``scripts/dedup_fills.py`` cleans historical
    dups.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Tuple, TypedDict

log = logging.getLogger("position_grouping")

# Floating-point tolerance for "qty has returned to zero". Crypto futures
# typically use 3-8 decimal qty precision; 1e-6 is safely below.
_QTY_EPS = 1e-6

# ── Fill-dedup tolerance constants ──────────────────────────────────────
#
# Used by ``is_same_fill`` (and downstream Phase 0.0.2 dedup guard +
# Phase 0.0.3 dedup script) to decide whether two fill rows describe the
# same physical trade execution.
#
# Why 2 seconds: synthetic fills produced by ``exchange_history_backfill``
# carry a slightly different timestamp than the real WS/REST fill for the
# same trade (the synthetic is reconstructed from REALIZED_PNL accounting,
# which may use the order's close timestamp rather than the fill's). T178
# observed real Binance matching-engine splits (single client order →
# multiple matching-engine fills) using IDENTICAL timestamps, so 2s is
# wide enough to catch dual-write skew without collapsing legitimate
# multi-fill orders.
#
# Why price tolerance is exact (0.0): both sources should report
# identical prices since they come from the same trade execution. Any
# divergence indicates the fills are genuinely different.
FILL_DEDUP_TOLERANCE_MS = 2000
FILL_DEDUP_PRICE_TOLERANCE_PCT = 0.0


class PositionRecord(TypedDict, total=False):
    """Closed-position row shape emitted by ``group_fills_into_positions``.

    Matches the keys read by ``db_orders.insert_closed_position`` via
    its ``row.get(...)`` calls. ``total=False`` so callers can pass a
    subset and let ``insert_closed_position``'s ``.get`` defaults fill
    the rest — but in practice this helper populates every field with
    a deterministic value.

    Keep in sync with the ``closed_positions`` schema in
    ``core/database.py`` and the INSERT column list in
    ``core/db_orders.py:insert_closed_position``.

    MFE/MAE are intentionally left at 0.0 here — the reconciler runs
    after rebuild (``backfill_completed=0`` triggers it) and computes
    those with T175's gross-PnL floor applied. Don't try to re-derive
    MFE/MAE inside this helper; the reconciler is the canonical owner.
    """
    account_id: int
    exchange_position_id: str
    terminal_position_id: str
    symbol: str
    direction: str
    quantity: float
    entry_price: float
    exit_price: float
    entry_time_ms: int
    exit_time_ms: int
    realized_pnl: float
    total_fees: float
    net_pnl: float
    funding_fees: float
    hold_time_ms: int
    exit_reason: str
    model_name: str
    source: str
    calc_id: str
    mfe: float
    mae: float
    backfill_completed: int


def is_same_fill(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Return True if two fill rows describe the same physical trade execution.

    Matches by:
      - ``symbol``, ``side``, ``is_close``, ``quantity``, ``direction``: exact
      - ``timestamp_ms``: within ``FILL_DEDUP_TOLERANCE_MS``
      - ``price``: within ``FILL_DEDUP_PRICE_TOLERANCE_PCT`` (currently exact)

    Note: ``side`` (BUY/SELL) and ``direction`` (LONG/SHORT) are both
    compared because the close of a SHORT position is a BUY-side fill;
    matching on side alone would let a SHORT close collide with a LONG
    open at the same price/time/qty. Belt-and-braces.

    Quantity comparison uses ``_QTY_EPS`` to absorb floating-point
    representation drift from the dual-write JSON round-trip — Binance's
    REST and WS payloads encode quantities as decimal strings, and the
    json parser's float conversion can produce values that differ by
    one ULP.
    """
    if a.get("symbol", "") != b.get("symbol", ""):
        return False
    if (a.get("side", "") or "").upper() != (b.get("side", "") or "").upper():
        return False
    if (a.get("direction", "") or "").upper() != (b.get("direction", "") or "").upper():
        return False
    if bool(a.get("is_close", 0)) != bool(b.get("is_close", 0)):
        return False

    qty_a = float(a.get("quantity", 0) or 0)
    qty_b = float(b.get("quantity", 0) or 0)
    if abs(qty_a - qty_b) > _QTY_EPS:
        return False

    ts_a = int(a.get("timestamp_ms", 0) or 0)
    ts_b = int(b.get("timestamp_ms", 0) or 0)
    if abs(ts_a - ts_b) > FILL_DEDUP_TOLERANCE_MS:
        return False

    price_a = float(a.get("price", 0) or 0)
    price_b = float(b.get("price", 0) or 0)
    if FILL_DEDUP_PRICE_TOLERANCE_PCT <= 0.0:
        if price_a != price_b:
            return False
    else:
        denom = price_b if price_b else (price_a if price_a else 1.0)
        if abs(price_a - price_b) / abs(denom) > FILL_DEDUP_PRICE_TOLERANCE_PCT:
            return False

    return True


def group_fills_into_positions(
    fills: Iterable[Dict[str, Any]],
    fee_rate_fallback: float = 0.0,
) -> List[PositionRecord]:
    """Group chronologically-sorted, deduplicated fills into ``PositionRecord``s.

    Open-but-not-closed positions at the end of the input stream are
    NOT emitted (they're still live; ``closed_positions`` tracks closed
    positions only).

    Caller is responsible for:
      - sorting ``fills`` chronologically (``timestamp_ms ASC, id ASC``)
      - deduplicating via ``is_same_fill`` BEFORE passing in (this helper
        does not dedup — it walks the stream as authoritative)

    Args:
        fills: iterable of fill row dicts (column-name keys, matching
            the ``fills`` table schema in ``core/database.py``).
        fee_rate_fallback: if a position's fills all have ``fee=0``,
            estimate ``total_fees`` as ``fee_rate_fallback * notional *
            2`` (both sides). Set to 0.0 to disable. Used by the rebuild
            script when historical fills predate fee-recording.

    Returns:
        List of ``PositionRecord``s, one per closed logical position,
        in close-time order.
    """
    rows: List[PositionRecord] = []
    # state per (account_id, symbol, direction): accumulating opens + closes
    state: Dict[Tuple[int, str, str], Dict[str, Any]] = {}

    for f in fills:
        account_id = f.get("account_id", 1)
        symbol = f.get("symbol", "")
        direction = f.get("direction", "")
        if not symbol or not direction:
            log.warning(
                "position_grouping: skipping fill missing symbol/direction: %r",
                f.get("exchange_fill_id", "<no-id>"),
            )
            continue
        key = (account_id, symbol, direction)
        st = state.get(key)
        is_close = bool(f.get("is_close", 0))
        qty = float(f.get("quantity", 0) or 0)

        if qty <= 0:
            continue   # ignore zero-qty fills (rare data anomaly)

        if st is None:
            # New position opens (regardless of is_close — defensive: if
            # the first fill we see is a close, the prior opens are
            # missing from the input, so treat this as a noise event).
            if is_close:
                log.debug(
                    "position_grouping: closing fill with no prior open "
                    "(symbol=%s, dir=%s, qty=%s) — likely fills outside "
                    "input window; skipping",
                    symbol, direction, qty,
                )
                continue
            state[key] = {
                "account_id": account_id,
                "open_qty": qty,
                "opens": [f],
                "closes": [],
            }
            continue

        if is_close:
            st["closes"].append(f)
            st["open_qty"] -= qty
            if st["open_qty"] <= _QTY_EPS:
                # Position closed (or over-closed). Emit row.
                rows.append(_build_row(key, st, fee_rate_fallback))
                if st["open_qty"] < -_QTY_EPS:
                    # Over-closed: residual qty would conceptually open an
                    # opposite-direction position. In one-way mode this
                    # shouldn't happen; in hedge mode the opposite
                    # direction has its own state key. The reversal-split
                    # fix (Phase 0.0.4) will pre-process such events into
                    # two fill rows. Log + reset here as a defensive
                    # fallback for pre-0.0.4 historical data.
                    log.warning(
                        "position_grouping: over-close on %s %s — "
                        "residual qty %.6f after close; resetting state. "
                        "This typically means a fill was missed or the "
                        "data is duplicated. Review fills around %s.",
                        symbol, direction, st["open_qty"],
                        f.get("timestamp_ms"),
                    )
                del state[key]
        else:
            # Additional open (averaging in)
            st["opens"].append(f)
            st["open_qty"] += qty

    return rows


def _build_row(
    key: Tuple[int, str, str],
    st: Dict[str, Any],
    fee_rate_fallback: float,
) -> PositionRecord:
    """Build a ``PositionRecord`` from accumulated opens + closes."""
    account_id, symbol, direction = key
    opens: List[Dict[str, Any]] = st["opens"]
    closes: List[Dict[str, Any]] = st["closes"]

    total_open_qty = sum(float(f.get("quantity", 0) or 0) for f in opens)
    total_close_qty = sum(float(f.get("quantity", 0) or 0) for f in closes)

    entry_price = (
        sum(float(f["price"]) * float(f["quantity"]) for f in opens) / total_open_qty
        if total_open_qty else 0.0
    )
    exit_price = (
        sum(float(f["price"]) * float(f["quantity"]) for f in closes) / total_close_qty
        if total_close_qty else 0.0
    )
    entry_time_ms = min(int(f.get("timestamp_ms", 0) or 0) for f in opens)
    exit_time_ms = max(int(f.get("timestamp_ms", 0) or 0) for f in closes) if closes else 0

    # Fees from the fill records (each fill carries its own fee)
    total_fees = (
        sum(float(f.get("fee", 0) or 0) for f in opens)
        + sum(float(f.get("fee", 0) or 0) for f in closes)
    )
    # If any fill is missing fee, fall back to fee_rate_fallback × notional
    if total_fees == 0 and fee_rate_fallback > 0:
        notional = total_close_qty * exit_price
        total_fees = fee_rate_fallback * notional * 2  # both sides

    # Realized PnL from close fills (each carries its own realized_pnl when
    # the WS/REST recorder set it). Fall back to math if not provided.
    realized_pnl = sum(float(f.get("realized_pnl", 0) or 0) for f in closes)
    if realized_pnl == 0 and total_close_qty > 0 and entry_price > 0:
        # Gross PnL math fallback
        if direction == "LONG":
            realized_pnl = (exit_price - entry_price) * total_close_qty
        else:  # SHORT
            realized_pnl = (entry_price - exit_price) * total_close_qty

    net_pnl = realized_pnl - total_fees

    # calc_id from the earliest opening fill (matches order_manager logic)
    calc_id = ""
    for f in opens:
        cid = f.get("calc_id")
        if cid:
            calc_id = cid
            break

    return {
        "account_id":           account_id,
        "exchange_position_id": "",  # not populated from fills alone
        "terminal_position_id": _synthetic_pos_id(symbol, direction, entry_time_ms),
        "symbol":               symbol,
        "direction":            direction,
        "quantity":             total_close_qty,
        "entry_price":          entry_price,
        "exit_price":           exit_price,
        "entry_time_ms":        entry_time_ms,
        "exit_time_ms":         exit_time_ms,
        "realized_pnl":         realized_pnl,
        "total_fees":           total_fees,
        "net_pnl":              net_pnl,
        "funding_fees":         0.0,
        "hold_time_ms":         max(0, exit_time_ms - entry_time_ms),
        "exit_reason":          "manual",  # heuristic — no order-type metadata in fills alone
        "model_name":           "",
        "source":               "rebuilt_from_fills",
        "calc_id":              calc_id,
        # MFE/MAE left to reconciler (T175 floor applies there).
        # backfill_completed=0 so the reconciler picks up rebuilt rows.
        "mfe":                  0.0,
        "mae":                  0.0,
        "backfill_completed":   0,
    }


def _synthetic_pos_id(symbol: str, direction: str, entry_time_ms: int) -> str:
    """Deterministic synthetic position ID — same logical position
    always gets the same ID across reruns. Format mirrors the
    db_orders.py:954 exchange-history backfill convention (``bf:...``).
    Distinguishable as ``rebuilt:`` for traceability."""
    return f"rebuilt:{symbol}:{direction}:{entry_time_ms}"
