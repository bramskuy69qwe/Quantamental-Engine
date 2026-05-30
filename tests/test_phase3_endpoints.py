"""
Phase 3 Task 2 (P3.T2) tests — operator manual-link endpoints.

Covers core/link_actions.py (the unit-testable handlers behind the three
endpoints) + a route-registration import-smoke for api/routes_orders.py.
Per HANDOFF gotcha #9, route LOGIC is tested via the underlying handlers,
NOT a second TestClient (which hangs the suite).

Intent (Rule 8): every operator link_status write must route through the
core.link_state choke-point (spec §3.6), the manual link must flip the
calc active|released → matched (mirroring the auto-matcher so the calc
lifecycle proceeds), and the invariant "calc_id present ⟺ link_status =
LINKED" must hold after every action. The transition validity is enforced
by link_state.LINK_TRANSITIONS (operator decided→decided moves only):
UNPLANNED/NULL sources are NOT linkable; LINKED is terminal.

Run: pytest tests/test_phase3_endpoints.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

ACCOUNT_ID = 1


# ── Fixtures / helpers ─────────────────────────────────────────────────


@pytest_asyncio.fixture
async def linkdb(monkeypatch):
    """Temp DB wired as the link_actions `db` singleton + config.DB_PATH.

    core.link_actions uses the module-level `db` singleton and
    config.DB_PATH (for find_candidate_calcs), so both are redirected at
    the temp DB. log_trade_event is stubbed to a no-op to avoid touching
    the real per-account trade_events DB.
    """
    from core.database import DatabaseManager
    import core.link_actions as la
    import core.trade_event_log as tel
    import config

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    database = DatabaseManager(path=tmp.name)
    await database.initialize()
    await database._conn.execute(
        "INSERT OR IGNORE INTO accounts (id, name) VALUES (?, ?)",
        (ACCOUNT_ID, "Test"),
    )
    await database._conn.commit()

    monkeypatch.setattr(la, "db", database)
    monkeypatch.setattr(config, "DB_PATH", tmp.name)
    monkeypatch.setattr(tel, "log_trade_event", lambda *a, **k: None)

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


def _now_ms() -> int:
    return int(time.time() * 1000)


async def _seed_order(db, *, eoid, link_status=None, calc_id=None,
                      symbol="BTCUSDT", side="BUY", order_type="limit",
                      price=50000.0, tp=55000.0, sl=48000.0,
                      reduce_only=0, created_at_ms=None) -> int:
    cur = await db._conn.execute(
        "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
        " order_type, reduce_only, price, tp_trigger_price, sl_trigger_price, "
        " created_at_ms, status, calc_id, link_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ACCOUNT_ID, eoid, symbol, side, order_type, reduce_only, price, tp, sl,
         created_at_ms or _now_ms(), "new", calc_id, link_status),
    )
    await db._conn.commit()
    return cur.lastrowid


async def _seed_calc(db, *, calc_id, status="active", ticker="BTCUSDT",
                     side="long", entry=50000.0, tp=55000.0, sl=48000.0) -> None:
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).isoformat()
    await db._conn.execute(
        "INSERT INTO pre_trade_log (account_id, timestamp, ticker, side, "
        " effective_entry, tp_price, sl_price, average, calc_id, status, "
        " window_seconds) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ACCOUNT_ID, ts, ticker, side, entry, tp, sl, entry, calc_id, status, 300),
    )
    await db._conn.commit()


async def _seed_fill(db, *, fid, eoid, is_close=0, calc_id=None,
                     symbol="BTCUSDT", side="BUY") -> None:
    await db._conn.execute(
        "INSERT INTO fills (account_id, exchange_fill_id, exchange_order_id, "
        " symbol, side, is_close, calc_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ACCOUNT_ID, fid, eoid, symbol, side, is_close, calc_id),
    )
    await db._conn.commit()


async def _order(db, order_id):
    async with db._conn.execute(
        "SELECT link_status, calc_id FROM orders WHERE id = ?", (order_id,),
    ) as cur:
        r = await cur.fetchone()
    return {"link_status": r[0], "calc_id": r[1]}


async def _calc_status(db, calc_id):
    async with db._conn.execute(
        "SELECT status FROM pre_trade_log WHERE calc_id = ?", (calc_id,),
    ) as cur:
        r = await cur.fetchone()
    return r[0] if r else None


async def _fill_calc(db, fid):
    async with db._conn.execute(
        "SELECT calc_id FROM fills WHERE exchange_fill_id = ?", (fid,),
    ) as cur:
        r = await cur.fetchone()
    return r[0] if r else None


def _assert_calcid_linked_invariant(order: dict):
    """calc_id present ⟺ link_status == LINKED."""
    has_calc = bool(order["calc_id"])
    is_linked = order["link_status"] == "LINKED"
    assert has_calc == is_linked, order


# ── manual_link_order ──────────────────────────────────────────────────


class TestManualLink:
    @pytest.mark.asyncio
    async def test_needs_review_to_linked_flips_calc(self, linkdb):
        from core.link_actions import manual_link_order
        from core.event_bus import event_bus

        oid = await _seed_order(linkdb, eoid="O1", link_status="NEEDS_MANUAL_REVIEW")
        await _seed_calc(linkdb, calc_id="C1", status="active")

        while not event_bus._queue.empty():
            event_bus._queue.get_nowait()

        result = await manual_link_order(ACCOUNT_ID, oid, "C1")
        assert result == "linked"

        o = await _order(linkdb, oid)
        assert o["link_status"] == "LINKED"
        assert o["calc_id"] == "C1"
        _assert_calcid_linked_invariant(o)
        # calc flipped active → matched (mirrors the auto-matcher)
        assert await _calc_status(linkdb, "C1") == "matched"
        # calc:linked fired through the choke-point
        events = []
        while not event_bus._queue.empty():
            events.append(event_bus._queue.get_nowait())
        assert any(c == "calc:linked" for c, _ in events)

    @pytest.mark.asyncio
    async def test_unlinked_to_linked(self, linkdb):
        from core.link_actions import manual_link_order
        oid = await _seed_order(linkdb, eoid="O2", link_status="UNLINKED")
        await _seed_calc(linkdb, calc_id="C2", status="active")
        assert await manual_link_order(ACCOUNT_ID, oid, "C2") == "linked"
        assert (await _order(linkdb, oid))["link_status"] == "LINKED"

    @pytest.mark.asyncio
    async def test_order_not_found(self, linkdb):
        from core.link_actions import manual_link_order
        await _seed_calc(linkdb, calc_id="C3")
        assert await manual_link_order(ACCOUNT_ID, 9999, "C3") == "order_not_found"

    @pytest.mark.asyncio
    async def test_already_linked(self, linkdb):
        from core.link_actions import manual_link_order
        oid = await _seed_order(linkdb, eoid="O4", link_status="LINKED", calc_id="C-OLD")
        await _seed_calc(linkdb, calc_id="C4")
        assert await manual_link_order(ACCOUNT_ID, oid, "C4") == "already_linked"
        # untouched
        assert (await _order(linkdb, oid))["calc_id"] == "C-OLD"

    @pytest.mark.asyncio
    async def test_calc_not_found(self, linkdb):
        from core.link_actions import manual_link_order
        oid = await _seed_order(linkdb, eoid="O5", link_status="NEEDS_MANUAL_REVIEW")
        assert await manual_link_order(ACCOUNT_ID, oid, "NOPE") == "calc_not_found"
        # order untouched (no half-write)
        o = await _order(linkdb, oid)
        assert o["link_status"] == "NEEDS_MANUAL_REVIEW"
        assert o["calc_id"] is None

    @pytest.mark.asyncio
    async def test_missing_calc_id(self, linkdb):
        from core.link_actions import manual_link_order
        oid = await _seed_order(linkdb, eoid="O6", link_status="NEEDS_MANUAL_REVIEW")
        assert await manual_link_order(ACCOUNT_ID, oid, "  ") == "missing_calc_id"

    @pytest.mark.asyncio
    async def test_unplanned_order_not_linkable(self, linkdb):
        # UNPLANNED is operator-terminal in LINK_TRANSITIONS — the operator
        # cannot link it (only the matcher can upgrade UNPLANNED, via
        # auto_classify; that is the P3.T1 distinction).
        from core.link_actions import manual_link_order
        oid = await _seed_order(linkdb, eoid="O7", link_status="UNPLANNED")
        await _seed_calc(linkdb, calc_id="C7")
        assert await manual_link_order(ACCOUNT_ID, oid, "C7") == "invalid_transition"
        assert (await _order(linkdb, oid))["calc_id"] is None

    @pytest.mark.asyncio
    async def test_null_link_status_not_linkable(self, linkdb):
        # A NULL link_status (matcher never ran) has no decided source to
        # transition FROM — rejected by the choke-point.
        from core.link_actions import manual_link_order
        oid = await _seed_order(linkdb, eoid="O8", link_status=None)
        await _seed_calc(linkdb, calc_id="C8")
        assert await manual_link_order(ACCOUNT_ID, oid, "C8") == "invalid_transition"

    @pytest.mark.asyncio
    async def test_calc_already_matched_not_reflipped(self, linkdb):
        # Linking to a calc already past active|released (e.g. matched by a
        # prior order — scale-in) links the order without re-flipping or
        # erroring.
        from core.link_actions import manual_link_order
        oid = await _seed_order(linkdb, eoid="O9", link_status="NEEDS_MANUAL_REVIEW")
        await _seed_calc(linkdb, calc_id="C9", status="matched")
        assert await manual_link_order(ACCOUNT_ID, oid, "C9") == "linked"
        assert (await _order(linkdb, oid))["link_status"] == "LINKED"
        assert await _calc_status(linkdb, "C9") == "matched"  # unchanged

    @pytest.mark.asyncio
    async def test_propagates_calc_id_to_opening_fills_only(self, linkdb):
        from core.link_actions import manual_link_order
        oid = await _seed_order(linkdb, eoid="OF", link_status="NEEDS_MANUAL_REVIEW")
        await _seed_calc(linkdb, calc_id="CF", status="active")
        await _seed_fill(linkdb, fid="f-open", eoid="OF", is_close=0)
        await _seed_fill(linkdb, fid="f-close", eoid="OF", is_close=1)

        assert await manual_link_order(ACCOUNT_ID, oid, "CF") == "linked"
        assert await _fill_calc(linkdb, "f-open") == "CF"     # opening inherits
        assert await _fill_calc(linkdb, "f-close") is None     # closing untouched (T2.2)


# ── mark_order_unplanned ───────────────────────────────────────────────


class TestMarkUnplanned:
    @pytest.mark.asyncio
    async def test_needs_review_to_unplanned(self, linkdb):
        from core.link_actions import mark_order_unplanned
        oid = await _seed_order(linkdb, eoid="U1", link_status="NEEDS_MANUAL_REVIEW")
        assert await mark_order_unplanned(ACCOUNT_ID, oid) == "marked"
        o = await _order(linkdb, oid)
        assert o["link_status"] == "UNPLANNED"
        _assert_calcid_linked_invariant(o)

    @pytest.mark.asyncio
    async def test_unlinked_to_unplanned(self, linkdb):
        from core.link_actions import mark_order_unplanned
        oid = await _seed_order(linkdb, eoid="U2", link_status="UNLINKED")
        assert await mark_order_unplanned(ACCOUNT_ID, oid) == "marked"
        assert (await _order(linkdb, oid))["link_status"] == "UNPLANNED"

    @pytest.mark.asyncio
    async def test_order_not_found(self, linkdb):
        from core.link_actions import mark_order_unplanned
        assert await mark_order_unplanned(ACCOUNT_ID, 4242) == "order_not_found"

    @pytest.mark.asyncio
    async def test_linked_not_markable(self, linkdb):
        # LINKED is forward-terminal — cannot be downgraded to UNPLANNED.
        from core.link_actions import mark_order_unplanned
        oid = await _seed_order(linkdb, eoid="U4", link_status="LINKED", calc_id="C-L")
        assert await mark_order_unplanned(ACCOUNT_ID, oid) == "invalid_transition"
        assert (await _order(linkdb, oid))["link_status"] == "LINKED"


# ── TOCTOU race (mirrors test_phase1_calc_cancel.TestCancelRace) ────────


class TestLinkActionRace:
    """The apply_fn UPDATE is guarded with WHERE link_status=<read> (+ calc_id
    IS NULL for link). If a concurrent writer (matcher re-run / bracket
    inheritance) flips the order out of the read state before apply_fn, the
    UPDATE hits 0 rows → LinkTransitionRaceLost → 'race_lost', and the
    operator action does NOT clobber the raced-in state. link_actions imports
    `transition as link_transition` at module scope, so patch the bound name
    in core.link_actions (not core.link_state)."""

    @pytest.mark.asyncio
    async def test_manual_link_race_lost(self, linkdb, monkeypatch):
        import core.link_actions as la
        from core.link_actions import manual_link_order

        oid = await _seed_order(linkdb, eoid="R1", link_status="NEEDS_MANUAL_REVIEW")
        await _seed_calc(linkdb, calc_id="CR", status="active")

        original = la.link_transition

        async def racing(order_id, current, target, *, apply_fn, **kw):
            # concurrent writer flips the order out of the read state.
            await linkdb._conn.execute(
                "UPDATE orders SET link_status = 'UNPLANNED' WHERE id = ?", (order_id,),
            )
            await linkdb._conn.commit()
            await original(order_id, current, target, apply_fn=apply_fn, **kw)

        monkeypatch.setattr(la, "link_transition", racing)

        assert await manual_link_order(ACCOUNT_ID, oid, "CR") == "race_lost"
        o = await _order(linkdb, oid)
        assert o["calc_id"] is None              # link NOT stamped
        assert o["link_status"] == "UNPLANNED"   # the raced-in value won
        assert await _calc_status(linkdb, "CR") == "active"  # calc NOT flipped

    @pytest.mark.asyncio
    async def test_mark_unplanned_race_lost(self, linkdb, monkeypatch):
        import core.link_actions as la
        from core.link_actions import mark_order_unplanned

        oid = await _seed_order(linkdb, eoid="R2", link_status="NEEDS_MANUAL_REVIEW")

        original = la.link_transition

        async def racing(order_id, current, target, *, apply_fn, **kw):
            await linkdb._conn.execute(
                "UPDATE orders SET link_status = 'LINKED', calc_id = 'C-RACE' "
                "WHERE id = ?", (order_id,),
            )
            await linkdb._conn.commit()
            await original(order_id, current, target, apply_fn=apply_fn, **kw)

        monkeypatch.setattr(la, "link_transition", racing)

        assert await mark_order_unplanned(ACCOUNT_ID, oid) == "race_lost"
        assert (await _order(linkdb, oid))["link_status"] == "LINKED"  # raced-in value won


# ── list_needs_review ──────────────────────────────────────────────────


class TestListNeedsReview:
    @pytest.mark.asyncio
    async def test_queue_filters_and_annotates_candidates(self, linkdb):
        from core.link_actions import list_needs_review
        # In queue:
        await _seed_order(linkdb, eoid="N1", link_status="NEEDS_MANUAL_REVIEW")
        await _seed_order(linkdb, eoid="N2", link_status="UNLINKED")
        # NOT in queue:
        await _seed_order(linkdb, eoid="N3", link_status="LINKED", calc_id="C-X")
        await _seed_order(linkdb, eoid="N4", link_status="UNPLANNED")
        # A close-matching, unlinked calc → should surface as a candidate.
        await _seed_calc(linkdb, calc_id="CAND", status="active",
                         entry=50000.0, tp=55000.0, sl=48000.0)

        queue = await list_needs_review(ACCOUNT_ID)
        eoids = {o["exchange_order_id"] for o in queue}
        assert eoids == {"N1", "N2"}
        assert all("candidates" in o for o in queue)
        n1 = next(o for o in queue if o["exchange_order_id"] == "N1")
        cand_ids = {c["calc_id"] for c in n1["candidates"]}
        assert "CAND" in cand_ids

    @pytest.mark.asyncio
    async def test_empty_queue(self, linkdb):
        from core.link_actions import list_needs_review
        await _seed_order(linkdb, eoid="E1", link_status="LINKED", calc_id="C-Y")
        assert await list_needs_review(ACCOUNT_ID) == []


# ── route registration import-smoke (no TestClient — gotcha #9) ─────────


class TestRoutesRegistered:
    def test_endpoints_registered(self):
        import api.routes_orders as ro

        def _has(path, method):
            return any(
                getattr(r, "path", None) == path
                and method in getattr(r, "methods", set())
                for r in ro.router.routes
            )

        assert _has("/orders/{order_id}/manual_link", "POST")
        assert _has("/orders/{order_id}/mark_unplanned", "POST")
        assert _has("/orders/needs_review", "GET")
