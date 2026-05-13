# Phase 1b — Mutable Shared State Map

**Codebase**: Quantamental Engine v2.3.1  
**Date**: 2026-05-07  
**Branch**: `audit/v2.3.1`

---

## State Container Index

| # | Container | Module | Lock | Notes |
|---|-----------|--------|------|-------|
| 1 | **AppState** (singleton) | `core/state.py:428` | `asyncio.Lock` | God-object — every route reads it |
| 2 | **DataCache** | `core/data_cache.py` (attached as `app_state._data_cache`) | `asyncio.Lock` | Single-writer for positions; must acquire BEFORE AppState lock |
| 3 | **AccountRegistry** | `core/account_registry.py:366` | `asyncio.Lock` | Credential cache |
| 4 | **ConnectionsManager** | `core/connections.py:201` | `asyncio.Lock` | 3rd-party API keys |
| 5 | **ExchangeFactory** | `core/exchange_factory.py:157` | **NONE** | CCXT/adapter instance cache |
| 6 | **EventBus** | `core/event_bus.py:113` | implicit (asyncio.Queue) | Handler registry |
| 7 | **exchange.py globals** | `core/exchange.py` | **NONE** | Legacy singleton + ThreadPool |
| 8 | **ws_manager globals** | `core/ws_manager.py` | **NONE** | Task handles, listen key, flags |
| 9 | **PlatformBridge** | `core/platform_bridge.py:810` | **NONE** | WS client set, counters, OrderManager |
| 10 | **OrderManager** | `core/order_manager.py` (owned by PlatformBridge) | **NONE** | Open orders cache |
| 11 | **api/cache.py globals** | `api/cache.py` | `asyncio.Lock` (backfill only) | Funding rates, backfill pointers |
| 12 | **schedulers.py globals** | `core/schedulers.py` | **NONE** | Task set, in-flight flag |

---

## 1. AppState (`core/state.py:428`)

### 1.1 `account_state: AccountState` (22 mutable float/str fields)

**What**: Live account balances, equity, PnL, margin, BOD/SOW snapshots, rolling high/low.

| Field | Represents | Writers | Ordered? |
|-------|-----------|---------|----------|
| `balance_usdt` | Wallet balance (USDT) | **DataCache.apply_account_update_rest** (:477), **DataCache.apply_account_update_platform** (:516), **DataCache.apply_position_update_incremental** (:275), **DataCache.apply_mark_price** (:584) | Yes — DataCache lock + conflict resolution (Platform > WS > REST) |
| `available_margin` | Free margin | Same 3 writers as balance_usdt | Same |
| `total_equity` | Balance + unrealized PnL | Same 3 writers + **DataCache.apply_mark_price** (:584) | Same; mark_price is sync (no lock) but asyncio-safe |
| `total_unrealized` | Sum of all position unrealized | **DataCache.apply_position_update_incremental** (:330), **DataCache.apply_mark_price** (:580) | Two paths — both inside DataCache; mark_price recalculates from positions list |
| `total_realized` | Cumulative realized PnL | NOT WRITTEN except at init (0.0) | **FINDING: never populated after init — always 0.0** |
| `total_position_value` | Sum of abs(notional) | **DataCache.apply_mark_price** (:581) | Single writer (sync) |
| `total_margin_used` | Sum of individual margins | **DataCache.apply_mark_price** (:582), **DataCache.apply_account_update_platform** (:520) | Two writers — both inside DataCache |
| `total_margin_ratio` | Maintenance margin ratio | **DataCache.apply_account_update_rest** (:482), **DataCache.apply_account_update_platform** (:521) | Conflict-resolved |
| `total_tp_usdt` | Sum of TP USDT across positions | **_recalculate_portfolio** (in DataCache and AppState) | Derived — always recomputed |
| `total_sl_usdt` | Sum of SL USDT across positions | Same as total_tp_usdt | Derived |
| `daily_pnl` | Equity − BOD equity | **_recalculate_portfolio** | Derived |
| `daily_pnl_percent` | daily_pnl / BOD equity | **_recalculate_portfolio** | Derived |
| `daily_unrealized` | Session unrealized (not reset) | **perform_bod_reset** (:413) sets to 0 | Single writer (BOD) |
| `daily_realized` | Session realized (not reset) | **perform_bod_reset** (:412) sets to 0 | Single writer (BOD) |
| `bod_equity` | Balance at midnight local | **perform_bod_reset** (:408), **DataCache.apply_account_update_rest** (:487, first-fetch), **DataCache.apply_bod_sow_equity** (:538) | 3 writers — BOD reset, first REST fetch, income-history backfill |
| `sow_equity` | Balance at start of week | **perform_bod_reset** (:420), **DataCache.apply_account_update_rest** (:492), **DataCache.apply_bod_sow_equity** (:542) | 3 writers — same pattern |
| `bod_timestamp` | ISO string of BOD time | **perform_bod_reset** (:409), **DataCache.apply_bod_sow_equity** (:540) | 2 writers |
| `sow_timestamp` | ISO string of SOW time | **perform_bod_reset** (:421), **DataCache.apply_bod_sow_equity** (:544) | 2 writers |
| `max_total_equity` | Intraday high | **_recalculate_portfolio**, **perform_bod_reset** (:410) | Derived + reset |
| `min_total_equity` | Intraday low | **_recalculate_portfolio**, **perform_bod_reset** (:411) | Derived + reset |
| `cashflows` | Cumulative deposits/withdrawals | NOT WRITTEN except init (0.0) | **FINDING: never populated** |

**Readers**: Every route handler via `api/helpers.py:_ctx()`, `routes_dashboard.py`, `routes_analytics.py`, `routes_calculator.py`, `routes_platform.py`. Also: `handlers.py:_build_account_snapshot`, `data_logger.py`, `monitoring.py`, `risk_engine.py`, `platform_bridge.py:get_state_json`.

### 1.2 `positions: List[PositionInfo]` (property → DataCache._positions)

**What**: All open positions with per-position PnL, margin, TP/SL, MFE/MAE.

