"""Linkage attribution battery — T2 PIPELINE tranche (LB-T2a..LB-T2e).

Spec: docs/design/linkage_battery_plan.md §2 (LB-T2 row) + §3 (conventions)
+ §4 (triage). Fixture idiom copied from tests/test_linkage_battery_e2e.py
(the reference file); the LB-D5 junction dual-key drive in
tests/test_linkage_battery_disagreement.py is the direct ancestor of LB-T2e.

Each scenario drives the REAL pipeline entry points (``process_fill`` — the
reversal dispatcher — / ``_process_single_fill`` / ``_ensure_junction_if_linked``
/ ``_build_close_row_for_fill``) against a tempfile DB and asserts the
attribution OUTPUTS (DB rows). Scenarios assert DESIRED semantics; verified
divergences are xfail(strict=True) with the mechanism in the reason, each
with a passing current-behavior pin twin on a shared drive helper (plan §4).
No TestClient (gotcha LOW-023); the +2s close-row timer never fires in-test —
the row build is awaited directly.

Verified-mechanism corrections vs the filed framings (re-investigation
discipline, CLAUDE.md):

* LB-T2e / HA-42: the LB-D5 side observation ("each _process_single_fill runs
  BOTH the direct _link_position_calc_on_open AND the
  _ensure_junction_if_linked replay via _reenrich_parent_after_fill →
  _enrich_order_best_effort") is WRONG as filed — the fill-arrival re-enrich
  calls bare ``order_enrichment.enrich_order`` (order_manager.py:1071-1073),
  never ``_enrich_order_best_effort``, so NO replay runs inside the fill hot
  path and the prescribed Defect-7 shape (order tpid stashed, fills tpid="")
  does NOT over-count (pinned below). The REAL over-count is a
  guard-key/write-key divergence inside the replay itself: the
  junction-exists guard keys on the ORDER's stashed tpid
  (order_manager.py:623-631) while the replayed synthetic fill carries
  ``MAX(fills.terminal_position_id)`` (:633-651), which the builder prefers
  over the order tpid (:2235 fill-tpid-wins) — when every opening fill
  carries a tpid different from the order's stash, the guard never
  satisfies and EVERY replay re-accumulates the full SUM(open qty) through
  the UPSERT accumulate semantics (db_orders.py:2021-2022). Unbounded: one
  inflation per WS order update (each routes through
  _enrich_order_best_effort → :525).

* LB-T2a: the reversal trigger is ``process_fill`` dispatching on
  ``snapshot.splits`` (order_manager.py:1917-1921), populated only in
  one-way mode when the fill crosses net qty through zero
  (position_snapshot.py:176-201; mode detection order_manager.py:984-985
  keys on the fill's ``direction`` being ""/"BOTH"). Driven here through
  the REAL dispatcher with a live app_state position; ``persist_snapshot``
  is stubbed (the order_manager.py:994-999 call raw-writes a per-account
  settings DB — an out-of-scope side channel).
"""
import os
import sys

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from tests.linkage_battery_helpers import (  # noqa: E402
    ACCOUNT_ID,
    RECENT_MS,
    calc_row,
    closed_rows,
    fill,
    fill_by_fid,
    junction_rows,
    make_real_db,
    order_by_eoid,
    order_dict,
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
    """Snapshot/restore app_state.positions (plan §3 app_state hygiene)."""
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


# ── LB-T2a: reversal split — both legs' attribution ────────────────────
#
# process_fill (order_manager.py:1895) dispatches to _process_reversal_split
# (:2069) when snapshot.splits is non-empty (:1917-1921). The trigger is
# LIVE snapshot state: compute_fill_snapshot (position_snapshot.py:67) needs
# a one-way-mode fill (direction ""/"BOTH", order_manager.py:984-985) and an
# app_state position whose net qty the fill crosses through zero
# (position_snapshot.py:176-201). We drive
# the REAL dispatcher (not _process_reversal_split directly) with a live
# LONG 1.0 position and a SELL 3.0 fill; persist_snapshot is stubbed to
# keep the per-account settings DB out of the test (best-effort side
# channel, :994-999).


class TestLBT2aReversalSplit:
    @pytest.mark.asyncio
    async def test_reversal_close_and_open_leg_attribution(
            self, real, live_positions, monkeypatch):
        om, db = real
        import core.position_snapshot as ps
        monkeypatch.setattr(ps, "persist_snapshot", lambda *a, **k: None)

        # Old position POS-R1: linked entry (CALC-R1), junction formed.
        await seed_calc(db, "CALC-R1", status="matched", window_seconds=300)
        await seed_order(db, "O-R1E", calc_id="CALC-R1", link_status="LINKED")
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-R1E", "POS-R1", 1.0, fid="F-R1E",
                             ts=RECENT_MS + 1000))
        junc = await junction_rows(db, "POS-R1")
        assert len(junc) == 1
        lifecycle = junc[0]["lifecycle_id"]
        assert lifecycle

        # Reversal SELL 3.0 arrives on a NEW linked order (short calc).
        await seed_calc(db, "CALC-R2", side="short", effective_entry=49000.0,
                        tp_price=46000.0, sl_price=50500.0, status="matched",
                        window_seconds=300)
        await seed_order(db, "O-R1X", side="SELL", quantity=3.0,
                         calc_id="CALC-R2", link_status="LINKED",
                         tp_trigger_price=None, sl_trigger_price=None,
                         created_at_ms=RECENT_MS + 1500)
        live_positions.positions = [_pos_info(tpid="POS-R1")]

        # One-way fill (direction "" → mode one_way → snapshot computes
        # qty_before=+1.0, qty_after=-2.0 → splits). tpid=POS-R1 as ws
        # stamps it from the live (old) position.
        f_rev = fill("O-R1X", "POS-R1", 3.0, fid="F-R1X",
                     ts=RECENT_MS + 2000, is_close=1, price=49000.0,
                     realized_pnl=-1000.0, direction="", side="SELL",
                     fee=3.0)
        await om.process_fill(ACCOUNT_ID, f_rev)

        # CLOSE leg: keeps the original tradeId + the OLD position's tpid,
        # qty=|qty_before|, full realized_pnl, fee by qty ratio (1/3), and
        # the close-side stamp overrides the parent-order calc (CALC-R2)
        # with POS-R1's junction PRIMARY (CALC-R1) + its lifecycle.
        close_leg = await fill_by_fid(db, "F-R1X")
        assert close_leg["is_close"] == 1
        assert close_leg["direction"] == "LONG"
        assert close_leg["quantity"] == pytest.approx(1.0)
        assert close_leg["terminal_position_id"] == "POS-R1"
        assert close_leg["realized_pnl"] == pytest.approx(-1000.0)
        assert close_leg["fee"] == pytest.approx(1.0)
        assert close_leg["calc_id"] == "CALC-R1"
        assert close_leg["lifecycle_id"] == lifecycle

        # OPEN leg: synthetic id, NEW direction, qty = fill - |qty_before|,
        # zero pnl, fee 2/3 — and NO position identity yet: tpid cleared
        # (:2109-2112, "assigned by the next ACCOUNT_UPDATE"), so the
        # junction skips (no_position_key) → no junction row, no lifecycle.
        # It DOES keep the parent-order calc (enrich_fill parent rule) —
        # partial attribution pending the mint (the LB-T2d shape).
        open_leg = await fill_by_fid(db, "synth:F-R1X:open")
        assert open_leg is not None
        assert open_leg["is_close"] == 0
        assert open_leg["direction"] == "SHORT"
        assert open_leg["quantity"] == pytest.approx(2.0)
        assert open_leg["terminal_position_id"] == ""
        assert open_leg["realized_pnl"] == pytest.approx(0.0)
        assert open_leg["fee"] == pytest.approx(2.0)
        assert open_leg["calc_id"] == "CALC-R2"
        assert open_leg["lifecycle_id"] is None

        # Junction: still ONLY the old position's row — the open leg
        # accumulated nowhere (no key), and CALC-R2 has no junction row.
        junc = await junction_rows(db)
        assert [(r["position_id"], r["calc_id"]) for r in junc] == [
            ("POS-R1", "CALC-R1")]
        assert junc[0]["contributed_qty"] == pytest.approx(1.0)

        # Close row for the close leg: old position's primary calc +
        # lifecycle; full close of POS-R1 → CALC-R1 completes; the new
        # direction's calc is untouched.
        await om._build_close_row_for_fill(
            ACCOUNT_ID,
            fill("O-R1X", "POS-R1", 1.0, fid="F-R1X", ts=RECENT_MS + 2000,
                 is_close=1, price=49000.0, realized_pnl=-1000.0,
                 direction="LONG", side="SELL"))
        closed = await closed_rows(db, "POS-R1")
        assert len(closed) == 1
        assert closed[0]["calc_id"] == "CALC-R1"
        assert closed[0]["lifecycle_id"] == lifecycle
        assert closed[0]["quantity"] == pytest.approx(1.0)
        assert closed[0]["realized_pnl"] == pytest.approx(-1000.0)
        assert closed[0]["exit_reason"] == "MANUAL_OTHER"
        assert (await calc_row(db, "CALC-R1"))["status"] == (
            "completed_via_position")
        assert (await calc_row(db, "CALC-R2"))["status"] == "matched"


