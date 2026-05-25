# Handoff — next Claude Code session

**Date**: 2026-05-25 (continued, Path A executed)
**Current branch**: `v2.5/post-rewind-drop-regime-infra` @ commit `ca9725c`
**Tests**: 2362 passed, 7 skipped (+129 net new across Phase 0.0)

## What this session did (T182-T194)

**Closed Phase 0.0 (Data Quality Pre-Work) end-to-end AND ran the
cleanup tools against the live DB.** Six development sub-tasks
(0.0.1-0.0.6) each followed by an audit-fix commit, plus two
live-DB-discovered bug fixes (T193 + T194) before --apply, plus the
actual cleanup execution.

### Phase 0.0 commit chain

```
ca9725c task 194: rebuild_closed_positions.py — preserve orphan-symbol rows by default
a61d1ef task 193: dedup_fills.py — preserve Binance matching-engine splits (same-source pairs)
01c4183 task 192: rewrite HANDOFF.md for Phase 0.0 completion
ab4e985 task 191: Phase 0.0.6 audit follow-up — atomic rebuild + M1/M2 tests
2b29e45 task 190: Phase 0.0.6 — scripts/rebuild_closed_positions.py
e34df52 task 189: Phase 0.0.5 audit follow-up — integration tests + index note
0a79675 task 188: Phase 0.0.5 — close-row builder via grouping + strict get_position_fills
775a50f task 187: Phase 0.0.4 audit follow-up — empty-fill-id guard + WS integration test
6965486 task 186: Phase 0.0.4 — reversal-split (close+open on zero-cross fill)
6d7df83 task 185: Phase 0.0.3 — scripts/dedup_fills.py
d3cc693 task 184: Phase 0.0.2 audit follow-up — preserve closes-only reconstruction
9c38691 task 183: Phase 0.0.2 — wire backfill through canonical position_grouping
3df7814 task 182: Phase 0.0.1 — promote core/position_grouping.py to production
```

### Live-DB cleanup state (Path A executed)

**Pre-cleanup backup**: `data/risk_engine.db.pre_phase0_0.bak` (19.8 MB,
2026-05-25 16:26). Restore from this if any UX regression surfaces.

**Cleanup deltas**:

| Metric | Pre | Post | Delta |
|---|---|---|---|
| Fills total | 350 | 317 | −33 (synthetic dups removed) |
| Closed positions | 184 | 151 | −33 net |
| Rebuilt rows (`source='rebuilt_from_fills'`) | 0 | 59 | clean rebuilds |
| Orphan rows preserved (`source='exchange_history_backfill'`) | 184 | 92 | untouched legacy |
| Reconciler queue (`backfill_completed=0`) | n/a | 59 | will recompute MFE/MAE |

