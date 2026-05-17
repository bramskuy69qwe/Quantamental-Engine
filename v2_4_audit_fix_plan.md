# v2.4 Audit Fix Implementation Plan (Revised — Smaller Tasks)

**Source:** `docs/audits/2026-05-17-v2.4-backend-audit.md` (92 findings)
**Branch tip:** `v2.4/backend-audit` (clean single commit on top of `v2.4/docs-update`)
**Target:** clear all Critical + High, selective Medium for v2.4.1; defer rest to v2.5

**Granularity:** 1-3 findings per task, average ~2. Each task is focused enough that Claude Code can hold full context without drift.

---

## Branch State

After the cleanup prompt: `v2.4/backend-audit` should be a single clean commit on top of `v2.4/docs-update`, containing only the final audit doc. All audit-fix branches stack linearly off this tip, one branch per task.

---

## Phase Overview

| Phase | Focus | Tasks | Findings Covered | Release Target |
|-------|-------|-------|------------------|----------------|
| 1 | Critical trading-path correctness | 3 | CRIT-002, -003, -004 | v2.4.1 |
| 2 | Critical reliability + data integrity | 2 | CRIT-001, -005, -006 | v2.4.1 |
| 3 | High correctness — order/position state | 4 | 8 HIGH | v2.4.1 |
| 4 | High correctness — async + security validation | 5 | 9 HIGH | v2.4.1 |
| 5 | Performance | 2 | 1 HIGH + 3 MED | v2.4.1 |
| 6 | Architecture — `db._conn` refactor | 4 | HIGH-002 (split by area) | v2.5 |
| 7 | Security baseline (no auth) | 3 | 4 MED + 1 LOW | v2.5 |
| 8 | Authentication (if needed) | 3 | HIGH-001 | v2.5 |
| 9 | State robustness + account isolation | 5 | 1 HIGH + 7 MED | v2.5 |
| 10 | UI/UX polish | 2 | 3 MED + 2 LOW | v2.5 |
| 11 | Test coverage expansion | 3 | MED-009 (ongoing) | v2.5 |
| 12 | Low-priority cleanup | 1 | All remaining LOW | opportunistic |

**v2.4.1 scope:** Phases 1-5 = **16 tasks**.
**v2.5 scope:** Phases 6-11 = **20 tasks**.
**Total:** 37 tasks for full audit cleanup.

---

## Senior-Engineer Framing Patterns

Append the appropriate framing at the **top** of each task prompt to set Claude Code's mental model.

### Pattern A — Trading-Path Correctness
> Act like a senior quant who's lost money to silent slippage bugs. You've seen division-by-zero crashes leave positions unmanaged, and you've debugged race conditions at 3am. Every change here goes through three filters: (1) does it preserve correctness under edge cases the original author didn't think of? (2) does it fail-safe (better to halt than corrupt)? (3) is the test rigorous enough that you'd bet capital on it?

### Pattern B — Reliability & Concurrency
> Approach this as a staff systems engineer responsible for a production trading platform. You've seen async bugs that only manifest under load. Your default stance: assume concurrent execution, assume any external call can fail, assume any cache can be stale. Every fix needs a story for what happens when the assumed-good case isn't.

### Pattern C — Security
> Think like a security engineer reviewing a financial system. You assume hostile inputs, leaky logs, compromised dependencies. Defense-in-depth is not optional — even if one layer "should" handle a class of bug, the second layer must exist. You're not paranoid; you're calibrated to the actual threat model of a system holding API keys with trading permissions.

### Pattern D — Architecture / Refactor
> Act like a tech lead doing a refactor. You move in small, safe steps. Each commit leaves the system green. You preserve existing behavior unless explicitly changing it. You write tests before changing the implementation so regressions surface immediately. Encapsulation, naming, and dependency direction matter — the goal is a codebase the next maintainer can understand without spelunking.

