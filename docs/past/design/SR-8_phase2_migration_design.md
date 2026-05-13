# SR-8 Phase 2: Migration Design

**Date**: 2026-05-12
**Depends on**: Phase 1 enumeration

---

## 1. Migration Plan Per Function

### fetch_binance_oi() — line 297

| Aspect | Before | After |
|--------|--------|-------|
| CCXT call | `exchange.fapiPublicGetOpenInterestHist(params)` | `adapter.fetch_open_interest_hist(symbol, period, start_ms, end_ms, limit)` |
| Instance | `self._ccxt_exchange` (async_support) | Injected adapter (sync, via `_run()`) |
| Pagination | 29-day chunks, 0.3s pacing — in regime_fetcher | Unchanged — stays in regime_fetcher |
| Rate-limit check | `app_state.ws_status.is_rate_limited` before each call | Unchanged |
| Error handling | DUAL-CATCH → collapses (see section 3) | Single `RateLimitError` |
| isinstance guard | N/A | `isinstance(adapter, SupportsOpenInterest)` (see section 5) |

### fetch_binance_funding() — line 379

| Aspect | Before | After |
|--------|--------|-------|
| CCXT call | `exchange.fapiPublicGetFundingRate(params)` | `adapter.fetch_funding_rates(symbol, start_ms, end_ms, limit)` |
| Instance | `self._ccxt_exchange` (async_support) | Injected adapter |
| Pagination | 30-day windows, 0.3s pacing — in regime_fetcher | Unchanged |
| Rate-limit check | Unchanged | Unchanged |
| Error handling | DUAL-CATCH → collapses | Single `RateLimitError` |
| isinstance guard | N/A | `isinstance(adapter, SupportsFundingRates)` (see section 5) |

---

## 2. Singleton Deletion

### _get_ccxt() — lines 265-295

**Current callers** (within regime_fetcher.py):
- `fetch_binance_oi()` line 303: `exchange = await self._get_ccxt()`
- `fetch_binance_funding()` line 382: `exchange = await self._get_ccxt()`

**What replaces it**: `self._adapter` — injected via constructor.

**Deletions** (~35 LOC):
- `_get_ccxt()` method (lines 265-295)
- `self._ccxt_exchange` instance variable (line 43)
- `close()` method body (lines 45-48) — becomes no-op or deleted
  (adapter lifecycle managed by exchange_factory, not by fetcher)
- `import ccxt.async_support` (dynamic, inside `_get_ccxt`) — gone
- `import aiohttp` (inside `_get_ccxt`) — gone

---

## 3. Dual-Catch Collapse

### Site 1: fetch_binance_oi() — lines 333-344

**Before** (TODO(SR-8) site):
```python
except Exception as e:
    # TODO(SR-8): remove ccxt isinstance once regime_fetcher routes
    # through adapter — only RateLimitError will be needed.
    from core.adapters.errors import RateLimitError as _RLE
    import ccxt as _ccxt
    if isinstance(e, (_RLE, _ccxt.DDoSProtection, _ccxt.RateLimitExceeded)):
        from core.exchange import handle_rate_limit_error
        handle_rate_limit_error(e)
    else:
        log.warning("OI fetch failed for %s: %s", sym, e)
    break
```

**After**:
```python
except RateLimitError as e:
    from core.exchange import handle_rate_limit_error
    handle_rate_limit_error(e)
    break
except Exception as e:
    log.warning("OI fetch failed for %s: %s", sym, e)
    break
```

### Site 2: fetch_binance_funding() — lines 414-425

Identical transformation. Same TODO(SR-8) comment removed, same collapse
to specific-before-broad pattern.

---

## 4. Scheduler Injection

### Current pattern (schedulers.py:400-403)

```python
fetcher = RegimeFetcher()
await fetcher.fetch_binance_oi(symbols, ...)
await fetcher.fetch_binance_funding(symbols, ...)
await fetcher.close()
```

### Post-migration pattern

```python
from core.exchange import _get_adapter
adapter = _get_adapter()
fetcher = RegimeFetcher(adapter)
await fetcher.fetch_binance_oi(symbols, ...)
await fetcher.fetch_binance_funding(symbols, ...)
# No close() needed — adapter lifecycle managed by exchange_factory
```

### Constructor change

```python
class RegimeFetcher:
    def __init__(self, adapter=None):
        self._adapter = adapter
```

