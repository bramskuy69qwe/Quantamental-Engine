# Audit Closeout — v2.3.1

**Period**: 2026-05-07 to 2026-05-13
**Auditor**: Claude Opus 4.6
**Scope**: Full deep audit of ~13,900 LOC, 78 Python files, 48 HTML templates
**Result**: 159 cumulative commits across 41 branches, test suite 60 → 574

---

## Summary

The Quantamental Risk Engine v2.3.1 audit identified 5 CRITICAL, 17 HIGH,
25 MEDIUM, and 20 LOW findings across the codebase. All CRITICALs and HIGHs
are resolved or deferred with explicit rationale. The codebase progressed
from no test coverage on core paths to 574 regression tests with a
deterministic 111-row computational baseline.

Key outcomes:
- **Adapter abstraction exhaustive**: All external I/O routes through
  vendor-neutral adapter layer (SR-7, SR-4, SR-6, SR-8, AD-5)
- **Rate-limit resilience**: 11 catch sites, burst serialization, proactive
  monitoring (RL-1, RL-3, MN-1a, RL-4)
- **Conditional order support**: Binance algo order integration — REST
  polling + WS real-time (OM-5, OM-5b)
- **Data quality**: Corrupted legacy rows deleted, is_close deterministic,
  MFE/MAE backfill sentinel fixed (AN-2, AD-4, AN-1)

---

## Findings Inventory

### Bucket 0: Safety Net

| ID | Status | Severity | Description |
|----|--------|----------|-------------|
| RE-9 | COMPLETE | HIGH | Unit tests for sizing, ATR, slippage, VWAP, analytics math. 60 tests + 111-row baseline CSV. |

### Bucket 1: Cheap CRITICALs

