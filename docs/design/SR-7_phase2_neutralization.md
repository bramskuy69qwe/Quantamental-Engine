# SR-7 Phase 2: Neutralization Proposals

**Date**: 2026-05-11
**Depends on**: Phase 1 enumeration (`SR-7_phase1_enumeration.md`)
**Scope**: Groups 1-5 (protocol changes). Group 6 filed separately.

---

## Group 1: Currency / Sizing

### 1.1 Currency field on NormalizedAccount

**Current**: No currency field. Both adapters assume USDT. Bybit WS
explicitly filters `coin == "USDT"`.

**Proposed**:
```python
@dataclass
class NormalizedAccount:
    currency: str = "USDT"       # Settlement/collateral currency
    total_equity: float = 0.0
    ...
```

**Rationale**: Multi-currency accounts (BTC-margined, multi-asset
portfolios) become representable. Consumer code can assert
`account.currency == expected` rather than assuming.

**Migration cost**: LOW
- protocols.py: add field (1 line)
- binance/rest_adapter.py: set `currency="USDT"` in NormalizedAccount (1 line)
- bybit/rest_adapter.py: same (1 line)
- Consumers: no change needed (default preserves behavior)

**Trade-offs**: Could model as `currencies: Dict[str, float]` for
multi-asset margin accounts. Rejected: adds complexity before a real
multi-asset adapter exists. Single `currency` field is sufficient for
USDM/USDT-margined accounts. Can extend later if inverse adapters land.

---

### 1.2 contract_size = 1.0 assumption

**Current**: Both adapters hardcode `contract_size=1.0` in
NormalizedPosition. Correct for linear USDM contracts. Wrong for
inverse contracts (e.g., Bybit inverse: 1 contract = $100 of BTC).

**Proposed**: No change to the field. Instead, add a comment clarifying
that `contract_size` is populated by the adapter from market info:

```python
contract_size: float = 1.0     # From exchange market info. 1.0 for linear.
                                # Adapters MUST query this from load_markets()
                                # for inverse/quanto contracts.
```

**Rationale**: The protocol field is already correct — it's the adapters
that are lazy. When inverse adapters are added, they'll populate this
from `market["contractSize"]` (already available via CCXT). No protocol
change needed.

**Migration cost**: ZERO (protocol unchanged; adapter fix is future work
when inverse support lands)

---

### 1.3 Qty unit conventions

**Current**: `size` on NormalizedPosition is "absolute quantity in base
asset" per the docstring. Both adapters comply (Binance: abs(positionAmt),
Bybit: contracts field). `quantity` on NormalizedOrder/NormalizedTrade
is undocumented but both adapters use base-asset quantity.

**Proposed**: Add explicit docstring to NormalizedOrder.quantity and
NormalizedTrade.quantity:

```python
quantity: float = 0.0           # Base-asset quantity (e.g., 0.5 BTC).
                                # NOT contract count for inverse.
                                # Adapters convert from native units.
```

**Rationale**: Makes the convention explicit so future adapters don't
accidentally pass contract counts for inverse pairs. No runtime change.

**Migration cost**: ZERO (docstring only)

---

## Group 2: Order Semantics

### 2.1 Order types: enum extension vs structural change

**Current**: `order_type` is a normalized string enum:
`limit / market / stop_loss / take_profit / trailing_stop`.

**Option A — Enum extension** (recommended):
Add types as needed: `stop_loss_limit`, `take_profit_limit`.
Keep flat string enum. TP/SL linkage via new fields (see 2.6).

**Option B — Structural change**:
Replace string with a richer type hierarchy:
```python
@dataclass
class OrderType:
    base: str = ""              # "limit" / "market"
    trigger: Optional[str] = None  # "stop_loss" / "take_profit"
    trigger_price: float = 0.0
```

