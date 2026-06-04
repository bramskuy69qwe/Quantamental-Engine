"""Phase 7.3 — position-closed webhook dispatcher tests.

Covers: config parsing (webhook_url + STRICT-bool webhook_enabled), the
enqueue/subscribe wiring, the worker dispatch (enabled-gating, retry-then-
succeed, dead-letter-on-exhaustion, json_safe coercion), and a real-event_bus
composition test (publish position:closed → handler enqueues → worker POSTs).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.account_config import _parse_config_json, AccountConfig
from core.webhook_dispatcher import WebhookDispatcher


def _async_return(value):
    async def _f(*a, **k):
        return value
    return _f


def _cfg(*, enabled=True, url="https://hook.test/x"):
    return AccountConfig(webhook_enabled=enabled, webhook_url=url)


# ── config parsing ───────────────────────────────────────────────────────────


class TestWebhookConfig:
    def test_defaults_off(self):
        c = _parse_config_json(None)
        assert c.webhook_url is None
        assert c.webhook_enabled is False

    def test_url_and_enabled(self):
        c = _parse_config_json(json.dumps({
            "webhook_url": "https://example.test/hook",
            "feature_flags": {"webhook_enabled": True},
        }))
        assert c.webhook_url == "https://example.test/hook"
        assert c.webhook_enabled is True

    def test_blank_url_is_none(self):
        assert _parse_config_json(json.dumps({"webhook_url": "   "})).webhook_url is None
        assert _parse_config_json(json.dumps({"webhook_url": 123})).webhook_url is None

    def test_enabled_strict_bool(self):
        # a string "true" / a number must NOT enable (mirrors snapshot_wins_drift —
        # bool("false") is True, which must not silently enable outbound POSTs).
        assert _parse_config_json(
            json.dumps({"feature_flags": {"webhook_enabled": "true"}})).webhook_enabled is False
        assert _parse_config_json(
            json.dumps({"feature_flags": {"webhook_enabled": 1}})).webhook_enabled is False
        assert _parse_config_json(
            json.dumps({"feature_flags": {"webhook_enabled": False}})).webhook_enabled is False

    def test_feature_flags_non_dict_safe(self):
        # feature_flags not a dict (string/list) → treated as {} → enabled stays off.
        assert _parse_config_json(json.dumps({"feature_flags": "nope"})).webhook_enabled is False
        assert _parse_config_json(json.dumps({"feature_flags": [1, 2]})).webhook_enabled is False


# ── wiring ───────────────────────────────────────────────────────────────────


class TestWiring:
    @pytest.mark.asyncio
    async def test_make_handler_enqueues(self):
        d = WebhookDispatcher(db=None)
        await d.make_handler(3)({"position_id": "P"})
        account_id, payload = d._queue.get_nowait()
        assert account_id == 3
        assert payload == {"position_id": "P"}

    def test_subscribe_all_topics(self):
        d = WebhookDispatcher(db=None)
        calls = []

        class _Bus:
            def subscribe(self, topic, handler):
                calls.append(topic)

        d.subscribe_all(_Bus(), [1, 2, 7])
        assert calls == ["engine:account:1:position:closed",
                         "engine:account:2:position:closed",
                         "engine:account:7:position:closed"]

    @pytest.mark.asyncio
    async def test_start_webhook_dispatcher_subscribes_loaded_accounts(self, monkeypatch):
        # The extracted startup helper: enumerate accounts via the registry, DROP
        # None / missing ids, subscribe each. Pins the integration seam that
        # _startup_fetch wires (previously untested).
        from core.webhook_dispatcher import start_webhook_dispatcher

        async def _fake_list():
            return [{"id": 1}, {"id": 4}, {"id": None}, {"name": "no-id"}]
        monkeypatch.setattr(
            "core.account_registry.account_registry.list_accounts", _fake_list)
        topics = []

        class _Bus:
            def subscribe(self, topic, handler):
                topics.append(topic)

        await start_webhook_dispatcher(_Bus(), db=None)
        assert topics == ["engine:account:1:position:closed",
                          "engine:account:4:position:closed"]   # None + missing-id dropped


# ── dispatch ─────────────────────────────────────────────────────────────────


class TestDispatch:
    @pytest.mark.asyncio
    async def test_posts_when_enabled(self, monkeypatch):
        monkeypatch.setattr("core.webhook_dispatcher.read_account_config_async",
                            _async_return(_cfg()))
        d = WebhookDispatcher(db=None, initial_backoff_s=0)
        posts = []

        async def _post(url, body):
            posts.append((url, body))
        d._post = _post

        await d._dispatch_one(1, {"position_id": "POS1", "net_pnl": 5.0})
        assert len(posts) == 1
        url, body = posts[0]
        assert url == "https://hook.test/x"
        assert body == {"event": "position_closed",
                        "payload": {"position_id": "POS1", "net_pnl": 5.0}}

    @pytest.mark.asyncio
    async def test_no_post_when_disabled(self, monkeypatch):
        monkeypatch.setattr("core.webhook_dispatcher.read_account_config_async",
                            _async_return(_cfg(enabled=False)))
        d = WebhookDispatcher(db=None, initial_backoff_s=0)
        posts = []
        d._post = lambda *a: posts.append(1)  # would record if (wrongly) called
        await d._dispatch_one(1, {"position_id": "POS1"})
        assert posts == []

    @pytest.mark.asyncio
    async def test_no_post_when_no_url(self, monkeypatch):
        monkeypatch.setattr("core.webhook_dispatcher.read_account_config_async",
                            _async_return(_cfg(url=None)))
        d = WebhookDispatcher(db=None, initial_backoff_s=0)
        posts = []
        d._post = lambda *a: posts.append(1)
        await d._dispatch_one(1, {"position_id": "POS1"})
        assert posts == []

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self, monkeypatch):
        monkeypatch.setattr("core.webhook_dispatcher.read_account_config_async",
                            _async_return(_cfg()))
        d = WebhookDispatcher(db=None, initial_backoff_s=0, max_attempts=5)
        n = {"c": 0}

        async def _flaky(url, body):
            n["c"] += 1
            if n["c"] < 3:
                raise RuntimeError("boom")
        d._post = _flaky
        dead = []

        async def _dl(*a):
            dead.append(a)
        d._dead_letter = _dl

        await d._dispatch_one(1, {"position_id": "POS1"})
        assert n["c"] == 3      # failed twice, delivered on the 3rd
        assert dead == []       # NOT dead-lettered

    @pytest.mark.asyncio
    async def test_dead_letters_on_exhaustion(self, monkeypatch):
        monkeypatch.setattr("core.webhook_dispatcher.read_account_config_async",
                            _async_return(_cfg()))
        d = WebhookDispatcher(db=None, initial_backoff_s=0, max_attempts=3)
        n = {"c": 0}

        async def _always_fail(url, body):
            n["c"] += 1
            raise RuntimeError("down")
        d._post = _always_fail
        dead = []

        async def _dl(account_id, payload, error):
            dead.append((account_id, payload, str(error)))
        d._dead_letter = _dl

        await d._dispatch_one(7, {"position_id": "POSX"})
        assert n["c"] == 3      # all attempts used
        assert len(dead) == 1
        assert dead[0][0] == 7
        assert dead[0][1]["position_id"] == "POSX"
        assert "down" in dead[0][2]

    @pytest.mark.asyncio
    async def test_json_safe_coerces_non_finite(self, monkeypatch):
        monkeypatch.setattr("core.webhook_dispatcher.read_account_config_async",
                            _async_return(_cfg()))
        d = WebhookDispatcher(db=None, initial_backoff_s=0)
        bodies = []

        async def _post(url, body):
            bodies.append(body)
        d._post = _post

        await d._dispatch_one(1, {"position_id": "P", "net_pnl": float("inf"),
                                  "deltas": {"realized_r": float("nan")}})
        p = bodies[0]["payload"]
        assert p["net_pnl"] is None               # inf → null (no Infinity on the wire)
        assert p["deltas"]["realized_r"] is None  # nan → null

    @pytest.mark.asyncio
    async def test_dead_letter_writes_engine_event(self, monkeypatch):
        # The REAL _dead_letter writes a webhook_dispatch_failed engine_event via
        # log_event (dispatched to_thread). The conftest guard redirects the
        # write off the live per-account DB.
        captured = []

        def _fake_log_event(account_id, event_type, payload, source, **k):
            captured.append((account_id, event_type, source, payload.get("position_id")))
            return 1
        monkeypatch.setattr("core.event_log.log_event", _fake_log_event)

        d = WebhookDispatcher(db=None, max_attempts=2)
        await d._dead_letter(5, {"position_id": "PZ"}, RuntimeError("x"))
        assert captured == [(5, "webhook_dispatch_failed", "webhook_dispatcher", "PZ")]

    @pytest.mark.asyncio
    async def test_dead_letter_payload_is_json_safe(self, monkeypatch):
        # The stored audit payload must NOT contain Infinity/NaN tokens (invalid
        # JSON for a strict reader of engine_events.payload_json).
        stored = {}

        def _fake_log_event(account_id, event_type, payload, source, **k):
            stored.update(payload)
            return 1
        monkeypatch.setattr("core.event_log.log_event", _fake_log_event)

        d = WebhookDispatcher(db=None, max_attempts=1)
        await d._dead_letter(1, {"position_id": "P", "net_pnl": float("inf")},
                             RuntimeError("x"))
        assert stored["payload"]["net_pnl"] is None   # coerced in the stored record


class TestPostContract:
    @pytest.mark.asyncio
    async def test_post_raises_on_non_2xx(self, monkeypatch):
        # The retry loop depends on _post RAISING on non-2xx (resp.raise_for_status).
        # All other tests substitute _post, so pin the real httpx path once with a
        # fake AsyncClient: 200 → no raise; 5xx → raise.
        import httpx

        class _Resp:
            def __init__(self, code):
                self.status_code = code

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(f"HTTP {self.status_code}")

        class _Client:
            code = 200

            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, json=None):
                return _Resp(_Client.code)

        monkeypatch.setattr(httpx, "AsyncClient", _Client)
        d = WebhookDispatcher(db=None)

        _Client.code = 200
        await d._post("http://x", {"a": 1})          # 2xx must NOT raise

        _Client.code = 500
        with pytest.raises(RuntimeError):
            await d._post("http://x", {"a": 1})      # non-2xx must raise (drives retry)


# ── composition over the real event_bus ──────────────────────────────────────


class TestEventBusComposition:
    @pytest.mark.asyncio
    async def test_publish_close_reaches_post(self, monkeypatch):
        from core.event_bus import EventBus, DOMAIN_POSITION
        monkeypatch.setattr("core.webhook_dispatcher.read_account_config_async",
                            _async_return(_cfg()))
        bus = EventBus()
        d = WebhookDispatcher(db=None, initial_backoff_s=0)
        posts = []

        async def _post(url, body):
            posts.append(body)
        d._post = _post

        d.subscribe_all(bus, [2])
        bus_worker = asyncio.create_task(bus.run())
        wh_worker = asyncio.create_task(d.run())
        try:
            await bus.publish_engine(2, DOMAIN_POSITION, "closed", {"position_id": "PE2"})
            await asyncio.wait_for(bus._queue.join(), timeout=2.0)   # bus → handler enqueued
            await asyncio.wait_for(d._queue.join(), timeout=2.0)     # worker → posted
        finally:
            for t in (bus_worker, wh_worker):
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass
        assert len(posts) == 1
        assert posts[0]["payload"]["position_id"] == "PE2"

    @pytest.mark.asyncio
    async def test_multi_account_routing_no_late_binding(self):
        # Subscribe TWO accounts; publish a close on EACH topic; assert each
        # handler enqueues ITS OWN account_id. A closure late-binding bug (all
        # handlers closing over the last loop var) would make both enqueue
        # account 5 — this is the regression guard for that. Also proves
        # account-scoping (each event routes only to its own topic's handler).
        from core.event_bus import EventBus, DOMAIN_POSITION
        bus = EventBus()
        d = WebhookDispatcher(db=None)
        d.subscribe_all(bus, [2, 5])
        bus_worker = asyncio.create_task(bus.run())
        try:
            await bus.publish_engine(2, DOMAIN_POSITION, "closed", {"position_id": "P2"})
            await bus.publish_engine(5, DOMAIN_POSITION, "closed", {"position_id": "P5"})
            await asyncio.wait_for(bus._queue.join(), timeout=2.0)
        finally:
            bus_worker.cancel()
            try:
                await bus_worker
            except asyncio.CancelledError:
                pass
        drained = []
        while not d._queue.empty():
            aid, payload = d._queue.get_nowait()
            drained.append((aid, payload["position_id"]))
        # each (account_id, payload) pairs its OWN account: {(2,P2),(5,P5)} — a
        # late-binding bug would give {(5,P2),(5,P5)}.
        assert sorted(drained) == [(2, "P2"), (5, "P5")]
