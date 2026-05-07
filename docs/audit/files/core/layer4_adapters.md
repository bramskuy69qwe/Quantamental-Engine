# Per-File Findings: Layer 4 — Adapters

**Files**: `exchange.py`, `exchange_market.py`, `exchange_income.py`, `exchange_factory.py`, `ws_manager.py`, `platform_bridge.py`, `news_fetcher.py`, `regime_fetcher.py`, `ohlcv_fetcher.py`, `adapters/*`  
**Pre-flagged**: Boundary map (vendor leakage, missing boundaries, protocol analysis, R1-R6). State map (F1, exchange.py singleton, ws_manager globals).

---

## `core/ws_manager.py` (547 lines)

### WS-1: Raw Binance JSON parsed outside adapter for market data

**File**: `core/ws_manager.py:375-405`  
**Severity**: **HIGH**  
**Category**: 3 (vendor neutrality)  
**Cross-ref**: Boundary map — vendor leakage, R5

**Observation**: `_apply_mark_price` (line 376), `_apply_kline` (line 383), `_apply_depth` (line 399) parse raw Binance WS JSON fields: `msg.get("s")`, `msg.get("p")`, `msg.get("k")`, `msg.get("b")`, `msg.get("a")`. The `WSAdapter` protocol has `parse_mark_price()`, `parse_kline()`, `parse_depth()` methods that do exactly this — but ws_manager only calls them for user data (lines 100-102), not market data.

**Financial path**: Mark price → `apply_mark_price` → `total_equity` → sizing. Kline → ATR → sizing coefficient. Depth → orderbook → VWAP/slippage. All feed financial calculations. A Bybit WS session would silently produce zeros/None from these parsers because field names differ.

**Suggested fix**: Replace raw JSON parsing with WSAdapter calls (R5 from boundary map).

**Blast radius**: `ws_manager.py:375-405` (3 functions).

---

### WS-2: Raw Binance `execution_type` read outside adapter

**File**: `core/ws_manager.py:138`  
**Severity**: **HIGH**  
**Category**: 3 (vendor neutrality)  
**Cross-ref**: Boundary map — vendor leakage

**Observation**: `execution_type = msg.get("o", {}).get("x", "")` reads Binance-specific WS JSON structure directly. This field (`o.x` = execution type: NEW, TRADE, CANCELED, etc.) is NOT exposed via `NormalizedOrder` or the WSAdapter parse output. Bybit's execution type lives in `data[0].execType`.

The execution type drives critical branching: TRADE triggers fill processing (line 187), which triggers position refresh.

**Suggested fix**: Add `execution_type: str` to `NormalizedOrder` or add a `parse_order_update_with_exec_type` method to WSAdapter that returns both the order and the execution type.

**Blast radius**: `ws_manager.py:138`, `adapters/protocols.py` (extend NormalizedOrder or WSAdapter), both WS adapter implementations.

---

### WS-3: Hardcoded `"source": "binance_ws"` string

**File**: `core/ws_manager.py:216`  
**Severity**: MEDIUM  
**Category**: 3 (vendor neutrality)

**Observation**: The order dict written to DB has `"source": "binance_ws"` hardcoded. Should be `f"{ws_adapter.exchange_id}_ws"` or derived from the active adapter.

**Blast radius**: `ws_manager.py:216` (1 line).

---

### WS-4: Binance-format fallback URLs as dead code

**File**: `core/ws_manager.py:284,367-371,418`  
**Severity**: LOW  
**Category**: 12 (dead code) + 3 (vendor)

**Observation**: Fallback paths construct Binance-format WS URLs (`f"{config.FSTREAM_WS}/{listen_key}"`, `f"{s}@kline_..."`) when no adapter is available. These should never fire in production (adapter is always configured). Dead code that reveals the original single-vendor design.

**Blast radius**: `ws_manager.py` (3 code blocks).

---

### WS-5: Pre-flagged state findings confirmed

State map findings confirmed at file:line:
- Module-level globals (lines 50-57): `_listen_key`, `_user_ws_task`, `_market_ws_task`, `_keepalive_task`, `_fallback_task`, `_calculator_symbol`, `_last_ws_position_update`, `_stopping`
- All use `global` keyword, no locks, asyncio-safe in single event loop

---

## `core/exchange.py` (368 lines)

