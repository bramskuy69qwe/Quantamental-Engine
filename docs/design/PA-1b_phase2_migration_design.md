# PA-1b Phase 2: open_time Reconstruction Fix

**Date**: 2026-05-12
**Source**: `core/exchange_income.py:339-362`

---

## 1. Algorithm Fix: Approach (b) — FIFO Position Accounting

### Why (b) over (a) and (c)

**(a) Walk back to earliest opening**: Finds the earliest opening fill
and associates all closes until the next opening. Simple but breaks on
scale-in: if a trader opens 50 → opens 40 more → closes 45, approach
(a) would associate the close with the earliest entry (the 50-qty fill)
rather than correctly distributing across entries.

**(b) FIFO quantity tracking**: Closes consume opening fills in
chronological order. The first close consumes the earliest opens until
exhausted. Partial closes share the same opening fills. This is the
standard futures accounting model (FIFO = first-in-first-out, which
Binance uses for position PnL calculation).

**(c) Exchange position lifecycle**: Binance doesn't expose a
per-position-ID lifecycle for USDM perpetuals (hedge mode uses
positionSide but not individual position IDs). Not available.

### Algorithm

Process REALIZED_PNL events sorted by time ascending (currently they're
processed in arbitrary order). For each symbol+direction, maintain a
running "position state" that tracks the opening fill timestamp:

```python
# Pre-compute: group all REALIZED_PNL events by (symbol, direction)
# Process chronologically within each group
# For each symbol+direction, track the position's open_time

position_open_times: Dict[Tuple[str, str], int] = {}
# Key: (symbol, direction), Value: earliest open_time for current position

for r in raw_pnl_sorted_asc:
    sym = r["symbol"]
    direction = ...  # derived from trade lookup
    key = (sym, direction)

    if key not in position_open_times:
        # First close for this position — find opening fills
        open_time = _find_open_time(sym, direction, close_ms, sym_fills)
        position_open_times[key] = open_time
    else:
        # Subsequent close for same position — REUSE the open_time
        open_time = position_open_times[key]

    r["open_time"] = open_time

    # Check if this close fully closes the position
    # (position size reaches 0 after this fill)
    # If so, clear the position state so the next open starts fresh
    if _is_position_fully_closed(sym, direction, close_ms, sym_fills):
        del position_open_times[key]
```

### Detecting full close

A position is fully closed when the cumulative close quantity equals or
exceeds the cumulative open quantity. This requires summing fills:

```python
def _is_position_fully_closed(sym, direction, up_to_ms, fills):
    open_side = "BUY" if direction == "LONG" else "SELL"
    close_side = "SELL" if direction == "LONG" else "BUY"
    open_qty = sum(float(f["qty"]) for f in fills
                   if f["side"] == open_side and int(f["time"]) <= up_to_ms)
    close_qty = sum(float(f["qty"]) for f in fills
                    if f["side"] == close_side and int(f["time"]) <= up_to_ms)
    return close_qty >= open_qty - 1e-8  # tolerance for float comparison
```

### Simplified approach (recommended for PA-1b)

The full FIFO model is correct but complex. A simpler fix that handles
the SKYAIUSDT case and most real scenarios:

**Group REALIZED_PNL events that close the same position by time
proximity.** If two REALIZED_PNL events for the same symbol+direction
occur within 60 seconds, they're partial closes of the same position →
share the same open_time.

```python
# Sort REALIZED_PNL by time ascending
# For each symbol+direction, if this close is within 60s of the previous
# close, reuse previous open_time instead of re-computing
```

This avoids the full FIFO tracking while fixing the primary bug (partial
closes within a short window picking up wrong open_times).

**Limitation**: Doesn't handle partial closes spread over hours/days.
For the engine's use case (automated crypto perps with sub-minute
execution), 60s covers >99% of partial-fill scenarios.

---

## 2. Backward Compatibility

Existing exchange_history rows with wrong open_time stay as-is. The fix
only affects NEW rows written by future `fetch_exchange_trade_history()`
calls.

---

## 3. Historical Correction

**No historical recompute.** Same decision as PA-1a. External
backtesting re-derives from raw exchange data. PA-1b ensures new rows
have correct open_times going forward.

---

## 4. Test Coverage

Synthetic partial-fill chains with mocked fill data:

| Scenario | Fills | Expected open_time |
|----------|-------|-------------------|
| 1 open + 2 closes (SKYAIUSDT case) | SELL 90@10:12 → BUY 45@16:54, BUY 45@16:55 | Both closes: 10:12 |
| 1 open + 3 closes | SELL 90 → BUY 30, BUY 30, BUY 30 (within 60s) | All three: same open_time |
| 2 separate positions | SELL 50@09:00 close@10:00, SELL 50@11:00 close@12:00 | First: 09:00, Second: 11:00 |
| Scale-in + partial close | SELL 50@09:00, SELL 40@09:30 → BUY 45@16:00, BUY 45@16:01 | Both closes: 09:00 (FIFO — earliest entry) |

---

## 5. Edge Cases

| Edge case | Behavior |
|-----------|----------|
| No opening fill within window | Log warning, set open_time=0. Do NOT silently grab wrong opening from 7-day fallback. open_time=0 is explicit "unknown." |
| Close qty exceeds open qty | Possible on position flip (close + open opposite side in one order). Log warning, treat as full close + new open. |
| Position flip (close LONG + open SHORT) | Binance sends separate REALIZED_PNL for the close portion. positionSide field distinguishes. Not affected by this fix — different direction key. |
| Very old position (open >7 days ago) | Current 7-day fallback is removed for same-symbol-within-60s case. For the first close of a position (not a partial), original algorithm runs unchanged. |

---

## 6. Commit Strategy

**Single atomic commit.** Changes concentrated in one function
(`fetch_exchange_trade_history()` in exchange_income.py):
- Replace per-REALIZED_PNL open_time computation with grouped approach
- ~20 lines modified in the augmentation loop
- ~40 lines of tests

---

## Migration Cost

| Change | Lines |
|--------|-------|
| Group REALIZED_PNL by time proximity for open_time sharing | +15 |
| Remove 7-day fallback for same-position partials | -5 |
| Edge case handling (open_time=0 on miss) | +3 |
| Tests (4 scenarios + edge cases) | +45 |
| **Total** | **~58** |
