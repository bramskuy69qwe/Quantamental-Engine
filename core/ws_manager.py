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
from core import correlation_log
from core.adapters.errors import RateLimitError
from core.state import app_state
from core.event_bus import event_bus
from core.order_state import resolve_tpsl_direction
from core.exchange import (
    fetch_account, fetch_positions, fetch_orderbook, fetch_ohlcv,
    create_listen_key, keepalive_listen_key,
    _get_adapter, handle_rate_limit_error, trade_event_sem,
)

log = logging.getLogger("ws_manager")


def _exchange_id() -> str:
    """Current exchange_id for time-sync lookups."""
    try:
        return _get_adapter().exchange_id
    except Exception:
        return ""


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
        asyncio.create_task(restart_market_streams(trigger="position_change"),
                            name="ws-restart")
    for sym in result.new_syms:
        asyncio.create_task(_on_new_position(sym), name="ws-new-position")
    # recalculate_portfolio() now called inside DataCache.apply_position_update_incremental()


def _tap_user_frame(ev: str, msg: dict) -> None:
    """corr-tap: ws_account_update / ws_order_update / ws_algo_update (CL.T1b,
    spec §5.4). Field extraction is Binance-raw best-effort (the live path);
    other adapters' frames emit with null fields rather than nothing."""
    if ev == "ACCOUNT_UPDATE":
        a = msg.get("a", {}) if isinstance(msg.get("a"), dict) else {}
        correlation_log.emit(
            "ws_manager", "binance", "in", correlation_log.CAT_WS_ACCOUNT_UPDATE,
            {"reason": a.get("m"), "n_balances": len(a.get("B") or []),
             "n_positions": len(a.get("P") or [])},
        )
    elif ev in ("ORDER_TRADE_UPDATE", "ALGO_UPDATE"):
        o = msg.get("o", {}) if isinstance(msg.get("o"), dict) else {}
        is_order = ev == "ORDER_TRADE_UPDATE"
        cat = (correlation_log.CAT_WS_ORDER_UPDATE if is_order
               else correlation_log.CAT_WS_ALGO_UPDATE)
        # Binance algo frames key their id as "aid", not "i" (audit T1b-1).
        oid = o.get("i") if is_order else o.get("aid")
        payload = {"order_id": oid, "status": o.get("X"), "side": o.get("S"),
                   "qty": o.get("q"), "price": o.get("p"), "filled": o.get("z"),
                   "exec_type": o.get("x"), "algo_type": o.get("at")}
        # dedup_key ONLY when the id resolved: a degenerate "None:X:q" key
        # would collide across DISTINCT frames — false duplicates corrupt
        # the §4.1 uniq -d mechanism, worse than no key at all.
        if oid is not None:
            payload["dedup_key"] = f"{oid}:{o.get('X')}:{o.get('q')}"
        correlation_log.emit(
            "ws_manager", "binance", "in", cat, payload, symbol=o.get("s"),
        )


