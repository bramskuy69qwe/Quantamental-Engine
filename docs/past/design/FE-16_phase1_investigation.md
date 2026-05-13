# FE-16 Phase 1: Tab Indicator Flicker

**Date**: 2026-05-13
**Branch**: `fix/FE-16-tab-indicator-flicker-diagnostic`
**Status**: Root cause identified, quick fix (~4 LOC)

---

## Root Cause

`hx-swap="innerHTML"` on `#dashboard-body` (every 1s) replaces the entire
tab bar including button inline styles. HTML always renders with Positions
tab hardcoded blue (lines 82-83). Inline script at bottom re-applies
correct state from `window._dashTab`, but there's one render frame between
DOM insertion (wrong styles) and script execution (correct styles).

User sees: positions tab flashes blue → script corrects to actual tab.
Visible when user is on "Open Orders" or "Order History" tabs.

---

## Fix: Neutral default styles (~4 LOC)

Remove hardcoded blue from the Positions tab button. Set all three tabs
to muted/transparent (neutral). The inline script already runs on every
HTMX swap and activates the correct tab.

Flash changes from "wrong tab active → correct tab active" to
"all neutral → correct tab active" — imperceptible.

---

## Severity: LOW (display-only, no behavioral impact)
