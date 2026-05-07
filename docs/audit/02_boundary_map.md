# Phase 1c — Boundary Map

**Codebase**: Quantamental Engine v2.3.1  
**Date**: 2026-05-07  
**Branch**: `audit/v2.3.1`

---

## External System Index

| # | System | Data Provided | Adapter Boundary | Port Interface |
|---|--------|---------------|------------------|----------------|
| 1 | **Exchange REST** (Binance/Bybit) | Account, positions, orders, trades, income, OHLCV, mark price, funding | `core/adapters/binance/rest_adapter.py`, `core/adapters/bybit/rest_adapter.py` | `ExchangeAdapter` Protocol (`core/adapters/protocols.py:106`) |
| 2 | **Exchange WS** (Binance/Bybit) | Real-time account updates, order events, klines, mark price, orderbook | `core/adapters/binance/ws_adapter.py`, `core/adapters/bybit/ws_adapter.py` | `WSAdapter` Protocol (`core/adapters/protocols.py:202`) |
| 3 | **Finnhub** | News articles, economic calendar | **NONE** — concrete httpx client in `core/news_fetcher.py:34` | **NONE** — core imports concrete `FinnhubFetcher` |
| 4 | **BWE News** | Crypto news via WebSocket | **NONE** — concrete websockets client in `core/news_fetcher.py:149` | **NONE** — core imports concrete `BweWsConsumer` |
| 5 | **FRED** (Federal Reserve) | US 10Y yield, HY spread | **NONE** — concrete httpx client in `core/regime_fetcher.py:127` | **NONE** — core imports concrete `RegimeFetcher` |
| 6 | **Yahoo Finance** | VIX data | **NONE** — concrete yfinance in `core/regime_fetcher.py:52` | **NONE** — core imports concrete `RegimeFetcher` |
| 7 | **Quantower Plugin** | Fills, positions, orders, account state, market data (inbound); risk state (outbound) | `core/platform_bridge.py:160` | **NONE** — `PlatformBridge` is a monolith mixing adapter + service + state |
| 8 | **SQLite** (persistence) | All persisted state | `core/database.py` + 12 `db_*.py` mixins, `core/db_router.py` | **NONE** — `db` singleton imported directly by 30+ modules |

---

## 1. Exchange REST (Binance / Bybit)

### Adapter boundary

Clean adapter layer exists:
- **Protocol**: `core/adapters/protocols.py:106` — `ExchangeAdapter` Protocol class
- **Binance**: `core/adapters/binance/rest_adapter.py` (334 lines) — `BinanceUSDMAdapter`
- **Bybit**: `core/adapters/bybit/rest_adapter.py` (403 lines) — `BybitLinearAdapter`
- **Registry**: `core/adapters/registry.py` — decorator-based lookup by `exchange:market_type` key
- **Factory**: `core/exchange_factory.py` — per-account instance cache

### Port interface

`ExchangeAdapter` Protocol defines 15 methods. All return normalized dataclasses (`NormalizedAccount`, `NormalizedPosition`, `NormalizedOrder`, `NormalizedTrade`, `NormalizedIncome`).

### Shapes crossing boundary

**Outbound (adapter → core)**: Typed normalized dataclasses. Clean.

**Inbound (core → adapter)**: Primitive kwargs (strings, ints, floats). Clean.

**Escape hatch**: `get_ccxt_instance()` method on the protocol exposes the raw CCXT object. Any consumer calling this gets raw vendor JSON. Currently used by: `exchange_market.py` (OHLCV, orderbook, mark price) and `exchange_income.py` (income history, equity backfill) — both use `get_exchange()` which returns the raw CCXT instance, bypassing the adapter entirely.

### Vendor leakage into core

| Location | Leakage | Severity |
|----------|---------|----------|
| `ws_manager.py:216` | `"source": "binance_ws"` hardcoded string | MEDIUM — should be `f"{adapter.exchange_id}_ws"` |
| `ws_manager.py:284` | Binance-format fallback URL `config.FSTREAM_WS/{listen_key}` when no adapter | MEDIUM — dead path if adapter always available |
| `ws_manager.py:367-371` | Binance-format stream names `{s}@kline_`, `@markPrice@1s`, `@depth20` as fallback | MEDIUM — same dead fallback path |
| `ws_manager.py:418` | Binance-format combined stream URL as fallback | MEDIUM — same |
| `ws_manager.py:138` | `msg.get("o", {}).get("x", "")` — raw Binance WS JSON field access in `_apply_order_update` | **HIGH** — this parses raw Binance payload structure outside the adapter; Bybit's WS order update format is completely different |
| `schedulers.py:148` | `f"{config.EXCHANGE_NAME.lower()}_rest"` as order source | LOW — cosmetic |
| `schedulers.py:183` | Same pattern for fill source | LOW |
| `schedulers.py:378-379` | `fetcher.fetch_binance_oi()`, `fetcher.fetch_binance_funding()` — Binance-specific method names called from orchestrator | **HIGH** — regime fetcher's OI/funding methods are Binance-specific; Bybit or IBKR would need different methods |
| `config.py` | `FSTREAM_WS`, `FSTREAM_COMB` — Binance fapi WS URLs as config defaults | LOW — only used as fallback |

### `core/exchange.py` importers (boundary violations)

Every module that imports from `core/exchange.py` bypasses the adapter boundary and accesses functions that internally call `get_exchange()` (raw CCXT) or `_get_adapter()`. These are the boundary violation call sites:

