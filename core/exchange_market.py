"""
Market data REST wrappers: OHLCV, orderbook, mark price, MFE/MAE calculations.

Split from exchange.py for maintainability. Uses the adapter layer for
exchange-specific REST calls, with get_exchange() fallback for CCXT-generic calls.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

import ccxt
import config
from core.state import app_state
from core.exchange import get_exchange, _REST_POOL
from core.constants import MS_PER_MINUTE, MS_PER_HOUR


def _get_adapter():
    """Late-import wrapper to avoid circular import with core.exchange."""
    from core.exchange import _get_adapter as _ga
    return _ga()

log = logging.getLogger("exchange")


# ── OHLCV / ATR ─────────────────────────────────────────────────────────────

async def fetch_ohlcv(symbol: str, timeframe: str = config.ATR_TIMEFRAME,
                      limit: int = config.ATR_FETCH_LIMIT) -> List:
    # Fallback path only — when plugin is connected it streams bars via ohlcv_bar events.
    try:
        from core.platform_bridge import platform_bridge  # late import: circular dep
        if platform_bridge.is_connected:
            cached = app_state.ohlcv_cache.get(symbol, [])
            if not cached:
                # Plugin hasn't sent bars yet — ask for them now.
                asyncio.create_task(platform_bridge.request_ohlcv(symbol, timeframe))
            return cached
    except Exception:
        pass

    loop = asyncio.get_event_loop()
    ex   = get_exchange()

    def _fetch():
        return ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    candles = await loop.run_in_executor(_REST_POOL, _fetch)
    app_state.ohlcv_cache[symbol] = candles
    return candles


async def fetch_ohlcv_window(
    symbol: str, since_ms: int, until_ms: int, timeframe: str = "1m"
) -> List:
    """
    Fetch OHLCV candles for an exact time window (since_ms -> until_ms, ms UTC).
    Makes multiple 1000-candle requests if the window is large.
    Returns list of [timestamp, open, high, low, close, volume].
    """
    loop = asyncio.get_event_loop()
    ex   = get_exchange()
    all_candles: List = []
    cursor = since_ms

    def _fetch(since):
        return ex.fetch_ohlcv(symbol, timeframe, since=since, limit=1000) or []

    while cursor < until_ms:
        batch = await loop.run_in_executor(_REST_POOL, _fetch, cursor)
        if not batch:
            break
        all_candles.extend([c for c in batch if c[0] <= until_ms])
        if batch[-1][0] >= until_ms or len(batch) < 1000:
            break
        cursor = batch[-1][0] + 1  # advance past last candle
    return all_candles


_3_MIN_MS  = 3 * MS_PER_MINUTE
_12_HR_MS  = 12 * MS_PER_HOUR
_1_HR_MS   = MS_PER_HOUR
_60_SEC_MS = MS_PER_MINUTE
_AGG_BUF   = 1_000   # 1 s buffer: Binance endTime can be exclusive


async def _agg_extremes(symbol: str, start_ms: int, end_ms: int) -> tuple:
    """
    Stream aggTrades for [start_ms, end_ms] in 1000-trade pages, tracking
    only (max_price, min_price) in O(1) memory.

    Returns (max_price, min_price) or (None, None) on error / no data.
    """
    adapter = _get_adapter()
    effective_end = end_ms + _AGG_BUF

    max_price: Optional[float] = None
    min_price: Optional[float] = None
    cursor = max(0, start_ms - _AGG_BUF)   # slight lookback for entry fill

    try:
        while cursor <= effective_end:
            # RL-1: abort if rate-limited (don't fire more REST calls into a 429)
            if app_state.ws_status.is_rate_limited:
                log.debug("aggTrades aborted for %s — rate limited", symbol)
                return None, None
            batch = await adapter.fetch_agg_trades(symbol, cursor, effective_end)
            if not batch:
                break
            for t in batch:
                price = float(t["p"])
                if max_price is None or price > max_price:
                    max_price = price
                if min_price is None or price < min_price:
                    min_price = price
            last_ts = int(batch[-1]["T"])
            if last_ts >= effective_end or len(batch) < 1000:
                break
            cursor = last_ts + 1
            # RL-1: pace pagination (was zero delay → burst)
            await asyncio.sleep(0.25)
    except ccxt.DDoSProtection as e:
        from core.exchange import handle_rate_limit_error
        handle_rate_limit_error(e)
        return None, None
    except ccxt.RateLimitExceeded as e:
        from core.exchange import handle_rate_limit_error
        handle_rate_limit_error(e)
        return None, None
    except Exception as e:
        log.warning(f"aggTrades failed for {symbol} [{start_ms},{end_ms}]: {e}")
        return None, None

    return max_price, min_price


async def _ohlcv_hl(
    symbol: str, start_ms: int, end_ms: int, tf: str
) -> tuple:
    """
    Fetch OHLCV and immediately reduce to (max_high, min_low).
    Returns (None, None) when the window is empty or start >= end.
    """
    if start_ms >= end_ms:
        return None, None
    candles = await fetch_ohlcv_window(symbol, start_ms, end_ms, tf)
    if not candles:
        return None, None
    return max(c[2] for c in candles), min(c[3] for c in candles)


def _merge_hl(*pairs: tuple) -> tuple:
    """Merge any number of (high, low) tuples — skips None pairs."""
    highs = [h for h, l in pairs if h is not None]
    lows  = [l for h, l in pairs if l is not None]
    if not highs:
        return None, None
    return max(highs), min(lows)


async def fetch_hl_for_trade(symbol: str, open_ms: int, close_ms: int) -> tuple:
    """
    Fetch the true (max_high, min_low) for a closed trade using the finest
    available data source for each section of the hold window.

    Tier 1 — hold < 3 min:  All aggTrades.
    Tier 2 — 3 min - 12 hr: Entry/exit aggTrades + body 1m OHLCV.
    Tier 3 — >= 12 hr:      5-section hybrid (aggTrades + 1m + 1h OHLCV).

    Returns (max_high, min_low) or (None, None) on complete failure.
    """
    duration = close_ms - open_ms

    # ── Tier 1: < 3 min — all aggTrades ───────────────────────────────────────
    if duration < _3_MIN_MS:
        high, low = await _agg_extremes(symbol, open_ms, close_ms)
        if high is not None:
            return high, low
        # Fallback: 1m covers the window (at most 3 candles)
        return await _ohlcv_hl(symbol, open_ms, close_ms, "1m")

    # ── Tier 2: 3 min – 12 hr ─────────────────────────────────────────────────
    if duration <= _12_HR_MS:
        _r2 = await asyncio.gather(
            _agg_extremes(symbol, open_ms,              open_ms  + _60_SEC_MS),
            _ohlcv_hl    (symbol, open_ms + _60_SEC_MS, close_ms - _60_SEC_MS, "1m"),
            _agg_extremes(symbol, close_ms - _60_SEC_MS, close_ms),
            return_exceptions=True,
        )
        if any(isinstance(v, BaseException) for v in _r2):
            log.warning("fetch_hl_for_trade tier2 partial failure (%s): %s", symbol, _r2)
            return await _ohlcv_hl(symbol, open_ms, close_ms, "1m")
        entry_h, body_h, exit_h = _r2
        high, low = _merge_hl(entry_h, body_h, exit_h)
        if high is not None:
            return high, low
        return await _ohlcv_hl(symbol, open_ms, close_ms, "1m")

    # ── Tier 3: >= 12 hr — 5-section hybrid, all concurrent ─────────────────
    e1m_end   = open_ms  + _1_HR_MS
    x1m_start = max(close_ms - _1_HR_MS, e1m_end)  # overlap guard

    r = await asyncio.gather(
        _agg_extremes(symbol, open_ms,              open_ms  + _60_SEC_MS),  # entry agg
        _ohlcv_hl    (symbol, open_ms + _60_SEC_MS, e1m_end,           "1m"),  # entry 1m
        _ohlcv_hl    (symbol, e1m_end,              x1m_start,         "1h"),  # middle 1h
        _ohlcv_hl    (symbol, x1m_start,            close_ms - _60_SEC_MS, "1m"),  # exit 1m
        _agg_extremes(symbol, close_ms - _60_SEC_MS, close_ms),              # exit agg
        return_exceptions=True,
    )
    if any(isinstance(v, BaseException) for v in r):
        log.warning("fetch_hl_for_trade tier3 partial failure (%s): %s", symbol, r)
        return await _ohlcv_hl(symbol, open_ms, close_ms, "1m")
    high, low = _merge_hl(*r)
    if high is not None:
        return high, low
    return await _ohlcv_hl(symbol, open_ms, close_ms, "1m")


def calc_mfe_mae(
    trade_high: Optional[float],
    trade_low:  Optional[float],
    entry_price: float,
    direction: str,
    quantity: float,
) -> tuple:
    """
    Calculate MFE and MAE as GROSS USDT PnL from pre-computed price extremes.

    LONG:  MFE = (trade_high - entry) * qty   MAE = (trade_low - entry) * qty
    SHORT: MFE = (entry - trade_low)  * qty   MAE = (entry - trade_high) * qty
    """
    if trade_high is None or trade_low is None or not entry_price or not quantity:
        return 0.0, 0.0
    if direction == "LONG":
        mfe = round((trade_high - entry_price) * quantity, 2)
        mae = round((trade_low  - entry_price) * quantity, 2)
    else:  # SHORT
        mfe = round((entry_price - trade_low)  * quantity, 2)
        mae = round((entry_price - trade_high) * quantity, 2)
    return mfe, mae


# ── Orderbook ────────────────────────────────────────────────────────────────

async def fetch_orderbook(symbol: str, limit: int = 20) -> Dict:
    # Fallback path only — when plugin is connected it streams depth via depth_snapshot events.
    try:
        from core.platform_bridge import platform_bridge  # late import: circular dep
        if platform_bridge.is_connected:
            cached = app_state.orderbook_cache.get(symbol)
            if not cached:
                asyncio.create_task(platform_bridge.request_depth(symbol))
            return cached or {"bids": [], "asks": []}
    except Exception:
        pass

    loop = asyncio.get_event_loop()
    ex   = get_exchange()

    def _fetch():
        return ex.fetch_order_book(symbol, limit=limit)

    ob = await loop.run_in_executor(_REST_POOL, _fetch)
    app_state.orderbook_cache[symbol] = ob
    return ob


# ── Mark price ───────────────────────────────────────────────────────────────

async def fetch_mark_price(symbol: str) -> float:
    loop = asyncio.get_event_loop()
    ex   = get_exchange()

    def _fetch():
        ticker = ex.fetch_ticker(symbol)
        return float(ticker.get("last") or ticker.get("close") or 0)

    price = await loop.run_in_executor(_REST_POOL, _fetch)
    app_state.mark_price_cache[symbol] = price
    return price