# ── LB-T2b: partial → final ladder ─────────────────────────────────────
#
# is_final is DERIVED per build (order_manager.py:3278-3303, Σ closing qty
# at-or-before this close's exit_time vs Σ opening qty) — closed_positions
# has NO is_final column, so the row-level finality observables are:
# per-order exit_reason on the partial (:3309-3311) vs ladder-aware
# reclassification on the final (:3312-3315 → _classify_final_exit_reason
# :3905), and calc completion gated on is_final (:3633-3636 →
# _complete_calcs_on_close :1373). matched → partially_actioned does NOT
# happen on a partial: the transition table supports it but NO producer
# writes it (calc_state.py:124-126, documented pre-Phase-6 deferred gap) —
# pinned as by-design-deferred, not xfailed.


class TestLBT2bPartialFinalLadder:
    @pytest.mark.asyncio
    async def test_partial_then_final_rows_and_calc_transitions(self, real):
        om, db = real
        await seed_calc(db, "CALC-L", status="matched", window_seconds=300)
        await seed_order(db, "O-L", quantity=4.0, calc_id="CALC-L",
                         link_status="LINKED")
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-L", "POS-L", 4.0, fid="F-L0",
                             ts=RECENT_MS + 1000))
        junc = await junction_rows(db, "POS-L")
        assert junc[0]["contributed_qty"] == pytest.approx(4.0)
        lifecycle = junc[0]["lifecycle_id"]

        # Partial close 1.0 via a TP rung.
        await seed_order(db, "O-LC1", side="SELL",
                         order_type="take_profit_market", reduce_only=1,
                         price=0.0, tp_trigger_price=55000.0,
                         sl_trigger_price=None,
                         created_at_ms=RECENT_MS + 1500)
        f_p = fill("O-LC1", "POS-L", 1.0, fid="F-LC1", is_close=1,
                   price=55000.0, realized_pnl=5000.0, ts=RECENT_MS + 2000)
        await om._process_single_fill(ACCOUNT_ID, f_p)
        stamped = await fill_by_fid(db, "F-LC1")
        assert stamped["calc_id"] == "CALC-L"
        assert stamped["lifecycle_id"] == lifecycle

        await om._build_close_row_for_fill(ACCOUNT_ID, f_p)
        rows = await closed_rows(db, "POS-L")
        assert len(rows) == 1
        partial = rows[0]
        assert partial["quantity"] == pytest.approx(1.0)
        # NOT final (1.0 < 4.0): per-order reason, no ladder reclass.
        assert partial["exit_reason"] == "TP_PLANNED"
        assert partial["calc_id"] == "CALC-L"
        assert partial["lifecycle_id"] == lifecycle
        # Calc after the partial: completion deferred to the final close
        # AND no partially_actioned producer exists (calc_state.py:124-126)
        # → stays matched.
        assert (await calc_row(db, "CALC-L"))["status"] == "matched"

        # Final close 3.0 via an SL — makes the ladder MIXED (TP + non-TP
        # distinct closing orders, :3967-3968).
        await seed_order(db, "O-LC2", side="SELL", order_type="stop_market",
                         reduce_only=1, price=0.0, tp_trigger_price=None,
                         sl_trigger_price=48000.0,
                         created_at_ms=RECENT_MS + 2500)
        f_f = fill("O-LC2", "POS-L", 3.0, fid="F-LC2", is_close=1,
                   price=52000.0, realized_pnl=6000.0, ts=RECENT_MS + 3000)
        await om._process_single_fill(ACCOUNT_ID, f_f)
        stamped = await fill_by_fid(db, "F-LC2")
        assert stamped["calc_id"] == "CALC-L"
        assert stamped["lifecycle_id"] == lifecycle

        await om._build_close_row_for_fill(ACCOUNT_ID, f_f)
        rows = await closed_rows(db, "POS-L")
        assert len(rows) == 2  # distinct exit_time_ms → distinct REPLACE keys
        final = rows[1]
        assert final["quantity"] == pytest.approx(3.0)
        # FINAL (1.0 + 3.0 ≥ 4.0): ladder-aware reason (TP rung + SL final).
        assert final["exit_reason"] == "MIXED"
        assert final["calc_id"] == "CALC-L"
        assert final["lifecycle_id"] == lifecycle
        # The partial row's per-order reason is untouched by the final build.
        assert rows[0]["exit_reason"] == "TP_PLANNED"
        # Completion fires exactly at the final close.
        assert (await calc_row(db, "CALC-L"))["status"] == (
            "completed_via_position")


