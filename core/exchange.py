"""
CCXT-based REST wrapper for Binance USD-M Futures.
All heavy lifting (positions, account, OHLCV) goes through here.
WebSocket streams are handled separately in ws_manager.py.
"""
from __future__ import annotations
import logging
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta

import ccxt
import config
from core.state import app_state, PositionInfo, TZ_LOCAL

log = logging.getLogger("exchange")


# Dedicated thread pool for all blocking CCXT REST calls.
# Keeps REST I/O isolated from the default executor used by the event loop,
# preventing REST saturation from blocking asyncio internals.
_REST_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="rest")


def _make_exchange() -> ccxt.binanceusdm:
    """Legacy factory — kept for compatibility; main.py still references it during init."""
    params = {
        "apiKey":  config.BINANCE_API_KEY,
        "secret":  config.BINANCE_API_SECRET,
        "options": {
            "defaultType": "future",
            "fetchCurrencies": False,
        },
        "enableRateLimit": True,
    }
    if config.HTTP_PROXY:
        params["proxies"] = {"http": config.HTTP_PROXY, "https": config.HTTP_PROXY}
    ex = ccxt.binanceusdm(params)
    return ex


_exchange: Optional[ccxt.binance] = None


def get_exchange() -> ccxt.Exchange:
    """Return the CCXT instance for the currently active account.

    Delegates to exchange_factory (keyed by account_id) so account switching
    automatically routes all REST calls to the new account without restarting.
    Falls back to the legacy singleton during the one-time startup window before
    account_registry has finished loading.
    """
    try:
        from core.account_registry import account_registry
        from core.exchange_factory import exchange_factory
        creds = account_registry.get_active_sync()
        if creds and creds.get("api_key"):
            return exchange_factory.get(
                creds["id"],
                creds["api_key"],
                creds["api_secret"],
                creds.get("exchange", "binance"),
                creds.get("market_type", "future"),
            )
    except Exception:
        pass  # fall through to legacy singleton during startup
    global _exchange
    if _exchange is None:
        _exchange = _make_exchange()
    return _exchange


# ── Exchange info ─────────────────────────────────────────────────────────────

