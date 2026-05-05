"""
Binance USD-M Futures WebSocket adapter.

Handles: URL construction, stream naming, and message parsing for Binance
user-data and market-data WebSocket streams.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from core.adapters.registry import register_ws_adapter
from core.adapters.protocols import NormalizedPosition
from core.adapters.binance.constants import (
    USER_STREAM_BASE,
    MARKET_STREAM_BASE,
    EVENT_ACCOUNT_UPDATE,
    EVENT_KLINE,
    EVENT_MARK_PRICE,
    EVENT_DEPTH,
)


@register_ws_adapter("binance", "linear_perpetual")
class BinanceWSAdapter:
    """Binance USD-M Futures WebSocket message parser and URL builder."""

    # ── URL construction ─────────────────────────────────────────────────────

    def build_user_stream_url(self, listen_key: str) -> str:
        return f"{USER_STREAM_BASE}/{listen_key}"

    def build_market_streams(
        self, symbols: List[str], timeframe: str, depth_symbol: Optional[str] = None
    ) -> List[str]:
        """Build Binance stream subscription names."""
        streams = []
        for sym in symbols:
            s = sym.lower()
            streams.append(f"{s}@kline_{timeframe}")
            streams.append(f"{s}@markPrice@1s")
        if depth_symbol:
            streams.append(f"{depth_symbol.lower()}@depth20")
        return streams

    def build_market_stream_url(self, streams: List[str]) -> str:
        return f"{MARKET_STREAM_BASE}?streams=" + "/".join(streams)

    # ── Event type extraction ────────────────────────────────────────────────

    def get_event_type(self, msg: dict) -> str:
        return msg.get("e", "")

    def get_event_time_ms(self, msg: dict) -> int:
        return msg.get("E", 0)

    def unwrap_stream_message(self, msg: dict) -> dict:
        """Binance combined streams wrap payload in {"stream": ..., "data": ...}."""
        return msg.get("data", msg)

    # ── User data stream parsing ─────────────────────────────────────────────

    def parse_account_update(self, msg: dict) -> Tuple[dict, List[NormalizedPosition]]:
        """Parse ACCOUNT_UPDATE event.

        Returns:
            balances: {"wallet_balance": float, "cross_wallet": float}
            positions: list of NormalizedPosition (only non-zero positions)
        """
        balances: dict = {}
        positions: List[NormalizedPosition] = []

        for b in msg.get("a", {}).get("B", []):
            if b.get("a") == "USDT":
                balances["wallet_balance"] = float(b.get("wb") or 0)
                balances["cross_wallet"] = float(b.get("cw") or 0)

        for p in msg.get("a", {}).get("P", []):
            amt = float(p.get("pa") or 0)
            positions.append(NormalizedPosition(
                symbol=p.get("s", ""),
                side="LONG" if amt > 0 else "SHORT",
                size=abs(amt),
                contract_size=1.0,
                entry_price=float(p.get("ep") or 0),
                mark_price=0.0,
                liquidation_price=0.0,
                unrealized_pnl=float(p.get("up") or 0),
                initial_margin=0.0,
                notional=0.0,
            ))

        return balances, positions

    # ── Market data stream parsing ───────────────────────────────────────────

    def parse_kline(self, msg: dict) -> Optional[Dict]:
        """Parse kline event. Returns None if candle is not closed yet."""
        k = msg.get("k", {})
        if not k.get("x"):  # only emit closed candles
            return None
        return {
            "symbol": msg.get("s", ""),
            "candle": [
                k["t"],              # open time ms
                float(k["o"]),       # open
                float(k["h"]),       # high
                float(k["l"]),       # low
                float(k["c"]),       # close
                float(k["v"]),       # volume
            ],
        }

    def parse_mark_price(self, msg: dict) -> Optional[Dict]:
        """Parse markPriceUpdate event."""
        sym = msg.get("s", "")
        mark = float(msg.get("p", 0) or 0)
        if not sym or not mark:
            return None
        return {"symbol": sym, "mark_price": mark}

    def parse_depth(self, msg: dict) -> Optional[Dict]:
        """Parse depthUpdate event (level 20 orderbook)."""
        sym = msg.get("s", "")
        if not sym:
            return None
        return {
            "symbol": sym,
            "bids": [[float(p), float(q)] for p, q in msg.get("b", [])],
            "asks": [[float(p), float(q)] for p, q in msg.get("a", [])],
        }
