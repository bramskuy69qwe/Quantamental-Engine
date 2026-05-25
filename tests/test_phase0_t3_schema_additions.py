"""
Phase 0 Task 3 (P0.T3) tests — pre_trade_log + accounts column additions.

Verifies:

  1. All 15 new pre_trade_log columns exist after initialize() per
     spec §3.2 (status, window_seconds, operator_id,
     superseded_by_calc_id, cancelled_reason, planned_size,
     overridden_size, planned_tp, overridden_tp, planned_sl,
     overridden_sl, tp_levels, filled_pct, tags, lifecycle_id).
     account_id was added in v1.3 migration — not P0.T3 scope.
  2. accounts.config_json column exists per spec §3.2.
  3. lifecycle_id index on pre_trade_log per spec §3.5.
  4. Migration idempotent — initialize() twice produces same schema.
  5. Existing rows survive migration with NULL defaults on new columns
     (no data loss, no silent default backfill).
  6. New rows can write all new fields end-to-end via raw SQL
     (Phase 1+ matcher will add typed helpers; this tests the column
     types accept the spec-documented values).

Run: pytest tests/test_phase0_t3_schema_additions.py -v
"""
from __future__ import annotations

import json
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


P0_T3_PRETRADE_COLS = {
    "status", "window_seconds", "operator_id", "superseded_by_calc_id",
    "cancelled_reason", "planned_size", "overridden_size", "planned_tp",
    "overridden_tp", "planned_sl", "overridden_sl", "tp_levels",
    "filled_pct", "tags", "lifecycle_id",
}


# ── 1. Columns exist ──────────────────────────────────────────────────


