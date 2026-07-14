"""Linkage attribution battery — interference scenarios (LB-I1..I6b).

Spec: docs/design/linkage_battery_plan.md §2 (matrix rows LB-I1..LB-I6b) +
§3 (conventions, binding). Fixture idiom copied from
tests/test_linkage_battery_e2e.py (the reference file).

Each scenario drives a REAL interference mutator (admin raw confirm, bulk
stale-cancel, matcher TOCTOU, WS cancel-release, tpid-reuse lifecycle
lookup, NMR-sticky / UNPLANNED-upgrade re-fire) against the real pipeline
entry points and asserts the attribution OUTPUTS (DB rows). DESIRED
semantics are asserted; verified divergences are xfail(strict=True) per
plan §4 (mechanism re-read at the write site before conversion). No
TestClient (gotcha LOW-023); the +2s close-row timer never fires — the
row build is awaited directly.
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
    reads: config.DB_PATH (raw-sqlite enrichment + routes_admin handler),
    link_actions.db (manual-link), trade_event_log stubbed (linkdb
    pattern)."""
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


class _FakeRequest:
    """Minimal Request stand-in for driving the real calc_link_confirm
    coroutine — the handler only calls ``await request.json()``."""

    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


# ── LB-I1: admin raw confirm — calc_id without link_status ────────────


class TestLBI1AdminRawConfirm:
    async def _drive_confirm(self, om, db):
        """Real NMR order (near-miss calc, SL off by 1000) + processed
        entry fill, then the REAL /admin/calc_link/confirm handler run
        directly. The handler reads config.DB_PATH (fixture-patched) and
        app_state.active_account_id — the latter is 1 only via the
        registry-unloaded default (state.py:415), so pin it loudly."""
        from core.state import app_state
        assert app_state.active_account_id == ACCOUNT_ID, (
            "precondition drift: an earlier test left a non-default "
            "active account; LB-I1 assumes account 1")
        await seed_calc(db, "CALC-I1", sl_price=47000.0, window_seconds=300)
        oid = await seed_order(db, "O-I1")
        await om._enrich_order_best_effort(order_dict("O-I1"))
        order = await order_row(db, oid)
        assert order["link_status"] == "NEEDS_MANUAL_REVIEW"
        assert order["calc_id"] is None
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-I1", "POS-I1", 1.0, fid="F-I1"))

        from api.routes_admin import calc_link_confirm
        resp = await calc_link_confirm(
            _FakeRequest({"order_id": oid, "calc_id": "CALC-I1"}))
        assert resp.status_code == 200
        assert b"alert-success" in resp.body
        return oid

    @pytest.mark.asyncio
    async def test_raw_confirm_mechanism_pinned(self, real):
        """Pins the CURRENT mechanism (routes_admin.py:290-291): raw
        UPDATE of orders.calc_id + fills.calc_id, NO link_status write,
        NO calc_state transition, NO junction — bypasses both
        choke-points."""
        om, db = real
        oid = await self._drive_confirm(om, db)

        order = await order_row(db, oid)
        assert order["calc_id"] == "CALC-I1"          # raw write landed
        assert order["link_status"] == "NEEDS_MANUAL_REVIEW"  # untouched
        # fills propagated (routes_admin.py:291) …
        assert (await fill_by_fid(db, "F-I1"))["calc_id"] == "CALC-I1"
        # … but the calc-state choke-point was bypassed: calc never
        # flips active → matched (compare link_actions.py manual lane).
        assert (await calc_row(db, "CALC-I1"))["status"] == "active"
        # And no junction replay fires from this lane either.
        assert await junction_rows(db, "POS-I1") == []

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        strict=True,
        reason="LB-I1: /admin/calc_link/confirm (routes_admin.py:290) "
               "raw-writes orders.calc_id and never touches link_status "
               "— bypasses the link_state auto_classify/transition "
               "choke-point entirely, so calc_id⟺LINKED "
               "(core/link_state.py invariant) is broken: calc_id set "
               "while link_status stays NEEDS_MANUAL_REVIEW.")
    async def test_invariant_holds_after_admin_confirm(self, real):
        # DESIRED: any lane that stamps calc_id also brings the order to
        # LINKED (the invariant every consumer — matcher already-
        # correlated gate, badges, needs-link queue — assumes).
        om, db = real
        oid = await self._drive_confirm(om, db)
        assert_calc_link_invariant(await order_row(db, oid))


