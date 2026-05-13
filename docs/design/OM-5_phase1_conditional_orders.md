# OM-5 Phase 1: Conditional Orders Enumeration

**Date**: 2026-05-13
**Branch**: `fix/OM-5-tpsl-position-matching`
**Status**: Enumeration complete, ready for Phase 4

---

## 1. Binance Conditional Order Endpoint

Binance Futures separates orders into two categories:
- **Basic orders**: LIMIT, MARKET — queried via `/fapi/v1/openOrders`
- **Conditional orders**: STOP_MARKET, TAKE_PROFIT_MARKET, STOP, TAKE_PROFIT,
  TRAILING_STOP_MARKET — queried via `/papi/v1/um/conditional/openOrders`

The engine currently only queries basic orders (`fapiPrivateGetOpenOrders`).
All TP/SL orders are conditional → invisible to the engine.

**Endpoint**: `GET /papi/v1/um/conditional/openOrders`
**Rate limit**: 1 weight (40 weight without symbol filter)
**Auth**: HMAC-SHA256 signed (same as existing FAPI calls)

---

## 2. CCXT Exposure

CCXT (v4.3.20) exposes conditional orders via Portfolio Margin API (PAPI):

```python
# Raw method (returns raw JSON):
self._ex.papiGetUmConditionalOpenOrders()
self._ex.papiGetUmConditionalOpenOrders({"symbol": "BTCUSDT"})

# Unified method (returns parsed Order objects):
self._ex.fetch_open_orders(symbol, params={"stop": True, "portfolioMargin": True})
```

**PAPI access**: May require Portfolio Margin enabled on the Binance account.
If PM is not enabled, the endpoint may return a permission error. Runtime
check needed — try the call, gracefully degrade if it fails.

**No FAPI conditional endpoint exists** — CCXT has zero `fapi` methods for
conditional orders.

---

## 3. Response Data Shape

Conditional order response uses **different field names** from basic orders:

| Basic order field | Conditional order field | Notes |
|-------------------|------------------------|-------|
| `orderId` | `strategyId` | Numeric ID |
| `clientOrderId` | `newClientStrategyId` | User-provided ID |
| `status` | `strategyStatus` | "NEW", "CANCELED", etc. |
| `type` | `strategyType` | "STOP", "TAKE_PROFIT", "STOP_MARKET", "TAKE_PROFIT_MARKET" |
| `origQty` | `origQty` | Same |
| `price` | `price` | Same |
| `stopPrice` | `stopPrice` | Trigger price — same |
| `side` | `side` | Same |
| `positionSide` | `positionSide` | Same ("BOTH"/"LONG"/"SHORT") |
| `reduceOnly` | `reduceOnly` | Same |
| `timeInForce` | `timeInForce` | Same |
| `time` | `bookTime` | Creation timestamp |
| `updateTime` | `updateTime` | Same |

Sample response:
```json
{
    "strategyId": 3645916,
    "newClientStrategyId": "x-xcKtGhcu27f109953d6e4dc0974006",
    "strategyStatus": "NEW",
    "strategyType": "STOP",
    "origQty": "0.010",
    "price": "35000.00",
    "reduceOnly": false,
    "side": "BUY",
    "positionSide": "BOTH",
    "stopPrice": "45000.00",
    "symbol": "BTCUSDT",
    "timeInForce": "GTC",
    "bookTime": 1707112625879,
    "updateTime": 1707112625879,
    "workingType": "CONTRACT_PRICE",
    "priceProtect": false
}
```

---

## 4. Mapping to Engine Order Model

Adapter `fetch_conditional_orders()` maps to `NormalizedOrder`:

```python
NormalizedOrder(
    exchange_order_id = str(o["strategyId"]),
    client_order_id   = o.get("newClientStrategyId", ""),
    symbol            = o["symbol"],
    side              = o["side"],
    order_type        = ORDER_TYPE_FROM_BINANCE.get(o["strategyType"], ...),
    status            = BINANCE_STATUS_MAP.get(o["strategyStatus"], "new"),
    price             = float(o.get("price", 0)),
    stop_price        = float(o.get("stopPrice", 0)),
    quantity          = float(o.get("origQty", 0)),
    filled_qty        = 0.0,  # conditional orders not partially filled
    reduce_only       = bool(o.get("reduceOnly", False)),
    time_in_force     = o.get("timeInForce", ""),
    position_side     = o.get("positionSide", ""),
    created_at_ms     = int(o.get("bookTime", 0)),
    updated_at_ms     = int(o.get("updateTime", 0)),
)
```

`strategyType` values map via existing `ORDER_TYPE_FROM_BINANCE`:
- "STOP" → "stop_loss"
- "STOP_MARKET" → "stop_loss"
- "TAKE_PROFIT" → "take_profit"
- "TAKE_PROFIT_MARKET" → "take_profit"
- "TRAILING_STOP_MARKET" → "trailing_stop"

**All mappings already exist in constants.py** — no new type values needed.

---

## 5. Plugin Gating (OM-5b)

