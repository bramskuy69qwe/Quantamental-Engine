# SR-7 Phase 1: Protocol Shape Enumeration

**Date**: 2026-05-10
**Source**: `core/adapters/protocols.py` (267 lines)
**Cross-referenced**: `binance/rest_adapter.py`, `binance/ws_adapter.py`,
`bybit/rest_adapter.py`, `bybit/ws_adapter.py`, `binance/constants.py`,
`bybit/constants.py`, `core/adapters/__init__.py`, `core/exchange_factory.py`

---

## Classification Key

| Tag | Meaning |
|-----|---------|
| **N** | Vendor-neutral (no broker assumptions) |
| **CP** | Crypto-perp-specific (assumes USDM perpetuals, single-currency, perp lifecycle) |
| **SV** | Single-vendor-specific (Binance-only or Bybit-only leakage) |

---

## 1. Normalized Data Models

### NormalizedAccount (protocols.py:16-25)

| Field | Type | Default | Class | Notes |
|-------|------|---------|-------|-------|
| total_equity | float | 0.0 | **N** | Both adapters populate |
| available_margin | float | 0.0 | **N** | Both populate |
| unrealized_pnl | float | 0.0 | **N** | Both populate |
| initial_margin | float | 0.0 | **N** | Both populate |
| maint_margin | float | 0.0 | **N** | Binance: totalMaintMargin. Bybit: totalMaintenanceMargin |
| fee_tier | str | "" | **N** | Binance: feeTier from account. Bybit: empty (not available in V5 account response) |
| maker_fee | float | 0.0 | **CP** | Binance: fetches live from fapiPrivateGetCommissionRate. Bybit: **hardcoded 0.0002** |
| taker_fee | float | 0.0 | **CP** | Binance: fetches live. Bybit: **hardcoded 0.00055** |
| | | | | **Missing**: `currency` field. Both adapters assume USDT. Bybit WS explicitly filters for `coin == "USDT"` |

### NormalizedPosition (protocols.py:28-41)

| Field | Type | Default | Class | Notes |
|-------|------|---------|-------|-------|
| symbol | str | "" | **N** | Both populate |
| side | str | "" | **N** | "LONG" / "SHORT". Both adapters normalize |
| size | float | 0.0 | **N** | Absolute quantity. Binance: abs(positionAmt). Bybit: contracts |
| contract_size | float | 1.0 | **CP** | **Hardcoded 1.0 in both adapters** — assumes linear contracts only. Inverse perps need different values |
| entry_price | float | 0.0 | **N** | Both populate |
| mark_price | float | 0.0 | **N** | Both populate |
| liquidation_price | float | 0.0 | **CP** | Perp-specific. Both populate |
| unrealized_pnl | float | 0.0 | **N** | Both populate |
| initial_margin | float | 0.0 | **CP** | Perp/margin-specific. Both populate |
| notional | float | 0.0 | **N** | Both populate |
| position_id | str | "" | **N** | Binance: empty (no native position ID). Bybit: empty |

### NormalizedOrder (protocols.py:44-67)

| Field | Type | Default | Class | Notes |
|-------|------|---------|-------|-------|
| exchange_order_id | str | "" | **N** | Both populate (orderId) |
| terminal_order_id | str | "" | **N** | From Quantower — empty from REST |
| client_order_id | str | "" | **N** | Both populate |
| symbol | str | "" | **N** | Both populate |
| side | str | "" | **N** | BUY / SELL. Both normalize |
| order_type | str | "" | **N** | Normalized: limit / market / stop_loss / take_profit / trailing_stop. Both map from vendor-specific enums |
| status | str | "" | **N** | Normalized: new / partially_filled / filled / canceled / expired / rejected. Both map from vendor-specific enums |
| price | float | 0.0 | **N** | Both populate |
| stop_price | float | 0.0 | **CP** | TP/SL trigger price. Both populate. Bybit checks both `stopPrice` and `triggerPrice` |
| quantity | float | 0.0 | **N** | Both populate |
| filled_qty | float | 0.0 | **N** | Both populate |
| avg_fill_price | float | 0.0 | **N** | Both populate |
| reduce_only | bool | **False** | **CP** | Perp-specific. Required field (not Optional). Both adapters set it. **SR-7 target: make Optional[bool] = None** |
| time_in_force | str | "" | **N** | Both populate |
| position_side | str | "" | **CP** | LONG / SHORT (hedge mode). Required field. **SR-7 target: make Optional[str] = None** |
| created_at_ms | int | 0 | **N** | Both populate |
| updated_at_ms | int | 0 | **N** | Both populate |
| | | | | **Missing**: parent_id (for TP/SL → parent order link), child_orders[] (parent → children), oca_group_id (one-cancels-all group) |

