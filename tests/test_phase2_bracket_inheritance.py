"""Phase 2.9 — TP/SL bracket calc_id inheritance (spec §4.5).

Covers ``OrderManager._propagate_bracket_calc_id``: when an entry + its
TP/SL are placed together as a bracket (detected via the T2.8 engine),
the entry's ``calc_id`` propagates onto the protective legs that don't
already carry one, and ``link_status`` is set to ``LINKED`` (maintaining
the "calc_id present ⟺ link_status=LINKED" invariant).

The matcher (``order_enrichment._try_correlate``) returns early for
reduce-only / close-type orders, so a TP/SL order ROW only EVER gets a
calc_id through this path — that is what T2.9 closes.

Two layers:
  - Unit (``Test*`` driving ``_propagate_bracket_calc_id`` directly on
    ``self._db._conn``): contract cases — propagate, idempotency,
    entry-must-have-calc, cohort isolation, window exclusion. Adapter
    resolution falls back to the venue-agnostic engine (link_field=None,
    the Binance shape) when no active account is configured.
  - Integration (``TestProcessOrderUpdateWiring``): drives the REAL
    ``process_order_update`` entry point with ``config.DB_PATH`` patched
    to the tmpfile DB. Rule-8 intent test — FAILS if the
    ``_propagate_bracket_calc_id`` call is dropped from / mis-ordered in
    ``process_order_update``.

Run: pytest tests/test_phase2_bracket_inheritance.py -v
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


# ── seed / read helpers ────────────────────────────────────────────────


async def _seed_order(db, eoid, *, order_type, calc_id=None, link_status=None,
                      reduce_only=0, position_side="LONG", created_at_ms=1000,
                      symbol="BTCUSDT", side="BUY", client_order_id="",
                      status="new", account_id=ACCOUNT_ID) -> int:
    cur = await db._conn.execute(
        "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
        " order_type, reduce_only, position_side, created_at_ms, status, "
        " client_order_id, calc_id, link_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (account_id, eoid, symbol, side, order_type, reduce_only,
         position_side, created_at_ms, status, client_order_id,
         calc_id, link_status),
    )
    await db._conn.commit()
    return cur.lastrowid


async def _read(db, eoid, account_id=ACCOUNT_ID):
    async with db._conn.execute(
        "SELECT calc_id, link_status FROM orders "
        "WHERE account_id=? AND exchange_order_id=?",
        (account_id, eoid),
    ) as cur:
        r = await cur.fetchone()
    return {"calc_id": r[0], "link_status": r[1]}


# ── unit: core propagation contract ────────────────────────────────────


class TestBracketPropagation:
    @pytest.mark.asyncio
    async def test_propagates_to_tp_and_sl(self, db, om):
        await _seed_order(db, "E", order_type="limit", calc_id="C1",
                          link_status="LINKED", created_at_ms=1000)
        await _seed_order(db, "TP", order_type="take_profit", reduce_only=1,
                          side="SELL", created_at_ms=1100)
        await _seed_order(db, "SL", order_type="stop_loss", reduce_only=1,
                          side="SELL", created_at_ms=1200)

        await om._propagate_bracket_calc_id(ACCOUNT_ID, "BTCUSDT")

        for eoid in ("TP", "SL"):
            row = await _read(db, eoid)
            assert row["calc_id"] == "C1", eoid
            assert row["link_status"] == "LINKED", eoid
        # entry untouched
        assert (await _read(db, "E"))["calc_id"] == "C1"

    @pytest.mark.asyncio
    async def test_orphaned_amendment_backfilled_on_link(self, db, om):
        # P4.T5 audit (SCOPING-001): a protective leg amended BEFORE this
        # inheritance ran carries calc_id=NULL (P4.T1 records the order's
        # then-NULL calc_id). On link, the leg's orphaned amendments must be
        # backfilled to the inherited calc_id — else the close-time drift
        # (get_calc_amendments) + P4.T2's cumulative count
        # (count_amendments_for_calcs), both scoped by calc_id, silently miss it.
        await _seed_order(db, "E", order_type="limit", calc_id="C1",
                          link_status="LINKED", created_at_ms=1000)
        sl_oid = await _seed_order(db, "SL", order_type="stop_loss",
                                   reduce_only=1, side="SELL", created_at_ms=1100)
        await db.insert_order_amendment({
            "order_id": sl_oid, "calc_id": None, "field": "sl_price",
            "old_value": 48000.0, "new_value": 47040.0, "ts_ms": 1050,
            "operator_id": None, "deviation_pct": -2.0, "lifecycle_id": None,
        })

        await om._propagate_bracket_calc_id(ACCOUNT_ID, "BTCUSDT")

        assert (await _read(db, "SL"))["calc_id"] == "C1"
        amends = await db.get_order_amendments(sl_oid)
        assert len(amends) == 1
        assert amends[0]["calc_id"] == "C1"   # backfilled — no longer orphaned

    @pytest.mark.asyncio
    async def test_backfill_does_not_overwrite_attributed_amendment(self, db, om):
        # The backfill is guarded WHERE calc_id IS NULL — an amendment already
        # attributed to a calc is NOT clobbered when its leg inherits a calc_id.
        await _seed_order(db, "E", order_type="limit", calc_id="C1",
                          link_status="LINKED", created_at_ms=1000)
        tp_oid = await _seed_order(db, "TP", order_type="take_profit",
                                   reduce_only=1, side="SELL", created_at_ms=1100)
        await db.insert_order_amendment({
            "order_id": tp_oid, "calc_id": "C-PRIOR", "field": "tp_price",
            "old_value": 55000.0, "new_value": 56000.0, "ts_ms": 1050,
            "operator_id": None, "deviation_pct": 1.8, "lifecycle_id": None,
        })

        await om._propagate_bracket_calc_id(ACCOUNT_ID, "BTCUSDT")

        amends = await db.get_order_amendments(tp_oid)
        assert amends[0]["calc_id"] == "C-PRIOR"   # NOT overwritten

    @pytest.mark.asyncio
    async def test_idempotent_does_not_overwrite_existing_calc(self, db, om):
        await _seed_order(db, "E", order_type="limit", calc_id="C1",
                          created_at_ms=1000)
        # TP already linked to a DIFFERENT calc — must NOT be overwritten.
        await _seed_order(db, "TP", order_type="take_profit", reduce_only=1,
                          calc_id="C-OTHER", link_status="LINKED",
                          created_at_ms=1100)
        await _seed_order(db, "SL", order_type="stop_loss", reduce_only=1,
                          created_at_ms=1200)

        await om._propagate_bracket_calc_id(ACCOUNT_ID, "BTCUSDT")

        assert (await _read(db, "TP"))["calc_id"] == "C-OTHER"
        assert (await _read(db, "SL"))["calc_id"] == "C1"

    @pytest.mark.asyncio
    async def test_running_twice_is_stable(self, db, om):
        await _seed_order(db, "E", order_type="limit", calc_id="C1",
                          created_at_ms=1000)
        await _seed_order(db, "SL", order_type="stop_loss", reduce_only=1,
                          created_at_ms=1100)

        await om._propagate_bracket_calc_id(ACCOUNT_ID, "BTCUSDT")
        await om._propagate_bracket_calc_id(ACCOUNT_ID, "BTCUSDT")

        assert (await _read(db, "SL"))["calc_id"] == "C1"

    @pytest.mark.asyncio
    async def test_no_entry_calc_no_propagation(self, db, om):
        # Entry has NO calc_id (UNPLANNED / unmatched) → nothing to inherit.
        await _seed_order(db, "E", order_type="limit", created_at_ms=1000)
        await _seed_order(db, "TP", order_type="take_profit", reduce_only=1,
                          created_at_ms=1100)

        await om._propagate_bracket_calc_id(ACCOUNT_ID, "BTCUSDT")

        assert (await _read(db, "TP"))["calc_id"] is None

    @pytest.mark.asyncio
    async def test_filled_entry_still_propagates(self, db, om):
        # Entry already FILLED (not in active orders) when the SL arrives —
        # candidate query must include non-active rows, else no bracket.
        await _seed_order(db, "E", order_type="limit", calc_id="C1",
                          status="filled", created_at_ms=1000)
        await _seed_order(db, "SL", order_type="stop_loss", reduce_only=1,
                          status="new", created_at_ms=1100)

        await om._propagate_bracket_calc_id(ACCOUNT_ID, "BTCUSDT")

        assert (await _read(db, "SL"))["calc_id"] == "C1"

    @pytest.mark.asyncio
    async def test_far_apart_is_not_a_bracket(self, db, om):
        # Entry + SL >2s apart → not "placed together" → no bracket.
        await _seed_order(db, "E", order_type="limit", calc_id="C1",
                          created_at_ms=1000)
        await _seed_order(db, "SL", order_type="stop_loss", reduce_only=1,
                          created_at_ms=1000 + 3000)

        await om._propagate_bracket_calc_id(ACCOUNT_ID, "BTCUSDT")

        assert (await _read(db, "SL"))["calc_id"] is None

    @pytest.mark.asyncio
    async def test_two_cohorts_each_inherits_own_entry(self, db, om):
        # LONG bracket (calc C1) + SHORT bracket (calc C2) on the same
        # symbol — each protective leg inherits ITS OWN cohort's entry.
        await _seed_order(db, "EL", order_type="limit", calc_id="C1",
                          position_side="LONG", created_at_ms=1000)
        await _seed_order(db, "TPL", order_type="take_profit", reduce_only=1,
                          position_side="LONG", side="SELL", created_at_ms=1100)
        await _seed_order(db, "ES", order_type="limit", calc_id="C2",
                          position_side="SHORT", side="SELL", created_at_ms=1000)
        await _seed_order(db, "SLS", order_type="stop_loss", reduce_only=1,
                          position_side="SHORT", side="BUY", created_at_ms=1100)

        await om._propagate_bracket_calc_id(ACCOUNT_ID, "BTCUSDT")

        assert (await _read(db, "TPL"))["calc_id"] == "C1"
        assert (await _read(db, "SLS"))["calc_id"] == "C2"

    @pytest.mark.asyncio
    async def test_entry_only_no_protective_no_write(self, db, om):
        # Two entries, no protective leg → not a bracket, no writes.
        await _seed_order(db, "E1", order_type="limit", calc_id="C1",
                          created_at_ms=1000)
        await _seed_order(db, "E2", order_type="market", created_at_ms=1100)

        await om._propagate_bracket_calc_id(ACCOUNT_ID, "BTCUSDT")

        assert (await _read(db, "E2"))["calc_id"] is None

    @pytest.mark.asyncio
    async def test_scale_in_shared_protective_picks_earliest_entry(self, db, om):
        # T237 review 2: two entries with DIFFERENT calcs share one SL within
        # the 2s window (near-simultaneous scale-in). Documented behavior:
        # the protective leg inherits the EARLIEST calc-bearing entry
        # (placement-time order-level attribution, deterministic). NOT the
        # most-contributing primary — that is a close-time/position-level
        # concept re-derived from the junction by T2.2/T2.6.
        await _seed_order(db, "E1", order_type="limit", calc_id="C1",
                          created_at_ms=1000)
        await _seed_order(db, "E2", order_type="limit", calc_id="C2",
                          created_at_ms=1100)
        await _seed_order(db, "SL", order_type="stop_loss", reduce_only=1,
                          created_at_ms=1200)

        await om._propagate_bracket_calc_id(ACCOUNT_ID, "BTCUSDT")

        assert (await _read(db, "SL"))["calc_id"] == "C1"  # earliest entry

    @pytest.mark.asyncio
    async def test_empty_symbol_is_noop(self, db, om):
        await om._propagate_bracket_calc_id(ACCOUNT_ID, "")  # no raise

    @pytest.mark.asyncio
    async def test_batch_wrapper_covers_distinct_symbols(self, db, om):
        await _seed_order(db, "EB", order_type="limit", calc_id="C1",
                          symbol="BTCUSDT", created_at_ms=1000)
        await _seed_order(db, "SLB", order_type="stop_loss", reduce_only=1,
                          symbol="BTCUSDT", created_at_ms=1100)
        await _seed_order(db, "EE", order_type="limit", calc_id="C2",
                          symbol="ETHUSDT", created_at_ms=1000)
        await _seed_order(db, "SLE", order_type="stop_loss", reduce_only=1,
                          symbol="ETHUSDT", created_at_ms=1100)

        await om._propagate_bracket_calc_id_for_orders(
            ACCOUNT_ID,
            [{"symbol": "BTCUSDT"}, {"symbol": "ETHUSDT"}, {"symbol": "BTCUSDT"}],
        )

        assert (await _read(db, "SLB"))["calc_id"] == "C1"
        assert (await _read(db, "SLE"))["calc_id"] == "C2"


# ── integration: REAL process_order_update path (Rule-8 wiring test) ────


@pytest_asyncio.fixture
async def real(monkeypatch):
    import config
    from core.database import DatabaseManager
    from core.order_manager import OrderManager
    from core.state import app_state

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    database = DatabaseManager(path=tmp.name)
    await database.initialize()
    await database._conn.execute(
        "INSERT OR IGNORE INTO accounts (id, name, config_json) "
        "VALUES (1, 'Test', ?)",
        ('{"window_seconds": 300}',),
    )
    await database._conn.commit()
    monkeypatch.setattr(config, "DB_PATH", tmp.name)
    # refresh_cache enriches app_state.positions; keep it empty + isolated.
    monkeypatch.setattr(app_state, "positions", [])
    yield OrderManager(database), database
    await database.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


class TestProcessOrderUpdateWiring:
    @pytest.mark.asyncio
    async def test_arriving_sl_inherits_entry_calc_via_real_path(self, real):
        om, db = real
        # Pre-existing matched entry (already filled) + a working TP, both
        # placed with the bracket. The SL arrives now via the WS handler.
        await _seed_order(db, "E", order_type="limit", calc_id="C1",
                          link_status="LINKED", status="filled",
                          created_at_ms=1000)
        await _seed_order(db, "TP", order_type="take_profit", reduce_only=1,
                          side="SELL", status="new", created_at_ms=1100)

        sl_order = {
            "account_id": ACCOUNT_ID,
            "exchange_order_id": "SL",
            "symbol": "BTCUSDT",
            "side": "SELL",
            "order_type": "stop_loss",
            "status": "new",
            "reduce_only": 1,
            "position_side": "LONG",
            "created_at_ms": 1200,
            "exchange_position_id": "",  # empty → no parent re-enrich connect
            "stop_price": 49000,
        }
        ok = await om.process_order_update(ACCOUNT_ID, sl_order)
        assert ok is True

        # Both protective legs inherited the entry's calc via the wired call.
        assert (await _read(db, "SL"))["calc_id"] == "C1"
        assert (await _read(db, "TP"))["calc_id"] == "C1"
        assert (await _read(db, "SL"))["link_status"] == "LINKED"
