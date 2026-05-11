# SR-4 Phase 2: Collapse Design

**Date**: 2026-05-12
**Depends on**: Phase 1 enumeration, SR-7 completed

---

## 1. SR-4d — fetch_ohlcv_window dead-code verification

### Grep evidence

```
$ grep -r "fetch_ohlcv_window" . --include="*.py"
./core/exchange_market.py:55:  async def fetch_ohlcv_window(   ← DEFINITION
./core/exchange.py:408:        fetch_ohlcv_window,              ← RE-EXPORT
```

**Zero callers.** The only two matches are the function definition and
the re-export. After SR-7 Step 4 moved tier/pagination logic into
`adapter.fetch_price_extremes()`, no code calls `fetch_ohlcv_window`.

### Proposal

**Delete** `fetch_ohlcv_window` from exchange_market.py and remove from
the re-export block in exchange.py.

**Migration cost**: ~15 lines deleted. No consumer changes (zero callers).

---

## 2. SR-4c — Augmentation logic extraction

### Problem

Three functions in exchange.py / exchange_income.py contain domain logic
beyond adapter delegation:

| Function | File | LOC | Logic |
|----------|------|-----|-------|
| `populate_open_position_metadata` | exchange.py:244 | ~70 | Loop: fetch trades → entry time, fetch extremes → MFE/MAE, fetch fees |
| `fetch_open_orders_tpsl` | exchange.py:322 | ~70 | Fetch orders → TP/SL→position mapping by (symbol, direction) |
| `fetch_exchange_trade_history` | exchange_income.py:254 | ~130 | Fetch income → augment with direction, entry/exit price, fees, open_time |

These are NOT adapter concerns (adapters do exchange I/O → normalized
shapes). They are **domain orchestration** — fetching multiple adapter
results and composing them into business objects.

### Destination: stay in exchange.py / exchange_income.py

**Recommendation**: Do NOT extract to a new service file. These functions
are already separated from adapter logic (they call `_get_adapter()` for
I/O and apply domain logic on the results). Moving them to a new file
creates churn without architectural benefit — their natural home is the
module that orchestrates exchange interactions.

The original SR-4c description said "Move to adapter or service layer."
After analysis:
- **Not adapter**: domain logic shouldn't live inside adapters
- **Not new service file**: existing files already serve this role

**Action**: Re-classify SR-4c as "no change needed." The current
placement is correct — these are orchestration functions in exchange.py /
exchange_income.py that call adapters for I/O. This is the right layer.

Document the architectural boundary:
```
adapters/        → Exchange I/O → NormalizedXxx shapes
exchange.py      → Orchestration (calls adapters, applies domain logic)
exchange_market.py → Market data orchestration
exchange_income.py → Income/trade history orchestration
```

**Migration cost**: ZERO. Documentation only.

---

## 3. SR-6a — Wire exchange_market.py through adapter

### Current state

4 functions in exchange_market.py call `get_exchange()` + `_REST_POOL`
directly instead of using the adapter:

| Function | Line | Raw CCXT call |
|----------|------|---------------|
| `fetch_ohlcv` | 44-51 | `ex.fetch_ohlcv(symbol, timeframe, limit)` |
| `fetch_orderbook` | 143-151 | `ex.fetch_order_book(symbol, limit)` |
| `fetch_mark_price` | 157-166 | `ex.fetch_ticker(symbol)` |
| `fetch_exchange_info` | exchange.py:140-143 | `ex.fetch_time` |

`fetch_ohlcv_window` is dead code (SR-4d deletes it).

### Adapter protocol additions

`fetch_ohlcv` already exists on ExchangeAdapter. Three methods need
adding:

```python
# In ExchangeAdapter protocol:

async def fetch_orderbook(self, symbol: str, limit: int = 20) -> Dict:
    """Fetch current orderbook snapshot.
    Returns: {"bids": [[price, qty], ...], "asks": [[price, qty], ...]}
    """
    ...

async def fetch_mark_price(self, symbol: str) -> float:
    """Fetch current mark/last price for a symbol."""
    ...

async def fetch_server_time(self) -> int:
    """Fetch exchange server time (ms UTC). For latency measurement."""
    ...
```

