# MP-1 Phase 1: Crash Recovery Risk States Enumeration

**Date**: 2026-05-12
**Source**: `core/state.py` (restore_from_snapshot), `core/db_snapshots.py`,
`core/schedulers.py` (_startup_fetch), `core/database.py` (schema)

---

## Current Crash Recovery Architecture

### What's persisted (account_snapshots table)

Written on every account state change. Contains ALL fields including
`dd_state` and `weekly_pnl_state` — they're in the DB already.

### What's restored on startup (SR-3's restore_from_snapshot)

8 fields restored from last snapshot (state.py:361-379):

| Field | Restored? |
|-------|:---------:|
| total_equity | YES |
| balance_usdt | YES |
| bod_equity | YES |
| sow_equity | YES |
| max_total_equity | YES |
| min_total_equity | YES |
| dd_baseline_equity | YES (derived from bod_equity) |
| drawdown | YES |
| **dd_state** | **NO** |
| **weekly_pnl_state** | **NO** |

### What happens to dd_state / weekly_pnl_state on restart

1. Engine starts → `restore_from_snapshot()` runs → restores 8 fields,
   dd_state and weekly_pnl_state stay at default `"ok"`
2. `_startup_fetch()` runs → fetches account, positions, OHLCV
3. `_recalculate_portfolio()` runs → recomputes dd_state and
   weekly_pnl_state from current equity vs baselines
4. Engine marks `is_initializing = False`

**The gap**: Between steps 1 and 3, dd_state is `"ok"` regardless of
what it was before crash. If the engine crashed at 23:45 with
`dd_state="limit"`, the restarted engine allows trades until step 3
completes (typically 5-15 seconds). During that window, the calculator
doesn't gate on drawdown.

### Why the gap matters for v2.4

v2.4 plans to promote dd_state/weekly_pnl_state from advisory to hard
gates. If the gate resets on crash, a user could restart the engine to
bypass a drawdown limit — defeating the purpose of the gate entirely.

---

## The Fix

**Scope is minimal**: dd_state and weekly_pnl_state are ALREADY in the
`account_snapshots` table. They're ALREADY written on every update.
They're just not READ BACK in `restore_from_snapshot()`.

**What needs to change**:
1. `restore_from_snapshot()` — add 2 fields to the restore set
2. Verify `get_last_account_state()` returns these fields (it does —
   returns `dict(row)` from the full snapshot)

**What does NOT need to change**:
- DB schema (columns already exist)
- Snapshot write path (already writes these fields)
- Recompute logic (still runs — but now starts from restored values
  instead of defaults, so first recompute produces the same result
  or updates appropriately)

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Restored dd_state="limit" prevents trading after restart | Correct behavior — this IS the purpose of the gate |
| Stale gate state from hours-old snapshot | Recompute runs within 5-15s of startup, correcting any stale state |
| dd_state in snapshot doesn't match current equity | Recompute uses live equity + restored baselines; gate state self-corrects |

The restore is a **safety net**, not the source of truth. The recompute
path still runs and can update the state. The restore just eliminates
the window where the default `"ok"` could allow trades that should be
blocked.

---

## Summary

| Aspect | Current | MP-1 Target |
|--------|---------|-------------|
| dd_state on restart | Defaults to "ok" | Restored from last snapshot |
| weekly_pnl_state on restart | Defaults to "ok" | Restored from last snapshot |
| Window of incorrect state | 5-15s (until recompute) | 0s (restored immediately) |
| Schema change | N/A | None needed |
| Write path change | N/A | None needed |
| Code change | restore_from_snapshot() | +2 lines |
