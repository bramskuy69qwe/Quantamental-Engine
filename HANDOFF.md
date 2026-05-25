# Handoff — next Claude Code session

**Date**: 2026-05-25
**Current branch**: `v2.5/post-rewind-drop-regime-infra` @ commit `fbeaf45`
**Tests**: 2233 passed, 7 skipped

## What this session did (T173-T180)

Started as "fix the MFE/MAE inaccuracy" (T173-T176), discovered the
underlying corruption goes way deeper (T177-T178), and locked in a
plan for the cleanup (T179-T180).

**T173-T176 — MFE/MAE display fixes (shipped)**:
- T173: sign-clamp on `calc_mfe_mae` — MFE ≥ 0, MAE ≤ 0; fixed
  session_mae seeding bug in `apply_mark_price`
- T174: position history template renders MFE+MAE together (was
  inconsistently splitting "0" rendering with "—")
- T175: realized-PnL floor on `calc_mfe_mae` — MFE for winners can't
  display below `gross_pnl`; MAE for losers can't display above
- T176: `INSERT OR REPLACE` on `closed_positions` preserves reconciler
  columns (`mfe`, `mae`, `backfill_completed`) — closes the partial-fill
  REPLACE race; aggTrades trailing buffer widened from 1s → 5s for
  clock-skew tolerance

**T177-T178 — paused → investigation pivot**:
- T177 started building a rebuild for the corrupted closed_positions
  data. Got `core/position_grouping.py` (chronological-walk grouping)
  + `scripts/rebuild_closed_positions_dryrun.py` (write-free diff)
  as drafts.
- During dry-run, discovered fills table has ~1.7-2x close-vs-open
  inflation — corruption is deeper than MFE/MAE. Paused T177;
  pivoted to T178 investigation (read-only).
- T178 findings doc: `docs/audits/2026-05-25-t178-fills-data-quality.md`
  — five corruption layers identified:
  1. **Synthetic-fill duplication** from
     `exchange_history_backfill` (db_orders.py:935+) creating fills
     alongside real WS/REST fills
  2. **`terminal_position_id` never populated** — Quantower's
     plugin is the only source; without plugin → empty (verified
     back to May 14 backups, not migration regression)
  3. **`get_position_fills` fallback contamination** — empty pos_id
     triggers `(symbol, direction)` match that pulls fills from
     distinct historical positions
  4. **Position-reversal lossiness** — LONG→SHORT in single fill
     records ONE row with `is_close=True`; new direction's open
     never persists
  5. 5 strict-duplicate pairs (Binance matching-engine splits — NOT
     bugs, leave as-is)

**T179-T180 — plan + drafts committed**:
- T179: inserted **Phase 0.0 (Data Quality Pre-Work)** into
  `docs/design/calc_linkage_implementation_plan.md`. Six sub-tasks
  (0.0.1 through 0.0.6) covering the three fixable layers + the
  centralization of `position_grouping.py` as the canonical
  "fills → position records" helper.
- T180: committed the T177 drafts as Phase 0.0 starting points so
  they don't get lost. NOT production-ready — clearly marked in
  docstrings; need TypedDict, dedup constants, tests before any
  caller uses them.

## Next session's job: implement Phase 0.0 starting from 0.0.1

Read `docs/design/calc_linkage_implementation_plan.md` Phase 0.0 section
end-to-end before touching anything. It captures:
- Why Phase 0.0 exists (links to T178 findings)
- Architectural decisions (position_grouping centralization, synthetic
  `synth:{tradeId}:open` exchange_fill_id convention, fill-dedup
  tolerance rule)
- Six sub-tasks with file-level scope, rewiring notes, test fallout
  flags, rollback plans
- Why it's a hard prerequisite for Phase 0.11's positions_calcs backfill

**Order of work (per plan)**:

