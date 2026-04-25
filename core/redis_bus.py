"""
Redis-backed event bus (redis.asyncio pub/sub).

Replaces a custom asyncio Queue + dispatcher. When Redis is unavailable the bus
falls back to direct in-process handler dispatch so the system is functionally
identical with or without Redis.

Channels:
    risk:account_updated      – WS ACCOUNT_UPDATE received
    risk:positions_refreshed  – positions refreshed (after fill or periodically)
    risk:risk_calculated      – risk calculator run completed
    risk:params_updated       – user updated risk parameters

Usage:
    from core.redis_bus import redis_bus

    # In lifespan startup:
    await redis_bus.connect()
    redis_bus.subscribe("risk:account_updated", my_handler)
    asyncio.create_task(redis_bus.run())

    # In lifespan teardown:
    await redis_bus.close()

    # To publish an event:
    await redis_bus.publish("risk:account_updated", {"event": "ACCOUNT_UPDATE", "ts": "..."})
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

import config

log = logging.getLogger("redis_bus")

# Canonical channel names
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


class RedisBus:
    """
    Thin asyncio pub/sub wrapper around redis.asyncio.

    Two separate Redis connections are used:
      _pub_client  – for PUBLISH commands
      _sub_client  – for SUBSCRIBE / message loop (redis-py requirement)

    Graceful degradation: if Redis is unreachable at connect() time, or
    disconnects later, publish() dispatches directly to registered handlers
    so no events are lost.
    """

    def __init__(self) -> None:
        self._pub_client = None
        self._sub_client = None
        self._pubsub = None
        self._handlers: Dict[str, List[Handler]] = {}
        self.available: bool = False

    async def connect(self) -> None:
        """
        Attempt connection to Redis. Sets self.available = True on success.
        Logs WARNING on failure — never raises (graceful degradation).
        """
        try:
            import redis.asyncio as aioredis
            self._pub_client = aioredis.from_url(
                config.REDIS_URL, decode_responses=True, socket_connect_timeout=2
            )
            self._sub_client = aioredis.from_url(
                config.REDIS_URL, decode_responses=True, socket_connect_timeout=2
            )
            await self._pub_client.ping()
            self._pubsub = self._sub_client.pubsub()
            self.available = True
            log.info(f"Redis connected at {config.REDIS_URL}")
        except Exception as exc:
            self.available = False
            log.warning(
                f"Redis unavailable ({exc}) — direct in-process dispatch fallback active"
            )

    def subscribe(self, channel: str, handler: Handler) -> None:
        """Register an async handler for a channel. Works regardless of Redis availability."""
        self._handlers.setdefault(channel, [])
        if handler not in self._handlers[channel]:
            self._handlers[channel].append(handler)

    def unsubscribe(self, channel: str, handler: Handler) -> None:
        """Remove a handler registration for a channel.
        Used during account switch to swap per-account channel subscriptions."""
        handlers = self._handlers.get(channel, [])
        try:
            handlers.remove(handler)
        except ValueError:
            pass
        # If no handlers remain and Redis is live, unsubscribe at Redis level
        if not handlers and self._pubsub and self.available:
            asyncio.create_task(self._pubsub.unsubscribe(channel))

    async def publish(self, channel: str, payload: Dict[str, Any]) -> None:
        """
        Publish payload to channel.
        - Redis available: JSON-encode and PUBLISH
        - Redis unavailable: directly await each registered handler
        Exceptions are caught and logged; never raises.
        """
        if self.available and self._pub_client is not None:
            try:
                await self._pub_client.publish(channel, json.dumps(payload))
                return
            except Exception as exc:
                log.warning(f"Redis publish failed ({exc}), falling back to direct dispatch")
                self.available = False

        # Direct in-process fallback
        await self._dispatch(channel, payload)

    async def _dispatch(self, channel: str, payload: Dict[str, Any]) -> None:
        """Call all registered handlers for channel directly."""
        for handler in self._handlers.get(channel, []):
            try:
                await handler(payload)
            except Exception as exc:
                log.error(f"Handler error on channel {channel!r}: {exc}", exc_info=True)

    async def run(self) -> None:
        """
        Long-running background coroutine. Subscribe to all registered channels
        and dispatch incoming messages to handlers.
        Reconnects automatically on Redis disconnect (5 s back-off).
        """
        while True:
            if not self.available or self._pubsub is None:
                await asyncio.sleep(5)
                await self.connect()
                continue

            try:
                channels = list(self._handlers.keys())
                if channels:
                    await self._pubsub.subscribe(*channels)
                    log.info(f"Redis subscribed to: {channels}")

                async for message in self._pubsub.listen():
                    if message["type"] != "message":
                        continue
                    channel = message["channel"]
                    try:
                        payload = json.loads(message["data"])
                    except (json.JSONDecodeError, TypeError):
                        log.warning(f"Invalid JSON on channel {channel!r}: {message['data']!r}")
                        continue
                    await self._dispatch(channel, payload)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning(f"Redis subscriber disconnected ({exc}), reconnecting in 5 s")
                self.available = False
                await asyncio.sleep(5)
                await self.connect()

    async def close(self) -> None:
        """Clean shutdown. Call in lifespan teardown."""
        try:
            if self._pubsub:
                await self._pubsub.unsubscribe()
                await self._pubsub.close()
            if self._pub_client:
                await self._pub_client.aclose()
            if self._sub_client:
                await self._sub_client.aclose()
        except Exception as exc:
            log.warning(f"Redis close error: {exc}")
        finally:
            self.available = False


# Module-level singleton
redis_bus = RedisBus()
