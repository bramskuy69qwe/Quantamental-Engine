"""
Task 168 regression tests — pollution-shape write-time guards.

T170 rewind: T168 originally also covered FE-MED-008 macro_only auto-
fallback + signal-window helper + the T167 replay-set construction
pins. Those were regime-infra-coupled and rolled back along with
T163-T169 in T170 (see audit doc T170 rollback section). What survives
is the FE-MED-017 pollution guard at the two canonical write paths —
purely defense-in-depth, independent of regime work.

Background:
  Operator audit-01 flagged 278 BTCUSDT `position_closed` rows in
  trade_events with `entry_price: 0.0`. Operator-confirmed: no real
  BTCUSDT trading occurred in the relevant period — these are pre-prod
  test fixtures, not corrupted live data. Pollution shape:
  `entry_price <= 0 AND quantity > 0 AND exit_price > 0` — impossible
  from any real fill path. Guards added at both write paths so future
  pollution sources can't reach either surface.

What this file pins:
  • Pollution-shape closed_positions writes refused; non-pollution
    writes still go through.
  • Pollution-shape trade_event 'position_closed' refused; other
    event types unaffected.
  • Refusal logs.warning so the operator sees rejected writes.
  • Source pins for both T168 guards.

Run: pytest tests/test_task168_pollution_guards.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


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
        entry_price=0.0,
        calc_id=None,
    )
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# 1. FE-MED-017 — write-time pollution guard at insert_closed_position
# ─────────────────────────────────────────────────────────────────────────────


class TestClosedPositionsPollutionGuard:
    @pytest.mark.asyncio
    async def test_pollution_shape_row_refused(self, test_db, caplog):
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
        """quantity=0 + entry=0 is a degenerate row but NOT the
        pollution shape — guard intentionally doesn't fire."""
        await test_db.insert_closed_position(_real_close_row(
            terminal_position_id="t-zero-qty",
            entry_price=0.0, quantity=0, exit_price=0.0,
        ))
        async with test_db._conn.execute(
            "SELECT COUNT(*) FROM closed_positions"
        ) as cur:
            n = (await cur.fetchone())[0]
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
        import logging
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

        caplog.set_level(logging.WARNING, logger="trade_event_log")
        result = log_trade_event(
            account_id=1, calc_id="any",
            event_type="position_closed",
            payload={"symbol": "BTCUSDT", "entry_price": 0.0, "exit_price": 110.0},
            source="test",
            data_dir=str(tmp_path),
        )
        assert result == -1

        conn = sqlite3.connect(str(db_path))
        n = conn.execute("SELECT COUNT(*) FROM trade_events").fetchone()[0]
        conn.close()
        assert n == 0

        joined = " ".join(r.message for r in caplog.records)
        assert "FE-MED-017" in joined
        assert "pollution" in joined.lower()

    def test_real_position_closed_event_passes(self, tmp_path):
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
            payload={"ticker": "BTCUSDT"},
            source="test",
            data_dir=str(tmp_path),
        )
        assert isinstance(rid, int) and rid >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 3. Source pins
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
        text = (
            Path(__file__).parent.parent / "core" / "db_orders.py"
        ).read_text(encoding="utf-8")
        executing = "\n".join(
            ln for ln in text.splitlines() if not ln.strip().startswith("#")
        )
        assert "entry <= 0 and qty > 0 and exit_p > 0" in executing

    def test_trade_event_guard_scoped_to_position_closed(self):
        text = (
            Path(__file__).parent.parent / "core" / "trade_event_log.py"
        ).read_text(encoding="utf-8")
        executing = "\n".join(
            ln for ln in text.splitlines() if not ln.strip().startswith("#")
        )
        assert 'event_type == "position_closed"' in executing
