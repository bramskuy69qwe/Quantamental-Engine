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
                "avg_price":    float(p.get("avgPrice", p.get("avg_price", p.get("open_price", 0)))),
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

    # ── WebSocket server (Quantower plugin connects here) ─────────────────────

    async def handle_ws(self, websocket) -> None:
        """FastAPI WebSocket handler — call from /ws/platform endpoint."""
        await websocket.accept()
        self._ws_clients.add(websocket)
        log.info("PlatformBridge: Quantower plugin connected (total=%d)", len(self._ws_clients))

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
            log.info("PlatformBridge: plugin disconnected (remaining=%d)", len(self._ws_clients))

    # ── Message dispatch ──────────────────────────────────────────────────────

    async def _dispatch(self, msg: dict) -> None:
        event_type = msg.get("type", "")
        if event_type == "fill":
            await self._handle_fill(msg)
        elif event_type == "position_snapshot":
            await self._handle_position_snapshot(msg)
        elif event_type == "heartbeat":
            pass  # just keep-alive — no action needed
        else:
            log.debug("PlatformBridge: unknown event type %r", event_type)

    async def _handle_fill(self, msg: dict) -> None:
        """A Quantower trade fill arrived — refresh positions the same way a
        Binance ORDER_TRADE_UPDATE would."""
        fill = _map_fill(msg)
        if fill is None:
            return

        # Guard: ignore fills from accounts other than the active one
        from core.state import app_state
        raw_acct = fill.get("account_id")
        if raw_acct is not None:
            try:
                if int(raw_acct) != app_state.active_account_id:
                    log.debug("PlatformBridge: ignoring fill from non-active account %r", raw_acct)
                    return
            except (TypeError, ValueError):
                # Empty string or non-numeric account_id means the platform sent an
                # unknown/null account — reject rather than silently accept.
                log.warning(
                    "PlatformBridge: fill rejected — invalid account_id %r (expected int)",
                    raw_acct,
                )
                return

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
        """Quantower pushes its full position list — use for reconciliation."""
        snap = _map_position_snapshot(msg)
        if snap is None:
            return
        log.info(
            "PlatformBridge: position snapshot received %d positions",
            len(snap.get("positions", [])),
        )
        # Future: reconcile snap["positions"] against app_state.positions
        # For now we rely on _refresh_positions_after_fill for live updates

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
