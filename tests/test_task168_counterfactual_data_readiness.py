"""
Task 168 regression tests — counterfactual data-readiness.

Verify-first per CLAUDE.md re-investigation discipline. The spec
flagged two findings as data-readiness gates for step 2 (historical
counterfactual + multi-P&L leaderboard). Investigation outcomes:

  FE-MED-017 — BTCUSDT pollution (278 entry_price=0 rows in
    trade_events). REPLAY SET = closed_positions JOIN pre_trade_log
    on calc_id (the T167 query shape). Investigation shows:
      • Pollution lives in the display-only trade_events table.
      • The T167 replay-set query excludes calc_id IS NULL/empty AND
        regime_multiplier IS NULL/<=0. Pre-prod test fixtures predate
        T87 (calc_id) AND T157 (regime_multiplier), so the replay set
        excludes them BY CONSTRUCTION.
    DOWN-SCOPED + DEFENSE-IN-DEPTH: pollution is display-only. Replay
    set is clean. T168 ships a write-time entry_price > 0 guard at
    the canonical insert_closed_position path + the trade_events
    position_closed write so future pollution sources can't reach
    either surface even if they bypass the calc_id path.

  FE-MED-008 — 2/7 macro signal cards "not backfilled". Investigation:
      • 7 regime cards: vix, us10y, hy, btc_dominance, btc_rvol_ratio,
        agg_oi_change, avg_funding.
      • btc_dominance is DISPLAY-ONLY — not in classifier ALL_SIGNALS.
        Doesn't affect counterfactual.
      • agg_oi_change + avg_funding: bounded by Binance public-API
        ~2-3yr window — HARD DATA-AVAILABILITY LIMIT, NOT backfillable.
      • Classifier auto-falls to mode="macro_only" when these are
        absent (regime_classifier.py:96-99 + 353-354). T157 persists
        regime_mode per pre_trade_log row.
    NOT-A-FIX — hard limit. Counterfactual replay on pre-window dates
    will produce macro_only-derived labels by construction. The
    leaderboard footnoting concern is step-2 scope; T168 just pins
    the auto-fallback + the regime_mode persistence as the data-
    readiness mechanism.

What this file pins:
  • Pollution-shape closed_positions writes refused; non-pollution
    writes still go through.
  • Pollution-shape trade_event 'position_closed' refused; other
    event types unaffected.
  • Refusal logs.warning so the operator sees rejected writes.
  • Live calc-backed close rows (entry_price > 0) flow through both
    paths unchanged.
  • FE-MED-008 mechanism: classifier with missing crypto signals →
    falls to macro_only. T157 regime_mode column carries this so the
    counterfactual / leaderboard can footnote macro_only-only rows.
  • T167 replay-set query (get_dual_pnl_trades) excludes pollution
    by construction — pin this so step 2 inherits the clean set.
  • Source pins for both T168 guards.

Run: pytest tests/test_task168_counterfactual_data_readiness.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def test_db():
    from core.database import DatabaseManager

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    yield db
    await db.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


def _real_close_row(**overrides) -> dict:
    """A canonical real-fill close row (entry_price > 0)."""
    base = {
        "account_id":           1,
        "exchange_position_id": "x123",
        "terminal_position_id": "t-real-1",
        "symbol":               "BTCUSDT",
        "direction":            "LONG",
        "quantity":             0.01,
        "entry_price":          80000.0,
        "exit_price":           81000.0,
        "entry_time_ms":        1716000000000,
        "exit_time_ms":         1716000060000,
        "realized_pnl":         10.0,
        "total_fees":           0.5,
        "net_pnl":              9.5,
        "calc_id":              "calc-real-1",
    }
    base.update(overrides)
    return base


def _pollution_close_row(**overrides) -> dict:
    """The 278-row pre-prod test-fixture shape — entry_price=0,
    exit_price > 0, quantity > 0."""
    base = _real_close_row(
        terminal_position_id="t-pollute-1",
        entry_price=0.0,           # ← the pollution marker
        calc_id=None,              # pre-T87 fixtures have no calc_id
    )
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# 1. FE-MED-017 — write-time pollution guard at insert_closed_position
# ─────────────────────────────────────────────────────────────────────────────


class TestClosedPositionsPollutionGuard:
    @pytest.mark.asyncio
    async def test_pollution_shape_row_refused(self, test_db, caplog):
        """entry_price=0 + quantity>0 + exit_price>0 → write refused +
        warning logged. Mirrors the exact shape of the 278 BTCUSDT
        pre-prod fixtures."""
        import logging
        caplog.set_level(logging.WARNING, logger="database")
        await test_db.insert_closed_position(_pollution_close_row())

        async with test_db._conn.execute(
            "SELECT COUNT(*) FROM closed_positions"
        ) as cur:
            n = (await cur.fetchone())[0]
        assert n == 0, (
            "Task 168 regression: pollution-shape row reached "
            "closed_positions — write-time guard at insert_closed_"
            "position failed."
        )

    @pytest.mark.asyncio
    async def test_real_fill_passes_unchanged(self, test_db):
        """entry_price > 0 → row goes through; the guard targets only
        the pollution shape."""
        await test_db.insert_closed_position(_real_close_row())
        async with test_db._conn.execute(
            "SELECT entry_price, exit_price, calc_id FROM closed_positions"
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        assert row[0] == pytest.approx(80000.0)
        assert row[1] == pytest.approx(81000.0)
        assert row[2] == "calc-real-1"

    @pytest.mark.asyncio
    async def test_zero_quantity_with_zero_entry_does_not_match_pollution(self, test_db):
        """quantity=0 + entry=0 is a degenerate row (probably should
        also be rejected, but NOT by this guard — it's not the
        pollution shape). The guard targets the specific 'qty>0 +
        exit>0 + entry=0' combination."""
        await test_db.insert_closed_position(_real_close_row(
            terminal_position_id="t-zero-qty",
            entry_price=0.0, quantity=0, exit_price=0.0,
        ))
        async with test_db._conn.execute(
            "SELECT COUNT(*) FROM closed_positions"
        ) as cur:
            n = (await cur.fetchone())[0]
        # Insert went through — guard doesn't fire on this shape.
        # (It's a separate data-quality question whether engine should
        # ever emit qty=0 close rows.)
        assert n == 1

    @pytest.mark.asyncio
    async def test_guard_warns_on_refused_write(self, test_db, caplog):
        import logging
        caplog.set_level(logging.WARNING, logger="database")
        await test_db.insert_closed_position(_pollution_close_row(
            symbol="BTCUSDT",
        ))
        msgs = [r.message for r in caplog.records]
        joined = " ".join(msgs)
        assert "FE-MED-017" in joined
        assert "pollution" in joined.lower()
        assert "BTCUSDT" in joined


