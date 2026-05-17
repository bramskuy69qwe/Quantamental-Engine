# History Redesign Data Audit

**Date:** 2026-05-15
**Branch:** `v2.4/history-redesign-audit`
**Purpose:** Pre-implementation audit of existing data sources for the `/history` page redesign.

---

## 1. `trade_event_log`

### File Location & Module Structure

- **Module:** `core/trade_event_log.py`
- **Migration:** `core/migrations/007_v2_4_trade_events.sql`
- **Admin template:** `templates/admin/trade_events.html`
- **Tests:** `tests/test_trade_event_log.py`, `tests/test_trade_event_producers.py`

### Schema (trade_events table)

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK AUTOINCREMENT | |
| `account_id` | INTEGER NOT NULL | |
| `calc_id` | TEXT | nullable; primary lookup key |
| `event_type` | TEXT NOT NULL | validated against Literal whitelist |
| `payload_json` | TEXT NOT NULL DEFAULT '{}' | arbitrary JSON dict |
| `source` | TEXT NOT NULL | originating module |
| `timestamp` | TEXT NOT NULL | ISO-8601 UTC |

Indexes: `idx_trade_events_calc_id`, `idx_trade_events_account_time`, `idx_trade_events_type`.

### Event Type Enum (12 types)

```python
TradeEventType = Literal[
    "calc_created",       # risk calculator produced eligible entry
    "order_placed",       # entry order sent to exchange
    "order_canceled",     # order canceled/expired
    "order_filled",       # fill received (any role)
    "position_opened",    # first fill opened a new position
    "position_closed",    # position fully closed
    "partial_close",      # partial exit fill while position still open
    "tp_modified",        # take-profit stop price changed
    "sl_modified",        # stop-loss price changed
    "liquidated",         # exchange liquidation
    "manual_close",       # user-initiated close
    "manual_link_added",  # admin manually linked calc_id to order
]
```

### Where Events Are Emitted

| Event Type | Source Module | Location |
|------------|-------------|----------|
| `calc_created` | `core/handlers.py:186` | `handle_risk_calculated` — logged when calc is eligible |
| `order_placed` | `core/order_manager.py:343` | new entry order detected |
| `order_canceled` | `core/order_manager.py:352` | order status canceled/expired |
| `order_filled` | `core/order_manager.py:449` | any fill received |
| `position_opened` | `core/order_manager.py:470` | entry fill on flat position (qty_before=0) |
| `position_closed` | `core/order_manager.py:717` | close-position flow completes |
| `partial_close` | `core/order_manager.py:489` | close fill but position still has qty |
| `tp_modified` | `core/order_manager.py:418` | TP stop price modified |
| `sl_modified` | `core/order_manager.py:418` | SL stop price modified |
| `manual_link_added` | `api/routes_admin.py:297` | admin manually links calc_id |

**Not yet emitted:** `liquidated`, `manual_close` (defined but no production caller found).

### Query Interface

`core/trade_event_log.py:116` — `query_trade_events()`

```python
def query_trade_events(
    *, account_id: int,
    calc_id: Optional[str] = None,    # filter by calc_id
    event_type: Optional[str] = None, # filter by type
    since: Optional[str] = None,      # ISO timestamp lower bound
    until: Optional[str] = None,      # ISO timestamp upper bound
    limit: int = 100,
) -> list[dict]
```

Returns newest-first, full row dicts.

---

## 2. `pre_trade_log`

