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

### Bucket 3+: see AUDIT_REPORT.md execution order

SR-4/SR-6 deferred items (identified during SR-7 Phase 3, NOT in SR-7
scope — belong to exchange.py collapse or adapter routing work):
- **SR-4a**: Eliminate `_REST_POOL` ThreadPoolExecutor (internal impl)
- **SR-4b**: Remove `get_exchange()` legacy singleton (adapter factory
  handles this)
- **SR-4c**: Move `fetch_exchange_trade_history` augmentation logic to
  adapter or service layer
- **SR-4d**: `fetch_ohlcv_window` pagination helper — internal, not
  protocol surface
- **SR-6a**: Wire remaining raw-CCXT calls in exchange_market.py
  through adapter (4 functions per original audit WS-1/EM-1)

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
- **AN-2** (MEDIUM): qt:-prefixed legacy trades from previous
  Quantower mode show hold=0s and high≈low (single-tick range).
  Timestamp bug or stale orphaned data. User is standalone now.
  Fix: delete or exclude qt: rows from analytics — Quantower-mode
  data is no longer relevant to standalone operation. Discovered
  during RL-1 investigation. Can land with AN-1 for practical
  convenience.
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
- **AN-3** (severity TBD pending diagnostic): MAE values exceed
  equity bounds. User observed mae >$260 on <$100 equity account.
  Three candidate causes:
  (a) Legitimate: high-leverage position + last-price wick on
      illiquid altcoin. aggTrades reads last price, not mark price
      used for liquidation. Mathematically plausible at 20x leverage
      with ~13% wick. If confirmed: documentation gap, not a bug.
  (b) Window bug: open_time/close_time wrong (potentially linked to
      AN-2 qt:-prefixed legacy rows with bad timestamps), causing
      fetch_hl_for_trade to pull extremes from a wider period.
  (c) Qty unit bug: qty stored in scaled/contract-multiplied form
      different from what calc_mfe_mae assumes.
  Diagnostic: query exchange_history WHERE ABS(mae) > 100; check
  qt: prefix, hold duration plausibility, qty cross-reference.
  May escalate to Bucket 4 if proven to be window/qty bug rather
  than legitimate wick artifact. Discovered: 2026-05-09.
  Operational gate: investigation deferred until after RL-3 + AN-1
  verification window closes.
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
  - Design docs: docs/design/SR-7_phase{1,2,3}_*.md