**Recommendation**: Option A. The existing flat enum is consumed by
OrderManager state machine, DB queries, and templates. A structural
change would require touching 20+ files. The real linkage problem
(which order is the TP for which position?) is solved by new fields
on NormalizedOrder, not by changing the type enum.

**Proposed addition to order_type values**:
```
Current:  limit | market | stop_loss | take_profit | trailing_stop
Add:      stop_loss_limit | take_profit_limit
```

**Migration cost**: LOW
- protocols.py: docstring update
- Adapter type-mapping dicts: add 2 entries each
- Consumers: no change (unrecognized types already fall through)

---

### 2.2 reduce_only as Optional

**Current**: `reduce_only: bool = False` — required field.

**Proposed**:
```python
reduce_only: Optional[bool] = None   # None = not applicable / not set
```

**Rationale**: Per Q3 resolution in AUDIT_REPORT.md — "data-only, no
downstream consumer." Adapters set when the exchange provides it; core
never reads it for decisions. `None` means "exchange didn't report this
field" (e.g., spot orders). `False` means "exchange explicitly said
not reduce-only."

**Migration cost**: LOW
- protocols.py: change type (1 line)
- Binance adapter: already sets True/False from exchange — no change
- Bybit adapter: already sets from exchange — no change
- Consumers: grep shows no code reads `order.reduce_only` for logic.
  DB stores it but doesn't query on it. Safe change.

---

### 2.3 position_side as Optional

**Current**: `position_side: str = ""` — empty string as sentinel for
"not set."

**Proposed**:
```python
position_side: Optional[str] = None  # "LONG" / "SHORT" / None
                                      # None = one-way mode or not applicable
```

**Rationale**: Empty string as sentinel is fragile (can't distinguish
"not set" from "exchange returned empty string"). `None` is explicit.
One-way mode accounts don't have position_side. Optional makes this
representable without fake values.

**Migration cost**: LOW
- protocols.py: change type (1 line)
- Adapters: replace `""` with `None` for one-way mode (2 lines each)
- Consumers: check `if order.position_side` already handles both `None`
  and `""` the same way (both falsy). No logic changes.

---

### 2.4 is_close: explicit field, not heuristic

**Current**: `is_close: bool = False` on NormalizedTrade. Populated by
heuristic: Binance `realizedPnl != 0`, Bybit `closedPnl != 0`.

**Proposed**: Keep the field but change the contract:

```python
is_close: bool = False          # Adapter MUST set definitively from
                                # exchange-specific signals. NOT a
                                # heuristic. Use: positionSide + side
                                # combination, or explicit close flag.
```

Adapters should use deterministic logic:
- Binance: `side == close_side_for_position` (SELL for LONG position,
  BUY for SHORT position) when positionSide is known
- Bybit: `closedSize > 0` field (available in V5 trade response)
- Fallback: `realizedPnl != 0` only when no better signal exists

**Rationale**: The `realizedPnl != 0` heuristic fails for:
- Partial closes where PnL rounds to exactly 0
- Funding fee events that set realizedPnl on non-close trades
Making it adapter-responsibility ensures each exchange uses its best signal.

**Migration cost**: MEDIUM
- protocols.py: docstring update (1 line)
- binance/rest_adapter.py: improve is_close logic (~5 lines)
- bybit/rest_adapter.py: use closedSize field (~3 lines)
- Consumers: no change (field type unchanged)

---

### 2.5 fee_source indicator

**Current**: No way to distinguish live-fetched fees from hardcoded
defaults. Bybit hardcodes; Binance fetches live.

**Proposed**: Add to NormalizedAccount:
```python
fee_source: str = "default"     # "live" | "default"
                                # "live": fetched from exchange API
                                # "default": hardcoded/configured fallback
```

**Rationale**: Consumers (sizing, analytics) can warn or adjust when
fees are defaults. Surfaces the AD-1 compliance variance without
requiring all adapters to fetch live fees.

