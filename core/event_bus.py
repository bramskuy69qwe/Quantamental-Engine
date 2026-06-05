"""
In-process asyncio event bus (Redis dependency dropped in v2.1).

Keeps the same pub/sub interface as the old redis_bus so all call sites
are unchanged except the import path and singleton name.

Channels (legacy flat scheme — engine-internal lifecycle):
    risk:account_updated      – WS ACCOUNT_UPDATE received
    risk:positions_refreshed  – positions refreshed (after fill or periodically)
    risk:risk_calculated      – risk calculator run completed
    risk:params_updated       – user updated risk parameters
    risk:trade_closed         – position fully closed

Phase-6 hierarchical, per-account topics (spec §9 — calc-linkage event catalog):
    engine:account:{account_id}:{domain}:{event}
    e.g. engine:account:2:calc:linked, engine:account:2:position:closed
    Built via ``ch_engine()`` / published via ``EventBus.publish_engine()`` so
    topic construction lives in one place. The calc:* / position:* emission
    sweeps (plan §6 rows 6.2-6.4, tasks P6.T3/T4) route through this wrapper;
    the account scope is carried by the TOPIC, not duplicated into the payload.

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


# Phase-6 (P6.T1) domain segments for the hierarchical topic scheme (spec §9).
# The catalog spans exactly these three domains; named here so the emission
# sweeps (P6.T3/T4) and any subscriber share one vocabulary instead of
# stringly-typed literals scattered across call sites.
DOMAIN_CALC     = "calc"
DOMAIN_POSITION = "position"
DOMAIN_ORDER    = "order"


def ch_engine(account_id: int, domain: str, event: str) -> str:
    """Return a Phase-6 hierarchical, per-account event topic (spec §9).

    ``engine:account:{account_id}:{domain}:{event}`` —
    e.g. ``ch_engine(2, DOMAIN_POSITION, "closed")`` →
    ``"engine:account:2:position:closed"``.

    The account scope lives in the topic (NOT duplicated into the payload),
    so a per-account subscriber can route on the topic alone. ``domain`` is one
    of ``DOMAIN_CALC`` / ``DOMAIN_POSITION`` / ``DOMAIN_ORDER``; ``event`` is the
    spec §9 suffix (``linked`` / ``closed`` / ``amended`` / ``duplicate_detected`` …).

    ``domain``/``event`` MUST be code-controlled literals with no ``:`` (the
    closed §9 catalog satisfies this) — dispatch is exact-match so a stray ``:``
    can't mis-route today, but it would make the topic ambiguous to a FUTURE
    split-based / prefix subscriber. Not validated here (no user input reaches it).
    """
    return f"engine:account:{account_id}:{domain}:{event}"


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
        # P8.T7: catch-all handlers that receive EVERY published event as
        # (channel, payload). The bus is otherwise exact-match per channel; the
        # notification center uses this to route the notifiable subset without
        # registering per-account × per-event-type channels.
        self._global_handlers: "List[Callable[[str, Dict[str, Any]], Awaitable[None]]]" = []
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

    def subscribe_all(self, handler) -> None:
        """Register a handler that receives EVERY published event as
        ``(channel, payload)`` (P8.T7). Idempotent. Dispatched AFTER the
        per-channel handlers; a global-handler error is logged + swallowed so
        it never affects the channel handlers or other global handlers."""
        if handler not in self._global_handlers:
            self._global_handlers.append(handler)

    async def publish(self, channel: str, payload: Dict[str, Any]) -> None:
        """Enqueue an event for dispatch. Never raises."""
        await self._queue.put((channel, payload))

    async def publish_engine(
        self, account_id: int, domain: str, event: str,
        payload: Dict[str, Any],
    ) -> None:
        """Publish on a Phase-6 per-account hierarchical topic (spec §9).

        Thin wrapper over :meth:`publish` that builds
        ``engine:account:{account_id}:{domain}:{event}`` via :func:`ch_engine`.
        The calc:* / position:* / order:* emission sweeps (P6.T3/T4) route
        through this so topic construction lives in ONE place. The payload is
        forwarded verbatim — the account scope is carried by the topic, not
        duplicated into the payload (matches the spec §9 payload shapes).
        Never raises (inherits :meth:`publish`'s enqueue-only contract).
        """
        await self.publish(ch_engine(account_id, domain, event), payload)

    def publish_engine_nowait(
        self, account_id: int, domain: str, event: str,
        payload: Dict[str, Any],
    ) -> None:
        """SYNC sibling of :meth:`publish_engine` for a non-coroutine emit on
        the event-loop thread (e.g. ``OrderManager._emit_fill_events`` calls
        this synchronously, without ``await``, on the loop thread before it
        dispatches its blocking trade-event writes off-loop). Uses
        ``Queue.put_nowait`` — safe from the loop thread on the unbounded queue
        (``maxsize=0`` → never ``QueueFull``).

        **Loop-thread only** — ``asyncio.Queue`` is not thread-safe, so a caller
        running in a worker thread (``asyncio.to_thread``) must NOT use this;
        it should emit from its on-loop caller via :meth:`publish_engine`.
        Best-effort: a put failure is swallowed so it never breaks the hot path.
        """
        try:
            self._queue.put_nowait((ch_engine(account_id, domain, event), payload))
        except Exception:
            log.debug(
                "publish_engine_nowait enqueue failed for %s:%s:%s",
                account_id, domain, event, exc_info=True,
            )

    async def _dispatch(self, channel: str, payload: Dict[str, Any]) -> None:
        for handler in self._handlers.get(channel, []):
            try:
                await handler(payload)
            except Exception as exc:
                log.error("Handler error on channel %r: %s", channel, exc)
        # P8.T7: catch-all handlers (channel + payload), after the exact-match
        # ones. Isolated so one global handler's error can't break the others.
        for ghandler in self._global_handlers:
            try:
                await ghandler(channel, payload)
            except Exception as exc:
                log.error("Global handler error on channel %r: %s", channel, exc)

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
                log.error("EventBus run loop error: %s", exc)

    async def close(self) -> None:
        """No-op — kept for interface compatibility with old redis_bus."""


# Module-level singleton
event_bus = EventBus()
