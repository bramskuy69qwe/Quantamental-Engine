"""SSE streaming endpoints for real-time state updates via Redis pub/sub."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from core.pubsub import position_channel
from core.pubsub.bus import get_bus

log = logging.getLogger("routes.streams")
router = APIRouter()


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
    """Server-Sent Events stream for position updates."""
    return EventSourceResponse(
        _position_event_generator(account_id, request),
        ping=30,
    )
