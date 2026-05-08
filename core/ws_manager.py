"""
WebSocket manager — exchange-agnostic via adapter layer.

Handles:
  - User data stream  (account / position updates)
  - Kline streams     (for ATR on all active positions)
  - Book ticker/depth streams (for active calculator ticker)
  - Heartbeat / reconnection with exponential back-off
  - Fallback to REST polling after WS_FALLBACK_TIMEOUT seconds stale
"""
from __future__ import annotations
import asyncio
import json
import time
import math
import logging
from datetime import datetime, timezone
from typing import Optional

import websockets

import config
from core.state import app_state
from core.event_bus import event_bus
from core.exchange import (
    get_exchange, _REST_POOL,
    fetch_account, fetch_positions, fetch_orderbook, fetch_ohlcv,
    create_listen_key, keepalive_listen_key,
    _get_adapter,
)

log = logging.getLogger("ws_manager")


def _get_ws_adapter():
    """Return the WS adapter for the currently active account."""
    from core.account_registry import account_registry
    from core.exchange_factory import exchange_factory
    creds = account_registry.get_active_sync()
    if not creds:
        return None
    return exchange_factory.get_ws_adapter(
        creds["id"],
        creds.get("exchange", "binance"),
        creds.get("market_type", "future"),
    )


# ── State ─────────────────────────────────────────────────────────────────────
_listen_key: Optional[str]        = None
_user_ws_task:    Optional[asyncio.Task] = None
_market_ws_task:  Optional[asyncio.Task] = None
_keepalive_task:  Optional[asyncio.Task] = None
_fallback_task:   Optional[asyncio.Task] = None
_calculator_symbol: Optional[str]        = None   # symbol currently open in calc
_last_ws_position_update: float = 0.0   # monotonic ts of last WS position change
_stopping: bool = False   # set by stop() to prevent reconnect tasks after teardown


# ── User data stream ──────────────────────────────────────────────────────────

async def _apply_account_update(msg: dict) -> None:
    """Apply ACCOUNT_UPDATE event through DataCache (single writer).
    Side effects (stream restart, portfolio recalc) fire outside the lock."""
    global _last_ws_position_update
    from core.data_cache import UpdateSource

    if app_state._data_cache is None:
        log.warning("_apply_account_update: DataCache not yet initialized — skipping")
        return

    ws_adapter = _get_ws_adapter()

    # Parse via adapter (exchange-agnostic)
    if ws_adapter:
        balances, norm_positions = ws_adapter.parse_account_update(msg)
    else:
        balances, norm_positions = {}, []

    event_time_ms = ws_adapter.get_event_time_ms(msg) if ws_adapter else int(time.time() * 1000)

    result = await app_state._data_cache.apply_position_update_incremental(
        UpdateSource.WS_USER, norm_positions, balances, event_time_ms,
    )

    if result.changed and norm_positions:
        _last_ws_position_update = time.monotonic()

    # Side effects outside DataCache lock
    if not norm_positions:
        return
    if result.closed_syms or result.new_syms:
        asyncio.create_task(restart_market_streams())
    for sym in result.new_syms:
        asyncio.create_task(_on_new_position(sym))
    # recalculate_portfolio() now called inside DataCache.apply_position_update_incremental()


async def _handle_user_event(msg: dict) -> None:
    """Parse and apply a user-data stream event via WS adapter."""
    ws_adapter = _get_ws_adapter()
    ev = ws_adapter.get_event_type(msg) if ws_adapter else msg.get("e", "")
    ws = app_state.ws_status

    # Real-time latency: lag between exchange event time and now
    event_time_ms = ws_adapter.get_event_time_ms(msg) if ws_adapter else msg.get("E", 0)
    if event_time_ms:
        ws.latency_ms = round(time.time() * 1000 - event_time_ms, 1)

    if ev == "ACCOUNT_UPDATE":
        await _apply_account_update(msg)

    elif ev == "ORDER_TRADE_UPDATE":
        await _apply_order_update(msg, ws_adapter)

    ws.last_update = datetime.now(timezone.utc)
    await event_bus.publish(
        "risk:account_updated",
        {"event": ev, "ts": datetime.now(timezone.utc).isoformat()},
    )


