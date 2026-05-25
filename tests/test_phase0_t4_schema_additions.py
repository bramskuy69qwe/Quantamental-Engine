"""
Phase 0 Task 4 (P0.T4) tests — orders + closed_positions column additions.

Verifies:

  1. All 6 new orders columns exist with correct types per spec §3.2
     (link_status, operator_id, cancel_reason_category,
     cancel_reason_raw, cancel_ts_ms, lifecycle_id).
  2. All 16 net-new closed_positions columns exist (exit_reason,
     funding_fees, calc_id already exist from earlier migrations and
     are NOT in P0.T4 scope).
  3. lifecycle_id indexes on orders + closed_positions per spec §3.5.
  4. Migration idempotent — initialize() twice produces same schema.
  5. Existing rows survive migration with NULL defaults on new columns.
  6. End-to-end round-trip of new fields via raw SQL with spec-shaped
     values (enum strings, delta percentages, liquidation fields).

Run: pytest tests/test_phase0_t4_schema_additions.py -v
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


P0_T4_ORDERS_COLS = {
    "link_status", "operator_id", "cancel_reason_category",
    "cancel_reason_raw", "cancel_ts_ms", "lifecycle_id",
}

P0_T4_CLOSED_POS_COLS = {
    "close_note", "entry_px_delta_pct", "size_delta_pct",
    "tp_drift_pct", "sl_drift_pct", "exit_vs_target_pct",
    "realized_r", "planned_r", "hold_time_actual_ms",
    "hold_time_planned_ms", "cumulative_amendment_count",
    "liquidation_px", "bankruptcy_px", "insurance_fund_fee",
    "adl_indicator", "lifecycle_id",
}


# ── 1. orders columns ─────────────────────────────────────────────────


class TestOrdersColumns:
    @pytest.mark.asyncio
    async def test_all_6_new_columns_present(self, db):
        async with db._conn.execute("PRAGMA table_info(orders)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        missing = P0_T4_ORDERS_COLS - cols
        assert not missing, f"missing orders columns: {missing}"

    @pytest.mark.asyncio
    async def test_column_types_match_spec(self, db):
        async with db._conn.execute("PRAGMA table_info(orders)") as cur:
            col_types = {row[1]: row[2] for row in await cur.fetchall()}
        assert col_types["link_status"] == "TEXT"
        assert col_types["operator_id"] == "TEXT"
        assert col_types["cancel_reason_category"] == "TEXT"
        assert col_types["cancel_reason_raw"] == "TEXT"
        assert col_types["cancel_ts_ms"] == "INTEGER"
        assert col_types["lifecycle_id"] == "TEXT"


# ── 2. closed_positions columns ───────────────────────────────────────


class TestClosedPositionsColumns:
    @pytest.mark.asyncio
    async def test_all_16_new_columns_present(self, db):
        async with db._conn.execute(
            "PRAGMA table_info(closed_positions)"
        ) as cur:
            cols = {row[1] for row in await cur.fetchall()}
        missing = P0_T4_CLOSED_POS_COLS - cols
        assert not missing, f"missing closed_positions columns: {missing}"

    @pytest.mark.asyncio
    async def test_column_types_match_spec(self, db):
        async with db._conn.execute(
            "PRAGMA table_info(closed_positions)"
        ) as cur:
            col_types = {row[1]: row[2] for row in await cur.fetchall()}
        text_cols = {"close_note", "lifecycle_id"}
        int_cols = {
            "hold_time_actual_ms", "hold_time_planned_ms",
            "cumulative_amendment_count", "adl_indicator",
        }
        real_cols = {
            "entry_px_delta_pct", "size_delta_pct", "tp_drift_pct",
            "sl_drift_pct", "exit_vs_target_pct", "realized_r",
            "planned_r", "liquidation_px", "bankruptcy_px",
            "insurance_fund_fee",
        }
        for c in text_cols:
            assert col_types[c] == "TEXT", f"{c} expected TEXT, got {col_types[c]}"
        for c in int_cols:
            assert col_types[c] == "INTEGER", f"{c} expected INTEGER, got {col_types[c]}"
        for c in real_cols:
            assert col_types[c] == "REAL", f"{c} expected REAL, got {col_types[c]}"

    @pytest.mark.asyncio
    async def test_existing_columns_preserved(self, db):
        # Sanity: P0.T4 must NOT drop or alter existing columns.
        # exit_reason (re-mapped in P0.T5), funding_fees (repurposed),
        # calc_id (already there) must all still exist with their
        # original types.
        async with db._conn.execute(
            "PRAGMA table_info(closed_positions)"
        ) as cur:
            col_types = {row[1]: row[2] for row in await cur.fetchall()}
        assert col_types.get("exit_reason") == "TEXT"
        assert col_types.get("funding_fees") == "REAL"
        assert col_types.get("calc_id") == "TEXT"


# ── 3. lifecycle_id indexes (spec §3.5) ───────────────────────────────


class TestLifecycleIndexes:
    @pytest.mark.asyncio
    async def test_orders_lifecycle_index(self, db):
        async with db._conn.execute("PRAGMA index_list(orders)") as cur:
            idxs = {row[1] for row in await cur.fetchall()}
        assert "idx_orders_lifecycle" in idxs

    @pytest.mark.asyncio
    async def test_closed_pos_lifecycle_index(self, db):
        async with db._conn.execute(
            "PRAGMA index_list(closed_positions)"
        ) as cur:
            idxs = {row[1] for row in await cur.fetchall()}
        assert "idx_closed_pos_lifecycle" in idxs


# ── 4. Idempotence ────────────────────────────────────────────────────


class TestMigrationIdempotent:
    @pytest.mark.asyncio
    async def test_re_initialize_does_not_error(self, db):
        await db.initialize()
        async with db._conn.execute("PRAGMA table_info(orders)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        for c in P0_T4_ORDERS_COLS:
            assert c in cols
        async with db._conn.execute(
            "PRAGMA table_info(closed_positions)"
        ) as cur:
            cp_cols = {row[1] for row in await cur.fetchall()}
        for c in P0_T4_CLOSED_POS_COLS:
            assert c in cp_cols


# ── 5. Existing rows preserved with NULL defaults ────────────────────


class TestExistingRowsPreserved:
    @pytest.mark.asyncio
    async def test_legacy_order_row_null_on_new_cols(self, db):
        # Insert using only legacy columns.
        await db._conn.execute(
            "INSERT INTO orders "
            "(account_id, exchange_order_id, symbol, side, order_type, "
            " status, quantity, created_at_ms, updated_at_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "ex-1", "BTCUSDT", "BUY", "limit", "new", 1.0, 1000, 1000),
        )
        await db._conn.commit()

        async with db._conn.execute(
            "SELECT link_status, operator_id, cancel_reason_category, "
            "cancel_reason_raw, cancel_ts_ms, lifecycle_id "
            "FROM orders WHERE exchange_order_id = ?",
            ("ex-1",),
        ) as cur:
            row = await cur.fetchone()
        assert all(v is None for v in row), (
            f"unexpected non-NULL P0.T4 column on legacy order row: {row}"
        )

    @pytest.mark.asyncio
    async def test_legacy_closed_position_row_null_on_new_cols(self, db):
        # Insert using only legacy columns via the canonical helper.
        await db.insert_closed_position({
            "account_id":           1,
            "terminal_position_id": "tpid-legacy",
            "symbol":               "BTCUSDT",
            "direction":            "LONG",
            "quantity":             1.0,
            "entry_price":          80000.0,
            "exit_price":           81000.0,
            "entry_time_ms":        1000,
            "exit_time_ms":         2000,
            "realized_pnl":         1000.0,
            "source":               "binance_ws",
        })
        async with db._conn.execute(
            "SELECT close_note, entry_px_delta_pct, size_delta_pct, "
            "tp_drift_pct, sl_drift_pct, exit_vs_target_pct, "
            "realized_r, planned_r, hold_time_actual_ms, "
            "hold_time_planned_ms, cumulative_amendment_count, "
            "liquidation_px, bankruptcy_px, insurance_fund_fee, "
            "adl_indicator, lifecycle_id "
            "FROM closed_positions WHERE terminal_position_id = ?",
            ("tpid-legacy",),
        ) as cur:
            row = await cur.fetchone()
        assert all(v is None for v in row), (
            f"unexpected non-NULL P0.T4 column on legacy closed_position "
            f"row: {row}"
        )


# ── 6. End-to-end write with all new fields ──────────────────────────


class TestWriteAllNewFields:
    @pytest.mark.asyncio
    async def test_orders_round_trip_with_p0t4_fields(self, db):
        # link_status enum + cancel-reason enum per spec §3.2.
        await db._conn.execute(
            "INSERT INTO orders "
            "(account_id, exchange_order_id, symbol, side, order_type, "
            " status, quantity, created_at_ms, updated_at_ms, "
            " link_status, operator_id, cancel_reason_category, "
            " cancel_reason_raw, cancel_ts_ms, lifecycle_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1, "ex-2", "BTCUSDT", "BUY", "limit", "canceled",
                1.0, 1000, 2000,
                "UNLINKED", "op-alice", "OPERATOR",
                "manual cancel via UI", 1500, "uuid-order-1",
            ),
        )
        await db._conn.commit()

        async with db._conn.execute(
            "SELECT link_status, operator_id, cancel_reason_category, "
            "cancel_reason_raw, cancel_ts_ms, lifecycle_id "
            "FROM orders WHERE exchange_order_id = ?",
            ("ex-2",),
        ) as cur:
            row = await cur.fetchone()
        assert tuple(row) == (
            "UNLINKED", "op-alice", "OPERATOR",
            "manual cancel via UI", 1500, "uuid-order-1",
        )

    @pytest.mark.asyncio
    async def test_closed_positions_round_trip_with_p0t4_fields(self, db):
        # Insert a row that exercises every P0.T4 column with spec-
        # shaped values (signed deltas, drift percentages, liquidation
        # fields, lifecycle id).
        await db._conn.execute(
            "INSERT INTO closed_positions "
            "(account_id, terminal_position_id, symbol, direction, "
            " quantity, entry_price, exit_price, entry_time_ms, "
            " exit_time_ms, realized_pnl, source, "
            " exit_reason, close_note, entry_px_delta_pct, "
            " size_delta_pct, tp_drift_pct, sl_drift_pct, "
            " exit_vs_target_pct, realized_r, planned_r, "
            " hold_time_actual_ms, hold_time_planned_ms, "
            " cumulative_amendment_count, liquidation_px, "
            " bankruptcy_px, insurance_fund_fee, adl_indicator, "
            " lifecycle_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            " ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1, "tpid-full", "BTCUSDT", "LONG",
                1.0, 80000.0, 81500.0, 1000, 60000, 1500.0,
                "binance_ws",
                "TP_AMENDED", "TP moved up after entry spike",
                0.5, -2.0, 1.5, 0.0,
                0.8, 1.2, 1.0,
                59000, 60000, 2,
                None, None, None, 0,
                "uuid-cp-1",
            ),
        )
        await db._conn.commit()

        async with db._conn.execute(
            "SELECT exit_reason, close_note, entry_px_delta_pct, "
            "size_delta_pct, tp_drift_pct, sl_drift_pct, "
            "exit_vs_target_pct, realized_r, planned_r, "
            "hold_time_actual_ms, hold_time_planned_ms, "
            "cumulative_amendment_count, adl_indicator, lifecycle_id "
            "FROM closed_positions WHERE terminal_position_id = ?",
            ("tpid-full",),
        ) as cur:
            row = await cur.fetchone()
        (exit_reason, close_note, entry_delta, size_delta, tp_drift,
         sl_drift, exit_vs_target, realized_r, planned_r,
         hold_actual, hold_planned, amend_count, adl, lifecycle) = row

        assert exit_reason == "TP_AMENDED"
        assert close_note == "TP moved up after entry spike"
        assert entry_delta == pytest.approx(0.5)
        assert size_delta == pytest.approx(-2.0)
        assert tp_drift == pytest.approx(1.5)
        assert sl_drift == pytest.approx(0.0)
        assert exit_vs_target == pytest.approx(0.8)
        assert realized_r == pytest.approx(1.2)
        assert planned_r == pytest.approx(1.0)
        assert hold_actual == 59000
        assert hold_planned == 60000
        assert amend_count == 2
        assert adl == 0
        assert lifecycle == "uuid-cp-1"

    @pytest.mark.asyncio
    async def test_liquidation_fields_only_set_on_liquidation(self, db):
        # Spec §3.2: liquidation_px / bankruptcy_px / insurance_fund_fee
        # nullable, populated only on LIQUIDATION close.
        await db._conn.execute(
            "INSERT INTO closed_positions "
            "(account_id, terminal_position_id, symbol, direction, "
            " quantity, entry_price, exit_price, entry_time_ms, "
            " exit_time_ms, realized_pnl, source, "
            " exit_reason, liquidation_px, bankruptcy_px, "
            " insurance_fund_fee, adl_indicator) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1, "tpid-liq", "BTCUSDT", "LONG",
                1.0, 80000.0, 70000.0, 1000, 30000, -10000.0,
                "binance_ws",
                "LIQUIDATION", 70500.0, 70100.0, 50.0, 1,
            ),
        )
        await db._conn.commit()
        async with db._conn.execute(
            "SELECT liquidation_px, bankruptcy_px, insurance_fund_fee, "
            "adl_indicator FROM closed_positions WHERE terminal_position_id = ?",
            ("tpid-liq",),
        ) as cur:
            row = await cur.fetchone()
        assert tuple(row) == (70500.0, 70100.0, 50.0, 1)
