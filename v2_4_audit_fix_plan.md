# v2.4 Audit Fix Implementation Plan

**Source:** `docs/audits/2026-05-17-v2.4-backend-audit.md` (92 findings)
**Branch tip:** `v2.4/backend-audit` (commit `a100a28` and successors)
**Target:** clear all Critical + High, selective Medium for v2.4.1; defer rest to v2.5

---

## Branch State Cleanup (Do First)

The audit branch has merge commits from 7+ re-audit iterations. Don't try to rewrite history — the final audit document is what matters. Recommendation:

1. From current tip: `git checkout v2.4/backend-audit` (whichever commit has the final 92-finding doc).
2. Create the implementation branches off this tip.
3. Each phase below = a new branch off the previous phase's tip (linear, stack-based, like the v2.4 work has been).
4. Optional cleanup: after all phases land, squash-merge into a single `v2.4-audit-fixes` commit before tagging v2.4.1. But functional first, history-clean second.

---

## Phase Overview

| Phase | Focus | Tasks | Severity Covered | Est. LOC | Release Target |
|-------|-------|-------|------------------|----------|----------------|
| 1 | Critical trading-path correctness | 1 | 3 CRIT | ~150 | v2.4.1 |
| 2 | Critical reliability + data integrity | 1 | 3 CRIT | ~200 | v2.4.1 |
| 3 | High correctness — order/position | 2 | 7 HIGH | ~400 | v2.4.1 |
| 4 | High correctness — WS, security, risk | 2 | 8 HIGH | ~400 | v2.4.1 |
| 5 | Performance — indexes, async, polling | 1 | 1 HIGH + 3 MED | ~200 | v2.4.1 |
| 6 | Architecture — `db._conn` refactor | 3 | 1 HIGH (split) | ~500 | v2.5 |
| 7 | Security baseline (excluding auth) | 1 | 4 HIGH + 5 MED | ~300 | v2.5 |
| 8 | Authentication implementation | 2-3 | 1 HIGH (large) | ~600 | v2.5 |
| 9 | State robustness + account isolation | 2 | 1 HIGH + 7 MED | ~400 | v2.5 |
| 10 | UI/UX polish (history page bugs) | 1 | 3 MED + 2 LOW | ~150 | v2.5 |
| 11 | Test coverage — priority modules | 2-3 | 1 MED (ongoing) | varies | v2.5 |
| 12 | Low-priority cleanup batch | 1 | All remaining LOW | ~200 | opportunistic |

**v2.4.1 patch scope:** Phases 1-5 (~7 tasks). Ships within 1-2 working days of focused effort.
**v2.5 scope:** Phases 6-11 (~13-15 tasks). Spread across a release cycle.

---

## Senior-Engineer Framing Patterns

Append the appropriate framing at the **top** of each task prompt to set Claude Code's mental model:

### Pattern A — Trading-Path Correctness
> Act like a senior quant who's lost money to silent slippage bugs. You've seen division-by-zero crashes leave positions unmanaged, and you've debugged race conditions at 3am. Every change here goes through three filters: (1) does it preserve correctness under edge cases the original author didn't think of? (2) does it fail-safe (better to halt than corrupt)? (3) is the test rigorous enough that you'd bet capital on it?

### Pattern B — Reliability & Concurrency
> Approach this as a staff systems engineer responsible for a production trading platform. You've seen async bugs that only manifest under load. Your default stance: assume concurrent execution, assume any external call can fail, assume any cache can be stale. Every fix needs a story for what happens when the assumed-good case isn't.

### Pattern C — Security
> Think like a security engineer reviewing a financial system. You assume hostile inputs, leaky logs, compromised dependencies, and insider threats. Defense-in-depth is not optional — even if one layer "should" handle a class of bug, the second layer must exist. You're not paranoid; you're calibrated to the actual threat model of a system holding API keys with trading permissions.

### Pattern D — Architecture / Refactor
> Act like a tech lead doing a refactor. You move in small, safe steps. Each commit leaves the system green. You preserve existing behavior unless explicitly changing it. You write tests before changing the implementation so regressions surface immediately. Encapsulation, naming, and dependency direction matter — the goal is a codebase the next maintainer can understand without spelunking.

### Pattern E — Performance
> Approach this like a performance engineer. Measure first, fix second. Every change must have a clear "before/after" delta you can articulate (latency, query count, memory). Don't optimize without evidence; don't accept a fix without verification. The system has 1247 tests — they're your safety net for ensuring perf wins don't trade off correctness.

### Pattern F — Testing
> Act like a QA engineer who's been burned by tests that pass for the wrong reasons. Tests should exercise behavior, not implementation. They should fail loudly when intent breaks. Coverage % means nothing if the tests are vacuous. Each new test you write needs to defend a specific behavior with a specific assertion that would fail in a specific way if the code regressed.

---

## Task Prompt Template

Use this skeleton for every audit-fix task:

```
# Task NN: <Title>

[Insert appropriate framing pattern A-F]

## Setup
1. From stack tip: `git checkout <prev_branch> && git checkout -b v2.4/<this_branch>`.
2. <Scope statement: bug fixes / refactor / new tests>. <File count estimate>.
3. Apply CLAUDE.md discipline. Commit at end automatically.

## Reference
- Audit doc: `docs/audits/2026-05-17-v2.4-backend-audit.md`
- Findings addressed: <FINDING IDs listed>

## Findings to Address

For each finding, restate:
- Severity + ID
- Brief description
- File:line
- Required fix
- Test requirement

## Build

[Per-finding subsections with concrete patches]

## Tests

[Regression tests for each fix; one or two per finding]

## Verify

Manual / automated verification steps.

Report:
- Findings addressed (FINDING ID → commit confirmation)
- Tests added (count + brief descriptions)
- Any finding that proved different in implementation than spec'd
- Commit hash.

## Out of scope

Findings deferred to other phases. Refactoring beyond fix scope. Stop-and-report.
```

---

## Phase 1: Critical Trading-Path Correctness