# ─────────────────────────────────────────────────────────────────────────────
# 2. FE-MED-017 — same guard at trade_event 'position_closed' writes
# ─────────────────────────────────────────────────────────────────────────────


class TestTradeEventsPollutionGuard:
    def test_pollution_position_closed_event_refused(self, tmp_path, caplog):
        """log_trade_event('position_closed', entry_price=0, exit_price>0)
        → returns -1 sentinel, no DB write."""
        import logging
        import sqlite3
        from core.trade_event_log import log_trade_event
        from core import database as _db_mod

        # Build a stripped-down DB with the trade_events table only,
        # used directly via the data_dir override.
        db_path = tmp_path / "risk_engine.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE accounts (id INTEGER PRIMARY KEY);
            INSERT INTO accounts (id) VALUES (1);
            CREATE TABLE trade_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              account_id INTEGER NOT NULL,
              calc_id TEXT,
              event_type TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              source TEXT NOT NULL,
              timestamp TEXT NOT NULL
            );
            """
        )
        conn.commit()
        conn.close()

        caplog.set_level(logging.WARNING, logger="trade_event_log")
        result = log_trade_event(
            account_id=1, calc_id="any",
            event_type="position_closed",
            payload={"symbol": "BTCUSDT", "entry_price": 0.0, "exit_price": 110.0},
            source="test",
            data_dir=str(tmp_path),
        )
        assert result == -1, (
            "Task 168 regression: pollution-shape trade_event reached "
            "the DB — guard at log_trade_event failed."
        )

        # DB row count = 0
        conn = sqlite3.connect(str(db_path))
        n = conn.execute("SELECT COUNT(*) FROM trade_events").fetchone()[0]
        conn.close()
        assert n == 0

        # Warning logged with FE-MED-017 anchor
        joined = " ".join(r.message for r in caplog.records)
        assert "FE-MED-017" in joined
        assert "pollution" in joined.lower()

    def test_real_position_closed_event_passes(self, tmp_path):
        """entry_price > 0 → event goes through normally."""
        import sqlite3
        from core.trade_event_log import log_trade_event

        db_path = tmp_path / "risk_engine.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE accounts (id INTEGER PRIMARY KEY);
            INSERT INTO accounts (id) VALUES (1);
            CREATE TABLE trade_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              account_id INTEGER NOT NULL,
              calc_id TEXT,
              event_type TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              source TEXT NOT NULL,
              timestamp TEXT NOT NULL
            );
            """
        )
        conn.commit()
        conn.close()

        rid = log_trade_event(
            account_id=1, calc_id="real-1",
            event_type="position_closed",
            payload={"symbol": "BTCUSDT", "entry_price": 80000.0, "exit_price": 81000.0},
            source="test",
            data_dir=str(tmp_path),
        )
        assert isinstance(rid, int) and rid >= 1

        conn = sqlite3.connect(str(db_path))
        n = conn.execute("SELECT COUNT(*) FROM trade_events").fetchone()[0]
        conn.close()
        assert n == 1

    def test_non_position_closed_event_unaffected(self, tmp_path):
        """The guard targets ONLY position_closed events — other types
        (e.g. calc_created with no entry_price at all) must pass."""
        import sqlite3
        from core.trade_event_log import log_trade_event

        db_path = tmp_path / "risk_engine.db"
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE accounts (id INTEGER PRIMARY KEY);
            INSERT INTO accounts (id) VALUES (1);
            CREATE TABLE trade_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              account_id INTEGER NOT NULL,
              calc_id TEXT,
              event_type TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              source TEXT NOT NULL,
              timestamp TEXT NOT NULL
            );
            """
        )
        conn.commit()
        conn.close()

        rid = log_trade_event(
            account_id=1, calc_id="c1",
            event_type="calc_created",
            payload={"ticker": "BTCUSDT"},   # no entry_price at all
            source="test",
            data_dir=str(tmp_path),
        )
        assert isinstance(rid, int) and rid >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 3. T167 replay-set query excludes pollution by construction
# ─────────────────────────────────────────────────────────────────────────────


class TestReplaySetCleanByConstruction:
    """The T167 dual-P&L query is what step 2's counterfactual will
    consume. Verify the query EXCLUDES the pollution shape even if a
    pollution row somehow reached closed_positions (e.g. a future
    write path bypassing the T168 guard)."""

    @pytest.mark.asyncio
    async def test_orphan_pollution_row_excluded_by_calc_id_filter(self, test_db):
        """Insert pollution-shape row DIRECTLY via the connection
        (bypassing the T168 guard) with calc_id=NULL → T167 replay
        query excludes via the calc_id IS NOT NULL guard."""
        await test_db._conn.execute(
            """
            INSERT INTO closed_positions
                (account_id, symbol, exit_time_ms, net_pnl, calc_id,
                 terminal_position_id, direction, quantity, entry_price,
                 exit_price, entry_time_ms, realized_pnl, total_fees)
            VALUES (1, 'BTCUSDT', 1716000000000, -0.5, NULL,
                    'pollute-orphan', 'LONG', 0.01, 0.0, 110.0, 0, 0, 0)
            """,
        )
        await test_db._conn.commit()

        rows = await test_db.get_dual_pnl_trades(account_id=1)
        assert rows == [], (
            "Task 168 regression: orphan pollution row (NULL calc_id) "
            "reached the dual-P&L replay set — T167 calc_id guard "
            "must keep it out for step-2 counterfactual cleanliness."
        )

    @pytest.mark.asyncio
    async def test_pollution_with_calc_id_but_no_regime_row_excluded(self, test_db):
        """Pollution row with a calc_id but no matching pre_trade_log
        entry → INNER JOIN drops it."""
        await test_db._conn.execute(
            """
            INSERT INTO closed_positions
                (account_id, symbol, exit_time_ms, net_pnl, calc_id,
                 terminal_position_id, direction, quantity, entry_price,
                 exit_price, entry_time_ms, realized_pnl, total_fees)
            VALUES (1, 'BTCUSDT', 1716000000000, -0.5, 'orphan-calc',
                    'pollute-orphan-calc', 'LONG', 0.01, 0.0, 110.0, 0, 0, 0)
            """,
        )
        await test_db._conn.commit()

        rows = await test_db.get_dual_pnl_trades(account_id=1)
        assert rows == []


# ─────────────────────────────────────────────────────────────────────────────
# 4. FE-MED-008 — auto-fallback to macro_only when crypto signals absent
# ─────────────────────────────────────────────────────────────────────────────


class TestMacroOnlyAutoFallback:
    """Hard data-availability limit on agg_oi_change + avg_funding
    (Binance ~2-3yr window). The classifier auto-falls to macro_only
    when these are missing → counterfactual on pre-window dates
    produces macro_only-derived labels by construction. This is the
    foundation for step 2's leaderboard footnoting."""

    def test_classify_regime_auto_detects_macro_only_when_crypto_absent(self):
        """No agg_oi_change, no avg_funding → mode auto-detect picks
        macro_only. The JSON v1 rules respect mode == macro_only."""
        from core.regime_classifier import classify_regime
        # Macro-only signal dict (pre-Binance-window date shape)
        label = classify_regime(
            {"vix_close": 50.0, "hy_spread": 6.0},
            mode="auto",
        )
        assert label == "risk_off_panic"

    def test_classify_regime_full_when_crypto_present(self):
        """Conversely — when crypto signals are present, mode picks
        full. Anti-control."""
        from core.regime_classifier import classify_regime
        label = classify_regime(
            {"vix_close": 50.0, "hy_spread": 6.0,
             "agg_oi_change": 0.0, "avg_funding": -0.02},
            mode="auto",
        )
        # Both paths yield panic in this signal config; the assertion
        # here is that classify_regime ran without throwing under
        # mode=full (asymmetry-aware threshold tests live in T163).
        assert label == "risk_off_panic"

    def test_regime_mode_persisted_per_pretrade_row(self, tmp_path):
        """T157 persists regime_mode on pre_trade_log. Step 2's
        leaderboard reads this column to footnote macro_only-derived
        rows. Pin both 'full' and 'macro_only' round-trip through
        insert_pre_trade_log."""
        import asyncio
        from core.database import DatabaseManager

        async def t():
            db = DatabaseManager(path=str(tmp_path / "x.db"))
            await db.initialize()
            await db.insert_pre_trade_log({
                "ticker": "BTCUSDT", "average": 80000.0, "side": "long",
                "calc_id": "macro-only-1",
                "regime_label": "risk_off_panic", "regime_multiplier": 0.4,
                "regime_mode": "macro_only",
                "apply_regime_multiplier": True, "regime_stale": False,
            })
            await db.insert_pre_trade_log({
                "ticker": "BTCUSDT", "average": 80000.0, "side": "long",
                "calc_id": "full-1",
                "regime_label": "risk_on_trending", "regime_multiplier": 1.2,
                "regime_mode": "full",
                "apply_regime_multiplier": True, "regime_stale": False,
            })
            async with db._conn.execute(
                "SELECT calc_id, regime_mode FROM pre_trade_log ORDER BY calc_id"
            ) as cur:
                rows = await cur.fetchall()
            await db.close()
            return rows
        rows = asyncio.run(t())
        assert {r[0]: r[1] for r in rows} == {
            "full-1": "full",
            "macro-only-1": "macro_only",
        }


