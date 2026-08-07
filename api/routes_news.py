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
    """Calendar events for a window, WITH the provenance the pane needs.

    Returns an envelope, not a bare array. Rationale: an empty array cannot
    distinguish "nothing is scheduled" from "the feed stopped writing two
    months ago", and the pane was rendering the literal message "no calendar
    events stored" over 6,278 stored events. Every meta field is DERIVED from
    the table (counts, MAX(fetched_at), DISTINCT source) — the only asserted
    string is `coverage`, which describes the fetcher's own whitelist.
    """
    # `to_date` is a bare 'YYYY-MM-DD' but event_time is a full ISO stamp, and
    # the filter is a STRING compare — '2026-09-06T12:30:00+00:00' <=
    # '2026-09-06' is False, so every event on the final day was silently
    # dropped. Widen to the end of that day. (Pre-existing; it also bit the
    # Finnhub era.)
    to_bound = f"{to_date}T23:59:59+00:00" if len(to_date) == 10 else to_date
    events = await db.get_calendar_events(
        from_date=from_date, to_date=to_bound, impact=impact)
    meta = await db.get_calendar_meta()
    meta.update({
        "window": {"from": from_date, "to": to_date},
        "window_count": len(events),
        # States the fetcher's OWN documented gaps, not just the ones FRED
        # structurally lacks. FOMC is the one an operator will assume is
        # covered — it is excluded because FRED reports 38 release dates for
        # it in a 45-day window, so its dates cannot locate a meeting.
        "coverage": "US government releases (FRED) — no FOMC, no ISM/PMI, "
                    "no Conference Board, no consensus forecasts",
    })
    return JSONResponse({"events": events, "meta": meta})


@router.post("/api/news/refresh", response_class=JSONResponse)
async def api_news_refresh():
    """Manual trigger: Finnhub news + the FRED economic calendar, immediately.

    The calendar half moved off Finnhub (403 — not on this plan, observed
    2026-08-07) to FRED. News stays on Finnhub, which works.
    """
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from core.news_fetcher import FredCalendarFetcher
    minus30 = (_dt.now(_tz.utc) - _td(days=30)).strftime("%Y-%m-%d")
    plus30 = (_dt.now(_tz.utc) + _td(days=30)).strftime("%Y-%m-%d")
    news_count = await FinnhubFetcher().fetch_news(category="general")
    cal_count  = await FredCalendarFetcher().fetch_calendar(minus30, plus30)
    return JSONResponse({"news_added": news_count, "calendar_added": cal_count})
