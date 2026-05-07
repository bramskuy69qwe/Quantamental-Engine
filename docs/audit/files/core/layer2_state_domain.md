# Per-File Findings: Layer 2 — State + Core Domain

**Files**: `state.py`, `data_cache.py`, `order_manager.py`, `order_state.py`, `event_bus.py`, `database.py`, `db_router.py`  
**Pre-flagged**: State map findings F1-F10, boundary map R2.  
**Focus**: State ownership (confirm/locate by line), PLUS layering violations, error handling, vendor leakage, naming, SRP.

---

## `core/order_manager.py` (406 lines)

### OM-1: WS order path bypasses state machine validation

**File**: `core/ws_manager.py:193-220` (caller), `core/order_manager.py` (bypassed), `core/db_orders.py:57` (ON CONFLICT)  
**Severity**: **CRITICAL**  
**Category**: 1 (financial correctness) + 2 (state ownership)

**Observation**: Two distinct DB write paths exist for orders:

| Path | Caller | State machine | Status guard |
|------|--------|---------------|--------------|
| A: `OrderManager.process_order_snapshot` | platform_bridge, schedulers REST poll | `validate_transition()` checked (line 56-62) | Yes — invalid transitions skipped |
| B: `db.upsert_order_batch` directly | `ws_manager._apply_order_update:220` | **NOT checked** | None — status overwritten unconditionally |

Path B is the WS ORDER_TRADE_UPDATE handler. The comment at ws_manager:191 even documents the intent: "Use upsert_order_batch (not process_order_snapshot which cancels missing orders)." But this also skips the state machine validation entirely.

**The DB layer has no guard**: `upsert_order_batch` SQL at `db_orders.py:57` uses `ON CONFLICT ... DO UPDATE SET status = excluded.status` — unconditional overwrite. A stale or replayed WS message with status "new" for an order already "filled" in the DB would regress it to "new". The state machine exists in OrderManager but is bypassed on the most frequent write path.

**Design intent (confirmed by owner)**: The WS bypass of `process_order_snapshot` was intentional — WS single-order updates should NOT run the cancel-stale logic (which is snapshot-only). But the bypass of `validate_transition` was unintentional (gap).

**Structural redesign candidate (OM-R1)**: Split OrderManager into two entry points:
- `process_order_snapshot(account_id, orders)` — validates + cancels stale (current behavior, snapshot path only)
- `process_order_update(account_id, order)` — validates only, no stale cancel (new method, WS path)
Both share the same `_validate_and_upsert()` inner method and the same DB writer. WS routes through the single-update method instead of bypassing OrderManager entirely.

**Blast radius**: `order_manager.py` (add `process_order_update` method), `ws_manager.py:190-227` (call `om.process_order_update()` instead of `db.upsert_order_batch`), `schedulers.py:128-156` (call `om.process_order_update()` for REST-polled orders), `db_orders.py:57-71` (add timestamp guard to `ON CONFLICT` as defense-in-depth).

---

### OM-2: TOCTOU between snapshot fetch and stale-cancel

**File**: `core/order_manager.py:48-83`  
**Severity**: HIGH  
**Category**: 2 (state ownership) + 5 (async/concurrency)  
**Cross-ref**: State map F5 (_open_orders 3 writers)

**Observation**: `process_order_snapshot` has a multi-step sequence:
1. Fetch existing active orders from DB (line 48)
2. Validate transitions in memory (lines 52-63)
3. Upsert valid orders to DB (line 68)
4. Mark orders NOT in snapshot as canceled (lines 73-83)
5. Rebuild _open_orders cache from DB (line 86)

Between step 1 and step 4, a WS ORDER_TRADE_UPDATE can arrive and write a new order to the DB via path B (OM-1). Step 4 then marks this fresh WS order as canceled because it wasn't in the (now-stale) platform snapshot.

**Concrete scenario**: Platform snapshot captured at T=0 contains orders [A, B]. At T=50ms, WS delivers new order C. At T=100ms, `mark_stale_orders_canceled` runs with `active_ids = [A, B]` → order C is falsely canceled in DB.

