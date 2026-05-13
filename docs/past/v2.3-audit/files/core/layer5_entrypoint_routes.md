# Per-File Findings: Layer 5 — Entrypoint + Routes

**Files**: `main.py`, `api/router.py`, `api/helpers.py`, `api/routes_*.py` (14 route files)  
**Pre-flagged**: SC-2 (ready despite failed startup), RE-1 (calculator no health gate), F1 (active_account_id writers).

---

## `main.py` (165 lines)

### MP-1: Crash recovery restores partial state — no `dd_state` or `weekly_pnl_state`

**File**: `main.py:91-103`  
**Severity**: MEDIUM  
**Category**: 9a (duplication — silent disagreement)

**Observation**: Crash recovery restores: `total_equity, bod_equity, sow_equity, max_total_equity, min_total_equity, balance_usdt, dd_baseline_equity, drawdown`. It does NOT restore `weekly_pnl_state`, `dd_state`, or `total_weekly_pnl`. These remain at their defaults ("ok", "ok", 0.0) until the first `_recalculate_portfolio` call — which happens during startup fetch, after which they're recomputed from the restored baselines. So this is safe IF startup fetch succeeds. If startup fetch fails (SC-2), the risk states stay at "ok" despite potentially being in "warning" or "limit" when the engine last shut down.

**v2.4 readiness**: When dd_state/weekly_pnl_state become hard gates, crash recovery must restore them too, or the engine restarts with gates open that should be closed.

**Blast radius**: `main.py:91-103` (add restoration of risk states from snapshot).

---

### MP-2: Account switch crash recovery restores fewer fields than startup

**File**: `main.py:91-103` vs `api/routes_accounts.py:119-125`  
**Severity**: **HIGH**  
**Category**: 9a (same-concept duplication — **silent disagreement**)

**Observation**: Two crash-recovery code paths restore from the same DB snapshot but with different field sets:

| Field | `main.py` startup | `routes_accounts.py` switch |
|-------|-------------------|-----------------------------|
| `total_equity` | Yes | Yes |
| `bod_equity` | Yes | Yes |
| `sow_equity` | Yes | Yes |
| `max_total_equity` | Yes | Yes |
| `min_total_equity` | Yes | **NO** |
| `balance_usdt` | Yes | **NO** |
| `dd_baseline_equity` | Yes | **NO** |
| `drawdown` | Yes | **NO** |

After an account switch, `min_total_equity` retains the previous account's value (wrong baseline for drawdown range display), `balance_usdt` stays at the old value until REST fetch, `dd_baseline_equity` is 0 (drawdown computes from wrong base), and `drawdown` is 0 (dashboard shows no drawdown for a brief window).

**Financial path**: Stale `dd_baseline_equity` → wrong drawdown calculation → wrong `dd_state` → dashboard shows wrong risk state during the switch window (between snapshot restore and first REST fetch).

**Suggested fix**: Extract a shared `restore_state_from_snapshot(account_id)` function called by both `main.py` and `routes_accounts.py`. One implementation, one field list.

**Blast radius**: `main.py:91-103`, `routes_accounts.py:119-125` → new shared function.

---

### MP-3: Lifespan shutdown doesn't cancel background tasks

**File**: `main.py:111-113`  
**Severity**: LOW  
**Category**: 7 (error handling)

**Observation**: Shutdown only calls `event_bus.close()` and `db.close()`. Background tasks spawned by `start_background_tasks()` (11 tasks including WS connections, polling loops) are not explicitly canceled. They'll get killed by the event loop shutdown, but WS connections may not close cleanly (no `ws_manager.stop()` call), and async generators may not finalize.

**Blast radius**: `main.py:111-113` (add `await ws_manager.stop()`), `schedulers.py` (add `stop_background_tasks()` that cancels all `_bg_tasks`).

---

### MP-4: Comment says "Binance REST/WS" — vendor name in entrypoint

**File**: `main.py:105`  
**Severity**: LOW  
**Category**: 13 (comments — misleading)

**Observation**: `# ── Background tasks (Binance REST/WS, schedulers, monitoring) ───`. The engine supports Binance + Bybit; the comment is stale.

---

## `api/routes_platform.py` (54 lines)

### RP-1: REST fallback endpoints expose private methods without authentication on 0.0.0.0

**File**: `api/routes_platform.py:33-49`, `main.py:5,8`  
**Severity**: **CRITICAL**  
**Category**: 7 (error handling) + 1 (financial correctness via external input)

**Observation**: `platform_event()` calls `platform_bridge._dispatch(body)` — a private method (underscore prefix). `platform_positions()` calls `platform_bridge._handle_position_snapshot(body)`. These REST endpoints accept arbitrary JSON and route it through the internal message dispatcher.

**Binding verification**: `main.py:5,8` documents the launch command as `uvicorn main:app --host 0.0.0.0 --port 8000`. The server binds to ALL network interfaces. Any device on the same network can:
- Push fake fills → trigger position refresh, write to DB, corrupt order lifecycle
- Push fake position snapshots → overwrite live position state via DataCache (Platform source = highest priority, always accepted)
- Push fake account state → overwrite equity/balance → wrong sizing recommendations
- Push fake `hello` → hijack `active_account_id` (F1) → REST calls routed to wrong account

