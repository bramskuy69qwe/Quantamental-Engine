"""CL.T3a — internal state/persistence taps (spec §5.5).

Covers: the data_cache apply chokepoints (position_snapshot_applied with
closes_detected as a (symbol, side, tpid) LIST; position_incremental_applied
with tpid_minted/tpid_present flags — the mint as a visible racer;
account_update_applied; portfolio_recalculated ON CHANGE ONLY) + the lock
waited_ms/held_ms annotations on the async apply paths; the calc_state /
link_state transition chokepoints (both link entry points — transition and
auto_classify); order_status_applied across all three sources
(ws / reconcile / stale-mark); reconcile_promote (silent when nothing
promotes); and db_write at the money-path writers — rowcount truth (the
ON CONFLICT guard's rejections are visible), key ids VERBATIM including "",
dedup visibility (funding INSERT OR IGNORE rowcount=0), and the
pollution-reject / failure paths as lines rather than absences.
"""

import asyncio
import json
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


@pytest.fixture
def _restore_app_state():
    """Snapshot/restore the global app_state fields the data_cache applies
    mutate, so these tests don't leak equity/portfolio values into others."""
    from core.state import app_state
    acc_snap = dict(app_state.account_state.__dict__)
    pf_snap = dict(app_state.portfolio.__dict__)
    yield app_state
    app_state.account_state.__dict__.update(acc_snap)
    app_state.portfolio.__dict__.update(pf_snap)


class _StubBus:
    async def publish(self, *a, **k):
        pass

    async def publish_engine(self, *a, **k):
        pass

    def publish_engine_nowait(self, *a, **k):
        pass


def _pos(ticker="XAUUSDT", direction="LONG", qty=1.0, tpid="POS-9"):
    from core.state import PositionInfo
    return PositionInfo(
        ticker=ticker, direction=direction, contract_amount=qty,
        average=100.0, fair_price=100.0, individual_unrealized=0.0,
        position_value_usdt=100.0,
        entry_timestamp="2026-06-12T00:00:00+00:00",
        sector="", position_id=tpid,
    )


async def _mk_db(tmp_path):
    from core.database import DatabaseManager
    d = DatabaseManager(path=str(tmp_path / "t3a.db"))
    await d.initialize()
    return d


# ── data_cache: position snapshot (spec §5.5) ───────────────────────────────

class TestPositionSnapshotApplied:
    def test_applied_snapshot_emits_closes_as_symbol_side_tpid_list(
        self, _restore_app_state,
    ):
        from core.data_cache import DataCache, UpdateSource

        cache = DataCache(_StubBus())
        cache._positions = [_pos(tpid="POS-9")]

        async def main():
            return await cache.apply_position_snapshot(
                UpdateSource.PLATFORM, [], force=True,
            )

        result = asyncio.run(main())
        assert result is not None and result.closed_syms == {"XAUUSDT"}
        envs = _by_cat(_drain(), "position_snapshot_applied")
        assert len(envs) == 1
        e = envs[0]
        assert e["component"] == "data_cache"
        p = e["payload"]
        # closes_detected is the (symbol, side, tpid) LIST, not a count —
        # the §4.1 race walkthrough depends on the tpid being readable here.
        assert p["closes_detected"] == [["XAUUSDT", "LONG", "POS-9"]]
        assert p["n_positions"] == 0
        assert p["trigger"] == "platform"
        assert p["force"] is True
        assert p["waited_ms"] >= 0 and p["held_ms"] >= 0

    def test_close_of_tpid_less_position_records_empty_string_verbatim(
        self, _restore_app_state,
    ):
        from core.data_cache import DataCache, UpdateSource

        cache = DataCache(_StubBus())
        cache._positions = [_pos(tpid="")]

        asyncio.run(cache.apply_position_snapshot(
            UpdateSource.PLATFORM, [], force=True,
        ))
        p = _by_cat(_drain(), "position_snapshot_applied")[0]["payload"]
        assert p["closes_detected"] == [["XAUUSDT", "LONG", ""]]

    def test_mass_close_caps_list_but_keeps_honest_counts(
        self, _restore_app_state,
    ):
        # HA-23 (CL.T5): a mass-close snapshot must NOT let closes_detected
        # blow the §7.4 4 KB cap and truncate the WHOLE payload to the
        # `_truncated` summary (losing n_positions, waited_ms, AND every
        # tpid). The list caps at 20; n_closes/n_closes_omitted stay honest.
        from core.data_cache import DataCache, UpdateSource

        cache = DataCache(_StubBus())
        cache._positions = [
            _pos(ticker=f"SYM{i:03d}USDT", tpid=f"POS-{i}") for i in range(75)
        ]

        asyncio.run(cache.apply_position_snapshot(
            UpdateSource.PLATFORM, [], force=True,
        ))
        p = _by_cat(_drain(), "position_snapshot_applied")[0]["payload"]
        # the envelope survived intact (not the _truncated summary)
        assert "_truncated" not in p
        assert len(p["closes_detected"]) == 20
        assert p["n_closes"] == 75
        assert p["n_closes_omitted"] == 55
        # the kept entries are still the readable (symbol, side, tpid) shape
        assert all(len(c) == 3 for c in p["closes_detected"])

    def test_rejected_snapshot_emits_nothing(self, _restore_app_state):
        from core.data_cache import DataCache, UpdateSource

        cache = DataCache(_StubBus())
        cache._should_accept_position_update = lambda *a: False

        result = asyncio.run(cache.apply_position_snapshot(
            UpdateSource.WS_USER, [_pos()], force=False,
        ))
        assert result is None
        assert _by_cat(_drain(), "position_snapshot_applied") == []


