# Handoff — next Claude Code session

**Date**: 2026-05-25 (continued)
**Current branch**: `v2.5/post-rewind-drop-regime-infra` @ commit `ab4e985`
**Tests**: 2356 passed, 7 skipped (+123 net new across Phase 0.0)

## What this session did (T182-T191)

**Closed Phase 0.0 (Data Quality Pre-Work) end-to-end.** All six
sub-tasks landed, each with an audit pass that found real issues
(2 BLOCKERs, several HIGH/MEDIUM) and was followed by a fixup commit.

### Phase 0.0 commit chain

```
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

### What each phase did

- **0.0.1 (T182)**: `core/position_grouping.py` promoted to production.
  `PositionRecord` TypedDict, `FILL_DEDUP_TOLERANCE_MS=2000`,
  `FILL_DEDUP_PRICE_TOLERANCE_PCT=0.0`, `is_same_fill(a,b)` helper.
  No production callers yet — pure foundation.

- **0.0.2 (T183 + T184)**: `core/db_orders.py::backfill_fills_from_exchange_history`
  refactored. Inline SQL dedup → `is_same_fill`. Ad-hoc `(symbol,
  direction, open_time)` grouping → `group_fills_into_positions`.
  T184 audit fix added in-memory synthetic OPENs for closes-only
  Binance-only path (the audit caught a real BLOCKER regression).

- **0.0.3 (T185)**: `scripts/dedup_fills.py` operator tool. Source
  priority `binance_ws > binance_rest > exchange_history_backfill`.
  Live DB smoke: 12 dup groups detected on BSBUSDT alone (exactly the
  T178 Layer 1 reproduction). Default `--dry-run`, `--apply` opt-in.

- **0.0.4 (T186 + T187)**: reversal-split. Single fill crossing zero
  now produces TWO fill rows: close-of-old (`{tradeId}`) + open-of-new
  (`synth:{tradeId}:open`). T187 audit fix added empty-fill-id guard +
  WS-pipeline integration test (verifies the full Binance one-way path
  `ps="BOTH"` → `direction="BOTH"` → one_way mode → reversal-split fires).

- **0.0.5 (T188 + T189)**: `_build_close_row_for_fill` refactored to
  use `find_opens_for_position_close_at` (new helper) when pos_id is
  empty. `get_position_fills` is now STRICT — empty pos_id returns [].
  T189 audit fix added integration tests (including a T178 Layer 3
  regression guard at the live close-row builder boundary) + a
  performance note about missing covering index.

- **0.0.6 (T190 + T191)**: `scripts/rebuild_closed_positions.py`
  operator tool. DELETE existing in scope + INSERT rebuilt rows via
  `group_fills_into_positions`. T191 audit fix made the operation
  ATOMIC (single transaction with rollback on failure) by adding
  `commit: bool` to `insert_closed_position` — kill or insert-failure
  mid-script now rolls back instead of leaving the DB wiped but
  rebuilt rows incomplete.

### What this means for the live DB

The Phase 0.0 work introduced FIXES + TOOLS, but **didn't yet apply
them to the live DB**. The live DB at
`data/risk_engine.db` still has the T178 corruption documented in
`docs/audits/2026-05-25-t178-fills-data-quality.md`.

The dry-run smoke against BSBUSDT showed the impact:
- **dedup_fills**: 12 duplicate groups (synthetic-backfill vs real
  WS/REST pairs).
- **rebuild_closed_positions**: 21 corrupted closed_positions rows
  collapse to 12 clean rebuilt positions.

Multiply across all symbols in the live DB → significant cleanup
available when the operator chooses to run it.

## Next session's job — pick a path

### Path A (recommended): operator runs Phase 0.0 cleanup, then Phase 0.1 starts

**Step 1 — Operator runs the Phase 0.0 cleanup tools.**

```bash
# 1. Back up the DB.
cp data/risk_engine.db data/risk_engine.db.pre_phase0_0.bak

# 2. Clean fills (Phase 0.0.3).
python scripts/dedup_fills.py                # DRY-RUN first
python scripts/dedup_fills.py --apply        # then apply

# 3. Rebuild closed_positions (Phase 0.0.6).
python scripts/rebuild_closed_positions.py            # DRY-RUN first
python scripts/rebuild_closed_positions.py --apply    # then apply

