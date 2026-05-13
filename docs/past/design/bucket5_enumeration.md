# Bucket 5 Enumeration

**Date**: 2026-05-13
**Status**: Enumeration complete

---

## Auto-Resolved Items (3)

| ID | Finding | Resolved By | Evidence |
|----|---------|-------------|----------|
| **BU-1** | CCXT "Unclosed client session" warning | AD-5 + SR-8 | Zero `ccxt.async_support` or `aiohttp` imports remain. All async CCXT usage eliminated. |
| **AN-3** | Legacy Quantower corruption (3 anomalous rows) | AN-2 | Already closed — duplicate of AN-2, which deleted all qt:-prefixed rows. |
| **DataCache public API** | Expose `recalculate_portfolio()` public | SR-3 | SR-3 migrated all external callers into DataCache. External call sites are now comments. No public wrapper needed. |

---

## v2.4-Dependent Items (3) — Defer

| ID | Finding | Why v2.4 | Effort |
|----|---------|----------|--------|
| **FE-11** | Engine unresponsive on rapid timeframe switching | Synchronous backend blocking event loop. Properly fixed by v2.4 Redis event-driven state architecture. Band-aid (debounce) possible but hides the real problem. | v2.4 scope |
| **UX-1** | Ghost interface pattern (unreachable/stale/bootstrapping states) | Cross-cuts FE-2, FE-3, SC-2, OM-5. Needs consolidated design. Best addressed alongside v2.4 UI refresh. | v2.4 UX bundle |
| **MP-2** | Equity history backfill on startup (flat line during downtime) | External backtesting re-derives equity. Engine curve not used as backtest input. Low urgency; proper fix needs v2.4 historical data architecture. | v2.4 scope |

---

## Likely Auto-Resolving (1) — Monitor

| ID | Finding | Mechanism | Action |
|----|---------|-----------|--------|
| **FE-12** | Residual equity curve flicker (pre-FE-9 race-corrupted snapshots) | Clean snapshots accumulate post-FE-9. Zero anomalous snapshots since May 12. Will age out of chart window naturally. | Close after 1 week if no recurrence. Monitor until May 19. |

---

## Quick Fixes (5) — Do First

| ID | Finding | Severity | LOC | Notes |
|----|---------|----------|-----|-------|
| **FE-7** | Cap dashboard order history at 10 visible, scrollable to 25 | LOW | ~5 | Template-only: add `max-height` + `overflow-y: auto` to order history table container. |
| **FE-4** | No edit-account-name in configuration tab | LOW | ~15 | Add input field + route handler + DB UPDATE. Small feature. |
| **FE-1** | Pagination >20 rows despite 20/page setting | LOW | ~10 | Check per_page param in route handler; likely missing LIMIT in SQL or template default mismatch. |
| **FE-10** | 1W equity chart "huge drop on left" | MEDIUM-LOW | ~10 | Chart Y-axis starts at 0 or null padding. Fix: filter null/zero entries from OHLC candle array before render, or set Y-axis min near data range. |
| **FE-3** | Position card flicker on refresh (entire card re-renders) | MEDIUM | ~15 | Narrow hx-target from card container to specific data spans (price, PnL, status). Template-only. |

---

## Diagnostic-First (2) — Investigate Before Fixing

| ID | Finding | Severity | Concern |
|----|---------|----------|---------|
| **FE-2** | Calculator first-click partial state | LOW | Async-render race — data fetch not awaited before template renders. May share root with FE-8. Investigate together. |
| **FE-8** | Calculator price flickers between symbols | HIGH-MEDIUM | Stale previous-symbol data contaminating new view. Multiple possible causes (WS subscription cleanup, concurrent fetch loops, HTMX poll serving cached wrong-symbol data). Severity escalation candidate if users can act on wrong calculations. |

**FE-2 + FE-8 share likely root cause** (calculator state management).
Investigate as a pair. If confirmed shared, single fix addresses both.

---

## New Finding from Adapter Docs (1)

