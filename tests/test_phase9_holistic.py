"""
Phase 9 HOLISTIC cross-task tests (filed by the Phase-9 holistic audit).

The per-task suites (test_phase9_multi_operator / _t3_operator_id /
_t4_session_timeout) each test ONE task in isolation — and crucially, the T3
order/amendment tests populate the operator-on-duty cache by directly
monkeypatching ``app_state.operator_id_by_account``, while the T1/T2/T4 route
tests assert the write-through against a throwaway ``SimpleNamespace``. So the
LOAD-BEARING producer→consumer chain of the whole phase — the register /
takeover / heartbeat endpoints WRITE the real ``app_state`` cache that the WS
stamp sites READ — was never exercised end-to-end. A dropped write-through on
any endpoint would pass all per-task tests while silently mis-attributing
every post-takeover / post-restart order.

These tests drive the REAL chain: real ``app_state`` singleton + the real
route handlers + the real ``OrderManager.process_order_update`` + the real
``reap_idle_sessions``. Intent (Rule 8):
  - takeover re-points the cache → the NEXT WS order is stamped the new owner;
  - the reaper invalidating the cache → the next WS order is stamped None
    (a gone operator stops being attributed);
  - cold cache (restart) → a heartbeat repopulates → WS attribution resumes;
  - process_order_update's setdefault never clobbers an upstream operator_id;
  - the manual-link action records WHO linked (on the manual_link_added event,
    NOT on orders.operator_id which holds the placement operator).

Run: pytest tests/test_phase9_holistic.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.auth_state import reap_idle_sessions
from core.state import app_state

ACCOUNT_ID = 1


def _arriving(eoid, *, account_id=ACCOUNT_ID, created_at_ms=1000):
    return {
        "account_id": account_id, "exchange_order_id": eoid, "symbol": "BTCUSDT",
        "side": "BUY", "order_type": "limit", "price": 50000.0,
        "stop_price": 0.0, "quantity": 1.0, "created_at_ms": created_at_ms,
    }


async def _order_operator(db, eoid, account_id=ACCOUNT_ID):
    async with db._conn.execute(
        "SELECT operator_id FROM orders WHERE account_id=? AND exchange_order_id=?",
        (account_id, eoid),
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else "<<missing>>"


async def _set_last_seen(db, sid, ts):
    await db._conn.execute(
        "UPDATE operator_sessions SET last_seen_ts=? WHERE id=?", (ts, sid))
    await db._conn.commit()


@pytest_asyncio.fixture
async def chain(monkeypatch):
    """The REAL register/takeover/heartbeat → app_state cache → WS-stamp chain,
    wired against a tempfile DB. Uses the REAL app_state singleton (not a
    SimpleNamespace) so the route write-through and the WS read share state."""
    import config
    from core.database import DatabaseManager
    from core.order_manager import OrderManager
    from core.account_registry import account_registry
    import api.routes_auth as ra

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    d = DatabaseManager(path=tmp.name)
    await d.initialize()
    await d._conn.execute(
        "INSERT OR IGNORE INTO accounts (id, name, config_json) VALUES (1,'T',?)",
        ('{"window_seconds": 300}',))
    await d._conn.commit()

    monkeypatch.setattr(config, "DB_PATH", tmp.name)
    monkeypatch.setattr(account_registry, "_active_id", ACCOUNT_ID)
    monkeypatch.setattr(app_state, "operator_id_by_account", {})   # real singleton, fresh
    monkeypatch.setattr(ra, "db", d)
    # process_order_update emits order trade events — keep them off the live DB.
    monkeypatch.setattr("core.trade_event_log.log_trade_event", lambda *a, **k: None)

    yield d, OrderManager(d), ra

    await d.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


class TestCrossTaskAttribution:
    @pytest.mark.asyncio
    async def test_takeover_repoints_cache_then_order_stamps_new_owner(self, chain):
        # SEAM-1 (the load-bearing chain): register/takeover WRITE the real
        # cache; the WS stamp READS it. A dropped write-through on either
        # endpoint is invisible to the per-task suites but fails here.
        d, om, ra = chain
        await ra.operator_session_register(operator_id="op-A")
        await om.process_order_update(ACCOUNT_ID, _arriving("O1"))
        assert await _order_operator(d, "O1") == "op-A"      # register write-through
        await ra.operator_session_takeover(operator_id="op-B")
        await om.process_order_update(ACCOUNT_ID, _arriving("O2"))
        assert await _order_operator(d, "O2") == "op-B"      # takeover write-through

    @pytest.mark.asyncio
    async def test_reap_invalidation_then_order_stamps_none(self, chain):
        # SEAM-2: the reaper clears the cache for a reaped seat → the NEXT WS
        # order stamps None (a gone operator stops being attributed). The
        # per-task test only asserted the dict was cleared, not the consequence.
        d, om, ra = chain
        await ra.operator_session_register(operator_id="op-A")
        await om.process_order_update(ACCOUNT_ID, _arriving("O1"))
        assert await _order_operator(d, "O1") == "op-A"
        active = await d.get_active_operator_session(ACCOUNT_ID)
        await _set_last_seen(d, active["id"], 1000)            # make it idle
        assert await reap_idle_sessions(d, idle_sec=1, now_ms=70_000) == 1
        await om.process_order_update(ACCOUNT_ID, _arriving("O2"))
        assert await _order_operator(d, "O2") is None         # gone operator not stamped

    @pytest.mark.asyncio
    async def test_cold_cache_heartbeat_repopulates_then_order_stamps(self, chain):
        # SEAM-3: engine restart → DB session survives, cache cold. A WS order
        # stamps None until a heartbeat write-throughs the cache; then it
        # resumes. Exercises the restart-recovery path end-to-end.
        d, om, ra = chain
        await d.start_operator_session(ACCOUNT_ID, "op-A")    # survived restart
        app_state.operator_id_by_account.clear()              # cold cache
        await om.process_order_update(ACCOUNT_ID, _arriving("O1"))
        assert await _order_operator(d, "O1") is None         # cold → None
        await ra.operator_session_heartbeat(operator_id="op-A")   # repopulate
        await om.process_order_update(ACCOUNT_ID, _arriving("O2"))
        assert await _order_operator(d, "O2") == "op-A"       # resumed

    @pytest.mark.asyncio
    async def test_process_order_update_setdefault_preserves_upstream_operator(self, chain):
        # SEAM-5: the WS stamp is setdefault, not an unconditional write — an
        # operator_id an upstream caller already set must survive.
        d, om, ra = chain
        app_state.operator_id_by_account[ACCOUNT_ID] = "cache-seat"
        order = _arriving("O1")
        order["operator_id"] = "explicit-Z"
        await om.process_order_update(ACCOUNT_ID, order)
        assert await _order_operator(d, "O1") == "explicit-Z"  # not clobbered by cache


# ── manual-link operator attribution (plan §9.3) ───────────────────────


@pytest_asyncio.fixture
async def linkdb(monkeypatch):
    """Wire core.link_actions.db (its module singleton) to a tempfile DB."""
    import config
    from core.database import DatabaseManager
    import core.link_actions as la
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    d = DatabaseManager(path=tmp.name)
    await d.initialize()
    monkeypatch.setattr(la, "db", d)
    monkeypatch.setattr(config, "DB_PATH", tmp.name)
    yield d
    await d.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


class TestManualLinkOperatorAttribution:
    @pytest.mark.asyncio
    async def test_manual_link_event_carries_active_operator(self, linkdb, monkeypatch):
        # plan §9.3: the manual-link ACTION records WHO linked — on the
        # manual_link_added event (NOT orders.operator_id, which holds the
        # placement operator). Resolved from the active operator session.
        from core.link_actions import manual_link_order

        captured: list = []
        monkeypatch.setattr(
            "core.trade_event_log.log_trade_event",
            lambda account_id, calc_id, event_type, payload, source="", **k:
                captured.append((event_type, payload)) or 1)

        # seed: a NEEDS_MANUAL_REVIEW order + an active calc + an operator session
        await linkdb._conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
            "order_type, status, price, link_status) "
            "VALUES (?, 'EO1', 'BTCUSDT', 'BUY', 'limit', 'new', 50000, 'NEEDS_MANUAL_REVIEW')",
            (ACCOUNT_ID,))
        oid = (await (await linkdb._conn.execute(
            "SELECT id FROM orders WHERE exchange_order_id='EO1'")).fetchone())[0]
        await linkdb._conn.execute(
            "INSERT INTO pre_trade_log (account_id, timestamp, ticker, calc_id, status) "
            "VALUES (?, '2026-06-07T00:00:00Z', 'BTCUSDT', 'C1', 'active')", (ACCOUNT_ID,))
        await linkdb._conn.commit()
        await linkdb.start_operator_session(ACCOUNT_ID, "op-LINKER")

        assert await manual_link_order(ACCOUNT_ID, oid, "C1") == "linked"

        added = [p for et, p in captured if et == "manual_link_added"]
        assert len(added) == 1
        assert added[0]["operator_id"] == "op-LINKER"     # who linked, on the event
        # placement column is NOT clobbered by the linker (it was never set here)
        assert await _order_operator(linkdb, "EO1") is None

    @pytest.mark.asyncio
    async def test_manual_link_event_operator_none_without_session(self, linkdb, monkeypatch):
        from core.link_actions import manual_link_order
        captured: list = []
        monkeypatch.setattr(
            "core.trade_event_log.log_trade_event",
            lambda account_id, calc_id, event_type, payload, source="", **k:
                captured.append((event_type, payload)) or 1)
        await linkdb._conn.execute(
            "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
            "order_type, status, price, link_status) "
            "VALUES (?, 'EO2', 'BTCUSDT', 'BUY', 'limit', 'new', 50000, 'NEEDS_MANUAL_REVIEW')",
            (ACCOUNT_ID,))
        oid = (await (await linkdb._conn.execute(
            "SELECT id FROM orders WHERE exchange_order_id='EO2'")).fetchone())[0]
        await linkdb._conn.execute(
            "INSERT INTO pre_trade_log (account_id, timestamp, ticker, calc_id, status) "
            "VALUES (?, '2026-06-07T00:00:00Z', 'BTCUSDT', 'C2', 'active')", (ACCOUNT_ID,))
        await linkdb._conn.commit()
        # no operator session started → None (best-effort, link still succeeds)
        assert await manual_link_order(ACCOUNT_ID, oid, "C2") == "linked"
        added = [p for et, p in captured if et == "manual_link_added"]
        assert added and added[0]["operator_id"] is None