**Suggested fix**: Add a `last_seen_ms > snapshot_ts_ms` guard to the cancel query, or acquire a logical lock around the snapshot processing to prevent interleaving.

**Blast radius**: `db_orders.py:316-346` (add timestamp guard), `order_manager.py:73-83` (pass snapshot timestamp).

---

### OM-3: `_open_orders` private attribute directly assigned from ws_manager and schedulers

**File**: `core/ws_manager.py:223`, `core/schedulers.py:456`  
**Severity**: **HIGH**  
**Category**: 2 (state ownership) + 8 (SRP)  
**Cross-ref**: State map F5

**Observation**: `ws_manager._apply_order_update:223` does `om._open_orders = await db.query_open_orders_all(...)` — reaching directly into OrderManager's private attribute. Similarly `schedulers._order_staleness_loop:456`. Same family as OM-1: OrderManager is designed as single owner of order state, but 2 external modules write its private field directly.

**Financial path**: `_open_orders` → `enrich_positions_tpsl` → TP/SL display on dashboard → trader sees stale/wrong TP/SL → may place duplicate stops or miss existing ones. Additionally, if OrderManager ever adds validation, events, or filtering to cache updates, these bypass paths would miss it — silently creating a second class of cache state.

**Severity justification**: HIGH — same ownership violation pattern as OM-1. The field feeds TP/SL display that traders use for risk decisions. The bypass prevents OrderManager from ever adding post-update logic without hunting down all writers.

**Suggested fix**: Add `OrderManager.refresh_cache(account_id)` method. The OM-R1 redesign (splitting into `process_order_update` + `process_order_snapshot`) should include cache refresh as part of both entry points, eliminating the need for external callers to touch `_open_orders` directly.

**Blast radius**: `ws_manager.py:223`, `schedulers.py:456` (2 call sites → call `om.refresh_cache()` instead).

---

### OM-4: `allow_cancel_all` mass-cancel triggered by orders with only terminal IDs

**File**: `core/order_manager.py:73-80`  
**Severity**: **HIGH**  
**Category**: 7 (error handling) + 1 (financial correctness)

**Observation**: `active_ids` is built from `exchange_order_id` only (line 74): `[o["exchange_order_id"] for o in orders if o.get("exchange_order_id")]`. If the Quantower plugin sends orders that only have `terminal_order_id` (with empty `exchange_order_id` — which happens for pending orders before exchange confirmation), `active_ids` is empty.

The guard at line 80: `allow_cancel_all = len(orders) > 0 and not active_ids` evaluates to `True` (orders exist, but no exchange IDs). This triggers `mark_stale_orders_canceled` with `allow_cancel_all=True` → SQL: `UPDATE orders SET status='canceled' WHERE account_id=? AND status IN ('new','partially_filled')` → **ALL active orders for this account are marked canceled in the DB.**