async def _handle_user_event(msg: dict) -> None:
    """Parse and apply a user-data stream event via WS adapter."""
    ws_adapter = _get_ws_adapter()
    ev = ws_adapter.get_event_type(msg) if ws_adapter else msg.get("e", "")
    ws = app_state.ws_status

    # corr-tap: entry point — one chain per inbound user-data frame
    # (spec §3.2 wsu-*); everything this frame causes inherits it.
    correlation_log.tick("wsu")
    _tap_user_frame(ev, msg)

    # Real-time latency: (local_now + clock_offset) - exchange_event_time
    from core import time_sync
    event_time_ms = ws_adapter.get_event_time_ms(msg) if ws_adapter else msg.get("E", 0)
    if event_time_ms:
        offset = time_sync.get_offset_ms(_exchange_id())
        ws.latency_ms = round((time.time() * 1000 + offset) - event_time_ms, 1)

    if ev == "ACCOUNT_UPDATE":
        await _apply_account_update(msg)

    elif ev == "ORDER_TRADE_UPDATE":
        await _apply_order_update(msg, ws_adapter)

    elif ev == "ALGO_UPDATE":
        await _apply_algo_update(msg, ws_adapter)

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
    execution_type = order.execution_type or ""

    # ── TP/SL order → update matching position in real-time ──────────────
    if order.order_type in _TPSL_TYPES:
        # OM-5: resolve "BOTH" (one-way mode) to LONG/SHORT via close-order semantics.
        pos_dir = resolve_tpsl_direction(order.position_side, order.side)

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

    # ── Fill → create fill record + refresh positions ────────────────────
    if execution_type == "TRADE":
        # PA-1a: create fill record from WS event (fact before state transition)
        try:
            await _create_fill_from_ws(order, msg)
        except Exception as e:
            log.warning("WS fill creation failed: %s", e)
        asyncio.create_task(_refresh_positions_after_fill(), name="ws-fill-refresh")

    # ── SR-1: Persist order via OrderManager (validates transition + timestamp)
    try:
        from core.order_manager_singleton import order_manager
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
        # P4.T1 (spec §3.2): detect + persist order_amendments BEFORE the
        # SR-1 transition gate in process_order_update rejects the new→new
        # self-transition that amendments arrive as. Isolated try so a
        # detection fault can't block order persistence.
        try:
            await order_manager.detect_and_persist_amendment(
                app_state.active_account_id, order_dict,
            )
        except Exception as _ae:
            log.debug("amendment detection skipped: %s", _ae)
        await order_manager.process_order_update(
            app_state.active_account_id, order_dict,
        )
    except Exception as e:
        log.debug("WS order persist skipped: %s", e)


async def _apply_algo_update(msg: dict, ws_adapter) -> None:
    """Handle ALGO_UPDATE: real-time conditional order lifecycle.

    Algo orders (TP/SL placed via Binance UI as "conditional") fire this
    event instead of ORDER_TRADE_UPDATE. Same enrichment pattern applies.
    """
    if not ws_adapter or not hasattr(ws_adapter, "parse_algo_update"):
        return

    order = ws_adapter.parse_algo_update(msg)
    algo_status = order.execution_type or ""  # reused field carries raw algo status

    # ── TP/SL → update matching position in real-time ──────────────────
    if order.order_type in _TPSL_TYPES:
        pos_dir = resolve_tpsl_direction(order.position_side, order.side)

        for pos in app_state.positions:
            if pos.ticker != order.symbol or pos.direction != pos_dir:
                continue

            if algo_status in ("NEW", "TRIGGERING"):
                if order.order_type == "take_profit":
                    pos.individual_tpsl = True
                    pos.individual_tp_price = order.stop_price
                    pos.individual_tp_amount = order.quantity
                elif order.order_type == "stop_loss":
                    pos.individual_tpsl = True
                    pos.individual_sl_price = order.stop_price
                    pos.individual_sl_amount = order.quantity

            elif algo_status in ("CANCELED", "EXPIRED", "REJECTED", "FINISHED"):
                if order.order_type == "take_profit":
                    pos.individual_tp_price = 0.0
                    pos.individual_tp_amount = 0.0
                elif order.order_type == "stop_loss":
                    pos.individual_sl_price = 0.0
                    pos.individual_sl_amount = 0.0
                if pos.individual_tp_price == 0.0 and pos.individual_sl_price == 0.0:
                    pos.individual_tpsl = False
            break

    # ── Persist via OrderManager ───────────────────────────────────────
    try:
        from core.order_manager_singleton import order_manager
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
            "avg_fill_price":     0.0,
            "reduce_only":        order.reduce_only,
            "time_in_force":      order.time_in_force,
            "position_side":      order.position_side,
            "exchange_position_id": "",
            "terminal_position_id": "",
            "source":             "binance_algo_ws",
            "created_at_ms":      order.created_at_ms,
            "updated_at_ms":      order.updated_at_ms,
        }
        # P4.T1: amendment detection on the algo path too (defensive — see
        # detect_and_persist_amendment scope note: no-op under cancel-replace).
        try:
            await order_manager.detect_and_persist_amendment(
                app_state.active_account_id, order_dict,
            )
        except Exception as _ae:
            log.debug("algo amendment detection skipped: %s", _ae)
        await order_manager.process_order_update(
            app_state.active_account_id, order_dict,
        )
    except Exception as e:
        log.debug("WS algo order persist skipped: %s", e)