| Writer | Method | Source | Lock |
|--------|--------|--------|------|
| **DataCache.apply_position_snapshot** | Full replacement (REST/Platform) | `exchange.py:fetch_positions`, `platform_bridge._handle_position_snapshot` | DataCache._lock + conflict resolution |
| **DataCache.apply_position_update_incremental** | In-place update/add/remove | `ws_manager._apply_account_update` (WS ACCOUNT_UPDATE) | DataCache._lock |
| **DataCache.apply_mark_price** | In-place field updates (fair_price, unrealized, MFE/MAE) | `ws_manager._apply_mark_price`, `platform_bridge._handle_mark_price` | **NO LOCK** (sync method) |
| **exchange.py:fetch_open_orders_tpsl** | Sets TP/SL fields on positions | `exchange.py:fetch_positions`, `platform_bridge._handle_orders_changed` | **NO LOCK** |
| **ws_manager._apply_order_update** | Sets TP/SL fields on positions | WS ORDER_TRADE_UPDATE | **NO LOCK** |
| **OrderManager.enrich_positions_tpsl** | Sets TP/SL fields on positions | `platform_bridge._handle_position_snapshot`, `order_manager.process_order_snapshot` | **NO LOCK** |
| **exchange.py:populate_open_position_metadata** | Sets entry_timestamp, session_mfe, session_mae, individual_fees | Startup, `platform_bridge` one-shot | **NO LOCK** |
| **ws_manager._on_new_position** | Sets entry_timestamp | WS new position detection | **NO LOCK** |
| **order_manager.process_fill** | Sets individual_fees | Platform fill | **NO LOCK** |
| **app_state.positions setter** (legacy) | Direct list assignment (logged warning) | Bypass path | **NO LOCK** |

**Readers**: `routes_dashboard.py:60,80,296`, `routes_analytics.py:335,375`, `routes_history.py:171`, `routes_calculator.py`, `api/cache.py:106,121`, `handlers.py:53,108,134`, `risk_engine.py:271,356,363`, `data_logger.py:158,162`, `monitoring.py:107`, `schedulers.py:162,304,459`, `exchange.py:195,216,296,327`, `platform_bridge.py:580,581,637,796,804`, `order_manager.py:89,153,198`, `ws_manager.py:148,240,355,368`.

**FINDING — Cross-container duplication**: `app_state._positions_legacy` vs `DataCache._positions`. The property dispatches to DataCache when available, but `_positions_legacy` still exists and is written during `reset_for_account_switch` and the legacy setter path. If DataCache is ever `None` (startup race), reads fall back to `_positions_legacy` which may be empty or stale.

**FINDING — TP/SL fields have 3 uncoordinated writers**: `fetch_open_orders_tpsl` (REST), `_apply_order_update` (WS), and `enrich_positions_tpsl` (OrderManager/Platform). None acquire a lock. In practice, asyncio cooperative scheduling prevents true concurrency, but the fields can be transiently inconsistent if a WS ORDER_TRADE_UPDATE fires between the snapshot replacement in `apply_position_snapshot` and the subsequent `enrich_positions_tpsl` call.

### 1.3 `portfolio: PortfolioStats`

**What**: Aggregate risk metrics derived from positions + account state.

| Field | Writers | Notes |
|-------|---------|-------|
| `total_exposure` | **_recalculate_portfolio** (DataCache + AppState copies) | Derived |
| `total_weekly_pnl` | **_recalculate_portfolio**, **perform_bod_reset** (:422) | Derived + reset |
| `total_weekly_pnl_percent` | Same | Derived + reset |
| `total_correlated_exposure` | **_recalculate_portfolio** | Derived (Dict[str, float]) |
| `drawdown` | **_recalculate_portfolio** | Derived |
| `dd_baseline_equity` | **_recalculate_portfolio** (via DataCache), **perform_bod_reset** (:416), **DataCache.apply_account_update_rest** (:490) | 3 writers |
| `weekly_pnl_state` | **_recalculate_portfolio**, **perform_bod_reset** (:424) | Derived + reset |
| `dd_state` | **_recalculate_portfolio** | Derived |

**FINDING — Duplicate `_recalculate_portfolio`**: Both `AppState.recalculate_portfolio()` (state.py:337) and `DataCache._recalculate_portfolio()` (data_cache.py:351) exist with **nearly identical logic**. `DataCache` version is the canonical path (called after every mutation). `AppState` version is still called from: `routes_accounts.py:138` (account switch), `handlers.py:212` (params_updated), `schedulers.py:310` (startup). These two copies must agree — silent divergence would cause financial correctness issues. Currently they DO agree, but maintenance risk is HIGH.

### 1.4 `exchange_info: ExchangeInfo`

| Field | Writers | Notes |
|-------|---------|-------|
| `name` | `exchange.py:fetch_exchange_info` (:112) | Per-account from registry |
| `account_id` | `exchange.py:fetch_account` (:142) | Fee tier string |
| `server_time` | `exchange.py:fetch_exchange_info` (:118) | UTC string |
| `latency_ms` | `exchange.py:fetch_exchange_info` (:115) | REST round-trip |
| `maker_fee` | `exchange.py:fetch_account` (:144), `state.py:load_params` (:316), `routes_accounts.py:386` | **3 writers** — REST fetch, startup load, UI params update |
| `taker_fee` | Same 3 writers | Same |

**Readers**: `risk_engine.py:344` (fee calculation), `routes_dashboard.py:242`, `routes_history.py:92-93`, `api/helpers.py:_ctx()`.

**FINDING — maker_fee/taker_fee have 3 writers with no ordering**: REST `fetch_account` may race with `load_params` during startup, and `routes_accounts.py` can overwrite at any time from the UI. All write to the same `exchange_info` fields without locks.

### 1.5 `ws_status: WSStatus`