### Pattern E — Performance
> Approach this like a performance engineer. Measure first, fix second. Every change must have a clear "before/after" delta you can articulate (latency, query count, memory). Don't optimize without evidence; don't accept a fix without verification.

### Pattern F — Testing
> Act like a QA engineer who's been burned by tests that pass for the wrong reasons. Tests should exercise behavior, not implementation. They should fail loudly when intent breaks. Coverage % means nothing if the tests are vacuous. Each new test you write needs to defend a specific behavior with a specific assertion that would fail in a specific way if the code regressed.

---

## Phase 1: Critical Trading-Path Correctness (v2.4.1)

**Branch base:** `v2.4/backend-audit`
**Framing:** Pattern A

### Task 85: CRIT-002 — Slippage division-by-zero
- **File:** `core/risk_engine.py:159-161`
- **Bug:** `est_slippage = max(0.0, (est_fill_price - best_price) / best_price)` — only `entry_price <= 0` is guarded, not `best_price`
- **Fix:** Add guard `if best_price <= 0: return 0.0, entry_price`
- **Test:** Regression test passing `best_price=0`, asserts no exception, returns sensible default
- **Effort:** small (~20 LOC including test)

### Task 86: CRIT-003 — Close-position fee edge cases
- **File:** `core/order_manager.py:654-668`
- **Bugs (two):**
  1. `max(f["timestamp_ms"] for f in close_fills)` raises ValueError on empty list
  2. Fee ratio div-by-zero risk via ternary evaluation order
- **Fix:** Empty-list guards + replace ternary with explicit if/else for division
- **Test:** Empty close_fills regression test; zero total_open_qty regression test
- **Effort:** small (~50 LOC)

### Task 87: CRIT-004 — exec_link self-comparison
- **File:** `core/exec_link.py:55-56`
- **Bug:** `tp_match = price_near(pretrade.get("tp_price"), pretrade.get("tp_price"))` — both args same. Always True. Same for sl_match.
- **Design call before fixing:** Two options:
  - **Short-term (small):** document limitation that TP/SL criteria are plan-vs-plan (always pass); the real value of exec_link is entry price comparison only. Skip TP/SL match contributions, show 1/1 instead of 3/3.
  - **Long-term (medium):** query `orders` table for actual TP/SL orders placed for this position, compare those against pretrade plan.
- **Recommended:** ship short-term in Task 87; defer long-term to v2.5 as part of Phase 9 modification tracking work.
- **Test:** mismatched pretrade.tp_price vs actual order.tp_price — assert match logic doesn't false-positive
- **Effort:** small (short-term) / medium (long-term)

---

## Phase 2: Critical Reliability + Data Integrity (v2.4.1)

**Branch base:** stack on Phase 1 tip
**Framing:** Pattern B

### Task 88: CRIT-001 — N+1 query in position_fills endpoint
- **File:** `api/routes_orders.py:159-184`
- **Bug:** Per-fill loop fires 2 individual queries (pre_trade_log + orders lookups). 50 fills = 100 queries.
- **Fix:** Batch-fetch using `WHERE calc_id IN (...)` and `WHERE exchange_order_id IN (...)`, then join in memory.
- **Benchmark required:** Before/after latency on a position with 50+ fills. Target: ≥10x improvement.
- **Test:** Integration test with 50-fill position asserting query count drops from ~100 to ~3
- **Effort:** medium (~80 LOC + benchmark)

### Task 89: CRIT-005 + CRIT-006 — Stack overflow + export isolation
Two small, isolated fixes in separate files; bundled because each is ~20 LOC.

- **CRIT-005** `core/ws_manager.py:496` — Move max-attempt guard before recursive `_reconnect_user(attempt+1)` call. Test: assert no stack overflow when `create_listen_key()` fails persistently.
- **CRIT-006** `core/data_logger.py:216-218` — Pass `account_id=app_state.active_account_id` to `db.get_all_pre_trade_log()`, `get_all_execution_log()`, `get_all_trade_history()`. Test: multi-account setup, verify each exports its own data.
- **Effort:** small total (~40 LOC across both)

