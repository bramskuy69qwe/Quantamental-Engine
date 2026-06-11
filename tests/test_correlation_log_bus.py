"""CL.T2a — event_bus carries + re-binds the publisher's corr_id (spec §6.2).

The bus consumer is a separate task contextvars cannot cross — queue
hand-off #1. The queued item became (channel, payload, corr_id); run()
re-binds the publisher's chain around each event's dispatch (reset in
finally), and the INSTRUMENTED dispatch emits bus_publish (at enqueue,
publisher context) + one bus_deliver per handler invocation.

Tests use FRESH EventBus instances inside asyncio.run (never the
singleton's queue — an asyncio.Queue binds to the first loop that uses
it; the singleton belongs to the suite's other consumers).
"""

import asyncio
import contextlib
import json

import pytest

import core.correlation_log as cl
from core.event_bus import EventBus


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


async def _pump(bus):
    """Run the bus until everything queued so far is dispatched."""
    task = asyncio.create_task(bus.run(), name="bus")
    await bus._queue.join()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


class TestCarryAndRebind:
    def test_consumer_task_rebinds_publishers_corr(self):
        async def main():
            bus = EventBus()
            seen = []

            async def handler(payload):
                seen.append(cl.current_corr_id())

            bus.subscribe("t:chan", handler)
            with cl.correlation_scope("wsu") as cid:
                await bus.publish("t:chan", {"x": 1})
            assert cl.current_corr_id() == ""  # publisher scope closed
            await _pump(bus)
            return cid, seen

        cid, seen = asyncio.run(main())
        assert seen == [cid]  # the hand-off: consumer saw the PUBLISHER's chain

    def test_handler_spawned_child_task_inherits_publishers_corr(self):
        async def main():
            bus = EventBus()
            child_corr = []

            async def child():
                child_corr.append(cl.current_corr_id())

            async def handler(payload):
                await asyncio.create_task(child(), name="h-child")

            bus.subscribe("t:chan", handler)
            with cl.correlation_scope("http") as cid:
                await bus.publish("t:chan", {})
            await _pump(bus)
            return cid, child_corr

        cid, child_corr = asyncio.run(main())
        assert child_corr == [cid]

    def test_rebind_resets_between_events(self):
        # event 1 published under a chain; event 2 published with NO scope —
        # a leaked binding from event 1 would stamp event 2's delivery
        async def main():
            bus = EventBus()
            seen = []

            async def boom(payload):
                seen.append(("boom", cl.current_corr_id()))
                raise RuntimeError("handler error")

            async def ok(payload):
                seen.append(("ok", cl.current_corr_id()))

            bus.subscribe("t:a", boom)
            bus.subscribe("t:b", ok)
            with cl.correlation_scope("wsu") as cid:
                await bus.publish("t:a", {})       # handler RAISES under cid
            await bus.publish("t:b", {})            # published scope-less
            await _pump(bus)
            return cid, seen

        cid, seen = asyncio.run(main())
        assert seen == [("boom", cid), ("ok", "")]  # finally reset held

    def test_publish_engine_nowait_carries_corr(self):
        async def main():
            bus = EventBus()
            seen = []

            async def handler(payload):
                seen.append(cl.current_corr_id())

            bus.subscribe("engine:account:1:calc:linked", handler)
            with cl.correlation_scope("wsu") as cid:
                bus.publish_engine_nowait(1, "calc", "linked", {"calc_id": "C1"})
            await _pump(bus)
            return cid, seen

        cid, seen = asyncio.run(main())
        assert seen == [cid]

    def test_publish_outside_any_scope_carries_empty(self):
        async def main():
            bus = EventBus()
            seen = []

            async def handler(payload):
                seen.append(cl.current_corr_id())

            bus.subscribe("t:chan", handler)
            await bus.publish("t:chan", {})
            await _pump(bus)
            return seen

        assert asyncio.run(main()) == [""]


