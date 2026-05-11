# SR-6 Phase 1: ws_manager Market Handler Enumeration

**Date**: 2026-05-12
**Source**: `core/ws_manager.py` — market data stream section (lines 350-448)
**Cross-referenced**: `core/adapters/binance/ws_adapter.py`,
`core/adapters/bybit/ws_adapter.py`, `core/adapters/protocols.py`

---

## Current Architecture

### Stream setup (ADAPTER-ROUTED — correct)

| Function | Line | Uses adapter? | Notes |
|----------|------|:---:|-------|
| `_build_market_streams()` | 352 | YES | `ws_adapter.build_market_streams(...)` with fallback |
| `_market_stream_loop()` | 408 | YES | `ws_adapter.build_market_stream_url(streams)` for URL |
| Message unwrap | 431 | YES | `ws_adapter.unwrap_stream_message(msg_outer)` |
| Event type dispatch | 432 | YES | `ws_adapter.get_event_type(msg)` for routing |

### Message handlers (BYPASS ADAPTER — the WS-1/WS-2 finding)

| Handler | Line | Uses adapter? | Raw Binance field names used |
|---------|------|:---:|------------------------------|
| `_apply_mark_price(msg)` | 375 | **NO** | `msg.get("s")`, `msg.get("p")` |
| `_apply_kline(msg)` | 383 | **NO** | `msg.get("k", {})`, `msg.get("s")`, `k["t"]`, `k["o"]`, `k["h"]`, `k["l"]`, `k["c"]`, `k["v"]`, `k.get("x")` |
| `_apply_depth(msg)` | 399 | **NO** | `msg.get("s")`, `msg.get("b", [])`, `msg.get("a", [])` |

### The bypass pattern

The dispatch in `_market_stream_loop()` (line 428-441) correctly uses
the adapter for unwrapping and event-type detection, but then passes
the raw message directly to handler functions that read Binance-specific
field names:

```python
msg = ws_adapter.unwrap_stream_message(msg_outer)  # ← adapter (correct)
ev = ws_adapter.get_event_type(msg)                 # ← adapter (correct)
if ev == "kline":
    _apply_kline(msg)       # ← reads raw Binance fields (BYPASS)
elif ev == "depthUpdate":
    _apply_depth(msg)        # ← reads raw Binance fields (BYPASS)
elif ev == "markPriceUpdate":
    _apply_mark_price(msg)   # ← reads raw Binance fields (BYPASS)
```

### WSAdapter parse methods exist but are unused

Both adapters already implement the parse methods:

| Protocol method | Binance (ws_adapter.py) | Bybit (ws_adapter.py) | Return shape |
|-----------------|:-:|:-:|---|
| `parse_kline(msg)` | L145 | L161 | `{"symbol": str, "candle": [t,o,h,l,c,v]}` or None |
| `parse_mark_price(msg)` | L162 | L188 | `{"symbol": str, "mark_price": float}` or None |
| `parse_depth(msg)` | L170 | L200 | `{"symbol": str, "bids": [[p,q],...], "asks": [[p,q],...]}` or None |

These methods translate exchange-specific field names to a common shape.
They're defined, tested implicitly by SR-7, but **never called by
ws_manager**.

---

## Impact of the bypass

**WS-1 (HARD BLOCKER for Bybit WS)**: Bybit WS messages have completely
different shapes:
- Mark price: `{"topic": "tickers.BTCUSDT", "data": {"symbol": "BTCUSDT", "markPrice": "68000.5"}}`
  — no `"s"` or `"p"` fields
- Kline: `{"topic": "kline.240.BTCUSDT", "data": {"start": ..., "open": ..., "confirm": true}}`
  — no `"k"` nested object, no `"x"` closed flag
- Depth: `{"topic": "orderbook.25.BTCUSDT", "data": {"s": "BTCUSDT", "b": [...], "a": [...]}}`
  — similar shape but nested differently

`_apply_kline(msg)` would silently produce no output on Bybit messages
(no `"k"` key → empty dict → `k.get("x")` returns None → returns early).
Market data goes dark.

**WS-2**: `execution_type` read in `_apply_order_update` at line 138:
`msg.get("o", {}).get("x", "")` — reads Binance's `o.x` execution type
field. Already mitigated by the `parse_order_update()` adapter call at
line 137, but the raw field read at line 138 is still Binance-specific.

---

## Consumer dependency map

| Handler | Writes to | Downstream consumers |
|---------|-----------|---------------------|
| `_apply_mark_price` | `app_state._data_cache.apply_mark_price(sym, mark)` | Dashboard mark price display, unrealized PnL calculation, session MFE/MAE |
| `_apply_kline` | `app_state._data_cache.apply_kline(sym, candle)` | ATR calculation, OHLCV cache for sizing |
| `_apply_depth` | `app_state._data_cache.apply_depth(sym, bids, asks)` | Calculator orderbook display, VWAP/slippage estimation |

All three write to DataCache methods that accept exchange-agnostic
shapes (symbol + data). The adapters' parse methods already produce
these shapes. The fix is pure wiring.

---

## WS-2: execution_type raw read

**Line 138**: `execution_type = msg.get("o", {}).get("x", "")`

This reads the raw Binance WS message to determine `execution_type`
(NEW, TRADE, CANCELED, etc.). The adapter's `parse_order_update()` at
line 137 returns a `NormalizedOrder` but doesn't expose execution_type
as a field (it maps to status instead).

**Options**:
(a) Add `execution_type` to NormalizedOrder or as a separate parse result
(b) Infer from NormalizedOrder.status (filled → TRADE, canceled → CANCELED)
(c) Add a dedicated `parse_execution_type(msg) → str` method to WSAdapter

---

## Summary

| Item | Status | Fix complexity |
|------|--------|---------------|
| Stream setup (build, URL, unwrap, event type) | ADAPTER-ROUTED | No change needed |
| `_apply_mark_price` | BYPASSES ADAPTER | LOW — 3 lines: call `ws_adapter.parse_mark_price(msg)`, use result |
| `_apply_kline` | BYPASSES ADAPTER | LOW — 5 lines: call `ws_adapter.parse_kline(msg)`, use result |
| `_apply_depth` | BYPASSES ADAPTER | LOW — 3 lines: call `ws_adapter.parse_depth(msg)`, use result |
| WS-2 `execution_type` | RAW BINANCE FIELD | MEDIUM — needs design decision on where execution_type lives |