### Schema (28 columns)

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `account_id` | INTEGER NOT NULL DEFAULT 1 | added via migration |
| `timestamp` | TEXT NOT NULL | ISO-8601 |
| `ticker` | TEXT NOT NULL | |
| `average` | REAL NOT NULL DEFAULT 0 | market price at calc time |
| `side` | TEXT NOT NULL DEFAULT '' | LONG/SHORT |
| `one_percent_depth` | REAL NOT NULL DEFAULT 0 | orderbook depth |
| `individual_risk` | REAL NOT NULL DEFAULT 0 | % risk allocated |
| `tp_price` | REAL NOT NULL DEFAULT 0 | take-profit price |
| `tp_amount_pct` | REAL NOT NULL DEFAULT 0 | TP distance as % |
| `tp_usdt` | REAL NOT NULL DEFAULT 0 | TP in USDT |
| `sl_price` | REAL NOT NULL DEFAULT 0 | stop-loss price |
| `sl_amount_pct` | REAL NOT NULL DEFAULT 0 | SL distance as % |
| `sl_usdt` | REAL NOT NULL DEFAULT 0 | SL in USDT |
| `model_name` | TEXT NOT NULL DEFAULT '' | |
| `model_desc` | TEXT NOT NULL DEFAULT '' | |
| `risk_usdt` | REAL NOT NULL DEFAULT 0 | risk in USDT terms |
| `atr_c` | TEXT NOT NULL DEFAULT '' | ATR coefficient |
| `atr_category` | TEXT NOT NULL DEFAULT '' | |
| `est_slippage` | REAL NOT NULL DEFAULT 0 | |
| `effective_entry` | REAL NOT NULL DEFAULT 0 | entry after slippage |
| `size` | REAL NOT NULL DEFAULT 0 | position size |
| `notional` | REAL NOT NULL DEFAULT 0 | |
| `est_profit` | REAL NOT NULL DEFAULT 0 | |
| `est_loss` | REAL NOT NULL DEFAULT 0 | |
| `est_r` | REAL NOT NULL DEFAULT 0 | expected R-multiple |
| `est_exposure` | REAL NOT NULL DEFAULT 0 | |
| `eligible` | INTEGER NOT NULL DEFAULT 0 | 1 if eligible |
| `notes` | TEXT NOT NULL DEFAULT '' | added via migration |
| `calc_id` | TEXT | added via `core/migrations/005_v2_4_calc_id.sql` |

### Insert Pattern

`core/db_trades.py:83` — `insert_pre_trade_log(row)` — all fields populated from risk calculator result dict. Called from `core/handlers.py` via `handle_risk_calculated`.

### Null/Empty Behavior

- All numeric fields default to 0 (never NULL).
- `calc_id` can be NULL (only populated since v2.4).
- `notes` defaults to '' (rarely populated — user-added via UI).
- `model_name` populated when model is active, '' otherwise.

### Query Interface

- `core/db_trades.py:246` — `query_pre_trade_log()` — paginated with date range, search, ticker, side, sort.
- `core/db_trades.py:216` — `get_all_pre_trade_log(days=365)` — unpaginated, days-limited.
- `core/db_orders.py:594` — `get_pre_trade_for_shortfall()` — finds closest pre_trade_log entry for a symbol within a time window before entry (used for slippage shortfall computation).

---

## 3. `fills` table

### Full Schema

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `account_id` | INTEGER NOT NULL | |
| `exchange_fill_id` | TEXT | UNIQUE(account_id, exchange_fill_id) |
| `terminal_fill_id` | TEXT DEFAULT '' | |
| `exchange_order_id` | TEXT DEFAULT '' | FK to orders |
| `symbol` | TEXT NOT NULL | |
| `side` | TEXT NOT NULL | BUY/SELL |
| `direction` | TEXT DEFAULT '' | LONG/SHORT |
| `price` | REAL DEFAULT 0 | fill price |
| `quantity` | REAL DEFAULT 0 | |
| `fee` | REAL DEFAULT 0 | in fee_asset units |
| `fee_asset` | TEXT DEFAULT 'USDT' | consistent currency |
| `exchange_position_id` | TEXT DEFAULT '' | |
| `terminal_position_id` | TEXT DEFAULT '' | position linkage key |
| `is_close` | INTEGER DEFAULT 0 | 0=open, 1=close |
| `realized_pnl` | REAL DEFAULT 0 | |
| `role` | TEXT DEFAULT '' | maker/taker |
| `source` | TEXT DEFAULT '' | ws/rest/backfill |
| `timestamp_ms` | INTEGER DEFAULT 0 | epoch ms |
| `calc_id` | TEXT | added v2.4 migration |
| `slippage_actual` | REAL | added v2.4 migration |
| `fill_type` | TEXT | added v2.4 migration |

