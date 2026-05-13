# FE-2 + FE-8 Phase 1: Calculator Stale-Symbol Investigation

**Date**: 2026-05-13
**Branch**: `fix/FE-2-FE-8-calculator-stale-symbol`
**Status**: Root cause identified, fix is simple (not architectural)

---

## Shared Root Cause

`set_calculator_symbol()` (ws_manager.py:537) is synchronous — updates
the global variable but does NOT:
1. Cancel old WS subscriptions (old symbol data keeps arriving)
2. Clear old caches (stale orderbook/mark_price persist)
3. Coordinate with pending HTMX requests

---

## FE-2: Recent-Click Partial State

**Race condition**: `recallHistory()` (calculator.html:549) fires
`updateOrderbook(ticker)` immediately, then `setTimeout(submit, 100ms)`.

1. `updateOrderbook()` creates HTMX `hx-get="/calculator/refresh/{ticker}"`
   with `hx-trigger="load"` → fires instantly for orderbook only
2. 100ms later, form submits to `/calculator/calculate` → returns full result
3. Orderbook arrives first (partial state), full result arrives second

**Fix**: Remove the 100ms setTimeout — fire form submit directly. The
`/calculator/calculate` endpoint already fetches orderbook and includes
it in the response. The independent orderbook HTMX request is redundant
on initial load.

**LOC**: ~3 lines (remove setTimeout, direct form submit)

---

## FE-8: Market Price Flicker

**Race condition**: Old symbol's WS streams keep running after symbol switch.

1. User switches symbol → `set_calculator_symbol(new_ticker)` → global updated
2. Old depth20/markPrice streams still connected → fire with old symbol data
3. `apply_mark_price()` and `apply_depth()` cache old data without checking
   if symbol is still the current calculator symbol
4. Template renders old cached data → then new data arrives → flicker

**Fix**: Clear calculator-specific caches on symbol switch. Add symbol
check in `set_calculator_symbol()` to evict old symbol's orderbook.

**LOC**: ~5 lines (cache eviction + guard)

---

## Downstream Impact

Both bugs are **display-only** — no state corruption, no analytics impact,
no financial consequence. Stale cached data is correct for its symbol,
just displayed in the wrong context. The cache naturally corrects on next
WS message for the new symbol.

---

## Severity

**LOW** (confirmed for both). Display flicker and partial render on
symbol switch. No data corruption. User workaround: click twice or
wait 2-3 seconds.

---

## Fix Shape (~10 LOC total)

### FE-2 (template fix, ~3 LOC)
In `recallHistory()`: replace `setTimeout(...requestSubmit(), 100)` with
direct `requestSubmit()`. The orderbook `hx-get` polling (every 2s) handles
ongoing refresh; the initial load doesn't need a separate pre-fetch.

### FE-8 (cache eviction, ~7 LOC)
In `set_calculator_symbol()` (ws_manager.py):
1. If symbol changed, delete old symbol from `orderbook_cache`
2. Trigger `restart_market_streams()` to switch WS subscriptions

**Recommendation**: Proceed directly to Phase 4. ~10 LOC combined.

---

## Files to Modify

| File | Change |
|------|--------|
| `templates/calculator.html:569-570` | Remove setTimeout, direct submit |
| `core/ws_manager.py:537-539` | Cache eviction + stream restart on symbol change |
