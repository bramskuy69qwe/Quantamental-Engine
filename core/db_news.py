from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("database")


class NewsMixin:
    """news_items + economic_calendar domain methods."""

    async def upsert_news_items(self, rows: List[Dict[str, Any]]) -> int:
        """Bulk upsert news items. Each row needs source, external_id, headline, published_at."""
        if not rows:
            return 0
        await self._conn.executemany(
            """INSERT INTO news_items
                 (source, external_id, headline, summary, url, image_url, category,
                  tickers, published_at, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(source, external_id)
               DO UPDATE SET headline=excluded.headline, summary=excluded.summary,
                             url=excluded.url, image_url=excluded.image_url,
                             category=excluded.category, tickers=excluded.tickers,
                             published_at=excluded.published_at""",
            [(r["source"], str(r["external_id"]), r["headline"],
              r.get("summary", ""), r.get("url", ""), r.get("image_url", ""),
              r.get("category", ""), r.get("tickers", ""),
              r["published_at"]) for r in rows],
        )
        await self._conn.commit()
        return len(rows)

    async def get_news_feed(
        self, limit: int = 50, since: str = "", source: str = "",
    ) -> List[Dict[str, Any]]:
        """Return news items sorted by published_at DESC. Optional since (ISO) and source filters."""
        query = (
            "SELECT id, source, external_id, headline, summary, url, image_url, "
            "category, tickers, published_at FROM news_items WHERE 1=1"
        )
        params: list = []
        if since:
            query += " AND published_at >= ?"
            params.append(since)
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY published_at DESC LIMIT ?"
        params.append(int(limit))
        async with self._conn.execute(query, params) as cur:
            rows = await cur.fetchall()
        return [
            {"id": r[0], "source": r[1], "external_id": r[2], "headline": r[3],
             "summary": r[4], "url": r[5], "image_url": r[6], "category": r[7],
             "tickers": r[8], "published_at": r[9]}
            for r in rows
        ]

    async def get_news_by_id(self, item_id: int) -> Optional[Dict[str, Any]]:
        """Return a single news item by primary key."""
        async with self._conn.execute(
            "SELECT id, source, external_id, headline, summary, url, image_url, "
            "category, tickers, published_at, fetched_at FROM news_items WHERE id = ?",
            (item_id,),
        ) as cur:
            r = await cur.fetchone()
        if not r:
            return None
        return {
            "id": r[0], "source": r[1], "external_id": r[2], "headline": r[3],
            "summary": r[4], "url": r[5], "image_url": r[6], "category": r[7],
            "tickers": r[8], "published_at": r[9], "fetched_at": r[10],
        }

    async def upsert_calendar_events(self, rows: List[Dict[str, Any]]) -> int:
        """Bulk upsert economic calendar events keyed on (event_time, country, event_name)."""
        if not rows:
            return 0
        await self._conn.executemany(
            """INSERT INTO economic_calendar
                 (event_time, country, event_name, impact, currency, unit,
                  previous, estimate, actual, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(event_time, country, event_name)
               DO UPDATE SET impact=excluded.impact, currency=excluded.currency,
                             unit=excluded.unit, previous=excluded.previous,
                             estimate=excluded.estimate, actual=excluded.actual,
                             fetched_at=excluded.fetched_at""",
            [(r["event_time"], r["country"], r["event_name"],
              r.get("impact", ""), r.get("currency", ""), r.get("unit", ""),
              r.get("previous"), r.get("estimate"), r.get("actual"))
             for r in rows],
        )
        await self._conn.commit()
        return len(rows)

    async def get_calendar_events(
        self, from_date: str = "", to_date: str = "", impact: str = "",
    ) -> List[Dict[str, Any]]:
        """Return calendar events sorted by event_time ASC. Optional impact filter (csv)."""
        query = (
            "SELECT id, event_time, country, event_name, impact, currency, unit, "
            "previous, estimate, actual FROM economic_calendar WHERE 1=1"
        )
        params: list = []
        if from_date:
            query += " AND event_time >= ?"
            params.append(from_date)
        if to_date:
            query += " AND event_time <= ?"
            params.append(to_date)
        if impact:
            levels = [s.strip() for s in impact.split(",") if s.strip()]
            if levels:
                query += " AND impact IN (" + ",".join("?" * len(levels)) + ")"
                params.extend(levels)
        query += " ORDER BY event_time ASC"
        async with self._conn.execute(query, params) as cur:
            rows = await cur.fetchall()
        return [
            {"id": r[0], "event_time": r[1], "country": r[2], "event_name": r[3],
             "impact": r[4], "currency": r[5], "unit": r[6],
             "previous": r[7], "estimate": r[8], "actual": r[9]}
            for r in rows
        ]
