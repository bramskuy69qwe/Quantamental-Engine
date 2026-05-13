# Per-File Findings: Layer 3 — Services

**Files**: `schedulers.py`, `handlers.py`, `monitoring.py`, `data_logger.py`, `backtest_runner.py`  
**Pre-flagged**: Boundary map (vendor leakage in schedulers), inventory (backtest_runner reclassified to service).

---

## `core/schedulers.py` (478 lines)

### SC-1: BOD scheduler crashes on last day of 31-day months

**File**: `core/schedulers.py:67-69`  
**Severity**: **CRITICAL**  
**Category**: 1 (financial correctness — miscounted drawdown, stale risk state) + 7 (error handling)

**Observation**: The midnight calculation uses `datetime.replace(day=day+1)`:
```python
midnight = now.replace(hour=0, minute=0, second=5, microsecond=0)
if now >= midnight:
    midnight = midnight.replace(day=midnight.day + 1)
```
On the last day of any 31-day month (Jan 31, Mar 31, May 31, Jul 31, Aug 31, Oct 31, Dec 31), `midnight.replace(day=32)` raises `ValueError`. The task crashes. `_spawn` logs the error but does NOT restart the task. BOD resets are missed for the rest of the engine's uptime.

**Financial path**: `perform_bod_reset` sets: `bod_equity` (daily PnL baseline), `max_total_equity`/`min_total_equity` (drawdown tracking), `dd_baseline_equity`, `daily_realized`/`daily_unrealized` (reset to 0). If BOD doesn't fire: drawdown uses stale multi-day baseline → drawdown percentage is wrong → `dd_state` is wrong → weekly PnL on Monday reset doesn't fire. Dashboard shows cumulative multi-day PnL as "daily" PnL.

**Suggested fix**: `midnight += timedelta(days=1)` instead of `midnight.replace(day=...)`.

**Blast radius**: `schedulers.py:69` (1 line fix).

---

### SC-2: All initial fetches can fail yet engine marks itself ready

**File**: `core/schedulers.py:258-329`  
**Severity**: MEDIUM  
**Category**: 6 (health observability)

