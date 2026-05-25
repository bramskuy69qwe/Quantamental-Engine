# Handoff — next Claude Code session

**Date**: 2026-05-26 (continued)
**Current branch**: `v2.5/post-rewind-drop-regime-infra` @ `7a6ea60`
**Tests**: 2526 passed, 7 skipped, 1 unrelated pre-existing failure
**Pre-existing failure**: `tests/test_data_cache_dd.py::TestRollingWindowPeak::test_old_high_excluded_from_window` — 30-day rolling-window boundary bug; unrelated. Worth filing as its own task.

## What this session did — Phase 0 COMPLETE (T200-T207)

Tasks 197-199 closed Phase 0.0 optional work. Tasks **200-207 closed
all of Phase 0** (foundation — schema additions, state-machine
helpers, calc-linkage backfill). Per implementation plan §14.3,
Phase 0 was 6 bundled tasks (P0.T1-T6); we shipped all 6 plus one
audit-followup. Phase 1 is now unblocked.

### Commit chain

```
7a6ea60  task 207: P0.T5 audit follow-up — pre_trade_log + orders lifecycle backfill + unmapped-exit-reason warning
f86c93f  task 206: Phase 0 T5 — calc-linkage backfill (exit_reason + lifecycle_id + junction)
99e67cc  task 205: Phase 0 T4 — orders + closed_positions column additions
3a13a34  task 204: Phase 0 T3 — pre_trade_log + accounts column additions
ce5c33a  task 203: Phase 0 T2 — operator_sessions scaffold (table + CRUD + dataclass)
6fb89cc  task 202: P0.T6 audit follow-up — clarify state-machine spec citations
9324b3e  task 201: Phase 0 T6 — state-machine enforcement helpers (calc + link)
1e51d1a  task 200: Phase 0 T1 — calc-linkage schema foundation (4 new tables + CRUD)
e3ffae6  task 199: HANDOFF — Phase 0.0.7 + tpid backfill + per-position events drilldown deferred
2ba874c  task 198: backfill terminal_position_id onto fills for rebuilt closed_positions
5e918f1  task 197: Phase 0.0.7 — scripts/synth_legacy_open_fills.py for legacy orphan recovery
```

### Phase 0 task-by-task

| Plan ref | Task | Commit | Files |
|---|---|---|---|
| P0.T1 | 4 new tables + CRUD helpers | 200 | core/database.py, core/db_orders.py, tests/test_phase0_t1_schema.py |
| P0.T2 | operator_sessions table + scaffold | 203 | core/database.py, core/db_auth.py, core/auth_state.py, tests/test_phase0_t2_operator_sessions.py |
| P0.T3 | pre_trade_log (15 cols) + accounts.config_json | 204 | core/database.py, tests/test_phase0_t3_schema_additions.py |
| P0.T4 | orders (6 cols) + closed_positions (16 cols) | 205 | core/database.py, tests/test_phase0_t4_schema_additions.py |
| P0.T5 | Calc-linkage backfill script | 206, 207 | core/database.py (fills.lifecycle_id), scripts/backfill_calc_linkage.py, tests/test_backfill_calc_linkage.py |
| P0.T6 | State-machine helpers (calc + link) | 201, 202 | core/calc_state.py, core/link_state.py, tests/test_state_machines.py |

### Schema landed (spec §3.1 + §3.2)

**5 new tables** (all with lifecycle_id where applicable, indexed per spec §3.5):
- `positions_calcs` — junction for scale-in attribution (UNIQUE on (position_id, calc_id, order_id))
- `order_amendments` — polymorphic field-level audit (entry/tp/sl/size/leverage)
- `funding_events` — per-event funding (UNIQUE on venue_event_id for dedup)
- `calc_match_audit` — per-criterion match evidence (batch-inserted by Phase 1 matcher)
- `operator_sessions` — multi-operator handoff audit (logic deferred to Phase 9)

