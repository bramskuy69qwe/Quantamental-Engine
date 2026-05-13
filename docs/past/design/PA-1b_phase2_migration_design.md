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

### Implementation: Lightweight FIFO (chosen over time-proximity heuristic)

Time-proximity grouping (60s threshold) barely covers the observed 55s
case and fails silently for manual partial closes, TWAP exits, or slower
automation. Lightweight FIFO eliminates the threshold question entirely.

**Precomputation** (before the raw_pnl augmentation loop):

For each symbol, sort all user fills chronologically. For each direction
(LONG/SHORT), maintain a FIFO queue of opening fills. Closing fills
consume from the queue head (oldest first). Record the queue head's
timestamp as the `open_time` for each close fill.

```python
# Precompute: close_fill_id → open_time_ms
close_open_times: Dict[str, int] = {}  # tradeId → open_time

for sym, sym_fills_raw in fills_by_symbol.items():
    sorted_fills = sorted(sym_fills_raw, key=lambda f: int(f.get("time", 0)))
    for direction in ("LONG", "SHORT"):
        open_side  = "BUY" if direction == "LONG" else "SELL"
        close_side = "SELL" if direction == "LONG" else "BUY"
        # FIFO queue: [(time_ms, remaining_qty), ...]
        queue: List[List] = []
        for fill in sorted_fills:
            side = fill.get("side", "")
            qty  = float(fill.get("qty", 0))
            ts   = int(fill.get("time", 0))
            fid  = str(fill.get("id", ""))
            if side == open_side:
                queue.append([ts, qty])
            elif side == close_side:
                # Record open_time = queue head (oldest unconsumed open)
                open_time = queue[0][0] if queue else 0
                close_open_times[fid] = open_time
                # Consume FIFO
                remaining = qty
                while remaining > 1e-8 and queue:
                    if queue[0][1] <= remaining + 1e-8:
                        remaining -= queue[0][1]
                        queue.pop(0)
                    else:
                        queue[0][1] -= remaining
                        remaining = 0
```

**In the raw_pnl loop**: Replace the backward-walk (lines 339-362) with
a simple lookup:

```python
open_time = close_open_times.get(tid, 0)
```

If `open_time == 0` → no opening fill found (log warning, explicit unknown).

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
| No opening fill found (empty queue) | `open_time=0`. Explicit unknown. Log warning. No 7-day fallback — no silent wrong grab. |
| Close qty exceeds open qty | FIFO queue empties mid-close. Remaining close qty has no matching open. `open_time=0` for that portion. Possible on data gaps or position flip. |
| Scale-in (multiple opens before close) | FIFO naturally handles: queue has [open1, open2]. First close consumes from open1 head. `open_time = open1.time`. Correct. |
| Position flip | Binance uses separate positionSide. Different direction key in the FIFO computation. Not affected. |
| Very old position (open >7 days ago) | FIFO queue built from `fetch_user_trades(limit=500)`. If position opened >500 trades ago, opening fill may not be in the fetched set → queue empty → `open_time=0`. Same limitation as current algorithm but explicit instead of wrong. |

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
| FIFO precomputation (before raw_pnl loop) | +30 |
| Replace backward-walk in raw_pnl loop | +3, -24 |
| Edge case handling (open_time=0, logging) | +3 |
| Tests (4 scenarios + edge cases) | +50 |
| **Total** | **~85 LOC** (net +11 code, +50 tests) |
