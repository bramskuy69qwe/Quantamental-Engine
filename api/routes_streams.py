"""SSE streaming endpoints for real-time state updates via Redis pub/sub."""
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
    """Yield SSE events from ALL Redis channels for an account.

    Uses PSUBSCRIBE on account:{id}:* pattern. Each message becomes an
    SSE event with the channel suffix as the event name.
    """
    bus = get_bus()
    pattern = channel_pattern(account_id)
    try:
        await bus._ensure_connection()
        pubsub = bus._redis.pubsub()
        await pubsub.psubscribe(pattern)
        async for message in pubsub.listen():
            if await request.is_disconnected():
                break
            if message["type"] == "pmessage":
                channel = message.get("channel", "")
                event_type = extract_event_type(channel)
                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    continue
                yield {"event": event_type, "data": json.dumps(data)}
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
    """Yield SSE events from the position_update Redis channel."""
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