**Modified tables**:
- `pre_trade_log`: 36 → 51 cols (status, window_seconds, operator_id, superseded_by_calc_id, cancelled_reason, planned/overridden size+tp+sl, tp_levels JSON, filled_pct, tags JSON, lifecycle_id)
- `orders`: 26 → 32 cols (link_status, operator_id, cancel_reason_category, cancel_reason_raw, cancel_ts_ms, lifecycle_id)
- `closed_positions`: 28 → 44 cols (close_note, 8 delta/drift/r REAL columns, hold_time pairs, cumulative_amendment_count, liquidation fields, adl_indicator, lifecycle_id)
- `accounts`: 14 → 15 (config_json TEXT per spec §3.3)
- `fills`: lifecycle_id added (spec-gap closure — §3.5 lists it but plan §0.6/0.7/0.8 omitted)

**Indexes** (spec §3.5: every lifecycle_id-carrying table indexed):
- idx_pretrade_lifecycle, idx_orders_lifecycle, idx_closed_pos_lifecycle, idx_fills_lifecycle
- idx_pc_lifecycle, idx_oa_lifecycle, idx_fe_lifecycle (in P0.T1 table DDL)

### State machines (P0.T6 + audit follow-up)

`core/calc_state.py` and `core/link_state.py` mirror the existing
`core/order_state.py` pattern. Both expose:
- Status enum (CalcStatus 8 values per spec §3.4; LinkStatus 4 values)
- Transitions dict (CALC_TRANSITIONS / LINK_TRANSITIONS) per spec §5/§6
- validate_transition / assert_transition pure helpers
- IllegalStateTransition exception carrying calc_id/order_id + current + target
- async transition() choke-point: validate → caller-supplied apply_fn → emit event
  - Invariants: invalid raises without side effect; apply failure skips event;
    event-bus failure does NOT roll back the DB UPDATE (logged + swallowed)

CalcStatus extensions vs spec §5:
- RELEASED state added per Phase 1.7 (calc release on order cancel) — documented
  in code header. Transitions in/out mirror ACTIVE's outgoing edges so a released
  calc can re-match within its original window.

LinkStatus vs spec §6:
- §6 diagram omits UNLINKED but §3.4 enum lists it. Code includes UNLINKED +
  its operator-action transitions (UNLINKED → UNPLANNED + UNLINKED → LINKED for
  late manual-link discovery), per Phase 3.1 + 3.4 scope.

### Calc-linkage backfill (P0.T5 + audit follow-up)

Operator script `scripts/backfill_calc_linkage.py` with `--dry-run`/`--apply`
+ `--account-id`/`--symbol` scoping. Five operations, all idempotent +
wrapped in a single transaction:

1. Re-map closed_positions.exit_reason legacy → spec §3.4 enum
   (`'manual'`→`MANUAL_OTHER`, `'tp'`→`TP_PLANNED`, `'sl'`→`SL_PLANNED`,
   `''`/NULL→`MANUAL_OTHER`).
2. Generate UUID-v4 lifecycle_id for each closed_positions row missing
   one. Stamp onto matching fills (by terminal_position_id).
3. Stamp lifecycle_id onto pre_trade_log via the chain
   `pre_trade_log.calc_id → fills.calc_id → fills.terminal_position_id
   → closed_positions.terminal_position_id` (P0.T5 + T207 audit fix).
4. Stamp lifecycle_id onto orders via the chain
   `orders.exchange_order_id → fills.exchange_order_id → ...
   closed_positions` (T207 audit fix).
5. Backfill positions_calcs junction from fills WHERE calc_id IS NOT
   NULL, grouped per (closed_position.id, calc_id, orders.id) with
   summed contributed_qty. Skip fills whose order_id doesn't resolve.

Plus: warning surfaced when unmapped exit_reason encountered (T207
audit follow-up). Live DB: 0 unmapped values.