async def _on_new_position(sym: str) -> None:
    """Background: restart market streams + fetch real entry time for a new position."""
    try:
        await restart_market_streams()
    except Exception:
        pass
    # RL-4: skip REST fetch if rate-limited (WS-derived entry time is acceptable)
    if app_state.ws_status.is_rate_limited:
        log.debug("_on_new_position: skipping %s — rate-limited", sym)
        return
    # Fetch real fill timestamp from exchange trades
    async with trade_event_sem:
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
        except RateLimitError as e:
            handle_rate_limit_error(e)
            log.warning("Rate limit hit in _on_new_position for %s: %s", sym, e)
        except Exception as e:
            log.warning("_on_new_position trade lookup failed for %s: %s", sym, e)


async def _create_fill_from_ws(order, raw_msg: dict) -> None:
    """PA-1a: create a fill record from WS ORDER_TRADE_UPDATE (execution_type=TRADE).

    Extracts fill-specific fields from the raw message (tradeId, lastFilledQty,
    lastFilledPrice, realizedProfit, commission) that are NOT on NormalizedOrder.
    Uses tradeId as exchange_fill_id for natural dedup with backfill path.

    Routes through `order_manager.process_fill` so the close-aggregation pipeline
    (_build_close_row_for_fill → insert_closed_position) fires for closing fills.
    Without this, WS-arrived fills land in the fills table but never produce a
    closed_positions row until the next engine restart's backfill sweep — leaving
    Position History stale (the engine's user-data WS is the sole fill source).
    """
    o = raw_msg.get("o", {})
    trade_id = str(o.get("t", ""))
    if not trade_id or trade_id == "0":
        return  # No trade ID — not a real fill

    sym = o.get("s", "")
    # NOTE (debug 2026-06-07): in Binance HEDGE mode (this operator's setup — all
    # live orders carry positionSide LONG/SHORT) this resolves `direction`
    # correctly, the lookup below finds the position, and the defect-1 minted
    # terminal_position_id is copied onto the fill. KNOWN LATENT GAP for Binance
    # ONE-WAY mode: positionSide="BOTH" is truthy, so direction="BOTH" never
    # matches a LONG/SHORT position -> tpid stays "" -> linkage breaks. Not fixed
    # here (operator is hedge-mode; a one-way fix needs close-vs-open side
    # inference + an integration test). Surfaced as a follow-up.
    direction = o.get("ps", "") or ("LONG" if o.get("S") == "BUY" else "SHORT")
    # Match the open position (if any) to populate terminal_position_id. Lets
    # _build_close_row_for_fill use the indexed terminal_position_id path instead
    # of falling back to (symbol, direction) — cleaner data + faster lookup.
    pos = next(
        (p for p in app_state.positions if p.ticker == sym and p.direction == direction),
        None,
    )
    terminal_position_id = pos.position_id if pos else ""

    realized_pnl = float(o.get("rp", 0) or 0)
    fill = {
        "account_id":           app_state.active_account_id,
        "exchange_fill_id":     trade_id,
        "terminal_fill_id":     "",
        "exchange_order_id":    str(o.get("i", "")),
        "symbol":               sym,
        "side":                 o.get("S", ""),
        "direction":            direction,
        "price":                float(o.get("L", 0) or 0),   # lastFilledPrice
        "quantity":             float(o.get("l", 0) or 0),   # lastFilledQty
        "fee":                  abs(float(o.get("n", 0) or 0)),
        "fee_asset":            o.get("N", "USDT"),
        "exchange_position_id": "",
        "terminal_position_id": terminal_position_id,
        "is_close":             int(realized_pnl != 0),
        "realized_pnl":         realized_pnl,
        "role":                 "maker" if o.get("m") else "taker",
        "source":               "binance_ws",
        "timestamp_ms":         int(o.get("T", 0)),
    }

    # Primary path: route through order_manager.process_fill so closing fills
    # trigger _build_close_row_for_fill → insert_closed_position. Falls back to
    # bare db.upsert_fill if the order_manager singleton is unavailable (very
    # early startup) or if process_fill raises — the fill must always be persisted.
    try:
        from core.order_manager_singleton import order_manager
        om = order_manager
    except Exception:
        om = None

    if om is not None:
        try:
            await om.process_fill(app_state.active_account_id, fill)
            log.debug(
                "WS fill via process_fill: %s %s qty=%.4f pnl=%.4f tpid='%s'",
                fill["symbol"], trade_id, fill["quantity"], realized_pnl,
                terminal_position_id,
            )
            return
        except Exception:
            log.exception("WS fill process_fill failed — falling back to upsert_fill")

    from core.database import db
    await db.upsert_fill(fill)
    log.debug("WS fill upserted (fallback): %s %s qty=%.4f pnl=%.4f",
              fill["symbol"], trade_id, fill["quantity"], realized_pnl)


