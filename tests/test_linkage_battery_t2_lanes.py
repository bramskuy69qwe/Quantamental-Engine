"""Linkage attribution battery — T2 LANES/MISC tranche (LB-T2f..T2l).

Spec: docs/design/linkage_battery_plan.md §2 (LB-T2 row) + §3 (conventions,
binding). Fixture idiom copied from tests/test_linkage_battery_e2e.py (the
reference file); LB-T2i pins the db-layer SIBLING of
tests/test_linkage_battery_interference.py's LB-I2 (time path).

Verified mechanisms (read at the write sites before writing, plan §3):

- LB-T2f: the strict matcher reads pre_trade_log.window_seconds per calc
  (calc_correlation.py:385-393 SELECT, :415 ``row["window_seconds"] or
  window_seconds``), bound = calc window + clock-skew (:429-431). The
  calculator form's ``link_window_seconds_override`` is persisted to a
  SEPARATE column that the matcher never reads — read only by the
  countdown path (routes_calculator.py:397 / db_orders.py:1370 →
  core/exec_link.py:145). Documented column duality:
  db_trades.py:176-191 (T215 L2, "intentional-for-now").
- LB-T2g: the entry criterion is PURE percent (calc_correlation.py:474-481,
  drift = |order-calc|/calc ≤ entry_tolerance_pct/100); tick_size feeds
  ONLY the TP/SL criteria (:494, :502). Defaults: 0.25% / skew 10 s
  (core/account_config.py:26-28).
- LB-T2h: ⑨ tier-2 close-tpid fallback keys ``(symbol, fill.direction)``
  into the map built by db_orders.get_open_entry_tpids_by_symbol_side
  (:1391-1420, keyed on orders.position_side — 'LONG'/'SHORT' in the
  operator's HEDGE deployment). A one-way close fill carries
  direction="BOTH" (ws_manager.py:431-435 KNOWN LATENT GAP) → both tier-1
  (app_state (symbol,direction) scan, order_manager.py:2045-2049) and
  tier-2 (:2061) miss → tpid stays "". Plain asserts (documented gap,
  operator runs HEDGE — no xfail per tranche mandate).
- LB-T2i: db.mark_stale_orders_canceled (db_orders.py:774, snapshot path)
  bulk-cancels via raw UPDATE (:853-858) with no calc release — the same
  strand as the LB-I2/LB-F3 time path; OrderManager.
  release_calcs_for_stale_cancels is the wired sweep that heals it.
- LB-T2j: /history/log_close (api/routes_history.py:59-89 post_trade_close)
  writes trade_history ONLY (db.insert_trade_history) — route-level
  upgrade of LB-E3's DB-layer journal-separation assert (plan §2 note).
- LB-T2k: funding_handler.handle_funding_incomes (:95-284) — open-position
  path writes funding_events keyed to the live tpid with junction-primary
  calc/lifecycle (:152-165, :211-222); closed-window fallback keys to the
  sealed closed row + reconciles closed_positions.funding_fees/net_pnl
  (:166-188, :263-267 → db_orders.py:2496/:2539); no open/closed match →
  ORPHAN, row skipped entirely (:189-210).
- LB-T2l: unminted-snapshot recovery is already covered in
  tests/test_linkage_binance_ws.py (see class note at the bottom); only
  the DataCache self-persist leg (data_cache.py:226-228) was unpinned.

No TestClient (gotcha LOW-023); the +2s close-row timer never fires — the
row build is awaited directly. All scenarios here are passing pins (no
engine divergence found that is not already documented by design).
"""
import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

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

# Same-instant twin of the helpers' anchor, 150 s earlier — for calcs that
# must sit OUTSIDE a small matcher window but INSIDE the account default
# (age 150 s: > 60+10 skew, ≤ 300+10). Derived from RECENT_MS so the pair
# stays anchored to one module-import instant (1fe4178 determinism rule).
PAST150_MS = RECENT_MS - 150_000
PAST150_ISO = datetime.fromtimestamp(
    PAST150_MS / 1000, tz=timezone.utc).isoformat()


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


