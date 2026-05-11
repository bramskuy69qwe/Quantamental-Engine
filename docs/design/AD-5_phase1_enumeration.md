# AD-5 Phase 1: ohlcv_fetcher.py Enumeration

**Date**: 2026-05-12
**Source**: `core/ohlcv_fetcher.py` (283 lines)
**Context**: Last remaining direct ccxt usage in codebase after SR-8

---

## Class Structure

`OHLCVFetcher` — single-use async batch fetcher for historical OHLCV data.

| Aspect | Details |
|--------|---------|
| Constructor | `self._exchange = None` (lazy init) |
| Lifecycle | Created fresh per job → fetch N symbols → `close()` |
| Callers | `api/routes_backtest.py` (POST /api/backtest/fetch), CLI entry |

---

## Raw CCXT Usage (3 sites)

| Site | Line | Call | Purpose |
|------|------|------|---------|
| `_get_exchange()` | 85 | `ccxt.async_support.[class](params)` | Create async exchange instance |
| `fetch_and_store()` | 143 | `await exchange.load_markets()` | Validate connectivity |
| `fetch_and_store()` | 163 | `await exchange.fetch_ohlcv(symbol, tf, since, limit)` | Fetch candle batch |

---

## Why OHLCVFetcher Can't Use Existing Adapter

| Dimension | Adapter | OHLCVFetcher |
|-----------|---------|-------------|
| Sync/async | Sync (executor-wrapped) | Async-native (`ccxt.async_support`) |
| Pagination | Single call | Loop: cursor advancement, 1500-candle batches |
| Retry | ccxt built-in only | Custom exponential backoff (5 retries, 5-60s) |
| Session | No session management | Custom aiohttp session + ThreadedResolver (Windows DNS fix) |
| Use case | Request-response (instant) | Batch (365 days = 2+ requests/symbol, sequential) |

The adapter's `fetch_ohlcv()` is a single-call method. OHLCVFetcher
wraps it with pagination, retry, throttling, and progress reporting.

---

## Session & BU-1 Connection

OHLCVFetcher creates its own `aiohttp.ClientSession` (line 83) with
`own_session=True`. Both current callers close it in `finally` blocks.

**BU-1 risk**: If `close()` not awaited (exception before finally),
session leaks → "Unclosed client session" asyncio ERROR. The two BU-1
occurrences in logs (May 9, May 10) were from pre-SR-8 regime_fetcher
code (which had the same pattern — deleted in SR-8). OHLCVFetcher's
callers are safe, but the pattern is fragile.

---

## Migration Options

### Option A: Pagination wrapper around sync adapter

OHLCVFetcher becomes a pagination loop calling `adapter.fetch_ohlcv()`
(sync, executor-wrapped). Loses async-native efficiency but gains
adapter abstraction + neutral error types.

**Trade-off**: Each batch goes through executor → thread pool → CCXT →
back. For 2-5 batches per symbol this is acceptable. For 100+ batches
(multi-year backfill) it's measurably slower than async-native.

### Option B: Add async fetch_ohlcv to adapter protocol

New optional protocol `SupportsAsyncOHLCV` with async-native
`fetch_ohlcv_async()`. Binance implements using `ccxt.async_support`.
OHLCVFetcher uses this.

**Trade-off**: Adds complexity to adapter layer for one consumer. Two
parallel OHLCV fetch methods (sync + async). Harder to maintain.

### Option C: Keep OHLCVFetcher as-is, isolate exceptions

OHLCVFetcher keeps its own `ccxt.async_support` instance but catches
ccxt exceptions and re-raises as neutral `AdapterError` types. Adds
context-manager pattern for session safety.

**Trade-off**: Still imports ccxt directly. But the isolation is clean —
callers never see ccxt types. Practical given OHLCVFetcher's unique
lifecycle (batch, async, retry-heavy).

---

## Summary

| Aspect | Current | Migration target |
|--------|---------|-----------------|
| ccxt import | Direct `ccxt.async_support` | TBD per option chosen |
| Exception types | Raw `ccxt.NetworkError`, `ccxt.BadSymbol` | Neutral `AdapterError` types |
| Session management | Manual create/close | Context manager pattern |
| Pagination | Custom loop (correct) | Keep — adapter doesn't paginate |
| Callers | 2 (routes_backtest, CLI) | Unchanged |