async def _refresh_positions_after_fill() -> None:
    # RL-4: skip if rate-limited (_account_refresh_loop covers drift)
    if app_state.ws_status.is_rate_limited:
        log.debug("_refresh_positions_after_fill: skipping — rate-limited")
        return
    async with trade_event_sem:
        try:
            await fetch_account()
            await fetch_positions(force=True)
            # force=True: fill-triggered refresh must always be accepted,
            # even if WS updated recently (avoids 30s delay on position close).
        except RateLimitError as e:
            handle_rate_limit_error(e)
            log.warning("Rate limit hit in _refresh_positions_after_fill: %s", e)
        except Exception as e:
            app_state.ws_status.add_log(f"Post-fill refresh error: {e}")


async def _user_data_loop(listen_key: str, attempt: int = 0) -> None:
    ws_adapter = _get_ws_adapter()
    url = ws_adapter.build_user_stream_url(listen_key) if ws_adapter else f"{config.FSTREAM_WS}/{listen_key}"
    ws  = app_state.ws_status
    ws.add_log(f"User-data WS connecting (attempt {attempt+1})")
    # corr-tap: ws_connect (spec §5.4b)
    correlation_log.emit("ws_manager", "binance", "internal",
                         correlation_log.CAT_WS_CONNECT,
                         {"stream": "user", "attempt": attempt + 1})
    _connected_at = None

    try:
        async with websockets.connect(
            url,
            ping_interval=config.WS_PING_INTERVAL,
            ping_timeout=30,
        ) as sock:
            ws.connected = True
            ws.reconnect_attempts = 0
            ws.using_fallback = False
            ws.user_connected_at = datetime.now(timezone.utc)  # P5-R2 door
            ws.add_log("User-data WS connected.")
            _connected_at = time.monotonic()
            # corr-tap: ws_connected
            correlation_log.emit("ws_manager", "binance", "internal",
                                 correlation_log.CAT_WS_CONNECTED,
                                 {"stream": "user"})

            # BY-WS-1: post-connect auth + topic subscription for exchanges
            # that require it (Bybit V5). Binance uses listen-key URL auth
            # and auto-sends all events, so this block is skipped.
            if ws_adapter and hasattr(ws_adapter, "requires_post_connect_auth") \
                    and ws_adapter.requires_post_connect_auth():
                from core.account_registry import account_registry
                acct = account_registry.get_active_account()
                if acct:
                    # HIGH-010 (Task 105): catch decrypt failures here so a
                    # bad master key during reconnect doesn't crash the WS
                    # loop (which would push us into the reconnect-retry
                    # cycle without surfacing the real cause). Mark the
                    # active account as auth-failed and abort this connect;
                    # the outer reconnect loop will see the flag (Task 103
                    # scheduler / WS-manager skip checks) and stop hammering.
                    from core.crypto import decrypt, CredentialDecryptionError
                    try:
                        # HIGH-029 (Task 116): decrypt() now returns
                        # SensitiveStr. Unwrap before passing to
                        # build_auth_payload — that builder constructs a
                        # JSON payload (json.dumps → str() on values) and
                        # the WS protocol embeds the raw key in the
                        # signed payload. The unwrap moves the leak
                        # surface from "any exception in build_auth_payload"
                        # to "any exception inside this short try block."
                        from core.security import SensitiveStr as _SS
                        api_key = decrypt(acct.get("api_key_enc", ""))
                        api_secret = decrypt(acct.get("api_secret_enc", ""))
                        if isinstance(api_key, _SS):
                            api_key = api_key.unwrap()
                        if isinstance(api_secret, _SS):
                            api_secret = api_secret.unwrap()
                    except CredentialDecryptionError as e:
                        log.critical(
                            "ws_manager: credential decryption failed during "
                            "WS reconnect for account_id=%s — %s. Aborting "
                            "this connect; account marked auth-failed until "
                            "credentials are re-entered.",
                            acct.get("id", "?"), e,
                        )
                        # FE-MED-034 (Task 151): redundant `from core.state
                        # import app_state` removed from this nested except
                        # block. The module-level import at line 24 already
                        # provides app_state. The inline re-import (any
                        # `from ... import name` is an assignment) made
                        # Python's compiler treat app_state as LOCAL
                        # throughout `_user_data_loop` — every reference
                        # before this except branch ran raised
                        # UnboundLocalError. The "shutdown race" framing
                        # in the FE-MED-034 filing was based on observation
                        # timing (asyncio cancel surfaces buffered task
                        # exceptions); actual mechanism is the local-
                        # shadow rule, which fires on every function call
                        # that reaches the unbound read. With the inline
                        # import gone, app_state resolves to the module-
                        # level binding throughout the function.
                        try:
                            aid = acct.get("id")
                            if aid is not None:
                                app_state.auth_failed_accounts.add(aid)
                            ws.add_log(
                                f"WS auth FAILED for account {aid}: "
                                "decryption error — update credentials in Config."
                            )
                        except Exception:
                            pass
                        return
                    auth_msg = ws_adapter.build_auth_payload(api_key, api_secret)
                    await sock.send(json.dumps(auth_msg))
                    sub_msg = ws_adapter.build_subscribe_payload(["position", "wallet", "order"])
                    await sock.send(json.dumps(sub_msg))
                    ws.add_log("User-data WS: auth + subscribe sent (position, wallet, order).")

            async for raw in sock:
                try:
                    msg = json.loads(raw)
                    await _handle_user_event(msg)
                except Exception as exc:
                    log.warning("User-data WS message error: %s", exc)
                ws.last_update = datetime.now(timezone.utc)
                ws.user_last_update = ws.last_update  # P5-R2: user-owned clock

        # P5-R2: a NORMAL close (code 1000 — e.g. Binance cycling the stream
        # or an expired/deleted listen key) makes `async for` fall through and
        # this function RETURN: the except below never fires, `connected`
        # stays True forever and no reconnect runs — the socket is dead while
        # every flag in the process says it is alive. Treat a clean
        # server-side close exactly like the error path. (The auth-failure
        # `return` above deliberately bypasses this — a bad credential must
        # not reconnect-hammer.)
        ws.connected = False
        ws.add_log("User-data WS closed by server (clean close).")
        correlation_log.emit(
            "ws_manager", "binance", "internal", correlation_log.CAT_WS_DISCONNECT,
            {"stream": "user", "reason": "clean_close",
             "uptime_s": round(time.monotonic() - _connected_at, 1) if _connected_at else None},
        )
        await _reconnect_user(attempt)

    except Exception as exc:
        ws.connected = False
        ws.add_log(f"User-data WS disconnected: {exc}")
        # corr-tap: ws_disconnect (spec §5.4b)
        correlation_log.emit(
            "ws_manager", "binance", "internal", correlation_log.CAT_WS_DISCONNECT,
            {"stream": "user", "reason": str(exc)[:200],
             "uptime_s": round(time.monotonic() - _connected_at, 1) if _connected_at else None},
        )
        await _reconnect_user(attempt)