### Live-DB state after Phase 0

| Metric | Value |
|---|---|
| closed_positions: total | 150 |
| closed_positions: with lifecycle_id | **150** (all unique UUIDs) |
| closed_positions: exit_reason | 150 × `MANUAL_OTHER` (all post-T206 re-map) |
| fills: total | 380 |
| fills: with lifecycle_id | 346 (the 34 missing are bf:-source legacy orphan-symbol fills) |
| orders: total | 144 |
| orders: with lifecycle_id | **75** (T207 backfill via fills chain) |
| pre_trade_log: total | 118 (24 carry calc_id but no chain to fill — none stamped) |
| positions_calcs | 0 (no legacy fills carry calc_id; Phase 1+ matcher populates forward) |
| operator_sessions / order_amendments / funding_events / calc_match_audit | 0 (Phase 1/4/5/9 wire writes) |

**Backups taken this session** (in `data/`):
- `risk_engine.db.pre_p0t1_schema.bak`
- `risk_engine.db.pre_p0t2_schema.bak`
- `risk_engine.db.pre_p0t3_schema.bak`
- `risk_engine.db.pre_p0t4_schema.bak`
- `risk_engine.db.pre_p0t5_backfill.bak`
- `risk_engine.db.pre_t207_audit_followup.bak`
- Plus Phase-0.0-era: `pre_phase0_0.bak`, `pre_synth_legacy_opens.bak`, `pre_tpid_backfill.bak`

Keep until next major release confirms no regression. Safe to delete
older `.bak` files (pre_phase0_0 onward) at operator's discretion.

## Next session's job — Phase 1 (matcher tightening)

Spec ref: docs/design/calc_linkage_spec.md §4 + §5 + §6
Plan ref: docs/design/calc_linkage_implementation_plan.md §277-326
+ §14.3 lines 846-859

Phase 1 = 7 tasks per §14.3:

| # | Task | Notes |
|---|---|---|
| **P1.T1** | Strict matcher rewrite | The bottleneck. 5/5 limit + 6/6 market criteria; tolerance config from `accounts.config_json.entry_tolerance_pct` (P0.T3 column ready). `calc_match_audit` row writes per criterion (P0.T1 table + CRUD ready). All calc.status transitions go through `core/calc_state.transition()` (P0.T6 ready). |
| P1.T2 | Per-account window from config_json | New `core/account_config.py` helper; reads accounts.config_json with spec §3.3 defaults. |
| P1.T3 | Calc revision detection | If existing `active` calc for (account, ticker, direction), set `status='superseded'`, write `superseded_by_calc_id`, emit `calc:superseded` event (via calc_state.transition). |
| P1.T4 | Calc cancel by operator endpoint | New endpoint + transition. |
| P1.T5 | Calc release on order cancel | `matched → released` transition when order cancel_reason_category='OPERATOR'; replacement-modal scaffold. |
| P1.T6 | Calc auto-complete on position close | Transition + event (may slide to Phase 2). |
| P1.T7 | Nullable TP/SL handling | Auto-route to manual-link if TP or SL null. |

Sequencing per §14.4: T1 is the bottleneck; T2-T7 parallel-safe after.

### Recommended start

Begin with **P1.T1** (matcher rewrite) — biggest single deliverable
in Phase 1, blocks T3-T7. Existing matcher lives in
`core/calc_correlation.py::correlate_order_to_calc` (per plan §1.1).
Replace with strict 5/5 (limit) / 6/6 (market) all-or-fall-through;
write `calc_match_audit` rows per criterion (winning + losing
candidates).

### Phase 0 deliverables Phase 1 will consume

