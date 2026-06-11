"""CL.T2b — outbound-boundary taps (spec §5.3/§5.3b/§5.7) + hand-off #2.

Covers: the venue REST chokepoint (rest_call/rest_return on the loop side
of adapters _run, with the scope-less rest-* fallback), the outbound-HTTP
families (webhook POST / Finnhub; FRED+yahoo via source pins), the webhook
internal-queue corr carry (spec §3.3 hand-off #2 — the POST joins the
originating close's chain), and the pubsub_publish tap.
"""

import asyncio
import contextlib
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


@pytest.fixture(autouse=True)
def _pin(monkeypatch):
    _drain()
    monkeypatch.setattr(cl, "_enabled", True)
    monkeypatch.setattr(cl, "_profile", "full")
    monkeypatch.setattr(cl, "_emit_error_logged", set())
    yield
    _drain()


# ── venue REST chokepoint (spec §5.3) ────────────────────────────────────────

class TestRestChokepoint:
    @pytest.fixture
    def adapter(self, monkeypatch):
        from core.adapters.base import BaseExchangeAdapter

        class _Dummy(BaseExchangeAdapter):
            exchange_id = "binance"

        inst = _Dummy("k", "s")
        monkeypatch.setattr(inst, "_get_weight_tracker", lambda: None)
        return inst

    def test_call_return_pair_share_ambient_corr(self, adapter):
        def fetch_positions():
            return [1, 2, 3]

        async def main():
            with cl.correlation_scope("sch-account_refresh") as cid:
                result = await adapter._run(fetch_positions)
            return cid, result

        cid, result = asyncio.run(main())
        assert result == [1, 2, 3]
        call, ret = [e for e in _drain() if e["component"] == "adapters.binance"]
        assert call["category"] == "rest_call" and ret["category"] == "rest_return"
        assert call["corr_id"] == ret["corr_id"] == cid
        assert call["direction"] == "out" and ret["direction"] == "in"
        assert call["payload"]["endpoint"] == "fetch_positions"
        assert ret["payload"]["ok"] is True
        assert ret["payload"]["n"] == 3
        assert ret["payload"]["duration_ms"] >= 0

    def test_scopeless_call_gets_one_shot_rest_fallback_pair(self, adapter):
        async def main():
            assert cl.current_corr_id() == ""
            await adapter._run(lambda: {})
            return cl.current_corr_id()

        ambient_after = asyncio.run(main())
        call, ret = [e for e in _drain() if e["component"] == "adapters.binance"]
        assert call["corr_id"].startswith("rest-")
        assert call["corr_id"] == ret["corr_id"]  # the pair still correlates
        assert ambient_after == ""  # the one-shot binding was reset

    def test_translated_error_tapped_then_raised(self, adapter):
        import ccxt
        from core.adapters.errors import ConnectionError as AdapterConnError

        def boom():
            raise ccxt.NetworkError("link down")

        async def main():
            with cl.correlation_scope("sch-ping"):
                await adapter._run(boom)

        with pytest.raises(AdapterConnError):
            asyncio.run(main())
        ret = [e for e in _drain() if e["category"] == "rest_return"]
        assert len(ret) == 1
        assert ret[0]["payload"]["ok"] is False
        # the ENGINE-facing translated type, not the ccxt internal
        assert ret[0]["payload"]["error_type"] == "ConnectionError"


# ── webhook: hand-off #2 + http_out taps (spec §3.3, §5.3b) ──────────────────