---

## Phase 3: High Correctness — Order/Position State (v2.4.1)

**Framing:** Pattern A

### Task 90: HIGH-004 + HIGH-005 — Null-check hygiene in recalc & enrichment
- **HIGH-004** `core/data_cache.py:516` — inconsistent null-checks in portfolio recalc; rolling_peak may be None
- **HIGH-005** `core/order_manager.py:526-562` — TP/SL enrichment proceeds with `mark=0`, picks arbitrary order via `min()` on equidistant zero-distances
- Both about defensive null/zero handling in adjacent code areas
- **Effort:** small-medium each, ~150 LOC total

### Task 91: HIGH-006 — Concurrent position list iteration
- **File:** `core/ws_manager.py:159-195`
- **Bug:** Iterates `app_state.positions` while `DataCache.apply_position_update_incremental()` modifies it
- **Fix:** Snapshot via `for p in list(app_state.positions):`
- **Test:** Concurrent modification test asserting no skip/duplicate during enrichment
- **Effort:** small (~30 LOC + concurrency test)

### Task 92: HIGH-009 — Overfill validation
- **File:** `core/order_manager.py:654-666`
- **Bug:** `total_close_qty` not capped at `total_open_qty`; fee proportional calc inflates on overfills
- **Fix:** `total_close_qty = min(total_close_qty, total_open_qty)` before fee calc
- **Test:** Synthetic overfill scenario; assert net_pnl matches expected
- **Effort:** small (~30 LOC)

### Task 93: HIGH-019 + HIGH-020 — Lifecycle & null-check
- **HIGH-019** `core/order_manager.py` — Position added before TP/SL placed; if TP/SL fails, position unprotected. Add retry queue + "awaiting protection" state flag.
- **HIGH-020** `core/exchange.py:144` — Null-check `app_state._data_cache` to match `fetch_positions` pattern (line 177)
- Both touch order/position lifecycle hygiene
- **Effort:** medium total (~150 LOC)

### Task 94: HIGH-021 + HIGH-025 — Cache freshness + partial fill re-enrichment
- **HIGH-021** `core/contract_validation.py:38-53` — Reduce contract spec cache TTL from 24h to 1-4h; add admin force-refresh endpoint
- **HIGH-025** `core/order_enrichment.py:47-89` — Partial fills don't re-enrich parent; stale TP/SL trigger prices on multi-fill entries. Re-run `_populate_tp_sl_trigger_prices()` per partial.
- Both about data-staleness fixes
- **Effort:** medium total (~120 LOC)

---

## Phase 4: High Correctness — Async + Security Validation (v2.4.1)

### Task 95: HIGH-007 + HIGH-008 — Silent async failures
**Framing:** Pattern B
- **HIGH-007** `core/adapters/base.py:109-110` — Weight tracker exceptions silently swallowed; add `log.warning`
- **HIGH-008** `core/schedulers.py:134-141` — `AuthenticationError` not caught in background refresh; disable refresh for affected account; log CRITICAL
- Both about not-failing-silently in async paths
- **Effort:** small total (~60 LOC)

### Task 96: HIGH-010 — Crypto decryption silent failure
**Framing:** Pattern C
- **File:** `core/crypto.py:54-58`
- **Bug:** `except (InvalidToken, Exception): return ""` — wrong master key returns empty creds; WS auth silently fails
- **Fix:** Raise on decryption failure; or log CRITICAL + set `app_state` flag to disable trading
- **Test:** Wrong master key scenario; assert detectable failure state
- **Effort:** small-medium (~50 LOC + state flag wiring)

### Task 97: HIGH-018 — PubSub queue spurious removal
**Framing:** Pattern B
- **File:** `core/pubsub/in_process_bus.py:46`
- **Bug:** Any exception during publish disconnects subscriber permanently; transient errors break SSE streams
- **Fix:** Only disconnect on `QueueFull`; log others without removing queue
- **Test:** Inject transient exception in publish path; assert subscriber still active after
- **Effort:** small (~40 LOC)

