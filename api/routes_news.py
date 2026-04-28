from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.database import db
from core.news_fetcher import FinnhubFetcher

log = logging.getLogger("routes.news")
router = APIRouter()


@router.get("/api/news/feed", response_class=JSONResponse)
async def api_news_feed(limit: int = 50, since: str = "", source: str = ""):
    limit = max(1, min(int(limit), 200))
    items = await db.get_news_feed(limit=limit, since=since, source=source)
    return JSONResponse(items)


@router.get("/api/news/{item_id}", response_class=JSONResponse)
async def api_news_item(item_id: int):
    item = await db.get_news_by_id(item_id)
    if not item:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(item)


@router.get("/api/calendar", response_class=JSONResponse)
async def api_calendar(from_date: str = "", to_date: str = "", impact: str = ""):
    events = await db.get_calendar_events(from_date=from_date, to_date=to_date, impact=impact)
    return JSONResponse(events)


@router.post("/api/news/refresh", response_class=JSONResponse)
async def api_news_refresh():
    """Manual trigger: pull Finnhub news + calendar immediately."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    fetcher = FinnhubFetcher()
    today = _dt.now(_tz.utc).strftime("%Y-%m-%d")
    plus7 = (_dt.now(_tz.utc) + _td(days=7)).strftime("%Y-%m-%d")
    news_count = await fetcher.fetch_news(category="general")
    cal_count  = await fetcher.fetch_calendar(today, plus7)
    return JSONResponse({"news_added": news_count, "calendar_added": cal_count})
