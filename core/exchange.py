"""
CCXT-based REST wrapper for Binance USD-M Futures.

Core functions: exchange init, account, positions, TP/SL, listen key.
Market data (OHLCV, orderbook, mark price) -> exchange_market.py
Income/equity/trade history -> exchange_income.py
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
from core.event_bus import event_bus, CH_TRADE_CLOSED
from core.database import db

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
        from core.account_registry import account_registry  # late import: startup ordering
        from core.exchange_factory import exchange_factory  # late import: startup ordering
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


# ── Exchange info ────────────────────────────────────────────────────────────

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
        from core.account_registry import account_registry  # late import: startup ordering
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


# ── Account & balance ────────────────────────────────────────────────────────

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


# ── Positions ────────────────────────────────────────────────────────────────


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
            p.entry_timestamp = datetime.now(timezone.utc).isoformat()

    # Detect closed positions and fire trade_closed events (outside lock — I/O)
    for ticker, old_pos in existing.items():
        if ticker not in new_tickers:
            try:
                asyncio.get_event_loop().create_task(
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


# ── Open position metadata (entry time, MFE/MAE from history) ───────────────

async def populate_open_position_metadata() -> None:
    """
    For each open position, fetch recent trades to determine entry time,
    then fetch OHLCV to compute true MFE/MAE since position open.
    Called once on startup so MFE/MAE reflect the full hold, not just
    the current engine session.
    """
    from core.exchange_market import _ohlcv_hl

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

            buy_side = "BUY" if pos.direction == "LONG" else "SELL"
            trades.sort(key=lambda t: int(t.get("time", 0)), reverse=True)

            cumulative = 0.0
            open_time_ms = 0
            for t in trades:
                if t.get("side") != buy_side:
                    break
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

            if hold_ms < 12 * 3600 * 1000:
                tf = "1m"
            else:
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


# ── Open orders -> TP/SL ────────────────────────────────────────────────────

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

    tp_map: Dict[str, dict] = {}
    sl_map: Dict[str, dict] = {}

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

    for pos in app_state.positions:
        sym = pos.ticker
        if sym in tp_map:
            pos.individual_tpsl     = True
            pos.individual_tp_price = tp_map[sym]["price"]
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


# ── Listen key for user-data WebSocket ──────────────────────────────────────

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


# ── Re-exports from split modules (backward compatibility) ───────────────────
# These modules were extracted from this file; all existing import paths
# (e.g. `from core.exchange import fetch_ohlcv`) continue to work.
from core.exchange_market import (  # noqa: E402, F401
    fetch_ohlcv, fetch_ohlcv_window, fetch_hl_for_trade, calc_mfe_mae,
    fetch_orderbook, fetch_mark_price,
)
from core.exchange_income import (  # noqa: E402, F401
    fetch_income_history, fetch_bod_sow_equity, fetch_income_for_backfill,
    build_equity_backfill, fetch_user_trades, fetch_exchange_trade_history,
    fetch_funding_rates,
)