# ── TP/SL types that map to position stop prices ────────────────────────────
_TPSL_TYPES = {"take_profit", "stop_loss"}


async def _apply_order_update(msg: dict, ws_adapter) -> None:
    """Handle ORDER_TRADE_UPDATE: real-time TP/SL enrichment + fill detection.

    Fires for every order event: placement, modification, fill, cancel.
    TP/SL orders update position fields immediately (sub-second).
    Fills trigger a position refresh via REST for consistency.
    """
    if not ws_adapter or not hasattr(ws_adapter, "parse_order_update"):
        return

    order = ws_adapter.parse_order_update(msg)
    execution_type = msg.get("o", {}).get("x", "")  # NEW, CANCELED, TRADE, AMENDMENT, EXPIRED

    # ── TP/SL order → update matching position in real-time ──────────────
    if order.order_type in _TPSL_TYPES:
        # Use position_side directly from WS payload (reliable in hedge mode).
        # Fallback to side-based inference only if position_side is empty.
        pos_dir = order.position_side
        if not pos_dir:
            pos_dir = "LONG" if order.side == "SELL" else "SHORT"

        for pos in app_state.positions:
            if pos.ticker != order.symbol or pos.direction != pos_dir:
                continue

            if execution_type in ("NEW", "AMENDMENT"):
                # TP/SL placed or modified
                if order.order_type == "take_profit":
                    pos.individual_tpsl = True
                    pos.individual_tp_price = order.stop_price
                    pos.individual_tp_amount = order.quantity
                    if pos.direction == "LONG":
                        pos.individual_tp_usdt = (order.stop_price - pos.average) * order.quantity
                    else:
                        pos.individual_tp_usdt = (pos.average - order.stop_price) * order.quantity
                elif order.order_type == "stop_loss":
                    pos.individual_tpsl = True
                    pos.individual_sl_price = order.stop_price
                    pos.individual_sl_amount = order.quantity
                    if pos.direction == "LONG":
                        pos.individual_sl_usdt = (pos.average - order.stop_price) * order.quantity
                    else:
                        pos.individual_sl_usdt = (order.stop_price - pos.average) * order.quantity

            elif execution_type in ("CANCELED", "EXPIRED"):
                # TP/SL canceled — clear the corresponding price
                if order.order_type == "take_profit":
                    pos.individual_tp_price = 0.0
                    pos.individual_tp_amount = 0.0
                    pos.individual_tp_usdt = 0.0
                elif order.order_type == "stop_loss":
                    pos.individual_sl_price = 0.0
                    pos.individual_sl_amount = 0.0
                    pos.individual_sl_usdt = 0.0
                # If both TP and SL are now 0, clear the flag
                if pos.individual_tp_price == 0.0 and pos.individual_sl_price == 0.0:
                    pos.individual_tpsl = False
            break  # found the matching position

    # ── Fill → refresh positions so new fills appear immediately ─────────
    if execution_type == "TRADE":
        asyncio.create_task(_refresh_positions_after_fill())

    # ── SR-1: Persist order via OrderManager (validates transition + timestamp)
    try:
        from core.platform_bridge import platform_bridge
        order_dict = {
            "account_id":         app_state.active_account_id,
            "exchange_order_id":  order.exchange_order_id,
            "terminal_order_id":  "",
            "client_order_id":    order.client_order_id,
            "symbol":             order.symbol,
            "side":               order.side,
            "order_type":         order.order_type,
            "status":             order.status,
            "price":              order.price,
            "stop_price":         order.stop_price,
            "quantity":           order.quantity,
            "filled_qty":         order.filled_qty,
            "avg_fill_price":     order.avg_fill_price,
            "reduce_only":        order.reduce_only,
            "time_in_force":      order.time_in_force,
            "position_side":      order.position_side,
            "exchange_position_id": "",
            "terminal_position_id": "",
            "source":             "binance_ws",
            "created_at_ms":      order.created_at_ms,
            "updated_at_ms":      order.updated_at_ms,
        }
        await platform_bridge.order_manager.process_order_update(
            app_state.active_account_id, order_dict,
        )
    except Exception as e:
        log.debug("WS order persist skipped: %s", e)


