"""CL.T1a — entry-point corr_id minting tests.

Covers: the HTTP middleware (http_request/http_response pair, redaction,
/static skip, SSE close-tap) and the blanket per-iteration loop scopes
(tick() unit semantics, a behavioral two-iteration probe, and a
source-scan completeness anchor over every spawned loop).

The WS frame taps (wsu/wsm/wsp/wsn) and WS-lifecycle taps are CL.T1b and
tested there.
"""

import asyncio
import inspect
import json
import time

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
def _pin_emit_side(monkeypatch):
    _drain()
    monkeypatch.setattr(cl, "_enabled", True)
    monkeypatch.setattr(cl, "_profile", "full")
    monkeypatch.setattr(cl, "_emit_error_logged", set())
    monkeypatch.setattr(cl, "_dropping", False)
    monkeypatch.setattr(cl, "_dropped", 0)
    yield
    _drain()


# ── tick(): the loop-scope primitive ─────────────────────────────────────────

class TestTick:
    def test_tick_sets_fresh_prefixed_ids(self):
        a = cl.tick("sch-funding_refresh")
        assert cl.current_corr_id() == a
        b = cl.tick("sch-funding_refresh")
        assert cl.current_corr_id() == b
        assert a != b
        assert a.startswith("sch-funding_refresh-") and b.startswith("sch-funding_refresh-")