# ── LB-T2c: liquidation close ──────────────────────────────────────────
#
# Detection is the close ORDER's type: order_type containing "liquidation"
# (the Binance forced-liq fallback) → _determine_exit_reason :3894-3895
# returns LIQUIDATION per-order, _classify_final_exit_reason :3958-3966
# makes it DOMINATE the ladder on the final build, and liquidation_px is
# the liq-fill VWAP (_liquidation_vwap :3973-4008; fills JOIN orders
# LIKE '%liquidation%'), persisted on the row (:3328-3332 → :3507). No
# fill-level flag is involved anywhere.


class TestLBT2cLiquidation:
    @pytest.mark.asyncio
    async def test_liquidation_close_row(self, real):
        om, db = real
        await seed_calc(db, "CALC-Q", status="matched", window_seconds=300)
        await seed_order(db, "O-Q", calc_id="CALC-Q", link_status="LINKED")
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-Q", "POS-Q", 1.0, fid="F-Q0",
                             ts=RECENT_MS + 1000))
        lifecycle = (await junction_rows(db, "POS-Q"))[0]["lifecycle_id"]

        # Forced-liquidation close order + its fill.
        await seed_order(db, "O-QL", side="SELL", order_type="liquidation",
                         reduce_only=1, price=0.0, tp_trigger_price=None,
                         sl_trigger_price=None,
                         created_at_ms=RECENT_MS + 1500)
        f_liq = fill("O-QL", "POS-Q", 1.0, fid="F-QL", is_close=1,
                     price=40000.0, realized_pnl=-10000.0,
                     ts=RECENT_MS + 2000)
        await om._process_single_fill(ACCOUNT_ID, f_liq)
        stamped = await fill_by_fid(db, "F-QL")
        assert stamped["calc_id"] == "CALC-Q"      # primary stamp unaffected
        assert stamped["lifecycle_id"] == lifecycle

        await om._build_close_row_for_fill(ACCOUNT_ID, f_liq)
        rows = await closed_rows(db, "POS-Q")
        assert len(rows) == 1
        row = rows[0]
        assert row["exit_reason"] == "LIQUIDATION"
        # liquidation_px = the liq-fill VWAP (here one fill @ 40000).
        assert row["liquidation_px"] == pytest.approx(40000.0)
        assert row["calc_id"] == "CALC-Q"
        assert row["lifecycle_id"] == lifecycle
        assert row["realized_pnl"] == pytest.approx(-10000.0)
        # Liquidation is still a FINAL close → calc completes normally.
        assert (await calc_row(db, "CALC-Q"))["status"] == (
            "completed_via_position")


