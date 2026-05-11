# FE-9 Phase 1: Equity Flash Crash Investigation

**Date**: 2026-05-12

---

## Root Cause: CONFIRMED — (c) Race condition

### The bug

`data_cache.py:276` in `apply_position_update_incremental()`:
```python
app_state.account_state.total_equity = balances.get("cross_wallet", 0)
```

Sets `total_equity` to Binance's `crossWalletBalance` (field `cw` in WS
ACCOUNT_UPDATE), which is wallet balance WITHOUT unrealized PnL.

The correct equity computation is `balance + unrealized` — which IS done
at `data_cache.py:584` inside `apply_mark_price()`:
```python
acc.total_equity = acc.balance_usdt + acc.total_unrealized
```

### The race

1. WS ACCOUNT_UPDATE arrives → `apply_position_update_incremental()`
   sets `total_equity = cross_wallet` (balance only, ~77.88)
2. Snapshot persisted with wrong equity
3. Next markPriceUpdate (within ~1s) → `apply_mark_price()` recomputes
   `total_equity = balance + unrealized` (correct, ~79.71)
4. MN-1 check #1 reads the 5-min snapshot window, sees 79.71 → 77.88 →
   fires pnl_anomaly with -2.33% drop

### Evidence

DB snapshots at the transition:
```
12:34:27  eq=79.71  bal=77.88  unreal=1.83  (correct: 77.88+1.83=79.71)
12:35:00  eq=77.88  bal=77.88  unreal=1.83  (BUG: eq=bal, ignoring unreal)
12:35:34  eq=77.88  bal=77.88  unreal=1.86  (BUG persists until mark price updates)
```

- 77.88 appears 58 times as `equity_after` in pnl_anomaly events — it's
  the balance_usdt value, not true equity
- 104 total pnl_anomaly events — likely ALL caused by this race

---

## Severity: HIGH

- **Calculator impact**: `calculate_position_size()` uses `total_equity`
  for sizing. A transient 2.3% equity drop produces 2.3% undersized
  positions for ~1s windows. Unlikely to hit during manual calculator
  use, but possible.
- **Monitoring pollution**: 104 false-positive pnl_anomaly events —
  check #1 is effectively useless until this is fixed.
- **Snapshot corruption**: DB stores wrong equity periodically. Affects
  equity curve display, BOD/SOW baselines if they happen to read during
  the race window, crash recovery restore values.

---

## Fix

**One line change**: `data_cache.py:276` should NOT set `total_equity`
from `cross_wallet`. Either:

**Option A** (recommended): Remove the total_equity assignment from the
WS balance handler. Let `apply_mark_price()` be the sole authority for
equity (it already computes `balance + unrealized` correctly). The WS
ACCOUNT_UPDATE sets `balance_usdt` and `total_unrealized` — equity is
derived, not directly assigned.

```python
# Before (line 276):
app_state.account_state.total_equity = balances.get("cross_wallet", 0)
# After:
# total_equity not set here — derived from balance + unrealized in apply_mark_price
```

**Option B**: Compute correctly inline:
```python
app_state.account_state.total_equity = (
    balances.get("wallet_balance", 0) + app_state.account_state.total_unrealized
)
```

Option A is cleaner — single source of truth for equity computation.

---

## Classification

- **Root cause**: (c) race condition — confirmed
- **Severity**: HIGH
- **Bucket**: 4 (stays — confirmed HIGH)
- **pnl_anomaly impact**: 104/104 events likely false positives from this bug
- **Fix scope**: 1-line deletion or replacement in data_cache.py