# ── LB-I2: stale-cancel asymmetry — bulk cancel never releases calc ───


class TestLBI2StaleCancelAsymmetry:
    async def _link_then_stale_cancel(self, om, db):
        """Calc matched + order LINKED, then the scheduler's bulk
        stale-cancel (schedulers.py:717 → db.mark_stale_orders,
        db_orders.py:867): raw UPDATE orders SET status='canceled' for
        rows last seen > threshold ago."""
        await seed_calc(db, "CALC-I2", window_seconds=300)
        oid = await seed_order(db, "O-I2")
        await om._enrich_order_best_effort(order_dict("O-I2"))
        order = await order_row(db, oid)
        assert order["link_status"] == "LINKED"
        assert (await calc_row(db, "CALC-I2"))["status"] == "matched"

        # Make the order stale: last_seen 10 min before the anchor
        # (cutoff is now-5min; mark_stale requires 0 < last_seen < cutoff).
        await db._conn.execute(
            "UPDATE orders SET last_seen_ms = ? WHERE id = ?",
            (RECENT_MS - 600_000, oid))
        await db._conn.commit()
        n = await db.mark_stale_orders(
            account_id=ACCOUNT_ID, stale_threshold_ms=5 * 60 * 1000)
        assert n == 1
        assert (await order_row(db, oid))["status"] == "canceled"
        return oid

    @pytest.mark.asyncio
    async def test_stale_cancel_strands_calc_matched(self, real):
        """Pins the CURRENT asymmetry (order_manager.py:1205 NOTE): the
        bulk path is a raw UPDATE that never flows through
        _release_calc_on_operator_cancel, so the calc stays 'matched'
        forever — and an identical replacement order finds ZERO
        candidates (matcher filter status IN ('active','released'),
        calc_correlation.py:389) → UNPLANNED. Pair test: the per-order
        WS-cancel path DOES release (LB-I4 below)."""
        om, db = real
        await self._link_then_stale_cancel(om, db)

        assert (await calc_row(db, "CALC-I2"))["status"] == "matched"

        # Operator re-pastes the identical order → no candidates → UNPLANNED.
        oid2 = await seed_order(db, "O-I2B", created_at_ms=RECENT_MS + 5000)
        await om._enrich_order_best_effort(
            order_dict("O-I2B", created_at_ms=RECENT_MS + 5000))
        order2 = await order_row(db, oid2)
        assert order2["link_status"] == "UNPLANNED"
        assert order2["calc_id"] is None

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        strict=True,
        reason="LB-I2: mark_stale_orders (db_orders.py:882, time-threshold "
               "path) bulk-cancels via raw UPDATE that never routes "
               "through _release_calc_on_operator_cancel — same "
               "raw-bulk-cancel family as the asymmetry documented at "
               "order_manager.py:1205 (that NOTE names the sibling "
               "mark_stale_orders_canceled, db_orders.py:774, the "
               "snapshot-reconciliation path — still unpinned, see plan "
               "§2 LB-T2). Calc stays 'matched', excluded from the "
               "candidate pool, so the replacement order lands UNPLANNED.")
    async def test_calc_released_after_stale_cancel(self, real):
        # DESIRED: a stale-cancelled unfilled entry releases its calc
        # back to the re-match pool, same as the WS-cancel path (LB-I4).
        om, db = real
        await self._link_then_stale_cancel(om, db)
        assert (await calc_row(db, "CALC-I2"))["status"] == "released"


# ── LB-I3: expiry-vs-match TOCTOU — order LINKED, calc expired ─────────