| Task | What | Risk | Test fallout |
|---|---|---|---|
| 0.0.1 | Refactor `core/position_grouping.py` draft → production: add `PositionRecord` TypedDict, `FILL_DEDUP_TOLERANCE_MS = 2000`, `FILL_DEDUP_PRICE_TOLERANCE_PCT = 0.0`, `is_same_fill(a, b)` helper. Write `tests/test_position_grouping.py` covering single position, scale-in, partial close, hedge mode, qty-epsilon. **No production callers yet.** | Low (additive) | None |
| 0.0.2 | Fix 1: dedup guard in `exchange_history_backfill` (db_orders.py:935+) using `is_same_fill`. Refactor its closed_positions construction to call `position_grouping`. | Medium | Existing tests on `exchange_history_backfill` will need updates for the new dedup behavior |
| 0.0.3 | Fix 2: `scripts/dedup_fills.py` (dry-run + apply). Operator-controlled; backup required. | Medium (destructive on apply) | Add new test fixtures |
| 0.0.4 | Fix 3: reversal-split. `position_snapshot.py` returns 2-portion snapshot when crossing zero; `order_manager.py:process_fill` writes 2 fill rows. Synthetic ID = `"synth:{tradeId}:open"`. | **High** (contract change) | **Expect substantial fallout**: any test asserting "1 fill per WS event" breaks for reversal scenarios |
| 0.0.5 | Refactor `_build_close_row_for_fill` to use `position_grouping` instead of `get_position_fills` fallback. Remove the bad fallback arm from `get_position_fills`. | Medium | Tests asserting `get_position_fills` returns rows when pos_id is empty (they're testing a bug) — invert or remove |
| 0.0.6 | `scripts/rebuild_closed_positions.py` (extends the T180 dryrun draft). Operator-controlled; rebuilds closed_positions from clean fills using `position_grouping`. Resets `backfill_completed=0` so reconciler re-runs MFE/MAE with T175's floor. | Medium (destructive on apply) | None — script is additive |

## Starting hint

**Step 1**: Read Phase 0.0 in the plan. Don't skim — every sub-task's
notes column matters.

**Step 2**: Check the T180 drafts (`core/position_grouping.py`,
`scripts/rebuild_closed_positions_dryrun.py`) — they're the starting
material for 0.0.1 and 0.0.6 but need the work described in those
sub-tasks before they're production-ready.

**Step 3**: Start with 0.0.1 (lowest risk, no production callers).
Work through to 0.0.6 in order — each depends on prior. Verify-first
discipline (cheap state-check) per the memory between sub-tasks.

**Step 4**: Each sub-task = one commit. Use the `task NNN: ...`
naming convention. Reference the Phase 0.0 sub-task number in the
commit body so future readers can trace.

**Step 5**: After 0.0.6, you can then proceed to Phase 0.1 (the
original schema additions) — at that point Phase 0.11's
positions_calcs backfill will have a clean source to work against.

## Important context from this session

**MFE/MAE math invariant** (T175): for a winning trade, MFE ≥ gross_pnl.
For a losing trade, MAE ≤ gross_pnl. Floor is enforced in `calc_mfe_mae`
when `exit_price` is supplied. T177's `position_grouping.py` draft
doesn't currently invoke this — when 0.0.6 rebuilds closed_positions,
the reconciler will run MFE/MAE separately (using T175's floor).
Don't try to re-derive MFE/MAE inside `position_grouping` — leave that
to the reconciler.

**T176 REPLACE race fix is still active** — `insert_closed_position`
preserves `mfe`/`mae`/`backfill_completed` across REPLACEs. This is
important for 0.0.6: when the rebuild script wipes and recreates
closed_positions rows, `backfill_completed` should be set to 0
explicitly so the reconciler re-runs.

**`scripts/rebuild_closed_positions_dryrun.py` is read-only.** Safe to
run against live DB for diagnostics. The Phase 0.0.6 production script
will be a separate file (`scripts/rebuild_closed_positions.py`)
with `--dry-run` default + `--apply` flag.

## What's surviving the rewind (from T170 — still relevant)

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
- **T173-T176** MFE/MAE fixes (sign-clamp + render-together + floor +
  REPLACE-race fix)

## Memory (auto-loaded — but worth knowing)

Three feedback memories in `~/.claude/projects/.../memory/`:
- **untracked-files-discipline**: call out `??` files explicitly
  when staging; don't silently filter
- **branch-off-cherry-pick**: new task branches must fork off the
  actual tip including cherry-picks, not the named-task commit alone
- **verify-first-default-mode**: cheap state-check before scoping
  regime/data-readiness work (opportunistic post-T169; full re-sync
  only if divergence found)

## Live-DB diagnostic snapshot

- DB: `data/risk_engine.db` (pre-split layout — has `closed_positions`)
- 175 closed trades, 2026-03-13 to 2026-05-20
- **ALL have NULL/empty calc_id** (calc path wasn't exercised in
  test sessions)
- 350 fills total; ALL have empty `terminal_position_id`
- Fills source distribution: `binance_rest` 152, `binance_ws` 65,
  `exchange_history_backfill` 133 (the last is the synthetic-dup
  source)
- BSBUSDT specifically: 79 fills (51 REST + 11 WS + 17 synthetic),
  21 closed_positions rows for what's likely 12 real logical
  positions
- `regime_signals`: vix/us10y/hy/btc_rvol cover the trade window;
  `avg_funding` has 20 days only; `agg_oi_change` is missing entirely

## Files for context

- `docs/audits/2026-05-25-t178-fills-data-quality.md` — full
  investigation, all 5 layers, repair-difficulty matrix
- `docs/audits/2026-05-17-v2.4-backend-audit.md` — Stat Summary
  section at top has the T170 rollback notes
- `docs/design/calc_linkage_spec.md` — 68-decision linkage spec
- `docs/design/calc_linkage_implementation_plan.md` — phased rollout
  including the **new Phase 0.0** section
- `v2.5_regime-plan.md` — regime architecture plan (preserved
  across rewind; regime rebuild comes AFTER calc_linkage)
- `CLAUDE.md` — project test/audit/Jinja/deployment discipline

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

## Recent commit chain on the current branch

```
fbeaf45 task 180: land Phase 0.0 starting drafts
bbc88e6 task 179: insert Phase 0.0 into calc_linkage_implementation_plan
275e0dc task 178: investigate fills data quality
6afde98 task 176: insert_closed_position preserves reconciler columns
41ae544 task 175: MFE/MAE realized-PnL floor
b4f5c53 task 174: position history MFE/MAE — render together
7265375 task 173: clamp MFE/MAE signs
07cd733 Revert "task 171: calculator anti-flicker" (T171 was wrong-mechanism)
86b19fe task 170: rewind — drop regime infrastructure T163-T169
```

The branch is in a clean state for Phase 0.0.1 to start.
