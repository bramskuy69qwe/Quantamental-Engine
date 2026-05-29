# Handoff — next Claude Code session

**Date**: 2026-05-28
**Current branch**: `v2.5/post-rewind-drop-regime-infra` @ `81ff8ef`
**Tests**: 2645 passed, 7 skipped, 1 unrelated pre-existing failure
**Pre-existing failure**: `tests/test_data_cache_dd.py::TestRollingWindowPeak::test_old_high_excluded_from_window` — 30-day rolling-window boundary bug; unrelated to calc-linkage. Worth filing as its own task.

## Session rules (apply to every session unless explicitly overridden)

These rules are load-bearing. Read them before scoping work; re-read them
when in doubt.

### Rule 1 — Think Before Coding
State assumptions explicitly. Ask rather than guess.
Push back when a simpler approach exists. Stop when confused.

### Rule 2 — Simplicity First
Minimum code that solves the problem. Nothing speculative.
No abstractions for single-use code.

### Rule 3 — Surgical Changes
Touch only what you must. Don't improve adjacent code.
Match existing style. Don't refactor what isn't broken.

### Rule 4 — Goal-Driven Execution
Define success criteria. Loop until verified.
Strong success criteria let Claude loop independently.

### Rule 5 — Token budgets are not advisory
Per-task: 50,000 tokens. Per-session: 300,000 tokens.
If approaching budget, summarize and start fresh.
Surface the breach. Do not silently overrun.

### Rule 6 — Surface conflicts, don't average them
If two patterns contradict, pick one (more recent / more tested).
Explain why. Flag the other for cleanup.
Don't blend conflicting patterns.

### Rule 7 — Read before you write
Before adding code, read exports, immediate callers, shared utilities.
If unsure why existing code is structured a certain way, ask.

### Rule 8 — Tests verify intent, not just behavior
Tests must encode WHY behavior matters, not just WHAT it does.
A test that can't fail when business logic changes is wrong.

### Rule 9 — Match the codebase's conventions, even if you disagree
Conformance > taste inside the codebase.
If you think a convention is harmful, surface it. Don't fork it silently.

### Rule 10 — Fail loud
"Completed" is wrong if anything was skipped silently.
"Tests pass" is wrong if any were skipped.
Default to surfacing uncertainty, not hiding it.

## What this session did — Phase 1 COMPLETE (T210-T225)

All 7 Phase-1 tasks (plan §1) shipped + independently audited, plus a
Phase-1.8 expiry addendum the audit surfaced. The calc-linkage **state
machine is fully wired**: every live `calc.status` transition routes
through `core/calc_state.transition()` (the P0.T6 choke-point) with
TOCTOU guards, and each is verified end-to-end.

### Task → commit map

| Plan ref | Task | Commit(s) |
|---|---|---|
| P1.T1 | Strict 5/5 LIMIT / 6/6 MARKET matcher + per-criterion audit | 210 (b667616); audits 211 (fbd3569), 212 (f174511) |
| P1.T2 | Per-account config (`core/account_config.py`) + freeze `window_seconds` at calc creation | 213 (f7ce004); audit 215 (10e558d) |
| P1.T3 | Calc revision / supersede (active\|released → superseded) | 214 (6e7e76c); audits 215, 217 (6d421e5) |
| P1.T4 | Calc cancel endpoint (`POST /calculator/cancel/{calc_id}`) | 219 (40144f0); audit 220 (884810c) |
| P1.T5 | Calc release on operator order cancel (matched → released) | 216 (62236d1) |
| P1.T6 | Calc auto-complete on position close (→ completed_via_position) | 221 (63830a2) |
| P1.T7 | Nullable TP/SL → manual-link | 223 (0109793) |
| P1.8 | Live calc-expiry sweeper (→ expired) | 224 (b65ecdd) |
| — | Acceptance-criteria reframe + lifecycle e2e | 225 (81ff8ef) |
| — | Docs: DB-routing split-brain; partially_actioned no-producer | 218 (ffa4e9c), 222 (083a833) |

### The calc state machine — fully wired (`core/calc_state.py`)

```
active ──matcher full-match──> matched ──position closes──> completed_via_position (terminal)
   │                              │
   │                              └──operator cancels working order──> released ──re-match──> matched
   ├──operator recalc (same key)──> superseded (terminal)                  │
   ├──operator clicks Cancel calc──> cancelled_by_operator (terminal)      └──window lapses / cancel / supersede
   └──window lapses (sweeper)──> expired (terminal)
```

