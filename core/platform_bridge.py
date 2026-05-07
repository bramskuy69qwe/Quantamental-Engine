"""
PlatformBridge — engine-side integration for external trading platforms.

In "standalone" mode this module is completely dormant — no overhead.

In "quantower" mode:
  - Maintains persistent WebSocket connections from the Quantower plugin
    (endpoint: /ws/platform in routes.py)
  - Receives fill and position-snapshot events from the plugin and
    routes them through the same internal paths as Binance WS events
  - Pushes risk-state updates back to the plugin for chart overlays

REST fallback:
  - POST /api/platform/event         — fill events
  - POST /api/platform/positions     — position snapshots
  - GET  /api/platform/state         — pull-based state for the plugin

Module-level singleton:
    from core.platform_bridge import platform_bridge
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

import config as _cfg
from core.state import app_state, PositionInfo
from core.database import db
from core.account_registry import account_registry
from core.order_manager import OrderManager
from core.order_state import QT_STATUS_MAP, QT_ORDER_TYPE_MAP

log = logging.getLogger("platform_bridge")


# ── Quantower → internal field mapping ────────────────────────────────────────

def _normalize_symbol(qt_symbol: str) -> str:
    """Convert Quantower symbol format to engine's CCXT format.
    "BTC/USDT" → "BTCUSDT", "BTC USDT" → "BTCUSDT"
    """
    return qt_symbol.replace("/", "").replace(" ", "").replace("-", "").upper()


def _map_fill(msg: dict) -> Optional[Dict[str, Any]]:
    """Translate a Quantower fill message to internal fill representation."""
    try:
        side_str = str(msg.get("side", "")).upper()
        # Prefer explicit direction from plugin (position direction, not trade side)
        direction = str(msg.get("direction", "")).upper()
        if direction not in ("LONG", "SHORT"):
            if side_str in ("BUY", "LONG"):
                direction = "LONG"
            elif side_str in ("SELL", "SHORT"):
                direction = "SHORT"
            else:
                direction = ""   # unknown — don't guess

        symbol = _normalize_symbol(msg.get("symbol", msg.get("ticker", "")))
        ts = int(msg.get("timestamp", time.time() * 1000))
        pos_id = str(msg.get("positionId", msg.get("position_id", "")))
        return {
            "type":         "fill",
            "symbol":       symbol,
            "ticker":       symbol,       # backward compat alias
            "side":         side_str,
            "direction":    direction,
            # Dual IDs from plugin (FillEvent.cs)
            "exchange_fill_id":    str(msg.get("exchangeFillId", msg.get("exchange_fill_id", ""))),
            "terminal_fill_id":    str(msg.get("terminalFillId", msg.get("terminal_fill_id", ""))),
            "exchange_order_id":   str(msg.get("exchangeOrderId", msg.get("exchange_order_id", ""))),
            "exchange_position_id": "",     # not available from terminal fills
            "terminal_position_id": pos_id,
            "position_id":  pos_id,       # backward compat alias
            "is_close":     bool(msg.get("isClose", msg.get("is_close", False))),
            "price":        float(msg.get("price", 0)),
            "quantity":     abs(float(msg.get("quantity", msg.get("qty", 0)))),
            "gross_pnl":    float(msg.get("grossPnL", msg.get("gross_pnl", 0))),
            "realized_pnl": float(msg.get("grossPnL", msg.get("gross_pnl", 0))),
            "fee":          float(msg.get("fee", 0)),
            "fee_asset":    str(msg.get("feeAsset", msg.get("fee_asset", "USDT"))),
            "role":         str(msg.get("role", "")),
            "source":       "quantower",
            "timestamp":    ts,
            "timestamp_ms": ts,           # alias for fills DB
            "account_id":   msg.get("accountId", msg.get("account_id")),
        }
    except Exception as exc:
        log.warning("_map_fill: could not parse fill message: %r — %r", msg, exc)
        return None


def _map_position_snapshot(msg: dict) -> Optional[Dict[str, Any]]:
    """Translate a Quantower position snapshot message."""
    try:
        positions = msg.get("positions", [])
        mapped = []
        for p in positions:
            qty = float(p.get("quantity", p.get("qty", 0)))
            mapped.append({
                "position_id":  str(p.get("positionId", p.get("position_id", ""))),
                "ticker":       _normalize_symbol(p.get("symbol", p.get("ticker", ""))),
                "direction":    "LONG" if qty >= 0 else "SHORT",
                "quantity":     abs(qty),
                "avg_price":    float(p.get("avgPrice", p.get("avg_price", p.get("openPrice", 0)))),
                "unrealized":   float(p.get("unrealizedPnL", p.get("unrealized_pnl", 0))),
                "open_time_ms": int(p.get("openTimeMs", p.get("open_time_ms", 0)) or 0),
                "tp_price":     float(p["tpPrice"]) if "tpPrice" in p else (float(p["tp_price"]) if "tp_price" in p else None),
                "sl_price":     float(p["slPrice"]) if "slPrice" in p else (float(p["sl_price"]) if "sl_price" in p else None),
                "liq_price":    float(p["liquidationPrice"]) if "liquidationPrice" in p else (float(p["liq_price"]) if "liq_price" in p else None),
            })
        return {"positions": mapped, "account_id": msg.get("accountId")}
    except Exception as exc:
        log.warning("_map_position_snapshot error: %r — %r", msg, exc)
        return None


def _map_order_snapshot(msg: dict) -> list[dict]:
    """Parse an order_snapshot message from the plugin into order dicts.

    Maps Quantower camelCase JSON → engine snake_case dicts suitable for
    OrderManager.process_order_snapshot().
    """
    orders = msg.get("orders", [])
    mapped = []
    for o in orders:
        symbol = _normalize_symbol(o.get("symbol", ""))
        if not symbol:
            continue
        raw_status = o.get("status", "Opened")
        raw_type   = o.get("orderType", "Market")
        mapped.append({
            "exchange_order_id":   o.get("exchangeOrderId", ""),
            "terminal_order_id":   o.get("terminalOrderId", ""),
            "client_order_id":     o.get("clientOrderId", ""),
            "symbol":              symbol,
            "side":                o.get("side", ""),
            "order_type":          QT_ORDER_TYPE_MAP.get(raw_type, raw_type.lower()),
            "status":              QT_STATUS_MAP.get(raw_status, "new"),
            "price":               float(o.get("price", 0) or 0),
            "stop_price":          float(o.get("stopPrice", 0) or 0),
            "quantity":            float(o.get("quantity", 0) or 0),
            "filled_qty":          float(o.get("filledQuantity", 0) or 0),
            "avg_fill_price":      float(o.get("avgFillPrice", 0) or 0),
            "reduce_only":         bool(o.get("reduceOnly", False)),
            "time_in_force":       o.get("timeInForce", ""),
            "position_side":       o.get("positionSide", ""),
            "terminal_position_id": o.get("positionId", ""),
            "source":              "quantower",
            "created_at_ms":       int(o.get("createdAt", 0) or 0),
            "updated_at_ms":       int(o.get("updatedAt", o.get("createdAt", 0)) or 0),
        })
    return mapped


class PlatformBridge:
    """Manages connections from external trading platform plugins."""

    def __init__(self) -> None:
        self._ws_clients: Set[Any] = set()   # FastAPI WebSocket objects
        self._last_push: float = 0.0
        self._historical_fill_count: int = 0   # session counter for backfill
        self._metadata_populated: bool = False  # one-shot flag for metadata backfill
        self._order_manager: OrderManager = OrderManager(db)

    @property
    def order_manager(self) -> OrderManager:
        return self._order_manager

    @property
    def is_connected(self) -> bool:
        return len(self._ws_clients) > 0

    @property
    def client_count(self) -> int:
        return len(self._ws_clients)

    # ── WebSocket server (Quantower plugin connects here) ─────────────────────

    async def handle_ws(self, websocket) -> None:
        """FastAPI WebSocket handler — call from /ws/platform endpoint."""
        await websocket.accept()
        self._ws_clients.add(websocket)
        log.info("PlatformBridge: plugin connected (total=%d)", len(self._ws_clients))

        # On first connection: request a position snapshot for immediate reconciliation
        try:
            await websocket.send_text(json.dumps({"type": "request_positions"}))
        except Exception:
            pass

        # Push the current risk state so the plugin has fresh data immediately
        await self.push_risk_state()

        try:
            async for raw in websocket.iter_text():
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await self._dispatch(msg)
        except Exception:
            pass
        finally:
            self._ws_clients.discard(websocket)
            remaining = len(self._ws_clients)
            if remaining == 0:
                log.info(
                    "PlatformBridge: last plugin client disconnected — "
                    "engine now in standalone monitoring mode"
                )
            else:
                log.info("PlatformBridge: plugin disconnected (remaining=%d)", remaining)

    # ── Message dispatch ──────────────────────────────────────────────────────

    async def _dispatch(self, msg: dict) -> None:
        event_type = msg.get("type", "")
        if event_type == "fill":
            await self._handle_fill(msg)
        elif event_type == "position_snapshot":
            await self._handle_position_snapshot(msg)
        elif event_type == "account_state":
            await self._handle_account_state(msg)
        elif event_type == "historical_fill":
            await self._handle_historical_fill(msg)
        elif event_type == "hello":
            await self._handle_hello(msg)
        elif event_type == "ohlcv_bar":
            self._handle_ohlcv_bar(msg)
        elif event_type == "mark_price":
            self._handle_mark_price(msg)
        elif event_type == "depth_snapshot":
            self._handle_depth_snapshot(msg)
        elif event_type == "order_snapshot":
            await self._handle_order_snapshot(msg)
        elif event_type == "orders_changed":
            await self._handle_orders_changed()
        elif event_type == "heartbeat":
            pass  # just keep-alive — no action needed
        else:
            log.debug("PlatformBridge: unknown event type %r", event_type)

    async def _handle_historical_fill(self, msg: dict) -> None:
        """One historical Quantower trade arrived (from Core.GetTrades on
        plugin connect). Idempotent upsert into exchange_history keyed by
        a stable trade_key derived from Quantower's Trade.Id."""
        trade_id = str(msg.get("trade_id", "")).strip()
        if not trade_id:
            return

        symbol     = _normalize_symbol(str(msg.get("symbol", "")))
        side_str   = str(msg.get("side", "")).upper()
        direction  = "LONG" if side_str == "BUY" else "SHORT"
        impact     = str(msg.get("position_impact_type", "")).lower()

        try:    price = float(msg.get("price") or 0)
        except: price = 0.0
        try:    qty = float(msg.get("quantity") or 0)
        except: qty = 0.0
        try:    gross_pnl = float(msg.get("gross_pnl") or 0)
        except: gross_pnl = 0.0

        # A fill is a close if impact says so OR if it has realized PnL
        is_close = "close" in impact or "reverse" in impact or gross_pnl != 0
        try:    fee = float(msg.get("fee") or 0)
        except: fee = 0.0
        try:    ts = int(msg.get("timestamp") or 0)
        except: ts = 0

        row = {
            "trade_key":   f"qt:{trade_id}",
            "time":        ts,
            "symbol":      symbol,
            # Closing fills carry realized PnL — opens are pure entries.
            "incomeType":  "REALIZED_PNL" if is_close else "OPEN",
            "income":      gross_pnl,
            "direction":   direction,
            "entry_price": 0.0 if is_close else price,
            "exit_price":  price if is_close else 0.0,
            "qty":         qty,
            "notional":    price * qty,
            "open_time":   0 if is_close else ts,
            "fee":         fee,
            "asset":       "USDT",
        }

        try:
            aid = app_state.active_account_id

            # For closing fills, check if a REALIZED_PNL row already exists
            # for the same time+symbol+direction (partial fill from same order).
            # If so, aggregate into the existing row instead of inserting.
            merged = False
            if is_close and ts:
                async with db._conn.execute(
                    "SELECT trade_key, income, qty, fee, exit_price, notional"
                    " FROM exchange_history"
                    " WHERE time=? AND symbol=? AND direction=? AND income_type='REALIZED_PNL'"
                    " AND account_id=? LIMIT 1",
                    (ts, symbol, direction, aid),
                ) as cur:
                    existing = await cur.fetchone()
                if existing:
                    # Aggregate: sum income/qty/fee, weighted-avg exit_price
                    old_qty = float(existing[2])
                    new_total_qty = old_qty + qty
                    wavg_exit = (float(existing[4]) * old_qty + price * qty) / new_total_qty if new_total_qty else price
                    await db._conn.execute(
                        "UPDATE exchange_history SET"
                        " income=income+?, qty=?, fee=fee+?,"
                        " exit_price=?, notional=notional+?"
                        " WHERE trade_key=?",
                        (gross_pnl, new_total_qty, fee,
                         round(wavg_exit, 8), round(price * qty, 2),
                         existing[0]),
                    )
                    await db._conn.commit()
                    merged = True

            if not merged:
                await db.upsert_exchange_history([row], account_id=aid)

            # For closing fills, resolve open_time from OPEN fills for
            # the same symbol.  Try nearest before close first, then any.
            if is_close and ts:
                try:
                    tk = f"qt:{trade_id}"
                    resolved = False
                    # 1) Nearest OPEN fill before this close (within 7 days)
                    async with db._conn.execute(
                        "SELECT MAX(time) FROM exchange_history"
                        " WHERE symbol=? AND income_type='OPEN'"
                        " AND account_id=? AND time<=? AND time>?-604800000",
                        (symbol, aid, ts, ts),
                    ) as cur:
                        r = await cur.fetchone()
                    if r and r[0] and r[0] != ts:
                        await db._conn.execute(
                            "UPDATE exchange_history SET open_time=?"
                            " WHERE trade_key=? AND (open_time=0 OR open_time=?)",
                            (r[0], tk, ts),
                        )
                        resolved = True
                    # 2) Fallback: earliest OPEN fill for this symbol
                    if not resolved:
                        async with db._conn.execute(
                            "SELECT MIN(time) FROM exchange_history"
                            " WHERE symbol=? AND income_type='OPEN' AND account_id=?",
                            (symbol, aid),
                        ) as cur:
                            r = await cur.fetchone()
                        if r and r[0] and r[0] != ts:
                            await db._conn.execute(
                                "UPDATE exchange_history SET open_time=?"
                                " WHERE trade_key=? AND (open_time=0 OR open_time=?)",
                                (r[0], tk, ts),
                            )
                    await db._conn.commit()
                except Exception:
                    pass  # best-effort — reconciler can fix later

            self._historical_fill_count += 1
            # First one + every 25th — visibility without spam
            if self._historical_fill_count == 1 or self._historical_fill_count % 25 == 0:
                log.info(
                    "PlatformBridge: historical_fill received (cumulative=%d) "
                    "symbol=%s direction=%s ts=%d",
                    self._historical_fill_count, symbol, direction, ts,
                )
        except Exception as exc:
            log.warning(
                "PlatformBridge: historical_fill upsert failed (trade_id=%s): %r",
                trade_id, exc,
            )

    async def _handle_account_state(self, msg: dict) -> None:
        """Plugin pushed an account-state snapshot (broker truth).

        Replaces what `core/exchange.py:fetch_account()` would write, but
        triggered by Quantower's Account.Updated event instead of polled REST.
        Throttled on the plugin side to ~5 Hz.
        """
        def _f(key: str) -> float:
            try:
                return float(msg.get(key, 0) or 0)
            except (TypeError, ValueError):
                return 0.0

        # Apply through DataCache — locked, conflict-resolved, auto-recalculates
        await app_state._data_cache.apply_account_update_platform(
            balance=_f("balance"),
            total_equity=_f("total_equity"),
            unrealized_pnl=_f("unrealized_pnl"),
            available_margin=_f("available_margin"),
            margin_ratio=_f("margin_ratio"),
        )

        await self.push_risk_state()

    async def _handle_hello(self, msg: dict) -> None:
        """Plugin introduces itself on connect — auto-populate broker_account_id
        on the matching account row so the user does not have to type it.

        Match policy:
          1. If any account already has this broker_account_id, just activate it.
          2. Otherwise, find accounts with empty broker_account_id. If exactly
             one exists, fill it in. If multiple, log and require manual setup.
        """
        terminal          = str(msg.get("terminal", "quantower")).strip().lower()
        broker            = str(msg.get("broker", "")).strip()
        broker_account_id = str(msg.get("broker_account_id", "")).strip()
        account_name      = str(msg.get("account_name", "")).strip()

        # AdditionalInfo (full broker-side dump) is logged at DEBUG only — it's
        # noisy (~70 keys for Binance) and we already know what's in it.
        # Bump the logger to DEBUG if you need to inspect a new broker.
        add_info = msg.get("additional_info") or {}
        if isinstance(add_info, dict) and add_info and log.isEnabledFor(logging.DEBUG):
            log.debug("PlatformBridge: hello AdditionalInfo dump (%d keys):", len(add_info))
            for k, v in add_info.items():
                log.debug("    %r = %r", k, v)

        if not broker_account_id:
            log.warning("PlatformBridge: hello missing broker_account_id; ignoring")
            return

        # Already configured?
        existing = account_registry.find_by_broker_id(broker_account_id)
        if existing is not None:
            app_state.active_account_id = existing["id"]
            log.info(
                "PlatformBridge: hello received - %s/%s/%s -> existing account_id=%d (%s)",
                terminal, broker, broker_account_id, existing["id"], existing["name"],
            )
            return

        # Auto-populate path:
        #   1. Prefer empty broker_account_id rows (clean first-time setup).
        #   2. Fallback: single-account setup -> overwrite whatever's there
        #      (handles the case where a previous hello wrote a wrong value
        #      like the connection alias instead of the real UID).
        all_accounts = account_registry.list_accounts_sync()
        empty = [a for a in all_accounts if not (a.get("broker_account_id") or "").strip()]
        target: Optional[Dict[str, Any]] = None
        if len(empty) == 1:
            target = empty[0]
        elif len(empty) == 0 and len(all_accounts) == 1:
            target = all_accounts[0]
            log.info(
                "PlatformBridge: single-account setup - replacing existing "
                "broker_account_id=%r with %r from hello",
                target.get("broker_account_id"), broker_account_id,
            )

        if target is not None:
            try:
                await account_registry.update_account(
                    target["id"], broker_account_id=broker_account_id,
                )
                app_state.active_account_id = target["id"]
                log.info(
                    "PlatformBridge: hello populated broker_account_id=%s on "
                    "account_id=%d (%s) - %s/%s",
                    broker_account_id, target["id"], target["name"], terminal, broker,
                )
            except Exception as exc:
                log.error("PlatformBridge: failed to populate broker_account_id: %r", exc)
        elif len(empty) == 0:
            log.warning(
                "PlatformBridge: hello broker_account_id=%s did not match any account "
                "and no empty rows are available. Set the field manually in "
                "Settings -> Accounts.",
                broker_account_id,
            )
        else:
            log.warning(
                "PlatformBridge: hello broker_account_id=%s ambiguous - %d accounts have "
                "empty broker_account_id. Set the field manually in Settings -> Accounts. "
                "(name=%s)",
                broker_account_id, len(empty), account_name,
            )

    async def _handle_fill(self, msg: dict) -> None:
        """A Quantower trade fill arrived — refresh positions the same way a
        Binance ORDER_TRADE_UPDATE would."""
        fill = _map_fill(msg)
        if fill is None:
            return

        # Route Quantower fill to internal account via broker_account_id
        qt_account_id = fill.get("account_id")
        if qt_account_id is not None:
            matched = account_registry.find_by_broker_id(str(qt_account_id))
            if matched:
                if matched["id"] != app_state.active_account_id:
                    log.debug(
                        "PlatformBridge: fill from non-active account "
                        "broker_id=%r (matched id=%d, active=%d) — ignoring",
                        qt_account_id, matched["id"], app_state.active_account_id,
                    )
                    return
            else:
                # No broker_account_id configured — accept only in single-account setups
                all_accounts = account_registry.list_accounts_sync()
                if len(all_accounts) > 1:
                    log.warning(
                        "PlatformBridge: fill rejected — broker_account_id %r did not match "
                        "any account. Set broker_account_id on the target account.",
                        qt_account_id,
                    )
                    return
                log.debug(
                    "PlatformBridge: broker_account_id %r not configured — "
                    "accepting fill in single-account setup",
                    qt_account_id,
                )

        log.info(
            "PlatformBridge: fill received ticker=%s dir=%s qty=%s price=%s",
            fill["ticker"], fill["direction"], fill["quantity"], fill["price"],
        )

        # NEW: write to fills table + update parent order + refresh fees
        try:
            await self._order_manager.process_fill(
                app_state.active_account_id, fill,
            )
        except Exception as exc:
            log.warning("PlatformBridge: order_manager.process_fill failed: %r", exc)

        # Trigger position refresh via the same path as Binance WS
        try:
            from core.ws_manager import _refresh_positions_after_fill  # late import: circular dep
            await _refresh_positions_after_fill()
        except Exception as exc:
            log.error("PlatformBridge: position refresh after fill failed: %r", exc)

    async def _handle_order_snapshot(self, msg: dict) -> None:
        """Plugin sent a full order snapshot — delegate to OrderManager."""
        try:
            raw_count = len(msg.get("orders", []))
            order_dicts = _map_order_snapshot(msg)
            await self._order_manager.process_order_snapshot(
                app_state.active_account_id, order_dicts,
            )
            log.info(
                "PlatformBridge: order_snapshot processed (%d raw → %d mapped, %d cached open)",
                raw_count, len(order_dicts), len(self._order_manager.open_orders),
            )
        except Exception as exc:
            log.warning("PlatformBridge: _handle_order_snapshot failed: %r", exc)

    async def _handle_orders_changed(self) -> None:
        """Plugin signals that orders were added/removed — refresh TP/SL from exchange."""
        try:
            from core.exchange import fetch_open_orders_tpsl
            await fetch_open_orders_tpsl()
            log.debug("PlatformBridge: TP/SL refreshed after orders_changed signal")
        except Exception as exc:
            log.warning("PlatformBridge: fetch_open_orders_tpsl failed: %r", exc)

    async def _handle_position_snapshot(self, msg: dict) -> None:
        """Quantower pushes its full position list — reconcile against engine state.

        Broker truth always wins. This overwrites app_state.positions with the
        authoritative snapshot so P&L / exposure calculations reflect reality.
        Session-local fields (MFE, MAE, entry_timestamp) are preserved from the
        existing position when matched by (ticker, direction).
        """
        snap = _map_position_snapshot(msg)
        if snap is None:
            return

        # Index existing positions by position_id (primary) and (ticker, direction) (fallback)
        by_id  = {p.position_id: p for p in app_state.positions if p.position_id}
        by_key = {(p.ticker, p.direction): p for p in app_state.positions}

        new_positions = []
        for p in snap["positions"]:
            pos_id    = p.get("position_id", "")
            ticker    = p["ticker"]
            direction = p["direction"]
            qty       = p["quantity"]
            avg       = p["avg_price"]
            unreal    = p["unrealized"]
            notional  = avg * qty

            prev = by_id.get(pos_id) if pos_id else by_key.get((ticker, direction))

            # Derive entry_timestamp: broker open_time > prev (exchange-derived) > now
            open_time_ms = p.get("open_time_ms", 0)
            if open_time_ms > 0:
                entry_ts = datetime.fromtimestamp(
                    open_time_ms / 1000, tz=timezone.utc
                ).isoformat()
            elif prev and prev.entry_timestamp:
                entry_ts = prev.entry_timestamp
            else:
                entry_ts = None  # let populate_open_position_metadata fill it later

            # Liquidation from broker snapshot
            liq_price = p.get("liq_price", None)
            if liq_price is None:
                liq_price = prev.liquidation_price if prev else 0.0

            pi = PositionInfo(
                position_id          = pos_id,
                ticker               = ticker,
                direction            = direction,
                contract_amount      = qty,
                average              = avg,
                individual_unrealized = unreal,
                position_value_usdt  = notional,
                sector               = _cfg.get_sector(ticker),
                entry_timestamp      = entry_ts,
                # Preserve session-local fields from previous state
                session_mfe          = prev.session_mfe if prev else 0.0,
                session_mae          = prev.session_mae if prev else 0.0,
                fair_price           = prev.fair_price if prev else 0.0,
                liquidation_price    = liq_price,
                individual_fees          = prev.individual_fees if prev else 0.0,
                individual_funding_fees = prev.individual_funding_fees if prev else 0.0,
                individual_realized     = prev.individual_realized if prev else 0.0,
                individual_margin_used  = prev.individual_margin_used if prev else 0.0,
                model_name              = prev.model_name if prev else "",
                # TP/SL NOT preserved from prev — OrderManager.enrich_positions_tpsl()
                # rebuilds from orders DB below, ensuring cancel clears immediately
            )
            new_positions.append(pi)

        # Snapshot previous positions for build_final_close_row (needs full PositionInfo)
        prev_by_key = {(p.ticker, p.direction): p for p in app_state.positions}

        # Apply through DataCache (single writer — atomic, conflict-resolved)
        # DataCache handles closure detection and publishes CH_TRADE_CLOSED.
        from core.data_cache import UpdateSource
        ts_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        result = await app_state._data_cache.apply_position_snapshot(
            UpdateSource.PLATFORM, new_positions, ts_ms,
        )

        # Schedule deferred close rows for disappeared positions.
        # Use DataCache's result.closed_syms instead of manual detection
        # to avoid divergence between closure detection logic.
        if result is not None:
            for sym in result.closed_syms:
                # Find the prev position for this symbol to pass to build_final_close_row
                for key, prev_pos in prev_by_key.items():
                    if key[0] == sym:
                        log.info(
                            "PlatformBridge: position disappeared %s %s — scheduling close row",
                            prev_pos.ticker, prev_pos.direction,
                        )
                        loop = asyncio.get_running_loop()
                        loop.call_later(
                            2.0,
                            lambda p=prev_pos: asyncio.ensure_future(
                                self._order_manager.build_final_close_row(p)
                            ),
                        )

        # Enrich positions with TP/SL from orders DB (replaces prev-preservation)
        self._order_manager.enrich_positions_tpsl(new_positions)

        log.info(
            "PlatformBridge: reconciled %d position(s) from broker snapshot",
            len(new_positions),
        )

        # One-shot: derive entry_timestamp + MFE/MAE from exchange history
        # for positions that don't have them yet (first snapshot after restart)
        if not self._metadata_populated and new_positions:
            self._metadata_populated = True
            try:
                from core.exchange import populate_open_position_metadata
                asyncio.ensure_future(populate_open_position_metadata())
            except Exception:
                pass

    # ── R4: market data handlers (inbound from plugin) ────────────────────────

    def _handle_ohlcv_bar(self, msg: dict) -> None:
        """Plugin streamed one OHLCV bar → DataCache."""
        symbol = _normalize_symbol(str(msg.get("symbol", "")))
        if not symbol:
            return
        try:
            candle = [
                int(msg.get("open_time", 0)),
                float(msg.get("open", 0)),
                float(msg.get("high", 0)),
                float(msg.get("low", 0)),
                float(msg.get("close", 0)),
                float(msg.get("volume", 0)),
            ]
        except (TypeError, ValueError):
            return
        app_state._data_cache.apply_kline(symbol, candle)

    def _handle_mark_price(self, msg: dict) -> None:
        """Plugin pushed a mark-price update → DataCache."""
        symbol = _normalize_symbol(str(msg.get("symbol", "")))
        try:
            price = float(msg.get("price", 0) or 0)
        except (TypeError, ValueError):
            price = 0.0
        if not symbol or not price:
            return
        app_state._data_cache.apply_mark_price(symbol, price)

    def _handle_depth_snapshot(self, msg: dict) -> None:
        """Plugin pushed an order-book snapshot → DataCache."""
        symbol = _normalize_symbol(str(msg.get("symbol", "")))
        if not symbol:
            return
        try:
            bids = [[float(p), float(q)] for p, q in (msg.get("bids") or [])]
            asks = [[float(p), float(q)] for p, q in (msg.get("asks") or [])]
        except (TypeError, ValueError):
            return
        app_state._data_cache.apply_depth(symbol, bids, asks)

    # ── R4: outbound requests to plugin ──────────────────────────────────────

    async def _send_to_clients(self, payload: dict) -> None:
        """Send a JSON message to all connected plugin clients."""
        if not self._ws_clients:
            return
        text = json.dumps(payload)
        dead: Set[Any] = set()
        for ws in list(self._ws_clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.add(ws)
        self._ws_clients -= dead

    async def request_ohlcv(self, symbol: str, interval: str = "1m") -> None:
        """Ask the plugin to start streaming OHLCV bars for a symbol."""
        await self._send_to_clients(
            {"type": "request_ohlcv", "symbol": symbol, "interval": interval}
        )
        log.info("PlatformBridge: request_ohlcv -> plugin symbol=%s interval=%s", symbol, interval)

    async def unsubscribe_ohlcv(self, symbol: str) -> None:
        """Tell the plugin to stop streaming OHLCV bars for a symbol."""
        await self._send_to_clients({"type": "unsubscribe_ohlcv", "symbol": symbol})
        log.debug("PlatformBridge: unsubscribe_ohlcv -> plugin symbol=%s", symbol)

    async def request_depth(self, symbol: str) -> None:
        """Ask the plugin to start streaming depth snapshots for a symbol."""
        await self._send_to_clients({"type": "request_depth", "symbol": symbol})

    async def unsubscribe_depth(self, symbol: str) -> None:
        await self._send_to_clients({"type": "unsubscribe_depth", "symbol": symbol})

    # ── Push risk state to plugin ─────────────────────────────────────────────

    async def push_risk_state(self) -> None:
        """Push current risk state to all connected plugin clients.
        Called from handlers after account updates."""
        if not self._ws_clients:
            return
        payload = json.dumps(self.get_state_json())
        dead: Set[Any] = set()
        for ws in list(self._ws_clients):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        self._ws_clients -= dead
        self._last_push = time.time()

    def get_state_json(self) -> dict:
        """Build a risk-state payload for GET /api/platform/state."""
        acc = app_state.account_state
        pf  = app_state.portfolio
        return {
            "type":              "risk_state",
            "timestamp_ms":      int(time.time() * 1000),
            "account_id":        app_state.active_account_id,
            "platform":          app_state.active_platform,
            "total_equity":      acc.total_equity,
            "daily_pnl":         acc.daily_pnl,
            "daily_pnl_pct":     acc.daily_pnl_percent,
            "weekly_pnl":        pf.total_weekly_pnl,
            "drawdown":          pf.drawdown,
            "exposure":          pf.total_exposure,
            "weekly_pnl_state":  pf.weekly_pnl_state,
            "dd_state":          pf.dd_state,
            "open_positions":    len(app_state.positions),
            "positions": [
                {
                    "ticker":     p.ticker,
                    "direction":  p.direction,
                    "unrealized": p.individual_unrealized,
                    "notional":   p.position_value_usdt,
                }
                for p in app_state.positions
            ],
        }


# Module-level singleton
platform_bridge = PlatformBridge()