async def _reconnect_user(attempt: int) -> None:
    global _listen_key
    # Abort reconnect if stop() has been called (e.g. during account switch)
    if _stopping:
        return
    ws = app_state.ws_status
    ws.reconnect_attempts = attempt + 1
    if attempt >= config.WS_RECONNECT_ATTEMPTS:
        # P5-R3: this used to be a PERMANENT surrender (~9 min of backoff,
        # then nothing until a manual restart) — and "staying on REST
        # fallback" was false for fills: _fallback_loop polls account/
        # positions/orderbook only, never trades, and gates on the SHARED
        # staleness clock which a healthy market socket keeps at ~0. Hand
        # off to the persistent retry loop instead (15/30/60/120 s forever,
        # stop+start per attempt, exits on connected) — the same loop that
        # already owns the failed-boot case (E2E-P5-001).
        ws.add_log("Max fast reconnects reached — handing off to the persistent retry loop.")
        try:
            from core.schedulers import spawn_user_ws_retry
            spawn_user_ws_retry()
        except Exception:
            log.error("user-WS retry hand-off failed", exc_info=True)
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

    asyncio.create_task(_user_data_loop(_listen_key, attempt + 1), name="ws-user")


# ── Market data stream (klines + book) ───────────────────────────────────────

# The stream list the CURRENT market WS subscribed with — the "old" side of
# the ws_stream_rebuild diff (spec §5.4b: the subscription-leak query needs
# old→new, and the rebuild runs after module state already changed).
_last_streams: list[str] = []


