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

## Phase 4: High Correctness — WS, Security, Risk

**Branch:** `v2.4/audit-phase4a` + `v2.4/audit-phase4b`
**Framing:** Pattern B for 4a, Pattern C for 4b
**Tasks:** 2

### Task 89: WebSocket + background task reliability

- **HIGH-007** `core/adapters/base.py:109-110` — weight tracker exceptions silently swallowed. Add `log.warning`.
- **HIGH-008** `core/schedulers.py:134-141` — `AuthenticationError` not caught; disable refresh for affected account.
- **HIGH-010** `core/crypto.py:54-58` — decryption silently returns ""; raise or set app_state flag.
- **HIGH-018** `core/pubsub/in_process_bus.py:46` — only QueueFull should disconnect; other exceptions log without removing the queue.

### Task 90: Risk engine + DD enforcement correctness

- **HIGH-011** `core/db_trades.py:57-59` — filter column whitelist
- **HIGH-017** `core/dd_gate.py:46-47` — DD gate fail-closed instead of fail-open (CRITICAL semantics for enforced mode)
- **HIGH-022** `api/routes_backtest.py:85` — date range validation (max 730 days)
- **HIGH-023** `api/routes_params.py:50` — cross-param validation (warning < limit)
- **HIGH-024** `api/routes_connections.py:55` — API keys in tracebacks; sanitize

**Why grouped:** Task 89 is about not-failing-silently in async code; Task 90 is about gates and validation. Both critical for safety.

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