class TestWebhookHandoff:
    @pytest.fixture
    def dispatcher(self, monkeypatch):
        import core.webhook_dispatcher as wd

        d = wd.WebhookDispatcher(db=object(), max_attempts=2,
                                 initial_backoff_s=0.0, max_backoff_s=0.0)
        cfg = SimpleNamespace(webhook_enabled=True,
                              webhook_url="https://hooks.example.com/secret-token/x")

        async def fake_cfg(db, account_id):
            return cfg

        monkeypatch.setattr(wd, "read_account_config_async", fake_cfg)
        return d

    @staticmethod
    async def _pump(d):
        task = asyncio.create_task(d.run(), name="webhook")
        await d._queue.join()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def test_post_joins_the_originating_chain_two_hops(self, dispatcher, monkeypatch):
        # close frame chain → bus re-bind (T2a) → handler enqueues WITH corr →
        # worker re-binds (T2b) → the POST taps ride the SAME chain
        posted = []

        async def fake_post(url, body):
            posted.append((url, cl.current_corr_id()))

        monkeypatch.setattr(dispatcher, "_post", fake_post)
        handler = dispatcher.make_handler(7)

        async def main():
            with cl.correlation_scope("wsu") as cid:
                await handler({"position_id": "P1"})  # what the bus would do (re-bound)
            assert cl.current_corr_id() == ""
            await self._pump(dispatcher)
            return cid

        cid = asyncio.run(main())
        assert posted and posted[0][1] == cid
        call, ret = [e for e in _drain() if e["component"] == "webhook_dispatcher"]
        assert call["category"] == "http_out_call" and ret["category"] == "http_out_return"
        assert call["corr_id"] == ret["corr_id"] == cid  # NOT a sch-webhook tick
        assert call["payload"]["host"] == "hooks.example.com"
        assert call["payload"]["attempt"] == 1
        assert ret["payload"]["ok"] is True
        # the URL path/query (which may carry tokens) never appears
        assert "secret-token" not in json.dumps([call, ret])

    def test_basic_auth_userinfo_never_leaks_into_host(self, monkeypatch):
        # audit T2b-1: netloc includes user:tok@…; hostname strips it
        import core.webhook_dispatcher as wd

        d = wd.WebhookDispatcher(db=object(), max_attempts=1,
                                 initial_backoff_s=0.0, max_backoff_s=0.0)
        cfg = SimpleNamespace(webhook_enabled=True,
                              webhook_url="https://user:tok123@hooks.example.com:8443/x")

        async def fake_cfg(db, account_id):
            return cfg

        async def ok_post(url, body):
            return None

        monkeypatch.setattr(wd, "read_account_config_async", fake_cfg)
        monkeypatch.setattr(d, "_post", ok_post)
        asyncio.run(d._dispatch_one(7, {"position_id": "P1"}))
        envs = [e for e in _drain() if e["component"] == "webhook_dispatcher"]
        assert envs and all(e["payload"]["host"] == "hooks.example.com" for e in envs)
        assert "tok123" not in json.dumps(envs)

    def test_failed_post_taps_status_then_retries_and_dead_letters(self, dispatcher, monkeypatch):
        class FakeHTTPError(Exception):
            def __init__(self):
                self.response = SimpleNamespace(status_code=503)

        async def bad_post(url, body):
            raise FakeHTTPError()

        dead = []

        async def fake_dead_letter(account_id, payload, error):
            dead.append(account_id)

        monkeypatch.setattr(dispatcher, "_post", bad_post)
        monkeypatch.setattr(dispatcher, "_dead_letter", fake_dead_letter)
        handler = dispatcher.make_handler(7)

        async def main():
            with cl.correlation_scope("wsu"):
                await handler({"position_id": "P1"})
            await self._pump(dispatcher)

        asyncio.run(main())
        assert dead == [7]
        rets = [e for e in _drain() if e["category"] == "http_out_return"]
        assert [r["payload"]["attempt"] for r in rets] == [1, 2]  # max_attempts=2
        assert all(r["payload"]["ok"] is False for r in rets)
        assert all(r["payload"]["status"] == 503 for r in rets)
        assert all(r["payload"]["error_type"] == "FakeHTTPError" for r in rets)


# ── Finnhub (spec §5.3b) ─────────────────────────────────────────────────────

class TestFinnhubTaps:
    def test_news_fetch_taps_pair_without_leaking_token(self, monkeypatch):
        import core.news_fetcher as nf

        class FakeResp:
            def raise_for_status(self):
                return None

            def json(self):
                return []

        class FakeClient:
            def __init__(self, timeout=None):
                ...

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, params=None):
                return FakeResp()

        monkeypatch.setattr(nf.httpx, "AsyncClient", FakeClient)
        monkeypatch.setattr(nf.FinnhubFetcher, "_key_ok",
                            lambda self: setattr(self, "api_key", "SECRET-FH") or True)

        async def main():
            with cl.correlation_scope("sch-news_refresh") as cid:
                n = await nf.FinnhubFetcher().fetch_news()
            return cid, n

        cid, n = asyncio.run(main())
        assert n == 0
        call, ret = [e for e in _drain() if e["peer"] == "finnhub"]
        assert call["payload"]["endpoint"] == "news"
        assert ret["payload"]["ok"] is True and ret["payload"]["n_items"] == 0
        assert call["corr_id"] == ret["corr_id"] == cid
        assert "SECRET-FH" not in json.dumps([call, ret])


