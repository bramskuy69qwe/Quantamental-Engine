"""
MEXC Futures WebSocket adapter.

Handles: post-connect auth (signed login), channel subscription,
heartbeat, and message parsing for MEXC private data streams.

Protocol notes (from API docs):
- URL: wss://contract.mexc.com/edge
- Auth: login message with HMAC-SHA256(apiKey + reqTime, secretKey)
- Subscribe: personal.filter with filter rules per channel
- Heartbeat: client sends {"method":"ping"} every 10-20s
- Messages: {"channel":"push.xxx", "data":{...}, "symbol":"BTC_USDT", "ts":...}
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Dict, List, Optional, Tuple

from core.adapters.registry import register_ws_adapter
from core.adapters.protocols import NormalizedPosition, NormalizedOrder
from core.adapters.mexc.constants import WS_URL


def _sign_login(api_key: str, api_secret: str, req_time: int) -> str:
    """Compute HMAC-SHA256 login signature: sign(apiKey + reqTime, secret)."""
    msg = f"{api_key}{req_time}"
    return hmac.new(
        api_secret.encode("utf-8"),
        msg.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _normalize_symbol(raw: str) -> str:
    """Strip MEXC native BTC_USDT / CCXT BTC/USDT:USDT to BTCUSDT."""
    s = raw.split(":")[0]
    return s.replace("/", "").replace("_", "")


@register_ws_adapter("mexc", "linear_perpetual")
class MexcWSAdapter:
    """MEXC Futures WebSocket message parser and URL builder."""

    # ── URL construction ─────────────────────────────────────────────────────

    def build_user_stream_url(self, listen_key: str) -> str:
        """MEXC doesn't use listen keys — single WS endpoint for all streams."""
        return WS_URL

    def build_market_streams(
        self, symbols: List[str], timeframe: str, depth_symbol: Optional[str] = None
    ) -> List[str]:
        """Build MEXC stream topic names (used for subscribe payload)."""
        streams = []
        for sym in symbols:
            native = sym.replace("USDT", "_USDT") if "_" not in sym else sym
            streams.append(f"sub.kline.{native}.{timeframe}")
            streams.append(f"sub.ticker.{native}")
        if depth_symbol:
            native = depth_symbol.replace("USDT", "_USDT") if "_" not in depth_symbol else depth_symbol
            streams.append(f"sub.depth.{native}")
        return streams

    def build_market_stream_url(self, streams: List[str]) -> str:
        return WS_URL

    # ── Event type extraction ────────────────────────────────────────────────

    def get_event_type(self, msg: dict) -> str:
        """Extract event type from MEXC WS message channel field."""
        channel = msg.get("channel", "")
        if channel == "push.personal.position":
            return "ACCOUNT_UPDATE"
        if channel == "push.personal.order":
            return "ORDER_TRADE_UPDATE"
        if channel == "push.personal.order.deal":
            return "ORDER_TRADE_UPDATE"
        if channel == "push.personal.asset":
            return "ACCOUNT_UPDATE"
        if "kline" in channel:
            return "kline"
        if "ticker" in channel:
            return "markPriceUpdate"
        if "depth" in channel:
            return "depthUpdate"
        if channel == "pong":
            return "pong"
        return channel

    def get_event_time_ms(self, msg: dict) -> int:
        return int(msg.get("ts", 0))

    def unwrap_stream_message(self, msg: dict) -> dict:
        """MEXC messages don't need unwrapping — data is at top level."""
        return msg

    # ── Message parsing ──────────────────────────────────────────────────────

    def parse_account_update(self, msg: dict) -> Tuple[dict, List[NormalizedPosition]]:
        """Parse MEXC position or asset update."""
        channel = msg.get("channel", "")
        data = msg.get("data", {})

        if channel == "push.personal.asset":
            # Balance update
            balances = {
                "total_equity": float(data.get("equity", 0) or 0),
                "available_margin": float(data.get("availableBalance", 0) or 0),
                "unrealized_pnl": float(data.get("unrealized", 0) or 0),
            }
            return balances, []

        if channel == "push.personal.position":
            # Position update
            positions = []
            items = data if isinstance(data, list) else [data]
            for p in items:
                vol = abs(float(p.get("holdVol", 0) or 0))
                if vol == 0:
                    continue
                pos_type = str(p.get("positionType", "1"))
                side = "LONG" if pos_type == "1" else "SHORT"
                positions.append(NormalizedPosition(
                    symbol=_normalize_symbol(p.get("symbol", "")),
                    side=side,
                    size=vol,  # contract qty — caller multiplies by contractSize
                    entry_price=float(p.get("holdAvgPrice", 0) or 0),
                    liquidation_price=float(p.get("liquidatePrice", 0) or 0),
                    unrealized_pnl=float(p.get("unrealized", 0) or 0),
                    position_id=str(p.get("positionId", "")),
                ))
            return {}, positions

        return {}, []

    def parse_kline(self, msg: dict) -> Optional[Dict]:
        """Parse MEXC kline message."""
        data = msg.get("data", {})
        if not data:
            return None
        return {
            "symbol": _normalize_symbol(msg.get("symbol", "")),
            "open": float(data.get("o", 0) or 0),
            "high": float(data.get("h", 0) or 0),
            "low": float(data.get("l", 0) or 0),
            "close": float(data.get("c", 0) or 0),
            "volume": float(data.get("v", 0) or 0),
            "timestamp": int(data.get("t", 0)),
        }

    def parse_mark_price(self, msg: dict) -> Optional[Dict]:
        data = msg.get("data", {})
        return {
            "symbol": _normalize_symbol(msg.get("symbol", "")),
            "mark_price": float(data.get("fairPrice", data.get("lastPrice", 0)) or 0),
        }

    def parse_depth(self, msg: dict) -> Optional[Dict]:
        data = msg.get("data", {})
        return {
            "symbol": _normalize_symbol(msg.get("symbol", "")),
            "bids": data.get("bids", []),
            "asks": data.get("asks", []),
        }

    # ── Post-connect authentication ──────────────────────────────────────────

    def requires_post_connect_auth(self) -> bool:
        """MEXC requires login after WS connect."""
        return True

    def build_auth_payload(self, api_key: str, api_secret: str) -> Optional[dict]:
        """Build MEXC login message with HMAC-SHA256 signature."""
        req_time = str(int(time.time() * 1000))
        signature = _sign_login(api_key, api_secret, int(req_time))
        return {
            "method": "login",
            "param": {
                "apiKey": api_key,
                "signature": signature,
                "reqTime": req_time,
            },
        }

    def build_subscribe_payload(self, topics: List[str]) -> Optional[dict]:
        """Build MEXC subscription message for private channels."""
        filters = [
            {"filter": "position"},
            {"filter": "order"},
            {"filter": "order.deal"},
            {"filter": "asset"},
        ]
        return {
            "method": "personal.filter",
            "param": {"filters": filters},
        }

    # ── Heartbeat ────────────────────────────────────────────────────────────

    @staticmethod
    def build_ping() -> dict:
        """Build MEXC heartbeat ping message. Send every 10-20 seconds."""
        return {"method": "ping"}

    @staticmethod
    def is_pong(msg: dict) -> bool:
        """Check if a message is a pong response."""
        return msg.get("channel") == "pong"

    # ── Fill parsing (for order_manager integration) ─────────────────────────

    def parse_fill(self, msg: dict) -> Optional[dict]:
        """Parse MEXC deal (fill) message for order_manager.process_fill."""
        if msg.get("channel") != "push.personal.order.deal":
            return None
        data = msg.get("data", {})
        if not data:
            return None

        side_code = str(data.get("T", data.get("side", "")))
        side = "BUY" if side_code in ("1", "buy", "BUY") else "SELL"

        return {
            "exchange_fill_id": str(data.get("id", "")),
            "exchange_order_id": str(data.get("orderId", "")),
            "symbol": _normalize_symbol(data.get("symbol", msg.get("symbol", ""))),
            "side": side,
            "price": float(data.get("p", data.get("price", 0)) or 0),
            "quantity": float(data.get("v", data.get("vol", 0)) or 0),
            "fee": abs(float(data.get("fee", 0) or 0)),
            "timestamp_ms": int(data.get("t", data.get("timestamp", 0)) or 0),
            "source": "mexc_ws",
        }

    def parse_order_update(self, msg: dict) -> Optional[dict]:
        """Parse MEXC order update for order_manager.process_order_update."""
        if msg.get("channel") != "push.personal.order":
            return None
        data = msg.get("data", {})
        if not data:
            return None

        side_code = str(data.get("side", ""))
        side = "BUY" if side_code in ("1", "buy", "BUY") else "SELL"

        state = str(data.get("state", "")).lower()
        status_map = {
            "1": "new", "2": "filled", "3": "partially_filled",
            "4": "canceled", "5": "partially_canceled",
        }
        status = status_map.get(state, state)

        return {
            "exchange_order_id": str(data.get("orderId", "")),
            "symbol": _normalize_symbol(data.get("symbol", msg.get("symbol", ""))),
            "side": side,
            "order_type": str(data.get("orderType", "")).lower(),
            "status": status,
            "price": float(data.get("price", 0) or 0),
            "quantity": float(data.get("vol", 0) or 0),
            "filled_qty": float(data.get("dealVol", 0) or 0),
            "avg_fill_price": float(data.get("dealAvgPrice", 0) or 0),
            "source": "mexc_ws",
        }
