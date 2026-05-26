"""
Post-persist order enrichment: populate tp/sl trigger prices from child
orders, run calc_id correlation (strict matcher per spec §4), propagate
calc_id to fills.

``enrich_order`` is async because the matcher integration
(``_try_correlate``) routes the calc-status flip through
``core/calc_state.transition()`` — the choke-point installed in P0.T6,
which is async (it awaits ``event_bus.publish``).

``enrich_fill`` and its helpers stay sync — they do not touch the
matcher or the state machine. Both wrappers are best-effort: failures
log warnings, never break the ingest hot path. Called after async
upsert completes.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("order_enrichment")

_SL_TYPES = frozenset({"stop_loss", "stop_market", "stop_loss_limit"})
_TP_TYPES = frozenset({"take_profit", "take_profit_market", "take_profit_limit"})
_CLOSE_TYPES = _SL_TYPES | _TP_TYPES | frozenset({"trailing_stop"})


async def enrich_order(order: Dict[str, Any], db_path: str) -> None:
    """Run all enrichment steps on an entry order after persistence.

    1. Populate tp_trigger_price / sl_trigger_price from child orders.
    2. If both trigger prices are set and calc_id is NULL, run the
       strict matcher (spec §4) and route any successful calc-status
       flip through ``calc_state.transition()``.
    3. Best-effort: exceptions logged, never raised.
    """
    try:
        _populate_tp_sl_trigger_prices(order, db_path)
        await _try_correlate(order, db_path)
    except Exception:
        log.warning("order enrichment failed for %s", order.get("exchange_order_id"), exc_info=True)


def enrich_fill(fill: Dict[str, Any], db_path: str) -> None:
    """Propagate calc_id from parent order to fill, classify fill_type, compute slippage."""
    try:
        _propagate_calc_id_to_fill(fill, db_path)
        _classify_and_compute_slippage(fill, db_path)
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


async def _try_correlate(order: Dict[str, Any], db_path: str) -> None:
    """Strict 5/5 (LIMIT) / 6/6 (MARKET) matcher per spec §4.

    Reads ``accounts.config_json`` for tolerance + window config; spec
    §3.3 defaults applied when fields are missing. Calls the pure sync
    matcher (``core/calc_correlation.correlate_order_to_calc``).
    Persists per-criterion audit rows into ``calc_match_audit``. Writes
    ``orders.link_status`` (always) and ``orders.calc_id`` (on full
    match). For a full match, routes the calc-status flip
    ``active|released → matched`` through
    :func:`core.calc_state.transition` so the event-bus fires through
    the choke-point installed in P0.T6.
    """
    order_type = (order.get("order_type") or "").lower()
    if order_type in _CLOSE_TYPES or order.get("reduce_only"):
        return

    eid = order.get("exchange_order_id")
    aid = order.get("account_id", 1)
    if not eid:
        return

    # Read current order state — trigger prices may have just been
    # populated, and the matcher needs the orders.id PK + created_at_ms
    # timestamp.
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT id, calc_id, link_status, "
            "       tp_trigger_price, sl_trigger_price, "
            "       price, avg_fill_price, created_at_ms "
            "FROM orders WHERE account_id = ? AND exchange_order_id = ?",
            (aid, eid),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return
    if row["calc_id"]:
        return  # already correlated — matcher is idempotent at this gate
    if not row["tp_trigger_price"] or not row["sl_trigger_price"]:
        return  # need both trigger prices

    is_market = order_type == "market"
    if is_market and not (row["avg_fill_price"] or 0):
        # Spec §4.1: MARKET 6/6 includes entry-vs-fill comparison.
        # Without a fill price yet, the matcher can't evaluate entry —
        # defer until the fill arrives and re-enrichment runs.
        return

    entry_tol, window_sec, skew = _read_account_config(db_path, aid)

    corr_order = {
        "account_id":        aid,
        "symbol":            order.get("symbol", ""),
        "side":              order.get("side", ""),
        "order_type":        order_type,
        "price":             row["price"],
        "avg_fill_price":    row["avg_fill_price"],
        "tp_trigger_price":  row["tp_trigger_price"],
        "sl_trigger_price":  row["sl_trigger_price"],
        "created_at_ms":     row["created_at_ms"],
    }

    tick_size = _get_tick_size(order.get("symbol", ""), row["price"])

    from core.calc_correlation import correlate_order_to_calc
    result = correlate_order_to_calc(
        corr_order,
        order_id=row["id"],
        tick_size=tick_size,
        entry_tolerance_pct=entry_tol,
        window_seconds=window_sec,
        clock_skew_tolerance_sec=skew,
        db_path=db_path,
    )

    if result.audit_rows:
        _insert_audit_rows(db_path, result.audit_rows)

    # Always write link_status. Write calc_id only on a full match.
    conn = sqlite3.connect(db_path)
    try:
        if result.calc_id:
            conn.execute(
                "UPDATE orders SET calc_id = ?, link_status = ? "
                "WHERE account_id = ? AND exchange_order_id = ? "
                "  AND calc_id IS NULL",
                (result.calc_id, result.link_status, aid, eid),
            )
        else:
            conn.execute(
                "UPDATE orders SET link_status = ? "
                "WHERE account_id = ? AND exchange_order_id = ?",
                (result.link_status, aid, eid),
            )
        conn.commit()
    finally:
        conn.close()

    # Route calc-status flip through calc_state.transition (the
    # choke-point P0.T6 installed). apply_fn does the actual UPDATE;
    # transition() handles validation + event emission.
    if result.calc_id and result.matched_from_status:
        from core.calc_state import transition, CalcStatus

        async def _apply_status_flip() -> None:
            inner = sqlite3.connect(db_path)
            try:
                inner.execute(
                    "UPDATE pre_trade_log SET status = ? WHERE calc_id = ?",
                    (CalcStatus.MATCHED.value, result.calc_id),
                )
                inner.commit()
            finally:
                inner.close()

        try:
            await transition(
                calc_id=result.calc_id,
                current_status=result.matched_from_status,
                target_status=CalcStatus.MATCHED.value,
                apply_fn=_apply_status_flip,
                event_payload={"order_id": row["id"]},
            )
        except Exception:
            log.warning(
                "calc_state.transition active→matched failed for "
                "calc_id=%s order_id=%s",
                result.calc_id, row["id"], exc_info=True,
            )

    if result.calc_id:
        log.info("Correlated order %s to calc_id %s (link_status=%s)",
                 eid, result.calc_id, result.link_status)


def _read_account_config(db_path: str, account_id: int) -> Tuple[float, int, int]:
    """Resolve (entry_tolerance_pct, window_seconds, clock_skew_tolerance_sec)
    from ``accounts.config_json`` with spec §3.3 defaults.
    """
    from core.calc_correlation import (
        SPEC_DEFAULT_ENTRY_TOLERANCE_PCT,
        SPEC_DEFAULT_WINDOW_SECONDS,
        SPEC_DEFAULT_CLOCK_SKEW_TOLERANCE,
    )

    cfg: Dict[str, Any] = {}
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT config_json FROM accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        finally:
            conn.close()
        if row and row[0]:
            parsed = json.loads(row[0])
            if isinstance(parsed, dict):
                cfg = parsed
    except Exception:
        pass  # missing column / malformed JSON / missing account row — use defaults

    return (
        float(cfg.get("entry_tolerance_pct", SPEC_DEFAULT_ENTRY_TOLERANCE_PCT)),
        int(cfg.get("window_seconds", SPEC_DEFAULT_WINDOW_SECONDS)),
        int(cfg.get("clock_skew_tolerance_sec", SPEC_DEFAULT_CLOCK_SKEW_TOLERANCE)),
    )


def _insert_audit_rows(db_path: str, rows: List[Dict[str, Any]]) -> None:
    """Bulk INSERT calc_match_audit rows via raw sqlite3.

    Mirrors the SQL in ``Database.insert_calc_match_audit_batch`` but
    stays sync to keep the enrichment-best-effort path simple. The
    async batch helper exists for hot-path callers; matcher invocation
    is off-hot-path enrichment.
    """
    if not rows:
        return
    sql = (
        "INSERT INTO calc_match_audit ("
        "  order_id, calc_id, criterion, calc_value, order_value, "
        "  tolerance_used, matched, ts_ms, winning"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    params = [(
        r.get("order_id"),
        r.get("calc_id", ""),
        r.get("criterion", ""),
        r.get("calc_value"),
        r.get("order_value"),
        r.get("tolerance_used"),
        int(bool(r.get("matched", 0))),
        r.get("ts_ms", 0),
        int(bool(r.get("winning", 0))),
    ) for r in rows]
    try:
        conn = sqlite3.connect(db_path)
        try:
            conn.executemany(sql, params)
            conn.commit()
        finally:
            conn.close()
    except Exception:
        log.warning(
            "calc_match_audit insert failed (%d rows)", len(rows), exc_info=True,
        )


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


# ── Internal: fill classification + slippage ─────────────────────────────────


def classify_fill_type(fill: Dict[str, Any], parent_order: Optional[Dict] = None) -> str:
    """Classify a fill as entry/tp/sl/manual/reduce_only."""
    if parent_order:
        otype = (parent_order.get("order_type") or "").lower()
        if otype in _TP_TYPES:
            return "tp"
        if otype in _SL_TYPES:
            return "sl"
    if fill.get("is_close"):
        return "manual"
    if fill.get("reduce_only") or (parent_order and parent_order.get("reduce_only")):
        return "reduce_only"
    return "entry"


def compute_slippage_actual(
    fill: Dict[str, Any],
    parent_order: Optional[Dict],
    fill_type: str,
    db_path: str,
) -> Optional[float]:
    """Compute slippage_actual for a fill.

    - entry: (fill_price - pre_trade_log.effective_entry) / effective_entry
    - tp/sl: (fill_price - parent_order.stop_price) / parent_order.stop_price
    - manual/reduce_only: None
    """
    fill_price = fill.get("price", 0)
    if not fill_price:
        return None

    if fill_type == "entry":
        calc_id = fill.get("calc_id")
        if not calc_id:
            return None
        aid = fill.get("account_id", 1)
        try:
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT effective_entry FROM pre_trade_log "
                "WHERE calc_id = ? AND account_id = ? LIMIT 1",
                (calc_id, aid),
            ).fetchone()
            conn.close()
            if row and row[0]:
                return (fill_price - row[0]) / row[0]
        except Exception:
            pass
        return None

    if fill_type in ("tp", "sl"):
        if not parent_order:
            return None
        expected = parent_order.get("stop_price") or parent_order.get("price", 0)
        if expected:
            return (fill_price - expected) / expected
        return None

    return None  # manual / reduce_only


def _classify_and_compute_slippage(fill: Dict[str, Any], db_path: str) -> None:
    """Classify fill_type and compute slippage_actual, then UPDATE the fill row."""
    fill_id = fill.get("exchange_fill_id")
    order_id = fill.get("exchange_order_id")
    aid = fill.get("account_id", 1)
    if not fill_id:
        return

    # Read parent order
    parent = None
    if order_id:
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM orders WHERE account_id = ? AND exchange_order_id = ?",
                (aid, order_id),
            ).fetchone()
            conn.close()
            if row:
                parent = dict(row)
        except Exception:
            pass

    # Read current fill state (may have calc_id set by prior enrichment)
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        frow = conn.execute(
            "SELECT * FROM fills WHERE account_id = ? AND exchange_fill_id = ?",
            (aid, fill_id),
        ).fetchone()
        conn.close()
        if frow:
            fill_data = dict(frow)
        else:
            fill_data = fill
    except Exception:
        fill_data = fill

    ftype = classify_fill_type(fill_data, parent)
    slip = compute_slippage_actual(fill_data, parent, ftype, db_path)

    try:
        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE fills SET fill_type = ?, slippage_actual = ? "
            "WHERE account_id = ? AND exchange_fill_id = ?",
            (ftype, slip, aid, fill_id),
        )
        conn.commit()
        conn.close()
    except Exception:
        log.debug("fill classification update failed", exc_info=True)
