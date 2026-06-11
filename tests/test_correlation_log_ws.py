"""CL.T1b — WS frame taps + connection-lifecycle taps + task naming.

Covers: wsu-/wsm-/wsp-/wsn- per-frame minting, the §5.4 frame categories
(dedup_keys included), the §5.4b lifecycle categories (calc_symbol_change /
ws_stream_rebuild behaviorally; connect/disconnect/keepalive via source
pins — they live inside real-socket paths), plugin market frames reusing
the volume-gated market categories, and ws task naming.
"""

import asyncio
import inspect
import json
from types import SimpleNamespace

import pytest

import core.correlation_log as cl
import core.ws_manager as wsm


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


@pytest.fixture(autouse=True)
def _pin(monkeypatch):
    _drain()
    monkeypatch.setattr(cl, "_enabled", True)
    monkeypatch.setattr(cl, "_profile", "full")
    monkeypatch.setattr(cl, "_mark_price_sample", 0)
    monkeypatch.setattr(cl, "_sample_counters", {})
    monkeypatch.setattr(cl, "_emit_error_logged", set())
    # ws_manager globals a test may touch — save/restore
    monkeypatch.setattr(wsm, "_calculator_symbol", None)
    monkeypatch.setattr(wsm, "_market_ws_task", None)
    monkeypatch.setattr(wsm, "_last_streams", [])
    yield
    _drain()


# ── Binance user-data frames (wsu-*) ─────────────────────────────────────────

class TestUserDataFrames:
    def _run_event(self, monkeypatch, msg, recorder):
        monkeypatch.setattr(wsm, "_get_ws_adapter", lambda: None)
        monkeypatch.setattr(wsm, "event_bus",
                            SimpleNamespace(publish=recorder("bus")))
        monkeypatch.setattr(wsm, "_apply_account_update", recorder("account"))
        monkeypatch.setattr(wsm, "_apply_order_update", recorder("order"))
        monkeypatch.setattr(wsm, "_apply_algo_update", recorder("algo"))
        asyncio.run(wsm._handle_user_event(msg))

    @staticmethod
    def _recorder(seen):
        def make(name):
            async def fn(*a, **k):
                seen.append((name, cl.current_corr_id()))
            return fn
        return make

    def test_order_update_mints_wsu_and_emits_with_dedup_key(self, monkeypatch):
        seen = []
        msg = {"e": "ORDER_TRADE_UPDATE", "E": 0,
               "o": {"i": 8821, "X": "FILLED", "S": "BUY", "q": "0.42",
                     "p": "69210", "z": "0.42", "s": "BTCUSDT", "x": "TRADE"}}
        self._run_event(monkeypatch, msg, self._recorder(seen))
        (env,) = [e for e in _drain() if e["category"] == "ws_order_update"]
        assert env["corr_id"].startswith("wsu-")
        assert env["symbol"] == "BTCUSDT"
        assert env["payload"]["dedup_key"] == "8821:FILLED:0.42"
        assert env["payload"]["status"] == "FILLED"
        # the dispatched handler AND the end-of-function bus publish both ran
        # INSIDE the frame's chain
        handler = [c for n, c in seen if n == "order"]
        assert handler == [env["corr_id"]]
        assert [c for n, c in seen if n == "bus"] == [env["corr_id"]]

    def test_algo_update_uses_aid_and_omits_dedup_when_id_missing(self, monkeypatch):
        # audit T1b-1: Binance algo frames key the id as "aid"; a degenerate
        # None-keyed dedup would FALSE-match distinct frames
        seen = []
        msg = {"e": "ALGO_UPDATE", "E": 0,
               "o": {"aid": 5512, "X": "NEW", "S": "SELL", "q": "1.0",
                     "p": "2400", "at": "STOP", "s": "XAUUSDT"}}
        self._run_event(monkeypatch, msg, self._recorder(seen))
        (env,) = [e for e in _drain() if e["category"] == "ws_algo_update"]
        assert env["payload"]["order_id"] == 5512
        assert env["payload"]["dedup_key"] == "5512:NEW:1.0"
        assert env["payload"]["algo_type"] == "STOP"
        # id missing entirely (foreign adapter shape) → envelope WITHOUT key
        msg2 = {"e": "ALGO_UPDATE", "E": 0, "o": {"X": "NEW", "q": "1.0"}}
        self._run_event(monkeypatch, msg2, self._recorder(seen))
        (env2,) = [e for e in _drain() if e["category"] == "ws_algo_update"]
        assert env2["payload"]["order_id"] is None
        assert "dedup_key" not in env2["payload"]

    def test_account_update_emits_summary(self, monkeypatch):
        seen = []
        msg = {"e": "ACCOUNT_UPDATE", "E": 0,
               "a": {"m": "ORDER", "B": [{}], "P": [{}, {}]}}
        self._run_event(monkeypatch, msg, self._recorder(seen))
        (env,) = [e for e in _drain() if e["category"] == "ws_account_update"]
        assert env["payload"] == {"reason": "ORDER", "n_balances": 1, "n_positions": 2}
        assert env["corr_id"].startswith("wsu-")

    def test_each_frame_gets_a_fresh_chain(self, monkeypatch):
        seen = []
        msg = {"e": "ACCOUNT_UPDATE", "E": 0, "a": {"m": "X", "B": [], "P": []}}
        self._run_event(monkeypatch, msg, self._recorder(seen))
        self._run_event(monkeypatch, dict(msg), self._recorder(seen))
        corrs = [e["corr_id"] for e in _drain() if e["category"] == "ws_account_update"]
        assert len(corrs) == 2 and corrs[0] != corrs[1]