async def _on_new_position(sym: str) -> None:
    """Background: restart market streams + fetch real entry time for a new position."""
    try:
        await restart_market_streams()
    except Exception:
        pass
    # Fetch real fill timestamp from exchange trades
    try:
        adapter = _get_adapter()
        trades = await adapter.fetch_user_trades(sym, limit=50)
        if trades:
            for pos in app_state.positions:
                if pos.ticker != sym:
                    continue
                entry_side = "BUY" if pos.direction == "LONG" else "SELL"
                sorted_trades = sorted(trades, key=lambda t: t.timestamp_ms, reverse=True)
                cum = 0.0
                for t in sorted_trades:
                    if t.side != entry_side:
                        continue  # skip interleaved trades from other direction
                    cum += abs(t.quantity)
                    if cum >= pos.contract_amount - 1e-8:
                        pos.entry_timestamp = datetime.fromtimestamp(
                            t.timestamp_ms / 1000, tz=timezone.utc
                        ).isoformat()
                        break
    except Exception as e:
        log.warning("_on_new_position trade lookup failed for %s: %s", sym, e)


async def _refresh_positions_after_fill() -> None:
    try:
        await fetch_account()
        await fetch_positions(force=True)
        # force=True: fill-triggered refresh must always be accepted,
        # even if WS updated recently (avoids 30s delay on position close).
    except Exception as e:
        app_state.ws_status.add_log(f"Post-fill refresh error: {e}")


async def _user_data_loop(listen_key: str, attempt: int = 0) -> None:
    # Gate: plugin provides account/position truth — no need for Binance user-data WS.
    # Sleep and retry until the plugin disconnects, then re-enter normally.
    try:
        from core.platform_bridge import platform_bridge  # late import: circular dep
        if platform_bridge.is_connected:
            app_state.ws_status.add_log("User-data WS: plugin connected — standing by (30s)")
            await asyncio.sleep(30)
            if not _stopping:
                asyncio.create_task(_user_data_loop(listen_key, 0))
            return
    except Exception:
        pass

    ws_adapter = _get_ws_adapter()
    url = ws_adapter.build_user_stream_url(listen_key) if ws_adapter else f"{config.FSTREAM_WS}/{listen_key}"
    ws  = app_state.ws_status
    ws.add_log(f"User-data WS connecting (attempt {attempt+1})")

    try:
        async with websockets.connect(
            url,
            ping_interval=config.WS_PING_INTERVAL,
            ping_timeout=30,
        ) as sock:
            ws.connected = True
            ws.reconnect_attempts = 0
            ws.using_fallback = False
            ws.add_log("User-data WS connected.")

            async for raw in sock:
                try:
                    msg = json.loads(raw)
                    await _handle_user_event(msg)
                except Exception as exc:
                    log.warning("User-data WS message error: %s", exc)
                ws.last_update = datetime.now(timezone.utc)

    except Exception as exc:
        ws.connected = False
        ws.add_log(f"User-data WS disconnected: {exc}")
        await _reconnect_user(attempt)


