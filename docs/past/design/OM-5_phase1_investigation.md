# OM-5 Phase 1: TP/SL Visibility Investigation

**Date**: 2026-05-13
**Branch**: `fix/OM-5-tpsl-visibility-diagnostic`
**Status**: Root cause identified

---

## Finding

TP/SL orders (STOP_MARKET, TAKE_PROFIT_MARKET) are correctly fetched,
parsed, persisted, and stored in the `orders` table. They are never
filtered from display. **The bug is a position-matching failure caused
by Binance one-way mode's `positionSide = "BOTH"` not matching
`pos.direction = "LONG"/"SHORT"`.**

---

## Root Cause: `position_side` Matching Bug (Layer b)

### The mismatch

Binance Futures has two position modes:
- **Hedge mode**: `positionSide` is `"LONG"` or `"SHORT"` per order
- **One-way mode** (Binance default): `positionSide` is `"BOTH"` for all orders

Positions are always stored with `direction = "LONG"` or `"SHORT"`
(derived from `positionAmt` sign in `rest_adapter.py:88`).

All three TP/SL matching paths compare `position_side == pos.direction`:
- `"BOTH" == "LONG"` → **FALSE** → TP/SL never linked to position

### Affected code paths (3 sites)

#### Site 1: `enrich_positions_tpsl()` — order_manager.py:148-161

Called by `refresh_cache()` after every order snapshot and WS update.
This is the **persistent** enrichment that survives between renders.

```python
tp_orders = [
    o for o in self._open_orders
    if o.get("symbol") == pos.ticker
    and o.get("position_side") == pos.direction  # ← "BOTH" ≠ "LONG"
    and o.get("order_type") in ("take_profit",)
    and o.get("status") in ("new", "partially_filled")
]
```

#### Site 2: `_apply_order_update()` — ws_manager.py:144-149

Real-time WS handler for TP/SL events. Enriches position immediately.

```python
pos_dir = order.position_side       # "BOTH" in one-way mode
if not pos_dir:                      # "BOTH" is truthy — no fallback!
    pos_dir = "LONG" if order.side == "SELL" else "SHORT"

for pos in app_state.positions:
    if pos.ticker != order.symbol or pos.direction != pos_dir:
        continue  # ← "LONG" ≠ "BOTH" → always skips
```

#### Site 3: `fetch_open_orders_tpsl()` — exchange.py:305-317

REST fallback when plugin is disconnected.

```python
pos_dir = o.position_side           # "BOTH"
if not pos_dir:                      # "BOTH" is truthy — no fallback!
    pos_dir = "LONG" if o.side == "SELL" else "SHORT"
key = (sym, pos_dir)                # ("BTCUSDT", "BOTH")

# ... then:
key = (pos.ticker, pos.direction)   # ("BTCUSDT", "LONG") — no match
```

### Why this explains both manifestations

1. **TP/SL set at order creation not visible**: Order is correctly
   persisted to DB and appears in the open orders table, but
   `enrich_positions_tpsl()` can't match it to a position → position
   card shows `—` for TP/SL prices.

2. **TP/SL edited mid-trade not visible**: WS `AMENDMENT` event is
   received and parsed correctly, but the position match at site 2
   fails → position state not updated.

---

## What works correctly

| Component | Status | Evidence |
|-----------|--------|----------|
| Binance REST fetch | OK | `fetch_open_orders()` returns all types, no filtering |
| WS adapter parse | OK | `parse_order_update()` extracts order_type, stop_price, execution_type |
| Order type mapping | OK | STOP_MARKET → "stop_loss", TAKE_PROFIT_MARKET → "take_profit" (constants.py:21-29) |
| OrderManager persist | OK | Orders stored in DB with correct type, price, status |
| DB queries | OK | `query_open_orders_all()` returns all types, no type filtering |
| Template rendering | OK | Displays all order types; position card shows `individual_tp_price` / `individual_sl_price` |
| State machine | OK | `validate_transition()` handles TP/SL lifecycle correctly |