def _tap_market_frame(ev: str, parsed: dict) -> None:
    """corr-tap: ws_kline / ws_depth / ws_mark_price (CL.T1b, spec §5.4 —
    volume-gated by the registry: depth OFF, mark-price sampled-opt-in)."""
    if ev == "kline":
        correlation_log.emit("ws_manager", "binance", "in",
                             correlation_log.CAT_WS_KLINE, {},
                             symbol=parsed.get("symbol"))
    elif ev == "depthUpdate":
        correlation_log.emit("ws_manager", "binance", "in",
                             correlation_log.CAT_WS_DEPTH, {},
                             symbol=parsed.get("symbol"))
    elif ev == "markPriceUpdate":
        correlation_log.emit("ws_manager", "binance", "in",
                             correlation_log.CAT_WS_MARK_PRICE,
                             {"mark": parsed.get("mark_price")},
                             symbol=parsed.get("symbol"))


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


async def _market_stream_loop(attempt: int = 0) -> None:
    # #3 (debug 2026-06-08): keep _market_ws_task pointing at the CURRENTLY
    # running loop across self-respawns (the no-streams sleep below + the
    # reconnect path), so restart_market_streams() (calc ticker switch, #4)
    # can actually cancel the live loop. Previously these respawns started a
    # new loop via create_task WITHOUT updating the global, so after any
    # market-WS reconnect the global tracked a DEAD task: a ticker switch then
    # cancelled nothing and left the OLD symbol's @depth20 streaming alongside
    # the new one (operator: "still subscribing to velvetusdt").
    global _market_ws_task, _last_streams
    ws = app_state.ws_status
    streams = _build_market_streams()
    if not streams:
        ws.add_log("No market streams to subscribe — sleeping 10s.")
        _last_streams = []  # nothing subscribed — keep the rebuild diff honest
        await asyncio.sleep(10)
        _market_ws_task = asyncio.create_task(_market_stream_loop(0), name="ws-market")
        return

    ws_adapter = _get_ws_adapter()
    url = ws_adapter.build_market_stream_url(streams) if ws_adapter else f"{config.FSTREAM_COMB}?streams=" + "/".join(streams)
    ws.add_log(f"Market WS connecting ({len(streams)} streams, attempt {attempt+1})")
    # corr-tap: ws_connect — the FULL stream list is the §5.4b leak query's
    # ground truth ("a ws_connect whose list still contains the old symbol")
    correlation_log.emit("ws_manager", "binance", "internal",
                         correlation_log.CAT_WS_CONNECT,
                         {"stream": "market", "attempt": attempt + 1,
                          "streams": streams})
    _last_streams = list(streams)
    _connected_at = None

    try:
        async with websockets.connect(
            url,
            ping_interval=config.WS_PING_INTERVAL,
            ping_timeout=30,
        ) as sock:
            ws.add_log("Market WS connected.")
            # shell-chrome-3: the MARKET socket's own liveness. `ws.connected` is
            # the user-data socket and is deliberately left alone here.
            ws.market_connected = True
            _connected_at = time.monotonic()
            # corr-tap: ws_connected
            correlation_log.emit("ws_manager", "binance", "internal",
                                 correlation_log.CAT_WS_CONNECTED,
                                 {"stream": "market", "n_streams": len(streams)})
            async for raw in sock:
                try:
                    msg_outer = json.loads(raw)
                    msg = ws_adapter.unwrap_stream_message(msg_outer) if ws_adapter else msg_outer.get("data", msg_outer)
                    ev = ws_adapter.get_event_type(msg) if ws_adapter else msg.get("e", "")
                    # Track latency from market data events (fires at sub-second rate)
                    from core import time_sync
                    evt_ms = ws_adapter.get_event_time_ms(msg) if ws_adapter else msg.get("E", 0)
                    if evt_ms:
                        offset = time_sync.get_offset_ms(_exchange_id())
                        ws.latency_ms = round((time.time() * 1000 + offset) - evt_ms, 1)
                        # shell-chrome-3: keep a MARKET-only copy. ws.latency_ms is
                        # also written by the user-data loop, so it cannot be
                        # attributed to the market feed on its own.
                        ws.market_latency_ms = ws.latency_ms
                    # corr-tap: entry point — one chain per market frame
                    # (spec §3.2 wsm-*; categories volume-gated in emit)
                    correlation_log.tick("wsm")
                    if ev == "kline":
                        parsed = ws_adapter.parse_kline(msg) if ws_adapter else None
                        if parsed:
                            _tap_market_frame(ev, parsed)
                            app_state._data_cache.apply_kline(parsed["symbol"], parsed["candle"])
                    elif ev == "depthUpdate":
                        parsed = ws_adapter.parse_depth(msg) if ws_adapter else None
                        if parsed:
                            _tap_market_frame(ev, parsed)
                            app_state._data_cache.apply_depth(parsed["symbol"], parsed["bids"], parsed["asks"])
                    elif ev == "markPriceUpdate":
                        parsed = ws_adapter.parse_mark_price(msg) if ws_adapter else None
                        if parsed:
                            _tap_market_frame(ev, parsed)
                            app_state._data_cache.apply_mark_price(parsed["symbol"], parsed["mark_price"])
                except Exception as exc:
                    log.warning("Market WS message error: %s", exc)
                ws.last_update = datetime.now(timezone.utc)
                # shell-chrome-3: market-only frame clock — ws.last_update is also
                # stamped by the user socket AND floored by the 30 s REST refresh,
                # so only this one can detect a silently half-open market feed.
                ws.market_last_update = ws.last_update

    except Exception as exc:
        ws.market_connected = False
        ws.add_log(f"Market WS disconnected: {exc}")
        # corr-tap: ws_disconnect (spec §5.4b)
        correlation_log.emit(
            "ws_manager", "binance", "internal", correlation_log.CAT_WS_DISCONNECT,
            {"stream": "market", "reason": str(exc)[:200],
             "uptime_s": round(time.monotonic() - _connected_at, 1) if _connected_at else None},
        )
        delay = min(config.WS_RECONNECT_BASE * (2 ** attempt), config.WS_RECONNECT_MAX)
        await asyncio.sleep(delay)
        if not _stopping:
            _market_ws_task = asyncio.create_task(_market_stream_loop(attempt + 1), name="ws-market")


