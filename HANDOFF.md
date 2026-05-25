# Handoff — next Claude Code session

**Date**: 2026-05-26
**Current branch**: `v2.5/post-rewind-drop-regime-infra`
**Tests**: 2382 passed, 7 skipped, 1 unrelated pre-existing failure
**Pre-existing failure**: `tests/test_data_cache_dd.py::TestRollingWindowPeak::test_old_high_excluded_from_window` — 30-day rolling-window boundary bug; unrelated to Phase 0.0.x work. File separately if not already.

## What this session did (T197-T199)

Closed Phase 0.0's optional Step 2 (legacy-orphan recovery) AND fixed
the pre-existing Position History fills-drawer gap that affected every
`rebuilt_from_fills` row.

### Commit chain (this session)

```
<TBD on commit>  T199: synth script — simulation-based dry-run validation + true idempotence
<TBD on commit>  T198: backfill terminal_position_id onto fills for rebuilt closed_positions
<TBD on commit>  T197: Phase 0.0.7 — synth_legacy_open_fills.py + Path C execution + plan update
```

### Step 1 + 2 status (was open in prior HANDOFF)

**Step 1** (engine reconciler picks up rebuilt rows): COMPLETED. After
Phase 0.0 the queue was 59 rebuilt rows; engine reconciler swept them
on subsequent runs. Verified MFE/MAE populated with sensible ranges
across all 59 rows; BSBUSDT spot-check clean.

**Step 2** (optional re-backfill of 92 orphan-symbol rows): COMPLETED
via a new operator script (`scripts/synth_legacy_open_fills.py`).
HANDOFF's original Step 2 framing had a mechanism flaw — proposed
re-running `backfill_fills_from_exchange_history`, but that function
synthesizes OPEN fills IN-MEMORY ONLY (db_orders.py:1138). Without
persisting OPEN fills to the fills table, `rebuild_closed_positions.py`
(which reads from fills) would still find nothing for the orphan
symbols. Path C was needed: a dedicated script that persists synth
OPEN fills AND re-derives `closed_positions` via `position_grouping`.

### Live-DB cleanup state (Step 2 executed)

**Pre-Step-2 backups**:
- `data/risk_engine.db.pre_synth_legacy_opens.bak` (~18.9 MB,
  2026-05-26 00:24) — taken before T197 --apply
- `data/risk_engine.db.pre_tpid_backfill.bak` (~18.9 MB,
  2026-05-26 01:03) — taken before T198 --apply

Restore from either if needed.

**Step 2 deltas**:

| Metric | Pre-T197 | Post-T197 | Post-T198 | Delta |
|---|---|---|---|---|
| Total `closed_positions` | 151 | 150 | 150 | — |
| `rebuilt_from_fills` rows | 59 | 121 | 121 | +62 |
| `exchange_history_backfill` orphans | 92 | 29 | 29 | −63 |
| `synth_legacy_open` fills | 0 | 63 | 63 | +63 |
| Fills with rebuilt: tpid | 0 | ~283 | **346** | +346 |
| Rebuilt rows with linked fills | 0 / 59 | 0 / 121 | **121 / 121** | full coverage |

**T197 (synth_legacy_open_fills.py)**:
- 92 orphans → 63 recoverable + 26 preserved (no upstream) + 3 fill-stream conflicts
- 65 synth OPEN fills inserted; 2 garbage synths (BILLUSDT, FOLKSUSDT)
  manually cleaned afterward (real OPEN already existed at same
  ts+price; synth duplicated it). T199's simulation-based dry-run
  now catches this class without operator intervention.

**T198 (rebuild_closed_positions.py --tpid-backfill-only)**:
- Fixed a pre-existing gap from Phase 0.0.6 (T190): rebuild emitted
  closed_positions with synthetic `terminal_position_id` but never
  wrote those tpids onto the underlying fills. Result: Position
  History fills drawer rendered empty for all 121 rebuilt rows.
- New flag `--tpid-backfill-only` UPDATEs fills.tpid without
  touching closed_positions (preserves reconciler state).
- Both `rebuild --apply` and `synth_legacy_open_fills --apply` now
  do tpid backfill inside their own transactions going forward.

**T199 (audit fix)**:
- Synth script's dry-run was previously blind to fill-stream
  conflicts (real-OPEN overlap, lifecycle absorption) — 3 such
  cases were discovered only at apply time on the live DB.
- Added simulation-based validation: builds planned synths,
  simulates `group_fills_into_positions` with existing fills +
  synths, reclassifies any planned synth that wouldn't produce a
  rebuilt record as `preserved (conflict)`.
- Re-running `--apply` against the post-T197 state now plans
  ZERO new synths — truly idempotent.

### Final orphan state (29 preserved)

| Preservation reason | Count | Symbols |
|---|---|---|
| No upstream RPNL (Binance income API window) | 26 | AIOTUSDT(2), AXLUSDT(1), CUSDT(1), DUSKUSDT(2), ETCUSDT(1), JCTUSDT(4), MUSDT(1), ONUSDT(5), PUFFERUSDT(1), SIRENUSDT(3), STOUSDT(1), TRUMPUSDT(2), TSTUSDT(1), XAUUSDT(1) |
| Real-OPEN conflict (partial close of larger position) | 2 | BILLUSDT, FOLKSUSDT |
| Lifecycle-absorption (residual qty consumed lifecycle into one record) | 1 | ONUSDT SHORT @ 1774634668929 |

These 29 are **structurally unrecoverable**. Their `closed_positions`
rows remain correct (T178 Layer 3) but cannot be cross-verified via
fills. Re-running the synth script confirms 0 planned work.

