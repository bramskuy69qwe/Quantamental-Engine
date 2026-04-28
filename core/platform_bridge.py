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
from typing import Any, Dict, Optional, Set

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
        return {
            "type":        "fill",
            "ticker":      _normalize_symbol(msg.get("symbol", msg.get("ticker", ""))),
            "direction":   "LONG" if str(msg.get("side", "")).upper() in ("BUY", "LONG") else "SHORT",
            "price":       float(msg.get("price", 0)),
            "quantity":    abs(float(msg.get("quantity", msg.get("qty", 0)))),
            "gross_pnl":   float(msg.get("grossPnL", msg.get("gross_pnl", 0))),
            "fee":         float(msg.get("fee", 0)),
            "timestamp":   int(msg.get("timestamp", time.time() * 1000)),
            "account_id":  msg.get("accountId", msg.get("account_id")),
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
                "ticker":       _normalize_symbol(p.get("symbol", p.get("ticker", ""))),
                "direction":    "LONG" if qty >= 0 else "SHORT",
                "quantity":     abs(qty),
                "avg_price":    float(p.get("avgPrice", p.get("avg_price", p.get("openPrice", 0)))),
                "unrealized":   float(p.get("unrealizedPnL", p.get("unrealized_pnl", 0))),
            })
        return {"positions": mapped, "account_id": msg.get("accountId")}
    except Exception as exc:
        log.warning("_map_position_snapshot error: %r — %r", msg, exc)
        return None