**Branch:** `v2.4/audit-phase1-trading-critical`
**Framing:** Pattern A (Trading-Path Correctness)
**Tasks:** 1
**Findings:** CRIT-002, CRIT-003, CRIT-004

### Task 85: Critical correctness in trading path

Three small but high-impact fixes, all in the calculator/order-close path:

- **CRIT-002** `core/risk_engine.py:159-161` — division by zero when `best_price = 0`. Guard with early return.
- **CRIT-003** `core/order_manager.py:654-668` — `max()` on empty list; div-by-zero in fee ratio. Add empty-list guards, replace ternary with explicit if/else.
- **CRIT-004** `core/exec_link.py:55-56` — TP/SL self-comparison bug. Both args are `pretrade.get("tp_price")` — always True. Short-term fix: document limitation + change to compare against actual order TP/SL on the exchange. Long-term: full match logic awaiting Phase 9 (TP/SL modification tracking).

Tests: explicit regression tests for each — pass `best_price=0` to slippage calc, close a position with empty close_fills list, run exec_link match where pretrade TP != actual TP.

**Why grouped:** all three are 5-20 LOC fixes in critical paths, share the same review focus, and are independent of each other.

---

## Phase 2: Critical Reliability + Data Integrity

**Branch:** `v2.4/audit-phase2-reliability-critical`
**Framing:** Pattern B (Reliability & Concurrency)
**Tasks:** 1
**Findings:** CRIT-001, CRIT-005, CRIT-006

### Task 86: Critical reliability fixes

- **CRIT-001** `api/routes_orders.py:159-184` — N+1 in position_fills endpoint. Batch-fetch via IN-clause. Single SELECT to pre_trade_log with `calc_id IN (...)`, single SELECT to orders with `exchange_order_id IN (...)`, then join in memory. Verify endpoint latency drops by ≥10x on a position with 50+ fills.
- **CRIT-005** `core/ws_manager.py:496` — recursive `_reconnect_user(attempt+1)` before max-attempt guard. Move the guard before the recursive call. Add a unit test that asserts no stack overflow on persistent 401.
- **CRIT-006** `core/data_logger.py:216-218` — export ignores active account. Pass `account_id=app_state.active_account_id` to all three `db.get_all_*` calls. Test with multi-account setup verifying each account exports its own data.

**Why grouped:** all three are data-integrity / availability issues that prevent v2.4.1 release if unaddressed.

---

## Phase 3: High Correctness — Order/Position Lifecycle

**Branch:** `v2.4/audit-phase3a` + `v2.4/audit-phase3b`
**Framing:** Pattern A
**Tasks:** 2

### Task 87: Order/position state correctness (Phase 3a)

- **HIGH-004** `core/data_cache.py:516` — inconsistent null-checks in portfolio recalc
- **HIGH-005** `core/order_manager.py:526-562` — TP/SL enrichment with `mark=0`
- **HIGH-006** `core/ws_manager.py:159-195` — position list iterated during concurrent modification (fix: `list(app_state.positions)` snapshot)
- **HIGH-009** `core/order_manager.py:654-666` — overfill validation (`total_close_qty <= total_open_qty`)

Tests: each fix gets a regression test exercising the specific edge case.

### Task 88: Order lifecycle gaps (Phase 3b)

- **HIGH-019** `core/order_manager.py` — position added to state before TP/SL placed; if TP/SL fails, position unprotected. Add retry queue + "awaiting protection" flag.
- **HIGH-020** `core/exchange.py:144` — null-check on `app_state._data_cache` to match `fetch_positions` pattern.
- **HIGH-021** `core/contract_validation.py:38-53` — contract spec cache TTL too long (24h → 1-4h) + admin force-refresh endpoint.
- **HIGH-025** `core/order_enrichment.py:47-89` — partial fills don't re-enrich parent order. Re-run `_populate_tp_sl_trigger_prices()` per partial fill.

**Why split into 3a/3b:** Task 87 is state-validation fixes; Task 88 is lifecycle gaps. Different mental models for review.

---

## Phase 4: Reliability + State Machine Hardening

**Branch prefix:** `v2.4/audit-t{NN}-<finding-or-theme>`
**Framing:** Mixed — Pattern A (trading-path correctness), B (observability), C (reliability), D (security), F (UX).
**Tasks:** 11 (Tasks 95-105)

**Note:** task numbering reflects actual session sequence after Phase 3 (Tasks 91-94 + sub-tasks). Earlier draft of this section used Tasks 89-90 placeholders pre-execution; those numbers were consumed by actual Phase 2 work (Task 89 = CRIT-005/006, Task 90 = HIGH-004/005). Renumbered to current sequence.

### Phase 4 entry state

Active count entering Phase 4: **17 HIGH / 42 MED / 21 LOW = 80 total**.

HIGHs by phase target:
- Phase 4 territory (15): HIGH-007, HIGH-008, HIGH-010, HIGH-011, HIGH-012, HIGH-013, HIGH-014, HIGH-015, HIGH-017, HIGH-018, HIGH-022, HIGH-023, HIGH-024, HIGH-026, HIGH-027.
- Phase 6 deferred (1): HIGH-002 (`db._conn` refactor).
- Phase 8 deferred (1): HIGH-001 (no auth).

Expected exit: **2 HIGH / ~30 MED / ~18 LOW ≈ 50 total** (assuming bundled MEDs land + Phase 3 verify-false rate holds).

### Top-5 clearance gates

Top 5 currently: HIGH-001, HIGH-012, HIGH-026, HIGH-027, HIGH-022. Phase 4 clears slots 2-5 (HIGH-001 stays — Phase 8). Order: Task 95 → slot 3 (HIGH-026), Task 96 → slot 2 (HIGH-012), Task 97 → slot 5 (HIGH-022), Task 104 → slot 4 (HIGH-027). Slots 2-5 exit Top 5 by end of Phase 4; HIGH-001 stays through to Phase 8.