class TestLBI3ExpiryMatchTOCTOU:
    @pytest.mark.asyncio
    async def test_order_linked_while_calc_stays_expired(self, real, monkeypatch):
        """Pins the composite race state (plain asserts — this is the
        designed race-loss semantics, not an xfail): the matcher decided
        LINKED off an 'active' snapshot, the expiry sweep flipped the calc
        first, and the guarded UPDATE (order_enrichment.py:517-524, WHERE
        status = matched_from_status) race-loses → CalcTransitionRaceLost
        swallowed at :556. The ORDER write (:378-384, gated only on
        calc_id IS NULL) has no such guard → order ends LINKED+calc_id
        while the calc stays 'expired'. correlate_order_to_calc is
        monkeypatched AT ITS SOURCE MODULE (core.calc_correlation) because
        _try_correlate imports it at call time (order_enrichment.py:357)."""
        om, db = real
        import core.calc_correlation as cc

        # Calc row already expired in the DB — the sweep won the race.
        await seed_calc(db, "CALC-I3", status="expired", window_seconds=300)
        oid = await seed_order(db, "O-I3")

        def _stale_snapshot_match(order, **kw):
            # Matcher's decision from BEFORE the expiry flip: full 6/6
            # off a calc it saw as 'active'.
            return cc.MatchResult(
                calc_id="CALC-I3", link_status="LINKED",
                audit_rows=[], matched_from_status="active")

        monkeypatch.setattr(cc, "correlate_order_to_calc", _stale_snapshot_match)
        await om._enrich_order_best_effort(order_dict("O-I3"))

        order = await order_row(db, oid)
        # The order side committed: LINKED + calc_id (invariant holds
        # order-locally) …
        assert order["link_status"] == "LINKED"
        assert order["calc_id"] == "CALC-I3"
        assert_calc_link_invariant(order)
        # … while the calc-side transition race-lost: the calc is a
        # dead ('expired') calc now referenced by a LINKED order.
        assert (await calc_row(db, "CALC-I3"))["status"] == "expired"


# ── LB-I4: WS cancel-release → re-match (the asymmetry's good half) ────


class TestLBI4ReleaseThenRematch:
    @pytest.mark.asyncio
    async def test_ws_cancel_releases_calc_then_new_order_rematches(self, real):
        """Expected PASS: the per-order WS cancel path
        (process_order_update → _release_calc_on_operator_cancel,
        order_manager.py:1172; gates: status=canceled, not reduce_only,
        filled_qty=0, calc matched) releases the calc + stamps
        cancel_reason, and the matcher (candidates status IN
        ('active','released'), calc_correlation.py:389) re-links a fresh
        6/6 order → calc matched again."""
        om, db = real
        await seed_calc(db, "CALC-I4", window_seconds=300)
        oid = await seed_order(db, "O-I4A")
        await om._enrich_order_best_effort(order_dict("O-I4A"))
        order = await order_row(db, oid)
        assert order["link_status"] == "LINKED"
        assert order["calc_id"] == "CALC-I4"
        assert (await calc_row(db, "CALC-I4"))["status"] == "matched"

        # WS cancel of the working (unfilled) entry — the real driving
        # pattern (test_correlation_log_replay.py TestAmendCancelLegs).
        accepted = await om.process_order_update(
            ACCOUNT_ID,
            order_dict("O-I4A", status="canceled", filled_qty=0.0,
                       reduce_only=0))
        assert accepted is True

        order = await order_row(db, oid)
        assert order["status"] == "canceled"
        assert order["cancel_reason_category"] == "OPERATOR"
        assert order["cancel_ts_ms"]
        assert (await calc_row(db, "CALC-I4"))["status"] == "released"

        # Fresh 6/6 order (the operator's re-paste) → re-match.
        oid2 = await seed_order(db, "O-I4B", created_at_ms=RECENT_MS + 5000)
        await om._enrich_order_best_effort(
            order_dict("O-I4B", created_at_ms=RECENT_MS + 5000))
        order2 = await order_row(db, oid2)
        assert order2["link_status"] == "LINKED"
        assert order2["calc_id"] == "CALC-I4"
        assert_calc_link_invariant(order2)
        assert (await calc_row(db, "CALC-I4"))["status"] == "matched"