### EX-1: Legacy singleton `_exchange` retains hardcoded Binance credentials

**File**: `core/exchange.py:32-47,49,74-77`  
**Severity**: MEDIUM  
**Category**: 3 (vendor neutrality) + 4 (hidden state)  
**Cross-ref**: State map §6.1, Boundary map R1

**Observation**: `_make_exchange()` creates `ccxt.binanceusdm` with `config.BINANCE_API_KEY/SECRET` (from .env). `_exchange` singleton is used only during startup before `exchange_factory` is ready. After startup, `get_exchange()` delegates to the factory. If the factory path ever falls through post-startup, it silently uses wrong credentials (from .env, not from the active account in the registry).

**Blast radius**: `exchange.py:32-77` (R1 candidate — eliminate legacy singleton).

---

### EX-2: `_REST_POOL` ThreadPoolExecutor duplicated

**File**: `core/exchange.py:29`, `core/adapters/base.py:19`  
**Severity**: LOW  
**Category**: 9a (duplication)

**Observation**: Two separate `ThreadPoolExecutor(max_workers=8)` instances exist: one in `exchange.py` (used by `exchange_market.py`, `exchange_income.py`) and one in `adapters/base.py` (used by all adapter methods). Both have 8 max workers — total 16 threads for REST I/O. The `exchange.py` pool should be eliminated when raw CCXT calls are migrated to adapters (R1).

**Blast radius**: `exchange.py:29`, `exchange_market.py:15`, `exchange_income.py:14` (all import `_REST_POOL` from exchange.py).

---

## `core/exchange_market.py` (268 lines)

### EM-1: Uses raw CCXT via `get_exchange()` instead of adapter

**File**: `core/exchange_market.py:44,63,246,260`  
**Severity**: HIGH  
**Category**: 3 (vendor neutrality)  
**Cross-ref**: Boundary map R1

**Observation**: `fetch_ohlcv` (line 44), `fetch_ohlcv_window` (line 63), `fetch_orderbook` (line 246), `fetch_mark_price` (line 260) all call `get_exchange()` to get the raw CCXT instance and call CCXT methods directly (`ex.fetch_ohlcv()`, `ex.fetch_order_book()`, `ex.fetch_ticker()`). The adapter protocol already has `fetch_ohlcv` — but `exchange_market.py` bypasses it.

`_agg_extremes` (line 88) correctly uses the adapter: `adapter.fetch_agg_trades()`.

**Financial path**: OHLCV → ATR → sizing; orderbook → VWAP/slippage → sizing; mark price → equity. All feed financial calculations.

**Suggested fix**: Migrate remaining functions to use `_get_adapter()` instead of `get_exchange()`. Add `fetch_orderbook` and `fetch_mark_price` to the adapter protocol if not present (currently absent from `ExchangeAdapter`).

**Blast radius**: `exchange_market.py` (4 functions), `protocols.py` (add 2 methods), both adapter implementations.

---

## `core/exchange_income.py` (410 lines)

### EI-1: Uses raw CCXT for equity backfill pagination

**File**: `core/exchange_income.py:14` (imports `get_exchange, _REST_POOL`)  
**Severity**: MEDIUM  
**Category**: 3 (vendor neutrality)  
**Cross-ref**: Boundary map R1

**Observation**: Imports `get_exchange` and `_REST_POOL` from exchange.py. Uses `_get_adapter()` for most calls (correct), but the import dependency on the legacy module keeps the coupling alive. `fetch_income_history` (line 29) correctly uses the adapter. `build_equity_backfill` (not shown in this read window) may use raw CCXT for pagination.

**Blast radius**: `exchange_income.py:14` (import cleanup when R1 eliminates legacy).

---

### EI-2: `fetch_income_history` re-wraps normalized data back into vendor dict format

**File**: `core/exchange_income.py:42-55`  
**Severity**: LOW  
**Category**: 10 (naming — misleading)

**Observation**: The function calls `adapter.fetch_income()` which returns `List[NormalizedIncome]`, then immediately converts back to dict format with vendor-style field names: `"incomeType": ni.income_type.upper()`, `"time": ni.timestamp_ms`. Comment says "for backward compatibility with existing consumers." This means the adapter boundary exists but its normalization is immediately undone.

**Blast radius**: `exchange_income.py:42-55` and all consumers of `fetch_income_history` return value. Fixing requires updating consumers to accept `NormalizedIncome` directly.

