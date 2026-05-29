"""
Phase 3 Task 1 (P3.T1) tests — route every ``orders.link_status`` write
through the ``core/link_state`` choke-point (spec §3.6).

P3.T1 sweeps the two raw-UPDATE sites onto ``link_state.auto_classify``:

  - ``core/order_enrichment._try_correlate`` (the strict matcher, §4.3)
  - ``core/order_manager._propagate_bracket_calc_id`` (bracket
    inheritance, §4.5)

Why a SEPARATE ``auto_classify`` and not ``transition()`` (Rule 8 — the
tests encode WHY this design exists): both sites assign link_status from
an *undecided* source. The matcher does NULL→X on first arrival AND
UNPLANNED→X on re-run (a candidate-less order upgrades to LINKED when a
matching calc finally arrives). ``transition()`` validates moves between
DECIDED enum values and — correctly for the OPERATOR state machine —
rejects UNPLANNED→LINKED (UNPLANNED is operator-terminal, see
``test_state_machines.TestLinkTransitionMatrix``). So the engine's
auto-classification needs its own entry point; routing it through
``transition()`` would wrongly reject the legitimate re-match upgrade.

Run: pytest tests/test_phase3_link_state.py -v
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core import link_state
from core.link_state import (
    AUTO_CLASSIFY_TARGETS,
    IllegalStateTransition,
    LinkStatus,
    assert_auto_classify,
    auto_classify,
)
from core.calc_correlation import (
    LINK_STATUS_LINKED,
    LINK_STATUS_NEEDS_MANUAL_REVIEW,
    LINK_STATUS_UNPLANNED,
)

ACCOUNT_ID = 1


# ── Fixtures / helpers ─────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db():
    """Tempfile DB initialized with the full schema."""
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    database = DatabaseManager(path=tmp.name)
    await database.initialize()
    await database._conn.execute(
        "INSERT OR IGNORE INTO accounts (id, name) VALUES (?, ?)",
        (ACCOUNT_ID, "Test"),
    )
    await database._conn.commit()
    yield database, tmp.name
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
    database, _ = db
    return OrderManager(database)


def _now_iso(offset_sec: float = 0.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_sec)).isoformat()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _insert_calc(db_path: str, *, calc_id: str, ticker: str, side: str,
                 effective_entry: float, tp_price: float, sl_price: float,
                 status: str = "active") -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO pre_trade_log "
            "(account_id, timestamp, ticker, side, effective_entry, "
            " tp_price, sl_price, average, calc_id, status, window_seconds) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ACCOUNT_ID, _now_iso(-5.0), ticker, side, effective_entry,
             tp_price, sl_price, effective_entry, calc_id, status, 300),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_order(db_path: str, *, exchange_order_id: str, symbol: str,
                  side: str, order_type: str, price: float,
                  tp_trigger_price: float, sl_trigger_price: float) -> int:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO orders "
            "(account_id, exchange_order_id, symbol, side, order_type, "
            " price, tp_trigger_price, sl_trigger_price, avg_fill_price, "
            " created_at_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ACCOUNT_ID, exchange_order_id, symbol, side, order_type, price,
             tp_trigger_price, sl_trigger_price, 0.0, _now_ms()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _read_order(db_path: str, order_id: int) -> Tuple[Optional[str], Optional[str]]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT calc_id, link_status FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
    finally:
        conn.close()


async def _seed_bracket_order(db, eoid, *, order_type, calc_id=None,
                              link_status=None, reduce_only=0, side="BUY",
                              created_at_ms=1000, symbol="BTCUSDT") -> int:
    cur = await db._conn.execute(
        "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
        " order_type, reduce_only, position_side, created_at_ms, status, "
        " client_order_id, calc_id, link_status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ACCOUNT_ID, eoid, symbol, side, order_type, reduce_only, "LONG",
         created_at_ms, "new", "", calc_id, link_status),
    )
    await db._conn.commit()
    return cur.lastrowid


async def _read_bracket(db, eoid) -> Dict[str, Any]:
    async with db._conn.execute(
        "SELECT calc_id, link_status FROM orders "
        "WHERE account_id=? AND exchange_order_id=?",
        (ACCOUNT_ID, eoid),
    ) as cur:
        r = await cur.fetchone()
    return {"calc_id": r[0], "link_status": r[1]}


def _spy_auto_classify(monkeypatch) -> List[Tuple[int, str]]:
    """Wrap link_state.auto_classify so calls are recorded AND still
    delegated to the real choke-point. Returns the recording list of
    (order_id, target_status). Both write sites do a call-time
    ``from core.link_state import auto_classify`` (lazy import), so
    patching the module attribute intercepts them."""
    recorded: List[Tuple[int, str]] = []
    real = link_state.auto_classify

    async def _wrapper(order_id, target_status, *, apply_fn, **kw):
        recorded.append((order_id, target_status))
        await real(order_id, target_status, apply_fn=apply_fn, **kw)

    monkeypatch.setattr(link_state, "auto_classify", _wrapper)
    return recorded


# ── 1. auto_classify choke-point — unit ────────────────────────────────


class TestAutoClassifyUnit:
    def test_targets_are_the_three_matcher_outputs(self):
        # UNLINKED is operator-set only and must NOT be auto-assignable.
        assert AUTO_CLASSIFY_TARGETS == {
            LinkStatus.LINKED,
            LinkStatus.NEEDS_MANUAL_REVIEW,
            LinkStatus.UNPLANNED,
        }
        assert LinkStatus.UNLINKED not in AUTO_CLASSIFY_TARGETS

    @pytest.mark.parametrize("target", [
        LINK_STATUS_LINKED,
        LINK_STATUS_NEEDS_MANUAL_REVIEW,
        LINK_STATUS_UNPLANNED,
    ])
    @pytest.mark.asyncio
    async def test_valid_target_calls_apply(self, target):
        applied = {"called": False}

        async def apply_fn():
            applied["called"] = True

        await auto_classify(7, target, apply_fn=apply_fn)
        assert applied["called"] is True

    @pytest.mark.asyncio
    async def test_unlinked_target_rejected_does_not_apply(self):
        applied = {"called": False}

        async def apply_fn():
            applied["called"] = True

        with pytest.raises(IllegalStateTransition) as exc:
            await auto_classify(9, "UNLINKED", apply_fn=apply_fn)
        assert exc.value.order_id == 9
        assert exc.value.target == "UNLINKED"
        assert applied["called"] is False

    @pytest.mark.asyncio
    async def test_unknown_target_rejected_does_not_apply(self):
        applied = {"called": False}

        async def apply_fn():
            applied["called"] = True

        with pytest.raises(IllegalStateTransition):
            await auto_classify(11, "FROBNICATE", apply_fn=apply_fn)
        assert applied["called"] is False

    def test_assert_auto_classify_raises_on_bad_target(self):
        with pytest.raises(IllegalStateTransition):
            assert_auto_classify(3, "UNLINKED")
        # valid ones do not raise
        assert_auto_classify(3, "LINKED")

    @pytest.mark.asyncio
    async def test_no_event_published_today(self, monkeypatch):
        # TRANSITION_EVENT_MAP is empty until Phase 6 — auto_classify
        # must complete cleanly WITHOUT publishing.
        published = []

        async def fake_publish(channel, payload):
            published.append((channel, payload))

        from core import event_bus as ebmod
        monkeypatch.setattr(ebmod.event_bus, "publish", fake_publish)

        async def apply_fn():
            pass

        await auto_classify(13, LINK_STATUS_LINKED, apply_fn=apply_fn)
        assert published == []

    @pytest.mark.asyncio
    async def test_apply_failure_propagates(self):
        async def apply_fn():
            raise RuntimeError("db down")

        with pytest.raises(RuntimeError, match="db down"):
            await auto_classify(15, LINK_STATUS_LINKED, apply_fn=apply_fn)


# ── 2. matcher routes its link_status write through auto_classify ──────


class TestMatcherRoutesThroughChokePoint:
    @pytest.mark.asyncio
    async def test_full_match_routes_linked(self, db, monkeypatch):
        from core.order_enrichment import enrich_order
        import config

        _, db_path = db
        monkeypatch.setattr(config, "DB_PATH", db_path)
        recorded = _spy_auto_classify(monkeypatch)

        _insert_calc(db_path, calc_id="calc-a", ticker="BTCUSDT", side="long",
                     effective_entry=50000.0, tp_price=55000.0, sl_price=48000.0)
        oid = _insert_order(
            db_path, exchange_order_id="o1", symbol="BTCUSDT", side="long",
            order_type="limit", price=50000.0,
            tp_trigger_price=55000.0, sl_trigger_price=48000.0,
        )

        await enrich_order(
            {"account_id": ACCOUNT_ID, "exchange_order_id": "o1",
             "symbol": "BTCUSDT", "side": "long", "order_type": "limit"},
            db_path,
        )

        # routed through the choke-point (not a raw UPDATE) ...
        assert (oid, LINK_STATUS_LINKED) in recorded
        # ... and the DB outcome is intact.
        calc_id, link_status = _read_order(db_path, oid)
        assert calc_id == "calc-a"
        assert link_status == LINK_STATUS_LINKED

    @pytest.mark.asyncio
    async def test_no_candidate_routes_unplanned(self, db, monkeypatch):
        from core.order_enrichment import enrich_order
        import config

        _, db_path = db
        monkeypatch.setattr(config, "DB_PATH", db_path)
        recorded = _spy_auto_classify(monkeypatch)

        oid = _insert_order(
            db_path, exchange_order_id="o2", symbol="ETHUSDT", side="long",
            order_type="limit", price=3000.0,
            tp_trigger_price=3300.0, sl_trigger_price=2800.0,
        )
        await enrich_order(
            {"account_id": ACCOUNT_ID, "exchange_order_id": "o2",
             "symbol": "ETHUSDT", "side": "long", "order_type": "limit"},
            db_path,
        )

        assert (oid, LINK_STATUS_UNPLANNED) in recorded
        calc_id, link_status = _read_order(db_path, oid)
        assert calc_id is None
        assert link_status == LINK_STATUS_UNPLANNED

    @pytest.mark.asyncio
    async def test_unplanned_then_linked_upgrade_via_auto_classify(
        self, db, monkeypatch,
    ):
        """The load-bearing case: an order first classified UNPLANNED
        (no calc in window) is UPGRADED to LINKED on matcher re-run when
        a matching calc finally arrives. This is exactly the move
        ``transition()`` would REJECT (UNPLANNED is operator-terminal),
        so it MUST go through ``auto_classify`` — proving why the two
        entry points are distinct."""
        from core.order_enrichment import enrich_order
        import config

        _, db_path = db
        monkeypatch.setattr(config, "DB_PATH", db_path)

        order_payload = {
            "account_id": ACCOUNT_ID, "exchange_order_id": "o3",
            "symbol": "BTCUSDT", "side": "long", "order_type": "limit",
        }
        oid = _insert_order(
            db_path, exchange_order_id="o3", symbol="BTCUSDT", side="long",
            order_type="limit", price=50000.0,
            tp_trigger_price=55000.0, sl_trigger_price=48000.0,
        )

        # 1st pass — no calc → UNPLANNED.
        await enrich_order(order_payload, db_path)
        assert _read_order(db_path, oid)[1] == LINK_STATUS_UNPLANNED

        # A matching calc now arrives; 2nd pass re-runs (UNPLANNED is
        # allowed to re-run, unlike NEEDS_MANUAL_REVIEW).
        _insert_calc(db_path, calc_id="calc-late", ticker="BTCUSDT",
                     side="long", effective_entry=50000.0,
                     tp_price=55000.0, sl_price=48000.0)
        recorded = _spy_auto_classify(monkeypatch)
        await enrich_order(order_payload, db_path)

        calc_id, link_status = _read_order(db_path, oid)
        assert calc_id == "calc-late"
        assert link_status == LINK_STATUS_LINKED
        # The upgrade went through auto_classify with the undecided
        # source — NOT transition(), which forbids it:
        assert (oid, LINK_STATUS_LINKED) in recorded
        assert link_state.validate_transition("UNPLANNED", "LINKED") is False


# ── 3. bracket inheritance routes through auto_classify ────────────────


class TestBracketRoutesThroughChokePoint:
    @pytest.mark.asyncio
    async def test_protective_legs_linked_via_auto_classify(
        self, db, om, monkeypatch,
    ):
        database, _ = db
        recorded = _spy_auto_classify(monkeypatch)

        await _seed_bracket_order(database, "E", order_type="limit",
                                  calc_id="C1", link_status="LINKED",
                                  created_at_ms=1000)
        tp_id = await _seed_bracket_order(database, "TP",
                                          order_type="take_profit",
                                          reduce_only=1, side="SELL",
                                          created_at_ms=1100)
        sl_id = await _seed_bracket_order(database, "SL",
                                          order_type="stop_loss",
                                          reduce_only=1, side="SELL",
                                          created_at_ms=1200)

        await om._propagate_bracket_calc_id(ACCOUNT_ID, "BTCUSDT")

        # Both protective legs inherited via the choke-point ...
        assert (tp_id, LINK_STATUS_LINKED) in recorded
        assert (sl_id, LINK_STATUS_LINKED) in recorded
        # ... with the DB invariant intact (calc_id present ⟺ LINKED).
        for eoid in ("TP", "SL"):
            row = await _read_bracket(database, eoid)
            assert row["calc_id"] == "C1", eoid
            assert row["link_status"] == "LINKED", eoid

    @pytest.mark.asyncio
    async def test_nothing_to_inherit_does_not_classify(
        self, db, om, monkeypatch,
    ):
        # An entry with NO calc_id cannot seed inheritance — no
        # auto_classify call should fire (bounded-by-design, spec §4.5).
        database, _ = db
        recorded = _spy_auto_classify(monkeypatch)

        await _seed_bracket_order(database, "E", order_type="limit",
                                  created_at_ms=1000)
        await _seed_bracket_order(database, "TP", order_type="take_profit",
                                  reduce_only=1, side="SELL",
                                  created_at_ms=1100)

        await om._propagate_bracket_calc_id(ACCOUNT_ID, "BTCUSDT")
        assert recorded == []