### NormalizedTrade (protocols.py:70-90)

| Field | Type | Default | Class | Notes |
|-------|------|---------|-------|-------|
| exchange_fill_id | str | "" | **N** | Both populate |
| exchange_order_id | str | "" | **N** | Both populate |
| terminal_fill_id | str | "" | **N** | From Quantower — empty from REST |
| terminal_position_id | str | "" | **N** | From Quantower — empty from REST |
| symbol | str | "" | **N** | Both populate |
| side | str | "" | **N** | BUY / SELL. Both normalize |
| direction | str | "" | **CP** | LONG / SHORT. Binance: from positionSide. Bybit: from positionIdx or inferred from side |
| price | float | 0.0 | **N** | Both populate |
| quantity | float | 0.0 | **N** | Both populate |
| fee | float | 0.0 | **N** | Both populate |
| fee_asset | str | "USDT" | **SV** | **Default hardcoded to "USDT"**. Binance: from commissionAsset. Bybit: from fee.currency or defaults to USDT |
| role | str | "" | **N** | maker / taker. Both populate |
| is_close | bool | False | **CP** | Closing fill detection. Binance: realizedPnl != 0. Bybit: closedPnl != 0. Heuristic, not definitive |
| realized_pnl | float | 0.0 | **CP** | Gross PnL on close. Both populate |
| timestamp_ms | int | 0 | **N** | Both populate |
| trade_id | str | "" | **N** | DEPRECATED alias of exchange_fill_id |

### NormalizedIncome (protocols.py:93-100)

| Field | Type | Default | Class | Notes |
|-------|------|---------|-------|-------|
| symbol | str | "" | **N** | Both populate |
| income_type | str | "" | **CP** | "realized_pnl" / "funding_fee" / "commission" / "transfer". **Bybit: only returns "realized_pnl"** — funding_fee/commission/transfer not implemented |
| amount | float | 0.0 | **N** | Both populate |
| timestamp_ms | int | 0 | **N** | Both populate |
| trade_id | str | "" | **N** | Both populate |

---

## 2. ExchangeAdapter Protocol (protocols.py:105-199)

### Properties

| Element | Type | Class | Binance | Bybit | Notes |
|---------|------|-------|---------|-------|-------|
| exchange_id | str | **N** | "binance" | "bybit" | Via @register_adapter decorator |
| market_type | str | **CP** | "linear_perpetual" | "linear_perpetual" | Hardcoded in both. No spot/inverse support |
| ohlcv_limit | int | **N** | 1500 | 200 | Exchange-specific API limits |

### Methods

