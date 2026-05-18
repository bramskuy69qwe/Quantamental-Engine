"""
Task 98 regression tests for HIGH-017 + HIGH-018.

HIGH-017: dd_gate_allows_new_entry must fail-CLOSED (block trading) when
account-settings DB read fails. Previously returned (True, None) — fail-open.

HIGH-018: InProcessBus.publish must keep the subscriber on unexpected
exceptions (log + continue). Previously disconnected the subscriber
on any non-QueueFull exception via broad except, losing SSE consumers
to transient errors.

Run: pytest tests/test_task98_dd_pubsub.py -v
"""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock, patch

import pytest


# ── HIGH-017: DD gate fail-closed ────────────────────────────────────────────

class TestDDGateFailClosed:
    """HIGH-017: DD gate's settings-read except must return (False, reason)
    not (True, None). Trading-block gates default to BLOCK on unknown state."""

    def test_dd_gate_fails_closed_on_settings_read_error(self, caplog):
        """Load-bearing pin: settings-read raise → (False, reason) + error log."""
        from core import dd_gate

        # Set portfolio.dd_state = "limit" to reach the settings-read branch.
        mock_pf = MagicMock(dd_state="limit", drawdown=0.10)
        mock_app_state = MagicMock(
            portfolio=mock_pf,
            dd_manually_unblocked=set(),
        )

        def _raise(_aid):
            raise RuntimeError("forced DB outage")

        caplog.set_level(logging.ERROR, logger="dd_gate")
        with patch("core.state.app_state", mock_app_state), \
             patch("core.db_account_settings.get_account_settings", _raise):
            allowed, reason = dd_gate.dd_gate_allows_new_entry(7)

        assert allowed is False, (
            "HIGH-017: settings-read error should fail closed (block trading). "
            "Returning True on this path silently bypasses configured DD limits "
            "during DB stress — the exact scenario the limit protects against."
        )
        assert reason is not None and "settings_unreadable" in reason, (
            f"Expected reason to identify the failure mode; got {reason!r}"
        )
        errors = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert any(
            "failing closed" in r.getMessage() for r in errors
        ), "Expected error log explaining the fail-closed path was taken"

    def test_dd_gate_normal_path_returns_actual_state(self):
        """Anti-over-correction: normal DB read returns the actual breach state."""
        from core import dd_gate

        mock_pf = MagicMock(dd_state="ok", drawdown=0.02)
        mock_app_state = MagicMock(
            portfolio=mock_pf,
            dd_manually_unblocked=set(),
        )

        # dd_state="ok" short-circuits at line 33 — settings read isn't even
        # exercised. Function returns (True, None).
        with patch("core.state.app_state", mock_app_state):
            allowed, reason = dd_gate.dd_gate_allows_new_entry(7)

        assert allowed is True and reason is None

    def test_dd_gate_advisory_mode_normal_path(self):
        """Anti-over-correction: 'limit' state + 'advisory' mode → allow."""
        from core import dd_gate

        mock_pf = MagicMock(dd_state="limit", drawdown=0.10)
        mock_app_state = MagicMock(
            portfolio=mock_pf,
            dd_manually_unblocked=set(),
        )
        mock_settings = MagicMock(dd_enforcement_mode="advisory", dd_limit_threshold=0.05)

        with patch("core.state.app_state", mock_app_state), \
             patch("core.db_account_settings.get_account_settings", return_value=mock_settings):
            allowed, reason = dd_gate.dd_gate_allows_new_entry(7)

        assert allowed is True and reason is None


# ── HIGH-018: pubsub keeps subscriber on non-QueueFull exceptions ────────────

class TestPubsubKeepsSubscriber:
    """HIGH-018: InProcessBus.publish must NOT disconnect subscriber on
    arbitrary exceptions. Only QueueFull (already correctly handled) drops
    the event; everything else logs + continues."""

    @pytest.mark.asyncio
    async def test_queuefull_drops_event_keeps_subscriber(self, caplog):
        """Sanity: QueueFull path already works pre-fix. Pin protects against
        future regression that removes the special-case."""
        from core.pubsub.in_process_bus import InProcessBus

        bus = InProcessBus()
        async def _drain():
            async for _ in bus.subscribe("test:*"):
                pass

        # Get a subscriber registered, but pre-fill its queue beyond capacity.
        # Easier: subscribe synchronously by hand — bypass the async iterator
        # so we control queue state directly.
        q = asyncio.Queue(maxsize=1)
        await q.put({"already_there": True})  # queue full
        async with bus._lock:
            bus._subscribers.setdefault("test:*", set()).add(q)

        caplog.set_level(logging.DEBUG, logger="core.pubsub.in_process_bus")
        await bus.publish("test:event", {"data": 1})

        # Subscriber still in set
        assert q in bus._subscribers["test:*"], (
            "QueueFull should not disconnect subscriber"
        )

    @pytest.mark.asyncio
    async def test_unexpected_exception_keeps_subscriber(self, caplog):
        """HIGH-018 load-bearing pin: an unexpected exception during event
        delivery (e.g., a misbehaving Queue subclass) must not disconnect
        the subscriber."""
        from core.pubsub.in_process_bus import InProcessBus

        bus = InProcessBus()

        # Inject a faulty "queue" object whose put_nowait raises RuntimeError.
        class _BrokenQueue:
            def put_nowait(self, _):
                raise RuntimeError("simulated unexpected error")

        broken_q = _BrokenQueue()
        async with bus._lock:
            bus._subscribers.setdefault("test:*", set()).add(broken_q)

        caplog.set_level(logging.ERROR, logger="core.pubsub.in_process_bus")
        await bus.publish("test:event", {"data": 1})

        # Subscriber still in set (pre-fix: would have been removed)
        assert broken_q in bus._subscribers["test:*"], (
            "HIGH-018 regression: subscriber was disconnected on a transient "
            "exception. Should keep subscription and log."
        )
        # log.exception fired
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert any(
            "unexpected error delivering" in r.getMessage() for r in errors
        ), "Expected log.exception with 'unexpected error delivering' context"

    @pytest.mark.asyncio
    async def test_normal_delivery_unchanged(self):
        """Anti-over-correction: normal event delivery leaves subscriber in set."""
        from core.pubsub.in_process_bus import InProcessBus

        bus = InProcessBus()
        q = asyncio.Queue(maxsize=10)
        async with bus._lock:
            bus._subscribers.setdefault("test:*", set()).add(q)

        await bus.publish("test:event", {"data": 42})

        # Subscriber still in set, event delivered
        assert q in bus._subscribers["test:*"]
        assert not q.empty()
        msg = q.get_nowait()
        assert msg["data"] == 42
