"""
Post-persist order enrichment: populate tp/sl trigger prices from child
orders, run calc_id correlation, propagate calc_id to fills.

All functions are sync (sqlite3) and best-effort: failures log warnings,
never break the ingest hot path. Called after async upsert completes.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, Optional

log = logging.getLogger("order_enrichment")

_SL_TYPES = frozenset({"stop_loss", "stop_market", "stop_loss_limit"})
_TP_TYPES = frozenset({"take_profit", "take_profit_market", "take_profit_limit"})
_CLOSE_TYPES = _SL_TYPES | _TP_TYPES | frozenset({"trailing_stop"})


def enrich_order(order: Dict[str, Any], db_path: str) -> None:
    """Run all enrichment steps on an entry order after persistence.

    1. Populate tp_trigger_price / sl_trigger_price from child orders.
    2. If both trigger prices are set and calc_id is NULL, run correlation.
    3. Best-effort: exceptions logged, never raised.
    """
    try:
        _populate_tp_sl_trigger_prices(order, db_path)
        _try_correlate(order, db_path)
    except Exception:
        log.warning("order enrichment failed for %s", order.get("exchange_order_id"), exc_info=True)


def enrich_fill(fill: Dict[str, Any], db_path: str) -> None:
    """Propagate calc_id from parent order to fill after persistence."""
    try:
        _propagate_calc_id_to_fill(fill, db_path)
    except Exception:
        log.warning("fill enrichment failed for %s", fill.get("exchange_fill_id"), exc_info=True)


# ── Internal: tp/sl trigger price population ─────────────────────────────────


def _populate_tp_sl_trigger_prices(order: Dict[str, Any], db_path: str) -> None:
    """Populate entry order's tp/sl trigger prices from child TP/SL orders."""
    # Skip close-side orders — they ARE the children, not the entry
    order_type = (order.get("order_type") or "").lower()
    if order_type in _CLOSE_TYPES or order.get("reduce_only"):
        return

    eid = order.get("exchange_order_id")
    pos_id = order.get("exchange_position_id", "")
    aid = order.get("account_id", 1)
    if not pos_id:
        return

    conn = sqlite3.connect(db_path)
    try:
        # Find child TP/SL orders attached to same position
        rows = conn.execute(
            "SELECT order_type, stop_price, price FROM orders "
            "WHERE account_id = ? AND exchange_position_id = ? "
            "AND reduce_only = 1 AND exchange_order_id != ?",
            (aid, pos_id, eid or ""),
        ).fetchall()

        tp_price = None
        sl_price = None
        for row in rows:
            child_type = (row[0] or "").lower()
            trigger = row[1] if row[1] else row[2]  # stop_price preferred, fallback to price
            if child_type in _TP_TYPES and trigger:
                tp_price = trigger
            elif child_type in _SL_TYPES and trigger:
                sl_price = trigger

        if tp_price is not None or sl_price is not None:
            conn.execute(
                "UPDATE orders SET tp_trigger_price = COALESCE(?, tp_trigger_price), "
                "sl_trigger_price = COALESCE(?, sl_trigger_price) "
                "WHERE account_id = ? AND exchange_order_id = ?",
                (tp_price, sl_price, aid, eid),
            )
            conn.commit()
    finally:
        conn.close()


# ── Internal: calc_id correlation ────────────────────────────────────────────


def _try_correlate(order: Dict[str, Any], db_path: str) -> None:
    """If entry order has both trigger prices but no calc_id, try correlation."""
    order_type = (order.get("order_type") or "").lower()
    if order_type in _CLOSE_TYPES or order.get("reduce_only"):
        return
    if order_type == "market":
        return

    eid = order.get("exchange_order_id")
    aid = order.get("account_id", 1)

    # Read current state from DB (trigger prices may have just been populated)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT calc_id, tp_trigger_price, sl_trigger_price, price "
            "FROM orders WHERE account_id = ? AND exchange_order_id = ?",
            (aid, eid),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return
    if row["calc_id"]:
        return  # already correlated
    if not row["tp_trigger_price"] or not row["sl_trigger_price"]:
        return  # need both for strict triple-match

    # Build order dict with current DB values for the correlator
    corr_order = {
        "account_id": aid,
        "symbol": order.get("symbol", ""),
        "side": order.get("side", ""),
        "order_type": order_type,
        "price": row["price"],
        "tp_trigger_price": row["tp_trigger_price"],
        "sl_trigger_price": row["sl_trigger_price"],
    }

    tick_size = _get_tick_size(order.get("symbol", ""), row["price"])

    from core.calc_correlation import correlate_order_to_calc
    calc_id = correlate_order_to_calc(corr_order, tick_size=tick_size, db_path=db_path)

    if calc_id:
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE orders SET calc_id = ? "
                "WHERE account_id = ? AND exchange_order_id = ? AND calc_id IS NULL",
                (calc_id, aid, eid),
            )
            conn.commit()
        finally:
            conn.close()
        log.info("Correlated order %s to calc_id %s", eid, calc_id)


def _get_tick_size(symbol: str, price: float) -> float:
    """Read tick size from exchange_info cache; fallback to price * 0.0001."""
    try:
        from core.state import app_state
        if hasattr(app_state, "exchange_info") and app_state.exchange_info:
            # Try adapter precision
            from core.exchange import _get_adapter
            adapter = _get_adapter()
            prec = adapter.get_precision(symbol)
            if prec and "price" in prec:
                return 10 ** (-prec["price"])
    except Exception:
        pass
    return max(price * 0.0001, 0.01) if price > 0 else 0.01


# ── Internal: fill calc_id propagation ───────────────────────────────────────


def _propagate_calc_id_to_fill(fill: Dict[str, Any], db_path: str) -> None:
    """Copy parent order's calc_id to the fill if not already set."""
    fill_id = fill.get("exchange_fill_id")
    order_id = fill.get("exchange_order_id")
    aid = fill.get("account_id", 1)

    if not order_id or not fill_id:
        return

    conn = sqlite3.connect(db_path)
    try:
        # Check fill doesn't already have calc_id
        frow = conn.execute(
            "SELECT calc_id FROM fills WHERE account_id = ? AND exchange_fill_id = ?",
            (aid, fill_id),
        ).fetchone()
        if frow and frow[0]:
            return  # already set

        # Read parent order's calc_id
        orow = conn.execute(
            "SELECT calc_id FROM orders WHERE account_id = ? AND exchange_order_id = ?",
            (aid, order_id),
        ).fetchone()
        if not orow or not orow[0]:
            return  # parent has no calc_id

        conn.execute(
            "UPDATE fills SET calc_id = ? "
            "WHERE account_id = ? AND exchange_fill_id = ?",
            (orow[0], aid, fill_id),
        )
        conn.commit()
    finally:
        conn.close()