## Next session's job

### Required (small)

- **Reconciler queue verification**: 62 rebuilt rows from T197
  apply have `backfill_completed=0`. After enough engine sweeps,
  all should drain. Verify with:
  ```python
  import sqlite3
  conn = sqlite3.connect('data/risk_engine.db')
  q = conn.execute("SELECT COUNT(*) FROM closed_positions "
                   "WHERE source='rebuilt_from_fills' "
                   "AND NOT backfill_completed").fetchone()[0]
  print(f'Queue: {q}')  # target 0
  ```

### Phase 0.1 ready to start

Read `docs/design/calc_linkage_implementation_plan.md` starting at
line 229. Phase 0.0 is hard-complete; Phase 0.1 (schema additions)
can proceed against the cleaned data.

Plan was extended this session: added P8.T9 / 8.10 for a
per-position trade events drilldown in Position History drawer
(see line ~599+). Phase total bumped to ~62 tasks.

## Known issues / follow-ups

### Pre-existing test failure (unrelated)

`tests/test_data_cache_dd.py::TestRollingWindowPeak::test_old_high_excluded_from_window`
fails on clean HEAD. 30-day rolling window boundary appears to
exclude the 40-day-old peak when it should include it (or test's
window math is off). Worth investigating separately; not blocking.

### Data quality finding (pre-existing)

11+ fills in the live DB have `direction=''`:

- ATAUSDT (2), BNBUSDT (1), COSUSDT (1), IRYSUSDT (2), LABUSDT (1),
  NAORISUSDT (1) — empty direction
- `position_grouping` silently skips fills with empty direction
- These don't affect any rebuilt closed_position (which is why
  121/121 rebuilt rows have linked fills despite the 34 empty-tpid
  fills remaining)
- Likely needs an upstream investigation into why some
  exchange_history_backfill fills land with empty direction. Filing
  as a separate task is recommended.

### Per-position trade events drilldown (deferred to Phase 8)

Q2 from this session: the `trade_events` table + admin/history-tab
views already exist; what's missing is a per-position drilldown in
the Position History drawer. Scoped as P8.T9 in the implementation
plan. Works for any calc-attributed position; empty-state for
legacy / rebuilt rows (which have no calc_id).

## Important context

### Operator-side artifacts after T197+T198 cleanup

- **Position History UI** now shows fills correctly for all 121
  rebuilt rows (was empty before T198).
- **MFE/MAE values** for the 62 new T197 rebuilds populate after the
  reconciler sweep (the engine should have done this since session).
- **Source-distribution analytics** show two buckets cleanly:
  `rebuilt_from_fills` (121, clean provenance, fills-backed) and
  `exchange_history_backfill` (29, legacy island — preserved
  intentionally per categorization above).
- **Backups**: keep `pre_synth_legacy_opens.bak` and
  `pre_tpid_backfill.bak` until next major release confirms no
  regression.

### Cross-broker / platform-agnostic note (unchanged)

Phase 0.0.x stayed broker-agnostic. The synth + tpid-backfill scripts
operate on the canonical fills + closed_positions schema and don't
hard-code any adapter knowledge.

### Audit discipline that paid off (extended)

- T184, T187, T191 (Phase 0.0 audit-find BLOCKERs): development-time
  tests + audits
- T193, T194 (Phase 0.0 live-DB-only finds): operator-trigger dry-run
  discipline
- **T199 (Phase 0.0.7 audit follow-up)**: discovered the synth
  script's dry-run was blind to fill-stream conflicts — added
  simulation-based validation so the dry-run accurately predicts
  apply-time outcomes. Two cases (real-OPEN conflict + lifecycle
  absorption) now categorized correctly without operator
  intervention.

**Lesson reinforcement**: dry-run output discipline isn't just
"print what we would write"; it's "print what would actually
happen after the write." For scripts that depend on downstream
deterministic computations (like helper output), simulating that
computation in dry-run prevents post-apply surprises.

## Files for context

- `docs/audits/2026-05-25-t178-fills-data-quality.md` — original
  T178 corruption investigation
- `docs/design/calc_linkage_implementation_plan.md` — phased rollout;
  Phase 0.0 ✓ done, Phase 0.1+ ready. P8.T9 added this session.
- `core/position_grouping.py` — canonical helper; T198 added
  `attribution_out` parameter for fill-id back-tracking
- `scripts/dedup_fills.py` — Phase 0.0.3 operator tool
- `scripts/rebuild_closed_positions.py` — Phase 0.0.6 + T198 tpid
  backfill + `--tpid-backfill-only` mode
- `scripts/synth_legacy_open_fills.py` — Phase 0.0.7 (T197 + T199)
- `tests/test_position_grouping.py` — added TestAttributionOut (5 tests)
- `tests/test_rebuild_closed_positions.py` — added 4 tpid-backfill tests
- `tests/test_synth_legacy_open_fills.py` — 12 tests covering all
  recovery + conflict shapes
- `CLAUDE.md` — project discipline (test/audit/Jinja/deployment)

## What's surviving the rewind (unchanged)

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

## Memory (auto-loaded — but worth knowing)

Three feedback memories in `~/.claude/projects/.../memory/`:
- **untracked-files-discipline**: call out `??` files explicitly
  when staging; don't silently filter
- **branch-off-cherry-pick**: new task branches must fork off the
  actual tip including cherry-picks, not the named-task commit alone
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

The branch is clean for Phase 0.1 to start. Live DB cleaned through
Phase 0.0.7 (T197) + tpid-backfill (T198). Synth script is truly
idempotent post-T199. Position History fills drawer populates for
all 121 rebuilt rows.
