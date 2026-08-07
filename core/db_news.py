from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("database")


class NewsMixin:
    """news_items + economic_calendar domain methods."""

    # ── HIGH-002 (Task 144, Phase 6 monitoring/reconciler) ──────────────────

    async def get_latest_news_timestamp(self) -> Optional[Any]:
        """Return MAX(published_at) from the `news_items` table — used
        by the monitoring layer's news-feed-staleness check.

        FE-LOW-027 (Task 145): table-name typo fix. Pre-Task-145 this
        helper (and its inline predecessor in `core/monitoring.py`)
        queried `FROM news` — a table that does not exist. The schema
        defines `news_items` (`core/database.py:316`). The original
        caller wrapped in `try/except: return` which silently swallowed
        the resulting OperationalError, making the news-staleness
        check dead code since whenever the typo was introduced.

        Task 144 preserved the typo byte-for-byte (refactor + bugfix
        kept orthogonal). Task 145 fixes both: (1) table name corrected
        to `news_items`; (2) the broad `except Exception` narrowed —
        we log on failure now instead of silently swallowing, so a
        future regression that breaks this query is loud, not silent.

        Returns the raw column value (ISO-8601 string per the schema —
        `published_at TEXT NOT NULL`) or None if the table is empty or
        a transient DB error occurs.
        """
        try:
            async with self._conn.execute(
                "SELECT MAX(published_at) FROM news_items"
            ) as cur:
                row = await cur.fetchone()
                return row[0] if row else None
        except Exception as exc:
            # FE-LOW-027 (Task 145): log instead of swallow. The pre-
            # Task-145 silent catch hid the FROM-news typo for an
            # unknown duration. Future failures should surface in logs.
            log.warning(
                "get_latest_news_timestamp failed: %r — news-staleness "
                "monitoring check will return None this cycle.",
                exc,
            )
            return None

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
        """Bulk upsert calendar events keyed on (event_time, country, event_name).

        The conflict clause REFUSES to overwrite a row owned by a different
        known provider (`WHERE source IN ('', excluded.source)`). The two
        providers' vocabularies genuinely collide — CPI, PPI, Initial Jobless
        Claims, ADP Employment Change and New Home Sales exist under both at
        identical UTC offsets — and without the guard a FRED write would null
        a Finnhub row's previous/estimate/actual, flip its source, and hand it
        to the next rebuild's DELETE. `''` (legacy, provenance unknown) is
        adoptable on purpose; two KNOWN providers never clobber each other.
        """
        if not rows:
            return 0
        await self._conn.executemany(
            """INSERT INTO economic_calendar
                 (event_time, country, event_name, impact, currency, unit,
                  previous, estimate, actual, fetched_at, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
               ON CONFLICT(event_time, country, event_name)
               DO UPDATE SET impact=excluded.impact, currency=excluded.currency,
                             unit=excluded.unit, previous=excluded.previous,
                             estimate=excluded.estimate, actual=excluded.actual,
                             fetched_at=excluded.fetched_at,
                             source=excluded.source
                 WHERE economic_calendar.source IN ('', excluded.source)""",
            [(r["event_time"], r["country"], r["event_name"],
              r.get("impact", ""), r.get("currency", ""), r.get("unit", ""),
              r.get("previous"), r.get("estimate"), r.get("actual"),
              r.get("source", ""))
             for r in rows],
        )
        await self._conn.commit()
        return len(rows)

    async def replace_calendar_events(
        self, source: str, from_iso: str, to_iso: str, rows: List[Dict[str, Any]],
    ) -> int:
        """Rebuild ONE provider's events inside a window: delete then insert.

        Why not a plain upsert: the UNIQUE key is
        (event_time, country, event_name), and a FRED row's event_time is
        DERIVED from a curated clock time (FRED publishes dates only — 0 of
        1000 sampled records carried a time). So correcting a wrong release
        time would MINT a second row and orphan the first, leaving two
        contradictory entries for one event — and this table never
        garbage-collects (it still holds 6k rows from a provider that
        stopped writing in June). Rebuilding the window makes a retime, a
        rename and a de-listing all idempotent.

        Scoped by `source` so it can never touch another provider's rows,
        and by the window so it can never delete history outside it.
        """
        # ONE transaction for DELETE + INSERT. Committing the delete first
        # would leave the window EMPTY if the insert then failed (crash,
        # SQLITE_BUSY) — turning a transient error into exactly the blank
        # calendar this whole change exists to fix. Note the inner
        # upsert_calendar_events early-returns without committing when `rows`
        # is empty, so the explicit commit below is what makes an
        # empty-window rebuild durable.
        await self._conn.execute(
            "DELETE FROM economic_calendar "
            "WHERE source = ? AND event_time >= ? AND event_time <= ?",
            (source, from_iso, to_iso),
        )
        n = await self.upsert_calendar_events(rows)
        await self._conn.commit()
        return n

    async def get_calendar_meta(self) -> Dict[str, Any]:
        """Provenance for the calendar pane — every field DERIVED, not asserted.

        The pane cannot otherwise tell "nothing is scheduled" from "the feed
        died in June", which is exactly the state this table was in.
        """
        async with self._conn.execute(
            "SELECT COUNT(*), MAX(fetched_at) FROM economic_calendar"
        ) as cur:
            total, last_fetch = await cur.fetchone()
        async with self._conn.execute(
            "SELECT DISTINCT source FROM economic_calendar ORDER BY source"
        ) as cur:
            sources = [r[0] for r in await cur.fetchall()]
        return {"stored_total": total or 0,
                "last_fetch": last_fetch,
                "sources": sources}

    async def get_calendar_events(
        self, from_date: str = "", to_date: str = "", impact: str = "",
    ) -> List[Dict[str, Any]]:
        """Return calendar events sorted by event_time ASC. Optional impact filter (csv)."""
        query = (
            "SELECT id, event_time, country, event_name, impact, currency, unit, "
            "previous, estimate, actual, source FROM economic_calendar WHERE 1=1"
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
             "previous": r[7], "estimate": r[8], "actual": r[9],
             "source": r[10]}
            for r in rows
        ]
