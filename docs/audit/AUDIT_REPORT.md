# Quantamental Engine v2.3.1 — Audit Report

**Date**: 2026-05-07  
**Branch**: `audit/v2.3.1`  
**Auditor**: Claude Opus 4.6  
**Scope**: Full read-only deep audit of ~13,900 LOC (78 Python files, 48 HTML templates)

---

## Executive Summary

The Quantamental Risk Engine is a well-structured FastAPI monitoring and sizing tool for crypto perpetual futures, with a partially-complete hexagonal architecture. The adapter layer (Binance + Bybit) exists and works for two crypto-perp venues. DataCache provides single-writer conflict resolution for position state. The codebase is clean by route-level standards — thin handlers, domain models, no vendor JSON in templates.

**5 CRITICAL findings** require immediate attention:

| # | ID | File:line | One-liner |
|---|-----|-----------|-----------|
| 1 | **RE-1** | risk_engine:308 | Stale-but-nonzero equity silently accepted by calculator — sizes positions for wrong equity with plausible-looking output |
| 2 | **SC-1** | schedulers:69 | BOD scheduler crashes on last day of 31-day months (`day+1` overflow) — drawdown miscounted for rest of uptime. **1-line fix.** |
| 3 | **OM-1** | ws_manager:220 / db_orders:57 | WS order path bypasses OrderManager state machine — DB `ON CONFLICT` overwrites status unconditionally, can regress filled→new |
| 4 | **PB-1/F1** | platform_bridge:435,465 | Adapter writes `active_account_id` directly, bypassing AccountRegistry — can route REST calls to wrong account |
| 5 | **RP-1** | routes_platform:33-49 | Unauthenticated REST endpoints on 0.0.0.0 accept arbitrary JSON → overwrite position/account state via Platform-priority DataCache path |

**17 HIGH findings** span state ownership races, vendor leakage preventing multi-exchange operation, missing health checks, and test gaps on core sizing math.

**25 MEDIUM**, **20 LOW** findings cover separation of concerns, duplication, naming, dead code, and error handling.

---

## Structural Redesign Candidates

These are places where the right fix is a small redesign, not a patch. Each names the affected system, current structure, and proposed shape.

### SR-1: OrderManager single-writer enforcement (OM-R1)

**Affected**: Order lifecycle state, TP/SL display  
**Current**: Two DB write paths — OrderManager validates transitions; ws_manager bypasses directly to `upsert_order_batch`. Three external modules write `_open_orders` cache.  
**Proposed**: Split OrderManager into `process_order_snapshot` (validates + cancels stale) and `process_order_update` (validates only). Both share `_validate_and_upsert()`. Add `refresh_cache()` method — no external direct assignment.  
**Depends on**: Nothing. Can land first.  
**Blast radius**: `order_manager.py`, `ws_manager.py:190-227`, `schedulers.py:128-156,456`, `db_orders.py:57` (timestamp guard).

### SR-2: AccountRegistry as single owner of account identity (F1 fix)

**Affected**: `active_account_id` across AppState + AccountRegistry  
**Current**: 3 writers (`routes_accounts`, `platform_bridge._handle_hello`, `state._init`), 2 containers, no sync.  
**Proposed**: AccountRegistry is the sole owner. `app_state.active_account_id` becomes a read-through property backed by `account_registry.active_id`. `platform_bridge._handle_hello` calls `account_registry.set_active()` instead of writing `app_state` directly.  
**Depends on**: Nothing. Can land first.  
**Blast radius**: `state.py` (property), `platform_bridge.py:435,465`, `routes_accounts.py:117,149`, all 40+ readers (no change — they read the property).

### SR-3: Crash recovery consolidation (MP-2 + F4 pattern)

**Affected**: State restoration at startup and account switch  
**Current**: `main.py:91-103` restores 8 fields; `routes_accounts.py:119-125` restores 4 fields. Same pattern as F4 (duplicate `_recalculate_portfolio`). Two paths doing similar things differently.  
**Proposed**: Extract `restore_state_from_snapshot(account_id)` → called by both. Eliminate `AppState.recalculate_portfolio` (F4) — all callers route through DataCache.  
**Depends on**: SR-2 (account identity must be settled first).  
**Blast radius**: `main.py:91-103`, `routes_accounts.py:119-138`, `handlers.py:212`, `schedulers.py:310`, `state.py:337-401` (delete duplicate).

### SR-4: exchange.py collapse (R1)

