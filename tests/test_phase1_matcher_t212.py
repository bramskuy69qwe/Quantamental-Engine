"""
Task 212 — regression tests for the M2 + L1/L2/L5 fixes.

Covers the observable behavior changes from T212:
- L1: enrich_order's try/except split (populate failure doesn't mask
  correlate)
- L2: find_candidate_calcs honors _norm_side (BUY ↔ long matching for
  Phase 3 manual-link UI)
- L5: matcher logs a warning when created_at_ms is missing/zero
  (silent now() fallback was masking adapter timestamp gaps)

M2 (asyncio.to_thread wrap) and L3 (tick-size fallback warning) and L6
(UNLINKED enum doc) don't have observable behavior changes worth
testing — they're internal hygiene improvements.

Run: pytest tests/test_phase1_matcher_t212.py -v
"""
from __future__ import annotations

import logging
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.calc_correlation import (
    correlate_order_to_calc,
    find_candidate_calcs,
)


# ── Shared fixtures ────────────────────────────────────────────────────


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


def _insert_calc(db_path: str, **kwargs) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO pre_trade_log "
            "(account_id, timestamp, ticker, side, effective_entry, "
            " tp_price, sl_price, average, calc_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (kwargs.get("account_id", 1),
             kwargs.get("timestamp", _now_iso(-5.0)),
             kwargs.get("ticker", "BTCUSDT"),
             kwargs.get("side", "long"),
             kwargs.get("effective_entry", 50000.0),
             kwargs.get("tp_price", 55000.0),
             kwargs.get("sl_price", 48000.0),
             kwargs.get("effective_entry", 50000.0),
             kwargs.get("calc_id", "test-calc"),
             kwargs.get("status", "active")),
        )
        conn.commit()
    finally:
        conn.close()


# ── L2: find_candidate_calcs side-normalization ────────────────────────


class TestL2FindCandidateCalcsSideNorm:
    """L2 fix: the Phase 3 manual-link UI's candidate finder must also
    honor side-vocabulary normalization. Pre-T212 it was case-sensitive
    and would silently return [] when calc.side='long' and order.side='BUY'.

    Why this matters: needs-link panel renders these candidates with
    per-criterion diffs so the operator can manually link. If the
    candidate finder doesn't return them, the operator sees an empty
    panel for a real near-miss — and the order quietly sits in
    NEEDS_MANUAL_REVIEW with no resolution path.
    """

    @pytest.mark.asyncio
    async def test_calc_long_finds_order_buy(self, db):
        _, db_path = db
        _insert_calc(db_path, calc_id="l2-c1", side="long",
                     effective_entry=50000.0, tp_price=55000.0, sl_price=48000.0)

        # find_candidate_calcs is called by the needs-link UI on the
        # ORDER's side (which is 'BUY' from the WS adapter).
        order = {
            "account_id": 1, "symbol": "BTCUSDT", "side": "BUY",
            "price": 50000.0,
            "tp_trigger_price": 55000.0, "sl_trigger_price": 48000.0,
        }
        candidates = find_candidate_calcs(
            order, max_drift_pct=0.05, within_hours=24, db_path=db_path,
        )
        # Pre-T212: 0 candidates (side mismatch in SQL). Post-T212: 1.
        assert len(candidates) == 1
        assert candidates[0].calc_id == "l2-c1"

    @pytest.mark.asyncio
    async def test_calc_short_finds_order_sell(self, db):
        _, db_path = db
        _insert_calc(db_path, calc_id="l2-c2", side="short",
                     effective_entry=50000.0, tp_price=45000.0, sl_price=52000.0)

        order = {
            "account_id": 1, "symbol": "BTCUSDT", "side": "SELL",
            "price": 50000.0,
            "tp_trigger_price": 45000.0, "sl_trigger_price": 52000.0,
        }
        candidates = find_candidate_calcs(
            order, max_drift_pct=0.05, within_hours=24, db_path=db_path,
        )
        assert len(candidates) == 1
        assert candidates[0].calc_id == "l2-c2"

    @pytest.mark.asyncio
    async def test_side_mismatch_excluded(self, db):
        """Calc 'long', order 'SELL' — different directions, candidate
        filter excludes.
        """
        _, db_path = db
        _insert_calc(db_path, calc_id="l2-c3", side="long",
                     effective_entry=50000.0, tp_price=55000.0, sl_price=48000.0)

        order = {
            "account_id": 1, "symbol": "BTCUSDT", "side": "SELL",
            "price": 50000.0,
            "tp_trigger_price": 55000.0, "sl_trigger_price": 48000.0,
        }
        candidates = find_candidate_calcs(
            order, max_drift_pct=0.05, within_hours=24, db_path=db_path,
        )
        assert candidates == []


# ── L5: created_at_ms fallback warning ─────────────────────────────────


