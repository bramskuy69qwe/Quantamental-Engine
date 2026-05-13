# SR-4 Phase 3: Migration Plan

**Date**: 2026-05-12
**Landing order**: SR-4d → SR-6a → SR-4a+b

---

## Step 1: SR-4d — Delete fetch_ohlcv_window

### Approach: Atomic single commit

**Changes:**
- exchange_market.py: delete `fetch_ohlcv_window()` (lines 55-79, 25 LOC)
- exchange.py: remove `fetch_ohlcv_window` from re-export block (line 408)

### Tests affected
- No existing tests reference `fetch_ohlcv_window` (grep confirms zero callers)
- New test: verify `fetch_ohlcv_window` is not importable from `core.exchange`

### Smoke-diff expectation: EMPTY
Pure dead-code deletion — no behavioral change.

### Dependencies: None

---

## Step 2: SR-6a — Wire exchange_market.py through adapter

### Approach: Atomic single commit

**Justification for atomic (not multi-commit):**

The 3 new adapter methods and 4 caller migrations are tightly coupled.
Each caller migration replaces `get_exchange() + _REST_POOL` with
`_get_adapter() + adapter.method()`. Making intermediate commits (e.g.,
"add adapter method but don't migrate caller yet") adds protocol methods
that have zero callers at commit time — test-only coverage with no
production exercise. More importantly:

- All 4 callers share the same 2 dependencies (`get_exchange`, `_REST_POOL`)
- Migrating 3 of 4 leaves the shared dependencies alive, preventing
  Step 3 from landing
- The 3 adapter methods are trivial CCXT delegations (3-4 lines each) —
  no complex logic to test independently

The risk of atomic is LOW because:
- Each adapter method is a thin `self._run(lambda: self._ex.method())`
- Each caller migration is a mechanical replacement of the same pattern
- The smoke-diff catches any behavioral drift

### Changes (ordered within the commit)

**1. Protocol additions** (protocols.py):
```python
async def fetch_orderbook(self, symbol: str, limit: int = 20) -> Dict: ...
async def fetch_mark_price(self, symbol: str) -> float: ...
async def fetch_server_time(self) -> int: ...
```

**2. Binance adapter** (binance/rest_adapter.py):
```python
async def fetch_orderbook(self, symbol, limit=20):
    return await self._run(lambda: self._ex.fetch_order_book(symbol, limit=limit))

async def fetch_mark_price(self, symbol):
    def _fetch():
        ticker = self._ex.fetch_ticker(symbol)
        return float(ticker.get("last") or ticker.get("close") or 0)
    return await self._run(_fetch)

async def fetch_server_time(self):
    return await self._run(self._ex.fetch_time)
```

**3. Bybit adapter** (bybit/rest_adapter.py):
Same pattern — CCXT methods are generic across exchanges.

**4. Caller migrations** (exchange_market.py):

| Function | Before | After |
|----------|--------|-------|
| `fetch_ohlcv` (L30) | `get_exchange()` + `_REST_POOL` | `_get_adapter()` + `adapter.fetch_ohlcv()` |
| `fetch_orderbook` (L131) | `get_exchange()` + `_REST_POOL` | `_get_adapter()` + `adapter.fetch_orderbook()` |
| `fetch_mark_price` (L156) | `get_exchange()` + `_REST_POOL` | `_get_adapter()` + `adapter.fetch_mark_price()` |

**5. fetch_exchange_info migration** (exchange.py):

| Function | Before | After |
|----------|--------|-------|
| `fetch_exchange_info` (L137) | `get_exchange()` + `_REST_POOL` | `_get_adapter()` + `adapter.fetch_server_time()` |

**6. Import cleanup** (exchange_market.py):
Remove `from core.exchange import get_exchange, _REST_POOL` — no longer
needed after migration. Keep `_get_adapter` wrapper.

**7. Dead import cleanup** (exchange_income.py):
Remove `from core.exchange import get_exchange, _REST_POOL` — already
unused (grep-verified: imported at line 15 but never referenced elsewhere
in the file).

**8. Dead import cleanup** (ws_manager.py):
Remove `get_exchange, _REST_POOL` from the import line (line 27). These
were imported but unused after SR-7 changes.

### Tests

**Existing tests affected:**
- test_rate_limit.py `test_price_extremes_has_pacing`: inspects Binance
  adapter source — no change needed (fetch_price_extremes unchanged)
- test_smoke.py: import tests — no change (re-exports preserved)
- test_rl3_exception_coverage.py: no change (tests mock at function level)

**New tests:**
- Verify `fetch_orderbook`, `fetch_mark_price`, `fetch_server_time` exist
  on ExchangeAdapter protocol
