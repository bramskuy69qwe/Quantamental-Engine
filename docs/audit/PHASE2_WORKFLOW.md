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

### Bucket 4 (HIGH cleanup):

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
- **FE-4** (LOW): No edit-account-name in configuration tab.
  Frontend + backend work — add edit field, route handler, DB
  UPDATE. Small feature, not a defect.

## Status: Where are we?

Last updated: 2026-05-09
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
  - Operational verification: pending 24-48h clean run after AN-1
- AN-1: **queued** — next after RL-3