Indexes: `idx_fills_terminal`, `idx_fills_order`, `idx_fills_position (terminal_position_id, is_close)`, `idx_fills_ts`.

### Key Findings

- **`order_type`**: NOT directly on fills. Must be derived by joining to `orders.order_type` via `exchange_order_id`. The fill knows the parent order but doesn't duplicate the order_type field.
- **`tp_price` / `sl_price`**: NOT on fills. The planned TP/SL at time of entry are on `orders.tp_trigger_price` / `orders.sl_trigger_price` (added v2.4) and on `pre_trade_log.tp_price` / `pre_trade_log.sl_price` (linked via calc_id).
- **Entry vs exit**: Distinguished by `is_close` flag (0=entry, 1=exit). Also derivable from `position_fill_snapshots` table (`core/migrations/010_v2_4_position_fill_snapshots.sql`).
- **Slippage**: `slippage_actual` column exists (v2.4 addition) but may not be consistently populated yet. Original slippage was `est_slippage` on `pre_trade_log`.
- **Fee**: Present, always in `fee_asset` (default USDT). Consistent.
- **Position FK**: `terminal_position_id` links fill to position. Index exists. Also `exchange_position_id` for exchange-native ID.

---

## 4. `closed_positions`

### Full Schema

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `account_id` | INTEGER NOT NULL | |
| `exchange_position_id` | TEXT DEFAULT '' | |
| `terminal_position_id` | TEXT DEFAULT '' | primary position key |
| `symbol` | TEXT NOT NULL | |
| `direction` | TEXT DEFAULT '' | LONG/SHORT |
| `quantity` | REAL DEFAULT 0 | |
| `entry_price` | REAL DEFAULT 0 | |
| `exit_price` | REAL DEFAULT 0 | |
| `entry_time_ms` | INTEGER DEFAULT 0 | epoch ms |
| `exit_time_ms` | INTEGER DEFAULT 0 | epoch ms |
| `realized_pnl` | REAL DEFAULT 0 | gross PnL |
| `total_fees` | REAL DEFAULT 0 | |
| `net_pnl` | REAL DEFAULT 0 | realized_pnl - total_fees |
| `funding_fees` | REAL DEFAULT 0 | |
| `mfe` | REAL DEFAULT 0 | max favorable excursion |
| `mae` | REAL DEFAULT 0 | max adverse excursion |
| `backfill_completed` | INTEGER DEFAULT 0 | MFE/MAE computation flag |
| `hold_time_ms` | INTEGER DEFAULT 0 | persisted at close time |
| `exit_reason` | TEXT DEFAULT '' | **ALREADY EXISTS** |
| `model_name` | TEXT DEFAULT '' | |
| `notes` | TEXT DEFAULT '' | |
| `shortfall_entry` | REAL DEFAULT 0 | entry slippage shortfall |
| `shortfall_exit` | REAL DEFAULT 0 | exit slippage shortfall |
| `source` | TEXT DEFAULT '' | |
| `calc_id` | TEXT | added v2.4 migration |

UNIQUE constraint: `(account_id, terminal_position_id, exit_time_ms)`.
Indexes: `idx_closed_pos_ts`, `idx_closed_pos_symbol`.

### Key Findings

- **MFE / MAE**: Persisted at close time. Computed by a background reconciler (`get_uncalculated_closed_positions` + `update_closed_position_mfe_mae`). `backfill_completed` flag tracks whether computation is done.
- **`exit_reason`**: **Already exists as a field.** The design README proposes adding it — it's already there. Values currently populated by `core/order_manager.py` at close time.
- **`hold_time_ms`**: Persisted (not derived). Computed as `exit_time_ms - entry_time_ms` at insert time.
- **`calc_id`**: Links back to the originating risk calculation (and through it, to `pre_trade_log` and `trade_events`).
- **No `tp_price` / `sl_price` on this table**: These must be joined from `orders` (via calc_id → orders.calc_id) or from `pre_trade_log` (via calc_id → pre_trade_log.calc_id).

### Query Interface

`core/db_orders.py:475` — `query_closed_positions()` — paginated, ms-based date range, search by symbol.

---

## 5. `execution_log`

### Status: EXISTS