| Field | Writers | Notes |
|-------|---------|-------|
| `connected` | `ws_manager._user_data_loop` (:294), `ws_manager.stop` (:545) | Set true on connect, false on disconnect/stop |
| `last_update` | `exchange.py:fetch_account` (:155), `exchange.py:fetch_positions` (:189), `ws_manager._handle_user_event` (:116), `ws_manager._market_stream_loop` (:441), `ws_manager._fallback_loop` (:489) | **5 writers** — no ordering, but all set to "now" |
| `latency_ms` | `exchange.py:fetch_exchange_info` (:117), `ws_manager._handle_user_event` (:108) | 2 writers — REST vs WS latency (different semantics!) |
| `reconnect_attempts` | `ws_manager._user_data_loop` (:295), `ws_manager._reconnect_user` (:319) | Single logical writer (WS reconnect path) |
| `using_fallback` | `ws_manager._user_data_loop` (:296), `ws_manager._fallback_loop` (:473,494), `ws_manager.stop` (:546) | Multiple writers — set true when stale, false when recovered/stopped |
| `logs` | 20+ call sites via `add_log()` | Append-only, trimmed to max display |

**Readers**: `api/helpers.py:106` (every template), `routes_dashboard.py:242`, `routes_params.py:30`, `monitoring.py:88`.

**FINDING — `latency_ms` conflates two measurements**: `fetch_exchange_info` writes REST round-trip latency; `_handle_user_event` writes WS event-to-process latency. These are different metrics sharing one field. The dashboard displays whichever was written last.

### 1.6 `ohlcv_cache: Dict[str, List]`

| Writer | Location | Lock |
|--------|----------|------|
| **DataCache.apply_kline** | `data_cache.py:589` | **NONE** (sync) |
| **exchange_market.fetch_ohlcv** | `exchange_market.py:50` | **NONE** |
| **DataCache.evict_symbol_caches** | `data_cache.py:610-612` | **NONE** |
| **reset_for_account_switch** | `state.py:274` | **NONE** |

**Readers**: `risk_engine.py:64` (ATR calculation), `routes_calculator.py:44`, `routes_analytics.py:376,385`.

**FINDING**: `exchange_market.fetch_ohlcv` and `DataCache.apply_kline` both write to the same dict. `fetch_ohlcv` does a full replacement; `apply_kline` appends/replaces last bar. If a WS kline arrives between the REST fetch and the assignment, the kline is lost (overwritten by REST). Not financially critical (ATR is tolerant of one missing bar), but violates single-writer principle.

### 1.7 `orderbook_cache: Dict[str, Dict]`

| Writer | Location | Lock |
|--------|----------|------|
| **DataCache.apply_depth** | `data_cache.py:605` | **NONE** |
| **exchange_market.fetch_orderbook** | `exchange_market.py:252` | **NONE** |
| **DataCache.evict_symbol_caches** | `data_cache.py:613-615` | **NONE** |
| **reset_for_account_switch** | `state.py:275` | **NONE** |

**Readers**: `risk_engine.py:101,145,167,367` (VWAP, slippage, depth), `routes_calculator.py:74`, `routes_dashboard.py:251,265`.

**FINDING — 2 writers, no ordering**: Same pattern as ohlcv_cache. REST fetch_orderbook and WS/Plugin depth updates write to the same dict without coordination. **Financially relevant**: risk_engine reads orderbook to compute VWAP fill price and slippage estimate. A stale or partial orderbook produces incorrect sizing.

### 1.8 `mark_price_cache: Dict[str, float]`

| Writer | Location | Lock |
|--------|----------|------|
| **DataCache.apply_mark_price** | `data_cache.py:560` | **NONE** (sync) |
| **exchange_market.fetch_mark_price** | `exchange_market.py:267` | **NONE** |
| **DataCache.evict_symbol_caches** | `data_cache.py:616-618` | **NONE** |

**Readers**: `routes_dashboard.py:249`, `data_cache.py:310,315` (position value calculation).

**FINDING**: Same dual-writer pattern. Less critical since mark price is a single float per symbol and both writers produce the same semantic value ("latest mark price").

### 1.9 `params: Dict[str, Any]`

| Writer | Location |
|--------|----------|
| **load_params** | `state.py:297` (startup) |
| **reset_for_account_switch** | `state.py:287` |
| **routes_params.py** | `:67` (user update via UI) |
| **routes_accounts.py** | `:384` (account-level param update) |

**Readers**: `risk_engine.py:243,281,308,363,364` (sizing, limits), `_recalculate_portfolio` (both copies), `routes_dashboard.py:53,196`, `routes_params.py:30`, `api/helpers.py:108`, `schedulers.py:88`.

Single owner in practice (user action triggers writes), but no lock protects reads during a write.

### 1.10 `pre_trade_log: List[Dict]`

| Writer | Location |
|--------|----------|
| **handlers.handle_risk_calculated** | `handlers.py:196-197` |
| **reset_for_account_switch** | `state.py:278` |

**Readers**: Currently none read from in-memory list — routes read from DB instead. The list is a vestige of the pre-DB CSV approach.

**FINDING — Dead state**: `pre_trade_log` in-memory list is written but never read by any route. All consumers query the DB table instead. This is dead mutable state.

### 1.11 `exchange_trade_history: List[Dict]`

| Writer | Location |
|--------|----------|
| **exchange_income.fetch_exchange_trade_history** | `exchange_income.py:384` |
| **reset_for_account_switch** | `state.py:277` |

**Readers**: `routes_history.py:66`.

Single writer (background refresh every 5 min). Used only by one route.

### 1.12 `current_regime: Optional[RegimeState]`

| Writer | Location |
|--------|----------|
| **schedulers._startup_fetch** | `schedulers.py:322` |
| **schedulers._regime_refresh_loop** | `schedulers.py:388` |
| **reset_for_account_switch** | `state.py:280` |

**Readers**: `risk_engine.py:314-318` (regime multiplier for position sizing), `routes_regime.py:34`, `routes_calculator.py` (via risk_engine).

**FINDING**: `current_regime` is read by the risk engine to determine position sizing multiplier. It is written by a background task every 10 minutes. No staleness gate exists at the read site — the risk engine checks `regime.is_stale` and falls back to 1.0 if stale, which is correct. However, the staleness threshold (`REGIME_STALE_MINUTES`) is configured separately from the refresh interval (10 min), creating a gap if they diverge.