- Verify both adapters implement all 3 methods (hasattr checks)
- Source inspection: exchange_market.py no longer references `get_exchange`
  or `_REST_POOL`
- Source inspection: exchange_income.py no longer references `get_exchange`
  or `_REST_POOL`

### Smoke-diff expectation: EMPTY
Mechanical replacement — adapter.method() calls the same CCXT method via
the same thread pool pattern. Behavioral equivalence guaranteed.

### Dependencies
- Depends on: SR-4d (fetch_ohlcv_window deleted, simplifies
  exchange_market.py imports)
- Required by: SR-4a+b (must complete before singleton/pool removal)

---

## Step 3: SR-4a+b — Delete singleton + pool

### Approach: Atomic single commit

### Pre-condition: Zero callers of get_exchange / _REST_POOL

**Required grep verification (run BEFORE implementation):**
```
grep -rn "get_exchange\|_REST_POOL\|_make_exchange\|_exchange" \
  core/ api/ --include="*.py" | grep -v __pycache__
```

Expected matches after SR-6a: ONLY in exchange.py itself (definition
lines). Zero matches in exchange_market.py, exchange_income.py,
ws_manager.py, or any api/ file.

### Changes

**Deletions from exchange.py:**

| Element | Lines | LOC |
|---------|-------|-----|
| `from concurrent.futures import ThreadPoolExecutor` | 12 | 1 |
| `_REST_POOL = ThreadPoolExecutor(...)` | 68 | 1 |
| `_make_exchange()` | 71-85 | 15 |
| `_exchange: Optional[ccxt.binance] = None` | 88 | 1 |
| `get_exchange()` | 91-116 | 26 |

**Total**: ~44 lines deleted.

**`import ccxt` removal check:**
After deleting the singleton, verify if `import ccxt` (line 16) has any
remaining usage in exchange.py. Grep for `ccxt.` in the file. If zero
matches → delete the import. Expected: zero remaining usage (all CCXT
access now goes through adapter).

**Import cleanups in exchange.py:**
Remove `ThreadPoolExecutor` import. Possibly remove `ccxt` import.

### Tests

**Existing tests affected:**
- test_smoke.py `test_import[core.exchange]`: still passes (module
  imports fine, just slimmer)
- test_rl3_exception_coverage.py, test_sr7_step1_errors.py: mock at
  function level, not at `get_exchange` level — no change needed

**New tests:**
- Verify `get_exchange` is NOT importable from `core.exchange`
  (`with pytest.raises(ImportError)` or `assert not hasattr(...)`)
- Verify `_REST_POOL` is NOT importable from `core.exchange`
- Verify exchange.py post-collapse functions still work:
  - `_get_adapter()` returns adapter (mock test)
  - `handle_rate_limit_error()` sets rate_limited_until (already tested)
  - `create_listen_key()` / `keepalive_listen_key()` with isinstance
    guard (already tested by SR-7 Step 3)
  - `fetch_account()`, `fetch_positions()` delegate to adapter (mock test)

### Smoke-diff expectation: EMPTY
Deletion of dead code only. All runtime paths already routed through
adapter by SR-6a.

### Dependencies
- Depends on: SR-6a complete (all callers migrated)

---

## Post-Collapse exchange.py Shape

After all 3 steps, exchange.py contains:

```
Functions remaining (~360 LOC):
  handle_rate_limit_error()       — rate-limit state management
  is_rate_limited()               — accessor
  _get_adapter()                  — central adapter lookup
  fetch_exchange_info()           — orchestration (via adapter)
  fetch_account()                 — orchestration (via adapter)
  fetch_positions()               — orchestration (via adapter + DataCache)
  populate_open_position_metadata() — orchestration (via adapter + DB)
  fetch_open_orders_tpsl()        — orchestration (via adapter + OrderManager)
  create_listen_key()             — protocol-guarded dispatch
  keepalive_listen_key()          — protocol-guarded dispatch
  Re-export block                 — backward compatibility

Deleted (~56 LOC):
  _REST_POOL                      — duplicate thread pool
  _make_exchange()                — legacy factory
  _exchange                       — legacy singleton
  get_exchange()                  — legacy getter

Imports removed:
  import ccxt                     — no direct CCXT usage
  from concurrent.futures import ThreadPoolExecutor
```

Zero raw CCXT calls. Zero thread pool. Zero singleton.
All I/O through `_get_adapter()` → adapter methods.

---

## Test Summary Across All Steps

| Step | New tests | Existing tests modified | Total at end |
|------|-----------|------------------------|-------------|
| SR-4d | 1 (dead-code deletion verification) | 0 | 326 |
| SR-6a | 4-5 (protocol methods, source inspection) | 0 | ~331 |
| SR-4a+b | 3-4 (singleton removal, facade verification) | 0 | ~335 |
