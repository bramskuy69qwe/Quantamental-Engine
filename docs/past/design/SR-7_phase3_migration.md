# SR-7 Phase 3: Adapter Migration Plan

**Date**: 2026-05-11
**Depends on**: Phase 2 neutralization proposals (accepted)
**Scope**: What changes in binance/, bybit/, and consumers to fit new protocol

---

## Landing Sequence

Dependencies dictate order. Elements within a step are independent and
can land in any order (or combined into one commit if small).

```
Step 1: core/adapters/errors.py (new file) — no dependencies
Step 2: Error migration (all catch sites) — depends on Step 1
Step 3: Protocol dataclass changes — independent of Step 2
Step 4: SupportsListenKey + auth model — depends on Step 3
Step 5: fetch_price_extremes — depends on Step 3
Step 6: NormalizedFundingRate + WSEventType — depends on Step 3
```

Each step gets its own commit (per workflow rules). Regression tests
written FIRST within each step.

---

## Step 1: Neutral Error Types

### New file: `core/adapters/errors.py`

```
AdapterError (base)
├── RateLimitError(message, retry_after_ms: Optional[int])
├── AuthenticationError
├── ConnectionError
├── ValidationError
└── ExchangeError
```

### Binance adapter changes (`binance/rest_adapter.py`)

Add a wrapper method (or decorator) around all CCXT calls that catches
ccxt exceptions and re-raises neutral types:

| ccxt exception | → neutral type | Applies to |
|----------------|---------------|------------|
| ccxt.RateLimitExceeded | RateLimitError | All REST methods |
| ccxt.DDoSProtection | RateLimitError (parse retry_after_ms from message) | All REST methods |
| ccxt.AuthenticationError | AuthenticationError | All private endpoints |
| ccxt.NetworkError, ccxt.RequestTimeout | ConnectionError | All methods |
| ccxt.InvalidOrder, ccxt.InsufficientFunds | ValidationError | Order methods |
| ccxt.ExchangeError, ccxt.ExchangeNotAvailable | ExchangeError | All methods |

Implementation: wrap the existing `self._run()` base-class method (which
calls `loop.run_in_executor`) with a try/except that translates. All
adapter methods inherit the translation automatically.

**Lines changed**: ~30 (base_adapter.py `_run()` wrapper + imports)

### Bybit adapter changes (`bybit/rest_adapter.py`)

Same pattern — `_run()` wrapper handles translation. Bybit CCXT raises
the same ccxt exception hierarchy.

**Lines changed**: ~30 (same pattern)

### Consumer changes (7 files)

| File | Change | Lines |
|------|--------|-------|
| core/exchange.py | `import ccxt` → `from core.adapters.errors import RateLimitError`; remove `import ccxt` (keep only if still needed for type instantiation in `_make_exchange`). Change 2 except clauses. | ~6 |
| core/exchange_market.py | Replace `import ccxt` → adapter errors import. Change 2 except clauses to `RateLimitError`. | ~6 |
| core/reconciler.py | Replace `import ccxt` → adapter errors import. Change 5 except clauses. | ~10 |
| core/ws_manager.py | Replace `import ccxt` → adapter errors import. Change 4 except clauses. | ~8 |
| core/schedulers.py | Replace `import ccxt` → adapter errors import. Change 2 except clauses. | ~6 |
| core/regime_fetcher.py | Replace dynamic `import ccxt as _ccxt` + isinstance checks → adapter errors import + isinstance `RateLimitError`. | ~6 |
| core/exchange.py `handle_rate_limit_error()` | Change param type annotation from `Exception` to `RateLimitError`. Use `exc.retry_after_ms` instead of regex parsing when available. | ~8 |

**Total consumer lines**: ~50

### Test surface

| Test file | Change needed |
|-----------|--------------|
| tests/test_rl3_exception_coverage.py | Replace `ccxt.RateLimitExceeded` with `RateLimitError` in mock setup (11 sites) |
| tests/test_rate_limit.py | Update 2 tests that reference ccxt exception types |
| NEW: tests/test_adapter_errors.py | Verify translation: mock CCXT raising each exception type → assert correct neutral type propagates |

---

## Step 2: Protocol Dataclass Changes

### protocols.py modifications

