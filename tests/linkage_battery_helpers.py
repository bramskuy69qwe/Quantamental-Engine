"""Shared helpers for the linkage attribution battery (LB-* scenarios).

Spec: docs/design/linkage_battery_plan.md (§3 conventions are binding).
Not collected by pytest (no test_ prefix). Battery files import explicitly
and own their fixtures so monkeypatch stays function-scoped.

Determinism: ONE module-import time anchor; calc rows take the ISO form,
order rows the ms twin (the 1fe4178 flake-fix pattern) so the matcher's
window check compares two values derived from the same instant.
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

ACCOUNT_ID = 1

_ANCHOR = datetime.now(timezone.utc) - timedelta(seconds=60)
RECENT_ISO = _ANCHOR.isoformat()
RECENT_MS = int(_ANCHOR.timestamp() * 1000)


# ── DB bootstrap ───────────────────────────────────────────────────────


async def make_real_db():
    """Tempfile DB + DatabaseManager + seeded account (window 300s).

    Returns (db, path, cleanup). The caller's fixture must also
    monkeypatch config.DB_PATH → path (raw-sqlite enrichment reads),
    core.link_actions.db → db (manual-link singleton), and stub
    core.trade_event_log.log_trade_event (the linkdb pattern,
    test_phase3_endpoints.py:37).
    """
    from core.database import DatabaseManager

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    await db._conn.execute(
        "INSERT OR IGNORE INTO accounts (id, name, config_json) "
        "VALUES (?, 'Test', ?)",
        (ACCOUNT_ID, '{"window_seconds": 300}'),
    )
    await db._conn.commit()

    async def cleanup():
        await db.close()
        try:
            os.unlink(tmp.name)
            for ext in ("-wal", "-shm"):
                p = tmp.name + ext
                if os.path.exists(p):
                    os.unlink(p)
        except OSError:
            pass

    return db, tmp.name, cleanup


# ── seeds (matcher-grade: every column the strict 6/6 SELECT reads) ────


async def seed_calc(
    db,
    calc_id: str,
    *,
    ticker: str = "BTCUSDT",
    side: str = "long",
    effective_entry: float = 50000.0,
    tp_price: float = 55000.0,
    sl_price: float = 48000.0,
    status: str = "active",
    window_seconds: Optional[int] = None,
    timestamp: Optional[str] = None,
    account_id: int = ACCOUNT_ID,
) -> None:
    await db._conn.execute(
        "INSERT INTO pre_trade_log (account_id, timestamp, ticker, side, "
        " effective_entry, tp_price, sl_price, average, calc_id, status, "
        " window_seconds) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (account_id, timestamp or RECENT_ISO, ticker, side, effective_entry,
         tp_price, sl_price, effective_entry, calc_id, status,
         window_seconds),
    )
    await db._conn.commit()


async def seed_order(
    db,
    eoid: str,
    *,
    symbol: str = "BTCUSDT",
    side: str = "BUY",
    order_type: str = "limit",
    status: str = "new",
    price: float = 50000.0,
    tp_trigger_price: Optional[float] = 55000.0,
    sl_trigger_price: Optional[float] = 48000.0,
    avg_fill_price: float = 0.0,
    quantity: float = 1.0,
    filled_qty: float = 0.0,
    reduce_only: int = 0,
    calc_id: Optional[str] = None,
    link_status: Optional[str] = None,
    lifecycle_id: Optional[str] = None,
    tpid: str = "",
    created_at_ms: Optional[int] = None,
    account_id: int = ACCOUNT_ID,
) -> int:
    """Hand-rolled orders row — carries terminal_position_id + lifecycle_id
    (T3b-entry BLOCKER rule) and returns the autoincrement id."""
    cur = await db._conn.execute(
        "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
        " order_type, status, price, tp_trigger_price, sl_trigger_price, "
        " avg_fill_price, quantity, filled_qty, reduce_only, calc_id, "
        " link_status, lifecycle_id, terminal_position_id, created_at_ms) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (account_id, eoid, symbol, side, order_type, status, price,
         tp_trigger_price, sl_trigger_price, avg_fill_price, quantity,
         filled_qty, reduce_only, calc_id, link_status, lifecycle_id,
         tpid, created_at_ms if created_at_ms is not None else RECENT_MS),
    )
    await db._conn.commit()
    return cur.lastrowid


def order_dict(
    eoid: str,
    *,
    symbol: str = "BTCUSDT",
    side: str = "BUY",
    order_type: str = "limit",
    status: str = "new",
    price: float = 50000.0,
    tp_trigger_price: Optional[float] = 55000.0,
    sl_trigger_price: Optional[float] = 48000.0,
    avg_fill_price: float = 0.0,
    quantity: float = 1.0,
    filled_qty: float = 0.0,
    reduce_only: int = 0,
    created_at_ms: Optional[int] = None,
    account_id: int = ACCOUNT_ID,
    **extra: Any,
) -> Dict[str, Any]:
    """WS-shaped order dict for process_order_update / enrich paths."""
    d: Dict[str, Any] = {
        "account_id": account_id,
        "exchange_order_id": eoid,
        "symbol": symbol,
        "side": side,
        "order_type": order_type,
        "status": status,
        "price": price,
        "tp_trigger_price": tp_trigger_price,
        "sl_trigger_price": sl_trigger_price,
        "avg_fill_price": avg_fill_price,
        "quantity": quantity,
        "filled_qty": filled_qty,
        "reduce_only": reduce_only,
        "created_at_ms": created_at_ms if created_at_ms is not None else RECENT_MS,
    }
    d.update(extra)
    return d


def fill(
    eoid: str,
    tpid: str,
    qty: float,
    *,
    fid: str = "F-1",
    ts: Optional[int] = None,
    is_close: int = 0,
    symbol: str = "BTCUSDT",
    direction: str = "LONG",
    price: float = 50000.0,
    realized_pnl: float = 0.0,
    account_id: int = ACCOUNT_ID,
    **extra: Any,
) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "account_id": account_id,
        "exchange_fill_id": fid,
        "exchange_order_id": eoid,
        "terminal_position_id": tpid,
        "symbol": symbol,
        "direction": direction,
        "quantity": qty,
        "price": price,
        "timestamp_ms": ts if ts is not None else RECENT_MS + 1000,
        "is_close": is_close,
    }
    if is_close:
        d["realized_pnl"] = realized_pnl
    d.update(extra)
    return d


# ── readers ────────────────────────────────────────────────────────────


async def q(db, sql: str, *params: Any) -> List[Dict[str, Any]]:
    async with db._conn.execute(sql, params) as cur:
        return [dict(r) for r in await cur.fetchall()]


async def order_row(db, order_id: int) -> Optional[Dict[str, Any]]:
    rows = await q(db, "SELECT * FROM orders WHERE id = ?", order_id)
    return rows[0] if rows else None


async def order_by_eoid(db, eoid: str) -> Optional[Dict[str, Any]]:
    rows = await q(db, "SELECT * FROM orders WHERE exchange_order_id = ?", eoid)
    return rows[0] if rows else None


async def fill_by_fid(db, fid: str) -> Optional[Dict[str, Any]]:
    rows = await q(db, "SELECT * FROM fills WHERE exchange_fill_id = ?", fid)
    return rows[0] if rows else None


async def junction_rows(db, position_id: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM positions_calcs"
    params: tuple = ()
    if position_id is not None:
        sql += " WHERE position_id = ?"
        params = (position_id,)
    return await q(db, sql + " ORDER BY id ASC", *params)


async def closed_rows(db, tpid: Optional[str] = None) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM closed_positions"
    params: tuple = ()
    if tpid is not None:
        sql += " WHERE terminal_position_id = ?"
        params = (tpid,)
    return await q(db, sql + " ORDER BY id ASC", *params)


async def calc_row(db, calc_id: str) -> Optional[Dict[str, Any]]:
    rows = await q(db, "SELECT * FROM pre_trade_log WHERE calc_id = ?", calc_id)
    return rows[0] if rows else None


def assert_calc_link_invariant(order: Dict[str, Any]) -> None:
    """System invariant: orders.calc_id present ⟺ link_status == LINKED."""
    has_calc = bool(order.get("calc_id"))
    is_linked = order.get("link_status") == "LINKED"
    assert has_calc == is_linked, (
        f"calc_id⟺LINKED invariant violated: calc_id={order.get('calc_id')!r} "
        f"link_status={order.get('link_status')!r}"
    )