# ── HTTP middleware ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    """The REAL middleware function (`main._corr_http_middleware`) mounted
    on a tiny purpose-built app — deliberately NOT `TestClient(main.app)`:
    the engine app is a singleton that tolerates exactly ONE in-process
    lifespan (test_routes.py owns it; a second deadlocks startup — the
    documented LOW-023 double-TestClient hang, see
    test_task101_sql_injection_defense.py's skip). Middleware behavior is
    app-independent, and no lifespan also means no writer thread — the
    envelopes stay in the module queue for assertion."""
    import main
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.middleware("http")(main._corr_http_middleware)

    @app.get("/")
    def root():
        return {"ok": True}

    @app.get("/whoami")
    def whoami():
        # the handler runs in a task anyio spawns INSIDE the middleware
        # scope — this pins the context-copy link T2b's REST taps rely on
        return {"corr": cl.current_corr_id()}

    @app.get("/boom")
    def boom():
        raise RuntimeError("kapow")

    return TestClient(app)  # no context manager → no lifespan


class TestHttpMiddleware:
    def test_request_response_pair_share_one_http_corr_id(self, client):
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 200
        envs = [e for e in _drain() if e["component"] == "http"]
        assert [e["category"] for e in envs] == ["http_request", "http_response"]
        req, resp = envs
        assert req["corr_id"] == resp["corr_id"]
        assert req["corr_id"].startswith("http-")
        assert req["direction"] == "in" and resp["direction"] == "out"
        assert req["payload"]["method"] == "GET" and req["payload"]["path"] == "/"
        assert resp["payload"]["status"] == r.status_code
        assert resp["payload"]["duration_ms"] >= 0

    def test_two_requests_get_distinct_chains(self, client):
        client.get("/", follow_redirects=False)
        client.get("/", follow_redirects=False)
        corrs = {e["corr_id"] for e in _drain() if e["component"] == "http"}
        assert len(corrs) == 2

    def test_secret_query_params_redacted(self, client):
        client.get("/", params={"api_key": "SECRET-123", "x": "1"}, follow_redirects=False)
        (req,) = [e for e in _drain() if e["category"] == "http_request"]
        assert req["payload"]["query"]["api_key"] == "[REDACTED]"
        assert req["payload"]["query"]["x"] == "1"
        assert "SECRET-123" not in json.dumps(req)

    def test_404_still_pairs(self, client):
        r = client.get("/definitely-not-a-route-xyz", follow_redirects=False)
        assert r.status_code == 404
        envs = [e for e in _drain() if e["component"] == "http"]
        assert [e["category"] for e in envs] == ["http_request", "http_response"]
        assert envs[1]["payload"]["status"] == 404

    def test_static_paths_skipped_entirely(self, client):
        client.get("/static/nope.css", follow_redirects=False)
        assert [e for e in _drain() if e["component"] == "http"] == []

    def test_handler_inherits_the_request_corr_id(self, client):
        # audit finding 3: the one structurally fragile link — anyio's
        # start_soon copies context at call time inside the scope
        r = client.get("/whoami", follow_redirects=False)
        envs = [e for e in _drain() if e["component"] == "http"]
        assert r.json()["corr"] == envs[0]["corr_id"]
        assert r.json()["corr"].startswith("http-")

    def test_unhandled_exception_emits_500_envelope_then_reraises(self, client):
        # audit finding 2: the except branch (genuinely unhandled only)
        with pytest.raises(RuntimeError, match="kapow"):
            client.get("/boom", follow_redirects=False)
        envs = [e for e in _drain() if e["component"] == "http"]
        assert [e["category"] for e in envs] == ["http_request", "http_response"]
        assert envs[1]["payload"]["status"] == 500
        assert envs[1]["payload"]["error_type"] == "RuntimeError"
        assert envs[0]["corr_id"] == envs[1]["corr_id"]


class TestSseCloseTap:
    def test_emits_single_response_at_stream_close_with_rebound_corr(self):
        from main import _sse_close_tap

        async def gen():
            yield b"data: 1\n\n"
            yield b"data: 2\n\n"

        async def run():
            chunks = []
            async for c in _sse_close_tap(gen(), "http-deadbeef", "/stream/x",
                                          200, time.perf_counter()):
                chunks.append(c)
            return chunks

        chunks = asyncio.run(run())
        assert len(chunks) == 2
        (env,) = [e for e in _drain() if e["category"] == "http_response"]
        assert env["payload"]["streaming"] is True
        assert env["payload"]["status"] == 200
        assert env["corr_id"] == "http-deadbeef"

    def test_emits_even_when_consumer_disconnects_midstream(self):
        from main import _sse_close_tap

        async def gen():
            while True:
                yield b"data: tick\n\n"

        async def run():
            agen = _sse_close_tap(gen(), "http-cafebabe", "/stream/y",
                                  200, time.perf_counter())
            await agen.__anext__()      # one chunk
            await agen.aclose()         # client gone

        asyncio.run(run())
        (env,) = [e for e in _drain() if e["category"] == "http_response"]
        assert env["corr_id"] == "http-cafebabe" and env["payload"]["streaming"] is True


# ── loop tick scopes ─────────────────────────────────────────────────────────

class TestLoopTickScopes:
    def test_reaper_loop_mints_fresh_corr_per_iteration(self, monkeypatch):
        import core.auth_state as auth_state
        import core.schedulers as sched

        seen = []

        async def fake_reap(db):
            seen.append(cl.current_corr_id())
            if len(seen) >= 2:
                raise SystemExit  # BaseException — escapes the loop's except Exception
            return 0

        monkeypatch.setattr(auth_state, "reap_idle_sessions", fake_reap)
        with pytest.raises(SystemExit):
            asyncio.run(sched._operator_session_reaper_loop(interval_s=0))
        assert len(seen) == 2
        assert all(c.startswith("sch-operator_session_reaper-") for c in seen)
        assert seen[0] != seen[1]  # fresh chain per tick

    def test_every_spawned_loop_body_has_a_tick_scope(self):
        """Completeness anchor (spec §3.2 blanket rule): every spawned root
        loop body mints a per-iteration scope. Enumerated from
        start_background_tasks' own source so a future _spawn() addition
        without a tick fails THIS test (forward discipline, spec §5.8)."""
        import re
        import core.monitoring as monitoring
        import core.schedulers as sched
        import core.webhook_dispatcher as webhook_dispatcher
        import core.ws_manager as ws_manager

        covered = {
            "startup_fetch": sched._startup_fetch,                  # boot
            "bod_scheduler": sched._bod_scheduler,
            "auto_export": sched._auto_export_scheduler,
            "account_refresh": sched._account_refresh_loop,
            "ping": sched._ping_loop,
            "history_refresh": sched._history_refresh_loop,
            "regime_refresh": sched._regime_refresh_loop,
            "news_refresh": sched._news_refresh_loop,
            "monitoring": monitoring.MonitoringService.run,
            "order_staleness": sched._order_staleness_loop,
            "algo_order_sync": sched._algo_order_sync_loop,
            "calc_expiry": sched._calc_expiry_loop,
            "funding_refresh": sched._funding_refresh_loop,
            "operator_session_reaper": sched._operator_session_reaper_loop,
            # spawned inside _startup_fetch:
            "webhook_dispatcher": webhook_dispatcher.WebhookDispatcher.run,
            "reconciler_closed_positions_periodic": sched._reconcile_closed_positions_periodic,
        }
        exempt = {
            # one-shot spawned from _startup_fetch's body: create_task copies
            # context, so it inherits the boot chain — no own tick needed.
            "reconciler_backfill",
            # the bus consumer re-binds the PUBLISHER's corr_id per event
            # (CL.T2a) — a loop tick here would fight the re-bind.
            "event_bus",
            # per-FRAME minting (wsn-*) lands with the WS frame taps (CL.T1b).
            "bwe_ws",
        }
        for name, fn in covered.items():
            src = inspect.getsource(fn)
            assert "correlation_log.tick(" in src, f"loop {name!r} lost its tick scope"

        # ws_manager-resident loops (not in start_background_tasks)
        for fn in (ws_manager._keepalive_loop, ws_manager._fallback_loop):
            assert "correlation_log.tick(" in inspect.getsource(fn)

        # completeness: every _spawn(...) name in start_background_tasks AND
        # inside _startup_fetch (audit finding 1: the next spawn is most
        # likely added there) is either covered or deliberately exempt
        spawn_src = (inspect.getsource(sched.start_background_tasks)
                     + inspect.getsource(sched._startup_fetch))
        spawned = set(re.findall(r'name="([^"]+)"', spawn_src))
        assert spawned, "no spawns found — scan broke"
        assert "reconciler_backfill" in spawned, "scan lost _startup_fetch's spawns"
        unaccounted = spawned - set(covered) - exempt
        assert not unaccounted, f"spawned loops without tick coverage: {unaccounted}"

    def test_startup_fetch_uses_boot_prefix(self):
        import core.schedulers as sched
        assert 'tick("boot")' in inspect.getsource(sched._startup_fetch)
