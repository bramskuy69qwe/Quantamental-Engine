# Binance USDⓈ-M Futures Adapter

Maintenance interface for the Binance Futures adapter. Covers the full API
surface, WS events, configuration assumptions, known quirks, and recent
migrations. Use this document to:
- Verify which endpoints the engine calls before upgrading CCXT or touching adapter code
- Cross-reference Binance changelog entries against engine impact
- Onboard new contributors to the Binance integration layer

**Last reviewed**: 2026-05-13
**Adapter code**: `core/adapters/binance/rest_adapter.py`, `ws_adapter.py`, `constants.py`
**CCXT version**: 4.3.20 (`ccxt.binanceusdm`)

---

## API Surface

### REST Endpoints Used

| CCXT Method / Raw Path | FAPI Path | Purpose | Weight | File:Line | Doc Reference |
|---|---|---|---|---|---|
| `fapiPrivateV2GetAccount()` | GET /fapi/v2/account | Account balances, fee tier, positions | 5 | rest_adapter:54 | [Account Info V2](https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Account-Information-V2) |
| `fapiPrivateGetCommissionRate()` | GET /fapi/v1/commissionRate | Per-symbol maker/taker fee rates | 20 | rest_adapter:57 | [Commission Rate](https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/User-Commission-Rate) |
| `fapiPrivateGetOpenOrders()` | GET /fapi/v1/openOrders | Basic open orders (LIMIT, MARKET — NOT conditional) | 1/40 | rest_adapter:105 | [Open Orders](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Current-All-Open-Orders) |
| `request("openAlgoOrders", ...)` | GET /fapi/v1/openAlgoOrders | Conditional/algo orders (TP/SL placed via UI) | 1/40 | rest_adapter:145 | [Algo Open Orders](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Current-All-Algo-Open-Orders) |
| `fapiPrivateGetUserTrades()` | GET /fapi/v1/userTrades | Per-symbol trade history (fills) | 5 | rest_adapter:181 | [User Trades](https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Account-Trade-List) |
| `fapiPrivateGetAllOrders()` | GET /fapi/v1/allOrders | Order history (all statuses) | 5 | rest_adapter:214 | [All Orders](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/All-Orders) |
| `fapiPrivateGetIncome()` | GET /fapi/v1/income | Income history (funding fees, realized PnL, transfers) | 30 | rest_adapter:262 | [Income History](https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Get-Income-History) |
| `fapiPublicGetAggTrades()` | GET /fapi/v1/aggTrades | Tick-level trade data for MFE/MAE price extremes | 20 | rest_adapter:328 | [Agg Trades](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Compressed-Aggregate-Trades-List) |
| `fetch_ohlcv()` | GET /fapi/v1/klines | OHLCV candles (ATR, regime signals, charting) | 5 | rest_adapter:362 | [Klines](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Kline-Candlestick-Data) |
| `fetch_order_book()` | GET /fapi/v1/depth | Orderbook (VWAP, slippage, 1% depth) | 5/10/20 | rest_adapter:437 | [Depth](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Order-Book) |
| `fetch_ticker()` | GET /fapi/v1/ticker/price | Mark price via ticker | 1 | rest_adapter:441 | [Price Ticker](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Symbol-Price-Ticker) |
| `fetch_time()` | GET /fapi/v1/time | Server time for latency measurement | 1 | rest_adapter:446 | [Server Time](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Check-Server-Time) |
| `fapiPrivatePostListenKey()` | POST /fapi/v1/listenKey | Create user-data stream listen key | 1 | rest_adapter:452 | [Listen Key](https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Start-User-Data-Stream) |
| `fapiPrivatePutListenKey()` | PUT /fapi/v1/listenKey | Keepalive listen key (every 25 min) | 1 | rest_adapter:459 | [Keepalive](https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api/Keepalive-User-Data-Stream) |
| `fapiPublicGetPremiumIndex()` | GET /fapi/v1/premiumIndex | Funding rates + mark prices (all symbols) | 10 | rest_adapter:471 | [Premium Index](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Mark-Price) |
| `fapiPublicGetFundingRate()` | GET /fapi/v1/fundingRate | Historical funding rate data | 1 | rest_adapter:499 | [Funding Rate](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History) |
| `fapiDataGetOpenInterestHist()` | GET /futures/data/openInterestHist | Open interest history (regime signals) | 1 | rest_adapter:514 | [OI History](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics) |