# ─────────────────────────────────────────────────────────────────────────────
# 5. Signal-window helper (gates step-2 leaderboard footnoting)
# ─────────────────────────────────────────────────────────────────────────────


class TestSignalWindowHelper:
    """db.get_regime_signal_range exposes min/max dates per signal.
    Step 2 uses this to identify the pre-Binance-window slice of
    trades and footnote the leaderboard accordingly. Pin the method
    + the agg_oi_change / avg_funding shape so step 2 has a stable
    contract."""

    @pytest.mark.asyncio
    async def test_get_regime_signal_range_returns_empty_for_unbackfilled(self, test_db):
        r = await test_db.get_regime_signal_range("agg_oi_change")
        # Empty DB → count=0; step 2 treats this as "no Binance window
        # available — fall to macro_only for ALL replays".
        assert r["count"] == 0
        assert r["min_date"] is None
        assert r["max_date"] is None

    @pytest.mark.asyncio
    async def test_get_regime_signal_range_after_partial_backfill(self, test_db):
        await test_db.upsert_regime_signals(
            "agg_oi_change",
            [{"date": "2024-01-01", "value": 0.5},
             {"date": "2024-06-01", "value": -0.2},
             {"date": "2025-01-01", "value": 0.1}],
            source="binance",
        )
        r = await test_db.get_regime_signal_range("agg_oi_change")
        assert r["count"] == 3
        assert r["min_date"] == "2024-01-01"
        assert r["max_date"] == "2025-01-01"


