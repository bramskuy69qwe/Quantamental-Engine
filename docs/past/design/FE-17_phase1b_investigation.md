# FE-17 Phase 1B: Deeper Recent-Click Diagnostic

**Date**: 2026-05-13
**Branch**: `fix/FE-17-recent-click-two-step`
**Status**: Root cause identified — HTMX processing race

---

## Why Phase 1 fix was insufficient

Phase 1 identified `_livePrice=0` as ONE blocker (valid, fix correct as
defense). But the persistent two-step behavior has a DIFFERENT root cause:
HTMX doesn't process `requestSubmit()` when called immediately after
`htmx.process()` on a newly created element.

---

## Root Cause: HTMX processing race

`recallHistory()` execution sequence:
1. Line 566: `updateOrderbook(h.ticker)` → replaces `#orderbook-container`
   innerHTML with new HTMX element → calls `htmx.process(c)` (line 454)
2. `htmx.process()` schedules the new element's `hx-trigger="load"`
   request — this is QUEUED but not yet fired
3. Line 571: `requestSubmit()` fires on `#calc-form` — HTMX should
   intercept this via the form's `hx-post` attribute
4. **Race:** HTMX is still initializing from `htmx.process()` — the
   `requestSubmit()` may fire before HTMX has settled its internal state

Result: the form submit either doesn't get intercepted by HTMX (fires as
a native form POST which gets blocked/ignored), or HTMX drops it because
it's processing the orderbook element's `load` trigger.

**Why second click works:** By the second click, HTMX has fully settled.
The orderbook's `hx-trigger="load"` has already fired and completed. The
form's `requestSubmit()` is intercepted normally.

---

## Why FE-2's original 100ms setTimeout worked

The FE-2 bug report said "first click partial state, second works." The
original code had `setTimeout(requestSubmit, 100)` which gave HTMX time
to process the orderbook element. FE-2 removed this delay to fix a
different race (orderbook rendering before calc result). But removing it
introduced THIS race (form submit before HTMX settles).

---

## Fix: requestAnimationFrame instead of setTimeout

Use `requestAnimationFrame` to defer the form submit by exactly one frame
(~16ms). This is enough for HTMX to process the new orderbook element
without the 100ms delay that caused FE-2's partial-state issue.

```javascript
// FE-17: defer submit by one frame to let HTMX settle after htmx.process()
requestAnimationFrame(function(){
    document.getElementById('calc-form').requestSubmit();
});
```

This is a better fix than setTimeout(100) because:
- One frame (~16ms) is enough for HTMX event loop to process
- Not long enough for the orderbook response to arrive and cause partial state (FE-2)
- More semantically correct (defers to next paint, not arbitrary timer)

---

## Complete async dependency graph

| Dependency | Source | Ready on first click? |
|---|---|---|
| `_livePrice` | Seeded from h.entry (line 553) | YES (Phase 1 fix) |
| `market-price` input | Set from h.entry (line 569) | YES (Phase 1 fix) |
| SL value | Set from h.slPrice (line 558) | YES |
| TP value | Set from h.tpPrice (line 557) | YES |
| Orderbook | `updateOrderbook()` triggers HTMX load | NO (async, arrives ~200ms later) |
| OHLCV/ATR | Fetched server-side in `/calculate` endpoint (line 44-45) | N/A (server fetches) |
| Regime | Read from app_state server-side | N/A (server reads) |
| HTMX settled | `htmx.process()` on orderbook element | **NO — this is the blocker** |

---

## LOC: 3 lines (replace direct requestSubmit with requestAnimationFrame)

## Severity: LOW (UX, no data correctness impact)