**Migration cost**: LOW
- protocols.py: add field (1 line)
- binance/rest_adapter.py: `fee_source="live"` (1 line)
- bybit/rest_adapter.py: `fee_source="default"` (1 line)
- Consumers: informational only, no logic change required

---

### 2.6 Order linkage (parent_id, child_orders, oca_group_id)

**Current**: No linkage between a market entry order and its
associated TP/SL orders. `fetch_open_orders_tpsl` in exchange.py
infers linkage by matching symbol + order type — fragile for
multi-position-per-symbol scenarios.

**Proposed**: Add optional linkage fields to NormalizedOrder:
```python
# Order linkage (for TP/SL → parent relationship)
parent_order_id: Optional[str] = None   # Exchange order ID of parent
oca_group_id: Optional[str] = None      # One-cancels-all group ID
```

**Rationale**:
- Binance: TP/SL orders reference the parent via the same symbol +
  positionSide. No explicit parent_order_id in API. `oca_group_id`
  not available.
- Bybit V5: `orderLinkId` provides explicit linkage. `ocoTriggerBy`
  exists for OCO groups.
- For Binance, adapters set `parent_order_id = None` (linkage inferred
  by consumer). For Bybit, adapters can populate directly.

**Migration cost**: LOW
- protocols.py: add 2 Optional fields (2 lines)
- Adapters: Binance leaves as None. Bybit populates if available.
- Consumers: existing `fetch_open_orders_tpsl` logic unchanged
  initially. Can migrate to use linkage fields in a future pass.

**Open question**: Should `child_orders: List[str]` also exist on the
parent? This creates a circular reference concern during streaming
updates (child arrives before parent). Recommend: parent_order_id on
children only; consumer builds the reverse mapping if needed.

---

## Group 3: Connection Lifecycle

### 3.1 Listen key methods → SupportsListenKey protocol

**Current**: `create_listen_key()` and `keepalive_listen_key()` on
ExchangeAdapter. Bybit stubs them (returns placeholder, no-op).

**Proposed**: Move to optional protocol:
```python
@runtime_checkable
class SupportsListenKey(Protocol):
    """Exchange uses a token-based user-data stream (Binance pattern)."""
    async def create_listen_key(self) -> str: ...
    async def keepalive_listen_key(self, key: str) -> None: ...
```

Remove from ExchangeAdapter. Callers check:
```python
if isinstance(adapter, SupportsListenKey):
    key = await adapter.create_listen_key()
```

**Rationale**: Clean separation. Bybit no longer pretends to support
listen keys. Adapters only implement what they actually do.

**Migration cost**: MEDIUM
- protocols.py: move 2 methods to new protocol (5 lines)
- exchange.py: `create_listen_key()` and `keepalive_listen_key()` callers
  add isinstance check (~4 call sites)
- ws_manager.py: `_keepalive_loop` guards with isinstance check
- binance/rest_adapter.py: add `SupportsListenKey` to class bases
- bybit/rest_adapter.py: remove stubs (2 methods deleted)

---

### 3.2 Authentication model abstraction

**Current**: ws_manager.py knows about listen keys but not about HMAC
auth. Bybit WS connection requires `build_auth_message()` and
`build_subscribe_message()` post-connect, which aren't in the WSAdapter
protocol.

**Proposed**: Add to WSAdapter protocol:
```python
def requires_post_connect_auth(self) -> bool:
    """Whether WS connection needs auth messages after connect."""
    ...

def build_auth_payload(self) -> Optional[dict]:
    """Return auth message to send after connect, or None."""
    ...

def build_subscribe_payload(self, topics: List[str]) -> Optional[dict]:
    """Return subscription message, or None if topics are in URL."""
    ...
```

**Rationale**: Abstracts the two auth models (listen-key-in-URL vs
post-connect-HMAC) behind a common interface. ws_manager can handle
both without exchange-specific branching.

