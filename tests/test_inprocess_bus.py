"""Tests for InProcessBus backend + factory config."""
import asyncio

import pytest

from core.pubsub.in_process_bus import InProcessBus
from core.pubsub.bus import get_bus, reset_bus, RedisBus


@pytest.fixture(autouse=True)
def _reset():
    reset_bus()
    yield
    reset_bus()


class TestPublishSubscribe:
    @pytest.mark.asyncio
    async def test_exact_channel_roundtrip(self):
        bus = InProcessBus()
        received = []

        async def _consume():
            async for msg in bus.subscribe("test:channel"):
                received.append(msg)
                break

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.05)
        await bus.publish("test:channel", {"hello": "world"})
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert len(received) == 1
        assert received[0]["hello"] == "world"

    @pytest.mark.asyncio
    async def test_pattern_subscription(self):
        bus = InProcessBus()
        received = []

        async def _consume():
            async for msg in bus.subscribe("account:1:*"):
                received.append(msg)
                if len(received) >= 2:
                    break

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.05)
        await bus.publish("account:1:position_update", {"type": "pos"})
        await bus.publish("account:1:fill", {"type": "fill"})
        await bus.publish("account:2:fill", {"type": "other_account"})
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert len(received) == 2
        assert received[0]["type"] == "pos"
        assert received[1]["type"] == "fill"

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        bus = InProcessBus()
        r1, r2 = [], []

        async def _c1():
            async for msg in bus.subscribe("ch"):
                r1.append(msg)
                break

        async def _c2():
            async for msg in bus.subscribe("ch"):
                r2.append(msg)
                break

        t1 = asyncio.create_task(_c1())
        t2 = asyncio.create_task(_c2())
        await asyncio.sleep(0.05)
        await bus.publish("ch", {"x": 1})
        await asyncio.sleep(0.05)
        for t in [t1, t2]:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        assert len(r1) == 1
        assert len(r2) == 1


class TestSubscriberCleanup:
    @pytest.mark.asyncio
    async def test_generator_close_removes_queue(self):
        bus = InProcessBus()

        async def _consume():
            async for msg in bus.subscribe("cleanup:test"):
                break  # exit after first

        task = asyncio.create_task(_consume())
        await asyncio.sleep(0.05)
        assert "cleanup:test" in bus._subscribers
        await bus.publish("cleanup:test", {"done": True})
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0.05)
        # Pattern entry should be cleaned up
        assert "cleanup:test" not in bus._subscribers or len(bus._subscribers.get("cleanup:test", set())) == 0


class TestQueueFull:
    @pytest.mark.asyncio
    async def test_full_queue_drops_without_blocking(self):
        bus = InProcessBus()
        # Subscribe but don't consume — queue will fill
        q = asyncio.Queue(maxsize=5)
        async with bus._lock:
            bus._subscribers.setdefault("full:test", set()).add(q)

        # Publish more than maxsize — should not block or crash
        for i in range(20):
            await bus.publish("full:test", {"i": i})
        # Queue has some messages, didn't crash
        assert q.qsize() <= 5


class TestFactory:
    def test_default_is_inprocess(self, monkeypatch):
        monkeypatch.setattr("config.PUBSUB_BACKEND", "inprocess")
        bus = get_bus()
        assert isinstance(bus, InProcessBus)

    def test_redis_backend(self, monkeypatch):
        monkeypatch.setattr("config.PUBSUB_BACKEND", "redis")
        bus = get_bus()
        assert isinstance(bus, RedisBus)

    def test_invalid_backend_falls_back(self, monkeypatch, caplog):
        monkeypatch.setattr("config.PUBSUB_BACKEND", "nonsense")
        import logging
        with caplog.at_level(logging.WARNING, logger="pubsub"):
            bus = get_bus()
        assert isinstance(bus, InProcessBus)
        assert "Unknown PUBSUB_BACKEND" in caplog.text