### 1.13 `is_initializing: bool`

| Writer | Location |
|--------|----------|
| `schedulers._startup_fetch` | `:329` (set False) |
| `routes_accounts.py` | `:110` (set True on switch), `:156,159` (set False after switch) |
| `reset_for_account_switch` | `:279` (set True) |

**Readers**: `api/helpers.py:109` (every template), `routes_dashboard.py:281` (/api/ready endpoint).

### 1.14 `active_account_id: int`

| Writer | Location |
|--------|----------|
| `routes_accounts.py` | `:117` (account switch), `:149` (rollback) |
| `platform_bridge._handle_hello` | `:435,465` (auto-detection from plugin) |
| `state._init` | `:247` (init to 1) |

**Readers**: ~40 locations across all routes, handlers, schedulers, exchange modules (used as DB query parameter).

**FINDING — 2 independent writers without coordination**: `routes_accounts.py` (user-initiated switch) and `platform_bridge._handle_hello` (auto-detection) can both write `active_account_id`. If the plugin sends a `hello` message during an account switch, they race. No lock protects this field.

### 1.15 `active_platform: str`

| Writer | Location |
|--------|----------|
| `routes_accounts.py` | `:255` |

**Readers**: `api/helpers.py:111`, `platform_bridge.get_state_json`, `handlers.py:76`.

Single writer. Low risk.

---

## 2. DataCache (`core/data_cache.py`)

### 2.1 `_positions: List[PositionInfo]`

Covered in §1.2 above. The canonical position store.

### 2.2 `_positions_version: VersionedState`

| Field | Mutated by |
|-------|-----------|
| `sequence` | `_advance_version` (incremented on every accepted mutation) |
| `source` | `_advance_version` (set to UpdateSource of accepted mutation) |
| `timestamp_ms` | `_advance_version` (exchange event time or wall clock) |
| `applied_at` | `_advance_version` (monotonic clock) |

Always mutated inside `self._lock`. Used by `_should_accept_position_update` for conflict resolution. Single owner.

### 2.3 `_account_version: VersionedState`

Same pattern as `_positions_version` but for account state updates.

### 2.4 Conflict Resolution Rules

```
Priority: Platform > WS_USER > REST
Window: REST rejected if WS/Platform updated within 5000ms
Force flag: fill-triggered REST always accepted
```

---

## 3. AccountRegistry (`core/account_registry.py:366`)

### 3.1 `_cache: Dict[int, Dict]`

Per-account credential store. Fields per entry: `id, name, exchange, market_type, api_key, api_secret, is_active, broker_account_id, maker_fee, taker_fee, environment, params`.

| Writer | Method | Lock |
|--------|--------|------|
| `load_all` | Full rebuild from DB | `self._lock` |
| `add_account` | Insert new entry | `self._lock` |
| `update_account` | Update fields | `self._lock` |
| `delete_account` | Remove entry | `self._lock` |
| `set_active` | Toggle is_active flags | `self._lock` |
| `update_account_params` | Update params sub-dict | `self._lock` |
| `update_account_fees` | Update fee fields | `self._lock` |

**Readers**: `get_active_sync` (**NO LOCK** — sync accessor for ThreadPoolExecutor), `get_account_params` (**NO LOCK**), `get_account_fees` (**NO LOCK**), `find_by_broker_id` (**NO LOCK**), `list_accounts_sync` (**NO LOCK**).

**FINDING — Sync readers bypass lock**: `get_active_sync`, `get_account_params`, `get_account_fees`, `find_by_broker_id`, and `list_accounts_sync` read from `_cache` without acquiring `_lock`. In asyncio single-threaded context this is safe between awaits. However, `get_active_sync` is called from `ThreadPoolExecutor` threads (CCXT calls in `exchange.py`), which CAN run concurrently with async writers. A dict mutation during a thread read could cause a `RuntimeError: dictionary changed size during iteration`. This is a latent concurrency bug.

### 3.2 `_active_id: int`

Written by `load_all`, `set_active`. Read by `get_active`, `get_active_sync`, `active_id` property.

**FINDING — Cross-container duplication**: `_active_id` in AccountRegistry and `active_account_id` in AppState represent the same concept. They can diverge: `platform_bridge._handle_hello` writes `app_state.active_account_id` without updating `account_registry._active_id`. `routes_accounts.py` updates both (via `set_active`). This is a race and a consistency bug.

---

## 4. ConnectionsManager (`core/connections.py:201`)

### 4.1 `_cache: Dict[str, Dict]`

Provider → API key store. All writes go through `load_all`, `upsert`, `delete` — all lock-protected. Sync readers (`get_sync`, `list_connections_sync`) bypass lock but are asyncio-safe.

Low risk. No cross-container duplication.

---

## 5. ExchangeFactory (`core/exchange_factory.py:157`)

### 5.1 `_instances: Dict[int, ccxt.Exchange]`

CCXT objects by account_id. Written by `get()` (lazy init), `invalidate()`, `invalidate_all()`. Read by `get()`. **No lock.**

### 5.2 `_adapters: Dict[int, ExchangeAdapter]`

REST adapters by account_id. Same write/read pattern. **No lock.**

### 5.3 `_ws_adapters: Dict[int, WSAdapter]`

WS adapters by account_id. Same pattern. **No lock.**

**FINDING — Stale instance risk**: `invalidate()` must be called on account switch or credential rotation. If missed, stale CCXT instances with old credentials will be used. `routes_accounts.py` calls `exchange_factory.invalidate(old_account_id)` during switch — but only for the old account. If credentials are rotated on the active account (via `update_account`), `invalidate()` is NOT called.

---

## 6. exchange.py globals (`core/exchange.py`)

### 6.1 `_exchange: Optional[ccxt.binance]`

Legacy singleton. Written by `get_exchange()` (:74-76) on first call. Read by `get_exchange()`.