**Migration cost**: MEDIUM
- protocols.py: add 3 methods to WSAdapter (6 lines)
- binance/ws_adapter.py: `requires_post_connect_auth() → False`,
  `build_auth_payload() → None`, `build_subscribe_payload() → None`
- bybit/ws_adapter.py: implement with existing HMAC logic
- ws_manager.py: add post-connect auth/subscribe step (~10 lines)

---

### 3.3 WebSocket subscription contract

**Current**: WSAdapter methods operate at wire-message level
(`build_market_streams`, `parse_kline`, `parse_mark_price`, etc.).
Every method has completely different implementation per exchange.

**Proposed**: Keep the current parse-level contract. Do NOT abstract to
"emit PositionEvent objects" level — that would require a complete
event-driven redesign beyond SR-7 scope.

Instead, formalize the existing contract with clearer docstrings and
a defined event type enum:

```python
class WSEventType:
    ACCOUNT_UPDATE = "ACCOUNT_UPDATE"
    ORDER_UPDATE = "ORDER_TRADE_UPDATE"
    KLINE = "kline"
    MARK_PRICE = "markPriceUpdate"
    DEPTH = "depthUpdate"
```

Bybit's `get_event_type()` already maps to these constants. Making them
explicit in the protocol ensures future adapters use the same values.

**Rationale**: The parse methods ARE the abstraction boundary. They take
vendor-specific wire messages and return normalized dicts. This is the
right level — attempting to abstract higher would require rearchitecting
ws_manager.py (huge blast radius, not in SR-7 scope).

**Migration cost**: LOW
- protocols.py: add WSEventType constants (5 lines)
- Adapters: reference constants instead of string literals
- ws_manager.py: reference constants instead of string literals

---

## Group 4: Market Data

### 4.1 aggTrades neutralization

**Option A — Neutral aggTrade dataclass**:
```python
@dataclass
class NormalizedAggTrade:
    price: float
    quantity: float
    timestamp_ms: int
    is_buyer_maker: bool = False
```
Both adapters translate from native shape. Consumer (`_agg_extremes`)
iterates over `NormalizedAggTrade` objects.

**Trade-offs (A)**:
- Pro: Clean typed objects, no fake field names
- Con: Creates objects for potentially 10,000+ trades per call. Memory
  and GC pressure. `_agg_extremes` only reads price — quantity and
  is_buyer_maker are wasted allocations.

**Option B — fetch_extremes_in_window** (RECOMMENDED):
```python
async def fetch_price_extremes(
    self, symbol: str, start_ms: int, end_ms: int
) -> Tuple[Optional[float], Optional[float]]:
    """Return (max_price, min_price) for the window, or (None, None).
    
    Implementation-specific: may use aggTrades, public trades,
    tick-level data, or OHLCV depending on exchange capabilities.
    """
    ...
```

Remove `fetch_agg_trades` from ExchangeAdapter. The only consumer is
`_agg_extremes` in exchange_market.py, which already reduces the full
trade stream to just (max, min). Move the reduction INTO the adapter.

**Trade-offs (B)**:
- Pro: Consumer doesn't know or care about aggTrades. Bybit can use
  its native `fetch_trades` + filter without faking Binance format.
  Zero memory waste — adapter streams and reduces in O(1) space.
- Con: Loses raw trade data access via protocol. Mitigated: `get_ccxt_
  instance()` escape hatch exists for raw access. No current consumer
  needs raw aggTrades other than for extremes.
- Con: Adapter now owns the pagination logic (which is Binance-specific
  1000-trade pages). But this is GOOD — pagination differences are
  exactly what adapters should encapsulate.

**Recommendation**: Option B. The protocol should express consumer
intent (price extremes for MFE/MAE), not implementation mechanism
(aggTrades).

**Migration cost**: MEDIUM
- protocols.py: replace `fetch_agg_trades` with `fetch_price_extremes`
- binance/rest_adapter.py: move `_agg_extremes` pagination logic from
  exchange_market.py into adapter method (~40 lines)
