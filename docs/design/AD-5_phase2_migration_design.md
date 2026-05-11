# AD-5 Phase 2: Migration Design (Option A)

**Date**: 2026-05-12
**Approach**: Pagination wrapper around sync adapter

---

## 1. Adapter Call Shape

Adapter already has `fetch_ohlcv(symbol, timeframe, limit, since_ms)`.
Signature matches OHLCVFetcher's needs exactly:

```python
# Current (direct ccxt):
candles = await exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=candle_limit)

# Post-migration (via adapter):
candles = await adapter.fetch_ohlcv(symbol, timeframe, candle_limit, since_ms=since_ms)
```

Adapter's `fetch_ohlcv` runs through `self._run()` (executor-wrapped).
The `await` in OHLCVFetcher's loop works because `_run()` returns a
coroutine via `loop.run_in_executor()`.

**No adapter method additions needed.** Existing signature is sufficient.

---

## 2. Pagination Loop Structure

Stays in OHLCVFetcher — unchanged from current implementation:

- **Batch size**: `_get_ohlcv_limit()` (reads `adapter.ohlcv_limit`, default 1500)
- **Cursor**: `since_ms`, advances by `last_ts + _tf_ms(timeframe)` after each batch
- **Throttle**: `await asyncio.sleep(0.25)` between batches
- **Termination**: `len(candles) < candle_limit` (end of data) OR `last_ts <= since_ms` (no progress) OR `since_ms >= now_ms` (reached present)
- **Gap detection**: Existing DB range check avoids re-fetching already-stored data

The pagination loop is domain logic (how much history to fetch, when to
stop) — correct to keep in OHLCVFetcher per SR-8's abstraction-level
precedent.

---

## 3. Windows DNS Investigation

**Adapter path is safe.** Verified:

| Component | Adapter (sync) | OHLCVFetcher (current async) |
|-----------|---------------|------------------------------|
| HTTP library | `requests` (via sync ccxt) | `aiohttp` (via ccxt.async_support) |
| DNS resolution | OS-native (sync, via requests) | c-ares/aiodns (async, problematic on Windows) |
| Proxy config | `params["proxies"] = {"http": ..., "https": ...}` | `params["aiohttp_proxy"] = ...` |
| ThreadedResolver needed? | **No** — sync DNS is fine | Yes (current workaround) |

Post-migration, OHLCVFetcher calls adapter's sync `fetch_ohlcv()` through
the executor. DNS resolution happens inside the sync ccxt call on the
executor thread — uses OS DNS, not aiohttp's async resolver. **The Windows
DNS workaround becomes unnecessary and is deleted.**

**Not a blocker.** Migration eliminates the problem rather than needing
to address it.

---

## 4. Exception Mapping

Per SR-7 Step 1, adapter's `BaseExchangeAdapter._run()` already translates
ccxt exceptions to neutral types at the boundary:

| ccxt exception | → neutral type |
|----------------|---------------|
| `ccxt.RateLimitExceeded` / `ccxt.DDoSProtection` | `RateLimitError` |
| `ccxt.NetworkError` / `ccxt.RequestTimeout` | `ConnectionError` |
| `ccxt.AuthenticationError` | `AuthenticationError` |
| `ccxt.InvalidOrder` / `ccxt.InsufficientFunds` | `ValidationError` |
| `ccxt.ExchangeError` | `ExchangeError` |

**OHLCVFetcher catch sites change from ccxt types to neutral types:**

```python
# Before:
except ccxt.BadSymbol:
except ccxt.NetworkError as e:

# After:
from core.adapters.errors import ConnectionError as AdapterConnectionError, ValidationError
except ValidationError:       # covers BadSymbol (mapped by adapter)
except AdapterConnectionError as e:  # covers NetworkError, RequestTimeout
```

Note: `ccxt.BadSymbol` maps to `ValidationError` in the adapter's
translation layer (it inherits from `ccxt.ExchangeError` which maps to
`ExchangeError`, but BadSymbol is more specifically a validation issue).
Verify during implementation — if BadSymbol maps to `ExchangeError`
instead, catch that.

---

## 5. Retry Logic Placement

**Stays in OHLCVFetcher.** Wraps adapter calls.

```python
except AdapterConnectionError as e:
    retries += 1
    if retries > _MAX_RETRIES:
        log.error("Network error fetching %s after %d retries: %s", symbol, _MAX_RETRIES, e)
        break
    wait = min(5 * (2 ** (retries - 1)), 60)
    log.warning("Network error fetching %s (attempt %d/%d): %s — retrying in %ds",
                symbol, retries, _MAX_RETRIES, e, wait)
    await asyncio.sleep(wait)
    continue
```

**Rationale**: Batch operations span minutes. A single transient network
blip shouldn't abort a 365-day backfill. The adapter's per-call retry
(ccxt `enableRateLimit`) handles in-request retries; OHLCVFetcher's retry
handles between-request failures (connection drops between batches).

---

## 6. Session Lifecycle — What's Deleted

| Deleted | Why |
|---------|-----|
| `self._exchange` (ccxt.async_support instance) | Replaced by adapter |
| `_get_exchange()` method (~40 LOC) | No longer needed |
| `close()` method | Adapter lifecycle managed by exchange_factory |
| `import ccxt.async_support` | No direct ccxt usage |
| `import aiohttp` | No custom session |
| `ThreadedResolver` / `TCPConnector` / `ClientSession` | DNS fix unnecessary with sync adapter |
| `own_session = True` pattern | No session to manage |

**Constructor becomes**:
```python
def __init__(self, adapter=None) -> None:
    self._adapter = adapter
```

Adapter injected by caller (same pattern as SR-8's RegimeFetcher).

---

## 7. Commit Strategy

**Single atomic commit.** Justification:
- Structural change (delete session management, inject adapter)
- All sites change together (can't partially migrate)
- ~60 LOC deleted, ~15 LOC added (net -45)
- 2 callers, both updated simultaneously

---

## 8. Test Coverage

**Existing tests**: `test_smoke.py` imports `core.ohlcv_fetcher` — must
still pass.

**New tests**:
- Source inspection: no `ccxt.async_support`, no `aiohttp`, no `_get_exchange`
- Constructor accepts adapter parameter
- OHLCVFetcher has no `close()` method (or it's a no-op)
- Exception types in source: `AdapterConnectionError` / `ValidationError`
  instead of `ccxt.NetworkError` / `ccxt.BadSymbol`

**Caller tests**: routes_backtest and CLI entry both need adapter injection.
Route test via existing test_routes.py if backtest route is covered; CLI
entry via source inspection.

---

## Migration Cost

| Change | Lines |
|--------|-------|
| Delete `_get_exchange()` + `close()` + session management | -45 |
| Constructor: add adapter param | +2 |
| `fetch_and_store()`: replace `exchange.fetch_ohlcv` → `adapter.fetch_ohlcv` | +1, -1 |
| `fetch_and_store()`: replace `exchange.load_markets` → `adapter.load_markets` | +1, -1 |
| Exception mapping: ccxt types → neutral types | +3, -3 |
| Remove `import ccxt.async_support`, `import aiohttp` | -2 |
| Add `from core.adapters.errors import ...` | +1 |
| Caller updates (routes_backtest, CLI): inject adapter | +4, -4 |
| **Net** | **~-45** |