---

## Secondary finding: Snapshot race (Layer c, latent)

While the primary cause is the matching bug, the investigation also
revealed a latent race condition in `process_order_snapshot()`:

1. WS delivers TP/SL order → persisted to DB
2. REST snapshot (15-30s cadence) may not yet include the new order
3. `mark_stale_orders_canceled()` marks all active orders NOT in
   snapshot as `canceled`
4. TP/SL order gets falsely canceled
5. Subsequent WS updates rejected by `validate_transition()`
   (canceled → new is invalid)

**This race is masked today** because the matching bug prevents TP/SL
from ever displaying. Once the matching bug is fixed, the race may
become visible under specific timing conditions.

**Recommendation**: Address the matching bug first (Phase 2), then
evaluate whether the race needs a grace period or WS-priority
mechanism (separate finding if confirmed in production).

---

## Severity

**HIGH** — confirmed protective-order visibility gap.

- TP/SL orders exist on Binance but engine shows no TP/SL on positions
- User cannot verify protection is in place from engine dashboard
- Risk: user may place duplicate TP/SL (position sizing error) or
  panic-close (opportunity cost)
- No direct financial impact (orders exist on exchange), but
  significant UX/confidence gap for a risk management tool

Stays in **Bucket 4**.

---

## Fix Shape Proposal (Phase 2)

### Core fix: Handle `"BOTH"` in position_side matching

Three sites need the same fix pattern. When `position_side` is
`"BOTH"` (or empty), fall back to side-based inference:

```python
# Proposed helper (shared by all 3 sites)
def _resolve_position_dir(position_side: str, side: str) -> str:
    """Resolve position direction from order fields.

    In hedge mode, position_side is 'LONG'/'SHORT' (use directly).
    In one-way mode, position_side is 'BOTH' — infer from order side:
      SELL order → reduces LONG position (TP/SL for LONG)
      BUY order  → reduces SHORT position (TP/SL for SHORT)
    """
    if position_side and position_side != "BOTH":
        return position_side
    return "LONG" if side == "SELL" else "SHORT"
```

### Sites to fix

1. **ws_manager.py:144-146** — Replace `if not pos_dir:` with helper
2. **order_manager.py:148-161** — Use helper in list comprehension filter
   (orders in DB have `side` column available)
3. **exchange.py:305-307** — Replace `if not pos_dir:` with helper

### Scope

- ~15 lines changed across 3 files + shared helper
- No DB migration needed
- No protocol change needed
- Tests: verify enrichment works with `position_side="BOTH"`

### Alternative: store resolved direction on order

Instead of resolving at match time, resolve at parse time (in adapter
or at DB write time). Pros: simpler matching. Cons: loses original
Binance value, harder to debug.

**Recommendation**: Resolve at match time (preserves raw data).

---

## Files referenced

| File | Lines | Role |
|------|-------|------|
| `core/order_manager.py` | 133-175 | `enrich_positions_tpsl()` — Site 1 |
| `core/ws_manager.py` | 123-184 | `_apply_order_update()` — Site 2 |
| `core/exchange.py` | 270-319 | `fetch_open_orders_tpsl()` — Site 3 |
| `core/adapters/binance/rest_adapter.py` | 86-133 | Position + order parsing |
| `core/adapters/binance/ws_adapter.py` | 108-155 | WS order parsing |
| `core/adapters/binance/constants.py` | 21-29 | Order type mapping |
| `core/adapters/protocols.py` | 31-75 | NormalizedPosition, NormalizedOrder |
| `core/adapters/__init__.py` | 59-81 | `to_position_info()` — direction assignment |
| `core/db_orders.py` | 318-348 | `mark_stale_orders_canceled()` — latent race |
| `core/schedulers.py` | 104-165 | `_account_refresh_loop()` — snapshot cadence |
