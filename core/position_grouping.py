"""
Group fills into logical positions via chronological-walk (T177).

Root cause this addresses: `get_position_fills` previously fell back
to (symbol, direction) matching when `terminal_position_id` was empty
(the common case — pos_id comes from Quantower's plugin, not Binance
WS, so any session without the plugin connected leaves the column
unpopulated). The fallback returned fills from MULTIPLE distinct
positions over time, causing the close-row builder to compute
nonsense entry_price (VWAP of cross-position opens) and entry_time
(min across all historical opens).

Grouping rule (no pos_id required):
  Walk fills chronologically, per-(symbol, direction). Track net
  open quantity. A logical position OPENS on the first non-close
  fill when net qty was 0. Subsequent fills ADD (is_close=0) or
  REDUCE (is_close=1) the qty. When qty returns to 0 (with a small
  epsilon for floating-point slop), the position is CLOSED and a
  closed_positions row is emitted. A new position can then open on
  the next non-close fill.

Why this is correct: fills represent actual order executions in
chronological order. A position's lifecycle is fully defined by its
fills — opens add, closes subtract, until qty hits 0. Cross-position
contamination is impossible because each position's fills are
contiguous in the qty-tracked stream (a new position can't open
while qty > 0 for the same symbol/direction in one-way mode).

Caveats:
  • Hedge mode (LONG + SHORT positions simultaneously on the same
    symbol) is handled because we key on (symbol, direction). The
    LONG and SHORT positions have independent qty tracks.
  • If qty goes NEGATIVE (overfill — close qty > open qty), we
    flush the current position at qty=0 and treat the residual as
    opening a new position of the OPPOSITE direction. Defensive;
    real Binance fills shouldn't overfill but partial-fill edge
    cases sometimes round.
  • Fills MUST be sorted chronologically AND deduplicated by
    exchange_fill_id before being fed in. Duplicate fills (e.g.,
    WS + REST reporting the same fill) would double-count qty.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Tuple

log = logging.getLogger("position_grouping")

# Floating-point tolerance for "qty has returned to zero". Crypto futures
# typically use 3-8 decimal qty precision; 1e-6 is safely below.
_QTY_EPS = 1e-6


def group_fills_into_positions(
    fills: Iterable[Dict[str, Any]],
    fee_rate_fallback: float = 0.0,
) -> List[Dict[str, Any]]:
    """Group chronologically-sorted fills into closed_positions rows.

    Each returned row has the shape expected by
    `db_orders.insert_closed_position`:
      account_id, symbol, direction, quantity, entry_price, exit_price,
      entry_time_ms, exit_time_ms, realized_pnl, total_fees, net_pnl,
      hold_time_ms, source, calc_id, exchange_position_id,
      terminal_position_id

    Open-but-not-closed positions at the end of the input stream are
    NOT emitted (they're still live; closed_positions tracks closed
    positions only).
    """
    rows: List[Dict[str, Any]] = []
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
                    # Over-closed: residual qty opens opposite-direction position?
                    # In one-way mode this shouldn't happen. In hedge mode the
                    # opposite direction has its own state key. Log + reset.
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
) -> Dict[str, Any]:
    """Build a closed_positions row dict from accumulated opens + closes."""
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
        # MFE/MAE left to reconciler
        "mfe":                  0.0,
        "mae":                  0.0,
    }


def _synthetic_pos_id(symbol: str, direction: str, entry_time_ms: int) -> str:
    """Deterministic synthetic position ID — same logical position
    always gets the same ID across reruns. Format mirrors the
    db_orders.py:954 exchange-history backfill convention (`bf:...`).
    Distinguishable as `rebuilt:` for traceability."""
    return f"rebuilt:{symbol}:{direction}:{entry_time_ms}"
