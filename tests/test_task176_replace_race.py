"""
Task 176 regression tests — INSERT OR REPLACE preserves reconciler columns.

Bug shape (operator-reported via T175 investigation):
  closed_positions uses `INSERT OR REPLACE`. The column list previously
  omitted `backfill_completed`, so any REPLACE wiped the reconciler's
  flag back to 0. Worse, callers that passed mfe=0/mae=0 (the real-time
  close-row builder) wiped the reconciler's computed MFE/MAE values too.

  Multi-fill closes that triggered the close-row builder twice could
  race the reconciler:
    1. Fill #1 arrives → close-row built with partial data, exit_time=t1
       → reconciler computes MFE over [entry, t1], sets backfill_completed=1
    2. Fill #2 arrives → close-row built again → INSERT OR REPLACE
       wipes mfe/mae/backfill_completed back to 0
    3. Reconciler may or may not re-pick up before the operator views.

  The visible symptom was MFE values BELOW the math floor of |gross_pnl|
  (T175 caveat: the floor itself bounds the under-reporting, but T176
  fixes the underlying race).

T176 fix:
  In insert_closed_position, READ the existing row's (mfe, mae,
  backfill_completed) before re-inserting. If backfill_completed=1 in
  the existing row, the reconciler ran and its values are authoritative
  — preserve them. Otherwise use the caller-supplied values (defaults
  0 for real-time path; exchange_history backfill provides them).

What this file pins:
  - REPLACE of a backfilled row preserves its mfe/mae/backfill_completed.
  - REPLACE of an UNbackfilled row uses caller-supplied values.
  - First INSERT (no existing row) uses caller-supplied values.
  - aggTrades trailing buffer widened from 1s → 5s (source pin).

Run: pytest tests/test_task176_replace_race.py -v
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


def _close_row(**overrides) -> dict:
    """A canonical real-fill close row."""
    base = {
        "account_id":           1,
        "exchange_position_id": "x123",
        "terminal_position_id": "term-abc",
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
        "calc_id":              "calc-1",
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# 1. T176 — REPLACE race preservation
# ─────────────────────────────────────────────────────────────────────────────


class TestPreserveReconcilerColumns:
    """The load-bearing T176 invariant: when a row is replaced and the
    pre-replace row had backfill_completed=1, the reconciler's values
    must survive the REPLACE."""

    @pytest.mark.asyncio
    async def test_replace_preserves_backfilled_mfe_mae(self, test_db):
        # 1. Initial insert (real-time close path, no mfe/mae)
        await test_db.insert_closed_position(_close_row())

        # 2. Reconciler runs — sets mfe/mae/backfill_completed=1
        async with test_db._conn.execute(
            "SELECT id FROM closed_positions LIMIT 1"
        ) as cur:
            row_id = (await cur.fetchone())[0]
        await test_db.update_closed_position_mfe_mae(row_id, mfe=25.0, mae=-3.5)

        # Verify reconciler state
        async with test_db._conn.execute(
            "SELECT mfe, mae, backfill_completed FROM closed_positions"
        ) as cur:
            r = await cur.fetchone()
        assert r["mfe"] == 25.0
        assert r["mae"] == -3.5
        assert r["backfill_completed"] == 1

        # 3. Real-time close-row builder fires AGAIN (e.g., late fill arrives).
        # Same UNIQUE key — triggers INSERT OR REPLACE. Caller passes
        # default mfe=0, mae=0 (typical real-time path).
        await test_db.insert_closed_position(_close_row(
            exit_price=81100.0,  # late fill changed the VWAP
            net_pnl=10.0,
        ))

        # T176 assertion: reconciler's values survived.
        async with test_db._conn.execute(
            "SELECT mfe, mae, backfill_completed, exit_price "
            "FROM closed_positions"
        ) as cur:
            r = await cur.fetchone()
        assert r["mfe"] == 25.0, (
            "T176 regression: REPLACE wiped reconciler's MFE — the "
            "partial-fill race-with-reconciler bug is back"
        )
        assert r["mae"] == -3.5, "T176 regression: REPLACE wiped MAE"
        assert r["backfill_completed"] == 1, (
            "T176 regression: REPLACE wiped backfill_completed flag — "
            "reconciler will recompute (over potentially the same data) "
            "wasting an API call, OR worse, recompute over a partial "
            "window if the row gets re-replaced before reconciler runs"
        )
        # Confirm the close-row-builder-owned columns DID update
        assert r["exit_price"] == 81100.0

    @pytest.mark.asyncio
    async def test_replace_unbackfilled_row_uses_new_values(self, test_db):
        """Anti-regression: when the existing row has backfill_completed=0
        (reconciler hasn't run yet), the new caller's mfe/mae values win.
        This is the legitimate "exchange_history backfill provides values"
        path that we don't want to break."""
        # 1. Initial insert with backfill=0 (caller-default mfe=0/mae=0)
        await test_db.insert_closed_position(_close_row())

        # 2. Second call provides explicit mfe/mae (e.g., exchange_history
        # backfill path at db_orders.py:976-977). Same UNIQUE key.
        await test_db.insert_closed_position(_close_row(
            mfe=10.0,
            mae=-2.0,
        ))

        # The new mfe/mae values should land — existing row wasn't backfilled
        async with test_db._conn.execute(
            "SELECT mfe, mae, backfill_completed FROM closed_positions"
        ) as cur:
            r = await cur.fetchone()
        assert r["mfe"] == 10.0
        assert r["mae"] == -2.0
        assert r["backfill_completed"] == 0  # still not via the reconciler

    @pytest.mark.asyncio
    async def test_first_insert_no_existing_row_uses_caller_values(self, test_db):
        """First-time INSERT (no row exists for this key yet) — caller's
        values land as-is. T176 read-before-write doesn't change first-
        time behavior."""
        await test_db.insert_closed_position(_close_row(
            mfe=15.5,
            mae=-7.25,
        ))
        async with test_db._conn.execute(
            "SELECT mfe, mae, backfill_completed FROM closed_positions"
        ) as cur:
            r = await cur.fetchone()
        assert r["mfe"] == 15.5
        assert r["mae"] == -7.25
        assert r["backfill_completed"] == 0

    @pytest.mark.asyncio
    async def test_three_way_race_sequence_correctness(self, test_db):
        """End-to-end of the race scenario:
          1. real-time close → insert (mfe=0, mae=0, backfill=0)
          2. reconciler → set mfe=25, mae=-3.5, backfill=1
          3. late real-time replace → reconciler values must survive
          4. another reconciler pass would NOT pick up this row
             (backfill=1 → excluded by get_uncalculated_closed_positions)
        """
        # Step 1
        await test_db.insert_closed_position(_close_row())
        async with test_db._conn.execute(
            "SELECT id FROM closed_positions LIMIT 1"
        ) as cur:
            row_id = (await cur.fetchone())[0]

        # Step 2
        await test_db.update_closed_position_mfe_mae(row_id, 25.0, -3.5)

        # Step 3
        await test_db.insert_closed_position(_close_row(
            exit_price=81100.0,
        ))

        # Step 4 — reconciler query should now SKIP this row
        rows = await test_db.get_uncalculated_closed_positions(account_id=1)
        assert len(rows) == 0, (
            "T176 regression: the reconciler would re-pick up a row "
            "that REPLACE wiped — reconciler thrashing"
        )


class TestPreserveLifecycleId:
    """T232 (holistic Phase-2 audit): the same INSERT OR REPLACE that
    motivated T176 also wipes closed_positions.lifecycle_id (a P0.T4
    column omitted from the INSERT list) on any recompute. The Phase-2
    backfill stamps lifecycle_id on historical closed_positions today,
    so a re-run of exchange_history_backfill (same UNIQUE key) would
    REPLACE-wipe it to NULL without preservation. Pin it like mfe/mae."""

    @pytest.mark.asyncio
    async def test_replace_preserves_stamped_lifecycle_id(self, test_db):
        # 1. Initial close-row insert (real-time path supplies no lifecycle).
        await test_db.insert_closed_position(_close_row())
        # 2. Backfill stamps a lifecycle_id (mirrors backfill_calc_linkage).
        await test_db._conn.execute(
            "UPDATE closed_positions SET lifecycle_id = ? "
            "WHERE terminal_position_id = ?",
            ("life-uuid-1", "term-abc"),
        )
        await test_db._conn.commit()
        # 3. A recompute REPLACEs the row on the same UNIQUE key, with no
        #    lifecycle_id supplied (the forward close-row builder's shape).
        await test_db.insert_closed_position(_close_row(exit_price=81100.0))
        # T232 assertion: the stamped lifecycle_id survived the REPLACE.
        async with test_db._conn.execute(
            "SELECT lifecycle_id, exit_price FROM closed_positions"
        ) as cur:
            r = await cur.fetchone()
        assert r["lifecycle_id"] == "life-uuid-1", (
            "T232 regression: INSERT OR REPLACE wiped a stamped "
            "closed_positions.lifecycle_id back to NULL (T176-class)"
        )
        assert r["exit_price"] == 81100.0   # close-row-owned column still updates

    @pytest.mark.asyncio
    async def test_caller_supplied_lifecycle_wins_on_first_insert(self, test_db):
        # When the caller (future P2.T6 seal) supplies lifecycle_id, it is
        # written; a later no-lifecycle REPLACE preserves it.
        await test_db.insert_closed_position(_close_row(lifecycle_id="seal-1"))
        await test_db.insert_closed_position(_close_row(exit_price=81200.0))
        async with test_db._conn.execute(
            "SELECT lifecycle_id FROM closed_positions"
        ) as cur:
            assert (await cur.fetchone())["lifecycle_id"] == "seal-1"


# ─────────────────────────────────────────────────────────────────────────────
# 2. T176 — aggTrades trailing buffer widened (Fix B)
# ─────────────────────────────────────────────────────────────────────────────


class TestAggTradesBufferWidened:
    """Source pin: the _BUF constant in binance/rest_adapter.py
    fetch_price_extremes is now 5_000ms (was 1_000ms). Catches the
    case where clock skew between Quantower-recorded fill time and
    Binance's market clock leaves the actual close tick outside the
    1s buffer."""

    def test_buf_is_at_least_5_seconds(self):
        src = (
            Path(__file__).parent.parent
            / "core" / "adapters" / "binance" / "rest_adapter.py"
        ).read_text(encoding="utf-8")
        executing = "\n".join(
            ln for ln in src.splitlines() if not ln.strip().startswith("#")
        )
        assert "_BUF = 5_000" in executing or "_BUF = 5000" in executing, (
            "T176 regression: aggTrades trailing buffer should be >= 5s "
            "to absorb Quantower/Binance clock skew. Smaller buffers "
            "(prior 1s) sometimes missed the actual close tick."
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. T176 source anchors
# ─────────────────────────────────────────────────────────────────────────────


class TestT176SourceAnchors:
    def test_db_orders_has_t176_anchor(self):
        src = (
            Path(__file__).parent.parent / "core" / "db_orders.py"
        ).read_text(encoding="utf-8")
        assert "T176" in src or "Task 176" in src

    def test_db_orders_includes_backfill_completed_in_insert_columns(self):
        """Source pin: the INSERT OR REPLACE column list must include
        `backfill_completed` so the value lands explicitly (and gets
        preserved when we pass the existing-row value)."""
        src = (
            Path(__file__).parent.parent / "core" / "db_orders.py"
        ).read_text(encoding="utf-8")
        # Inside the canonical insert_closed_position SQL
        assert "backfill_completed, hold_time_ms" in src, (
            "T176 regression: backfill_completed dropped from the INSERT "
            "column list — REPLACEs will default it back to 0"
        )

    def test_db_orders_reads_existing_before_replace(self):
        """Source pin: the read-before-write pattern must be present."""
        src = (
            Path(__file__).parent.parent / "core" / "db_orders.py"
        ).read_text(encoding="utf-8")
        executing = "\n".join(
            ln for ln in src.splitlines() if not ln.strip().startswith("#")
        )
        # The preserved_* variables come from a SELECT before the INSERT.
        assert "preserved_mfe" in executing
        assert "preserved_mae" in executing
        assert "preserved_backfill" in executing
        # And the SELECT references the right keys
        assert "WHERE account_id = ? AND terminal_position_id = ?" in src