### Task 98: HIGH-011 + HIGH-017 — Filter whitelist + DD gate semantics
**Framing:** Pattern C
- **HIGH-011** `core/db_trades.py:57-59` — Add `_ALLOWED_FILTER_COLS` whitelist before f-string interpolation
- **HIGH-017** `core/dd_gate.py:46-47` — DD gate currently fails OPEN on DB error; flip to fail-CLOSED (or cache last-known enforcement mode). Semantics change — verify test coverage for enforced mode behavior.
- **Effort:** small-medium total (~80 LOC); HIGH-017 has semantic risk, careful review

### Task 99: HIGH-022 + HIGH-023 — Route input validation
**Framing:** Pattern C
- **HIGH-022** `api/routes_backtest.py:85` — Validate `date_to - date_from <= 730 days`; return 400 if exceeded
- **HIGH-023** `api/routes_params.py:50` — Cross-param validation: `dd_warning_threshold < dd_limit_threshold`
- Both are route-handler input hardening
- **Effort:** small total (~50 LOC)

### Task 100: HIGH-024 — API key traceback sanitization
**Framing:** Pattern C
- **File:** `api/routes_connections.py:55`
- **Bug:** API keys may appear in tracebacks if exception occurs during upsert
- **Fix:** Wrap key values in `Sensitive` masking object with safe `__repr__`; sanitize tracebacks in exception handler
- **Test:** Force exception during connection upsert; assert key not in log output
- **Effort:** small-medium (~60 LOC, depends on helper design)

---

## Phase 5: Performance (v2.4.1)

**Framing:** Pattern E

### Task 101: HIGH-003 + MED-005 — DB-side performance
- **HIGH-003** Add indexes `CREATE INDEX IF NOT EXISTS idx_pretrade_calc_id ON pre_trade_log (calc_id)` and same for orders. Verify via `EXPLAIN QUERY PLAN`.
- **MED-005** Audit `core/trade_event_log.py:99+` and `core/calc_correlation.py:75+`. Wrap sync sqlite3 calls in `asyncio.to_thread()` where called from async paths.
- **Effort:** small total (~80 LOC including verification scripts)

### Task 102: MED-006 + MED-007 — Runtime efficiency
- **MED-006** HTMX polling pauses on hidden tabs. Use `intersect` trigger or visibility API.
- **MED-007** OHLCV cache memory bound. Add per-symbol max-age eviction + disconnected-symbol cleanup.
- **Effort:** medium total (~150 LOC)

**End of v2.4.1 patch scope. After Task 102: tag v2.4.1, write release notes.**

---

## Phase 6: Architecture — `db._conn` Refactor (v2.5)

**Framing:** Pattern D
**HIGH-002:** 24 locations bypass DatabaseManager API. Split by file/area.

### Task 103: Routes layer (8 locations)
- `api/routes_orders.py` direct `db._conn` access points
- Create public helpers: `db.batch_get_pretrade_logs()`, `db.get_closed_position_by_id()`, etc.

### Task 104: Platform bridge (8 locations)
- `core/platform_bridge.py` direct access points
- Add bridge-specific helpers to DatabaseManager

### Task 105: Monitoring (3 locations)
- `core/monitoring.py` direct access points
- Add monitoring helpers

### Task 106: Reconciler + remaining (5 locations)
- `core/reconciler.py` + remaining scattered access points
- Final cleanup of any leftover `db._conn` references

After Task 106: grep for `db\._conn` should return only the DatabaseManager internal definition.

---

## Phase 7: Security Baseline (no auth) (v2.5)

**Framing:** Pattern C

### Task 107: SQL & sort validation
- **MED-003** Route-level `sort_by`/`sort_dir` validation
- **MED-022** Fix LIKE clause SQL injection in `mark_stale_orders_canceled` (parameterized)
- **LOW-001** Ticker regex validation