# ── LB-T2d: fill-before-mint — first fill permanently stranded ─────────
#
# [FIXED at reconciler R3 (`b50b59c`) — R5/NIT-5 annotation: the banner
# below documents the PRE-FIX mechanism this scenario was filed against
# (kept as the historical record per plan §4 triage); the tests inside
# pin the FIXED shape — mint-after-fill retro-sweep + evidence-gated,
# order-keyed delta-reconcile in position_identity.]
#
# Entry fill tpid="" AND parent order tpid="" (nothing minted): the
# builder's no-key path (order_manager.py:2264-2272 — Defect-7 fallback
# reads the order tpid :2264-2266, then the residual empty key SKIPs
# no_position_key :2267-2272) writes NO junction, NO lifecycle, no
# backfill. The mint then lands the realistic way — the data_cache mint
# stamps the SECOND fill's tpid (the exact race the Defect-7 docstring
# :2256-2263 names) — which forms the junction with ONLY its own qty.
# Retroactive reconciliation: the ONE replay lane
# (_ensure_junction_if_linked :559, fired on every later WS order update
# via _enrich_order_best_effort :525) is gated by the (position_id,
# calc_id) existence check :623-631, which the second fill's row now
# satisfies → replay SKIPs (junction_exists) and the first fill's qty
# never reaches contributed_qty. The Defect-1 backfill :2280-2289 stamps
# the ORDER's tpid only — never sibling fills rows.


