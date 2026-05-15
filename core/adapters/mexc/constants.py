"""
MEXC Futures — exchange-specific constants.
"""

# ── Base URLs ────────────────────────────────────────────────────────────────
BASE_URL = "https://contract.mexc.com"
WS_URL = "wss://contract.mexc.com/edge"

# ── Auth header names ────────────────────────────────────────────────────────
HEADER_API_KEY = "ApiKey"
HEADER_REQ_TIME = "Request-Time"
HEADER_SIGNATURE = "Signature"
HEADER_RECV_WINDOW = "Recv-Window"
DEFAULT_RECV_WINDOW_MS = 10_000   # ±10s default, max 60s

# ── Rate limits (count-based, NOT weight-based) ─────────────────────────────
# MEXC uses 20 requests / 2 seconds per endpoint category.
# We use a unified conservative budget (v2.4). Per-category tracking is v2.5+.
MAX_REQUESTS_WINDOW = 20
RATE_LIMIT_WINDOW_SECONDS = 2
RATE_LIMIT_ERROR_CODE = 510

# ── REST limits ──────────────────────────────────────────────────────────────
OHLCV_LIMIT = 2000

# ── REST endpoint paths ──────────────────────────────────────────────────────
EP_ACCOUNT_ASSETS = "/api/v1/private/account/assets"
EP_OPEN_POSITIONS = "/api/v1/private/position/open_positions"
EP_OPEN_ORDERS = "/api/v1/private/order/list/open_orders"
EP_ORDER_DEALS = "/api/v1/private/order/list/order_deals"
EP_CONTRACT_DETAIL = "/api/v1/contract/detail"
EP_TICKER = "/api/v1/contract/ticker"
EP_DEPTH = "/api/v1/contract/depth"

# ── Error codes ──────────────────────────────────────────────────────────────
ERR_SUCCESS = 0
ERR_RATE_LIMIT = 510
ERR_TIMESTAMP_INVALID = 513
ERR_PARAM_ERROR = 600
ERR_CONTRACT_NOT_EXIST = 1001
ERR_INSUFFICIENT_BALANCE = 2005

# ── WS topics (informational — WS adapter is Task 38) ───────────────────────
WS_TOPIC_POSITION = "sub.personal.position"
WS_TOPIC_ORDER = "sub.personal.order"
WS_TOPIC_ASSET = "sub.personal.asset"