| Importer | Line | What's imported | Financial path? |
|----------|------|-----------------|-----------------|
| `ws_manager.py` | :25 | `get_exchange, _REST_POOL, fetch_account, fetch_positions, fetch_orderbook, fetch_ohlcv, create_listen_key, keepalive_listen_key, _get_adapter` | Yes — position/account data, WS lifecycle |
| `schedulers.py` | :18 | `fetch_exchange_info, fetch_account, fetch_positions, fetch_ohlcv, create_listen_key, fetch_bod_sow_equity, fetch_exchange_trade_history, populate_open_position_metadata` | Yes — all startup/refresh flows |
| `schedulers.py` | :125 | `_get_adapter` (late import inside loop) | Yes — REST order sync |
| `api/cache.py` | :16 | `build_equity_backfill, fetch_funding_rates` | Display — analytics |
| `api/routes_accounts.py` | :18 | `fetch_exchange_info, fetch_account, fetch_positions, populate_open_position_metadata, create_listen_key` | Yes — account switch |
| `api/routes_analytics.py` | :19 | `fetch_funding_rates` | Display |
| `api/routes_calculator.py` | :11 | `fetch_orderbook, fetch_ohlcv` | Yes — feeds risk engine sizing |
| `api/routes_dashboard.py` | :262 | `fetch_orderbook` (late import) | Display |
| `core/exchange_income.py` | :15 | `get_exchange, _REST_POOL` | Yes — equity/income data |
| `core/exchange_market.py` | :15 | `get_exchange, _REST_POOL` | Yes — OHLCV/orderbook/mark price |
| `core/ohlcv_fetcher.py` | :36 | `_get_adapter` (late import) | Yes — OHLCV ingestion |
| `core/platform_bridge.py` | :561,:680 | `fetch_open_orders_tpsl, populate_open_position_metadata` (late imports) | Yes — TP/SL, metadata |
| `core/reconciler.py` | :17 | `fetch_hl_for_trade, calc_mfe_mae, fetch_exchange_trade_history` | Yes — MFE/MAE reconciliation |

**Note**: `exchange_market.py` and `exchange_income.py` use `get_exchange()` to get the raw CCXT instance and call Binance-specific CCXT methods directly. These modules ARE the adapter gap — they should be methods on the `ExchangeAdapter` protocol, not standalone functions using raw CCXT. Some methods (like `fetch_ohlcv`, `fetch_income`) already exist on the adapter, but `exchange_market.py` and `exchange_income.py` duplicate them outside the adapter layer.

### Second-vendor test

**Bybit (crypto perp)**: Already implemented. Works because Bybit's API shape closely mirrors Binance's (both are crypto linear perpetuals with USDT settlement, similar order types, similar position model).

**Interactive Brokers (TradFi equities/options)**: Would fail. See §Protocol Vendor-Neutrality Analysis below.

---

## 2. Exchange WS (Binance / Bybit)

### Adapter boundary

Clean adapter layer exists:
- **Protocol**: `core/adapters/protocols.py:202` — `WSAdapter` Protocol class
- **Binance**: `core/adapters/binance/ws_adapter.py` (168 lines)
- **Bybit**: `core/adapters/bybit/ws_adapter.py` (217 lines)

### Shapes crossing boundary

**Outbound (adapter → core)**: Normalized dataclasses (`NormalizedPosition`, `NormalizedOrder`) from `parse_account_update` and `parse_order_update`. Clean.

**Leak**: `ws_manager._apply_order_update` at line 138 reads raw Binance JSON (`msg.get("o", {}).get("x", "")`) to extract `execution_type`. This field is NOT in the `NormalizedOrder` return — it's read from the raw message BEFORE the adapter parses it. Bybit's execution type is in a completely different structure. **HIGH** — this code path only works for Binance.

### Vendor leakage into core

`ws_manager.py` is the main consumer. Its fallback paths (lines 284, 367-371, 418) construct Binance-format URLs and stream names when no adapter is available. These are dead code paths when an adapter is configured, but they reveal the original Binance-only design.

The `_apply_mark_price`, `_apply_kline`, `_apply_depth` functions in `ws_manager.py` (lines 375-405) parse raw Binance WS JSON (`msg.get("s")`, `msg.get("p")`, `msg.get("k")`) directly instead of using the WSAdapter's `parse_*` methods. **HIGH** — these work for Binance only. The adapter HAS the parse methods, but ws_manager doesn't call them for market data — only for user data.

---

## 3. Finnhub (News + Calendar)

### Adapter boundary: NONE

`core/news_fetcher.py:FinnhubFetcher` is a concrete class with:
- Hardcoded base URL: `https://finnhub.io/api/v1`
- Direct `httpx.AsyncClient` usage
- Finnhub-specific response parsing (JSON shapes, field names)
- Direct DB writes via `db.upsert_news_items()`, `db.upsert_economic_calendar()`

### Port interface: NONE

`FinnhubFetcher` is imported directly by `schedulers.py:35` and instantiated at `_news_refresh_loop:408`.

### Second-vendor test

Replacing Finnhub with (e.g.) NewsAPI, CoinTelegraph API, or Bloomberg B-PIPE would require rewriting `FinnhubFetcher` entirely. No port interface exists. The data shape (news items with title/source/url/timestamp) is generic enough for a port, but no abstraction exists.

**Vendor leakage:** `"source": "finnhub"` hardcoded in normalized output (news_fetcher.py:78). Templates and DB queries may filter on this value.

---

## 4. BWE News (WebSocket)

### Adapter boundary: NONE