**Concrete failure chain**:
1. Plugin sends order snapshot with 5 orders, all with `terminal_order_id` only (exchange hasn't acked yet)
2. `active_ids = []`, `allow_cancel_all = True`
3. All 12 existing active orders in DB (including TP/SL) falsely marked canceled
4. `_open_orders` cache rebuilt from DB → empty
5. `enrich_positions_tpsl` runs → all positions show no TP/SL on dashboard
6. Trader sees "no stops" → may place duplicate TP/SL on exchange → when price hits, both fire → 2× intended close quantity
7. OR: Trader sees "no stops" but trusts the dashboard → doesn't place replacement stops → unprotected position

**Capital exposure**: Indirect — exchange-side orders are NOT actually canceled (engine is monitoring-only). But the trader's information is wrong. The duplicate-stop scenario (step 6) creates real capital exposure: double the intended exit quantity could flip a position or cause unintended fills.

**Severity justification**: HIGH — wrong TP/SL display on a dashboard the trader relies on for risk decisions. Not CRITICAL because no automated order action occurs, but the human-decision chain has real capital exposure.

**Suggested fix**: Include both ID types: `active_ids = [o.get("exchange_order_id") or o.get("terminal_order_id") for o in orders if o.get("exchange_order_id") or o.get("terminal_order_id")]`. Or: disable `allow_cancel_all` entirely — stale orders should be caught by the `mark_stale_orders` time-based cleanup instead.

**Blast radius**: `order_manager.py:73-80` only.

---

### OM-5: `enrich_positions_tpsl` TP/SL selection logic may pick wrong order

**File**: `core/order_manager.py:108-135`  
**Severity**: MEDIUM  
**Category**: 1 (financial correctness — minor)

**Observation**: When multiple TP or SL orders exist for the same position, `enrich_positions_tpsl` picks "closest to mark price" (line 124, 130): `min(tp_orders, key=lambda o: abs(o.get("stop_price", 0) - mark))`. This selects the TP that would trigger next, which is reasonable. But if `mark` is 0 (no valid price — line 101-105), it falls through to setting TP/SL to 0.0 for that position. The guard is correct, but positions without a mark price get no TP/SL displayed even when TP/SL orders exist on the exchange.

**Suggested fix**: Fall back to entry price when mark price is unavailable: `mark = pos.fair_price or pos.average or 0`. Currently line 100 does exactly this — but the `if not mark:` guard on line 101 still skips when both are 0. Consider using the TP/SL order closest to entry price as fallback when mark is unavailable.

**Blast radius**: `order_manager.py:100-105` only.

---

## `core/state.py` (428 lines)

### ST-1: `_lock` allocated but never acquired

**File**: `core/state.py:213`  
**Severity**: LOW  
**Category**: 12 (dead code)

**Observation**: `self._lock = asyncio.Lock()` is the only reference. No code path in the codebase acquires `app_state._lock`. The DataCache docstring (data_cache.py:86) references a lock ordering constraint "AppState._lock is being phased out," confirming it's vestigial.

**Suggested fix**: Remove the lock. If lock ordering documentation references it, update to note removal.

**Blast radius**: `state.py:213` (delete), `data_cache.py:86` (update comment).

---

### ST-2: `positions` setter allows bypass with warning only — currently dead but a maintenance trap

**File**: `core/state.py:259-265`  
**Severity**: MEDIUM  
**Category**: 4 (hidden state)

**Observation**: The `positions` setter logs a warning ("Direct write bypasses DataCache") but still writes to `_positions_legacy`. Verified: **no current code calls `app_state.positions = ...`** (grep confirmed zero matches). The setter is a dead path.

However, the behavior is subtly broken even if called: writes go to `_positions_legacy`, but the getter (line 254) returns `DataCache._positions` when DataCache is active. So a caller writing `app_state.positions = new_list` would see their data silently discarded on the next read — the getter returns the DataCache version, not the just-written legacy list. A log warning fires, but the actual mutation is invisible.

**Financial path if ever triggered**: Risk engine reads `app_state.positions` (which returns DataCache's list) for sizing. If a caller writes to the setter expecting their positions to be visible, the risk engine would see stale DataCache positions instead. But since no current caller triggers this, the risk is future-only.

**Severity justification**: MEDIUM — dead path, no current callers, but the semantic trap (write succeeds, read ignores) is dangerous for future maintainers. A `raise RuntimeError` would be safer than a log-and-permit.

**Suggested fix**: Replace log-and-permit with `raise RuntimeError("Direct write to positions is disabled — use data_cache.apply_position_snapshot()")`.

**Blast radius**: `state.py:259-265` only. No current callers affected.

---

### ST-3: Pre-flagged findings (state map cross-refs)

| State map ID | File:line | Confirmed |
|-------------|-----------|-----------|
| F1 (active_account_id cross-container) | `state.py:247` (init), readers at 40+ sites | Confirmed — see boundary map |
| F4 (_recalculate_portfolio duplicate) | `state.py:337-401` vs `data_cache.py:367-428` | Confirmed — diff verified, functionally identical |
| F9 (dead variable baseline) | `state.py:375` | Confirmed |
| F10 (get_active_sync docstring) | `account_registry.py:113-114` | Confirmed |
| total_realized never written | `state.py:138` | Confirmed — field stays 0.0, persisted to DB as 0 |
| cashflows never read | `state.py:157` | Confirmed — fully dead |
| pre_trade_log in-memory dead | `state.py:235` | Confirmed — written but never read |

---

## `core/data_cache.py` (636 lines)

### DC-1: `_preserve_metadata` preserves stale unrealized PnL through REST snapshots

**File**: `core/data_cache.py:162-164`  
**Severity**: MEDIUM  
**Category**: 1 (financial correctness — minor)

**Observation**: `_preserve_metadata` at line 163: `if old_pos.individual_unrealized != 0.0: new_pos.individual_unrealized = old_pos.individual_unrealized`. Intent is "preserve WS-sourced unrealized PnL if it is more recent than REST." But the condition `!= 0.0` preserves ANY non-zero old value, even when the new REST value is more recent and different. If WS set unrealized to $500, then REST fetches a corrected value of $400, the $500 persists because it's non-zero.

**Financial path**: Stale unrealized → `total_unrealized` (data_cache.py:580) → `total_equity = balance_usdt + total_unrealized` (data_cache.py:584) → `_recalculate_portfolio` → drawdown, weekly PnL, exposure → also `risk_engine.run_risk_calculator:308` reads `total_equity` for sizing. Full financial path exists.

**Mitigating factor**: `apply_mark_price` fires at ~1Hz per symbol and recalculates unrealized from mark price, overwriting the stale value within ~1 second. The exposure window is narrow during normal WS operation. **If market WS is also down**, the stale value persists indefinitely — but this compounds with RE-1 (stale equity), which is separately CRITICAL.

**Severity justification**: MEDIUM — the ~1s window during normal operation is too brief to affect a human sizing decision. The compound failure (both WS streams down) is covered by RE-1. Independently, this finding's practical impact is negligible.

**Suggested fix**: Compare timestamps: only preserve old unrealized when `_positions_version.source` is WS/Platform and `incoming source` is REST. This is effectively what the conflict resolution does at the snapshot level, but the per-field preservation bypasses it.

**Blast radius**: `data_cache.py:162-164` only.

---

### DC-2: `apply_mark_price` sync mutation without lock — correct but fragile

**File**: `core/data_cache.py:555-587`  
**Severity**: LOW (DESIGN NOTE)  
**Category**: 5 (async/concurrency)

**Observation**: `apply_mark_price` is synchronous (no `async`, no `await`), runs without `self._lock`, yet modifies: position fields (fair_price, unrealized, MFE/MAE, position_value), account_state fields (total_unrealized, total_position_value, total_margin_used, total_equity, available_margin), and calls `_recalculate_portfolio`. This is correct in asyncio's cooperative model — a sync function runs to completion without yielding, so no concurrent access is possible.

**Risk**: If this method ever becomes async (adds an `await` inside), the unlocked mutation becomes a race condition. The correctness depends on it remaining synchronous. No code change needed, but the constraint should be documented.

**Blast radius**: None currently. Future risk only.

---

## `core/event_bus.py` (113 lines)

### EB-1: Sequential handler dispatch — slow handler blocks all subsequent handlers

**File**: `core/event_bus.py:89-94`  
**Severity**: MEDIUM  
**Category**: 5 (async/concurrency)

**Observation**: `_dispatch` awaits each handler sequentially: `for handler in ... await handler(payload)`. If `handle_account_updated` (which does a DB write + plugin push) takes 200ms, all subsequent handlers for that event are delayed 200ms. This creates coupling between unrelated handlers.

**Suggested fix**: Use `asyncio.gather` for concurrent dispatch, or spawn each handler as a task. Currently not a bottleneck (handlers are fast), but a structural concern as the handler count grows.

**Blast radius**: `event_bus.py:89-94` only.

---

### EB-2: Handler errors silently swallowed — financial-record handlers can fail without visible signal

**File**: `core/event_bus.py:93-94`  
**Severity**: **HIGH**  
**Category**: 7 (error handling)

**Observation**: `except Exception as exc: log.error(...)` — handler errors are logged but not propagated, counted, or flagged. The bus carries financial-record events:

| Channel | Handler | What fails silently |
|---------|---------|-------------------|
| `risk:account_updated` | `handle_account_updated` | Account snapshot DB write + plugin push |
| `risk:positions_refreshed` | `handle_positions_refreshed` | Position snapshot + account snapshot DB writes |
| `risk:risk_calculated` | `handle_risk_calculated` | Pre-trade log DB write |
| `risk:trade_closed` | `reconciler.on_trade_closed` | MFE/MAE reconciliation |
| `risk:position_closed` | `reconciler.on_position_closed` | Closed position MFE/MAE |

**Financial path**: `handle_account_updated` failure → account snapshot silently dropped → `account_snapshots` table has gaps → crash recovery (`main.py:91`) reads last-available snapshot, which is now stale → on restart, equity/drawdown/BOD baselines are wrong → sizing recommendations based on wrong equity (compounds with RE-1). Also: analytics equity curve has gaps; drawdown calculations use stale peaks.

**Severity justification**: HIGH — the error IS logged (not truly silent), but no health signal, retry, or counter exists. A persistent handler failure would make crash recovery restore stale state. Live state (DataCache) is unaffected (mutation already applied before event fires), so live sizing is fine. The risk is in historical records and crash recovery.

**Suggested fix**: Add error counter per (channel, handler). If a handler fails 3+ times in 5 minutes, set `app_state.ws_status.add_log("HANDLER FAILURE: ...")` and publish a health event that monitoring can detect.

**Blast radius**: `event_bus.py:89-94` (add counter), `monitoring.py` (add handler-health check).

---

## `core/database.py` (689 lines)

### DB-1: `_conn` private attribute exposed to external modules

**File**: `core/database.py:450`, accessed at `platform_bridge.py:300,313,322,335,343,351,358,363`, `reconciler.py:98`  
**Severity**: MEDIUM  
**Category**: 3 (separation of concerns)  
**Cross-ref**: Boundary map — persistence layer finding

**Observation**: `self._conn: Optional[aiosqlite.Connection]` is private by convention but accessed directly by 2 external modules (9 total access sites). This exposes raw SQL execution, bypasses domain methods, and creates hidden schema dependencies.

**Suggested fix**: Add the missing domain methods to `db_exchange.py` (for `_handle_historical_fill`) and `reconciler.py` (for uncalculated symbol query). Make `_conn` truly private or add a deprecation warning on external access.

**Blast radius**: `platform_bridge.py` (6 sites → 2 new domain methods), `reconciler.py` (1 site → 1 new domain method), `db_exchange.py` (add methods).

---

### DB-2: `_conn` not guarded against pre-initialization access

**File**: `core/database.py:450`  
**Severity**: LOW  
**Category**: 7 (error handling)

**Observation**: `self._conn: Optional[aiosqlite.Connection] = None`. If any domain method is called before `initialize()`, `self._conn.execute(...)` raises an opaque `AttributeError: 'NoneType' object has no attribute 'execute'`. No guard or descriptive error exists.

**Suggested fix**: Add a property that raises `RuntimeError("Database not initialized — call db.initialize() first")` when `_conn` is None.

**Blast radius**: `database.py` (add property), all 12 `db_*.py` mixins (no change — they access `self._conn` which would use the property).

---

### DB-3: Schema migrations as sequential ALTER TABLE with silent duplicate handling

**File**: `core/database.py:467-498`  
**Severity**: LOW  
**Category**: 8 (SRP)

**Observation**: Schema migrations are a flat list of `ALTER TABLE ADD COLUMN` statements in `initialize()`, each wrapped in try/except that silently ignores "duplicate column name" errors. This works but is fragile: a non-duplicate `OperationalError` (e.g., disk full, locked DB) is re-raised, but the error message is checked via string matching (`"duplicate column name" in str(e).lower()`). A different SQLite version or locale could produce a different error string.

**Suggested fix**: Check column existence with `PRAGMA table_info(table)` before ALTER, or use the `migrations_log` table that already exists for data migrations.

**Blast radius**: `database.py:467-498` only.

---

## `core/order_state.py` (67 lines)

### OS-1: `validate_transition` silently rejects unknown statuses

**File**: `core/order_state.py:36-41`  
**Severity**: LOW  
**Category**: 7 (error handling) + 10 (naming)

**Observation**: `validate_transition` catches `ValueError` and `KeyError` from unknown status strings and returns `False`. A new exchange status not yet mapped (e.g., Bybit's `"Untriggered"`) would be silently rejected, and the order would be skipped without any log entry. The caller in `order_manager.py:60` logs "Invalid transition X->Y" but doesn't distinguish between a genuinely invalid transition and an unmapped status.

**Suggested fix**: Log unknown statuses at WARNING level inside `validate_transition` so they're visible in logs without reading caller code.

**Blast radius**: `order_state.py:36-41` only.

---

## `core/db_router.py` (169 lines)

### DR-1: `account_db(account_id=...)` raises NotImplementedError at runtime

**File**: `core/db_router.py:122-126`  
**Severity**: LOW  
**Category**: 7 (error handling)

**Observation**: The `account_db` method accepts `account_id: Optional[int]` but raises `NotImplementedError("pending R1b")` if the caller doesn't provide the full (terminal, broker, broker_account_id) tuple. This is a known deferred feature, but the public API signature accepts a parameter that will crash at runtime. No caller currently uses this path.

**Suggested fix**: Remove the `account_id` parameter from the signature until R1b is implemented, or document the limitation in the docstring.

**Blast radius**: `db_router.py:99-126` only. No current callers affected.

---

## Summary

| ID | Severity | Category | File | One-liner |
|----|----------|----------|------|-----------|
| OM-1 | **CRITICAL** | 1+2 (financial+state) | order_manager / ws_manager / db_orders | WS order path bypasses state machine — `upsert_order_batch` overwrites status unconditionally. **Structural redesign candidate OM-R1**: split OrderManager into `process_order_snapshot` + `process_order_update`. |
| OM-2 | HIGH | 2+5 (state+async) | order_manager:48-83 | TOCTOU between snapshot fetch and stale-cancel — WS order arriving mid-snapshot gets falsely canceled |
| OM-3 | **HIGH** | 2+8 (state+SRP) | ws_manager:223, schedulers:456 | `_open_orders` directly assigned from outside OrderManager — same ownership violation family as OM-1 |
| OM-4 | **HIGH** | 7+1 (error+financial) | order_manager:73-80 | `allow_cancel_all` mass-cancels all DB orders when plugin sends orders with only terminal IDs (empty exchange_order_id) — wrong TP/SL display, duplicate-stop risk |
| EB-2 | **HIGH** | 7 (error handling) | event_bus:93-94 | Handler errors silently swallowed — failed `handle_account_updated` drops snapshot → stale crash recovery → wrong equity on restart |
| OM-5 | MEDIUM | 1 (financial minor) | order_manager:100-135 | No TP/SL displayed when mark price unavailable despite orders existing |
| DC-1 | MEDIUM | 1 (financial minor) | data_cache:162-164 | Stale unrealized PnL preserved through REST snapshots — financial path exists but ~1s window mitigated by mark price updates |
| ST-2 | MEDIUM | 4 (hidden state) | state:259-265 | positions setter warns but permits bypass — dead path today, semantic trap for future (write silently discarded on read) |
| EB-1 | MEDIUM | 5 (async) | event_bus:89-94 | Sequential handler dispatch — slow handler blocks subsequent |
| DB-1 | MEDIUM | 3 (separation) | database:450 + 9 access sites | `_conn` private attribute exposed to external modules |
| ST-1 | LOW | 12 (dead code) | state:213 | `_lock` allocated but never acquired |
| DC-2 | LOW | 5 (async) | data_cache:555-587 | `apply_mark_price` sync-without-lock is correct but fragile |
| DB-2 | LOW | 7 (error handling) | database:450 | `_conn` not guarded against pre-init access |
| DB-3 | LOW | 8 (SRP) | database:467-498 | Schema migrations use string-matching for duplicate detection |
| OS-1 | LOW | 7+10 (error+naming) | order_state:36-41 | Unknown statuses silently rejected without logging |
| DR-1 | LOW | 7 (error handling) | db_router:122-126 | `account_db(account_id=...)` raises NotImplementedError at runtime |
| ST-3 | — | — | multiple | State map F1/F4/F9/F10 confirmed at file:line (see table above) |