# ── data_cache: incremental WS apply (spec §5.5) ────────────────────────────

class TestPositionIncrementalApplied:
    def _np(self, symbol="ETHUSDT", side="LONG", size=2.0, **kw):
        return SimpleNamespace(
            symbol=symbol, side=side, size=size,
            entry_price=100.0, unrealized_pnl=0.0, **kw,
        )

    def test_new_position_mint_is_a_visible_racer(self, _restore_app_state):
        from core.data_cache import DataCache, UpdateSource

        cache = DataCache(_StubBus())
        asyncio.run(cache.apply_position_update_incremental(
            UpdateSource.WS_USER, [self._np()], {},
        ))
        envs = _by_cat(_drain(), "position_incremental_applied")
        assert len(envs) == 1
        e = envs[0]
        assert e["symbol"] == "ETHUSDT"
        p = e["payload"]
        assert p["tpid_minted"] is True and p["tpid_present"] is False
        assert p["terminal_position_id"]  # the minted id, non-empty
        assert p["qty_before"] == 0 and p["qty_after"] == 2.0
        assert p["closed"] is False
        assert p["waited_ms"] >= 0 and p["held_ms"] >= 0

    def test_upstream_id_is_never_overwritten_and_not_minted(
        self, _restore_app_state,
    ):
        from core.data_cache import DataCache, UpdateSource

        cache = DataCache(_StubBus())
        asyncio.run(cache.apply_position_update_incremental(
            UpdateSource.WS_USER, [self._np(position_id="QT-77")], {},
        ))
        p = _by_cat(_drain(), "position_incremental_applied")[0]["payload"]
        assert p["terminal_position_id"] == "QT-77"
        assert p["tpid_minted"] is False and p["tpid_present"] is True

    def test_update_then_close_carry_qty_before_after_and_tpid(
        self, _restore_app_state,
    ):
        from core.data_cache import DataCache, UpdateSource

        cache = DataCache(_StubBus())

        async def main():
            await cache.apply_position_update_incremental(
                UpdateSource.WS_USER, [self._np(size=2.0)], {},
            )
            await cache.apply_position_update_incremental(
                UpdateSource.WS_USER, [self._np(size=3.0)], {},
            )
            await cache.apply_position_update_incremental(
                UpdateSource.WS_USER, [self._np(size=0)], {},
            )

        asyncio.run(main())
        new, upd, close = _by_cat(_drain(), "position_incremental_applied")
        tpid = new["payload"]["terminal_position_id"]
        assert upd["payload"]["qty_before"] == 2.0
        assert upd["payload"]["qty_after"] == 3.0
        assert upd["payload"]["terminal_position_id"] == tpid
        assert upd["payload"]["tpid_minted"] is False
        assert upd["payload"]["tpid_present"] is True
        assert close["payload"]["closed"] is True
        assert close["payload"]["qty_before"] == 3.0
        assert close["payload"]["qty_after"] == 0
        assert close["payload"]["terminal_position_id"] == tpid

    def test_balances_only_frame_emits_no_position_envelope(
        self, _restore_app_state,
    ):
        from core.data_cache import DataCache, UpdateSource

        cache = DataCache(_StubBus())
        asyncio.run(cache.apply_position_update_incremental(
            UpdateSource.WS_USER, [], {"wallet_balance": 5.0},
        ))
        assert _by_cat(_drain(), "position_incremental_applied") == []


# ── data_cache: account applies + portfolio recalc (spec §5.5) ──────────────

