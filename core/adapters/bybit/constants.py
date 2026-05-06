"""
Bybit Linear Perpetual — exchange-specific constants.
"""

# ── WebSocket endpoints (V5 API) ─────────────────────────────────────────────
USER_STREAM_BASE = "wss://stream.bybit.com/v5/private"
MARKET_STREAM_BASE = "wss://stream.bybit.com/v5/public/linear"

# ── REST limits ──────────────────────────────────────────────────────────────
OHLCV_LIMIT = 200          # Max candles per single request (Bybit V5)

# ── Order type mapping: unified -> Bybit ─────────────────────────────────────
ORDER_TYPE_TO_BYBIT = {
    "take_profit": "TakeProfit",
    "stop_loss": "StopLoss",
    "limit": "Limit",
    "market": "Market",
}

# ── Order type mapping: Bybit -> unified ─────────────────────────────────────
ORDER_TYPE_FROM_BYBIT = {
    "TakeProfit": "take_profit",
    "StopLoss": "stop_loss",
    "Limit": "limit",
    "Market": "market",
    "Stop": "stop_loss",
}

# ── Order status mapping: Bybit -> unified ───────────────────────────────────
BYBIT_STATUS_MAP = {
    "New":              "new",
    "PartiallyFilled":  "partially_filled",
    "Filled":           "filled",
    "Cancelled":        "canceled",
    "Rejected":         "rejected",
    "Deactivated":      "expired",
    "Untriggered":      "new",
    "Triggered":        "new",
}

# CCXT-normalized status → unified (CCXT lowercases Bybit statuses)
BYBIT_CCXT_STATUS_MAP = {
    "open":     "new",
    "closed":   "filled",
    "canceled":  "canceled",
    "expired":   "expired",
    "rejected":  "rejected",
}

# ── WS topic prefixes ────────────────────────────────────────────────────────
TOPIC_POSITION = "position"
TOPIC_WALLET = "wallet"
TOPIC_ORDER = "order"
TOPIC_KLINE = "kline"
TOPIC_TICKERS = "tickers"
TOPIC_ORDERBOOK = "orderbook"