# ── LB-T2f: matcher window — per-calc column, override-column duality ──


class TestLBT2fWindowOverride:
    """The matcher's effective window is pre_trade_log.window_seconds
    (frozen from accounts.config_json at calc creation, handlers.py:552-556;
    per-calc read at calc_correlation.py:415, in-window gate :429-431:
    age = |order_ts - calc_ts| must be ≤ window + clock_skew(10 s))."""

    @pytest.mark.asyncio
    async def test_order_outside_small_window_not_linked(self, real):
        om, db = real
        # Calc placed 150 s before the order, small 60 s window:
        # 150 > 60 + 10 skew → not a candidate → zero candidates → UNPLANNED.
        await seed_calc(db, "CALC-F1", window_seconds=60,
                        timestamp=PAST150_ISO)
        oid = await seed_order(db, "O-F1")
        await om._enrich_order_best_effort(order_dict("O-F1"))

        order = await order_row(db, oid)
        assert order["link_status"] == "UNPLANNED"
        assert order["calc_id"] is None
        assert_calc_link_invariant(order)
        assert (await calc_row(db, "CALC-F1"))["status"] == "active"

    @pytest.mark.asyncio
    async def test_widened_window_seconds_links_same_shape(self, real):
        om, db = real
        # Same 150 s age, window_seconds=300 (the column the matcher
        # actually reads): 150 ≤ 300 + 10 → in window → 6/6 → LINKED.
        await seed_calc(db, "CALC-F2", window_seconds=300,
                        timestamp=PAST150_ISO)
        oid = await seed_order(db, "O-F2")
        await om._enrich_order_best_effort(order_dict("O-F2"))

        order = await order_row(db, oid)
        assert order["link_status"] == "LINKED"
        assert order["calc_id"] == "CALC-F2"
        assert_calc_link_invariant(order)
        assert (await calc_row(db, "CALC-F2"))["status"] == "matched"

    @pytest.mark.asyncio
    async def test_link_window_override_column_is_not_read_by_matcher(
            self, real):
        """Pins the documented T215 L2 column DUALITY (db_trades.py:176-191):
        the calculator form's link_window_seconds_override (HIGH-027 /
        routes_calculator.py:177-198, persisted by insert_pre_trade_log)
        is read ONLY by the countdown path (routes_calculator.py:397 /
        db_orders.py:1370 → exec_link.py:145) — the strict matcher's
        SELECT (calc_correlation.py:385-393) never touches it. A huge
        override therefore does NOT extend the matcher window; only
        window_seconds does. Plain assert: intentional-for-now per the
        code comment ("deferred cleanup: migrate exec_link then drop")."""
        om, db = real
        await seed_calc(db, "CALC-F3", window_seconds=60,
                        timestamp=PAST150_ISO)
        await db._conn.execute(
            "UPDATE pre_trade_log SET link_window_seconds_override = 86400 "
            "WHERE calc_id = 'CALC-F3'")
        await db._conn.commit()
        oid = await seed_order(db, "O-F3")
        await om._enrich_order_best_effort(order_dict("O-F3"))

        order = await order_row(db, oid)
        # Despite a 24 h override on the calc, the 60 s window_seconds
        # governs: the order stays UNPLANNED.
        assert order["link_status"] == "UNPLANNED"
        assert order["calc_id"] is None
        assert (await calc_row(db, "CALC-F3"))["status"] == "active"


# ── LB-T2g: entry-tolerance boundary (0.25 % pct bound) ────────────────


