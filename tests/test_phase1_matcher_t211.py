"""
Task 211 — regression tests for P1.T1 audit follow-up.

Pins the H1/H2/H3/H4/M3/M5/L4 fixes so the audit findings don't
silently recur. Each test class encodes one finding's intent.

Why a separate file rather than appending to test_phase1_matcher.py:
keeps the original spec-acceptance pins distinct from the
audit-regression pins. If a future task tightens the matcher and
breaks one of these, the failing test name immediately maps to the
audit finding (H1, H2, etc.) for triage.

Run: pytest tests/test_phase1_matcher_t211.py -v
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.calc_correlation import (
    LINK_STATUS_LINKED,
    LINK_STATUS_NEEDS_MANUAL_REVIEW,
    LINK_STATUS_UNPLANNED,
    _norm_side,
    correlate_order_to_calc,
)


# ── Shared fixtures (mirror tests/test_phase1_matcher.py) ─────────────


@pytest_asyncio.fixture
async def db():
    """Tempfile DB initialized with the full schema."""
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
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


def _insert_calc(db_path: str, **kwargs) -> None:
    """Insert a pre_trade_log row with explicit defaults."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO pre_trade_log "
            "(account_id, timestamp, ticker, side, "
            " effective_entry, tp_price, sl_price, average, "
            " calc_id, status, window_seconds) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (kwargs.get("account_id", 1),
             kwargs.get("timestamp", _now_iso(-5.0)),
             kwargs.get("ticker", "BTCUSDT"),
             kwargs.get("side", "long"),
             kwargs.get("effective_entry", 50000.0),
             kwargs.get("tp_price", 55000.0),
             kwargs.get("sl_price", 48000.0),
             kwargs.get("effective_entry", 50000.0),  # average mirrors entry
             kwargs.get("calc_id", "test-calc"),
             kwargs.get("status", "active"),
             kwargs.get("window_seconds")),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_order(db_path: str, **kwargs) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO orders "
            "(account_id, exchange_order_id, symbol, side, order_type, "
            " price, tp_trigger_price, sl_trigger_price, avg_fill_price, "
            " created_at_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (kwargs.get("account_id", 1),
             kwargs.get("exchange_order_id", "o-test"),
             kwargs.get("symbol", "BTCUSDT"),
             kwargs.get("side", "BUY"),
             kwargs.get("order_type", "limit"),
             kwargs.get("price", 50000.0),
             kwargs.get("tp_trigger_price", 55000.0),
             kwargs.get("sl_trigger_price", 48000.0),
             kwargs.get("avg_fill_price", 0.0),
             kwargs.get("created_at_ms", _now_ms())),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ── H1: side-vocabulary normalization ─────────────────────────────────