`core/news_fetcher.py:BweWsConsumer` is a concrete class with:
- Hardcoded WS URL from `config.BWE_NEWS_WS_URL`
- BWE-specific protocol (plaintext ping/pong, custom message format)
- BWE-specific field names: `news_title`, `source_name`, `coins_included`, `url`, `timestamp`
- Direct DB writes

### Port interface: NONE

Imported directly by `schedulers.py:35`.

### Second-vendor test

Same as Finnhub — no abstraction. Replacement requires full rewrite.

---

## 5. FRED (Federal Reserve Economic Data)

### Adapter boundary: NONE

`core/regime_fetcher.py:RegimeFetcher.fetch_fred_series()` is a concrete method with:
- Hardcoded URL: `https://api.stlouisfed.org/fred/series/observations`
- FRED-specific query params (`series_id`, `api_key`, `file_type`)
- FRED-specific response parsing
- Direct DB writes via `db.upsert_regime_signals()`

### Second-vendor test

Replacing FRED with (e.g.) Quandl, Alpha Vantage, or a Bloomberg terminal feed would require rewriting the fetch method. The data shape (date + value time series) is generic, but no port exists.

---

## 6. Yahoo Finance (VIX)

### Adapter boundary: NONE

`core/regime_fetcher.py:RegimeFetcher.fetch_vix()` uses `yfinance` library directly:
- `import yfinance as yf` (lazy import inside method)
- yfinance-specific API: `yf.download("^VIX", ...)`
- pandas DataFrame response parsing

### Second-vendor test

VIX data is also available from FRED (series VIXCLS), CBOE directly, or any market data provider. No port exists — would require rewriting the method.

---

## 7. Quantower Plugin

### Adapter boundary: PARTIAL

`core/platform_bridge.py:PlatformBridge` (810 lines) is classified as adapter but mixes 4 responsibilities:

1. **WS server** (lines 184-218): FastAPI WebSocket endpoint handler
2. **Message parser** (lines 40-158): `_map_fill`, `_map_position_snapshot`, `_map_order_snapshot` — Quantower-specific JSON to internal dict
3. **State sync / order relay** (lines 381-684): `_handle_account_state`, `_handle_position_snapshot`, `_handle_fill`, `_handle_order_snapshot` — applies parsed data to DataCache, OrderManager, DB
4. **Outbound push** (lines 730-806): `push_risk_state`, `request_ohlcv` — pushes state to plugin clients

### Port interface: NONE

`platform_bridge` singleton is imported directly by `schedulers.py`, `handlers.py`, `exchange.py`, `ws_manager.py`. No protocol or interface exists.

### Vendor leakage

**Into core**: `platform_bridge._handle_hello` writes `app_state.active_account_id` directly (F1 from state map — boundary violation + multi-writer bug).

**From plugin**: Quantower-specific field names (`positionId`, `exchangeOrderId`, `terminalOrderId`, `grossPnL`, `avgPrice`, `openTimeMs`) are parsed in `_map_fill` and `_map_position_snapshot`. These would need to change for a different trading terminal (e.g., TradingView webhook, MetaTrader bridge).

### Second-vendor test

Replacing Quantower with (e.g.) MetaTrader, Sierra Chart, or a custom execution bridge would require rewriting all `_map_*` functions and the WS protocol. The internal dict shapes produced by the mappers are generic, so the service layer (`_handle_*`) would survive — but only if the mappers are extracted into a separate adapter.

---

## 8. SQLite (Persistence)

### Adapter boundary: PARTIAL

`core/database.py:DatabaseManager` (689 lines) + 12 `db_*.py` mixin modules provide domain-specific query methods. `core/db_router.py` selects the correct DB file.

### Port interface: NONE

The `db` singleton is imported directly by 30+ modules. No persistence port exists. All SQL is aiosqlite-specific (SQLite dialect, WAL mode, `ON CONFLICT` syntax).

### Second-vendor test

Replacing SQLite with PostgreSQL, TimescaleDB, or a file-based store would require rewriting all SQL and connection management. The domain methods (e.g., `insert_account_snapshot`, `query_open_orders_all`) could become a port interface, but currently they contain raw SQL.

---

## Protocol Vendor-Neutrality Analysis (`core/adapters/protocols.py`)

The `ExchangeAdapter` Protocol (15 methods, 5 data models) was designed for crypto perpetual futures. Both existing adapters (Binance, Bybit) are crypto linear perpetual venues with nearly identical API shapes. This section tests whether the protocol is truly vendor-neutral or crypto-perp-shaped.

### NormalizedAccount

| Field | Crypto-perp assumption | IBKR TradFi equivalent | Would translate? |
|-------|----------------------|------------------------|------------------|
| `total_equity` | Single account, single currency (USDT) | Multi-currency equity; stocks have RegT margin, options have different | **NO** — needs `currency` field, multi-segment support |
| `available_margin` | Cross-margin available balance | Buying power varies by asset class (equities vs options vs futures) | **NO** — needs `asset_class` context |
| `unrealized_pnl` | Single-currency PnL | Multi-currency, multi-asset PnL | **NO** — needs currency + aggregation rules |
| `initial_margin` | Cross-margin model | Portfolio margin or RegT — completely different models | **NO** |
| `maint_margin` | Cross-margin maintenance | Portfolio margin maintenance | Partially |
| `fee_tier` | Exchange VIP tier | Commission schedule | Different concept |
| `maker_fee`/`taker_fee` | Percentage per trade | Per-share, per-contract, tiered, varies by route | **NO** — fee structure is fundamentally different |