**FINDING — Dead path**: `_exchange` is only used during the startup window before `exchange_factory` is ready. After startup, `get_exchange()` always delegates to `exchange_factory`. The legacy singleton retains hardcoded Binance credentials from `.env` (not from the active account). If the factory path ever falls through after startup, it would silently use wrong credentials.

### 6.2 `_REST_POOL: ThreadPoolExecutor`

Shared thread pool (8 workers). Used by `exchange.py` and `core/adapters/base.py`. Immutable after creation.

---

## 7. ws_manager globals (`core/ws_manager.py`)

| Global | Type | Writers | Notes |
|--------|------|---------|-------|
| `_listen_key` | `Optional[str]` | `start()` (:503), `_reconnect_user` (:334), `stop()` (:539) | Set via `global` keyword |
| `_user_ws_task` | `Optional[Task]` | `start()` (:505), `stop()` (:541) | Task handle |
| `_market_ws_task` | `Optional[Task]` | `start()` (:506), `restart_market_streams()` (:522), `stop()` (:542) | Task handle |
| `_keepalive_task` | `Optional[Task]` | `start()` (:507), `stop()` (:543) | Task handle |
| `_fallback_task` | `Optional[Task]` | `start()` (:508), `stop()` (:544) | Task handle |
| `_calculator_symbol` | `Optional[str]` | `set_calculator_symbol()` (:514) | UI-driven |
| `_last_ws_position_update` | `float` | `_apply_account_update` (:87) | Monotonic timestamp |
| `_stopping` | `bool` | `start()` (:502), `stop()` (:530) | Shutdown coordination |

All use `global` keyword. No locks. Asyncio-safe in single-event-loop context.

---

## 8. PlatformBridge (`core/platform_bridge.py:810`)

### 8.1 `_ws_clients: Set[Any]`

| Writer | Method | Lock |
|--------|--------|------|
| `handle_ws` | add on connect (:187), discard on disconnect (:209) | **NONE** |
| `_send_to_clients` | remove dead clients (:741) | **NONE** |
| `push_risk_state` | remove dead clients (:776) | **NONE** |

**Readers**: `is_connected` property (checked by ws_manager, schedulers, exchange.py, handlers.py).

### 8.2 `_last_push: float`

Written by `push_risk_state` (:777). Not read externally.

### 8.3 `_historical_fill_count: int`

Written by `_handle_historical_fill` (:367). Read only for logging.

### 8.4 `_metadata_populated: bool`

Written by `_handle_position_snapshot` (:677). One-shot flag — set True once, never reset.

### 8.5 `_order_manager: OrderManager`

Owned instance. See §10.

---

## 9. OrderManager (`core/order_manager.py`)

### 9.1 `_open_orders: List[Dict]`

| Writer | Method | Lock |
|--------|--------|------|
| `process_order_snapshot` | Full rebuild from DB (:86) | **NONE** |
| `ws_manager._apply_order_update` | Direct assignment (:223) | **NONE** |
| `schedulers._order_staleness_loop` | Direct assignment (:456) | **NONE** |

**Readers**: `enrich_positions_tpsl` (:109-121), `open_orders` property.

**FINDING — 3 uncoordinated writers**: `process_order_snapshot` (platform snapshot), `_apply_order_update` (WS), and `_order_staleness_loop` (background) all replace `_open_orders` without locks. While asyncio prevents true concurrency, the list can be stale if an event fires between a DB query and the assignment.

---

## 10. api/cache.py globals

| Global | Type | Writers | Lock |
|--------|------|---------|------|
| `_backfill_earliest_ms` | `Dict[int, Optional[int]]` | `_maybe_backfill_equity` | `_backfill_lock` |
| `_FUNDING_RATES` | `Dict[str, Dict]` | `_refresh_funding_rates_bg` (:110) | **NONE** (flag-guarded) |
| `_FUNDING_RATES_TS` | `float` | `_refresh_funding_rates_bg` (:111) | **NONE** |
| `_FUNDING_REFRESHING` | `bool` | `_ensure_funding_rates` (:99), `_refresh_funding_rates_bg` (:115) | **NONE** |

Funding rates: non-critical (display only, not used in sizing or risk decisions).

---

## 11. schedulers.py globals

| Global | Type | Writers | Notes |
|--------|------|---------|-------|
| `_bg_tasks` | `Set[Task]` | `_spawn()` (add), done callback (discard) | Task registry |
| `_account_refresh_in_flight` | `bool` | `_account_refresh_loop` (:107,117,193) | Overlap guard |

---

## Cross-Container State Findings

### F1: `active_account_id` — 2 containers, 3 writers, NO synchronization

| Container | Field | Writers |
|-----------|-------|---------|
| AppState | `active_account_id` | `routes_accounts.py:117,149`, `platform_bridge._handle_hello:435,465` |
| AccountRegistry | `_active_id` | `load_all`, `set_active` |

`platform_bridge._handle_hello` writes AppState but not AccountRegistry. If the two diverge, `exchange.py:get_exchange()` (which reads AccountRegistry) will use a different account than the one displayed in the UI (which reads AppState). **Severity: CRITICAL (financial)** — orders could be submitted to the wrong account.

### F2: `positions` — 2 backing stores, migration incomplete

| Container | Field | Status |
|-----------|-------|--------|
| AppState | `_positions_legacy` | Written during reset, fallback when DataCache is None |
| DataCache | `_positions` | Canonical store after initialization |

The property in AppState dispatches correctly, but `_positions_legacy` is still mutated in `reset_for_account_switch`, creating a brief window where the legacy list is authoritative.

### F3: `maker_fee` / `taker_fee` — 3 containers

| Container | Field | Writers |
|-----------|-------|---------|
| AppState.exchange_info | `maker_fee`, `taker_fee` | `fetch_account`, `load_params`, `routes_accounts.py` |
| AccountRegistry._cache[id] | `maker_fee`, `taker_fee` | `update_account_fees` |
| Config module | `MAKER_FEE`, `TAKER_FEE` | Immutable defaults |

`risk_engine.py:344` reads from `exchange_info`. If that's stale while the registry has been updated (or vice versa), the calculator uses wrong fees. **Severity: MEDIUM** — fee discrepancy affects sizing/PnL estimates but not order execution.

