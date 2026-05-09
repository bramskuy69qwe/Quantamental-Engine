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
from core.database import db
from core.adapters import get_adapter, to_position_info, map_market_type
from core.adapters.protocols import ExchangeAdapter

log = logging.getLogger("exchange")


# ── RL-1: Rate-limit detection + global pause ────────────────────────────────

def handle_rate_limit_error(exc: Exception) -> None:
    """Parse 429/418 from CCXT exceptions, set rate_limited_until on WSStatus.

    Called by any REST caller that catches DDoSProtection or RateLimitExceeded.
    Parses Binance 418 "banned until <epoch_ms>" for precise backoff; falls back
    to 120s default pause for 429 without a specific timestamp.
    """
    import re
    msg = str(exc)
    ws = app_state.ws_status

    # Try to parse "banned until <epoch_ms>" from 418 responses
    match = re.search(r"banned until (\d+)", msg)
    if match:
        epoch_ms = int(match.group(1))
        ws.rate_limited_until = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
        log.error("RL-1: IP banned until %s — all REST calls paused", ws.rate_limited_until)
    else:
        # 429 without specific ban time — back off 120 seconds
        ws.rate_limited_until = datetime.now(timezone.utc) + timedelta(seconds=120)
        log.warning("RL-1: 429 detected — REST calls paused for 120s")

    ws.add_log(f"Rate limited until {ws.rate_limited_until.strftime('%H:%M:%S UTC')}")


def is_rate_limited() -> bool:
    """Check if we're currently in a rate-limit backoff period."""
    return app_state.ws_status.is_rate_limited


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
    """Fetch account balance, fees, and update account_state through DataCache."""
    adapter = _get_adapter()
    na = await adapter.fetch_account()

    ts_ms = int(time.time() * 1000)
    await app_state._data_cache.apply_account_update_rest(na, ts_ms)

    # Exchange info: fee tier + live commission rates (outside lock — safe)
    exi = app_state.exchange_info
    exi.account_id = na.fee_tier
    if na.maker_fee > 0:
        exi.maker_fee = na.maker_fee
    if na.taker_fee > 0:
        exi.taker_fee = na.taker_fee
    if na.maker_fee > 0 or na.taker_fee > 0:
        from core.account_registry import account_registry
        await account_registry.update_account_fees(
            app_state.active_account_id,
            na.maker_fee if na.maker_fee > 0 else exi.maker_fee,
            na.taker_fee if na.taker_fee > 0 else exi.taker_fee,
        )

    app_state.ws_status.last_update = datetime.now(timezone.utc)


# ── Positions ────────────────────────────────────────────────────────────────


async def fetch_positions(force: bool = False) -> None:
    """Fetch open positions via adapter and update app_state through DataCache.

    All conflict resolution, metadata preservation, closure detection, and
    event publishing are handled atomically inside DataCache — no TOCTOU race.

    Set force=True for fill-triggered refreshes that must always be accepted.
    """
    from core.data_cache import UpdateSource

    if app_state._data_cache is None:
        log.warning("fetch_positions: DataCache not yet initialized — skipping")
        return

    adapter = _get_adapter()
    normalized = await adapter.fetch_positions()

    positions = [
        to_position_info(np, sector=config.get_sector(np.symbol))
        for np in normalized
    ]

    ts_ms = int(time.time() * 1000)
    result = await app_state._data_cache.apply_position_snapshot(
        UpdateSource.REST, positions, ts_ms, force=force,
    )

    # Always mark that REST ran (even if DataCache rejected the snapshot)
    app_state.ws_status.last_update = datetime.now(timezone.utc)

    if result is None:
        log.debug("fetch_positions: DataCache rejected REST update (WS is fresher)")
    else:
        # Evict cache entries for symbols no longer in any active position
        active_tickers = {p.ticker for p in app_state.positions}
        app_state._data_cache.evict_symbol_caches(active_tickers)

    # Always attach TP/SL from open orders — even if position snapshot was
    # rejected, orders can change independently (user edits TP/SL on exchange)
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

            entry_side = "BUY" if pos.direction == "LONG" else "SELL"
            trades.sort(key=lambda t: t.timestamp_ms, reverse=True)

            cumulative = 0.0
            open_time_ms = 0
            for t in trades:
                if t.side != entry_side:
                    continue  # skip interleaved trades from other direction
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

            # ── 3. Populate fees from fills DB ─────────────────────────────
            if pos.position_id:
                try:
                    fees = await db.get_position_fees(
                        app_state.active_account_id, pos.position_id,
                    )
                    pos.individual_fees = fees
                except Exception:
                    pass  # best-effort — fees table may be empty on first run
        except (ccxt.RateLimitExceeded, ccxt.DDoSProtection) as e:
            handle_rate_limit_error(e)
            log.warning("Rate limit hit in populate_open_position_metadata for %s: %s", pos.ticker, e)
            return
        except Exception as e:
            log.warning("populate_open_position_metadata failed for %s: %s", pos.ticker, e)