# ── Binance market frames (wsm-*, volume-gated) ──────────────────────────────

class TestMarketFrames:
    def test_kline_emitted_at_full(self):
        wsm._tap_market_frame("kline", {"symbol": "ETHUSDT", "candle": [1, 2]})
        (env,) = _drain()
        assert env["category"] == "ws_kline" and env["symbol"] == "ETHUSDT"

    def test_depth_default_off(self):
        wsm._tap_market_frame("depthUpdate", {"symbol": "ETHUSDT", "bids": [], "asks": []})
        assert _drain() == []

    def test_mark_price_gated_by_sample(self, monkeypatch):
        wsm._tap_market_frame("markPriceUpdate", {"symbol": "ETHUSDT", "mark_price": 3000.5})
        assert _drain() == []  # sample 0 = drop
        monkeypatch.setattr(cl, "_mark_price_sample", 1)
        wsm._tap_market_frame("markPriceUpdate", {"symbol": "ETHUSDT", "mark_price": 3000.5})
        (env,) = _drain()
        assert env["category"] == "ws_mark_price" and env["payload"]["mark"] == 3000.5

    def test_linkage_profile_drops_market_frames(self, monkeypatch):
        monkeypatch.setattr(cl, "_profile", "linkage")
        wsm._tap_market_frame("kline", {"symbol": "ETHUSDT", "candle": []})
        assert _drain() == []


# ── Quantower platform frames (wsp-*) ────────────────────────────────────────

