# FE-13 Phase 1: Stop Entry Misclassification

**Date**: 2026-05-13
**Branch**: `fix/FE-13-stop-entry-classification`
**Status**: Root cause identified, fix shape clear

---

## Root Cause

`ORDER_TYPE_FROM_BINANCE` (constants.py:24-25) maps `STOP_MARKET → "stop_loss"`
unconditionally. A STOP_MARKET with `reduceOnly=false` that OPENS a position
is misclassified as `"stop_loss"` when it should be `"stop_entry"`.

Same applies to `TAKE_PROFIT_MARKET → "take_profit"` for entry take-profit
orders (less common but same pattern).

The static mapping dict has no access to `reduceOnly`. The fix must happen
at parse time where `reduceOnly` is available.

---

## Downstream Impact Analysis

### Behavioral impact (3 subsystems affected)

**1. enrich_positions_tpsl() — WRONG ENRICHMENT**
- Filters `order_type in ("take_profit",)` and `("stop_loss",)`
- Entry stop order classified as "stop_loss" → matches filter → sets
  phantom SL price on existing position
- Result: position shows wrong SL price; risk calculations use wrong value

**2. _apply_order_update / _apply_algo_update — WRONG ENRICHMENT**
- Checks `order.order_type in _TPSL_TYPES` ({"take_profit", "stop_loss"})
- Entry stop triggers real-time position enrichment
- Result: WS event for entry stop writes wrong SL to position in real-time

**3. _determine_exit_reason() — POTENTIAL MISATTRIBUTION**
- Maps "stop_loss" → "sl_hit" for exit reason
- If entry stop fills and the fill is somehow processed as a close, exit
  reason would be "sl_hit" instead of proper entry attribution
- Risk: LOW — entry fills don't go through exit reason path normally

### Display-only impact (no behavioral consequence)
- Templates show "stop_loss" where "stop_entry" would be more accurate
- Order history, open orders table, execution log all show wrong label
- User confusion but no state corruption

### Not affected
- `_TPSL_TYPES` set: fix automatically excludes entry types (new values
  won't match the set)
- DB index on order_type: new values still indexed correctly
- Analytics aggregation by order_type: entry types segregated naturally

---

## Auto-Resolution Check

**NOT resolved** by any prior fix:
- OM-5: Added conditional order support but uses same mapping
- AD-4: Fixed is_close (side+positionSide) but didn't touch order_type
- The mapping has been wrong since the adapter was written

---

## Fix Shape

**Inline refinement at parse sites** (~15 LOC). After initial mapping from
`ORDER_TYPE_FROM_BINANCE`, check `reduceOnly` and append `_entry` suffix:

```python
# After initial mapping
if order_type in ("stop_loss", "take_profit") and not reduce_only:
    order_type = order_type + "_entry"  # stop_loss_entry, take_profit_entry
```

### Sites to fix (4)

| Site | File | Where |
|------|------|-------|
| REST basic orders | binance/rest_adapter.py `fetch_open_orders()` | After ORDER_TYPE_FROM_BINANCE lookup |
| REST algo orders | binance/rest_adapter.py `fetch_algo_open_orders()` | After ORDER_TYPE_FROM_BINANCE lookup |
| WS basic orders | binance/ws_adapter.py `parse_order_update()` | After ORDER_TYPE_FROM_BINANCE lookup |
| WS algo orders | binance/ws_adapter.py `parse_algo_update()` | After ORDER_TYPE_FROM_BINANCE lookup |

Bybit adapters: same pattern, same 4 sites.

### What stays unchanged
- `_TPSL_TYPES = {"take_profit", "stop_loss"}` — entry types not in set
- `enrich_positions_tpsl()` — filters unchanged, entry types excluded
- `_determine_exit_reason()` — entry fills don't use this path
- Templates — render new type strings naturally ("stop_loss_entry")

### New type values
- `"stop_loss_entry"` — STOP_MARKET that opens a position
- `"take_profit_entry"` — TAKE_PROFIT_MARKET that opens a position

---

## Severity

**MEDIUM** (confirmed). Phantom TP/SL enrichment is the primary behavioral
issue — position shows wrong SL/TP price from entry stop orders. Bounded
to users who place both entry stops and protective stops simultaneously.
Not HIGH because:
- Entry stop orders are uncommon (most users place market/limit entries)
- Phantom enrichment is overwritten on next `refresh_cache()` cycle
- No financial action taken based on phantom values

---

## Recommendation

Skip Phase 2 — fix is straightforward inline check. Proceed directly to
Phase 4 implementation. ~15 LOC + ~10 LOC tests.

---

## Files Referenced

| File | Role |
|------|------|
| `core/adapters/binance/constants.py:24-25` | Source of misclassification |
| `core/adapters/binance/rest_adapter.py` | 2 parse sites (basic + algo) |
| `core/adapters/binance/ws_adapter.py` | 2 parse sites (basic + algo) |
| `core/order_manager.py:168-210` | enrich_positions_tpsl (affected) |
| `core/ws_manager.py:128,242` | _TPSL_TYPES check (not affected by fix) |
