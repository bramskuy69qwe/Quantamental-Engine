# SR-8 Phase 1: regime_fetcher.py Enumeration

**Date**: 2026-05-12
**Source**: `core/regime_fetcher.py` (~450 LOC)

---

## Raw CCXT Usage (Migration Targets)

Only 2 functions use raw ccxt. Both call the self-managed
`ccxt.async_support.binanceusdm` instance via `_get_ccxt()`.

### Site 1: fetch_binance_oi() — line 297

| Aspect | Details |
|--------|---------|
| CCXT method | `exchange.fapiPublicGetOpenInterestHist(params)` |
| Parameters | `{symbol, period="1d", startTime, endTime, limit=30}` |
| Loop pattern | Per-symbol (10 hardcoded symbols), 29-day chunks, 0.3s pacing |
| Error handling | **DUAL-CATCH TODO(SR-8)**: `(_RLE, _ccxt.DDoSProtection, _ccxt.RateLimitExceeded)` |
| Rate-limit checks | `app_state.ws_status.is_rate_limited` at lines 317, 322 |

### Site 2: fetch_binance_funding() — line 379

| Aspect | Details |
|--------|---------|
| CCXT method | `exchange.fapiPublicGetFundingRate(params)` |
| Parameters | `{symbol, startTime, endTime, limit=1000}` |
| Loop pattern | Per-symbol (10 symbols), 30-day windows, 0.3s pacing |
| Error handling | **DUAL-CATCH TODO(SR-8)**: identical to Site 1 |
| Rate-limit checks | `app_state.ws_status.is_rate_limited` at lines 398, 405 |

---

## Self-Managed CCXT Instance: _get_ccxt()

| Aspect | Details |
|--------|---------|
| Line | 265-295 |
| Class | `ccxt.async_support.binanceusdm` |
| Session | Custom `aiohttp.ClientSession` with `ThreadedResolver` |
| Credentials | Optional (public endpoints work without auth) |
| Why async? | Historical — current code is fully sequential (no concurrency within fetcher) |
| Lifecycle | Lazy-created, cached, closed via `await fetcher.close()` |

---

## Existing Adapter Protocol Coverage

**Both needed adapter methods already exist:**

| Protocol | Method | Binance adapter | Bybit adapter |
|----------|--------|:---:|:---:|
| `SupportsFundingRates` | `fetch_funding_rates(symbol, start_ms, end_ms, limit)` | YES (line 453) | YES (line 469) |
| `SupportsOpenInterest` | `fetch_open_interest_hist(symbol, period, start_ms, end_ms, limit)` | YES (line 468) | NO |

**regime_fetcher uses neither.** It bypasses the adapter entirely and
makes direct ccxt.async_support calls to the same Binance endpoints.

---

## Non-CCXT Data Sources (OUT OF SCOPE)

| Function | Source | Library | Status |
|----------|--------|---------|--------|
| `fetch_vix()` | Yahoo Finance | yfinance | Keep as-is |
| `fetch_fred_series()` | FRED API | httpx | Keep as-is (clean async) |
| `compute_btc_rvol_ratio()` | DB OHLCV cache | internal | Keep as-is |

---

## Callers

| Caller | File:line | Frequency | What it calls |
|--------|-----------|-----------|---------------|
| Scheduler (TradFi) | schedulers.py:380 | Hourly | fetch_vix, fetch_fred, compute_rvol (non-CCXT, out of scope) |
| Scheduler (Binance) | schedulers.py:400 | Every 4 hours | `fetch_binance_oi()`, `fetch_binance_funding()` (CCXT, in scope) |

Scheduler creates a fresh `RegimeFetcher()` per refresh cycle, calls
methods, then `await fetcher.close()`.

---

## Migration Summary

**What changes:**
1. `fetch_binance_oi()`: replace `exchange.fapiPublicGetOpenInterestHist()`
   with `adapter.fetch_open_interest_hist()` (already on protocol)
2. `fetch_binance_funding()`: replace `exchange.fapiPublicGetFundingRate()`
   with `adapter.fetch_funding_rates()` (already on protocol)
3. Delete `_get_ccxt()` — no more self-managed ccxt.async_support instance
4. Collapse TODO(SR-8) dual-catch sites to single `RateLimitError`
5. Scheduler passes adapter instance instead of letting fetcher create its own

**What stays:**
- Pagination logic (29-day/30-day chunking, 0.3s pacing) — stays in
  regime_fetcher, wrapping adapter calls
- Rate-limit early-abort checks — stay
- Non-CCXT sources (VIX, FRED, rvol) — untouched

**New adapter methods needed: ZERO.** Both `SupportsFundingRates` and
`SupportsOpenInterest` protocols already have the needed methods, and
the Binance adapter already implements them.

**Bybit gap**: `SupportsOpenInterest` not implemented by Bybit adapter.
regime_fetcher should check `isinstance(adapter, SupportsOpenInterest)`
before calling. If not supported, skip OI fetch gracefully (same pattern
as `SupportsListenKey`).