### NormalizedPosition

| Field | Crypto-perp assumption | IBKR TradFi | Would translate? |
|-------|----------------------|-------------|------------------|
| `symbol` | `BTCUSDT` format (base+quote, no delimiter) | `AAPL` (stock), `SPY 240119C00500000` (option), `ESH4` (future) | **NO** — symbol taxonomy is different per asset class |
| `side` | `LONG` / `SHORT` (hedge mode) | Long/short for stocks; complex for options (delta sign, not "side") | Partially — equities yes, options no |
| `size` | Absolute quantity in base asset | Shares (stocks), contracts (options/futures) | Yes for simple cases |
| `contract_size` | 1.0 for linear, varies for inverse | 100 for equity options, varies for futures | Yes |
| `entry_price` | VWAP of fills | Average cost basis | Yes |
| `liquidation_price` | Margin call price | Not applicable for cash equity | **NO** — only applies to leveraged products |
| `unrealized_pnl` | Mark-to-market in USDT | Mark-to-market in position's currency | Needs `currency` field |
| `position_id` | Exchange-assigned | Broker-assigned | Yes |

### NormalizedOrder

| Field | Crypto-perp assumption | IBKR TradFi | Would translate? |
|-------|----------------------|-------------|------------------|
| `order_type` | `limit` / `market` / `stop_loss` / `take_profit` / `trailing_stop` | Same basics + MOC, LOC, adaptive, bracket, OCA, etc. | **NO** — enum is too narrow |
| `status` | `new` / `partially_filled` / `filled` / `canceled` / `expired` / `rejected` | Same + `pre_submitted`, `submitted`, `inactive`, `api_pending` | **NO** — lifecycle is different |
| `time_in_force` | `GTC` / `IOC` / `FOK` / `GTX` (post-only) | Same + `DAY`, `OPG`, `DTC`, `AUC` | Missing TradFi values |
| `position_side` | `LONG` / `SHORT` (hedge mode) | Not applicable for equities; side-inferred | Crypto-perp specific |
| `stop_price` | Single trigger price | Multiple legs for brackets, OCA groups | Too simple |
| `reduce_only` | Crypto-specific flag (close-only) | Not a universal concept | Crypto-perp specific |

### NormalizedTrade

| Field | Crypto-perp assumption | IBKR TradFi | Would translate? |
|-------|----------------------|-------------|------------------|
| `fee_asset` | Always `"USDT"` | Currency of the commission (may differ from position currency) | Needs generalization |
| `is_close` | Inferred from `realizedPnl != 0` | Explicit from broker's fill report | Different inference logic |
| `realized_pnl` | Per-fill gross PnL | Per-fill only for some brokers; others report per-position | Partially |
| `direction` | From `positionSide` field | Inferred from transaction, not a separate field | Different |

### NormalizedIncome

| Field | Crypto-perp assumption | IBKR TradFi | Would translate? |
|-------|----------------------|-------------|------------------|
| `income_type` | `"realized_pnl"` / `"funding_fee"` / `"commission"` / `"transfer"` | Same concepts + `"dividend"`, `"interest"`, `"withholding_tax"`, `"corporate_action"` | **NO** — enum is too narrow |

### Protocol-level methods

| Method | Crypto-perp assumption | IBKR TradFi issue |
|--------|----------------------|-------------------|
| `create_listen_key` / `keepalive_listen_key` | Binance-originated concept; Bybit adapter returns placeholder | IBKR uses a completely different streaming model (reqAccountUpdates, reqPositions) | **NO** — method should not exist on the protocol |
| `fetch_agg_trades` | Public trade tape | Different format per venue | Partially |
| `fetch_current_funding_rates` | Perpetual futures funding | Does not exist in TradFi | **NO** — should be on optional capability protocol |
| `normalize_symbol` / `denormalize_symbol` | Exchange-specific symbol format conversion | Different per venue | Yes — but current implementations assume crypto format |

### Per-field redesign detail

**1. Single-currency account model**

`NormalizedAccount` has one `total_equity: float` field and no `currency` field. It assumes a single USDT-denominated account. Multi-currency requires:
- Add `currency: str` (e.g., "USDT", "USD", "EUR")
- Or: `balances: Dict[str, float]` keyed by currency
- IBKR has separate segments (securities, commodities) with different margin models — would need `segment: str`
- Structural change: moderate (add field, update all consumers)

**2. Order type enum (5 current vs 15+ TradFi)**

Current 5 in protocol: `limit`, `market`, `stop_loss`, `take_profit`, `trailing_stop`

Missing for TradFi (need fundamentally different fields):
- `MOC` (market-on-close), `LOC` (limit-on-close) — need `auction_time` field
- `bracket` — needs `parent_id`, `child_orders[]`
- `OCA` (one-cancels-all) — needs `oca_group_id`
- `adaptive` (IBKR) — needs `algo_strategy`, `algo_params`
- `iceberg` — needs `display_qty`
- `twap` / `vwap` algo — needs `start_time`, `end_time`, `participation_rate`

This is NOT just an enum extension. Bracket and OCA orders need relational fields that don't exist on `NormalizedOrder`. Would require either: (a) polymorphic order types, or (b) optional fields for extended order features.

**3. `create_listen_key` / `keepalive_listen_key`**

These are on the `ExchangeAdapter` (REST) Protocol — but they are a WS auth concern. Binance's user-data stream requires a REST-created listen key; Bybit authenticates WS via HMAC on connect (the Bybit adapter returns a placeholder `"bybit_ws_auth"`). IBKR uses persistent TCP with OAuth.

