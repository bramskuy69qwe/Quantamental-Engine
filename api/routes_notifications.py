"""P8.T7 (spec §12.5): in-app notification poll endpoint."""
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from core.state import app_state
from core.database import db
from core.notifications import notification_center

log = logging.getLogger("routes.notifications")
router = APIRouter()


@router.get("/notifications/poll")
async def notifications_poll(since: int = -1):
    """New notifications for the active account, newer than ``since``, filtered
    by the account's config_json.notification_subscriptions.

    ``since < 0`` = init: returns the current cursor only (no backlog replay),
    so a fresh page doesn't toast every buffered event. Returns
    ``{"notifications": [...], "latest_id": N}``.
    """
    aid = app_state.active_account_id
    if since < 0:
        return JSONResponse(
            {"notifications": [], "latest_id": notification_center.latest_id(aid)}
        )
    subscribed = None
    try:
        from core.account_config import read_account_config_async
        cfg = await read_account_config_async(db, aid)
        subscribed = {t for t, on in cfg.notification_subscriptions.items() if on}
    except Exception:
        log.debug("notifications_poll config read failed; not filtering", exc_info=True)
    items, latest = notification_center.poll(aid, since, subscribed)
    return JSONResponse({"notifications": items, "latest_id": latest})