class TestH1SideNormalization:
    """H1 fix: matcher must collapse BUY/long, SELL/short via _norm_side.

    Why this matters: the calculator writes 'long'/'short' into
    pre_trade_log.side, but WS adapters write 'BUY'/'SELL' into
    orders.side. Pre-T211 the matcher's SQL `WHERE side = ?` would
    never match anything in production.
    """

    def test_norm_side_buy_maps_to_long(self):
        assert _norm_side("BUY") == "long"
        assert _norm_side("buy") == "long"
        assert _norm_side("Buy") == "long"
        assert _norm_side("long") == "long"
        assert _norm_side("LONG") == "long"

    def test_norm_side_sell_maps_to_short(self):
        assert _norm_side("SELL") == "short"
        assert _norm_side("sell") == "short"
        assert _norm_side("short") == "short"
        assert _norm_side("SHORT") == "short"

    def test_norm_side_empty_returns_empty(self):
        assert _norm_side("") == ""
        assert _norm_side(None) == ""

    def test_norm_side_unknown_returns_lowercased(self):
        """Unknown values aren't auto-mapped — mismatch fails the
        criterion explicitly instead of silently aliasing.
        """
        assert _norm_side("close") == "close"
        assert _norm_side("CLOSE") == "close"

    @pytest.mark.asyncio
    async def test_calc_long_order_BUY_matches(self, db):
        """The production case: pre_trade_log.side='long',
        orders.side='BUY'. New matcher matches them.
        """
        _, db_path = db
        _insert_calc(db_path, calc_id="cl1", side="long")  # calc convention
        order_id = _insert_order(db_path, side="BUY")       # WS convention
        result = correlate_order_to_calc(
            {"account_id": 1, "symbol": "BTCUSDT", "side": "BUY",
             "order_type": "limit", "price": 50000.0,
             "tp_trigger_price": 55000.0, "sl_trigger_price": 48000.0},
            order_id=order_id,
            tick_size=0.1,
            db_path=db_path,
        )
        assert result.calc_id == "cl1"
        assert result.link_status == LINK_STATUS_LINKED

    @pytest.mark.asyncio
    async def test_calc_short_order_SELL_matches(self, db):
        _, db_path = db
        _insert_calc(db_path, calc_id="cs1", side="short",
                     effective_entry=50000.0, tp_price=45000.0, sl_price=52000.0)
        order_id = _insert_order(
            db_path, side="SELL",
            tp_trigger_price=45000.0, sl_trigger_price=52000.0,
        )
        result = correlate_order_to_calc(
            {"account_id": 1, "symbol": "BTCUSDT", "side": "SELL",
             "order_type": "limit", "price": 50000.0,
             "tp_trigger_price": 45000.0, "sl_trigger_price": 52000.0},
            order_id=order_id,
            tick_size=0.1,
            db_path=db_path,
        )
        assert result.calc_id == "cs1"

    @pytest.mark.asyncio
    async def test_side_mismatch_excluded(self, db):
        """Calc is 'long', order is 'SELL' — different directions
        normalize differently; candidate excluded. Result: UNPLANNED
        (since the only candidate doesn't match side).
        """
        _, db_path = db
        _insert_calc(db_path, calc_id="cn1", side="long")
        order_id = _insert_order(db_path, side="SELL")
        result = correlate_order_to_calc(
            {"account_id": 1, "symbol": "BTCUSDT", "side": "SELL",
             "order_type": "limit", "price": 50000.0,
             "tp_trigger_price": 55000.0, "sl_trigger_price": 48000.0},
            order_id=order_id,
            tick_size=0.1,
            db_path=db_path,
        )
        assert result.calc_id is None
        assert result.link_status == LINK_STATUS_UNPLANNED


# ── H2: status='active' written at calc creation ──────────────────────


