"""
Historical OHLCV ingestion — fetches via adapter and stores in ohlcv_cache.

Usage (standalone):
    python -m core.ohlcv_fetcher --symbols BTCUSDT ETHUSDT --timeframe 4h --days 365

Usage (from code):
    from core.ohlcv_fetcher import OHLCVFetcher
    from core.exchange import _get_adapter
    fetcher = OHLCVFetcher(adapter=_get_adapter())
    count = await fetcher.fetch_and_store("BTCUSDT", "4h", since_days=365)
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

import config
from core.adapters.errors import (
    ConnectionError as AdapterConnectionError,
    ExchangeError as AdapterExchangeError,
    RateLimitError,
)
from core.database import db

log = logging.getLogger("ohlcv_fetcher")

# Max network retries per batch before giving up on a symbol
_MAX_RETRIES = 5


class OHLCVFetcher:
    """Fetches and stores historical OHLCV data via adapter.

    Pagination/retry at this level (not in adapter) because:
    - Batch operations span minutes; need aggressive retry (5 attempts, 5-60s)
    - Cursor advancement is domain logic (how much history, when to stop)
    - Adapter's fetch_ohlcv() is single-call by design
    """

    def __init__(self, adapter=None) -> None:
        self._adapter = adapter

    def _get_adapter(self):
        if self._adapter is not None:
            return self._adapter
        from core.exchange import _get_adapter
        self._adapter = _get_adapter()
        return self._adapter

    def _get_ohlcv_limit(self) -> int:
        try:
            return self._get_adapter().ohlcv_limit
        except Exception:
            return 1500

    async def fetch_and_store(
        self,
        symbol: str,
        timeframe: str = "4h",
        since_days: int = 365,
        until_ms: Optional[int] = None,
        progress_cb=None,
    ) -> int:
        """
        Fetch historical candles for symbol/timeframe going back `since_days`.
        Stores into ohlcv_cache via db.upsert_ohlcv.

        Skips already-covered date ranges (checks existing DB range first).
        Returns total candles written.

        progress_cb: optional async callable(pct: float, msg: str) for progress updates.
        """
        adapter = self._get_adapter()
        now_ms = until_ms or int(time.time() * 1000)
        target_since_ms = now_ms - int(since_days * 86_400_000)

        candle_limit = self._get_ohlcv_limit()

        # Check what we already have stored
        stored = await db.get_ohlcv_range(symbol, timeframe)
        stored_min = stored["min_ts_ms"]
        stored_max = stored["max_ts_ms"]
        stored_count = stored["count"]

        # Determine fetch range: fill gaps on both ends
        fetch_since_ms = target_since_ms
        if stored_min is not None and stored_min <= target_since_ms:
            # Historical range already covered — only fetch new candles from stored_max
            fetch_since_ms = max(target_since_ms, stored_max - _tf_ms(timeframe) * 2)

        log.info(
            "Fetching %s %s from %s (stored: %d candles)",
            symbol, timeframe,
            datetime.utcfromtimestamp(fetch_since_ms / 1000).strftime("%Y-%m-%d"),
            stored_count,
        )

        adapter.set_priority("background")  # OHLCV fetch is background priority

        # Fast-fail connectivity check
        try:
            await adapter.load_markets()
        except AdapterConnectionError as e:
            log.error(
                "Cannot reach exchange API (%s). "
                "Check your internet connection or set HTTP_PROXY in .env. "
                "Aborting fetch for %s.",
                e, symbol,
            )
            return 0
        except Exception as e:
            log.error("Failed to load exchange markets: %s", e)
            return 0

        total_written = 0
        since_ms = fetch_since_ms
        batch_num = 0
        retries = 0

        while since_ms < now_ms:
            try:
                candles = await adapter.fetch_ohlcv(
                    symbol, timeframe,
                    candle_limit,
                    since_ms=since_ms,
                )
                retries = 0  # reset on success
            except (AdapterExchangeError, ValueError) as e:
                # Covers BadSymbol (mapped to ExchangeError by adapter)
                log.warning("Symbol error fetching %s: %s", symbol, e)
                break
            except (AdapterConnectionError, RateLimitError) as e:
                retries += 1
                if retries > _MAX_RETRIES:
                    log.error(
                        "Network error fetching %s after %d retries (%s). "
                        "Check connectivity or set HTTP_PROXY in .env. Giving up.",
                        symbol, _MAX_RETRIES, e,
                    )
                    break
                wait = min(5 * (2 ** (retries - 1)), 60)   # 5s, 10s, 20s, 40s, 60s
                log.warning(
                    "Network error fetching %s (attempt %d/%d): %s — retrying in %ds",
                    symbol, retries, _MAX_RETRIES, e, wait,
                )
                await asyncio.sleep(wait)
                continue
            except Exception as e:
                log.error("Unexpected error fetching %s: %s", symbol, e)
                break

            if not candles:
                break

            written = await db.upsert_ohlcv(symbol, timeframe, candles)
            total_written += written
            batch_num += 1

            last_ts = candles[-1][0]
            if last_ts <= since_ms:
                break  # no progress — avoid infinite loop
            since_ms = last_ts + _tf_ms(timeframe)

            if progress_cb:
                pct = min(100.0, (last_ts - fetch_since_ms) / max(now_ms - fetch_since_ms, 1) * 100)
                await progress_cb(pct, f"Fetched {total_written} candles up to {_ms_to_str(last_ts)}")

            # Rate limit courtesy pause between batches
            if len(candles) < candle_limit:
                break  # reached the end of available data
            await asyncio.sleep(0.25)

        log.info("Stored %d candles for %s %s", total_written, symbol, timeframe)
        return total_written

    async def fetch_many(
        self,
        symbols: List[str],
        timeframe: str = "4h",
        since_days: int = 365,
        progress_cb=None,
    ) -> Dict[str, int]:
        """Fetch multiple symbols sequentially. Returns {symbol: count}."""
        results: Dict[str, int] = {}
        for i, sym in enumerate(symbols):
            if progress_cb:
                await progress_cb(
                    i / len(symbols) * 100,
                    f"Fetching {sym} ({i + 1}/{len(symbols)})",
                )
            results[sym] = await self.fetch_and_store(sym, timeframe, since_days)
        return results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tf_ms(timeframe: str) -> int:
    """Timeframe string → milliseconds per candle."""
    units = {"m": 60_000, "h": 3_600_000, "d": 86_400_000, "w": 604_800_000}
    for suffix, ms in units.items():
        if timeframe.endswith(suffix):
            try:
                return int(timeframe[:-1]) * ms
            except ValueError:
                pass
    return 3_600_000  # default 1h


def _ms_to_str(ts_ms: int) -> str:
    return datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M")


# ── CLI entry point ───────────────────────────────────────────────────────────

async def _main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Fetch historical OHLCV from exchange")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"],
                        help="Symbols to fetch (e.g. BTCUSDT ETHUSDT)")
    parser.add_argument("--timeframe", default="4h", help="Candle timeframe (default: 4h)")
    parser.add_argument("--days", type=int, default=365, help="Days of history (default: 365)")
    args = parser.parse_args()

    await db.initialize()
    from core.exchange import _get_adapter
    fetcher = OHLCVFetcher(adapter=_get_adapter())

    async def progress(pct: float, msg: str) -> None:
        print(f"  [{pct:5.1f}%] {msg}")

    for sym in args.symbols:
        print(f"\nFetching {sym} {args.timeframe} ({args.days}d)...")
        count = await fetcher.fetch_and_store(sym, args.timeframe, args.days, progress_cb=progress)
        print(f"  → {count} candles written")


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    asyncio.run(_main())
