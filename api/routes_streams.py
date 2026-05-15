"""SSE streaming endpoints for real-time state updates via pub/sub bus."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from core.pubsub import position_channel
from core.pubsub.bus import get_bus
from core.pubsub.channels import channel_pattern, extract_event_type

log = logging.getLogger("routes.streams")
router = APIRouter()


# ── Multiplexed SSE endpoint (all account events on one connection) ──────────


async def _multiplexed_event_generator(account_id: int, request: Request):
    """Yield SSE events from ALL channels for an account.

    Uses the bus's subscribe() with pattern matching — works for both
    InProcessBus (fnmatch) and RedisBus (PSUBSCRIBE).
    """
    bus = get_bus()
    pattern = channel_pattern(account_id)
    try:
        async for payload in bus.subscribe(pattern):
            if await request.is_disconnected():
                break
            # For InProcessBus, payload is the dict directly.
            # For RedisBus, payload is already parsed by bus.subscribe().
            # Extract event type from the bus's internal routing.
            # Since subscribe() returns raw payloads without channel info,
            # we use a wrapper channel field if available, else default.
            event_type = payload.pop("_channel_suffix", "update") if isinstance(payload, dict) else "update"
            yield {"event": event_type, "data": json.dumps(payload)}
    except asyncio.CancelledError:
        pass
    except GeneratorExit:
        pass
    except Exception:
        log.debug("SSE multiplexed stream error", exc_info=True)


@router.get("/stream/account/{account_id}")
async def stream_account(account_id: int, request: Request):
    """Multiplexed SSE stream — all event types for one account."""
    return EventSourceResponse(
        _multiplexed_event_generator(account_id, request),
        ping=30,
    )


# ── Per-channel SSE endpoint (backward-compat / debugging) ───────────────────


async def _position_event_generator(account_id: int, request: Request):
    """Yield SSE events from the position_update channel."""
    bus = get_bus()
    try:
        async for payload in bus.subscribe(position_channel(account_id)):
            if await request.is_disconnected():
                break
            yield {"event": "position_update", "data": json.dumps(payload)}
    except asyncio.CancelledError:
        pass
    except Exception:
        log.debug("SSE position stream error", exc_info=True)


@router.get("/stream/account/{account_id}/positions")
async def stream_positions(account_id: int, request: Request):
    """Per-channel SSE stream for position updates (backward-compat)."""
    return EventSourceResponse(
        _position_event_generator(account_id, request),
        ping=30,
    )