Every edge has a live producer (was NOT true mid-phase — see Lessons):
- **matched**: `core/order_enrichment.py::_try_correlate` (the matcher path)
- **superseded**: `core/handlers.py::_supersede_prior_active_calcs` (on recalc)
- **released**: `core/order_manager.py::_release_calc_on_operator_cancel` (WS cancel of unfilled working order)
- **cancelled_by_operator**: `core/handlers.py::cancel_calc_by_operator` (endpoint)
- **completed_via_position**: `core/order_manager.py::_complete_calcs_on_close` (from `_build_close_row_for_fill`)
- **expired**: `core/handlers.py::sweep_expired_calcs` (periodic `_calc_expiry_loop`, 60s)

All 5 mutating sites share ONE pattern: read status → `calc_state.transition(current, target, apply_fn=...)` where apply_fn does `UPDATE ... WHERE status=<read>` and raises `core.calc_state.CalcTransitionRaceLost` on rowcount 0 (TOCTOU guard) so the event is skipped if a concurrent transition won.

### Test coverage added this phase

~135 new tests across: `test_phase1_matcher.py` (+t211/t212), `test_phase1_account_config.py`, `test_phase1_calc_revision.py`, `test_phase1_calc_cancel.py`, `test_phase1_calc_release.py`, `test_phase1_calc_complete.py`, `test_phase1_nullable_tpsl.py`, `test_phase1_calc_expiry.py`, `test_phase1_lifecycle_e2e.py` (drives all 6 live transitions through the REAL handlers + the matched→released→matched re-match loop, asserting `pre_trade_log.status`).

## Lessons from Phase 1 (read before Phase 2)

**Process:**

1. **Audit every task with an independent agent — green tests are NOT
   enough.** The biggest catches were deploy-blockers the tests
   *couldn't* catch because the tests encoded the same wrong assumption:
   - **H1 (side-casing)**: matcher SQL did `WHERE side = ?`; the
     calculator writes `long`/`short`, WS adapters write `BUY`/`SELL`.
     The matcher would have matched **nothing** in production. Tests
     passed because they used `long` on both sides. Fixed via
     `core.calc_correlation.norm_side`.
   - **H2 (status DEFAULT NULL)**: `insert_pre_trade_log` never wrote
     `status`; new calcs landed NULL → excluded by the matcher's
     `status IN ('active','released')` filter → backfilled to `expired`
     at next restart. Every new calc was dead-on-arrival.
   - **no-live-expiry** (whole-phase audit): `calc:expired` had no live
     producer; calcs lingered as candidates forever. Built the sweeper
     (T224).
   The pattern that works: after each task, `Agent(general-purpose)`
   with a skeptical, concern-listed prompt + verify its load-bearing
   claims yourself before acting. It paid off every single task.

2. **Verify the audit's MECHANISM before applying its fix** (CLAUDE.md
   re-investigation discipline). Two spec items turned out
   architecturally impossible / infeasible and were correctly
   *reframed* rather than built: the §4.4 pre-submission replacement
   modal (impossible — see Lesson 4) and the §1 "golden-dataset
   match-rate" acceptance criterion (no same-dataset "before"; old
   matcher fully replaced).

3. **Don't run `git push` as a "quick check".** Pushed b667616 framed
   as a check before the audit had run. Surfaced it (Rule 10) and
   fixed forward. `git push` is never a check.

**Architecture / domain (load-bearing for Phase 2):**

4. **The engine is OBSERVE-ONLY.** There is no `place_order` /
   `cancel_order` in `core/` — all order/fill/cancel/position data
   arrives via WS observation of Quantower→venue. Consequences that
   recur: cancel classification defaults to `OPERATOR` (can't know
   "did we cancel"); the matcher is the *only* auto-link path (spec
   §4.5/§15-R2); any "pre-submission" UI is impossible — only
   post-arrival.

5. **Single-DB transactional path.** ALL calc-linkage tables
   (`pre_trade_log`, `orders`, `fills`, `closed_positions`,
   `positions_calcs`, `calc_match_audit`, …) live in
   `config.DB_PATH` = `data/risk_engine.db`. Every matcher/handler
   callsite uses it (the `db` singleton or `config.DB_PATH`). The
   per-account DBs are vestigial for `pre_trade_log` (orphaned,
   pre-Phase-0 schema). **BUT `trade_events` lives in the per-account
   DB** — cross-DB from `pre_trade_log`, linked by `calc_id` string
   only, **no SQL JOIN across files**. Phase 2 junction/reverse-query
   work must account for this (read both, join in Python). Spec §12.7.

