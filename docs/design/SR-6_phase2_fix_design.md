# SR-6 Phase 2: Fix Design

**Date**: 2026-05-12
**Scope**: WS-1 (3 handler wiring) + WS-2 (execution_type)

---

## WS-1: Wire 3 market handlers through adapter parse methods

### Shape verification

Adapter parse methods return dicts. DataCache methods accept primitives.
Shapes align perfectly:

| Adapter method | Returns | DataCache method | Accepts |
|---------------|---------|-----------------|---------|
| `parse_mark_price(msg)` | `{"symbol": str, "mark_price": float}` | `apply_mark_price(symbol, mark)` | `(str, float)` |
| `parse_kline(msg)` | `{"symbol": str, "candle": [t,o,h,l,c,v]}` | `apply_kline(symbol, candle)` | `(str, list)` |
| `parse_depth(msg)` | `{"symbol": str, "bids": [[p,q],...], "asks": [[p,q],...]}` | `apply_depth(symbol, bids, asks)` | `(str, list, list)` |

All three adapter methods return `None` when the message is invalid or
incomplete (e.g., open kline not yet closed). The handler must check for
`None` before calling DataCache.

### Call pattern (post-fix)

In `_market_stream_loop()`, the dispatch block becomes:

```python
msg = ws_adapter.unwrap_stream_message(msg_outer)
ev = ws_adapter.get_event_type(msg)
if ev == "kline":
    parsed = ws_adapter.parse_kline(msg)
    if parsed:
        app_state._data_cache.apply_kline(parsed["symbol"], parsed["candle"])
elif ev == "depthUpdate":
    parsed = ws_adapter.parse_depth(msg)
    if parsed:
        app_state._data_cache.apply_depth(parsed["symbol"], parsed["bids"], parsed["asks"])
elif ev == "markPriceUpdate":
    parsed = ws_adapter.parse_mark_price(msg)
    if parsed:
        app_state._data_cache.apply_mark_price(parsed["symbol"], parsed["mark_price"])
```

The standalone `_apply_kline`, `_apply_mark_price`, `_apply_depth`
functions are **deleted** — their logic was only "parse raw Binance
fields + write to cache." The adapter parse methods replace the parsing;
the DataCache methods replace the cache write. No intermediate function
needed.

**Silent-failure prevention**: Bybit messages with no matching raw keys
would have produced empty dicts → no-op handlers → invisible market data
loss. Post-fix, the adapter parse method is the only path. If a Bybit
message arrives, `BybitWSAdapter.parse_kline(msg)` knows how to extract
`msg["data"]["confirm"]` etc. If the adapter returns `None` (unknown
format), the handler explicitly skips. No silent degradation.

---

## WS-2: execution_type on NormalizedOrder

### Current usage

`execution_type` is read from raw Binance WS at ws_manager.py:138:
```python
execution_type = msg.get("o", {}).get("x", "")
```

Used at 3 sites:
- L152: `if execution_type in ("NEW", "AMENDMENT")` → apply TP/SL prices
- L171: `elif execution_type in ("CANCELED", "EXPIRED")` → clear TP/SL
- L187: `if execution_type == "TRADE"` → trigger position refresh

### Options

**Option A — Add `execution_type` to NormalizedOrder** (RECOMMENDED):
```python
@dataclass
class NormalizedOrder:
    ...
    execution_type: Optional[str] = None  # "NEW" | "TRADE" | "CANCELED" | "AMENDMENT" | "EXPIRED"
```

Adapters set from exchange-specific signals:
- Binance: `msg["o"]["x"]` (already parsed in `parse_order_update`)
- Bybit: inferred from topic + order state changes

Trade-offs:
- Pro: Same pattern as reduce_only, position_side, parent_order_id
  (Optional field, adapter-populated). Consumer reads a clean field.
- Pro: `_apply_order_update` no longer reads raw `msg` at all — all
  data comes from the NormalizedOrder object.
- Con: `execution_type` is a Binance concept name. Bybit calls it
  differently (no direct equivalent — order lifecycle events are
  structured differently). The field becomes "execution lifecycle
  phase" abstracted across exchanges.
- Mitigation: values are simple enough to be universal (NEW, TRADE,
  CANCELED, EXPIRED map to any exchange's order lifecycle).

**Option B — Infer from NormalizedOrder.status**:
Map status values: "filled" → TRADE, "canceled" → CANCELED, "expired"
→ EXPIRED, "new" → NEW.

Trade-offs:
- Pro: No new field needed.
- Con: Lossy — can't distinguish AMENDMENT from NEW (both produce
  status="new"). AMENDMENT is needed for TP/SL modification detection.
  Breaks the TP/SL enrichment path.
- **Rejected**: AMENDMENT is critical for TP/SL mid-trade edits (OM-5).

**Option C — Dedicated `parse_execution_type(msg)` on WSAdapter**:

Trade-offs:
- Pro: Doesn't pollute NormalizedOrder.
- Con: Requires passing both `msg` (raw) AND `order` (parsed) to the
  handler. Defeats the purpose of adapter abstraction (handler still
  needs raw message).
- **Rejected**: Handler should only see normalized objects.

### Recommendation: Option A

Add `execution_type: Optional[str] = None` to NormalizedOrder. Both
adapters populate in `parse_order_update()`. ws_manager reads from the
NormalizedOrder object instead of raw message.

---

## Atomic vs split commit

**Recommendation: single atomic commit.**

Justification:
- WS-1 and WS-2 touch the same function (`_market_stream_loop` dispatch
  and `_apply_order_update`). Splitting creates intermediate states where
  half the handlers are adapter-routed and half are raw — inconsistent.
- Total scope is ~30 lines changed (11 for WS-1 handler wiring, 5 for
  WS-2 execution_type field + adapter, 10 for deleting the standalone
  handler functions, 5 for tests).
- Both fixes serve the same goal: eliminate raw Binance field access
  from ws_manager.py. Landing together ensures the file is clean at
  commit boundary.

---

## Migration cost

| Change | Lines |
|--------|-------|
| Delete `_apply_mark_price()` | -6 |
| Delete `_apply_kline()` | -14 |
| Delete `_apply_depth()` | -7 |
| Rewrite dispatch in `_market_stream_loop()` | +12 |
| Add `execution_type` to NormalizedOrder | +1 |
| Binance `parse_order_update`: set execution_type | +1 |
| Bybit `parse_order_update`: set execution_type | +3 |
| `_apply_order_update`: read from order instead of msg | -1, +1 |
| **Net** | **-10** |