**Not used** (PAPI): `papiGetUmConditionalOpenOrders()` — requires Portfolio Margin. Tested 2026-05-13, returns 404 on non-PM accounts. Use FAPI `openAlgoOrders` instead.

### WebSocket Events Handled

| Event Type | Stream | Handler | Parser | Purpose |
|---|---|---|---|---|
| `ACCOUNT_UPDATE` | User-data | `_apply_account_update()` ws_manager:111 | `parse_account_update()` ws_adapter:66 | Position + balance deltas via DataCache |
| `ORDER_TRADE_UPDATE` | User-data | `_apply_order_update()` ws_manager:114 | `parse_order_update()` ws_adapter:108 | Basic order lifecycle: placement, fill, cancel. TP/SL enrichment for basic stop orders |
| `ALGO_UPDATE` | User-data | `_apply_algo_update()` ws_manager:117 | `parse_algo_update()` ws_adapter:144 | Conditional order lifecycle: place, trigger, cancel, expire. TP/SL enrichment for algo orders (OM-5) |
| `kline` | Market combined | Inline ws_manager:520 | `parse_kline()` ws_adapter:178 | Closed candles → OHLCV cache for ATR/charting |
| `markPriceUpdate` | Market combined | Inline ws_manager:528 | `parse_mark_price()` ws_adapter:195 | Real-time mark price for position valuation |
| `depthUpdate` | Market combined | Inline ws_manager:524 | `parse_depth()` ws_adapter:204 | Orderbook for VWAP/slippage/1% depth |

### WebSocket Events NOT Handled

Events appearing on the user-data stream but silently dropped by the
dispatcher (no `elif` branch in `_handle_user_event`):

| Event | Purpose | Why Not Handled |
|---|---|---|
| `STRATEGY_UPDATE` | Grid/DCA strategy lifecycle | Out of scope — engine doesn't manage strategies |
| `GRID_UPDATE` | Grid trading updates | Out of scope |
| `listenKeyExpired` | Listen key expiry notification | Handled implicitly by keepalive loop reconnect logic |
| `MARGIN_CALL` | Margin call warning | Not implemented — engine has its own margin monitoring (MN-1) |

### WebSocket Stream Architecture

```
User-data stream (private, authenticated):
  URL: wss://fstream.binance.com/private/ws/{listenKey}
  Events: ACCOUNT_UPDATE, ORDER_TRADE_UPDATE, ALGO_UPDATE
  Auth: Listen key from POST /fapi/v1/listenKey
  Keepalive: PUT /fapi/v1/listenKey every 25 min (_keepalive_loop)
  Reconnect: Exponential backoff, fresh listen key on each attempt
  Plugin gating: Stands by when Quantower plugin connected (30s retry loop)

Market-data stream (public, combined):
  URL: wss://fstream.binance.com/market/stream?streams={list}
  Streams per symbol: {sym}@kline_{tf}, {sym}@markPrice@1s
  Streams per calc symbol: {sym}@depth20
  Dynamic: Streams rebuilt when positions change (restart_market_streams)
```

---

## Account Configuration Assumptions

| Setting | Value | Notes |
|---|---|---|
| Position mode | Hedge mode primary | `positionSide` = LONG/SHORT. One-way mode ("BOTH") supported via `resolve_tpsl_direction()` helper (OM-5) |
| Margin type | USDⓈ-M | Not COIN-M, not Portfolio Margin |
| PAPI access | Not available | Returns 404 (verified 2026-05-13). All conditional order access via FAPI |
| CCXT exchange class | `ccxt.binanceusdm` | NOT `ccxt.binance` — `binanceusdm` routes all calls through fapi.binance.com, avoiding geo-restricted Spot endpoints |

