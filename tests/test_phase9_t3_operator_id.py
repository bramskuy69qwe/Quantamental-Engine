"""
Phase 9 Task 3 (P9.T3) — ``operator_id`` propagation onto action rows.

Stamps the active operator session's seat (``operator_id``) onto the three
action-row tables that carry the column: ``pre_trade_log`` (calc creation),
``orders`` (WS arrival), and ``order_amendments`` — plus the matching
``calc:created`` and ``position:amended`` event payloads. Spec §3.1/§3.2/§9 +
Q56 ("operator_id on every action row"); plan §9 P9.T3.

Two resolve paths (HANDOFF P9.T3 hot-path note):

  - ``current_operator_id(db, account_id)`` — authoritative DB resolve. Used by
    the NON-hot calc-creation path, where "who created this calc" is HIGH VALUE
    and must be correct even when the WS cache is cold (e.g. right after a
    restart, before any browser registers).
  - ``cached_operator_id(account_id)`` — O(1) read of the ``app_state``
    write-through cache (set on register/takeover). Used by the HOT WS
    order/amendment write sites; ``None`` when no seat has registered, which is
    acceptable there (weak, best-effort attribution).

Intent (Rule 8) — what these tests pin that a refactor must not break:
  - the resolvers are BEST-EFFORT: a DB/cache fault yields ``None``, never an
    exception that would break the calc/order/amendment write it decorates;
  - the calc-creation stamp is DB-resolved (correct even when the cache is cold);
  - the WS stamps read the cache and tolerate a cold cache (``None``);
  - the ``orders`` ON CONFLICT is FIRST-KNOWN-WINS: a later observation never
    nulls a known operator nor reattributes to a later seat, but DOES back-fill
    a NULL (REST-landed-first → WS back-fills);
  - the caveat is honest: attribution is to the ACTIVE session owner, NOT the
    request submitter — a foreign seat's calc mis-attributes to the owner
    (acceptable at single-tenant localhost);
  - the event payloads carry the same resolved id, not the pre-P9 ``None``.

Run: pytest tests/test_phase9_t3_operator_id.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.auth_state import (
    cached_operator_id,
    current_operator_id,
    register_session,
    takeover_session,
)
from core.state import app_state

ACCOUNT_ID = 1


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db():
    """Tempfile DB with the full schema + account 1."""
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    d = DatabaseManager(path=tmp.name)
    await d.initialize()
    await d._conn.execute(
        "INSERT OR IGNORE INTO accounts (id, name, config_json) "
        "VALUES (1, 'Test', ?)",
        ('{"window_seconds": 300}',),
    )
    await d._conn.commit()
    yield d, tmp.name
    await d.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


@pytest_asyncio.fixture
async def om(db, monkeypatch):
    """OrderManager over the test DB, with config.DB_PATH repointed so the
    enrichment/correlation reads inside process_order_update hit it (mirrors
    the test_phase2_junction `real` fixture)."""
    import config
    from core.order_manager import OrderManager
    d, db_path = db
    monkeypatch.setattr(config, "DB_PATH", db_path)
    return OrderManager(d)


@pytest.fixture(autouse=True)
def captured_trade_events(monkeypatch):
    """Capture ``log_trade_event`` for the whole module.

    (1) No test writes the LIVE per-account DB (the producer resolves
    config.DATA_DIR where account 1 exists live). (2) The event tests assert
    the captured payloads. Both calc-creation and ``_emit_amendment_event``
    lazy-import ``log_trade_event``, so patching the module attribute binds the
    fake at call time."""
    captured: list = []

    def _fake(account_id, calc_id, event_type, payload, source="", **_kw):
        captured.append({
            "account_id": account_id, "calc_id": calc_id,
            "event_type": event_type, "payload": payload, "source": source,
        })
        return 1

    monkeypatch.setattr("core.trade_event_log.log_trade_event", _fake)
    return captured


@pytest.fixture(autouse=True)
def _clean_bus():
    """event_bus is a module singleton with a shared queue; drain before AND
    after each test so a publish-without-drain can't leak crumbs across tests
    (or into other files that assert on a clean bus)."""
    _drain_bus()
    yield
    _drain_bus()


def _drain_bus():
    from core.event_bus import event_bus
    out = []
    while not event_bus._queue.empty():
        out.append(event_bus._queue.get_nowait())
    return out


async def _calc_payload(**over):
    p = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ticker": "BTCUSDT",
        "side": "long",
        "effective_entry": 50000.0,
        "tp_price": 55000.0,
        "sl_price": 48000.0,
        "calc_id": "calc-1",
        "eligible": True,
    }
    p.update(over)
    return p


async def _calc_operator(db, calc_id):
    async with db._conn.execute(
        "SELECT operator_id FROM pre_trade_log WHERE calc_id=?", (calc_id,),
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else "<<missing>>"


async def _order_operator(db, eoid, account_id=ACCOUNT_ID):
    async with db._conn.execute(
        "SELECT operator_id FROM orders WHERE account_id=? AND exchange_order_id=?",
        (account_id, eoid),
    ) as cur:
        row = await cur.fetchone()
    return row[0] if row else "<<missing>>"


async def _seed_working_order(db, eoid, *, order_type="limit", price=0.0,
                              stop_price=0.0, quantity=0.0, status="new",
                              calc_id=None, terminal_position_id="",
                              account_id=ACCOUNT_ID):
    cur = await db._conn.execute(
        "INSERT INTO orders (account_id, exchange_order_id, symbol, side, "
        " order_type, status, price, stop_price, quantity, calc_id, "
        " terminal_position_id) "
        "VALUES (?, ?, 'BTCUSDT', 'BUY', ?, ?, ?, ?, ?, ?, ?)",
        (account_id, eoid, order_type, status, price, stop_price, quantity,
         calc_id, terminal_position_id),
    )
    await db._conn.commit()
    return cur.lastrowid


def _amend_incoming(eoid, *, order_type="limit", price=0.0, stop_price=0.0,
                    quantity=0.0, updated_at_ms=1000):
    return {
        "account_id": ACCOUNT_ID, "exchange_order_id": eoid,
        "order_type": order_type, "status": "new", "price": price,
        "stop_price": stop_price, "quantity": quantity,
        "updated_at_ms": updated_at_ms,
    }


def _arriving(eoid, *, created_at_ms=1000, account_id=ACCOUNT_ID):
    return {
        "account_id": account_id, "exchange_order_id": eoid, "symbol": "BTCUSDT",
        "side": "BUY", "order_type": "limit", "price": 50000.0,
        "stop_price": 0.0, "quantity": 1.0, "created_at_ms": created_at_ms,
    }


# ── 1. Resolvers (core/auth_state) ────────────────────────────────────


class TestResolvers:
    @pytest.mark.asyncio
    async def test_current_operator_id_resolves_active_session(self, db):
        d, _ = db
        await register_session(d, ACCOUNT_ID, "seat-A")
        assert await current_operator_id(d, ACCOUNT_ID) == "seat-A"

    @pytest.mark.asyncio
    async def test_current_operator_id_none_when_no_session(self, db):
        d, _ = db
        assert await current_operator_id(d, ACCOUNT_ID) is None

    @pytest.mark.asyncio
    async def test_current_operator_id_best_effort_on_fault(self, db, monkeypatch):
        # A resolver fault must NOT propagate — attribution is non-blocking.
        d, _ = db

        async def _boom(_aid):
            raise RuntimeError("db down")

        monkeypatch.setattr(d, "get_active_operator_session", _boom)
        assert await current_operator_id(d, ACCOUNT_ID) is None

    @pytest.mark.asyncio
    async def test_current_operator_id_most_recent_active_wins(self, db):
        # Best-effort single-active is not guaranteed (P9.T1 note); the resolver
        # leans on get_active_operator_session's most-recent ordering.
        d, _ = db
        await d.start_operator_session(ACCOUNT_ID, "seat-old", start_ts_ms=1000)
        await d.start_operator_session(ACCOUNT_ID, "seat-new", start_ts_ms=2000)
        assert await current_operator_id(d, ACCOUNT_ID) == "seat-new"

    def test_cached_operator_id_reads_app_state_cache(self, monkeypatch):
        monkeypatch.setattr(app_state, "operator_id_by_account", {7: "seat-7"})
        assert cached_operator_id(7) == "seat-7"
        assert cached_operator_id(99) is None        # cold for another account

    def test_cached_operator_id_coerces_empty_seat_to_none(self, monkeypatch):
        # Symmetry with current_operator_id (which does `op if op else None`):
        # an empty/falsy cached seat must NOT stamp an empty string onto rows.
        monkeypatch.setattr(app_state, "operator_id_by_account", {7: ""})
        assert cached_operator_id(7) is None


# ── 2. Write-through cache (api/routes_auth) ───────────────────────────


def _wire_routes(monkeypatch, d, account_id=ACCOUNT_ID):
    import api.routes_auth as ra
    ns = SimpleNamespace(active_account_id=account_id, operator_id_by_account={})
    monkeypatch.setattr(ra, "db", d)
    monkeypatch.setattr(ra, "app_state", ns)
    return ra, ns


class TestWriteThroughCache:
    @pytest.mark.asyncio
    async def test_register_owner_sets_cache(self, db, monkeypatch):
        d, _ = db
        ra, ns = _wire_routes(monkeypatch, d)
        await ra.operator_session_register(operator_id="seat-A")
        assert ns.operator_id_by_account[ACCOUNT_ID] == "seat-A"

    @pytest.mark.asyncio
    async def test_register_foreign_does_not_set_cache(self, db, monkeypatch):
        # A non-owner (foreign) seat must NOT claim the cache — the owner stays.
        d, _ = db
        ra, ns = _wire_routes(monkeypatch, d)
        await ra.operator_session_register(operator_id="seat-A")   # owner
        await ra.operator_session_register(operator_id="seat-B")   # foreign
        assert ns.operator_id_by_account[ACCOUNT_ID] == "seat-A"

    @pytest.mark.asyncio
    async def test_takeover_sets_cache_to_new_seat(self, db, monkeypatch):
        d, _ = db
        ra, ns = _wire_routes(monkeypatch, d)
        await ra.operator_session_register(operator_id="seat-A")
        await ra.operator_session_takeover(operator_id="seat-B")
        assert ns.operator_id_by_account[ACCOUNT_ID] == "seat-B"


# ── 3. Site 1 — calc creation (pre_trade_log + calc:created) ───────────


@pytest_asyncio.fixture
async def wired_handlers(db, monkeypatch):
    """Point core.handlers.db at the test DB (calc-creation resolves operator
    via this module-level db). Pin the active account to ACCOUNT_ID so the
    calc tests don't depend on the global account_registry default coinciding
    with 1 — handle_risk_calculated reads app_state.active_account_id (→
    account_registry.active_id → _active_id) for BOTH the resolve and the
    insert; an earlier test mutating it would otherwise target a different
    account than the session we seed here."""
    d, db_path = db
    from core import handlers
    from core.account_registry import account_registry
    monkeypatch.setattr(handlers, "db", d)
    monkeypatch.setattr(account_registry, "_active_id", ACCOUNT_ID)
    return handlers, d


class TestCalcCreationStamp:
    @pytest.mark.asyncio
    async def test_calc_stamped_with_active_operator(self, wired_handlers):
        handlers, d = wired_handlers
        await register_session(d, ACCOUNT_ID, "seat-A")
        await handlers.handle_risk_calculated(await _calc_payload(calc_id="c-1"))
        assert await _calc_operator(d, "c-1") == "seat-A"

    @pytest.mark.asyncio
    async def test_calc_operator_none_when_no_session(self, wired_handlers):
        handlers, d = wired_handlers
        await handlers.handle_risk_calculated(await _calc_payload(calc_id="c-2"))
        assert await _calc_operator(d, "c-2") is None

    @pytest.mark.asyncio
    async def test_calc_created_event_carries_operator_id(self, wired_handlers):
        handlers, d = wired_handlers
        await register_session(d, ACCOUNT_ID, "seat-A")
        _drain_bus()
        await handlers.handle_risk_calculated(
            await _calc_payload(calc_id="c-3", eligible=True))
        # Exact per-account topic (account pinned to ACCOUNT_ID by the fixture)
        # — a wrong-account-channel regression must FAIL, not pass on a suffix.
        chan = f"engine:account:{ACCOUNT_ID}:calc:created"
        created = [p for c, p in _drain_bus() if c == chan]
        assert len(created) == 1
        assert created[0]["calc_id"] == "c-3"
        assert created[0]["operator_id"] == "seat-A"

    @pytest.mark.asyncio
    async def test_calc_insert_survives_resolver_fault(self, wired_handlers, monkeypatch):
        # Resolver fault → operator None, but the calc still persists (the
        # attribution must never break the money-path write).
        handlers, d = wired_handlers
        await register_session(d, ACCOUNT_ID, "seat-A")

        async def _boom(_aid):
            raise RuntimeError("db down")

        monkeypatch.setattr(d, "get_active_operator_session", _boom)
        await handlers.handle_risk_calculated(await _calc_payload(calc_id="c-4"))
        assert await _calc_operator(d, "c-4") is None      # row exists, op NULL


class TestForeignSeatCaveat:
    @pytest.mark.asyncio
    async def test_foreign_seat_calc_misattributes_to_active_owner(self, wired_handlers):
        # CAVEAT (b), pinned: handle_risk_calculated has no submitter identity —
        # it attributes to the ACTIVE session owner. A foreign seat present (B,
        # banner shown, no row started) does NOT change attribution: the calc is
        # stamped with the owner A, not B. Acceptable at single-tenant localhost.
        handlers, d = wired_handlers
        await register_session(d, ACCOUNT_ID, "seat-A")     # A owns
        await register_session(d, ACCOUNT_ID, "seat-B")     # B foreign (no row)
        await handlers.handle_risk_calculated(await _calc_payload(calc_id="c-5"))
        assert await _calc_operator(d, "c-5") == "seat-A"


# ── 4. Site 2 — orders (WS arrival + upsert COALESCE) ──────────────────


class TestOrderStamp:
    @pytest.mark.asyncio
    async def test_order_arrival_stamps_cached_operator(self, om, db, monkeypatch):
        # REAL cache path: set app_state cache → cached_operator_id reads it →
        # process_order_update stamps the orders row.
        from core.state import app_state
        monkeypatch.setattr(app_state, "operator_id_by_account", {ACCOUNT_ID: "seat-Y"})
        d, _ = db
        await om.process_order_update(ACCOUNT_ID, _arriving("WS-1"))
        assert await _order_operator(d, "WS-1") == "seat-Y"

    @pytest.mark.asyncio
    async def test_order_operator_none_when_cache_cold(self, om, db, monkeypatch):
        monkeypatch.setattr(app_state, "operator_id_by_account", {})   # cold
        d, _ = db
        await om.process_order_update(ACCOUNT_ID, _arriving("WS-2"))
        assert await _order_operator(d, "WS-2") is None

    @pytest.mark.asyncio
    async def test_order_stamp_is_account_scoped(self, om, db, monkeypatch):
        # An order arriving on account 2 must stamp account 2's seat — proves
        # cached_operator_id is called with the ORDER's account_id, not a
        # hardcoded/closure-captured one (a mutation passing ACCOUNT_ID=1 would
        # otherwise survive the whole suite).
        monkeypatch.setattr(
            app_state, "operator_id_by_account", {1: "seat-A", 2: "seat-B"})
        d, _ = db
        await om.process_order_update(2, _arriving("WS-acct2", account_id=2))
        assert await _order_operator(d, "WS-acct2", account_id=2) == "seat-B"

    @pytest.mark.asyncio
    async def test_upsert_coalesce_preserves_first_known(self, db):
        # First-known-wins: a later observation never nulls nor reattributes.
        d, _ = db
        await d.upsert_order_batch([{
            "account_id": ACCOUNT_ID, "exchange_order_id": "C-1",
            "symbol": "BTCUSDT", "updated_at_ms": 1000, "operator_id": "seat-A"}])
        # later observation with NO operator (e.g. REST reconciliation)
        await d.upsert_order_batch([{
            "account_id": ACCOUNT_ID, "exchange_order_id": "C-1",
            "symbol": "BTCUSDT", "updated_at_ms": 2000, "operator_id": None}])
        assert await _order_operator(d, "C-1") == "seat-A"
        # later observation with a DIFFERENT seat must NOT reattribute
        await d.upsert_order_batch([{
            "account_id": ACCOUNT_ID, "exchange_order_id": "C-1",
            "symbol": "BTCUSDT", "updated_at_ms": 3000, "operator_id": "seat-B"}])
        assert await _order_operator(d, "C-1") == "seat-A"

    @pytest.mark.asyncio
    async def test_upsert_coalesce_backfills_null(self, db):
        # REST landed first (no operator); the WS arrival back-fills it.
        d, _ = db
        await d.upsert_order_batch([{
            "account_id": ACCOUNT_ID, "exchange_order_id": "C-2",
            "symbol": "BTCUSDT", "updated_at_ms": 1000, "operator_id": None}])
        await d.upsert_order_batch([{
            "account_id": ACCOUNT_ID, "exchange_order_id": "C-2",
            "symbol": "BTCUSDT", "updated_at_ms": 2000, "operator_id": "seat-A"}])
        assert await _order_operator(d, "C-2") == "seat-A"


# ── 5. Site 3 — order_amendments + position:amended payloads ───────────


@pytest_asyncio.fixture
async def om_plain(db):
    from core.order_manager import OrderManager
    d, _ = db
    return OrderManager(d)


class TestAmendmentStamp:
    @pytest.mark.asyncio
    async def test_amendment_row_stamped_with_cached_operator(
        self, om_plain, db, monkeypatch
    ):
        from core.state import app_state
        monkeypatch.setattr(app_state, "operator_id_by_account", {ACCOUNT_ID: "seat-Z"})
        d, _ = db
        oid = await _seed_working_order(
            d, "A-1", order_type="limit", price=50000.0, quantity=1.0)
        await om_plain.detect_and_persist_amendment(
            ACCOUNT_ID, _amend_incoming("A-1", price=50100.0, quantity=1.0))
        async with d._conn.execute(
            "SELECT operator_id FROM order_amendments WHERE order_id=?", (oid,),
        ) as cur:
            rows = await cur.fetchall()
        assert rows and all(r[0] == "seat-Z" for r in rows)

    @pytest.mark.asyncio
    async def test_amendment_operator_none_when_cache_cold(
        self, om_plain, db, monkeypatch
    ):
        from core.state import app_state
        monkeypatch.setattr(app_state, "operator_id_by_account", {})
        d, _ = db
        oid = await _seed_working_order(
            d, "A-2", order_type="limit", price=50000.0, quantity=1.0)
        await om_plain.detect_and_persist_amendment(
            ACCOUNT_ID, _amend_incoming("A-2", price=50100.0, quantity=1.0))
        async with d._conn.execute(
            "SELECT operator_id FROM order_amendments WHERE order_id=?", (oid,),
        ) as cur:
            rows = await cur.fetchall()
        assert rows and all(r[0] is None for r in rows)

    @pytest.mark.asyncio
    async def test_position_amended_trade_event_carries_operator(
        self, om_plain, db, monkeypatch, captured_trade_events
    ):
        from core.state import app_state
        monkeypatch.setattr(app_state, "operator_id_by_account", {ACCOUNT_ID: "seat-Z"})
        d, _ = db
        await _seed_working_order(
            d, "A-3", order_type="take_profit", stop_price=64000.0,
            quantity=1.0, calc_id="calc-a", terminal_position_id="POS-1")
        await om_plain.detect_and_persist_amendment(
            ACCOUNT_ID, _amend_incoming("A-3", order_type="take_profit",
                                        stop_price=64500.0, quantity=1.0))
        evs = [e for e in captured_trade_events
               if e["event_type"] == "position_amended"]
        assert evs and all(e["payload"]["operator_id"] == "seat-Z" for e in evs)

    @pytest.mark.asyncio
    async def test_position_amended_eventbus_carries_operator(
        self, om_plain, db, monkeypatch
    ):
        from core.state import app_state
        monkeypatch.setattr(app_state, "operator_id_by_account", {ACCOUNT_ID: "seat-Z"})
        d, _ = db
        await _seed_working_order(
            d, "A-4", order_type="limit", price=50000.0, quantity=1.0,
            terminal_position_id="POS-1")
        _drain_bus()
        await om_plain.detect_and_persist_amendment(
            ACCOUNT_ID, _amend_incoming("A-4", price=50100.0, quantity=1.0,
                                        updated_at_ms=777))
        amended = [p for c, p in _drain_bus()
                   if c == "engine:account:1:position:amended"]
        assert amended and all(p["operator_id"] == "seat-Z" for p in amended)
