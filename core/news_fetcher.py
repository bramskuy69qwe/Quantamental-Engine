"""
News + economic-calendar fetchers for the regime News tab.

Two transports:
  - FinnhubFetcher: REST/httpx, polls /news and /calendar/economic. Mirrors the
    fetch_fred_series shape in core/regime_fetcher.py (per-call AsyncClient,
    raise_for_status, structured errors).
  - BweWsConsumer:  long-running websocket subscriber for @BWEnews crypto
    headlines. Mirrors the reconnect loop in core/ws_manager.py.

Both write into the news_items / economic_calendar tables via core.database.db.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

import config
from core.database import db

log = logging.getLogger("news_fetcher")


# ── Finnhub (news + economic calendar) ──────────────────────────────────────

class FinnhubFetcher:
    """REST client for Finnhub `/news` and `/calendar/economic`."""

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key if api_key is not None else config.FINNHUB_API_KEY

    def _key_ok(self) -> bool:
        if not self.api_key:
            log.warning("FINNHUB_API_KEY not set — Finnhub fetches skipped")
            return False
        return True

    async def fetch_news(self, category: str = "general") -> int:
        """Pull latest market news for `category`. Returns rows upserted."""
        if not self._key_ok():
            return 0
        url = f"{self.BASE_URL}/news"
        params = {"category": category, "token": self.api_key}
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                items = resp.json() or []
        except httpx.HTTPStatusError as e:
            log.error("Finnhub news HTTP %s: %s", e.response.status_code, e)
            return 0
        except Exception as e:
            log.error("Finnhub news fetch failed: %s", e)
            return 0

        rows: List[Dict[str, Any]] = []
        for it in items:
            ts = it.get("datetime")
            if not ts:
                continue
            try:
                published = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
            except (ValueError, TypeError):
                continue
            related = it.get("related") or ""
            rows.append({
                "source":       "finnhub",
                "external_id":  str(it.get("id", "")),
                "headline":     (it.get("headline") or "").strip(),
                "summary":      (it.get("summary") or "").strip(),
                "url":          it.get("url") or "",
                "image_url":    it.get("image") or "",
                "category":     it.get("category") or category,
                "tickers":      related if isinstance(related, str) else ",".join(related),
                "published_at": published,
            })
        rows = [r for r in rows if r["external_id"] and r["headline"]]
        if not rows:
            return 0
        count = await db.upsert_news_items(rows)
        log.info("Finnhub news: upserted %d items (category=%s)", count, category)
        return count

    async def fetch_calendar(self, from_date: str, to_date: str) -> int:
        """Pull economic calendar events between from/to (YYYY-MM-DD). Returns rows upserted."""
        if not self._key_ok():
            return 0
        url = f"{self.BASE_URL}/calendar/economic"
        params = {"from": from_date, "to": to_date, "token": self.api_key}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                payload = resp.json() or {}
        except httpx.HTTPStatusError as e:
            log.error("Finnhub calendar HTTP %s: %s", e.response.status_code, e)
            return 0
        except Exception as e:
            log.error("Finnhub calendar fetch failed: %s", e)
            return 0

        events = (payload.get("economicCalendar") or
                  payload.get("calendar") or
                  payload.get("data") or [])
        rows: List[Dict[str, Any]] = []
        for ev in events:
            time_str = ev.get("time") or ev.get("datetime") or ""
            if not time_str:
                continue
            iso_time = _to_iso_utc(time_str)
            if not iso_time:
                continue
            event_name = (ev.get("event") or ev.get("name") or "").strip()
            country = (ev.get("country") or ev.get("region") or "").strip()
            if not event_name or not country:
                continue
            rows.append({
                "event_time":  iso_time,
                "country":     country,
                "event_name":  event_name,
                "impact":      _normalise_impact(ev.get("impact")),
                "currency":    ev.get("currency") or "",
                "unit":        ev.get("unit") or "",
                "previous":    _to_float(ev.get("prev") or ev.get("previous")),
                "estimate":    _to_float(ev.get("estimate") or ev.get("forecast")),
                "actual":      _to_float(ev.get("actual")),
            })
        if not rows:
            return 0
        count = await db.upsert_calendar_events(rows)
        log.info("Finnhub calendar: upserted %d events (%s → %s)", count, from_date, to_date)
        return count


# ── BWE News (websocket) ────────────────────────────────────────────────────

class BweWsConsumer:
    """Long-running asyncio task that consumes BWE News WS messages and writes to DB.

    Protocol (per BWEnews API docs):
      - Connect to wss://bwenews-api.bwe-ws.com/ws (no auth required)
      - Send text "ping" periodically; server replies with text "pong"
      - News messages are JSON: {source_name, news_title, coins_included, url, timestamp}
    """

    # Application-level ping interval (seconds) — server keepalive
    _PING_INTERVAL = 30

    def __init__(self, url: Optional[str] = None) -> None:
        self.url = url or config.BWE_NEWS_WS_URL
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    async def run(self) -> None:
        """Connect-with-retry loop. Mirrors the reconnect pattern in core/ws_manager.py."""
        import websockets

        backoff = 5
        while not self._stop:
            try:
                # Disable the websockets library's built-in ping so we send our own
                # application-level "ping" text frame per the BWE protocol spec.
                async with websockets.connect(
                    self.url,
                    ping_interval=None,
                    max_size=2**20,
                ) as ws:
                    log.info("BWE WS: connected to %s", self.url)
                    backoff = 5
                    ping_task = asyncio.ensure_future(self._ping_loop(ws))
                    try:
                        async for raw in ws:
                            try:
                                await self._handle_message(raw)
                            except Exception as e:
                                log.warning("BWE WS: message handler error: %s", e)
                    finally:
                        ping_task.cancel()
                        try:
                            await ping_task
                        except asyncio.CancelledError:
                            pass
            except (websockets.exceptions.ConnectionClosedError,
                    websockets.exceptions.ConnectionClosedOK,
                    OSError) as e:
                log.warning("BWE WS: disconnected (%s) — reconnecting in %ds", e, backoff)
            except Exception as e:
                log.error("BWE WS: unexpected error: %s", e)
            if self._stop:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def _ping_loop(self, ws: Any) -> None:
        """Send application-level 'ping' frames every _PING_INTERVAL seconds."""
        try:
            while True:
                await asyncio.sleep(self._PING_INTERVAL)
                try:
                    await ws.send("ping")
                except Exception:
                    break
        except asyncio.CancelledError:
            pass

    async def _handle_message(self, raw: Any) -> None:
        """Parse a single BWE message and upsert to news_items.

        Expected JSON schema:
          {
            "source_name":    str,   // publisher, e.g. "BWENEWS"
            "news_title":     str,   // headline
            "coins_included": list,  // e.g. ["BTC", "ETH"]
            "url":            str,   // article link
            "timestamp":      int    // Unix epoch seconds
          }
        Ignore plain-text "pong" keepalive replies.
        """
        if isinstance(raw, (bytes, bytearray)):
            try:
                raw = raw.decode("utf-8", errors="replace")
            except Exception:
                return
        # Ignore pong keepalive
        if isinstance(raw, str) and raw.strip().lower() == "pong":
            return
        try:
            msg = json.loads(raw) if isinstance(raw, str) else raw
        except json.JSONDecodeError:
            return
        if not isinstance(msg, dict):
            return

        headline = (msg.get("news_title") or "").strip()
        if not headline:
            return

        ts_raw = msg.get("timestamp")
        published = _to_iso_utc(ts_raw) or datetime.now(timezone.utc).isoformat()

        # Stable deduplication key: timestamp + headline hash
        ext_id = (f"{int(ts_raw)}|{hash(headline) & 0xFFFFFFFF:08x}"
                  if ts_raw is not None
                  else f"{published}|{hash(headline) & 0xFFFFFFFF:08x}")

        await db.upsert_news_items([{
            "source":       "bwe",
            "external_id":  ext_id,
            "headline":     headline,
            "summary":      "",
            "url":          msg.get("url") or "",
            "image_url":    "",
            "category":     "crypto",
            "tickers":      _stringify_tickers(msg.get("coins_included")),
            "published_at": published,
        }])


# ── Helpers ──────────────────────────────────────────────────────────────────

def _to_float(v: Any) -> Optional[float]:
    if v is None or v == "" or v == ".":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _normalise_impact(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip().lower()
    # Finnhub uses 'low'/'medium'/'high' or numeric stars (1-3)
    if s in ("low", "medium", "high"):
        return s
    if s in ("1", "1.0"):
        return "low"
    if s in ("2", "2.0"):
        return "medium"
    if s in ("3", "3.0"):
        return "high"
    return s


def _to_iso_utc(v: Any) -> str:
    """Coerce a Finnhub or BWE timestamp into an ISO-8601 UTC string. Returns '' on failure."""
    if v is None or v == "":
        return ""
    # numeric (epoch seconds or millis)
    if isinstance(v, (int, float)):
        ts = float(v)
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except (ValueError, OSError, OverflowError):
            return ""
    s = str(v).strip()
    if not s:
        return ""
    # numeric-string epoch
    if s.isdigit():
        return _to_iso_utc(int(s))
    # Finnhub calendar uses "YYYY-MM-DD HH:MM:SS" (UTC); also accept "YYYY-MM-DD"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    # ISO-8601 fallback
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return ""


def _stringify_tickers(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    if isinstance(v, (list, tuple)):
        return ",".join(str(x) for x in v if x)
    return str(v)