### Task 108: Key derivation
- **MED-004** Replace plain SHA256 in `core/crypto.py:37-38` with PBKDF2 + random salt
- Migration path for existing keys (re-derive on first use; document)

### Task 109: Frontend security headers
- **MED-040** SRI hashes on CDN scripts (htmx, idiomorph, echarts)
- **MED-041** CSP middleware

---

## Phase 8: Authentication (v2.5, LARGE — decision required first)

**Framing:** Pattern C
**HIGH-001:** No auth on any endpoint.

**Decision before starting:** does deployment context require this?
- **Single-user localhost:** defer indefinitely, document in README
- **Remote/multi-user:** proceed with all 3 tasks

### Task 110: Auth foundation
- Users table schema + migration
- Password storage (argon2 or bcrypt)
- Session middleware + token gen/validation
- Login + logout endpoints

### Task 111: Endpoint protection
- `Depends(get_current_user)` on all routes
- Per-account scoping where appropriate
- CSRF tokens for state-changing endpoints

### Task 112: UI integration
- Login page
- Session cookie handling
- "Logged in as" indicator + logout button

---

## Phase 9: State Robustness + Account Isolation (v2.5)

**Framing:** Pattern B

### Task 113: HIGH-012 — Account switch deferred close race
- `api/routes_accounts.py` + `core/order_manager.py:607`
- Bug: `loop.call_later` lambda captures `account_id` from outer scope; if switch happens during 2s delay, close row uses old account context
- Fix: pass account_id explicitly or pin via closure-time variable

### Task 114: MED-001 + MED-010 — Concurrency hygiene
- **MED-001** Position lookup fallback to entry_price=0.0; log warning + DB fallback lookup
- **MED-010** asyncio.Lock keyed by (account_id, exchange_fill_id) for fill processing OR rely on UNIQUE constraint

### Task 115: MED-016 + MED-017 — Math edge cases
- **MED-016** Negative position size clamp when slippage ≥ 100%
- **MED-017** Mark price cache age tracking; skip update if age > threshold

### Task 116: MED-018 + MED-019 — Equity + position limit
- **MED-018** Negative equity clamp / liquidation warning
- **MED-019** Enforce `max_position_count` at order submission, not just advisory

### Task 117: MED-020 + MED-021 — Shutdown + config validation
- **MED-020** Call `ws_manager.stop()`, cancel `_bg_tasks` in shutdown
- **MED-021** Validate `EXCHANGE_REFRESH_HZ`, `EXEC_LINK_PRICE_TOL` config values

---

## Phase 10: UI/UX Polish (v2.5)

**Framing:** Pattern D

### Task 118: MED-013 + MED-014 — Trade Events filter & pagination
- **MED-013** Add `hx-include="closest div"` to event_type select
- **MED-014** Replace custom pagination with `{{ pagination() }}` macro

### Task 119: MED-015 + LOW-013 + LOW-014 — Race conditions & cache
- **MED-015** Cancel pending poll on tab switch
- **LOW-013** Open positions subtab flicker (extend interval or hx-preserve)
- **LOW-014** Exec link panel cache clear after confirm

---

## Phase 11: Test Coverage Expansion (v2.5, ongoing)

**Framing:** Pattern F
**MED-009:** 41/59 modules lack dedicated tests. Priority modules first.

### Task 120: exec_link.py tests
- Target ~80% line coverage on `core/exec_link.py`
- Cover: matching algorithm cases (3/3, 2/3, 1/3, 0/3), market vs limit order, null TP/SL, tolerance boundary cases

### Task 121: order_enrichment.py tests
- Target ~80% on `core/order_enrichment.py`
- Cover: enrichment flow, partial fill re-enrichment, slippage calculation edge cases

### Task 122: crypto.py + db_orders.py tests
- `core/crypto.py` — encryption/decryption roundtrip, wrong-key handling, edge cases
- `core/db_orders.py` priority queries with full edge case coverage

---