class TestLBT2dFillBeforeMint:
    async def _drive_fill_before_mint(self, om, db):
        """Linked order, fill 1 pre-mint (tpid=""), fill 2 carries the
        minted tpid, then the retro replay lane fires. Returns the
        junction rows for POS-M."""
        await seed_calc(db, "CALC-M", status="matched", window_seconds=300)
        await seed_order(db, "O-M", calc_id="CALC-M", link_status="LINKED")

        # Fill 1: nothing minted anywhere → junction skipped entirely.
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-M", "", 1.0, fid="F-M1", ts=RECENT_MS + 1000))
        assert await junction_rows(db) == []           # no_position_key
        f1 = await fill_by_fid(db, "F-M1")
        assert f1["terminal_position_id"] == ""
        assert f1["lifecycle_id"] is None
        assert f1["calc_id"] == "CALC-M"   # parent calc DID propagate

        # The mint lands with the second fill.
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-M", "POS-M", 1.0, fid="F-M2",
                             ts=RECENT_MS + 2000))
        # Retro lane: a later WS order update replays the junction ensure.
        await om._ensure_junction_if_linked(ACCOUNT_ID, "O-M")
        return await junction_rows(db, "POS-M")

    @pytest.mark.asyncio
    async def test_pin_mint_sweep_full_identity(self, real):
        # LB-F9 FIXED (R3): the mint-carrying second fill sweeps the
        # pre-mint sibling (tpid + lifecycle stamped) and delta-reconciles
        # the junction row to the order's true opening SUM. Pins the full
        # fixed shape beyond the twin's qty assert.
        om, db = real
        junc = await self._drive_fill_before_mint(om, db)
        assert len(junc) == 1
        assert junc[0]["calc_id"] == "CALC-M"
        assert junc[0]["contributed_qty"] == pytest.approx(2.0)
        assert (await order_by_eoid(db, "O-M"))[
            "terminal_position_id"] == "POS-M"
        # The formerly-stranded first fill now carries full identity.
        f1 = await fill_by_fid(db, "F-M1")
        assert f1["terminal_position_id"] == "POS-M"
        assert f1["lifecycle_id"] == junc[0]["lifecycle_id"]
        f2 = await fill_by_fid(db, "F-M2")
        assert f2["terminal_position_id"] == "POS-M"
        assert f2["lifecycle_id"] == junc[0]["lifecycle_id"]

    @pytest.mark.asyncio
    async def test_mint_reconciles_first_fill(self, real):
        # LB-F9 FIXED (R3, was strict-xfail): once the mint lands, the
        # junction reflects the FULL opening quantity — including the
        # pre-mint first fill (mint-after-fill retro-sweep +
        # evidence-gated, order-keyed delta-reconcile).
        om, db = real
        junc = await self._drive_fill_before_mint(om, db)
        assert len(junc) == 1
        assert junc[0]["contributed_qty"] == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_pin_sweep_skips_rebuilt_namespace_fills(self, real):
        """R5 (R3-audit NIT-6 rider): the mint-after-fill LIFECYCLE sweep
        is STRUCTURALLY fenced off the offline-rebuild namespaces — a
        fill the fenced rebuild lane re-keyed to rebuilt:/bf: is never
        stamped with the live trade's lifecycle even when it shares the
        order (the §2.2 fence, previously reachability-argued only). The
        tpid sweep was already safe by shape (empty-only)."""
        om, db = real
        await seed_calc(db, "CALC-N6", status="matched", window_seconds=300)
        await seed_order(db, "O-N6", calc_id="CALC-N6", link_status="LINKED")
        # Fill 1 lands pre-mint (stranded), then the rebuild lane re-keys
        # it into the rebuilt: namespace.
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-N6", "", 1.0, fid="F-N6A",
                             ts=RECENT_MS + 1000))
        await db._conn.execute(
            "UPDATE fills SET terminal_position_id = "
            "'rebuilt:BTCUSDT:LONG:1' WHERE exchange_fill_id = 'F-N6A'")
        await db._conn.commit()
        # Fill 2 carries the live mint → the R3 sweep + reconcile fire.
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-N6", "POS-N6", 1.0, fid="F-N6B",
                             ts=RECENT_MS + 2000))
        f1 = await fill_by_fid(db, "F-N6A")
        assert f1["terminal_position_id"] == "rebuilt:BTCUSDT:LONG:1"
        assert f1["lifecycle_id"] is None          # the NIT-6 fence
        f2 = await fill_by_fid(db, "F-N6B")
        assert f2["terminal_position_id"] == "POS-N6"
        assert f2["lifecycle_id"]                  # live fill still stamps
        # The delta-reconcile SUM stays ORDER-keyed across namespaces
        # (§5-Q2 (b) DECIDED: fills are evidence of the ORDER's true
        # qty regardless of key namespace — only the lifecycle STAMP is
        # fenced). Pins the boundary between the two rules.
        junc = await junction_rows(db, "POS-N6")
        assert len(junc) == 1
        assert junc[0]["contributed_qty"] == pytest.approx(2.0)

    @pytest.mark.asyncio
    async def test_pin_second_order_same_calc_replays(self, real):
        """R2-audit NIT-6 fix (R3): the replay guard now includes
        order_id — a SECOND order of the same calc on the same position
        forms its own junction row via the link-after-fill replay
        (previously the (position_id, calc_id) guard skipped it forever,
        an F9-family under-count)."""
        om, db = real
        await seed_calc(db, "CALC-2O", status="matched", window_seconds=300)
        await seed_order(db, "O-2O-A", calc_id="CALC-2O",
                         link_status="LINKED")
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-2O-A", "POS-2O", 1.0, fid="F-2OA",
                             ts=RECENT_MS + 1000))
        # Second order, same calc: fill processed while UNLINKED (the
        # link-timing race), linked afterwards → the replay lane is the
        # ONLY path that can form its junction row.
        await seed_order(db, "O-2O-B", created_at_ms=RECENT_MS + 1500)
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-2O-B", "POS-2O", 2.0, fid="F-2OB",
                             ts=RECENT_MS + 2000))
        await db._conn.execute(
            "UPDATE orders SET calc_id = 'CALC-2O', link_status = 'LINKED' "
            "WHERE exchange_order_id = 'O-2O-B'")
        await db._conn.commit()

        await om._ensure_junction_if_linked(ACCOUNT_ID, "O-2O-B")

        junc = await junction_rows(db, "POS-2O")
        by_order_qty = sorted(r["contributed_qty"] for r in junc)
        assert len(junc) == 2, (
            "second order of the same calc never replayed — the old "
            "(position_id, calc_id) guard shape")
        assert by_order_qty == [pytest.approx(1.0), pytest.approx(2.0)]
        assert len({r["lifecycle_id"] for r in junc}) == 1


