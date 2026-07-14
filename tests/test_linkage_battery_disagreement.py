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
    async def _drive_late_close_fill(self, om, db, live_positions):
        """POS-1 fully closed (orders persisted with its tpid), POS-2 live
        on the same slot; return the tpid ⑨ resolves for a late POS-1
        close fill arriving with an empty tpid."""
        # POS-1 history: entry + close orders persisted with POS-1's tpid.
        await seed_order(db, "O-D3E", status="filled", filled_qty=1.0,
                         avg_fill_price=50000.0, tpid="POS-1")
        await seed_order(db, "O-D3C", side="SELL", reduce_only=1,
                         status="filled", filled_qty=1.0,
                         tp_trigger_price=None, sl_trigger_price=None,
                         tpid="POS-1", created_at_ms=RECENT_MS + 1000)
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
    async def test_pin_current_tier1_resolves_to_live_slot(
            self, real, live_positions):
        # PIN (current behavior): tier-1 (symbol,direction) wins → the
        # live POS-2. Guards the xfail twin against fixture regressions —
        # if this pin breaks, the xfail's failure mode changed too.
        om, db = real
        resolved = await self._drive_late_close_fill(om, db, live_positions)
        assert resolved == "POS-2"

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        strict=True,
        reason="LB-D3: _resolve_close_tpid tier-1 (order_manager.py:1985-"
               "1989) scans app_state.positions by (symbol, direction) "
               "with no parent-order identity check — the fill's "
               "exchange_order_id → orders.terminal_position_id (POS-1) "
               "is never consulted, so a late close fill of the CLOSED "
               "POS-1 resolves to the live same-slot POS-2 (wrong "
               "instance; misattributes the close to POS-2's junction).")
    async def test_late_close_fill_resolves_to_its_own_position(
            self, real, live_positions):
        om, db = real
        resolved = await self._drive_late_close_fill(om, db, live_positions)

        # DESIRED: parent-order identity wins — the fill belongs to POS-1.
        assert resolved == "POS-1", (
            f"late close fill resolved to {resolved!r} — the live "
            "same-slot position, not the closed position the fill's "
            "parent order belongs to")


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
    async def test_pin_current_dual_key_forms(self, real):
        # PIN (current behavior): the mixed-tpid fills split the junction
        # under both keys with two minted lifecycles. Guards the xfail
        # twin against fixture regressions.
        om, db = real
        junc = await self._drive_mixed_tpid_fills(om, db)
        assert {r["position_id"] for r in junc} == {"POS-A", "POS-B"}
        assert len({r["lifecycle_id"] for r in junc}) == 2

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        strict=True,
        reason="LB-D5: _link_position_calc_on_open keys the junction on "
               "fill.terminal_position_id when present (order_manager.py"
               ":2175) and falls back to the order's tpid only when the "
               "fill's is empty (:2204-2206) — two fills of ONE entry "
               "order carrying '' then 'POS-B' key TWO junction rows "
               "(POS-A via Defect-7 fallback, POS-B via the fill), each "
               "with its own minted lifecycle (:2266); the Defect-1 "
               "back-fill (:2221-2226) never rewrites a non-empty order "
               "tpid, so the dual key persists (HA-42-adjacent "
               "double-count shape).")
    async def test_one_economic_open_keys_one_junction(self, real):
        om, db = real
        junc = await self._drive_mixed_tpid_fills(om, db)
        keys = {r["position_id"] for r in junc}
        lifecycles = {r["lifecycle_id"] for r in junc}
        # DESIRED: one economic open → ONE junction key, ONE lifecycle.
        assert len(keys) == 1, (
            f"one entry order's fills keyed the junction under {keys} — "
            "two position identities for one economic open")
        assert len(lifecycles) == 1


# ── LB-D6: closed_positions REPLACE asymmetry ──────────────────────────
#
# insert_closed_position (db_orders.py:299) binds calc_id UNCONDITIONALLY
# (:536; documented-intentional, :365-373) while lifecycle_id carries
# forward from the existing row when the caller omits it (:420 +
# :462-465). A REPLACE that rebinds the calc therefore keeps the OLD
# lifecycle → a (calc, lifecycle) pair that never coexisted.


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
    async def test_pin_current_replace_mixes_identity(self, real):
        # PIN (current behavior): REPLACE yields calc B welded to calc A's
        # carried-forward lifecycle. Guards the xfail twin against
        # fixture regressions.
        _om, db = real
        assert await db.insert_closed_position(self._row("CALC-A", "L1"))
        assert await db.insert_closed_position(self._row("CALC-B", None))
        rows = await closed_rows(db, "POS-D6")
        assert len(rows) == 1
        assert (rows[0]["calc_id"], rows[0]["lifecycle_id"]) == (
            "CALC-B", "L1")

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        strict=True,
        reason="LB-D6: insert_closed_position binds calc_id "
               "unconditionally (db_orders.py:536, documented-intentional "
               "asymmetry :365-373) but carries lifecycle_id forward from "
               "the existing row when the caller passes None (:420 + "
               ":462-465) — REPLACE (CALC-A,L1) with (CALC-B,None) yields "
               "the mixed-identity pair (CALC-B, L1).")
    async def test_replace_keeps_identity_pair_coherent(self, real):
        _om, db = real
        assert await db.insert_closed_position(self._row("CALC-A", "L1"))
        assert await db.insert_closed_position(self._row("CALC-B", None))

        rows = await closed_rows(db, "POS-D6")
        assert len(rows) == 1  # REPLACE on (account, tpid, exit_time_ms)
        got = (rows[0]["calc_id"], rows[0]["lifecycle_id"])
        # DESIRED: the row carries the REPLACing writer's coherent
        # identity pair — calc B with the lifecycle THAT writer supplied
        # (None) — not calc B welded to calc A's lifecycle.
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