- `core.calc_state.transition` — every status change goes through it
- `core.link_state.transition` — same for orders.link_status
- `accounts.config_json` column — Phase 1.T2 helper reads it
- `pre_trade_log.window_seconds` + `operator_id` + 13 other cols — matcher writes them
- `calc_match_audit` table + `insert_calc_match_audit_batch` helper — matcher batch-writes
- `positions_calcs` schema + `upsert_position_calc_link` — Phase 2 wires
- `orders.link_status` + `orders.lifecycle_id` — matcher writes link_status; lifecycle stays NULL until Phase 2's first opening fill

## Known issues / follow-ups (carried forward)

### Pre-existing test failure (unrelated)

`tests/test_data_cache_dd.py::TestRollingWindowPeak::test_old_high_excluded_from_window`
still fails on clean HEAD. 30-day rolling window boundary appears to
exclude the 40-day-old peak when it should include it (or test's
window math is off). Investigate separately; not blocking Phase 1.

### Data quality finding (pre-existing, carried from prior HANDOFF)

11+ fills in the live DB have `direction=''` across ATAUSDT, BNBUSDT,
COSUSDT, IRYSUSDT, LABUSDT, NAORISUSDT. `position_grouping` silently
skips fills with empty direction. They don't affect any rebuilt
closed_position (121/121 linked correctly) but the upstream cause —
why some exchange_history_backfill fills land with empty direction —
warrants investigation. File as its own task.

### Per-position trade events drilldown (deferred to P8.T9)

Plan §8.10 / §14.3 P8.T9 added in task 199 — per-position trade events
drilldown in Position History drawer. Lazy-loaded timeline reusing
`core.trade_event_log.query_trade_events`. Empty-state for legacy /
rebuilt rows with no calc_id. Picks up in Phase 8 after Phase 1+
event-emission sweeps land.

## Files for context

- `docs/design/calc_linkage_spec.md` — spec; key sections §3.1-§3.5
  (data model), §4 (matcher), §5/§6 (state machines), §9 (event catalog),
  §12.3 (restart)
- `docs/design/calc_linkage_implementation_plan.md` — phased rollout.
  Phase 0 ✓ done (lines 229-275). Phase 1 starts line 277.
- `core/database.py` — schema + migrations (all P0 tables + columns
  landed here)
- `core/db_orders.py` — OrdersMixin with 12 new CRUD helpers
  (positions_calcs, order_amendments, funding_events, calc_match_audit)
- `core/db_auth.py` — AuthMixin with operator_sessions CRUD
- `core/auth_state.py` — OperatorSession dataclass + event topic constants
- `core/calc_state.py` / `core/link_state.py` — state machines
- `scripts/backfill_calc_linkage.py` — P0.T5 backfill (operator-controlled)
- `tests/test_phase0_t{1,2,3,4}_*.py` — 69 tests for P0.T1-T4
- `tests/test_state_machines.py` — 51 tests for P0.T6
- `tests/test_backfill_calc_linkage.py` — 24 tests for P0.T5 + audit follow-up
- `CLAUDE.md` — project discipline (test/audit/Jinja/deployment)

## Surviving the rewind (unchanged)

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
- T182-T194 Phase 0.0 — data quality cleanup primitives + tools +
  LIVE-DB cleanup APPLIED
- **T197-T199 Phase 0.0.7 + audit-fix** — legacy-orphan recovery +
  fills tpid back-link + simulation-based dry-run validation
- **T200-T207 Phase 0 foundation** — schema additions, state machines,
  calc-linkage backfill (all 6 sub-tasks shipped)

## Memory (auto-loaded — but worth knowing)

Three feedback memories in `~/.claude/projects/.../memory/`:
- **untracked-files-discipline**: call out `??` files explicitly
  when staging
- **branch-off-cherry-pick**: new task branches must fork off the
  actual tip including cherry-picks
- **verify-first-default-mode**: cheap state-check before scoping
  regime/data-readiness work

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

The branch is clean and ready for Phase 1. All Phase 0 schema is in
the live DB. State-machine choke-points are in place. Backfill script
is idempotent (verified). Phase 1.T1 (matcher rewrite) is the next
move.