The new `fetch_conditional_orders()` call MUST NOT be plugin-gated.
This is by design — it addresses the OM-5b finding coincidentally.

**Current gating that must be bypassed:**
- `_account_refresh_loop()` (schedulers.py:115): `if platform_bridge.is_connected: continue`
  → The conditional fetch must run OUTSIDE this guard, or the guard must be
  loosened for the conditional fetch specifically.
- `fetch_open_orders_tpsl()` (exchange.py:281): `if platform_bridge.is_connected: return`
  → Same issue.

**Recommended approach**: Add a dedicated `_conditional_order_sync()` call in
the scheduler that runs on 15s cadence regardless of plugin state. This is
cleaner than modifying the existing gated paths.

---

## 6. Display Layer

**No template changes needed.** Current templates render all order types
generically:
- `open_orders_table.html`: displays `order_type`, `stop_price` — works for
  conditional orders using the same type strings
- `dashboard_body.html`: working_orders tab renders all types identically
- Position card TP/SL columns read from `individual_tp_price`/`individual_sl_price`
  which are populated by `enrich_positions_tpsl()`

**Two display paths, both handle conditional orders if in DB:**
1. Dashboard → reads `OrderManager._open_orders` cache → `enrich_positions_tpsl()`
2. History tab → reads DB via `query_open_orders()` with `status IN ('new', 'partially_filled')`

**One consideration**: Conditional orders use `strategyId` as their ID.
The `orders` table uses `(account_id, exchange_order_id)` as unique key.
Must ensure `strategyId` doesn't collide with basic `orderId` values.
Binance uses different ID spaces, so collision is unlikely. As a safety
measure, prefix conditional IDs: `"cond:{strategyId}"`.

---

## 7. OrderManager / process_order_snapshot Handling

`process_order_snapshot()` handles conditional orders correctly if they're
in the order list — it validates transitions, upserts, and marks stale
orders as canceled.

**Important**: Conditional orders must be processed in a SEPARATE snapshot
from basic orders. If mixed, `mark_stale_orders_canceled()` would cancel
basic orders not in the conditional snapshot and vice versa.

**Recommended approach**: Separate method `process_conditional_snapshot()`
that only marks conditional orders stale (filter by ID prefix or source).
Or: merge both snapshots into one call (fetch basic + conditional, combine,
then call `process_order_snapshot()` once).

**Simpler alternative**: Skip `process_order_snapshot()` entirely for
conditional orders. Instead, directly upsert and enrich:
1. Fetch conditional orders via PAPI
2. Upsert via `upsert_order_batch()`
3. Mark conditional orders NOT in the fetch as canceled (separate query
   scoped to conditional IDs only)
4. Call `refresh_cache()` → `enrich_positions_tpsl()`

---

## 8. v2.4 Deferral Notes

**Deferred to v2.4 feature roadmap:**
- WS event coverage for conditional orders (Binance user data stream may
  not fire ORDER_TRADE_UPDATE for conditional order lifecycle — confirmed
  by this investigation)
- Real-time TP/SL updates (currently ~15-30s REST polling latency)
- Conditional order placement from engine (currently view-only)
- Bybit conditional order support (Bybit has a different mechanism)
- Conditional order history integration with analytics

---

## 9. Implementation Summary

| Component | Change | LOC est. |
|-----------|--------|----------|
| `rest_adapter.py` | Add `fetch_conditional_orders()` method | ~25 |
| `protocols.py` | Add `fetch_conditional_orders` to protocol (optional) | ~3 |
| `schedulers.py` | Add `_conditional_order_sync()` on 15s cadence, NOT plugin-gated | ~20 |
| `exchange.py` | Update `fetch_open_orders_tpsl()` to merge conditional results | ~15 |
| Templates | None | 0 |
| DB schema | None (reuses `orders` table) | 0 |
| Tests | Conditional order parsing, enrichment, non-gating | ~40 |

**Total**: ~60-100 LOC + tests. Single commit.

**Trade-off**: 15-30s latency on conditional order visibility. No real-time
updates. Operationally sufficient — user sees TP/SL within one refresh cycle.

---

## Files Referenced

| File | Lines | Role |
|------|-------|------|
| `core/adapters/binance/rest_adapter.py` | 102-133 | `fetch_open_orders()` — basic only |
| `core/adapters/binance/constants.py` | 21-29 | `ORDER_TYPE_FROM_BINANCE` — already has all types |
| `core/adapters/protocols.py` | 130-245 | `ExchangeAdapter` protocol |
| `core/schedulers.py` | 104-165 | `_account_refresh_loop()` — plugin-gated |
| `core/exchange.py` | 271-319 | `fetch_open_orders_tpsl()` — plugin-gated |
| `core/order_manager.py` | 37-86 | `process_order_snapshot()` |
| `core/order_manager.py` | 133-175 | `enrich_positions_tpsl()` |
| `.venv/Lib/site-packages/ccxt/binance.py` | parse_order | Strategy field mapping |