6. **Side vocabulary bridge** — always normalize sides with
   `core.calc_correlation.norm_side` (BUY/long → `long`, SELL/short →
   `short`). The calc side-column and the order side-column use
   different vocabularies; comparing raw strings is the H1 bug.

7. **Schema null-ability realities.** `pre_trade_log.tp_price`/`sl_price`
   are **NOT NULL DEFAULT 0** — an "absent" TP/SL is `0.0`, not SQL
   NULL (T7 keys off `bool(value)`). `status` was DEFAULT NULL (needed
   the T210 backfill). When Phase 2 adds columns, decide null-ability
   deliberately and write the value at creation (don't rely on a
   later backfill).

8. **The transition choke-point is the law.** Never `UPDATE
   pre_trade_log SET status=...` directly — route through
   `calc_state.transition()` so the event fires and the edge is
   validated. The only sanctioned raw UPDATE is the one-shot NULL
   backfill in `database.py`. Phase 2 lifecycle_id stamping etc. should
   follow the same apply_fn + TOCTOU-guard shape; reuse
   `CalcTransitionRaceLost`.

9. **Test gotcha**: a second `TestClient(app)` in a fresh test file
   hangs the suite (documented in `test_routes.py` / `test_task101`).
   Test route logic via the underlying helper + an import-smoke, not a
   new TestClient.

10. **Events are forward-scaffolding** — there are ZERO production
    `calc:*` subscribers yet. Emitting extra payload keys is harmless.
    `calc:created` is NOT on the event_bus (only a `trade_events` row).
    Don't assume any `calc:*` event is consumed until you grep a
    subscriber.

## Next session's job — Phase 2 (position-level attribution)

Spec ref: `docs/design/calc_linkage_spec.md` §3.1 (positions_calcs),
§3.5 (lifecycle_id), §7 (position lifecycle), §8 (multi-TP).
Plan ref: `docs/design/calc_linkage_implementation_plan.md` §2 (lines
~345-375). **Effort: L — touches the hottest path (`process_fill`).**

Phase 2 = junction-aware position lifecycle. Tasks 2.1-2.12:

| # | Task |
|---|---|
| **P2.T1** | On each opening fill, insert/update `positions_calcs` (1 row per order, cumulative `contributed_qty`). **At the first fill that opens a position, generate the UUID `lifecycle_id`** and back-fill it onto `pre_trade_log.lifecycle_id`, `orders.lifecycle_id`, and the junction row. The bottleneck — blocks T3-T6. |
| P2.T2 | Stamp `calc_id` + `lifecycle_id` on every closing fill |
| P2.T3 | Add `calc_id` to `PositionInfo`; populate from junction on first fill + rehydrate |
| P2.T4 | Scale-in: new calc fires while position open → append junction row, per-calc planned_tp/sl/size |
| P2.T5 | At close, compute deltas (entry_px_delta_pct, size_delta_pct, tp/sl_drift, exit_vs_target, realized_r, hold_time). **Delta basis = most-contributing calc** (largest contributed_qty; tie-break first-entry) per spec §3.2 |
| P2.T6 | `closed_positions.calc_id` = most-contributing calc |
| P2.T7 | `exit_reason` PLANNED vs AMENDED (from amendment count + price match) |
| P2.T8 | Bracket detection per-adapter (Bybit orderLinkId, Binance positionSide clustering, OKX algoOrdId) + 2s fallback |
| P2.T9 | TP/SL inherit `calc_id` from entry when bracket detected |
| ~~P2.T10~~ | REMOVED (Q19/Q54 unified — standalone TP/SL goes through the standard matcher) |
| P2.T11 | Multi-TP partial-close lifecycle (position stays OPEN until size=0; final exit_reason=TP_LADDER_COMPLETE / MIXED) |
| P2.T12 | Restart rehydrate: populate PositionInfo.calc_id + contributing_calc_ids from junction |

### Recommended start — P2.T1 (lifecycle_id + junction)

Biggest deliverable; blocks the rest. The hook is
`core/order_manager.py::_process_single_fill` / `process_fill` (the
opening-fill path). At the first opening fill: generate `lifecycle_id`
(UUID v4), `upsert_position_calc_link(...)` (P0.T1 helper — ready), and
back-fill `lifecycle_id` onto the matched `pre_trade_log` + `orders`
rows. Scale-in fills inherit the position's existing `lifecycle_id`.