| Element | Change | Lines |
|---------|--------|-------|
| NormalizedAccount | Add `currency: str = "USDT"`, `fee_source: str = "default"` | 2 |
| NormalizedOrder.reduce_only | `bool = False` → `Optional[bool] = None` | 1 |
| NormalizedOrder.position_side | `str = ""` → `Optional[str] = None` | 1 |
| NormalizedOrder | Add `parent_order_id: Optional[str] = None`, `oca_group_id: Optional[str] = None` | 2 |
| NormalizedOrder.order_type docstring | Add `stop_loss_limit`, `take_profit_limit` to documented values | 1 |
| NormalizedTrade.is_close docstring | Clarify: adapter MUST set definitively, not heuristic | 1 |
| NormalizedTrade.fee_asset | Change default from `"USDT"` to `""` (no assumed currency) | 1 |
| NEW: NormalizedFundingRate dataclass | 4 fields: symbol, funding_rate, next_funding_time_ms, mark_price | 6 |
| NEW: WSEventType class | 5 constants | 7 |
| ExchangeAdapter.fetch_current_funding_rates | Return type → `Dict[str, NormalizedFundingRate]` | 1 |

### Binance adapter changes

| File | Change | Lines |
|------|--------|-------|
| rest_adapter.py | Set `currency="USDT"`, `fee_source="live"` in fetch_account | 2 |
| rest_adapter.py | Set `reduce_only=True/False` (unchanged — already does this) | 0 |
| rest_adapter.py | Set `position_side=None` when empty string | 1 |
| rest_adapter.py | Return NormalizedFundingRate in fetch_current_funding_rates | 5 |
| rest_adapter.py | Improve is_close logic: use side+positionSide deterministic check | 5 |
| rest_adapter.py | Set fee_asset from commissionAsset (already does, just verify default change works) | 0 |
| ws_adapter.py | Use WSEventType constants instead of string literals | 5 |
| constants.py | Add `stop_loss_limit`, `take_profit_limit` to ORDER_TYPE_FROM_BINANCE | 2 |

### Bybit adapter changes

| File | Change | Lines |
|------|--------|-------|
| rest_adapter.py | Set `currency="USDT"`, `fee_source="default"` in fetch_account | 2 |
| rest_adapter.py | Set `position_side=None` for one-way mode (positionIdx=0) | 1 |
| rest_adapter.py | Return NormalizedFundingRate in fetch_current_funding_rates | 5 |
| rest_adapter.py | Improve is_close: use closedSize > 0 field | 3 |
| rest_adapter.py | Set fee_asset from fee.currency (already does) | 0 |
| ws_adapter.py | Use WSEventType constants instead of string literals | 5 |
| constants.py | Add stop_loss_limit, take_profit_limit to ORDER_TYPE_FROM_BYBIT | 2 |

### Consumer changes

| File | Change | Lines |
|------|--------|-------|
| api/routes_analytics.py | `fd.get("funding_rate")` → `fd.funding_rate` (3 sites) | 3 |
| api/cache.py | `data.get("funding_rate")` → `data.funding_rate` (2 sites) | 2 |
| core/exchange_income.py `fetch_funding_rates()` | Update return type annotation | 1 |
| core/exchange.py `fetch_open_orders_tpsl()` | Handle `position_side is None` (already falsy, no logic change) | 0 |
| core/ws_manager.py | Use WSEventType constants in event dispatch | 3 |

### Test surface

| Test file | Change needed |
|-----------|--------------|
| tests/test_rl3_exception_coverage.py | No change (field types are Optional — test mocks still work) |
| NEW: tests/test_protocol_dataclasses.py | Verify Optional fields, default values, NormalizedFundingRate |
| Existing order_manager tests | Verify position_side=None doesn't break transition logic |

---

## Step 3: SupportsListenKey + Auth Model

### protocols.py modifications

| Change | Lines |
|--------|-------|
| Remove `create_listen_key` and `keepalive_listen_key` from ExchangeAdapter | -6 |
| Add `SupportsListenKey` protocol (2 methods) | +8 |
| Add to WSAdapter: `requires_post_connect_auth() → bool` | +3 |
| Add to WSAdapter: `build_auth_payload() → Optional[dict]` | +3 |
| Add to WSAdapter: `build_subscribe_payload(topics) → Optional[dict]` | +3 |