async def fetch_exchange_info() -> None:
    """Update exchange_info on app_state."""
    loop = asyncio.get_event_loop()
    ex   = get_exchange()

    t0 = time.monotonic()
    server_time = await loop.run_in_executor(_REST_POOL, ex.fetch_time)
    latency_ms  = (time.monotonic() - t0) * 1000

    info = app_state.exchange_info
    # Use active account's exchange name dynamically
    try:
        from core.account_registry import account_registry
        creds = account_registry.get_active_sync()
        info.name = creds.get("exchange", config.EXCHANGE_NAME).capitalize()
    except Exception:
        info.name = config.EXCHANGE_NAME
    info.latency_ms = round(latency_ms, 2)
    info.server_time = datetime.fromtimestamp(
        server_time / 1000, tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")
    info.maker_fee  = config.MAKER_FEE
    info.taker_fee  = config.TAKER_FEE


# ── Account & balance ─────────────────────────────────────────────────────────

async def fetch_account() -> None:
    """Fetch futures account balance and update account_state."""
    loop = asyncio.get_event_loop()
    ex   = get_exchange()

    raw  = await loop.run_in_executor(_REST_POOL, ex.fetch_balance)  # REST call outside lock
    info_raw = raw.get("info", {})

    async with app_state._lock:
        acc = app_state.account_state
        acc.total_equity       = float(info_raw.get("totalWalletBalance",    0) or 0)
        acc.available_margin   = float(info_raw.get("availableBalance",      0) or 0)
        acc.total_unrealized   = float(info_raw.get("totalUnrealizedProfit", 0) or 0)
        acc.total_margin_used  = float(info_raw.get("totalInitialMargin",    0) or 0)
        acc.total_margin_ratio = float(info_raw.get("totalMaintMargin",      0) or 0)
        acc.balance_usdt       = float(info_raw.get("totalWalletBalance",    0) or 0)

        # Set BOD / SOW equity on first fetch if not set
        if acc.bod_equity == 0.0:
            acc.bod_equity       = acc.total_equity
            acc.max_total_equity = acc.total_equity
            acc.min_total_equity = acc.total_equity
            app_state.portfolio.dd_baseline_equity = acc.total_equity
        if acc.sow_equity == 0.0:
            acc.sow_equity = acc.total_equity

        app_state.exchange_info.account_id = info_raw.get("feeTier", "")
        app_state.ws_status.last_update    = datetime.now(timezone.utc)


# ── Positions ─────────────────────────────────────────────────────────────────


def _parse_position_v2(raw: dict) -> Optional[PositionInfo]:
    """Parse a position entry from fapiPrivateV2GetAccount response."""
    amt = float(raw.get("positionAmt", 0) or 0)
    if amt == 0:
        return None

    symbol      = raw.get("symbol", "")
    direction   = "LONG" if amt > 0 else "SHORT"
    avg_price   = float(raw.get("entryPrice", 0) or 0)
    notional    = abs(float(raw.get("notional", 0) or 0))
    unrealized  = float(raw.get("unrealizedProfit", 0) or 0)
    liq_price   = float(raw.get("liquidationPrice", 0) or 0)
    margin_used = float(raw.get("initialMargin", 0) or 0)
    mark_price  = float(raw.get("markPrice", avg_price) or avg_price)

    return PositionInfo(
        ticker               = symbol,
        contract_amount      = abs(amt),
        contract_size        = 1.0,
        direction            = direction,
        position_value_usdt  = notional,
        position_value_asset = abs(amt),
        average              = avg_price,
        fair_price           = mark_price,
        liquidation_price    = liq_price,
        individual_margin_used  = margin_used,
        individual_unrealized   = unrealized,
        sector               = config.get_sector(symbol),
    )


async def fetch_positions() -> None:
    """
    Fetch open positions via fapiPrivateV2GetAccount — avoids the
    leverageBrackets KeyError that ccxt.fetch_positions() can throw
    on newer Binance Futures API responses.
    """
    loop = asyncio.get_event_loop()
    ex   = get_exchange()

    def _fetch():
        account = ex.fapiPrivateV2GetAccount()
        return account.get("positions", [])

    raw_list = await loop.run_in_executor(_REST_POOL, _fetch)

    positions = []
    for r in (raw_list or []):
        p = _parse_position_v2(r)
        if p:
            positions.append(p)

    # Snapshot existing state under lock so we read a consistent list
    async with app_state._lock:
        existing = {p.ticker: p for p in app_state.positions}

    new_tickers = {p.ticker for p in positions}

    # Preserve metadata that only lives in our state (never comes from REST)
    for p in positions:
        if p.ticker in existing:
            old = existing[p.ticker]
            p.model_name           = old.model_name
            p.individual_tpsl      = old.individual_tpsl
            p.individual_tp_price  = old.individual_tp_price
            p.individual_sl_price  = old.individual_sl_price
            p.individual_tp_amount = old.individual_tp_amount
            p.individual_sl_amount = old.individual_sl_amount
            p.order_timestamp      = old.order_timestamp
            p.entry_timestamp      = old.entry_timestamp
            p.session_mfe          = old.session_mfe
            p.session_mae          = old.session_mae
            # Preserve WS-sourced unrealized PnL if it is more recent than REST snapshot
            if old.individual_unrealized != 0.0:
                p.individual_unrealized = old.individual_unrealized
        elif not p.entry_timestamp:
            # New position — WS _on_new_position handles real fill time lookup.
            # Set now() as placeholder so hold time shows immediately.
            p.entry_timestamp = datetime.now(timezone.utc).isoformat()

    # Detect closed positions and fire trade_closed events (outside lock — I/O)
    for ticker, old_pos in existing.items():
        if ticker not in new_tickers:
            try:
                from core.event_bus import event_bus, CH_TRADE_CLOSED
                import asyncio as _asyncio
                _asyncio.get_event_loop().create_task(
                    event_bus.publish(CH_TRADE_CLOSED, {
                        "ticker":            ticker,
                        "direction":         old_pos.direction,
                        "approx_close_ms":   int(datetime.now(timezone.utc).timestamp() * 1000),
                    })
                )
            except Exception as _e:
                log.warning(f"Failed to publish trade_closed for {ticker}: {_e}")

    # Atomic list replacement under lock so WS handlers see a consistent list
    async with app_state._lock:
        app_state.positions = sorted(positions, key=lambda p: p.entry_timestamp or "")
        app_state.ws_status.last_update = datetime.now(timezone.utc)

    # Evict cache entries for symbols no longer in any active position.
    # Prevents unbounded memory growth when many symbols rotate through the engine.
    active_tickers = {p.ticker for p in app_state.positions}
    for sym in list(app_state.ohlcv_cache.keys()):
        if sym not in active_tickers:
            del app_state.ohlcv_cache[sym]
    for sym in list(app_state.orderbook_cache.keys()):
        if sym not in active_tickers:
            del app_state.orderbook_cache[sym]
    for sym in list(app_state.mark_price_cache.keys()):
        if sym not in active_tickers:
            del app_state.mark_price_cache[sym]

    # Attach TP/SL from open orders (outside lock — REST call)
    await fetch_open_orders_tpsl()


# ── Open position metadata (entry time, MFE/MAE from history) ────────────────

async def populate_open_position_metadata() -> None:
    """
    For each open position, fetch recent trades to determine entry time,
    then fetch OHLCV to compute true MFE/MAE since position open.
    Called once on startup so MFE/MAE reflect the full hold, not just
    the current engine session.
    """
    loop = asyncio.get_event_loop()
    ex   = get_exchange()

    for i, pos in enumerate(app_state.positions):
        if i > 0:
            await asyncio.sleep(0.5)  # pace REST calls to avoid 429
        try:
            # ── 1. Find position open time from recent trades ────────────
            def _fetch_trades(sym=pos.ticker):
                return ex.fapiPrivateGetUserTrades({"symbol": sym, "limit": 200}) or []

            trades = await loop.run_in_executor(_REST_POOL, _fetch_trades)
            if not trades:
                continue

            # Walk trades newest→oldest to find the opening fill cluster.
            # The position opened when cumulative qty (same side) first
            # reaches the current position amount.
            buy_side = "BUY" if pos.direction == "LONG" else "SELL"
            trades.sort(key=lambda t: int(t.get("time", 0)), reverse=True)

            cumulative = 0.0
            open_time_ms = 0
            for t in trades:
                if t.get("side") != buy_side:
                    break  # hit a trade on the opposite side → position boundary
                cumulative += abs(float(t.get("qty", 0) or 0))
                open_time_ms = int(t.get("time", 0))
                if cumulative >= pos.contract_amount - 1e-8:
                    break

            if not open_time_ms:
                continue

            pos.entry_timestamp = datetime.fromtimestamp(
                open_time_ms / 1000, tz=timezone.utc
            ).isoformat()

            # ── 2. Fetch OHLCV to compute MFE/MAE since open ────────────
            now_ms = int(time.time() * 1000)
            hold_ms = now_ms - open_time_ms

            # Pick timeframe based on hold duration
            if hold_ms < 12 * 3600 * 1000:      # < 12h → 1m candles
                tf = "1m"
            else:                                 # ≥ 12h → 1h candles
                tf = "1h"

            max_price, min_price = await _ohlcv_hl(pos.ticker, open_time_ms, now_ms, tf)
            if max_price is None or min_price is None:
                continue

            if pos.direction == "LONG":
                pos.session_mfe = round((max_price - pos.average) * pos.contract_amount, 2)
                pos.session_mae = round((min_price - pos.average) * pos.contract_amount, 2)
            else:
                pos.session_mfe = round((pos.average - min_price) * pos.contract_amount, 2)
                pos.session_mae = round((pos.average - max_price) * pos.contract_amount, 2)

            log.info(
                "Position metadata: %s open=%s mfe=%.2f mae=%.2f",
                pos.ticker, pos.entry_timestamp, pos.session_mfe, pos.session_mae,
            )
        except Exception as e:
            log.warning("populate_open_position_metadata failed for %s: %s", pos.ticker, e)


# ── Open orders → TP/SL ──────────────────────────────────────────────────────

async def fetch_open_orders_tpsl() -> None:
    """
    Fetch all open orders on Binance Futures and map TAKE_PROFIT / STOP_MARKET
    orders to their respective positions so TP/SL show on the dashboard.
    """
    loop = asyncio.get_event_loop()
    ex   = get_exchange()

    def _fetch():
        return ex.fapiPrivateGetOpenOrders() or []

    try:
        orders = await loop.run_in_executor(_REST_POOL, _fetch)
    except Exception as e:
        app_state.ws_status.add_log(f"Open orders fetch error: {e}")
        return

    # Build per-symbol TP/SL map
    tp_map: Dict[str, dict] = {}   # symbol → best TP order
    sl_map: Dict[str, dict] = {}   # symbol → best SL order

    for o in orders:
        sym   = o.get("symbol", "")
        otype = o.get("type", "")
        stop  = float(o.get("stopPrice", 0) or 0)
        qty   = float(o.get("origQty", 0) or 0)

        if otype in ("TAKE_PROFIT", "TAKE_PROFIT_MARKET"):
            if sym not in tp_map or stop > tp_map[sym]["price"]:
                tp_map[sym] = {"price": stop, "qty": qty}
        elif otype in ("STOP", "STOP_MARKET"):
            if sym not in sl_map or stop < sl_map[sym].get("price", 1e18):
                sl_map[sym] = {"price": stop, "qty": qty}

    # Apply to positions
    for pos in app_state.positions:
        sym = pos.ticker
        if sym in tp_map:
            pos.individual_tpsl     = True
            pos.individual_tp_price = tp_map[sym]["price"]
            tp_notional = tp_map[sym]["price"] * tp_map[sym]["qty"]
            if pos.direction == "LONG":
                pos.individual_tp_usdt = (tp_map[sym]["price"] - pos.average) * tp_map[sym]["qty"]
            else:
                pos.individual_tp_usdt = (pos.average - tp_map[sym]["price"]) * tp_map[sym]["qty"]
        if sym in sl_map:
            pos.individual_tpsl     = True
            pos.individual_sl_price = sl_map[sym]["price"]
            if pos.direction == "LONG":
                pos.individual_sl_usdt = (pos.average - sl_map[sym]["price"]) * sl_map[sym]["qty"]
            else:
                pos.individual_sl_usdt = (sl_map[sym]["price"] - pos.average) * sl_map[sym]["qty"]


# ── OHLCV / ATR ───────────────────────────────────────────────────────────────

async def fetch_ohlcv(symbol: str, timeframe: str = config.ATR_TIMEFRAME,
                      limit: int = config.ATR_FETCH_LIMIT) -> List:
    # Fallback path only — when plugin is connected it streams bars via ohlcv_bar events.
    try:
        from core.platform_bridge import platform_bridge
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
    Fetch OHLCV candles for an exact time window (since_ms → until_ms, ms UTC).
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


_3_MIN_MS  =  3 * 60 * 1_000
_12_HR_MS  = 12 * 60 * 60 * 1_000
_1_HR_MS   =  1 * 60 * 60 * 1_000
_60_SEC_MS =       60 * 1_000
_AGG_BUF   =        1 * 1_000   # 1 s buffer: Binance endTime can be exclusive


async def _agg_extremes(symbol: str, start_ms: int, end_ms: int) -> tuple:
    """
    Stream aggTrades for [start_ms, end_ms] in 1000-trade pages, tracking
    only (max_price, min_price) in O(1) memory.

    Binance note: endTime can be exclusive.  We extend by _AGG_BUF to ensure
    the closing fill (which sets the true extreme for MFE) is never missed.
    Paginated: if a single page returns 1000 trades (volatile market / long
    window), fetches the next page from last_ts+1 until the window is covered.

    Returns (max_price, min_price) or (None, None) on error / no data.
    """
    loop = asyncio.get_event_loop()
    ex   = get_exchange()
    effective_end = end_ms + _AGG_BUF

    max_price: Optional[float] = None
    min_price: Optional[float] = None
    cursor = max(0, start_ms - _AGG_BUF)   # slight lookback for entry fill

    def _fetch(since: int) -> list:
        return ex.fapiPublicGetAggTrades({
            "symbol":    symbol,
            "startTime": since,
            "endTime":   effective_end,
            "limit":     1000,
        }) or []

    try:
        while cursor <= effective_end:
            batch = await loop.run_in_executor(_REST_POOL, _fetch, cursor)
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
    except Exception as e:
        log.warning(f"aggTrades failed for {symbol} [{start_ms},{end_ms}]: {e}")
        return None, None

    return max_price, min_price


async def _ohlcv_hl(
    symbol: str, start_ms: int, end_ms: int, tf: str
) -> tuple:
    """
    Fetch OHLCV and immediately reduce to (max_high, min_low), discarding
    open/close/volume which are never used for MFE/MAE.
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

    Tier 1 — hold < 3 min
      All aggTrades — exact tick-level price extremes.
      Falls back to 1m OHLCV if aggTrades returns nothing.

    Tier 2 — 3 min ≤ hold < 12 hr
      Entry 60 s  : aggTrades (precise)
      Body        : 1m OHLCV H/L  (efficient)
      Exit  60 s  : aggTrades (precise)
      All three sections fetched concurrently via asyncio.gather.

    Tier 3 — hold ≥ 12 hr
      Entry 60 s              : aggTrades
      Entry 1-hour buffer     : 1m OHLCV H/L
      Middle bulk             : 1h OHLCV H/L
      Exit  1-hour buffer     : 1m OHLCV H/L
      Exit  60 s              : aggTrades
      All five sections fetched concurrently.

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
        # Fallback if all three returned None (e.g. very recent data not yet available)
        return await _ohlcv_hl(symbol, open_ms, close_ms, "1m")

    # ── Tier 3: ≥ 12 hr — 5-section hybrid, all concurrent ───────────────────
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

    Inputs are the stitched (max_high, min_low) from fetch_hl_for_trade —
    no candle iteration needed here, just two multiplications.

    LONG:  MFE = (trade_high - entry) * qty   MAE = (trade_low - entry) * qty
    SHORT: MFE = (entry - trade_low)  * qty   MAE = (entry - trade_high) * qty

    Gross (no fee deduction) so MFE/MAE are directly comparable to the gross
    Realized PnL column. MFE >= gross PnL by definition when the closing fill
    is captured in the window.
    MAE >= 0 means the position was in profit for its entire lifetime.
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


# ── Orderbook ─────────────────────────────────────────────────────────────────

async def fetch_orderbook(symbol: str, limit: int = 20) -> Dict:
    # Fallback path only — when plugin is connected it streams depth via depth_snapshot events.
    try:
        from core.platform_bridge import platform_bridge
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


# ── Mark price ────────────────────────────────────────────────────────────────

async def fetch_mark_price(symbol: str) -> float:
    loop = asyncio.get_event_loop()
    ex   = get_exchange()

    def _fetch():
        ticker = ex.fetch_ticker(symbol)
        return float(ticker.get("last") or ticker.get("close") or 0)

    price = await loop.run_in_executor(_REST_POOL, _fetch)
    app_state.mark_price_cache[symbol] = price
    return price


# ── Listen key for user-data WebSocket ───────────────────────────────────────

async def create_listen_key() -> str:
    loop = asyncio.get_event_loop()
    ex   = get_exchange()

    def _create():
        resp = ex.fapiPrivatePostListenKey()
        return resp.get("listenKey", "")

    return await loop.run_in_executor(_REST_POOL, _create)


async def keepalive_listen_key(listen_key: str) -> None:
    loop = asyncio.get_event_loop()
    ex   = get_exchange()

    def _keepalive():
        ex.fapiPrivatePutListenKey({"listenKey": listen_key})

    await loop.run_in_executor(_REST_POOL, _keepalive)


# ── Income history (REALIZED_PNL, FUNDING_FEE, COMMISSION, etc.) ──────────────

async def fetch_income_history(
    income_type: str = "",
    start_ms: Optional[int] = None,
    limit: int = 1000,
) -> List[Dict]:
    """
    Fetch income history from Binance Futures via fapiPrivateGetIncome.
    income_type: "REALIZED_PNL", "FUNDING_FEE", "COMMISSION", "" (all)
    """
    loop = asyncio.get_event_loop()
    ex   = get_exchange()

    def _fetch():
        params: Dict = {"limit": limit}
        if income_type:
            params["incomeType"] = income_type
        if start_ms is not None:
            params["startTime"] = start_ms
        return ex.fapiPrivateGetIncome(params=params) or []

    return await loop.run_in_executor(_REST_POOL, _fetch)


async def fetch_bod_sow_equity() -> None:
    """
    Derive BOD and SOW equity from Binance income history so values survive
    server restarts and reflect real exchange data.

    BOD equity  = current_equity − Σ income(today midnight → now)
    SOW equity  = current_equity − Σ income(Monday midnight → now)
    """
    current_equity = app_state.account_state.total_equity
    if current_equity == 0:
        return

    now_local = datetime.now(TZ_LOCAL)

    # Start of today (local midnight) → UTC ms
    today_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_ms = int(today_midnight.astimezone(timezone.utc).timestamp() * 1000)

    # Start of current week (Monday midnight local) → UTC ms
    days_since_monday = now_local.weekday()  # 0 = Monday
    monday_midnight = (now_local - timedelta(days=days_since_monday)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    monday_ms = int(monday_midnight.astimezone(timezone.utc).timestamp() * 1000)

    try:
        today_income = await fetch_income_history(start_ms=today_ms, limit=1000)
        today_pnl = sum(float(i.get("income", 0)) for i in today_income)
        app_state.account_state.bod_equity = round(current_equity - today_pnl, 4)
        if app_state.account_state.bod_timestamp == "":
            app_state.account_state.bod_timestamp = today_midnight.isoformat()
    except Exception as e:
        app_state.ws_status.add_log(f"BOD equity fetch error: {e}")

    try:
        week_income = await fetch_income_history(start_ms=monday_ms, limit=1000)
        week_pnl = sum(float(i.get("income", 0)) for i in week_income)
        app_state.account_state.sow_equity = round(current_equity - week_pnl, 4)
        if app_state.account_state.sow_timestamp == "":
            app_state.account_state.sow_timestamp = monday_midnight.isoformat()
    except Exception as e:
        app_state.ws_status.add_log(f"SOW equity fetch error: {e}")


async def fetch_income_for_backfill(start_ms: int, end_ms: int) -> List[Dict]:
    """
    Paginated fetch of ALL income types from start_ms to end_ms (ms UTC).
    Advances cursor by last event timestamp + 1 until end_ms is covered
    or Binance returns fewer than 1000 records.
    """
    loop = asyncio.get_event_loop()
    ex   = get_exchange()
    all_events: List[Dict] = []
    cursor = start_ms

    def _fetch(since: int) -> list:
        return ex.fapiPrivateGetIncome(params={
            "startTime": since,
            "endTime":   end_ms,
            "limit":     1000,
        }) or []

    while cursor < end_ms:
        batch = await loop.run_in_executor(_REST_POOL, _fetch, cursor)
        if not batch:
            break
        all_events.extend(batch)
        if len(batch) < 1000:
            break
        cursor = int(batch[-1]["time"]) + 1

    return all_events


async def build_equity_backfill(
    start_ms: int, end_ms: int, current_equity: float
) -> tuple:
    """
    Reconstruct historical equity data points from Binance income events.

    Works backwards from current_equity:
        equity_at_T = current_equity − Σ(income events with time > T)

    Returns (equity_records, cashflow_records):
      - equity_records:   [(ts_ms, equity)]  sorted ascending — all income types
      - cashflow_records: [(ts_ms, amount)]  sorted ascending — TRANSFER events only
                          (positive = deposit, negative = withdrawal)
    Both lists are empty if no income events are found or current_equity is 0.
    """
    if current_equity == 0:
        return [], []

    try:
        events = await fetch_income_for_backfill(start_ms, end_ms)
    except Exception as e:
        log.warning("fetch_income_for_backfill failed: %r", e)
        return [], []

    if not events:
        return [], []

    # Sort descending by time to walk backwards
    events_sorted = sorted(events, key=lambda e: int(e.get("time", 0)), reverse=True)
    type_counts: Dict[str, int] = {}
    transfer_abs_sum = 0.0

    records: List[tuple] = []
    cashflow_records: List[tuple] = []
    running_deduct = 0.0
    for event in events_sorted:
        etype = str(event.get("incomeType", "UNKNOWN"))
        type_counts[etype] = type_counts.get(etype, 0) + 1
        income = float(event.get("income", 0) or 0)
        # Reconstruct trading equity from PnL drivers only.
        # - Include REALIZED_PNL and FUNDING_FEE
        # - Exclude TRANSFER (external cashflow)
        # - Exclude COMMISSION to avoid compounding fee rows on top of realized PnL
        if etype in {"REALIZED_PNL", "FUNDING_FEE"}:
            running_deduct += income
        equity_at_event = round(current_equity - running_deduct, 4)
        # Skip impossible values: negative equity is an artifact of large deposits
        # that occurred after this point in time (pre-funding-event period).
        if equity_at_event < 0:
            continue
        records.append((int(event["time"]), equity_at_event))
        # Collect TRANSFER events (deposits/withdrawals) as cashflow points
        if etype == "TRANSFER":
            transfer_abs_sum += abs(income)
            cashflow_records.append((int(event["time"]), income))

    if not records:
        return [], []

    # Return oldest-first
    records.sort(key=lambda r: r[0])
    cashflow_records.sort(key=lambda r: r[0])

    # ── Trim pre-deposit era ──────────────────────────────────────────────────
    # Backward reconstruction through a large deposit produces very small (but
    # positive) equity values for the period before the deposit, e.g. $2 equity
    # across weeks before a $490 deposit hit.  These points are misleading and
    # create a near-zero flat line followed by a cliff jump on the chart.
    # Strategy: find the first record where equity reaches ≥ 2% of the peak
    # reconstructed value and discard everything before it.
    max_eq = max(eq for _, eq in records)
    trim_threshold = max_eq * 0.02
    first_valid = next(
        (i for i, (_, eq) in enumerate(records) if eq >= trim_threshold), 0
    )
    records = records[first_valid:]

    if not records:
        return [], []

    # ── Fill idle gaps ────────────────────────────────────────────────────────
    # Income events only exist when trades/funding occur.  Inactive periods
    # (no trades, no funding) produce zero data points → missing candles.
    # Bridge any gap > 1 day with daily synthetic points, holding the last
    # known equity constant (no income = no change in closed-position equity).
    _DAY_MS = 86_400_000
    filled: List[tuple] = []
    for i, (ts, eq) in enumerate(records):
        filled.append((ts, eq))
        if i + 1 < len(records):
            next_ts = records[i + 1][0]
            fill_ts = ts + _DAY_MS
            while fill_ts < next_ts - _DAY_MS // 2:
                filled.append((fill_ts, eq))
                fill_ts += _DAY_MS

    max_step = 0.0
    max_step_ts = 0
    for i in range(1, len(filled)):
        step = abs(float(filled[i][1]) - float(filled[i - 1][1]))
        if step > max_step:
            max_step = step
            max_step_ts = int(filled[i][0])

    # Diagnostic-only: compare alternative reconstructions to detect
    # potential double-counting across income types.
    def _alt_max_step(allowed_types: set[str]) -> float:
        rd = 0.0
        alt_records: List[tuple] = []
        for event in events_sorted:
            et = str(event.get("incomeType", ""))
            inc = float(event.get("income", 0) or 0)
            if et in allowed_types:
                rd += inc
            eq = round(current_equity - rd, 4)
            if eq >= 0:
                alt_records.append((int(event.get("time", 0) or 0), eq))
        alt_records.sort(key=lambda r: r[0])
        if len(alt_records) < 2:
            return 0.0
        mx = 0.0
        for i in range(1, len(alt_records)):
            s = abs(float(alt_records[i][1]) - float(alt_records[i - 1][1]))
            if s > mx:
                mx = s
        return round(mx, 4)

    alt_max_step_realized_only = _alt_max_step({"REALIZED_PNL"})
    alt_max_step_realized_plus_funding = _alt_max_step({"REALIZED_PNL", "FUNDING_FEE"})

    # Diagnostic-only: compare timestamp semantics.
    # pre_event: current behavior (value before applying current event at event ts)
    # post_event: value after applying current event at event ts
    def _alt_max_step_post_event(allowed_types: set[str]) -> float:
        rd = 0.0
        alt_records: List[tuple] = []
        for event in events_sorted:
            et = str(event.get("incomeType", ""))
            eq = round(current_equity - rd, 4)
            if eq >= 0:
                alt_records.append((int(event.get("time", 0) or 0), eq))
            inc = float(event.get("income", 0) or 0)
            if et in allowed_types:
                rd += inc
        alt_records.sort(key=lambda r: r[0])
        if len(alt_records) < 2:
            return 0.0
        mx = 0.0
        for i in range(1, len(alt_records)):
            s = abs(float(alt_records[i][1]) - float(alt_records[i - 1][1]))
            if s > mx:
                mx = s
        return round(mx, 4)

    alt_max_step_post_event_realized_plus_funding = _alt_max_step_post_event({"REALIZED_PNL", "FUNDING_FEE"})

    def _alt_summary(allowed_types: set[str]) -> Dict[str, float]:
        rd = 0.0
        alt_records: List[tuple] = []
        for event in events_sorted:
            et = str(event.get("incomeType", ""))
            eq = round(current_equity - rd, 4)
            if eq >= 0:
                alt_records.append((int(event.get("time", 0) or 0), eq))
            inc = float(event.get("income", 0) or 0)
            if et in allowed_types:
                rd += inc
        alt_records.sort(key=lambda r: r[0])
        if not alt_records:
            return {"count": 0, "first_eq": 0.0, "last_eq": 0.0, "range": 0.0, "max_step": 0.0}
        mx = 0.0
        for i in range(1, len(alt_records)):
            s = abs(float(alt_records[i][1]) - float(alt_records[i - 1][1]))
            if s > mx:
                mx = s
        first_eq = float(alt_records[0][1])
        last_eq = float(alt_records[-1][1])
        return {
            "count": len(alt_records),
            "first_eq": round(first_eq, 4),
            "last_eq": round(last_eq, 4),
            "range": round(abs(last_eq - first_eq), 4),
            "max_step": round(mx, 4),
        }

    alt_summary_with_commission = _alt_summary({"REALIZED_PNL", "FUNDING_FEE", "COMMISSION"})
    alt_summary_no_commission = _alt_summary({"REALIZED_PNL", "FUNDING_FEE"})
    top_non_transfer_events = sorted(
        [
            {
                "time": int(e.get("time", 0) or 0),
                "incomeType": str(e.get("incomeType", "")),
                "income": float(e.get("income", 0) or 0),
            }
            for e in events_sorted
            if str(e.get("incomeType", "")) != "TRANSFER"
        ],
        key=lambda e: abs(float(e["income"])),
        reverse=True,
    )[:5]
    return filled, cashflow_records


async def fetch_user_trades(symbol: str, limit: int = 500) -> List[Dict]:
    """Fetch recent trade fills for a symbol from Binance Futures userTrades."""
    loop = asyncio.get_event_loop()
    ex   = get_exchange()

    def _fetch():
        return ex.fapiPrivateGetUserTrades(params={"symbol": symbol, "limit": limit}) or []

    try:
        return await loop.run_in_executor(_REST_POOL, _fetch)
    except Exception as e:
        app_state.ws_status.add_log(f"User trades fetch error ({symbol}): {e}")
        return []


async def fetch_exchange_trade_history(limit: int = 200) -> None:
    """
    Fetch recent realized-PnL income entries from Binance, then augment each
    row with direction, exit_price, entry_price (computed), and fee (from
    COMMISSION income events matched by tradeId).  Stores newest-first.

    Fallback path only — when the Quantower plugin is connected, exchange_history
    is populated by the plugin's historical_fill events instead. Skipping the
    Binance fetch avoids duplicate / divergent rows.
    """
    try:
        from core.platform_bridge import platform_bridge
        if platform_bridge.is_connected:
            log.debug(
                "fetch_exchange_trade_history: plugin connected — skipping "
                "Binance backfill (Quantower is canonical)"
            )
            return
    except Exception:
        pass

    try:
        # Primary: REALIZED_PNL events
        raw_pnl = await fetch_income_history(income_type="REALIZED_PNL", limit=limit)

        # Secondary: COMMISSION events keyed by tradeId → fee amount (always positive)
        raw_commission = await fetch_income_history(income_type="COMMISSION", limit=limit)
        fee_map: Dict[str, float] = {}
        for c in raw_commission:
            tid = str(c.get("tradeId", ""))
            if tid:
                fee_map[tid] = abs(float(c.get("income", 0) or 0))

        # Funding fees: FUNDING_FEE events grouped by symbol with timestamps
        raw_funding = await fetch_income_history(income_type="FUNDING_FEE", limit=limit)
        funding_by_symbol: Dict[str, List[tuple]] = {}
        for f in raw_funding:
            sym = f.get("symbol", "")
            if sym:
                funding_by_symbol.setdefault(sym, []).append(
                    (int(f.get("time", 0)), abs(float(f.get("income", 0) or 0)))
                )

        # Tertiary: userTrades per symbol → exit price, direction, qty, open_time
        # Fetch all symbols concurrently (max 5 in-flight) to avoid N×latency cost.
        symbols = list({r.get("symbol", "") for r in raw_pnl if r.get("symbol")})
        trade_lookup: Dict[str, Dict] = {}
        fills_by_symbol: Dict[str, List[Dict]] = {}

        _sym_sem = asyncio.Semaphore(5)

        async def _fetch_sym(s: str):
            async with _sym_sem:
                return s, await fetch_user_trades(s, limit=500)

        _sym_results = await asyncio.gather(
            *[_fetch_sym(s) for s in symbols], return_exceptions=True
        )
        for _res in _sym_results:
            if isinstance(_res, BaseException):
                log.warning("fetch_user_trades failed for a symbol: %r", _res)
                continue
            sym, fills = _res
            fills_by_symbol[sym] = fills
            for t in fills:
                trade_lookup[str(t.get("id", ""))] = t

        # Augment each PnL event
        for r in raw_pnl:
            tid      = str(r.get("tradeId", ""))
            trade    = trade_lookup.get(tid, {})
            sym      = r.get("symbol", "")
            close_ms = int(r.get("time", 0))

            side       = trade.get("side", "")
            direction  = "LONG" if side == "SELL" else ("SHORT" if side == "BUY" else "")
            exit_price = float(trade.get("price", 0) or 0)
            qty        = float(trade.get("qty",   0) or 0)
            income_val = float(r.get("income", 0) or 0)

            # entry_price derived from: PnL = (exit-entry)*qty (LONG) or (entry-exit)*qty (SHORT)
            if direction == "LONG" and exit_price > 0 and qty > 0:
                entry_price = exit_price - income_val / qty
            elif direction == "SHORT" and exit_price > 0 and qty > 0:
                entry_price = exit_price + income_val / qty
            else:
                entry_price = 0.0

            # open_time: oldest opening-direction fill of the CURRENT leg only.
            # We bound the search below by the most recent closing-direction fill
            # before this close — that marks when the previous leg ended.
            # Without this bound, min() would grab fills from prior unrelated legs
            # (e.g. a STOUSDT position opened months ago at a much higher price),
            # causing the OHLCV window to span historical candles and corrupt MFE/MAE.
            open_side  = "BUY"  if direction == "LONG"  else ("SELL" if direction == "SHORT" else "")
            close_side = "SELL" if direction == "LONG"  else ("BUY"  if direction == "SHORT" else "")
            open_time  = 0
            open_fills: List[Dict] = []   # always defined; populated below if direction known
            if open_side:
                sym_fills = fills_by_symbol.get(sym, [])
                # Most recent closing fill before this close = end of the prior leg
                prev_close_fills = [t for t in sym_fills
                                    if t.get("side") == close_side
                                    and int(t.get("time", 0)) < close_ms]
                prev_leg_end_ms = max(
                    (int(t.get("time", 0)) for t in prev_close_fills), default=0
                )
                # Opening fills of the current leg must be after the prior leg ended
                open_fills = [t for t in sym_fills
                              if t.get("side") == open_side
                              and prev_leg_end_ms < int(t.get("time", 0)) < close_ms]
                if not open_fills:
                    # Partial-close scenario: prev_leg_end_ms points to a partial close
                    # of the current position (not a full leg boundary), so no opening
                    # fills appear in the strict window.  Fall back to a 7-day cap —
                    # wide enough to find the original entry but short enough to exclude
                    # historical positions from months ago.
                    _SEVEN_DAYS_MS = 7 * 24 * 3600 * 1000
                    open_fills = [t for t in sym_fills
                                  if t.get("side") == open_side
                                  and close_ms - _SEVEN_DAYS_MS < int(t.get("time", 0)) < close_ms]
                if open_fills:
                    open_time = int(min(open_fills, key=lambda t: int(t.get("time", 0)))
                                    .get("time", 0))

            # closed notional = exit_price × qty
            notional = round(exit_price * qty, 2) if exit_price and qty else 0.0

            # Entry commission: sum from all opening fills
            entry_fee = sum(abs(float(f.get("commission", 0) or 0)) for f in open_fills)
            # Funding fees: all FUNDING_FEE events for this symbol within the hold window
            funding_fee = sum(
                amt for ts, amt in funding_by_symbol.get(sym, [])
                if open_time and open_time <= ts <= close_ms
            )
            # Exit commission: COMMISSION income event matched by closing tradeId
            exit_fee = fee_map.get(tid, 0.0)

            r["direction"]   = direction
            r["exit_price"]  = exit_price
            r["entry_price"] = round(entry_price, 6) if entry_price else 0.0
            r["fee"]         = round(entry_fee + funding_fee + exit_fee, 6)
            r["qty"]         = qty
            r["open_time"]   = open_time
            r["notional"]    = notional
            r["trade_key"]   = f"{r.get('time', '')}_{r.get('symbol', '')}_{r.get('incomeType', '')}"

        raw_pnl.sort(key=lambda x: x.get("time", 0), reverse=True)
        app_state.exchange_trade_history = raw_pnl

        try:
            from core.database import db
            await db.upsert_exchange_history(raw_pnl, account_id=app_state.active_account_id)
        except Exception as e:
            app_state.ws_status.add_log(f"exchange_history DB upsert error: {e}")
    except Exception as e:
        app_state.ws_status.add_log(f"Exchange trade history error: {e}")


async def fetch_funding_rates(symbols: List[str]) -> Dict[str, Dict]:
    """
    Fetch current funding rate + next funding time for each symbol.
    Single batch call to /fapi/v1/premiumIndex (no symbol param = all symbols).

    Returns:
        {symbol: {"funding_rate": float, "next_funding_time": int, "mark_price": float}}
    """
    if not symbols:
        return {}

    exchange = get_exchange()
    loop     = asyncio.get_event_loop()
    wanted   = set(symbols)

    try:
        raw_list = await loop.run_in_executor(
            _REST_POOL,
            lambda: exchange.fapiPublicGetPremiumIndex() or [],
        )
    except Exception as e:
        log.warning("fetch_funding_rates batch failed: %r", e)
        return {s: {"funding_rate": 0.0, "next_funding_time": 0, "mark_price": 0.0} for s in symbols}

    results: Dict[str, Dict] = {}
    for raw in raw_list:
        sym = raw.get("symbol", "")
        if sym in wanted:
            results[sym] = {
                "funding_rate":      float(raw.get("lastFundingRate", 0) or 0),
                "next_funding_time": int(raw.get("nextFundingTime",   0) or 0),
                "mark_price":        float(raw.get("markPrice",        0) or 0),
            }
    # Fill missing
    for s in symbols:
        if s not in results:
            results[s] = {"funding_rate": 0.0, "next_funding_time": 0, "mark_price": 0.0}
    return results