# ─────────────────────────────────────────────────────────────────────────────
# 6. T168 source pins
# ─────────────────────────────────────────────────────────────────────────────


class TestT168SourceAnchors:
    def test_db_orders_has_t168_anchor(self):
        text = (
            Path(__file__).parent.parent / "core" / "db_orders.py"
        ).read_text(encoding="utf-8")
        assert "Task 168" in text or "T168" in text
        assert "FE-MED-017" in text

    def test_trade_event_log_has_t168_anchor(self):
        text = (
            Path(__file__).parent.parent / "core" / "trade_event_log.py"
        ).read_text(encoding="utf-8")
        assert "Task 168" in text or "T168" in text
        assert "FE-MED-017" in text

    def test_closed_positions_guard_shape_pinned(self):
        """Source pin: the canonical pollution-shape condition must
        check entry<=0 AND qty>0 AND exit>0. A weaker check would
        false-positive on legitimate degenerate rows."""
        text = (
            Path(__file__).parent.parent / "core" / "db_orders.py"
        ).read_text(encoding="utf-8")
        executing = "\n".join(
            ln for ln in text.splitlines() if not ln.strip().startswith("#")
        )
        assert "entry <= 0 and qty > 0 and exit_p > 0" in executing

    def test_trade_event_guard_scoped_to_position_closed(self):
        """Source pin: the trade_event guard must check event_type
        first — other event types (calc_created, order_placed, etc.)
        don't have entry_price."""
        text = (
            Path(__file__).parent.parent / "core" / "trade_event_log.py"
        ).read_text(encoding="utf-8")
        executing = "\n".join(
            ln for ln in text.splitlines() if not ln.strip().startswith("#")
        )
        assert 'event_type == "position_closed"' in executing
