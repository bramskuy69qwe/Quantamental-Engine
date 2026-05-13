# PA-1 Phase 1: Partial-Fill Aggregation Investigation

**Date**: 2026-05-12
**Case**: SKYAIUSDT 2026-05-11, 1 SHORT position closed in 2 partial fills

---

## Ground Truth (Binance)

- Entry: SELL 90 @ 0.431650, 10:12:16 UTC
- Close 1: BUY 45 @ 0.373820, 16:54:10 UTC, PnL +2.60
- Close 2: BUY 45 @ 0.376100, 16:55:05 UTC, PnL +2.50
- Total: 1 position, 2 close fills, +5.10 PnL

---

## Manifestation (a): Missing Fill

**fills table**: Only close 1 (fid=120920342 @16:54:10 qty=45) exists.
Close 2 (@16:55:05 qty=45) has NO fill entry.

**orders table**: BOTH close orders exist (oid=1303936892 @16:54:10,
oid=1303983335 @16:55:05). Both status=filled.

**Root cause**: The WS ORDER_TRADE_UPDATE handler at `_apply_order_update()`
triggers `_refresh_positions_after_fill()` on `execution_type == "TRADE"`.
This calls `fetch_positions(force=True)`. If the first partial close
triggers a position refresh that sees qty drop from 90→45, and the second
partial close arrives ~55s later, the fill recording depends on the
`backfill_fills_from_exchange_history` path (which runs at startup, not
per-event).

The WS handler persists the ORDER (via OrderManager), but fills are
NOT created from WS events directly — they come from:
1. Quantower plugin (platform_bridge fill events) — not active
2. `backfill_fills_from_exchange_history` at startup — batch process

There is no per-WS-event fill creation. The second close fill simply
wasn't picked up by the last startup backfill if it occurred after the
engine's last `fetch_exchange_trade_history()` call.

**This is NOT a WS event miss** — it's a **fill recording gap**. WS
events update orders and trigger position refreshes, but don't create
fill records. Fills come from periodic batch reconciliation.

---

## Manifestation (b): Position Split (open_time mismatch)

**exchange_history** shows 2 REALIZED_PNL rows for the main trade:

| Close time | Income | Qty | open_time (reconstructed) |
|-----------|--------|-----|--------------------------|
| 16:54:10 | +2.60 | 45 | **10:12:16** (correct — the 90-qty entry) |
| 16:55:05 | +2.50 | 45 | **09:45:36** (WRONG — this is the earlier 35-qty trade's entry) |

**Root cause**: `fetch_exchange_trade_history()` in exchange_income.py
reconstructs `open_time` per REALIZED_PNL event by walking user trades
backward. The logic (lines 340-363):

1. Find the most recent closing-direction fill before this close →
   this marks the "previous leg end"
2. Find opening-direction fills between "previous leg end" and close

For the SECOND partial close (16:55:05), the "most recent closing fill
before this close" IS the first partial close (16:54:10). The logic
treats the first partial as the boundary between legs. So it looks for
opening fills between 16:54:10 and 16:55:05 — finds NONE in that 55s
window. Falls back to the 7-day cap, which picks up the 09:45:36 entry
from the earlier unrelated 35-qty trade.

**This is a design limitation in the open_time reconstruction algorithm.**
Partial closes share the same opening fills as the original position,
but the backward-walk algorithm doesn't know they're partial — it treats
each REALIZED_PNL as a separate round-trip.

---

## Root Cause Summary

| Manifestation | Root cause | Shared? |
|---------------|-----------|---------|
| (a) Missing fill | Fills only created via batch backfill, not per-WS-event. Second partial close occurred after last backfill. | Independent |
| (b) Position split | open_time reconstruction treats each REALIZED_PNL as separate trade; partial closes break the leg-boundary detection. | Independent |

**Two distinct bugs, not one.** Both relate to partial fills but in
different subsystems (fill recording vs trade reconstruction).

---

## Severity: HIGH (confirmed)

- (a) distorts trade history completeness — missing fills mean missing
  commission data, incomplete audit trail
- (b) distorts position count (1 position → 2 in exchange_history),
  corrupts open_time for MFE/MAE calculation (wrong time window →
  wrong extremes), distorts win rate and per-trade analytics

---

## Fix Shape

**Two independent fixes, recommend separate commits:**

**Fix (a)**: Create fill records from WS TRADE events directly (not
just orders). When `execution_type == "TRADE"`, extract fill data from
the WS message and upsert into fills table. This eliminates dependency
on periodic batch backfill for fill completeness.

**Fix (b)**: Improve open_time reconstruction to handle partial closes.
Options:
- Track position-level open_time (set once on entry, not per
  REALIZED_PNL event) — simplest
- Detect partial closes (qty < total position qty) and reuse the
  previous partial's open_time
- Group REALIZED_PNL events by close-time proximity (within 60s of
  each other = same position close)

Fix (b) is the more architecturally significant change; fix (a) is a
reliability improvement.

---

## Cross-references

- **SR-1**: OrderManager handles order state transitions; doesn't
  address fill creation from WS events
- **SR-6 WS-2**: `execution_type` field is correctly populated but
  only used for TP/SL enrichment and position refresh trigger, not
  fill creation
- **Reconciler**: Processes exchange_history rows for MFE/MAE; doesn't
  create or fix position records
- **backfill_fills_from_exchange_history**: The batch fill creator;
  works on exchange_history rows which already have the split problem