---

## Authentication

- **API key + secret**: HMAC SHA256 signature on all private endpoints
- **Storage**: Encrypted in `accounts` table (`api_key_enc`, `api_secret_enc`)
- **Encryption**: Fernet symmetric encryption via `ENV_MASTER_KEY` (see `core/crypto.py`)
- **Required permissions**: Futures Trading (read + trade), Futures Account (read)
- **Listen key**: Created at startup, refreshed every 25 min. Expires after 60 min without keepalive

---

## Rate Limits

| Aspect | Detail |
|---|---|
| Model | Per-IP, weight-based. 2400 weight/minute for most endpoints |
| Engine handling | `RateLimitError` hierarchy (SR-7). `handle_rate_limit_error()` in exchange.py sets global `rate_limited_until` |
| Monitoring | Check #9 in MN-1 tracks rate-limit event frequency |
| 429 response | Contains `retry_after_ms` header |
| 418 (IP ban) | Parses "banned until {epoch_ms}" from error message body. Duration typically 2-5 min |
| Pacing | 0.5s sleep between sequential REST calls (RL-1) |
| Conditional orders | Weight 1 with symbol filter, 40 without |
| Degraded mode | REST refresh interval raised from 5s → 15s when WS down (RL-1) |
| Proactive tracking | RL-2 (queued, not implemented): weight counter to preemptively throttle |

**Catch sites** (RL-3 coverage, 11 sites): exchange.py (2), reconciler.py (5), ws_manager.py (4). All call `handle_rate_limit_error()` before broad `except Exception`.

---

## Known Quirks

### positionSide="BOTH" (One-Way Mode)
Binance one-way mode sets `positionSide="BOTH"` on all orders. Positions
are always `direction="LONG"/"SHORT"` (derived from `positionAmt` sign).
Matching requires inference: `SELL → LONG`, `BUY → SHORT` (close-order
semantics). Handled by `resolve_tpsl_direction()` in `order_state.py` (OM-5).

### Conditional Orders vs Basic Orders
Binance separates basic orders (LIMIT, MARKET) from conditional orders
(STOP_MARKET, TAKE_PROFIT_MARKET placed via UI). Distinct API surfaces:
- Basic: `/fapi/v1/openOrders` + `ORDER_TRADE_UPDATE`
- Conditional: `/fapi/v1/openAlgoOrders` + `ALGO_UPDATE`

Conditional orders use different field names:

| Basic | Conditional (REST) | Conditional (WS `o` dict) |
|---|---|---|
| `orderId` | `algoId` | `aid` |
| `clientOrderId` | `clientAlgoId` | `caid` |
| `status` | `algoStatus` | `X` |
| `type` | `orderType` | `o` |
| `stopPrice` | `triggerPrice` | `tp` |
| `origQty` | `totalQty` | `q` |

Engine prefixes conditional IDs with `algo:` to prevent collision.

### retry_after_ms Availability
Only populated for HTTP 418 (IP ban). HTTP 429 responses do NOT include
`retry_after_ms` — engine defaults to 120s pause via `handle_rate_limit_error`.

### exchange_history trade_key Format
Income API rows use `{timestamp_ms}_{symbol}_{incomeType}` as `trade_key`
(no exchange-native tradeId). PA-1a dedup uses `symbol+side+qty+|ts|<1s`
tolerance to avoid dual records from WS fill creation.

### Plugin Connection Gating
When Quantower plugin is connected:
- User-data WS stands by (30s retry loop) — no ORDER_TRADE_UPDATE events
- Account/position REST sync skipped (plugin is authoritative)
- Basic order REST sync: NOT gated (OM-5b)
- Conditional/algo order sync: NOT gated (OM-5)