class TestLBT2gEntryToleranceBoundary:
    """Entry criterion (calc_correlation.py:474-481): drift =
    |entry_source - calc_entry| / calc_entry ≤ entry_tolerance_pct/100
    (account default 0.25 %, account_config.py:28). NOTE: the entry
    criterion is PURE percent — tick_size feeds only the TP/SL criteria
    (:494/:502), so with order TP/SL set EXACTLY equal to the calc's
    (diff 0 ≤ any tick) these pins are insensitive to the
    _get_tick_size fallback looseness (order_enrichment.py:626-654).
    Deltas ±0.1 % / ±0.5 % pin that the tolerance EXISTS, not its edge."""

    @pytest.mark.asyncio
    async def test_entry_just_inside_tolerance_links(self, real):
        om, db = real
        await seed_calc(db, "CALC-G1", window_seconds=300)  # entry 50000
        # Limit price +0.1 % (50050): drift 0.001 ≤ 0.0025 → 6/6.
        oid = await seed_order(db, "O-G1", price=50050.0)
        await om._enrich_order_best_effort(order_dict("O-G1", price=50050.0))

        order = await order_row(db, oid)
        assert order["link_status"] == "LINKED"
        assert order["calc_id"] == "CALC-G1"
        assert_calc_link_invariant(order)
        assert (await calc_row(db, "CALC-G1"))["status"] == "matched"
        # Audit trail: the winning candidate's entry row matched.
        audit = await q(
            db, "SELECT criterion, matched FROM calc_match_audit "
                "WHERE order_id = ?", oid)
        by_crit = {r["criterion"]: r["matched"] for r in audit}
        assert by_crit["entry"] == 1

    @pytest.mark.asyncio
    async def test_entry_just_outside_tolerance_goes_manual(self, real):
        om, db = real
        await seed_calc(db, "CALC-G2", window_seconds=300)  # entry 50000
        # Limit price +0.5 % (50250): drift 0.005 > 0.0025 → entry fails,
        # the other five criteria pass → 1 candidate, 0 full matches →
        # NEEDS_MANUAL_REVIEW (calc_correlation.py:526-532), 5/6 audit.
        oid = await seed_order(db, "O-G2", price=50250.0)
        await om._enrich_order_best_effort(order_dict("O-G2", price=50250.0))

        order = await order_row(db, oid)
        assert order["link_status"] == "NEEDS_MANUAL_REVIEW"
        assert order["calc_id"] is None
        assert_calc_link_invariant(order)
        # Candidate evaluated (NOT the zero-candidate UNPLANNED lane) and
        # entry is the single failed criterion.
        audit = await q(
            db, "SELECT criterion, matched FROM calc_match_audit "
                "WHERE order_id = ? AND calc_id = 'CALC-G2'", oid)
        assert len(audit) == 6
        by_crit = {r["criterion"]: r["matched"] for r in audit}
        assert by_crit["entry"] == 0
        for crit in ("ticker", "direction", "window", "tp", "sl"):
            assert by_crit[crit] == 1, f"{crit} unexpectedly failed"
        # Calc untouched — awaiting the operator.
        assert (await calc_row(db, "CALC-G2"))["status"] == "active"


# ── LB-T2h: one-way "BOTH" gap in hedge-keyed close-tpid recovery ──────