**Observation**: `_startup_fetch` runs `fetch_exchange_info`, `fetch_account`, `fetch_positions` each in separate try/except blocks (correct — one failure doesn't block others). But if ALL three fail (e.g., network down), the engine still reaches `app_state.is_initializing = False` (line 329) with zero equity, zero positions. No aggregate health check gates the "ready" signal.

Combined with RE-1: the calculator is now accepting requests with stale/zero state.

**Suggested fix**: After startup fetch, check `acc.total_equity > 0` before marking ready. Or add a `startup_health_ok` flag that `/api/ready` checks.

**Blast radius**: `schedulers.py:329` (add guard), `routes_dashboard.py:281` (`/api/ready` could check additional conditions).

---

### SC-3: Pre-flagged vendor leakage in scheduler

**File**: `core/schedulers.py:148,183,378-379`  
**Severity**: HIGH  
**Category**: 3 (vendor neutrality)  
**Cross-ref**: Boundary map — vendor leakage in core

Already documented: `config.EXCHANGE_NAME.lower()` as order/fill source string; `fetch_binance_oi()`, `fetch_binance_funding()` vendor-named methods. Confirmed at file:line.

---

## `core/handlers.py` (213 lines)

### HD-1: `handle_params_updated` calls AppState duplicate recalculate_portfolio

**File**: `core/handlers.py:212`  
**Severity**: MEDIUM  
**Category**: 8 (SRP)  
**Cross-ref**: State map F4

**Observation**: `app_state.recalculate_portfolio()` calls the AppState copy, not the DataCache canonical path. Per F4, both are functionally identical today, but this is the wrong canonical entry point. The DataCache copy is the intended single path for all portfolio recalculations.

**Suggested fix**: Replace with `app_state._data_cache._recalculate_portfolio()` or better: trigger a DataCache apply that includes recalculation.

**Blast radius**: `handlers.py:212` (1 call site).

---

### HD-2: Function attribute `_prev_syms` on handler for state tracking

**File**: `core/handlers.py:109-112`  
**Severity**: LOW  
**Category**: 4 (hidden state)

**Observation**: `handle_positions_refreshed._prev_syms` stores a set as a function attribute for cross-call state tracking. Non-standard Python pattern. Works but makes the function non-reentrant and hard to test in isolation. The state is invisible to any monitoring.

**Suggested fix**: Move to a class or module-level variable with explicit naming.

**Blast radius**: `handlers.py:109-112` only.

---

## `core/monitoring.py` (131 lines)

### MN-1: Monitoring checks are thin — missing adapter, DB, plugin, and data-freshness health

**File**: `core/monitoring.py` (entire file)  
**Severity**: HIGH  
**Category**: 6 (health observability)

**Observation**: MonitoringService runs 3 checks every 60 seconds:
1. P&L anomaly (equity drop > 1% in 5 min)
2. WS staleness (last_update > 45s and not in fallback)
3. Position count mismatch (in-memory vs last DB snapshot)

**Missing checks** per the audit spec category 6:

| Check | Description | Why it matters |
|-------|-------------|----------------|
| Adapter REST health | Can we reach the exchange REST API? Last successful call? | REST failures → stale account/position data → RE-1 |
| Market WS stream health | Are klines and mark prices arriving? Last kline timestamp? | Silent market WS death → mark prices freeze → stale equity |
| DB write health | Last successful DB write? Connection alive? | DB failure → silently dropped snapshots → EB-2 |
| Plugin connection health | Is Quantower connected? Last message? | Plugin disconnect → engine switches to standalone but no alert |
| Regime data freshness | Last regime classification? Signal age? | Stale regime → wrong multiplier → wrong sizing |
| Event bus handler health | Any handler failing persistently? | Compounds with EB-2 |

**Suggested fix**: Add checks for each. The adapters and DataCache already track timestamps (`_positions_version.applied_at`, `_account_version.applied_at`, `ws_status.last_update`). Monitoring needs to read and alert on them.

**Blast radius**: `monitoring.py` (add 4-6 new check methods). No other files need changes — the data is already available.

---

## `core/backtest_runner.py` (627 lines)

### BT-1: Duplicated sizing logic — ATR coefficient and base_size formula

**File**: `core/backtest_runner.py:89-165`  
**Severity**: MEDIUM  
**Category**: 9a (same-concept duplication — currently agrees)

**Observation**: Three functions duplicate logic from `risk_engine.py`:

| Backtest function | Risk engine equivalent | Agreement? |
|-------------------|----------------------|------------|
| `_wilder_atr` (line 89) | `risk_engine._wilder_atr` (line 28) | Same algorithm, different signature (returns list vs single float) |
| `_atr_coefficient` (line 115) | `calculate_atr_coefficient` (line 52) | Identical thresholds and cap. Verified: same categories, same 0.2/0.6/1.0 boundaries |
| `_size_position` (line 142) | `calculate_position_size` (line 190) | Core formula `base_size = (atr_c * risk_usdt) / sl_pct` matches. Regime multiplier applied at different point but mathematically equivalent (both multiplicative) |

**Slippage model intentionally differs**: Live engine uses VWAP walk on live orderbook. Backtest uses synthetic model `_simulate_slippage` (volume-proportional, line 132-139). This is by design — backtest can't use live orderbook.

**Verified agreement**: The core sizing math produces identical results given the same inputs. The duplication is a maintenance risk: a change to `risk_engine.py` that isn't mirrored in `backtest_runner.py` would silently diverge backtest results from live behavior.

**Suggested fix**: Extract shared pure math (`_wilder_atr`, `_atr_coefficient`, `_sl_pct`, base_size formula) into a `core/sizing_math.py` module imported by both. The slippage model remains separate (live vs synthetic).

**Blast radius**: `risk_engine.py` (import shared functions), `backtest_runner.py` (import shared functions), new `sizing_math.py`.

---

### BT-2: `_simulate_slippage` falls back to fee rate when no volume data

**File**: `core/backtest_runner.py:132-139`  
**Severity**: LOW  
**Category**: 10 (naming — misleading) + 1 (financial minor)

**Observation**: `if avg_volume_usdt <= 0: return fee_rate`. When volume data is missing, slippage defaults to the fee rate. This conflates two different costs — slippage is market impact, fee is commission. The result: positions are sized as if slippage equals the fee (typically 0.02-0.05%), which underestimates real slippage for illiquid pairs.

**Suggested fix**: Return 0 or a configurable default slippage when volume is missing, not the fee rate.

**Blast radius**: `backtest_runner.py:138` (1 line).

---

### BT-3: `_lookup_signal` duplicated from `regime_classifier.py`

**File**: `core/backtest_runner.py:607-619`, `core/regime_classifier.py:216-228`  
**Severity**: LOW  
**Category**: 9a (same-concept duplication — identical)

**Observation**: Identical binary search function in both files. Both search a sorted list of `{date, value}` dicts for the nearest value at or before a target date. Line-for-line match.

**Suggested fix**: Extract to a shared utility (e.g., `core/signal_utils.py`).

**Blast radius**: `backtest_runner.py`, `regime_classifier.py` (import change only).

---

## `core/data_logger.py` (244 lines)

### DL-1: Synchronous file I/O on the asyncio event loop

**File**: `core/data_logger.py:37-43`  
**Severity**: LOW  
**Category**: 5 (async/concurrency)

**Observation**: `_append_csv` does `open(path, "a")` — synchronous disk I/O. Called from `take_daily_snapshot` and `take_monthly_snapshot`, which are invoked from the asyncio event loop via `_bod_scheduler`. For small CSV snapshots (<1KB), the block is negligible (<1ms). `export_all_to_excel` (line 222) IS async but uses pandas internally, which does synchronous I/O.

**Suggested fix**: Low priority. If snapshots grow large, wrap in `run_in_executor`. Current size makes this cosmetic.

**Blast radius**: `data_logger.py` only.

---

## Summary

| ID | Severity | Category | File | One-liner |
|----|----------|----------|------|-----------|
| SC-1 | **CRITICAL** | 1+7 (financial+error) | schedulers:67-69 | BOD scheduler crashes on last day of 31-day months (`datetime.replace(day=32)`) — drawdown miscounted against wrong baseline for rest of uptime. 1-line fix. |
| MN-1 | **HIGH** | 6 (health) | monitoring.py | Only 3 of ~9 needed health checks implemented — no adapter REST, market WS, DB, plugin, regime, or handler health. **v2.4-readiness prerequisite**: health-aware gating requires the monitor to know health. |
| SC-3 | HIGH | 3 (vendor) | schedulers:148,183,378 | Pre-flagged vendor leakage: `fetch_binance_oi()`, `fetch_binance_funding()`, exchange name in source strings |
| SC-2 | MEDIUM | 6 (health) | schedulers:258-329 | All startup fetches can fail yet engine marks ready — compounds with RE-1. **v2.4-readiness prerequisite**: engine must refuse "ready" when data is missing before gate can trust state. |
| HD-1 | MEDIUM | 8 (SRP) | handlers:212 | Calls AppState duplicate `recalculate_portfolio` instead of DataCache canonical path (F4) |
| BT-1 | MEDIUM | 9a (duplication) | backtest_runner:89-165 | ATR/sizing logic duplicated from risk_engine — currently agrees but maintenance risk |
| BT-2 | LOW | 10+1 (naming+financial) | backtest_runner:138 | Slippage falls back to fee rate when volume missing — conflates two costs |
| BT-3 | LOW | 9a (duplication) | backtest_runner:607 | `_lookup_signal` identical to `regime_classifier:216` — extract candidate |
| HD-2 | LOW | 4 (hidden state) | handlers:109-112 | Function attribute `_prev_syms` for cross-call state — non-standard pattern |
| DL-1 | LOW | 5 (async) | data_logger:37-43 | Synchronous file I/O on event loop — negligible for current file sizes |