### F4: `_recalculate_portfolio` — duplicated logic in 2 containers

| Location | Called from |
|----------|-----------|
| `AppState.recalculate_portfolio` (state.py:337) | `routes_accounts.py:138`, `handlers.py:212`, `schedulers.py:310` |
| `DataCache._recalculate_portfolio` (data_cache.py:351) | Every DataCache `apply_*` method |

Both copies compute identical metrics but could diverge if maintained independently. **Severity: HIGH** — if they disagree, drawdown gates, weekly loss limits, and exposure limits would differ depending on which path was last called.

---

## Summary Table: Multi-Writer Fields (severity-verified)

| Field | Writers | Lock? | Financial Path | Severity | Justification |
|-------|---------|-------|----------------|----------|---------------|
| `active_account_id` (F1, cross-container) | 3 (routes, platform_bridge, registry) | NO | `get_exchange()` → all REST/WS → wrong account for position/balance fetch and order creation | **CRITICAL** | Also a boundary violation: adapter writes core state directly (see Phase 1c) |
| `_open_orders` (F5) | 3 (snapshot, WS, staleness) | NO | `enrich_positions_tpsl` → TP/SL display; `mark_stale_orders_canceled` → can falsely cancel valid orders in DB → trader sees wrong TP/SL → may place duplicate or miss existing stop | **HIGH** | Does not directly submit orders to exchange, but stale/wrong TP/SL display misleads trading decisions. `mark_stale_orders_canceled` can corrupt order lifecycle state. |
| `positions` TP/SL fields (F6) | 3 (REST, WS, OrderManager) | NO | Display on dashboard + `total_tp_usdt`/`total_sl_usdt` in portfolio stats. NOT read for exchange order submission or modification. Not used by risk_engine for sizing. | **HIGH** | TP/SL prices are display-only (verified: templates read them, no code sends orders based on cached values). Stale display misleads human trader. Not CRITICAL because no automated path acts on them. |
| `orderbook_cache` (F7) | 2 (REST, WS/Plugin) | NO | `risk_engine.estimate_vwap_fill` → `calculate_slippage` → `calculate_position_size` → `est_size` (recommended position size) and `est_slippage` | **HIGH** | Stale orderbook → wrong VWAP fill estimate → wrong position size recommendation. Advisory (human reviews calculator output), not automated order execution. |
| `AccountRegistry sync readers` (F8) | Lock bypassed on reads | N/A | `get_active_sync` → `get_exchange()`/`_get_adapter()` → all REST calls including TP/SL creation and listen key | **HIGH** | All current callers are on asyncio event loop thread (NOT in ThreadPoolExecutor despite docstring). `dict()` copy prevents reference sharing. Latent defect: if any future caller runs from thread pool, `dict()` copy during concurrent write raises `RuntimeError`. On critical financial path but currently mitigated by asyncio cooperative model. |
| `_recalculate_portfolio` (F4, duplicate logic) | 2 implementations | N/A | Drawdown gates, weekly loss limits, exposure calculations | **HIGH** | Line-by-line diff verified: **functionally identical** (see §F4 Verification below). Only differences are comments and a dead variable `baseline` in state.py that is computed but never used. Not CRITICAL (no silent disagreement), but HIGH maintenance risk — any future edit to one copy without the other creates a CRITICAL silent disagreement. |
| `maker_fee/taker_fee` (F3, cross-container) | 3 containers | NO | `risk_engine.py:344` reads `exchange_info.maker_fee/taker_fee` → fee estimation in sizing calculator → `est_profit`/`est_loss`/`est_r` | **MEDIUM** | Fee discrepancy affects P&L estimates but not order execution. Exchange applies its own fees regardless of engine's estimate. |
| `ohlcv_cache` | 2 (REST, WS/Plugin) | NO | `risk_engine.calculate_atr_coefficient` → `atr_c` → position size scaling | **MEDIUM** | REST full-replace can overwrite a WS kline, losing one bar. ATR(14) and ATR(100) are tolerant of a single missing bar — impact on sizing is negligible. |
| `mark_price_cache` | 2 (REST, WS/Plugin) | NO | `DataCache.apply_mark_price` → position unrealized PnL → `total_equity` → drawdown/exposure calculations | **MEDIUM** | Both writers produce the same semantic value. WS fires at 1Hz, REST at 30s. The stale window is < 1 second. |
| `ws_status.latency_ms` | 2 (REST vs WS, different semantics) | NO | Display only | **LOW** |
| `bod_equity/sow_equity` | 3 (BOD reset, first-fetch, backfill) | Inside lock | Drawdown baseline, daily/weekly PnL | OK — ordered by design |
| `balance_usdt/total_equity` | 3 (REST, WS, Platform) | Inside lock | All financial calculations | OK — conflict-resolved via DataCache |

---

## F4 Verification: `_recalculate_portfolio` Diff

Textual diff of `AppState.recalculate_portfolio` (state.py:337-401) vs `DataCache._do_recalculate_portfolio` (data_cache.py:367-428):

**Functional differences: NONE.** All math, field assignments, threshold comparisons, and state transitions are identical.

**Non-functional differences:**
1. Method signature: `self` vs `(self, app_state)` parameter
2. Position source: `self.positions` vs `self._positions` — both resolve to `DataCache._positions` when DataCache is active
3. state.py has a dead variable `baseline = pf.dd_baseline_equity if pf.dd_baseline_equity > 0 else total_equity` (computed but never read — dead code). DataCache correctly omits it.
4. Comment verbosity: state.py has more explanatory comments; DataCache is terser.

**Verdict:** Currently identical. The risk is future divergence, not current disagreement. Severity stays **HIGH** (not CRITICAL).

---

## Drawdown & Weekly-Loss State Machine (previously missing)

These fields form the engine's risk gate state. They are NOT separate state machines with transition logic — they are derived labels recomputed on every portfolio recalculation from current ratios.

### Fields and ownership

