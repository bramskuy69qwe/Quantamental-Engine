from __future__ import annotations

import logging

from fastapi import APIRouter, Request, WebSocket, HTTPException, WebSocketException, status
from fastapi.responses import JSONResponse

import config
from core.platform_bridge import platform_bridge

log = logging.getLogger("routes.platform")
router = APIRouter()


def _verify_token(token: str | None) -> None:
    """Raise if PLATFORM_TOKEN is configured and the caller didn't supply it."""
    expected = config.PLATFORM_TOKEN
    if not expected:
        return  # no token configured — allow (local-only deployment)
    if token != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid platform token")


def _extract_bearer(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return None


@router.get("/api/platform/state", response_class=JSONResponse)
async def platform_state(request: Request):
    """JSON risk state snapshot for external consumers (Quantower plugin)."""
    _verify_token(_extract_bearer(request))
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
    _verify_token(_extract_bearer(request))
    try:
        body = await request.json()
        await platform_bridge._dispatch(body)
        return JSONResponse({"status": "ok"})
    except HTTPException:
        raise
    except Exception as exc:
        return JSONResponse({"status": "error", "error": str(exc)}, status_code=400)


@router.post("/api/platform/positions", response_class=JSONResponse)
async def platform_positions(request: Request):
    """REST fallback: Quantower plugin pushes position snapshot here."""
    _verify_token(_extract_bearer(request))
    try:
        body = await request.json()
        await platform_bridge._handle_position_snapshot(body)
        return JSONResponse({"status": "ok"})
    except HTTPException:
        raise
    except Exception as exc:
        return JSONResponse({"status": "error", "error": str(exc)}, status_code=400)


@router.websocket("/ws/platform")
async def ws_platform(websocket: WebSocket):
    """Persistent WebSocket for the Quantower plugin."""
    expected = config.PLATFORM_TOKEN
    if expected:
        token = websocket.query_params.get("token", "")
        if token != expected:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
            return
    await platform_bridge.handle_ws(websocket)