The `execution_log` table **exists** in the main database schema (`core/database.py:121-135`).

### Schema

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `account_id` | INTEGER NOT NULL DEFAULT 1 | added via migration |
| `entry_timestamp` | TEXT NOT NULL | ISO-8601 |
| `ticker` | TEXT NOT NULL | |
| `side` | TEXT DEFAULT '' | |
| `entry_price_actual` | REAL DEFAULT 0 | |
| `size_filled` | REAL DEFAULT 0 | |
| `slippage` | REAL DEFAULT 0 | |
| `order_type` | TEXT DEFAULT 'limit' | MARKET/LIMIT/etc. |
| `maker_fee` | REAL DEFAULT 0 | |
| `taker_fee` | REAL DEFAULT 0 | |
| `latency_snapshot` | REAL DEFAULT 0 | ms |
| `orderbook_depth_snapshot` | TEXT DEFAULT '' | |
| `source_terminal` | TEXT DEFAULT 'manual' | added v2.1 |

### Population Source

- **Manual only**: populated via `POST /history/log_execution` (UI form in `api/routes_history.py:78`).
- Also written to CSV via `core/data_logger.py:80` (`log_execution()`).
- **No automated population** from WS/REST fill events. This is a manual entry table.

### Query Interface

- `core/db_trades.py:260` — `query_execution_log()` — paginated.
- `core/db_trades.py:226` — `get_all_execution_log(days)` — unpaginated.

### Important Note

The design README's "exec link" feature proposes matching `execution_log` entries to `fills` entries. This only works if `execution_log` is populated. Currently it's manual-only, so the exec link feature requires either:
1. Manual entry discipline (user logs every trade in execution_log), or
2. Auto-population from fills (new feature).

---

## 6. Current `/history` Page Structure

### File: `templates/history.html`

### Current Layout (3 visual sections)

```
┌─ Open Positions + Open Orders ──────────────────────────────────────────┐
│  hx-get="/fragments/history/open_positions" every 1s                    │
│  Subtabs: Positions(N) | Open Orders(N)                                 │
└─────────────────────────────────────────────────────────────────────────┘

┌─ Toolbar ────────────────────────────────────────────────────────────────┐
│  Export button | Refresh button | Date range picker + calendar           │
└─────────────────────────────────────────────────────────────────────────┘

┌─ Position History | Order History | Trade History ────────────────────────┐
│  Tab 1: exchange_history (GET /fragments/history/exchange, every 30s)    │
│  Tab 2: orders (GET /fragments/history/order_history)                    │
│  Tab 3: fills (GET /fragments/history/fills)                             │
└─────────────────────────────────────────────────────────────────────────┘

┌─ Pre-Trade Log ──────────────────────────────────────────────────────────┐
│  GET /fragments/history/pre_trade, every 30s                            │
└─────────────────────────────────────────────────────────────────────────┘
```

### Fragments Included

| Fragment | Endpoint | Refresh |
|----------|----------|---------|
| `fragments/history/open_positions.html` | `/fragments/history/open_positions` | every 1s |
| `fragments/history/exchange_table.html` | `/fragments/history/exchange` | every 30s |
| `fragments/history/order_history_table.html` | `/fragments/history/order_history` | load + every 30s |
| `fragments/history/fills_table.html` | `/fragments/history/fills` | load + every 30s |
| `fragments/history/pre_trade_table.html` | `/fragments/history/pre_trade` | every 30s |

Additional fragments that exist but are NOT currently rendered on the main page:
- `fragments/history/closed_positions_table.html` — exists but not wired
- `fragments/history/execution_table.html` — exists but not wired
- `fragments/history/live_trades_table.html` — exists but not wired
- `fragments/history/trade_history_table.html` — exists but not wired (legacy manual)

### Tab Switcher: `htTab`

Implemented inline in `history.html:150-166`. Persists active tab via `window._htTab`. Manages 3 tabs: `positions`, `orders`, `trades`. Toggles `display:none` on panels, updates border/color on tab buttons.

### Date Range System

Global `_dateFrom`/`_dateTo` vars injected into every HTMX request via `htmx:configRequest` listener. Presets (today, yesterday, 7d, 15d, 30d, 90d). Custom dual-month calendar. Calls `refreshAllTables()` which hits all registered endpoints.

