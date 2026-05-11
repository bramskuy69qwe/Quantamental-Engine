# SC-2 Phase 2: Gating Design

**Date**: 2026-05-12
**Depends on**: Phase 1 enumeration, MN-1 (monitoring infrastructure)

---

## 1. Hysteresis on Ready Transitions

### Problem

Without hysteresis, ready state flaps during normal WS reconnects.
WS disconnects typically last 1-5s (reconnect with exponential backoff:
1s, 2s, 4s..., max 60s). REST fallback activates at 30s stale. A
naive "WS stale → not ready" gate would flash the startup overlay
on every reconnect.

### Proposed hysteresis

| Transition | Delay | Rationale |
|-----------|-------|-----------|
| ready → not-ready | **60s** of sustained fault | WS fallback activates at 30s; if REST fallback recovers data, engine is still operational. 60s means both WS AND REST have failed for a full minute. Normal reconnects complete in <10s. |
| not-ready → ready | **10s** of sustained recovery | Once data is flowing again, 10s confirms stability (not a single lucky fetch). Short enough to avoid unnecessary delay. |

Implementation: `_fault_since: Optional[float]` and `_recovery_since: Optional[float]` timestamps on a lightweight `ReadyStateEvaluator` that runs on each MonitoringService cycle (60s).

---

## 2. Recovery vs Degradation Asymmetry

### Signal categories

| Signal | Category | Recovery rule |
|--------|----------|--------------|
| `is_initializing` | **Sticky-once-achieved** | Once `False`, never reverts to `True` via SC-2. Bootstrap is a one-time gate. Account-switch sets it `True` independently (existing behavior). |
| Account data loaded | **Hard fault (bootstrap)** | If `account_state.total_equity == 0` after bootstrap, remains not-ready until a successful `fetch_account()` populates it. No auto-retry by SC-2 — schedulers handle retry. |
| WS/REST data flowing | **Soft fault (auto-recovers)** | Hysteresis applies. WS reconnects, REST fallback activates, data resumes → recovery. SC-2 waits for 60s sustained fault before declaring not-ready. |
| Rate-limited | **Soft fault (time-bounded)** | `rate_limited_until` has a known expiry. Engine auto-recovers when the timer expires. SC-2 does NOT gate on rate-limit alone — data may still be flowing via cached state. Only gates if rate-limit + data staleness co-occur. |

### Evaluation logic

```python
def is_engine_ready(self) -> Tuple[bool, str]:
    """Evaluate ready state. Returns (ready, reason)."""
    # Gate 1: Bootstrap must be complete (sticky)
    if app_state.is_initializing:
        return False, "Engine initializing"

    # Gate 2: Account data must be present
    if app_state.account_state.total_equity <= 0:
        return False, "Account data not loaded (equity=0)"

    # Gate 3: Data must be flowing (hysteresis-protected)
    ws = app_state.ws_status
    stale_s = ws.seconds_since_update
    if stale_s > 60 and not ws.connected and not ws.using_fallback:
        # Both WS and REST have failed for >60s
        return False, f"Exchange data offline ({stale_s:.0f}s stale)"

    return True, ""
```

Gate 3 uses the 60s hysteresis implicitly: `seconds_since_update > 60`
means data hasn't arrived via ANY path (WS or REST fallback) for 60s.
The fallback loop runs every 15s, so if REST is working,
`seconds_since_update` stays <15s even when WS is down.

---

## 3. Degradation Reason Format

### Structured response

```python
{
    "ready": True,           # Backward-compatible boolean
    "reason": "",            # Empty when ready; populated when not
    "details": {             # Optional structured context
        "signal": "ws_stale",
        "duration_seconds": 65,
        "summary": "Exchange data offline (65s stale)"
    }
}
```

When ready: `{"ready": true, "reason": ""}`.
When not ready: `{"ready": false, "reason": "Exchange data offline (65s stale)", "details": {...}}`.

Forward-compatible: old consumers read `ready` (unchanged). New
consumers can parse `reason` and `details`.

---

## 4. Calculator Integration

### What gets gated

**Trade-sizing only.** The calculator has two modes:
1. **Sizing calculation** (full `calculate_position_size` → `eligible` result) — GATED
2. **Display/read** (showing current positions, PnL, mark prices) — NOT GATED

When not ready, `calculate_position_size()` returns early:
```python
if not engine_ready:
    result["eligible"] = False
    result["ineligible_reason"] = f"Engine not ready: {reason}"
    return result
```

### UI communication

The calculator page already shows `ineligible_reason` in the UI when
`eligible` is false. No new UI element needed — the existing
ineligibility display handles this case naturally. The reason text
("Engine not ready: Exchange data offline (65s stale)") appears in the
same place as "Volatility exceeds maximum threshold."

### Dashboard integration

The existing `base.html` startup overlay activates on `is_initializing`.
For SC-2's ongoing not-ready state (post-bootstrap), use the MN-1 banner
approach: a persistent banner at the top of the dashboard showing the
reason. This reuses the `/api/monitoring/events` surface — SC-2 emits a
critical MonitoringEvent when transitioning to not-ready.

---

## 5. Backward Compatibility of /api/ready

### Additive approach

```python
@router.get("/api/ready")
async def api_ready():
    ready, reason = ready_state_evaluator.evaluate()
    response = {"ready": ready}
    if reason:
        response["reason"] = reason
    return JSONResponse(response)
```

- `{"ready": bool}` always present — old consumers unaffected
- `"reason"` added only when not ready — no new field during normal operation
- Old `base.html` overlay JS reads `d.ready` only — continues working

---

## 6. Commit Strategy

### Two commits

**Commit 1**: ReadyStateEvaluator + /api/ready upgrade + tests
- `ReadyStateEvaluator` class with `evaluate() → (bool, str)`
- 3 gates (bootstrap, account data, data staleness)
- Hysteresis tracking (`_fault_since`, `_recovery_since`)
- `/api/ready` response upgraded (additive)
- Tests: each gate individually, hysteresis behavior, backward compat

**Commit 2**: Calculator integration + MonitoringEvent emission
- `calculate_position_size()` early-return when not ready
- MonitoringEvent emission on ready-state transitions
- Tests: calculator returns ineligible when not ready, eligible when ready

### Justification for split

Commit 1 is purely about the state machine + API. Commit 2 adds
behavioral gating (calculator refuses requests). Separating them
allows verifying the state machine is correct before it affects
calculator behavior. If Commit 1's state machine has an edge case,
Commit 2 hasn't shipped yet — calculator still works as before.

---

## Migration Cost Estimate

| Change | Lines |
|--------|-------|
| ReadyStateEvaluator class (evaluate, hysteresis) | +40 |
| /api/ready upgrade | +5 |
| Calculator early-return gate | +8 |
| MonitoringEvent emission on transitions | +10 |
| Tests (Commit 1: 8-10 tests, Commit 2: 4-5 tests) | +80 |
| **Total** | **~145** |