class TestAccountAndPortfolioTaps:
    def test_rest_account_apply_carries_equity_before_after(
        self, _restore_app_state,
    ):
        from core.data_cache import DataCache

        app_state = _restore_app_state
        app_state.account_state.total_equity = 500.0
        cache = DataCache(_StubBus())
        na = SimpleNamespace(
            total_equity=1000.0, available_margin=900.0,
            unrealized_pnl=5.0, initial_margin=50.0, maint_margin=0.1,
        )
        ok = asyncio.run(cache.apply_account_update_rest(na))
        assert ok is True
        envs = _by_cat(_drain(), "account_update_applied")
        assert len(envs) == 1
        p = envs[0]["payload"]
        assert p["source"] == "rest"
        assert p["equity_before"] == 500.0
        assert p["equity_after"] == 1000.0
        assert p["waited_ms"] >= 0 and p["held_ms"] >= 0

    def test_rejected_rest_account_apply_emits_nothing(
        self, _restore_app_state,
    ):
        from core.data_cache import DataCache

        cache = DataCache(_StubBus())
        cache._should_accept_account_update = lambda *a: False
        na = SimpleNamespace(
            total_equity=1.0, available_margin=1.0,
            unrealized_pnl=0.0, initial_margin=0.0, maint_margin=0.0,
        )
        ok = asyncio.run(cache.apply_account_update_rest(na))
        assert ok is False
        assert _by_cat(_drain(), "account_update_applied") == []

    def test_platform_account_apply_tagged_platform(self, _restore_app_state):
        from core.data_cache import DataCache

        cache = DataCache(_StubBus())
        asyncio.run(cache.apply_account_update_platform(
            balance=10.0, total_equity=11.0, unrealized_pnl=1.0,
            available_margin=9.0, margin_ratio=0.1,
        ))
        envs = _by_cat(_drain(), "account_update_applied")
        assert len(envs) == 1
        assert envs[0]["payload"]["source"] == "platform"

    def test_portfolio_recalculated_emits_on_state_change_only(
        self, _restore_app_state,
    ):
        from core.data_cache import DataCache

        app_state = _restore_app_state
        app_state.portfolio.dd_state = "ok"
        app_state.portfolio.weekly_pnl_state = "ok"
        cache = DataCache(_StubBus())

        def fake(app_state_arg):
            app_state_arg.portfolio.dd_state = "warning"

        cache._do_recalculate_portfolio = fake
        cache._recalculate_portfolio()   # ok -> warning: emits
        cache._recalculate_portfolio()   # warning -> warning: silent
        envs = _by_cat(_drain(), "portfolio_recalculated")
        assert len(envs) == 1
        p = envs[0]["payload"]
        assert p["dd_state_before"] == "ok" and p["dd_state"] == "warning"
        assert p["weekly_pnl_state_before"] == "ok"
        assert p["weekly_pnl_state"] == "ok"


# ── calc_state / link_state transition chokepoints (spec §5.5) ──────────────

class TestTransitionTaps:
    def test_calc_transition_emits_from_to_reason(self):
        from core import calc_state

        async def apply():
            pass

        asyncio.run(calc_state.transition(
            "CALC-1", "active", "matched",
            apply_fn=apply, account_id=7, reason="full-match",
        ))
        envs = _by_cat(_drain(), "calc_transition")
        assert len(envs) == 1
        e = envs[0]
        assert e["component"] == "calc_state"
        assert e["account_id"] == 7
        assert e["payload"] == {
            "calc_id": "CALC-1", "from": "active", "to": "matched",
            "reason": "full-match",
        }

    def test_illegal_calc_transition_emits_nothing(self):
        from core import calc_state

        async def apply():
            pass

        with pytest.raises(calc_state.IllegalStateTransition):
            asyncio.run(calc_state.transition(
                "CALC-1", "matched", "active",
                apply_fn=apply, account_id=7,
            ))
        assert _by_cat(_drain(), "calc_transition") == []

    def test_failed_apply_fn_emits_nothing(self):
        from core import calc_state

        async def apply():
            raise calc_state.CalcTransitionRaceLost(
                "CALC-1", "active", "matched",
            )

        with pytest.raises(calc_state.CalcTransitionRaceLost):
            asyncio.run(calc_state.transition(
                "CALC-1", "active", "matched",
                apply_fn=apply, account_id=7,
            ))
        assert _by_cat(_drain(), "calc_transition") == []

    def test_link_transition_operator_path(self):
        from core import link_state

        async def apply():
            pass

        asyncio.run(link_state.transition(
            42,
            link_state.LinkStatus.NEEDS_MANUAL_REVIEW.value,
            link_state.LinkStatus.LINKED.value,
            apply_fn=apply, reason="operator-link",
        ))
        envs = _by_cat(_drain(), "link_transition")
        assert len(envs) == 1
        p = envs[0]["payload"]
        assert p["order_id"] == 42
        assert p["from"] == link_state.LinkStatus.NEEDS_MANUAL_REVIEW.value
        assert p["to"] == link_state.LinkStatus.LINKED.value
        assert p["via"] == "transition"

    def test_link_auto_classify_engine_path_from_is_none(self):
        from core import link_state

        async def apply():
            pass

        asyncio.run(link_state.auto_classify(
            43, link_state.LinkStatus.LINKED.value,
            apply_fn=apply, reason="strict-match",
        ))
        envs = _by_cat(_drain(), "link_transition")
        assert len(envs) == 1
        p = envs[0]["payload"]
        assert p["order_id"] == 43
        assert p["from"] is None
        assert p["to"] == link_state.LinkStatus.LINKED.value
        assert p["via"] == "auto_classify"