class TestPlatformFrames:
    @pytest.fixture
    def bridge(self):
        from core.platform_bridge import platform_bridge
        return platform_bridge

    def test_fill_frame_emits_platform_fill_with_dedup(self, bridge):
        bridge._tap_platform_frame("fill", {"symbol": "XAUUSDT", "side": "BUY",
                                            "quantity": 1.0, "price": 2400.0,
                                            "trade_id": "T-77"})
        (env,) = _drain()
        assert env["category"] == "platform_fill"
        assert env["peer"] == "quantower" and env["symbol"] == "XAUUSDT"
        assert env["payload"]["dedup_key"] == "qt:T-77"
        assert env["payload"]["historical"] is False

    def test_historical_fill_flagged(self, bridge):
        bridge._tap_platform_frame("historical_fill", {"trade_id": "T-1"})
        (env,) = _drain()
        assert env["payload"]["historical"] is True

    def test_snapshot_kinds_collapse_to_platform_snapshot(self, bridge):
        for kind in ("position_snapshot", "account_state", "order_snapshot", "orders_changed"):
            bridge._tap_platform_frame(kind, {})
        envs = _drain()
        assert [e["payload"]["kind"] for e in envs] == [
            "position_snapshot", "account_state", "order_snapshot", "orders_changed"]
        assert {e["category"] for e in envs} == {"platform_snapshot"}

    def test_plugin_market_frames_reuse_gated_market_categories(self, bridge, monkeypatch):
        bridge._tap_platform_frame("mark_price", {"symbol": "BTCUSDT", "price": 69000})
        bridge._tap_platform_frame("depth_snapshot", {"symbol": "BTCUSDT"})
        assert _drain() == []  # mark sample 0 + depth default-off
        monkeypatch.setattr(cl, "_mark_price_sample", 1)
        bridge._tap_platform_frame("mark_price", {"symbol": "BTCUSDT", "price": 69000})
        (env,) = _drain()
        assert env["category"] == "ws_mark_price" and env["peer"] == "quantower"

    def test_heartbeat_emits_nothing(self, bridge):
        bridge._tap_platform_frame("heartbeat", {})
        assert _drain() == []

    def test_platform_push_is_market_grouped_and_off_in_linkage(self, monkeypatch):
        # the NAMED deviation (registry comment): platform_push rides the
        # ~1Hz risk-state fanout → market group, dropped by linkage
        assert cl.registry()["platform_push"] == cl.GROUP_MARKET
        monkeypatch.setattr(cl, "_profile", "linkage")
        assert not cl.enabled(cl.CAT_PLATFORM_PUSH)

    def test_dispatch_inherits_ambient_chain_ha1(self, bridge, monkeypatch):
        # HA-1 (CL.T2b): _dispatch no longer mints — the REST fallback
        # (/api/platform/event) inherits its request's http-* chain, so a
        # REST-POSTed fill's money path joins the http pair instead of
        # splitting into a trigger-less wsp chain.
        seen = []

        async def fake_fill(msg):
            seen.append(cl.current_corr_id())

        monkeypatch.setattr(bridge, "_handle_fill", fake_fill)
        with cl.correlation_scope("http") as cid:
            asyncio.run(bridge._dispatch({"type": "fill", "symbol": "XAUUSDT",
                                          "trade_id": "T-9"}))
        assert seen == [cid]  # inherited, NOT a fresh wsp-*
        (env,) = [e for e in _drain() if e["category"] == "platform_fill"]
        assert env["corr_id"] == cid

    def test_handle_ws_receive_loop_mints_wsp_per_frame(self, bridge, monkeypatch):
        # the WS path still mints (HA-1 moved the mint to the receive loop)
        seen = []

        async def fake_dispatch(msg):
            seen.append((msg["type"], cl.current_corr_id()))

        class FakeWS:
            async def accept(self):
                return None

            async def send_text(self, text):
                return None

            async def iter_text(self):
                yield json.dumps({"type": "heartbeat"})
                yield json.dumps({"type": "hello"})

        monkeypatch.setattr(bridge, "_dispatch", fake_dispatch)
        asyncio.run(bridge.handle_ws(FakeWS()))
        _drain()  # discard push/disconnect envelopes — minting is the assert
        assert [t for t, _ in seen] == ["heartbeat", "hello"]
        corrs = [c for _, c in seen]
        assert all(c.startswith("wsp-") for c in corrs)
        assert corrs[0] != corrs[1]  # fresh chain per frame


# ── BWE news frames (wsn-*) ──────────────────────────────────────────────────

class TestNewsFrames:
    def test_news_message_mints_wsn_and_emits(self, monkeypatch):
        import core.news_fetcher as nf
        seen = []

        async def fake_upsert(rows):
            seen.append(cl.current_corr_id())

        monkeypatch.setattr(nf.db, "upsert_news_items", fake_upsert)
        consumer = nf.BweWsConsumer()
        raw = json.dumps({"id": 991, "news_title": "headline",
                          "timestamp": 1760000000000, "source_name": "x"})
        asyncio.run(consumer._handle_message(raw))
        (env,) = [e for e in _drain() if e["category"] == "ws_news"]
        assert env["corr_id"].startswith("wsn-")
        assert env["payload"]["dedup_key"] == "bwe:991"
        # the db write happened INSIDE the frame's chain (T3a will tap it)
        assert seen == [env["corr_id"]]

    def test_pong_and_empty_headline_emit_nothing(self, monkeypatch):
        import core.news_fetcher as nf
        monkeypatch.setattr(nf.db, "upsert_news_items",
                            lambda rows: (_ for _ in ()).throw(AssertionError))
        consumer = nf.BweWsConsumer()
        asyncio.run(consumer._handle_message("pong"))
        asyncio.run(consumer._handle_message(json.dumps({"news_title": ""})))
        assert [e for e in _drain() if e["category"] == "ws_news"] == []


# ── WS connection lifecycle (§5.4b) ──────────────────────────────────────────

