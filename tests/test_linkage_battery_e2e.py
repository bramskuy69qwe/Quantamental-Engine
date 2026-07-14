"""Linkage attribution battery — end-to-end flows (LB-E1..E3).

Spec: docs/design/linkage_battery_plan.md §2 (scenario matrix) + §3
(conventions). Reference file for the battery: the disagreement and
interference files follow the fixture + assertion idioms established here.

Each scenario drives the REAL pipeline entry points (`_enrich_order_best_effort`,
`_process_single_fill`, `_build_close_row_for_fill`, `link_actions`) against a
tempfile DB and asserts the attribution OUTPUTS (DB rows). Scenarios assert
DESIRED semantics; a divergence found here is triaged per plan §4 before any
xfail conversion. No TestClient (gotcha LOW-023). The +2s close-row timer
(order_manager.py:1928 `loop.call_later`) never fires inside a test — the
row build is driven directly for determinism.
"""
import os
import sys

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tests.linkage_battery_helpers import (  # noqa: E402
    ACCOUNT_ID,
    RECENT_MS,
    assert_calc_link_invariant,
    calc_row,
    closed_rows,
    fill,
    fill_by_fid,
    junction_rows,
    make_real_db,
    order_dict,
    order_row,
    q,
    seed_calc,
    seed_order,
)


@pytest_asyncio.fixture
async def real(monkeypatch):
    """OrderManager + tempfile DB wired into every singleton the pipeline
    reads: config.DB_PATH (raw-sqlite enrichment), link_actions.db
    (manual-link), trade_event_log stubbed (linkdb pattern)."""
    import config
    import core.link_actions as la
    import core.trade_event_log as tel
    from core.order_manager import OrderManager

    db, path, cleanup = await make_real_db()
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(la, "db", db)
    monkeypatch.setattr(tel, "log_trade_event", lambda *a, **k: None)
    yield OrderManager(db), db
    await cleanup()


# ── LB-E1: happy path — calc → 6/6 auto-link → fill → junction → close ─


class TestLBE1HappyPath:
    @pytest.mark.asyncio
    async def test_full_chain_attribution(self, real):
        om, db = real
        await seed_calc(db, "CALC-E1", window_seconds=300)
        oid = await seed_order(db, "O-E1")

        # Order arrival → strict matcher.
        await om._enrich_order_best_effort(order_dict("O-E1"))
        order = await order_row(db, oid)
        assert order["link_status"] == "LINKED"
        assert order["calc_id"] == "CALC-E1"
        assert_calc_link_invariant(order)
        assert (await calc_row(db, "CALC-E1"))["status"] == "matched"

        # Entry fill → junction + lifecycle mint + tpid backfill.
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-E1", "POS-E1", 1.0, fid="F-E1"))
        junc = await junction_rows(db, "POS-E1")
        assert len(junc) == 1
        assert junc[0]["calc_id"] == "CALC-E1"
        assert junc[0]["order_id"] == oid
        assert junc[0]["contributed_qty"] == pytest.approx(1.0)
        lifecycle = junc[0]["lifecycle_id"]
        assert lifecycle  # minted
        order = await order_row(db, oid)
        assert order["terminal_position_id"] == "POS-E1"
        assert order["lifecycle_id"] == lifecycle
        assert (await calc_row(db, "CALC-E1"))["lifecycle_id"] == lifecycle
        f_entry = await fill_by_fid(db, "F-E1")
        assert f_entry["calc_id"] == "CALC-E1"
        assert f_entry["lifecycle_id"] == lifecycle

        # Close fill → primary-calc stamp → close row → calc completion.
        await seed_order(db, "O-E1C", side="SELL", reduce_only=1,
                         tp_trigger_price=None, sl_trigger_price=None,
                         created_at_ms=RECENT_MS + 1500)
        f_close = fill("O-E1C", "POS-E1", 1.0, fid="F-E1C", is_close=1,
                       price=55000.0, realized_pnl=5000.0,
                       ts=RECENT_MS + 2000)
        await om._process_single_fill(ACCOUNT_ID, f_close)
        stamped = await fill_by_fid(db, "F-E1C")
        assert stamped["calc_id"] == "CALC-E1"
        assert stamped["lifecycle_id"] == lifecycle

        await om._build_close_row_for_fill(ACCOUNT_ID, f_close)
        closed = await closed_rows(db, "POS-E1")
        assert len(closed) == 1
        assert closed[0]["calc_id"] == "CALC-E1"
        assert closed[0]["lifecycle_id"] == lifecycle
        assert (await calc_row(db, "CALC-E1"))["status"] == (
            "completed_via_position")


# ── LB-E2: calc-timing race — NMR → manual link → attribution ─────────


