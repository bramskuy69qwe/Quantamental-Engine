# Per-File Findings: `core/risk_engine.py`

**Layer**: quant (434 lines)  
**Purpose**: ATR-based position sizing, VWAP slippage estimation, correlated exposure checks, full risk calculator output.  
**Financial path**: Direct — produces position size recommendations that traders act on.

---

## Audit Notes

**Stop-loss calculation**: `sl_price` is entirely user-supplied via HTML form (`routes_calculator.py:29`). No ATR-based stop placement logic exists in the codebase. The engine sizes positions *given* a user-chosen SL distance (`sl_pct = abs(sl_price - average) / average` at line 221); it never suggests where to place the stop. The sizing math (`base_size = atr_c * risk_usdt / sl_pct` at line 247) was verified correct for both long and short, including sign handling at lines 337/340.

---

## Findings

### RE-1: No health gate before sizing calculation — stale equity silently accepted

**File**: `core/risk_engine.py:308`, `api/routes_calculator.py:49`  
**Severity**: **CRITICAL**  
**Category**: 1 (financial correctness) + 6 (health observability / health-aware decisions)

**Observation**: `run_risk_calculator` reads `acc.total_equity` with a **zero-only** guard: `total_equity = acc.total_equity if acc.total_equity > 0 else 1.0`. This catches the startup case (equity not yet loaded → $1 fallback → obviously-tiny sizes a human would notice). But it does NOT catch the worse failure mode: **stale-but-nonzero equity**.

**Failure scenario**: Equity loaded at $10,000. WS disconnects, REST fails. Real equity drops to $5,000 (positions moved against). Calculator reads stale `acc.total_equity = $10,000` → sizes positions for 2× actual equity → overleveraged. The output looks reasonable (not obviously wrong), so the trader may not notice.

**Staleness info EXISTS but is unused**:
- `DataCache._account_version.applied_at` — monotonic timestamp of last accepted account update. The calculator never checks it.
- `app_state.ws_status.is_stale` — True when no WS data received in > `WS_FALLBACK_TIMEOUT` seconds. The calculator never checks it.
- `routes_calculator.py:49` calls `run_risk_calculator` with zero pre-flight freshness validation.

**Partial mitigation**: `DataCache.apply_mark_price` (line 584) continuously recalculates `total_equity = balance_usdt + total_unrealized` from live mark prices. If the MARKET WS stream stays alive (separate connection from USER stream), equity IS being mark-to-market updated even when account REST fails. But if both streams die and REST fails, equity freezes at last-known value with no warning.

**Suggested fix**: Add a pre-flight equity freshness check:
1. In `run_risk_calculator`: check `app_state._data_cache._account_version.applied_at`. If age > (e.g.) 120 seconds AND `app_state.ws_status.is_stale`, return ineligible with reason "Account data stale — equity may be inaccurate."
2. In `routes_calculator.py`: check `app_state.is_initializing` before calling the calculator.
3. Include `equity_age_ms` in the calculator output so the UI can display a staleness warning.

**Blast radius**: `risk_engine.py:308` (add age check), `routes_calculator.py:49` (add pre-flight), `data_cache.py` (expose `account_age_seconds` property). Template `calc_result.html` (display warning badge).

---

### RE-2: Orderbook-dependent sizing reads multi-writer cache without staleness check

**File**: `core/risk_engine.py:101,145,167,367`  
**Severity**: HIGH  
**Category**: 2 (state ownership) / 6 (health observability)  
**Cross-ref**: State map §1.7 (orderbook_cache 2 writers, no ordering)

**Observation**: `estimate_vwap_fill`, `calculate_slippage`, `calculate_one_percent_depth`, and `run_risk_calculator` all read `app_state.orderbook_cache.get(symbol)` without checking freshness. The orderbook could be minutes old if WS disconnected and REST fallback hasn't run. A stale orderbook produces wrong VWAP fill estimate → wrong slippage → wrong position size.

**Suggested fix**: Add `orderbook_age_ms` or `last_update_ts` to the cache entry. `calculate_slippage` should check age and either refuse or log a warning when the orderbook is older than (e.g.) 30 seconds.

**Blast radius**: `risk_engine.py` (4 call sites), `data_cache.py:apply_depth` (add timestamp), `exchange_market.py:fetch_orderbook` (add timestamp).

---

### RE-3: OHLCV cache read for ATR without freshness check

**File**: `core/risk_engine.py:64`  
**Severity**: MEDIUM  
**Category**: 6 (health observability)  
**Cross-ref**: State map §1.6 (ohlcv_cache 2 writers)

**Observation**: `calculate_atr_coefficient` reads `app_state.ohlcv_cache.get(symbol, [])`. If the cache is stale (WS kline stream disconnected), ATR is computed from old candles. ATR(14) and ATR(100) are relatively tolerant of a few missing bars, but a significantly stale cache (hours old) would produce misleading volatility estimates.

**Suggested fix**: Track last kline timestamp per symbol. If the last bar is more than 2× the ATR timeframe old, return `atr_c = None` with category "stale_data" instead of computing from stale candles.

**Blast radius**: `risk_engine.py` (1 call site), `data_cache.py:apply_kline` (add timestamp tracking).

---

### RE-4: `compute_funding_exposure` assumes 8h settlement interval

**File**: `core/analytics.py:297-300`  
**Severity**: MEDIUM  
**Category**: 3 (vendor neutrality)

**Observation**: Comment says "Binance settles every 8h, so 3 payments per day." This is true for Binance and Bybit linear perps, but other venues (dYdX: hourly, some DeFi: continuous) have different intervals. The 3× multiplier is hardcoded.

**Suggested fix**: Accept `settlements_per_day: int = 3` as a parameter, or derive from the active exchange's funding schedule via the adapter.

