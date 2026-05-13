# OM-5 Phase 1: Conditional Orders Enumeration (revised)

**Date**: 2026-05-13 (revised from initial incorrect findings)
**Branch**: `fix/OM-5-tpsl-position-matching`
**Status**: Enumeration complete, pending REST endpoint verification

---

## Corrections from Initial Phase 1

Initial Phase 1 incorrectly stated "No FAPI equivalent exists" for
conditional orders. Three corrections:

1. **REST endpoint exists on FAPI** (since 2025-12-09 algo migration):
   `GET /fapi/v1/openAlgoOrders` — available to all USDⓈ-M accounts.

2. **WS event already arrives on existing stream**: `ALGO_UPDATE` fires
   on the same `/ws/<listenKey>` user data stream the engine already
   subscribes to. Events are received but silently dropped — the
   dispatcher only handles `ACCOUNT_UPDATE` and `ORDER_TRADE_UPDATE`.

3. **PAPI is PM-only**: The PAPI conditional endpoints require
   Portfolio Margin. Not applicable to this account.

**Root cause of missed findings**: Phase 1 inferred API paths from
CCXT method names and search snippets rather than fetching Binance
documentation directly. Future Phase 1 work involving external APIs
should fetch and read the documentation pages.

---

## 1. REST Endpoint

**Path**: `GET /fapi/v1/openAlgoOrders`
**Weight**: 1 with symbol filter, 40 without
**Auth**: HMAC-SHA256 signed (standard FAPI auth)

**Parameters**:
- `symbol` (optional): filter by trading pair
- `algoType` (optional): filter by algo type (e.g., "CONDITIONAL")
- `algoId` (optional): filter by specific algo order ID
- `timestamp` (required): standard signed request timestamp

**CCXT access**: Not in CCXT's endpoint list (v4.3.20). Use raw request:
```python
ex.request("openAlgoOrders", "fapiPrivate", "GET", params)
```

---

## 2. REST Response Shape

```json
{
    "algoId": 123456,
    "symbol": "SAGAUSDT",
    "side": "SELL",
    "positionSide": "LONG",
    "totalQty": "100",
    "executedQty": "0",
    "orderType": "STOP_MARKET",
    "algoType": "CONDITIONAL",
    "algoStatus": "NEW",
    "triggerPrice": "0.4500",
    "price": "0",
    "reduceOnly": true,
    "workingType": "CONTRACT_PRICE",
    "selfTradePreventionMode": "NONE",
    "goodTillDate": 0,
    "bookTime": 1747130943000,
    "updateTime": 1747130943000
}
```

**Key field differences from basic orders**:

| Basic order | Algo/conditional order | Notes |
|-------------|----------------------|-------|
| `orderId` | `algoId` | Numeric ID |
| `clientOrderId` | (via `caid` in WS) | REST may use different field |
| `status` | `algoStatus` | NEW, TRIGGERING, TRIGGERED, FINISHED, CANCELED, REJECTED, EXPIRED |
| `type` | `orderType` | STOP_MARKET, TAKE_PROFIT_MARKET, STOP, TAKE_PROFIT, TRAILING_STOP_MARKET |
| `stopPrice` | `triggerPrice` | The activation price |
| `origQty` | `totalQty` | Order quantity |
| `executedQty` | `executedQty` | Same name |
| — | `algoType` | Always "CONDITIONAL" for TP/SL |

---

## 3. Mapping to Engine Order Model

```python
NormalizedOrder(
    exchange_order_id = f"algo:{o['algoId']}",  # prefix to avoid ID collision
    client_order_id   = o.get("clientAlgoId", ""),
    symbol            = o["symbol"],
    side              = o["side"],
    order_type        = ORDER_TYPE_FROM_BINANCE.get(o["orderType"], o["orderType"].lower()),
    status            = ALGO_STATUS_MAP.get(o["algoStatus"], "new"),
    price             = float(o.get("price", 0)),
    stop_price        = float(o.get("triggerPrice", 0)),
    quantity          = float(o.get("totalQty", 0)),
    filled_qty        = float(o.get("executedQty", 0)),
    reduce_only       = bool(o.get("reduceOnly", False)),
    time_in_force     = o.get("timeInForce", "GTC"),
    position_side     = o.get("positionSide", ""),
    created_at_ms     = int(o.get("bookTime", 0)),
    updated_at_ms     = int(o.get("updateTime", 0)),
)
```

**Algo status mapping** (new constant):
```python
ALGO_STATUS_MAP = {
    "NEW":        "new",
    "TRIGGERING": "new",           # still active, about to trigger
    "TRIGGERED":  "partially_filled",  # forwarded to matching engine
    "FINISHED":   "filled",
    "CANCELED":   "canceled",
    "REJECTED":   "rejected",
    "EXPIRED":    "expired",
}
```

**`ORDER_TYPE_FROM_BINANCE` already has all needed types** — no additions.

---

## 4. WS Event: ALGO_UPDATE

**Event type**: `"ALGO_UPDATE"` on existing user data stream
**Already received by engine**: YES — arrives at `_handle_user_event()`
(ws_manager.py:100) but falls through unhandled.

**Confirmed**: `grep -r "ALGO_UPDATE" *.py` → zero matches in codebase.