class TestBusTaps:
    def test_publish_emits_bus_publish_with_summary_and_subscriber_count(self):
        async def main():
            bus = EventBus()

            async def h(payload): ...
            async def g(channel, payload): ...

            bus.subscribe("t:chan", h)
            bus.subscribe_all(g)
            with cl.correlation_scope("wsu") as cid:
                await bus.publish("t:chan", {"calc_id": "C1", "symbol": "BTCUSDT",
                                             "qty": 5, "noise": "x"})
            return cid

        cid = asyncio.run(main())
        (env,) = [e for e in _drain() if e["category"] == "bus_publish"]
        assert env["corr_id"] == cid
        assert env["component"] == "event_bus"
        assert env["symbol"] == "BTCUSDT"
        assert env["payload"]["channel"] == "t:chan"
        assert env["payload"]["n_subscribers"] == 2
        s = env["payload"]["summary"]
        assert s["calc_id"] == "C1" and s["symbol"] == "BTCUSDT" and s["n_keys"] == 4
        assert "noise" not in s  # summary carries pivot ids, not the payload

    def test_dispatch_emits_one_bus_deliver_per_handler_with_outcome(self):
        async def main():
            bus = EventBus()

            async def good(payload): ...
            async def bad(payload):
                raise ValueError("nope")
            async def global_h(channel, payload): ...

            bus.subscribe("t:chan", good)
            bus.subscribe("t:chan", bad)
            bus.subscribe_all(global_h)
            with cl.correlation_scope("wsu") as cid:
                await bus.publish("t:chan", {})
            await _pump(bus)
            return cid

        cid = asyncio.run(main())
        delivers = [e for e in _drain() if e["category"] == "bus_deliver"]
        assert len(delivers) == 3  # 2 channel handlers + 1 global
        by_handler = {e["payload"]["handler"]: e for e in delivers}
        good_env = next(v for k, v in by_handler.items() if "good" in k)
        bad_env = next(v for k, v in by_handler.items() if "bad" in k)
        glob_env = next(v for k, v in by_handler.items() if "global_h" in k)
        assert good_env["payload"]["ok"] is True
        assert "error_type" not in good_env["payload"]
        assert bad_env["payload"]["ok"] is False
        assert bad_env["payload"]["error_type"] == "ValueError"
        assert glob_env["payload"]["ok"] is True
        # every delivery rides the PUBLISHER's chain (the §6.2 hand-off)
        assert {e["corr_id"] for e in delivers} == {cid}
        assert all(e["payload"]["duration_ms"] >= 0 for e in delivers)

    def test_structural_coverage_any_publish_taps_publish_and_deliver(self):
        # spec §5.2: coverage is structural — ANY topic produces the pair,
        # not a pinned topic list
        async def main():
            bus = EventBus()

            async def h(payload): ...

            for ch in ("risk:position_closed",
                       "engine:account:7:position:closed",
                       "t:arbitrary:topic"):
                bus.subscribe(ch, h)
                await bus.publish(ch, {"position_id": "P1"})
            await _pump(bus)

        asyncio.run(main())
        envs = _drain()
        assert sum(e["category"] == "bus_publish" for e in envs) == 3
        assert sum(e["category"] == "bus_deliver" for e in envs) == 3

    def test_zero_subscriber_publish_taps_publish_only(self):
        async def main():
            bus = EventBus()
            await bus.publish("t:nobody-listens", {"calc_id": "C1"})
            await _pump(bus)

        asyncio.run(main())
        envs = _drain()
        (pub,) = [e for e in envs if e["category"] == "bus_publish"]
        assert pub["payload"]["n_subscribers"] == 0
        assert [e for e in envs if e["category"] == "bus_deliver"] == []

    def test_off_profile_silences_taps_but_transport_still_delivers(self, monkeypatch):
        monkeypatch.setattr(cl, "_profile", "off")

        async def main():
            bus = EventBus()
            got = []

            async def h(payload):
                got.append(payload)

            bus.subscribe("t:chan", h)
            await bus.publish("t:chan", {"x": 1})
            await _pump(bus)
            return got

        got = asyncio.run(main())
        assert got == [{"x": 1}]   # the bus still works
        assert _drain() == []       # the taps are gated, not the transport

    def test_non_dict_payload_never_raises(self):
        # contract-violating payload: publish's never-raises contract holds
        # and the tap degrades (n_keys=-1) instead of breaking the publisher
        async def main():
            bus = EventBus()
            got = []

            async def h(payload):
                got.append(payload)

            bus.subscribe("t:chan", h)
            await bus.publish("t:chan", None)  # type: ignore[arg-type]
            await _pump(bus)
            return got

        got = asyncio.run(main())
        assert got == [None]
        (pub,) = [e for e in _drain() if e["category"] == "bus_publish"]
        assert pub["payload"]["summary"] == {"n_keys": -1}

    def test_handler_payload_unchanged_regression(self):
        # subscribers see the exact payload object — the 3-tuple change is
        # invisible to them
        async def main():
            bus = EventBus()
            got = []

            async def h(payload):
                got.append(payload)

            bus.subscribe("t:chan", h)
            sent = {"a": 1, "nested": {"b": 2}}
            await bus.publish("t:chan", sent)
            await _pump(bus)
            return sent, got

        sent, got = asyncio.run(main())
        assert got == [sent] and got[0] is sent