### Phase 1 deliverables Phase 2 consumes

- `orders.calc_id` (matcher) → `fills.calc_id` (propagated by
  `enrich_fill`) → the input for `positions_calcs`.
- `positions_calcs` schema + `upsert_position_calc_link` /
  `insert_calc_match_audit_batch` etc. (P0.T1 CRUD — ready).
- `orders.lifecycle_id`, `pre_trade_log.lifecycle_id`,
  `closed_positions.lifecycle_id` columns — all present, **all NULL on
  live rows today** (matcher leaves NULL; the backfill stamped only
  historical rows). P2.T1 starts forward generation.
- `_build_close_row_for_fill` already derives the contributing-calc set
  + calls `_complete_calcs_on_close` (T6). P2.T5/T6 add delta
  computation + most-contributing-calc selection at the SAME site —
  the junction (P2.T1) is the source of truth for "most-contributing".
- The completed-via-position transition (T6) already fires; P2 enriches
  the close row it's attached to.

## Known issues / follow-ups (carried forward)

### DB-routing / split-brain (settled 2026-05-28, surface-only)

Calc-linkage transactional path is single-DB on `config.DB_PATH`
(risk_engine.db). Per-account `pre_trade_log` is vestigial; `trade_events`
is per-account (cross-DB from pre_trade_log — no SQL JOIN). Full detail
in spec §12.7 + plan Phase-0 DB-routing note. **Phase 2 junction +
reverse-query work must read both DBs and join in Python.** No code
change unless the transactional path migrates to per-account routing
(then the Phase-0/1 column-adds need per-account `.sql` migrations).

### Phase-1 deferrals (out of scope by design — file as needed)

- **Order-side TP/SL gate** (T223 audit): `_try_correlate` early-returns
  if the ORDER lacks both tp/sl trigger prices → a no-TP/SL order never
  reaches the matcher → never gets `link_status`. Spec §4.5 wants
  standalone stops to go through the matcher. Pre-existing T211 gate.
- **`find_candidate_calcs` drift** (T223 audit): the Phase-3 manual-link
  finder wasn't updated to the matcher's null-handling / norm_side
  exactly. Reconcile when building the Phase-3 needs-link UI.
- **`calc:order_cancelled` event** (spec §9): not emitted (RELEASED has
  no event topic; deferred per T216). No consumers yet.