This should be on the `WSAdapter` Protocol (or better: an optional `SupportsListenKey` protocol), not on the REST adapter. It leaked into the REST protocol because Binance's implementation requires a REST call to create it.

**4. `reduce_only` and `position_side`**

- `reduce_only: bool` — on `NormalizedOrder`. Crypto-perp specific (prevents increasing position). No TradFi equivalent. Should move to an optional crypto extension or be made `Optional[bool] = None`.
- `position_side: str` — on `NormalizedOrder` ("LONG"/"SHORT"). Only meaningful in hedge mode (Binance/Bybit). IBKR doesn't have this concept. Should be `Optional[str] = None`.
- `side: str` on `NormalizedPosition` ("LONG"/"SHORT") — works for equities (long/short). Works for options conceptually (long call vs short put) but oversimplifies the actual position risk.

### Verdict

**The protocol is crypto-perpetual-shaped, not broker-neutral.** Both adapters (Binance, Bybit) are linear USDT perpetual venues with near-identical API semantics. The protocol works because both share: single-currency USDT account, hedge-mode positions, TP/SL as order types, funding rate mechanism, and listen key / HMAC auth pattern.

**Severity: HIGH** — vendor leakage at the protocol level forces every adapter to inherit it. For current crypto-perp use case, the protocol works correctly. Becomes blocking when a non-crypto venue is added.

---

---

## Additional Boundary Surfaces Audited

### Persistence layer (SQLite)

**Adapter boundary**: Domain methods exist (`db.insert_account_snapshot()`, `db.query_open_orders_all()`, etc.) across 12 `db_*.py` mixin modules. All SQL is contained within these mixins and `database.py`. No raw SQL escapes to service/core/route code — **except** `core/platform_bridge.py` which executes raw SQL directly via `db._conn.execute()` at lines 300, 313, 335, 343, 351, 358 (inside `_handle_historical_fill`). This bypasses the domain method layer.

**Finding**: `platform_bridge.py` accesses `db._conn` (private attribute) to run raw `SELECT`/`UPDATE` queries against `exchange_history` table. This creates a hidden dependency on the DB schema and bypasses the `db_exchange.py` mixin that owns this table. **Severity: MEDIUM** — functional but couples the adapter to DB internals.

### Dashboard / HTMX templates

**Data shape**: Templates read **typed domain objects** (`PositionInfo`, `AccountState`, `PortfolioStats`, `WSStatus`) via the `_ctx()` helper in `api/helpers.py`. Field names used in templates (`p.ticker`, `p.direction`, `p.individual_unrealized`, `acc.total_equity`, `pf.drawdown`) are all engine-domain names defined on dataclasses in `core/state.py`.

**Vendor leakage**: Only 2 instances found:
- `templates/base.html:403` — `<option value="binance">Binance</option>` hardcoded in account creation form. Should be a dynamic list of registered exchanges.
- `templates/fragments/accounts.html:23` — placeholder text `"e.g. binancefutures_1234"` for broker_account_id field.

**Verdict**: Templates are clean. They read domain models, not vendor JSON. Broker change would NOT require template rewrites (beyond the 2 hardcoded strings above). **No finding** beyond the 2 LOW items.

### Auth / secrets

**Credential flow**: `AccountRegistry.load_all()` → decrypts API keys from DB → caches plaintext in `_cache` dict → `exchange_factory.get()` receives `(api_key, api_secret)` as string params → `BaseExchangeAdapter.__init__()` stores as `self._api_key`, `self._api_secret` → passed to CCXT constructor as `apiKey`/`secret`.

**Port-level**: Adapters receive credentials as constructor kwargs (`api_key: str, api_secret: str, proxy: str`). No typed `Credentials` object exists — plain strings throughout. No auth assumption leaks into core logic (core never sees API keys).

**Finding**: The `exchange_factory._make_ccxt_instance()` function at line 56-61 hardcodes Binance-specific class selection (`ccxt.binanceusdm` for `exchange=="binance" and market_type=="future"`). This is correct behavior for a factory, but it's doing adapter selection OUTSIDE the adapter registry. The adapter registry already handles this via `get_adapter()`. **Severity: LOW** — redundant selection logic that could diverge from registry.

### Error / exception types

**Protocol defines no error types.** The `ExchangeAdapter` Protocol has no error taxonomy — adapters raise whatever the underlying CCXT or httpx raises.

**Vendor exceptions reaching core**:
- `core/ohlcv_fetcher.py:144,169,172` — catches `ccxt.NetworkError` and `ccxt.BadSymbol` directly. These are CCXT-vendor-specific exception types.
- `core/ws_manager.py:337` and `core/account_registry.py:331,361` — use `safe_exchange_error(e)` to sanitize exception messages (strips API keys from error strings). This is a wrapper, not a type boundary — the underlying exception is still CCXT-specific.
- All other error handling in core uses bare `except Exception`.

**Finding**: No adapter-neutral error types exist. If a non-CCXT adapter were added (e.g., using `httpx` directly for a REST API, or `aiohttp`), the error types would be completely different. `ohlcv_fetcher.py` catching `ccxt.NetworkError` would miss the new adapter's errors entirely. **Severity: MEDIUM** — currently all adapters use CCXT, so this works. Becomes a bug when a non-CCXT adapter is added.

### Timestamps