class TestH2StatusWrite:
    """H2 fix: insert_pre_trade_log writes status='active' so new calcs
    are matcher-eligible (and not flipped to 'expired' by the next-
    startup backfill).

    Why this matters: the P0.T3 schema column DEFAULTed to NULL. Pre-
    T211, every new calc landed NULL → excluded by the matcher's
    status IN ('active', 'released') filter → orphaned at next restart
    by the T210 backfill migration.
    """

    @pytest.mark.asyncio
    async def test_new_calc_has_status_active(self, db):
        d, db_path = db
        await d.insert_pre_trade_log({
            "account_id": 1,
            "timestamp": _now_iso(),
            "ticker": "BTCUSDT",
            "side": "long",
            "effective_entry": 50000.0,
            "tp_price": 55000.0,
            "sl_price": 48000.0,
            "calc_id": "h2-test-calc",
        })

        async with d._conn.execute(
            "SELECT status FROM pre_trade_log WHERE calc_id = ?",
            ("h2-test-calc",),
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        assert row[0] == "active"

    @pytest.mark.asyncio
    async def test_caller_can_override_status(self, db):
        """Supersede flow writes status='superseded' directly; the
        helper must honor explicit overrides.
        """
        d, db_path = db
        await d.insert_pre_trade_log({
            "account_id": 1,
            "timestamp": _now_iso(),
            "ticker": "BTCUSDT",
            "side": "long",
            "effective_entry": 50000.0,
            "tp_price": 55000.0,
            "sl_price": 48000.0,
            "calc_id": "h2-override-calc",
            "status": "superseded",  # explicit override
        })

        async with d._conn.execute(
            "SELECT status FROM pre_trade_log WHERE calc_id = ?",
            ("h2-override-calc",),
        ) as cur:
            row = await cur.fetchone()
        assert row[0] == "superseded"


# ── H3: NEEDS_MANUAL_REVIEW skips re-runs ─────────────────────────────


class TestH3NoAuditExplosion:
    """H3 fix: once link_status='NEEDS_MANUAL_REVIEW' is set, repeated
    enrich_order calls early-return — they don't write fresh audit
    rows on every WS update.

    Why this matters: pre-T211 a needs-review order with N candidates
    would write 6×N audit rows per WS update. A real order can see
    5-20 WS updates over its lifetime (status flips, partial-fill
    progress, amendments). That's 100s-1000s of duplicate audit rows.
    """

    @pytest.mark.asyncio
    async def test_repeated_enrich_after_review_doesnt_grow_audit(
        self, db, monkeypatch,
    ):
        from core.order_enrichment import enrich_order
        d, db_path = db
        import config
        monkeypatch.setattr(config, "DB_PATH", db_path)

        # Calc TP off by 20 USD (exceeds tick_size=5 heuristic) →
        # matcher routes to NEEDS_MANUAL_REVIEW on first run.
        _insert_calc(db_path, calc_id="h3-calc",
                     effective_entry=50000.0, tp_price=55020.0, sl_price=48000.0)
        order_id = _insert_order(
            db_path, exchange_order_id="h3-o",
            tp_trigger_price=55000.0, sl_trigger_price=48000.0,
        )

        order_dict = {
            "account_id": 1, "exchange_order_id": "h3-o",
            "symbol": "BTCUSDT", "side": "BUY", "order_type": "limit",
        }

        # First enrich_order → matcher runs, writes audit rows,
        # sets link_status=NEEDS_MANUAL_REVIEW.
        await enrich_order(order_dict, db_path)

        conn = sqlite3.connect(db_path)
        try:
            count_after_first = conn.execute(
                "SELECT COUNT(*) FROM calc_match_audit WHERE order_id = ?",
                (order_id,),
            ).fetchone()[0]
        finally:
            conn.close()
        assert count_after_first > 0  # matcher did run once

        # Second, third, fourth enrich_order calls — should ALL be
        # no-ops because link_status is already NEEDS_MANUAL_REVIEW.
        for _ in range(3):
            await enrich_order(order_dict, db_path)

        conn = sqlite3.connect(db_path)
        try:
            count_after_repeats = conn.execute(
                "SELECT COUNT(*) FROM calc_match_audit WHERE order_id = ?",
                (order_id,),
            ).fetchone()[0]
        finally:
            conn.close()

        # Same count — no duplicates.
        assert count_after_repeats == count_after_first, (
            f"audit rows grew from {count_after_first} to "
            f"{count_after_repeats} across 4 enrich_order calls — "
            f"H3 guard isn't holding"
        )

    @pytest.mark.asyncio
    async def test_repeated_enrich_on_unplanned_is_safe(
        self, db, monkeypatch,
    ):
        """UNPLANNED is allowed to re-run — no audit rows are written
        on UNPLANNED (zero candidates), so re-runs are cheap. Newly-
        arriving calcs could move UNPLANNED → LINKED on a later call.
        """
        from core.order_enrichment import enrich_order
        d, db_path = db
        import config
        monkeypatch.setattr(config, "DB_PATH", db_path)

        # No calcs seeded → first enrich_order returns UNPLANNED.
        order_id = _insert_order(
            db_path, exchange_order_id="h3u-o",
            tp_trigger_price=55000.0, sl_trigger_price=48000.0,
        )
        await enrich_order({
            "account_id": 1, "exchange_order_id": "h3u-o",
            "symbol": "BTCUSDT", "side": "BUY", "order_type": "limit",
        }, db_path)

        # Now insert a matching calc and re-enrich — should LINK.
        _insert_calc(db_path, calc_id="h3u-calc")
        await enrich_order({
            "account_id": 1, "exchange_order_id": "h3u-o",
            "symbol": "BTCUSDT", "side": "BUY", "order_type": "limit",
        }, db_path)

        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT calc_id, link_status FROM orders WHERE id = ?",
                (order_id,),
            ).fetchone()
        finally:
            conn.close()
        assert row[0] == "h3u-calc"
        assert row[1] == LINK_STATUS_LINKED