class TestL5CreatedAtMsFallbackWarning:
    """L5 fix: when the matcher receives an order with no created_at_ms,
    it falls back to now() — which silently passes the in-window check.
    A log warning surfaces the fallback so we notice when production
    hits it (suggests an adapter ingest bug).
    """

    @pytest.mark.asyncio
    async def test_missing_created_at_ms_logs_warning(self, db, caplog):
        _, db_path = db
        _insert_calc(db_path, calc_id="l5-c1")

        # Order built WITHOUT created_at_ms
        order = {
            "account_id": 1, "symbol": "BTCUSDT", "side": "BUY",
            "order_type": "limit", "price": 50000.0,
            "tp_trigger_price": 55000.0, "sl_trigger_price": 48000.0,
            # created_at_ms intentionally omitted
        }

        with caplog.at_level(logging.WARNING, logger="calc_correlation"):
            result = correlate_order_to_calc(
                order, order_id=1, tick_size=0.1, db_path=db_path,
            )

        # Matcher still works (fallback to now()), so the candidate
        # is in-window and matches.
        assert result.calc_id == "l5-c1"
        # And the warning was logged.
        warnings = [r for r in caplog.records
                    if "no created_at_ms" in r.getMessage()]
        assert len(warnings) >= 1, (
            "expected a warning when matcher falls back to now() for "
            "missing created_at_ms; got log records: "
            f"{[r.getMessage() for r in caplog.records]}"
        )

    @pytest.mark.asyncio
    async def test_zero_created_at_ms_logs_warning(self, db, caplog):
        """Same behavior when ts is explicitly 0 (the DDL default for
        the orders table)."""
        _, db_path = db
        _insert_calc(db_path, calc_id="l5-c2")

        order = {
            "account_id": 1, "symbol": "BTCUSDT", "side": "BUY",
            "order_type": "limit", "price": 50000.0,
            "tp_trigger_price": 55000.0, "sl_trigger_price": 48000.0,
            "created_at_ms": 0,
        }

        with caplog.at_level(logging.WARNING, logger="calc_correlation"):
            result = correlate_order_to_calc(
                order, order_id=1, tick_size=0.1, db_path=db_path,
            )
        assert result.calc_id == "l5-c2"
        warnings = [r for r in caplog.records
                    if "no created_at_ms" in r.getMessage()]
        assert len(warnings) >= 1


# ── L1: enrich_order try/except split ──────────────────────────────────


class TestL1EnrichOrderTryExceptSplit:
    """L1 fix: a populator failure must not skip the matcher. Pre-T212,
    one outer try/except wrapped both steps — if populate threw, the
    matcher never ran. Post-T212, each step has its own try/except;
    populator failures log distinctly and the matcher still runs.

    Why this matters: the matcher is independently useful even when the
    populator fails. The populator reads child TP/SL orders and stamps
    parent.tp_trigger_price/sl_trigger_price; the matcher reads those
    same fields from DB later. If the populator can recover its work
    in a later re-enrichment, the matcher should still get to try
    NOW with whatever's already in DB.
    """

    @pytest.mark.asyncio
    async def test_populator_failure_doesnt_skip_correlate(
        self, db, monkeypatch, caplog,
    ):
        from core import order_enrichment
        from core.order_enrichment import enrich_order

        d, db_path = db
        import config
        monkeypatch.setattr(config, "DB_PATH", db_path)

        # Seed: calc + order with tp/sl ALREADY stamped (so we don't
        # need the populator to do its job to test the matcher path).
        _insert_calc(db_path, calc_id="l1-c1")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO orders "
                "(account_id, exchange_order_id, symbol, side, order_type, "
                " price, tp_trigger_price, sl_trigger_price, created_at_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (1, "l1-o", "BTCUSDT", "BUY", "limit",
                 50000.0, 55000.0, 48000.0, int(datetime.now().timestamp()*1000)),
            )
            conn.commit()
        finally:
            conn.close()

        # Make the populator raise. Patch on the module attribute since
        # enrich_order calls it directly.
        def _bad_populator(order, db_path):
            raise RuntimeError("simulated populator failure")
        monkeypatch.setattr(
            order_enrichment, "_populate_tp_sl_trigger_prices",
            _bad_populator,
        )

        with caplog.at_level(logging.WARNING, logger="order_enrichment"):
            await enrich_order(
                {"account_id": 1, "exchange_order_id": "l1-o",
                 "symbol": "BTCUSDT", "side": "BUY",
                 "order_type": "limit"},
                db_path,
            )

        # The populator warning should appear...
        populate_warnings = [
            r for r in caplog.records
            if "populate tp/sl trigger prices failed" in r.getMessage()
        ]
        assert len(populate_warnings) >= 1, (
            "populator failure should log a distinct warning"
        )

        # ...AND the matcher should have still run and linked the order.
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT calc_id, link_status FROM orders "
                "WHERE exchange_order_id = ?",
                ("l1-o",),
            ).fetchone()
        finally:
            conn.close()
        assert row[0] == "l1-c1", (
            f"matcher should have run despite populator failure; "
            f"got calc_id={row[0]!r}"
        )
        assert row[1] == "LINKED"
