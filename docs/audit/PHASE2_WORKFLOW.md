# Phase 2 Workflow

## Required reading before any work
1. `docs/audit/AUDIT_REPORT.md` — full findings, severities, dependencies
2. `docs/design/connection_status_ui.md` — forward-looking design (NOT 
   for current implementation)
3. This document

## Pre-Phase-2 prep (one-time, before first fix)
- [ ] `git tag pre-audit-v2.3.1` — immutable rollback anchor
- [ ] Smoke-test baseline: deterministic input slice → captured 
      `tests/baselines/pre_audit_baseline.csv`
- [ ] 24-hour cold re-read of audit report completed

## Per-fix workflow (every Phase 2 commit)
1. Pick ONE finding from the priority list below
2. Branch: `fix/<finding-id>-<short-name>` (e.g., `fix/SC-1-bod-overflow`)
3. Write a regression test FIRST that captures current behavior
4. Confirm the test passes against current code
5. Apply the fix
6. Run all tests; only the new test status should change
7. Run smoke-test slice; diff against baseline
8. If diff shows ONLY expected changes → commit, merge
9. If diff shows unexpected changes → STOP, investigate, do not merge

## Hard rules
- One finding per branch. No "while I'm here" cleanups.
- Don't refactor outside the finding's scope.
- If a fix turns out larger than expected, STOP and propose a redesign 
  rather than expanding scope mid-session.
- Don't bulk-fix related items in one commit. Dependent findings can 
  share a PR as separate commits, but each commit gets its own 
  regression test and smoke-test diff verification.
- If you disagree with an audit finding, log it as a question for 
  the human — do not silently skip the fix.
- **Pre-phase gate (engine-off)**: Before beginning any implementation
  phase (code modification), explicitly ask: "Is the engine stopped?"
  Wait for user confirmation. Do not begin if unacknowledged. Applies
  to all Phase 4 steps and any phase that writes code. Read-only phases
  (enumeration, design) are exempt.

## Current priority order

### Bucket 0: Pre-redesign safety net (BEFORE any structural work)
- RE-9: unit tests for sizing, ATR, slippage, VWAP, analytics math