**Canonical format at boundary**: All normalized dataclasses use **epoch milliseconds** (`int`) for timestamps — `timestamp_ms`, `created_at_ms`, `updated_at_ms`. This is consistent across both adapters. Adapters convert from vendor format (Binance `"time"`, Bybit `"timestamp"`) to `int` ms at the boundary.

**Internal conversions**: Core code converts epoch ms to `datetime` objects (via `datetime.fromtimestamp(ms/1000, tz=timezone.utc)`) and ISO strings (via `.isoformat()`) for display and DB storage. These conversions happen INSIDE core, not at the boundary.

**Finding**: Clean. Epoch ms int is the canonical boundary format. **No finding.**

### News source (Finnhub, BWE)

Audited in §3 and §4 above. Both are concrete clients with no port interface. **Finnhub** uses httpx with hardcoded URLs and Finnhub-specific JSON parsing. **BWE** uses websockets with BWE-specific protocol (plaintext ping/pong) and BWE-specific field names (`news_title`, `source_name`, `coins_included`). Both write directly to DB via `db.upsert_news_items()`.

**Vendor leakage**: `"source": "finnhub"` and `"source": "bwe"` hardcoded in news item dicts. If templates or queries filter on source, swapping providers requires updating those filters.

---

## Boundary Violation Summary

### Missing adapter boundaries (no port, no adapter)

| System | Concrete client location | Core consumer | Severity |
|--------|-------------------------|---------------|----------|
| **Finnhub** | `core/news_fetcher.py:FinnhubFetcher` | `schedulers.py:408` | MEDIUM — output flows to `news_items`/`economic_calendar` DB tables, read by `routes_news.py` and `routes_regime.py` for display only. Does NOT feed regime classifier (classifier reads `regime_signals`, populated by `regime_fetcher.py`). No financial decision path. |
| **BWE News** | `core/news_fetcher.py:BweWsConsumer` | `schedulers.py:432` | MEDIUM — same display-only path as Finnhub. News items shown on regime dashboard but not consumed by any classifier, signal generator, or sizing logic. |
| **FRED** | `core/regime_fetcher.py:fetch_fred_series` | `schedulers.py:362-366` | **HIGH** — feeds regime classifier → regime multiplier → position sizing |
| **Yahoo Finance** | `core/regime_fetcher.py:fetch_vix` | `schedulers.py:357` | **HIGH** — same path (VIX → regime) |
| **SQLite** | `core/database.py` + 12 mixins | 30+ modules | MEDIUM — migration to another DB is unlikely but coupling is extreme |
| **Quantower** | `core/platform_bridge.py` | `schedulers.py`, `handlers.py`, `exchange.py`, `ws_manager.py` | **HIGH** — directly mutates core state (F1), mixes 4 responsibilities |

### Vendor leakage in core code (should be in adapter only)

| Location | Leakage | Severity | Why |
|----------|---------|----------|-----|
| `ws_manager.py:138` | Raw Binance WS JSON field access (`msg.get("o", {}).get("x", "")`) outside adapter | **HIGH** | Bybit orders have completely different WS structure; this line breaks for non-Binance |
| `ws_manager.py:375-405` | `_apply_mark_price`, `_apply_kline`, `_apply_depth` parse raw Binance JSON instead of using WSAdapter parse methods | **HIGH** | Adapter has the parse methods; ws_manager ignores them for market data |
| `schedulers.py:378-379` | `fetch_binance_oi()`, `fetch_binance_funding()` — vendor-named methods in orchestrator | **HIGH** | Should be generic `fetch_oi(exchange_id)` or adapter methods |
| `regime_fetcher.py:297,364` | Methods named `fetch_binance_oi`, `fetch_binance_funding` | **HIGH** | Vendor name in method signature; logic hardcodes Binance fapi endpoints |
| `platform_bridge.py:435,465` | Adapter writes `app_state.active_account_id` directly | **CRITICAL** | Boundary violation + multi-writer bug (F1 from state map) |
| `exchange_market.py`, `exchange_income.py` | Use `get_exchange()` raw CCXT instead of adapter methods | **HIGH** | Duplicates adapter functionality outside the adapter layer; some methods exist on adapter but are bypassed |
| `config.py` | `FSTREAM_WS`, `FSTREAM_COMB` Binance WS URLs as defaults | LOW | Only used as fallback when no adapter |
| `ws_manager.py:216` | `"source": "binance_ws"` hardcoded | MEDIUM | Should derive from adapter |

### Structural Redesign Candidates (with blast radius)

#### R1: `core/exchange.py` + `exchange_market.py` + `exchange_income.py`

**Current**: 3 modules (~1,046 LOC) using raw CCXT via `get_exchange()`, re-exporting adapter functions for backward compatibility, holding legacy singleton `_exchange` and `_REST_POOL` ThreadPoolExecutor.

**Proposed**: Move remaining raw-CCXT methods into `ExchangeAdapter` protocol. `core/exchange.py` becomes a thin facade delegating to `exchange_factory.get_adapter()`. Eliminate `_exchange` singleton and `_REST_POOL` (adapters own their own executor via `BaseExchangeAdapter`).

**Blast radius** (16 files import from `core/exchange.py`):
- `ws_manager.py` — imports `get_exchange`, `_REST_POOL`, `fetch_account`, `fetch_positions`, `fetch_orderbook`, `fetch_ohlcv`, `create_listen_key`, `keepalive_listen_key`, `_get_adapter`
- `schedulers.py` — imports 8 functions
- `api/cache.py`, `api/routes_accounts.py`, `api/routes_analytics.py`, `api/routes_calculator.py`, `api/routes_dashboard.py` — import specific fetch functions
- `exchange_income.py`, `exchange_market.py` — import `get_exchange`, `_REST_POOL`
- `ohlcv_fetcher.py`, `platform_bridge.py`, `reconciler.py` — late imports of specific functions

