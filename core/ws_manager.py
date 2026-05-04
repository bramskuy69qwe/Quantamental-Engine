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
from core.state import app_state, PositionInfo
from core.event_bus import event_bus
from core.exchange import (
    get_exchange, _REST_POOL,
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
_calculator_symbol: Optional[str]        = None   # symbol currently open in calc
_last_ws_position_update: float = 0.0   # monotonic ts of last WS position change
_stopping: bool = False   # set by stop() to prevent reconnect tasks after teardown


# ── User data stream ──────────────────────────────────────────────────────────

async def _apply_account_update(msg: dict) -> None:
    """Apply ACCOUNT_UPDATE event: update balances and positions under lock,
    then fire side effects (stream restart, portfolio recalc) outside lock."""
    global _last_ws_position_update
    balances = msg.get("a", {}).get("B", [])
    raw_positions = msg.get("a", {}).get("P", [])
    closed_syms: set = set()
    new_syms: set = set()

    async with app_state._lock:
        for b in balances:
            if b.get("a") == "USDT":
                app_state.account_state.balance_usdt = float(b.get("wb") or 0)
                app_state.account_state.total_equity = float(b.get("cw") or 0)

        if raw_positions:
            existing = {p.ticker: p for p in app_state.positions}
            closed_syms, new_syms = _apply_position_updates(existing, raw_positions)
            if closed_syms:
                app_state.positions = [p for p in app_state.positions if p.ticker not in closed_syms]
            _last_ws_position_update = time.monotonic()

        app_state.account_state.total_unrealized = sum(
            p.individual_unrealized for p in app_state.positions
        )

    # Outside lock: side effects
    if not raw_positions:
        return
    if closed_syms or new_syms:
        asyncio.create_task(restart_market_streams())
    for sym in new_syms:
        asyncio.create_task(_on_new_position(sym))
    app_state.recalculate_portfolio()


def _apply_position_updates(existing: dict, raw_positions: list) -> tuple[set, set]:
    """Process raw position updates. Returns (closed_syms, new_syms)."""
    closed_syms: set = set()
    new_syms: set = set()

    for p_raw in raw_positions:
        sym  = p_raw.get("s", "")
        amt  = float(p_raw.get("pa") or 0)
        upnl = float(p_raw.get("up") or 0)
        ep   = float(p_raw.get("ep") or 0)

        if amt == 0:
            if sym in existing:
                closed_syms.add(sym)
            continue

        if sym in existing:
            pos = existing[sym]
            pos.individual_unrealized = upnl
            pos.contract_amount = abs(amt)
            pos.direction = "LONG" if amt > 0 else "SHORT"
            if ep > 0:
                pos.average = ep
            mark = app_state.mark_price_cache.get(sym, 0)
            if mark:
                pos.position_value_usdt = abs(amt) * mark
            continue

        # New position
        mark = app_state.mark_price_cache.get(sym, ep) or ep
        app_state.positions.append(PositionInfo(
            ticker=sym,
            direction="LONG" if amt > 0 else "SHORT",
            contract_amount=abs(amt),
            average=ep,
            fair_price=mark,
            individual_unrealized=upnl,
            position_value_usdt=abs(amt) * mark,
            entry_timestamp=datetime.now(timezone.utc).isoformat(),
            sector=config.get_sector(sym),
        ))
        new_syms.add(sym)

    return closed_syms, new_syms


async def _handle_user_event(msg: dict) -> None:
    """Parse and apply a user-data stream event."""
    ev = msg.get("e", "")
    ws = app_state.ws_status

    # Real-time latency: lag between Binance event time and now
    event_time_ms = msg.get("E", 0)
    if event_time_ms:
        ws.latency_ms = round(time.time() * 1000 - event_time_ms, 1)

    if ev == "ACCOUNT_UPDATE":
        await _apply_account_update(msg)

    ws.last_update = datetime.now(timezone.utc)
    await event_bus.publish(
        "risk:account_updated",
        {"event": ev, "ts": datetime.now(timezone.utc).isoformat()},
    )


async def _on_new_position(sym: str) -> None:
    """Background: restart market streams + fetch real entry time for a new position."""
    try:
        await restart_market_streams()
    except Exception:
        pass
    # Fetch real fill timestamp from Binance trades
    try:
        loop = asyncio.get_event_loop()
        ex = get_exchange()
        trades = await loop.run_in_executor(
            _REST_POOL,
            lambda: ex.fapiPrivateGetUserTrades({"symbol": sym, "limit": 50}) or [],
        )
        if trades:
            for pos in app_state.positions:
                if pos.ticker != sym:
                    continue
                buy = "BUY" if pos.direction == "LONG" else "SELL"
                trades.sort(key=lambda t: int(t.get("time", 0)), reverse=True)
                cum = 0.0
                for t in trades:
                    if t.get("side") != buy:
                        break
                    cum += abs(float(t.get("qty", 0) or 0))
                    open_ms = int(t.get("time", 0))
                    if cum >= pos.contract_amount - 1e-8:
                        pos.entry_timestamp = datetime.fromtimestamp(
                            open_ms / 1000, tz=timezone.utc
                        ).isoformat()
                        break
                break
    except Exception as e:
        log.warning("_on_new_position trade lookup failed for %s: %s", sym, e)


async def _refresh_positions_after_fill() -> None:
    try:
        await fetch_account()
        await fetch_positions()
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
        from core.platform_bridge import platform_bridge  # late import: circular dep
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
                try:
                    msg = json.loads(raw)
                    await _handle_user_event(msg)
                except Exception as exc:
                    log.warning("User-data WS message error: %s", exc)
                ws.last_update  = datetime.now(timezone.utc)

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
    symbols = {p.ticker for p in app_state.positions}
    if _calculator_symbol:
        symbols.add(_calculator_symbol)

    streams = []
    for sym in symbols:
        s = sym.lower()
        streams.append(f"{s}@kline_{config.ATR_TIMEFRAME}")
        # Mark price stream at 1s cadence for real-time unrealized PnL
        if sym in {p.ticker for p in app_state.positions}:
            streams.append(f"{s}@markPrice@1s")
    if _calculator_symbol:
        s = _calculator_symbol.lower()
        streams.append(f"{s}@depth20")

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
            # Update notional and margin from mark price
            pos.position_value_usdt = abs(mark * pos.contract_amount * pos.contract_size)
            pos.position_value_asset = abs(pos.contract_amount * pos.contract_size)
            if pos.average > 0:
                if pos.direction == "LONG":
                    pos.individual_unrealized = (mark - pos.average) * pos.contract_amount
                else:
                    pos.individual_unrealized = (pos.average - mark) * pos.contract_amount
                # Session MFE/MAE in USDT — track running max/min of unrealized PnL
                unreal = pos.individual_unrealized
                if unreal > pos.session_mfe:
                    pos.session_mfe = round(unreal, 2)
                if pos.session_mae == 0.0 or unreal < pos.session_mae:
                    pos.session_mae = round(unreal, 2)
            break

    acc = app_state.account_state
    acc.total_unrealized = sum(
        p.individual_unrealized for p in app_state.positions
    )
    acc.total_position_value = sum(
        p.position_value_usdt for p in app_state.positions
    )
    acc.total_margin_used = sum(
        p.individual_margin_used for p in app_state.positions
    )
    # Equity = balance + unrealized (real-time from mark price)
    if acc.balance_usdt > 0:
        acc.total_equity = acc.balance_usdt + acc.total_unrealized
        acc.available_margin = acc.total_equity - acc.total_margin_used
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
                try:
                    msg_outer = json.loads(raw)
                    msg  = msg_outer.get("data", msg_outer)
                    ev   = msg.get("e", "")
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
        await asyncio.sleep(5)
        ws = app_state.ws_status

        if ws.is_stale and not ws.using_fallback:
            ws.using_fallback = True
            ws.add_log("WS stale — switched to REST polling fallback.")

        if ws.using_fallback:
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
