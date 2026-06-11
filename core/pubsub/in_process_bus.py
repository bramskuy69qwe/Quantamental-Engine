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

from core import correlation_log

log = logging.getLogger("pubsub.inprocess")

_QUEUE_MAX = 100


class InProcessBus:
    """In-process pub/sub backed by asyncio.Queue per subscriber."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, Set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, channel: str, payload: Dict[str, Any]) -> None:
        """Publish to all matching subscribers. Never blocks."""
        # corr-tap: pubsub_publish (CL.T2b, spec §5.7) — market-grouped
        # (fires per recalc cycle; volume-gated, OFF in linkage)
        _sym = payload.get("symbol") if isinstance(payload, dict) else None
        correlation_log.emit(
            "pubsub", "internal", "internal", correlation_log.CAT_PUBSUB_PUBLISH,
            {"channel": channel, "backend": "inproc"},
            symbol=_sym if isinstance(_sym, str) else None,
        )
        from core.pubsub.channels import extract_event_type
        enriched = {**payload, "_channel_suffix": extract_event_type(channel)}
        async with self._lock:
            for pattern, queues in self._subscribers.items():
                if fnmatch.fnmatchcase(channel, pattern):
                    for q in queues:
                        try:
                            q.put_nowait(enriched)
                        except asyncio.QueueFull:
                            log.debug(
                                "InProcessBus: dropped message on %s (queue full)",
                                channel,
                            )
                        except Exception:
                            # HIGH-018 (Task 98): keep the subscriber. Previously
                            # any exception added q to a `dead` list and discarded
                            # it from the subscriber set — a transient error
                            # (payload serialization, recoverable bug) silently
                            # disconnected SSE consumers with no recovery short
                            # of page reload. Now: log with full traceback and
                            # let the next event delivery retry. Normal cleanup
                            # still happens in subscribe()'s finally block when
                            # the consumer generator ends.
                            log.exception(
                                "InProcessBus: unexpected error delivering "
                                "to subscriber on %s; keeping subscription",
                                channel,
                            )

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