async def _reconnect_user(attempt: int) -> None:
    global _listen_key
    # Abort reconnect if stop() has been called (e.g. during account switch)
    if _stopping:
        return
    ws = app_state.ws_status
    ws.reconnect_attempts = attempt + 1
    if attempt >= config.WS_RECONNECT_ATTEMPTS:
        ws.add_log("Max reconnect attempts reached — staying on REST fallback.")
        return

    delay = min(config.WS_RECONNECT_BASE * (2 ** attempt), config.WS_RECONNECT_MAX)
    ws.add_log(f"Reconnecting user-data in {delay:.1f}s ...")
    await asyncio.sleep(delay)

    # Check again after the sleep — stop() may have been called during the wait
    if _stopping:
        return

    # Refresh listen key
    try:
        _listen_key = await create_listen_key()
    except Exception as e:
        ws.add_log(f"Failed to refresh listen key: {e}")
        from core.crypto import safe_exchange_error
        log.error("create_listen_key failed during reconnect (attempt %d): %s", attempt, safe_exchange_error(e))
        await _reconnect_user(attempt + 1)
        return

    # Final guard: ensure listen key is valid and we haven't been stopped
    if not _listen_key or _stopping:
        ws.add_log("Reconnect aborted — no valid listen key or stop requested.")
        return

    asyncio.create_task(_user_data_loop(_listen_key, attempt + 1))


# ── Market data stream (klines + book) ───────────────────────────────────────

def _build_market_streams() -> list[str]:
    """Build the combined stream list for all active position symbols + calculator."""
    ws_adapter = _get_ws_adapter()
    position_symbols = [p.ticker for p in app_state.positions]
    all_symbols = list({*position_symbols, _calculator_symbol} - {None})

    if ws_adapter:
        return ws_adapter.build_market_streams(
            all_symbols, config.ATR_TIMEFRAME, _calculator_symbol
        )

    # Fallback (should not hit if adapter is configured)
    streams = []
    for sym in all_symbols:
        s = sym.lower()
        streams.append(f"{s}@kline_{config.ATR_TIMEFRAME}")
        if sym in {p.ticker for p in app_state.positions}:
            streams.append(f"{s}@markPrice@1s")
    if _calculator_symbol:
        streams.append(f"{_calculator_symbol.lower()}@depth20")
    return streams


def _apply_mark_price(msg: dict) -> None:
    sym  = msg.get("s", "")
    mark = float(msg.get("p", 0) or 0)
    if not sym or not mark:
        return
    app_state._data_cache.apply_mark_price(sym, mark)


def _apply_kline(msg: dict) -> None:
    k  = msg.get("k", {})
    sym = msg.get("s", "")
    if not k.get("x"):          # only closed candles
        return
    candle = [
        k["t"],                  # open time
        float(k["o"]),
        float(k["h"]),
        float(k["l"]),
        float(k["c"]),
        float(k["v"]),
    ]
    app_state._data_cache.apply_kline(sym, candle)


def _apply_depth(msg: dict) -> None:
    sym = msg.get("s", "")
    if not sym:
        return
    bids = [[float(p), float(q)] for p, q in msg.get("b", [])]
    asks = [[float(p), float(q)] for p, q in msg.get("a", [])]
    app_state._data_cache.apply_depth(sym, bids, asks)


async def _market_stream_loop(attempt: int = 0) -> None:
    ws = app_state.ws_status
    streams = _build_market_streams()
    if not streams:
        ws.add_log("No market streams to subscribe — sleeping 10s.")
        await asyncio.sleep(10)
        asyncio.create_task(_market_stream_loop(0))
        return

    ws_adapter = _get_ws_adapter()
    url = ws_adapter.build_market_stream_url(streams) if ws_adapter else f"{config.FSTREAM_COMB}?streams=" + "/".join(streams)
    ws.add_log(f"Market WS connecting ({len(streams)} streams, attempt {attempt+1})")

    try:
        async with websockets.connect(
            url,
            ping_interval=config.WS_PING_INTERVAL,
            ping_timeout=30,
        ) as sock:
            ws.add_log("Market WS connected.")
            async for raw in sock:
                try:
                    msg_outer = json.loads(raw)
                    msg = ws_adapter.unwrap_stream_message(msg_outer) if ws_adapter else msg_outer.get("data", msg_outer)
                    ev = ws_adapter.get_event_type(msg) if ws_adapter else msg.get("e", "")
                    if ev == "kline":
                        _apply_kline(msg)
                    elif ev == "depthUpdate":
                        _apply_depth(msg)
                    elif ev == "markPriceUpdate":
                        _apply_mark_price(msg)
                except Exception as exc:
                    log.warning("Market WS message error: %s", exc)
                ws.last_update = datetime.now(timezone.utc)

    except Exception as exc:
        ws.add_log(f"Market WS disconnected: {exc}")
        delay = min(config.WS_RECONNECT_BASE * (2 ** attempt), config.WS_RECONNECT_MAX)
        await asyncio.sleep(delay)
        if not _stopping:
            asyncio.create_task(_market_stream_loop(attempt + 1))


