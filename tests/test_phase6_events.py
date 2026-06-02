"""
Phase 6 (event-bus enrichment) — P6.T1: topic-naming wrapper + per-account scoping.

Covers the spec §9 hierarchical topic primitive
``engine:account:{account_id}:{domain}:{event}`` built by ``ch_engine`` and
published via ``EventBus.publish_engine``. The calc:* / position:* / order:*
emission sweeps (P6.T3/T4) route through this wrapper, so these tests pin the
ONE place topic construction lives:

  1. ``ch_engine`` builds the exact hierarchical string and is distinct per
     account / domain / event (no cross-account or cross-domain collision).
  2. ``publish_engine`` enqueues on that exact topic and dispatches the payload
     VERBATIM to a subscriber (the account scope is in the topic, NOT injected
     into the payload — matches the spec §9 payload shapes).
  3. Account scoping is real: a subscriber bound to a different account_id does
     not receive another account's event.

Run: pytest tests/test_phase6_events.py -v
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.event_bus import (  # noqa: E402
    EventBus,
    ch_engine,
    DOMAIN_CALC,
    DOMAIN_POSITION,
    DOMAIN_ORDER,
)


async def _drain_one(bus: EventBus):
    """Pull and dispatch exactly one queued event (avoids run()'s infinite loop)."""
    channel, payload = await bus._queue.get()
    await bus._dispatch(channel, payload)
    bus._queue.task_done()
    return channel, payload


# ── 1. ch_engine topic construction ──────────────────────────────────────────


class TestChEngine:
    def test_constructs_hierarchical_topic(self):
        assert ch_engine(2, DOMAIN_POSITION, "closed") == "engine:account:2:position:closed"
        assert ch_engine(1, DOMAIN_CALC, "linked") == "engine:account:1:calc:linked"

    def test_domain_constants_are_spec_values(self):
        # The spec §9 catalog spans exactly these three domains; a typo'd
        # rename here would silently break every sweep that imports them.
        assert (DOMAIN_CALC, DOMAIN_POSITION, DOMAIN_ORDER) == ("calc", "position", "order")

    def test_distinct_per_account_domain_event(self):
        base = ch_engine(1, DOMAIN_CALC, "linked")
        assert base != ch_engine(2, DOMAIN_CALC, "linked")        # account
        assert base != ch_engine(1, DOMAIN_POSITION, "linked")    # domain
        assert base != ch_engine(1, DOMAIN_CALC, "superseded")    # event


# ── 2. publish_engine routing + payload fidelity ─────────────────────────────


class TestPublishEngine:
    @pytest.mark.asyncio
    async def test_routes_to_subscriber_on_hierarchical_topic(self):
        bus = EventBus()
        received = []

        async def handler(payload):
            received.append(payload)

        bus.subscribe(ch_engine(2, DOMAIN_POSITION, "closed"), handler)
        await bus.publish_engine(2, DOMAIN_POSITION, "closed", {"position_id": "p1"})
        channel, _ = await _drain_one(bus)
        assert channel == "engine:account:2:position:closed"
        assert received == [{"position_id": "p1"}]

    @pytest.mark.asyncio
    async def test_payload_forwarded_verbatim_no_account_injection(self):
        # The account scope lives in the TOPIC; publish_engine must not mutate
        # or augment the caller's payload (spec §9 payloads carry no account_id).
        bus = EventBus()
        seen = []

        async def handler(payload):
            seen.append(payload)

        bus.subscribe(ch_engine(1, DOMAIN_CALC, "linked"), handler)
        payload = {"calc_id": "C1", "order_id": "O1"}
        await bus.publish_engine(1, DOMAIN_CALC, "linked", payload)
        await _drain_one(bus)
        assert seen == [{"calc_id": "C1", "order_id": "O1"}]
        assert "account_id" not in seen[0]      # not injected
        assert payload == {"calc_id": "C1", "order_id": "O1"}   # not mutated

    @pytest.mark.asyncio
    async def test_account_scope_isolates_subscribers(self):
        # A subscriber bound to account 1 must NOT receive account 2's event —
        # the whole point of per-account topics.
        bus = EventBus()
        got_acct1 = []

        async def handler(payload):
            got_acct1.append(payload)

        bus.subscribe(ch_engine(1, DOMAIN_POSITION, "closed"), handler)
        await bus.publish_engine(2, DOMAIN_POSITION, "closed", {"position_id": "p2"})
        await _drain_one(bus)
        assert got_acct1 == []      # account-1 handler saw nothing


# ── 3. publish_engine_nowait (sync enqueue for loop-thread non-coroutines) ────


class TestPublishEngineNowait:
    @pytest.mark.asyncio
    async def test_sync_enqueue_routes_to_subscriber(self):
        # P6.T4: the SYNC enqueue path used by OrderManager._emit_fill_events
        # (sync, on the loop thread). Builds the same hierarchical topic and
        # routes the payload verbatim to a subscriber.
        bus = EventBus()
        received = []

        async def handler(payload):
            received.append(payload)

        bus.subscribe(ch_engine(3, DOMAIN_POSITION, "partial_close"), handler)
        bus.publish_engine_nowait(3, DOMAIN_POSITION, "partial_close", {"position_id": "p9"})
        channel, _ = await _drain_one(bus)
        assert channel == "engine:account:3:position:partial_close"
        assert received == [{"position_id": "p9"}]

    def test_enqueue_only_and_best_effort(self):
        # Sync, no await; enqueues exactly one item and never raises (it must not
        # break the fill hot path it is called from).
        bus = EventBus()
        bus.publish_engine_nowait(1, DOMAIN_POSITION, "opened", {"x": 1})
        assert bus._queue.qsize() == 1