### Binance adapter changes

| File | Change | Lines |
|------|--------|-------|
| rest_adapter.py | Add `SupportsListenKey` to class inheritance. Methods already exist. | 1 |
| ws_adapter.py | Add `requires_post_connect_auth() → False` | 2 |
| ws_adapter.py | Add `build_auth_payload() → None` | 2 |
| ws_adapter.py | Add `build_subscribe_payload(topics) → None` (topics in URL) | 2 |

### Bybit adapter changes

| File | Change | Lines |
|------|--------|-------|
| rest_adapter.py | Remove `create_listen_key` stub and `keepalive_listen_key` no-op | -6 |
| ws_adapter.py | Rename existing `build_auth_message()` → `build_auth_payload()` | 1 |
| ws_adapter.py | Rename existing `build_subscribe_message()` → `build_subscribe_payload()` | 1 |
| ws_adapter.py | Add `requires_post_connect_auth() → True` | 2 |

### Consumer changes

| File | Change | Lines |
|------|--------|-------|
| core/exchange.py | `create_listen_key()`: add isinstance check for SupportsListenKey before calling adapter | 5 |
| core/exchange.py | `keepalive_listen_key()`: same isinstance check | 5 |
| core/ws_manager.py `_user_data_loop()` | After connect: if `ws_adapter.requires_post_connect_auth()`, send auth + subscribe payloads | 8 |
| core/ws_manager.py `_keepalive_loop()` | Guard with isinstance(adapter, SupportsListenKey) | 3 |
| core/ws_manager.py `_reconnect_user()` | Guard listen key refresh with isinstance | 3 |
| core/schedulers.py `_startup_fetch()` | Guard listen key creation with isinstance | 3 |
| api/routes_accounts.py `_reinit()` | Guard listen key creation with isinstance | 3 |

### Test surface

| Test file | Change needed |
|-----------|--------------|
| tests/test_rl3_exception_coverage.py `ws__keepalive_loop` | Update mock — may need to mock isinstance check |
| NEW: tests/test_listen_key_protocol.py | Verify Binance implements SupportsListenKey, Bybit doesn't |
| NEW: tests/test_ws_auth_model.py | Verify post-connect auth flow for Bybit adapter |

---

## Step 4: fetch_price_extremes

### protocols.py modifications

| Change | Lines |
|--------|-------|
| Remove `fetch_agg_trades(symbol, start_ms, end_ms) → List[Dict]` | -4 |
| Add `fetch_price_extremes(symbol, start_ms, end_ms, precision) → Tuple[Optional[float], Optional[float]]` | +12 |

```python
async def fetch_price_extremes(
    self,
    symbol: str,
    start_ms: int,
    end_ms: int,
    precision: Literal["high", "medium", "low", "auto"] = "auto",
) -> Tuple[Optional[float], Optional[float]]:
    """Return (max_price, min_price) for the time window.

    precision hint (adapter maps to native resolution):
      "high"   — tick-level (aggTrades or equivalent)
      "medium" — 1m OHLCV
      "low"    — 1h OHLCV
      "auto"   — adapter decides based on window duration
    """
    ...
```

### Binance adapter changes (`binance/rest_adapter.py`)

Move the multi-resolution logic currently in `exchange_market.py`
(`_agg_extremes` + `_ohlcv_hl` + tier routing) INTO the adapter:

| Change | Lines |
|--------|-------|
| Remove `fetch_agg_trades()` method | -10 |
| Add `fetch_price_extremes()` with full tier logic | +60 |
| Tier routing: "auto" uses duration heuristic (current logic from `fetch_hl_for_trade`) | included |
| "high" → aggTrades pagination (current `_agg_extremes` logic) | included |
| "medium" → 1m OHLCV (current `_ohlcv_hl` with "1m") | included |
| "low" → 1h OHLCV (current `_ohlcv_hl` with "1h") | included |
| Hybrid sections (tier 2/3 entry-agg + body-OHLCV + exit-agg) | included |

Note: This is a **relocation** of existing logic from exchange_market.py,
not new logic. The adapter internalizes the pagination and boundary-minute
patterns that are currently in the consumer.

### Bybit adapter changes (`bybit/rest_adapter.py`)