| Field | Container | Purpose | Writers |
|-------|-----------|---------|---------|
| `pf.drawdown` | PortfolioStats | `(max_eq - cur_eq) / max_eq` | `_recalculate_portfolio` (both copies), `main.py:102` (crash recovery) |
| `pf.dd_baseline_equity` | PortfolioStats | Resets every BOD; basis for max_equity tracking | `perform_bod_reset` (:416), `DataCache.apply_account_update_rest` (:490, first-fetch), `main.py:101` (crash recovery) |
| `pf.dd_state` | PortfolioStats | `"ok"` / `"warning"` / `"limit"` | `_recalculate_portfolio` (both copies), `perform_bod_reset` (implicit via ok reset) |
| `pf.weekly_pnl_state` | PortfolioStats | `"ok"` / `"warning"` / `"limit"` | `_recalculate_portfolio` (both copies), `perform_bod_reset` (:424, resets to "ok" on Monday) |
| `pf.total_weekly_pnl` | PortfolioStats | `cur_eq - sow_equity` | `_recalculate_portfolio` (both copies), `perform_bod_reset` (:422, resets to 0) |
| `acc.max_total_equity` | AccountState | Intraday high watermark | `_recalculate_portfolio` (both copies), `perform_bod_reset` (:410), `DataCache.apply_account_update_rest` (:488, first-fetch), `main.py:97` (crash recovery) |
| `acc.min_total_equity` | AccountState | Intraday low | `_recalculate_portfolio` (both copies), `perform_bod_reset` (:411), `DataCache.apply_account_update_rest` (:489, first-fetch), `main.py:98` (crash recovery) |

### Financial path

`dd_state` and `weekly_pnl_state` are included in the risk calculator output (`risk_engine.py:425-426`) but are **NOT used as eligibility gates**. The calculator's `eligible` field is determined by: ATR volatility, position count, exposure limit, and correlated exposure. Drawdown and weekly-loss states are **advisory** — displayed on dashboard, pushed to Quantower plugin, and persisted to snapshots DB for analytics.

**DESIGN NOTE:** Drawdown and weekly-loss "limits" (`dd_state == "limit"`, `weekly_pnl_state == "limit"`) do NOT gate order submission or block the risk calculator in v2.3.1. This is **intentionally advisory** — v2.4 is planned to promote these to hard gates. See §v2.4 Readiness below.

### Crash recovery writer (previously missing)

`main.py:91-103` restores `total_equity`, `bod_equity`, `sow_equity`, `max_total_equity`, `min_total_equity`, `balance_usdt`, `dd_baseline_equity`, `drawdown` from the last DB snapshot. This is an additional writer for these fields that was not listed in §1.1 or §1.3. It fires once during startup before DataCache is initialized, so it cannot conflict with DataCache writers. **No finding** — ordering is safe.

---

## Containers §4 and §11: Confirmed No Findings

**ConnectionsManager** (`core/connections.py:201`): Single-owner pattern. All writes lock-protected. Sync readers (`get_sync`, `list_connections_sync`) bypass lock but run on asyncio thread only. No financial-decision path reads from this container (API keys for Finnhub/FRED/BWE are data providers, not order execution). **No findings.**

**api/cache.py globals**: Equity backfill cache is lock-protected (`_backfill_lock`). Funding rate cache (`_FUNDING_RATES`) uses a boolean flag guard (`_FUNDING_REFRESHING`) — not a lock, but adequate because asyncio is cooperative and the flag prevents concurrent refreshes. Funding rates are display-only (not used in sizing or risk decisions). **No findings.**

---

## Config State: Verified Immutable at Runtime

`config.py` loads all values from environment variables at import time. No code path mutates `config.*` attributes after import. All `config.` references in core/api code are read-only. `config.get_sector()` is a pure function. **No finding — config is not runtime-mutable state.**

---

## `total_realized` and `cashflows`: Verified Bug Status

### `total_realized` (AccountState field)

**Writers:** None after `__init__` (always 0.0).

**Readers that use the value in calculations or persistence:**
- `handlers.py:38` → `_build_account_snapshot()` → persisted to `account_snapshots.total_realized` in DB (always 0)
- `data_logger.py:136` → daily snapshot CSV (always 0)
- `db_snapshots.py:29,36` → INSERT into account_snapshots (always 0)

**Readers that display or query:**
- `db_analytics.py` does NOT query `total_realized` — analytics use `total_equity` and `daily_pnl`
- No template reads `total_realized`
- No route handler accesses it

**Verdict:** Silent bug. The DB column `total_realized` in `account_snapshots` always contains 0.0. No current calculation depends on it (drawdown uses `total_equity`, not `total_realized`). Anyone querying the DB directly for realized PnL gets zeros. **Severity: LOW** — no financial calculation affected, but the schema column is misleading. The actual realized PnL is tracked per-trade in `closed_positions.realized_pnl`, which IS correctly populated.

### `cashflows` (AccountState field)

**Writers:** None after `__init__` (always 0.0).

**Readers:** Zero. No code path reads `acc.cashflows`. Not persisted to DB. Not displayed in templates. Fully dead field. **Severity: LOW** — dead code, no impact.

---

## F1 Addendum: Boundary Violation

`platform_bridge._handle_hello` (an adapter) writes `app_state.active_account_id` directly (`platform_bridge.py:435,465`), bypassing `account_registry.set_active()`. This is both:
1. A multi-writer state bug (documented above as CRITICAL)
2. A **boundary violation** — an adapter directly mutates core state instead of going through the registry service

The correct design: PlatformBridge notifies AccountRegistry (single owner of account identity), which updates both `_active_id` and `app_state.active_account_id` via a single code path. Flagged for Phase 1c boundary map.

---

## v2.4 Readiness: dd_state / weekly_pnl_state as Hard Gates

### Current state reliability for gating

`dd_state` and `weekly_pnl_state` are plain string attributes on `app_state.portfolio`, recomputed on every `_recalculate_portfolio` call. They are **derived** from upstream values that flow through DataCache with conflict resolution:

