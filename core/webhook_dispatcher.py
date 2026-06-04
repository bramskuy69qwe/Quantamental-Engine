"""Position-closed webhook dispatcher (Phase 7.3, spec §11.3 / plan §7.4-7.5).

On a position close the engine emits the full §9 ``position:closed`` payload on
the per-account event_bus (P6.T2). This dispatcher is the FIRST in-process
subscriber of that event: it POSTs ``{"event": "position_closed", "payload":
<§9>}`` to the account's configured ``webhook_url`` (gated behind
``config_json.feature_flags.webhook_enabled`` — default OFF, no accidental
outbound traffic), with exponential-backoff retries and an ``engine_events``
dead-letter on exhaustion.

**Decoupling.** The event_bus dispatch loop is SEQUENTIAL — a slow handler stalls
ALL events — so the per-account subscriber handler only ENQUEUES the job
(non-blocking ``put_nowait``); a separate background worker (:meth:`run`, spawned
at schedulers startup) drains the queue and does the retrying HTTP off the
dispatch path.

**Dead-letter deviation (deviation-discipline).** Plan §7.5 says "dead-letter
QUEUE"; this writes a ``webhook_dispatch_failed`` ``engine_events`` row instead
of a dedicated replay table, because spec §11.3's webhook model is
fire-and-forget with the subscriber RE-FETCHING via the reverse-query endpoints
(Phase 7.1/7.2) — a missed webhook self-heals on the subscriber's next poll, so
replay isn't load-bearing. A replayable queue table is a deferred follow-up.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List

import httpx

from core.account_config import read_account_config_async
from core.context_query import json_safe
from core.event_bus import DOMAIN_POSITION, ch_engine

log = logging.getLogger("webhook_dispatcher")

DEFAULT_MAX_ATTEMPTS      = 5
DEFAULT_INITIAL_BACKOFF_S = 1.0
DEFAULT_MAX_BACKOFF_S     = 30.0
DEFAULT_TIMEOUT_S         = 10.0


class WebhookDispatcher:
    """Subscribes per-account ``position:closed`` and POSTs to the account's
    webhook URL with retry + backoff + dead-letter. One instance, one worker."""

    def __init__(
        self, db: Any, *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        initial_backoff_s: float = DEFAULT_INITIAL_BACKOFF_S,
        max_backoff_s: float = DEFAULT_MAX_BACKOFF_S,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._db = db
        self._max_attempts = max_attempts
        self._initial_backoff_s = initial_backoff_s
        self._max_backoff_s = max_backoff_s
        self._timeout_s = timeout_s
        self._queue: "asyncio.Queue" = asyncio.Queue()

    # ── wiring ──────────────────────────────────────────────────────────────

    def make_handler(self, account_id: int):
        """Return an async event_bus handler (closure capturing ``account_id``)
        that ENQUEUES the close payload — non-blocking, so the retrying HTTP
        happens in the worker, off the sequential event-dispatch loop. The §9
        payload carries no account_id (it's in the topic), hence the closure."""
        async def _handler(payload: Dict[str, Any]) -> None:
            try:
                self._queue.put_nowait((account_id, payload))
            except Exception:
                log.debug("webhook enqueue failed account=%s", account_id, exc_info=True)
        return _handler

    def subscribe_all(self, bus: Any, account_ids: List[int]) -> None:
        """Subscribe a per-account handler to each account's ``position:closed``
        topic. Called once at startup with the loaded account ids. (No wildcard
        subscriptions on the event_bus → one exact-topic subscribe per account;
        accounts added at runtime need a restart — documented limitation.)"""
        for aid in account_ids:
            bus.subscribe(ch_engine(aid, DOMAIN_POSITION, "closed"), self.make_handler(aid))

    # ── worker ──────────────────────────────────────────────────────────────

    async def run(self) -> None:
        """Long-running worker: drain the queue and dispatch each close webhook.
        Spawned in schedulers startup; cancelled on shutdown."""
        while True:
            try:
                account_id, payload = await self._queue.get()
            except asyncio.CancelledError:
                break
            try:
                await self._dispatch_one(account_id, payload)
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("webhook dispatch error account=%s", account_id)
            finally:
                self._queue.task_done()

    async def _dispatch_one(self, account_id: int, payload: Dict[str, Any]) -> None:
        """Resolve config, then (if enabled + URL set) POST with backoff retries;
        dead-letter on exhaustion. A disabled account is a no-op."""
        cfg = await read_account_config_async(self._db, account_id)
        if not (cfg.webhook_enabled and cfg.webhook_url):
            return
        # json_safe: the §9 payload is engine-computed but SELECT-*-sourced floats
        # could be non-finite; json.dumps(allow_nan=True) would emit Infinity/NaN
        # (invalid JSON) onto the wire. Coerce to null (mirrors the /context guard).
        body = json_safe({"event": "position_closed", "payload": payload})
        backoff = self._initial_backoff_s
        last_err: Any = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                await self._post(cfg.webhook_url, body)
                return  # delivered
            except Exception as e:
                last_err = e
                log.warning(
                    "webhook POST failed (attempt %d/%d) account=%s: %s",
                    attempt, self._max_attempts, account_id, e,
                )
                if attempt < self._max_attempts:
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, self._max_backoff_s)
        await self._dead_letter(account_id, payload, last_err)

    async def _post(self, url: str, body: Dict[str, Any]) -> None:
        """POST ``body`` as JSON; raise on non-2xx. Extracted so tests can
        substitute it without mocking httpx internals."""
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()

    async def _dead_letter(self, account_id: int, payload: Dict[str, Any], error: Any) -> None:
        """Record an exhausted webhook to ``engine_events`` (off-loop —
        ``log_event`` opens its own sync sqlite3 conn). Best-effort."""
        try:
            from core.event_log import log_event
            await asyncio.to_thread(
                log_event, account_id, "webhook_dispatch_failed", {
                    "position_id": payload.get("position_id"),
                    "attempts": self._max_attempts,
                    "error": str(error),
                    "payload": payload,
                }, "webhook_dispatcher",
            )
            log.error(
                "webhook DEAD-LETTERED account=%s position=%s after %d attempts: %s",
                account_id, payload.get("position_id"), self._max_attempts, error,
            )
        except Exception:
            log.exception("webhook dead-letter write failed account=%s", account_id)