class TestLBE2ManualLinkLane:
    async def _drive_to_nmr(self, om, db):
        """Order + near-miss calc (SL off by 1000) → NEEDS_MANUAL_REVIEW,
        entry fill already processed BEFORE the operator links (the
        90a9da4 link-timing shape)."""
        await seed_calc(db, "CALC-E2", sl_price=47000.0, window_seconds=300)
        oid = await seed_order(db, "O-E2")
        await om._enrich_order_best_effort(order_dict("O-E2"))
        order = await order_row(db, oid)
        assert order["link_status"] == "NEEDS_MANUAL_REVIEW"
        assert order["calc_id"] is None
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-E2", "POS-E2", 1.0, fid="F-E2"))
        assert (await fill_by_fid(db, "F-E2"))["calc_id"] is None
        return oid

    @pytest.mark.asyncio
    async def test_manual_link_backfills_order_calc_and_fills(self, real):
        om, db = real
        oid = await self._drive_to_nmr(om, db)

        from core.link_actions import manual_link_order
        assert await manual_link_order(ACCOUNT_ID, oid, "CALC-E2") == "linked"

        order = await order_row(db, oid)
        assert order["link_status"] == "LINKED"
        assert order["calc_id"] == "CALC-E2"
        assert_calc_link_invariant(order)
        assert (await calc_row(db, "CALC-E2"))["status"] == "matched"
        # link_actions.py:240 — opening fills backfilled.
        assert (await fill_by_fid(db, "F-E2"))["calc_id"] == "CALC-E2"

    @pytest.mark.asyncio
    async def test_junction_exists_after_manual_link(self, real):
        # LB-F1 FIXED (was xfail): manual_link_order now replays the
        # junction for an already-filled order (_ensure_junction_if_linked
        # via a throwaway OrderManager on link_actions' own db binding) —
        # the manual lane has the same Defect-8 replay as the auto lane.
        om, db = real
        oid = await self._drive_to_nmr(om, db)
        from core.link_actions import manual_link_order
        assert await manual_link_order(ACCOUNT_ID, oid, "CALC-E2") == "linked"

        junc = await junction_rows(db, "POS-E2")
        assert len(junc) == 1, (
            "no junction row after manual_link of an already-filled order")
        assert junc[0]["calc_id"] == "CALC-E2"

    @pytest.mark.asyncio
    async def test_close_row_attributed_after_manual_link(self, real):
        om, db = real
        oid = await self._drive_to_nmr(om, db)
        from core.link_actions import manual_link_order
        assert await manual_link_order(ACCOUNT_ID, oid, "CALC-E2") == "linked"

        await seed_order(db, "O-E2C", side="SELL", reduce_only=1,
                         tp_trigger_price=None, sl_trigger_price=None,
                         created_at_ms=RECENT_MS + 1500)
        f_close = fill("O-E2C", "POS-E2", 1.0, fid="F-E2C", is_close=1,
                       price=55000.0, realized_pnl=5000.0,
                       ts=RECENT_MS + 2000)
        await om._process_single_fill(ACCOUNT_ID, f_close)
        await om._build_close_row_for_fill(ACCOUNT_ID, f_close)

        closed = await closed_rows(db, "POS-E2")
        assert len(closed) == 1
        assert closed[0]["calc_id"] == "CALC-E2"


# ── LB-E3: unplanned lane + manual-journal separation ──────────────────


class TestLBE3UnplannedAndJournal:
    @pytest.mark.asyncio
    async def test_unplanned_close_row_has_no_calc(self, real):
        om, db = real
        oid = await seed_order(db, "O-E3")  # no calcs seeded → 0 candidates
        await om._enrich_order_best_effort(order_dict("O-E3"))
        order = await order_row(db, oid)
        assert order["link_status"] == "UNPLANNED"
        assert order["calc_id"] is None
        assert_calc_link_invariant(order)

        await om._process_single_fill(
            ACCOUNT_ID, fill("O-E3", "POS-E3", 1.0, fid="F-E3"))
        assert await junction_rows(db, "POS-E3") == []

        await seed_order(db, "O-E3C", side="SELL", reduce_only=1,
                         tp_trigger_price=None, sl_trigger_price=None,
                         created_at_ms=RECENT_MS + 1500)
        f_close = fill("O-E3C", "POS-E3", 1.0, fid="F-E3C", is_close=1,
                       price=51000.0, realized_pnl=1000.0,
                       ts=RECENT_MS + 2000)
        await om._process_single_fill(ACCOUNT_ID, f_close)
        await om._build_close_row_for_fill(ACCOUNT_ID, f_close)

        closed = await closed_rows(db, "POS-E3")
        assert len(closed) == 1
        assert not closed[0]["calc_id"]
        assert not closed[0]["lifecycle_id"]

    @pytest.mark.asyncio
    async def test_manual_journal_is_disjoint_from_closed_positions(self, real):
        om, db = real
        before = len(await closed_rows(db))

        await db.insert_trade_history({
            "account_id": ACCOUNT_ID,
            "ticker": "BTCUSDT",
            "direction": "LONG",
            "entry_price": 50000.0,
            "exit_price": 51000.0,
            "individual_realized": 1000.0,
        })

        # trade_history got the row; closed_positions untouched.
        assert len(await q(db, "SELECT * FROM trade_history")) == 1
        assert len(await closed_rows(db)) == before
        # And the journal schema carries NO linkage identifiers at all.
        cols = {r["name"] for r in await q(
            db, "PRAGMA table_info(trade_history)")}
        assert not ({"calc_id", "lifecycle_id", "terminal_position_id"} & cols)