# ── LB-I5: lifecycle bleed on tpid reuse ───────────────────────────────


class TestLBI5LifecycleBleedOnTpidReuse:
    async def _two_trades_same_tpid(self, om, db):
        """Trade 1 (CALC-I5A / O-I5A) opens POS-R, mints L1, fully
        closes (close row awaited directly). Trade 2 (NEW calc CALC-I5B
        + NEW order O-I5B, linked) fills with the SAME tpid POS-R —
        the recurring-slot-id shape the :2239 docstring calls out.
        Returns (L1, trade-2 junction row)."""
        # Trade 1: link → open → close.
        await seed_calc(db, "CALC-I5A", window_seconds=300)
        oid_a = await seed_order(db, "O-I5A")
        await om._enrich_order_best_effort(order_dict("O-I5A"))
        assert (await order_row(db, oid_a))["calc_id"] == "CALC-I5A"
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-I5A", "POS-R", 1.0, fid="F-I5A"))
        junc = await junction_rows(db, "POS-R")
        assert len(junc) == 1
        l1 = junc[0]["lifecycle_id"]
        assert l1

        await seed_order(db, "O-I5AC", side="SELL", reduce_only=1,
                         tp_trigger_price=None, sl_trigger_price=None,
                         created_at_ms=RECENT_MS + 1500)
        f_close = fill("O-I5AC", "POS-R", 1.0, fid="F-I5AC", is_close=1,
                       price=55000.0, realized_pnl=5000.0,
                       ts=RECENT_MS + 2000)
        await om._process_single_fill(ACCOUNT_ID, f_close)
        await om._build_close_row_for_fill(ACCOUNT_ID, f_close)
        assert len(await closed_rows(db, "POS-R")) == 1
        assert (await calc_row(db, "CALC-I5A"))["status"] == (
            "completed_via_position")

        # Trade 2: fresh calc + fresh order, SAME tpid slot.
        await seed_calc(db, "CALC-I5B", window_seconds=300)
        oid_b = await seed_order(db, "O-I5B", created_at_ms=RECENT_MS + 3000)
        await om._enrich_order_best_effort(
            order_dict("O-I5B", created_at_ms=RECENT_MS + 3000))
        assert (await order_row(db, oid_b))["calc_id"] == "CALC-I5B"
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-I5B", "POS-R", 1.0, fid="F-I5B",
                             ts=RECENT_MS + 4000))
        junc = await junction_rows(db, "POS-R")
        assert len(junc) == 2
        row_b = [r for r in junc if r["calc_id"] == "CALC-I5B"][0]
        return l1, row_b

    @pytest.mark.asyncio
    async def test_current_lookup_reuses_closed_trades_lifecycle(self, real):
        """Pins the CURRENT mechanism: the lifecycle lookup
        (order_manager.py:2254-2266) selects ANY positions_calcs row for
        the tpid — no sealed-at-close filter — so trade 2 inherits L1."""
        om, db = real
        l1, row_b = await self._two_trades_same_tpid(om, db)
        assert row_b["lifecycle_id"] == l1  # the bleed, verbatim

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        strict=True,
        reason="LB-I5: lifecycle mint/reuse lookup (order_manager.py:"
               "2254-2266) reuses ANY junction row's lifecycle_id for "
               "the same position_id with no closed/sealed filter — the "
               "documented ASSUMPTION (:2239, 'a recurring tpid would "
               "bleed a closed trade's lifecycle into a new one; fix is "
               "seal-at-close, deferred'). A tpid-reusing adapter makes "
               "trade 2 inherit trade 1's L1.")
    async def test_fresh_lifecycle_for_new_economic_trade(self, real):
        # DESIRED: a new economic trade (calc B, order B, after the slot
        # fully closed) mints a FRESH lifecycle even when the venue
        # reuses the tpid slot.
        om, db = real
        l1, row_b = await self._two_trades_same_tpid(om, db)
        assert row_b["lifecycle_id"] and row_b["lifecycle_id"] != l1