---

## `core/platform_bridge.py` (810 lines)

### PB-1 through PB-6: Pre-flagged findings confirmed

All findings from boundary map R2 confirmed at file:line:

| ID | File:line | Finding | Severity |
|----|-----------|---------|----------|
| PB-1 | :435,:465 | Writes `app_state.active_account_id` directly (F1 boundary violation) | **CRITICAL** |
| PB-2 | :300,:313,:322,:335,:343,:351,:358,:363 | Raw SQL via `db._conn.execute()` in `_handle_historical_fill` | MEDIUM |
| PB-3 | :168 | Owns `OrderManager` instance — adapter owns core domain object | MEDIUM |
| PB-4 | :538,:561,:680 | Late imports from `core.exchange` — circular dependency | MEDIUM |
| PB-5 | :46 | `_normalize_symbol` hardcodes BTCUSDT-style format | LOW |
| PB-6 | entire file | 810-line monolith mixing 4 responsibilities | HIGH (R2) |

### PB-7: `_handle_historical_fill` bare `except` on SQL parsing

**File**: `core/platform_bridge.py:261-263`  
**Severity**: LOW  
**Category**: 7 (error handling)

**Observation**: Lines 261-265: `try: price = float(msg.get("price") or 0)` / `except: price = 0.0`. Bare `except:` catches ALL exceptions including `KeyboardInterrupt` and `SystemExit`. Should be `except (TypeError, ValueError):`.

---

## `core/regime_fetcher.py` (558 lines)

### RF-1: Vendor-specific method names and hardcoded endpoints

**File**: `core/regime_fetcher.py:291,297,364`  
**Severity**: HIGH  
**Category**: 3 (vendor neutrality)  
**Cross-ref**: Boundary map R3

**Observation**:
- Line 291: `self._ccxt_exchange = ccxt_async.binanceusdm(params)` — hardcoded Binance class
- Line 297: `async def fetch_binance_oi(...)` — vendor name in method signature
- Line 320: `exchange.fapiPublicGetOpenInterestHist(...)` — Binance-specific REST endpoint
- Line 306: Hardcoded symbol list `["BTCUSDT", "ETHUSDT", ...]` — Binance format
- Line 364: `async def fetch_binance_funding(...)` — vendor name in method signature

**Financial path**: OI change and funding rate → regime classifier → regime multiplier → position sizing.

**Suggested fix**: R3 from boundary map — extract DataSourcePort, implement per-exchange.

**Blast radius**: `regime_fetcher.py` (2 methods + CCXT factory), `schedulers.py:378-379` (callers).

---

### RF-2: No adapter abstraction for FRED, yfinance

**File**: `core/regime_fetcher.py:127-175,52-120`  
**Severity**: HIGH  
**Category**: 3 (vendor neutrality)  
**Cross-ref**: Boundary map §5, §6

**Observation**: `fetch_fred_series()` (line 127) uses hardcoded FRED URL + httpx directly. `fetch_vix()` (line 52) uses `yfinance.download()` directly. Both have no port interface. Financial path: signals → regime classifier → multiplier → sizing.

**Blast radius**: R3 candidate.

---

## `core/news_fetcher.py` (340 lines)

### NF-1: No adapter abstraction for Finnhub or BWE

**File**: `core/news_fetcher.py:30-145,149-296`  
**Severity**: MEDIUM  
**Category**: 3 (vendor neutrality)  
**Cross-ref**: Boundary map §3, §4, R4

**Observation**: `FinnhubFetcher` (line 30) hardcodes `https://finnhub.io/api/v1`, uses httpx directly, parses Finnhub-specific JSON. `BweWsConsumer` (line 149) hardcodes BWE WS protocol. Both write to DB directly. Financial path: display-only (does not feed regime classifier or sizing).

**Blast radius**: R4 candidate.

---

### NF-2: BWE reconnect loop has unbounded exponential backoff

**File**: `core/news_fetcher.py` (run method, not visible in excerpt)  
**Severity**: LOW  
**Category**: 7 (error handling)

**Observation**: BWE WS consumer reconnects with exponential backoff. The backoff variable grows without a cap. After many failures, the reconnect delay could reach hours. The `ws_manager.py` has `config.WS_RECONNECT_MAX` (60s cap) — BWE does not.