class TestPreTradeLogColumns:
    @pytest.mark.asyncio
    async def test_all_15_new_columns_present(self, db):
        async with db._conn.execute("PRAGMA table_info(pre_trade_log)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        missing = P0_T3_PRETRADE_COLS - cols
        assert not missing, f"missing columns: {missing}"

    @pytest.mark.asyncio
    async def test_column_types_match_spec(self, db):
        async with db._conn.execute("PRAGMA table_info(pre_trade_log)") as cur:
            col_types = {row[1]: row[2] for row in await cur.fetchall()}
        # Type expectations from spec §3.2
        text_cols = {
            "status", "operator_id", "superseded_by_calc_id",
            "cancelled_reason", "tp_levels", "tags", "lifecycle_id",
        }
        int_cols = {"window_seconds"}
        real_cols = {
            "planned_size", "overridden_size", "planned_tp", "overridden_tp",
            "planned_sl", "overridden_sl", "filled_pct",
        }
        for c in text_cols:
            assert col_types[c] == "TEXT", f"{c} expected TEXT, got {col_types[c]}"
        for c in int_cols:
            assert col_types[c] == "INTEGER", f"{c} expected INTEGER, got {col_types[c]}"
        for c in real_cols:
            assert col_types[c] == "REAL", f"{c} expected REAL, got {col_types[c]}"


class TestAccountsConfigJson:
    @pytest.mark.asyncio
    async def test_config_json_column_present(self, db):
        async with db._conn.execute("PRAGMA table_info(accounts)") as cur:
            cols = {row[1]: row[2] for row in await cur.fetchall()}
        assert "config_json" in cols
        assert cols["config_json"] == "TEXT"


# ── 2. Lifecycle_id index per spec §3.5 ───────────────────────────────


class TestLifecycleIndex:
    @pytest.mark.asyncio
    async def test_pretrade_lifecycle_index_present(self, db):
        async with db._conn.execute(
            "PRAGMA index_list(pre_trade_log)"
        ) as cur:
            idxs = {row[1] for row in await cur.fetchall()}
        assert "idx_pretrade_lifecycle" in idxs


# ── 3. Migration idempotence ──────────────────────────────────────────


class TestMigrationIdempotent:
    @pytest.mark.asyncio
    async def test_re_initialize_does_not_error(self, db):
        # initialize() ran once via the fixture. Calling again should
        # be a no-op (existing migrations swallow "duplicate column
        # name" errors per the loop's except handler).
        await db.initialize()

        # Re-verify columns still present after the re-run.
        async with db._conn.execute("PRAGMA table_info(pre_trade_log)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        for c in P0_T3_PRETRADE_COLS:
            assert c in cols


# ── 4. Pre-existing rows survive migration with NULL defaults ─────────


class TestExistingRowsPreserved:
    @pytest.mark.asyncio
    async def test_existing_row_gets_null_defaults(self, db):
        # Insert a row using only legacy columns (simulates pre-P0.T3
        # data). All P0.T3 columns should be NULL on this row.
        await db._conn.execute(
            "INSERT INTO pre_trade_log "
            "(timestamp, ticker, account_id) VALUES (?, ?, ?)",
            ("2026-01-01T00:00:00Z", "BTCUSDT", 1),
        )
        await db._conn.commit()

        async with db._conn.execute(
            "SELECT status, window_seconds, operator_id, "
            "superseded_by_calc_id, cancelled_reason, planned_size, "
            "overridden_size, planned_tp, overridden_tp, planned_sl, "
            "overridden_sl, tp_levels, filled_pct, tags, lifecycle_id "
            "FROM pre_trade_log WHERE ticker = ?",
            ("BTCUSDT",),
        ) as cur:
            row = await cur.fetchone()

        # Every P0.T3 column defaults to NULL — no silent backfill.
        assert all(v is None for v in row), (
            f"unexpected non-NULL P0.T3 column on legacy row: {dict(zip(P0_T3_PRETRADE_COLS, row))}"
        )


# ── 5. New rows can write all new fields end-to-end ───────────────────


class TestWriteAllNewFields:
    @pytest.mark.asyncio
    async def test_round_trip_with_all_p0t3_fields_set(self, db):
        # Spec-shaped values for each new column.
        tp_levels_json = json.dumps([
            {"price": 64500.0, "size_pct": 50},
            {"price": 65000.0, "size_pct": 30},
            {"price": 65500.0, "size_pct": 20},
        ])
        tags_json = json.dumps(["momentum", "earnings_window"])
        await db._conn.execute(
            "INSERT INTO pre_trade_log "
            "(timestamp, ticker, account_id, calc_id, status, "
            " window_seconds, operator_id, superseded_by_calc_id, "
            " cancelled_reason, planned_size, overridden_size, "
            " planned_tp, overridden_tp, planned_sl, overridden_sl, "
            " tp_levels, filled_pct, tags, lifecycle_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2026-05-26T12:00:00Z", "BTCUSDT", 1, "calc-abc",
                "active", 300, "op-alice", None,
                None, 0.5, 0.5,
                64500.0, 64500.0, 63500.0, 63500.0,
                tp_levels_json, None, tags_json, None,
            ),
        )
        await db._conn.commit()

        async with db._conn.execute(
            "SELECT status, window_seconds, operator_id, planned_size, "
            "overridden_size, planned_tp, overridden_tp, planned_sl, "
            "overridden_sl, tp_levels, tags, lifecycle_id "
            "FROM pre_trade_log WHERE calc_id = ?",
            ("calc-abc",),
        ) as cur:
            row = await cur.fetchone()

        (status, window_seconds, operator_id, planned_size,
         overridden_size, planned_tp, overridden_tp, planned_sl,
         overridden_sl, tp_levels, tags, lifecycle_id) = row

        assert status == "active"
        assert window_seconds == 300
        assert operator_id == "op-alice"
        assert planned_size == pytest.approx(0.5)
        assert overridden_size == pytest.approx(0.5)
        assert planned_tp == pytest.approx(64500.0)
        assert overridden_tp == pytest.approx(64500.0)
        assert planned_sl == pytest.approx(63500.0)
        assert overridden_sl == pytest.approx(63500.0)
        # JSON columns are stored as TEXT — round-trip via json.loads.
        parsed_tp_levels = json.loads(tp_levels)
        assert len(parsed_tp_levels) == 3
        assert parsed_tp_levels[0]["price"] == 64500.0
        assert json.loads(tags) == ["momentum", "earnings_window"]
        assert lifecycle_id is None   # set later by Phase 2.1

    @pytest.mark.asyncio
    async def test_config_json_round_trip_on_accounts(self, db):
        # Spec §3.3 schema.
        cfg = {
            "window_seconds": 300,
            "clock_skew_tolerance_sec": 10,
            "entry_tolerance_pct": 0.25,
            "snapshot_drift_tolerance_pct": 0.5,
            "deviation_thresholds": {"yellow_pct": 5, "red_pct": 15},
            "size_deviation_threshold_pct": 10,
            "notification_subscriptions": {
                "calc_expired": True,
                "position_liquidated": True,
                "position_size_drift": True,
                "duplicate_order_detected": True,
                "near_replacement_match": True,
            },
        }
        await db._conn.execute(
            "INSERT INTO accounts (id, name, exchange, market_type, "
            " api_key_enc, api_secret_enc, is_active, created_at, "
            " config_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                42, "Test Account", "binance", "future",
                "stub", "stub", 1,
                "2026-05-26T12:00:00Z",
                json.dumps(cfg),
            ),
        )
        await db._conn.commit()

        async with db._conn.execute(
            "SELECT config_json FROM accounts WHERE id = ?",
            (42,),
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        parsed = json.loads(row[0])
        assert parsed["window_seconds"] == 300
        assert parsed["entry_tolerance_pct"] == 0.25
        assert parsed["snapshot_drift_tolerance_pct"] == 0.5
        assert parsed["notification_subscriptions"]["calc_expired"] is True

    @pytest.mark.asyncio
    async def test_lifecycle_id_set_after_creation_via_update(self, db):
        # Phase 2.1: lifecycle_id is back-filled when the calc first
        # contributes to a position. Simulate with a separate UPDATE.
        await db._conn.execute(
            "INSERT INTO pre_trade_log "
            "(timestamp, ticker, account_id, calc_id, status) "
            "VALUES (?, ?, ?, ?, ?)",
            ("2026-05-26T12:00:00Z", "BTCUSDT", 1, "calc-life", "matched"),
        )
        await db._conn.commit()
        await db._conn.execute(
            "UPDATE pre_trade_log SET lifecycle_id = ? WHERE calc_id = ?",
            ("uuid-aaaa", "calc-life"),
        )
        await db._conn.commit()

        async with db._conn.execute(
            "SELECT lifecycle_id FROM pre_trade_log WHERE calc_id = ?",
            ("calc-life",),
        ) as cur:
            row = await cur.fetchone()
        assert row[0] == "uuid-aaaa"