# ── LB-T2e: HA-42 repro — mid-fill double-junction over-count ──────────
#
# [FIXED at reconciler R2 (`aa20957`) — R5/NIT-5 annotation: shape (2)
# below documents the PRE-FIX guard-key/write-key divergence (kept as
# the historical record + the HA-42 mechanism correction); the tests
# inside pin the FIXED shape — guard ≡ write key by construction, the
# 1.0→1.0→1.0 idempotent progression.]
#
# HEADLINE. Two shapes, both driven:
#
# (1) The FILED shape (LB-D5 side obs: order pre-seeded with tpid, fills
#     tpid="" → Defect-7 fallback key) does NOT over-count — the
#     fill-arrival re-enrich (_reenrich_parent_after_fill,
#     order_manager.py:1071-1073) calls bare order_enrichment.enrich_order,
#     NOT _enrich_order_best_effort, so no replay runs inside
#     _process_single_fill; the direct builder is the only accumulator and
#     the UPSERT sums exactly once per fill. A later WS-order-update replay
#     then SKIPs on the guard (junction_exists, :623-631) because the
#     fallback write key (order tpid, :2264-2266) EQUALS the guard key.
#     Pinned PASSING — this corrects the filed mechanism.
#
# (2) The REAL over-count needs the guard key and the write key to
#     DIVERGE: order stash tpid=POS-STALE (sticky OrderManager stash /
#     snapshot recovery), fills carry the freshly-minted tpid=POS-H2.
#     Direct builder keys POS-H2 (fill tpid wins, :2235); Defect-1 backfill
#     (:2280-2286) only fills an EMPTY order tpid → stash survives. Every
#     replay (one per WS order update, _enrich_order_best_effort :525)
#     then: guard checks (POS-STALE, calc) :623-631 → row absent →
#     DELEGATED; synthetic fill carries MAX(fills.tpid)=POS-H2 + SUM(qty)
#     (:633-651); builder re-keys POS-H2 and the UPSERT ACCUMULATES
#     (db_orders.py:2021-2022 contributed_qty = existing + excluded) →
#     +SUM per replay, unbounded. 1.0 filled → 2.0 after one order update
#     → 3.0 after two.