#### R2: `core/platform_bridge.py`

**Current**: 810-line monolith with **6 identified issues**:
1. Mixes 4 responsibilities (WS server, message parser, state sync, outbound push)
2. Writes `app_state.active_account_id` directly at lines 435, 465 (F1 boundary violation — adapter bypassing AccountRegistry)
3. Accesses `db._conn.execute()` directly at lines 300, 313, 335, 343, 351, 358 (`_handle_historical_fill`) — bypasses `db_exchange.py` domain methods
4. Owns `OrderManager` instance — an 810-line adapter should not own a core domain object
5. Imports from `core.exchange` (late imports at lines 538, 561, 680) — circular dependency requiring late imports
6. `_normalize_symbol` hardcodes `BTCUSDT`-style format (strips `/`, ` `, `-`) — Quantower-specific assumption

**Proposed**: Split into 4 modules, each addressing specific issues:
- (a) `platform_ws_server.py` — WebSocket accept/dispatch, client set management. Issues addressed: #1 (SRP).
- (b) `platform_parser.py` — `_map_fill`, `_map_position_snapshot`, `_map_order_snapshot`, `_normalize_symbol`. Issues addressed: #1, #6. Parser becomes testable in isolation; symbol normalization can be made configurable per terminal.
- (c) `platform_sync.py` — state application via DataCache, OrderManager, **AccountRegistry** (never `app_state` directly). Issues addressed: #1, **#2** (F1 fix: `_handle_hello` calls `account_registry.set_active()` instead of writing `app_state.active_account_id`), **#3** (historical fill persistence goes through `db.upsert_exchange_history()` domain method, not raw SQL), #4 (OrderManager owned by the service layer or injected, not by the adapter).
- (d) `platform_push.py` — outbound risk state, OHLCV/depth subscription requests. Issues addressed: #1.
- **Deferred**: #5 (circular dependency) — resolving requires R1 (exchange.py collapse) first, since the late imports reference `core.exchange` functions that should become adapter methods.

**Blast radius** (5 direct importers):
- `schedulers.py:27` — imports `platform_bridge` singleton (would import from `platform_sync` or a facade)
- `handlers.py:78` — late import for `push_risk_state` (would import from `platform_push`)
- `exchange.py:294` — imports `platform_bridge.order_manager.enrich_positions_tpsl` (would import OrderManager from service layer)
- `ws_manager.py:273,538` — late imports for `is_connected`, `_refresh_positions_after_fill` (would import from `platform_ws_server` and `platform_sync`)
- `api/routes_platform.py` — imports for REST endpoints (would import from `platform_push`)

#### R3: `core/regime_fetcher.py`

**Current**: Single `RegimeFetcher` class (558 LOC) with vendor-specific methods: `fetch_vix` (yfinance), `fetch_us10y_yield` (FRED), `fetch_hy_spread` (FRED), `compute_btc_rvol_ratio` (CCXT+numpy), `fetch_binance_oi` (Binance-specific), `fetch_binance_funding` (Binance-specific).

**Proposed**: Extract `DataSourcePort` protocol:
```python
class DataSourcePort(Protocol):
    async def fetch_signal(self, signal_name: str, from_date: str, to_date: str) -> int: ...
```
Implement: `FredDataSource` (yields, spreads), `YFinanceDataSource` (VIX), `ExchangeDataSource` (OI/funding via exchange adapter). Orchestrator calls port, not concrete fetcher.

**Blast radius** (3 files):
- `schedulers.py:34,357-384` — imports `RegimeFetcher`, calls vendor-named methods
- `api/routes_regime.py` — may import for manual refresh
- `regime_classifier.py` — consumes DB signals (unaffected — reads from DB, not from fetcher)

#### R4: `core/news_fetcher.py`

**Current**: Two concrete classes (`FinnhubFetcher`, `BweWsConsumer`, 340 LOC), no shared interface. Hardcoded URLs, vendor-specific parsing, direct DB writes.

**Proposed**: Extract `NewsPort` protocol:
```python
class NewsPort(Protocol):
    async def fetch_news(self, category: str = "") -> int: ...
    async def fetch_calendar(self, from_date: str, to_date: str) -> int: ...
```
Implement `FinnhubNewsAdapter`, `BweNewsAdapter`.

**Blast radius** (2 files):
- `schedulers.py:35,408-433` — imports both classes
- No other direct importers

#### R4: `core/news_fetcher.py`

**Current**: Two concrete classes (`FinnhubFetcher`, `BweWsConsumer`, 340 LOC), no shared interface. Hardcoded URLs, vendor-specific parsing, direct DB writes.

**Proposed**: Extract `NewsPort` protocol:
```python
class NewsPort(Protocol):
    async def fetch_news(self, category: str = "") -> int: ...
    async def fetch_calendar(self, from_date: str, to_date: str) -> int: ...
```
Implement `FinnhubNewsAdapter`, `BweNewsAdapter`.

**Blast radius** (2 files):
- `schedulers.py:35,408-433` — imports both classes
- No other direct importers

**Financial path**: News output is **display-only** — it flows to `news_items` and `economic_calendar` DB tables, read by `routes_news.py` and `routes_regime.py` for dashboard display. It does NOT feed the regime classifier (`regime_classifier.py` reads from `regime_signals` table, which is populated by `regime_fetcher.py`, not `news_fetcher.py`). **Severity: MEDIUM** — no financial decision path.

