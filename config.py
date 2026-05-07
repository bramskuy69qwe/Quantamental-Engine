import os
from dotenv import load_dotenv

load_dotenv()

# ── Project identity ─────────────────────────────────────────────────────────
PROJECT_NAME_    = "Quantamental Engine"
PROJECT_VERSION_ = "v2.1"
PROJECT_NAME     = f"{PROJECT_NAME_} {PROJECT_VERSION_}"  # "Quantamental Engine v2.1"

# ── Exchange ──────────────────────────────────────────────────────────────────
# NOTE: BINANCE_API_KEY / BINANCE_API_SECRET are kept for the one-time seed
# migration that imports them as Account 1 in the accounts table.
# After the first startup they are no longer the source of truth — use the
# accounts table and account_registry instead.
BINANCE_API_KEY    = os.getenv("BINANCE_API_KEY", "")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET", "")

# ── Multi-account credential encryption ───────────────────────────────────────
# Required for encrypting API keys stored in the accounts table.
# Generate once: python -c "import secrets; print(secrets.token_hex(32))"
ENV_MASTER_KEY = os.getenv("ENV_MASTER_KEY", "")
EXCHANGE_NAME      = "Binance"
MARKET_TYPE        = "future"          # USD-M perpetuals

# ── Timezone ──────────────────────────────────────────────────────────────────
TIMEZONE_OFFSET_HOURS = 7             # UTC+7

# ── Fees (Binance USD-M default tiers) ────────────────────────────────────────
MAKER_FEE = 0.0002                    # 0.02 %
TAKER_FEE = 0.0005                    # 0.05 %

# ── ATR parameters ────────────────────────────────────────────────────────────
ATR_SHORT_PERIOD = 14
ATR_LONG_PERIOD  = 100
ATR_TIMEFRAME    = "4h"
ATR_FETCH_LIMIT  = 220                # extra buffer for Wilder warm-up

# ── Correlated sectors ────────────────────────────────────────────────────────
BIG_TWO_CRYPTO = {"BTCUSDT", "ETHUSDT"}

TOP_TWENTY_ALTS = {
    "BNBUSDT",  "XRPUSDT",  "SOLUSDT",  "ADAUSDT",  "DOGEUSDT",
    "AVAXUSDT", "TRXUSDT",  "DOTUSDT",  "LINKUSDT", "MATICUSDT",
    "LTCUSDT",  "BCHUSDT",  "ATOMUSDT", "UNIUSDT",  "ICPUSDT",
    "FILUSDT",  "HBARUSDT", "APTUSDT",  "ARBUSDT",  "OPUSDT",
    "NEARUSDT", "INJUSDT",  "SUIUSDT",  "SEIUSDT",  "TIAUSDT",
}

COMMODITIES = {"XAUUSDT", "XAGUSDT"}

def get_sector(symbol: str) -> str:
    s = symbol.upper()
    if s in BIG_TWO_CRYPTO:
        return "big_two_crypto"
    if s in TOP_TWENTY_ALTS:
        return "top_twenty_alts"
    if s in COMMODITIES:
        return "commodities"
    return "other_alts"

# ── WebSocket ─────────────────────────────────────────────────────────────────
WS_PING_INTERVAL      = 20            # seconds
WS_RECONNECT_BASE     = 1.0           # exponential back-off base (seconds)
WS_RECONNECT_MAX      = 60.0
WS_RECONNECT_ATTEMPTS = 15
WS_FALLBACK_TIMEOUT   = 30            # fall back to REST after N seconds stale

# Legacy WS URLs — kept for fallback paths only.
# Canonical source: core/adapters/binance/constants.py
FSTREAM_WS   = "wss://fstream.binance.com/private/ws"
FSTREAM_COMB = "wss://fstream.binance.com/market/stream"

# ── Data paths ────────────────────────────────────────────────────────────────
DATA_DIR       = "data"
SNAPSHOTS_DIR  = f"{DATA_DIR}/snapshots"
PARAMS_FILE    = f"{DATA_DIR}/params.json"
PRE_TRADE_LOG  = f"{DATA_DIR}/pre_trade_log.csv"
EXECUTION_LOG  = f"{DATA_DIR}/execution_log.csv"
LIVE_TRADES    = f"{DATA_DIR}/live_trades_log.csv"
TRADE_HISTORY  = f"{DATA_DIR}/trade_history.csv"

# ── Infrastructure ────────────────────────────────────────────────────────────
DB_PATH  = f"{DATA_DIR}/risk_engine.db"
LOGS_DIR = f"{DATA_DIR}/logs"
LOG_FILE = f"{LOGS_DIR}/risk_engine.jsonl"

# ── HTTP proxy (optional) ─────────────────────────────────────────────────────
# Set if Binance Futures API (fapi.binance.com) is geo-restricted in your region.
# Example: HTTP_PROXY=http://127.0.0.1:7890
HTTP_PROXY = os.getenv("HTTP_PROXY", "")

# ── UI polling intervals (seconds) ───────────────────────────────────────────
DASHBOARD_POLL_INTERVAL   = 3
CALCULATOR_POLL_INTERVAL  = 2
HISTORY_POLL_INTERVAL     = 30
WS_STATUS_POLL_INTERVAL   = 5
WS_LOG_MAX_DISPLAY        = 10

# ── API Keys (DB-first fallback chain) ──────────────────────────────────────

def get_api_key(provider: str) -> str:
    """DB first (via connections_manager), then .env fallback."""
    try:
        from core.connections import connections_manager
        key = connections_manager.get_sync(provider)
        if key:
            return key
    except Exception:
        pass  # connections_manager not loaded yet during startup
    return os.getenv(f"{provider.upper()}_API_KEY", "")

# Keep module-level attributes for backward compatibility — consumers that
# read config.FRED_API_KEY will get the .env value at import time.  Modules
# that need the DB-first chain should call config.get_api_key("fred").
FRED_API_KEY = os.getenv("FRED_API_KEY", "")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
BWE_NEWS_WS_URL = os.getenv("BWE_NEWS_WS_URL", "wss://bwenews-api.bwe-ws.com/ws")

# ── Platform bridge auth ─────────────────────────────────────────────────────
# Shared secret for Quantower plugin REST/WS endpoints.
# Generate: python -c "import secrets; print(secrets.token_hex(32))"
PLATFORM_TOKEN = os.getenv("PLATFORM_TOKEN", "")

REGIME_STALE_MINUTES = 90   # current_regime older than this is treated as stale

REGIME_MULTIPLIERS = {
    "risk_on_trending":   1.2,
    "risk_on_choppy":     1.0,
    "neutral":            1.0,
    "risk_off_defensive": 0.7,
    "risk_off_panic":     0.4,
}

REGIME_THRESHOLDS = {
    "vix_panic":            30,
    "vix_defensive":        25,
    "vix_risk_on":          20,
    "vix_choppy":           22,
    "hy_spread_panic":      5.0,
    "hy_spread_defensive":  4.5,
    "hy_spread_neutral":    4.0,   # HY at/above this caps regime at neutral (no risk-on)
    "hy_spread_risk_on":    3.5,   # HY must be below this for risk-on classification
    "rvol_ratio_choppy":    1.3,
    "rvol_ratio_trending":  1.2,
    "funding_panic":        -0.01,
}
