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
- **SR-4d**: Delete dead-code `fetch_ohlcv_window` (zero callers)
- **SR-4c**: Extract augmentation logic to service layer
- **SR-6a**: Wire exchange_market.py through adapter (prerequisite for SR-4a+b)
- **SR-4a + SR-4b**: Remove `_REST_POOL` + `get_exchange()` singleton (combined)
- SR-6 (remaining): adapter routing for non-6a items
- SR-8: regime data source ports
- MN-1: monitoring expansion
- SC-2: ready-state gating
- MP-1: crash recovery risk states

### Bucket 4 (HIGH cleanup):
- **OM-5** (severity TBD, potentially HIGH): TP/SL set at order
  creation not visible in open-orders tab or TPSL tab. Three
  possible layers:
  (a) Display bug — exists in app state, template doesn't render.
  (b) Fetch bug — Binance USDM TP/SL at order creation creates
      separate STOP_MARKET/TAKE_PROFIT_MARKET orders with
      reduceOnly=true. Parser may miss those types or filter.
  (c) Timing/race — stale snapshot replay clearing TP/SL. SR-1
      covered main entry order; TP/SL may be out of scope.
  Manifests in TWO paths, likely same root cause:
  (a) TP/SL set at order creation not visible (original report)
  (b) TP/SL edited mid-trade not visible (observed during SR-7
      verification window)
  Both paths produce STOP_MARKET/TAKE_PROFIT_MARKET orders with
  reduceOnly=true on Binance USDM; same fetch and display surface.
  Diagnostic: query Binance API for open orders on affected symbol;
  compare against engine local state; isolate fetch vs display.
  May escalate to Bucket 1 if confirmed protective-order gap.
  Discovered: 2026-05-10, verification window.
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
- **AN-2** (HIGH, promoted from Bucket 5): qt:-prefixed legacy
  Quantower rows have multiple corruption modes — hold=0s with
  high≈low (original report) AND long-hold-with-extreme-MAE
  (hold 2-6 days, wick_pct >245%, confirmed by AN-3 diagnostic
  2026-05-11: 3/3 rows qt:-prefixed SIRENUSDT). Likely additional
  smaller-magnitude corruption below diagnostic threshold.
  Actively distorts visible dashboard MAE values. Unifying fix:
  exclude or delete all qt:-prefixed rows from analytics queries
  (and consider deleting from exchange_history table entirely).
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
- **BU-1** (LOW): CCXT "Unclosed client session" resource warning
  observed during RL-3+AN-1 verification window. Possible CCXT
  client lifecycle bug — exchange instance not closed on some path
  (account switch, shutdown, or error recovery). Defer until after
  SR-7. Discovered: 2026-05-10, verification window.

## Status: Where are we?

Last updated: 2026-05-10
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
- SR-4: **in progress** — Phase 3 (migration plan) complete, awaiting review
  Branch: fix/SR-4-exchange-collapse
  Phase 1: enumeration done
  Phase 2: collapse design done (Q1/Q2 verified)
  Phase 3: migration plan done
  Phase 4: implementation — blocked on Phase 3 review