- bybit/rest_adapter.py: implement with native fetch_trades + reduce
- exchange_market.py: delete `_agg_extremes`, call adapter method
- exchange.py `fetch_hl_for_trade`: call adapter.fetch_price_extremes
  instead of exchange_market._agg_extremes

**Open question**: Should `fetch_price_extremes` also accept a
`resolution` hint (e.g., "tick" vs "1m") so the adapter can choose
between aggTrades and OHLCV? Current `fetch_hl_for_trade` already does
this tiering logic — should it move to the adapter entirely?

---

### 4.2 Funding rate neutralization

**Current**: `fetch_current_funding_rates(symbols)` returns
`{symbol: {"funding_rate": float, "next_funding_time": int, "mark_price": float}}`.
Both adapters implement with different endpoints but same return shape.

**Proposed**: No change to the method signature. The return shape is
already neutral. Add a `NormalizedFundingRate` dataclass for type safety:

```python
@dataclass
class NormalizedFundingRate:
    symbol: str = ""
    funding_rate: float = 0.0
    next_funding_time_ms: int = 0
    mark_price: float = 0.0
```

Change return type: `Dict[str, NormalizedFundingRate]`.

**Migration cost**: LOW
- protocols.py: add dataclass, change return type signature
- Both adapters: return NormalizedFundingRate instead of dict
- Consumers: update attribute access from `["funding_rate"]` to
  `.funding_rate` (~3 call sites in regime_fetcher.py, schedulers.py)

---

### 4.3 OHLCV consistency

**Current**: Both adapters delegate to CCXT `fetch_ohlcv`. Return format
is `List[List]` (CCXT standard: `[[timestamp, open, high, low, close, volume], ...]`).
No vendor-specific quirks in either implementation.

**Proposed**: No change. Already vendor-neutral.

The only difference is `ohlcv_limit` (1500 Binance vs 200 Bybit). This
is correctly exposed as a property so callers can paginate accordingly.

---

## Group 5: Error Types

### 5.1 Neutral error taxonomy

**Current**: RL-1/RL-3 catch `ccxt.RateLimitExceeded` and
`ccxt.DDoSProtection` directly. Ties all callers to CCXT exception
hierarchy.

**Proposed**: Define adapter-neutral exception hierarchy:

```python
# core/adapters/errors.py

class AdapterError(Exception):
    """Base for all adapter-raised errors."""
    pass

class RateLimitError(AdapterError):
    """429 / rate-limit / DDoS protection. May include backoff hint."""
    def __init__(self, message: str = "", retry_after_ms: Optional[int] = None):
        super().__init__(message)
        self.retry_after_ms = retry_after_ms

class AuthenticationError(AdapterError):
    """API key invalid, expired, or insufficient permissions."""
    pass

class ConnectionError(AdapterError):
    """Network-level failure: timeout, DNS, connection refused."""
    pass

class ValidationError(AdapterError):
    """Request rejected by exchange: invalid params, insufficient margin."""
    pass

class ExchangeError(AdapterError):
    """Exchange-side error: maintenance, internal error, unknown."""
    pass
```

**Mapping from ccxt**:
| ccxt exception | Neutral type |
|----------------|-------------|
| ccxt.RateLimitExceeded | RateLimitError |
| ccxt.DDoSProtection | RateLimitError (with retry_after_ms parsed) |
| ccxt.AuthenticationError | AuthenticationError |
| ccxt.NetworkError, ccxt.RequestTimeout | ConnectionError |
| ccxt.InvalidOrder, ccxt.InsufficientFunds | ValidationError |
| ccxt.ExchangeError, ccxt.ExchangeNotAvailable | ExchangeError |

**Where translation happens**: Inside each adapter method. Adapters
catch ccxt exceptions and re-raise as neutral types. Callers never
import ccxt.

