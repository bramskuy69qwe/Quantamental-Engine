"""
WebSocket manager for Binance USD-M Futures.

Handles:
  - User data stream  (account / position updates)
  - Kline 4h streams  (for ATR on all active positions)
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
    fetch_account, fetch_positions, fetch_orderbook, fetch_ohlcv,
    create_listen_key, keepalive_listen_key,
)

log = logging.getLogger("ws_manager")


# ── State ─────────────────────────────────────────────────────────────────────
_listen_key: Optional[str]        = None
_user_ws_task:    Optional[asyncio.Task] = None
_market_ws_task:  Optional[asyncio.Task] = None
_keepalive_task:  Optional[asyncio.Task] = None
_fallback_task:   Optional[asyncio.Task] = None
_upnl_task:       Optional[asyncio.Task] = None
_calculator_symbol: Optional[str]        = None   # symbol currently open in calc
_stopping: bool = False   # set by stop() to prevent reconnect tasks after teardown
_subscribed_position_symbols: set[str] = set()    # symbols in current market WS


# ── User data stream ──────────────────────────────────────────────────────────

async def _handle_user_event(msg: dict) -> None:
    """Parse and apply a user-data stream event."""
    ev = msg.get("e", "")
    ws = app_state.ws_status

    # Real-time latency: lag between Binance event time and now
    event_time_ms = msg.get("E", 0)
    if event_time_ms:
        ws.latency_ms = round(time.time() * 1000 - event_time_ms, 1)

    if ev == "ACCOUNT_UPDATE":
        balances = msg.get("a", {}).get("B", [])
        positions = msg.get("a", {}).get("P", [])

        async with app_state._lock:
            for b in balances:
                if b.get("a") == "USDT":
                    app_state.account_state.balance_usdt = float(b.get("wb") or 0)
                    app_state.account_state.total_equity = float(b.get("cw") or 0)

            # Update unrealized from position updates
            for p_raw in positions:
                sym = p_raw.get("s", "")
                upnl = float(p_raw.get("up") or 0)
                for pos in app_state.positions:
                    if pos.ticker == sym:
                        pos.individual_unrealized = upnl
                        break

            app_state.account_state.total_unrealized = sum(
                p.individual_unrealized for p in app_state.positions
            )

    elif ev == "ORDER_TRADE_UPDATE":
        # Trigger a position refresh so new fills appear immediately
        asyncio.create_task(_refresh_positions_after_fill())

    ws.last_update = datetime.now(timezone.utc)
    await event_bus.publish(
        "risk:account_updated",
        {"event": ev, "ts": datetime.now(timezone.utc).isoformat()},
    )


async def _refresh_positions_after_fill() -> None:
    try:
        await fetch_account()
        await fetch_positions()
        # Restart market streams if new position symbols appeared so they get
        # markPrice@1s subscriptions immediately rather than waiting for next reconnect.
        new_symbols = {p.ticker for p in app_state.positions}
        if new_symbols != _subscribed_position_symbols:
            app_state.ws_status.add_log(
                f"New position symbols detected {new_symbols - _subscribed_position_symbols} — restarting market streams."
            )
            await restart_market_streams()
        await event_bus.publish(
            "risk:positions_refreshed",
            {"trigger": "fill", "ts": datetime.now(timezone.utc).isoformat()},
        )
    except Exception as e:
        app_state.ws_status.add_log(f"Post-fill refresh error: {e}")


async def _user_data_loop(listen_key: str, attempt: int = 0) -> None:
    # Gate: plugin provides account/position truth — no need for Binance user-data WS.
    # Sleep and retry until the plugin disconnects, then re-enter normally.
    try:
        from core.platform_bridge import platform_bridge
        if platform_bridge.is_connected:
            app_state.ws_status.add_log("User-data WS: plugin connected — standing by (30s)")
            await asyncio.sleep(30)
            if not _stopping:
                asyncio.create_task(_user_data_loop(listen_key, 0))
            return
    except Exception:
        pass

    url = f"{config.FSTREAM_WS}/{listen_key}"
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
                t0  = time.monotonic()
                msg = json.loads(raw)
                await _handle_user_event(msg)
                ws.latency_ms   = round((time.monotonic() - t0) * 1000, 2)
                ws.last_update  = datetime.now(timezone.utc)

    except (websockets.exceptions.ConnectionClosedError,
            websockets.exceptions.ConnectionClosedOK,
            OSError) as exc:
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
        log.exception("create_listen_key failed during reconnect (attempt %d)", attempt)
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
    global _subscribed_position_symbols
    pos_symbols = {p.ticker for p in app_state.positions}
    _subscribed_position_symbols = pos_symbols.copy()

    all_symbols = pos_symbols | ({_calculator_symbol} if _calculator_symbol else set())

    streams = []
    for sym in all_symbols:
        s = sym.lower()
        streams.append(f"{s}@kline_{config.ATR_TIMEFRAME}")
        if sym in pos_symbols:
            streams.append(f"{s}@markPrice@1s")
    if _calculator_symbol:
        streams.append(f"{_calculator_symbol.lower()}@depth20")

    return streams


def _apply_mark_price(msg: dict) -> None:
    sym  = msg.get("s", "")
    mark = float(msg.get("p", 0) or 0)
    if not sym or not mark:
        return

    app_state.mark_price_cache[sym] = mark

    for pos in app_state.positions:
        if pos.ticker == sym:
            pos.fair_price = mark
            pos.position_value_usdt = mark * pos.contract_amount
            if pos.average > 0:
                if pos.direction == "LONG":
                    pos.individual_unrealized = (mark - pos.average) * pos.contract_amount
                else:
                    pos.individual_unrealized = (pos.average - mark) * pos.contract_amount
                unreal = pos.individual_unrealized
                if unreal > pos.session_mfe:
                    pos.session_mfe = round(unreal, 2)
                if pos.session_mae == 0.0 or unreal < pos.session_mae:
                    pos.session_mae = round(unreal, 2)
            break

    app_state.account_state.total_unrealized = sum(
        p.individual_unrealized for p in app_state.positions
    )
    app_state.recalculate_portfolio()


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

    cache = app_state.ohlcv_cache.get(sym, [])
    if cache and cache[-1][0] == candle[0]:
        cache[-1] = candle
    else:
        cache.append(candle)
        if len(cache) > config.ATR_FETCH_LIMIT + 10:
            cache = cache[-(config.ATR_FETCH_LIMIT + 10):]
    app_state.ohlcv_cache[sym] = cache


def _apply_depth(msg: dict) -> None:
    sym = msg.get("s", "")
    if not sym:
        return
    app_state.orderbook_cache[sym] = {
        "bids": [[float(p), float(q)] for p, q in msg.get("b", [])],
        "asks": [[float(p), float(q)] for p, q in msg.get("a", [])],
    }


async def _market_stream_loop(attempt: int = 0) -> None:
    ws = app_state.ws_status
    streams = _build_market_streams()
    if not streams:
        ws.add_log("No market streams to subscribe — sleeping 10s.")
        await asyncio.sleep(10)
        asyncio.create_task(_market_stream_loop(0))
        return

    url = f"{config.FSTREAM_COMB}?streams=" + "/".join(streams)
    ws.add_log(f"Market WS connecting ({len(streams)} streams, attempt {attempt+1})")

    try:
        async with websockets.connect(
            url,
            ping_interval=config.WS_PING_INTERVAL,
            ping_timeout=30,
        ) as sock:
            ws.add_log("Market WS connected.")
            async for raw in sock:
                msg_outer = json.loads(raw)
                msg  = msg_outer.get("data", msg_outer)
                ev   = msg.get("e", "")
                if ev == "kline":
                    _apply_kline(msg)
                elif ev == "depthUpdate":
                    _apply_depth(msg)
                elif ev == "markPriceUpdate":
                    _apply_mark_price(msg)
                ws.last_update = datetime.now(timezone.utc)

    except (websockets.exceptions.ConnectionClosedError,
            websockets.exceptions.ConnectionClosedOK,
            OSError) as exc:
        ws.add_log(f"Market WS disconnected: {exc}")
        delay = min(config.WS_RECONNECT_BASE * (2 ** attempt), config.WS_RECONNECT_MAX)
        await asyncio.sleep(delay)
        asyncio.create_task(_market_stream_loop(attempt + 1))


# ── UPNL sync loop ───────────────────────────────────────────────────────────

async def _upnl_sync_loop() -> None:
    """
    Every 1 s, recompute UPNL + notional from the mark price cache for every
    open position.  Primary update path is still markPrice@1s WS events via
    _apply_mark_price(); this loop is a belt-and-suspenders guard that covers:
      - positions opened after the market WS connected (not yet subscribed)
      - any brief gap between WS events
    """
    while True:
        await asyncio.sleep(1)
        try:
            cache   = app_state.mark_price_cache
            updated = False
            for pos in app_state.positions:
                mark = cache.get(pos.ticker, 0.0)
                if not mark or not pos.average:
                    continue
                pos.fair_price          = mark
                pos.position_value_usdt = mark * pos.contract_amount
                if pos.direction == "LONG":
                    upnl = (mark - pos.average) * pos.contract_amount
                else:
                    upnl = (pos.average - mark) * pos.contract_amount
                pos.individual_unrealized = upnl
                if upnl > pos.session_mfe:
                    pos.session_mfe = round(upnl, 2)
                if pos.session_mae == 0.0 or upnl < pos.session_mae:
                    pos.session_mae = round(upnl, 2)
                updated = True
            if updated:
                app_state.account_state.total_unrealized = sum(
                    p.individual_unrealized for p in app_state.positions
                )
                app_state.recalculate_portfolio()
        except Exception:
            pass


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
        await asyncio.sleep(5)
        ws = app_state.ws_status

        if ws.is_stale and not ws.using_fallback:
            ws.using_fallback = True
            ws.add_log("WS stale — switched to REST polling fallback.")

        if ws.using_fallback:
            try:
                # Skip account/position REST fetch if plugin is providing live data.
                try:
                    from core.platform_bridge import platform_bridge
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
    global _listen_key, _user_ws_task, _market_ws_task, _keepalive_task, _fallback_task, _upnl_task, _stopping
    _stopping = False
    _listen_key = listen_key

    _user_ws_task   = asyncio.create_task(_user_data_loop(listen_key))
    _market_ws_task = asyncio.create_task(_market_stream_loop())
    _keepalive_task = asyncio.create_task(_keepalive_loop())
    _fallback_task  = asyncio.create_task(_fallback_loop())
    _upnl_task      = asyncio.create_task(_upnl_sync_loop())

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
    global _listen_key, _user_ws_task, _market_ws_task, _keepalive_task, _fallback_task, _upnl_task, _stopping

    # Signal before cancelling so _reconnect_user aborts if it wakes during teardown
    _stopping = True

    tasks = [t for t in (_user_ws_task, _market_ws_task, _keepalive_task, _fallback_task, _upnl_task)
             if t is not None and not t.done()]
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    _listen_key     = None
    _user_ws_task   = None
    _market_ws_task = None
    _keepalive_task = None
    _fallback_task  = None
    _upnl_task      = None

    app_state.ws_status.connected = False
    app_state.ws_status.using_fallback = False
    app_state.ws_status.add_log("WS stopped (account switch).")
