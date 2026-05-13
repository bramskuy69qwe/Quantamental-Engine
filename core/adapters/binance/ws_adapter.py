"""
Binance USD-M Futures WebSocket adapter.

Handles: URL construction, stream naming, and message parsing for Binance
user-data and market-data WebSocket streams.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from core.adapters.registry import register_ws_adapter
from core.adapters.protocols import NormalizedPosition, NormalizedOrder
from core.adapters.binance.constants import (
    USER_STREAM_BASE,
    MARKET_STREAM_BASE,
    EVENT_ACCOUNT_UPDATE,
    EVENT_ORDER_UPDATE,
    EVENT_KLINE,
    EVENT_MARK_PRICE,
    EVENT_DEPTH,
    ORDER_TYPE_FROM_BINANCE,
    BINANCE_STATUS_MAP,
    ALGO_STATUS_MAP,
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

    # ── Post-connect auth (Binance: not needed — listen key in URL) ──────────

    def requires_post_connect_auth(self) -> bool:
        return False

    def build_auth_payload(self, api_key: str, api_secret: str):
        return None

    def build_subscribe_payload(self, topics):
        return None

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

    def parse_order_update(self, msg: dict) -> NormalizedOrder:
        """Parse ORDER_TRADE_UPDATE event into a NormalizedOrder.

        WS payload fields (inside "o" dict):
            s=symbol, S=side, o=orderType, ot=origOrderType, X=status,
            x=executionType, i=orderId, c=clientOrderId, sp=stopPrice,
            p=price, q=origQty, z=cumFilledQty, ap=avgPrice, f=timeInForce,
            R=reduceOnly, ps=positionSide, T=tradeTime, t=tradeId,
            rp=realizedProfit, l=lastFilledQty, L=lastFilledPrice
        """
        o = msg.get("o", {})
        otype = o.get("ot", o.get("o", ""))
        unified_type = ORDER_TYPE_FROM_BINANCE.get(otype, otype.lower())
        raw_status = o.get("X", "")
        status = BINANCE_STATUS_MAP.get(raw_status, "new")

        return NormalizedOrder(
            exchange_order_id=str(o.get("i", "")),
            client_order_id=o.get("c", ""),
            symbol=o.get("s", ""),
            side=o.get("S", ""),
            order_type=unified_type,
            status=status,
            price=float(o.get("p", 0) or 0),
            stop_price=float(o.get("sp", 0) or 0),
            quantity=float(o.get("q", 0) or 0),
            filled_qty=float(o.get("z", 0) or 0),
            avg_fill_price=float(o.get("ap", 0) or 0),
            reduce_only=bool(o.get("R", False)),
            time_in_force=o.get("f", ""),
            position_side=o.get("ps", ""),
            execution_type=o.get("x", ""),       # NEW, TRADE, CANCELED, AMENDMENT, EXPIRED
            created_at_ms=int(o.get("T", 0)),
            updated_at_ms=int(msg.get("T", 0)),
        )

    def parse_algo_update(self, msg: dict) -> NormalizedOrder:
        """Parse ALGO_UPDATE event into a NormalizedOrder.

        WS payload fields (inside "o" dict):
            aid=algoId, caid=clientAlgoId, at=algoType, o=orderType,
            s=symbol, S=side, ps=positionSide, X=algoStatus,
            tp=triggerPrice, p=price, q=quantity, R=reduceOnly,
            T=bookTime, ut=updateTime
        """
        o = msg.get("o", {})
        otype = o.get("o", "")
        unified_type = ORDER_TYPE_FROM_BINANCE.get(otype, otype.lower())
        raw_status = o.get("X", "")
        status = ALGO_STATUS_MAP.get(raw_status, "new")

        return NormalizedOrder(
            exchange_order_id=f"algo:{o.get('aid', '')}",
            client_order_id=o.get("caid", ""),
            symbol=o.get("s", ""),
            side=o.get("S", ""),
            order_type=unified_type,
            status=status,
            price=float(o.get("p", 0) or 0),
            stop_price=float(o.get("tp", 0) or 0),
            quantity=float(o.get("q", 0) or 0),
            filled_qty=0.0,
            reduce_only=bool(o.get("R", False)),
            time_in_force=o.get("f", "GTC"),
            position_side=o.get("ps", ""),
            execution_type=raw_status,  # reuse as lifecycle indicator
            created_at_ms=int(o.get("T", 0) or 0),
            updated_at_ms=int(o.get("ut", 0) or msg.get("T", 0) or 0),
        )

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