---

## 7. Live Position State — What's Already Available?

### MFE (Max Favorable Excursion)

- **Tracked**: `session_mfe` field on `TradePosition` dataclass (`core/state.py:104`).
- **Computation**: Updated every tick in `core/data_cache.py:758` — tracks max unrealized PnL during the session. Also bootstrapped from historical candle data at startup in `core/exchange.py:259`.
- **Persisted to DB**: NO — in-memory only, reset on restart (seeded from agg_trades on next startup).

### MAE (Max Adverse Excursion)

- **Tracked**: `session_mae` field on `TradePosition` dataclass (`core/state.py:105`).
- **Computation**: `core/data_cache.py:760` — tracks minimum unrealized PnL.
- **Same limitations as MFE**: In-memory, volatile.

### Stop Adjustments Count

- **Derivable**: Yes. Count `tp_modified` + `sl_modified` events in `trade_events` for the position's `calc_id`:
  ```sql
  SELECT COUNT(*) FROM trade_events
  WHERE calc_id = ? AND event_type IN ('tp_modified', 'sl_modified')
  ```
- Not currently computed/displayed but trivially queryable.

### Current Hold Time

- **Trivial**: `now() - entry_timestamp`. Already rendered in `open_positions.html` via `hold_time()` template helper.

### Conclusion: `live_trades` Table Redundant?

The design README proposes a `live_trades` table with columns: `ticker`, `direction`, `entry_timestamp`, `max_profit`, `max_loss`, `stop_adjustments`.

**All of these are already available from existing data:**

| Proposed Column | Existing Source |
|----------------|-----------------|
| `ticker` | `app_state.positions[].ticker` |
| `direction` | `app_state.positions[].direction` |
| `entry_timestamp` | `app_state.positions[].entry_timestamp` |
| `max_profit` | `app_state.positions[].session_mfe` |
| `max_loss` | `app_state.positions[].session_mae` |
| `stop_adjustments` | `COUNT(trade_events WHERE event_type IN (tp_modified, sl_modified))` |

**The legacy CSV system (`data/live_trades_log.csv`)** is dead code:
- `update_live_trade()` in `core/data_logger.py:94` exists but is **never called** from anywhere in the codebase.
- The `/fragments/history/live_trades` endpoint reads from this CSV but gets empty data.

**Recommendation**: No new `live_trades` table needed. Render the "Live Trades" tab directly from `app_state.positions` + a `trade_events` count query for stop_adjustments.

---

## 8. Position <-> Fills Linkage

### Primary Linkage Key: `terminal_position_id`

Both `fills` and `closed_positions` have a `terminal_position_id` column that serves as the foreign key linking fills to their parent position.

### Index

```sql
CREATE INDEX idx_fills_position ON fills (terminal_position_id, is_close);
```

### Query Functions

1. **`get_position_fills(account_id, pos_id, symbol, direction, is_close=None)`**
   - `core/db_orders.py:520`
   - Primary lookup: `WHERE terminal_position_id = ?`
   - Fallback: `WHERE terminal_position_id = '' AND symbol = ? AND direction = ?` (for legacy fills without position linkage)
   - Returns all fills ordered by `timestamp_ms ASC`

2. **`get_position_fees(account_id, terminal_position_id)`**
   - `core/db_orders.py:510`
   - `SELECT SUM(fee) FROM fills WHERE terminal_position_id = ?`

3. **`get_fills_by_order(account_id, exchange_order_id)`**
   - `core/db_orders.py:543`
   - Alternative lookup via order ID

4. **`get_unrecorded_closing_fills(account_id, pos_id, symbol, direction)`**
   - `core/db_orders.py:555`
   - Finds closing fills not yet covered by a `closed_positions` row

### Linkage Reliability