# ── LB-I6a: NMR sticky beats a later perfect calc (pin, no xfail) ─────


class TestLBI6aNmrSticky:
    @pytest.mark.asyncio
    async def test_nmr_stays_sticky_after_perfect_calc_and_fill(self, real):
        """Pins the CURRENT design (order_enrichment.py:313 T211-H3
        gate): once the matcher decides NEEDS_MANUAL_REVIEW, the
        decision sticks — a PERFECT calc seeded afterwards + the
        fill-arrival re-fire (_reenrich_parent_after_fill,
        order_manager.py:1901) do NOT upgrade it. Deferred follow-up #3;
        plain asserts by plan mandate."""
        om, db = real
        # Near-miss candidate: SL off by 1000 → NMR.
        await seed_calc(db, "CALC-I6A1", sl_price=47000.0, window_seconds=300)
        oid = await seed_order(db, "O-I6A")
        await om._enrich_order_best_effort(order_dict("O-I6A"))
        order = await order_row(db, oid)
        assert order["link_status"] == "NEEDS_MANUAL_REVIEW"

        # A PERFECT calc arrives after the NMR decision …
        await seed_calc(db, "CALC-I6A2", window_seconds=300)
        # … then the entry fill re-fires the matcher.
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-I6A", "POS-I6A", 1.0, fid="F-I6A"))

        order = await order_row(db, oid)
        assert order["link_status"] == "NEEDS_MANUAL_REVIEW"  # sticky
        assert order["calc_id"] is None
        assert_calc_link_invariant(order)
        assert await junction_rows(db, "POS-I6A") == []
        assert (await fill_by_fid(db, "F-I6A"))["calc_id"] is None
        # The perfect calc is untouched, still awaiting a manual link.
        assert (await calc_row(db, "CALC-I6A2"))["status"] == "active"


# ── LB-I6b: UNPLANNED → LINKED upgrade on fill re-fire ─────────────────


class TestLBI6bUnplannedUpgrade:
    @pytest.mark.asyncio
    async def test_fill_refire_upgrades_unplanned_to_linked(self, real):
        """Expected PASS: UNPLANNED (zero candidates) is allowed to
        re-run (order_enrichment.py:310-312), so the fill-arrival
        re-fire links the order, the matcher's fill backfill
        (order_enrichment.py:417-422) stamps the already-persisted entry
        fill, and _link_position_calc_on_open (running AFTER the re-fire
        inside _process_single_fill) forms the junction + mints the
        lifecycle."""
        om, db = real
        oid = await seed_order(db, "O-I6B")  # no calcs yet → 0 candidates
        await om._enrich_order_best_effort(order_dict("O-I6B"))
        order = await order_row(db, oid)
        assert order["link_status"] == "UNPLANNED"
        assert order["calc_id"] is None

        # Calc created AFTER the order → then the entry fill arrives.
        await seed_calc(db, "CALC-I6B", window_seconds=300)
        await om._process_single_fill(
            ACCOUNT_ID, fill("O-I6B", "POS-I6B", 1.0, fid="F-I6B"))

        order = await order_row(db, oid)
        assert order["link_status"] == "LINKED"
        assert order["calc_id"] == "CALC-I6B"
        assert_calc_link_invariant(order)
        assert order["terminal_position_id"] == "POS-I6B"
        assert (await calc_row(db, "CALC-I6B"))["status"] == "matched"

        junc = await junction_rows(db, "POS-I6B")
        assert len(junc) == 1
        assert junc[0]["calc_id"] == "CALC-I6B"
        assert junc[0]["order_id"] == oid
        lifecycle = junc[0]["lifecycle_id"]
        assert lifecycle
        f_entry = await fill_by_fid(db, "F-I6B")
        assert f_entry["calc_id"] == "CALC-I6B"
        assert f_entry["lifecycle_id"] == lifecycle