# 4. Reconciler auto-runs on next engine sweep, applies T175's
#    MFE/MAE floor to the rebuilt rows.
```

**Step 2 — Verify the cleanup landed correctly.** Spot-check
closed_positions for a known symbol; compare to the pre-cleanup
backup. Check that MFE/MAE values appear correct after reconciler
sweep.

**Step 3 — Start Phase 0.1.** Read
`docs/design/calc_linkage_implementation_plan.md` lines 229+
(Phase 0: Foundation — schema additions). That's the original phase
0 — additive schema work. The plan was reorganized so 0.0 is the
pre-work; 0.1 onwards is the original linkage rollout.

### Path B: Skip the cleanup, go directly to Phase 0.1

Phase 0.1 is purely schema additions (additive, non-breaking). It
doesn't depend on the Phase 0.0 cleanup having run — that's a
prerequisite for **Phase 0.11's positions_calcs backfill**, not for
Phase 0.1's schema work.

If the operator wants to defer the cleanup, Phase 0.1 can proceed
immediately. The cleanup can happen any time before Phase 0.11.

### Recommendation

Path A. The cleanup is operator-visible — it'll fix the BSBUSDT-style
anomalies the operator already flagged. Running it now means the next
sessions can develop against clean data, not against the corrupted
fixture.

## Important context

### Operator workflow surface

Two new operator scripts. Both default to dry-run, require explicit
`--apply` for destructive operations, print a 3-second countdown
warning, and chunk DELETEs / wrap in transactions for safety.

- `scripts/dedup_fills.py`: source-priority dedup. Cleans
  Layer 1 (synthetic duplication).
- `scripts/rebuild_closed_positions.py`: atomic rebuild. Cleans
  Layer 3 (cross-position contamination) + Layer 5 in the historical
  data.

Layer 4 (reversal-split) is already fixed in the LIVE write path
(Phase 0.0.4); historical reversals will be reconstructed by the
rebuild script.

### What still needs operator action

- The `bf:%`-prefixed closed_positions rows from prior backfill runs
  will be REPLACED by `rebuilt:%`-prefixed rows when
  `rebuild_closed_positions.py --apply` runs. Old rows are wiped via
  the script's DELETE step.
- After rebuild, `backfill_completed=0` triggers the reconciler to
  re-run MFE/MAE with T175's gross-PnL floor in place. Wait for the
  next reconciler sweep before assessing UI correctness.

### Cross-broker / platform-agnostic note

Phase 0.0 stayed broker-agnostic. The mode-detection heuristic in
`_snapshot_and_fix_isclose` correctly handles:
- Binance one-way (`ps="BOTH"` → one_way mode → reversal-split fires)
- Binance hedge (`ps="LONG"`/`"SHORT"` → hedge mode → suppressed,
  correct because each side tracks independently)
- Quantower plugin (`direction="LONG"`/`"SHORT"` → hedge mode →
  suppressed, correct because plugin pre-splits via OPEN +
  REALIZED_PNL events)
- MEXC (no `direction` set by adapter → empty → one_way mode →
  reversal-split fires if zero-crossing observed)

The one Binance-flavored token (`"BOTH"`) only ever appears in
Binance one-way events. Other broker paths benignly skip splits via
either hedge classification or pre-splitting at the adapter layer.

### Audit discipline that paid off

Every Phase 0.0.X commit was followed by an independent audit pass.
Three of those audits surfaced real issues that would have shipped
broken:
- **T184 (B1)**: closes-only Binance-only backfill produced zero
  closed_positions. Real regression for the no-plugin path.
- **T187 (M1)**: `synth::open` collision on empty fill_id.
- **T191 (B1)**: rebuild DELETE+INSERTs not atomic — kill mid-script
  left the DB wiped.

Three were verified clean (audits found only LOW/MEDIUM gaps —
documentation, perf, opportunistic test coverage). Pattern is
recommended for future destructive / cross-cutting work.

## Files for context

- `docs/audits/2026-05-25-t178-fills-data-quality.md` — full T178
  investigation (the corruption Phase 0.0 closes)
- `docs/design/calc_linkage_implementation_plan.md` — phased rollout.
  Phase 0.0 is lines 54-227 (✓ done). Phase 0.1 onwards starts at
  line 229.
- `core/position_grouping.py` — canonical "fills → position records"
  helper (Phase 0.0.1, with reverse-lookup helpers added in 0.0.5)
- `scripts/dedup_fills.py` — Phase 0.0.3 operator tool
- `scripts/rebuild_closed_positions.py` — Phase 0.0.6 operator tool
- `tests/test_position_grouping.py`, `test_phase0_0_2_*`,
  `test_dedup_fills.py`, `test_phase0_0_4_*`, `test_phase0_0_5_*`,
  `test_rebuild_closed_positions.py` — Phase 0.0 test suites
  (~120 new tests across the phase)
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
- T173-T176 MFE/MAE fixes (sign-clamp + render-together + floor +
  REPLACE-race fix)
- **T182-T191** Phase 0.0 — data quality cleanup primitives + tools
  (this session)

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

The branch is in a clean state for Phase 0.1 to start (with or without
the operator running the Phase 0.0 cleanup tools first).