### CCXT binanceusdm vs binance
Engine uses `ccxt.binanceusdm`, which inherits from `ccxt.binance` but
routes all endpoints through `fapi.binance.com`. Using `ccxt.binance` with
`defaultType: "future"` would hit `api.binance.com` for `exchangeInfo`
(geo-restricted in some regions).

---

## Recent Migrations / Watch List

### 2025-12-09: Conditional Orders → Algo Service
Binance migrated conditional/strategy orders to a new Algo Service.
- New REST endpoint: `GET /fapi/v1/openAlgoOrders`
- New WS event: `ALGO_UPDATE` on user-data stream (replaces undocumented
  earlier behavior)
- Error code `-4120 STOP_ORDER_SWITCH_ALGO` indicates use of old
  pre-migration conditional endpoints
- Engine retrofitted via OM-5 (2026-05-13)

### Watch Items
- PAPI expansion: Binance may extend PAPI to non-PM accounts in future
- WS `ALGO_UPDATE` event schema may evolve as Algo Service matures
- Rate limit model changes: Binance periodically adjusts weight allocations

---

## Changelog Watch

- **Source**: https://developers.binance.com/docs/derivatives/change-log
- **Cadence**: Review monthly or before each engine release
- **Last reviewed**: 2026-05-13
- **Process**: Check changelog for endpoint deprecations, field renames,
  new event types. Cross-reference against this document's REST and WS tables.

---

## Cross-References

### Adapter Code
| File | Purpose |
|---|---|
| `core/adapters/binance/rest_adapter.py` | REST API wrapper (BinanceUSDMAdapter) |
| `core/adapters/binance/ws_adapter.py` | WS message parsers (BinanceWSAdapter) |
| `core/adapters/binance/constants.py` | Endpoint URLs, type/status mappings |
| `core/adapters/protocols.py` | Vendor-neutral adapter protocol |
| `core/adapters/__init__.py` | Adapter registry + NormalizedPosition → PositionInfo converter |
| `core/exchange_factory.py` | CCXT instance cache + adapter resolution |
| `core/ws_manager.py` | WS lifecycle: connection, dispatch, reconnect, streams |
| `core/exchange.py` | REST orchestration: fetch_account, fetch_positions, TP/SL enrichment |

### Audit Findings Touching This Adapter
| Finding | Status | Impact |
|---|---|---|
| SR-7 | Done | Protocol vendor-neutrality (neutral error types, optional fields) |
| SR-4 | Done | exchange.py collapse (all I/O through adapter) |
| SR-6 | Done | ws_manager adapter routing (deleted raw-Binance handlers) |
| SR-8 | Done | regime_fetcher adapter migration |
| AD-5 | Done | ohlcv_fetcher migrated to adapter |
| MN-1a | Done | Rate-limit event wiring to monitoring |
| OM-5 | Done | Conditional order support (ALGO_UPDATE + openAlgoOrders) |
| OM-5b | Done | Basic order REST sync no longer plugin-gated |
| RL-3 | Done | Rate-limit exception coverage (11 catch sites) |
| AD-3 | Deferred | Bybit hardcoded fees (not this adapter, but adapter quality pattern) |
| AD-4 | Deferred | is_close heuristic improvements |

### Design Documents
- `docs/design/SR-7_phase*.md` — Protocol redesign
- `docs/design/OM-5_phase1_investigation.md` — TP/SL visibility root cause
- `docs/design/OM-5_phase1_conditional_orders.md` — Conditional order API enumeration

---

## Incomplete Sections

The following are known gaps in this document, to be filled as work progresses:

- **Bybit adapter**: Separate document needed (`docs/adapters/bybit.md`). Bybit has
  different WS event shapes, conditional order mechanism, and fee model.
- **Order placement**: Engine currently view-only for conditional orders. When
  order placement is added, document the POST endpoints and their params.
- **Position TP/SL via API**: Binance may have a dedicated position-level TP/SL
  endpoint separate from algo orders. Not yet investigated.
- **COIN-M adapter**: Not implemented. Document if added.