# ── FRED / yahoo (caller-side; source pins — executor paths) ────────────────

class TestRegimeFetcherTaps:
    @staticmethod
    def _fake_httpx(monkeypatch, json_value):
        import core.regime_fetcher as rf

        class FakeResp:
            def raise_for_status(self):
                return None

            def json(self):
                return json_value

        class FakeClient:
            def __init__(self, timeout=None):
                ...

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, params=None):
                return FakeResp()

        monkeypatch.setattr(rf.httpx, "AsyncClient", FakeClient)
        return rf

    def test_fred_tap_pair_fires_under_scope(self, monkeypatch):
        rf = self._fake_httpx(monkeypatch, {"observations": [
            {"date": "2026-06-01", "value": "4.2"}]})
        monkeypatch.setattr(rf.config, "FRED_API_KEY", "SECRET-FRED")
        seen = []

        async def fake_upsert(name, rows, source=None):
            seen.append(len(rows))
            return len(rows)

        monkeypatch.setattr(rf.db, "upsert_regime_signals", fake_upsert)

        async def main():
            with cl.correlation_scope("sch-regime_refresh") as cid:
                await rf.RegimeFetcher().fetch_fred_series(
                    "DGS10", "us10y", "2026-05-01", "2026-06-01")
            return cid

        cid = asyncio.run(main())
        call, ret = [e for e in _drain() if e["peer"] == "fred"]
        assert call["payload"]["series"] == "DGS10"
        assert ret["payload"]["ok"] is True and ret["payload"]["n_observations"] == 1
        assert call["corr_id"] == ret["corr_id"] == cid
        assert "SECRET-FRED" not in json.dumps([call, ret])

    def test_fred_schema_drift_degrades_not_crashes(self, monkeypatch):
        # audit T2b-2: a truthy non-LIST observations value was graceful
        # pre-tap (the T163 isinstance guard logs + returns 0) — the tap's
        # arg construction must not crash before that guard runs. (A non-dict
        # BODY crashes inside T163's own error branch — pre-existing, out of
        # scope here.)
        rf = self._fake_httpx(monkeypatch, {"observations": 42})
        monkeypatch.setattr(rf.config, "FRED_API_KEY", "K")

        async def main():
            return await rf.RegimeFetcher().fetch_fred_series(
                "DGS10", "us10y", "2026-05-01", "2026-06-01")

        assert asyncio.run(main()) == 0  # T163 isinstance guard path, no raise
        (ret,) = [e for e in _drain() if e["category"] == "http_out_return"]
        assert ret["payload"]["ok"] is True
        assert ret["payload"]["n_observations"] is None

    def test_fred_and_yahoo_taps_present_at_source(self):
        import inspect

        from core.regime_fetcher import RegimeFetcher

        vix_src = inspect.getsource(RegimeFetcher.fetch_vix)
        fred_src = inspect.getsource(RegimeFetcher.fetch_fred_series)
        for src, peer in ((vix_src, "yahoo"), (fred_src, "fred")):
            assert "CAT_HTTP_OUT_CALL" in src
            assert "CAT_HTTP_OUT_RETURN" in src
            assert f'"{peer}"' in src
        # caller-side rule: the tap is OUTSIDE the executor callable
        assert "run_in_executor" in vix_src


# ── pubsub (spec §5.7) ───────────────────────────────────────────────────────

class TestPubsubTap:
    def test_inproc_publish_taps_market_gated(self, monkeypatch):
        from core.pubsub.in_process_bus import InProcessBus

        async def main(cid_prefix):
            with cl.correlation_scope(cid_prefix) as cid:
                await InProcessBus().publish("acct.1.position_update",
                                             {"symbol": "BTCUSDT"})
            return cid

        cid = asyncio.run(main("wsu"))
        (env,) = [e for e in _drain() if e["category"] == "pubsub_publish"]
        assert env["payload"] == {"channel": "acct.1.position_update",
                                  "backend": "inproc"}
        assert env["symbol"] == "BTCUSDT" and env["corr_id"] == cid

        monkeypatch.setattr(cl, "_profile", "linkage")
        asyncio.run(main("wsu"))
        assert [e for e in _drain() if e["category"] == "pubsub_publish"] == []
