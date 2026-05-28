"""
Phase 1 Task 7 (P1.T7 / plan §1 task 1.10) — nullable TP/SL → manual-link.

Spec Q27 / §13: a calc may legitimately carry a null TP or SL (the
operator chose not to set one). Such a calc can't be confirmed by the
strict matcher, so it must auto-route the order to NEEDS_MANUAL_REVIEW
"regardless of other criteria" — NOT auto-link, NOT be silently
excluded.

Pins:
- null calc TP → NEEDS_MANUAL_REVIEW (even when entry/ticker/window/SL
  all match).
- null calc SL → NEEDS_MANUAL_REVIEW.
- both null → NEEDS_MANUAL_REVIEW.
- a COMPLETE calc still LINKS even when a null-TP sibling exists for the
  same key (the null-TP candidate doesn't poison the clean match).
- null/0 ENTRY is still skipped (the anchor) — not a candidate.
- audit records calc_value=None for a genuine null TP (clear signal in
  the manual-review diff).

Run: pytest tests/test_phase1_nullable_tpsl.py -v
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.calc_correlation import (
    LINK_STATUS_LINKED,
    LINK_STATUS_NEEDS_MANUAL_REVIEW,
    LINK_STATUS_UNPLANNED,
    correlate_order_to_calc,
)


@pytest_asyncio.fixture
async def db():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    await db._conn.execute(
        "INSERT OR IGNORE INTO accounts (id, name) VALUES (?, ?)", (1, "Test"),
    )
    await db._conn.commit()
    yield db, tmp.name
    await db.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


def _now_iso(off: float = -5.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=off)).isoformat()


def _insert_calc(db_path: str, *, calc_id: str, effective_entry=50000.0,
                 tp_price: float = 55000.0, sl_price: float = 48000.0,
                 side: str = "long") -> None:
    """Insert a calc. NOTE: pre_trade_log.tp_price/sl_price are NOT NULL
    DEFAULT 0 — an operator who omits a TP/SL stores 0.0, NOT SQL NULL.
    So 'absent TP/SL' tests pass tp_price=0.0 / sl_price=0.0, and the
    matcher's bool() guard treats 0.0 as absent → manual-link.
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO pre_trade_log "
            "(account_id, timestamp, ticker, side, effective_entry, "
            " tp_price, sl_price, average, calc_id, status, window_seconds) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 300)",
            (1, _now_iso(), "BTCUSDT", side, effective_entry,
             tp_price, sl_price, effective_entry, calc_id),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_order(db_path: str, *, eid="o-1", price=50000.0,
                  tp=55000.0, sl=48000.0) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO orders "
            "(account_id, exchange_order_id, symbol, side, order_type, "
            " price, tp_trigger_price, sl_trigger_price, avg_fill_price, "
            " created_at_ms) "
            "VALUES (1, ?, 'BTCUSDT', 'BUY', 'limit', ?, ?, ?, 0, ?)",
            (eid, price, tp, sl, int(time.time() * 1000)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _order_dict():
    return {
        "account_id": 1, "symbol": "BTCUSDT", "side": "BUY",
        "order_type": "limit", "price": 50000.0,
        "tp_trigger_price": 55000.0, "sl_trigger_price": 48000.0,
        "created_at_ms": int(time.time() * 1000),
    }


# ── nullable TP/SL → manual-link ──────────────────────────────────────


class TestNullableTPSL:
    @pytest.mark.asyncio
    async def test_null_tp_routes_to_manual_review(self, db):
        """calc.tp_price = NULL, everything else matches → NEEDS_MANUAL_REVIEW
        (not LINKED, not UNPLANNED). Spec Q27.
        """
        _, db_path = db
        _insert_calc(db_path, calc_id="nt-1", tp_price=0.0)  # SQL NULL TP
        oid = _insert_order(db_path)
        result = correlate_order_to_calc(
            _order_dict(), order_id=oid, tick_size=0.1, db_path=db_path,
        )
        assert result.calc_id is None
        assert result.link_status == LINK_STATUS_NEEDS_MANUAL_REVIEW

    @pytest.mark.asyncio
    async def test_null_sl_routes_to_manual_review(self, db):
        _, db_path = db
        _insert_calc(db_path, calc_id="ns-1", sl_price=0.0)  # SQL NULL SL
        oid = _insert_order(db_path)
        result = correlate_order_to_calc(
            _order_dict(), order_id=oid, tick_size=0.1, db_path=db_path,
        )
        assert result.calc_id is None
        assert result.link_status == LINK_STATUS_NEEDS_MANUAL_REVIEW

    @pytest.mark.asyncio
    async def test_both_null_routes_to_manual_review(self, db):
        _, db_path = db
        _insert_calc(db_path, calc_id="nb-1", tp_price=0.0, sl_price=0.0)
        oid = _insert_order(db_path)
        result = correlate_order_to_calc(
            _order_dict(), order_id=oid, tick_size=0.1, db_path=db_path,
        )
        assert result.calc_id is None
        assert result.link_status == LINK_STATUS_NEEDS_MANUAL_REVIEW

    @pytest.mark.asyncio
    async def test_zero_tp_also_routes_to_manual_review(self, db):
        """0.0 TP (not just SQL NULL) is treated the same — incomplete."""
        _, db_path = db
        _insert_calc(db_path, calc_id="zt-1", tp_price=0.0)
        oid = _insert_order(db_path)
        result = correlate_order_to_calc(
            _order_dict(), order_id=oid, tick_size=0.1, db_path=db_path,
        )
        assert result.link_status == LINK_STATUS_NEEDS_MANUAL_REVIEW

    @pytest.mark.asyncio
    async def test_audit_shows_null_tp_criterion_failed(self, db):
        """The TP criterion records matched=False with calc_value=None,
        so the manual-review diff clearly shows 'calc had no TP'.
        """
        _, db_path = db
        _insert_calc(db_path, calc_id="na-1", tp_price=0.0)
        oid = _insert_order(db_path)
        result = correlate_order_to_calc(
            _order_dict(), order_id=oid, tick_size=0.1, db_path=db_path,
        )
        by_criterion = {r["criterion"]: r for r in result.audit_rows}
        assert by_criterion["tp"]["matched"] is False
        assert by_criterion["tp"]["calc_value"] is None  # genuine null, not "0.0"
        # Other criteria still evaluated + matched
        assert by_criterion["entry"]["matched"] is True
        assert by_criterion["sl"]["matched"] is True


# ── a null-TP candidate must not poison a clean sibling ──────────────


class TestNullableDoesntPoisonCleanMatch:
    @pytest.mark.asyncio
    async def test_complete_calc_still_links_despite_null_tp_sibling(self, db):
        """Two calcs for the same (account, ticker, side): one complete
        (full match), one with null TP. An order arrives matching the
        complete one fully → it LINKS to the complete calc. The null-TP
        sibling is just a losing candidate, not a manual-review trigger.

        Why this matters: 'auto-route to manual-link' applies to the
        null-TP calc itself, not to OTHER candidates. A clean full match
        must still win.
        """
        _, db_path = db
        # Complete calc (newer) + null-TP calc (older)
        _insert_calc(db_path, calc_id="clean", tp_price=55000.0, sl_price=48000.0)
        _insert_calc(db_path, calc_id="nulltp", tp_price=0.0, sl_price=48000.0)
        oid = _insert_order(db_path)
        result = correlate_order_to_calc(
            _order_dict(), order_id=oid, tick_size=0.1, db_path=db_path,
        )
        assert result.calc_id == "clean"
        assert result.link_status == LINK_STATUS_LINKED


# ── null entry is still skipped (the anchor) ─────────────────────────


class TestNullEntryStillSkipped:
    @pytest.mark.asyncio
    async def test_null_entry_calc_excluded_not_manual_review(self, db):
        """A calc with no effective_entry is genuinely malformed (entry
        is the price anchor + drift denominator) — still M5-skipped, so
        the order falls to UNPLANNED (no eligible candidate), NOT
        manual-review. Spec Q27 is about TP/SL, not entry.
        """
        _, db_path = db
        _insert_calc(db_path, calc_id="ne-1", effective_entry=0.0)
        oid = _insert_order(db_path)
        result = correlate_order_to_calc(
            _order_dict(), order_id=oid, tick_size=0.1, db_path=db_path,
        )
        assert result.calc_id is None
        assert result.link_status == LINK_STATUS_UNPLANNED
        assert result.audit_rows == []  # skipped → no audit
