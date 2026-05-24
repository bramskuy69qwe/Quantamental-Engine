"""
Market data REST wrappers: OHLCV, orderbook, mark price, MFE/MAE calculations.

Split from exchange.py for maintainability. All exchange-specific REST
calls go through the adapter layer.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Dict, List, Optional

import config
from core.adapters.errors import RateLimitError
from core.state import app_state


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

    adapter = _get_adapter()
    candles = await adapter.fetch_ohlcv(symbol, timeframe, limit)
    app_state.ohlcv_cache[symbol] = candles
    return candles


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
    exit_price: Optional[float] = None,
) -> tuple:
    """
    Calculate MFE and MAE as GROSS USDT PnL from pre-computed price extremes.

    LONG:  MFE = (trade_high - entry) * qty   MAE = (trade_low - entry) * qty
    SHORT: MFE = (entry - trade_low)  * qty   MAE = (entry - trade_high) * qty

    T173 sign-clamp: MFE is the best FAVORABLE excursion (≥ 0). MAE is the
    worst ADVERSE excursion (≤ 0). Without the clamp, a LONG trade that
    never dropped below entry (trade_low > entry_price) produces a
    POSITIVE mae — wrong direction. Symmetric for SHORT, and for trades
    that never moved favorably. The clamp enforces the convention that
    callers + analytics (sharpe_mfe, sortino_mae) rely on.

    T175 realized-PnL floor: when `exit_price` is supplied, the GROSS
    realized PnL of the trade (= (exit-entry)*qty for LONG; (entry-exit)
    *qty for SHORT) is a mathematical FLOOR for the excursion magnitude:
      • For a winning trade: MFE ≥ gross_realized_pnl. The exit price was
        an actual transaction during the trade lifetime, so trade_high
        (LONG) / trade_low (SHORT) MUST equal or exceed the favorable
        direction's exit excursion.
      • For a losing trade: MAE ≤ gross_realized_pnl (both negative).
    The price-extremes lookup can MISS the actual close moment when:
      - Partial-fill REPLACE races wipe reconciler results (db_orders.py
        INSERT OR REPLACE omits backfill_completed → defaults to 0).
      - aggTrades / OHLCV window alignment misses the exact close tick.
      - exit_price is a VWAP that doesn't correspond to a single market
        tick visible in aggTrades.
    The floor catches the under-reporting class: even if the lookup
    missed the actual extreme, the displayed MFE/MAE never go below
    realized PnL. (The floor does NOT bound the over-reporting case
    where the lookup picks up a spike outside the actual trade range —
    that needs separate investigation.)
    """
    if trade_high is None or trade_low is None or not entry_price or not quantity:
        return 0.0, 0.0
    if direction == "LONG":
        mfe = round((trade_high - entry_price) * quantity, 2)
        mae = round((trade_low  - entry_price) * quantity, 2)
    else:  # SHORT
        mfe = round((entry_price - trade_low)  * quantity, 2)
        mae = round((entry_price - trade_high) * quantity, 2)
    # T173 clamp: MFE ≥ 0, MAE ≤ 0.
    mfe = max(0.0, mfe)
    mae = min(0.0, mae)
    # T175 floor: bound to realized-PnL when caller supplies exit_price.
    if exit_price and exit_price > 0:
        if direction == "LONG":
            gross_realized = round((exit_price - entry_price) * quantity, 2)
        else:  # SHORT
            gross_realized = round((entry_price - exit_price) * quantity, 2)
        # gross_realized > 0 → winner → favorable floor on MFE
        # gross_realized < 0 → loser → adverse floor on MAE
        mfe = max(mfe, max(0.0, gross_realized))
        mae = min(mae, min(0.0, gross_realized))
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

    adapter = _get_adapter()
    ob = await adapter.fetch_orderbook(symbol, limit)
    app_state.orderbook_cache[symbol] = ob
    return ob


# ── Mark price ───────────────────────────────────────────────────────────────

async def fetch_mark_price(symbol: str) -> float:
    adapter = _get_adapter()
    price = await adapter.fetch_mark_price(symbol)
    app_state.mark_price_cache[symbol] = price
    return price