class TestWsLifecycle:
    def test_calc_symbol_change_without_loop(self):
        wsm.set_calculator_symbol("ethusdt")
        (env,) = [e for e in _drain() if e["category"] == "calc_symbol_change"]
        assert env["payload"] == {"old": None, "new": "ETHUSDT",
                                  "restart_scheduled": False}
        assert env["symbol"] == "ETHUSDT"

    def test_calc_symbol_same_symbol_is_silent(self):
        wsm.set_calculator_symbol("btcusdt")
        _drain()
        wsm.set_calculator_symbol("BTCUSDT")  # no actual change
        assert [e for e in _drain() if e["category"] == "calc_symbol_change"] == []

    def test_calc_symbol_change_with_loop_schedules_restart(self, monkeypatch):
        calls = []

        async def fake_restart(trigger="position_change"):
            calls.append(trigger)

        monkeypatch.setattr(wsm, "restart_market_streams", fake_restart)

        async def main():
            wsm.set_calculator_symbol("solusdt")
            await asyncio.sleep(0)  # let the created task run

        asyncio.run(main())
        assert calls == ["calc_symbol_change"]
        (env,) = [e for e in _drain() if e["category"] == "calc_symbol_change"]
        assert env["payload"]["restart_scheduled"] is True

    def test_stream_rebuild_emits_old_new_diff(self, monkeypatch):
        async def fake_loop(attempt=0):
            return None

        monkeypatch.setattr(wsm, "_market_stream_loop", fake_loop)
        monkeypatch.setattr(wsm, "_last_streams", ["aaausdt@kline_5m", "aaausdt@depth20"])
        monkeypatch.setattr(wsm, "_build_market_streams",
                            lambda: ["bbbusdt@kline_5m", "aaausdt@kline_5m"])

        async def main():
            await wsm.restart_market_streams(trigger="calc_symbol_change")
            await asyncio.sleep(0)
            return wsm._market_ws_task.get_name()

        task_name = asyncio.run(main())
        assert task_name == "ws-market"
        (env,) = [e for e in _drain() if e["category"] == "ws_stream_rebuild"]
        p = env["payload"]
        assert p["trigger"] == "calc_symbol_change"
        assert p["added"] == ["bbbusdt@kline_5m"]
        assert p["removed"] == ["aaausdt@depth20"]

    def test_no_streams_branch_resets_last_streams_ha5(self, monkeypatch):
        # HA-5: without the reset, a flat interlude leaves _last_streams
        # stale and the next rebuild diff reports phantom 'removed' entries
        monkeypatch.setattr(wsm, "_build_market_streams", lambda: [])
        monkeypatch.setattr(wsm, "_last_streams", ["ghost@kline_5m"])

        async def boom(_secs):
            raise SystemExit  # exit the loop right after the reset

        monkeypatch.setattr(asyncio, "sleep", boom)
        with pytest.raises(SystemExit):
            asyncio.run(wsm._market_stream_loop())
        assert wsm._last_streams == []

    def test_connect_lifecycle_taps_present_in_socket_paths(self):
        """The connect/connected/disconnect emits live inside real-socket
        blocks — pinned at source level (behavioral coverage needs a live
        socket; the leak QUERY is covered by the rebuild/symbol tests)."""
        user_src = inspect.getsource(wsm._user_data_loop)
        market_src = inspect.getsource(wsm._market_stream_loop)
        for src in (user_src, market_src):
            assert "CAT_WS_CONNECT" in src
            assert "CAT_WS_CONNECTED" in src
            assert "CAT_WS_DISCONNECT" in src
        assert '"streams": streams' in market_src  # full list on ws_connect
        assert 'correlation_log.tick("wsm")' in market_src  # per-frame mint
        keepalive_src = inspect.getsource(wsm._keepalive_loop)
        assert "CAT_WS_LISTENKEY_KEEPALIVE" in keepalive_src
        news_src = inspect.getsource(__import__("core.news_fetcher", fromlist=["BweWsConsumer"]).BweWsConsumer.run)
        assert "CAT_WS_CONNECTED" in news_src and "CAT_WS_DISCONNECT" in news_src

    def test_ws_tasks_are_named_at_every_spawn_site(self):
        src = inspect.getsource(wsm)
        assert src.count('name="ws-user"') >= 3      # start + standby + reconnect
        assert src.count('name="ws-market"') >= 4    # start + no-streams + reconnect + rebuild
        assert 'name="ws-keepalive"' in src
        assert 'name="ws-fallback"' in src
        assert src.count('name="ws-restart"') >= 2   # both restart trigger sites
        # no unnamed create_task left in ws_manager — a window scan, because
        # a paren-matching regex truncates at nested calls' first ')'
        import re
        for m in re.finditer(r"asyncio\.create_task\(", src):
            window = src[m.start(): m.start() + 200]
            assert "name=" in window, f"unnamed ws task near: {window[:90]!r}"
