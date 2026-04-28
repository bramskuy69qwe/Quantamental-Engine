from __future__ import annotations

import logging

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import JSONResponse

from core.platform_bridge import platform_bridge

log = logging.getLogger("routes.platform")
router = APIRouter()


@router.get("/api/platform/state", response_class=JSONResponse)
async def platform_state(request: Request):
    """JSON risk state snapshot for external consumers (Quantower plugin)."""
    return JSONResponse(platform_bridge.get_state_json())


@router.get("/api/platform/connection", response_class=JSONResponse)
async def platform_connection(request: Request):
    """Live plugin connection status — polled by the UI banner."""
    return JSONResponse({
        "connected":    platform_bridge.is_connected,
        "client_count": platform_bridge.client_count,
    })


@router.post("/api/platform/event", response_class=JSONResponse)
async def platform_event(request: Request):
    """REST fallback: Quantower plugin POSTs fill events here."""
    try:
        body = await request.json()
        await platform_bridge._dispatch(body)
        return JSONResponse({"status": "ok"})
    except Exception as exc:
        return JSONResponse({"status": "error", "error": str(exc)}, status_code=400)


@router.post("/api/platform/positions", response_class=JSONResponse)
async def platform_positions(request: Request):
    """REST fallback: Quantower plugin pushes position snapshot here."""
    try:
        body = await request.json()
        await platform_bridge._handle_position_snapshot(body)
        return JSONResponse({"status": "ok"})
    except Exception as exc:
        return JSONResponse({"status": "error", "error": str(exc)}, status_code=400)


@router.websocket("/ws/platform")
async def ws_platform(websocket: WebSocket):
    """Persistent WebSocket for the Quantower plugin."""
    await platform_bridge.handle_ws(websocket)
