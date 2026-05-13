# RL-4 Phase 2: Trade-Event Burst Serialization Design

**Date**: 2026-05-13
**Branch**: `fix/RL-4-rate-limit-periodicity-investigation`
**Status**: Design ready for Phase 4 implementation

---

## Design Point 1: Retry Semantics Classification

| # | Caller | Classification | Rationale | On Rate-Limit |
|---|--------|---------------|-----------|---------------|
| 1 | `on_trade_closed` | **SAFE TO SKIP** | `_history_refresh_loop` (5 min) re-fetches trade history. Uncalculated MFE/MAE rows picked up by next event or startup backfill. | Log + skip |
| 2 | `backfill_all` / `_process` | **SAFE TO SKIP** | One-shot at startup, BUT: uncalculated rows remain with `backfill_completed=0` and are picked up by next `on_trade_closed` for active symbols, or next engine restart. MFE/MAE delay is acceptable — not time-critical. | Log + skip |
| 3 | `_reconcile_closed_positions` | **SAFE TO SKIP** | Idempotent. Queries `mfe=0 AND mae=0` rows. Runs again on next `on_position_closed` event and at startup via `backfill_all()`. | Log + skip |
| 4 | `_on_new_position` | **SAFE TO SKIP** | Entry timestamp is a convenience field. WS provides approximate entry time from the fill event. If skipped, `pos.entry_timestamp` stays at WS-derived time — acceptable approximation. Exact exchange timestamp is a refinement, not critical. | Log + skip |
| 5 | `_refresh_positions_after_fill` | **SAFE TO SKIP** | WS `ACCOUNT_UPDATE` already updated positions. REST refresh is confirmation-only. `_account_refresh_loop` (15-30s) covers any drift. | Log + skip |
| 6 | `_fallback_loop` | **SAFE TO SKIP** | Periodic safety net by definition. Already has `is_rate_limited` guard (ws_manager.py:575). | Already guarded |

**Conclusion**: All 6 callers are **SAFE TO SKIP** when rate-limited.
No retry queue needed. The engine's existing periodic loops and
event-driven re-processing cover all skipped work within minutes.

Revised from initial expectation: `backfill` and `_on_new_position`
were expected to NEED RETRY, but:
- `backfill`: uncalculated rows are durable in DB, caught by later events
- `_on_new_position`: WS-derived entry time is acceptable approximation

---

## Design Point 2: Semaphore Sizing

### Budget math

```
Binance weight budget: ~2400 weight / minute = ~40 weight / second
Average REST call weight: 5-10 (fetch_account=5, fetch_positions=5,
  fetch_user_trades=5, fetch_price_extremes=20)
Burst total: 6 callers × 1-3 calls × ~7 avg weight = ~75-150 weight

Without semaphore: 75-150 weight in <1 second → OK in isolation,
  but combined with periodic calls already consuming ~500-800/min,
  burst pushes over 2400/min threshold.

With semaphore(2) + 0.5s inter-call pacing:
  Max 2 concurrent REST calls at any time.
  6 callers × ~1.5 calls avg = ~9 total calls.
  At ~0.5s between pairs: ~4.5 seconds total burst duration.
  Weight rate: ~75-150 over 4.5s = ~17-33 weight/sec → safe margin.
```

### Sizing decision: **Semaphore(2)**

| Size | Burst Duration | Weight/sec | Tradeoff |
|------|---------------|------------|----------|
| 1 | ~9s | ~8-17 | Too slow — post-trade state update delayed |
| **2** | ~4.5s | **17-33** | **Good balance — fast enough, safe margin** |
| 3 | ~3s | ~25-50 | Marginal improvement, higher burst risk |
| 5+ | ~2s | ~40-75 | Doesn't solve the problem |

**Semaphore(2) chosen**: post-trade cleanup completes in ~4-5 seconds
(imperceptible to user), well under budget ceiling.

---

## Implementation Design

### Shared semaphore

```python
# core/exchange.py (or core/rate_limit.py)
_trade_event_sem = asyncio.Semaphore(2)
```

Single semaphore shared by all 6 burst callers. Placement in
`exchange.py` (near `handle_rate_limit_error`) since that module
already owns rate-limit coordination.

### Per-caller changes (Option A + B combined)

Each burst caller wraps its REST calls with:

```python
async with _trade_event_sem:
    if app_state.ws_status.is_rate_limited:
        log.debug("Skipping %s: rate-limited until %s", caller_name, ...)
        return
    # ... existing REST calls ...
```

### Specific sites

| Caller | File:Function | Change |
|--------|---------------|--------|
| `on_trade_closed` | reconciler.py:`on_trade_closed` | Wrap REST section in `async with _trade_event_sem` + guard |
| `backfill`/`_process` | reconciler.py:`_process` | Wrap `fetch_hl_for_trade` call in semaphore + guard |
| `_reconcile_closed_positions` | reconciler.py:`_reconcile_closed_positions` | Wrap REST section + guard |
| `_on_new_position` | ws_manager.py:`_on_new_position` | Wrap `fetch_user_trades` call + guard |
| `_refresh_positions_after_fill` | ws_manager.py:`_refresh_positions_after_fill` | Wrap `fetch_account` + `fetch_positions` + guard |
| `_fallback_loop` | ws_manager.py:`_fallback_loop` | Already has `is_rate_limited` guard. Add semaphore only. |

### LOC estimate

| Component | LOC |
|-----------|-----|
| Semaphore declaration | 2 |
| 6 callers × ~4 lines (import + async with + guard + log) | ~24 |
| Tests | ~20 |
| **Total** | **~46** |

---

## Deferred: RL-4-B

**RL-4-B** (MEDIUM, v2.4 candidate): Trade-event fan-out architectural
review. Six independent subsystems responding to one event suggests
potential for shared data fetching — single REST sweep on trade close,
distribute results to subscribers via event payload. Reduces fan-out
from 6 independent REST calls to 1 coordinated sweep.

---

## Files to Modify

| File | Change |
|------|--------|
| `core/exchange.py` | Declare `_trade_event_sem = asyncio.Semaphore(2)` |
| `core/reconciler.py` | Import semaphore, wrap 3 callers |
| `core/ws_manager.py` | Import semaphore, wrap 3 callers |
| `tests/test_rl4_burst_serialization.py` | New: semaphore + guard tests |
