"""Linkage attribution battery — disagreement scenarios (LB-D1..D7).

Spec: docs/design/linkage_battery_plan.md §2 (scenario matrix) + §3
(conventions) + §4 (triage). Fixture idiom copied from
tests/test_linkage_battery_e2e.py (the reference file).

Each scenario drives the REAL pipeline entry points against a tempfile DB
and asserts the attribution OUTPUTS (DB rows). Scenarios assert DESIRED
semantics; verified divergences are xfail(strict=True) with the mechanism
in the reason (plan §4 — triage before fixing). No TestClient (gotcha
LOW-023); the +2s close-row timer never fires in-test — the row build is
awaited directly.
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


@pytest.fixture
def live_positions():
    """Snapshot/restore app_state.positions (plan §3 app_state hygiene;
    the test_correlation_log_attribution.py:1241 _restore_positions
    pattern). Yields the app_state with an EMPTY positions list."""
    from core.state import app_state

    snap = list(app_state.positions)
    app_state.positions = []
    yield app_state
    app_state.positions = snap


def _pos_info(ticker="BTCUSDT", direction="LONG", tpid="POS-1", **kw):
    """Minimal live PositionInfo (test_correlation_log_attribution.py:1228)."""
    from core.state import PositionInfo

    base = dict(
        ticker=ticker, direction=direction, contract_amount=1.0,
        average=50000.0, fair_price=50000.0, individual_unrealized=0.0,
        position_value_usdt=50000.0,
        entry_timestamp="2026-06-12T00:00:00+00:00",
        sector="", position_id=tpid,
    )
    base.update(kw)
    return PositionInfo(**base)


# ── LB-D1: orders.calc_id single-winner ────────────────────────────────
#
# Matcher links the entry; bracket legs inherit via
# _propagate_bracket_calc_id (order_manager.py:705, WHERE calc_id IS NULL
# guard :884); a late manual_link returns "already_linked"
# (link_actions.py:150-152, before any write). Nothing overwrites an
# existing calc_id anywhere.


class TestLBD1SingleWinner:
    @pytest.mark.asyncio
    async def test_bracket_inherit_then_manual_link_cannot_overwrite(self, real):
        om, db = real
        await seed_calc(db, "CALC-D1", window_seconds=300)
        oid_entry = await seed_order(db, "O-D1")
        # Protective legs placed "together" (within the 2s detect window,
        # bracket_detection.py:54): TP + SL, reduce-only protective types.
        oid_tp = await seed_order(
            db, "O-D1-TP", side="SELL", order_type="take_profit_market",
            reduce_only=1, price=0.0, tp_trigger_price=55000.0,
            sl_trigger_price=None, created_at_ms=RECENT_MS + 100)
        oid_sl = await seed_order(
            db, "O-D1-SL", side="SELL", order_type="stop_market",
            reduce_only=1, price=0.0, tp_trigger_price=None,
            sl_trigger_price=48000.0, created_at_ms=RECENT_MS + 200)

        # 1. Matcher links the ENTRY only (protective legs early-return
        #    in the matcher — order_manager.py:718-721 docstring).
        await om._enrich_order_best_effort(order_dict("O-D1"))
        entry = await order_row(db, oid_entry)
        assert entry["calc_id"] == "CALC-D1"
        assert entry["link_status"] == "LINKED"
        assert_calc_link_invariant(entry)
        assert (await calc_row(db, "CALC-D1"))["status"] == "matched"
        for oid in (oid_tp, oid_sl):
            leg = await order_row(db, oid)
            assert leg["calc_id"] is None  # not yet inherited

        # 2. Bracket inheritance: protective legs inherit the entry's calc
        #    (calc_id + LINKED; lifecycle_id deliberately NOT stamped —
        #    documented scope deviation order_manager.py:735-744).
        await om._propagate_bracket_calc_id(ACCOUNT_ID, "BTCUSDT")
        for oid in (oid_tp, oid_sl):
            leg = await order_row(db, oid)
            assert leg["calc_id"] == "CALC-D1"
            assert leg["link_status"] == "LINKED"
            assert leg["lifecycle_id"] is None
            assert_calc_link_invariant(leg)

        # 3. Idempotency: a second propagation pass no-ops (the
        #    WHERE calc_id IS NULL guard, order_manager.py:884).
        await om._propagate_bracket_calc_id(ACCOUNT_ID, "BTCUSDT")
        for oid in (oid_entry, oid_tp, oid_sl):
            assert (await order_row(db, oid))["calc_id"] == "CALC-D1"

        # 4. Late manual_link with a competing calc: single-winner —
        #    "already_linked" before any write (link_actions.py:150-152).
        await seed_calc(db, "CALC-D1B", effective_entry=51000.0,
                        tp_price=56000.0, sl_price=49000.0,
                        window_seconds=300)
        from core.link_actions import manual_link_order
        assert await manual_link_order(
            ACCOUNT_ID, oid_entry, "CALC-D1B") == "already_linked"
        assert await manual_link_order(
            ACCOUNT_ID, oid_tp, "CALC-D1B") == "already_linked"
        assert await manual_link_order(
            ACCOUNT_ID, oid_sl, "CALC-D1B") == "already_linked"

        # Nothing overwrote: all three rows still carry the first winner,
        # the invariant holds everywhere, and the competing calc was
        # never touched (still active — the impl returned pre-lookup).
        for oid in (oid_entry, oid_tp, oid_sl):
            row = await order_row(db, oid)
            assert row["calc_id"] == "CALC-D1"
            assert row["link_status"] == "LINKED"
            assert_calc_link_invariant(row)
        assert (await calc_row(db, "CALC-D1B"))["status"] == "active"
        assert (await calc_row(db, "CALC-D1"))["status"] == "matched"


# ── LB-D2: scale-in — parent-rule vs primary-rule split (documented) ───
#
# Calc A contributes qty 1, calc B qty 3 to the SAME position. Primary =
# most-contributing (B; _position_primary_calc order_manager.py:2058 via
# _most_contributing_calc_id :2091). The close FILL and the close ROW take
# the primary (B; :2503-2517 and :3291-3295); A's OPENING fill keeps its
# parent order's calc (A; enrich_fill parent rule). Expected PASS — this
# scenario documents the split, it is not a divergence.


class TestLBD2ScaleInPrimaryVsParent:
    @pytest.mark.asyncio
    async def test_close_takes_primary_opening_fills_keep_parent(self, real):
        om, db = real
        await seed_calc(db, "CALC-A2", status="matched", window_seconds=300)
        await seed_calc(db, "CALC-B2", status="matched", window_seconds=300)
        oid_a = await seed_order(db, "O-D2A", calc_id="CALC-A2",
                                 link_status="LINKED")
        oid_b = await seed_order(db, "O-D2B", calc_id="CALC-B2",
                                 link_status="LINKED",
                                 created_at_ms=RECENT_MS + 500)

        await om._process_single_fill(
            ACCOUNT_ID, fill("O-D2A", "POS-D2", 1.0, fid="F-D2A",
                             ts=RECENT_MS + 1000))
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-D2B", "POS-D2", 3.0, fid="F-D2B",
                             ts=RECENT_MS + 1200, price=50200.0))

        junc = await junction_rows(db, "POS-D2")
        assert len(junc) == 2
        by_calc = {r["calc_id"]: r for r in junc}
        assert by_calc["CALC-A2"]["contributed_qty"] == pytest.approx(1.0)
        assert by_calc["CALC-B2"]["contributed_qty"] == pytest.approx(3.0)
        lifecycle = by_calc["CALC-A2"]["lifecycle_id"]
        assert lifecycle and by_calc["CALC-B2"]["lifecycle_id"] == lifecycle

        # Opening fills: parent rule — each keeps ITS order's calc.
        assert (await fill_by_fid(db, "F-D2A"))["calc_id"] == "CALC-A2"
        assert (await fill_by_fid(db, "F-D2B"))["calc_id"] == "CALC-B2"

        # Close the full 4.0 → close fill stamped with the PRIMARY (B).
        await seed_order(db, "O-D2C", side="SELL", reduce_only=1,
                         tp_trigger_price=None, sl_trigger_price=None,
                         created_at_ms=RECENT_MS + 1500)
        f_close = fill("O-D2C", "POS-D2", 4.0, fid="F-D2C", is_close=1,
                       price=52000.0, realized_pnl=7400.0,
                       ts=RECENT_MS + 2000)
        await om._process_single_fill(ACCOUNT_ID, f_close)
        stamped = await fill_by_fid(db, "F-D2C")
        assert stamped["calc_id"] == "CALC-B2"      # primary rule
        assert stamped["lifecycle_id"] == lifecycle

        # A's opening fill is NOT rewritten by the close-side stamp.
        assert (await fill_by_fid(db, "F-D2A"))["calc_id"] == "CALC-A2"

        # Close row: calc = primary (B), lifecycle shared.
        await om._build_close_row_for_fill(ACCOUNT_ID, f_close)
        closed = await closed_rows(db, "POS-D2")
        assert len(closed) == 1
        assert closed[0]["calc_id"] == "CALC-B2"
        assert closed[0]["lifecycle_id"] == lifecycle
        # Both contributing calcs complete on the final close — the row
        # credits B, completion covers A too (parent-vs-primary split).
        assert (await calc_row(db, "CALC-A2"))["status"] == (
            "completed_via_position")
        assert (await calc_row(db, "CALC-B2"))["status"] == (
            "completed_via_position")


# ── LB-D3: ⑨ same-slot reopen hazard ───────────────────────────────────
#
# POS-1 (BTCUSDT LONG) fully closed; POS-2 live on the SAME
# (symbol, direction) slot. A late POS-1 close fill arrives with an empty
# tpid but with exchange_order_id = POS-1's close order — the parent-order
# identity that pins the correct instance is IN the DB
# (orders.terminal_position_id = POS-1), yet tier-1 resolves by
# (symbol, direction) against app_state.positions only.


class TestLBD3SameSlotReopen:
    async def _drive_late_close_fill(self, om, db, live_positions,
                                     close_order_tpid="POS-1"):
        """POS-1 fully closed, POS-2 live on the same slot; return the
        tpid ⑨ resolves for a late POS-1 close fill arriving with an
        empty tpid. close_order_tpid controls whether POS-1's close
        order carries its stamp (the LB-F5 tier-0 source)."""
        # POS-1 history: entry + close orders persisted.
        await seed_order(db, "O-D3E", status="filled", filled_qty=1.0,
                         avg_fill_price=50000.0, tpid="POS-1")
        await seed_order(db, "O-D3C", side="SELL", reduce_only=1,
                         status="filled", filled_qty=1.0,
                         tp_trigger_price=None, sl_trigger_price=None,
                         tpid=close_order_tpid,
                         created_at_ms=RECENT_MS + 1000)
        # POS-2: live on the same (symbol, direction) slot.
        await seed_order(db, "O-D3E2", tpid="POS-2",
                         created_at_ms=RECENT_MS + 5000)
        live_positions.positions = [_pos_info(tpid="POS-2")]

        # Late POS-1 close fill: empty tpid, parent = POS-1's close order.
        f_late = fill("O-D3C", "", 1.0, fid="F-D3C", is_close=1,
                      price=51000.0, realized_pnl=1000.0,
                      ts=RECENT_MS + 2000)
        return await om._resolve_close_tpid(ACCOUNT_ID, f_late)

    @pytest.mark.asyncio
    async def test_late_close_fill_resolves_to_its_own_position(
            self, real, live_positions):
        # LB-F5 FIXED (was xfail): ⑨ tier-0 (parent_order) consults the
        # fill's own exchange_order_id → orders.terminal_position_id
        # BEFORE the (symbol, direction) heuristics — the late close
        # fill resolves to POS-1 even with POS-2 live on the slot.
        om, db = real
        resolved = await self._drive_late_close_fill(om, db, live_positions)
        assert resolved == "POS-1"

    @pytest.mark.asyncio
    async def test_pin_heuristic_fallback_without_parent_stamp(
            self, real, live_positions):
        # PIN (residual gap, reconciler-relevant): when the close order
        # carries NO tpid (pre-LB-F5 rows; stamp lost), tier-0 has
        # nothing and tier-1 still resolves the live same-slot instance
        # (POS-2). The heuristic tail exists until identity has one
        # owner — documents WHY tier-0's stamp source matters.
        om, db = real
        resolved = await self._drive_late_close_fill(
            om, db, live_positions, close_order_tpid="")
        assert resolved == "POS-2"

    @pytest.mark.asyncio
    async def test_close_order_stamp_end_to_end(self, real, live_positions):
        # LB-F5 stamp half: the FIRST tpid-carrying closing fill (ws
        # stamps it from the then-live position) copies its tpid onto
        # the parent close order (empty-only guard); a LATE sibling fill
        # then resolves via tier-0 even after the slot reopened.
        from tests.linkage_battery_helpers import order_by_eoid
        om, db = real
        await seed_order(db, "O-D3E", status="filled", filled_qty=1.0,
                         avg_fill_price=50000.0, tpid="POS-1")
        await seed_order(db, "O-D3C2", side="SELL", reduce_only=1,
                         tp_trigger_price=None, sl_trigger_price=None,
                         created_at_ms=RECENT_MS + 1000)  # tpid EMPTY

        # First partial close fill arrives WITH the tpid (POS-1 live then).
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-D3C2", "POS-1", 0.5, fid="F-D3C2A",
                             is_close=1, price=50500.0, realized_pnl=250.0,
                             ts=RECENT_MS + 1500))
        assert (await order_by_eoid(db, "O-D3C2"))[
            "terminal_position_id"] == "POS-1"

        # POS-1 now gone; POS-2 live on the same slot; the late sibling
        # fill (empty tpid) resolves via tier-0 → POS-1, not POS-2.
        live_positions.positions = [_pos_info(tpid="POS-2")]
        f_late = fill("O-D3C2", "", 0.5, fid="F-D3C2B", is_close=1,
                      price=51000.0, realized_pnl=250.0,
                      ts=RECENT_MS + 2000)
        assert await om._resolve_close_tpid(ACCOUNT_ID, f_late) == "POS-1"


# ── LB-D4: offline rebuild close-calc rule = the owner's §3.2 rule ─────
#
# T3 scenario (battery plan §2 row LB-D4, owed since the T2 tranche;
# shipped at R4). The offline rebuild lane
# (db_orders.rebuild_closed_positions_for_symbol →
# position_grouping._build_row) historically derived the close row's
# calc from the EARLIEST opening fill with a calc_id, while the live
# builder uses the junction PRIMARY (§3.2 most-contributing) — a
# consumer re-deriving identity with a DIFFERENT rule. R4: the grouper
# delegates to the owner's _most_contributing_calc_id over the opening
# fills (same rule; the evidence is fills instead of junction rows, and
# junction contributed_qty IS SUM(fill qty) per calc, so the two
# converge whenever opening fills carry their calc stamps).


class TestLBD4RebuildCloseCalcRule:
    @pytest.mark.asyncio
    async def test_rebuild_close_calc_follows_owner_primary_rule(self, real):
        om, db = real
        # The LB-D2 shape driven through the REAL pipeline: calc A
        # contributes 1.0, calc B 3.0 (fills carry their parent calc
        # stamps: A on F-D4A, B on F-D4B — pinned by LB-D2 above).
        await seed_calc(db, "CALC-A4", status="matched", window_seconds=300)
        await seed_calc(db, "CALC-B4", status="matched", window_seconds=300)
        await seed_order(db, "O-D4A", calc_id="CALC-A4",
                         link_status="LINKED")
        await seed_order(db, "O-D4B", calc_id="CALC-B4",
                         link_status="LINKED",
                         created_at_ms=RECENT_MS + 500)
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-D4A", "POS-D4", 1.0, fid="F-D4A",
                             ts=RECENT_MS + 1000))
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-D4B", "POS-D4", 3.0, fid="F-D4B",
                             ts=RECENT_MS + 1200, price=50200.0))
        await seed_order(db, "O-D4C", side="SELL", reduce_only=1,
                         tp_trigger_price=None, sl_trigger_price=None,
                         created_at_ms=RECENT_MS + 1500)
        f_close = fill("O-D4C", "POS-D4", 4.0, fid="F-D4C", is_close=1,
                       price=52000.0, realized_pnl=7400.0,
                       ts=RECENT_MS + 2000)
        await om._process_single_fill(ACCOUNT_ID, f_close)
        await om._build_close_row_for_fill(ACCOUNT_ID, f_close)
        live = await closed_rows(db, "POS-D4")
        assert len(live) == 1
        assert live[0]["calc_id"] == "CALC-B4"   # live rule: junction primary

        # Drive the db_orders rebuild lane over the same fills. It
        # DELETEs the live row and re-groups from fills under a
        # deterministic rebuilt: tpid.
        res = await db.rebuild_closed_positions_for_symbol(
            ACCOUNT_ID, "BTCUSDT")
        assert res["deleted"] == 1
        assert res["rebuilt"] == 1

        rows = await closed_rows(db)
        assert len(rows) == 1
        row = rows[0]
        assert row["terminal_position_id"].startswith(
            "rebuilt:BTCUSDT:LONG:")
        assert row["source"] == "rebuilt_from_fills"
        # THE LB-D4 assert: the rebuilt row takes the §3.2 primary (B,
        # the most-contributing calc) — pre-R4 the earliest-fill rule
        # flipped it back to A.
        assert row["calc_id"] == "CALC-B4"


# ── LB-D5: junction dual-key (HA-42-adjacent) ──────────────────────────
#
# Entry order carries tpid=POS-A; its FIRST fill arrives tpid="" (Defect-7
# order-fallback keys the junction POS-A, order_manager.py:2204-2206); the
# SECOND fill of the SAME order arrives tpid=POS-B (fill tpid wins,
# :2175). One economic open → junction keyed under TWO position_ids, each
# minting its own lifecycle (:2266); the Defect-1 back-fill (:2221-2226)
# only fills an EMPTY order tpid, so nothing reconciles the split.


class TestLBD5JunctionDualKey:
    async def _drive_mixed_tpid_fills(self, om, db):
        """One linked entry order (tpid=POS-A); fill 1 arrives tpid='',
        fill 2 arrives tpid='POS-B'. Returns the junction rows."""
        await seed_calc(db, "CALC-D5", status="matched", window_seconds=300)
        await seed_order(db, "O-D5", calc_id="CALC-D5",
                         link_status="LINKED", tpid="POS-A")

        # First fill: tpid empty → Defect-7 order-fallback keys POS-A.
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-D5", "", 1.0, fid="F-D5A",
                             ts=RECENT_MS + 1000))
        assert {r["position_id"] for r in await junction_rows(db)} == {
            "POS-A"}

        # Second fill, SAME order: tpid=POS-B (e.g. the mint landed
        # between the two fills with a different id than the order stash).
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-D5", "POS-B", 1.0, fid="F-D5B",
                             ts=RECENT_MS + 1100))
        return await junction_rows(db)

    @pytest.mark.asyncio
    async def test_pin_migration_unifies_key_and_restamps(self, real):
        # LB-F6 FIXED (R2): the second fill's canonical key (POS-B)
        # triggers the migration pass — the POS-A row is re-keyed/merged,
        # the first fill's tpid is re-stamped, and the order's stale
        # stash is corrected in the same coherence pass. Pins the full
        # fixed shape beyond the xfail-twin's key/lifecycle asserts.
        om, db = real
        junc = await self._drive_mixed_tpid_fills(om, db)
        assert {r["position_id"] for r in junc} == {"POS-B"}
        assert len({r["lifecycle_id"] for r in junc}) == 1
        assert sum(r["contributed_qty"] for r in junc) == pytest.approx(2.0)
        # Fill re-stamp (plan §2.1.3): the pre-migration fill follows.
        assert (await fill_by_fid(db, "F-D5A"))[
            "terminal_position_id"] == "POS-B"
        # Order-stash correction (R2 coherence extension): the dead key
        # no longer feeds ⑨ tier-0 / the replay guard.
        from tests.linkage_battery_helpers import order_by_eoid
        assert (await order_by_eoid(db, "O-D5"))[
            "terminal_position_id"] == "POS-B"

    @pytest.mark.asyncio
    async def test_one_economic_open_keys_one_junction(self, real):
        # LB-F6 FIXED (R2, was strict-xfail): one economic open → ONE
        # junction key, ONE lifecycle (key migration in
        # position_identity.link_position_calc_on_open).
        om, db = real
        junc = await self._drive_mixed_tpid_fills(om, db)
        assert len({r["position_id"] for r in junc}) == 1
        assert len({r["lifecycle_id"] for r in junc}) == 1

    @pytest.mark.asyncio
    async def test_pin_migration_never_drags_rebuilt_rows(self, real):
        """R5 pin (holistic-audit LOW-3): the R2 key migration is
        structurally fenced off the offline-rebuild namespaces — a
        script-written junction row keyed rebuilt:/bf: for the same
        (calc, order) is never merged/re-keyed onto the live canonical
        key (operator tooling owns its rows), while the live fill still
        forms its own row normally."""
        om, db = real
        await seed_calc(db, "CALC-D5R", status="matched", window_seconds=300)
        oid = await seed_order(db, "O-D5R", calc_id="CALC-D5R",
                               link_status="LINKED")
        # Script-written junction row under the rebuilt: namespace.
        await db.upsert_position_calc_link({
            "position_id": "rebuilt:BTCUSDT:LONG:9", "calc_id": "CALC-D5R",
            "order_id": oid, "account_id": ACCOUNT_ID,
            "contributed_qty": 5.0, "first_fill_ts": RECENT_MS - 1000,
            "last_fill_ts": RECENT_MS - 1000, "lifecycle_id": "L-REBUILT",
        })
        # Live fill carrying its own tpid → would trigger migration of
        # any stale (calc, order) row; the rebuilt row must be skipped.
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-D5R", "POS-D5R", 1.0, fid="F-D5R",
                             ts=RECENT_MS + 1000))
        junc = {r["position_id"]: r for r in await junction_rows(db)
                if r["calc_id"] == "CALC-D5R"}
        assert set(junc) == {"rebuilt:BTCUSDT:LONG:9", "POS-D5R"}
        assert junc["rebuilt:BTCUSDT:LONG:9"]["contributed_qty"] == (
            pytest.approx(5.0))                      # untouched
        assert junc["rebuilt:BTCUSDT:LONG:9"]["lifecycle_id"] == "L-REBUILT"
        assert junc["POS-D5R"]["contributed_qty"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_pin_mirror_ordering_gate_and_convergence(self, real):
        """R2-audit MAJOR-1 direction gate: a STALE stash must never pull
        a correct fills-derived row onto the dead key. Mirror ordering:
        stash=POS-A (stale), F1 carries the true mint POS-B, F2 arrives
        tpid='' (Defect-7 derives POS-A). The gate blocks migration on
        the stash-derived event — POS-B's row and F1's tpid stay intact;
        the bounded POS-A residue row converges on the NEXT
        tpid-carrying event (R3 retro-reconcile input for the no-later-
        event tail)."""
        from tests.linkage_battery_helpers import order_by_eoid
        om, db = real
        await seed_calc(db, "CALC-D5M", status="matched", window_seconds=300)
        await seed_order(db, "O-D5M", calc_id="CALC-D5M",
                         link_status="LINKED", tpid="POS-A")

        # F1: the true mint POS-B (junction keys POS-B; stash survives).
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-D5M", "POS-B", 1.0, fid="F-D5M1",
                             ts=RECENT_MS + 1000))
        # F2: empty tpid → Defect-7 stash fallback POS-A. The gate must
        # NOT migrate POS-B → POS-A; F1's fill tpid must stay POS-B.
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-D5M", "", 1.0, fid="F-D5M2",
                             ts=RECENT_MS + 1100))
        junc = {r["position_id"]: r for r in await junction_rows(db)}
        assert junc["POS-B"]["contributed_qty"] == pytest.approx(1.0)
        assert (await fill_by_fid(db, "F-D5M1"))[
            "terminal_position_id"] == "POS-B"      # NOT mutated
        assert junc["POS-A"]["contributed_qty"] == pytest.approx(1.0)

        # F3 carries POS-B again → migration fires (fills-derived key):
        # the POS-A residue merges into POS-B; fills + stash converge.
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-D5M", "POS-B", 1.0, fid="F-D5M3",
                             ts=RECENT_MS + 1200))
        junc = await junction_rows(db)
        assert [(r["position_id"], r["calc_id"]) for r in junc] == [
            ("POS-B", "CALC-D5M")]
        assert junc[0]["contributed_qty"] == pytest.approx(3.0)
        assert (await fill_by_fid(db, "F-D5M2"))[
            "terminal_position_id"] == "POS-B"      # residue re-stamped
        assert (await order_by_eoid(db, "O-D5M"))[
            "terminal_position_id"] == "POS-B"      # stash corrected


# ── LB-D6: closed_positions REPLACE asymmetry — LB-F7 FIXED (R4) ───────
#
# insert_closed_position binds calc_id UNCONDITIONALLY (documented-
# intentional T234 asymmetry) while lifecycle_id carried forward from
# the existing row when the caller omits it — so a REPLACE that REBOUND
# the calc kept the OLD lifecycle → a (calc, lifecycle) pair that never
# coexisted. R4: the carry-forward is PAIR-GATED on calc_id — it fires
# only when the calc is unchanged (the T232 preserve case); a calc
# rebind takes the REPLACing writer's whole pair.


class TestLBD6ReplaceAsymmetry:
    def _row(self, calc_id, lifecycle_id):
        return {
            "account_id": ACCOUNT_ID,
            "terminal_position_id": "POS-D6",
            "symbol": "BTCUSDT",
            "direction": "LONG",
            "quantity": 1.0,
            "entry_price": 50000.0,
            "exit_price": 51000.0,
            "entry_time_ms": RECENT_MS,
            "exit_time_ms": RECENT_MS + 5000,   # same REPLACE key both times
            "realized_pnl": 1000.0,
            "calc_id": calc_id,
            "lifecycle_id": lifecycle_id,
        }

    @pytest.mark.asyncio
    async def test_pin_carry_forward_when_calc_unchanged(self, real):
        # R4 pin (reframed from the pre-R4 mixed-identity pin, which
        # asserted (CALC-B, L1)): the T232 lifecycle preserve still fires
        # when the calc is UNCHANGED — a recompute that re-derives the
        # SAME calc and omits lifecycle (the backfill re-run shape) keeps
        # the stamped lifecycle. Guards the R4 pair gate against
        # over-fixing the exact case the preserve exists for.
        _om, db = real
        assert await db.insert_closed_position(self._row("CALC-A", "L1"))
        assert await db.insert_closed_position(self._row("CALC-A", None))
        rows = await closed_rows(db, "POS-D6")
        assert len(rows) == 1
        assert (rows[0]["calc_id"], rows[0]["lifecycle_id"]) == (
            "CALC-A", "L1")

    @pytest.mark.asyncio
    async def test_replace_keeps_identity_pair_coherent(self, real):
        # LB-F7 FIXED (R4, was strict-xfail): the lifecycle carry-forward
        # in insert_closed_position is PAIR-GATED on calc_id — a REPLACE
        # that REBINDS the calc takes the REPLACing writer's whole pair.
        _om, db = real
        assert await db.insert_closed_position(self._row("CALC-A", "L1"))
        assert await db.insert_closed_position(self._row("CALC-B", None))

        rows = await closed_rows(db, "POS-D6")
        assert len(rows) == 1  # REPLACE on (account, tpid, exit_time_ms)
        got = (rows[0]["calc_id"], rows[0]["lifecycle_id"])
        # The row carries the REPLACing writer's coherent identity pair —
        # calc B with the lifecycle THAT writer supplied (None) — not
        # calc B welded to calc A's carried-forward lifecycle.
        assert got == ("CALC-B", None), (
            f"mixed identity after REPLACE: {got} — calc rebound to B "
            "while A's lifecycle L1 was carried forward")


# ── LB-D7: badge live-vs-history divergence (BY DESIGN, 32df20e) ───────
#
# Live badge = CURRENT state (deviation_badge_level, state.py:169 —
# sl_removed reflects "now"); history badge = sticky WORST
# (stamp_close_deviation_badges, state.py:225-231 — persisted
# tpsl_amended level: 1 amended/yellow, 2 SL-removed/red). Plain asserts
# pin the actual behavior; no xfail — the divergence is intentional.


class TestLBD7BadgeLiveVsHistory:
    YELLOW, RED = 10.0, 25.0

    def test_live_badge_tracks_current_state(self):
        from core.state import deviation_badge_level

        common = dict(has_calc=True, size_delta_pct=0.0, amendment_count=0,
                      yellow_pct=self.YELLOW, red_pct=self.RED)
        # While the SL is removed: live red (unprotected NOW).
        assert deviation_badge_level(
            **common, tpsl_amended=True, sl_removed=True) == "red"
        # SL re-added: live drops to yellow — the drift history still
        # shows via tpsl_amended, but the unprotected state is gone.
        assert deviation_badge_level(
            **common, tpsl_amended=True, sl_removed=False) == "yellow"
        # Fully on-plan now: green (live carries no memory of its own).
        assert deviation_badge_level(
            **common, tpsl_amended=False, sl_removed=False) == "green"

    def test_history_badge_is_sticky_worst(self):
        from core.state import stamp_close_deviation_badges

        rows = [
            {"calc_id": "C-RED", "tpsl_amended": 2,      # SL removed once
             "size_delta_pct": 0.0, "cumulative_amendment_count": 0},
            {"calc_id": "C-YEL", "tpsl_amended": 1,      # amended once
             "size_delta_pct": 0.0, "cumulative_amendment_count": 0},
            {"calc_id": "C-GRN", "tpsl_amended": None,   # never amended
             "size_delta_pct": 0.0, "cumulative_amendment_count": 0},
            {"calc_id": None, "tpsl_amended": 2},        # unlinked → ""
        ]
        stamp_close_deviation_badges(
            rows, yellow_pct=self.YELLOW, red_pct=self.RED)
        assert rows[0]["deviation_badge"] == "red"     # sticky worst
        assert rows[1]["deviation_badge"] == "yellow"
        assert rows[2]["deviation_badge"] == "green"
        assert rows[3]["deviation_badge"] == ""        # no plan ≠ violated

    def test_divergence_same_facts_live_yellow_history_red(self):
        """The 32df20e design split on ONE economic story: SL removed
        mid-life, then re-added before close. Live (now) = yellow;
        the persisted close row (worst level 2) = red. Both correct —
        live answers "how is it NOW", history answers "what happened"."""
        from core.state import (
            deviation_badge_level,
            stamp_close_deviation_badges,
        )

        live = deviation_badge_level(
            has_calc=True, size_delta_pct=0.0, amendment_count=0,
            yellow_pct=self.YELLOW, red_pct=self.RED,
            tpsl_amended=True, sl_removed=False)   # re-added → not-red now
        hist_row = {"calc_id": "C-D7", "tpsl_amended": 2,
                    "size_delta_pct": 0.0, "cumulative_amendment_count": 0}
        stamp_close_deviation_badges(
            [hist_row], yellow_pct=self.YELLOW, red_pct=self.RED)

        assert live == "yellow"
        assert hist_row["deviation_badge"] == "red"
        assert live != hist_row["deviation_badge"]  # the designed split