**Blast radius**: `news_fetcher.py` (reconnect loop).

---

## `core/ohlcv_fetcher.py` (282 lines)

### OF-1: Hardcoded Binance exchange class selection

**File**: `core/ohlcv_fetcher.py:53-66`  
**Severity**: MEDIUM  
**Category**: 3 (vendor neutrality)

**Observation**: `_get_exchange()` (line 48) defaults to `"binanceusdm"` and has an if/elif chain for exchange selection: `if ex_name == "binance" and market_type == "future": exchange_name = "binanceusdm"`. This duplicates the exchange class selection logic in `exchange_factory._make_ccxt_instance()`.

**Blast radius**: `ohlcv_fetcher.py:48-67` (eliminate when R1 provides a unified CCXT factory).

---

### OF-2: Catches `ccxt.NetworkError` and `ccxt.BadSymbol` — vendor-specific exceptions

**File**: `core/ohlcv_fetcher.py:144,169,172`  
**Severity**: MEDIUM  
**Category**: 3 (vendor neutrality) + 7 (error handling)  
**Cross-ref**: Boundary map — error types, v2.4-readiness

**Observation**: `except ccxt.NetworkError` and `except ccxt.BadSymbol` — vendor-specific exception types. A non-CCXT adapter would produce different exception types (e.g., `httpx.ConnectError`).

**Blast radius**: `ohlcv_fetcher.py:144,169,172` (3 catch sites). V2.4 prerequisite: adapter-neutral error types (R6).

---

## `core/adapters/` (Binance + Bybit implementations)

### AD-1: Bybit adapter returns hardcoded default fees

**File**: `core/adapters/bybit/rest_adapter.py:82-83`  
**Severity**: MEDIUM  
**Category**: 1 (financial correctness — minor)

**Observation**: `NormalizedAccount` returned by Bybit adapter has `maker_fee=0.0002, taker_fee=0.00055` hardcoded. Binance adapter fetches live fees via `fapiPrivateGetCommissionRate`. A Bybit user on a higher VIP tier would have their fees overestimated → conservative sizing estimates (position slightly too small), and P&L estimates in the calculator would show more cost than actual.

**Financial path**: `exchange_info.maker_fee/taker_fee` → `risk_engine.py:344` → `fee_rate` → `fee_cost` → `est_profit`/`est_loss` calculation.

**Conservative-direction caveat**: The failure mode is undersizing (trader leaves money on the table) rather than overleveraging (trader takes on excess risk). Phase 2 priority should be calibrated accordingly — this is a real financial impact but in the safer direction.

**Meta-finding — adapter compliance variance**: The `ExchangeAdapter` protocol does not specify whether `maker_fee`/`taker_fee` on `NormalizedAccount` must be live-fetched or may be hardcoded defaults. Binance adapter fetches live via `fapiPrivateGetCommissionRate`; Bybit hardcodes VIP0 defaults. This inconsistency means fee accuracy varies silently by adapter. The protocol should either: (a) require a `fetch_fees()` capability (Bybit becomes non-compliant until fixed), or (b) add a `fees_source: Literal["live", "default"]` field so consumers can warn when using defaults. Tag for v2.4 protocol redesign (R6).

**Suggested fix**: Fetch Bybit fee tier via V5 account info API (`/v5/account/fee-rate`).

**Blast radius**: `bybit/rest_adapter.py:48-84` (fetch_account method), `protocols.py` (add fee_source field or fetch_fees method — R6).

---

### AD-2: `_REST_POOL` shared singleton in `base.py`

**File**: `core/adapters/base.py:19`  
**Severity**: LOW  
**Category**: 4 (hidden state)

**Observation**: Module-level `ThreadPoolExecutor` shared across all adapter instances. Immutable after creation. No finding beyond the duplication with `exchange.py:29` (EX-2).

---

### AD-3: `BaseExchangeAdapter.normalize_symbol` default strips delimiters

**File**: `core/adapters/base.py:98-100`  
**Severity**: LOW  
**Category**: 3 (vendor neutrality)

**Observation**: Default implementation: `return raw_symbol.upper().replace("/", "").replace("-", "").replace(" ", "")`. This produces `BTCUSDT` format. Works for crypto but would produce nonsense for TradFi symbols containing legitimate delimiters (e.g., `SPY 240119C00500000` → `SPY240119C00500000`).