class TestLBT2hOneWayBothGap:
    """Documented deployment gap (plain asserts, NO xfail — the operator
    runs HEDGE mode; ws_manager.py:427-435 files the one-way shape as a
    KNOWN LATENT GAP). ⑨ _resolve_close_tpid tier-2
    (order_manager.py:2050-2061) looks up ``(symbol, fill.direction)`` in
    the map from get_open_entry_tpids_by_symbol_side (db_orders.py:
    1391-1420), which is keyed on orders.position_side. Hedge entry rows
    produce 'LONG'/'SHORT' keys; a one-way close fill arrives with
    direction="BOTH" (ws_manager.py:435: positionSide 'BOTH' is truthy so
    the LONG/SHORT inference never runs) → tier-1 (symbol,direction) scan
    and tier-2 both miss → tpid stays ""."""

    async def _seed_hedge_entry(self, db):
        # Filled hedge entry order carrying the minted tpid — the row the
        # tier-2 recovery map is built from.
        await seed_order(db, "O-H-ENTRY", symbol="ONEWAYUSDT",
                         status="filled", filled_qty=1.0,
                         avg_fill_price=50000.0, tpid="POS-H")
        await db._conn.execute(
            "UPDATE orders SET position_side = 'LONG' "
            "WHERE exchange_order_id = 'O-H-ENTRY'")
        await db._conn.commit()

    @pytest.mark.asyncio
    async def test_map_is_hedge_keyed_and_both_lookup_misses(self, real):
        om, db = real
        await self._seed_hedge_entry(db)
        # A one-way entry row (position_side='BOTH') WITH a tpid produces a
        # ('BOTH')-keyed entry — the guard at db_orders.py:1418 passes
        # ('BOTH' is truthy). The gap is not the map dropping BOTH rows;
        # it is key disjointness: hedge rows can never satisfy a BOTH fill,
        # and a real one-way entry never acquires a tpid upstream (the
        # ws_manager (symbol,direction) position lookup misses first).
        await seed_order(db, "O-H-BOTHROW", symbol="ONEWAY2USDT",
                         status="filled", filled_qty=1.0, tpid="POS-B")
        await db._conn.execute(
            "UPDATE orders SET position_side = 'BOTH' "
            "WHERE exchange_order_id = 'O-H-BOTHROW'")
        await db._conn.commit()

        tpids = await db.get_open_entry_tpids_by_symbol_side(ACCOUNT_ID)
        assert tpids == {
            ("ONEWAYUSDT", "LONG"): "POS-H",     # hedge-keyed
            ("ONEWAY2USDT", "BOTH"): "POS-B",    # what a BOTH row produces
        }

        from core.state import app_state
        saved = app_state.positions
        app_state.positions = []   # tier-1 must miss (no live positions)
        try:
            # BOTH-shaped close fill → tier-1 miss + tier-2 key miss → "".
            both_fill = fill("O-H-CLOSE", "", 1.0, fid="F-H-PROBE",
                             symbol="ONEWAYUSDT", direction="BOTH",
                             is_close=1, realized_pnl=100.0)
            assert await om._resolve_close_tpid(ACCOUNT_ID, both_fill) == ""
            # Contrast: the SAME fill shaped hedge (direction='LONG')
            # resolves via tier-2 — the gap is exactly the BOTH key.
            long_fill = dict(both_fill, direction="LONG")
            assert await om._resolve_close_tpid(
                ACCOUNT_ID, long_fill) == "POS-H"
        finally:
            app_state.positions = saved

    @pytest.mark.asyncio
    async def test_both_close_fill_strands_through_pipeline(self, real):
        om, db = real
        await self._seed_hedge_entry(db)
        await seed_order(db, "O-H-CLOSE", symbol="ONEWAYUSDT", side="SELL",
                         reduce_only=1, tp_trigger_price=None,
                         sl_trigger_price=None,
                         created_at_ms=RECENT_MS + 1500)

        from core.state import app_state
        saved = app_state.positions
        app_state.positions = []
        try:
            f_close = fill("O-H-CLOSE", "", 1.0, fid="F-H-CLOSE",
                           symbol="ONEWAYUSDT", direction="BOTH",
                           is_close=1, price=51000.0, realized_pnl=1000.0,
                           ts=RECENT_MS + 2000)
            await om._process_single_fill(ACCOUNT_ID, f_close)
        finally:
            app_state.positions = saved

        # Persisted with an EMPTY tpid — the ⑨ resolution declined (both
        # tiers missed on the BOTH key)…
        stranded = await fill_by_fid(db, "F-H-CLOSE")
        assert stranded["terminal_position_id"] == ""
        # …so the close-side attribution chain never engages: the stamp
        # (order_manager.py:2556 empty-tpid SKIP) leaves the fill without
        # calc/lifecycle, and no junction can be consulted.
        assert not stranded["calc_id"]
        assert not stranded["lifecycle_id"]
        assert await junction_rows(db) == []


