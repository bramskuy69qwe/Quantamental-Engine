# FE-17 Phase 1: Calculator Recent-Click Two-Step

**Date**: 2026-05-13
**Branch**: `fix/FE-17-recent-click-two-step`
**Status**: Root cause identified, quick fix (~3 LOC)

---

## Root Cause

`getEffectiveEntry()` (calculator.html:440) only reads `_livePrice` for
market orders — it does NOT read the `market-price` input as fallback.

When `recallHistory()` runs:
1. Line 553: Seeds `_livePrice = h.entry` (IF h.entry > 0)
2. Line 569: Sets `market-price` input to `h.entry`
3. Line 571: `requestSubmit()` fires

If `h.entry` is 0 (e.g., history saved without valid entry) OR
`_livePrice` was already 0 from page load and h.entry is falsy:
- `getEffectiveEntry()` returns `_livePrice || 0` = 0
- `htmx:beforeRequest` handler (line 479) blocks: `entry <= 0`
- Form doesn't submit → "awaiting calculation"
- `schedulePricePoll()` (line 554) started 500ms timer → price fetch completes
- Second click: `_livePrice` now has real value from fetch → submit succeeds

Even when `h.entry` IS valid and `_livePrice` is seeded correctly, there's
an edge case: if `_livePrice` was previously set to a different symbol's
price and `recallHistory()` is called for a new symbol, `_livePrice` might
briefly have the wrong symbol's price. The market-price input fallback
provides a more reliable source since it's explicitly set for the recalled
symbol.

---

## Fix: Add market-price input fallback (~3 LOC)

```javascript
function getEffectiveEntry(){
  if(_orderType==='market'){
    if(_livePrice>0) return _livePrice;
    // FE-17: fallback to market-price input (set by recallHistory/price fetch)
    var mp=parseFloat(document.getElementById('market-price').value);
    return mp>0?mp:0;
  }
  var v=parseFloat(document.getElementById('limit-price').value);
  return v>0?v:(_livePrice||0);
}
```

---

## Severity: LOW (UX, no data correctness impact)