### Task 95: HIGH-026 — Silent-swallow in `_build_close_row_for_fill`
**Findings:** HIGH-026 (OPEN; VERIFIED REAL per sweep batch 1b).
**Pattern:** B (observability).
**Scope:** `core/order_manager.py:737-741` — surface the outer `try/except Exception: log.exception(...)` either by re-raising after logging, emitting `engine_event("close_row_build_failed", ...)`, or returning a structured failure indicator. Pick based on caller contract.
**Estimated LOC:** ~30-50 production + ~30-50 tests.
**Verification:** none required — sweep batch 1b confirmed real. No NEEDS DEEP READ gate.
**Dependencies:** none.
**Notes:** Top-5 slot 3 clearance. Function was visited in Tasks 86, 86.1, 92 — touch surface is well-understood. Watch for changes to `insert_closed_position` call-pattern that might affect Task 104.

### Task 96: HIGH-012 — Account-switch closure (verify-first)
**Findings:** HIGH-012 (OPEN; NEEDS DEEP READ per sweep batch 1c — Task 92.5 inspection deferred).
**Pattern:** A (trading-path correctness) or pin-only.
**Scope:** `core/order_manager.py:594-599` — closure-over-`account_id` in `loop.call_later` lambda inside `process_fill`. Verify whether `account_id` is rebound anywhere in `process_fill`'s body. If stable (Task 93's halt-report hypothesis), VERIFIED FALSE pin; if rebound, real fix (explicit value capture + verify-active-before-insert).
**Estimated LOC:** pin-only ~30 LOC; real-fix ~30-50 production + ~30-50 tests.
**Verification:** **NEEDS DEEP READ gate.** Phase 3 pattern: 5/14 "race"-framed findings verified false. Hold hypothesis that HIGH-012 will also verify false.
**Dependencies:** none.
**Notes:** Top-5 slot 2 clearance. If verified false, the resolved/false ratio swings further toward "engine architecture is more correct than audit assumed."

### Task 97: HIGH-022 + HIGH-023 + MED-036 — Route input validation bundle
**Findings:** HIGH-022 (Top-5 slot 5, backtest date range), HIGH-023 (cross-param validation), MED-036 (max_position_count vs open positions).
**Pattern:** A (correctness) + D (defense-in-depth).
**Scope:** `api/routes_backtest.py`, `api/routes_params.py`. Add `(to_date - from_date) <= 730 days` validation; add `warning_threshold < limit_threshold` assert; add `max_position_count >= len(app_state.positions)` check before applying params.
**Estimated LOC:** ~50-80 production + ~30-50 tests.
**Verification:** sweep batch 1c VERIFIED REAL for HIGH-022 + HIGH-023; sweep batch 1c VERIFIED REAL for MED-036.
**Dependencies:** none.
**Notes:** Top-5 slot 5 clearance (HIGH-022). Bundle AA from sweep reports.

### Task 98: HIGH-017 + HIGH-018 — DD gate fail-closed + pubsub robustness
**Findings:** HIGH-017 (DD gate fails OPEN on DB error), HIGH-018 (pubsub kills subscriber on any exception).
**Pattern:** C (reliability).
**Scope:** `core/dd_gate.py:46-47` — change `except Exception: return True, None` to fail-closed semantics. `core/pubsub/in_process_bus.py:46` — narrow `except Exception` to only QueueFull; log other exceptions without removing the queue.
**Estimated LOC:** ~30-50 production + ~30-50 tests.
**Verification:** both VERIFIED REAL per sweep batch 1d.
**Dependencies:** none.
**Notes:** Both small single-finding fixes; bundle to share planning + commit overhead.

### Task 99: HIGH-007 + HIGH-014 + HIGH-015 + LOW-019 — Adapter observability/reliability bundle
**Findings:** HIGH-007 (weight tracker silent swallow), HIGH-014 (weight tracker never reconciles vs response headers), HIGH-015 (commission fetch silent fail in both binance + bybit adapters), LOW-019 (price extremes silent fail).
**Pattern:** C (reliability) + B (observability).
**Scope:** `core/adapters/base.py`, `core/adapters/binance/rest_adapter.py`, `core/adapters/bybit/rest_adapter.py`. Add `log.warning` on swallowed exceptions; HIGH-014 needs response-header parsing for reconciliation (moderate effort).
**Estimated LOC:** ~40-60 production (HIGH-007/HIGH-015/LOW-019 are 1-3 LOC each; HIGH-014 is 20-30 LOC) + ~40-60 tests.
**Verification:** all VERIFIED REAL per sweep batch 1b (HIGH-007) and 1c (HIGH-014, HIGH-015, LOW-019).
**Dependencies:** none.
**Notes:** Bundle K + N per sweep. File locality (all adapter layer) makes context-switching cheap.

### Task 100: HIGH-024 — Credential leak (api_key in traceback)
**Findings:** HIGH-024.
**Pattern:** D (security).
**Scope:** `api/routes_connections.py:128` — wrap api_key in a `SensitiveStr` class that masks `__repr__`. Class lives in `core/security.py` (new file) or as a util in an existing module.
**Estimated LOC:** ~30 production (class + 1-line wrap at call site) + ~20 tests.
**Verification:** VERIFIED REAL per sweep batch 1c.
**Dependencies:** none.
**Notes:** Bundle BB from sweep.

### Task 101: HIGH-011 + MED-003 + MED-022 — SQL injection defense-in-depth bundle
**Findings:** HIGH-011 (filter column whitelist in db_trades), MED-003 (sort_by/sort_dir whitelist at route level), MED-022 (parameterize LIKE prefix in mark_stale_orders_canceled).
**Pattern:** D (security / defense-in-depth).
**Scope:** `core/db_trades.py:57-59`, `api/routes_orders.py` + `api/routes_history.py`, `core/db_orders.py:362,364`. Add `_ALLOWED_FILTER_COLS` set; route-level `sort_by in ALLOWED` check; replace f-string LIKE with `?` placeholder.
**Estimated LOC:** ~30-50 production + ~30-50 tests.
**Verification:** all VERIFIED REAL per sweep batch 1a (MED-003), 1c (HIGH-011, MED-022).
**Dependencies:** none.
**Notes:** Bundle J from sweep. All defense-in-depth — no live exploitable injection today, but hardens the layer.

