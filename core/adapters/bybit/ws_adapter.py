"""
Bybit Linear Perpetual WebSocket adapter.

Handles: URL construction, stream naming, and message parsing for Bybit V5
private and public WebSocket streams.

Bybit V5 WS differences from Binance:
- Auth via HMAC signature on connect (not listen key in URL)
- Topics are subscribed after connect via JSON message
- Combined stream uses {"topic": "...", "data": [...]} format
- Position/wallet updates come as separate topics
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Dict, List, Optional, Tuple

from core.adapters.registry import register_ws_adapter
from core.adapters.protocols import NormalizedPosition
from core.adapters.bybit.constants import (
    USER_STREAM_BASE,
    MARKET_STREAM_BASE,
    TOPIC_POSITION,
    TOPIC_WALLET,
    TOPIC_KLINE,
    TOPIC_TICKERS,
    TOPIC_ORDERBOOK,
)


@register_ws_adapter("bybit", "linear_perpetual")
class BybitWSAdapter:
    """Bybit V5 Linear Perpetual WebSocket message parser and URL builder."""

    # ── URL construction ─────────────────────────────────────────────────────

    def build_user_stream_url(self, listen_key: str) -> str:
        """Bybit private WS URL — listen_key is ignored (auth via HMAC on connect)."""
        return USER_STREAM_BASE

    def build_market_streams(
        self, symbols: List[str], timeframe: str, depth_symbol: Optional[str] = None
    ) -> List[str]:
        """Build Bybit V5 topic subscription list."""
        # Map timeframe format: "4h" -> "240" (minutes for Bybit)
        tf_map = {"1m": "1", "5m": "5", "15m": "15", "30m": "30",
                  "1h": "60", "4h": "240", "1d": "D", "1w": "W"}
        bybit_tf = tf_map.get(timeframe, "240")

        streams = []
        for sym in symbols:
            streams.append(f"kline.{bybit_tf}.{sym}")
            streams.append(f"tickers.{sym}")
        if depth_symbol:
            streams.append(f"orderbook.25.{depth_symbol}")
        return streams

    def build_market_stream_url(self, streams: List[str]) -> str:
        """Bybit public linear WS URL — subscriptions sent after connect."""
        return MARKET_STREAM_BASE

    # ── Authentication helper ────────────────────────────────────────────────

    def build_auth_message(self, api_key: str, api_secret: str) -> dict:
        """Build the HMAC auth message to send after WS connect."""
        expires = int((time.time() + 10) * 1000)
        signature = hmac.HMAC(
            api_secret.encode("utf-8"),
            f"GET/realtime{expires}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {"op": "auth", "args": [api_key, expires, signature]}

    def build_subscribe_message(self, topics: List[str]) -> dict:
        """Build subscription message to send after connect."""
        return {"op": "subscribe", "args": topics}

    # ── Event type extraction ────────────────────────────────────────────────

    def get_event_type(self, msg: dict) -> str:
        """Bybit uses 'topic' field. Map to Binance-compatible event names."""
        topic = msg.get("topic", "")
        if topic.startswith("position"):
            return "ACCOUNT_UPDATE"
        if topic.startswith("wallet"):
            return "ACCOUNT_UPDATE"
        if topic.startswith("kline"):
            return "kline"
        if topic.startswith("tickers"):
            return "markPriceUpdate"
        if topic.startswith("orderbook"):
            return "depthUpdate"
        return topic

    def get_event_time_ms(self, msg: dict) -> int:
        """Extract timestamp from Bybit message."""
        return int(msg.get("ts", 0))

    def unwrap_stream_message(self, msg: dict) -> dict:
        """Bybit V5 public streams don't have a wrapper — message IS the data."""
        return msg

    # ── User data stream parsing ─────────────────────────────────────────────

    def parse_account_update(self, msg: dict) -> Tuple[dict, List[NormalizedPosition]]:
        """Parse Bybit position or wallet update.

        Bybit sends position and wallet as separate topics:
        - {"topic": "position", "data": [{...}]}
        - {"topic": "wallet", "data": [{...}]}

        Returns:
            balances: {"wallet_balance": float, "cross_wallet": float}
            positions: list of NormalizedPosition
        """
        balances: dict = {}
        positions: List[NormalizedPosition] = []

        topic = msg.get("topic", "")
        data_list = msg.get("data", [])

        if topic == "wallet":
            for wallet in data_list:
                coins = wallet.get("coin", [])
                for coin in coins:
                    if coin.get("coin") == "USDT":
                        balances["wallet_balance"] = float(coin.get("walletBalance", 0) or 0)
                        balances["cross_wallet"] = float(coin.get("equity", 0) or 0)
                        break

        elif topic == "position":
            for p in data_list:
                size = float(p.get("size", 0) or 0)
                side_raw = p.get("side", "")
                if side_raw == "Buy":
                    side = "LONG"
                elif side_raw == "Sell":
                    side = "SHORT"
                else:
                    side = "LONG" if size > 0 else "SHORT"

                positions.append(NormalizedPosition(
                    symbol=p.get("symbol", ""),
                    side=side,
                    size=abs(size),
                    contract_size=1.0,
                    entry_price=float(p.get("entryPrice", 0) or 0),
                    mark_price=float(p.get("markPrice", 0) or 0),
                    liquidation_price=float(p.get("liqPrice", 0) or 0),
                    unrealized_pnl=float(p.get("unrealisedPnl", 0) or 0),
                    initial_margin=float(p.get("positionIM", 0) or 0),
                    notional=float(p.get("positionValue", 0) or 0),
                ))

        return balances, positions

    # ── Market data stream parsing ───────────────────────────────────────────

    def parse_kline(self, msg: dict) -> Optional[Dict]:
        """Parse Bybit kline topic. Returns None if candle is not closed."""
        data_list = msg.get("data", [])
        if not data_list:
            return None

        k = data_list[0]
        if not k.get("confirm"):  # only emit closed candles
            return None

        topic = msg.get("topic", "")
        # topic format: "kline.240.BTCUSDT"
        parts = topic.split(".")
        symbol = parts[2] if len(parts) >= 3 else ""

        return {
            "symbol": symbol,
            "candle": [
                int(k.get("start", 0)),      # open time ms
                float(k.get("open", 0)),
                float(k.get("high", 0)),
                float(k.get("low", 0)),
                float(k.get("close", 0)),
                float(k.get("volume", 0)),
            ],
        }

    def parse_mark_price(self, msg: dict) -> Optional[Dict]:
        """Parse Bybit tickers topic for mark price."""
        data = msg.get("data", {})
        if isinstance(data, list):
            data = data[0] if data else {}

        symbol = data.get("symbol", "")
        mark = float(data.get("markPrice", 0) or 0)
        if not symbol or not mark:
            return None
        return {"symbol": symbol, "mark_price": mark}

    def parse_depth(self, msg: dict) -> Optional[Dict]:
        """Parse Bybit orderbook topic."""
        data = msg.get("data", {})
        symbol = data.get("s", "")
        if not symbol:
            # Try topic: "orderbook.25.BTCUSDT"
            topic = msg.get("topic", "")
            parts = topic.split(".")
            symbol = parts[2] if len(parts) >= 3 else ""

        if not symbol:
            return None

        return {
            "symbol": symbol,
            "bids": [[float(p), float(q)] for p, q in data.get("b", [])],
            "asks": [[float(p), float(q)] for p, q in data.get("a", [])],
        }
