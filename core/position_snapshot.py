"""
Position state snapshot at fill time — derives is_close from qty deltas.

Replaces the unreliable realizedPnl heuristic for one-way mode.
In one-way mode, a buy reduces a short (is_close) or opens/adds a long
(not is_close). The exchange WS doesn't tag this reliably; we infer it
from net position qty before and after the fill.
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

log = logging.getLogger("position_snapshot")


@dataclass
class FillSnapshot:
    """Position state at fill time."""
    fill_id: str
    symbol: str
    mode: str  # "one_way" | "hedge"
    position_side: Optional[str]
    qty_before: float
    qty_after: float
    is_open: bool
    is_close: bool
    is_partial_close: bool
    timestamp_ms: int


def compute_fill_snapshot(
    fill: Dict[str, Any],
    positions: List[Any],
    mode: str = "one_way",
) -> FillSnapshot:
    """Compute position state snapshot for a fill.

    Args:
        fill: Fill dict with symbol, side, quantity, timestamp_ms, etc.
        positions: Current position list (app_state.positions or similar).
            Each needs .ticker, .direction, .contract_amount attributes.
        mode: "one_way" or "hedge".

    Returns:
        FillSnapshot with derived is_open/is_close/is_partial_close.
    """
    symbol = fill.get("symbol", "")
    fill_side = (fill.get("side") or "").upper()
    fill_qty = abs(fill.get("quantity", 0))
    fill_id = fill.get("exchange_fill_id", "")
    ts = fill.get("timestamp_ms", 0)

    # Find current net position for this symbol
    pos = next((p for p in positions if getattr(p, "ticker", "") == symbol), None)

    if mode == "hedge":
        # Hedge mode: side is deterministic from positionSide
        position_side = fill.get("direction", fill.get("position_side", ""))
        qty_before = getattr(pos, "contract_amount", 0) if pos else 0
        is_close = fill.get("is_close", False)  # Exchange provides this in hedge mode
        return FillSnapshot(
            fill_id=fill_id, symbol=symbol, mode="hedge",
            position_side=position_side,
            qty_before=qty_before, qty_after=qty_before,  # approximate
            is_open=not is_close, is_close=is_close, is_partial_close=False,
            timestamp_ms=ts,
        )

    # One-way mode: derive from net position qty
    # Convention: long = positive qty, short = negative qty
    if pos:
        direction = (getattr(pos, "direction", "") or "").upper()
        raw_qty = abs(getattr(pos, "contract_amount", 0))
        if direction == "SHORT":
            qty_before = -raw_qty
        else:
            qty_before = raw_qty
    else:
        qty_before = 0.0

    # Compute qty_after based on fill side
    # BUY adds to long / reduces short; SELL adds to short / reduces long
    if fill_side == "BUY":
        qty_after = qty_before + fill_qty
    elif fill_side == "SELL":
        qty_after = qty_before - fill_qty
    else:
        qty_after = qty_before

    # Derive is_close: did the fill reduce position size toward zero?
    # - Going from negative to less-negative (or zero or positive): closing short
    # - Going from positive to less-positive (or zero or negative): closing long
    abs_before = abs(qty_before)
    abs_after = abs(qty_after)

    if qty_before == 0:
        # Flat → opening
        is_open = True
        is_close = False
        is_partial = False
    elif (qty_before > 0 and fill_side == "SELL") or (qty_before < 0 and fill_side == "BUY"):
        # Fill reduces existing position
        is_close = True
        is_open = False
        is_partial = abs_after > 0 and (qty_before * qty_after > 0)  # same sign = partial
        # Overshoot: crossing zero means close + new open
        if qty_before * qty_after < 0:
            is_open = True  # also opens in opposite direction
    else:
        # Fill adds to existing position (same direction)
        is_open = True
        is_close = False
        is_partial = False

    return FillSnapshot(
        fill_id=fill_id, symbol=symbol, mode="one_way",
        position_side=None,
        qty_before=qty_before, qty_after=qty_after,
        is_open=is_open, is_close=is_close, is_partial_close=is_partial,
        timestamp_ms=ts,
    )


def persist_snapshot(snapshot: FillSnapshot, db_path: str, account_id: int = 1) -> None:
    """Write a position_fill_snapshots row."""
    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "INSERT INTO position_fill_snapshots "
            "(account_id, fill_id, symbol, mode, position_side, "
            "qty_before, qty_after, is_open, is_close, is_partial_close, timestamp_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, snapshot.fill_id, snapshot.symbol, snapshot.mode,
             snapshot.position_side, snapshot.qty_before, snapshot.qty_after,
             int(snapshot.is_open), int(snapshot.is_close), int(snapshot.is_partial_close),
             snapshot.timestamp_ms),
        )
        conn.commit()
        conn.close()
    except Exception:
        log.debug("persist_snapshot failed", exc_info=True)