**Migration cost**: HIGH (but scoped to adapter boundary)
- New file: `core/adapters/errors.py` (~30 lines)
- Both adapters: wrap all CCXT calls in try/except, re-raise neutral
  (~20 sites per adapter, systematic)
- All 11 RL-3 catch sites: change from `ccxt.RateLimitExceeded` to
  `RateLimitError` (11 lines, mechanical)
- `handle_rate_limit_error()`: change parameter type annotation
- exchange_market.py: change 2 catch sites
- schedulers.py: change 2 catch sites
- regime_fetcher.py: change 2 isinstance checks

**Trade-off**: Could defer this to after SR-7 implementation lands
(Phase 4) as a separate commit. The protocol redesign works without
neutral errors — they're additive, not blocking. However, doing it
during SR-7 avoids re-touching RL-3 catch sites twice.

**Recommendation**: Include in SR-7 scope. The adapter boundary is
being redesigned anyway; this is the natural time to clean up the
error crossing too.

---

### 5.2 RL-3 mapping to neutral types

**Current RL-3 pattern**:
```python
except (ccxt.RateLimitExceeded, ccxt.DDoSProtection) as e:
    handle_rate_limit_error(e)
```

**Post-SR-7 pattern**:
```python
except RateLimitError as e:
    handle_rate_limit_error(e)
```

`handle_rate_limit_error()` already parses the message string for
"banned until <epoch>". With `RateLimitError.retry_after_ms`, the
adapter can pre-parse and the handler just reads the field:

```python
def handle_rate_limit_error(exc: RateLimitError) -> None:
    ws = app_state.ws_status
    if exc.retry_after_ms:
        ws.rate_limited_until = datetime.fromtimestamp(
            exc.retry_after_ms / 1000, tz=timezone.utc
        )
    else:
        ws.rate_limited_until = datetime.now(timezone.utc) + timedelta(seconds=120)
```

**Migration cost**: Covered by 5.1 above.

---

## Summary: Migration Cost Estimates

| Group | Item | Cost | Lines touched |
|-------|------|------|---------------|
| 1.1 | currency field | LOW | ~5 |
| 1.2 | contract_size | ZERO | 0 (comment only) |
| 1.3 | qty conventions | ZERO | 0 (docstring only) |
| 2.1 | order type extension | LOW | ~10 |
| 2.2 | reduce_only Optional | LOW | ~3 |
| 2.3 | position_side Optional | LOW | ~5 |
| 2.4 | is_close deterministic | MEDIUM | ~15 |
| 2.5 | fee_source indicator | LOW | ~5 |
| 2.6 | order linkage fields | LOW | ~5 |
| 3.1 | SupportsListenKey | MEDIUM | ~20 |
| 3.2 | auth model abstraction | MEDIUM | ~25 |
| 3.3 | WS event type constants | LOW | ~15 |
| 4.1 | fetch_price_extremes | MEDIUM | ~80 |
| 4.2 | NormalizedFundingRate | LOW | ~15 |
| 4.3 | OHLCV | ZERO | 0 |
| 5.1 | Neutral error types | HIGH | ~100 |

**Total estimated**: ~300 lines of changes across ~15 files.
Largest items: fetch_price_extremes (pagination logic moves) and
neutral error types (systematic catch-site changes).

---

## Open Questions for User

1. **fetch_price_extremes resolution hint** (4.1): Should the adapter
   own the tier logic (aggTrades for <3min, OHLCV for longer), or
   should the caller pass a hint? Current: caller owns tier logic in
   `fetch_hl_for_trade`. Moving it to adapter makes the adapter
   smarter but less composable.

2. **Neutral errors timing** (5.1): Include in SR-7 Phase 4
   implementation, or defer to a separate finding (SR-7b)? Including
   it means SR-7 touches RL-3 catch sites. Deferring means those sites
   get touched twice.

3. **child_orders[] on parent** (2.6): Include reverse mapping field,
   or let consumers build it? Recommend: omit for now, add if a
   consumer needs it.