class TestLBT2eHA42DoubleJunction:
    @pytest.mark.asyncio
    async def test_filed_defect7_shape_does_not_overcount(self, real):
        # The prescribed HA-42 shape (order tpid stashed, two fills
        # tpid="") — junction contributed_qty == total filled EXACTLY,
        # even after a WS-order-update replay. PASSES: corrects the
        # LB-D5 side observation's "both paths per fill" framing.
        om, db = real
        await seed_calc(db, "CALC-H1", status="matched", window_seconds=300)
        await seed_order(db, "O-H1", calc_id="CALC-H1", link_status="LINKED",
                         quantity=2.0, tpid="POS-H1")

        await om._process_single_fill(
            ACCOUNT_ID, fill("O-H1", "", 1.0, fid="F-H1A",
                             ts=RECENT_MS + 1000))
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-H1", "", 1.0, fid="F-H1B",
                             ts=RECENT_MS + 1100))
        junc = await junction_rows(db, "POS-H1")
        assert len(junc) == 1
        assert junc[0]["contributed_qty"] == pytest.approx(2.0)  # exact

        # WS order update → replay lane: guard key (order tpid POS-H1)
        # == write key → junction_exists → idempotent, still 2.0.
        await om._enrich_order_best_effort(
            order_dict("O-H1", status="filled", quantity=2.0,
                       filled_qty=2.0, avg_fill_price=50000.0))
        junc = await junction_rows(db, "POS-H1")
        assert len(junc) == 1
        assert junc[0]["contributed_qty"] == pytest.approx(2.0)
        assert len({r["lifecycle_id"] for r in junc}) == 1

    async def _drive_stale_stash_replays(self, om, db):
        """The verified over-count drive: order stash tpid=POS-STALE,
        ONE fill tpid=POS-H2 (1.0), then two replay firings (the first
        via the real WS-order-update lane _enrich_order_best_effort, the
        second via the replay directly). Returns the per-stage junction
        totals for the order plus the final rows."""
        await seed_calc(db, "CALC-H2", status="matched", window_seconds=300)
        await seed_order(db, "O-H2", calc_id="CALC-H2", link_status="LINKED",
                         tpid="POS-STALE")

        async def _total():
            rows = await junction_rows(db)
            return sum(r["contributed_qty"] for r in rows)

        totals = []
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-H2", "POS-H2", 1.0, fid="F-H2",
                             ts=RECENT_MS + 1000))
        totals.append(await _total())
        # Replay 1: the live WS-order-update lane (:289 → :516 → :525).
        await om._enrich_order_best_effort(
            order_dict("O-H2", status="filled", filled_qty=1.0,
                       avg_fill_price=50000.0))
        totals.append(await _total())
        # Replay 2: any subsequent order update re-fires the same lane.
        await om._ensure_junction_if_linked(ACCOUNT_ID, "O-H2")
        totals.append(await _total())
        return totals, await junction_rows(db)

    @pytest.mark.asyncio
    async def test_pin_replay_guard_matches_write_key(self, real):
        # LB-F8 FIXED (R2): the replay derives the fills-aggregate write
        # key FIRST and exists-checks THAT key (guard ≡ write by
        # construction, position_identity.ensure_junction_if_linked) —
        # a divergent order stash can no longer defeat the guard. Pins
        # the fixed progression: 1.0 filled stays 1.0 across replays.
        om, db = real
        totals, junc = await self._drive_stale_stash_replays(om, db)
        assert totals == [pytest.approx(1.0), pytest.approx(1.0),
                          pytest.approx(1.0)]
        # Single junction row keyed by the FILL's tpid. NB the stale
        # stash itself survives here (no stale junction ROW ever existed
        # for (calc, order), so the R2 migration pass has nothing to
        # move) — it is simply INERT now: the guard keys on the
        # fills-derived write key, never the stash.
        assert [(r["position_id"], r["calc_id"]) for r in junc] == [
            ("POS-H2", "CALC-H2")]
        assert junc[0]["contributed_qty"] == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_junction_contributed_qty_equals_filled_qty(self, real):
        # LB-F8 FIXED (R2, was strict-xfail): the junction ledger equals
        # what actually filled — replays are idempotent regardless of
        # which tpid keyed the row.
        om, db = real
        totals, junc = await self._drive_stale_stash_replays(om, db)
        assert totals[-1] == pytest.approx(1.0)