- **`partially_actioned` has no producer** (spec §16, T222): the state +
  edges + `calc:partially_filled` event are defined but nothing
  transitions a calc INTO it. Producer ("partial fill + no further
  action") belongs to Phase 2 (position-level fill tracking).
- **Multi-account expiry + §12.3 restart-rehydrate**: the T224 sweeper
  sweeps only the active account, live (not restart-time). Full §12.3
  rehydrate-expiry is later-phase.
- **`link_window_seconds_override` vs `window_seconds`** column duality:
  legacy (Task 104b, read by `exec_link.py`) vs new (T213, read by the
  matcher). Both written per-calc. Deprecate the legacy column when
  exec_link migrates. Anchor-comment in `db_trades.py`.

### lifecycle_id vs tpid-reuse (P2.T1 assumption, surfaced by T226-audit)

`_link_position_calc_on_open` reuses a position's `lifecycle_id` by
looking up existing `positions_calcs` rows for the same
`terminal_position_id`. This assumes **tpid identifies one position
instance** (never reused across close→reopen on the same symbol/dir
slot). The whole position subsystem already depends on this invariant
(`get_position_fills` strict-tpid match; `_build_close_row_for_fill`
VWAPs opens by tpid) — a recurring tpid would corrupt close-rows/fees
long before it reached the junction. Live paths hold it: binance_ws
leaves `PositionInfo.position_id=""` (→ empty tpid → junction skipped),
Quantower emits a per-position-object id. **If a future adapter emits a
recurring slot-id**, a closed trade's lifecycle would bleed into a new
one; the fix is seal-at-close, deferred because it must distinguish full
vs partial close (couples with Phase 2.11 multi-TP). Not a live blocker;
documented as an anchor comment in `order_manager.py`.

### closed_positions attribution lags the junction primary (until P2.T5/T6)

Surfaced by the holistic Phase-2 audit (after T229). Within ONE position
three attribution surfaces can disagree until P2.T5/T6 land:
- `fills.calc_id` (closing) + `PositionInfo.calc_id` = the junction
  PRIMARY / most-contributing calc (set by P2.T2 + P2.T3).
- `closed_positions.calc_id` = the EARLIEST opening fill's calc_id —
  still the Phase-1 `_build_close_row_for_fill` behavior
  (`order_manager.py`, the "calc_id from earliest entry fill" block).

For a scale-in where the larger order is NOT first they point at
different calcs. Verified e2e: open calc-A qty3, scale-in calc-B qty7,
close → `closed_positions.calc_id=calc-A` while everything else = calc-B.
**P2.T6 explicitly sets `closed_positions.calc_id = most-contributing`,
which resolves this.** Also: `closed_positions.lifecycle_id` is NULL on
close-built rows today — spec §3.5 says it's "sealed at close", so the
P2.T5/T6 close-row enrichment must stamp it from the junction. No data
loss; an attribution-consistency gap the remaining close-row tasks close.

### Junction contributed_qty redelivery double-count (T232 audit — confirmed, deferred)

Holistic Phase-2 audit (after T231) + my own runtime probe confirmed:
delivering the SAME `exchange_fill_id` twice through `_process_single_fill`
leaves `fills` deduped to one row (UNIQUE constraint) but
`positions_calcs.contributed_qty` **double-counts** (junction UPSERT does
`contributed_qty = existing + excluded`, keyed on the (position,calc,order)
triple, not fill identity). Measured: junction `contributed_qty=6` for two
deliveries of a qty-3 fill. **`orders.filled_qty` double-counts identically
(=6)** — this is a pre-existing engine-wide shape, NOT new to Phase 2; the
junction inherited it. The engine's settled discipline elsewhere is
SUM-from-fills ("never accumulate", e.g. `get_position_fees`).

Impact: `contributed_qty` is the most-contributing-calc (primary) basis, so
a redelivery hitting one calc on a *near-tie* scale-in could flip the
primary → wrong calc on closing-fill stamp + PositionInfo.calc_id.
Edge-of-edge; single-tenant localhost; observe-only.

**Not fixed in T232** because the clean fix (derive `contributed_qty` from
`SELECT SUM(quantity) FROM fills WHERE exchange_order_id=? AND
terminal_position_id=? AND is_close=0`, idempotent via the fills dedup) is
non-trivial: the unit tests drive `_link_position_calc_on_open` directly
WITHOUT persisting fills, so a SUM-from-fills approach needs the test
seeding reworked to persist fills first. **Deferred to a focused task**
that should apply the SUM-discipline to the junction (and ideally align
`orders.filled_qty` the same way). The misleading `test_qty_accumulates_
lifecycle_stable` (used the same `fid` for both fills, which looked like
a redelivery-safety test but wasn't) was fixed in T232 to use distinct fids.

### Calc-cancel UI wiring (deferred from T219 / P1.T4)

Cancel endpoint + transition shipped; the "Cancel calc" button (spec
§10.1) is not wired. When wiring it: htmx swallows non-2xx bodies (the
global `htmx:responseError` handler at base.html:996-1008 shows a
generic message), so return 200 + status-discriminated body OR add
per-element `hx-target-4*` handling to surface distinct cancel outcomes.
Codebase-wide htmx pattern (calculate_risk's 400s hit the same swallow).

### Per-position trade events drilldown (deferred to P8.T9)

Lazy-loaded timeline reusing `core.trade_event_log.query_trade_events`.
**Note the cross-DB obstacle** (trade_events per-account vs pre_trade_log
in risk_engine.db) — grouping events to a position needs read-both-join-
in-Python, not SQL.

### Pre-existing test failure + data-quality finding (unrelated)

- `TestRollingWindowPeak::test_old_high_excluded_from_window` fails on
  clean HEAD (30-day rolling-window boundary). Unrelated; file separately.
- 11+ live fills have `direction=''` (ATAUSDT, BNBUSDT, COSUSDT, IRYSUSDT,
  LABUSDT, NAORISUSDT). `position_grouping` skips empty-direction fills;
  they don't corrupt rebuilt closes but the upstream cause warrants a task.

## Files for context

- `docs/design/calc_linkage_spec.md` — spec. §3.1-§3.5 (data model),
  §4 (matcher), §5/§6 (state machines), §7 (position lifecycle), §8
  (multi-TP), §9 (events), §12.7 (DB routing), §16 (deferred).
- `docs/design/calc_linkage_implementation_plan.md` — Phase 0 ✓, Phase 1
  ✓ (§1, criteria reframed), **Phase 2 starts §2 (~line 345)**.
- `core/calc_correlation.py` — matcher + `norm_side` + `MatchResult` +
  `find_candidate_calcs`.
- `core/calc_state.py` — CALC_TRANSITIONS + `transition()` choke-point +
  `CalcTransitionRaceLost`.
- `core/account_config.py` — `AccountConfig` + sync/async config readers.
- `core/handlers.py` — `handle_risk_calculated` (calc create + supersede
  + window-freeze), `cancel_calc_by_operator`, `sweep_expired_calcs`.
- `core/order_manager.py` — `_release_calc_on_operator_cancel`,
  `_complete_calcs_on_close`, `_build_close_row_for_fill` (the Phase-2
  delta-computation site), `process_fill` (the P2.T1 hook).
- `core/order_enrichment.py` — `enrich_order` (async) → `_try_correlate`
  (matcher integration), `enrich_fill` (calc_id propagation).
- `core/db_orders.py` — OrdersMixin: `upsert_position_calc_link` (P2.T1),
  junction/audit CRUD.
- `core/schedulers.py` — `_calc_expiry_loop` + `start_background_tasks`.
- `tests/test_phase1_*.py` — the phase's test suite (esp.
  `test_phase1_lifecycle_e2e.py` for the full chain).
- `CLAUDE.md` — project discipline (test/audit/Jinja/deployment/live-DB).

## Surviving the rewind (unchanged + Phase 1 appended)

Independently load-bearing fixes preserved across the regime rewind:
- T148 MED-004 PBKDF2-SHA256 KDF upgrade (security)
- T151 `_user_data_loop` local-shadow fix (real bug)
- T154 Calculator first-submit 422 backend race (real bug)
- T157 4 regime columns on `pre_trade_log` (additive, NULL-default)
- T159 risk-engine clamps — MED-002/016/019/021 (real correctness)
- T160 MED-024 fill-misrouting UNIQUE (multi-account safety)
- T161 contract-validation NameError reactivation (LIVE DEAD-CODE BUG)
- T162 broad-except narrowing sweep (regression guardrail)
- T165 MED-017 mark-price freshness half (timestamps + stale-flag)
- T168 pollution guards (`insert_closed_position` + `log_trade_event`)
- T173-T176 MFE/MAE fixes
- T182-T194 Phase 0.0 — data quality cleanup primitives + tools + LIVE-DB
  cleanup APPLIED
- T197-T199 Phase 0.0.7 + audit-fix — legacy-orphan recovery + fills tpid
  back-link + simulation-based dry-run validation
- T200-T207 Phase 0 foundation — schema additions, state machines,
  calc-linkage backfill
- **T210-T225 Phase 1 — calc-linkage matcher + full state machine**
  (strict matcher, per-account config, revision/supersede, cancel
  endpoint, release-on-cancel, auto-complete-on-close, nullable TP/SL,
  live expiry sweeper) — all 7 tasks + audits shipped, state machine
  fully wired, lifecycle verified end-to-end.

## Memory (auto-loaded — but worth knowing)

Feedback memories in `~/.claude/projects/.../memory/`:
- **session-rules**: the 10 rules above (full text here in HANDOFF).
- **untracked-files-discipline**: call out `??` files explicitly when staging.
- **branch-off-cherry-pick**: new task branches fork off the actual tip
  including cherry-picks.
- **verify-first-default-mode**: cheap state-check before scoping
  regime/data-readiness work.

## Recoverable branches (in case you need to peek)

```
v2.5/regime-2a-counterfactual         (T169 tip — full pre-rewind state)
v2.5/regime-1c-dual-pnl               (T167)
v2.5/regime-1b-live-sizing            (T165)
v2.5/regime-1a-classifier-interface   (T163)
v2.5/fix-t168-counterfactual-data-readiness
v2.5/fix-t166-hysteresis-reading-unit
v2.5/fix-t164-fred-error-conservative
v2.5/audit-t162-broad-except-sweep    (last pre-regime state)
```

The branch is clean and ready for Phase 2. Phase 1's calc state machine
is fully wired + audited; every transition has a live producer and is
verified end-to-end. **P2.T1 (lifecycle_id generation + positions_calcs
population at first opening fill) is the next move** — the bottleneck
that unblocks the rest of position-level attribution.