### Task 102: HIGH-013 + MED-018 — Trust-but-verify exchange responses bundle
**Findings:** HIGH-013 (Binance missing account fields default to 0), MED-018 (negative equity not clamped in data_cache).
**Pattern:** A (correctness — exchange-data ingest).
**Scope:** `core/adapters/binance/rest_adapter.py:72-79` — validate critical fields (equity, balance) present and > 0; raise if missing. `core/data_cache.py:768` — clamp `total_equity = max(0.0, balance + unrealized)` or trigger liquidation warning.
**Estimated LOC:** ~30 production + ~30-50 tests.
**Verification:** both VERIFIED REAL per sweep batch 1c.
**Dependencies:** none.
**Notes:** Bundle M from sweep. Both about not trusting that exchange responses are well-formed; both about not silently using 0/negative values that corrupt downstream risk metrics.

### Task 103: HIGH-008 — Scheduler auth error
**Findings:** HIGH-008.
**Pattern:** C (reliability).
**Scope:** `core/schedulers.py:134-141` — catch `AuthenticationError` in `_account_refresh_loop`; log CRITICAL + disable periodic refresh for affected account (don't crash the task).
**Estimated LOC:** ~20-30 production + ~20-30 tests.
**Verification:** VERIFIED REAL per sweep batch 1b. **Light architectural check**: confirm scheduler-side error handling doesn't assume engine-side order placement (Task 93 architecture pattern — should be fine here since this is account-fetch not order-placement, but verify upfront).
**Dependencies:** none.
**Notes:** Bundles naturally with MED-012 (no task restart on crash) — could fold MED-012 into this task if scope fits, else defer MED-012 to Phase 4 follow-up. Bundle E from sweep.

### Task 104: HIGH-027 — Calc-to-fill matching window + UI + countdown
**Findings:** HIGH-027 (Top-5 slot 4; scope refined in Task 94.1 to include UI).
**Pattern:** A (correctness) + F (UX).
**Scope:**
  - Backend: `core/exec_link.py` (time-window check in `compute_exec_match`), `accounts` table migration (per-account `link_window_seconds`), `pre_trade_log` migration (per-pretrade `link_window_seconds_override`).
  - Frontend: account settings editor, calculator override input, live countdown element near calculator.
  - DB migration: defensive for existing rows (6h default backfill).
**Estimated LOC:** ~200-300 total + tests (per Task 94.1 refined estimate). Largest task in Phase 4.
**Verification:** VERIFIED REAL (architectural gap, not race). Open design decisions per Task 94.1's audit-doc entry need resolution before implementation (MAX_LINK_WINDOW default, countdown precision, expired-state UI).
**Dependencies:** **Task 95 (HIGH-026) recommended first** — both touch position-lifecycle / close-path code; sequencing avoids merge friction. Could parallelize if branches stay disjoint.
**Notes:** Slot 4 Top-5 clearance. Sequence after smaller wins (95-103) so design decisions can incubate. May split into 104a (backend + tests) and 104b (UI + countdown) if scope balloons.

### Task 105: HIGH-010 — Crypto silent fallback
**Findings:** HIGH-010 (HIGH-016 is consolidated duplicate).
**Pattern:** D (security).
**Scope:** `core/crypto.py:54-56` — raise on decryption failure OR set `app_state.disable_trading` flag. Audit's `log.error` mitigation (already in code) doesn't propagate; callers still receive `""` and proceed with empty credentials.
**Estimated LOC:** ~20 production + ~20 tests.
**Verification:** VERIFIED REAL per sweep batch 1c.
**Dependencies:** none.
**Notes:** Standalone. Could ride earlier in Phase 4 (no real dependencies) but parked here so credential-related work clusters with HIGH-024 area (Task 100).

### Phase 4 totals

| Estimate | Value |
|---|---|
| Production LOC (sum) | ~620-870 |
| Test LOC (sum) | ~340-510 |
| Total | **~960-1380 LOC** |
| Task count | 11 |
| HIGH findings cleared | 15 (resolved or verified false) |
| Bundled MEDs/LOWs | 5 (MED-003, MED-018, MED-022, MED-036, LOW-019); more may ride along during fix work |

Under the 1500 LOC threshold for a single phase. No need for 4a/4b split.

### Bundle drop log (sweep proposals that no longer apply)

Sweep batches 1a-1e proposed Bundles A-GG. Outcomes post-Phase 3:

| Bundle | Original scope | Disposition |
|---|---|---|
| V | HIGH-019 + HIGH-025 + HIGH-026 position-protection cluster | **Dropped.** HIGH-019 and HIGH-025 verified false. HIGH-026 remains, but as standalone Task 95. |
| W | HIGH-020 startup-race null-checks | **Dropped.** HIGH-020 resolved Task 93. |
| X | HIGH-021 + MED-017 + MED-032 cache freshness | **Partially absorbed.** HIGH-021 resolved Task 94. MED-017 + MED-032 remain — defer to Phase 5 cache-freshness rollup. |
| Q | MED-002 + MED-016 + MED-018 epsilon hardening | **Partial.** MED-018 absorbed into Task 102. MED-002 + MED-016 remain for Phase 5. |
| O | MED-005 + MED-028 async-blocking-IO | **Deferred to Phase 5** (performance pass). |
| F | MED-013 + MED-014 template UI fixes | **Deferred to Phase 11 / frontend pass** (out of Phase 4 reliability scope). |
| L | MED-020 + LOW-017 graceful shutdown | **Deferred to Phase 5 or Phase 12** (lifecycle hygiene). |
| P | MED-023 + MED-025 + MED-026 platform-bridge hardening | **Deferred to Phase 5** (platform bridge work clusters). |
| Y | MED-024 broker_account_id UNIQUE | **Deferred to Phase 5** (DB schema work). |
| Z | MED-034 + MED-035 order state machine | **Deferred to Phase 5** (state machine batch). |

Bundles A-I and others not listed: either already absorbed into Phase 1-3 tasks or scoped to Phase 5/6/11/12 by theme.

### Phase 4 session count estimate

At observed pace of ~1-2 tasks per session (single bundled task or 2 standalone), Phase 4 = **8-11 sessions**. Sequencing optimization: Task 95 (small, Top-5) + Task 96 (verify-gate, could be pin-only) + Task 98 (small bundle) could fit in 1-2 sessions; Task 104 (HIGH-027 UI) is likely a 2-session task on its own. Roughly **10 sessions = ~3 weeks at one session/2 days**.

### Phase 4 Status: COMPLETE (tagged v2.4.1)

11 main tasks executed (95-105) + 9 interstitials (94.1, 94.2, 97.1, 99.1, 101.1, 102.1, 103.5, plus the 104a/104b split).

Stat Summary at Phase 4 close:
- 0 CRIT
- 6 HIGH (all deferred follow-ups or architectural — HIGH-001, HIGH-002, HIGH-028, HIGH-029, HIGH-030, HIGH-031)
- 39 MED
- 21 LOW
- **66 active**

Tagged **v2.4.1** at the Task 106 commit (which adds CHANGELOG.md + this closure note). Task 105 tip was 938e50f; the tag attaches to the Task 106 commit one level above.

Calibration patterns documented across Phase 4:
- Race-framing false-positive rate stable at 8 / 15 (53 %).
- Audit-impact-imprecision pattern at 4 examples (HIGH-019, HIGH-026, HIGH-013, HIGH-008) — all real bugs but with mechanism / direction the audit described incorrectly. Implication recorded: trace downstream consumers independently when investigating, fix the real harm not the described one.

Resolved this phase: HIGH-008, HIGH-010, HIGH-011, HIGH-013, HIGH-014, HIGH-015, HIGH-017, HIGH-018, HIGH-022, HIGH-023, HIGH-024, HIGH-026, HIGH-027, plus the supporting MED + LOW (see CHANGELOG.md for the full list).

Phase 5 entry: addresses analytics + quality findings + the four deferred follow-ups (HIGH-028 / 029 / 030 / 031) + MED batch + LOW batch. Pre-Phase-5 task: draft Phase 5 bundle plan parallel to Task 94.2's structure.

---

## Phase 5: Performance

**Branch:** `v2.4/audit-phase5-performance`
**Framing:** Pattern E (Performance)
**Tasks:** 1

### Task 91: Performance fixes

- **HIGH-003** Missing indexes on `pre_trade_log.calc_id` and `orders.calc_id`. Add via migration. Run EXPLAIN QUERY PLAN to verify usage.
- **MED-005** Sync sqlite3 in async paths. Audit all callers; wrap in `to_thread()` where missing.
- **MED-006** HTMX polling on hidden tabs. Use intersect trigger or visibility API to pause hidden-tab polling.
- **MED-007** OHLCV cache growth. Add max-age eviction + symbol cleanup.

Verification: micro-benchmark each fix. position_fills endpoint latency, calc_id lookup query time (with and without indexes), poll-request count per minute.

**End of v2.4.1 patch scope.** After this lands, tag `v2.4.1`.

---

## Phase 6: Architecture — `db._conn` Refactor (v2.5)

**Branch:** `v2.4/audit-phase6a/b/c`
**Framing:** Pattern D (Architecture / Refactor)
**Tasks:** 3

### HIGH-002: 24 locations bypass DatabaseManager API

Refactor `db._conn.execute(...)` direct access into public helper methods. Split by area:

- **Task 92 — Routes layer (8 locations):** `api/routes_orders.py`. Create `db.batch_get_pretrade_logs()`, `db.get_closed_position()`, etc.
- **Task 93 — Platform bridge (8 locations):** `core/platform_bridge.py`. Create helpers for bridge-specific queries.
- **Task 94 — Monitoring/reconciler (8 locations):** `core/monitoring.py`, `core/reconciler.py`, others.

Each task: 8 call sites + corresponding new public methods + test that the refactored callers behave identically.

---

## Phase 7: Security Baseline (v2.5, excluding auth)

**Branch:** `v2.4/audit-phase7-security-baseline`
**Framing:** Pattern C (Security)
**Tasks:** 1

### Task 95: Security hardening (no auth)

- **MED-003** sort_by / sort_dir validation at route level
- **MED-004** KDF (PBKDF2/scrypt) instead of plain SHA256
- **MED-022** SQL injection in `mark_stale_orders_canceled` LIKE clause
- **MED-040** SRI hashes on CDN scripts (htmx, idiomorph, echarts)
- **MED-041** Content-Security-Policy middleware
- **LOW-001** Ticker input format validation

---

## Phase 8: Authentication (v2.5, LARGE)

**Branch:** `v2.4/audit-phase8a/b/c`
**Framing:** Pattern C
**Tasks:** 2-3

### HIGH-001: No authentication on any API endpoint

This is the biggest single finding. Split:

- **Task 96 — Auth foundation:** Session middleware, token generation/validation, login endpoint, password storage (use argon2 or bcrypt), DB schema for users.
- **Task 97 — Endpoint protection:** `Depends(get_current_user)` on all routes. Per-account scoping where appropriate.
- **Task 98 — UI integration:** Login page, session cookies, logout, CSRF tokens for state-changing endpoints.

Discuss before starting: does the deployment context (single-user localhost) actually need this? If yes, full implementation. If no, document the decision and defer indefinitely with a clear "single-user only" warning in README.

---

## Phase 9: State Robustness + Account Isolation (v2.5)

**Branch:** `v2.4/audit-phase9a/b`
**Framing:** Pattern B
**Tasks:** 2

### Task 99: Account isolation

- **HIGH-012** Account switch race condition with deferred close-row build.
- **MED-001** Position lookup falls back to entry_price=0.0 when not in memory.
- **MED-010** Concurrent processing of same exchange_fill_id (asyncio.Lock).

### Task 100: State validation + shutdown

- **MED-016** Negative position size when slippage ≥ 100%.
- **MED-017** Mark price cache without age tracking.
- **MED-018** Negative equity not clamped.
- **MED-019** max_position_count advisory only — enforce at order submission.
- **MED-020** Background tasks not cancelled on shutdown.
- **MED-021** Config values parsed without validation.

---

## Phase 10: UI/UX Polish (v2.5)

**Branch:** `v2.4/audit-phase10-ui-polish`
**Framing:** Pattern D
**Tasks:** 1

### Task 101: History page UI/UX fixes

- **MED-013** Event type dropdown loses search state (`hx-include="closest div"`)
- **MED-014** Trade Events uses custom pagination instead of macro
- **MED-015** Tab switch race with auto-poll (cancel pending on switch)
- **LOW-013** Open positions subtab flicker on 1s refresh
- **LOW-014** Exec link panel caching prevents refresh after confirm

---

## Phase 11: Test Coverage Expansion (v2.5, ongoing)

**Branch:** `v2.4/audit-phase11a/b/c`
**Framing:** Pattern F (Testing)
**Tasks:** 2-3

### MED-009: 41/59 modules lack dedicated tests

Priority order from the audit:
- **Task 102:** `core/exec_link.py` tests (new module, untested) + `core/order_enrichment.py` tests (critical path, untested).
- **Task 103:** `core/crypto.py` tests (security-critical) + `core/db_orders.py` tests (842 LOC, fragmented coverage).
- **Task 104:** `core/ws_manager.py` tests (reconnect logic, message handling) + `core/reconciler.py` tests.

Each task: target ~80% line coverage on the named module. Stop-and-report; don't try to test all 41 in one task.

---

## Phase 12: Low-Priority Cleanup

**Branch:** `v2.4/audit-phase12-cleanup`
**Framing:** Pattern D
**Tasks:** 1

### Task 105: LOW findings batch

Bundle remaining LOW findings:
- **LOW-004** dead code (`load_recent_history`)
- **LOW-005** print → log in `ohlcv_fetcher`
- **LOW-006** downgrade ~20 warnings to info/debug
- **LOW-011** delete migration 008 placeholder
- **LOW-012** add EXEC_LINK_PRICE_TOL to .env.example
- **LOW-015** document migration recovery procedure
- **LOW-016** per_page upper bound
- **LOW-017** event_bus close() implementation
- **LOW-018** (duplicate, already covered)
- **LOW-019** logging in adapter exception handlers
- **LOW-020** static asset Cache-Control headers
- **LOW-021** SSE connection limit

---

## Recommended Sequencing

**Week 1 (v2.4.1 patch):**
- Day 1-2: Phase 1 + Phase 2 (Tasks 85-86) → critical bugs cleared
- Day 3-4: Phase 3 + Phase 4 (Tasks 87-90) → high-severity correctness cleared
- Day 5: Phase 5 (Task 91) → performance baseline → tag v2.4.1

**Week 2-3 (v2.5 first half):**
- Phase 6 (Tasks 92-94) — db._conn refactor
- Phase 7 (Task 95) — security baseline
- Phase 9 (Tasks 99-100) — state robustness

**Week 3-4 (v2.5 second half — depends on auth decision):**
- Phase 8 (Tasks 96-98) — auth implementation IF needed for deployment
- Phase 10 (Task 101) — UI polish
- Phase 11 (Tasks 102-104) — test coverage
- Phase 12 (Task 105) — cleanup

**After v2.5 ships:**
- Frontend audit (Cowork + Playwright)
- v2.6 planning incorporates frontend findings + remaining backlog

---

## Failure Modes to Watch For

When Claude Code is grinding through audit fixes, common drift patterns:

1. **Scope creep within a task** — fixing finding X "while we're here" tempts fixing Y nearby. Resist unless trivial; otherwise add to a future phase.
2. **Over-engineering simple fixes** — div-by-zero is one early-return, not a whole defensive-programming rewrite.
3. **Insufficient testing** — every fix needs a regression test that fails before the fix and passes after. No "smoke test" hand-waving.
4. **Breaking abstractions in cleanup** — Phase 6 refactor is the right place to fix encapsulation. Don't do it ad-hoc in earlier phases.
5. **Skipping audit-doc updates** — when a finding is resolved, mark it in the audit doc. When a finding turns out wrong on closer inspection, document why.

If you see Claude Code drifting into any of these, push back. The plan trades thoroughness for safety — a slow, deliberate pace is the goal.

---

## When Phases Are Done

After each phase commit lands:
- Read Claude Code's report.
- Spot-check the diff (don't trust blind).
- Run engine briefly to confirm no regression in live use.
- Verify added tests pass and exercise the right thing (read at least 2-3 of them).
- Mark addressed findings in the audit doc.

After Phase 5 (v2.4.1): tag, write release notes, ship.
After Phase 11 or earlier exit criteria for v2.5: tag, write release notes, ship, then start frontend audit phase.

---

## Phase 5 — Bundle Plan (Task 109)

### 5.0 Status at planning time

Plan written against **current main** (`c2bd969`, v2.4.1 tag commit). Audit doc Stat Summary: **67 active — 0 CRIT / 6 HIGH / 40 MED / 21 LOW** (backend-only, including MED-047 filed this task).

Two branches exist but are NOT in main's lineage:
- `v2.4/audit-t107-frontend-merge` (`970b130`) — audit-doc-only merge of audit-01's 28 FE-* findings into the unified ledger.
- `v2.4.1/hotfix-t108-crit001` (`4ecd75d`) — v2.4.1.1 hotfix; resolves FE-CRIT-001 + FE-HIGH-005 + FE-MED-014 + FE-LOW-001, files + resolves FE-MED-015. Also includes a fast-forward merge of Task 107 inside.

After both merge into main, the ledger reaches the combined post-hotfix state (~91 active, 0 CRIT, 11 HIGH including the 5 unresolved FE-HIGHs, 54 MED, 27 LOW). Phase 5 bundle execution is keyed to that post-merge state; pre-Phase-5 merge is itself a prerequisite mini-task.

### 5.1 Pre-Phase-5 prerequisites (must merge before mini-phase 5.1 starts)

These are not Phase 5 work themselves — they restore the lineage the rest of Phase 5 plans against.

| Step | Action | Outcome |
|------|--------|---------|
| 1 | `git checkout main && git merge v2.4/audit-t107-frontend-merge --ff-only` | Audit doc gains 28 FE-* entries (Sections 30-35). Stat Summary becomes 94 active. |
| 2 | `git merge v2.4.1/hotfix-t108-crit001` | Resolves FE-CRIT-001 + 4 bundled + FE-MED-015. Stat Summary becomes 91 active. Tag v2.4.1.1 already exists locally. |
| 3 | Reconcile any merge conflict on the audit doc Stat Summary (the +MED-047 line filed this task may collide with Task 108's combined-ledger updates). | Single coherent post-merge Stat Summary. |
| 4 | Operator smoke-checks v2.4.1.1 per smoke-checklist document; pushes tag to origin when satisfied. | v2.4.1.1 operationally trusted. |

If the operator decides NOT to merge the hotfix (intentional rollback was visible in earlier session reminders), then FE-CRIT-001 stays open and must be re-addressed inside Phase 5. The bundle plan below assumes the hotfix lands.

### 5.2 Inventory (post-prerequisite-merge)

| Source | CRIT | HIGH | MED | LOW | Total |
|---|---|---|---|---|---|
| Backend audit (Phase 1-4 deferred + MED-047) | 0 | 6 | 40 | 21 | 67 |
| Frontend audit-01 (minus v2.4.1.1 hotfix) | 0 | 5 | 14 | 6 | 25 |
| **Combined Phase 5 scope** | **0** | **11** | **54** | **27** | **92** |

If t107/t108 are NOT merged before Phase 5 begins, the in-scope inventory shrinks to the 67 backend-only entries — FE-* work moves to a later phase.

### 5.3 Pattern groups (leverage-first bundles)

Same approach as Task 94.2: group by leverage / pattern, not severity.

**Bundle A — Missing UI primitives (leverage refactor; biggest payoff)**

Build Card / TableRow / EmptyState / StatusIndicator / PeriodSelector primitives. Migrate page-by-page.

Resolves (post-merge):
- FE-MED-001 (Analytics card spacing)
- FE-MED-002 (TableRow drift)
- FE-MED-006 (7 empty-state treatments)
- FE-MED-007 (Regime period selector duplication)
- FE-MED-008 (regime not-backfilled inconsistent)
- FE-LOW-003 (Connections card layout drift)
- FE-LOW-005 (provider naming inconsistency)
- Possibly FE-HIGH-001 (Plugin OFF — touches StatusIndicator)

Estimated: 5-7 tasks (one per primitive + first-migration reference page each). The mini-phase that pays for itself fastest — 8+ findings resolved per 5 primitives.

**Bundle B — Bybit/MEXC adapter completeness (Phase 4 deferred follow-ups)**

Sequence-critical: FE-HIGH-002 (UI exposure) MUST come first; the three backend parallels can't be verified end-to-end without it.

1. **FE-HIGH-002** — populate Add Account modal's EXCHANGE dropdown from the adapter registry.
2. **HIGH-028** — Bybit `_reconcile_from_response()` override (parallel to Task 99's Binance fix).
3. **HIGH-030** — Bybit account-field validation (parallel to Task 102's Binance fix).
4. **HIGH-031** — MEXC account-field validation (parallel; reduced impact since read-only adapter).

Estimated: 4 tasks. Each ~1 of the prior Phase 4 tasks in size.

**Bundle C — Credential & security hardening**

- **HIGH-029** — credential traceback leak in `api/routes_accounts.py` (5 sites) + `core/account_registry.py` post-decryption sites. Parallel to Task 100's narrow-scope SensitiveStr fix.
- **MED-046** — `_CREATE_STATEMENTS.split(";")` footgun. Switch to `sqlite3.executescript()`.
- **MED-047** — template wiring-pin retrofit. Opportunistic — done in-place when each template is next touched, not as a standalone task.

Estimated: 2-3 tasks. MED-047 is mostly absorbed by Bundles A/D/E touching templates.

**Bundle D — Data quality + performance (FE-side; needs operator answers first)**

Blocked by audit-01 Open Questions:
- **FE-HIGH-003** + **FE-MED-004** — Trade Events Log BTCUSDT entries (`entry_price: 0.0`, CALC ID always `—`). Audit-01 Open Q #4: are these real / replay / test pollution? Answer determines fix scope (clean DB + add write-time validation vs. ignore as test artifact).
- **FE-HIGH-004** — Dashboard 1Hz `/fragments/ws_status` polling → SSE. Audit-01 Open Q #3: is the 1Hz cadence intentional?
- **FE-HIGH-006** — Trade Events Log raw-JSON expansion → key-value grid.
- **FE-MED-003** — duplicate timestamps in Events Log (group under parent row, or fix duplicate emission).
- **FE-MED-013** — Analytics Performance Ratios partial coverage (SORTINO MAE / PROFIT FACTOR / EXPECTANCY missing).
- **FE-MED-009** — Equity Curve y-axis auto-scale.

Estimated: 3-4 tasks after operator answers.

**Bundle E — Calculator / Settings UX polish**

- **FE-MED-005** — Calculator Recent card date-less timestamps. Audit-01 Open Q #2 (relative vs absolute format).
- **FE-MED-011** — Calculator `_SIZE`, `EST_SIZE` underscore labels.
- **FE-MED-012** — `1% DEPTH` / `FEE (2X)` ambiguous labels (tooltip or rename).

Estimated: 1-2 tasks.

**Bundle F — Deferred architectural (NOT Phase 5 work; documented as deferred)**

- **HIGH-001** — auth on all endpoints. Phase 8 (deployment context decision).
- **HIGH-002** — `db._conn` private-attribute access across 24 sites. Phase 6 (architectural refactor).

**Bundle G — Remaining backend MEDs + LOWs**

Backend MEDs + LOWs not pattern-matched above. Audit individually, bundle by pattern as opportunities emerge during execution. Includes MED-044 (ws_manager recursion-vs-iteration), MED-007 (cache eviction), and others not yet pattern-matched.

Estimated: variable — 5-10 tasks depending on bundling success.

### 5.4 Execution order

```
Pre-5.0 — Merge t107 + t108 into main (lineage restoration; see 5.1)
          Outcome: combined ledger at 91 active.

Mini-phase 5.0 — Audit-02 pass (close coverage gaps)
                 Tasks: 1 (Claude-in-Chrome session, ~60-90 min)
                 Coverage: Analytics sub-tabs (8), Regime sub-tabs (3),
                           Backtest sub-tabs (3), Calculator populated state
                           + countdown UI states, mobile breakpoint,
                           multi-account behavior, hover/focus, number
                           formatting scan, SSE flicker.
                 Output: docs/audits/2026-05-XX-v2.4-frontend-audit-02.md +
                         unified-ledger merge into the main audit doc
                         (Task 107 pattern).
                 Operator-decisions gate: answers to audit-01 Open Qs #1-#5
                                          must be captured here.

Mini-phase 5.1 — Primitive scaffolding (Bundle A)
                 Tasks: 5-7
                 Sequence: Card → TableRow → EmptyState → StatusIndicator →
                           PeriodSelector. Migrate one reference page per
                           primitive (Analytics for Card; History for TableRow;
                           Dashboard for EmptyState; header for StatusIndicator;
                           Regime for PeriodSelector).

Mini-phase 5.2 — Bybit/MEXC adapter completeness (Bundle B)
                 Tasks: 4
                 Sequence-critical: FE-HIGH-002 → HIGH-028 → HIGH-030 → HIGH-031.

Mini-phase 5.3 — Credential hardening + housekeeping (Bundle C)
                 Tasks: 2-3
                 Includes opportunistic MED-047 retrofits as 5.1 / 5.4 / 5.5
                 touch templates.

Mini-phase 5.4 — Data quality + performance (Bundle D)
                 Tasks: 3-4
                 Dependency: audit-01 Open Qs #3 + #4 answered.

Mini-phase 5.5 — Calculator / Settings UX polish (Bundle E)
                 Tasks: 1-2
                 Dependency: audit-01 Open Q #2 answered.

Mini-phase 5.6 — Remaining MED/LOW cleanup (Bundle G)
                 Tasks: variable (~5-10).

Phase 5 close target: Stat Summary < 30 active across all severities.
Phase 5 tag candidate: v2.5.0 (or v2.4.2 / v2.4.3 if scope contracts).
```

### 5.5 Open dependencies (must answer before relevant mini-phase)

These are audit-01's open questions, surfaced for the operator. Some affect bundle scope; others affect individual fix shape.

1. **Mobile / narrow viewport intended?** (audit-01 Open Q #1) — drives Bundle A scope (responsive breakpoints in primitives). If desktop-only, document and stop optimising for narrow.
2. **Calculator timestamp format preference?** (audit-01 Open Q #2) — drives FE-MED-005 fix (relative "Today 16:07" vs absolute "2026-05-18 16:07"). Product-preference call.
3. **`ws_status` polling cadence intentional?** (audit-01 Open Q #3) — drives FE-HIGH-004 fix (SSE vs back off to 5-10 s vs leave alone).
4. **BTCUSDT events real / replay / test?** (audit-01 Open Q #4) — drives FE-HIGH-003 + FE-MED-004 scope (clean DB + write-time validation vs filter at display time).
5. **Add Account Bybit/MEXC presentation?** (audit-01 Open Q #5) — drives FE-HIGH-002 fix detail (beta tag vs warning vs full enable).

These should be answered during mini-phase 5.0 (audit-02) so the rest of Phase 5 isn't blocked on operator decisions.

### 5.6 Calibration patterns to carry forward

Documented Phase 1-4 patterns, top-of-mind for Phase 5:

1. **Race-framing FP rate: 8 / 15 (53 %)** — race-framed findings default to verify-before-fix. Audit's "race / concurrent / interleave" language typically describes a real bug but with the wrong mechanism.
2. **Audit-impact-imprecision (4 examples in Phase 4 — HIGH-019, HIGH-026, HIGH-013, HIGH-008)** — trace downstream consumers independently of the audit's described mechanism. Real bug, wrong description; fix the real harm.
3. **Template compile-test discipline (MED-047)** — source-string greps are insufficient for Jinja2. Every template-touching task needs a real `jinja2.Environment.render` test against a synthetic context.
4. **Audit-doc-source-document commit discipline** — referenced source docs (audit reports, screenshots) must commit in the same commit. Task 107 referenced audit-01 but didn't commit it; Task 108 had to backfill. Don't repeat.
5. **Branch lineage discipline (introduced this task)** — release-tag tasks (Task 106) and audit-merge tasks (Task 107) and hotfix tasks (Task 108) all need to be checked into main's lineage before the next planning cycle. Otherwise downstream tasks (like Task 109) hit Stat-Summary drift and have to choose between three reconciliation paths.

### 5.7 Latent observations (surfaced during this inventory pass)

- **Bundle A's biggest payoff is the StatusIndicator primitive resolving the Plugin OFF misread (FE-HIGH-001).** This is the only Bundle A item that touches a HIGH-tier finding; the rest are MED/LOW. Worth sequencing StatusIndicator early in 5.1 so FE-HIGH-001 closes alongside the leverage refactor.
- **MED-047 retrofit cost is opportunistic, not standalone.** Bundles A / D / E all touch templates; each task in those bundles should adopt the compile-render pattern. Counting MED-047 as a standalone task is double-counting.
- **Audit-02 prerequisites mini-phase 5.1.** Audit-02 itself might surface FE-CRIT or FE-HIGH that displaces primitive work. Run audit-02 first, then plan 5.1 against the post-02 inventory.
- **No Phase 5 finding has a money-at-risk shape** — the four deferred backend HIGHs are all Bybit / MEXC parallels or credential-traceback parallels (operational hardening, not active trading correctness). v2.4.1's CRIT/HIGH-tier trading-loop work is done. Phase 5 is hygiene + UX.
