"""
Phase 1 Task 1 (P1.T1) tests — strict matcher rewrite.

Verifies the new strict matcher per spec §4:

  - LIMIT 5/5 (ticker, side, in-window, entry-loose, TP, SL — all must match)
  - MARKET 6/6 (same, with entry compared against avg_fill_price)
  - Per-criterion audit rows persist for every candidate
  - Winner's audit rows carry winning=True
  - 0 candidates in window → UNPLANNED, no audit rows
  - 1+ candidates but no full match → NEEDS_MANUAL_REVIEW
  - Multiple full matches → most-recent wins (tie-break)
  - Window boundary respects clock-skew padding (spec §4.2)
  - status filter: only ('active', 'released') rows are candidates
  - enrich_order routes successful match through calc_state.transition

These tests encode WHY the strict matcher matters (per Rule 8): the
old 3/3 limit + 2/2 market matcher allowed stale-calc binding when a
new order happened to align on a couple of legs. Strict all-or-fall-
through forces operator review when criteria diverge — supporting
spec §4's "no scoring, no partial-auto-link" rule.

Run: pytest tests/test_phase1_matcher.py -v
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.calc_correlation import (
    LINK_STATUS_LINKED,
    LINK_STATUS_NEEDS_MANUAL_REVIEW,
    LINK_STATUS_UNPLANNED,
    SPEC_DEFAULT_CLOCK_SKEW_TOLERANCE,
    SPEC_DEFAULT_ENTRY_TOLERANCE_PCT,
    SPEC_DEFAULT_WINDOW_SECONDS,
    MatchResult,
    correlate_order_to_calc,
)


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db():
    """Tempfile DB initialized with the full schema (P0.T1-T4 + P1.T1)."""
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    # Seed an accounts row so config_json reads work.
    await db._conn.execute(
        "INSERT OR IGNORE INTO accounts (id, name) VALUES (?, ?)",
        (1, "Test"),
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


def _now_iso(offset_sec: float = 0.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_sec)).isoformat()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _insert_calc(
    db_path: str,
    *,
    calc_id: str,
    ticker: str,
    side: str,
    effective_entry: float,
    tp_price: float,
    sl_price: float,
    status: str = "active",
    window_seconds: Optional[int] = None,
    timestamp: Optional[str] = None,
    account_id: int = 1,
) -> None:
    """Insert a pre_trade_log row directly via sqlite3 (matches the matcher's read path)."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO pre_trade_log "
            "(account_id, timestamp, ticker, side, "
            " effective_entry, tp_price, sl_price, average, "
            " calc_id, status, window_seconds) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, timestamp or _now_iso(-5.0), ticker, side,
             effective_entry, tp_price, sl_price, effective_entry,
             calc_id, status, window_seconds),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_order(
    db_path: str,
    *,
    exchange_order_id: str,
    symbol: str,
    side: str,
    order_type: str,
    price: float,
    tp_trigger_price: float,
    sl_trigger_price: float,
    avg_fill_price: float = 0.0,
    created_at_ms: Optional[int] = None,
    account_id: int = 1,
) -> int:
    """Insert an orders row; return the autoincrement id."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO orders "
            "(account_id, exchange_order_id, symbol, side, order_type, "
            " price, tp_trigger_price, sl_trigger_price, avg_fill_price, "
            " created_at_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (account_id, exchange_order_id, symbol, side, order_type,
             price, tp_trigger_price, sl_trigger_price, avg_fill_price,
             created_at_ms or _now_ms()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _build_order(
    *,
    symbol: str = "BTCUSDT",
    side: str = "long",
    order_type: str = "limit",
    price: float = 50000.0,
    avg_fill_price: float = 0.0,
    tp_trigger_price: float = 55000.0,
    sl_trigger_price: float = 48000.0,
    account_id: int = 1,
    created_at_ms: Optional[int] = None,
) -> Dict[str, Any]:
    return {
        "account_id":       account_id,
        "symbol":           symbol,
        "side":             side,
        "order_type":       order_type,
        "price":            price,
        "avg_fill_price":   avg_fill_price,
        "tp_trigger_price": tp_trigger_price,
        "sl_trigger_price": sl_trigger_price,
        "created_at_ms":    created_at_ms or _now_ms(),
    }


# ── 1. Strict LIMIT matcher ────────────────────────────────────────────


class TestStrictLimit:
    """LIMIT 5/5 — ticker, side, in-window, entry-loose, TP, SL.

    Spec §4.1: "5/5 (all must match)" — no scoring, no partial-auto-link.
    """

    @pytest.mark.asyncio
    async def test_full_match_links(self, db):
        _, db_path = db
        _insert_calc(db_path, calc_id="calc-a", ticker="BTCUSDT", side="long",
                     effective_entry=50000.0, tp_price=55000.0, sl_price=48000.0)
        order_id = _insert_order(
            db_path, exchange_order_id="o1", symbol="BTCUSDT", side="long",
            order_type="limit", price=50000.0,
            tp_trigger_price=55000.0, sl_trigger_price=48000.0,
        )
        result = correlate_order_to_calc(
            _build_order(),
            order_id=order_id,
            tick_size=0.1,
            db_path=db_path,
        )
        assert result.calc_id == "calc-a"
        assert result.link_status == LINK_STATUS_LINKED
        assert result.matched_from_status == "active"
        # 6 criteria audited: ticker, direction, window, entry, tp, sl
        assert len(result.audit_rows) == 6
        assert all(r["matched"] for r in result.audit_rows)
        assert all(r["winning"] for r in result.audit_rows)

    @pytest.mark.asyncio
    async def test_tp_outside_tick_tolerance_routes_to_review(self, db):
        """A 1-USD diff exceeds tick_size=0.1 → fails the TP criterion.

        Why this matters: spec §4.1 forbids partial auto-link. Even one
        failing criterion forces operator review — otherwise stale
        calcs could silently bind to amended orders.
        """
        _, db_path = db
        _insert_calc(db_path, calc_id="calc-b", ticker="BTCUSDT", side="long",
                     effective_entry=50000.0, tp_price=55000.0, sl_price=48000.0)
        order_id = _insert_order(
            db_path, exchange_order_id="o2", symbol="BTCUSDT", side="long",
            order_type="limit", price=50000.0,
            tp_trigger_price=55001.0,  # 1 USD off — outside tick 0.1
            sl_trigger_price=48000.0,
        )
        result = correlate_order_to_calc(
            _build_order(tp_trigger_price=55001.0),
            order_id=order_id,
            tick_size=0.1,
            db_path=db_path,
        )
        assert result.calc_id is None
        assert result.link_status == LINK_STATUS_NEEDS_MANUAL_REVIEW
        # All criteria audited; tp criterion matched=False, others True
        by_criterion = {r["criterion"]: r for r in result.audit_rows}
        assert by_criterion["tp"]["matched"] is False
        assert by_criterion["entry"]["matched"] is True
        assert by_criterion["sl"]["matched"] is True

    @pytest.mark.asyncio
    async def test_entry_within_loose_tolerance(self, db):
        """Entry uses loose entry_tolerance_pct (default 0.25%), not tick.

        Spec §4.2: |order - calc| / calc ≤ entry_tolerance_pct. A 0.1%
        drift on a 50k entry = 50 USD — far beyond tick_size — but
        within the entry-loose band, so it should still match.
        """
        _, db_path = db
        _insert_calc(db_path, calc_id="calc-c", ticker="BTCUSDT", side="long",
                     effective_entry=50000.0, tp_price=55000.0, sl_price=48000.0)
        order_id = _insert_order(
            db_path, exchange_order_id="o3", symbol="BTCUSDT", side="long",
            order_type="limit", price=50050.0,  # 0.1% drift
            tp_trigger_price=55000.0, sl_trigger_price=48000.0,
        )
        result = correlate_order_to_calc(
            _build_order(price=50050.0),
            order_id=order_id,
            tick_size=0.1,
            entry_tolerance_pct=0.25,
            db_path=db_path,
        )
        assert result.calc_id == "calc-c"
        assert result.link_status == LINK_STATUS_LINKED

    @pytest.mark.asyncio
    async def test_entry_outside_loose_tolerance_routes_to_review(self, db):
        """0.5% drift exceeds entry_tolerance_pct=0.25 → NEEDS_MANUAL_REVIEW."""
        _, db_path = db
        _insert_calc(db_path, calc_id="calc-d", ticker="BTCUSDT", side="long",
                     effective_entry=50000.0, tp_price=55000.0, sl_price=48000.0)
        order_id = _insert_order(
            db_path, exchange_order_id="o4", symbol="BTCUSDT", side="long",
            order_type="limit", price=50250.0,  # 0.5% drift
            tp_trigger_price=55000.0, sl_trigger_price=48000.0,
        )
        result = correlate_order_to_calc(
            _build_order(price=50250.0),
            order_id=order_id,
            tick_size=0.1,
            entry_tolerance_pct=0.25,
            db_path=db_path,
        )
        assert result.calc_id is None
        assert result.link_status == LINK_STATUS_NEEDS_MANUAL_REVIEW
        by_criterion = {r["criterion"]: r for r in result.audit_rows}
        assert by_criterion["entry"]["matched"] is False


# ── 2. Strict MARKET matcher ───────────────────────────────────────────


class TestStrictMarket:
    """MARKET 6/6 — entry compared against avg_fill_price (spec §4.1).

    Why a separate class: market orders don't carry a limit price. The
    matcher MUST use avg_fill_price as the entry comparison source —
    not order.price (which is 0 for market orders).
    """

    @pytest.mark.asyncio
    async def test_market_uses_avg_fill_price_for_entry(self, db):
        _, db_path = db
        _insert_calc(db_path, calc_id="calc-e", ticker="BTCUSDT", side="long",
                     effective_entry=50000.0, tp_price=55000.0, sl_price=48000.0)
        order_id = _insert_order(
            db_path, exchange_order_id="m1", symbol="BTCUSDT", side="long",
            order_type="market", price=0.0,
            avg_fill_price=50030.0,  # within 0.25% of 50k
            tp_trigger_price=55000.0, sl_trigger_price=48000.0,
        )
        result = correlate_order_to_calc(
            _build_order(order_type="market", price=0.0, avg_fill_price=50030.0),
            order_id=order_id,
            tick_size=0.1,
            db_path=db_path,
        )
        assert result.calc_id == "calc-e"
        assert result.link_status == LINK_STATUS_LINKED


# ── 3. Candidate filtering ─────────────────────────────────────────────


class TestCandidateFilter:
    """Spec §4.3 pre-filter: account/ticker/side/status/in-window."""

    @pytest.mark.asyncio
    async def test_no_candidates_returns_unplanned_with_no_audit(self, db):
        """Zero candidates → UNPLANNED with NO audit rows.

        Why this matters: spec §4.3's "UNPLANNED if zero candidates"
        case means the operator never computed a calc. No audit rows
        because there's nothing to audit against — emitting empty
        audit rows would just be noise in calc_match_audit.
        """
        _, db_path = db
        # No pre_trade_log rows inserted.
        order_id = _insert_order(
            db_path, exchange_order_id="o5", symbol="BTCUSDT", side="long",
            order_type="limit", price=50000.0,
            tp_trigger_price=55000.0, sl_trigger_price=48000.0,
        )
        result = correlate_order_to_calc(
            _build_order(),
            order_id=order_id,
            tick_size=0.1,
            db_path=db_path,
        )
        assert result.calc_id is None
        assert result.link_status == LINK_STATUS_UNPLANNED
        assert result.audit_rows == []

    @pytest.mark.asyncio
    async def test_expired_status_excluded(self, db):
        """Spec §3.4 + §4.3: only status IN ('active', 'released') is eligible.

        Why this matters: the P1.T1 backfill set 118 legacy NULL rows to
        'expired' precisely so the new matcher refuses to bind to them.
        Test pins that behavior.
        """
        _, db_path = db
        _insert_calc(db_path, calc_id="calc-old", ticker="BTCUSDT", side="long",
                     effective_entry=50000.0, tp_price=55000.0, sl_price=48000.0,
                     status="expired")
        order_id = _insert_order(
            db_path, exchange_order_id="o6", symbol="BTCUSDT", side="long",
            order_type="limit", price=50000.0,
            tp_trigger_price=55000.0, sl_trigger_price=48000.0,
        )
        result = correlate_order_to_calc(
            _build_order(),
            order_id=order_id,
            tick_size=0.1,
            db_path=db_path,
        )
        assert result.calc_id is None
        assert result.link_status == LINK_STATUS_UNPLANNED  # expired isn't a candidate

    @pytest.mark.asyncio
    async def test_released_status_is_eligible(self, db):
        """Spec §5 + §4.3: released calc participates (P1.T5 replacement).

        Why this matters: when an order cancels and its calc transitions
        active → released, the calc must remain eligible for re-match
        on a replacement order. Forgetting 'released' here would break
        the Phase 1.5 replacement flow.
        """
        _, db_path = db
        _insert_calc(db_path, calc_id="calc-r", ticker="BTCUSDT", side="long",
                     effective_entry=50000.0, tp_price=55000.0, sl_price=48000.0,
                     status="released")
        order_id = _insert_order(
            db_path, exchange_order_id="o7", symbol="BTCUSDT", side="long",
            order_type="limit", price=50000.0,
            tp_trigger_price=55000.0, sl_trigger_price=48000.0,
        )
        result = correlate_order_to_calc(
            _build_order(),
            order_id=order_id,
            tick_size=0.1,
            db_path=db_path,
        )
        assert result.calc_id == "calc-r"
        assert result.matched_from_status == "released"


# ── 4. Window boundary + clock-skew ────────────────────────────────────


class TestWindowBoundary:
    """Spec §4.2: |order_ts - calc_ts| ≤ window_seconds + clock_skew_tolerance.

    Why a dedicated test class: the time-window check is the
    only spec criterion with TWO tunable knobs (window + skew). Getting
    the boundary off by 10 seconds means valid trades hit
    manual-review for the wrong reason.
    """

    @pytest.mark.asyncio
    async def test_inside_window_matches(self, db):
        _, db_path = db
        # Calc 60 s ago, default window 300 s
        _insert_calc(db_path, calc_id="calc-w1", ticker="BTCUSDT", side="long",
                     effective_entry=50000.0, tp_price=55000.0, sl_price=48000.0,
                     timestamp=_now_iso(-60.0))
        order_id = _insert_order(
            db_path, exchange_order_id="w1", symbol="BTCUSDT", side="long",
            order_type="limit", price=50000.0,
            tp_trigger_price=55000.0, sl_trigger_price=48000.0,
        )
        result = correlate_order_to_calc(
            _build_order(),
            order_id=order_id,
            tick_size=0.1,
            window_seconds=300,
            clock_skew_tolerance_sec=10,
            db_path=db_path,
        )
        assert result.calc_id == "calc-w1"

    @pytest.mark.asyncio
    async def test_outside_window_falls_to_unplanned(self, db):
        """Calc older than window+skew = not a candidate (excluded silently)."""
        _, db_path = db
        # Calc 1000 s ago, window 300 + skew 10 = 310 s allowed
        _insert_calc(db_path, calc_id="calc-w2", ticker="BTCUSDT", side="long",
                     effective_entry=50000.0, tp_price=55000.0, sl_price=48000.0,
                     timestamp=_now_iso(-1000.0))
        order_id = _insert_order(
            db_path, exchange_order_id="w2", symbol="BTCUSDT", side="long",
            order_type="limit", price=50000.0,
            tp_trigger_price=55000.0, sl_trigger_price=48000.0,
        )
        result = correlate_order_to_calc(
            _build_order(),
            order_id=order_id,
            tick_size=0.1,
            window_seconds=300,
            clock_skew_tolerance_sec=10,
            db_path=db_path,
        )
        # Out-of-window candidate isn't audited (spec §4.3); zero
        # eligible candidates → UNPLANNED.
        assert result.calc_id is None
        assert result.link_status == LINK_STATUS_UNPLANNED
        assert result.audit_rows == []

    @pytest.mark.asyncio
    async def test_clock_skew_padding_grants_extra_window(self, db):
        """Calc just past window but within window+skew should still match.

        Why this matters: spec §4.2 explicitly pads the window with
        clock_skew_tolerance_sec. A test that doesn't exercise the
        padding wouldn't fail if someone removed it — and we'd silently
        lose matches near the boundary.
        """
        _, db_path = db
        # Calc 305 s ago, window 300, skew 10 → 310 allowed
        _insert_calc(db_path, calc_id="calc-w3", ticker="BTCUSDT", side="long",
                     effective_entry=50000.0, tp_price=55000.0, sl_price=48000.0,
                     timestamp=_now_iso(-305.0))
        order_id = _insert_order(
            db_path, exchange_order_id="w3", symbol="BTCUSDT", side="long",
            order_type="limit", price=50000.0,
            tp_trigger_price=55000.0, sl_trigger_price=48000.0,
        )
        result = correlate_order_to_calc(
            _build_order(),
            order_id=order_id,
            tick_size=0.1,
            window_seconds=300,
            clock_skew_tolerance_sec=10,
            db_path=db_path,
        )
        assert result.calc_id == "calc-w3"  # within window+skew


# ── 5. Multi-match tie-break ───────────────────────────────────────────


class TestMultiMatchTieBreak:
    """Spec §4.3: when multiple full matches exist, the most-recent wins."""

    @pytest.mark.asyncio
    async def test_most_recent_full_match_wins(self, db):
        _, db_path = db
        _insert_calc(db_path, calc_id="calc-old", ticker="BTCUSDT", side="long",
                     effective_entry=50000.0, tp_price=55000.0, sl_price=48000.0,
                     timestamp=_now_iso(-120.0))
        _insert_calc(db_path, calc_id="calc-new", ticker="BTCUSDT", side="long",
                     effective_entry=50000.0, tp_price=55000.0, sl_price=48000.0,
                     timestamp=_now_iso(-30.0))
        order_id = _insert_order(
            db_path, exchange_order_id="m1", symbol="BTCUSDT", side="long",
            order_type="limit", price=50000.0,
            tp_trigger_price=55000.0, sl_trigger_price=48000.0,
        )
        result = correlate_order_to_calc(
            _build_order(),
            order_id=order_id,
            tick_size=0.1,
            db_path=db_path,
        )
        assert result.calc_id == "calc-new"
        # Both calcs are audited; the winner's rows carry winning=True
        winner_rows = [r for r in result.audit_rows if r["calc_id"] == "calc-new"]
        loser_rows = [r for r in result.audit_rows if r["calc_id"] == "calc-old"]
        assert all(r["winning"] for r in winner_rows)
        assert not any(r["winning"] for r in loser_rows)


# ── 6. Integration: enrich_order routes through calc_state.transition ──


class TestEnrichOrderIntegration:
    """End-to-end via enrich_order: matcher → audit persistence →
    orders.calc_id+link_status → calc_state.transition(active→matched).

    Why this matters: the matcher decision is wasted if the wiring
    around it doesn't persist audit rows, update link_status, AND
    drive the calc-status state machine through the choke-point
    P0.T6 installed.
    """

    @pytest.mark.asyncio
    async def test_full_flow_persists_audit_and_transitions_calc(self, db, monkeypatch):
        from core.order_enrichment import enrich_order

        d, db_path = db
        # Point config.DB_PATH at our tmp DB (some helpers fall back to it)
        import config
        monkeypatch.setattr(config, "DB_PATH", db_path)

        _insert_calc(db_path, calc_id="calc-int1", ticker="BTCUSDT", side="long",
                     effective_entry=50000.0, tp_price=55000.0, sl_price=48000.0)
        order_id = _insert_order(
            db_path, exchange_order_id="i1", symbol="BTCUSDT", side="long",
            order_type="limit", price=50000.0,
            tp_trigger_price=55000.0, sl_trigger_price=48000.0,
        )

        # event_bus.publish enqueues into a Queue; dispatch happens via a
        # separate run() loop that isn't active in tests. Drain the queue
        # after enrich_order to verify the calc:linked event was published.
        # Drain pre-existing events first — the bus is a module-level
        # singleton and other tests may have left items in the queue.
        from core.event_bus import event_bus
        while not event_bus._queue.empty():
            event_bus._queue.get_nowait()

        await enrich_order(
            {"account_id": 1, "exchange_order_id": "i1",
             "symbol": "BTCUSDT", "side": "long", "order_type": "limit"},
            db_path,
        )

        events: List[tuple] = []
        while not event_bus._queue.empty():
            events.append(event_bus._queue.get_nowait())
        calc_linked = [(c, p) for c, p in events if c == "calc:linked"]

        # Assert calc_match_audit persisted (one row per criterion = 6)
        conn = sqlite3.connect(db_path)
        try:
            audit_rows = conn.execute(
                "SELECT criterion, matched, winning FROM calc_match_audit "
                "WHERE order_id = ?", (order_id,),
            ).fetchall()
            order_row = conn.execute(
                "SELECT calc_id, link_status FROM orders WHERE id = ?",
                (order_id,),
            ).fetchone()
            calc_row = conn.execute(
                "SELECT status FROM pre_trade_log WHERE calc_id = ?",
                ("calc-int1",),
            ).fetchone()
        finally:
            conn.close()

        assert len(audit_rows) == 6  # ticker, direction, window, entry, tp, sl
        assert all(r[1] == 1 for r in audit_rows)  # all matched
        assert all(r[2] == 1 for r in audit_rows)  # winning (single candidate)
        assert order_row[0] == "calc-int1"
        assert order_row[1] == LINK_STATUS_LINKED
        assert calc_row[0] == "matched"  # calc_state.transition flipped it
        # Verify event_bus fired through the choke-point
        assert len(calc_linked) == 1
        payload = calc_linked[0][1]
        assert payload["calc_id"] == "calc-int1"
        assert payload["from_status"] == "active"
        assert payload["to_status"] == "matched"

    @pytest.mark.asyncio
    async def test_no_match_writes_link_status_without_calc_id(self, db, monkeypatch):
        """When matcher returns NEEDS_MANUAL_REVIEW, link_status is set
        but calc_id stays NULL — operator picks the calc later via the
        Phase 3 manual-link UI.
        """
        from core.order_enrichment import enrich_order

        d, db_path = db
        import config
        monkeypatch.setattr(config, "DB_PATH", db_path)

        # Calc exists but TP doesn't match. _get_tick_size falls back to
        # max(price * 0.0001, 0.01) = 5.0 for BTC at 50k, so we use a
        # 20 USD diff to exceed that.
        _insert_calc(db_path, calc_id="calc-int2", ticker="BTCUSDT", side="long",
                     effective_entry=50000.0, tp_price=55020.0, sl_price=48000.0)
        order_id = _insert_order(
            db_path, exchange_order_id="i2", symbol="BTCUSDT", side="long",
            order_type="limit", price=50000.0,
            tp_trigger_price=55000.0, sl_trigger_price=48000.0,
        )
        await enrich_order(
            {"account_id": 1, "exchange_order_id": "i2",
             "symbol": "BTCUSDT", "side": "long", "order_type": "limit"},
            db_path,
        )

        conn = sqlite3.connect(db_path)
        try:
            order_row = conn.execute(
                "SELECT calc_id, link_status FROM orders WHERE id = ?",
                (order_id,),
            ).fetchone()
            calc_row = conn.execute(
                "SELECT status FROM pre_trade_log WHERE calc_id = ?",
                ("calc-int2",),
            ).fetchone()
        finally:
            conn.close()

        assert order_row[0] is None  # calc_id NOT stamped on near-miss
        assert order_row[1] == LINK_STATUS_NEEDS_MANUAL_REVIEW
        assert calc_row[0] == "active"  # calc not transitioned

    @pytest.mark.asyncio
    async def test_zero_candidates_writes_unplanned(self, db, monkeypatch):
        from core.order_enrichment import enrich_order

        d, db_path = db
        import config
        monkeypatch.setattr(config, "DB_PATH", db_path)

        order_id = _insert_order(
            db_path, exchange_order_id="i3", symbol="BTCUSDT", side="long",
            order_type="limit", price=50000.0,
            tp_trigger_price=55000.0, sl_trigger_price=48000.0,
        )
        await enrich_order(
            {"account_id": 1, "exchange_order_id": "i3",
             "symbol": "BTCUSDT", "side": "long", "order_type": "limit"},
            db_path,
        )

        conn = sqlite3.connect(db_path)
        try:
            order_row = conn.execute(
                "SELECT calc_id, link_status FROM orders WHERE id = ?",
                (order_id,),
            ).fetchone()
        finally:
            conn.close()

        assert order_row[0] is None
        assert order_row[1] == LINK_STATUS_UNPLANNED


# ── 7. Backfill migration ──────────────────────────────────────────────


class TestNullStatusBackfill:
    """P1.T1 ships a one-shot UPDATE that sets pre_trade_log.status='expired'
    for legacy NULL-status rows. Pin the migration runs at initialize().
    """

    @pytest.mark.asyncio
    async def test_null_status_rows_become_expired(self, db):
        d, db_path = db
        # Insert a row with status=NULL directly via sqlite3, bypassing the
        # CHECK that would normally apply during normal app insertion.
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO pre_trade_log "
                "(account_id, timestamp, ticker, side, "
                " effective_entry, tp_price, sl_price, average, "
                " calc_id, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
                (1, _now_iso(), "BTCUSDT", "long",
                 50000.0, 55000.0, 48000.0, 50000.0, "calc-legacy"),
            )
            conn.commit()
        finally:
            conn.close()

        # Re-run initialize (idempotent) — the backfill UPDATE flips the NULL
        await d.initialize()

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT status FROM pre_trade_log WHERE calc_id = ?",
                ("calc-legacy",),
            ).fetchone()
        finally:
            conn.close()
        assert row[0] == "expired"
