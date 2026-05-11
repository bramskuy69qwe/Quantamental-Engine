"""
Macro signal data fetchers for the regime classifier.

Fetches historical data from free sources and stores in regime_signals table.
Signals (by priority / historical depth):

  vix_close       — Yahoo Finance (^VIX)             — 30+ years
  us10y_yield     — FRED API (DGS10)                 — 50+ years
  hy_spread       — FRED API (BAMLH0A0HYM2)          — 25+ years
  btc_dominance   — CoinGecko global market cap       — ~2013+
  btc_rvol_ratio  — Derived from ohlcv_cache (30d/7d) — as far as OHLCV
  agg_oi_change   — Binance fapi open interest         — ~2-3 years
  avg_funding     — Binance fapi funding rate           — ~2-3 years

Usage:
    fetcher = RegimeFetcher()
    result = await fetcher.fetch_all("2020-01-01", "2025-01-01", mode="macro_only")
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

import httpx

import config
from core.database import db

log = logging.getLogger("regime_fetcher")

# Type alias for progress callback
ProgressCB = Optional[Callable]


class RegimeFetcher:
    """Fetches and stores macro signal data from multiple free sources."""

    def __init__(self, adapter=None) -> None:
        self._adapter = adapter

    # ── VIX (Yahoo Finance via yfinance) ─────────────────────────────────────

    async def fetch_vix(
        self, since_date: str, until_date: str, progress_cb: ProgressCB = None,
    ) -> int:
        """Fetch VIX daily close from Yahoo Finance. Returns rows written."""
        await _progress(progress_cb, 0, "Fetching VIX from Yahoo Finance...")

        def _download():
            import yfinance as yf
            from datetime import datetime as _dt, timedelta as _td
            # yf.download end is exclusive — extend by 1 day to include until_date itself.
            end_dt = (_dt.strptime(until_date, "%Y-%m-%d") + _td(days=1)).strftime("%Y-%m-%d")

            # yf.download() honours start/end correctly for long ranges; Ticker.history()
            # has known issues with index tickers like ^VIX (returns truncated data).
            df = yf.download(
                "^VIX",
                start=since_date,
                end=end_dt,
                progress=False,
                auto_adjust=False,
                threads=False,
            )
            if df is None or df.empty:
                return []

            # yfinance >= 0.2.x returns MultiIndex columns even for a single ticker.
            # Flatten to level 0 so "Close" is a normal column.
            if hasattr(df.columns, "levels"):
                df.columns = df.columns.get_level_values(0)

            if "Close" not in df.columns:
                log.warning("VIX: 'Close' column missing — got %s", list(df.columns))
                return []

            closes = df["Close"].dropna()
            rows = []
            for date_idx, val in closes.items():
                try:
                    v = float(val)
                    if math.isnan(v):
                        continue
                    date_str = (
                        date_idx.strftime("%Y-%m-%d")
                        if hasattr(date_idx, "strftime")
                        else str(date_idx)[:10]
                    )
                    rows.append({"date": date_str, "value": round(v, 4)})
                except (ValueError, TypeError):
                    continue
            return rows

        try:
            rows = await asyncio.get_event_loop().run_in_executor(None, _download)
        except ModuleNotFoundError as e:
            msg = "yfinance not installed — run: pip install \"yfinance>=0.2.36\""
            log.error("VIX: %s (%s)", msg, e)
            await _progress(progress_cb, 100, f"VIX: {msg}")
            return 0
        except Exception as e:
            log.error("VIX download error: %s", e)
            await _progress(progress_cb, 100, f"VIX: error — {e}")
            return 0

        if not rows:
            log.warning("No VIX data returned for %s to %s", since_date, until_date)
            await _progress(progress_cb, 100, "VIX: no data returned")
            return 0

        count = await db.upsert_regime_signals("vix_close", rows, source="yfinance")
        await _progress(progress_cb, 100, f"VIX: {count} rows stored")
        log.info("Stored %d VIX values (%s to %s)", count, since_date, until_date)
        return count

    # ── FRED API (US 10Y yield, HY spread) ───────────────────────────────────

    async def fetch_fred_series(
        self,
        series_id: str,
        signal_name: str,
        since_date: str,
        until_date: str,
        progress_cb: ProgressCB = None,
    ) -> int:
        """Fetch a FRED series. Returns rows written."""
        api_key = config.FRED_API_KEY
        if not api_key:
            log.warning("FRED_API_KEY not set — skipping %s", series_id)
            await _progress(progress_cb, 100, f"{signal_name}: FRED_API_KEY not set")
            return 0

        await _progress(progress_cb, 0, f"Fetching {series_id} from FRED...")

        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": series_id,
            "api_key": api_key,
            "file_type": "json",
            "observation_start": since_date,
            "observation_end": until_date,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        observations = data.get("observations", [])
        rows = []
        for obs in observations:
            val_str = obs.get("value", ".")
            if val_str == "." or val_str == "":
                continue
            try:
                rows.append({"date": obs["date"], "value": round(float(val_str), 4)})
            except (ValueError, KeyError):
                continue

        if not rows:
            await _progress(progress_cb, 100, f"{signal_name}: no data")
            return 0

        count = await db.upsert_regime_signals(signal_name, rows, source="fred")
        await _progress(progress_cb, 100, f"{signal_name}: {count} rows stored")
        log.info("Stored %d %s values from FRED", count, signal_name)
        return count

    async def fetch_us10y_yield(
        self, since_date: str, until_date: str, progress_cb: ProgressCB = None,
    ) -> int:
        return await self.fetch_fred_series(
            "DGS10", "us10y_yield", since_date, until_date, progress_cb,
        )

    async def fetch_hy_spread(
        self, since_date: str, until_date: str, progress_cb: ProgressCB = None,
    ) -> int:
        return await self.fetch_fred_series(
            "BAMLH0A0HYM2", "hy_spread", since_date, until_date, progress_cb,
        )

    # ── BTC Realized Vol Ratio (derived from ohlcv_cache) ────────────────────

    async def compute_btc_rvol_ratio(
        self, since_date: str, until_date: str, progress_cb: ProgressCB = None,
    ) -> int:
        """
        Compute 30d/7d annualized realized vol ratio from BTCUSDT daily closes.
        Stored as btc_rvol_ratio. Requires BTCUSDT OHLCV in the cache.
        """
        await _progress(progress_cb, 0, "Computing BTC realized vol ratio...")

        since_dt = datetime.strptime(since_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        # Need 30 extra days of lookback for the 30d window
        lookback_dt = since_dt - timedelta(days=45)
        lookback_ms = int(lookback_dt.timestamp() * 1000)
        until_ms = int(datetime.strptime(until_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc, hour=23, minute=59, second=59,
        ).timestamp() * 1000)

        candles = await db.get_ohlcv("BTCUSDT", "1d", since_ms=lookback_ms, until_ms=until_ms)
        if not candles:
            # Try 4h and resample
            candles_4h = await db.get_ohlcv("BTCUSDT", "4h", since_ms=lookback_ms, until_ms=until_ms)
            if not candles_4h:
                log.warning("No BTCUSDT OHLCV data for rvol computation")
                await _progress(progress_cb, 100, "BTC rvol: no OHLCV data")
                return 0
            candles = _resample_to_daily(candles_4h)

        if len(candles) < 35:
            log.warning("Insufficient BTCUSDT candles for rvol (%d)", len(candles))
            await _progress(progress_cb, 100, "BTC rvol: insufficient data")
            return 0

        closes = [(datetime.utcfromtimestamp(c[0] / 1000).strftime("%Y-%m-%d"), float(c[4]))
                   for c in candles]

        # Compute log returns
        log_returns = []
        for i in range(1, len(closes)):
            if closes[i][1] > 0 and closes[i - 1][1] > 0:
                lr = math.log(closes[i][1] / closes[i - 1][1])
                log_returns.append((closes[i][0], lr))

        rows = []
        for i in range(29, len(log_returns)):
            date_str = log_returns[i][0]
            if date_str < since_date:
                continue

            # 7-day realized vol (annualized)
            rets_7d = [r[1] for r in log_returns[i - 6:i + 1]]
            vol_7d = _std(rets_7d) * math.sqrt(365)

            # 30-day realized vol (annualized)
            rets_30d = [r[1] for r in log_returns[i - 29:i + 1]]
            vol_30d = _std(rets_30d) * math.sqrt(365)

            if vol_7d > 0:
                ratio = round(vol_30d / vol_7d, 4)
                rows.append({"date": date_str, "value": ratio})

        if not rows:
            await _progress(progress_cb, 100, "BTC rvol: no values computed")
            return 0

        count = await db.upsert_regime_signals("btc_rvol_ratio", rows, source="derived")
        await _progress(progress_cb, 100, f"BTC rvol ratio: {count} rows stored")
        log.info("Stored %d BTC rvol ratio values", count)
        return count

    # ── Binance OI & Funding (via CCXT, proxied) ─────────────────────────────

    # ── Binance crypto signals (via adapter) ──────────────────────────────────
    # Pagination/chunking at this level (not in adapter) because:
    # - Window sizes are domain-driven (regime look-back period), partially
    #   informed by Binance's 30-day API limit but chosen for regime semantics
    # - Symbol selection is domain-driven (top-10 aggregate breadth)
    # - Pacing is domain-driven (0.3s courtesy, not exchange-specific)
    # - Early abort is domain-driven (rate-limit circuit breaker)
    # Contrast: adapter.fetch_price_extremes() owns tier logic because
    # resolution choice (aggTrades vs OHLCV) IS exchange-specific.

    async def fetch_binance_oi(
        self, since_date: str, until_date: str, progress_cb: ProgressCB = None,
    ) -> int:
        """Fetch aggregate open interest for top symbols. Returns rows written."""
        from core.adapters.errors import RateLimitError
        from core.adapters.protocols import SupportsOpenInterest

        await _progress(progress_cb, 0, "Fetching Binance open interest...")

        if not isinstance(self._adapter, SupportsOpenInterest):
            log.info("fetch_binance_oi: adapter doesn't support open interest — skipping")
            return 0

        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
                    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"]

        since_dt = datetime.strptime(since_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        until_dt = datetime.strptime(until_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        all_daily: Dict[str, float] = {}

        for sym_idx, sym in enumerate(symbols):
            if app_state.ws_status.is_rate_limited:
                log.info("fetch_binance_oi: aborting — rate limited")
                break
            current_start = since_dt
            while current_start < until_dt:
                if app_state.ws_status.is_rate_limited:
                    break
                period_end = min(current_start + timedelta(days=29), until_dt)
                try:
                    data = await self._adapter.fetch_open_interest_hist(
                        sym, "1d",
                        int(current_start.timestamp() * 1000),
                        int(period_end.timestamp() * 1000),
                        limit=30,
                    )
                except RateLimitError as e:
                    from core.exchange import handle_rate_limit_error
                    handle_rate_limit_error(e)
                    break
                except Exception as e:
                    log.warning("OI fetch failed for %s: %s", sym, e)
                    break

                for entry in data:
                    date_str = datetime.utcfromtimestamp(
                        int(entry["timestamp"]) / 1000
                    ).strftime("%Y-%m-%d")
                    oi_usdt = float(entry.get("sumOpenInterestValue", 0))
                    all_daily[date_str] = all_daily.get(date_str, 0) + oi_usdt

                current_start = period_end + timedelta(days=1)
                await asyncio.sleep(0.3)

            if progress_cb:
                pct = (sym_idx + 1) / len(symbols) * 80
                await _progress(progress_cb, pct, f"OI: {sym} done")

        if not all_daily:
            await _progress(progress_cb, 100, "OI: no data")
            return 0

        # Convert to daily % change
        sorted_dates = sorted(all_daily.keys())
        rows = []
        for i in range(1, len(sorted_dates)):
            prev_oi = all_daily[sorted_dates[i - 1]]
            curr_oi = all_daily[sorted_dates[i]]
            if prev_oi > 0:
                pct_change = round((curr_oi - prev_oi) / prev_oi * 100, 4)
                rows.append({"date": sorted_dates[i], "value": pct_change})

        count = await db.upsert_regime_signals("agg_oi_change", rows, source="binance")
        await _progress(progress_cb, 100, f"OI change: {count} rows stored")
        log.info("Stored %d aggregate OI change values", count)
        return count

    async def fetch_binance_funding(
        self, since_date: str, until_date: str, progress_cb: ProgressCB = None,
    ) -> int:
        """Fetch average funding rate across top symbols. Returns rows written."""
        from core.adapters.errors import RateLimitError
        from core.adapters.protocols import SupportsFundingRates

        await _progress(progress_cb, 0, "Fetching Binance funding rates...")

        if not isinstance(self._adapter, SupportsFundingRates):
            log.info("fetch_binance_funding: adapter doesn't support funding rates — skipping")
            return 0

        symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
                    "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT"]

        since_dt = datetime.strptime(since_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        until_dt = datetime.strptime(until_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

        daily_rates: Dict[str, List[float]] = {}

        for sym_idx, sym in enumerate(symbols):
            if app_state.ws_status.is_rate_limited:
                log.info("fetch_binance_funding: aborting — rate limited")
                break
            since_ms = int(since_dt.timestamp() * 1000)
            until_ms = int(until_dt.timestamp() * 1000)

            while since_ms < until_ms:
                if app_state.ws_status.is_rate_limited:
                    break
                try:
                    data = await self._adapter.fetch_funding_rates(
                        sym, since_ms,
                        min(since_ms + 30 * 86_400_000, until_ms),
                        limit=1000,
                    )
                except RateLimitError as e:
                    from core.exchange import handle_rate_limit_error
                    handle_rate_limit_error(e)
                    break
                except Exception as e:
                    log.warning("Funding fetch failed for %s: %s", sym, e)
                    break

                if not data:
                    break

                for entry in data:
                    ts_ms = int(entry["fundingTime"])
                    date_str = datetime.utcfromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d")
                    rate = float(entry["fundingRate"])
                    daily_rates.setdefault(date_str, []).append(rate)

                last_ts = int(data[-1]["fundingTime"])
                if last_ts <= since_ms:
                    break
                since_ms = last_ts + 1
                await asyncio.sleep(0.3)

            if progress_cb:
                pct = (sym_idx + 1) / len(symbols) * 80
                await _progress(progress_cb, pct, f"Funding: {sym} done")

        if not daily_rates:
            await _progress(progress_cb, 100, "Funding: no data")
            return 0

        # Average all rates per day (across all symbols and funding intervals)
        rows = []
        for date_str in sorted(daily_rates.keys()):
            rates = daily_rates[date_str]
            avg = round(sum(rates) / len(rates), 6)
            rows.append({"date": date_str, "value": avg})

        count = await db.upsert_regime_signals("avg_funding", rows, source="binance")
        await _progress(progress_cb, 100, f"Avg funding: {count} rows stored")
        log.info("Stored %d average funding rate values", count)
        return count

    # ── Fetch All ────────────────────────────────────────────────────────────

    async def fetch_all(
        self,
        since_date: str,
        until_date: str,
        mode: str = "full",
        progress_cb: ProgressCB = None,
    ) -> Dict[str, int]:
        """
        Fetch all macro signals for the given date range.
        mode: "full" (all signals) or "macro_only" (TradFi signals only, for deep history).
        Returns {signal_name: count_written}.
        """
        results: Dict[str, int] = {}
        total_steps = 6 if mode == "full" else 4

        async def step_progress(step: int, inner_pct: float, msg: str):
            if progress_cb:
                overall = (step / total_steps + inner_pct / 100 / total_steps) * 100
                await progress_cb(overall, msg)

        # Step 1: VIX
        try:
            results["vix_close"] = await self.fetch_vix(
                since_date, until_date,
                lambda p, m: step_progress(0, p, m),
            )
        except ImportError:
            log.error("yfinance not installed — run: pip install yfinance")
            results["vix_close"] = 0
            await step_progress(0, 100, "VIX: yfinance not installed")
        except Exception as e:
            log.error("VIX fetch failed: %s", e)
            results["vix_close"] = 0

        # Step 2: US 10Y Yield (FRED)
        try:
            results["us10y_yield"] = await self.fetch_us10y_yield(
                since_date, until_date,
                lambda p, m: step_progress(1, p, m),
            )
        except Exception as e:
            log.error("US10Y fetch failed: %s", e)
            results["us10y_yield"] = 0

        # Step 3: HY Spread (FRED)
        try:
            results["hy_spread"] = await self.fetch_hy_spread(
                since_date, until_date,
                lambda p, m: step_progress(2, p, m),
            )
        except Exception as e:
            log.error("HY spread fetch failed: %s", e)
            results["hy_spread"] = 0

        # Step 4: BTC rvol ratio (derived from OHLCV)
        try:
            results["btc_rvol_ratio"] = await self.compute_btc_rvol_ratio(
                since_date, until_date,
                lambda p, m: step_progress(3, p, m),
            )
        except Exception as e:
            log.error("BTC rvol ratio computation failed: %s", e)
            results["btc_rvol_ratio"] = 0

        # Steps 5+6: Binance OI & Funding (full mode only)
        if mode == "full":
            try:
                results["agg_oi_change"] = await self.fetch_binance_oi(
                    since_date, until_date,
                    lambda p, m: step_progress(4, p, m),
                )
            except Exception as e:
                log.error("Binance OI fetch failed: %s", e)
                results["agg_oi_change"] = 0

            try:
                results["avg_funding"] = await self.fetch_binance_funding(
                    since_date, until_date,
                    lambda p, m: step_progress(5, p, m),
                )
            except Exception as e:
                log.error("Binance funding fetch failed: %s", e)
                results["avg_funding"] = 0

        await _progress(progress_cb, 100, "All signals fetched")
        return results


# ── Helpers ──────────────────────────────────────────────────────────────────

def _std(values: List[float]) -> float:
    """Population standard deviation."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _resample_to_daily(candles_4h: List[List]) -> List[List]:
    """Group 4h candles into daily OHLCV. Returns list of daily candles."""
    daily: Dict[str, List[List]] = {}
    for c in candles_4h:
        date_str = datetime.utcfromtimestamp(c[0] / 1000).strftime("%Y-%m-%d")
        daily.setdefault(date_str, []).append(c)

    result = []
    for date_str in sorted(daily.keys()):
        bars = daily[date_str]
        ts = int(datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)
        o = float(bars[0][1])
        h = max(float(b[2]) for b in bars)
        lo = min(float(b[3]) for b in bars)
        c = float(bars[-1][4])
        vol = sum(float(b[5]) for b in bars)
        result.append([ts, o, h, lo, c, vol])
    return result


async def _progress(cb: ProgressCB, pct: float, msg: str) -> None:
    if cb:
        try:
            await cb(pct, msg)
        except Exception:
            pass