**T193 live-DB find**: `dedup_fills.py` was wrongly collapsing Binance
matching-engine splits (sequential tradeIds, same source, identical
data). Caught before `--apply`. Fixed: preserve same-source groups.
Live DB had exactly 5 such pairs (matches T178 audit's count). Net
delete count: 38 → 33 dup groups.

**T194 live-DB find**: `rebuild_closed_positions.py` would have wiped
92 closed_positions rows for 19 symbols whose fills are missing or
broken (legacy pre-Phase-0.0.2 backfill artifacts). Caught before
`--apply`. Fixed: preserve orphan-symbol rows by default; added
`--wipe-orphans` flag for explicit override.

**BSBUSDT spot-check** (T178 reference symbol): 21 corrupted rows →
12 clean `rebuilt_from_fills` rows. No more cross-position-VWAP'd
entries or time-overlapping fragments.

## Next session's job

### Step 1: trigger the reconciler

The 59 rebuilt rows have `backfill_completed=0`, which queues them
for the reconciler to compute MFE/MAE with T175's gross-PnL floor.
This happens on the engine's next reconciler sweep — typically every
few minutes when the engine is running.

If the engine is not currently running, start it and wait for the
reconciler to catch up (logs will show `get_uncalculated_closed_positions`
returning the queue). After a sweep, all 59 rows should have
`backfill_completed=1` with computed MFE/MAE.

Verification query:

```python
import sqlite3
conn = sqlite3.connect('data/risk_engine.db')
rows = conn.execute(
    "SELECT COUNT(*) FROM closed_positions "
    "WHERE source='rebuilt_from_fills' AND NOT backfill_completed"
).fetchone()
print(f'Reconciler queue depth: {rows[0]}')  # should drop to 0
```

### Step 2 (optional): re-backfill orphan symbols

92 orphan-symbol rows from 19 symbols (`AIOTUSDT`, `AXLUSDT`,
`BASEDUSDT`, `BILLUSDT`, `CUSDT`, `DOGSUSDT`, `DUSKUSDT`, `ETCUSDT`,
`FOLKSUSDT`, `JCTUSDT`, `MUSDT`, `ONUSDT`, `PUFFERUSDT`, `SIRENUSDT`,
`STOUSDT`, `TRUMPUSDT`, `TRXUSDT`, `TSTUSDT`, `XAUUSDT`) remain in
their pre-cleanup state. The fills table doesn't have the OPEN rows
needed to reconstruct them via `position_grouping`.

Options for those rows:
- **Leave as-is**: the rows are visible in Position History with
  pre-Phase-0.0.2 reconstructed values. Not corrupted per T178 Layer 3
  (no cross-position VWAP, since each was a single-position
  reconstruction from the REALIZED_PNL row's embedded fields). Just
  legacy, can't be cross-verified.
- **Trigger `backfill_fills_from_exchange_history`** for those
  accounts — Phase 0.0.2's T184 fix synthesizes in-memory OPEN fills
  from the REALIZED_PNL row's `entry_price` + `open_time`, then
  reconstructs `closed_positions` via the canonical helper. After
  that, re-running `rebuild_closed_positions.py --apply` would
  produce rebuilt rows for those symbols too (no longer orphan).
  Operator-triggered via the API or scheduler.

### Step 3: start Phase 0.1

Phase 0.1 is the original Phase 0 from the linkage plan — additive
schema additions. Read `docs/design/calc_linkage_implementation_plan.md`
starting around line 229. Phase 0.0 is now a hard-completed
prerequisite; Phase 0.1 onwards can proceed against clean data.

## Important context

### Operator-side artifacts after cleanup

- **Position History UI** will reflect the cleaned data on next
  page-load. BSBUSDT goes from 21 rows to 12.
- **MFE/MAE values** for the 59 rebuilt rows will display 0/0 until
  the reconciler sweep completes (Step 1 above).
- **Analytics dashboards** that aggregate by `source` will show a
  new bucket `rebuilt_from_fills` alongside `exchange_history_backfill`.
- **Backup file**: `data/risk_engine.db.pre_phase0_0.bak` — keep for
  rollback if anything surprises.

### Cross-broker / platform-agnostic note

Phase 0.0 stayed broker-agnostic across all observed paths (Binance
one-way, Binance hedge, Quantower plugin, MEXC). The cleanup tools
also handle multi-broker sources via the SOURCE_PRIORITY map in
`scripts/dedup_fills.py`. Verified by source-distribution checks
during the live-DB cleanup.

### Audit discipline that paid off

Every Phase 0.0.X commit was followed by an audit pass. THREE audits
surfaced real BLOCKER-class issues that would have shipped broken:
- T184: closes-only Binance-only backfill produced zero
  closed_positions.
- T187: `synth::open` collision on empty fill_id.
- T191: rebuild DELETE+INSERTs not atomic — kill mid-script left DB wiped.

PLUS two LIVE-DB-discovered bugs ONLY surfaced from running the tools
against real data:
- T193: same-source matching-engine splits wrongly collapsed.
- T194: orphan-symbol rows wiped without replacement.

**Lesson**: development-time tests + audits catch a lot but can't
catch every data-shape class. Always dry-run against the live DB
before destructive operations, and have the operator-confirm pattern
(default `--dry-run`, explicit `--apply`) in place so mistakes are
catchable.

## Files for context

- `docs/audits/2026-05-25-t178-fills-data-quality.md` — full T178
  investigation (the corruption Phase 0.0 closes)
- `docs/design/calc_linkage_implementation_plan.md` — phased rollout.
  Phase 0.0 is lines 54-227 (✓ done, ✓ cleanup applied). Phase 0.1
  onwards starts at line 229.
- `core/position_grouping.py` — canonical "fills → position records"
  helper (Phase 0.0.1, with reverse-lookup helpers added in 0.0.5)
- `scripts/dedup_fills.py` — Phase 0.0.3 operator tool (T193 fix applied)
- `scripts/rebuild_closed_positions.py` — Phase 0.0.6 operator tool
  (T191 atomicity + T194 orphan-preservation fixes applied)
- `tests/test_position_grouping.py`, `test_phase0_0_2_*`,
  `test_dedup_fills.py`, `test_phase0_0_4_*`, `test_phase0_0_5_*`,
  `test_rebuild_closed_positions.py` — Phase 0.0 test suites
  (~129 new tests across the phase)
- `CLAUDE.md` — project test/audit/Jinja/deployment discipline

## What's surviving the rewind (from T170, still relevant)

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
- **T182-T194** Phase 0.0 — data quality cleanup primitives + tools
  + LIVE-DB cleanup APPLIED

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

The branch is in a clean state for Phase 0.1 to start. The live DB
is cleaned per Path A; reconciler will catch up on MFE/MAE for the
59 rebuilt rows on its next sweep.
