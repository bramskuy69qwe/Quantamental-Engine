# PA-1a Phase 2: WS Fill Creation Design

**Date**: 2026-05-12
**Scope**: Create fill records from WS TRADE events directly

---

## 1. WS Handler Change

**Location**: `ws_manager.py:_apply_order_update()`, at the
`if execution_type == "TRADE":` block (line 187).

Currently this block only calls `_refresh_positions_after_fill()`.
Add fill creation BEFORE the position refresh:

```python
if execution_type == "TRADE":
    # PA-1a: create fill record from WS event
    await _create_fill_from_ws(order, msg)
    asyncio.create_task(_refresh_positions_after_fill())
```

New function `_create_fill_from_ws(order: NormalizedOrder, raw_msg: dict)`
extracts fill-specific fields from the raw WS message and upserts via
`db.upsert_fill()`.

**Why a new function, not inline**: The fill data requires reading raw
message fields (`o.t`, `o.rp`, `o.l`, `o.L`, `o.N`, `o.n`) that are
NOT on NormalizedOrder. NormalizedOrder captures order-level state; the
fill is a per-execution event with different fields.

---

## 2. Fill Data Shape

WS ORDER_TRADE_UPDATE has fill-specific fields (from Binance docs):
- `o.t` — trade ID (unique per fill)
- `o.l` — last filled quantity (this fill's qty)
- `o.L` — last filled price (this fill's price)
- `o.rp` — realized profit (for closing fills)
- `o.n` — commission amount
- `o.N` — commission asset
- `o.m` — is maker (bool)

Fill record constructed from these:

```python
fill = {
    "account_id":           app_state.active_account_id,
    "exchange_fill_id":     str(o.get("t", "")),      # trade ID — unique key
    "terminal_fill_id":     "",
    "exchange_order_id":    str(o.get("i", "")),       # parent order ID
    "symbol":               o.get("s", ""),
    "side":                 o.get("S", ""),             # BUY/SELL
    "direction":            o.get("ps", ""),            # LONG/SHORT
    "price":                float(o.get("L", 0) or 0), # last fill price
    "quantity":             float(o.get("l", 0) or 0), # last fill qty
    "fee":                  abs(float(o.get("n", 0) or 0)),
    "fee_asset":            o.get("N", "USDT"),
    "exchange_position_id": "",
    "terminal_position_id": "",
    "is_close":             int(float(o.get("rp", 0) or 0) != 0),
    "realized_pnl":         float(o.get("rp", 0) or 0),
    "role":                 "maker" if o.get("m") else "taker",
    "source":               "binance_ws",
    "timestamp_ms":         int(o.get("T", 0)),
}
```

**Comparison to backfill format**: Backfill uses `trade_key` (format:
`{timestamp}_{symbol}_{incomeType}`) as `exchange_fill_id`. WS uses
Binance's native `tradeId` (integer). These are DIFFERENT keys for the
same logical fill — see idempotency section.

---

## 3. Idempotency

**Dedup key**: `UNIQUE(account_id, exchange_fill_id)` on fills table.

**Collision risk**: WS fill uses `tradeId` (e.g., `"120920342"`).
Backfill uses `trade_key` (e.g., `"1778518450000_SKYAIUSDT_REALIZED_PNL"`).
These NEVER collide — different format.

**Result**: The same logical fill can exist TWICE in the fills table
(once from WS, once from backfill) with different `exchange_fill_id`
values. This is acceptable:
- Both have the same symbol, side, price, quantity, timestamp
- Downstream analytics (closed_positions, MFE/MAE) use fills by
  position grouping, not by fill count
- The backfill path groups fills by `(symbol, direction, open_time)`
  for closed_positions creation — duplicates in fills don't create
  duplicate closed_positions

**Alternative** (stricter dedup): Use a composite key that matches
across both paths. Rejected — would require changing backfill's key
format, breaking existing data.

**Recommended approach**: Accept dual records. The WS fill is
authoritative (real-time, complete fields); the backfill fill is
supplementary. No downstream harm from having both.

---

## 4. Order vs Fill Timing

**Sequence**:
1. `parse_order_update(msg)` → NormalizedOrder (already done)
2. **NEW: `_create_fill_from_ws(order, msg)`** → upsert fill to DB
3. `OrderManager.process_order_update()` → persist order state
4. `_refresh_positions_after_fill()` → REST position refresh

Fill creation BEFORE order persistence because:
- The fill is a fact (trade occurred); the order update is a state
  transition. Facts should be recorded first.
- If order persistence fails, the fill should still be recorded (it
  happened on the exchange).
- Fill creation is a simple INSERT; order persistence involves state
  machine validation. Simpler operation first reduces failure-window risk.

---

## 5. Failure Handling

**Independent operations.** Fill creation failure should NOT block order
persistence or position refresh.

```python
if execution_type == "TRADE":
    try:
        await _create_fill_from_ws(order, msg)
    except Exception as e:
        log.warning("WS fill creation failed: %s", e)
    asyncio.create_task(_refresh_positions_after_fill())
```

If fill creation fails (DB error, schema mismatch), the fill will be
recovered on next startup via `backfill_fills_from_exchange_history()`.
The WS fill is a reliability improvement, not the sole path.

---

## 6. Test Coverage

**Tests**:
- Source inspection: `_create_fill_from_ws` exists in ws_manager.py
- Source inspection: `execution_type == "TRADE"` block calls fill creation
- Mock WS message with fill fields → verify fill dict has correct fields
  (trade_id as exchange_fill_id, last_fill_price, last_fill_qty, etc.)
- Verify `is_close` logic: `rp != 0` → is_close=1
- Verify `role`: `m=True` → "maker", `m=False` → "taker"

**Not tested** (would need live DB): actual upsert_fill call. Covered
by existing db_orders tests.

---

## 7. Commit Strategy

**Single atomic commit.** Changes:
- ws_manager.py: add `_create_fill_from_ws()` function + call from
  TRADE handler (~25 lines)
- Tests (~30 lines)
- PHASE2_WORKFLOW.md status update

---

## 8. Backward Compatibility

- Existing fill records (from backfill) unchanged
- Backfill still runs at startup — catches any WS-missed fills
- New WS fills have `source="binance_ws"` to distinguish from
  `source="exchange_history_backfill"`
- Fills table UNIQUE constraint prevents true duplicates (same
  exchange_fill_id); dual records from different sources are acceptable

---

## Open Question: Historical Correction

**Flagged, not answering**: Should we run a one-time migration to:
- Backfill missing fills from exchange_history (bug a)
- Fix wrong open_times in exchange_history (bug b)

Or accept historical corruption and let external backtesting re-derive
from raw exchange data?

**Recommendation preview**: Accept historical as-is. External backtesting
platforms pull directly from exchange API. Correcting historical records
in the engine DB has diminishing value if the primary consumer is moving
external. PA-1a ensures NEW fills are captured correctly going forward.

---

## Migration Cost

| Change | Lines |
|--------|-------|
| `_create_fill_from_ws()` function | +20 |
| Call from TRADE handler | +5 |
| Tests | +30 |
| **Total** | **~55** |