# ── Keepalive for listen key (must ping every 30 min) ────────────────────────

async def _keepalive_loop() -> None:
    while True:
        await asyncio.sleep(25 * 60)   # 25 minutes
        if _listen_key:
            try:
                await keepalive_listen_key(_listen_key)
                app_state.ws_status.add_log("Listen key refreshed.")
            except Exception as e:
                app_state.ws_status.add_log(f"Listen key refresh failed: {e}")


# ── REST fallback polling ─────────────────────────────────────────────────────

async def _fallback_loop() -> None:
    """Poll REST API when WS is stale for > WS_FALLBACK_TIMEOUT seconds."""
    while True:
        # RL-1: raised from 5s to 15s to reduce REST pressure during WS outage
        await asyncio.sleep(15)
        ws = app_state.ws_status

        if ws.is_stale and not ws.using_fallback:
            ws.using_fallback = True
            ws.add_log("WS stale — switched to REST polling fallback.")

        if ws.using_fallback:
            # RL-1: skip if rate-limited
            if ws.is_rate_limited:
                continue
            try:
                # Skip account/position REST fetch if plugin is providing live data.
                try:
                    from core.platform_bridge import platform_bridge  # late import: circular dep
                    _plugin_up = platform_bridge.is_connected
                except Exception:
                    _plugin_up = False
                if not _plugin_up:
                    await fetch_account()
                    await fetch_positions()
                if _calculator_symbol:
                    await fetch_orderbook(_calculator_symbol)
                ws.last_update = datetime.now(timezone.utc)
            except Exception as e:
                ws.add_log(f"REST fallback error: {e}")

        elif ws.using_fallback and not ws.is_stale:
            ws.using_fallback = False
            ws.add_log("WS recovered — REST fallback disabled.")


# ── Public API ────────────────────────────────────────────────────────────────

async def start(listen_key: str) -> None:
    global _listen_key, _user_ws_task, _market_ws_task, _keepalive_task, _fallback_task, _stopping
    _stopping = False
    _listen_key = listen_key

    _user_ws_task   = asyncio.create_task(_user_data_loop(listen_key))
    _market_ws_task = asyncio.create_task(_market_stream_loop())
    _keepalive_task = asyncio.create_task(_keepalive_loop())
    _fallback_task  = asyncio.create_task(_fallback_loop())

    app_state.ws_status.add_log("WebSocket manager started.")


def set_calculator_symbol(symbol: str) -> None:
    global _calculator_symbol
    _calculator_symbol = symbol.upper() if symbol else None


async def restart_market_streams() -> None:
    global _market_ws_task
    if _market_ws_task and not _market_ws_task.done():
        _market_ws_task.cancel()
    _market_ws_task = asyncio.create_task(_market_stream_loop())


async def stop() -> None:
    """Cancel all WS tasks. Call before account switch to cleanly teardown streams."""
    global _listen_key, _user_ws_task, _market_ws_task, _keepalive_task, _fallback_task, _stopping

    # Signal before cancelling so _reconnect_user aborts if it wakes during teardown
    _stopping = True

    tasks = [t for t in (_user_ws_task, _market_ws_task, _keepalive_task, _fallback_task)
             if t is not None and not t.done()]
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    _listen_key    = None
    _user_ws_task  = None
    _market_ws_task = None
    _keepalive_task = None
    _fallback_task  = None

    app_state.ws_status.connected = False
    app_state.ws_status.using_fallback = False
    app_state.ws_status.add_log("WS stopped (account switch).")