# ── LB-T2i: stale-cancel snapshot SIBLING (db layer + sweep) ───────────


class TestLBT2iSnapshotCancelSibling:
    """LB-I2 (interference file) pins mark_stale_orders — the TIME path.
    This is the db-layer SIBLING: mark_stale_orders_canceled
    (db_orders.py:774, snapshot-reconciliation path, raw bulk UPDATE at
    :853-858 for orders NOT IN active_ids) strands the calc exactly the
    same way; the LB-F3 sweep releases it."""

    async def _link_then_snapshot_cancel(self, om, db):
        await seed_calc(db, "CALC-T2I", window_seconds=300)
        oid = await seed_order(db, "O-T2I")
        await om._enrich_order_best_effort(order_dict("O-T2I"))
        order = await order_row(db, oid)
        assert order["link_status"] == "LINKED"
        assert (await calc_row(db, "CALC-T2I"))["status"] == "matched"

        # Venue snapshot no longer contains O-T2I (operator canceled it
        # venue-side) → the db layer bulk-cancels it.
        n = await db.mark_stale_orders_canceled(
            ACCOUNT_ID, ["O-SOMETHING-ELSE"])
        assert n == 1
        assert (await order_row(db, oid))["status"] == "canceled"
        return oid

    @pytest.mark.asyncio
    async def test_db_snapshot_cancel_alone_strands_calc(self, real):
        """The raw db layer performs NO calc release (same asymmetry as
        the time path, order_manager.py:1205 documented gap) — pinned so
        a future db-level behavior change is noticed."""
        om, db = real
        await self._link_then_snapshot_cancel(om, db)
        assert (await calc_row(db, "CALC-T2I"))["status"] == "matched"

    @pytest.mark.asyncio
    async def test_sweep_releases_after_snapshot_cancel(self, real):
        """OrderManager.release_calcs_for_stale_cancels (the LB-F3 sweep,
        wired after all three bulk call sites) routes the stranded calc
        through the ONE release rule → released + reason-stamped
        (idempotency marker)."""
        om, db = real
        oid = await self._link_then_snapshot_cancel(om, db)

        assert await om.release_calcs_for_stale_cancels(ACCOUNT_ID) == 1
        assert (await calc_row(db, "CALC-T2I"))["status"] == "released"
        assert (await order_row(db, oid))["cancel_reason_category"] == (
            "OPERATOR")
        # Idempotent: the reason stamp marks the order processed.
        assert await om.release_calcs_for_stale_cancels(ACCOUNT_ID) == 0


# ── LB-T2j: /history/log_close route-handler drive ─────────────────────


# ── LB-T2k: funding assign (open / closed-window) + orphan ─────────────


