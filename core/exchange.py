"""
CCXT-based REST wrapper — exchange-agnostic via adapter layer.

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
from core.adapters import get_adapter, to_position_info, map_market_type
from core.adapters.protocols import ExchangeAdapter

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


def _get_adapter() -> ExchangeAdapter:
    """Return the adapter for the currently active account."""
    from core.account_registry import account_registry
    from core.exchange_factory import exchange_factory
    creds = account_registry.get_active_sync()
    if not creds or not creds.get("api_key"):
        raise RuntimeError("No active account credentials available")
    return exchange_factory.get_adapter(
        creds["id"],
        creds["api_key"],
        creds["api_secret"],
        creds.get("exchange", "binance"),
        creds.get("market_type", "future"),
    )


# ── Exchange info ────────────────────────────────────────────────────────────

async def fetch_exchange_info() -> None:
    """Update exchange_info on app_state (latency, server time, name, fees)."""
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
    # Also sync to ws_status so the WS indicator shows a value immediately
    app_state.ws_status.latency_ms = info.latency_ms
    info.server_time = datetime.fromtimestamp(
        server_time / 1000, tz=timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")
    # Fees: use per-account values from registry, then fallback to config defaults
    from core.account_registry import account_registry
    maker, taker = account_registry.get_account_fees(app_state.active_account_id)
    if info.maker_fee == 0.0:
        info.maker_fee = maker
    if info.taker_fee == 0.0:
        info.taker_fee = taker


# ── Account & balance ────────────────────────────────────────────────────────

async def fetch_account() -> None:
    """Fetch account balance, fees, and update account_state via adapter."""
    adapter = _get_adapter()
    na = await adapter.fetch_account()

    async with app_state._lock:
        acc = app_state.account_state
        acc.total_equity       = na.total_equity
        acc.available_margin   = na.available_margin
        acc.total_unrealized   = na.unrealized_pnl
        acc.total_margin_used  = na.initial_margin
        acc.total_margin_ratio = na.maint_margin
        acc.balance_usdt       = na.total_equity

        # Set BOD / SOW equity on first fetch if not set
        if acc.bod_equity == 0.0:
            acc.bod_equity       = acc.total_equity
            acc.max_total_equity = acc.total_equity
            acc.min_total_equity = acc.total_equity
            app_state.portfolio.dd_baseline_equity = acc.total_equity
        if acc.sow_equity == 0.0:
            acc.sow_equity = acc.total_equity

        # Exchange info: fee tier + live commission rates
        exi = app_state.exchange_info
        exi.account_id = na.fee_tier
        if na.maker_fee > 0:
            exi.maker_fee = na.maker_fee
        if na.taker_fee > 0:
            exi.taker_fee = na.taker_fee
        # Persist live fees to DB so load_params() doesn't revert to stale values
        if na.maker_fee > 0 or na.taker_fee > 0:
            from core.account_registry import account_registry
            await account_registry.update_account_fees(
                app_state.active_account_id,
                na.maker_fee if na.maker_fee > 0 else exi.maker_fee,
                na.taker_fee if na.taker_fee > 0 else exi.taker_fee,
            )

        app_state.ws_status.last_update    = datetime.now(timezone.utc)


# ── Positions ────────────────────────────────────────────────────────────────


async def fetch_positions() -> None:
    """Fetch open positions via adapter and update app_state."""
    adapter = _get_adapter()
    normalized = await adapter.fetch_positions()

    positions = [
        to_position_info(np, sector=config.get_sector(np.symbol))
        for np in normalized
    ]

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

    adapter = _get_adapter()

    for i, pos in enumerate(app_state.positions):
        if i > 0:
            await asyncio.sleep(0.5)  # pace REST calls to avoid 429
        try:
            # ── 1. Find position open time from recent trades ────────────
            trades = await adapter.fetch_user_trades(pos.ticker, limit=200)
            if not trades:
                continue

            buy_side = "BUY" if pos.direction == "LONG" else "SELL"
            trades.sort(key=lambda t: t.timestamp_ms, reverse=True)

            cumulative = 0.0
            open_time_ms = 0
            for t in trades:
                if t.side != buy_side:
                    break
                cumulative += abs(t.quantity)
                open_time_ms = t.timestamp_ms
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
    Fetch all open orders and map take_profit / stop_loss orders to their
    respective positions so TP/SL show on the dashboard.
    """
    adapter = _get_adapter()

    try:
        orders = await adapter.fetch_open_orders()
    except Exception as e:
        app_state.ws_status.add_log(f"Open orders fetch error: {e}")
        return

    tp_map: Dict[str, dict] = {}
    sl_map: Dict[str, dict] = {}

    for o in orders:
        sym = o.symbol
        if o.order_type == "take_profit":
            if sym not in tp_map or o.stop_price > tp_map[sym]["price"]:
                tp_map[sym] = {"price": o.stop_price, "qty": o.quantity}
        elif o.order_type == "stop_loss":
            if sym not in sl_map or o.stop_price < sl_map[sym].get("price", 1e18):
                sl_map[sym] = {"price": o.stop_price, "qty": o.quantity}

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
    adapter = _get_adapter()
    return await adapter.create_listen_key()


async def keepalive_listen_key(listen_key: str) -> None:
    adapter = _get_adapter()
    await adapter.keepalive_listen_key(listen_key)


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