### Adapter implementations

**Binance** (rest_adapter.py):
```python
async def fetch_orderbook(self, symbol, limit=20):
    return await self._run(lambda: self._ex.fetch_order_book(symbol, limit=limit))

async def fetch_mark_price(self, symbol):
    ticker = await self._run(lambda: self._ex.fetch_ticker(symbol))
    return float(ticker.get("last") or ticker.get("close") or 0)

async def fetch_server_time(self):
    return await self._run(self._ex.fetch_time)
```

**Bybit** (rest_adapter.py): Same pattern — CCXT methods are generic.

### Consumer migration (exchange_market.py)

Each function replaces `get_exchange()` + `_REST_POOL` + `run_in_executor`
with `_get_adapter()` + adapter method:

**fetch_ohlcv** (line 30): Already has plugin-connected gate.
```python
# Before:
ex = get_exchange()
candles = await loop.run_in_executor(_REST_POOL, _fetch)
# After:
adapter = _get_adapter()
candles = await adapter.fetch_ohlcv(symbol, timeframe, limit)
```

**fetch_orderbook** (line 131): Already has plugin-connected gate.
```python
# Before:
ex = get_exchange()
ob = await loop.run_in_executor(_REST_POOL, _fetch)
# After:
adapter = _get_adapter()
ob = await adapter.fetch_orderbook(symbol, limit)
```

**fetch_mark_price** (line 156): No gate.
```python
# Before:
ex = get_exchange()
price = await loop.run_in_executor(_REST_POOL, _fetch)
# After:
adapter = _get_adapter()
price = await adapter.fetch_mark_price(symbol)
```

**fetch_exchange_info** (exchange.py:137): Server time.
```python
# Before:
ex = get_exchange()
server_time = await loop.run_in_executor(_REST_POOL, ex.fetch_time)
# After:
adapter = _get_adapter()
server_time = await adapter.fetch_server_time()
```

### exchange_market.py post-migration

After migration, exchange_market.py no longer imports `get_exchange` or
`_REST_POOL`. Its imports reduce to:
```python
from core.adapters.errors import RateLimitError
from core.state import app_state
```
Plus the late-import `_get_adapter` wrapper.

**Migration cost**: ~30 lines changed across 4 functions + ~15 lines
added per adapter (3 new methods each).

---

## 4. SR-4a + SR-4b — Remove singleton + pool

### Prerequisites

After SR-6a completes, the only remaining caller of `get_exchange()` is...
none. All functions will use `_get_adapter()`. Verify with grep.

### What gets deleted

| Element | File | Lines |
|---------|------|-------|
| `_REST_POOL` | exchange.py:68 | 1 |
| `_make_exchange()` | exchange.py:71-85 | 15 |
| `_exchange` | exchange.py:88 | 1 |
| `get_exchange()` | exchange.py:91-116 | 26 |
| `import ccxt` | exchange.py:16 | 1 (if no other ccxt usage remains) |
| `from concurrent.futures import ThreadPoolExecutor` | exchange.py:12 | 1 |

Also remove from importers:
- `exchange_market.py:16` — `from core.exchange import get_exchange, _REST_POOL`
- `ws_manager.py:27` — `get_exchange, _REST_POOL`

### What stays in exchange.py

| Function | Why it stays |
|----------|-------------|
| `handle_rate_limit_error()` | Consumed by 6+ modules |
| `is_rate_limited()` | Accessor |
| `_get_adapter()` | Central adapter lookup |
| `fetch_exchange_info()` | Orchestration (now via adapter) |
| `fetch_account()` | Orchestration |
| `fetch_positions()` | Orchestration |
| `populate_open_position_metadata()` | Orchestration (SR-4c: stays) |
| `fetch_open_orders_tpsl()` | Orchestration (SR-4c: stays) |
| `create_listen_key()` | Protocol-guarded dispatch |
| `keepalive_listen_key()` | Protocol-guarded dispatch |
| Re-export block | Backward compatibility |