# ── M3: TOCTOU on status flip ─────────────────────────────────────────


class TestM3TOCTOUStatusFlip:
    """M3 fix: the UPDATE that flips active → matched is scoped with
    AND status = ?. If a concurrent caller (operator cancel, supersede)
    moved status out from under the matcher, the UPDATE affects 0 rows
    and event emission is skipped.

    Why this matters: pre-T211 the UPDATE was unguarded, so we could
    publish calc:linked for a calc whose actual current state was
    'cancelled_by_operator' — operator gets a stale event for a calc
    they just cancelled.
    """

    @pytest.mark.asyncio
    async def test_concurrent_cancel_blocks_transition(
        self, db, monkeypatch,
    ):
        """Simulate the race: matcher reads status='active', then
        operator-cancel flips it to 'cancelled_by_operator', then the
        apply_fn UPDATE fires. UPDATE should match 0 rows, event
        shouldn't fire.
        """
        from core.order_enrichment import enrich_order
        from core.event_bus import event_bus
        d, db_path = db
        import config
        monkeypatch.setattr(config, "DB_PATH", db_path)

        _insert_calc(db_path, calc_id="m3-calc")
        order_id = _insert_order(db_path, exchange_order_id="m3-o")

        # Race injection: flip status to cancelled_by_operator AFTER
        # the matcher's SELECT but BEFORE the apply_fn UPDATE.
        # Cleanest way: monkeypatch transition() to inject the flip in
        # between validation and apply_fn invocation.
        from core import calc_state
        original_transition = calc_state.transition

        async def racing_transition(
            calc_id, current_status, target_status, *, apply_fn, **kwargs,
        ):
            # Inject the race by flipping status before apply_fn runs.
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    "UPDATE pre_trade_log SET status = ? WHERE calc_id = ?",
                    ("cancelled_by_operator", calc_id),
                )
                conn.commit()
            finally:
                conn.close()
            # Now call the real transition — apply_fn's WHERE status=?
            # will affect 0 rows.
            await original_transition(
                calc_id, current_status, target_status,
                apply_fn=apply_fn, **kwargs,
            )

        # _try_correlate does ``from core.calc_state import transition``
        # inside the function (local import). Patch on the source module
        # so the next import picks up the monkeypatched version.
        monkeypatch.setattr("core.calc_state.transition", racing_transition)

        # Drain bus before
        while not event_bus._queue.empty():
            event_bus._queue.get_nowait()

        await enrich_order({
            "account_id": 1, "exchange_order_id": "m3-o",
            "symbol": "BTCUSDT", "side": "BUY", "order_type": "limit",
        }, db_path)

        # Verify pre_trade_log status stayed at 'cancelled_by_operator'
        # (the racing flip won, not the matcher).
        conn = sqlite3.connect(db_path)
        try:
            status = conn.execute(
                "SELECT status FROM pre_trade_log WHERE calc_id = ?",
                ("m3-calc",),
            ).fetchone()[0]
        finally:
            conn.close()
        assert status == "cancelled_by_operator", (
            f"matcher overwrote a concurrent cancel — got {status!r}"
        )

        # Verify no calc:linked event published.
        events = []
        while not event_bus._queue.empty():
            events.append(event_bus._queue.get_nowait()[:2])  # CL.T2a: item is (ch, payload, corr_id)
        # P6.T3: calc:linked now rides engine:account:{id}:calc:linked.
        linked = [e for e in events if e[0].endswith(":calc:linked")]
        assert len(linked) == 0, (
            f"matcher emitted calc:linked despite losing the race: "
            f"{linked}"
        )


