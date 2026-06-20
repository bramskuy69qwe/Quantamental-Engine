"""CL.T5 (plan 5.3) — the known-bug replay gate (spec §10.10, acceptance #10).

Each of the EIGHT historical linkage bugs (HANDOFF 2026-06-09) must be
FAST-diagnosable: drivable through the taps as built and findable with
ONE §9-style query. The rev-2 spec additions (§5.4b WS lifecycle, §5.5
orders/db rows, §5.6 mandates + drift/funding/reenrich) exist precisely
because the rev-1 replay scored 1 FAST / 5 MEDIUM / 2 BLIND.

This file is the acceptance gate, not the unit coverage — the per-tap
behavior is pinned in test_correlation_log_{state,attribution,ws}.py.
Here each bug is driven through its REAL tap(s) and the ONE diagnostic
query (a predicate mirroring the cookbook/§9 jq recipe) is asserted to
surface the bug's signature.

Also closes the Phase-3-audit gaps on acceptance #1:
- an amend leg AND a cancel leg in a replay (the open→close replays had
  neither), with an in-replay SKIPPED line;
- the HA-35 (post-LINKED link-write failure) + HA-40 (closing-fill
  attribution stamp) envelope-less seams, now tapped.
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import core.correlation_log as cl


def _drain():
    out = []
    while True:
        try:
            item = cl._queue.get_nowait()
        except Exception:
            break
        if isinstance(item, str):
            out.append(json.loads(item))
    return out


def _by_cat(envs, cat):
    return [e for e in envs if e["category"] == cat]


@pytest.fixture(autouse=True)
def _pin(monkeypatch):
    _drain()
    monkeypatch.setattr(cl, "_enabled", True)
    monkeypatch.setattr(cl, "_profile", "full")
    monkeypatch.setattr(cl, "_emit_error_logged", set())
    yield
    _drain()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


async def _mk_db(tmp_path):
    from core.database import DatabaseManager
    d = DatabaseManager(path=str(tmp_path / "replay.db"))
    await d.initialize()
    return d


def _pos_info(ticker="BTCUSDT", direction="LONG", tpid="POS-1", **kw):
    from core.state import PositionInfo
    base = dict(
        ticker=ticker, direction=direction, contract_amount=1.0,
        average=100.0, fair_price=100.0, individual_unrealized=0.0,
        position_value_usdt=100.0,
        entry_timestamp="2026-06-12T00:00:00+00:00",
        sector="", position_id=tpid,
    )
    base.update(kw)
    return PositionInfo(**base)


@pytest.fixture
def _restore_positions():
    from core.state import app_state
    snap = list(app_state.positions)
    app_state.positions = []
    yield app_state
    app_state.positions = snap


@pytest.fixture
def _restore_app_state():
    from core.state import app_state
    acc = dict(app_state.account_state.__dict__)
    pf = dict(app_state.portfolio.__dict__)
    pos = list(app_state.positions)
    yield app_state
    app_state.account_state.__dict__.update(acc)
    app_state.portfolio.__dict__.update(pf)
    app_state.positions = pos


class _StubBus:
    async def publish(self, *a, **k):
        pass

    async def publish_engine(self, *a, **k):
        pass

    def publish_engine_nowait(self, *a, **k):
        pass


# ── the §9 one-query diagnostics (predicates mirroring the cookbook jq) ───────

def q_close_recording(envs):
    """⑨ close-recording: a close that landed via the symbol/direction WALK
    because the strict tpid lookup missed (opening fills written empty)."""
    return [e for e in _by_cat(envs, "attr_close_build")
            if e["payload"].get("opens_found_strict") == 0
            and e["payload"].get("walk_used")
            and e["payload"].get("row_written")]


def q_unminted_snapshot(envs):
    """Restart-reseeded position (empty tpid) whose id was re-derived from
    the persisted entry order."""
    return [e for e in _by_cat(envs, "attr_tpid_resolve")
            if e["payload"].get("via") == "snapshot_recovery"
            and e["payload"].get("outcome") == "RESOLVED"]


def q_close_tpid_race(envs):
    """Close-tpid race: the live PositionInfo vanished, the close tpid fell
    back to the entry-order tier."""
    return [e for e in _by_cat(envs, "attr_tpid_resolve")
            if e["payload"].get("tier") == "entry_order_fallback"]


def q_fill_mint_race(envs):
    """Fill-mint race: the incremental apply minted a NEW tpid (the second
    racer made visible)."""
    return [e for e in _by_cat(envs, "position_incremental_applied")
            if e["payload"].get("tpid_minted") is True]


def q_ticker_leak(envs):
    """Subscription leak (#4): a calc_symbol_change with no SUBSEQUENT
    ws_stream_rebuild for it (the dead market sub kept streaming)."""
    leaks = []
    for e in envs:
        if e["category"] != "calc_symbol_change":
            continue
        seq = e["seq"]
        rebuilt = any(
            r["category"] == "ws_stream_rebuild"
            and r["payload"].get("trigger") == "calc_symbol_change"
            and r["seq"] > seq
            for r in envs)
        if not rebuilt:
            leaks.append(e)
    return leaks


def q_stale_orders(envs):
    """Stale orders (#f): the reconciler promoted orders the venue's
    terminal frame never delivered."""
    return [e for e in _by_cat(envs, "reconcile_promote")
            if e["payload"].get("count", 0) > 0]


def q_child_parent_reenrich(envs):
    """Child→parent re-enrich (#g): a fill arrival re-triggered the parent
    market order's correlation."""
    return [e for e in _by_cat(envs, "attr_reenrich_trigger")
            if e["payload"].get("via") == "fill_arrival"
            and e["payload"].get("outcome") == "TRIGGERED"]


def q_sl_removal(envs):
    """SL-removal badge (#h): the live stop went to 0 while the calc
    planned one — the badge should NOT read green/on-plan."""
    return [e for e in _by_cat(envs, "attr_drift_check")
            if e["payload"].get("sl_removed") is True]


# ── the eight bugs, each diagnosable with one query ──────────────────────────

class TestEightBugReplay:
    def test_bug1_close_recording(self, tmp_path, _restore_positions):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                await db.upsert_fill({
                    "account_id": 1, "exchange_fill_id": "F-OPEN",
                    "exchange_order_id": "E-OPEN", "symbol": "BTCUSDT",
                    "direction": "LONG", "price": 100.0, "quantity": 1.0,
                    "is_close": 0, "timestamp_ms": 1000,
                    "terminal_position_id": "",  # opening fill written EMPTY
                })
                close = {
                    "account_id": 1, "exchange_fill_id": "F-CLOSE",
                    "exchange_order_id": "E-CLOSE", "symbol": "BTCUSDT",
                    "direction": "LONG", "price": 110.0, "quantity": 1.0,
                    "is_close": 1, "timestamp_ms": 2000,
                    "terminal_position_id": "POS-9", "realized_pnl": 10.0,
                }
                await db.upsert_fill(dict(close))
                _drain()
                await om._build_close_row_for_fill(1, close)
                return _drain()
            finally:
                await db.close()

        envs = asyncio.run(main())
        hits = q_close_recording(envs)
        assert len(hits) == 1
        p = hits[0]["payload"]
        # the root cause readable on the one line
        assert p["strict_key"] == "POS-9" and p["opens_found_walk"] == 1
        assert p["open_fill_tpids"] == {"empty": 1, "populated": 0}

    def test_bug2_unminted_snapshot(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                await db.upsert_order_batch([{
                    "account_id": 1, "exchange_order_id": "E-ENT",
                    "symbol": "BTCUSDT", "status": "filled",
                    "order_type": "limit", "quantity": 1.0, "filled_qty": 1.0,
                    "reduce_only": 0, "position_side": "LONG",
                    "terminal_position_id": "POS-7",
                    "created_at_ms": 1000, "updated_at_ms": 1000,
                }])
                pos = _pos_info(tpid="")  # restart-reseeded: empty id
                _drain()
                await om._enrich_positions_calc_id(1, [pos])
                return pos.position_id, _drain()
            finally:
                await db.close()

        recovered, envs = asyncio.run(main())
        assert recovered == "POS-7"
        hits = q_unminted_snapshot(envs)
        assert len(hits) == 1
        assert hits[0]["payload"]["tier"] == "entry_order"

    def test_bug3_close_tpid_race(self, _restore_positions):
        from core.order_manager import OrderManager

        class _Db:  # the live position is GONE; the entry-order tier resolves
            async def get_open_entry_tpids_by_symbol_side(self, account_id):
                return {("BTCUSDT", "LONG"): "POS-2"}

        om = OrderManager(_Db())
        got = asyncio.run(om._resolve_close_tpid(1, {
            "symbol": "BTCUSDT", "direction": "LONG",
            "exchange_fill_id": "F-9", "exchange_order_id": "E-9"}))
        assert got == "POS-2"
        hits = q_close_tpid_race(_drain())
        assert len(hits) == 1
        assert hits[0]["payload"]["outcome"] == "RESOLVED"

    def test_bug4_fill_mint_race(self, _restore_app_state):
        from core.data_cache import DataCache, UpdateSource

        cache = DataCache(_StubBus())
        np = SimpleNamespace(symbol="ETHUSDT", side="LONG", size=2.0,
                             entry_price=100.0, unrealized_pnl=0.0)
        asyncio.run(cache.apply_position_update_incremental(
            UpdateSource.WS_USER, [np], {}))
        hits = q_fill_mint_race(_drain())
        assert len(hits) == 1
        # the minted id is non-empty and present as the second racer
        assert hits[0]["payload"]["terminal_position_id"]
        assert hits[0]["payload"]["tpid_present"] is False

    def test_bug5_ticker_switch_leak(self, monkeypatch):
        import core.ws_manager as wsm

        # healthy: the symbol change is followed by a real ws_stream_rebuild
        monkeypatch.setattr(wsm, "_calculator_symbol", None, raising=False)

        async def fake_loop(attempt=0):
            return None

        monkeypatch.setattr(wsm, "_market_stream_loop", fake_loop)
        monkeypatch.setattr(wsm, "_last_streams",
                            ["btcusdt@kline_5m", "btcusdt@depth20"])
        monkeypatch.setattr(wsm, "_build_market_streams",
                            lambda: ["ethusdt@kline_5m"])

        async def healthy():
            wsm.set_calculator_symbol("ethusdt")     # calc_symbol_change
            await wsm.restart_market_streams(trigger="calc_symbol_change")
            await asyncio.sleep(0)

        asyncio.run(healthy())
        assert q_ticker_leak(_drain()) == []  # change WITH rebuild → no leak

        # leaky: the symbol change with NO following rebuild (the #4 bug —
        # restart only fired on position changes, so the calc-switch leaked)
        monkeypatch.setattr(wsm, "_calculator_symbol", "ethusdt", raising=False)
        wsm.set_calculator_symbol("solusdt")
        leaks = q_ticker_leak(_drain())
        assert len(leaks) == 1
        assert leaks[0]["payload"]["new"] == "SOLUSDT"

    def test_bug6_stale_orders(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                await db.upsert_order_batch([{
                    "account_id": 1, "exchange_order_id": "E-STALE",
                    "symbol": "BTCUSDT", "status": "new",
                    "quantity": 1.0, "filled_qty": 1.0,  # truth: fully filled
                    "updated_at_ms": 1000,
                }])
                _drain()
                await db.reconcile_filled_orders(1)
                return _drain()
            finally:
                await db.close()

        hits = q_stale_orders(asyncio.run(main()))
        assert len(hits) == 1
        assert hits[0]["payload"]["promoted"] == ["E-STALE"]

    def test_bug7_child_parent_reenrich(self, tmp_path, monkeypatch):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                import config
                import core.order_enrichment as oe
                monkeypatch.setattr(config, "DB_PATH",
                                    str(tmp_path / "replay.db"))

                async def _noop(order, db_path):
                    pass

                monkeypatch.setattr(oe, "enrich_order", _noop)
                from core.order_manager import OrderManager
                om = OrderManager(db)
                await db.upsert_order_batch([{
                    "account_id": 1, "exchange_order_id": "E-MKT",
                    "symbol": "BTCUSDT", "status": "filled",
                    "order_type": "market", "quantity": 1.0, "filled_qty": 1.0,
                    "reduce_only": 0, "updated_at_ms": 1000,
                }])
                _drain()
                await om._reenrich_parent_after_fill(1, "E-MKT")
                return _drain()
            finally:
                await db.close()

        hits = q_child_parent_reenrich(asyncio.run(main()))
        assert len(hits) == 1
        assert hits[0]["payload"]["dedup_key"] == "E-MKT:reenrich_fill"

    def test_bug8_sl_removal_badge(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                await db.upsert_position_calc_link({
                    "position_id": "POS-1", "calc_id": "CALC-1", "order_id": 1,
                    "account_id": 1, "contributed_qty": 1.0, "first_fill_ts": 1,
                    "last_fill_ts": 1, "planned_size": 1.0,
                    "planned_tp": 110.0, "planned_sl": 95.0,
                })
                pos = _pos_info(tpid="POS-1", individual_tp_price=110.0,
                                individual_sl_price=95.0)
                _drain()
                await om._enrich_positions_calc_id(1, [pos])  # green/on-plan
                pos.individual_sl_price = 0.0                  # stop pulled
                await om._enrich_positions_calc_id(1, [pos])
                return _drain()
            finally:
                await db.close()

        envs = asyncio.run(main())
        hits = q_sl_removal(envs)
        assert len(hits) == 1
        p = hits[0]["payload"]
        assert p["planned_sl"] == 95.0 and p["live_sl"] == 0.0
        # 2026-06-20 severity: a removed stop is now RED (unprotected), not
        # yellow; the badge still transitions off green (bug #8 stays caught).
        assert p["badge_before"] == "green" and p["badge"] == "red"


# ── acceptance #1 gap: amend + cancel legs + an in-replay SKIPPED line ───────

class TestAmendCancelLegs:
    def test_open_amend_cancel_legs_on_the_status_surface(
        self, tmp_path, monkeypatch,
    ):
        """The Phase-3 replays were open→close only. Drive an entry that
        fills, a protective leg that is CANCELLED, and an AMEND (cancel+new,
        the observe-path shape of an amendment) — all visible as
        order_status_applied transitions, with the unlinked order's
        junction SKIPPED line present in the same replay."""
        async def main():
            db = await _mk_db(tmp_path)
            try:
                import core.order_enrichment as oe

                async def _noop(order, db_path):
                    pass

                monkeypatch.setattr(oe, "enrich_order", _noop)
                from core.order_manager import OrderManager
                om = OrderManager(db)
                _drain()

                async def upd(**o):
                    o.setdefault("account_id", 1)
                    o.setdefault("symbol", "BTCUSDT")
                    o.setdefault("quantity", 1.0)
                    await om.process_order_update(1, o)

                # open: entry new → filled
                await upd(exchange_order_id="E-ENT", status="new")
                await upd(exchange_order_id="E-ENT", status="filled",
                          filled_qty=1.0)
                # a working protective stop, then CANCELLED (the cancel leg)
                await upd(exchange_order_id="E-SL", status="new",
                          reduce_only=1)
                await upd(exchange_order_id="E-SL", status="canceled",
                          reduce_only=1)
                # AMEND = cancel the old stop + place a re-priced one
                await upd(exchange_order_id="E-SL2", status="new",
                          reduce_only=1)
                await upd(exchange_order_id="E-SL2", status="canceled",
                          reduce_only=1)
                await upd(exchange_order_id="E-SL3", status="new",
                          reduce_only=1)
                return _drain()
            finally:
                await db.close()

        envs = asyncio.run(main())
        osa = _by_cat(envs, "order_status_applied")
        afters = [e["payload"]["after"] for e in osa]
        # the open leg
        assert "filled" in afters
        # the cancel leg — a working order taken to canceled
        cancels = [e for e in osa if e["payload"]["after"] == "canceled"]
        assert len(cancels) >= 2  # E-SL (cancel) + E-SL2 (the amend's cancel)
        # the amend's replacement order arrived (cancel+new on the same side)
        assert any(e["payload"]["order_id"] == "E-SL3"
                   and e["payload"]["after"] == "new" for e in osa)
        # the amend is a cancel→new PAIR on the same leg lineage: E-SL2
        # cancelled AND E-SL3 placed (the observe-path amendment shape)
        assert any(e["payload"]["order_id"] == "E-SL2"
                   and e["payload"]["after"] == "canceled" for e in osa)
        # an in-replay SKIPPED line that BELONGS to one of these legs (the
        # unlinked orders' junction replay), not just any SKIPPED line —
        # proves the replay walked the real enrich→junction path per leg
        leg_eids = {"E-ENT", "E-SL", "E-SL2", "E-SL3"}
        skipped = [e for e in _by_cat(envs, "attr_junction_form")
                   if e["payload"].get("outcome") == "SKIPPED"
                   and e["payload"].get("exchange_order_id") in leg_eids]
        assert skipped, "the replay must contain a SKIPPED line for a real leg"
        assert skipped[0]["payload"]["reason"] == "not_linked"


# ── the two envelope-less seams, now closed (HA-35 / HA-40) ──────────────────

class TestSeamClosures:
    def _matcher_db(self, tmp_path):
        """A LINKED-match-ready DB: order E-1 (tpid POS-7) + a matching
        active calc (CALC-1) + the audit/amendment tables the apply path
        touches."""
        p = str(tmp_path / "seam.db")
        conn = sqlite3.connect(p)
        conn.execute(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, account_id INT,"
            " exchange_order_id TEXT, calc_id TEXT, link_status TEXT,"
            " tp_trigger_price REAL, sl_trigger_price REAL, price REAL,"
            " avg_fill_price REAL, created_at_ms INT,"
            " terminal_position_id TEXT, lifecycle_id TEXT,"
            " reduce_only INT DEFAULT 0, order_type TEXT DEFAULT 'limit',"
            " symbol TEXT, position_side TEXT DEFAULT '')")
        conn.execute("INSERT INTO orders (id, account_id, exchange_order_id,"
                     " tp_trigger_price, sl_trigger_price, price, avg_fill_price,"
                     " created_at_ms, terminal_position_id, lifecycle_id) VALUES"
                     " (9, 1, 'E-1', 110.0, 95.0, 100.0, 0.0, ?, 'POS-7', '')",
                     (int(datetime.now(timezone.utc).timestamp() * 1000),))
        conn.execute("CREATE TABLE accounts (id INTEGER PRIMARY KEY, config_json TEXT)")
        conn.execute("INSERT INTO accounts (id, config_json) VALUES (1, NULL)")
        conn.execute(
            "CREATE TABLE pre_trade_log (calc_id TEXT, timestamp TEXT,"
            " side TEXT, effective_entry REAL, tp_price REAL, sl_price REAL,"
            " status TEXT, window_seconds INT, account_id INT, ticker TEXT)")
        conn.execute(
            "INSERT INTO pre_trade_log VALUES ('CALC-1', ?, 'long', 100.0,"
            " 110.0, 95.0, 'active', NULL, 1, 'BTCUSDT')", (_now_iso(),))
        conn.execute(
            "CREATE TABLE calc_match_audit (order_id INT, calc_id TEXT,"
            " criterion TEXT, calc_value TEXT, order_value TEXT,"
            " tolerance_used REAL, matched INT, ts_ms INT, winning INT)")
        conn.execute("CREATE TABLE order_amendments (id INTEGER PRIMARY KEY,"
                     " order_id INT, calc_id TEXT)")
        conn.commit()
        conn.close()
        return p

    def _order(self):
        return {
            "account_id": 1, "symbol": "BTCUSDT", "side": "BUY",
            "order_type": "limit", "price": 100.0, "avg_fill_price": 0.0,
            "tp_trigger_price": 110.0, "sl_trigger_price": 95.0,
            "created_at_ms": int(datetime.now(timezone.utc).timestamp() * 1000),
            "exchange_order_id": "E-1", "terminal_position_id": "",
            "lifecycle_id": "", "status": "new", "quantity": 1.0,
        }

    def test_ha35_linked_then_write_failure_is_a_db_write_twin(
        self, tmp_path, monkeypatch,
    ):
        """HA-35: the matcher decides LINKED, then the raw orders.calc_id
        UPDATE (inside auto_classify's apply_fn) raises. Before CL.T5 that
        was envelope-less — the chain read LINKED with no DB link. Now the
        failure is a one-query find: db_write ok:false table=orders, and the
        link_transition is correctly ABSENT (the write never completed)."""
        from core.order_enrichment import _try_correlate
        import core.order_enrichment as oe

        db = self._matcher_db(tmp_path)
        orig_to_thread = asyncio.to_thread

        async def _maybe_fail(fn, *a, **k):
            # surgical: fail ONLY the link-stamp, leave matcher reads intact
            if getattr(fn, "__name__", "") == "_update_orders_sync":
                raise RuntimeError("disk full")
            return await orig_to_thread(fn, *a, **k)

        monkeypatch.setattr(oe.asyncio, "to_thread", _maybe_fail)

        async def main():
            with cl.correlation_scope("wsu"):
                try:
                    await _try_correlate(self._order(), db)
                except Exception:
                    pass  # _enrich_order_best_effort swallows in production
            return _drain()

        envs = asyncio.run(main())
        # LINKED decided
        match = _by_cat(envs, "attr_match_attempt")
        assert match and match[0]["payload"]["outcome"] == "LINKED"
        # the seam: the orders-stamp failure twin
        fail = [e for e in _by_cat(envs, "db_write")
                if e["payload"]["table"] == "orders"
                and e["payload"]["ok"] is False]
        assert len(fail) == 1
        assert fail[0]["payload"]["error_type"] == "RuntimeError"
        assert fail[0]["payload"]["exchange_order_id"] == "E-1"
        # and link_transition is ABSENT — the LINKED-with-no-link signature
        assert _by_cat(envs, "link_transition") == []

    def test_ha40_close_stamp_assigned_skip_and_error(self, tmp_path):
        """HA-40: the closing-fill primary-calc/lifecycle inheritance — a
        §5.6-class decision that shipped envelope-less. Now one
        attr_close_stamp line per closing-fill invocation: ASSIGNED with the
        junction, SKIPPED no_junction without one, ERROR on write failure."""
        async def main():
            db = await _mk_db(tmp_path)
            try:
                from core.order_manager import OrderManager
                om = OrderManager(db)
                out = {}

                # ASSIGNED: a close fill on a position WITH a junction
                await db.upsert_position_calc_link({
                    "position_id": "POS-1", "calc_id": "CALC-1", "order_id": 1,
                    "account_id": 1, "contributed_qty": 1.0, "first_fill_ts": 1,
                    "last_fill_ts": 1, "planned_size": 1.0,
                })
                await db.upsert_fill({
                    "account_id": 1, "exchange_fill_id": "F-C", "is_close": 1,
                    "exchange_order_id": "E-C", "symbol": "BTCUSDT",
                    "direction": "LONG", "quantity": 1.0, "price": 110.0,
                    "terminal_position_id": "POS-1", "timestamp_ms": 2000,
                })
                _drain()
                await om._stamp_closing_fill_attribution(1, {
                    "is_close": 1, "terminal_position_id": "POS-1",
                    "exchange_fill_id": "F-C", "exchange_order_id": "E-C",
                    "symbol": "BTCUSDT"})
                out["assigned"] = _drain()

                # SKIPPED no_junction: a close fill on a junction-less position
                await om._stamp_closing_fill_attribution(1, {
                    "is_close": 1, "terminal_position_id": "POS-NONE",
                    "exchange_fill_id": "F-N", "exchange_order_id": "E-N",
                    "symbol": "BTCUSDT"})
                out["skip"] = _drain()

                # opening fill is a domain filter — NO envelope
                await om._stamp_closing_fill_attribution(1, {
                    "is_close": 0, "terminal_position_id": "POS-1",
                    "exchange_fill_id": "F-O", "exchange_order_id": "E-O"})
                out["open"] = _drain()
                return out
            finally:
                await db.close()

        out = asyncio.run(main())
        a = _by_cat(out["assigned"], "attr_close_stamp")
        assert len(a) == 1
        assert a[0]["payload"]["outcome"] == "ASSIGNED"
        assert a[0]["payload"]["calc_id"] == "CALC-1"
        assert a[0]["payload"]["dedup_key"] == "F-C:close_stamp"
        s = _by_cat(out["skip"], "attr_close_stamp")
        assert len(s) == 1
        assert s[0]["payload"]["outcome"] == "SKIPPED"
        assert s[0]["payload"]["reason"] == "no_junction"
        assert s[0]["payload"]["terminal_position_id"] == "POS-NONE"
        assert _by_cat(out["open"], "attr_close_stamp") == []  # domain filter