# ── Open orders -> TP/SL ────────────────────────────────────────────────────

async def fetch_open_orders_tpsl() -> None:
    """
    Fetch all open orders and map take_profit / stop_loss orders to their
    respective positions so TP/SL show on the dashboard.

    When the Quantower plugin is connected, TP/SL comes from the orders DB
    via OrderManager (fed by order_snapshot events). REST is only used when
    the plugin is disconnected.
    """
    from core.platform_bridge import platform_bridge
    if platform_bridge.is_connected:
        platform_bridge.order_manager.enrich_positions_tpsl(app_state.positions)
        return

    adapter = _get_adapter()

    try:
        orders = await adapter.fetch_open_orders()
    except (ccxt.RateLimitExceeded, ccxt.DDoSProtection) as e:
        handle_rate_limit_error(e)
        log.warning("Rate limit hit in fetch_open_orders_tpsl: %s", e)
        return
    except Exception as e:
        app_state.ws_status.add_log(f"Open orders fetch error: {e}")
        return

    # Key by (symbol, position_direction) so long+short on same symbol get distinct TP/SL.
    # TP order for LONG is a SELL, TP for SHORT is a BUY; SL mirrors the same logic.
    tp_map: Dict[tuple, dict] = {}
    sl_map: Dict[tuple, dict] = {}

    for o in orders:
        sym = o.symbol
        # Use position_side directly (reliable in hedge mode).
        # Fallback to side-based inference only if position_side is empty.
        pos_dir = o.position_side
        if not pos_dir:
            pos_dir = "LONG" if o.side == "SELL" else "SHORT"
        key = (sym, pos_dir)
        if o.order_type == "take_profit":
            if key not in tp_map or o.stop_price > tp_map[key]["price"]:
                tp_map[key] = {"price": o.stop_price, "qty": o.quantity}
        elif o.order_type == "stop_loss":
            if key not in sl_map or o.stop_price < sl_map[key].get("price", 1e18):
                sl_map[key] = {"price": o.stop_price, "qty": o.quantity}

    for pos in app_state.positions:
        key = (pos.ticker, pos.direction)
        if key in tp_map:
            pos.individual_tpsl     = True
            pos.individual_tp_price = tp_map[key]["price"]
            if pos.direction == "LONG":
                pos.individual_tp_usdt = (tp_map[key]["price"] - pos.average) * tp_map[key]["qty"]
            else:
                pos.individual_tp_usdt = (pos.average - tp_map[key]["price"]) * tp_map[key]["qty"]
        if key in sl_map:
            pos.individual_tpsl     = True
            pos.individual_sl_price = sl_map[key]["price"]
            if pos.direction == "LONG":
                pos.individual_sl_usdt = (pos.average - sl_map[key]["price"]) * sl_map[key]["qty"]
            else:
                pos.individual_sl_usdt = (sl_map[key]["price"] - pos.average) * sl_map[key]["qty"]


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
