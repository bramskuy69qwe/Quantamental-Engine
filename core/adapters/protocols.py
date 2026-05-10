"""
Normalized data models and Protocol definitions for exchange adapters.

All adapters must return these normalized shapes — consumers never see
exchange-specific field names or response structures.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol, Tuple, runtime_checkable


# ── Normalized response shapes ───────────────────────────────────────────────

@dataclass
class NormalizedAccount:
    """Exchange-agnostic account balance snapshot."""
    currency: str = "USDT"         # Settlement/collateral currency
    total_equity: float = 0.0
    available_margin: float = 0.0
    unrealized_pnl: float = 0.0
    initial_margin: float = 0.0
    maint_margin: float = 0.0
    fee_tier: str = ""
    maker_fee: float = 0.0
    taker_fee: float = 0.0
    fee_source: str = "default"    # "live" (from exchange API) | "default" (hardcoded/config)


@dataclass
class NormalizedPosition:
    """Exchange-agnostic open position."""
    symbol: str = ""
    side: str = ""                  # "LONG" | "SHORT"
    size: float = 0.0              # Absolute quantity in base asset
    contract_size: float = 1.0     # Multiplier (1.0 for linear, varies for inverse)
    entry_price: float = 0.0
    mark_price: float = 0.0
    liquidation_price: float = 0.0
    unrealized_pnl: float = 0.0
    initial_margin: float = 0.0
    notional: float = 0.0
    position_id: str = ""          # broker/exchange position ID


@dataclass
class NormalizedOrder:
    """Exchange-agnostic order. Maps to `orders` DB table."""
    # Identity
    exchange_order_id: str = ""     # exchange-assigned (Binance orderId, Bybit orderId)
    terminal_order_id: str = ""     # terminal-assigned (Quantower UniqueId) — empty from REST
    client_order_id: str = ""       # user/client-assigned (Binance clientOrderId)
    # Core fields (original 5 kept in place for backward compat)
    symbol: str = ""
    side: str = ""                  # BUY / SELL
    order_type: str = ""            # limit / market / stop_loss / take_profit / trailing_stop
    status: str = ""                # new / partially_filled / filled / canceled / expired / rejected
    price: float = 0.0              # limit price
    stop_price: float = 0.0         # trigger price (TP/SL)
    quantity: float = 0.0           # original qty
    filled_qty: float = 0.0         # cumulative filled
    avg_fill_price: float = 0.0     # VWAP of fills
    reduce_only: Optional[bool] = None   # None = not applicable / not reported
    time_in_force: str = ""         # GTC / IOC / FOK / GTX
    # Position linkage (hedge mode)
    position_side: Optional[str] = None  # "LONG" / "SHORT" / None (one-way mode)
    # Order linkage (TP/SL → parent relationship)
    parent_order_id: Optional[str] = None   # Exchange order ID of parent
    oca_group_id: Optional[str] = None      # One-cancels-all group ID
    # Timestamps
    created_at_ms: int = 0
    updated_at_ms: int = 0


@dataclass
class NormalizedTrade:
    """Exchange-agnostic trade fill. Maps to `fills` DB table."""
    # Identity
    exchange_fill_id: str = ""      # exchange trade ID (Binance id, Bybit execId)
    exchange_order_id: str = ""     # parent order (Binance orderId)
    terminal_fill_id: str = ""      # terminal trade ID — empty from REST
    terminal_position_id: str = ""  # terminal position ID — empty from REST
    # Core fields (original 7 kept for backward compat)
    symbol: str = ""
    side: str = ""                  # BUY / SELL
    direction: str = ""             # LONG / SHORT (from positionSide, not inferred from side)
    price: float = 0.0
    quantity: float = 0.0
    fee: float = 0.0
    fee_asset: str = ""
    role: str = ""                  # maker / taker
    is_close: bool = False          # closing vs opening fill
    realized_pnl: float = 0.0      # gross PnL for closing fills
    timestamp_ms: int = 0
    trade_id: str = ""              # DEPRECATED — alias of exchange_fill_id, remove in v2.3


@dataclass
class NormalizedIncome:
    """Exchange-agnostic income/PnL event."""
    symbol: str = ""
    income_type: str = ""          # "realized_pnl" | "funding_fee" | "commission" | "transfer"
    amount: float = 0.0
    timestamp_ms: int = 0
    trade_id: str = ""


@dataclass
class NormalizedFundingRate:
    """Exchange-agnostic live funding rate snapshot."""
    symbol: str = ""
    funding_rate: float = 0.0
    next_funding_time_ms: int = 0
    mark_price: float = 0.0


class WSEventType:
    """Canonical event type strings for WebSocket adapter → consumer contract."""
    ACCOUNT_UPDATE = "ACCOUNT_UPDATE"
    ORDER_UPDATE = "ORDER_TRADE_UPDATE"
    KLINE = "kline"
    MARK_PRICE = "markPriceUpdate"
    DEPTH = "depthUpdate"


# ── Protocol definitions ─────────────────────────────────────────────────────

@runtime_checkable
class ExchangeAdapter(Protocol):
    """REST adapter — what every exchange implementation must provide."""

    exchange_id: str
    market_type: str

    @property
    def ohlcv_limit(self) -> int:
        """Max candles per single OHLCV request."""
        ...

    async def fetch_account(self) -> NormalizedAccount:
        """Fetch account balances and margin info."""
        ...

    async def fetch_positions(self) -> List[NormalizedPosition]:
        """Fetch all open positions."""
        ...

    async def fetch_open_orders(self) -> List[NormalizedOrder]:
        """Fetch all open orders (TP/SL/limit)."""
        ...

    async def fetch_user_trades(self, symbol: str, limit: int = 200) -> List[NormalizedTrade]:
        """Fetch recent fills for a symbol."""
        ...

    async def fetch_order_history(self, symbol: str = "", limit: int = 100) -> List[NormalizedOrder]:
        """Fetch historical orders (all statuses). Optional — returns [] if not supported."""
        ...

    async def fetch_income(
        self,
        income_type: str = "",
        start_ms: Optional[int] = None,
        end_ms: Optional[int] = None,
        limit: int = 1000,
    ) -> List[NormalizedIncome]:
        """Fetch income history (PnL, funding, commissions)."""
        ...

    async def fetch_price_extremes(
        self,
        symbol: str,
        start_ms: int,
        end_ms: int,
        precision: str = "auto",
    ) -> Tuple[Optional[float], Optional[float]]:
        """Return (max_price, min_price) for the time window.

        precision hint (adapter maps to native resolution):
          "high"   — tick-level (aggTrades or equivalent)
          "medium" — 1m OHLCV
          "low"    — 1h OHLCV
          "auto"   — adapter decides based on window duration
        Returns (None, None) on error or no data.
        """
        ...

    async def fetch_ohlcv(
        self, symbol: str, timeframe: str = "4h", limit: int = 220, since_ms: Optional[int] = None
    ) -> List:
        """Fetch OHLCV candles."""
        ...

    async def load_markets(self) -> None:
        """Load exchange market info (precision, limits, etc.)."""
        ...

    def get_precision(self, symbol: str) -> Dict[str, int]:
        """Return precision info: {"price": N, "amount": N}."""
        ...

    def round_price(self, symbol: str, price: float) -> float:
        """Round price to exchange-required precision."""
        ...

    def round_amount(self, symbol: str, amount: float) -> float:
        """Round order amount to exchange-required precision."""
        ...

    def normalize_symbol(self, raw_symbol: str) -> str:
        """Convert exchange-native symbol to unified format (e.g. BTCUSDT)."""
        ...

    def denormalize_symbol(self, unified_symbol: str) -> str:
        """Convert unified symbol to exchange-native format."""
        ...

    async def fetch_current_funding_rates(self, symbols: List[str]) -> Dict[str, "NormalizedFundingRate"]:
        """Fetch live funding rate + next funding time + mark price for symbols.

        Returns:
            {symbol: NormalizedFundingRate}
        """
        ...

    def get_ccxt_instance(self):
        """Return underlying CCXT instance (escape hatch for edge cases)."""
        ...


@runtime_checkable
class WSAdapter(Protocol):
    """WebSocket adapter — exchange-specific stream handling."""

    def build_user_stream_url(self, listen_key: str) -> str:
        """Construct the user data stream WebSocket URL."""
        ...

    def build_market_streams(
        self, symbols: List[str], timeframe: str, depth_symbol: Optional[str] = None
    ) -> List[str]:
        """Build stream subscription names for market data."""
        ...

    def build_market_stream_url(self, streams: List[str]) -> str:
        """Construct the combined market data WebSocket URL."""
        ...

    def get_event_type(self, msg: dict) -> str:
        """Extract the event type string from a WS message."""
        ...

    def get_event_time_ms(self, msg: dict) -> int:
        """Extract event timestamp (ms) from a WS message."""
        ...

    def parse_account_update(self, msg: dict) -> Tuple[dict, List[NormalizedPosition]]:
        """Parse account/balance update. Returns (balances_dict, position_updates)."""
        ...

    def parse_kline(self, msg: dict) -> Optional[Dict]:
        """Parse kline/candlestick message. Returns None if candle is not closed."""
        ...

    def parse_mark_price(self, msg: dict) -> Optional[Dict]:
        """Parse mark price update. Returns {"symbol": str, "mark_price": float}."""
        ...

    def parse_depth(self, msg: dict) -> Optional[Dict]:
        """Parse orderbook depth update."""
        ...

    def unwrap_stream_message(self, msg: dict) -> dict:
        """Unwrap combined-stream envelope to get the inner data payload."""
        ...

    # ── Post-connect authentication ─────────────────────────────────────────

    def requires_post_connect_auth(self) -> bool:
        """Whether WS connection needs auth messages sent after connect."""
        ...

    def build_auth_payload(self, api_key: str, api_secret: str) -> Optional[dict]:
        """Return auth message to send after connect, or None if not needed."""
        ...

    def build_subscribe_payload(self, topics: List[str]) -> Optional[dict]:
        """Return subscription message, or None if topics are in URL."""
        ...


# ── Optional capability protocols ────────────────────────────────────────────

@runtime_checkable
class SupportsListenKey(Protocol):
    """Exchange uses a token-based user-data stream (Binance pattern)."""

    async def create_listen_key(self) -> str:
        """Create a user-data stream listen key."""
        ...

    async def keepalive_listen_key(self, key: str) -> None:
        """Refresh/keepalive the listen key."""
        ...


@runtime_checkable
class SupportsFundingRates(Protocol):
    """Exchange supports perpetual funding rate history."""
    async def fetch_funding_rates(
        self, symbol: str, start_ms: int, end_ms: int, limit: int = 1000
    ) -> List[Dict]:
        ...


@runtime_checkable
class SupportsOpenInterest(Protocol):
    """Exchange supports open interest history."""
    async def fetch_open_interest_hist(
        self, symbol: str, period: str, start_ms: int, end_ms: int, limit: int = 500
    ) -> List[Dict]:
        ...