# ── order_status_applied: the WS source (spec §5.5) ─────────────────────────

class TestOrderStatusWs:
    def _om(self, active_map):
        from core.order_manager import OrderManager

        class _Db:
            async def get_active_orders_map(self, account_id):
                return active_map

            async def upsert_order_batch(self, rows):
                pass

        om = OrderManager(_Db())

        async def _anoop(*a, **k):
            pass

        def _noop(*a, **k):
            pass

        om._enrich_order_best_effort = _anoop
        om._re_enrich_parent_on_child_arrival = _anoop
        om._propagate_bracket_calc_id = _anoop
        om._detect_duplicate_orders = _anoop
        om._release_calc_on_operator_cancel = _anoop
        om.refresh_cache = _anoop
        om._emit_order_events = _noop
        om._publish_order_update = _noop
        return om

    def test_ws_update_emits_before_after_and_dedup_key(self):
        om = self._om({"E-1": {"status": "new"}})
        order = {
            "exchange_order_id": "E-1", "status": "partially_filled",
            "symbol": "BTCUSDT", "quantity": 0.5,
        }
        accepted = asyncio.run(om.process_order_update(1, order))
        assert accepted is True
        envs = _by_cat(_drain(), "order_status_applied")
        assert len(envs) == 1
        e = envs[0]
        assert e["component"] == "order_manager"
        assert e["symbol"] == "BTCUSDT"
        p = e["payload"]
        assert p["before"] == "new" and p["after"] == "partially_filled"
        assert p["source"] == "ws"
        assert p["dedup_key"] == "E-1:partially_filled:0.5"

    def test_sr1_rejected_transition_emits_nothing(self):
        om = self._om({"E-1": {"status": "partially_filled"}})
        order = {"exchange_order_id": "E-1", "status": "new",
                 "symbol": "BTCUSDT", "quantity": 0.5}
        accepted = asyncio.run(om.process_order_update(1, order))
        assert accepted is False
        assert _by_cat(_drain(), "order_status_applied") == []

    def test_unknown_order_before_is_empty_string_verbatim(self):
        om = self._om({})
        order = {"exchange_order_id": "E-9", "status": "new",
                 "symbol": "BTCUSDT", "quantity": 1.0}
        asyncio.run(om.process_order_update(1, order))
        p = _by_cat(_drain(), "order_status_applied")[0]["payload"]
        assert p["before"] == "" and p["after"] == "new"


# ── reconcile / stale-mark sources + db_write at the writers (spec §5.5) ────

