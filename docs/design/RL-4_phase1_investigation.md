# RL-4 Phase 1: Rate Limit Periodicity Investigation

**Date**: 2026-05-13
**Branch**: `fix/RL-4-rate-limit-periodicity-investigation`
**Status**: Root cause identified — trade-event burst, not periodic scheduler

---

## Finding

The ~8-minute 429 periodicity is NOT a scheduler loop. It's a
**trade-event-triggered concurrent REST burst** — 6 subsystems fire
REST calls simultaneously when a trade closes, exceeding the rate
limit budget in one second. The ~8-min interval was the user's
trading cadence on May 10, not a scheduler frequency.

**Still active post-audit**: 77 events on May 13 alone (most recent
burst at 08:56:08 UTC).

---

## Evidence

### Burst anatomy (identical in every burst)

Every 429 burst contains the same 6 callers firing within the same
second:

| Caller | Source | REST Call |
|--------|--------|-----------|
| `on_trade_closed` | reconciler.py | fetch_user_trades (history) |
| `backfill` | reconciler.py | fetch_price_extremes (MFE/MAE) |
| `reconcile_closed_pos` | reconciler.py | fetch_user_trades (verification) |
| `_on_new_position` | ws_manager.py | fetch_user_trades (entry time) |
| `_refresh_positions_after_fill` | ws_manager.py | fetch_account + fetch_positions |
| `fallback_loop` | ws_manager.py | fetch_account (periodic, happens to coincide) |

12 log lines per burst (6 callers × 2 lines each: RL-1 detection + handler warning).

### May 13 burst timestamps and gaps

```
05:48:11 — burst (12 events)
07:20:47 — burst (92.6 min gap — long idle period)
07:57:23 — burst (36.6 min gap)
08:40:26 — burst (43.0 min gap)
08:46:53 — burst (6.5 min gap)
08:56:08 — burst (9.3 min gap)
```

Gaps are irregular (6-93 min), correlating with user trade timing,
NOT a fixed scheduler interval.

### Historical volume

| Date | 429 Events | Notes |
|------|-----------|-------|
| May 5 | 26 | |
| May 6 | 68 | |
| May 7 | 325 | 418 IP ban event (RL-1/RL-3 investigation) |
| May 8-9 | 39 | Post RL-3 fix |
| May 10 | 105 | RL-4 filed (user observed ~8-min periodicity) |
| May 11 | 250 | Active trading day |
| May 12 | 65 | |
| May 13 | 77 | Current (still happening) |

### OM-5 impact assessment

The OM-5 `_algo_order_sync_loop` (15s cadence) and OM-5b ungated
basic order sync add baseline REST pressure but are NOT in the burst
caller list. They contribute to cumulative weight but don't trigger
the burst. The burst predates OM-5 (present since May 5).

---

## Auto-Resolution Check

**NOT auto-resolved.** The burst pattern is unchanged across all
audit fixes:
- RL-3 (exception coverage): Properly catches 429 at all 6 sites ✓
  but doesn't prevent the burst
- MN-1a (rate-limit event wiring): Records the events in monitoring ✓
  but doesn't throttle
- SR-7 (neutral errors): RateLimitError hierarchy works ✓ but no
  proactive throttling
- OM-5/OM-5b: Add baseline REST calls but don't worsen the burst
  (not in burst callers)

The RL-1 120s pause AFTER a 429 is working — but by then the burst
has already happened.

---

## Root Cause

**Concurrent uncoordinated REST calls on trade events.**

When a fill arrives via WS:
1. `_refresh_positions_after_fill()` fires as `asyncio.create_task()`
2. `_on_new_position()` fires as `asyncio.create_task()`
3. Reconciler `on_trade_closed` event fires via event_bus
4. Reconciler `backfill` runs for the symbol
5. Reconciler `reconcile_closed_pos` runs
6. `fallback_loop` happens to fire at the same moment (periodic)

All 6 are independent async tasks — they run concurrently on the
event loop, each making 1-3 REST calls. Total burst: ~10-15 REST
calls in <1 second.

Binance's per-minute weight budget can absorb this occasionally.
But if the user is actively trading (multiple fills in short
succession), the cumulative weight from recent periodic calls +
the burst exceeds the budget.

---

## Severity

**MEDIUM** (confirmed). Not causing financial harm (RL-1 pause
mechanism prevents escalation to 418 IP ban). But:
- Degrades engine responsiveness for 120s after each burst
- Blocks all REST calls during pause (positions, orders, fills stale)
- Visible in MN-1 monitoring as rate-limit events

---

## Fix Options

### Option A: Serialize trade-event REST calls (~20 LOC)
Add an asyncio.Semaphore(1) or Queue around trade-event-triggered
REST calls. Instead of 6 concurrent tasks, they execute sequentially
with 0.5s pacing (RL-1 pattern). Total burst time: ~3s instead of
<1s. Spreads weight across the budget window.

**Pros**: Simple, addresses root cause directly.
**Cons**: Delays individual callers by 0.5-3s (acceptable — these
are post-trade cleanup, not latency-critical).

### Option B: Rate-limit budget guard (~15 LOC)
Check `app_state.ws_status.is_rate_limited` at the top of each
burst caller. Skip if already rate-limited. This already exists in
`_account_refresh_loop` (schedulers.py:118) but NOT in the 6 burst
callers.

**Pros**: Very simple, prevents cascade within a burst.
**Cons**: Doesn't prevent the initial burst that triggers the 429.

### Option C: RL-2 promotion (proactive weight tracker, ~100-200 LOC)
Track cumulative API weight, throttle BEFORE hitting 429. Full
solution but significant scope expansion.

**Recommendation**: Option A + B combined (~30 LOC total). Serialize
the burst callers AND add rate-limit guards. Defer RL-2 to v2.4.

---

## Files Referenced

| File | Function | Role in Burst |
|------|----------|---------------|
| `core/ws_manager.py` | `_refresh_positions_after_fill()` | Concurrent task on fill |
| `core/ws_manager.py` | `_on_new_position()` | Concurrent task on new position |
| `core/reconciler.py` | `on_trade_closed()` | Event bus handler |
| `core/reconciler.py` | `backfill_all()` / `_process()` | MFE/MAE computation |
| `core/reconciler.py` | `_reconcile_closed_positions()` | Closed position verification |
| `core/ws_manager.py` | `_fallback_loop()` | Periodic REST poll (coincidental overlap) |
