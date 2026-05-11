# SC-2 Phase 1: Ready-State Gating Enumeration

**Date**: 2026-05-12
**Source**: `api/routes_dashboard.py` (/api/ready), `core/schedulers.py`
(_startup_fetch), `core/state.py` (is_initializing), `templates/base.html`

---

## Current Ready-State Behavior

### The flag: `app_state.is_initializing`

| Aspect | Details |
|--------|---------|
| Type | `bool`, default `True` |
| Set to `True` | On `AppState.__init__` (line 250), account switch (routes_accounts:110), reset (state:299) |
| Set to `False` | At END of `_startup_fetch()` (schedulers:348) — after all initial REST fetches, WS startup, regime computation complete |
| Read by | `/api/ready` (routes_dashboard:281), `base.html` template (line 248), helpers.py context (line 109) |

### /api/ready endpoint

```python
@router.get("/api/ready")
async def api_ready():
    return JSONResponse({"ready": not app_state.is_initializing})
```

Returns `{"ready": true}` once `_startup_fetch()` completes. **Bootstrap-only** — once set to `False`, it stays `False` forever (never reverts to `True` during ongoing operation).

### UI consumer

`base.html` renders a full-screen overlay ("Connecting to exchange...") when `is_initializing` is `True`. JavaScript polls `/api/ready` every 600ms and removes the overlay when `ready: true`.

### What it DOESN'T do

- Does NOT check whether fetched data is valid/populated (equity > 0, positions loaded, OHLCV cached)
- Does NOT gate the calculator (calculator runs regardless of ready state)
- Does NOT revert to "not ready" if data goes stale after initial load
- Does NOT consider MN-1 monitoring events (MonitoringService starts after `is_initializing` goes `False`)

---

## Audit's SC-2 Finding

From AUDIT_REPORT.md:
> **SC-2** (ready-state gating): Engine must refuse "ready" when data is missing

From connection_status_ui.md degradation policy:
> **Any group INITIALIZING**: Engine refuses "ready" status (SC-2 fix). Calculator returns ineligible.

The v2.4 gate-readiness design says:
- Engine should refuse "ready" during INITIALIZING mode
- Calculator should return `eligible: false` with reason when data groups are INITIALIZING or OFFLINE
- Exchange account OFFLINE → halt new entries
- Exchange market OFFLINE → halt new entries (ATR/slippage unavailable)
- Regime OFFLINE → use neutral multiplier (don't halt)

---

## SC-2 Scope Assessment

The full v2.4 degradation policy (per connection_status_ui.md) is a
larger system requiring the health surface from MN-1. SC-2's core
scope is narrower:

**Minimum viable SC-2**:
1. `/api/ready` checks more than just `is_initializing` — also checks
   that critical data is actually present
2. Calculator refuses requests when engine is not ready
3. Ready state can REVERT to false if critical data goes away

**What "critical data present" means**:
- Account data loaded (`account_state.total_equity > 0` or at least
  one successful `fetch_account`)
- WS or REST data flowing (not permanently stale)
- At minimum: exchange connection alive

**What's explicitly NOT in SC-2 scope** (deferred to v2.4 gate work):
- Per-source health modes (LIVE/FALLBACK/DEGRADED/OFFLINE)
- Per-group roll-up logic
- Calculator-level gating per venue
- Regime/news offline degradation policy

---

## MN-1 Integration Assessment

**Can SC-2 consume MonitoringEvents?**

Yes, but indirectly. MN-1's MonitoringService runs on the same polling
cycle. SC-2's ready-state check could read `MonitoringService.get_active_events()`
and check for critical-severity events as a gating signal.

However, this creates a coupling: MonitoringService must start BEFORE
ready-state gating can evaluate. Currently MonitoringService starts
after `is_initializing = False`. This ordering would need to change.

**Simpler approach**: SC-2 reads the same underlying signals that MN-1
monitors (WSStatus fields, account state), but directly — not through
MonitoringEvents. This avoids ordering dependency and keeps the two
systems independent.

MN-1 events are for operator alerting. SC-2 is for programmatic gating.
Same signals, different consumers.

---

## Summary

| Aspect | Current | SC-2 Target |
|--------|---------|-------------|
| Ready condition | `not is_initializing` (bootstrap only) | Bootstrap complete AND critical data present |
| Reverts to not-ready | Never | When critical data lost (WS stale + REST stale) |
| Calculator gating | None | Returns ineligible when not ready |
| Data checks | None | Account data, WS/REST liveness |
| /api/ready response | `{"ready": bool}` | `{"ready": bool, "reason": str}` (optional degradation reason) |