class TestReconcileAndStaleMark:
    def test_reconcile_promote_chain(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                await db.upsert_order_batch([{
                    "account_id": 1, "exchange_order_id": "E-1",
                    "symbol": "BTCUSDT", "status": "new",
                    "quantity": 1.0, "filled_qty": 1.0,
                    "updated_at_ms": 1000,
                }])
                _drain()
                n1 = await db.reconcile_filled_orders(1)
                first = _drain()
                n2 = await db.reconcile_filled_orders(1)
                second = _drain()
                return n1, first, n2, second
            finally:
                await db.close()

        n1, first, n2, second = asyncio.run(main())
        assert n1 == 1
        osa = _by_cat(first, "order_status_applied")
        assert len(osa) == 1
        assert osa[0]["payload"] == {
            "order_id": "E-1", "before": "new", "after": "filled",
            "source": "reconcile",
        }
        promote = _by_cat(first, "reconcile_promote")
        assert len(promote) == 1
        assert promote[0]["payload"]["promoted"] == ["E-1"]
        assert promote[0]["payload"]["count"] == 1
        dbw = [e for e in _by_cat(first, "db_write")
               if e["payload"].get("writer") == "reconcile_filled_orders"]
        assert len(dbw) == 1 and dbw[0]["payload"]["rowcount"] == 1
        # zero-promotion pass stays SILENT (no every-60s noise)
        assert n2 == 0
        assert _by_cat(second, "order_status_applied") == []
        assert _by_cat(second, "reconcile_promote") == []

    def test_stale_mark_time_based(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                await db.upsert_order_batch([{
                    "account_id": 1, "exchange_order_id": "E-2",
                    "symbol": "ETHUSDT", "status": "new",
                    "quantity": 1.0, "filled_qty": 0.0,
                    "updated_at_ms": 1000,
                }])
                # upsert stamps last_seen_ms=now; age it artificially
                await db._conn.execute(
                    "UPDATE orders SET last_seen_ms=1 "
                    "WHERE exchange_order_id='E-2'",
                )
                await db._conn.commit()
                _drain()
                n = await db.mark_stale_orders(1, stale_threshold_ms=1000)
                return n, _drain()
            finally:
                await db.close()

        n, envs = asyncio.run(main())
        assert n == 1
        osa = _by_cat(envs, "order_status_applied")
        assert len(osa) == 1
        p = osa[0]["payload"]
        assert p["source"] == "stale-mark" and p["via"] == "time"
        assert p["before"] == "new" and p["after"] == "canceled"

    def test_stale_mark_snapshot_based(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                await db.upsert_order_batch([{
                    "account_id": 1, "exchange_order_id": "E-3",
                    "symbol": "ETHUSDT", "status": "new",
                    "quantity": 1.0, "filled_qty": 0.0,
                    "updated_at_ms": 1000,
                }])
                _drain()
                n = await db.mark_stale_orders_canceled(1, ["OTHER-ID"])
                return n, _drain()
            finally:
                await db.close()

        n, envs = asyncio.run(main())
        assert n == 1
        osa = _by_cat(envs, "order_status_applied")
        assert len(osa) == 1
        assert osa[0]["payload"]["via"] == "snapshot"
        assert osa[0]["payload"]["source"] == "stale-mark"


class TestDbWriteTaps:
    def test_order_batch_rowcount_exposes_guard_rejection(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                row = {
                    "account_id": 1, "exchange_order_id": "E-4",
                    "symbol": "BTCUSDT", "status": "new",
                    "quantity": 1.0, "filled_qty": 0.0,
                    "updated_at_ms": 2000,
                }
                await db.upsert_order_batch([row])
                first = _drain()
                stale = dict(row, updated_at_ms=1000)  # older -> guard rejects
                await db.upsert_order_batch([stale])
                second = _drain()
                return first, second
            finally:
                await db.close()

        first, second = asyncio.run(main())
        w1 = _by_cat(first, "db_write")[0]["payload"]
        assert w1["table"] == "orders" and w1["op"] == "UPSERT"
        assert w1["n_rows"] == 1 and w1["rowcount"] == 1
        assert w1["exchange_order_ids"] == ["E-4"]
        w2 = _by_cat(second, "db_write")[0]["payload"]
        assert w2["rowcount"] == 0      # the guard rejection is VISIBLE
        assert w2["n_rows"] == 1 and w2["ok"] is True

    def test_fill_and_close_taps_carry_ids_verbatim_incl_empty(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                with cl.correlation_scope("wsu") as cid:
                    await db.upsert_fill({
                        "account_id": 1, "exchange_fill_id": "F-1",
                        "exchange_order_id": "E-5", "symbol": "BTCUSDT",
                        "terminal_position_id": "",   # stranded shape
                        "is_close": True, "timestamp_ms": 5,
                    })
                    await db.insert_closed_position({
                        "account_id": 1, "symbol": "BTCUSDT",
                        "direction": "LONG", "quantity": 1.0,
                        "entry_price": 100.0, "exit_price": 110.0,
                        "entry_time_ms": 1, "exit_time_ms": 2,
                        "terminal_position_id": "", "calc_id": None,
                    })
                return cid, _drain()
            finally:
                await db.close()

        cid, envs = asyncio.run(main())
        writes = _by_cat(envs, "db_write")
        fills = [e for e in writes if e["payload"]["table"] == "fills"]
        closes = [e for e in writes
                  if e["payload"]["table"] == "closed_positions"]
        assert len(fills) == 1 and len(closes) == 1
        # chain-join: both rode the ambient corr scope
        assert fills[0]["corr_id"] == closes[0]["corr_id"] == cid
        assert fills[0]["payload"]["terminal_position_id"] == ""
        assert fills[0]["payload"]["rowcount"] == 1
        p = closes[0]["payload"]
        assert p["op"] == "REPLACE" and p["rowcount"] == 1
        # the canonical stranded-row query: tpid == "" VERBATIM
        assert p["terminal_position_id"] == "" and p["calc_id"] == ""

    def test_pollution_reject_is_a_line_not_an_absence(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                await db.insert_closed_position({
                    "account_id": 1, "symbol": "BTCUSDT",
                    "direction": "LONG", "quantity": 1.0,
                    "entry_price": 0, "exit_price": 110.0,  # pollution shape
                    "terminal_position_id": "POS-X",
                })
                return _drain()
            finally:
                await db.close()

        envs = asyncio.run(main())
        w = _by_cat(envs, "db_write")
        assert len(w) == 1
        p = w[0]["payload"]
        assert p["ok"] is False and p["reason"] == "pollution_reject"
        assert p["rowcount"] == 0
        assert p["terminal_position_id"] == "POS-X"

    def test_fill_and_update_order_emits_one_line_per_table(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                await db.upsert_order_batch([{
                    "account_id": 1, "exchange_order_id": "E-6",
                    "symbol": "BTCUSDT", "status": "new",
                    "quantity": 2.0, "filled_qty": 0.0,
                    "updated_at_ms": 1000,
                }])
                _drain()
                await db.upsert_fill_and_update_order(
                    {"account_id": 1, "exchange_fill_id": "F-2",
                     "exchange_order_id": "E-6", "symbol": "BTCUSDT",
                     "quantity": 1.0, "price": 100.0, "timestamp_ms": 9},
                    exchange_order_id="E-6",
                )
                return _drain()
            finally:
                await db.close()

        envs = asyncio.run(main())
        writes = _by_cat(envs, "db_write")
        tables = sorted(e["payload"]["table"] for e in writes)
        assert tables == ["fills", "orders"]
        order_w = [e for e in writes if e["payload"]["table"] == "orders"][0]
        assert order_w["payload"]["writer"] == "fill_qty_rollup"
        assert order_w["payload"]["rowcount"] == 1

    def test_junction_and_funding_dedup_visibility(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                await db.upsert_position_calc_link({
                    "position_id": "", "calc_id": "CALC-1", "order_id": 5,
                    "account_id": 1, "contributed_qty": 1.0,
                    "first_fill_ts": 1, "last_fill_ts": 1,
                })
                ev = {"position_id": "POS-1", "calc_id": "CALC-1",
                      "account_id": 1, "symbol": "BTCUSDT", "amount": -0.5,
                      "ts_ms": 9, "venue_event_id": "V-1"}
                first = await db.insert_funding_event(dict(ev))
                replay = await db.insert_funding_event(dict(ev))
                return first, replay, _drain()
            finally:
                await db.close()

        first, replay, envs = asyncio.run(main())
        assert first is True and replay is False
        junction = [e for e in _by_cat(envs, "db_write")
                    if e["payload"]["table"] == "positions_calcs"]
        assert len(junction) == 1
        # tpid VERBATIM incl. "" on the junction write
        assert junction[0]["payload"]["terminal_position_id"] == ""
        assert junction[0]["payload"]["calc_id"] == "CALC-1"
        funding = [e for e in _by_cat(envs, "db_write")
                   if e["payload"]["table"] == "funding_events"]
        assert len(funding) == 2
        assert funding[0]["payload"]["rowcount"] == 1
        # WS-replay dedup hit: INSERT OR IGNORE rowcount=0 is VISIBLE
        assert funding[1]["payload"]["rowcount"] == 0

    def test_pre_trade_log_and_mfe_mae_writers(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                await db.insert_pre_trade_log({
                    "account_id": 1, "ticker": "BTCUSDT",
                    "calc_id": "CALC-9", "eligible": True,
                })
                await db.insert_closed_position({
                    "account_id": 1, "symbol": "BTCUSDT",
                    "direction": "LONG", "quantity": 1.0,
                    "entry_price": 100.0, "exit_price": 110.0,
                    "entry_time_ms": 1, "exit_time_ms": 2,
                    "terminal_position_id": "POS-2", "calc_id": None,
                })
                async with db._conn.execute(
                    "SELECT id FROM closed_positions "
                    "WHERE terminal_position_id='POS-2'",
                ) as cur:
                    row_id = (await cur.fetchone())[0]
                _drain()
                await db.update_closed_position_mfe_mae(row_id, 5.0, -2.0)
                return _drain()
            finally:
                await db.close()

        envs = asyncio.run(main())
        mfe = [e for e in _by_cat(envs, "db_write")
               if e["payload"].get("writer") == "mfe_mae_update"]
        assert len(mfe) == 1
        assert mfe[0]["payload"]["rowcount"] == 1

    def test_pre_trade_log_tap_carries_calc_id(self, tmp_path):
        async def main():
            db = await _mk_db(tmp_path)
            try:
                await db.insert_pre_trade_log({
                    "account_id": 1, "ticker": "ETHUSDT",
                    "calc_id": "CALC-7", "eligible": False,
                })
                return _drain()
            finally:
                await db.close()

        envs = asyncio.run(main())
        w = [e for e in _by_cat(envs, "db_write")
             if e["payload"]["table"] == "pre_trade_log"]
        assert len(w) == 1
        assert w[0]["symbol"] == "ETHUSDT"
        p = w[0]["payload"]
        assert p["calc_id"] == "CALC-7" and p["eligible"] is False
        assert p["op"] == "INSERT" and p["rowcount"] == 1


# ── failure paths: a write that did NOT land must still be a line ───────────

class TestDbWriteFailurePaths:
    def test_insert_closed_position_batched_failure_emits_then_reraises(
        self, tmp_path,
    ):
        import sqlite3 as _sqlite3

        async def main():
            db = await _mk_db(tmp_path)
            try:
                orig = db._conn.execute

                def _boom(sql, *a, **k):
                    if "INSERT OR REPLACE INTO closed_positions" in sql:
                        raise _sqlite3.OperationalError("disk I/O error")
                    return orig(sql, *a, **k)

                db._conn.execute = _boom
                raised = False
                try:
                    await db.insert_closed_position({
                        "account_id": 1, "symbol": "BTCUSDT",
                        "direction": "LONG", "quantity": 1.0,
                        "entry_price": 100.0, "exit_price": 110.0,
                        "entry_time_ms": 1, "exit_time_ms": 2,
                        "terminal_position_id": "POS-F", "calc_id": None,
                    }, commit=False)
                except _sqlite3.OperationalError:
                    raised = True
                finally:
                    db._conn.execute = orig
                return raised, _drain()
            finally:
                await db.close()

        raised, envs = asyncio.run(main())
        # T191 contract intact: commit=False failures still PROPAGATE
        assert raised is True
        w = [e for e in _by_cat(envs, "db_write")
             if e["payload"]["table"] == "closed_positions"]
        assert len(w) == 1
        p = w[0]["payload"]
        assert p["ok"] is False
        assert p["error_type"] == "OperationalError"
        assert p["terminal_position_id"] == "POS-F"

    def test_upsert_fill_failure_swallowed_with_error_line(self, tmp_path):
        import sqlite3 as _sqlite3

        async def main():
            db = await _mk_db(tmp_path)
            try:
                orig = db._conn.execute

                def _boom(sql, *a, **k):
                    if "INSERT INTO fills" in sql:
                        raise _sqlite3.OperationalError("locked")
                    return orig(sql, *a, **k)

                db._conn.execute = _boom
                try:
                    # swallow path: must NOT raise
                    await db.upsert_fill({
                        "account_id": 1, "exchange_fill_id": "F-X",
                        "symbol": "BTCUSDT", "timestamp_ms": 1,
                    })
                finally:
                    db._conn.execute = orig
                return _drain()
            finally:
                await db.close()

        envs = asyncio.run(main())
        w = [e for e in _by_cat(envs, "db_write")
             if e["payload"]["table"] == "fills"]
        assert len(w) == 1
        p = w[0]["payload"]
        assert p["ok"] is False and p["error_type"] == "OperationalError"
        assert p["exchange_fill_id"] == "F-X"


# ── audit-log writers: the chain-join into the typed tables (spec §5.5) ─────

class TestAuditLogWriterTaps:
    def _mk_legacy_db(self, tmp_path):
        import sqlite3 as _s
        conn = _s.connect(tmp_path / "risk_engine.db")
        conn.execute(
            "CREATE TABLE engine_events (id INTEGER PRIMARY KEY,"
            " account_id INT, event_type TEXT, payload_json TEXT,"
            " timestamp TEXT, source TEXT)",
        )
        conn.execute(
            "CREATE TABLE trade_events (id INTEGER PRIMARY KEY,"
            " account_id INT, calc_id TEXT, event_type TEXT,"
            " payload_json TEXT, source TEXT, timestamp TEXT)",
        )
        conn.commit()
        conn.close()
        return str(tmp_path)

    def test_log_event_emits_chain_join_line(self, tmp_path):
        from core import event_log

        ddir = self._mk_legacy_db(tmp_path)
        etype = sorted(event_log._VALID_EVENT_TYPES)[0]
        row_id = event_log.log_event(1, etype, {"k": 1}, "test", data_dir=ddir)
        w = [e for e in _by_cat(_drain(), "db_write")
             if e["payload"]["table"] == "engine_events"]
        assert len(w) == 1
        assert w[0]["payload"]["row_id"] == row_id
        assert w[0]["payload"]["event_type"] == etype
        assert w[0]["payload"]["rowcount"] == 1

    def test_log_trade_event_emits_and_pollution_reject_twin(self, tmp_path):
        from core import trade_event_log

        ddir = self._mk_legacy_db(tmp_path)
        rid = trade_event_log.log_trade_event(
            1, "CALC-1", "position_closed",
            {"entry_price": 100.0, "exit_price": 110.0, "symbol": "BTCUSDT"},
            "test", data_dir=ddir,
        )
        assert rid > 0
        ok_w = [e for e in _by_cat(_drain(), "db_write")
                if e["payload"]["table"] == "trade_events"]
        assert len(ok_w) == 1
        assert ok_w[0]["payload"]["calc_id"] == "CALC-1"
        assert ok_w[0]["symbol"] == "BTCUSDT"
        # pollution shape → the REFUSED write is a line, not an absence
        rid2 = trade_event_log.log_trade_event(
            1, "CALC-1", "position_closed",
            {"entry_price": 0, "exit_price": 110.0, "symbol": "BTCUSDT"},
            "test", data_dir=ddir,
        )
        assert rid2 == -1
        rej = [e for e in _by_cat(_drain(), "db_write")
               if e["payload"]["table"] == "trade_events"]
        assert len(rej) == 1
        assert rej[0]["payload"]["ok"] is False
        assert rej[0]["payload"]["reason"] == "pollution_reject"

    @staticmethod
    def _fail_insert_connect(orig):
        """A sqlite3.connect wrapper that injects a Connection subclass whose
        execute raises on INSERT (only) — so _resolve_db_path's SELECT probe
        survives and only the write fails. A subclass via the ``factory``
        arg is the supported way to override execute (the C-level
        sqlite3.Connection forbids per-instance attribute assignment)."""
        import sqlite3 as _s

        class _FailInsert(_s.Connection):
            def execute(self, sql, *a, **k):
                if str(sql).strip().upper().startswith("INSERT"):
                    raise _s.OperationalError("disk I/O error")
                return super().execute(sql, *a, **k)

        return lambda path, *a, **k: orig(path, *a, factory=_FailInsert, **k)

    def test_log_event_write_failure_emits_ok_false_twin_ha41(self, tmp_path):
        # HA-41 (CL.T5): a real INSERT failure was success-side only and every
        # caller swallows → envelope-less. The ok:false twin (T3a pattern)
        # makes the failed engine_events write a one-query find.
        from core import event_log

        ddir = self._mk_legacy_db(tmp_path)
        etype = sorted(event_log._VALID_EVENT_TYPES)[0]
        orig = event_log.sqlite3.connect
        event_log.sqlite3.connect = self._fail_insert_connect(orig)
        try:
            with pytest.raises(Exception):
                event_log.log_event(1, etype, {"k": 1}, "test", data_dir=ddir)
        finally:
            event_log.sqlite3.connect = orig
        w = [e for e in _by_cat(_drain(), "db_write")
             if e["payload"]["table"] == "engine_events"]
        assert len(w) == 1
        assert w[0]["payload"]["ok"] is False
        assert w[0]["payload"]["error_type"] == "OperationalError"

    def test_log_trade_event_write_failure_emits_ok_false_twin_ha41(self, tmp_path):
        from core import trade_event_log

        ddir = self._mk_legacy_db(tmp_path)
        orig = trade_event_log.sqlite3.connect
        trade_event_log.sqlite3.connect = self._fail_insert_connect(orig)
        try:
            with pytest.raises(Exception):
                trade_event_log.log_trade_event(
                    1, "CALC-1", "position_closed",
                    {"entry_price": 100.0, "exit_price": 110.0,
                     "symbol": "BTCUSDT"}, "test", data_dir=ddir)
        finally:
            trade_event_log.sqlite3.connect = orig
        w = [e for e in _by_cat(_drain(), "db_write")
             if e["payload"]["table"] == "trade_events"
             and e["payload"].get("ok") is False]
        assert len(w) == 1
        assert w[0]["payload"]["error_type"] == "OperationalError"
        assert w[0]["payload"]["calc_id"] == "CALC-1"


# ── registry conformance for the T3a categories ─────────────────────────────

class TestT3aRegistryConformance:
    def test_all_t3a_categories_registered_in_expected_groups(self):
        reg = cl.registry()
        for cat in ("position_snapshot_applied", "position_incremental_applied",
                    "account_update_applied", "portfolio_recalculated",
                    "calc_transition", "link_transition",
                    "order_status_applied", "reconcile_promote"):
            assert reg[cat] == "state"
        assert reg["db_write"] == "db"