| ID | Finding | Severity | LOC |
|----|---------|----------|-----|
| **BY-WS-1** | Bybit WS `parse_order_update()` missing — order events silently dropped | MEDIUM | ~30 | BybitWSAdapter defines `TOPIC_ORDER` but has no parser. Engine's WS manager checks `hasattr(ws_adapter, "parse_order_update")` and skips. Bybit order events invisible. |

---

## Remaining MEDIUM/LOW from Audit Report (not in Bucket 5)

These findings are tracked in other buckets or structural redesigns.
Most are either DONE or deferred to v2.4:

**Already done** (verified in PHASE2_WORKFLOW.md): SC-2, MP-1, MN-1, 
OM-5, AD-2/3/4/5, SR-7, SR-4, SR-6, SR-8, RL-3, RE-1, SC-1, RP-1

**Bucket 3 structural** (done): SR-1/2/3

**Bucket 4 remaining**: PA-1(b) operational verification only

**Not yet addressed** (MEDIUM, potentially Bucket 5):
- **RE-3/4/5** (analytics: equity-weighted Sharpe, daily-return
  calculation gaps) — pure analytics quality, not blocking
- **WS-3** (source string cosmetic) — LOW, cosmetic
- **ST-2** (setter raise on invalid state) — LOW, defensive
- **EX-1** (legacy singleton cleanup) — already done by SR-4
- **PB-2/3/4** (platform_bridge boundary violations) — deferred to SR-5

---

## Recommended Order

### Phase 1: Quick fixes (1-2 sessions)
1. FE-7 (order history cap, ~5 LOC)
2. FE-1 (pagination fix, ~10 LOC)
3. FE-10 (chart Y-axis, ~10 LOC)
4. FE-3 (card flicker hx-target, ~15 LOC)
5. FE-4 (edit account name, ~15 LOC)

### Phase 2: Diagnostic investigations
6. FE-2 + FE-8 (calculator state management, investigate as pair)

### Phase 3: Adapter gap
7. BY-WS-1 (Bybit WS order parser, ~30 LOC)

### Defer to v2.4
- FE-11, UX-1, MP-2

### Close
- BU-1 (auto-resolved), AN-3 (closed), DataCache API (SR-3 resolved)
- FE-12 (monitor until May 19, close if no recurrence)

---

## Aggregate Estimate

| Category | Items | LOC |
|----------|-------|-----|
| Quick fixes | 6 | ~35-45 |
| Diagnostics | 3 (FE-13, FE-2+FE-8) | ~30-50 |
| Adapter gap | 1 | ~30 |
| **Active total** | **10** | **~95-125** |
| Deferred (v2.4) | 3 | — |
| Auto-resolved/close | 4 | 0 |

---

## Quick Fixes Sub-Enumeration (added 2026-05-13)

All 6 confirmed active. Mostly independent files — single branch with
atomic commits. Ordered by simplicity:

| Order | ID | File(s) | Change | LOC |
|-------|-----|---------|--------|-----|
| 1 | FE-1 | routes_orders.py | Standardize per_page 25→20 (lines 42, 65) | 2 |
| 2 | FE-7 | dashboard_body.html | Add max-height + overflow-y to order history (line 179) | 3-5 |
| 3 | FE-14 | open_orders_table.html | Add TP/SL columns (after Trigger, before TIF) | 5-8 |
| 4 | FE-10 | db_analytics.py | Fix equity OHLC gap handling (init prev_close) | 4-6 |
| 5 | FE-4 | accounts.html | Inline-editable account name (same pattern as broker_account_id) | 8-10 |
| 6 | FE-3 | dashboard.html + possibly new endpoint | HTMX target refinement for position card refresh | 8-12 |

**Branch**: `fix/bucket5-quick-fixes`
**FE-14 note**: Needs verification that order rows from DB include TP/SL
fields. If not, either join from algo orders or add columns to orders table.
**FE-3 note**: Most complex — may need new fragment endpoint for positions-only
refresh. Leave last; may be deferred if scope expands beyond quick fix.

**FE-13 (NEW)**: Stop entry vs stop_loss disambiguation. Diagnostic-first —
separate branch after quick fixes batch.
**FE-14 (NEW)**: TP/SL column display. Quick fix tier if data available.