**exchange.py post-collapse**: A thin orchestration facade — no raw CCXT,
no thread pool, no singleton. All I/O goes through `_get_adapter()`.
The file remains because it provides the public API (`fetch_account`,
`fetch_positions`, etc.) that consumers import.

### ccxt import

After removing the singleton, check if `import ccxt` is still needed in
exchange.py. Currently used by:
- `_make_exchange()` → deleted
- `get_exchange()` return type annotation → deleted

If no remaining usage: remove `import ccxt` entirely from exchange.py.
ccxt is only imported in adapter files + regime_fetcher (async_support).

**Migration cost**: ~45 lines deleted from exchange.py, ~5 lines removed
from importers.

---

## CRITICAL: _REST_POOL Unification Investigation

### Are they functionally identical?

| Property | exchange.py:68 | adapters/base.py:26 |
|----------|----------------|---------------------|
| Type | `ThreadPoolExecutor` | `ThreadPoolExecutor` |
| max_workers | 8 | 8 |
| thread_name_prefix | `"rest"` | `"adapter-rest"` |
| Purpose | Blocking CCXT REST calls | Blocking CCXT REST calls |
| Created at | Module import time | Module import time |
| Destroyed at | Process exit | Process exit |

**Functionally identical**: same type, same pool size, same purpose, same
lifecycle (both process-scoped, created at import, never explicitly shut
down).

### Do they have different lifecycle management?

No. Both are module-level constants, created once at import time, never
closed or recreated. Neither is adapter-scoped — base.py's pool is shared
across all adapter instances (module-level, not instance-level).

### Are they ever used concurrently for different work?

Yes, currently. When `fetch_ohlcv()` in exchange_market.py calls
`loop.run_in_executor(_REST_POOL, _fetch)` (exchange.py's pool), and
simultaneously a reconciler calls `adapter.fetch_price_extremes()` which
goes through `adapter._run()` (base.py's pool), both pools are active.
This means the engine currently has **16 threads** available for REST
calls (8 per pool), though the effective concurrency is limited by
Binance's 2400 req/min rate limit.

### Can they be unified?

**Yes.** After SR-6a, all REST calls go through `adapter._run()` which
uses base.py's `_REST_POOL`. exchange.py's `_REST_POOL` has zero callers.
Delete it.

**Unification plan**: exchange.py's pool is simply deleted (SR-4a). No
migration to base.py needed — adapters already use their own pool.
Pool size stays at 8 (base.py's pool). If 16→8 thread reduction causes
throughput issues under load, increase base.py's pool size later
(configuration, not architecture).

**Lifecycle implication**: Going from 2 pools to 1 pool halves available
REST threads from 16 to 8. Given Binance's 2400 req/min limit and the
RL-1/RL-3 pacing changes, 8 threads is more than sufficient. The engine
was never intentionally designed for 16 threads — the duplication was
accidental (exchange_market.py copied the pattern from exchange.py when
it was split out).

---

## Summary: Landing Sequence

| Step | Sub-item | Action | Net LOC | Risk |
|------|----------|--------|---------|------|
| 1 | SR-4d | Delete `fetch_ohlcv_window` (dead code) | -15 | ZERO |
| 2 | SR-4c | No code change — document architectural boundary | 0 | ZERO |
| 3 | SR-6a | Add 3 adapter methods + migrate 4 functions | +30 net | LOW |
| 4 | SR-4a+b | Delete singleton + pool + imports | -45 | LOW (all callers migrated in step 3) |

**Total**: ~30 lines net reduction. exchange.py shrinks from ~416 LOC to
~360 LOC and contains zero raw CCXT calls.