class PlatformBridge:
    """Manages connections from external trading platform plugins."""

    def __init__(self) -> None:
        self._ws_clients: Set[Any] = set()   # FastAPI WebSocket objects
        self._last_push: float = 0.0
        self._historical_fill_count: int = 0   # session counter for backfill

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
        elif event_type == "heartbeat":
            pass  # just keep-alive — no action needed
        else:
            log.debug("PlatformBridge: unknown event type %r", event_type)

    async def _handle_historical_fill(self, msg: dict) -> None:
        """One historical Quantower trade arrived (from Core.GetTrades on
        plugin connect). Idempotent upsert into exchange_history keyed by
        a stable trade_key derived from Quantower's Trade.Id."""
        from core.db_router import db_router
        from core.state import app_state

        trade_id = str(msg.get("trade_id", "")).strip()
        if not trade_id:
            return

        symbol     = _normalize_symbol(str(msg.get("symbol", "")))
        side_str   = str(msg.get("side", "")).upper()
        direction  = "LONG" if side_str == "BUY" else "SHORT"
        impact     = str(msg.get("position_impact_type", "")).lower()
        is_close   = "close" in impact or "reverse" in impact

        try:    price = float(msg.get("price") or 0)
        except: price = 0.0
        try:    qty = float(msg.get("quantity") or 0)
        except: qty = 0.0
        try:    gross_pnl = float(msg.get("gross_pnl") or 0)
        except: gross_pnl = 0.0
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
            "asset":       "USDT",  # default for Binance Futures perps
        }

        try:
            await db_router.account.upsert_exchange_history(
                [row], account_id=app_state.active_account_id,
            )
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
        from core.state import app_state

        def _f(key: str) -> float:
            try:
                return float(msg.get(key, 0) or 0)
            except (TypeError, ValueError):
                return 0.0

        acc = app_state.account_state
        acc.balance_usdt        = _f("balance")
        acc.total_equity        = _f("total_equity")
        acc.total_unrealized    = _f("unrealized_pnl")
        acc.available_margin    = _f("available_margin")
        # Maintenance margin is not a direct AccountState field; treat the
        # gap between equity and available as margin-used (matches the
        # Binance-direct calculation in fetch_account).
        acc.total_margin_used   = max(0.0, acc.total_equity - acc.available_margin)
        acc.total_margin_ratio  = _f("margin_ratio")

        # Derived metrics (drawdown, daily_pnl, weekly_pnl, exposure) recompute
        # against the new equity. recalculate_portfolio expects the positions
        # list too — that's already maintained via position_snapshot.
        try:
            app_state.recalculate_portfolio()
        except Exception as exc:
            log.error("PlatformBridge: recalculate_portfolio after account_state failed: %r", exc)

        # Push fresh risk_state to the plugin so its UI overlays stay in sync.
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

        from core.account_registry import account_registry
        from core.state import app_state

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

    # ── R4: market data handlers (inbound from plugin) ────────────────────────

    def _handle_ohlcv_bar(self, msg: dict) -> None:
        """Plugin streamed one OHLCV bar. Updates ohlcv_cache in-place."""
        from core.state import app_state
        import config as _cfg

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

        cache = app_state.ohlcv_cache.get(symbol, [])
        if cache and cache[-1][0] == candle[0]:
            cache[-1] = candle          # replace in-progress bar
        else:
            cache.append(candle)
            if len(cache) > _cfg.ATR_FETCH_LIMIT + 10:
                cache = cache[-(_cfg.ATR_FETCH_LIMIT + 10):]
        app_state.ohlcv_cache[symbol] = cache

    def _handle_mark_price(self, msg: dict) -> None:
        """Plugin pushed a mark-price update for a symbol."""
        from core.state import app_state

        symbol = _normalize_symbol(str(msg.get("symbol", "")))
        try:
            price = float(msg.get("price", 0) or 0)
        except (TypeError, ValueError):
            price = 0.0
        if not symbol or not price:
            return

        app_state.mark_price_cache[symbol] = price
        for pos in app_state.positions:
            if pos.ticker != symbol:
                continue
            pos.fair_price = price
            if pos.average > 0:
                if pos.direction == "LONG":
                    pos.individual_unrealized = (price - pos.average) * pos.contract_amount
                else:
                    pos.individual_unrealized = (pos.average - price) * pos.contract_amount
                unreal = pos.individual_unrealized
                if unreal > pos.session_mfe:
                    pos.session_mfe = round(unreal, 2)
                if pos.session_mae == 0.0 or unreal < pos.session_mae:
                    pos.session_mae = round(unreal, 2)
            break

        app_state.account_state.total_unrealized = sum(
            p.individual_unrealized for p in app_state.positions
        )
        try:
            app_state.recalculate_portfolio()
        except Exception:
            pass

    def _handle_depth_snapshot(self, msg: dict) -> None:
        """Plugin pushed an order-book snapshot."""
        from core.state import app_state

        symbol = _normalize_symbol(str(msg.get("symbol", "")))
        if not symbol:
            return
        try:
            app_state.orderbook_cache[symbol] = {
                "bids": [[float(p), float(q)] for p, q in (msg.get("bids") or [])],
                "asks": [[float(p), float(q)] for p, q in (msg.get("asks") or [])],
            }
        except (TypeError, ValueError):
            pass

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

    async def _handle_fill(self, msg: dict) -> None:
        """A Quantower trade fill arrived — refresh positions the same way a
        Binance ORDER_TRADE_UPDATE would."""
        fill = _map_fill(msg)
        if fill is None:
            return

        from core.state import app_state
        from core.account_registry import account_registry

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

        # Trigger position refresh via the same path as Binance WS
        try:
            from core.ws_manager import _refresh_positions_after_fill
            await _refresh_positions_after_fill()
        except Exception as exc:
            log.error("PlatformBridge: position refresh after fill failed: %r", exc)

    async def _handle_position_snapshot(self, msg: dict) -> None:
        """Quantower pushes its full position list — reconcile against engine state.

        Broker truth always wins. This overwrites app_state.positions with the
        authoritative snapshot so P&L / exposure calculations reflect reality.
        """
        snap = _map_position_snapshot(msg)
        if snap is None:
            return

        from core.state import app_state, PositionInfo
        import config as _cfg

        new_positions = []
        for p in snap["positions"]:
            ticker    = p["ticker"]
            direction = p["direction"]
            qty       = p["quantity"]
            avg       = p["avg_price"]
            unreal    = p["unrealized"]
            notional  = avg * qty

            pi = PositionInfo(
                ticker               = ticker,
                direction            = direction,
                contract_amount      = qty,
                average              = avg,
                individual_unrealized = unreal,
                position_value_usdt  = notional,
                sector               = _cfg.get_sector(ticker),
            )
            new_positions.append(pi)

        app_state.positions = new_positions
        log.info(
            "PlatformBridge: reconciled %d position(s) from broker snapshot",
            len(new_positions),
        )

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
        from core.state import app_state
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