## Phase 12: Low-Priority Cleanup (opportunistic)

**Framing:** Pattern D

### Task 123: LOW findings batch
Bundle all remaining LOW findings (12+):
- **LOW-004** Delete dead `load_recent_history`
- **LOW-005** Print → log in `ohlcv_fetcher`
- **LOW-006** Downgrade ~20 warnings to info/debug
- **LOW-011** Delete migration 008 placeholder
- **LOW-012** Add `EXEC_LINK_PRICE_TOL` to `.env.example`
- **LOW-015** Document migration recovery procedure
- **LOW-016** `per_page` upper bound
- **LOW-017** Implement `event_bus.close()` properly
- **LOW-019** Adapter exception logging
- **LOW-020** Static asset Cache-Control headers
- **LOW-021** SSE connection limit

Single sweep task; ~200 LOC across many files.

---

## Recommended Sequencing

**Week 1 (v2.4.1 patch):**
- Day 1: Tasks 85-87 (Phase 1) → 3 critical correctness fixes
- Day 2: Tasks 88-89 (Phase 2) → 3 critical reliability fixes
- Day 3: Tasks 90-92 (Phase 3 first half)
- Day 4: Tasks 93-94 (Phase 3 second half)
- Day 5: Tasks 95-97 (Phase 4 first half)
- Day 6: Tasks 98-100 (Phase 4 second half)
- Day 7: Tasks 101-102 (Phase 5) → tag v2.4.1

**Weeks 2-4 (v2.5):**
- Phase 6 (Tasks 103-106) — db._conn refactor
- Phase 7 (Tasks 107-109) — security baseline
- Auth decision; if proceed, Phase 8 (Tasks 110-112)
- Phase 9 (Tasks 113-117) — state robustness
- Phase 10 (Tasks 118-119) — UI polish
- Phase 11 (Tasks 120-122) — tests
- Phase 12 (Task 123) — cleanup → tag v2.5

**After v2.5:**
- Frontend audit phase (Cowork + Playwright)
- v2.6 planning from frontend findings + remaining backlog

---

## Task Prompt Template

```
# Task NN: <Title>

[Appropriate Pattern A-F framing pasted here]

## Setup
1. From stack tip: `git checkout <prev_branch> && git checkout -b v2.4/<this_branch>`.
2. <Scope statement>. <File count estimate>.
3. Apply CLAUDE.md discipline. Commit at end automatically.

## Reference
- Audit doc: `docs/audits/2026-05-17-v2.4-backend-audit.md`
- Findings addressed: <FINDING IDs>

## Findings

For each finding:
- Severity + ID
- File:line
- Bug description
- Required fix
- Test requirement

## Build

[Concrete patches per finding]

## Tests

[Regression tests; one or two per finding]

## Verify

Manual / automated verification.

Report:
- Findings addressed (FINDING ID → commit confirmation)
- Tests added
- Any deviation from spec'd approach
- Commit hash.

## Out of scope

Other findings (defer to next phase task). Refactoring beyond fix scope.
Stop-and-report.
```

---

## Failure Modes to Watch For

1. **Scope creep within a task** — fixing finding X "while we're here" tempts fixing Y nearby. Resist unless trivial.
2. **Over-engineering simple fixes** — div-by-zero is one early-return, not a defensive-programming rewrite.
3. **Insufficient testing** — every fix needs a regression test that fails before the fix.
4. **Breaking abstractions in cleanup** — Phase 6 is the right place to fix encapsulation. Don't do it ad-hoc earlier.
5. **Skipping audit-doc updates** — when a finding is resolved, mark it. When wrong on closer inspection, document why.

---

## Verification After Each Task

- Read Claude Code's report.
- Spot-check the diff (don't trust blind).
- Run engine briefly to confirm no live regression.
- Verify added tests pass and exercise the right thing.
- Mark addressed findings in the audit doc.
- After phase completes, run full suite once.

After Phase 5: tag v2.4.1, write release notes, ship.
