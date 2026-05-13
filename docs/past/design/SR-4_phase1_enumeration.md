# SR-4 Phase 1: exchange.py Shape Enumeration

**Date**: 2026-05-12
**Source**: `core/exchange.py` (416 lines), cross-referenced with
`core/exchange_market.py`, `core/exchange_income.py`, `core/adapters/base.py`

---

## Module-Level Variables

| Line | Name | Type | SR-4 Item | Callers |
|------|------|------|-----------|---------|
| 68 | `_REST_POOL` | ThreadPoolExecutor(8) | **SR-4a** | exchange.py:143, exchange_market.py:50,72,149,164, ws_manager.py (imported but unused after SR-7) |
| 88 | `_exchange` | Optional[ccxt.binance] | **SR-4b** | Only via get_exchange():115 |

**Cross-cutting**: `_REST_POOL` in exchange.py duplicates `_REST_POOL` in
`core/adapters/base.py:26` (same config: 8 workers). Adapter calls go through
base.py's pool; legacy `get_exchange()` callers go through exchange.py's pool.

---

## Functions

### Stays in exchange.py (no SR-4 sub-item)

| Line | Function | Callers (external) |
|------|----------|-------------------|
| 29 | `handle_rate_limit_error(exc)` | reconciler (5), ws_manager (4), schedulers (2), regime_fetcher (2), exchange_market (1) |
| 60 | `is_rate_limited() → bool` | Not directly imported; callers use `app_state.ws_status.is_rate_limited` |
| 119 | `_get_adapter() → ExchangeAdapter` | exchange_market.py, exchange_income.py, ws_manager.py, ohlcv_fetcher.py, schedulers.py |
| 137 | `fetch_exchange_info()` | schedulers.py, routes_accounts.py |
| 171 | `fetch_account()` | schedulers.py, ws_manager.py, routes_accounts.py |
| 200 | `fetch_positions(force=False)` | schedulers.py, ws_manager.py, routes_accounts.py |
| 388 | `create_listen_key() → str` | schedulers.py, ws_manager.py, routes_accounts.py |
| 396 | `keepalive_listen_key(key)` | ws_manager.py |

### SR-4a: Eliminate _REST_POOL

**Problem**: Two thread pools — `exchange.py:68` and `adapters/base.py:26`.
Adapter-based functions already use base.py's pool via `_run()`. Legacy
functions still use exchange.py's pool via `loop.run_in_executor(_REST_POOL, ...)`.

**Functions using exchange.py _REST_POOL directly**:

| File | Line | Function | Call |
|------|------|----------|------|
| exchange.py | 143 | `fetch_exchange_info` | `loop.run_in_executor(_REST_POOL, ex.fetch_time)` |
| exchange_market.py | 50 | `fetch_ohlcv` | `loop.run_in_executor(_REST_POOL, _fetch)` |
| exchange_market.py | 72 | `fetch_ohlcv_window` | `loop.run_in_executor(_REST_POOL, _fetch, cursor)` |
| exchange_market.py | 149 | `fetch_orderbook` | `loop.run_in_executor(_REST_POOL, _fetch)` |
| exchange_market.py | 164 | `fetch_mark_price` | `loop.run_in_executor(_REST_POOL, _fetch)` |

**Note**: ws_manager.py imports `_REST_POOL` but doesn't use it directly
after SR-7 changes — unused import.

All 5 call sites also call `get_exchange()` for their CCXT instance. These
are the remaining "raw CCXT" paths that should route through adapter instead
(overlaps with SR-6a).

### SR-4b: Remove get_exchange() legacy singleton

| Line | Element | Purpose |
|------|---------|---------|
| 71 | `_make_exchange()` | Factory for singleton ccxt.binanceusdm |
| 88 | `_exchange` | Singleton variable |
| 91 | `get_exchange()` | Getter with exchange_factory delegation + singleton fallback |

**Direct callers of get_exchange()**:

| File | Line | Function | What it fetches |
|------|------|----------|-----------------|
| exchange.py | 140 | `fetch_exchange_info` | `ex.fetch_time` (server time/latency) |
| exchange_market.py | 45 | `fetch_ohlcv` | `ex.fetch_ohlcv(symbol, ...)` |
| exchange_market.py | 64 | `fetch_ohlcv_window` | `ex.fetch_ohlcv(symbol, ...)` |
| exchange_market.py | 144 | `fetch_orderbook` | `ex.fetch_order_book(symbol, ...)` |
| exchange_market.py | 158 | `fetch_mark_price` | `ex.fetch_ticker(symbol)` |

**Overlap with SR-6a**: All 4 exchange_market.py callers are the same
functions identified in the original audit as WS-1/EM-1 (raw CCXT
instead of adapter). SR-4b removal requires SR-6a wiring to happen
simultaneously — can't remove the getter without replacing the callers.

