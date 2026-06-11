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
import time
from typing import Any, Awaitable, Callable, Dict, List

from core import correlation_log

log = logging.getLogger("event_bus")

# CL.T2a (spec §6.2, D6): the queued item is (channel, payload, corr_id) —
# the publisher's chain id is captured at enqueue and RE-BOUND by the
# dispatch loop before handlers run, because the bus consumer is a separate
# task that contextvars cannot cross. Subscribers (and their create_task
# children) therefore inherit the ORIGINATING chain. This is deliberately a
# small, isolated diff (its own commit) so it stays independently revertable.

# The pivot fields a bus_publish summary carries (spec §5.2 payload-summary:
# enough to join the chain to trade entities without duplicating payloads).
_SUMMARY_KEYS = ("calc_id", "position_id", "terminal_position_id",
                 "lifecycle_id", "order_id", "symbol")


def _payload_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {k: payload[k] for k in _SUMMARY_KEYS if k in payload}
    out["n_keys"] = len(payload)
    return out

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

    publish() enqueues (channel, payload, corr_id) — the publisher's
    correlation-chain id, re-bound by run() around dispatch (CL.T2a, spec
    §6.2); run() drains the queue and dispatches to registered handlers.
    No external process needed.
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

    def _n_subscribers(self, channel: str) -> int:
        return len(self._handlers.get(channel, [])) + len(self._global_handlers)

    def _tap_publish(self, channel: str, payload: Any) -> None:
        # corr-tap: bus_publish (spec §5.2) — publisher's context, fired AFTER
        # a successful enqueue ("published" = enqueued; no phantom envelope if
        # the put path ever fails). Guarded: a tap must never break publish's
        # never-raises contract, even on a contract-violating non-dict payload.
        try:
            is_dict = isinstance(payload, dict)
            sym = payload.get("symbol") if is_dict else None
            correlation_log.emit(
                "event_bus", "event_bus", "internal", correlation_log.CAT_BUS_PUBLISH,
                {"channel": channel,
                 "summary": _payload_summary(payload) if is_dict else {"n_keys": -1},
                 "n_subscribers": self._n_subscribers(channel)},
                symbol=sym if isinstance(sym, str) else None,
            )
        except Exception:
            log.debug("bus_publish tap failed for %r", channel, exc_info=True)

    async def publish(self, channel: str, payload: Dict[str, Any]) -> None:
        """Enqueue an event for dispatch. Never raises.

        CL.T2a: captures the publisher's corr_id with the queued item so the
        dispatch loop can re-bind it (spec §6.2)."""
        await self._queue.put((channel, payload, correlation_log.current_corr_id()))
        self._tap_publish(channel, payload)

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
            channel = ch_engine(account_id, domain, event)
            # sync-in-task on the loop thread → contextvar capture works here
            self._queue.put_nowait((channel, payload, correlation_log.current_corr_id()))
            self._tap_publish(channel, payload)  # after the enqueue succeeded
        except Exception:
            log.debug(
                "publish_engine_nowait enqueue failed for %s:%s:%s",
                account_id, domain, event, exc_info=True,
            )

    @staticmethod
    def _handler_name(handler: Any) -> str:
        return getattr(handler, "__qualname__", None) or repr(handler)

    def _tap_deliver(self, channel: str, handler: Any, ok: bool,
                     err: str, t0: float) -> None:
        # corr-tap: bus_deliver (spec §5.2) — emitted by the INSTRUMENTED
        # dispatch path, one envelope per handler invocation (only the loop
        # can see which handler ran, its outcome, and its duration — a
        # subscribe_all catch-all cannot). Runs under the re-bound publisher
        # corr_id when invoked via run().
        payload: Dict[str, Any] = {
            "channel": channel, "handler": self._handler_name(handler),
            "ok": ok, "duration_ms": round((time.perf_counter() - t0) * 1000, 2),
        }
        if err:
            payload["error_type"] = err
        correlation_log.emit("event_bus", "event_bus", "internal",
                             correlation_log.CAT_BUS_DELIVER, payload)

    async def _dispatch(self, channel: str, payload: Dict[str, Any]) -> None:
        for handler in self._handlers.get(channel, []):
            t0 = time.perf_counter()
            try:
                await handler(payload)
                self._tap_deliver(channel, handler, True, "", t0)
            except Exception as exc:
                self._tap_deliver(channel, handler, False, type(exc).__name__, t0)
                log.error("Handler error on channel %r: %s", channel, exc)
        # P8.T7: catch-all handlers (channel + payload), after the exact-match
        # ones. Isolated so one global handler's error can't break the others.
        for ghandler in self._global_handlers:
            t0 = time.perf_counter()
            try:
                await ghandler(channel, payload)
                self._tap_deliver(channel, ghandler, True, "", t0)
            except Exception as exc:
                self._tap_deliver(channel, ghandler, False, type(exc).__name__, t0)
                log.error("Global handler error on channel %r: %s", channel, exc)

    async def run(self) -> None:
        """Long-running coroutine: drain the queue and dispatch events.

        CL.T2a: re-binds the PUBLISHER's corr_id around each event's dispatch
        (correlation_scope resets in finally — a handler error cannot leak the
        binding into the next event). Handlers and their create_task children
        therefore inherit the originating chain (spec §6.2)."""
        while True:
            try:
                channel, payload, corr_id = await self._queue.get()
                with correlation_log.correlation_scope(corr_id=corr_id):
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
