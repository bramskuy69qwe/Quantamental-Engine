"""
Phase 4 Task 1 (P4.T1) tests — order amendment detection + persistence.

Verifies ``OrderManager.detect_and_persist_amendment`` (called from
``ws_manager._apply_order_update`` BEFORE ``process_order_update``):

  - Maps the engine's order columns to the spec §3.2 amendment fields by
    order_type (entry→entry_price, take_profit→tp_price, stop_loss→sl_price,
    quantity→size).
  - Writes one immutable ``order_amendments`` row per changed working-order
    field, with signed deviation_pct and denormalized calc_id/lifecycle_id.
  - Only a real prior value changing to a *different* real value counts: a
    0/absent old or new is a set/remove (a cancel), not an amendment.
  - **Chained baseline (the load-bearing P4.T1 decision)**: a second
    amendment's old_value comes from the most recent prior amendment's
    new_value, NOT the stored order row (which goes stale because the SR-1
    transition gate rejects the new→new amend upsert). A test seeds two
    amendments and asserts the second chains off the first.

WHY this lives ahead of the SR-1 gate (Rule 8 intent): an amendment arrives
as a new→new self-transition, which ``validate_transition`` rejects
(order_state.py / test_order_manager.py:121), so ``process_order_update``
returns False before any post-gate hook runs. Detection MUST be invoked
pre-gate (ws_manager) — the wiring test guards that the call exists and runs
before process_order_update.

Run: pytest tests/test_phase4_amendments.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

ACCOUNT_ID = 1


@pytest_asyncio.fixture
async def db():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    database = DatabaseManager(path=tmp.name)
    await database.initialize()
    yield database
    await database.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


@pytest_asyncio.fixture
async def om(db):
    from core.order_manager import OrderManager
    return OrderManager(db)


async def _seed_working_order(
    db, eoid, *, order_type="limit", price=0.0, stop_price=0.0, quantity=0.0,
    status="new", calc_id=None, lifecycle_id=None, symbol="BTCUSDT",
    side="BUY", account_id=ACCOUNT_ID,
) -> int:
    cur = await db._conn.execute(
        "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
        " order_type, status, price, stop_price, quantity, calc_id, lifecycle_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (account_id, eoid, symbol, side, order_type, status, price,
         stop_price, quantity, calc_id, lifecycle_id),
    )
    await db._conn.commit()
    return cur.lastrowid


def _incoming(eoid, *, order_type="limit", price=0.0, stop_price=0.0,
              quantity=0.0, status="new", updated_at_ms=1000,
              account_id=ACCOUNT_ID):
    return {
        "account_id": account_id,
        "exchange_order_id": eoid,
        "order_type": order_type,
        "status": status,
        "price": price,
        "stop_price": stop_price,
        "quantity": quantity,
        "updated_at_ms": updated_at_ms,
    }


# ── 1. field mapping (pure) ─────────────────────────────────────────────


class TestAmendmentFieldPairs:
    """order_type → (spec §3.2 field, orders column) pairs (Rule 8: the
    polymorphic field mapping is the contract)."""

    def test_entry_order_maps_price_to_entry_price(self, om):
        assert om._amendment_field_pairs("limit") == (
            ("entry_price", "price"), ("size", "quantity"))

    def test_market_entry_also_entry_price(self, om):
        assert om._amendment_field_pairs("market")[0] == ("entry_price", "price")

    def test_take_profit_maps_stop_price_to_tp_price(self, om):
        assert om._amendment_field_pairs("take_profit")[0] == ("tp_price", "stop_price")
        assert om._amendment_field_pairs("take_profit_market")[0] == ("tp_price", "stop_price")

    def test_stop_loss_maps_stop_price_to_sl_price(self, om):
        assert om._amendment_field_pairs("stop_loss")[0] == ("sl_price", "stop_price")
        assert om._amendment_field_pairs("stop_market")[0] == ("sl_price", "stop_price")

    def test_size_pair_always_present(self, om):
        for ot in ("limit", "take_profit", "stop_loss", "market"):
            assert om._amendment_field_pairs(ot)[1] == ("size", "quantity")

    def test_none_order_type_falls_back_to_entry(self, om):
        assert om._amendment_field_pairs(None)[0] == ("entry_price", "price")

    def test_entry_stop_reads_stop_price_under_entry_label(self, om):
        # FE-13 `_entry` suffix: non-reduce-only stop/TP ENTRY orders carry
        # their trigger in stop_price (price==0 for stop-market), so they must
        # read stop_price while keeping the entry_price label (audit CORR-001).
        assert om._amendment_field_pairs("stop_loss_entry")[0] == ("entry_price", "stop_price")
        assert om._amendment_field_pairs("take_profit_entry")[0] == ("entry_price", "stop_price")

    def test_trailing_stop_excluded(self, om):
        # Venue-automatic trigger — not an operator amendment.
        assert om._amendment_field_pairs("trailing_stop") == ()


# ── 2. detect + persist ─────────────────────────────────────────────────


async def _amendments(db, order_id):
    return await db.get_order_amendments(order_id)


class TestDetectAndPersistAmendment:
    @pytest.mark.asyncio
    async def test_entry_price_amendment_written(self, db, om):
        oid = await _seed_working_order(
            db, "O-1", order_type="limit", price=50000.0, quantity=1.0,
            calc_id="calc-a", lifecycle_id="lc-1")
        await om.detect_and_persist_amendment(
            ACCOUNT_ID, _incoming("O-1", price=50100.0, quantity=1.0,
                                  updated_at_ms=12345))
        rows = await _amendments(db, oid)
        assert len(rows) == 1
        r = rows[0]
        assert r["field"] == "entry_price"
        assert r["old_value"] == pytest.approx(50000.0)
        assert r["new_value"] == pytest.approx(50100.0)
        assert r["deviation_pct"] == pytest.approx(0.2)
        assert r["calc_id"] == "calc-a"
        assert r["lifecycle_id"] == "lc-1"
        assert r["ts_ms"] == 12345
        assert r["order_id"] == oid

    @pytest.mark.asyncio
    async def test_tp_price_amendment(self, db, om):
        oid = await _seed_working_order(
            db, "TP", order_type="take_profit", stop_price=55000.0, quantity=1.0)
        await om.detect_and_persist_amendment(
            ACCOUNT_ID, _incoming("TP", order_type="take_profit",
                                  stop_price=56000.0, quantity=1.0))
        rows = await _amendments(db, oid)
        assert [r["field"] for r in rows] == ["tp_price"]
        assert rows[0]["new_value"] == pytest.approx(56000.0)

    @pytest.mark.asyncio
    async def test_sl_price_amendment(self, db, om):
        oid = await _seed_working_order(
            db, "SL", order_type="stop_loss", stop_price=48000.0, quantity=1.0)
        await om.detect_and_persist_amendment(
            ACCOUNT_ID, _incoming("SL", order_type="stop_loss",
                                  stop_price=47000.0, quantity=1.0))
        rows = await _amendments(db, oid)
        assert [r["field"] for r in rows] == ["sl_price"]

    @pytest.mark.asyncio
    async def test_size_amendment(self, db, om):
        oid = await _seed_working_order(
            db, "O-1", order_type="limit", price=50000.0, quantity=1.0)
        await om.detect_and_persist_amendment(
            ACCOUNT_ID, _incoming("O-1", price=50000.0, quantity=1.5))
        rows = await _amendments(db, oid)
        assert [r["field"] for r in rows] == ["size"]
        assert rows[0]["old_value"] == pytest.approx(1.0)
        assert rows[0]["new_value"] == pytest.approx(1.5)

    @pytest.mark.asyncio
    async def test_two_fields_two_rows(self, db, om):
        oid = await _seed_working_order(
            db, "SL", order_type="stop_loss", stop_price=48000.0, quantity=1.0)
        await om.detect_and_persist_amendment(
            ACCOUNT_ID, _incoming("SL", order_type="stop_loss",
                                  stop_price=47000.0, quantity=2.0))
        rows = await _amendments(db, oid)
        assert {r["field"] for r in rows} == {"sl_price", "size"}

    @pytest.mark.asyncio
    async def test_unknown_order_no_row(self, db, om):
        # No stored working order → first arrival / not tracked → nothing.
        await om.detect_and_persist_amendment(
            ACCOUNT_ID, _incoming("GHOST", price=50000.0, quantity=1.0))
        async with db._conn.execute("SELECT COUNT(*) FROM order_amendments") as cur:
            assert (await cur.fetchone())[0] == 0

    @pytest.mark.asyncio
    async def test_no_change_no_row(self, db, om):
        oid = await _seed_working_order(
            db, "O-1", order_type="limit", price=50000.0, quantity=1.0)
        await om.detect_and_persist_amendment(
            ACCOUNT_ID, _incoming("O-1", price=50000.0, quantity=1.0))
        assert await _amendments(db, oid) == []

    @pytest.mark.asyncio
    async def test_initial_set_old_zero_not_amendment(self, db, om):
        # TP trigger goes from absent (0) to a value → that's a set, not an amend.
        oid = await _seed_working_order(
            db, "TP", order_type="take_profit", stop_price=0.0, quantity=1.0)
        await om.detect_and_persist_amendment(
            ACCOUNT_ID, _incoming("TP", order_type="take_profit",
                                  stop_price=55000.0, quantity=1.0))
        assert await _amendments(db, oid) == []

    @pytest.mark.asyncio
    async def test_removal_new_zero_not_amendment(self, db, om):
        # TP trigger goes to 0 (removed) → cancel, not an amend.
        oid = await _seed_working_order(
            db, "TP", order_type="take_profit", stop_price=55000.0, quantity=1.0)
        await om.detect_and_persist_amendment(
            ACCOUNT_ID, _incoming("TP", order_type="take_profit",
                                  stop_price=0.0, quantity=1.0))
        assert await _amendments(db, oid) == []

    @pytest.mark.asyncio
    async def test_market_entry_price_zero_no_entry_amendment(self, db, om):
        # Market order: price stays 0 → only size can amend.
        oid = await _seed_working_order(
            db, "M", order_type="market", price=0.0, quantity=1.0)
        await om.detect_and_persist_amendment(
            ACCOUNT_ID, _incoming("M", order_type="market", price=0.0, quantity=2.0))
        rows = await _amendments(db, oid)
        assert [r["field"] for r in rows] == ["size"]

    @pytest.mark.asyncio
    async def test_stop_market_entry_trigger_amendment(self, db, om):
        """Audit CORR-001 regression: a stop-market ENTRY (order_type
        stop_loss_entry, price=0, trigger in stop_price) whose trigger moves
        MUST record an entry_price amendment. Before the fix this mapped to the
        price column (0→0) and the change guard silently dropped it."""
        oid = await _seed_working_order(
            db, "ES", order_type="stop_loss_entry", price=0.0,
            stop_price=49000.0, quantity=1.0)
        await om.detect_and_persist_amendment(
            ACCOUNT_ID, _incoming("ES", order_type="stop_loss_entry",
                                  price=0.0, stop_price=48000.0, quantity=1.0))
        rows = await _amendments(db, oid)
        assert len(rows) == 1
        assert rows[0]["field"] == "entry_price"
        assert rows[0]["old_value"] == pytest.approx(49000.0)
        assert rows[0]["new_value"] == pytest.approx(48000.0)

    @pytest.mark.asyncio
    async def test_trailing_stop_not_recorded(self, db, om):
        # Trailing-stop trigger moves are venue-automatic → not amendments.
        oid = await _seed_working_order(
            db, "TS", order_type="trailing_stop", stop_price=49000.0, quantity=1.0)
        await om.detect_and_persist_amendment(
            ACCOUNT_ID, _incoming("TS", order_type="trailing_stop",
                                  stop_price=48000.0, quantity=1.0))
        assert await _amendments(db, oid) == []

    @pytest.mark.asyncio
    async def test_null_calc_id_and_lifecycle_ok(self, db, om):
        oid = await _seed_working_order(
            db, "O-1", order_type="limit", price=50000.0, quantity=1.0,
            calc_id=None, lifecycle_id=None)
        await om.detect_and_persist_amendment(
            ACCOUNT_ID, _incoming("O-1", price=50100.0, quantity=1.0))
        rows = await _amendments(db, oid)
        assert len(rows) == 1
        assert rows[0]["calc_id"] is None
        assert rows[0]["lifecycle_id"] is None

    @pytest.mark.asyncio
    async def test_chained_baseline_second_amendment_uses_last_new_value(self, db, om):
        """THE load-bearing P4.T1 test: the stored order row stays stale (the
        SR-1 gate rejects the amend upsert), so a second amendment must chain
        off the FIRST amendment's new_value, not the stored row's value."""
        oid = await _seed_working_order(
            db, "O-1", order_type="limit", price=50000.0, quantity=1.0)
        # amendment 1: 50000 → 50100
        await om.detect_and_persist_amendment(
            ACCOUNT_ID, _incoming("O-1", price=50100.0, quantity=1.0,
                                  updated_at_ms=100))
        # amendment 2: 50100 → 50200 (stored row is STILL 50000 — never upserted)
        await om.detect_and_persist_amendment(
            ACCOUNT_ID, _incoming("O-1", price=50200.0, quantity=1.0,
                                  updated_at_ms=200))
        rows = await _amendments(db, oid)
        assert [r["ts_ms"] for r in rows] == [100, 200]
        # Second row chains off the first (old=50100), NOT the stale row (50000).
        assert rows[1]["old_value"] == pytest.approx(50100.0)
        assert rows[1]["new_value"] == pytest.approx(50200.0)
        # ...and a third identical re-delivery (50200) is no-change → no new row.
        await om.detect_and_persist_amendment(
            ACCOUNT_ID, _incoming("O-1", price=50200.0, quantity=1.0,
                                  updated_at_ms=300))
        assert len(await _amendments(db, oid)) == 2


# ── 3. wiring guard (pre-gate placement is load-bearing) ────────────────


class TestWsManagerWiring:
    def test_apply_order_update_calls_detect_before_process(self):
        """The detect call must exist AND precede process_order_update in
        _apply_order_update — placement ahead of the SR-1 gate is the whole
        point (a post-gate call would never see new→new amendments)."""
        import inspect
        from core import ws_manager
        src = inspect.getsource(ws_manager._apply_order_update)
        # Compare the qualified CALL expressions (robust to the code comment
        # that mentions process_order_update by name).
        detect_call = "order_manager.detect_and_persist_amendment"
        process_call = "order_manager.process_order_update"
        assert detect_call in src, \
            "ws_manager._apply_order_update must invoke detect_and_persist_amendment"
        assert src.index(detect_call) < src.index(process_call), \
            "amendment detection must run BEFORE process_order_update (pre-gate)"

    def test_apply_algo_update_also_wired_pre_gate(self):
        """The algo (ALGO_UPDATE) handler must wire detection the same way —
        defensive coverage of conditional orders (audit ALGO-001)."""
        import inspect
        from core import ws_manager
        src = inspect.getsource(ws_manager._apply_algo_update)
        detect_call = "order_manager.detect_and_persist_amendment"
        process_call = "order_manager.process_order_update"
        assert detect_call in src, \
            "ws_manager._apply_algo_update must invoke detect_and_persist_amendment"
        assert src.index(detect_call) < src.index(process_call), \
            "algo amendment detection must run BEFORE process_order_update (pre-gate)"