**Blast radius**: `analytics.py` (1 function), `routes_analytics.py` (1 caller).

---

### RE-5: `periods_per_year = 365` hardcoded for annualization

**File**: `core/analytics.py:35,53,75,103`  
**Severity**: MEDIUM  
**Category**: 3 (vendor neutrality)

**Observation**: Sharpe, Sortino, and excursion-based variants all use `periods_per_year: int = 365` as default. Correct for 24/7 crypto markets but wrong for TradFi equities (~252 trading days). The parameter IS configurable per-call, so no current bug exists — but the default bakes in a crypto assumption.

**Suggested fix**: No code change needed for v2.3.1. If TradFi venues are added, callers must pass `periods_per_year=252`. Consider deriving from active exchange's market hours.

**Blast radius**: All callers in `routes_analytics.py` (5 functions).

---

### RE-6: Beta uses population covariance while Sharpe/Sortino use sample variance

**File**: `core/analytics.py:190-192`  
**Severity**: LOW  
**Category**: 1 (financial correctness — minor)

**Observation**: `compute_beta` divides by `n` (population covariance), while `sharpe` and `sortino` divide by `n-1` (sample variance). This is a statistical inconsistency. For n > 30 the difference is negligible, but for small sample sizes (10-20 data points, which is allowed by the `if n < 10` guard), the difference can be material (~5-10%).

**Suggested fix**: Use `n-1` for sample covariance in `compute_beta`, consistent with the other functions.

**Blast radius**: `analytics.py` (1 function), `routes_analytics.py` (1 caller).

---

### RE-7: `regime_classifier.py` mixes pure classification with DB I/O

**File**: `core/regime_classifier.py` (entire file)  
**Severity**: MEDIUM  
**Category**: 8 (single-responsibility violation) / 3 (pure-logic vs I/O separation)

**Observation**: The pure classification function `classify_regime()` (lines 53-135) is correctly I/O-free and takes a signals dict as input. But the module also contains `classify_range()`, `compute_current_regime()`, and `_compute_stability()` — all async functions that read from and write to the database. The file mixes quant logic (classification rules) with service orchestration (DB reads, bulk writes, progress callbacks).

**Suggested fix**: Extract `classify_regime()` and `_lookup_nearest()` into a pure `regime_rules.py` module. Leave the async orchestration functions in `regime_classifier.py` (or rename to `regime_service.py`).

**Blast radius**: `regime_classifier.py` (split), `schedulers.py:322,388` (import path change), `api/routes_regime.py` (import path change).

---

### RE-8: Reconciler uses raw SQL and has vendor-specific timing assumption

**File**: `core/reconciler.py:21,98-103`  
**Severity**: MEDIUM  
**Category**: 3 (vendor neutrality) + 8 (SRP)

**Observation**:
1. Line 21: `_SETTLE_DELAY = 8` — "seconds after close for Binance to settle." This is a Binance-specific assumption. Bybit may have different settlement timing.
2. Lines 98-103: `db._conn.execute("SELECT DISTINCT symbol FROM exchange_history WHERE ...")` — raw SQL accessing `db._conn` private attribute, bypassing domain methods. Also embeds business logic in SQL: `trade_key NOT LIKE 'qt:%'` (filter out Quantower fills).

**Suggested fix**:
1. Make settle delay configurable per-exchange or derive from adapter.
2. Add `db.get_uncalculated_symbols()` domain method in `db_exchange.py` to replace raw SQL.

**Blast radius**: `reconciler.py` (2 changes), `db_exchange.py` (1 new method).

---

### RE-9: No unit tests for core sizing/ATR/slippage logic

**File**: `core/risk_engine.py`, `core/analytics.py`  
**Severity**: HIGH  
**Category**: 11 (test gaps on high-risk pure functions)

**Observation**: `_wilder_atr`, `calculate_atr_coefficient`, `estimate_vwap_fill`, `calculate_slippage`, `calculate_position_size`, and `run_risk_calculator` have zero test coverage. `tests/test_smoke.py` only verifies that modules import without error. These are pure functions with well-defined inputs and outputs — ideal for unit testing. A regression in ATR or slippage math would directly affect position sizing.

Similarly, `analytics.py` functions (Sharpe, Sortino, VaR, CVaR, beta) have no tests despite being pure math.

**Suggested fix**: Add `tests/test_risk_engine.py` and `tests/test_analytics.py` with known-answer tests for each function.

**Blast radius**: New test files only (no production code changes).

---

## Summary

| ID | Severity | Category | One-liner |
|----|----------|----------|-----------|
| RE-1 | **CRITICAL** | 1+6 (financial+health) | Stale-but-nonzero equity silently accepted by calculator — sizes positions for wrong equity, output looks plausible |
| RE-2 | HIGH | 2+6 (state/health) | Orderbook cache read for VWAP/slippage has no staleness check |
| RE-9 | HIGH | 11 (test gaps) | Zero test coverage on core sizing/ATR/slippage/analytics math |
| RE-3 | MEDIUM | 6 (health) | OHLCV cache read for ATR has no staleness check |
| RE-4 | MEDIUM | 3 (vendor) | Funding exposure hardcodes 8h settlement (Binance-specific) |
| RE-5 | MEDIUM | 3 (vendor) | Annualization uses 365 days (crypto-specific default) |
| RE-7 | MEDIUM | 8+3 (SRP/separation) | regime_classifier mixes pure classification with DB I/O |
| RE-8 | MEDIUM | 3+8 (vendor/SRP) | Reconciler: Binance settle delay, raw SQL bypassing domain methods |
| RE-6 | LOW | 1 (financial minor) | Beta uses population covariance vs sample variance elsewhere |
