# Changelog

## [v2.4.1] — 2026-05-18

### Summary

v2.4.1 closes Phases 1–4 of the v2.4 audit response. Across 92 original audit
findings + 9 emergent discoveries (101 total), 24 HIGH/CRIT-tier issues were
resolved, 8 race-framed findings were verified false (structurally impossible
under Python's asyncio + GIL semantics), and 2 cross-section duplicates were
consolidated. Six HIGH-tier findings remain deferred and are documented as
known-deferred at tag time (HIGH-001 auth to Phase 8; HIGH-002 db._conn to
Phase 6; HIGH-028 / 029 / 030 / 031 as exchange-adapter parallels to be
addressed in Phase 5+).

Audit ledger state at tag: **0 CRIT / 6 HIGH / 39 MED / 21 LOW = 66 active**.

### Resolved (CRIT)
- **CRIT-001** (Task 88): N+1 query in fills enrichment — batch-fetch pre_trade_log + orders. ~31× speedup on 50-fill positions.
- **CRIT-002** (Task 85): Slippage divide-by-zero guard in risk_engine.
- **CRIT-004** (Task 87): TP/SL exec-link semantics correction (1/1 — was misleading 3/3).
- **CRIT-006** (Task 89): Active-account scoping in data_logger; cross-account snapshot leakage closed.
- **CRIT-008** (Task 88.1): Missing pre_trade_log.calc_id column on legacy DBs — migration added.

### Resolved (HIGH)
Phase 1–3:
- **HIGH-003** (Task 88.1): Two missing pre_trade_log indexes for the calc-to-fill query path.
- **HIGH-009** (Task 92): Close-fee overfill cap in `_build_close_row_for_fill`.
- **HIGH-020** (Task 93): fetch_account null-check.
- **HIGH-021** (Task 94): Contract-spec TTL reduction (24 h → 4 h) + admin force-refresh endpoint.

Phase 4:
- **HIGH-007 + HIGH-014 + HIGH-015 + LOW-019** (Task 99): Adapter observability + Binance weight-tracker header reconciliation + fee-fetch log + price-extremes log.
- **HIGH-008** (Task 103): Scheduler AuthenticationError handling + `app_state.auth_failed_accounts` state.
- **HIGH-010** (Task 105): `core/crypto.decrypt` silent fallback → `CredentialDecryptionError` + 3 caller updates.
- **HIGH-011 + MED-003 + MED-022** (Task 101): SQL injection defense — filter-column whitelist, route-level sort validator, LIKE-prefix parameterization.
- **HIGH-013 + MED-018** (Task 102): Trust-but-verify exchange responses — critical-field validation + negative-equity clamp.
- **HIGH-017 + HIGH-018** (Task 98): DD-gate fail-closed on settings-read failure + pubsub except narrowing (subscriber retention).
- **HIGH-022 + HIGH-023 + MED-036** (Task 97): Route input validation — backtest date-range bounds + cross-parameter `warning < limit` checks + max-position-count runtime guard.
- **HIGH-024** (Task 100): Credential leak prevention — `SensitiveStr` wrapper, narrow scope on routes_connections.
- **HIGH-026** (Task 95): Silent-swallow remediation in `_build_close_row_for_fill` — structured engine_event emission.
- **HIGH-027** (Tasks 104a + 104b): Calc-to-fill matching window — schema (per-account default, per-calc override) + `compute_exec_match` window logic + UI countdown (4-state: LINKABLE / EXPIRING_SOON / EXPIRED / LINKED_CONFIRMED).

### Verified false (audit framing imprecise; pin tests added)
- **CRIT-003**: max() on empty close_fills — already guarded.
- **CRIT-005**: WS-reconnect race — single-coroutine reconnect path is structurally serialized.
- **HIGH-004 / HIGH-005 / HIGH-006**: Already guarded.
- **HIGH-012**: Account-switch deferred-close closure race — lambda captures function parameter, not attribute.
- **HIGH-019**: Engine actively places TP/SL — engine is passive observer (Quantower plugin places).
- **HIGH-025**: Partial-fill TP/SL re-enrichment — already correct.

### Filed during fix phase (resolved or deferred)
- **CRIT-008** (filed + resolved Task 88.1).
- **LOW-022 + MED-043** (filed + resolved Task 85b).
- **HIGH-026** (filed Task 90.5d? — resolved Task 95).
- **MED-044** (filed Task 89; OPEN, target Phase 4).
- **HIGH-027** (filed Task 93; resolved Tasks 104a + 104b).
- **HIGH-028** (filed Task 99.1; deferred — Bybit reconciliation parallel to HIGH-014).
- **HIGH-029** (filed Task 100; deferred — exchange-credential traceback leak parallel to HIGH-024).
- **LOW-023** (filed Task 101.1; OPEN — full-suite TestClient hang root cause).
- **HIGH-030 + HIGH-031** (filed Task 102.1; deferred — Bybit + MEXC account-field parallels to HIGH-013).
- **MED-045** (filed + resolved Task 103.5).
- **MED-046** (filed Task 104b; OPEN — `_CREATE_STATEMENTS.split(";")` footgun in database.py).

### Infrastructure
- **pytest-timeout** (Task 101.1): 30 s default per test (`pyproject.toml` `[tool.pytest.ini_options]`). Caught the LOW-023 hang on first full-suite run. CLAUDE.md documents the test-discipline playbook.
- **concurrent-log-handler** (Task 103.5): replaces stdlib `RotatingFileHandler` to fix the Windows multi-process log-rotation `PermissionError [WinError 32]` observed at runtime after Task 103.

### Calibration patterns documented (audit doc)
- **Race-framing false-positive rate: 8 of 15 (53 %)** — race-framed findings should default to verify-before-assume. CRIT-003, CRIT-005, HIGH-004, HIGH-005, HIGH-006, HIGH-012, HIGH-019, HIGH-025 are all real-bug-but-not-race or already-guarded.
- **Audit-impact-imprecision pattern: 4 examples** — HIGH-019 (wrong architecture), HIGH-026 (already-logged), HIGH-013 (wrong direction — collapses to micro, not excessive), HIGH-008 (wrong mechanism — retry-hammers, doesn't crash). Implication: trace downstream consumers independently of audit's described mechanism.

### Deferred at v2.4.1 tagging (documented as known-deferred)
- **HIGH-001** — Authentication on all endpoints. Phase 8 (deployment context decision needed).
- **HIGH-002** — `db._conn` private-attribute access across 24 sites. Phase 6 (architectural refactor).
- **HIGH-028** — Bybit weight-tracker reconciliation. Sister to HIGH-014's Binance fix (Task 99); deferred during the same task.
- **HIGH-029** — Credential traceback leak in `api/routes_accounts.py` (5 sites) + `core/account_registry.py` decrypt sites. Parallel to HIGH-024's narrow scope (Task 100).
- **HIGH-030** — Bybit account-field validation. Sister to HIGH-013's Binance fix (Task 102).
- **HIGH-031** — MEXC account-field validation. Reduced impact (read-only adapter) but completes the trust-but-verify family.
- **MED-046** — SQL-split footgun in `core/database.py`. Discovered Task 104a, filed Task 104b. Follow-up cleanup.

### Phase 4 task ledger

| Task | Findings | Branch tip |
|------|----------|------------|
| 95 | HIGH-026 | e352593 |
| 96 | HIGH-012 (verified false) | 625a909 |
| 97 + 97.1 | HIGH-022 + HIGH-023 + MED-036 + wiring pins | a26d2dd / 6edd30b |
| 98 | HIGH-017 + HIGH-018 | f2d2533 |
| 99 + 99.1 | HIGH-007 + HIGH-014 + HIGH-015 + LOW-019 + HIGH-028 filing | 435add1 / 3f7baf8 |
| 100 | HIGH-024 + HIGH-029 filing | 853b91f |
| 101 + 101.1 | HIGH-011 + MED-003 + MED-022 + pytest-timeout + LOW-023 filing | dda5519 / 848b467 |
| 102 + 102.1 | HIGH-013 + MED-018 + HIGH-030 + HIGH-031 filings | 5ea794b / 560e63d |
| 103 + 103.5 | HIGH-008 + MED-045 (filed + resolved) | 1cb8787 / 0f7548e |
| 104a + 104b | HIGH-027 backend + frontend + MED-046 filing | 78f76a8 / 0d1fa93 |
| 105 | HIGH-010 | 938e50f |

Full pytest at tag: **1456 passed, 3 skipped** (LOW-023 skipped pending fixture refactor).

---

(Prior history of v2.4 development lives in `v2.4.md`, `v2_4_audit_fix_plan.md`,
and the per-task commit messages.)
