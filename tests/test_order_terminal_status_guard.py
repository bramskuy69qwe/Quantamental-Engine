"""
Terminal-status guard on the orders upsert (debug session 2026-06-07).

Bug (live Binance-WS path, orphan "open" orders): a market order fully fills
on the exchange (filled_qty == quantity, avg_fill_price set) but its `orders`
row is stuck at status='new', so it lingers in the open-orders pane after the
position is closed. Root cause: a late/duplicate Binance ORDER_TRADE_UPDATE
with X=NEW (carrying Binance's cumulative z=qty, so filled_qty stays correct)
arrives AFTER the FILLED event with a monotonic event time. It passes the
upsert's time-only WHERE guard and clobbers status back to 'new'. The SR-1
gate (order_manager.process_order_update) cannot catch it because terminal
orders are excluded from get_active_orders_map, so validate_transition is
never invoked for them.

Fix: the upsert ON CONFLICT WHERE now also requires
`orders.status NOT IN (terminal)`, enforcing the order_state state machine's
"terminal has no out-edges" rule at the single DB chokepoint that covers ALL
callers (WS update + REST snapshot + algo batch).

Intent (Rule 8) — what these pin that a refactor must not break:
  - a terminal status (filled/canceled/expired/rejected) is MONOTONIC: a later
    non-terminal observation can never downgrade it, even with a newer event ts;
  - the guard is NOT over-broad: a legitimate partially_filled -> filled still
    applies (partially_filled is not terminal).

These run against a REAL DatabaseManager (not a mock), unlike the gate-only
tests in test_order_manager.py whose mocked get_active_orders_map cannot
exercise this DB-layer guard.

Run: pytest tests/test_order_terminal_status_guard.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest_asyncio.fixture
async def db():
    """Tempfile DB with the full schema + account 1."""
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    d = DatabaseManager(path=tmp.name)
    await d.initialize()
    await d._conn.execute(
        "INSERT OR IGNORE INTO accounts (id, name, config_json) VALUES (1, 'Test', '{}')"
    )
    await d._conn.commit()
    yield d
    try:
        await d.close()
    except Exception:
        pass
    try:
        os.unlink(tmp.name)
    except Exception:
        pass


def _order(eid: str, status: str, updated_at_ms: int, *, filled_qty: float = 0.0,
           avg_fill_price: float = 0.0) -> dict:
    return {
        "account_id": 1,
        "exchange_order_id": eid,
        "symbol": "VELVETUSDT",
        "side": "BUY",
        "order_type": "market",
        "status": status,
        "quantity": 35.0,
        "filled_qty": filled_qty,
        "avg_fill_price": avg_fill_price,
        "updated_at_ms": updated_at_ms,
        "created_at_ms": updated_at_ms,
    }


async def _status(d, eid: str):
    async with d._conn.execute(
        "SELECT status FROM orders WHERE exchange_order_id = ?", (eid,)
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else None


@pytest.mark.asyncio
async def test_filled_not_downgraded_by_late_new(db):
    """The exact orphan-order bug: a late NEW event must NOT undo FILLED."""
    await db.upsert_order_batch([_order("ORD-A", "new", 1000)])
    await db.upsert_order_batch(
        [_order("ORD-A", "filled", 2000, filled_qty=35.0, avg_fill_price=0.2)]
    )
    assert await _status(db, "ORD-A") == "filled"

    # Late / duplicate Binance ORDER_TRADE_UPDATE (X=NEW), monotonic event time,
    # cumulative filled_qty still 35. Pre-fix this downgraded status -> 'new'.
    await db.upsert_order_batch([_order("ORD-A", "new", 3000, filled_qty=35.0)])
    assert await _status(db, "ORD-A") == "filled"


@pytest.mark.asyncio
async def test_partial_then_filled_still_applied(db):
    """Guard must NOT block the legitimate partially_filled -> filled edge."""
    await db.upsert_order_batch([_order("ORD-B", "new", 1000)])
    await db.upsert_order_batch([_order("ORD-B", "partially_filled", 2000, filled_qty=10.0)])
    assert await _status(db, "ORD-B") == "partially_filled"

    await db.upsert_order_batch([_order("ORD-B", "filled", 3000, filled_qty=35.0)])
    assert await _status(db, "ORD-B") == "filled"


@pytest.mark.asyncio
async def test_canceled_not_resurrected_to_new(db):
    """A canceled (terminal) order cannot be resurrected to new."""
    await db.upsert_order_batch([_order("ORD-C", "new", 1000)])
    await db.upsert_order_batch([_order("ORD-C", "canceled", 2000)])
    assert await _status(db, "ORD-C") == "canceled"

    await db.upsert_order_batch([_order("ORD-C", "new", 3000)])
    assert await _status(db, "ORD-C") == "canceled"