**Affected**: `exchange.py` + `exchange_market.py` + `exchange_income.py` (1,046 LOC)  
**Current**: 3 modules using raw CCXT via `get_exchange()`, re-exporting adapter functions, holding legacy singleton. 16 importers.  
**Proposed**: Migrate remaining raw-CCXT methods to `ExchangeAdapter` protocol. Add `fetch_orderbook`, `fetch_mark_price` to protocol. `exchange.py` becomes thin facade. Eliminate `_exchange` singleton and `_REST_POOL`.  
**Depends on**: SR-1 (OrderManager must be consolidated first so the routing change doesn't interact with the state machine fix).  
**Blast radius**: 16 importers, both adapter implementations, `protocols.py`.

### SR-5: platform_bridge split (R2)

**Affected**: `platform_bridge.py` (810 LOC, 6 identified issues)  
**Current**: Monolith: WS server + message parser + state sync + outbound push + raw SQL + boundary violation.  
**Proposed**: 4 modules: `platform_ws_server.py`, `platform_parser.py`, `platform_sync.py` (routes through AccountRegistry/DataCache/OrderManager), `platform_push.py`.  
**Depends on**: SR-2 (F1 fix), SR-1 (OrderManager consolidation).  
**Blast radius**: 5 direct importers.

### SR-6: Adapter routing consolidation (R5 + WS-1/WS-2/EM-1)

**Affected**: `ws_manager.py` market data parsing, `exchange_market.py` raw CCXT calls  
**Current**: Adapter has parse methods; ws_manager ignores them for market data. exchange_market uses raw CCXT for 4 functions.  
**Proposed**: Wire ws_manager market handlers through WSAdapter `parse_*` methods. Wire exchange_market through `_get_adapter()`.  
**Depends on**: SR-4 (protocol must have all needed methods first).  
**Blast radius**: `ws_manager.py:375-405,138`, `exchange_market.py:44,63,246,260`.

### SR-7: Protocol vendor-neutrality (R6)

**Affected**: `core/adapters/protocols.py`, both adapter implementations  
**Current**: Crypto-perp-shaped: single-currency account, listen_key on REST adapter, reduce_only/position_side as required fields, 5 order types.  
**Proposed**: Move crypto-specific to optional protocols. Add `currency` field. Make `reduce_only: Optional[bool] = None` (Q3 resolved: data-only, no downstream consumer — vendor-specific data stored but not acted on; adapters set when present, core never reads), `position_side: Optional[str] = None`. Add `fee_source: Literal["live", "default"]` indicator (Q2/AD-1: adapter compliance variance). Define adapter-neutral error types.  
**Depends on**: Should land BEFORE SR-4 and SR-6 (otherwise adapter-level fixes get re-touched).  
**Blast radius**: Both adapter implementations, `exchange.py`, `exchange_factory.py`, `ws_manager.py`, `data_cache.py`, `order_manager.py`.

### SR-8: Regime data source ports (R3)

**Affected**: `regime_fetcher.py` (558 LOC), `schedulers.py` callers  
**Current**: Single class with vendor-named methods (`fetch_binance_oi`, `fetch_vix`), hardcoded CCXT class, hardcoded FRED URLs.  
**Proposed**: `DataSourcePort` protocol. Implement: `FredDataSource`, `YFinanceDataSource`, `ExchangeDataSource`.  
**Depends on**: SR-4 (exchange adapter must have OI/funding methods).  
**Blast radius**: `regime_fetcher.py`, `schedulers.py:357-384`.

---

## Recommended Phase 2 Execution Order

### Bucket 1: Cheap CRITICAL fixes (can land immediately, single-commit each)

| Finding | Fix | Effort |
|---------|-----|--------|
| **SC-1** (BOD day overflow) | `midnight += timedelta(days=1)` | 1 line |
| **RP-1** (unauthenticated endpoints) | Add bearer token check to `/api/platform/*`; change default host to `127.0.0.1` | ~20 lines |
| **RE-1** (stale equity in calculator) | Add equity freshness check using `_account_version.applied_at` + `ws_status.is_stale` | ~15 lines |

### Bucket 2: Foundation structural redesigns (other fixes depend on these)

**Sequence**: SR-1 → SR-2 → SR-3 (dependency chain)

| Redesign | Why first | Effort |
|----------|-----------|--------|
| **SR-1** (OrderManager split) | Fixes OM-1 CRITICAL. Required before SR-4/SR-5 to avoid interaction. | ~100 lines |
| **SR-2** (AccountRegistry single owner) | Fixes F1/PB-1 CRITICAL. Required before SR-3/SR-5. | ~30 lines |
| **SR-3** (Crash recovery consolidation) | Fixes MP-2 HIGH + F4. Requires SR-2. | ~50 lines |

### Bucket 3: v2.4 prerequisites (required before gating work)

**Sequence**: SR-7 → SR-4 → SR-6 → SR-8 → MN-1 → SC-2 → MP-1

| Item | Why prerequisite | Depends on |
|------|-----------------|------------|
| **SR-7** (protocol redesign) | Must land before adapter-level fixes or they get re-touched | Nothing |
| **SR-4** (exchange.py collapse) | Consolidates adapter usage; adds missing protocol methods | SR-7 |
| **SR-6** (adapter routing) | Wires ws_manager/exchange_market through adapter | SR-4 |
| **SR-8** (regime data ports) | Vendor-neutral data sources for regime signals | SR-4 |
| **MN-1** (monitoring expansion) | Health-aware gating requires the monitor to know health | Nothing |
| **SC-2** (ready-state gating) | Engine must refuse "ready" when data is missing | MN-1 |
| **MP-1** (crash recovery risk states) | dd_state/weekly_pnl_state must survive restart | SR-3 |
| Adapter-neutral errors | Every `except ccxt.*` needs surgery without this | SR-7 |

### Bucket 4: HIGH cleanup (dependency order)

| Finding | Depends on |
|---------|-----------|
| OM-2 (TOCTOU snapshot/cancel) | SR-1 |
| OM-3 (_open_orders direct assignment) | SR-1 |
| OM-4 (allow_cancel_all mass-cancel) | SR-1 |
| WS-1, WS-2, EM-1 (adapter bypass) | SR-4, SR-6 |
| RF-1, RF-2 (regime vendor leakage) | SR-8 |
| AD-1 (Bybit hardcoded fees) | SR-7 |
| RE-2 (orderbook staleness) | Nothing |
| RE-9 (test gaps) | Nothing |
| EB-2 (handler error swallowing) | Nothing |
| PB-6 (platform_bridge split) | SR-5 |

### Bucket 5: MEDIUM/LOW (can land alongside unrelated work)

No dependency constraints. Group by file proximity to minimize PR churn. Recommended batches:
- **State cleanup**: ST-1 (dead lock), ST-2 (setter raise), F9 (dead baseline), F10 (docstring), dead fields (total_realized, cashflows, pre_trade_log)
- **Duplication extraction**: BT-1 (sizing math), BT-3 (_lookup_signal), EI-2 (unwrapped normalization)
- **Error handling**: EB-1 (sequential dispatch), DB-2 (pre-init guard), DB-3 (migration string matching), OS-1 (unknown status logging), NF-2 (BWE backoff cap), PB-7 (bare except)
- **Vendor cosmetics**: WS-3 (source string), WS-4 (dead fallback URLs), MP-4 (comment), EX-1 (legacy singleton cleanup)

---

## CRITICAL Findings

| ID | File:line | Category | Finding |
|----|-----------|----------|---------|
| RE-1 | risk_engine:308, routes_calculator:49 | 1+6 (financial+health) | Stale-but-nonzero equity silently accepted — sizes for wrong equity. `_account_version.applied_at` exists but calculator never checks it. |
| SC-1 | schedulers:69 | 1+7 (financial+error) | `midnight.replace(day=day+1)` → ValueError on 31st of 7 months/year. Task dies, BOD reset never fires again. Drawdown miscounted. 1-line fix. |
| OM-1 | ws_manager:220, db_orders:57 | 1+2 (financial+state) | WS order writes bypass OrderManager `validate_transition()`. DB `ON CONFLICT` overwrites status unconditionally. Stale WS message can regress filled→new. Structural redesign candidate SR-1. |
| PB-1/F1 | platform_bridge:435,465 | 1+3 (financial+boundary) | Adapter writes `app_state.active_account_id` directly, bypassing AccountRegistry. Can diverge from `account_registry._active_id` → REST calls routed to wrong account. Structural redesign candidate SR-2. |
| RP-1 | routes_platform:33-49 | 7+1 (security+financial) | Unauthenticated REST endpoints on `0.0.0.0`. Any network device can POST fake fills/positions/account state via Platform-priority DataCache path (always accepted, overrides WS and REST). |

## HIGH Findings

| ID | File:line | Category | Finding |
|----|-----------|----------|---------|
| OM-2 | order_manager:48-83 | 2+5 | TOCTOU: WS order arriving between snapshot fetch and stale-cancel gets falsely canceled |
| OM-3 | ws_manager:223, schedulers:456 | 2+8 | `_open_orders` directly assigned from outside OrderManager — ownership violation |
| OM-4 | order_manager:73-80 | 7+1 | `allow_cancel_all` mass-cancels DB orders when plugin sends orders with only terminal IDs |
| EB-2 | event_bus:93-94 | 7 | Handler errors silently swallowed — failed snapshot handler → stale crash recovery |
| MP-2 | main:91 vs routes_accounts:119 | 9a | Crash recovery silent disagreement — switch restores 4 of 8 fields (misses drawdown baseline) |
| RE-2 | risk_engine:101,145,167,367 | 2+6 | Orderbook cache read for VWAP/slippage has no staleness check |
| RE-9 | risk_engine, analytics | 11 | Zero test coverage on core sizing/ATR/slippage/analytics math |
| WS-1 | ws_manager:375-405 | 3 | Market data parsed as raw Binance JSON — WSAdapter parse methods exist but ignored. Cheap wiring fix. **Hard blocker for Bybit WS production deployment.** |
| WS-2 | ws_manager:138 | 3 | Raw Binance `execution_type` read outside adapter — drives fill detection. Cheap wiring fix. |
| EM-1 | exchange_market:44,63,246,260 | 3 | Uses raw CCXT instead of adapter for OHLCV/orderbook/mark price. Cheap wiring fix. |
| RF-1 | regime_fetcher:291,297,364 | 3 | Vendor-named methods, hardcoded Binance CCXT class and fapi endpoints |
| RF-2 | regime_fetcher:52-175 | 3 | No port interface for FRED/yfinance — financial path to sizing via regime multiplier |
| PB-6 | platform_bridge (entire) | 8 | 810-line monolith: 4 responsibilities + 6 identified issues. Structural redesign SR-5. |
| MN-1 | monitoring.py | 6 | Only 3 of ~9 needed health checks. v2.4-readiness prerequisite. |
| AD-1 | bybit/rest_adapter:82-83 | 1+3 | Hardcoded default fees — overestimates costs (conservative direction). Adapter compliance variance meta-finding. |
| SC-3 | schedulers:148,183,378 | 3 | Pre-flagged vendor leakage: vendor-named methods in orchestrator |
| AccountRegistry sync readers | account_registry:113-115 | 2 | `get_active_sync` lock bypass on financial-critical path. Currently asyncio-safe; latent defect. |

## MEDIUM Findings (25)

State: DC-1, ST-2, RA-1, RA-2, MP-1, SC-2.  
Vendor/boundary: WS-3, EX-1, EI-1, NF-1, OF-1, OF-2, PB-2, PB-3, PB-4, AD compliance variance, **CF-1** (hardcoded URLs/origins in fetchers — should live in ConnectionsManager; see Q4 resolution).  
SRP: HD-1, RE-7, RE-8.  
Error: OM-5, EB-1, RP-1 WS endpoint (same exposure as REST).  
Analytics: RE-3, RE-4, RE-5.

## LOW Findings (20)

Dead code / remove: ST-1, WS-4, F9 (baseline variable), **total_realized + cashflows** (Q1 resolved: remove fields, replace with `get_realized_pnl(account_id, period)` query-time aggregation from `closed_positions`), pre_trade_log in-memory list.  
Duplication: EX-2, BT-2, BT-3, EI-2.  
Error handling: DB-2, DB-3, OS-1, NF-2, PB-7, MP-3.  
Naming/comments: RE-6 (beta covariance), F10 (docstring), MP-4, PB-5, AD-3.  
Fragility: DC-2 (sync-without-lock), HD-2 (function attribute state), DR-1 (NotImplementedError).

---

## v2.4 Readiness Summary

Before dd_state/weekly_pnl_state can be promoted from advisory to hard gates:

1. **Eliminate dual `_recalculate_portfolio`** (SR-3) — gate must trust a single computation path
2. **Expand monitoring** (MN-1) — health-aware gating requires the monitor to know health
3. **Ready-state gating** (SC-2) — engine must refuse "ready" when data is missing
4. **Crash recovery restore risk states** (MP-1) — gate must survive restart
5. **Consolidate adapter usage** (SR-4 → SR-6) — every data path through adapter before gate can be applied at one point
6. **Adapter-neutral error types** (SR-7 prerequisite) — non-CCXT adapters need neutral exceptions
7. **Trade-entry path enumeration**: Calculator (add dd/weekly check to `eligible` at risk_engine:421) + Plugin push (already sends dd_state to plugin; C# plugin must gate locally) + Direct exchange (ungatable from engine)
8. **WS-1 is a hard blocker for Bybit WS production deployment** — ws_manager parses raw Binance JSON for market data; Bybit messages have a different shape. Must be resolved (SR-6) before any Bybit live WS deployment.

For the full UI/observability design that depends on MN-1 and SC-2, see **`docs/design/connection_status_ui.md`** — connection groups, health surface model, roll-up logic, degradation policy, notification anti-patterns, and sequencing constraints.

---

## Resolved Questions

### Q1: `total_realized` on AccountState — RESOLVED: remove

**Intent**: Periodic realized PnL (daily/weekly/monthly). **Wrong architecture**: storing a derived cumulative value on a state singleton. The correct data lives in `closed_positions.realized_pnl` — already correctly populated per trade.

**Resolution**: Remove `total_realized` and `cashflows` fields from `AccountState`. Add `get_realized_pnl(account_id, period)` query on the persistence layer that aggregates `closed_positions`. Update the LOW finding from "dead field" to "remove in favor of query-time aggregation."

**Architectural note**: Periodic values should be computed-on-read from `closed_positions`, not stored as derived state. This is the same pattern that protects against the SC-1 class of reset-failure bug — if a BOD reset fails, a query-time aggregation still gives the correct answer because it doesn't depend on a reset having fired.

### Q2: Bybit WS integration — RESOLVED: adapter-only, not in production

Bybit WS adapter exists and is registered, but `ws_manager.py` parses raw Binance JSON for market data (WS-1). Bybit WS messages have a completely different shape (`{"topic": "tickers.BTCUSDT", "data": {...}}` vs Binance's `{"e": "markPriceUpdate", "s": "BTCUSDT", "p": "..."}`). **WS-1 is a hard blocker for Bybit WS production deployment.**

Updated WS-1 finding and v2.4-readiness section accordingly.

### Q3: `reduce_only` on NormalizedOrder — RESOLVED: data-only, no downstream consumer

`reduce_only` is stored in the `orders` DB table and set by both adapters, but no core logic reads it for any decision. Aligns with SR-7's proposal: mark as `Optional[bool] = None` on the protocol. Adapters set when present, core never reads. Vendor-specific data stored but not acted on.

### Q4: BWE endpoint — RESOLVED: stable, but surfaces hardcoded-config finding

BWE endpoint is stable. The hardcoded Origin header is one instance of a broader pattern: **connection-config values hardcoded in adapter/fetcher code instead of living in the dedicated `ConnectionsManager` config layer.**

**New finding — CF-1** (MEDIUM, category 3): Hardcoded URLs, origins, and API base paths that should be configurable:

| File:line | Hardcoded value | Should live in |
|-----------|----------------|----------------|
| `news_fetcher.py:34` | `https://finnhub.io/api/v1` | ConnectionsManager or config |
| `news_fetcher.py:192` | `Origin: https://bwenews-api.bwe-ws.com` | ConnectionsManager |
| `regime_fetcher.py:144` | `https://api.stlouisfed.org/fred/series/observations` | ConnectionsManager or config |
| `connections.py:116` | `https://api.stlouisfed.org/fred/series` (test endpoint) | Same constant as regime_fetcher — but duplicated |
| `connections.py:125` | `https://finnhub.io/api/v1/stock/market-status?exchange=US` | Same base as news_fetcher — duplicated |
| `connections.py:134` | `https://api.coingecko.com/api/v3/ping` | Config |
| `connections.py:144` | `https://fapi.binance.com/fapi/v1/fundingRate` | Adapter constants (already in `binance/constants.py` for WS, but REST test URL hardcoded here) |
| `adapters/binance/constants.py:6-7` | `wss://fstream.binance.com/...` | Acceptable in adapter constants (vendor-specific by design) |
| `adapters/bybit/constants.py:6-7` | `wss://stream.bybit.com/...` | Acceptable in adapter constants |

Adapter-internal URLs (last 2 rows) are correctly placed in adapter constants. The issue is fetcher/connection-test URLs that duplicate or bypass the config layer.

---

## Open Questions (remaining)

1. **Platform bridge `_handle_historical_fill`** — the raw SQL at lines 300-363 aggregates partial fills by `time+symbol+direction`. Is this aggregation logic correct for all edge cases (e.g., multiple fills at the same millisecond for different orders)? Deferred to post-audit research.