| Change | Lines |
|--------|-------|
| Remove `fetch_agg_trades()` method (currently fakes Binance format) | -13 |
| Add `fetch_price_extremes()` using Bybit's native fetch_trades + OHLCV | +40 |
| Precision mapping: "high" → paginated fetch_trades, "medium"/"low" → OHLCV | included |
| No need to fake `{"p", "T"}` format — adapter reduces internally | included |

### Consumer changes

| File | Change | Lines |
|------|--------|-------|
| core/exchange_market.py | Delete `_agg_extremes()` function entirely (~45 lines) | -45 |
| core/exchange_market.py | Delete `_ohlcv_hl()` function (or keep as utility if used elsewhere) | -15 |
| core/exchange_market.py | Rewrite `fetch_hl_for_trade()`: delegate to `adapter.fetch_price_extremes()` with "auto" precision. Remove internal tier routing. | ~20 (net reduction) |
| core/exchange.py | Remove re-export of `_agg_extremes` if present | ~1 |
| core/reconciler.py | No change — calls `fetch_hl_for_trade` (unchanged public API) | 0 |

**Key insight**: `fetch_hl_for_trade` becomes a thin wrapper that gets
the adapter and calls `adapter.fetch_price_extremes(symbol, start_ms, end_ms, "auto")`.
The merge logic (`_merge_hl` for combining multiple windows) stays in
exchange_market.py IF multi-section tiering remains in the consumer. OR
the adapter can own the full multi-section logic internally.

**Recommendation**: Adapter owns the full multi-section logic. Consumer
(`fetch_hl_for_trade`) becomes a one-liner delegation. This is cleanest —
each exchange can optimize its own resolution strategy.

### Test surface

| Test file | Change needed |
|-----------|--------------|
| tests/test_risk_engine.py `TestMFEMAE` | No change (tests calc_mfe_mae, not fetch_hl_for_trade) |
| tests/test_rl3_exception_coverage.py | Update mocks: `fetch_hl_for_trade` still raises from adapter internally |
| NEW: tests/test_fetch_price_extremes.py | Per-adapter unit tests: mock CCXT calls → verify correct (max, min) returned for each precision level |

---

## Step 5: NormalizedFundingRate + WSEventType

Already covered in Step 2 (protocol dataclass changes). Listed
separately for clarity but lands in the same commit.

---

## SR-7 Boundary Check

The following were identified during migration analysis but belong to
**SR-4** (exchange.py collapse) or later work. NOT in SR-7 scope:

| Item | Why out of scope | Belongs to |
|------|-----------------|------------|
| Eliminate `_REST_POOL` ThreadPoolExecutor | Internal exchange.py implementation — not protocol | SR-4 |
| Remove `get_exchange()` legacy singleton | Adapter factory handles this — cleanup | SR-4 |
| Move `fetch_exchange_trade_history` to adapter | Large function with complex augmentation logic — internal | SR-4 |
| Wire `exchange_market.py` fully through adapter | Several functions still use raw CCXT — routing, not protocol | SR-6 |
| `fetch_ohlcv_window` pagination | Internal helper, not protocol surface | SR-4 |

---

## Total Estimated Changes

| Step | New lines | Removed lines | Net | Files touched |
|------|-----------|---------------|-----|---------------|
| 1. Errors | +80 | -0 | +80 | 9 (1 new + 8 modified) |
| 2. Dataclasses | +30 | -5 | +25 | 12 |
| 3. ListenKey + Auth | +40 | -12 | +28 | 8 |
| 4. fetch_price_extremes | +120 | -70 | +50 | 5 |
| **Total** | **+270** | **-87** | **+183** | **~15 unique files** |

Plus test files: ~4 new test files, ~2 updated test files.

---

## Recommended Phase 4 Sub-Steps

Within Phase 4 (implementation), land as separate commits:

1. `core/adapters/errors.py` + adapter `_run()` wrappers + consumer catch-site migration
2. Protocol dataclass changes + adapter field updates + consumer attribute access updates
3. SupportsListenKey protocol + consumer isinstance guards + Bybit stub removal
4. `fetch_price_extremes` on both adapters + exchange_market.py simplification
5. Regression tests for each step (written FIRST per workflow)

Each commit: tests first → verify fail → implement → verify pass → smoke-diff.