The `adapter` parameter is optional so that the TradFi refresh path
(line 380), which doesn't need an adapter (VIX, FRED, rvol only), can
still create `RegimeFetcher()` without one.

---

## 5. Bybit isinstance Guards

Two call sites need guards:

### fetch_binance_oi()

```python
if not isinstance(self._adapter, SupportsOpenInterest):
    log.info("OI fetch skipped — adapter doesn't support open interest")
    return
```

Bybit doesn't implement `SupportsOpenInterest` — OI fetch is skipped
gracefully.

### fetch_binance_funding()

```python
if not isinstance(self._adapter, SupportsFundingRates):
    log.info("Funding fetch skipped — adapter doesn't support funding rates")
    return
```

Bybit DOES implement `SupportsFundingRates`, so this guard is a safety
net (won't trigger for Bybit today, but protects against future adapters
that don't support funding rates).

---

## 6. Abstraction-Level Decision

### Option (a): Pagination stays in regime_fetcher (RECOMMENDED)

**Rationale**: The pagination patterns serve a DOMAIN purpose, not an
exchange-I/O purpose:

1. **29-day OI chunks**: Chosen to match regime classification's
   look-back window, not because of Binance API limits. A different
   domain use case might want 7-day chunks or full history.

2. **30-day funding windows**: Chosen to capture ~1 month of funding
   rate data per regime refresh. A backtest might want 90-day windows.

3. **10 hardcoded symbols**: The symbol selection is a REGIME decision
   (aggregate market breadth from top-10 perps), not an adapter concern.

4. **0.3s pacing**: Domain-level rate-limit courtesy, not exchange-
   specific. Different exchanges might tolerate faster/slower rates.

5. **Per-symbol iteration with early abort**: The `is_rate_limited`
   check between symbols is a domain-level circuit breaker, not
   something the adapter should own.

**Contrast with fetch_price_extremes**: That method pushed tier logic
into the adapter because the TIER SELECTION is exchange-specific
(aggTrades vs OHLCV availability differs per exchange; Binance has
aggTrades pagination at 1000, Bybit doesn't). The consumer's intent
("give me price extremes for this window") is genuinely exchange-
agnostic. The regime_fetcher's intent ("give me 29 days of OI in one
page") is NOT exchange-specific — it's the same request shape for any
exchange that supports OI history.

**Documentation for future maintainers** (add as comment in
regime_fetcher.py):

```python
# Pagination/chunking at this level (not in adapter) because:
# - Window sizes are domain-driven (regime look-back period)
# - Symbol selection is domain-driven (top-10 aggregate breadth)
# - Pacing is domain-driven (0.3s courtesy, not exchange-specific)
# - Early abort is domain-driven (rate-limit circuit breaker)
# Contrast: adapter.fetch_price_extremes() owns tier logic because
# resolution choice (aggTrades vs OHLCV) IS exchange-specific.
```

### Option (b): Push pagination into adapter — REJECTED

Would require new adapter methods:
```python
async def fetch_funding_history(symbol, start_ms, end_ms) -> List[Dict]
async def fetch_oi_history(symbol, start_ms, end_ms) -> List[Dict]
```
These would duplicate the existing `fetch_funding_rates` and
`fetch_open_interest_hist` with internal pagination — creating two ways
to fetch the same data (paginated vs single-page). The single-page
methods are already correct for the adapter's abstraction level.

---

## 7. Commit Strategy: Single atomic commit

**Justification**:
- Total scope: ~50 lines changed (2 function bodies, constructor,
  scheduler injection, 2 dual-catch collapses, _get_ccxt deletion)
- All changes serve one goal: eliminate self-managed ccxt instance
- Intermediate states (e.g., "inject adapter but keep _get_ccxt") are
  inconsistent and untestable
- Same pattern as SR-6 (similar scope, same justification)

---

## Migration Cost Summary

| Change | Lines |
|--------|-------|
| Delete `_get_ccxt()` + close() + instance var | -35 |
| Constructor: add `adapter` param | +2 |
| `fetch_binance_oi`: replace exchange call + isinstance guard | +5, -5 |
| `fetch_binance_funding`: replace exchange call + isinstance guard | +5, -5 |
| Collapse 2 dual-catch sites | +4, -12 |
| Scheduler injection (schedulers.py) | +3, -2 |
| Documentation comment | +5 |
| **Net** | **~-35** |
