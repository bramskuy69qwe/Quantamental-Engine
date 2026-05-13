# Bybit Linear Perpetuals Adapter

Maintenance interface for the Bybit V5 Linear adapter. Covers the API
surface, WS events, configuration assumptions, known quirks, and
verification status. Each entry is marked as VERIFIED, LISTED, or
ASSUMED — see legend below.

**Legend:**
- **VERIFIED (date)**: Tested against live API or exercised in audit commits
- **LISTED (date)**: Present in adapter code but not exercised during audit
- **ASSUMED**: Based on CCXT introspection or docs reading without verification

**Last reviewed**: 2026-05-13
**Adapter code**: `core/adapters/bybit/rest_adapter.py`, `ws_adapter.py`, `constants.py`
**CCXT version**: >=4.3.20 (`ccxt.bybit` with `defaultType: "linear"`)
**CCXT class**: `ccxt.bybit` (generic, not a Bybit-specific subclass like Binance's `binanceusdm`)

---

## API Surface

### REST Endpoints Used

| Bybit V5 Path | Purpose | Adapter Method | Status | Notes |
|---|---|---|---|---|
| GET /v5/account/wallet-balance | Account equity, margin, unrealized PnL | `fetch_account()` | LISTED (2026-05-13) | Via CCXT `fetch_balance(type="unified")`. USDT coin entry extracted for precision. |
| GET /v5/account/fee-rate | Live per-user maker/taker fee rates | `fetch_account()` | VERIFIED (2026-05-13) | AD-3: discovered during audit. Params: `category=linear, symbol=BTCUSDT`. Fallback to VIP0 defaults on failure. |
| GET /v5/position/list | Open positions (all USDT-settled) | `fetch_positions()` | LISTED (2026-05-13) | Via CCXT `fetch_positions(settleCoin=USDT)`. Maps positionIdx for hedge mode. |
| GET /v5/order/realtime | Open orders (basic, not conditional) | `fetch_open_orders()` | LISTED (2026-05-13) | Via CCXT `fetch_open_orders(category=linear)`. Status via `BYBIT_CCXT_STATUS_MAP`. |
| GET /v5/execution/list | Trade fills (per-symbol) | `fetch_user_trades()` | VERIFIED (2026-05-13) | AD-4: is_close logic verified. Uses positionIdx for hedge mode direction. |
| GET /v5/order/history | Closed/canceled order history | `fetch_order_history()` | LISTED (2026-05-13) | Checks `info.stopOrderType` for TP/SL type mapping. |
| GET /v5/position/closed-pnl | Realized PnL history | `_fetch_closed_pnl()` | VERIFIED (2026-05-13) | AD-2: routed for REALIZED_PNL income type. Returns closedPnl per order. |
| GET /v5/account/contract-transaction-log | Unified transaction log (funding, settlement, etc.) | `_fetch_transaction_log()` | VERIFIED (2026-05-13) | AD-2: discovered during audit. Supports type filtering (TRADE, SETTLEMENT, TRANSFER_IN). |
| GET /v5/market/kline | OHLCV candles | `fetch_ohlcv()` | LISTED (2026-05-13) | Limit capped at 200 per request. Timeframe mapping in adapter. |
| GET /v5/market/orderbook | Depth snapshot | `fetch_orderbook()` | LISTED (2026-05-13) | Via CCXT `fetch_order_book()`. |
| GET /v5/market/tickers | Mark price + funding rate | `fetch_mark_price()`, `fetch_current_funding_rates()` | LISTED (2026-05-13) | Tickers endpoint serves both mark price and live funding rate. |
| GET /v5/market/time | Server timestamp | `fetch_server_time()` | LISTED (2026-05-13) | Via CCXT `fetch_time()`. |
| GET /v5/public/funding/history | Historical funding rates | `fetch_funding_rates()` | LISTED (2026-05-13) | Via CCXT `fetch_funding_rate_history()`. |
| GET /v5/public/trading-history | Public trades (tick-level) | `fetch_price_extremes()` tier 1 | LISTED (2026-05-13) | Used for high-precision MFE/MAE on short trades (<3 min). |

**Not used**: Listen key endpoints — Bybit authenticates WS via HMAC signature on connect, not listen keys.

**Not used**: Conditional/algo order endpoints — Bybit conditional order handling not yet investigated (differs from Binance's algo API). ASSUMED: Bybit has `/v5/order/create` with `triggerPrice` for conditional placement.

### WebSocket Events Handled

| Topic Prefix | Mapped Event | Handler | Parser | Status |
|---|---|---|---|---|
| `position` | `ACCOUNT_UPDATE` | `_apply_account_update()` | `parse_account_update()` | LISTED (2026-05-13) |
| `wallet` | `ACCOUNT_UPDATE` | `_apply_account_update()` | `parse_account_update()` | LISTED (2026-05-13) |
| `kline.{tf}.{sym}` | `kline` | `_on_market_data()` inline | `parse_kline()` | LISTED (2026-05-13) |
| `tickers.{sym}` | `markPriceUpdate` | `_on_market_data()` inline | `parse_mark_price()` | LISTED (2026-05-13) |
| `orderbook.25.{sym}` | `depthUpdate` | `_on_market_data()` inline | `parse_depth()` | LISTED (2026-05-13) |

### WebSocket Events NOT Handled

| Topic | Purpose | Why Not Handled |
|---|---|---|
| `order` | Order lifecycle updates | Topic prefix defined in constants (`TOPIC_ORDER`) but no `parse_order_update()` method on BybitWSAdapter. Engine receives these but can't parse them. |
| `execution` | Fill events | Not subscribed. Would require adding topic subscription + parser. |
| `stopOrder` | Conditional order triggers | Not implemented. Bybit conditional order WS support is a gap. |

### WebSocket Architecture

```
Private stream (authenticated):
  URL: wss://stream.bybit.com/v5/private
  Auth: HMAC-SHA256 post-connect message
    {"op": "auth", "args": [api_key, expires_ms, signature]}
    signature = HMAC(secret, "GET/realtime{expires}")
  Subscribe: {"op": "subscribe", "args": ["position", "wallet"]}
  Keepalive: Bybit ping/pong (handled by websockets library)

Public stream (market data):
  URL: wss://stream.bybit.com/v5/public/linear
  No auth required.
  Subscribe: {"op": "subscribe", "args": ["kline.240.BTCUSDT", "tickers.BTCUSDT", ...]}
  Dynamic: Streams rebuilt when positions change.
```

**Key difference from Binance**: Bybit uses post-connect HMAC auth (not
listen keys). No keepalive endpoint needed — Bybit handles via ping/pong.
The `build_user_stream_url()` method ignores the listen_key parameter.

---

## Account Configuration Assumptions

| Setting | Value | Status |
|---|---|---|
| Account type | Unified Trading Account (UTA) | ASSUMED — adapter calls `/v5/account/wallet-balance` which requires UTA |
| Contract type | Linear perpetuals (USDT-settled) | LISTED — `category=linear` passed to all V5 calls |
| Position mode | Hedge mode supported via positionIdx | VERIFIED (2026-05-13) — AD-4 confirmed positionIdx 1=LONG, 2=SHORT |
| One-way mode | Supported with closedPnl fallback | VERIFIED (2026-05-13) — AD-4: positionIdx=0, is_close falls back to closedPnl heuristic |
| Inverse contracts | Not supported | ASSUMED — adapter hardcodes `category=linear` |
| CCXT class | `ccxt.bybit` (generic) | LISTED — exchange_factory.py uses generic `getattr(ccxt, "bybit")` fallback |

---

## Authentication

- **REST**: API key + secret, HMAC SHA256 signature (standard CCXT handling)
- **WS**: Post-connect auth message with HMAC signature of `"GET/realtime{expires}"`
- **Storage**: Same encrypted accounts table as Binance (`api_key_enc`, `api_secret_enc`)
- **Required permissions**: Contract Trading (read + trade), Account (read)
- **No listen keys**: Unlike Binance, Bybit WS auth is stateless (no key to create/refresh)

---

## Rate Limits

| Aspect | Detail | Status |
|---|---|---|
| Model | Per-API-key, request-count based (not weight-based like Binance) | ASSUMED — Bybit docs state limits per endpoint per 5s window |
| Engine handling | Same `RateLimitError` hierarchy (SR-7) as Binance | LISTED |
| Fee-rate endpoint | Unknown limit — called once per `fetch_account()` invocation | ASSUMED |
| Transaction log | Unknown limit | ASSUMED |
| Closed-pnl | 100 per page, paginated | LISTED |

**Gap**: Rate limit behavior is less thoroughly verified than Binance. No
equivalent of RL-3's 11-site coverage audit has been done for Bybit-specific
rate limiting.

---

## Known Quirks

### Hedge Mode: positionIdx (VERIFIED, AD-4)
Bybit uses `positionIdx` (1=LONG, 2=SHORT, 0=one-way) rather than Binance's
`positionSide` (LONG/SHORT/BOTH). The adapter maps these to the same
`direction` field. AD-4 verified that is_close logic using positionIdx +
side is deterministic in hedge mode.

### closedPnl Unreliable for is_close (VERIFIED, AD-4)
`closedPnl = 0` for break-even closes. The adapter falls back to this
heuristic only in one-way mode (positionIdx=0) where position direction
is unavailable. Known limitation filed as AD-4-B (v2.4 candidate).

### Per-User Fee Endpoint Exists (VERIFIED, AD-3)
`/v5/account/fee-rate` returns actual maker/taker rates. This was missed
in initial Phase 0 enumeration ("no per-user commission rate endpoint").
The AD-3 fix uses it with VIP0 fallback.

### Income Type Routing Required (VERIFIED, AD-2)
Bybit has no single unified income endpoint. Routing:
- REALIZED_PNL → `/v5/position/closed-pnl`
- FUNDING_FEE → `/v5/account/contract-transaction-log?type=SETTLEMENT`
- COMMISSION → not separately exposed (embedded in trade execution)
Initial enumeration incorrectly claimed "no unified endpoint" — the
transaction log IS unified, just with different field names.

### WS Order Events: Gap
BybitWSAdapter defines `TOPIC_ORDER = "order"` in constants but has NO
`parse_order_update()` method. The engine's WS manager checks
`hasattr(ws_adapter, "parse_order_update")` and skips if absent. This
means Bybit order events received via WS are silently dropped. Filing
for future work.

### No Conditional/Algo Order Support
Bybit conditional orders (TP/SL) are not yet supported. Unlike Binance
(which required discovering a separate API surface in OM-5), Bybit
conditional orders may use the same `/v5/order/create` endpoint with
`triggerPrice`. Investigation needed.

### CCXT Generic Class
Engine uses `ccxt.bybit` (generic) rather than a futures-specific subclass.
This means `load_markets()` loads ALL Bybit markets (spot, linear, inverse,
option). The adapter filters by `category=linear` per call. Binance avoids
this via `ccxt.binanceusdm` which only loads futures markets.

---

## Recent Migrations / Watch List

### No Known Recent Migrations
Bybit's V5 API has been stable since its introduction. No equivalent of
Binance's December 2025 conditional→algo migration has been observed.

### Watch Items
- Bybit V5 conditional order API surface — may differ from standard order
  placement. Investigate before implementing TP/SL support.
- Bybit rate limit model — verify actual limits before increasing call frequency
- WS order event parsing — `parse_order_update()` missing, blocking real-time
  order visibility on Bybit

---

## Changelog Watch

- **Source**: https://bybit-exchange.github.io/docs/changelog/v5
- **Cadence**: Monthly or before each engine release
- **Last reviewed**: 2026-05-13 (AD-2/3/4 scope only)
- **Process**: Check for endpoint deprecations, field renames, new event types.
  Cross-reference against this document.

---

## Cross-References

### Adapter Code
| File | Purpose |
|---|---|
| `core/adapters/bybit/rest_adapter.py` | REST API wrapper (BybitLinearAdapter) |
| `core/adapters/bybit/ws_adapter.py` | WS message parsers (BybitWSAdapter) |
| `core/adapters/bybit/constants.py` | URLs, type/status mappings, topic prefixes |
| `core/adapters/protocols.py` | Vendor-neutral adapter protocol (shared with Binance) |
| `core/exchange_factory.py` | CCXT instance cache (generic fallback for Bybit) |

### Audit Findings Touching This Adapter
| Finding | Status | Impact |
|---|---|---|
| AD-2 | Done | Income type routing (closed-pnl + transaction-log) |
| AD-3 | Done | Live fee fetch via /v5/account/fee-rate |
| AD-4 | Done | Deterministic is_close (positionIdx + side, both adapters) |
| AD-4-B | v2.4 candidate | One-way mode break-even close fix |
| SR-7 | Done | Protocol vendor-neutrality (neutral error types) |

---

## Incomplete Sections

These sections are known gaps, marked explicitly for future verification:

- **WS order event parsing**: `parse_order_update()` missing. Order topic
  defined in constants but not implemented. Priority: HIGH if Bybit becomes
  primary exchange.
- **Conditional order support**: Not investigated. May use standard order
  creation with triggerPrice, or separate endpoint. Priority: MEDIUM.
- **Rate limit model**: Not verified against live API. Bybit uses per-key
  request counts, not weight-based. Actual limits per endpoint unknown.
- **COIN-M / Inverse contracts**: Not supported. `category=linear` hardcoded.
- **Order placement**: View-only. No `create_order()` or `cancel_order()`
  on the adapter.
- **Account info / VIP level**: `/v5/account/info` available but not called.
  Fee-rate endpoint proved sufficient for AD-3.
- **Historical data pagination**: Closed-pnl and transaction-log have cursor-
  based pagination. Current implementation fetches single page only.

---

## Maintenance Log

| Date | Reviewer | Scope |
|---|---|---|
| 2026-05-13 | Claude Opus 4.6 | Initial creation. Verified surface from AD-2/3/4 sweep (fee-rate, transaction-log, is_close). Remaining surface marked LISTED or ASSUMED. WS order parsing gap identified. |