class TestLBT2kFundingAssignOrphan:
    async def _open_linked_position(self, om, db, calc_id, eoid, tpid):
        """Real open: calc → 6/6 link → entry fill → junction + lifecycle.
        Returns the minted lifecycle_id."""
        await seed_calc(db, calc_id, window_seconds=300)
        await seed_order(db, eoid)
        await om._enrich_order_best_effort(order_dict(eoid))
        await om._process_single_fill(
            ACCOUNT_ID, fill(eoid, tpid, 1.0, fid=f"F-{eoid}"))
        junc = await junction_rows(db, tpid)
        assert len(junc) == 1 and junc[0]["calc_id"] == calc_id
        return junc[0]["lifecycle_id"]

    @staticmethod
    def _funding_income(symbol, ts_ms, amount):
        return {"symbol": symbol, "incomeType": "FUNDING_FEE",
                "income": amount, "time": ts_ms}

    @pytest.mark.asyncio
    async def test_open_position_funding_lands_in_funding_events(self, real):
        """Open-position fast path (funding_handler.py:152-165): the row
        lands in funding_events ONLY — keyed to the live tpid, with
        calc/lifecycle denormalized from the REAL junction resolver
        (om._position_primary_calc, the production wiring). Re-poll
        dedups on the synthetic venue_event_id (:211-226)."""
        om, db = real
        from core.funding_handler import handle_funding_incomes
        lifecycle = await self._open_linked_position(
            om, db, "CALC-K1", "O-K1", "POS-K1")

        positions = [SimpleNamespace(ticker="BTCUSDT", position_id="POS-K1")]
        incomes = [
            self._funding_income("BTCUSDT", RECENT_MS + 5000, -1.23),
            # Domain filter: non-funding income rows are skipped entirely.
            {"symbol": "BTCUSDT", "incomeType": "REALIZED_PNL",
             "income": 99.0, "time": RECENT_MS + 5000},
        ]
        counts = await handle_funding_incomes(
            account_id=ACCOUNT_ID, incomes=incomes, positions=positions,
            db=db, primary_calc_resolver=om._position_primary_calc)
        assert counts == {"written": 1, "deduped": 0,
                          "orphan": 0, "reconciled": 0}

        fev = await q(db, "SELECT * FROM funding_events")
        assert len(fev) == 1
        assert fev[0]["position_id"] == "POS-K1"
        assert fev[0]["calc_id"] == "CALC-K1"
        assert fev[0]["lifecycle_id"] == lifecycle
        assert fev[0]["amount"] == pytest.approx(-1.23)
        assert fev[0]["venue_event_id"] == (
            f"binance:funding:{ACCOUNT_ID}:BTCUSDT:{RECENT_MS + 5000}")
        # Open path touches NO other attribution surface.
        assert await closed_rows(db) == []

        # Idempotent re-poll: same settlement → dedup, no second row.
        counts2 = await handle_funding_incomes(
            account_id=ACCOUNT_ID, incomes=incomes, positions=positions,
            db=db, primary_calc_resolver=om._position_primary_calc)
        assert counts2 == {"written": 0, "deduped": 1,
                          "orphan": 0, "reconciled": 0}
        assert len(await q(db, "SELECT * FROM funding_events")) == 1

    @pytest.mark.asyncio
    async def test_closed_window_funding_reconciles_closed_row(self, real):
        """Deferred-funding fallback (funding_handler.py:166-188): no open
        position → find_closed_position_for_funding (db_orders.py:2496,
        settlement ts inside [entry_time_ms, exit_time_ms]) keys the row
        to the SEALED closed tpid, then reconcile_closed_position_funding
        (db_orders.py:2539) re-derives funding_fees + net_pnl on the
        final close row."""
        om, db = real
        from core.funding_handler import handle_funding_incomes
        await self._open_linked_position(om, db, "CALC-K2", "O-K2", "POS-K2")
        await seed_order(db, "O-K2C", side="SELL", reduce_only=1,
                         tp_trigger_price=None, sl_trigger_price=None,
                         created_at_ms=RECENT_MS + 1500)
        f_close = fill("O-K2C", "POS-K2", 1.0, fid="F-K2C", is_close=1,
                       price=55000.0, realized_pnl=5000.0,
                       ts=RECENT_MS + 2000)
        await om._process_single_fill(ACCOUNT_ID, f_close)
        await om._build_close_row_for_fill(ACCOUNT_ID, f_close)

        closed = (await closed_rows(db, "POS-K2"))[0]
        assert closed["calc_id"] == "CALC-K2"
        assert float(closed["funding_fees"] or 0.0) == pytest.approx(0.0)
        # Settlement strictly inside the sealed lifecycle window.
        mid_ts = (int(closed["entry_time_ms"])
                  + int(closed["exit_time_ms"])) // 2

        counts = await handle_funding_incomes(
            account_id=ACCOUNT_ID,
            incomes=[self._funding_income("BTCUSDT", mid_ts, -2.5)],
            positions=[],       # position already closed — open cache misses
            db=db, primary_calc_resolver=om._position_primary_calc)
        assert counts == {"written": 1, "deduped": 0,
                          "orphan": 0, "reconciled": 1}

        fev = await q(db, "SELECT * FROM funding_events")
        assert len(fev) == 1
        assert fev[0]["position_id"] == "POS-K2"
        # calc/lifecycle come from the SEALED closed row (== junction
        # primary at close), not a re-resolution.
        assert fev[0]["calc_id"] == closed["calc_id"]
        assert fev[0]["lifecycle_id"] == closed["lifecycle_id"]

        after = (await closed_rows(db, "POS-K2"))[0]
        assert float(after["funding_fees"]) == pytest.approx(-2.5)
        expected_net = (float(closed["realized_pnl"] or 0.0)
                        - float(closed["total_fees"] or 0.0) - 2.5)
        assert float(after["net_pnl"]) == pytest.approx(expected_net)

    @pytest.mark.asyncio
    async def test_orphan_funding_writes_nothing(self, real):
        """No open position AND no closed window for the symbol → ORPHAN
        (funding_handler.py:189-210): counted + logged, row NOT written
        anywhere — funding_events, closed_positions and the journal all
        stay untouched (observe-only spec §11[F])."""
        om, db = real
        from core.funding_handler import handle_funding_incomes
        counts = await handle_funding_incomes(
            account_id=ACCOUNT_ID,
            incomes=[self._funding_income("GHOSTUSDT", RECENT_MS + 5000,
                                          -0.77)],
            positions=[], db=db,
            primary_calc_resolver=om._position_primary_calc)
        assert counts == {"written": 0, "deduped": 0,
                          "orphan": 1, "reconciled": 0}
        assert await q(db, "SELECT * FROM funding_events") == []
        assert await closed_rows(db) == []


