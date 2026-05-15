"""
In-process pub/sub backend via asyncio.Queue.

Functionally identical to RedisBus for single-process deployments.
Zero external dependencies. Pattern matching uses fnmatch (same glob
semantics as Redis PSUBSCRIBE).

Bounded subscriber queues (maxsize=100): slow subscribers drop messages
with a warning, never leak memory or block publishers.
"""
from __future__ import annotations

import asyncio
import fnmatch
import logging
from typing import Any, AsyncIterator, Dict, Set

log = logging.getLogger("pubsub.inprocess")

_QUEUE_MAX = 100


class InProcessBus:
    """In-process pub/sub backed by asyncio.Queue per subscriber."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, Set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, channel: str, payload: Dict[str, Any]) -> None:
        """Publish to all matching subscribers. Never blocks."""
        from core.pubsub.channels import extract_event_type
        enriched = {**payload, "_channel_suffix": extract_event_type(channel)}
        async with self._lock:
            for pattern, queues in self._subscribers.items():
                if fnmatch.fnmatchcase(channel, pattern):
                    dead: list = []
                    for q in queues:
                        try:
                            q.put_nowait(enriched)
                        except asyncio.QueueFull:
                            log.debug(
                                "InProcessBus: dropped message on %s (queue full)",
                                channel,
                            )
                        except Exception:
                            dead.append(q)
                    for q in dead:
                        queues.discard(q)

    async def subscribe(self, channel_pattern: str) -> AsyncIterator[Dict[str, Any]]:
        """Subscribe and yield messages matching the pattern."""
        q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
        async with self._lock:
            self._subscribers.setdefault(channel_pattern, set()).add(q)
        try:
            while True:
                payload = await q.get()
                yield payload
        except (GeneratorExit, asyncio.CancelledError):
            pass
        finally:
            async with self._lock:
                subs = self._subscribers.get(channel_pattern)
                if subs is not None:
                    subs.discard(q)
                    if not subs:
                        del self._subscribers[channel_pattern]

    async def close(self) -> None:
        """Clear all subscribers."""
        async with self._lock:
            self._subscribers.clear()