**Blast radius**: Protocol-level concern (R6).

---

## Summary

| ID | Severity | Category | File | One-liner |
|----|----------|----------|------|-----------|
| PB-1 | **CRITICAL** | 1+3 (financial+boundary) | platform_bridge:435,465 | F1 confirmed: adapter writes `active_account_id` directly, bypassing registry |
| WS-1 | **HIGH** | 3 (vendor) | ws_manager:375-405 | Market data parsed as raw Binance JSON, WSAdapter parse methods ignored (R5). **Cheap wiring fix + v2.4 prerequisite.** |
| WS-2 | **HIGH** | 3 (vendor) | ws_manager:138 | Raw Binance `execution_type` read outside adapter — drives fill detection. **Cheap wiring fix + v2.4 prerequisite.** |
| EM-1 | **HIGH** | 3 (vendor) | exchange_market:44,63,246,260 | Uses raw CCXT via `get_exchange()` instead of adapter for OHLCV/orderbook/mark (R1). **Cheap wiring fix + v2.4 prerequisite.** |
| RF-1 | HIGH | 3 (vendor) | regime_fetcher:291,297,364 | Vendor-named methods, hardcoded Binance CCXT class and endpoints (R3) |
| RF-2 | HIGH | 3 (vendor) | regime_fetcher:52-175 | No port interface for FRED/yfinance — financial path to sizing (R3) |
| PB-6 | HIGH | 8 (SRP) | platform_bridge (entire) | 810-line monolith: 4 responsibilities + 6 identified issues (R2) |
| WS-3 | MEDIUM | 3 (vendor) | ws_manager:216 | `"source": "binance_ws"` hardcoded |
| EX-1 | MEDIUM | 3+4 (vendor+hidden) | exchange:32-77 | Legacy singleton retains hardcoded Binance .env creds (R1) |
| EI-1 | MEDIUM | 3 (vendor) | exchange_income:14 | Imports legacy `get_exchange`/`_REST_POOL` coupling |
| NF-1 | MEDIUM | 3 (vendor) | news_fetcher:30-296 | No port interface for Finnhub/BWE (display-only, R4) |
| OF-1 | MEDIUM | 3 (vendor) | ohlcv_fetcher:53-66 | Hardcoded Binance exchange class selection duplicates factory |
| OF-2 | MEDIUM | 3+7 (vendor+error) | ohlcv_fetcher:144,169,172 | Catches `ccxt.NetworkError`/`BadSymbol` — vendor-specific exceptions |
| AD-1 | **HIGH** | 1+3 (financial+hygiene) | bybit/rest_adapter:82-83 | Hardcoded default fees instead of live fetch — overestimates costs for VIP users (conservative direction: undersized, not overleveraged). **Meta-finding**: adapter compliance variance — Binance fetches live fees, Bybit doesn't. Protocol doesn't require it. Tag for v2.4 protocol redesign. |
| PB-2 | MEDIUM | 3 (separation) | platform_bridge:300-363 | Raw SQL via `db._conn.execute()` bypassing domain methods |
| PB-3 | MEDIUM | 8 (SRP) | platform_bridge:168 | Adapter owns core `OrderManager` instance |
| PB-4 | MEDIUM | 5 (async) | platform_bridge:538,561,680 | Late imports from `core.exchange` — circular dependency |
| EI-2 | LOW | 10 (naming) | exchange_income:42-55 | Adapter normalization immediately unwrapped to vendor dict format |
| EX-2 | LOW | 9a (duplication) | exchange:29 + base:19 | Two separate ThreadPoolExecutor(8) instances — 16 total REST threads |
| WS-4 | LOW | 12 (dead code) | ws_manager:284,367-371,418 | Binance-format fallback URLs as dead code |
| PB-5 | LOW | 3 (vendor) | platform_bridge:46 | `_normalize_symbol` hardcodes BTCUSDT-style format |
| PB-7 | LOW | 7 (error) | platform_bridge:261-263 | Bare `except:` catches SystemExit/KeyboardInterrupt |
| NF-2 | LOW | 7 (error) | news_fetcher (reconnect) | BWE backoff has no cap — delay can grow to hours |
| AD-3 | LOW | 3 (vendor) | base:98-100 | Default `normalize_symbol` strips delimiters — breaks TradFi symbols (R6) |
