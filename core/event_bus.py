"""
In-process asyncio event bus (Redis dependency dropped in v2.1).

Keeps the same pub/sub interface as the old redis_bus so all call sites
are unchanged except the import path and singleton name.

Channels:
    risk:account_updated      – WS ACCOUNT_UPDATE received
    risk:positions_refreshed  – positions refreshed (after fill or periodically)
    risk:risk_calculated      – risk calculator run completed
    risk:params_updated       – user updated risk parameters
    risk:trade_closed         – position fully closed

Usage:
    from core.event_bus import event_bus

    # In lifespan startup:
    await event_bus.connect()
    event_bus.subscribe("risk:account_updated", my_handler)
    asyncio.create_task(event_bus.run())

    # In lifespan teardown:
    await event_bus.close()

    # To publish an event:
    await event_bus.publish("risk:account_updated", {"event": "ACCOUNT_UPDATE", "ts": "..."})
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Dict, List

log = logging.getLogger("event_bus")

# Canonical channel names (identical to old redis_bus — no callsite changes needed)
CH_ACCOUNT_UPDATED     = "risk:account_updated"
CH_POSITIONS_REFRESHED = "risk:positions_refreshed"
CH_RISK_CALCULATED     = "risk:risk_calculated"
CH_PARAMS_UPDATED      = "risk:params_updated"
CH_TRADE_CLOSED        = "risk:trade_closed"


def ch_account(account_id: int, suffix: str) -> str:
    """Return a scoped channel name for a specific account.
    e.g. ch_account(2, "account_updated") → "risk:2:account_updated"
    """
    return f"risk:{account_id}:{suffix}"


Handler = Callable[[Dict[str, Any]], Awaitable[None]]


class EventBus:
    """
    In-process pub/sub event bus backed by asyncio.Queue.

    publish() enqueues (channel, payload); run() drains the queue
    and dispatches to registered handlers. No external process needed.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()
        self._handlers: Dict[str, List[Handler]] = {}
        self.available: bool = True

    async def connect(self) -> None:
        """No-op — kept for interface compatibility with old redis_bus."""
        log.info("EventBus: in-process mode active")

    def subscribe(self, channel: str, handler: Handler) -> None:
        """Register an async handler for a channel."""
        self._handlers.setdefault(channel, [])
        if handler not in self._handlers[channel]:
            self._handlers[channel].append(handler)

    def unsubscribe(self, channel: str, handler: Handler) -> None:
        """Remove a handler registration for a channel."""
        handlers = self._handlers.get(channel, [])
        try:
            handlers.remove(handler)
        except ValueError:
            pass

    async def publish(self, channel: str, payload: Dict[str, Any]) -> None:
        """Enqueue an event for dispatch. Never raises."""
        await self._queue.put((channel, payload))

    async def _dispatch(self, channel: str, payload: Dict[str, Any]) -> None:
        for handler in self._handlers.get(channel, []):
            try:
                await handler(payload)
            except Exception as exc:
                log.error("Handler error on channel %r: %s", channel, exc, exc_info=True)

    async def run(self) -> None:
        """Long-running coroutine: drain the queue and dispatch events."""
        while True:
            try:
                channel, payload = await self._queue.get()
                await self._dispatch(channel, payload)
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("EventBus run loop error: %s", exc, exc_info=True)

    async def close(self) -> None:
        """No-op — kept for interface compatibility with old redis_bus."""


# Module-level singleton
event_bus = EventBus()