**Financial path**: A POST to `/api/platform/event` with `{"type": "account_state", "total_equity": 0}` zeros out displayed equity. A POST with `{"type": "position_snapshot", "positions": []}` empties all positions. These write through DataCache with `UpdateSource.PLATFORM` priority (always accepted, overrides WS and REST). The attacker bypasses all conflict resolution because Platform is trusted as "broker truth."

**Suggested fix**: Add bearer token or API key authentication to `/api/platform/*` endpoints. At minimum, bind to `127.0.0.1` instead of `0.0.0.0` in the documented launch command, and add `--host` guidance to the README.

**Blast radius**: `routes_platform.py:33-49` (add auth check), `main.py` docstring (update default host). The `/ws/platform` WebSocket endpoint has the same exposure but is harder to exploit (requires WebSocket client).

---

## `api/routes_accounts.py` (391 lines)

### RA-1: Account switch calls `app_state.recalculate_portfolio()` (F4 duplicate path)

**File**: `api/routes_accounts.py:138`  
**Severity**: MEDIUM  
**Category**: 8 (SRP)  
**Cross-ref**: State map F4, Layer 2 HD-1

**Observation**: Same finding as HD-1 — calls the AppState duplicate `recalculate_portfolio` instead of DataCache canonical path.

---

### RA-2: Account switch writes `active_account_id` on app_state + registry separately

**File**: `api/routes_accounts.py:116-117`  
**Severity**: MEDIUM  
**Category**: 2 (state ownership)  
**Cross-ref**: State map F1

**Observation**: Two separate writes: `account_registry.set_active(account_id)` (line 116) then `app_state.active_account_id = account_id` (line 117). The registry updates its `_active_id` AND the DB `active_account_id` setting. Then `app_state` is updated separately. If any code between these two reads `app_state.active_account_id`, it sees the old value while the registry already says the new value. In practice, no yield exists between lines 116-117, so this is safe in asyncio — but it confirms the F1 dual-ownership pattern.

---

## `api/routes_calculator.py` (80 lines)

### RC-1: No readiness/staleness check before calculator run

**File**: `api/routes_calculator.py:49`  
**Severity**: — (covered by RE-1 CRITICAL)  
**Cross-ref**: RE-1

Confirmed: `run_risk_calculator()` called with no pre-flight check for `is_initializing`, equity staleness, or adapter health. Already documented as RE-1 in Layer 1.

---

## `api/helpers.py` (157 lines)

No findings. Pure formatting utilities (`_fmt`, `_hold_time`, `_ms_to_local`, `_paginate_list`) with no state mutation, no vendor leakage, no security concerns. `_ctx()` reads app_state for template context — correct and thin.

---

## `api/router.py` (40 lines)

No findings. Pure router composition — includes 14 sub-routers in order.

---

## Remaining route files (11 files, ~2,200 LOC)

Spot-checked: `routes_dashboard.py`, `routes_analytics.py`, `routes_history.py`, `routes_orders.py`, `routes_params.py`, `routes_regime.py`, `routes_news.py`, `routes_backtest.py`, `routes_connections.py`, `routes_models.py`, `routes_config.py`.

**Pattern**: All routes are thin handlers — read from `app_state` or `db`, pass to templates. No business logic beyond pagination/filtering. No vendor-specific field names (templates read domain model attributes).

**One pattern across all routes**: No route checks `is_initializing` or data freshness before serving. During startup, a user loading the dashboard sees stale/zero data without warning. The `/api/ready` endpoint exists (routes_dashboard.py:281) but templates don't gate on it — they render whatever state is available.

---

## Summary

| ID | Severity | Category | File | One-liner |
|----|----------|----------|------|-----------|
| MP-2 | **HIGH** | 9a (duplication — **silent disagreement**) | main:91 vs routes_accounts:119 | Crash recovery restores different fields at startup vs account switch — switch misses `min_total_equity, balance_usdt, dd_baseline_equity, drawdown` |
| RP-1 | **CRITICAL** | 7+1 (security+financial) | routes_platform:33-49 | REST fallback on 0.0.0.0 exposes `_dispatch`/`_handle_position_snapshot` without auth — any device on network can overwrite position/account state via Platform-priority DataCache path |
| MP-1 | MEDIUM | 9a (duplication) | main:91-103 | Crash recovery doesn't restore `dd_state`/`weekly_pnl_state` — safe today, v2.4-readiness gap |
| RA-1 | MEDIUM | 8 (SRP) | routes_accounts:138 | Calls AppState duplicate `recalculate_portfolio` (F4 cross-ref) |
| RA-2 | MEDIUM | 2 (state) | routes_accounts:116-117 | Dual writes to registry + app_state for active_account_id (F1 cross-ref) |
| MP-3 | LOW | 7 (error) | main:111-113 | Shutdown doesn't cancel background tasks or close WS |
| MP-4 | LOW | 13 (comments) | main:105 | Comment says "Binance" but engine supports Binance + Bybit |
