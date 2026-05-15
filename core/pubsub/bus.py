"""
PubSubBus abstraction + Redis backend implementation.

The PubSubBus protocol defines publish/subscribe. RedisBus implements it
via redis.asyncio. In-process fallback available for environments without
Redis (development / test).

All payloads are JSON-serialized with datetime→ISO and Decimal→str handling.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, AsyncIterator, Dict, Optional, Protocol

log = logging.getLogger("pubsub")


def _json_default(obj: Any) -> str:
    """JSON serializer for types not handled by default."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj)
    return str(obj)


class PubSubBus(Protocol):
    """Backend-agnostic pub/sub interface."""

    async def publish(self, channel: str, payload: Dict[str, Any]) -> None: ...
    async def subscribe(self, channel_pattern: str) -> AsyncIterator[Dict[str, Any]]: ...
    async def close(self) -> None: ...


class RedisBus:
    """Redis-backed pub/sub implementation."""

    def __init__(self, redis_url: str = "") -> None:
        self._url = redis_url
        self._redis = None
        self._connected = False

    async def _ensure_connection(self) -> None:
        if self._redis is not None and self._connected:
            return
        try:
            import redis.asyncio as aioredis
            if not self._url:
                import config
                self._url = config.REDIS_URL
            self._redis = aioredis.from_url(
                self._url, decode_responses=True,
                retry_on_timeout=True,
            )
            await self._redis.ping()
            self._connected = True
            log.info("RedisBus connected to %s", self._url)
        except Exception as exc:
            self._connected = False
            log.warning("RedisBus connection failed: %s", exc)
            raise

    async def publish(self, channel: str, payload: Dict[str, Any]) -> None:
        """Publish a message to a Redis channel. Best-effort."""
        try:
            await self._ensure_connection()
            msg = json.dumps(payload, default=_json_default)
            await self._redis.publish(channel, msg)
        except Exception:
            log.debug("RedisBus publish failed on %s", channel, exc_info=True)

    async def subscribe(self, channel_pattern: str) -> AsyncIterator[Dict[str, Any]]:
        """Subscribe and yield messages. Reconnects on failure."""
        while True:
            try:
                await self._ensure_connection()
                pubsub = self._redis.pubsub()
                await pubsub.subscribe(channel_pattern)
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        try:
                            yield json.loads(message["data"])
                        except (json.JSONDecodeError, TypeError):
                            continue
            except GeneratorExit:
                return
            except Exception:
                log.debug("RedisBus subscribe error, reconnecting...", exc_info=True)
                self._connected = False
                await asyncio.sleep(1)

    async def close(self) -> None:
        if self._redis:
            await self._redis.close()
            self._connected = False


# Module-level singleton (lazy-init)
_bus = None


def get_bus():
    """Return the shared PubSubBus singleton (InProcessBus or RedisBus)."""
    global _bus
    if _bus is None:
        import config
        backend = getattr(config, "PUBSUB_BACKEND", "inprocess").lower()
        if backend == "redis":
            _bus = RedisBus()
            log.info("PubSubBus: using RedisBus backend")
        elif backend == "inprocess":
            from core.pubsub.in_process_bus import InProcessBus
            _bus = InProcessBus()
            log.info("PubSubBus: using InProcessBus backend")
        else:
            log.warning("Unknown PUBSUB_BACKEND=%r — falling back to InProcessBus", backend)
            from core.pubsub.in_process_bus import InProcessBus
            _bus = InProcessBus()
    return _bus


def reset_bus() -> None:
    """Reset the singleton (for testing)."""
    global _bus
    _bus = None