| ID | Status | Severity | Description |
|----|--------|----------|-------------|
| SC-1 | COMPLETE | CRITICAL | BOD day-overflow fix (1 line) |
| RP-1 | COMPLETE | CRITICAL | Auth + 127.0.0.1 default for /api/platform/* |
| RE-1 | COMPLETE | CRITICAL | Wire up existing staleness checks in calculator |

### Bucket 2: Foundation Structural Redesigns

| ID | Status | Severity | Description |
|----|--------|----------|-------------|
| SR-1 | COMPLETE | CRITICAL | OrderManager single-writer enforcement. 73 tests. |
| SR-2 | COMPLETE | CRITICAL | AccountRegistry single owner. 18 tests. |
| SR-3 | COMPLETE | HIGH | Crash recovery consolidation. 13 tests. |

### Bucket 2.5: Rate-Limit Hardening

| ID | Status | Severity | Description |
|----|--------|----------|-------------|
| RL-1 | COMPLETE | HIGH | Rate-limit handling (23 tests). Operational verification FAILED → led to RL-3. |
| RL-3 | COMPLETE | HIGH | Exception coverage (11 catch sites). 11 tests. Operational verification PASSED. |
| AN-1 | COMPLETE | HIGH | backfill_completed sentinel (replaces mfe=0 heuristic). 7 tests. |

### Bucket 3: Structural Sequence

| ID | Status | Severity | Description |
|----|--------|----------|-------------|
| SR-7 | COMPLETE | HIGH | Protocol vendor-neutrality (4 steps). Neutral error types, optional fields. |
| SR-4 | COMPLETE | HIGH | exchange.py collapse + adapter wiring. Zero raw CCXT in exchange.py. |
| SR-6 | COMPLETE | HIGH | WS adapter routing. Deleted raw-Binance handlers. |
| SR-8 | COMPLETE | HIGH | Regime fetcher adapter migration. Deleted ccxt singleton. |
| MN-1 | COMPLETE | HIGH | Monitoring expansion (3 → 9 checks). MonitoringEvent model. |
| SC-2 | COMPLETE | HIGH | Ready-state gating. ReadyStateEvaluator + calculator integration. |
| MP-1 | COMPLETE | HIGH | Crash recovery risk states (dd_state + weekly_pnl_state). |

### Bucket 4: HIGH Cleanup

| ID | Status | Severity | Description |
|----|--------|----------|-------------|
| AD-5 | COMPLETE | HIGH | ohlcv_fetcher migrated to adapter. Last direct ccxt consumer eliminated. |
| MN-1a | COMPLETE | MEDIUM | Rate-limit event wiring to monitoring (3 lines). |
| FE-9 | COMPLETE | HIGH | Equity flash crash race condition fixed (91.5% pnl_anomaly reduction). |
| PA-1a | COMPLETE | HIGH | WS fill creation + backfill dedup. |
| PA-1b | COMPLETE | HIGH | FIFO open_time reconstruction. |
| PA-1 | PARTIAL | HIGH | Position-split manifestation (b) residual — deferred, needs live observation. |
| AN-2 | COMPLETE | HIGH | Quantower legacy data cleanup (148 rows deleted, archived). |
| OM-5 | COMPLETE | HIGH | Conditional/algo order support (REST + WS + snapshot isolation). |
| OM-5b | COMPLETE | HIGH | Basic order REST sync no longer plugin-gated. |
| MN-2 | COMPLETE | MEDIUM | Drawdown label clarity ("Today's DD"). Design gap, not bug. |
| AD-2 | COMPLETE | MEDIUM | Bybit income_type routing via V5 endpoints. |
| AD-3 | COMPLETE | MEDIUM | Bybit live fee fetch via /v5/account/fee-rate. |
| AD-4 | COMPLETE | MEDIUM | Deterministic is_close (side+positionSide, both adapters). |
| RL-4 | COMPLETE | MEDIUM | Trade-event burst serialization (Semaphore(2) + rate-limit guards). |

### Bucket 5: MEDIUM/LOW Cleanup

| ID | Status | Severity | Description |
|----|--------|----------|-------------|
| FE-1 | COMPLETE | LOW | per_page standardization (25→20). |
| FE-7 | COMPLETE | LOW | Order history scrollable container + sticky header. |
| FE-10 | COMPLETE | MEDIUM-LOW | Equity chart left-side drop (init prev_close). |
| FE-4 | COMPLETE | LOW | Inline-editable account name. |
| FE-15 | COMPLETE | LOW | Top bar selector CSS truncation. |
| FE-16 | COMPLETE | LOW | Tab indicator flicker (neutral defaults on HTMX-refreshed tab bars). |
| FE-13 | COMPLETE | MEDIUM | Stop entry vs stop_loss disambiguation (reduceOnly check, 7 parse sites). |
| FE-2 | COMPLETE | LOW | Calculator first-click partial state (removed setTimeout race). |
| FE-8 | COMPLETE | LOW | Calculator price flicker (cache eviction on symbol switch). |
| FE-17 | COMPLETE | LOW | Calculator recent-click (3-phase: _livePrice fallback + rAF + hidden field pre-population). |
| BY-WS-1 | COMPLETE | MEDIUM | Bybit WS order parser + post-connect auth/subscribe. |

### Auto-Resolved

| ID | Status | Resolved By | Description |
|----|--------|-------------|-------------|
| BU-1 | AUTO_RESOLVED | AD-5 + SR-8 | CCXT unclosed client session (all async eliminated). |
| AN-3 | AUTO_RESOLVED | AN-2 | Duplicate of AN-2 (legacy Quantower corruption). |
| DataCache API | AUTO_RESOLVED | SR-3 | External callers migrated into DataCache internals. |

### Deferred to v2.4

| ID | Status | Severity | Description | Rationale |
|----|--------|----------|-------------|-----------|
| MN-2-B | DEFERRED_v2.4 | MEDIUM | Monthly drawdown metric (month_peak_equity). ~30-50 LOC. | Prerequisite for v2.4 gate promotion. |
| MN-2-C | DEFERRED_v2.4 | HIGH | Rolling-window drawdown for enforcement. | Addresses "5%/day × 10 days never triggers" gap. |
| AD-4-B | DEFERRED_v2.4 | LOW | One-way mode break-even close fix. | Needs position-direction context at trade time. |
| RL-4-B | DEFERRED_v2.4 | MEDIUM | Fan-out architectural review (shared data fetch on trade close). | 6 subsystems → 1 coordinated sweep. |
| RL-2 | DEFERRED_v2.4 | MEDIUM | Proactive weight tracker. | Prevents 429 at source rather than catching after. |
| FE-14 | DEFERRED_v2.4 | LOW | TP/SL columns on order rows. | Needs DB schema addition (tpTriggerPrice). |
| FE-3 | DEFERRED_v2.4 | MEDIUM | Position card flicker (HTMX morphing or new endpoint). | Exceeds template-only scope. |
| FE-11 | DEFERRED_v2.4 | MEDIUM | Engine unresponsive on rapid timeframe switching. | Blocked by v2.4 Redis event-driven architecture. |
| UX-1 | DEFERRED_v2.4 | MEDIUM | Ghost interface pattern (3 states). | Cross-cuts multiple components; needs consolidated design. |
| UX-2 | DEFERRED_v2.4 | MEDIUM | Unified data table pattern. | Depends on v2.4 UI architecture decision. |
| MP-2 | DEFERRED_v2.4 | MEDIUM | Equity history backfill on startup gaps. | External backtesting re-derives; proper fix needs v2.4. |
| FE-17-WATCH | DEFERRED_v2.4 | LOW | rAF → htmx:afterProcess upgrade if symptom re-surfaces. | ~5-8 LOC upgrade path. |

### Deferred to v2.4.5

| ID | Status | Severity | Description |
|----|--------|----------|-------------|
| MEXC-1 | DEFERRED_v2.4.5 | MEDIUM | Read-only MEXC adapter. Investigation prerequisites documented. |

### Monitoring

| ID | Status | Description | Close Date |
|----|--------|-------------|------------|
| FE-12 | MONITOR | Residual equity curve flicker (pre-FE-9 snapshots aging out). Zero anomalies since May 12. | Close after May 19 if no recurrence. |

---

## v2.4 Dependency List (Prioritized)

### Prerequisites for v2.4 Gate Promotion
1. **MN-2-B** (MEDIUM): Monthly drawdown metric — without this, dd_state only
   tracks intraday drawdown, insufficient for enforcement gate.
2. **MN-2-C** (HIGH): Rolling-window drawdown — the "5%/day for 10 days"
   gap means intraday threshold alone can't gate cumulative loss.

### Architecture-Dependent Items
3. **FE-11** (MEDIUM): Blocked by Redis event-driven architecture. Synchronous
   backend blocking event loop during query/recompute.
4. **UX-2** (MEDIUM): Depends on UI framework decision (HTMX continuation vs
   component framework).
5. **FE-3** (MEDIUM): Needs HTMX morphing extension or new fragment endpoints.

### Independent v2.4 Items
6. **RL-4-B** (MEDIUM): Fan-out review — can land early in v2.4 cycle.
7. **RL-2** (MEDIUM): Proactive weight tracker — reduces 429 events to near-zero.
8. **AD-4-B** (LOW): One-way mode is_close fix — requires position-direction context.
9. **UX-1** (MEDIUM): Ghost interface — consolidated design after FE-3 and SC-2.
10. **FE-14** (LOW): TP/SL columns — DB schema addition.
11. **MP-2** (MEDIUM): Equity backfill — historical data architecture.

---

## v2.4.5 Scope: MEXC Integration

Read-only adapter creation. Investigation prerequisites:
- Operational check: MEXC USDⓈ-M Futures API access (geo-restrictions, IP whitelisting)
- WS auth model: listen key vs post-connect HMAC vs API key in URL
- CCXT coverage: `ccxt.mexc` method inventory for futures endpoints
- Conditional order mechanism: separate API surface or standard order params

Estimated effort: 2-3 sessions (investigation + adapter + tests).
Can run parallel to v2.4 prep — no engine-core changes needed
(adapter abstraction already exhaustive).

---

## Verification Status

### Operationally Verified
| Finding | Verification | Date |
|---------|-------------|------|
| RL-3 | 21h clean run, zero 429/418 | 2026-05-10 |
| AN-1 | 21h clean run, zero unnecessary backfill REST | 2026-05-10 |
| SR-7 | 429 cluster caught by neutral RateLimitError, proper 120s pauses | 2026-05-12 |
| SR-4 + SR-6 | 1-2h smoke clean, zero deleted-function references | 2026-05-12 |
| SR-8 | 1-2h smoke clean | 2026-05-12 |
| FE-9 | 91.5% pnl_anomaly rate reduction | 2026-05-12 |
| OM-5 | SAGAUSDT conditional appeared in engine | 2026-05-13 |
| FE-16 | Tab flicker eliminated (dashboard + history) | 2026-05-13 |
| FE-17 | Recent-click single-step calculation | 2026-05-13 |

### Accumulating (Awaiting Natural Events)
| Finding | Signal Needed | Notes |
|---------|--------------|-------|
| PA-1(b) | Natural partial close | Verify FIFO open_time on real partial-close event |
| RL-4 | Trade closures | 24h log analysis: 429 burst pattern should drop to ~zero |
| OM-5 WS | ALGO_UPDATE event | Real-time conditional order lifecycle |
| BY-WS-1 | Bybit trading activity | Bybit WS order event parsing |

### Pending Bundled Window
Combined Bucket 3+4 cumulative verification — 7-14 day window from
engine restart on latest branch.

---

## Architectural Patterns Established

### Core + Adapter Ring
Every external connection (Binance, Bybit, future MEXC) is an adapter
implementing a vendor-neutral protocol. Engine core never imports exchange
libraries directly. Established by SR-7 → SR-4 → SR-6 → SR-8 → AD-5.

### Adapter Documentation Discipline
`docs/adapters/binance.md` (282 lines) and `docs/adapters/bybit.md` (245 lines)
as maintenance interfaces. Each endpoint entry tagged VERIFIED / LISTED /
ASSUMED. Lesson from AD-2/3: 2 of 3 API surface assumptions were wrong —
don't trust inferred knowledge, verify against canonical docs.

### Per-Commit Stop-and-Report
Multi-layer judgment at every commit boundary. Enables scope correction
(FE-14, FE-3 deferred mid-batch), discovery capture (AD-3 fee endpoint),
and verification-period additions (FE-13, FE-16, FE-17).

### Auto-Resolution Check
Standard Phase 1 question: "Did any prior fix coincidentally resolve this?"
Caught BU-1 (AD-5+SR-8 eliminated async CCXT), DataCache API (SR-3),
AN-3 (AN-2). Prevents wasted implementation effort.

### Smoke-Diff Against Baseline
Pure-math baseline (111 rows) detects regression in sizing/ATR/slippage/
analytics functions. Limitation: empty diff doesn't mean no behavior change —
only that baseline-exercised paths are unaffected. DB and display changes
are not covered.

### Hypothesis-Driven Instrumentation
FE-17 demonstrated the progression: broad observation → specific hypothesis
→ falsifying instrumentation → root cause. Three phases narrowed the search
space layer by layer (client timing → HTMX processing → server validation).
Each round eliminated a layer rather than just finding another bug at the
same layer.

### Implicit Multi-Purpose Code
FE-2's 100ms setTimeout served two purposes: preventing partial-state
contamination AND serving as HTMX settling window. Only one was visible
at fix time. Future fixes that remove timing-related code should check
whether the timing is doing implicit work beyond the visible purpose.

### Structural ≠ Operational
FE-16's structural analysis correctly identified which tab bars are inside
HTMX swap targets. But "not affected" required operational verification —
static analysis is necessary but not sufficient.

### "WS Not Handled" Can Mask "WS Not Subscribed"
BY-WS-1: the adapter doc identified missing `parse_order_update()` method.
The fix also required adding post-connect topic subscription — the engine
wasn't receiving events in the first place. Future WS work should verify
topics are subscribed before adding handlers.

### Diminishing Returns Threshold
Three diagnostic rounds is the threshold for stuck iteration. FE-17
progressed (each round narrowed the search space) so continued past three.
If rounds stop narrowing, defer with context preserved rather than iterate.

---

## Artifact Inventory

### Design Documents (34)
`docs/design/`: SR-7 (3), SR-4 (3), SR-6 (2), SR-8 (2), SC-2 (2),
MN-1 (2), MP-1 (1), AD-5 (2), PA-1 (3), FE-9 (1), RL-4 (2), MN-2 (1),
AD-2-3-4 (1), OM-5 (2), FE-13 (1), FE-2-8 (1), FE-16 (1), FE-17 (2),
bucket5 (1), connection_status_ui (1).

### Adapter Documentation (2)
`docs/adapters/`: binance.md (282 lines), bybit.md (245 lines + BY-WS-1 update).

### Workflow Log
`docs/audit/PHASE2_WORKFLOW.md`: Complete history of all fixes, operational
verification results, and v2.4 deferral decisions.

### Test Baselines
`tests/baselines/pre_audit_baseline.csv`: 111-row deterministic baseline.

### Archives
`docs/archive/quantower_legacy_*_2026-05-12.csv`: 148 rows archived before
AN-2 deletion.

---

## Next Steps

1. **Operational verification window** (7-14 days): Engine runs on latest
   branch. Natural trade events accumulate verification signals for PA-1(b),
   RL-4, OM-5 WS, BY-WS-1.

2. **FE-12 monitor close** (May 19): If zero anomalous equity snapshots
   since May 12, close FE-12 as self-resolved.

3. **Combined verification report**: After 7-14 day window, structured report
   covering all accumulating items.

4. **MEXC investigation session**: Post-audit, pre-v2.4. Read-only adapter
   investigation. Can start independently.

5. **v2.4 prep entry**: Deferred items as dependency list. MN-2-B/C as
   first priority (gate promotion prerequisites).