| Method | Return | Class | Binance | Bybit | Adapter Divergence |
|--------|--------|-------|---------|-------|--------------------|
| fetch_account() | NormalizedAccount | **N** | fapiPrivateV2GetAccount + fapiPrivateGetCommissionRate (BTCUSDT) | fetch_balance({"type":"unified"}) | Binance fetches live fees; Bybit hardcodes. Binance queries BTCUSDT as representative symbol |
| fetch_positions() | List[NormalizedPosition] | **CP** | fapiPrivateV2GetAccount → positions | fetch_positions({"settleCoin":"USDT"}) | Bybit uses settleCoin filter (USDT-only). Both hardcode contract_size=1.0 |
| fetch_open_orders() | List[NormalizedOrder] | **N** | fapiPrivateGetOpenOrders | fetch_open_orders({"category":"linear"}) | Different type/status enum mappings. Bybit checks stopOrderType field first for TP/SL detection |
| fetch_user_trades(sym, limit) | List[NormalizedTrade] | **N** | fapiPrivateGetUserTrades | fetch_my_trades(sym, {"category":"linear"}) | Different field names. Bybit infers direction from positionIdx or side |
| fetch_order_history(sym, limit) | List[NormalizedOrder] | **N** | fapiPrivateGetAllOrders | fetch_closed_orders({"category":"linear"}) | Same mapping patterns as fetch_open_orders |
| fetch_income(type, start, end, limit) | List[NormalizedIncome] | **CP** | fapiPrivateGetIncome (all types) | private_get_v5_position_closed_pnl (**realized_pnl only**) | **Critical gap**: Bybit ignores income_type param, returns only realized_pnl |
| fetch_agg_trades(sym, start, end) | List[Dict] | **SV** | fapiPublicGetAggTrades → raw response | fetch_trades → mapped to {"p", "T"} format | **Return format leaks**: consumers expect `t["p"]` and `t["T"]` (Binance field names). Bybit adapter fakes this format |
| fetch_ohlcv(sym, tf, limit, since) | List | **N** | Generic fetch_ohlcv | Generic fetch_ohlcv | Both delegate to CCXT |
| create_listen_key() | str | **SV** | fapiPrivatePostListenKey → listenKey | **Stub**: returns "bybit_ws_auth" | Bybit uses HMAC auth, not listen keys. Protocol method exists only because Binance needs it |
| keepalive_listen_key(key) | None | **SV** | fapiPrivatePutListenKey | **No-op** (pass) | Same — Binance-specific lifecycle |
| load_markets() | None | **N** | Generic (base class) | Generic (base class) | Both delegate to CCXT |
| get_precision(sym) | Dict | **N** | Generic (base class) | Generic (base class) | Both delegate to CCXT |
| round_price(sym, price) | float | **N** | Generic (base class) | Generic (base class) | Floor-based rounding |
| round_amount(sym, amt) | float | **N** | Generic (base class) | Generic (base class) | Floor-based rounding |
| normalize_symbol(raw) | str | **N** | upper + strip delimiters | upper + strip `/`, `:USDT`, `:USD` | Different cleaning logic but same output format |
| denormalize_symbol(unified) | str | **N** | Passthrough | Passthrough | Both return input unchanged |
| fetch_current_funding_rates(syms) | Dict[str, Dict] | **CP** | fapiPublicGetPremiumIndex | fetch_tickers({"category":"linear"}) | Different API endpoints, same return shape |
| get_ccxt_instance() | Any | **N** | Generic (base class) | Generic (base class) | Escape hatch |

### Optional Capability Protocols

| Protocol | Method | Binance | Bybit |
|----------|--------|---------|-------|
| SupportsFundingRates | fetch_funding_rates(sym, start, end, limit) | Implemented (fapiPublicGetFundingRate) | Implemented (fetch_funding_rate_history) |
| SupportsOpenInterest | fetch_open_interest_hist(sym, period, start, end, limit) | Implemented (fapiDataGetOpenInterestHist) | **Not implemented** |

---

## 3. WSAdapter Protocol (protocols.py:202-246)

