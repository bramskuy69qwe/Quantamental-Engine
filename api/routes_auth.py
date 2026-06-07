"""Operator-session endpoints — Phase 9 T1 (minimal; plan §9 / spec §12.1).

Single-tenant localhost has no auth, and the engine has a single global
active account (``app_state.active_account_id``). An "operator" is therefore
a per-browser SEAT token (a localStorage UUID the frontend mints). These two
endpoints back the minimal multi-session BANNER:

  - ``POST /operator/session/register`` — report whether another seat is
    active on the active account (``state: foreign``) or this seat owns it
    (``state: owner``); starts a session row when none is active.
  - ``POST /operator/session/takeover`` — displace the foreign active
    session and make this seat the owner.

There is NO hard read-only lock (that's the full P9.T1) and no idle timeout
(P9.T4). The orchestration lives in :mod:`core.auth_state`; this module is
the thin HTTP surface (reads the global active account, validates the seat
token). operator_id propagation onto action rows is P9.T3.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Form
from fastapi.responses import JSONResponse

from core.database import db
from core.state import app_state
from core.auth_state import register_session, takeover_session

log = logging.getLogger("routes.auth")
router = APIRouter()

# Seat tokens are client-minted UUIDs (~36 chars). Bound the length so a
# malformed/malicious POST can't bloat the operator_sessions table.
_MAX_SEAT_LEN = 64


def _seat(operator_id: str) -> str:
    return (operator_id or "").strip()


@router.post("/operator/session/register")
async def operator_session_register(operator_id: str = Form(...)):
    """Register this browser seat against the active account. JSON ``state``:
    ``owner`` (this seat holds the account) or ``foreign`` (a different seat
    is active → the UI raises the takeover banner)."""
    seat = _seat(operator_id)
    if not seat or len(seat) > _MAX_SEAT_LEN:
        return JSONResponse({"error": "invalid operator_id"}, status_code=400)
    aid = app_state.active_account_id
    result = await register_session(db, aid, seat)
    result["account_id"] = aid
    # P9.T3: write-through the operator-on-duty cache so the WS
    # order/amendment write sites stamp operator_id O(1) (no per-write DB
    # read). Only when THIS seat owns the session — a "foreign" result
    # means a different seat is active, so we must not claim it here.
    if result.get("state") == "owner":
        app_state.operator_id_by_account[aid] = seat
    return JSONResponse(result)


@router.post("/operator/session/takeover")
async def operator_session_takeover(operator_id: str = Form(...)):
    """Displace the foreign active session and make this seat the owner of
    the active account's session."""
    seat = _seat(operator_id)
    if not seat or len(seat) > _MAX_SEAT_LEN:
        return JSONResponse({"error": "invalid operator_id"}, status_code=400)
    aid = app_state.active_account_id
    result = await takeover_session(db, aid, seat)
    result["account_id"] = aid
    # P9.T3: takeover always makes this seat the owner — refresh the
    # operator-on-duty cache (see register handler).
    if result.get("state") == "owner":
        app_state.operator_id_by_account[aid] = seat
    return JSONResponse(result)