- **WS fills (Binance)**: `terminal_position_id` populated by `core/order_manager.py` when processing fills. Reliable for recent data.
- **Backfilled fills**: `terminal_position_id` is empty (`''`). Fallback to `(symbol, direction)` matching works for single-position-per-symbol scenarios but can cross-contaminate if multiple positions existed for the same symbol.
- **The `position_fill_snapshots` table** (`core/migrations/010_v2_4_position_fill_snapshots.sql`) provides an additional layer: records `qty_before`, `qty_after`, `is_open`, `is_close`, `is_partial_close` at fill time. Linked via `fill_id`. Used to derive `is_close` reliably in one-way mode.

---

## Conclusions

### 1. Does `trade_event_log` provide enough data for a "Trade Events" UI tab?

**Yes.** The schema captures the full lifecycle (12 event types), with `calc_id` as the primary correlation key, freeform `payload_json` for details, and proper indexing. The query interface supports filtering by calc_id, event_type, and time range. Current coverage is good: calc_created, order_placed, order_canceled, order_filled, position_opened, position_closed, partial_close, tp_modified, sl_modified are all actively emitted.

### 2. Can the README's `execution_log` be eliminated in favor of `pre_trade_log` + `fills` matching?

**No — but it can be repurposed.** `execution_log` already exists and serves a different function: it's the manual trade entry log (user-submitted execution details). The README's "exec link" feature proposes matching fills to execution_log entries, but since execution_log is only manually populated, this feature is limited to users who manually log trades.

**For the redesign**, the more practical approach is:
- Keep `execution_log` as-is (manual entry table, Card 3 Tab 2).
- The exec link feature works best when `execution_log` is populated (either manually or auto-populated from fills in the future).
- The `pre_trade_log` provides the planned TP/SL prices (via calc_id linkage to fills), which is what the fill drawer actually needs for showing planned vs actual comparison.

### 3. Can the README's `live_trades` be replaced with computed-from-existing-data?

**Yes, completely.** All proposed `live_trades` columns are already available:
- Position metadata: `app_state.positions` (in-memory, updated every tick)
- MFE/MAE: `session_mfe` / `session_mae` on position objects
- Stop adjustments: derivable from `trade_events` count query
- Hold time: trivial computation

No new table or migration needed. The CSV-based live_trades system is dead code.

### 4. What Schema Additions ARE Genuinely Needed?

| Addition | Rationale |
|----------|-----------|
| `fills.tp_price REAL` | Store planned TP at time of entry fill (for exec link comparison). Alternatively, join via calc_id to pre_trade_log. |
| `fills.sl_price REAL` | Same as above for SL. |
| `fills.exec_log_id TEXT` | FK to execution_log.id (for exec link feature, if pursued). |
| `fills.exec_link_confirmed INTEGER` | Tracks whether user confirmed the exec link match. |
| `closed_positions.tp_price REAL` | Snapshot of planned TP at entry (for Position History display). Alternatively, join via calc_id. |
| `closed_positions.sl_price REAL` | Same for SL. |

**Already present (no migration needed):**
- `closed_positions.exit_reason` — already exists (README incorrectly proposes adding it)
- `closed_positions.mfe` / `mae` — already exist with backfill computation
- `fills.calc_id` — already exists
- `fills.slippage_actual` — already exists
- `orders.tp_trigger_price` / `sl_trigger_price` — already exist (v2.4)
- `orders.calc_id` — already exists
- `pre_trade_log.calc_id` — already exists (migration 005)

**NOT needed:**
- `live_trades` table — replace with in-memory + trade_events query
- `execution_log` schema changes — table already has all needed columns
- `pre_trade_log.model_name` — already exists in the CREATE TABLE schema

### Decision: Join vs Denormalize for TP/SL

The TP/SL at time of entry can be resolved two ways:

1. **Join path**: `closed_positions.calc_id` -> `pre_trade_log.calc_id` -> `pre_trade_log.tp_price/sl_price`
2. **Denormalize**: Add `tp_price`/`sl_price` directly to `closed_positions` and `fills`

Trade-off: Join is simpler (no migration), but slower for large result sets and requires the pre_trade_log entry to exist (it won't for backfilled positions). Denormalization is more robust for display but requires migration + population logic.

**Recommendation**: Denormalize on `closed_positions` only (add `tp_price`/`sl_price`). For fills, use the join path via calc_id since fills are only shown in the drawer (single-position context, fast query).