### Bucket 1: Cheap CRITICALs
- SC-1: BOD day-overflow (1-line)
- RP-1: auth + 127.0.0.1 default for /api/platform/*
- RE-1: wire up existing staleness checks in calculator

### Bucket 2: Foundation structural redesigns
- SR-1: OrderManager split (snapshot vs single-update)
- SR-2: AccountRegistry single owner of active_account_id
- (SR-1 and SR-2 can land in parallel; SR-3 depends on SR-2)
- SR-3: Crash recovery consolidation

### Bucket 2.5: Rate-limit hardening + reconciler noise reduction
Sequence: RL-3 → AN-1 → 24-48h re-verification → SR-7

- **RL-3** (NEW, HIGH): RL-1 exception coverage gaps. Broad
  `except Exception` handlers swallowed `ccxt.RateLimitExceeded`
  (429) without calling `handle_rate_limit_error()`. Evidence: 9s
  of SIRENUSDT 429s on 2026-05-07 20:01 UTC without
  `rate_limited_until` being set, escalating to 418 IP ban.
  Branch: `fix/RL-3-rate-limit-exception-coverage`.
  Discovered: 2026-05-09, RL-1 operational verification.
  **11 catch sites fixed** (actual, post-audit refinement):
  - exchange.py (2): `populate_open_position_metadata` outer loop,
    `fetch_open_orders_tpsl`
  - reconciler.py (5): `on_trade_closed`, `backfill_all` history
    pre-fetch, `backfill_all/_process` per-symbol,
    `on_position_closed`, `_reconcile_closed_positions` per-row
  - ws_manager.py (4): `_on_new_position`, `_refresh_positions_
    after_fill`, `_keepalive_loop`, `_fallback_loop`
  Audit note: original audit listed exchange.py `get_exchange:104`
  and `fetch_exchange_info:145` as uncovered, but these wrap local
  factory/registry lookups (no REST calls) — correctly excluded.
  Three ws_manager.py sites (`_refresh_positions_after_fill`,
  `_keepalive_loop`, `_fallback_loop`) were originally marked
  "GENERIC (unaudited)" and added during implementation audit.

- **AN-1** (HIGH, promoted to Bucket 2.5): MFE/MAE backfill uses 0
  as sentinel for "not yet computed," but 0 is a valid computed
  result for tight trades. The query `WHERE mfe=0 OR mae=0`
  reprocesses every trade where MFE or MAE happens to be exactly 0
  (or rounds to 0). Operational impact: persistent REST calls every
  startup, contributor to per-second pressure that triggered the
  May 5 and May 7 bans. Fix: add `backfill_completed` boolean
  column; query `WHERE NOT backfill_completed`. Requires migration.
  Small fix, high operational leverage. Discovered during RL-1
  investigation. Promoted from Bucket 4 — reduces baseline
  reconciler REST pressure, making rate-limit events less likely.
  Operational note: SIRENUSDT/ONUSDT rows stuck since 2026-05-05.
  Branch: `fix/AN-1-backfill-sentinel`.

### Bucket 3: Revised sequence (dependency-ordered)
- SR-7: **done**
- SR-4 + SR-6a: **done** (SR-4d, SR-4c no-change, SR-6a, SR-4a+b)
- SR-6 (remaining): adapter routing for non-6a items (WS-1/WS-2)
- SR-8: regime data source ports
- MN-1: monitoring expansion
- SC-2: ready-state gating
- MP-1: crash recovery risk states

### Differential verification schedule (Bucket 3)
Per-item verification windows based on risk profile:
- Pure refactors (SR-6 remaining, SR-8): 1-2 hr smoke test
- Additive changes (MN-1): 1-2 hr smoke test
- Behavior changes (SC-2, MP-1): 6-12 hr verification
- End of Bucket 3 (after MP-1): bundled with end-of-Bucket-4
  combined 24-48h window. Rationale: structural Bucket 3 work
  is pure refactor (smoke-diff empty per-item), behavior-change
  items had partial verification, full window earns more keep
  when testing cumulative Bucket 3+4 stack.
Same grep pattern and routing logic (A/B/C) for all windows.

### Bucket 4 execution order
1. AD-5 (architectural cleanup, possibly resolves aiohttp
   unclosed-session anomaly)
2. MN-1a (~2-line quick win, activates check #9)
3. FE-9 diagnostic (determines if (b)/(c) → stays in Bucket 4,
   or (a) → falls to Bucket 5)
4. Remaining HIGH items (AN-2, AD-2/3/4, RL-4, OM-5, MN-2/RE-2)
   ordered as findings inform

### Bucket 4 (HIGH cleanup):
- **OM-5**: **done** — conditional/algo order support (REST + WS).
  Root cause: Binance separates basic orders (FAPI openOrders) from
  conditional orders (FAPI openAlgoOrders, WS ALGO_UPDATE). Engine
  queried only basic orders and handled only ORDER_TRADE_UPDATE.
  All TP/SL placed via Binance UI are "conditional" → invisible.
  Fix: (1) REST polling via /fapi/v1/openAlgoOrders every 15s, NOT
  plugin-gated; (2) ALGO_UPDATE WS handler for real-time lifecycle;
  (3) snapshot isolation via algo: ID prefix + scoped stale-cancel.
  Also includes positionSide="BOTH" matching fix for one-way mode
  (fix/OM-5-tpsl-position-matching, correct but not the user's issue).
  15+14 regression tests, 516/516 green, baseline empty.
  Branch: fix/OM-5-conditional-orders-support.
  Design docs: docs/design/OM-5_phase1_investigation.md,
  docs/design/OM-5_phase1_conditional_orders.md.
- **OM-5b**: partially addressed — conditional order REST polling
  runs regardless of plugin state (addresses OM-5b for algo orders).
  Basic-order plugin gating (3 sites) remains: fetch_open_orders_tpsl
  (exchange.py:281), _account_refresh_loop (schedulers.py:115),
  _user_data_loop standby (ws_manager.py:317). Separate fix still
  needed for basic order discovery on startup. Discovered: 2026-05-13.
- **MN-2** (severity TBD, potentially HIGH): Monthly drawdown
  shows 0 in dashboard despite real drawdown this month. Failing
  layer unknown: reset logic, calculation logic, frontend display,
  or definition mismatch. Diagnostic: query dd_state directly,
  compare to dashboard render, isolate failing layer.
  Operational gate: dd_state is being promoted from advisory to
  gate in v2.4 — this finding must be resolved before v2.4
  promotion, otherwise a broken metric gets promoted to
  enforcement role. Discovered: 2026-05-10, verification window.
- **AD-2** (MEDIUM): Bybit adapter `fetch_income()` ignores
  `income_type` parameter — only returns "realized_pnl". Funding
  fee, commission, and transfer income types silently return empty.
  Protocol violation. Fix: implement V5 transaction log endpoint
  for non-PnL income types. Discovered: 2026-05-11, SR-7 Phase 1
  audit. Not in SR-7 scope (adapter quality, not protocol design).
- **RL-4** (MEDIUM): Periodic 429 bursts at ~8-minute intervals.
  5 bursts on 2026-05-10 18:57-19:25 UTC. Periodicity suggests a
  scheduled task hitting Binance hard enough to trigger rate limits
  every ~8 minutes. Diagnostic: cross-reference burst timestamps
  with scheduler config in core/schedulers.py; the ~8-minute
  interval should match one configured loop. May justify promoting
  RL-2 (proactive weight tracker, currently deferred) earlier —
  proactive tracking would prevent periodic hits at the source.
  Discovered: 2026-05-12, SR-7 verification window.
- **PA-1a**: **done** — WS fill creation + backfill dedup. Fills now
  created from WS TRADE events via _create_fill_from_ws() using native
  tradeId. Backfill dedup checks (symbol+side+qty+|ts|<1s) prevents
  dual records. 468/468 green, baseline diff empty.
- **PA-1b**: **done** — FIFO open_time reconstruction. Replaced 24-line
  backward-walk with precomputed FIFO queue per (symbol, direction).
  Closes consume opening fills oldest-first; partial closes share
  the correct open_time. Eliminates 7-day fallback silent wrong grab.
  Orphan closes get open_time=0 (explicit unknown). Scale-in handled
  naturally. 479/479 green, baseline diff empty.
- **PA-1**: partially addressed — manifestation (a) WS event miss
  resolved by PA-1a; open_time reconstruction resolved by PA-1b.
  Manifestation (b) position-split (reconciler creates new record per
  partial close instead of updating same position) may be residual.
  Deferred: requires live partial-close observation to confirm whether
  PA-1a+PA-1b together resolved the split behavior or if reconciler
  logic still needs work. Severity reduced to MEDIUM pending
  confirmation. Original discovery: 2026-05-12.
- **MN-1a**: **done** — wired record_rate_limit_event() into
  handle_rate_limit_error(). Check #9 (rate-limit frequency) now active.
  3 lines added. 454/454 green, baseline diff empty.
- **AD-5**: **done** — ohlcv_fetcher migrated to adapter (Option A:
  pagination wrapper around sync adapter). Deleted ccxt.async_support,
  aiohttp session, ThreadedResolver (~45 LOC). Windows DNS workaround
  eliminated (sync adapter uses OS-native DNS). Last direct ccxt
  consumer eliminated — adapter abstraction is now exhaustive.
  Only ccxt import remaining: exchange_factory.py (adapter infrastructure,
  correct placement). 450/450 green, baseline diff empty.
- **AN-2**: **done** — DELETE with export-first. Removed all 148
  qt:-prefixed legacy Quantower rows from exchange_history (254→106,
  58% of table) and 148 matching fills. All rows confirmed corrupted:
  hold=0s entries, MAE>245%, impossible hold times (up to ~7948 days).
  14 symbols affected: STOUSDT(56), SIRENUSDT(29), ONUSDT(12),
  BTCUSDT(10), JCTUSDT(10), TRUMPUSDT(7), +8 others.
  Archive: docs/archive/quantower_legacy_*_2026-05-12.csv (commit 48755ee).
  Migration: two _run_once entries in database.py (idempotent).
  8 regression tests. 487/487 green, baseline diff empty.
  Branch: fix/AN-2-quantower-legacy-cleanup.
- **AD-4** (MEDIUM): Adapter is_close heuristic improvements.
  Binance: use side+positionSide deterministic check instead of
  realizedPnl != 0. Bybit: use closedSize > 0 field. Improves
  accuracy for new fills going forward. Historical data unaffected
  (stored at write time). Discovered: 2026-05-11, SR-7 Phase 4
  is_close investigation. NOT in SR-7 scope (adapter quality).
- **AD-3** (LOW): Bybit adapter hardcodes maker_fee=0.0002,
  taker_fee=0.00055 (VIP0 tier assumption). Binance fetches live
  from fapiPrivateGetCommissionRate. Fix: query Bybit V5 account
  info for actual fee tier, or accept config override. Discovered:
  2026-05-11, SR-7 Phase 1 audit. Partially addressed by SR-7's
  `fee_source` indicator (surfaces the gap without fixing it).

### Bucket 5 (MEDIUM/LOW cleanup):
- Public API on DataCache: expose `recalculate_portfolio()` (no
  underscore) as the public method, keep `_recalculate_portfolio`
  internal. Migrate the 3 SR-3 callers to the public form. ~5 lines.
- (AN-2 promoted to Bucket 4 — see below)
- **FE-1** (LOW): Pagination inconsistency in position/order/trade
  history. Some pages render >20 rows despite 20/page setting.
  Options are 20/50 per page. Spacing inconsistent across views.
  Fix: use position history as canonical; migrate order and trade
  history to match its pagination logic and spacing.
- **FE-2** (LOW): Calculator recent-calculated click renders partial
  state on first click (orderbook only, rest is ghost UI); second
  click works. Async-render race — data fetch not awaited before
  template renders, or HTMX swaps orderbook independently. Fix:
  investigate load order; fix await chain or add loading skeleton.
- **FE-3** (MEDIUM): Open position card flickers on refresh —
  entire card re-renders instead of just data nodes. Pattern issue
  across the frontend. Fix: audit hx-target granularity; move
  targets from wrapping containers to specific data spans (price,
  PnL, status). Container renders once; only data nodes refresh.
  One consolidated PR. May warrant its own session given scope.
- ~~**AN-3**~~ CLOSED: duplicate of AN-2 (legacy Quantower data
  corruption). Diagnostic (2026-05-11): 3/3 anomalous rows are
  qt:-prefixed, all wick_pct >245%, mathematically inconsistent
  with real trades. Root cause = AN-2's corrupted timestamps
  causing fetch_price_extremes to read a wider window.
- **FE-4** (LOW): No edit-account-name in configuration tab.
  Frontend + backend work — add edit field, route handler, DB
  UPDATE. Small feature, not a defect.
- **FE-7** (LOW): Cap dashboard order history at 10 visible lines,
  scrollable to 25, with existing link to full history tab.
  Frontend-only. Discovered: 2026-05-10.
- **SR-7 feature note**: WebSocket endpoint URL input field needed
  in configs > connection tab. Downstream of SR-7's protocol
  vendor-neutrality redesign — custom endpoints only become
  meaningful once protocol is vendor-neutral. Land alongside or
  after SR-7, not as standalone frontend finding.
- **FE-8** (severity TBD, leaning HIGH-MEDIUM): Calculator market
  price flickers between previous-calculated symbol and current
  symbol when switching. Derived values (size, etc.) also flicker.
  Possible causes: (a) WS subscription not cleaned up on switch,
  (b) concurrent price-fetch loops, (c) calculator state holding
  both symbols, (d) HTMX poll serving cached wrong-symbol data,
  (e) race between recent-calc-click and live-data-fetch.
  Possible shared root with FE-2 (first-click partial state) —
  both involve stale previous-symbol data contaminating new view.
  Severity escalation: if users can act on visibly-coherent but
  wrong calculations (flicker not visible at click moment),
  severity is HIGH (risk-management gap, Bucket 4 candidate).
  Discovered: 2026-05-11, SR-7 verification window.
- **FE-9**: **done, verified** (91.5% pnl_anomaly rate reduction). Race
  condition eliminated. Single residual event attributed to 5-min lookback
  catching pre-fix snapshot; zero events for 38 min afterward.
  (data_cache.py:276 removed). User reports flickering "still presents"
  — three explanations: (a) fix incomplete, (b) chart rendering historical
  race-corrupted snapshots (will age out), (c) separate display-layer
  flicker. 1-2 hr smoke MANDATORY: compare pnl_anomaly rate pre (19/hr)
  vs post (should be 0-2/hr if fix correct). 457/457 green.
- ~~**FE-9** (potentially HIGH)~~: Total equity flash crash on equity curve
  tab — equity briefly shows wrong (low) value for ~1s. Strong potential
  connection to dozens of pnl_anomaly events in MN-1 logs (equity drops
  -1.0% to -5.3% throughout SC-2 verification window). pnl_anomaly noise
  may be generated by flash crash bug rather than real equity anomalies.
  Causes: (a) display bug, (b) fetch bug — data layer returns wrong
  value then corrects, (c) race condition — calculation uses partial
  state during update. Diagnostic: capture pnl_anomaly timestamps, check
  if equity value matches flash-crash visual. Bucket 4 if (b)/(c);
  Bucket 5 if (a). Discovered: 2026-05-12, SC-2 verification window.
- **UX-1** (Bucket 5, candidate for v2.4 UX bundle): Consistent ghost
  interface pattern across data-dependent components. Three states:
  (a) Engine unreachable — ghost structure with "data pending" indicators
  (b) Data stale — SC-2 not-ready → ghost overlay/fade with staleness
      annotation
  (c) Data immature / bootstrapping — consistent loading indicators
  Cross-references: FE-2 (unintentional case c), FE-3 (hx-target
  granularity determines re-render), OM-5 (TP/SL placement pending).
  Address after Bucket 3 completes. Discovered: 2026-05-12.
- **MP-2** (MEDIUM, Bucket 5): Equity history backfill on startup.
  Engine equity curve shows flat line during downtime (gaps filled with
  last value). No backfill fetches missing equity data on restart.
  Fix: compute snapshots from price+state during downtime, OR derive
  from exchange equity endpoint, OR mark gaps explicitly in UI.
  Bucket 5 by default (external backtesting re-derives). Bucket 4 if
  engine curve intended as backtest input. Discovered: 2026-05-12.
- **FE-12** (MEDIUM): Residual equity curve flicker — chart rendering
  historical race-corrupted snapshots from pre-FE-9 data. Will age out
  as clean snapshots accumulate. Revisit if persists after ~1 week.
  Discovered: 2026-05-12.
- **FE-10** (MEDIUM-LOW): 1W equity chart shows "huge drop on left" with
  value appearing only on right. Chart axis/data padding issue — engine
  may pad missing days with zero/null, Y-axis starts at 0 instead of
  near data range, or query returns null entries. Different bug from FE-9.
  Discovered: 2026-05-12.
- **FE-11** (MEDIUM): Rapid timeframe switching (1D/1W repeatedly) makes
  engine unresponsive temporarily. Synchronous backend blocking event loop
  during query/recompute. Known limitation for v2.3.1 — properly addressed
  by v1.2 Redis event-driven state architecture. Discovered: 2026-05-12.
- **BU-1** (LOW): CCXT "Unclosed client session" resource warning
  observed during RL-3+AN-1 verification window. Possible CCXT
  client lifecycle bug — exchange instance not closed on some path
  (account switch, shutdown, or error recovery). Defer until after
  SR-7. Discovered: 2026-05-10, verification window.

## Status: Where are we?

Last updated: 2026-05-13 (OM-5 done, OM-5b partially addressed)
- Bucket 0: **done** — RE-9 landed (60 tests, 111-row baseline CSV)
- Bucket 1: **done** — SC-1, RP-1, RE-1 all landed (branch: audit/v2.3.1)
- Bucket 2: **done** — all three foundation redesigns landed
  - SR-1: 73 regression tests (branch: fix/SR-1-order-manager-single-owner)
  - SR-2: 18 regression tests (branch: fix/SR-2-account-registry-single-owner)
  - SR-3: 13 regression tests (branch: fix/SR-3-crash-recovery-consolidation)
  - 237/237 full suite green, baseline diff empty after all three
- RL-1: **done** — rate-limit handling band-aid (branch: fix/RL-1-rate-limit-handling)
  - 23 regression tests, 260/260 full suite green, baseline diff empty
  - Operational verification **FAILED** (2026-05-09): 418 IP ban on
    2026-05-07 20:01-20:04 UTC. RL-1 catch sites did not engage on
    429s — only caught 418 (DDoSProtection). See RL-3 in Bucket 2.5.
  - Note: v2.3.1 recomputes dd_state/weekly_pnl_state on restart
    rather than restoring from snapshot. v2.4 gate semantics may
    revisit this decision.
- RL-3: **done** — exception coverage fix (branch: fix/RL-3-rate-limit-exception-coverage)
  - 11 regression tests, 271/271 full suite green, baseline diff empty
  - Fixed 11 catch sites across exchange.py, reconciler.py, ws_manager.py
  - Added ccxt.RateLimitExceeded + ccxt.DDoSProtection before broad except Exception
  - Operational verification: **PASSED** (2026-05-10) — 21h clean run, zero 429/418
- AN-1: **done** — backfill_completed sentinel fix (branch: fix/AN-1-backfill-sentinel)
  - 7 regression tests, 278/278 full suite green, baseline diff empty
  - Added `backfill_completed INTEGER` column to exchange_history + closed_positions
  - Queries use `NOT backfill_completed` instead of `mfe=0 OR mae=0` sentinel
  - Update functions set `backfill_completed=1` alongside mfe/mae values
  - Migration: ALTER TABLE ADD COLUMN + UPDATE existing computed rows
  - Operational verification: **PASSED** (2026-05-10) — 21h clean run, zero 429/418
- SR-7: **done** — protocol vendor-neutrality redesign
  Branch: fix/SR-7-protocol-vendor-neutrality
  - Step 1: neutral error types (RateLimitError hierarchy) — 291→291 green
  - Step 2: protocol dataclass changes (Optional fields, NormalizedFundingRate, WSEventType) — 303→303 green
  - Step 3: SupportsListenKey + auth model abstraction — 314→314 green
  - Step 4: fetch_price_extremes (replaces fetch_agg_trades, tier logic in adapter) — 325→325 green
  - All 4 steps: baseline diff empty, behavioral equivalence verified
  - Operational verification: **PASSED** (2026-05-12) — 429 cluster on
    May 10 caught across 6 sites by neutral RateLimitError, proper 120s
    pauses, no 418 escalation. Stress-tested under real production load.
  - Design docs: docs/design/SR-7_phase{1,2,3}_*.md
- SR-4 + SR-6a: **done** — exchange.py collapse + adapter wiring
  Branch: fix/SR-4-exchange-collapse
  - Step 1 (SR-4d): deleted dead-code fetch_ohlcv_window — 328 green
  - Step 2 (SR-6a): 3 adapter methods + 4 caller migrations — 343 green
  - Step 3 (SR-4a+b): deleted singleton + pool + ccxt import — 356 green
  - All 3 steps: baseline diff empty
  - exchange.py post-collapse: thin orchestration facade, zero raw CCXT,
    zero thread pool, zero singleton. All I/O through _get_adapter().
  - Operational verification: **PASSED** (2026-05-12) — 1-2 hr smoke clean,
    429s caught by neutral errors, zero deleted-function references
- SR-6 remaining (WS-1/WS-2): **done** — ws_manager adapter routing
  Branch: fix/SR-6-ws-adapter-routing
  - WS-1: deleted 3 raw-Binance handlers, inlined adapter parse calls
  - WS-2: added execution_type to NormalizedOrder, Binance adapter populates
  - 372/372 green, baseline diff empty
  - Operational verification: **PASSED** (2026-05-12) — 1-2 hr smoke clean
- SR-8: **done** — regime_fetcher adapter migration
  Branch: fix/SR-8-regime-adapter-migration
  - Replaced 2 raw ccxt calls with adapter methods (fetch_open_interest_hist,
    fetch_funding_rates — both already existed on protocol)
  - Deleted _get_ccxt() singleton + ccxt.async_support + aiohttp session (~35 LOC)
  - Collapsed 2 TODO(SR-8) dual-catch sites to single RateLimitError
  - Added SupportsOpenInterest / SupportsFundingRates isinstance guards
  - Scheduler injects adapter via _get_adapter()
  - 387/387 green, baseline diff empty
  - Remaining direct ccxt: ohlcv_fetcher.py (async_support, filed as AD-5)
  - Adapter migration arc complete except AD-5 — ohlcv_fetcher is the
    last direct ccxt consumer in the codebase
  - Operational verification: **PASSED** (2026-05-12) — 1-2 hr smoke clean
- MN-1: **done** — monitoring expansion (3 → 9 checks)
  Branch: fix/MN-1-monitoring-expansion
  - Commit 1: MonitoringEvent data model, ring buffer, API endpoint
  - Commit 2: 6 new checks (regime freshness, news health, plugin
    connection, reconciler health, DB health, rate-limit frequency)
  - MonitoringEvent forward-compatible with webhook dispatch
  - 417/417 green, baseline diff empty
  - Check #9 dormant pending MN-1a wiring (Bucket 4)
  - Monitoring data model + ring buffer + API endpoint established
  - Webhook signature defined for future external integration
  - Operational verification: **PASSED** (2026-05-12) — tests + pattern reuse
    sufficient; failure-path exercise limited by absence of organic faults
- SC-2: **done** — ready-state gating
  Branch: fix/SC-2-ready-state-gating
  - Commit 1: ReadyStateEvaluator (3 gates: bootstrap, account, staleness),
    /api/ready upgraded with reason field, 60s hysteresis
  - Commit 2: calculator returns ineligible when not ready, uses existing
    ineligible_reason mechanism
  - 430/430 green, baseline diff empty
  - Operational verification: **PASSED** (2026-05-12, partial) — no false
    positives, engine stayed ready. Fault path unverified (no sustained
    60s+ staleness). Deferred to production observation.
- MP-1: **done** — crash recovery risk states
  Branch: fix/MP-1-crash-recovery-risk-states
  - Added dd_state + weekly_pnl_state to restore_from_snapshot() (+2 lines)
  - Both fields already in DB schema + write path — only read-back was missing
  - Eliminates 5-15s window where gate defaults to "ok" after restart
  - 437/437 green, baseline diff empty
  - Operational verification: 1-2 hr smoke (adjusted — restart-recovery
    tested in suite, not time-dependent)
- **Bucket 3 complete.** Final 24-48h verification bundled with
  end-of-Bucket-4 (decision: 2026-05-12). Pre-Bucket-4 evidence:
  5.3h MN-1+SC-2+MP-1 code + 21h Bucket 3 structural code under
  production load. Structured report 2026-05-12: CLEAN across all
  7 findings with caveats — MN-1 partial (checks 2,4-9 unfired
  due to healthy conditions), SC-2 fault path unverified (no organic
  60s+ staleness), MP-1 per-field restore test-suite verified but
  not log-observed.
  Outstanding TODO during Bucket 4: deliberate stop-start with
  pre/post dd_state and weekly_pnl_state capture at any natural
  restart — closes MP-1 observational gap.