# ── Keepalive for listen key (must ping every 30 min) ────────────────────────

async def _keepalive_loop() -> None:
    while True:
        correlation_log.tick("sch-keepalive")  # corr-tap: entry scope (CL.T1a)
        await asyncio.sleep(25 * 60)   # 25 minutes
        if _listen_key:
            try:
                await keepalive_listen_key(_listen_key)
                app_state.ws_status.add_log("Listen key refreshed.")
                # corr-tap: ws_listenkey_keepalive (spec §5.4b)
                correlation_log.emit("ws_manager", "binance", "internal",
                                     correlation_log.CAT_WS_LISTENKEY_KEEPALIVE,
                                     {"ok": True})
            except RateLimitError as e:
                handle_rate_limit_error(e)
                log.warning("Rate limit hit in keepalive_loop: %s", e)
                correlation_log.emit("ws_manager", "binance", "internal",
                                     correlation_log.CAT_WS_LISTENKEY_KEEPALIVE,
                                     {"ok": False, "error": "rate_limit"})
            except Exception as e:
                app_state.ws_status.add_log(f"Listen key refresh failed: {e}")
                correlation_log.emit("ws_manager", "binance", "internal",
                                     correlation_log.CAT_WS_LISTENKEY_KEEPALIVE,
                                     {"ok": False, "error": str(e)[:200]})


# ── REST fallback polling ─────────────────────────────────────────────────────