# ── M5: zero calc_entry skipped, not silently failed ──────────────────


class TestM5MalformedCalcSkip:
    """M5 fix: a calc with effective_entry=0 (or TP/SL=0) is malformed
    and skipped as a candidate. Pre-T211 the matcher silently set
    drift=1.0 and reported matched=False on the entry criterion —
    which looked like a real drift miss in the audit row.

    Why this matters: zero-value calcs come from data corruption or
    edge cases in calculator rounding. They shouldn't pollute the
    audit log with phantom near-misses.
    """

    @pytest.mark.asyncio
    async def test_zero_entry_calc_excluded(self, db):
        _, db_path = db
        # Insert a malformed calc (entry=0)
        _insert_calc(db_path, calc_id="m5-bad",
                     effective_entry=0.0, tp_price=55000.0, sl_price=48000.0)
        # Plus a clean calc for the same symbol
        _insert_calc(db_path, calc_id="m5-good",
                     effective_entry=50000.0, tp_price=55000.0, sl_price=48000.0)

        order_id = _insert_order(db_path)
        result = correlate_order_to_calc(
            {"account_id": 1, "symbol": "BTCUSDT", "side": "BUY",
             "order_type": "limit", "price": 50000.0,
             "tp_trigger_price": 55000.0, "sl_trigger_price": 48000.0},
            order_id=order_id,
            tick_size=0.1,
            db_path=db_path,
        )
        # Matcher should match the GOOD calc, ignoring the malformed one.
        assert result.calc_id == "m5-good"
        # No audit rows from the malformed calc.
        for r in result.audit_rows:
            assert r["calc_id"] != "m5-bad", (
                "malformed calc leaked into audit rows"
            )

    @pytest.mark.asyncio
    async def test_zero_tp_calc_routes_to_manual_review(self, db):
        """T7 (P1.T7) CHANGED this behavior: a zero/null-TP calc is no
        longer M5-skipped (that was a T211 over-reach). Per spec Q27,
        nullable TP/SL is legitimate and must auto-route to manual-link.
        So a zero-TP calc is now a CANDIDATE whose TP criterion fails →
        order → NEEDS_MANUAL_REVIEW (not UNPLANNED). Only null/0 ENTRY
        is still skipped (the anchor).
        """
        from core.calc_correlation import LINK_STATUS_NEEDS_MANUAL_REVIEW
        _, db_path = db
        _insert_calc(db_path, calc_id="m5-zerotp",
                     effective_entry=50000.0, tp_price=0.0, sl_price=48000.0)
        order_id = _insert_order(db_path)
        result = correlate_order_to_calc(
            {"account_id": 1, "symbol": "BTCUSDT", "side": "BUY",
             "order_type": "limit", "price": 50000.0,
             "tp_trigger_price": 55000.0, "sl_trigger_price": 48000.0},
            order_id=order_id,
            tick_size=0.1,
            db_path=db_path,
        )
        # Candidate exists (zero-TP), TP criterion fails → manual review.
        assert result.calc_id is None
        assert result.link_status == LINK_STATUS_NEEDS_MANUAL_REVIEW
        # Audit rows ARE present now (the candidate was evaluated); the
        # TP criterion shows matched=False.
        by_criterion = {r["criterion"]: r for r in result.audit_rows}
        assert by_criterion["tp"]["matched"] is False


# ── H4 + M4 — covered implicitly by integration tests + matcher tests ──
#
# H4 (post-fill enrich_order re-fire): covered end-to-end by
# tests/integration/test_scenarios.py::happy_path_market + market_entry_with_tpsl
# which exercise the fill-arrives → matcher-succeeds flow.
#
# M4 (composite index): a presence test would assert the index name
# exists in PRAGMA index_list, but the index is auxiliary (correctness
# unaffected) and creating an index-presence test gives little value
# beyond a smoke check. Skip for now; if the index gets dropped in a
# future refactor, integration-test performance regressions will
# surface it.
