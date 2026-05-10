"""
Market data REST wrappers: OHLCV, orderbook, mark price, MFE/MAE calculations.

Split from exchange.py for maintainability. Uses the adapter layer for
exchange-specific REST calls, with get_exchange() fallback for CCXT-generic calls.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

import config
from core.adapters.errors import RateLimitError
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


async def fetch_hl_for_trade(symbol: str, open_ms: int, close_ms: int) -> tuple:
    """
    Fetch the true (max_high, min_low) for a closed trade.

    Delegates to the adapter's fetch_price_extremes with "auto" precision,
    which internally handles multi-resolution tier routing (aggTrades for
    short windows, hybrid aggTrades+OHLCV for longer windows).

    Returns (max_high, min_low) or (None, None) on complete failure.
    """
    from core.exchange import handle_rate_limit_error

    adapter = _get_adapter()
    try:
        return await adapter.fetch_price_extremes(symbol, open_ms, close_ms, "auto")
    except RateLimitError as e:
        handle_rate_limit_error(e)
        return None, None
    except Exception as e:
        log.warning("fetch_hl_for_trade failed for %s: %s", symbol, e)
        return None, None


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