async def _fallback_loop() -> None:
    """Poll REST API when WS is stale for > WS_FALLBACK_TIMEOUT seconds."""
    while True:
        correlation_log.tick("sch-ws_fallback")  # corr-tap: entry scope (CL.T1a)
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
            async with trade_event_sem:  # RL-4: serialize with trade-event burst callers
                try:
                    await fetch_account()
                    await fetch_positions()
                    if _calculator_symbol:
                        await fetch_orderbook(_calculator_symbol)
                    ws.last_update = datetime.now(timezone.utc)
                except RateLimitError as e:
                    handle_rate_limit_error(e)
                    log.warning("Rate limit hit in fallback_loop: %s", e)
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

    # Named tasks (CL.T1b, spec §4 `task` field): one logical stream keeps a
    # stable, lineage-readable name across reconnect respawns.
    _user_ws_task   = asyncio.create_task(_user_data_loop(listen_key), name="ws-user")
    _market_ws_task = asyncio.create_task(_market_stream_loop(), name="ws-market")
    _keepalive_task = asyncio.create_task(_keepalive_loop(), name="ws-keepalive")
    _fallback_task  = asyncio.create_task(_fallback_loop(), name="ws-fallback")

    app_state.ws_status.add_log("WebSocket manager started.")


def set_calculator_symbol(symbol: str) -> None:
    """Set the active calculator symbol and clean up stale caches.

    FE-8: evict old symbol's orderbook cache to prevent flicker when
    switching symbols.

    #4 (debug 2026-06-08): also REBUILD the market WS streams when the symbol
    changes. The calculator symbol is part of the market-stream set
    (_build_market_streams adds ``{sym}@depth20`` + its ticker), but changing it
    alone never re-subscribed — restart_market_streams() only fired on POSITION
    symbol changes (handlers.handle_positions_refreshed). So the WS kept
    streaming the OLD symbol's depth/ticker indefinitely, repopulating its caches
    (operator saw BOTH symbols' prices + orderbooks; cmd "still subscribing to
    velvetusdt"). Schedule the rebuild — this is a sync fn called from sync +
    async routes — and GATE it on an ACTUAL change so the 1 Hz /api/price poll
    (same symbol) never thrashes the WS. No-op when no loop is running (tests /
    very early startup; the next restart_market_streams picks up the new symbol).
    """
    global _calculator_symbol
    new_sym = symbol.upper() if symbol else None
    old_sym = _calculator_symbol
    _calculator_symbol = new_sym
    if new_sym == old_sym:
        return
    if old_sym:
        app_state.orderbook_cache.pop(old_sym, None)
    try:
        asyncio.get_running_loop()
        restart_scheduled = True
    except RuntimeError:
        restart_scheduled = False
    # corr-tap: calc_symbol_change (spec §5.4b — the leak query's trigger
    # side: a calc_symbol_change with no later ws_stream_rebuild is the bug)
    correlation_log.emit("ws_manager", "internal", "internal",
                         correlation_log.CAT_CALC_SYMBOL_CHANGE,
                         {"old": old_sym, "new": new_sym,
                          "restart_scheduled": restart_scheduled},
                         symbol=new_sym)
    if not restart_scheduled:
        return  # no running loop (test / pre-startup) — next restart applies it
    asyncio.create_task(restart_market_streams(trigger="calc_symbol_change"),
                        name="ws-restart")


async def restart_market_streams(trigger: str = "position_change") -> None:
    global _market_ws_task
    # corr-tap: ws_stream_rebuild — old→new diff (spec §5.4b). `old` is what
    # the current WS actually subscribed with (_last_streams); `new` reflects
    # the already-mutated module state this rebuild will apply.
    new_streams = _build_market_streams()
    correlation_log.emit(
        "ws_manager", "internal", "internal",
        correlation_log.CAT_WS_STREAM_REBUILD,
        {"trigger": trigger,
         "old_streams": list(_last_streams),
         "new_streams": new_streams,
         "added": sorted(set(new_streams) - set(_last_streams)),
         "removed": sorted(set(_last_streams) - set(new_streams))},
    )
    if _market_ws_task and not _market_ws_task.done():
        _market_ws_task.cancel()
    _market_ws_task = asyncio.create_task(_market_stream_loop(), name="ws-market")


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
    app_state.ws_status.market_connected = False      # shell-chrome-3
    app_state.ws_status.using_fallback = False
    app_state.ws_status.add_log("WS stopped (account switch).")