```
acc.total_equity  ─→ pf.drawdown      ─→ dd_state
acc.max_total_equity ─┘     (max_eq - cur / max_eq)

acc.total_equity  ─→ pf.total_weekly_pnl_percent ─→ weekly_pnl_state
acc.sow_equity    ─┘     ((cur - sow) / sow)
```

**Writer analysis (same pattern as F4 duplication):**

| Write site | Location | When called |
|-----------|----------|-------------|
| `DataCache._do_recalculate_portfolio` | data_cache.py:416-428 | After every DataCache `apply_*` mutation (canonical path) |
| `AppState.recalculate_portfolio` | state.py:389-401 | `routes_accounts.py:138` (account switch), `handlers.py:212` (params update), `schedulers.py:310` (startup) |
| `perform_bod_reset` | state.py:424 | Monday midnight — resets `weekly_pnl_state` to "ok" |

**Reliability assessment:** The upstream values (`total_equity`, `sow_equity`, `max_total_equity`) are protected by DataCache's conflict resolution. The derived `dd_state`/`weekly_pnl_state` are recomputed atomically within each `_recalculate_portfolio` call — no TOCTOU between reading upstream and writing the state label. **However, the dual-writer duplication (F4) means the two copies could produce different state labels if called with different upstream values.** Before v2.4, the AppState copy should be removed — all callers should go through DataCache.

**v2.4 readiness concern:** If the duplicate `_recalculate_portfolio` in AppState is not eliminated before the gate is wired, the gate could consult a `dd_state` that was set by the AppState copy (which may have run with slightly stale upstream values) while the DataCache copy (running with fresher values) would have produced a different label.

### Trade-entry paths enumeration

**Finding: v2.3.1 has ZERO automated order-submission paths.** The engine is a monitoring/sizing tool; it does not place orders on any exchange. The adapter protocol (`core/adapters/protocols.py`) defines only read methods (`fetch_open_orders`, `fetch_order_history`, `fetch_positions`, `fetch_account`, etc.) — no `create_order`, `submit_order`, or `place_order` methods exist.

Current trade-entry paths (all external, human-initiated):

| # | Path | How trades enter the engine | Where a v2.4 gate would be inserted |
|---|------|---------------------------|--------------------------------------|
| 1 | **Quantower plugin** | Trader places order in Quantower → fill arrives via `platform_bridge._handle_fill` → recorded in DB | Before the plugin relays the order to the exchange (C# plugin side), or in `push_risk_state` payload so the plugin can gate locally |
| 2 | **Direct exchange** | Trader places order on Binance/Bybit web/app → order event arrives via WS `ORDER_TRADE_UPDATE` → recorded in DB | Not gateable from engine side — order is already placed when WS event arrives |
| 3 | **Risk calculator** | `routes_calculator.py` calls `run_risk_calculator()` → returns sizing recommendation → trader manually acts | `eligible` field in calculator output (already gates on ATR, exposure, position count). Add `dd_state`/`weekly_pnl_state` check to eligibility logic in `risk_engine.py:421` |

**v2.4 readiness concerns:**

1. **Gate must be applied in ≥2 places** — the calculator (path 3) and the plugin push payload (path 1). Path 2 (direct exchange) is ungatable from the engine. This is inherent to the architecture (engine monitors, doesn't execute).

2. **Plugin-side gate requires protocol addition** — `push_risk_state` already sends `dd_state`/`weekly_pnl_state` to the plugin. The C# plugin would need to read these fields and block order relay when state is "limit". This is a plugin-side change, not an engine change.

3. **Calculator gate is trivial** — add `pf.dd_state == "limit"` and `pf.weekly_pnl_state == "limit"` to the eligibility check at `risk_engine.py:421`. Single code change, single location.

### Read accessibility

`dd_state` and `weekly_pnl_state` are plain `str` attributes on `app_state.portfolio` (a `PortfolioStats` dataclass). Reading is a direct attribute access — **no async context, no lock, no await needed.** Any module that imports `app_state` can read them synchronously:

```python
from core.state import app_state
if app_state.portfolio.dd_state == "limit":
    ...  # block
```

**No v2.4 readiness concern on read accessibility.** The values are always available, always consistent with the last `_recalculate_portfolio` run, and readable from any context (sync, async, thread).

---

## Additional Findings

### F9: Dead variable `baseline` in AppState.recalculate_portfolio

**File:** `core/state.py:375`  
**Severity:** LOW (dead code)  
**Category:** 12 (dead code)

```python
baseline = pf.dd_baseline_equity if pf.dd_baseline_equity > 0 else total_equity
```

This variable is computed but never read. The drawdown calculation on line 383 uses `max_eq`, not `baseline`. The DataCache copy correctly omits this line. Harmless but misleading — suggests `baseline` is used when it isn't.

### F10: Misleading docstring on `get_active_sync`

**File:** `core/account_registry.py:113-114`  
**Severity:** LOW (comments — category 13)  
**Category:** 13 (comments/docstrings — misleading)

```python
def get_active_sync(self) -> Dict[str, Any]:
    """Synchronous accessor for use inside ThreadPoolExecutor (CCXT)."""
```

The docstring claims this method is designed for ThreadPoolExecutor use. Verified: all 5 callers (`exchange.py:63,84,111`, `ws_manager.py:39`, `ohlcv_fetcher.py:57`) run on the asyncio event loop thread, NOT inside ThreadPoolExecutor. The method provides no thread-safety guarantees (no lock, no atomic snapshot beyond `dict()` copy). If a future developer trusts the docstring and calls it from a thread, a `RuntimeError: dictionary changed size during iteration` is possible if `_cache` is being mutated by an async writer. The docstring should either be corrected to "Synchronous accessor — must be called from asyncio event loop thread" or the method should be made genuinely thread-safe.

---

## Lock Ordering Constraints

```
REQUIRED ORDER (if multiple locks needed):
  DataCache._lock  →  AppState._lock
  (never reverse)
```

This is documented in `data_cache.py:86` but NOT enforced at runtime. No deadlock detection exists. Currently, `AppState._lock` is "being phased out" (per docstring) — no code path acquires both locks simultaneously. But the constraint must be maintained as the migration continues.
