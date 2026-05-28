"""
Phase 0 Task 1 (P0.T1) tests — calc-linkage schema foundation.

Verifies:

  1. All 4 new tables exist with the expected columns + types
     (positions_calcs, order_amendments, funding_events,
     calc_match_audit). Schema reference: docs/design/calc_linkage_spec.md
     §3.1.
  2. All indexes are present, including the lifecycle_id index on
     every table carrying it (§3.5).
  3. CRUD helpers in core.db_orders.OrdersMixin work end-to-end:
     - positions_calcs: upsert is cumulative on (position_id, calc_id,
       order_id); reads by position/calc/lifecycle
     - order_amendments: immutable inserts; read by order/calc
     - funding_events: INSERT OR IGNORE deduplication on
       venue_event_id; sum-by-position helper
     - calc_match_audit: batched insert; read by order/calc with
       optional order_id filter

Run: pytest tests/test_phase0_t1_schema.py -v
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
    """Tempfile DB initialized with the full schema."""
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


async def _table_columns(db, table: str) -> dict:
    async with db._conn.execute(f"PRAGMA table_info({table})") as cur:
        return {row[1]: row[2] for row in await cur.fetchall()}


async def _table_indexes(db, table: str) -> set:
    async with db._conn.execute(f"PRAGMA index_list({table})") as cur:
        return {row[1] for row in await cur.fetchall()}


# ── 1. Schema: tables exist with correct columns ───────────────────────


class TestSchemaPositionsCalcs:
    @pytest.mark.asyncio
    async def test_columns_match_spec(self, db):
        cols = await _table_columns(db, "positions_calcs")
        expected = {
            "id", "position_id", "calc_id", "order_id", "account_id",
            "contributed_qty", "first_fill_ts", "last_fill_ts",
            "planned_size", "size_delta_pct", "planned_tp", "planned_sl",
            "lifecycle_id",
        }
        assert set(cols.keys()) == expected

    @pytest.mark.asyncio
    async def test_indexes_present(self, db):
        idx = await _table_indexes(db, "positions_calcs")
        # 5 named indexes per spec + 1 SQLite-auto for the UNIQUE.
        assert "idx_pc_position" in idx
        assert "idx_pc_calc" in idx
        assert "idx_pc_order" in idx
        assert "idx_pc_account" in idx
        assert "idx_pc_lifecycle" in idx

    @pytest.mark.asyncio
    async def test_unique_constraint_on_triple(self, db):
        # Same (position_id, calc_id, order_id) twice via raw INSERT
        # raises. (Upsert helper handles this gracefully — tested
        # separately.)
        await db._conn.execute(
            "INSERT INTO positions_calcs "
            "(position_id, calc_id, order_id, account_id, "
            " contributed_qty, first_fill_ts, last_fill_ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("pos-1", "calc-a", 100, 1, 5.0, 1000, 1000),
        )
        await db._conn.commit()
        with pytest.raises(Exception):
            await db._conn.execute(
                "INSERT INTO positions_calcs "
                "(position_id, calc_id, order_id, account_id, "
                " contributed_qty, first_fill_ts, last_fill_ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("pos-1", "calc-a", 100, 1, 99.0, 9999, 9999),
            )
            await db._conn.commit()


class TestSchemaOrderAmendments:
    @pytest.mark.asyncio
    async def test_columns_match_spec(self, db):
        cols = await _table_columns(db, "order_amendments")
        expected = {
            "id", "order_id", "calc_id", "field", "old_value",
            "new_value", "ts_ms", "operator_id", "deviation_pct",
            "lifecycle_id",
        }
        assert set(cols.keys()) == expected

    @pytest.mark.asyncio
    async def test_indexes_present(self, db):
        idx = await _table_indexes(db, "order_amendments")
        assert "idx_oa_order" in idx
        assert "idx_oa_calc" in idx
        assert "idx_oa_calc_ts" in idx
        assert "idx_oa_lifecycle" in idx


class TestSchemaFundingEvents:
    @pytest.mark.asyncio
    async def test_columns_match_spec(self, db):
        cols = await _table_columns(db, "funding_events")
        expected = {
            "id", "position_id", "calc_id", "account_id", "symbol",
            "amount", "mark_price", "funding_rate", "ts_ms",
            "venue_event_id", "lifecycle_id",
        }
        assert set(cols.keys()) == expected

    @pytest.mark.asyncio
    async def test_indexes_present(self, db):
        idx = await _table_indexes(db, "funding_events")
        assert "idx_fe_position" in idx
        assert "idx_fe_account_ts" in idx
        assert "idx_fe_lifecycle" in idx

    @pytest.mark.asyncio
    async def test_venue_event_id_unique_constraint(self, db):
        await db._conn.execute(
            "INSERT INTO funding_events "
            "(position_id, account_id, symbol, amount, ts_ms, "
            " venue_event_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (1, 1, "BTCUSDT", -0.05, 1000, "venue-evt-1"),
        )
        await db._conn.commit()
        with pytest.raises(Exception):
            await db._conn.execute(
                "INSERT INTO funding_events "
                "(position_id, account_id, symbol, amount, ts_ms, "
                " venue_event_id) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (2, 1, "ETHUSDT", -0.10, 2000, "venue-evt-1"),
            )
            await db._conn.commit()


class TestSchemaCalcMatchAudit:
    @pytest.mark.asyncio
    async def test_columns_match_spec(self, db):
        cols = await _table_columns(db, "calc_match_audit")
        expected = {
            "id", "order_id", "calc_id", "criterion", "calc_value",
            "order_value", "tolerance_used", "matched", "ts_ms",
            "winning",
        }
        assert set(cols.keys()) == expected

    @pytest.mark.asyncio
    async def test_indexes_present(self, db):
        idx = await _table_indexes(db, "calc_match_audit")
        assert "idx_cma_order" in idx
        assert "idx_cma_calc" in idx


# ── 2. positions_calcs CRUD ────────────────────────────────────────────


class TestPositionsCalcsUpsert:
    @pytest.mark.asyncio
    async def test_first_insert_creates_row(self, db):
        await db.upsert_position_calc_link({
            "position_id": "pos-1", "calc_id": "calc-a", "order_id": 100,
            "account_id": 1, "contributed_qty": 5.0,
            "first_fill_ts": 1000, "last_fill_ts": 1000,
            "planned_size": 10.0, "size_delta_pct": -50.0,
            "planned_tp": 105.0, "planned_sl": 95.0,
            "lifecycle_id": "uuid-1",
        })
        rows = await db.get_position_calc_links("pos-1")
        assert len(rows) == 1
        assert rows[0]["contributed_qty"] == pytest.approx(5.0)
        assert rows[0]["lifecycle_id"] == "uuid-1"

    @pytest.mark.asyncio
    async def test_repeated_upsert_accumulates_qty(self, db):
        # Same triple twice — qty should sum, last_fill_ts should
        # advance, first_fill_ts should stay.
        base = {
            "position_id": "pos-1", "calc_id": "calc-a", "order_id": 100,
            "account_id": 1, "planned_size": 10.0,
            "size_delta_pct": -50.0, "planned_tp": None,
            "planned_sl": None, "lifecycle_id": "uuid-1",
        }
        await db.upsert_position_calc_link({
            **base, "contributed_qty": 3.0,
            "first_fill_ts": 1000, "last_fill_ts": 1000,
        })
        await db.upsert_position_calc_link({
            **base, "contributed_qty": 4.0,
            "first_fill_ts": 2000, "last_fill_ts": 2000,
        })
        rows = await db.get_position_calc_links("pos-1")
        assert len(rows) == 1
        assert rows[0]["contributed_qty"] == pytest.approx(7.0)
        assert rows[0]["first_fill_ts"] == 1000   # preserved
        assert rows[0]["last_fill_ts"] == 2000    # advanced

    @pytest.mark.asyncio
    async def test_different_calc_for_same_position_creates_second_row(self, db):
        # Scale-in: second calc on same position should be a NEW
        # junction row.
        await db.upsert_position_calc_link({
            "position_id": "pos-1", "calc_id": "calc-a", "order_id": 100,
            "account_id": 1, "contributed_qty": 5.0,
            "first_fill_ts": 1000, "last_fill_ts": 1000,
            "planned_size": None, "size_delta_pct": None,
            "planned_tp": None, "planned_sl": None,
            "lifecycle_id": "uuid-1",
        })
        await db.upsert_position_calc_link({
            "position_id": "pos-1", "calc_id": "calc-b", "order_id": 101,
            "account_id": 1, "contributed_qty": 3.0,
            "first_fill_ts": 2000, "last_fill_ts": 2000,
            "planned_size": None, "size_delta_pct": None,
            "planned_tp": None, "planned_sl": None,
            "lifecycle_id": "uuid-1",
        })
        rows = await db.get_position_calc_links("pos-1")
        assert len(rows) == 2
        calc_ids = {r["calc_id"] for r in rows}
        assert calc_ids == {"calc-a", "calc-b"}


class TestPositionsCalcsReads:
    @pytest.mark.asyncio
    async def test_get_calc_position_links(self, db):
        # Same calc contributing to TWO positions (sequential trades).
        for i, pid in enumerate(("pos-1", "pos-2"), start=1):
            await db.upsert_position_calc_link({
                "position_id": pid, "calc_id": "calc-x", "order_id": 100 + i,
                "account_id": 1, "contributed_qty": 5.0,
                "first_fill_ts": 1000 * i, "last_fill_ts": 1000 * i,
                "planned_size": None, "size_delta_pct": None,
                "planned_tp": None, "planned_sl": None,
                "lifecycle_id": f"uuid-{i}",
            })
        rows = await db.get_calc_position_links("calc-x")
        assert len(rows) == 2
        assert {r["position_id"] for r in rows} == {"pos-1", "pos-2"}

    @pytest.mark.asyncio
    async def test_get_lifecycle_links(self, db):
        # Scale-in: two calcs, same lifecycle_id, same position.
        for calc_id in ("calc-a", "calc-b"):
            await db.upsert_position_calc_link({
                "position_id": "pos-1", "calc_id": calc_id,
                "order_id": 100 if calc_id == "calc-a" else 101,
                "account_id": 1, "contributed_qty": 5.0,
                "first_fill_ts": 1000, "last_fill_ts": 1000,
                "planned_size": None, "size_delta_pct": None,
                "planned_tp": None, "planned_sl": None,
                "lifecycle_id": "uuid-1",
            })
        rows = await db.get_lifecycle_links("uuid-1")
        assert len(rows) == 2
        assert {r["calc_id"] for r in rows} == {"calc-a", "calc-b"}

    @pytest.mark.asyncio
    async def test_get_lifecycle_links_empty_string_returns_empty(self, db):
        assert await db.get_lifecycle_links("") == []


# ── 3. order_amendments CRUD ──────────────────────────────────────────


class TestOrderAmendmentsInsertAndRead:
    @pytest.mark.asyncio
    async def test_insert_then_read(self, db):
        await db.insert_order_amendment({
            "order_id": 100, "calc_id": "calc-a", "field": "tp_price",
            "old_value": 105.0, "new_value": 110.0, "ts_ms": 1000,
            "operator_id": "op-1", "deviation_pct": 4.76,
            "lifecycle_id": "uuid-1",
        })
        rows = await db.get_order_amendments(100)
        assert len(rows) == 1
        assert rows[0]["field"] == "tp_price"
        assert rows[0]["deviation_pct"] == pytest.approx(4.76)

    @pytest.mark.asyncio
    async def test_multiple_amendments_ordered_by_ts(self, db):
        for ts in (3000, 1000, 2000):
            await db.insert_order_amendment({
                "order_id": 100, "calc_id": "calc-a", "field": "tp_price",
                "old_value": 100.0, "new_value": 100.0 + ts / 1000,
                "ts_ms": ts, "operator_id": "op-1",
                "deviation_pct": 0.0, "lifecycle_id": "uuid-1",
            })
        rows = await db.get_order_amendments(100)
        assert [r["ts_ms"] for r in rows] == [1000, 2000, 3000]

    @pytest.mark.asyncio
    async def test_get_calc_amendments_since_filter(self, db):
        for ts in (1000, 2000, 3000):
            await db.insert_order_amendment({
                "order_id": 100, "calc_id": "calc-a", "field": "sl_price",
                "old_value": 95.0, "new_value": 94.0, "ts_ms": ts,
                "operator_id": None, "deviation_pct": -1.05,
                "lifecycle_id": "uuid-1",
            })
        all_rows = await db.get_calc_amendments("calc-a")
        assert len(all_rows) == 3
        recent = await db.get_calc_amendments("calc-a", since_ms=2000)
        assert len(recent) == 2
        assert all(r["ts_ms"] >= 2000 for r in recent)


# ── 4. funding_events CRUD ────────────────────────────────────────────


class TestFundingEventsInsertDedupSum:
    @pytest.mark.asyncio
    async def test_insert_new_returns_true(self, db):
        inserted = await db.insert_funding_event({
            "position_id": 1, "calc_id": "calc-a", "account_id": 1,
            "symbol": "BTCUSDT", "amount": -0.05,
            "mark_price": 80000.0, "funding_rate": -0.0001,
            "ts_ms": 1000, "venue_event_id": "evt-1",
            "lifecycle_id": "uuid-1",
        })
        assert inserted is True

    @pytest.mark.asyncio
    async def test_duplicate_venue_event_id_returns_false(self, db):
        base = {
            "position_id": 1, "calc_id": "calc-a", "account_id": 1,
            "symbol": "BTCUSDT", "amount": -0.05,
            "mark_price": 80000.0, "funding_rate": -0.0001,
            "ts_ms": 1000, "venue_event_id": "evt-dup",
            "lifecycle_id": "uuid-1",
        }
        first = await db.insert_funding_event(base)
        second = await db.insert_funding_event(base)
        assert first is True
        assert second is False

        rows = await db.get_position_funding_events(1)
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_sum_position_funding(self, db):
        for i, amt in enumerate([-0.05, -0.04, +0.02], start=1):
            await db.insert_funding_event({
                "position_id": 1, "calc_id": "calc-a", "account_id": 1,
                "symbol": "BTCUSDT", "amount": amt,
                "mark_price": 80000.0, "funding_rate": -0.0001,
                "ts_ms": 1000 * i, "venue_event_id": f"evt-{i}",
                "lifecycle_id": "uuid-1",
            })
        total = await db.sum_position_funding(1)
        assert total == pytest.approx(-0.07)

    @pytest.mark.asyncio
    async def test_sum_position_funding_no_events_returns_zero(self, db):
        # Phase 5.4 needs this: closed_positions.funding_fees defaults
        # to 0 for positions with no funding events.
        assert await db.sum_position_funding(999) == 0.0


# ── 5. calc_match_audit CRUD ──────────────────────────────────────────


class TestCalcMatchAuditBatchAndRead:
    @pytest.mark.asyncio
    async def test_batch_insert_returns_count(self, db):
        rows = [
            {"order_id": 100, "calc_id": "calc-a", "criterion": "ticker",
             "calc_value": "BTCUSDT", "order_value": "BTCUSDT",
             "tolerance_used": 0.0, "matched": True, "ts_ms": 1000,
             "winning": True},
            {"order_id": 100, "calc_id": "calc-a", "criterion": "direction",
             "calc_value": "LONG", "order_value": "LONG",
             "tolerance_used": 0.0, "matched": True, "ts_ms": 1000,
             "winning": True},
            {"order_id": 100, "calc_id": "calc-a", "criterion": "entry",
             "calc_value": "80000.0", "order_value": "80050.0",
             "tolerance_used": 0.25, "matched": True, "ts_ms": 1000,
             "winning": True},
        ]
        n = await db.insert_calc_match_audit_batch(rows)
        assert n == 3
        readback = await db.get_order_match_audit(100)
        assert len(readback) == 3

    @pytest.mark.asyncio
    async def test_batch_empty_input_returns_zero(self, db):
        assert await db.insert_calc_match_audit_batch([]) == 0

    @pytest.mark.asyncio
    async def test_get_calc_match_audit_filters_by_order(self, db):
        # Two orders, both audited against same calc.
        for oid in (100, 200):
            await db.insert_calc_match_audit_batch([
                {"order_id": oid, "calc_id": "calc-x",
                 "criterion": "ticker", "calc_value": "BTC",
                 "order_value": "BTC", "tolerance_used": 0.0,
                 "matched": True, "ts_ms": 1000, "winning": False},
            ])
        all_rows = await db.get_calc_match_audit("calc-x")
        assert len(all_rows) == 2
        only_100 = await db.get_calc_match_audit("calc-x", order_id=100)
        assert len(only_100) == 1
        assert only_100[0]["order_id"] == 100

    @pytest.mark.asyncio
    async def test_matched_winning_stored_as_int_booleans(self, db):
        # SQLite stores Python booleans as integers; helper coerces
        # via int(bool(...)). Round-trip preserves the boolean
        # semantics.
        await db.insert_calc_match_audit_batch([
            {"order_id": 100, "calc_id": "calc-a", "criterion": "tp",
             "calc_value": "105", "order_value": "104", "tolerance_used": 0.25,
             "matched": False, "ts_ms": 1000, "winning": False},
        ])
        rows = await db.get_order_match_audit(100)
        assert rows[0]["matched"] == 0
        assert rows[0]["winning"] == 0