### SR-4c: Move augmentation logic

Three functions contain business logic beyond simple adapter delegation:

| Line | Function | Logic | Size | Callers |
|------|----------|-------|------|---------|
| 244 | `populate_open_position_metadata()` | Loop over positions: fetch trades → find entry time, fetch extremes → MFE/MAE, fetch fees | ~70 LOC | schedulers.py, platform_bridge.py |
| 322 | `fetch_open_orders_tpsl()` | Fetch orders → map TP/SL to positions by symbol+direction | ~70 LOC | fetch_positions() (internal), platform_bridge.py |
| (re-export) | `fetch_exchange_trade_history()` | In exchange_income.py. Fetch income → augment with direction, entry/exit price, fees, open_time | ~130 LOC | schedulers.py, reconciler.py |

These are NOT simple adapter wrappers — they contain domain logic (entry
time reconstruction, TP/SL → position mapping, income → trade augmentation).
Moving them to adapters would push domain logic INTO the adapter boundary.
Alternative: extract to a service module (`core/trade_service.py` or similar).

### SR-4d: fetch_ohlcv_window pagination

| File | Line | Function | Details |
|------|------|----------|---------|
| exchange_market.py | 55 | `fetch_ohlcv_window(symbol, since_ms, until_ms, tf)` | Paginated OHLCV fetch (1000-candle pages) via raw CCXT `ex.fetch_ohlcv()` + `_REST_POOL` |

**Callers**: Only used internally by `fetch_hl_for_trade` (now delegates
to adapter). After SR-7 Step 4, `fetch_hl_for_trade` delegates to
`adapter.fetch_price_extremes()` which has its own internal OHLCV pagination.

**Status**: `fetch_ohlcv_window` may now be dead code in the fetch_hl_for_trade
path. Verify if any other callers exist.

**Other callers**:

| File | Line | Function |
|------|------|----------|
| exchange_income.py | (check needed) | `build_equity_backfill` does NOT call it |
| ohlcv_fetcher.py | (check needed) | May have its own fetch logic |

---

## Re-Export Block (Lines 407-415)

exchange.py re-exports from exchange_market.py and exchange_income.py
for backward compatibility:

**From exchange_market.py**: `fetch_ohlcv`, `fetch_ohlcv_window`,
`fetch_hl_for_trade`, `calc_mfe_mae`, `fetch_orderbook`, `fetch_mark_price`

**From exchange_income.py**: `fetch_income_history`, `fetch_bod_sow_equity`,
`fetch_income_for_backfill`, `build_equity_backfill`, `fetch_user_trades`,
`fetch_exchange_trade_history`, `fetch_funding_rates`

---

## Cross-Cutting Concerns

### 1. _REST_POOL + get_exchange() always co-occur
Every function using exchange.py's `_REST_POOL` also calls `get_exchange()`.
Eliminating one requires eliminating both. Both are replaced by
`adapter._run()` which uses `base.py:_REST_POOL` internally.

### 2. SR-4b depends on SR-6a
Can't remove `get_exchange()` without first wiring the 4 exchange_market.py
functions through adapter. The collapse order must be:
1. Wire exchange_market.py functions through adapter (SR-6a scope)
2. Remove `get_exchange()` + `_make_exchange()` + `_exchange` (SR-4b)
3. Remove exchange.py `_REST_POOL` (SR-4a — no remaining callers)

### 3. fetch_exchange_info() is the last holdout
After exchange_market.py functions are migrated, `fetch_exchange_info()`
is the only function that still uses `get_exchange()` + `_REST_POOL`.
It needs adapter-level `fetch_server_time()` or similar.

### 4. Re-export block creates import coupling
exchange.py's re-exports mean all importers get exchange.py loaded even
if they only need exchange_market functions. This is harmless but adds
to import graph complexity.

---

## Summary: What Can Change vs What's Cross-Cutting

| Sub-item | Independent? | Depends on |
|----------|-------------|------------|
| SR-4a (_REST_POOL) | No | SR-4b + SR-6a (all callers must be migrated first) |
| SR-4b (get_exchange) | No | SR-6a (exchange_market.py callers must use adapter) |
| SR-4c (augmentation) | Yes | Nothing — can extract independently |
| SR-4d (fetch_ohlcv_window) | Yes | Verify dead-code status first |

**Recommended Phase 4 landing order**:
1. SR-4d (verify dead code, delete or keep)
2. SR-4c (extract augmentation to service layer)
3. SR-6a dependency (wire exchange_market.py through adapter — may be
   combined with SR-4b or done as prerequisite)
4. SR-4b + SR-4a together (remove singleton + pool once no callers remain)
