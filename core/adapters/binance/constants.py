"""
Binance USD-M Futures — exchange-specific constants.
"""

# ── WebSocket endpoints ──────────────────────────────────────────────────────
USER_STREAM_BASE = "wss://fstream.binance.com/private/ws"
MARKET_STREAM_BASE = "wss://fstream.binance.com/market/stream"

# ── REST limits ──────────────────────────────────────────────────────────────
OHLCV_LIMIT = 1500          # Max candles per single request

# ── Order type mapping: unified -> Binance ────────────────────────────────────
ORDER_TYPE_TO_BINANCE = {
    "take_profit": "TAKE_PROFIT_MARKET",
    "stop_loss": "STOP_MARKET",
    "limit": "LIMIT",
    "market": "MARKET",
}

# ── Order type mapping: Binance -> unified ────────────────────────────────────
ORDER_TYPE_FROM_BINANCE = {
    "TAKE_PROFIT": "take_profit",
    "TAKE_PROFIT_MARKET": "take_profit",
    "STOP": "stop_loss",
    "STOP_MARKET": "stop_loss",
    "LIMIT": "limit",
    "MARKET": "market",
    "TRAILING_STOP_MARKET": "trailing_stop",
}

# ── Order status mapping: Binance -> unified ─────────────────────────────────
BINANCE_STATUS_MAP = {
    "NEW":              "new",
    "PARTIALLY_FILLED": "partially_filled",
    "FILLED":           "filled",
    "CANCELED":         "canceled",
    "EXPIRED":          "expired",
    "REJECTED":         "rejected",
    "NEW_INSURANCE":    "new",
    "NEW_ADL":          "new",
}

# ── WS event types ───────────────────────────────────────────────────────────
EVENT_ACCOUNT_UPDATE = "ACCOUNT_UPDATE"
EVENT_ORDER_UPDATE = "ORDER_TRADE_UPDATE"
EVENT_KLINE = "kline"
EVENT_MARK_PRICE = "markPriceUpdate"
EVENT_DEPTH = "depthUpdate"