**Event shape** (inside `msg["o"]`):

| Field | Meaning | Maps to |
|-------|---------|---------|
| `aid` | Algo order ID | `exchange_order_id` (as `algo:{aid}`) |
| `caid` | Client algo ID | `client_order_id` |
| `s` | Symbol | `symbol` |
| `S` | Side | `side` |
| `ps` | Position side | `position_side` |
| `o` | Order type (STOP_MARKET etc.) | `order_type` via ORDER_TYPE_FROM_BINANCE |
| `X` | Algo status | `status` via ALGO_STATUS_MAP |
| `tp` | Trigger price | `stop_price` |
| `p` | Price | `price` |
| `q` | Quantity | `quantity` |
| `R` | Reduce only | `reduce_only` |
| `at` | Algo type ("CONDITIONAL") | — (filter, not stored) |
| `wt` | Working type | — (not needed) |

**Lifecycle events**:
- `X=NEW`: TP/SL placed → enrich position immediately
- `X=CANCELED`: TP/SL removed → clear position TP/SL
- `X=TRIGGERING`: about to fire → no action needed
- `X=TRIGGERED`: forwarded to matching → status update
- `X=FINISHED`: filled → clear TP/SL, position closing handled separately
- `X=EXPIRED`: system canceled → clear TP/SL

---

## 5. Implementation Plan (Phase 4)

### Step 1: Adapter + REST polling (~60 LOC)

- `rest_adapter.py`: Add `fetch_algo_open_orders()` method using
  `self._ex.request("openAlgoOrders", "fapiPrivate", "GET", params)`
- `constants.py`: Add `ALGO_STATUS_MAP`
- `schedulers.py`: Add `_algo_order_sync()` on 15s cadence, NOT
  plugin-gated. Calls `fetch_algo_open_orders()` → processes via
  separate snapshot path → `refresh_cache()` → `enrich_positions_tpsl()`
- Snapshot isolation: Algo orders use `algo:` ID prefix. Stale-cancel
  scoped to `exchange_order_id LIKE 'algo:%'` only.

### Step 2: WS event handler (~40 LOC)

- `ws_manager.py`: Add `elif ev == "ALGO_UPDATE"` branch in
  `_handle_user_event()`. Parse `msg["o"]` into NormalizedOrder
  using algo field names. Apply same TP/SL enrichment as
  `_apply_order_update()`. Persist via `process_order_update()`.
- `ws_adapter.py`: Add `parse_algo_update(msg)` → NormalizedOrder

### Scope

| Component | Change | LOC |
|-----------|--------|-----|
| `rest_adapter.py` | `fetch_algo_open_orders()` | ~25 |
| `constants.py` | `ALGO_STATUS_MAP` | ~10 |
| `ws_adapter.py` | `parse_algo_update()` | ~20 |
| `ws_manager.py` | `ALGO_UPDATE` dispatcher + enrichment | ~25 |
| `schedulers.py` | `_algo_order_sync()` 15s loop | ~20 |
| `order_manager.py` | `process_algo_snapshot()` with scoped stale-cancel | ~20 |
| Templates | None | 0 |
| DB schema | None (reuses `orders` table with `algo:` prefix) | 0 |
| Tests | REST parsing, WS parsing, enrichment, non-gating | ~50 |

**Total**: ~140 LOC + ~50 LOC tests.

### Trade-offs

- REST polling: 15s latency for startup discovery + drift reconciliation
- WS handler: real-time updates for placement, modification, trigger, cancel
- Combined: best-of-both — WS for immediacy, REST for consistency
- `algo:` ID prefix prevents collision with basic order IDs

---

## 6. Plugin Gating (OM-5b)

New fetch paths are NOT plugin-gated:
- `_algo_order_sync()` runs regardless of `platform_bridge.is_connected`
- `ALGO_UPDATE` WS handler runs regardless (WS dispatcher is not gated)
- This addresses OM-5b for conditional/algo orders specifically

OM-5b for basic orders (existing gated paths) remains a separate fix.

---

## 7. v2.4 Deferral Notes (reduced scope)

With both REST and WS integrated in Phase 4, the only v2.4 items are:
- Conditional order PLACEMENT from engine (currently view-only)
- Bybit conditional order support
- Conditional order history integration with analytics
- `ALGO_UPDATE` events during `_user_data_loop` standby (OM-5b basic
  order gating still prevents WS from connecting when plugin is active)

---

## Files Referenced

| File | Lines | Role |
|------|-------|------|
| `core/ws_manager.py` | 100-121 | `_handle_user_event()` — missing ALGO_UPDATE branch |
| `core/adapters/binance/rest_adapter.py` | 102-133 | `fetch_open_orders()` — basic only |
| `core/adapters/binance/constants.py` | 21-29 | `ORDER_TYPE_FROM_BINANCE` — has all types |
| `core/adapters/binance/ws_adapter.py` | 108-142 | `parse_order_update()` — template for algo parser |
| `core/schedulers.py` | 104-165 | `_account_refresh_loop()` — plugin-gated |
| `core/order_manager.py` | 37-86 | `process_order_snapshot()` — needs algo-scoped variant |
| `core/order_manager.py` | 133-175 | `enrich_positions_tpsl()` — works if orders in cache |