| Method | Return | Class | Binance | Bybit | Adapter Divergence |
|--------|--------|-------|---------|-------|--------------------|
| build_user_stream_url(key) | str | **SV** | `wss://fstream.binance.com/private/ws/{key}` | `wss://stream.bybit.com/v5/private` (key ignored) | Binance embeds listen key in URL. Bybit uses post-connect HMAC auth |
| build_market_streams(syms, tf, depth_sym) | List[str] | **SV** | `{sym}@kline_{tf}`, `{sym}@markPrice@1s`, `{sym}@depth20` | `kline.{tf_mapped}.{sym}`, `tickers.{sym}`, `orderbook.25.{sym}` | Completely different naming. Depth hardcoded: 20 (Binance) vs 25 (Bybit) |
| build_market_stream_url(streams) | str | **SV** | `wss://...?streams=s1/s2/s3` (topics in URL) | `wss://...` (topics sent post-connect via JSON) | Fundamentally different subscription model |
| get_event_type(msg) | str | **SV** | `msg["e"]` → "ACCOUNT_UPDATE", "ORDER_TRADE_UPDATE", etc. | Topic-based mapping: "position"→"ACCOUNT_UPDATE", "tickers"→"markPriceUpdate" | Bybit translates to Binance event names for compatibility |
| get_event_time_ms(msg) | int | **N** | `msg["E"]` | `msg["ts"]` | Different field names, same semantics |
| parse_account_update(msg) | Tuple[dict, List[NormalizedPosition]] | **SV** | Single message with `{a: {B: [...], P: [...]}}` | Two separate topics: "wallet" and "position" | Binance: one event, both balance+positions. Bybit: separate events per concern |
| parse_kline(msg) | Optional[Dict] | **SV** | `k.x` for closed check, `k.t/o/h/l/c/v` | `confirm` field, `start/open/high/low/close/volume` | Different field names, different closed-candle signal |
| parse_mark_price(msg) | Optional[Dict] | **SV** | `msg.s`, `msg.p` | `data.symbol`, `data.markPrice` | Different nesting |
| parse_depth(msg) | Optional[Dict] | **N** | `msg.s`, `msg.b`, `msg.a` | `data.s`, `data.b`, `data.a` | Similar shape, different nesting |
| unwrap_stream_message(msg) | dict | **SV** | `msg["data"]` (combined stream envelope) | Passthrough (no envelope) | Binance wraps; Bybit doesn't |

### Bybit-only methods (not in Protocol)

| Method | Purpose |
|--------|---------|
| build_auth_message() | HMAC-SHA256 signature for private WS auth |
| build_subscribe_message(topics) | `{"op": "subscribe", "args": topics}` |

---

## 4. Exchange Factory (exchange_factory.py)

| Concern | Class | Details |
|---------|-------|---------|
| CCXT instantiation | **SV** | `if exchange == "binance" and market_type == "future": ccxt.binanceusdm(...)` — special-cased. Others: `getattr(ccxt, exchange)` |
| Market type mapping | **CP** | `map_market_type("future") → "linear_perpetual"`. Only "linear_perpetual" is registered |
| Cache key | **N** | Per account_id. Multi-account clean |
| Proxy support | **N** | Via config.HTTP_PROXY |

---

## 5. Summary: Vendor-Neutrality Classification

| Category | Count | Elements |
|----------|-------|----------|
| **Vendor-neutral (N)** | ~40 | Most data model fields, OHLCV/orderbook/precision methods, symbol normalization |
| **Crypto-perp-specific (CP)** | ~15 | reduce_only, position_side, direction, liquidation_price, initial_margin, funding rates, contract_size=1.0, market_type="linear_perpetual", is_close heuristic, income types |
| **Single-vendor-specific (SV)** | ~12 | create_listen_key/keepalive_listen_key (Binance-only lifecycle), fee_asset default "USDT", fetch_agg_trades return format (Binance field names faked by Bybit), all WSAdapter methods (completely different stream protocols), CCXT class selection |

### Top SR-7 Targets (from AUDIT_REPORT.md cross-reference)

1. **currency field** — missing from NormalizedAccount. Both adapters assume USDT
2. **reduce_only** → `Optional[bool] = None` (data-only, no downstream consumer)
3. **position_side** → `Optional[str] = None` (only meaningful in hedge mode)
4. **create_listen_key / keepalive_listen_key** — relocate out of ExchangeAdapter. Binance-only lifecycle
5. **fee_source indicator** — `Literal["live", "default"]` to flag Bybit's hardcoded fees vs Binance's live fetch
6. **fetch_agg_trades return format** — normalize so Bybit doesn't fake Binance field names
7. **Neutral error types** — replace `ccxt.*` exceptions with adapter-neutral error hierarchy
8. **Order type structural needs** — parent_id, child_orders[], oca_group_id for TP/SL linkage