# ── LB-T2l: snapshot-recovery — only the self-persist leg was unpinned ─


class TestLBT2lRecoverySelfPersistLeg:
    """Coverage check (tranche mandate): the unminted-snapshot recovery
    itself is ALREADY asserted in tests/test_linkage_binance_ws.py —
    test_snapshot_position_recovers_tpid_and_links (:513: empty
    position_id → tpid re-derived from the entry order via
    get_open_entry_tpids_by_symbol_side, junction enrich stamps calc_id
    + non-empty badge) and test_snapshot_no_entry_order_stays_unlinked
    (:559 negative guard). NOT re-implemented here.

    The one leg no test pinned: the recovery's SELF-PERSIST claim
    (order_manager.py:2678-2680 — "setting it here self-persists:
    DataCache._preserve_metadata carries a now-present position_id
    across the next snapshot rebuild"). position_id is NOT in
    _PRESERVE_FIELDS (data_cache.py:64-85); the carry is the dedicated
    branch at data_cache.py:226-228, previously untested (only calc_id's
    _PRESERVE_FIELDS carry is pinned, test_phase2_junction.py:801)."""

    @pytest.mark.asyncio
    async def test_recovered_tpid_survives_snapshot_rebuild(self):
        from core.data_cache import DataCache
        from core.state import PositionInfo
        old = PositionInfo(ticker="BTCUSDT", direction="LONG",
                           position_id="binance:BTCUSDT:LONG:1775300000000")
        # REST snapshot rebuild delivers the position WITHOUT an id (the
        # recovery precondition would otherwise recur every refresh).
        new = PositionInfo(ticker="BTCUSDT", direction="LONG")
        DataCache._preserve_metadata(new, old)
        assert new.position_id == "binance:BTCUSDT:LONG:1775300000000"

    @pytest.mark.asyncio
    async def test_upstream_id_not_clobbered_by_preserve(self):
        # Guard rail: when the rebuild DOES carry an id (plugin-sourced),
        # preserve must not overwrite it with the stale one.
        from core.data_cache import DataCache
        from core.state import PositionInfo
        old = PositionInfo(ticker="BTCUSDT", direction="LONG",
                           position_id="STALE-OLD")
        new = PositionInfo(ticker="BTCUSDT", direction="LONG",
                           position_id="FRESH-NEW")
        DataCache._preserve_metadata(new, old)
        assert new.position_id == "FRESH-NEW"