#### R5: `ws_manager.py` market data parsing

**Current**: Lines 375-405 parse raw Binance WS JSON for klines (`msg.get("k")`), mark price (`msg.get("s")`, `msg.get("p")`), and depth (`msg.get("b")`, `msg.get("a")`). The WSAdapter Protocol has `parse_kline()`, `parse_mark_price()`, `parse_depth()` methods that do exactly this — but ws_manager calls them only for user data, not market data.

**Proposed**: Replace lines 375-405 with WSAdapter `parse_*` calls:
```python
parsed = ws_adapter.parse_mark_price(msg)
if parsed:
    app_state._data_cache.apply_mark_price(parsed["symbol"], parsed["mark_price"])
```

**Blast radius** (1 file): `ws_manager.py` only. No public API change.

#### R6: Protocol itself (`core/adapters/protocols.py`)

**Current**: Crypto-perp-shaped (266 LOC); `create_listen_key`/`keepalive_listen_key` on REST adapter; `reduce_only`/`position_side` as required fields on `NormalizedOrder`; 5 order types; single-currency account model; `fetch_current_funding_rates` on base protocol.

**Proposed**:
1. Move `create_listen_key`, `keepalive_listen_key` to optional `SupportsListenKey` protocol (or into WSAdapter)
2. Move `fetch_current_funding_rates` to existing `SupportsFundingRates` protocol
3. Make `reduce_only: Optional[bool] = None`, `position_side: Optional[str] = None` on NormalizedOrder
4. Add `currency: str = "USDT"` to `NormalizedAccount` and `NormalizedPosition`
5. Order type/status/TIF are already string-based (not enums) — no structural change needed, but document the canonical values

**Blast radius** (8+ files):
- `core/adapters/binance/rest_adapter.py`, `core/adapters/bybit/rest_adapter.py` — implement the protocol
- `core/adapters/binance/ws_adapter.py`, `core/adapters/bybit/ws_adapter.py` — implement WSAdapter
- `exchange.py:347-349` — calls `create_listen_key`, `keepalive_listen_key`
- `exchange_factory.py:116-153` — adapter instantiation
- `ws_manager.py:500-508` — listen key lifecycle
- `data_cache.py:65` — `_PRESERVE_FIELDS` references `position_side` fields
- `order_manager.py:112-121` — reads `position_side` from open orders for TP/SL matching
- `exchange.py:316-318` — reads `position_side` from orders for TP/SL mapping

---

## v2.4 Readiness Tie-In

The multiple data-entry paths that bypass the adapter layer are a direct blocker for v2.4 risk gating. Before `dd_state`/`weekly_pnl_state` can be promoted to hard gates, **every path that writes position/order/account state must flow through the adapter boundary** so the gate can be applied at one point.

Current bypassing paths that must be resolved:

| Path | Current bypass | Required for v2.4 |
|------|---------------|-------------------|
| `ws_manager.py:375-405` | Parses raw Binance WS JSON directly (R5) | Must use WSAdapter parse methods so any adapter's market data triggers the same gate check |
| `ws_manager.py:138` | Reads raw Binance `execution_type` field outside adapter | Must add `execution_type` to `NormalizedOrder` or WSAdapter parse output |
| `exchange_market.py` + `exchange_income.py` | Use raw CCXT via `get_exchange()` (R1) | Must use adapter methods so gate logic doesn't need to know which exchange is active |
| `platform_bridge.py:435,465` | Writes `app_state.active_account_id` directly (F1) | Must go through AccountRegistry so gate can trust the active account identity |
| `platform_bridge.py:300-363` | Raw SQL via `db._conn.execute()` | Must use DB domain methods so schema changes don't silently break the adapter |
| `schedulers.py:378-379` | Calls `fetch_binance_oi()`, `fetch_binance_funding()` — vendor-named methods (R3) | Must use adapter or port so regime data is exchange-agnostic |

### Error types as v2.4 prerequisite

Introducing a non-CCXT adapter (e.g., direct REST via httpx for an exchange without CCXT support) requires adapter-neutral error types in the protocol FIRST. Currently:

- `core/ohlcv_fetcher.py:144,169,172` catches `ccxt.NetworkError` and `ccxt.BadSymbol` — these are CCXT-vendor-specific. A non-CCXT adapter's network errors (e.g., `httpx.ConnectError`) would not be caught.
- `core/ws_manager.py:337` catches generic `Exception` and wraps via `safe_exchange_error()` — safe but loses error semantics.
- All adapter methods propagate raw CCXT exceptions through `BaseExchangeAdapter._run()` — no translation layer.

**Required**: Define adapter-neutral exceptions in `core/adapters/protocols.py`:
```python
class AdapterNetworkError(Exception): ...
class AdapterAuthError(Exception): ...
class AdapterBadSymbol(Exception): ...
class AdapterRateLimited(Exception): ...
```

Each adapter catches vendor-specific exceptions in its methods and re-raises as the neutral type. Core code catches only neutral types. Without this, every `except ccxt.*` site (currently 3 in `ohlcv_fetcher.py`) needs surgery each time a non-CCXT adapter is added.

**Summary**: The adapter boundary is necessary (not just desirable) before v2.4 gating is feasible. Redesign candidates R1, R2, R3, R5, plus adapter-neutral error types (R6 prerequisite), are prerequisites for v2.4, not optional cleanups.
