# Calc-Linkage System — Implementation Plan

**Status**: design — pending execution
**Created**: 2026-05-24
**Source spec**: [calc_linkage_spec.md](calc_linkage_spec.md) (68 decisions)
**Scope**: phased rollout of the calc-linkage data model, matcher,
event surface, and operator UX described in the spec.

---

## 1. Phasing rationale

Phases are ordered by **dependency** and **leverage** — each phase
delivers user-visible value while only depending on prior phases.
Critical path is **Phase 0.0 → 0 → 1 → 2** (data quality + schema +
matcher + junction); everything else builds on those.

```
Phase 0.0: Data Quality Pre-Work (T178 fixes, position_grouping centralization)
  │
  └─> Phase 0: Foundation (schema-only, no behavior change)
        │
        ├─> Phase 1: Matcher tightening (strict 6/6, audit table)
        │     │
        │     └─> Phase 3: Link status + manual-link tab
        │           │
        │           └─> Phase 8: Operator UX (dashboard, modals, notifications)
        │
        ├─> Phase 2: Position-level attribution (junction-aware lifecycle)
        │     │
        │     ├─> Phase 4: Amendment tracking + deviation
        │     │
        │     ├─> Phase 5: Funding + fees attribution
        │     │
        │     └─> Phase 6: Event bus enrichment + close payload
        │           │
        │           └─> Phase 7: Reverse-query + audit export
        │
        └─> Phase 9: Multi-operator + advanced (independent)
```

Effort tiers: S (≤2 days), M (3-7 days), L (>7 days).

**Phase 0.0 added 2026-05-25** following the T178 findings doc
([docs/audits/2026-05-25-t178-fills-data-quality.md](../audits/2026-05-25-t178-fills-data-quality.md)).
T178 surfaced three layers of corruption in the existing fills /
closed_positions data that would otherwise propagate into Phase 0.11's
`positions_calcs` backfill. Phase 0.0 cleans the source first +
centralizes the "fills → positions" grouping rule in one canonical
helper. Hard prerequisite for Phase 0.11 and Phase 0.12.

---

## Phase 0.0: Data Quality Pre-Work (NEW — added 2026-05-25)

**Goal**: Establish `core/position_grouping.py` as the single source of
truth for "given fills → produce position records". Close the three
data corruption layers identified in T178 BEFORE the junction backfill
(Phase 0.11) or any downstream phase depends on the existing fills /
closed_positions data.

**Dependencies**: none (runs before Phase 0.1).

**Effort**: M-L (5-10 days).

### Why this phase exists

T178 ([docs/audits/2026-05-25-t178-fills-data-quality.md](../audits/2026-05-25-t178-fills-data-quality.md))
found three corruption layers in the existing data:

1. **Synthetic-fill duplication** — `exchange_history_backfill` at
   [db_orders.py:935](../../core/db_orders.py#L935) inserts synthetic
   fills derived from REALIZED_PNL accounting alongside real WS/REST
   fills. ~1.7-2x close-vs-open qty inflation account-wide.
2. **`terminal_position_id` never populated** — the WS path copies it
   from `app_state.positions[*].position_id`, which is only set by
   Quantower's plugin. Without the plugin, all 350 fills carry empty
   pos_id. Cross-checked back to May 14 — never populated, not a
   migration regression.
3. **`get_position_fills` fallback contamination** — when pos_id is
   empty (always, per #2), the SQL falls back to `(symbol, direction)`
   matching, returning ALL historical opens across distinct positions.
   The close-row builder then computes cross-position VWAP entry_price
   + `min(timestamp)` entry_time. Direct cause of operator-visible
   anomalies like BSBUSDT row 22037 showing entry_price 0.771 at
   entry_time 2026-05-19 18:11 when the position actually opened at
   06:10 the next day.
4. **Position-reversal lossiness** — a single fill that crosses zero
   (LONG → SHORT in one event) is recorded as ONE record with
   `is_close=True`. The implicit "open of new direction" is lost.

If the original Phase 0 runs against this data, Phase 0.11's backfill
of `positions_calcs` inherits all four defects into the new junction
table. Phase 0.0 cleans the source first.

### Architectural decision: centralize position grouping

Currently the "fills → position records" logic is duplicated across:
- `order_manager.py:_build_close_row_for_fill` (live close-row builder,
  uses the broken `get_position_fills` fallback)
- `db_orders.py:935+` `exchange_history_backfill` (uses ad-hoc
  `(symbol, direction, open_time)` grouping — Layer 3 in T178)
- (proposed) a one-off rebuild script
- (future) Phase 0.11's positions_calcs backfill

Phase 0.0.1 collapses all of these to a single canonical helper. After
Phase 0.0:
- `core/position_grouping.py` defines `PositionRecord` TypedDict and
  `group_fills_into_positions(fills) -> list[PositionRecord]` as the
  authoritative grouping function.
- All four call sites above call into it.
- Tests for the grouping rule live in one place.
- The chronological-walk algorithm replaces the broken pos_id-based
  fallback and the ad-hoc (symbol, direction, open_time) grouping.

### Synthetic exchange_fill_id convention (reversal-split)

Per operator decision (2026-05-25), reversal-split synthetic fill
records use the prefix convention:

```
Close portion: exchange_fill_id = "{tradeId}"          (original Binance ID)
Open portion:  exchange_fill_id = "synth:{tradeId}:open"  (synthetic)
```

This is:
- **Deterministic** (re-import produces same IDs → idempotent)
- **Visually flagged** (`synth:` prefix unambiguous)
- **Filterable** (`WHERE exchange_fill_id NOT LIKE 'synth:%'` for
  real-Binance-only queries)
- **Aligned** with the existing `bf:` prefix precedent at
  [db_orders.py:954](../../core/db_orders.py#L954)

No schema change required. The existing `UNIQUE(account_id,
exchange_fill_id)` constraint continues to enforce uniqueness across
real + synthetic IDs since the synthetic prefix guarantees no
collision with Binance's numeric tradeIds.

### Fill-dedup tolerance rule

`is_same_fill(a, b)` in `core/position_grouping.py` matches fills by:

```
a.symbol == b.symbol
AND a.side == b.side
AND a.is_close == b.is_close
AND abs(a.timestamp_ms - b.timestamp_ms) <= FILL_DEDUP_TOLERANCE_MS
AND abs(a.price - b.price) / b.price <= FILL_DEDUP_PRICE_TOLERANCE_PCT
AND a.quantity == b.quantity
```

Constants:
- `FILL_DEDUP_TOLERANCE_MS = 2000` (2 seconds — wide enough to catch
  synthetic-vs-real timestamp skew from the dual-write paths;
  T178 found Binance matching-engine splits use IDENTICAL timestamps,
  so 2s won't collapse them)
- `FILL_DEDUP_PRICE_TOLERANCE_PCT = 0.0` (exact — both sources should
  report identical prices since they come from the same trade)

Tunable in code, validated by the dedup script's dry-run output before
operator runs `--apply`.

### Tasks

| # | Task | File(s) | Notes |
|---|---|---|---|
| 0.0.1 | Land `core/position_grouping.py` as canonical helper. `PositionRecord` TypedDict matching `insert_closed_position`'s expected shape. `group_fills_into_positions(fills, fee_rate_fallback=0.0) -> list[PositionRecord]` chronological-walk grouping. `FILL_DEDUP_TOLERANCE_MS` + `FILL_DEDUP_PRICE_TOLERANCE_PCT` constants. `is_same_fill(a, b) -> bool` helper. Tests cover: single position open→close, scale-in (multi-fill open), partial close, full close, hedge mode (LONG+SHORT simultaneously), float-precision qty epsilon. **No production callers yet** — just available + verified. (T177's uncommitted draft is the starting point.) | `core/position_grouping.py` (new), `tests/test_position_grouping.py` (new) | Foundation for all subsequent tasks. |
| 0.0.2 | **Fix 1**: dedup guard in `exchange_history_backfill`. Before each fill insert, query for existing fill matching via `is_same_fill`. Skip insert if found. Refactor the function's closed_positions construction to call `position_grouping.group_fills_into_positions()` (replaces inline `(symbol, direction, open_time)` grouping — T178 Layer 3). | `core/db_orders.py:935-988`, uses `core/position_grouping.py` | Stops new synthetic dups going forward. Existing dups still in table; Fix 2 cleans those. |
| 0.0.3 | **Fix 2**: dedup historical fills script. `scripts/dedup_fills.py` with `--dry-run` (default) and `--apply` modes. Iterates fills chronologically, groups by `is_same_fill` rule, keeps one per group with source priority: `binance_ws` > `binance_rest` > `exchange_history_backfill`. Prints diff in dry-run; deletes in apply. Operator runs against a fresh backup first, reviews, runs against live DB when satisfied. **NOT auto-run on engine startup.** | `scripts/dedup_fills.py` (new), `tests/test_dedup_fills.py` (new) | Destructive on live DB. Operator-controlled. Backup required. |
| 0.0.4 | **Fix 3**: reversal-split. In `position_snapshot.py`, when `qty_before * qty_after < 0` (reversal), return a `FillSnapshot` with `splits` list containing both portions. In `order_manager.py:process_fill`, when snapshot indicates reversal, write TWO fill rows: close-of-old (`exchange_fill_id = "{tradeId}"`, qty = `\|qty_before\|`, direction = old, is_close=True) + open-of-new (`exchange_fill_id = "synth:{tradeId}:open"`, qty = `fill_qty - \|qty_before\|`, direction = new, is_close=False). | `core/position_snapshot.py:108-124` (extend `FillSnapshot` schema), `core/order_manager.py:process_fill` (multi-write path), `core/db_orders.py:upsert_fill_and_update_order` (handle synthetic ID gracefully) | Test fallout expected: existing tests asserting "1 fill per WS event" need updates for reversal scenarios. Document as known impact. UNIQUE constraint unchanged — synthetic ID prefix prevents collision. |
| 0.0.5 | Refactor `_build_close_row_for_fill` in `core/order_manager.py` to call `position_grouping.group_fills_into_positions()` instead of the broken `get_position_fills(symbol, direction)` fallback. Remove the `(COALESCE(terminal_position_id, '') = '' AND symbol=? AND direction=?)` arm from `get_position_fills`'s SQL — make it strict: empty pos_id → returns empty list. | `core/order_manager.py:605-749`, `core/db_orders.py:646-667` | Closes Layer 3 of T178. Even before `lifecycle_id` from Phase 2.1 replaces terminal_position_id, the close-row builder uses grouping rather than the broken fallback. |
| 0.0.6 | One-shot rebuild closed_positions from cleaned fills. `scripts/rebuild_closed_positions.py` with `--dry-run` (default) and `--apply` modes. Uses `position_grouping.group_fills_into_positions()` against the dedup'd fills. Operator-confirmed; backup first; `backfill_completed` reset to 0 on rebuilt rows so reconciler re-runs MFE/MAE with T175's floor in place. | `scripts/rebuild_closed_positions.py` (new — extends T177's draft) | Run AFTER 0.0.3 dedup completes. Destructive. |

### Tests

- `tests/test_position_grouping.py` — `PositionRecord` shape, all
  grouping scenarios (single position, scale-in, partial close, hedge
  mode, qty-epsilon, dedup match rule)
- `tests/test_dedup_fills.py` — dedup match rule, source priority,
  dry-run vs apply, idempotency
- `tests/test_phase0_0_reversal_split.py` — Fix 3 contract: 1 reversal
  event → 2 fill records with correct qty split, directions, synthetic
  ID format
- `tests/test_phase0_0_close_row_grouping.py` — `_build_close_row_for_fill`
  uses `position_grouping`, not the fallback. `get_position_fills`
  returns `[]` when pos_id is empty.

### Acceptance criteria

- `core/position_grouping.py` is the only place that defines "given
  fills → produce position records" (grep verification)
- `exchange_history_backfill` no longer creates synthetic duplicate
  fills (test against synthetic fixture covering the dual-write
  scenario)
- `scripts/dedup_fills.py` produces a usable dry-run output for the
  live DB; operator-confirmed before `--apply` runs
- `scripts/rebuild_closed_positions.py` produces a usable dry-run
  output
- Position reversals produce 2 fill records (close + `synth:...:open`)
  going forward
- `get_position_fills` returns empty when pos_id is empty (no fallback
  contamination)
- Full test suite passes (with documented test updates for reversal
  scenarios — count of changed tests reported)
- Reconciler re-runs against rebuilt closed_positions and produces
  MFE/MAE values consistent with T175's floor invariant

### Rollback plan

If any sub-task introduces unexpected regressions:
- 0.0.1 (helper) — pure additive, no rollback needed; just delete files
- 0.0.2 (dedup guard) — revert the single function change in
  `db_orders.py:935+`
- 0.0.3 (dedup script) — operator restores from backup
- 0.0.4 (reversal-split) — revert `position_snapshot.py` +
  `order_manager.py` changes; synthetic fills already in DB can stay
  (they don't break anything, just sit there)
- 0.0.5 (close-row refactor) — revert; `get_position_fills` fallback
  arm restored; close-row builder back to the broken-but-known-shape
  fallback
- 0.0.6 (rebuild) — operator restores closed_positions from backup

### Then Phase 0.1-0.10 proceed as originally written (schema additions)
### Then Phase 0.11 backfills positions_calcs — NOW against clean fills via `position_grouping`
### Then Phase 0.12 re-maps exit_reason — optionally also re-runs `position_grouping` to fully rebuild closed_positions from clean fills (operator opt-in via flag)

---

## Phase 0: Foundation — schema additions

**Goal**: All new tables and columns exist in DB; no behavior change.
Safe to deploy independently.

**Dependencies**: Phase 0.0 (data quality pre-work).

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 0.1 | Add `positions_calcs` junction table (incl. `lifecycle_id` column + index) | `core/database.py` (migrate), `core/db_orders.py` (CRUD helpers) |
| 0.2 | Add `order_amendments` table (incl. `lifecycle_id` column + index) | `core/database.py`, `core/db_orders.py` |
| 0.3 | Add `funding_events` table (incl. `lifecycle_id` column + index) | `core/database.py`, `core/db_orders.py` |
| 0.4 | Add `calc_match_audit` table | `core/database.py`, `core/db_orders.py` |
| 0.5 | Add `operator_sessions` table | `core/database.py`, `core/auth_state.py` (new) |
| 0.6 | Add columns to `pre_trade_log`: status, window_seconds, account_id, operator_id, superseded_by_calc_id, cancelled_reason, planned_size, overridden_size, planned_tp, overridden_tp, planned_sl, overridden_sl, tp_levels (JSON), filled_pct, tags (JSON), **lifecycle_id** | `core/database.py` |
| 0.7 | Add columns to `orders`: link_status, operator_id, cancel_reason_category, cancel_reason_raw, cancel_ts_ms, **lifecycle_id** | `core/database.py` |
| 0.8 | Add columns to `closed_positions`: exit_reason (re-mapped), close_note, entry_px_delta_pct, size_delta_pct, tp_drift_pct, sl_drift_pct, exit_vs_target_pct, realized_r, planned_r, hold_time_actual_ms, hold_time_planned_ms, cumulative_amendment_count, funding_fees (already exists, repurpose), liquidation_px, bankruptcy_px, insurance_fund_fee, adl_indicator, **lifecycle_id** | `core/database.py` |
| 0.9 | Add `accounts.config_json` column (incl. `entry_tolerance_pct` and `snapshot_drift_tolerance_pct` defaults) | `core/database.py` |
| 0.10 | Create all indexes per spec §3.1 (incl. `lifecycle_id` indexes on every carrying table) | `core/database.py` |
| 0.11 | Migration script: backfill `positions_calcs` from existing `fills WHERE calc_id IS NOT NULL` — uses `core/position_grouping.py::group_fills_into_positions()` from Phase 0.0.1 for the position-lifecycle grouping (chronological-walk, NOT the pre-T178 broken pos_id fallback). `contributed_qty = SUM(fill_qty)` per (position, calc_id) tuple. Back-fill `lifecycle_id` per historical position lifecycle via UUID-v4 at this migration's run-time (forward fills will generate lifecycle_id at first opening fill per Phase 2.1). | `migrations/` (new dir or extend existing) |
| 0.12 | Re-map existing `closed_positions.exit_reason`: `'manual'`→`MANUAL_OTHER`; `'tp'`→`TP_PLANNED`; `'sl'`→`SL_PLANNED`; default to `MANUAL_OTHER` if NULL | same migration script |
| 0.13 | State-machine enforcement helpers: `core/calc_state.py` + `core/link_state.py` with valid-transition dicts + `transition()` choke-point + `IllegalStateTransition` exception (per spec §3.6) | `core/calc_state.py` (new), `core/link_state.py` (new) |

### Tests

- `tests/test_phase0_schema.py`:
  - All tables exist with expected columns + indexes
  - All foreign-key relationships valid (no orphan rows after backfill)
  - `positions_calcs` rows correctly reconstructed from historical fills
    (synthetic golden dataset)
  - `pre_trade_log.status` default = `'active'` for existing rows
  - `orders.link_status` backfilled correctly (LINKED if calc_id present,
    UNPLANNED otherwise)

### Acceptance criteria

- All migrations run idempotently (re-running has no effect)
- All existing tests still pass (no behavior change)
- Backfill report logged: count of junction rows created, count of
  orders re-categorized
- DB size growth measured and documented

### DB-routing note (settled 2026-05-28, T217 audit)

The Phase-0 (and Phase-1) schema additions were applied as Python
`ALTER TABLE` migrations against `config.DB_PATH` (= `risk_engine.db`)
inside `core/database.py::initialize`, NOT as per-account `.sql`
migrations via the migration runner. This is correct for the current
deployment because the entire calc-linkage transactional path is
single-DB on `config.DB_PATH` (see spec §12.7). The per-account DBs
from the v1.3 split carry a vestigial, pre-Phase-0 `pre_trade_log`
that the calc-linkage path never touches.

**If a future phase migrates the transactional path to per-account
routing**, the Phase-0/1 column-adds must first be re-expressed as
per-account `.sql` migrations and dry-run against the live per-account
DB (per the live-DB-dry-run discipline in CLAUDE.md). Until then,
treat `risk_engine.db` as the single source of truth for calc-linkage.

---

## Phase 1: Matcher tightening

**Goal**: Replace existing 3/3 (limit) / 2/2 (market) matcher with
strict 6/6 (both order types). Add per-criterion audit. Per-account window from
`config_json`. Clock-skew tolerance. Calc revision supersede.

**Dependencies**: Phase 0.

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 1.1 | Rewrite matcher to strict-all-or-fall-through | [core/calc_correlation.py](core/calc_correlation.py) — replace `correlate_order_to_calc()` |
| 1.2 | Read `window_seconds` and `clock_skew_tolerance_sec` from `accounts.config_json` per-account | new `core/account_config.py` helper |
| 1.3 | Freeze `window_seconds` onto `pre_trade_log.window_seconds` at calc creation | [core/handlers.py:182-260](core/handlers.py#L182-L260) `handle_risk_calculated()` |
| 1.4 | Write per-criterion `calc_match_audit` rows for every match attempt (winning + losing candidates) | `core/calc_correlation.py` + `core/db_orders.py` |
| 1.5 | Implement calc-revision detection on Calculate: if existing `active` calc for (account, ticker, direction) exists, set `status='superseded'`, `superseded_by_calc_id`, emit `calc:superseded` event | `core/handlers.py` |
| 1.6 | Implement calc-cancel-by-operator endpoint + status transition | `api/routes_calculator.py`, `core/handlers.py` |
| 1.7 | Implement calc-released state after order cancel: when order's `cancel_reason_category='OPERATOR'`, set linked calc's status back to `released` (within original window) | [core/order_manager.py](core/order_manager.py) (cancel-path handler) |
| 1.8 | Implement calc auto-complete on position close: when position closes, transition all contributing calcs to `completed_via_position` + emit `calc:completed` | `core/order_manager.py:_build_close_row_for_fill()` |
| 1.9 | Implement entry-tolerance band separate from tick-size (default 0.25% via config) | `core/calc_correlation.py` |
| 1.10 | Allow nullable TP/SL on calc; if either is null, auto-route to manual-link (link_status=NEEDS_MANUAL_REVIEW regardless of other criteria) | `core/calc_correlation.py` |

### Tests

- `tests/test_phase1_matcher.py`:
  - Strict 6/6 limit (entry vs limit px): missing 1 criterion → NEEDS_MANUAL_REVIEW
  - Strict 6/6 market (entry vs fill px): missing 1 criterion → NEEDS_MANUAL_REVIEW
  - Full match: LINKED + audit row per criterion
  - Window frozen: config change after calc creation does not affect
    in-flight calc expiry
  - Clock-skew: ±tolerance padding works at window boundary
  - Calc revision: 2nd calc for same (symbol, direction) marks 1st as
    superseded + emits event
  - Calc cancel: status transition + event emitted
  - Order cancel released calc: re-match eligible for replacement
  - Calc auto-complete on position close: status + event
  - Nullable TP or SL: routes to manual-link

### Acceptance criteria

- All Phase 0 tests still pass ✓ (2639 pass, 7 skip, 1 unrelated
  pre-existing rolling-window failure).
- ~~No silent regression in match success rate (golden-dataset
  before/after link-rate comparison)~~ — **NOT performed** (T225
  reframe). A golden-dataset comparison was not feasible retroactively:
  the old 3/3-limit / 2/2-market matcher was fully replaced in T210
  (no "before" to diff against on the same dataset), and the new strict
  contract is *intentionally* stricter (fewer auto-links, more
  manual-review), so a raw link-rate drop is expected, not a regression.
  Verification instead rests on the per-criterion matcher tests
  (test_phase1_matcher.py) + the lifecycle e2e (below). Revisit with a
  forward link-rate dashboard once live data accumulates under the new
  matcher.
- Per-criterion audit rows present for **every order arrival that has
  ≥1 in-window candidate** (T225 reframe — was "100% of order
  arrivals"). Two paths legitimately produce zero audit rows by design:
  (a) zero in-window candidates → UNPLANNED (nothing to audit); (b) an
  order lacking both TP/SL trigger prices is gated out of the matcher
  (order_enrichment `_try_correlate`) before any candidate scan. The
  audit model is per-candidate (spec §4.3), not per-order.
- Calc state machine transitions verified end-to-end (T225): a calc is
  driven through each live transition via the REAL handlers — created
  (handle_risk_calculated), matched (matcher), released
  (_release_calc_on_operator_cancel), cancelled (cancel_calc_by_operator),
  completed (_build_close_row_for_fill), superseded (recalc), expired
  (sweep_expired_calcs) — with pre_trade_log.status asserted at each
  step (tests/test_phase1_lifecycle_e2e.py). Per-transition unit tests
  cover the edge cases.

### Acceptance-criteria addendum (T224 / T225)

- **Live expiry**: window-lapsed active|released calcs are transitioned
  to `expired` by a periodic sweeper (core/handlers.sweep_expired_calcs
  + schedulers._calc_expiry_loop) so calc:expired fires live and the
  candidate set stays bounded. (Was a holistic-audit gap H1/H2/L2;
  closed in T224.) The full §12.3 restart-rehydrate expiry + multi-
  account sweep remain later-phase refinements.

---

## Phase 2: Position-level attribution

**Goal**: Junction-aware position lifecycle. `PositionInfo.calc_id`
populated. Scale-in append-to-junction. Closing fills stamped.
Deltas computed at close.

**Dependencies**: Phase 0, Phase 1.

**Effort**: L (touches the hottest path in the engine).

### Tasks

| # | Task | File(s) |
|---|---|---|
| 2.1 | On every opening fill, insert/update `positions_calcs` row (single row per order, `contributed_qty` updated on each fill). **At first fill that opens a new position, generate UUID `lifecycle_id`** and back-fill onto matched `pre_trade_log.lifecycle_id`, `orders.lifecycle_id`, and the junction row. Scale-in calcs inherit the position's existing `lifecycle_id`. | [core/order_manager.py](core/order_manager.py) `process_fill()` |
| 2.2 | Stamp `calc_id` AND `lifecycle_id` on every closing fill (both inherited from position's primary) | `core/order_manager.py` close-side fill handler |
| 2.3 | Add `calc_id` field to `PositionInfo`; populate from junction on first fill + on rehydrate | [core/state.py:115-160](core/state.py#L115-L160), `core/exchange.py:350` |
| 2.4 | Scale-in path: if new calc fires while position open and resulting fill arrives, append to junction with new calc_id; per-calc planned_tp/sl/size copied from calc at contribution time | `core/order_manager.py` |
| 2.5 | At position close, compute deltas against the most-contributing calc (largest `contributed_qty` in junction; tie-break first-entry — spec §3.2). **SHIPPED (T233)**: the 6 deltas fully derivable from data available at close — `entry_px_delta_pct`, `size_delta_pct`, `exit_vs_target_pct`, `realized_r`, `planned_r`, `hold_time_actual_ms` — computed in `_compute_close_deltas`, persisted via `insert_closed_position` (+ REPLACE-preserve). Planned size/TP/SL from the primary's junction snapshot (T2.4); planned_entry from `pre_trade_log.effective_entry`; deltas stored raw/signed (realized_r is direction-agnostic). **DEFERRED** (operator-approved, T233): `tp_drift_pct`/`sl_drift_pct` → P4.6 (need final AMENDED TP/SL from amendment tracking; close order exposes only the triggered level); `cumulative_amendment_count` → P4.3 (`order_amendments` unwired today, a `0` would misread as "no amendments"); `hold_time_planned_ms` → no planned-duration source in any schema. | `core/order_manager.py:_build_close_row_for_fill()` |
| 2.6 | **SHIPPED (T234)**: `closed_positions.calc_id` = most-contributing junction calc (`_position_primary_calc`; largest contributed_qty, tie-break first-entry) and `closed_positions.lifecycle_id` sealed from the junction (spec §3.5). Falls back to the Phase-1 "earliest opening fill with a calc_id" rule (calc_id only; lifecycle NULL) when the position has no junction (UNPLANNED / binance empty-tpid). **R1 CLOSED**: the closed row now agrees with `fills.calc_id` (T2.2), `PositionInfo.calc_id` (T2.3), and the T2.5 delta basis — all four surfaces converge on the most-contributing calc (verified e2e: scale-in calc-A qty3 first + calc-B qty7 → all = calc-B, lifecycle sealed). `insert_closed_position` already REPLACE-preserves both columns (T232). | `core/order_manager.py:_build_close_row_for_fill()` |
| 2.7 | **SHIPPED (T235)**: forward close path emits the spec §3.4 `exit_reason` ENUM (was legacy tp_hit/sl_hit/manual/limit_close/trailing_stop), aligning new rows with the §3.4 values the P0.T5 backfill applied to historical rows. Mapping (mirrors the backfill): take_profit→`TP_PLANNED`, stop/stop_loss/trailing→`SL_PLANNED`, market/limit/none/not-found→`MANUAL_OTHER`. Fills-only rebuild (`position_grouping`) → `MANUAL_OTHER`. History template maps the enum to family badge LABELS (TP/SL/Manual/Liq/Exp/Mixed), replacing the raw-enum-string fallthrough; it applies the same color-hook classes (badge-green/red/gray/yellow) the legacy badges used — those are undefined in base CSS app-wide, so the label is the functional win, not the tint. Keeps legacy fallbacks. **DEFERRED to Phase 4** (forced; continues the operator-approved T2.5 final-TP/SL deferral): the `*_AMENDED` distinction — spec keys it on `cumulative_amendment_count > 0` (P4.3, populated by the unwired P4.1 ws_manager amendment writer) AND a plan-vs-final-TP/SL difference (P4.6); the close order exposes only the single triggered level, so a now-comparison is semantically wrong (false positives both ways). AMENDED becomes a Phase-4 re-classification on the idempotent close-row rebuild seam. **Deviations**: trailing→SL_PLANNED (no §3.4 trailing variant); limit_close→MANUAL_OTHER; LIQUIDATION/ADL/EXPIRED/MANUAL_* subtypes/TP_LADDER/MIXED need other phases (venue status signals / multi-TP P2.11 / operator note) and route to the closest available enum. | `core/order_manager.py` |
| 2.8 | **SHIPPED (T236)**: TP/SL bracket detection — venue-agnostic engine [core/bracket_detection.py](core/bracket_detection.py) (`detect_brackets`: two-tier — venue-native shared-link → `(symbol, position_side)` + 2s time-window; a bracket requires ≥1 entry + ≥1 protective leg, entry/protective by `order_type`) + a thin per-adapter `detect_bracket()` on **Binance** (no shared id → positionSide+window), **Bybit** (`orderLinkId` via `client_order_id`, Beta), and **MEXC** (no shared id / no positionSide → symbol+window). **DETECT ONLY** — no calc_id writes (T2.9). **OKX dropped** (no adapter exists); **MT4/MT5 (forex) brokers forward-looking** (out of scope). Detection on live Binance is necessarily a heuristic (`exchange_position_id` is empty on the observe-only path, clientOrderId is unique per order), bounded by T2.9 only propagating from an entry that carries a calc_id. | [core/bracket_detection.py](core/bracket_detection.py), [core/adapters/binance/rest_adapter.py](core/adapters/binance/rest_adapter.py), [core/adapters/bybit/rest_adapter.py](core/adapters/bybit/rest_adapter.py), [core/adapters/mexc/rest_adapter.py](core/adapters/mexc/rest_adapter.py) |
| 2.9 | **SHIPPED (T237)**: TP/SL inheritance from entry — `OrderManager._propagate_bracket_calc_id` consumes the T2.8 detection primitive (`adapter.detect_bracket`, venue-agnostic fallback `link_field=None` when no active adapter), and for each detected bracket whose ENTRY leg carries a `calc_id` (matcher-linked, spec §4.1) stamps that `calc_id` + `link_status='LINKED'` onto every protective leg whose `calc_id` is still NULL. Wired into all three arrival handlers: `process_order_update` (WS, per arriving symbol, after enrichment), `process_order_snapshot` + `process_algo_snapshot` (REST reconciliation, per distinct batch symbol — Binance TP/SL conditionals arrive on the algo path while the entry arrives on the basic path; both already persisted so detection reads them together). Idempotent (`WHERE calc_id IS NULL`); best-effort; cheap pre-checks short-circuit. This is the ONLY path a TP/SL order ROW gets a `calc_id` (the strict matcher returns early for reduce-only/close-types). Bounded: only a calc-bearing entry propagates, so a mis-grouped window cluster cannot fabricate a link (worst case: TP/SL sharing a window with an UNPLANNED entry stays NULL → standard matcher, spec §4.5). `upsert_order_batch` uses `ON CONFLICT DO UPDATE` excluding `calc_id`/`link_status`, so inherited values survive later order updates (no REPLACE-wipe). **Deviations**: (a) propagates `calc_id` + `link_status` only, NOT `lifecycle_id` — the entry's lifecycle is minted at its first opening FILL (T2.1) which commonly hasn't happened when the protective leg arrives, so a COALESCE would write NULL in the common case and the idempotency guard would never revisit it (half-correct partial); protective-order lifecycle stamping stays a known gap (same as T2.1, which stamps only the entry order). (b) RAW `UPDATE orders SET link_status` matching the matcher's NULL→LINKED initial-arrival set — explicitly NOT routed through `link_state.transition` (link_state.py:53; the choke-point validates current→target between existing enum values, a NULL current would raise). P3.T1 sweeps both sites onto the choke-point together. | [core/order_manager.py](core/order_manager.py) `_propagate_bracket_calc_id` + the three arrival handlers |
| 2.10 | ~~Standalone TP/SL auto-inherit~~ — REMOVED per Q19/Q54 unification (spec §15 R2). All standalone TP/SL goes through the standard matcher (Phase 1); 6/6 match → auto-link, else manual-link tab. No special-case logic needed in `core/order_manager.py`. | (no file changes; behavior covered by Phase 1) |
| 2.11 | **SHIPPED (T238)**: Multi-TP partial-close lifecycle. **Operator-confirmed model = per-partial closed_positions rows PRESERVED** (one row per closing order, as before — NOT consolidated to one row/position; that was the explicit fork, Option A chosen). T2.11 adds on top: (1) **calc completion deferred to the FINAL close** (size→0) — pre-T2.11 `_complete_calcs_on_close` ran on every close-row build, completing the calc prematurely on the first partial; now gated on `is_final`. Final-close is **data-derived from fills** (Σ closing qty ≥ Σ opening qty — deterministic, NOT the racy ACCOUNT_UPDATE snapshot), with `force_final=True` from the position-disappearance safety net (`build_final_close_row`). (2) **Ladder-aware FINAL exit_reason** (`_classify_final_exit_reason`): `TP_LADDER_COMPLETE` (≥2 distinct TP closing orders, no SL/manual) or `MIXED` (≥1 TP + ≥1 SL/manual close); non-final partial rows + single-close + all-SL keep their per-order `_determine_exit_reason` value. (3) **Enriched `partial_close` trade event** payload (position_id, qty_reduced, remaining_qty, realized_pnl_partial — spec §8/§9). **Deviations**: per-partial rows kept (Option A); single full close is `is_final` immediately so the common case is unchanged; empty-tpid (binance one-way) / missing-opens → `is_final=True` fallback (preserves pre-T2.11 complete-on-close) + ladder classify falls back to per-order reason (no per-position fill sum possible). `tp_level_idx` omitted from the event (needs calc.tp_levels parse + price match — deferred, not load-bearing). | [core/order_manager.py](core/order_manager.py) `_build_close_row_for_fill`, `_classify_final_exit_reason`, `_complete_calcs_on_close`, `_emit_fill_events` |
| 2.12 | **SHIPPED (T240)**: Restart rehydrate — for each open position, populate `calc_id` (primary) + `contributing_calc_ids` (all junction calcs, primary-first then contributed_qty desc) + `size_delta_pct` (live size deviation) from `positions_calcs`. **Implementation deviation (better than the stated files)**: T2.3's `_enrich_positions_calc_id` already runs at startup (`_startup_fetch` → `process_order_snapshot` → `refresh_cache`) and authoritatively re-derives `calc_id` from the persisted junction — so rehydrate was already covered for calc_id. T2.12 EXTENDS that one method (instead of a separate `core/exchange.py` / startup hook, which would duplicate it and risk divergence) to also populate the two new `PositionInfo` fields. All three are authoritative (mirror the junction each refresh; CLEARED when no junction) + added to `DataCache._PRESERVE_FIELDS` (survive snapshot rebuilds like `calc_id`). `size_delta_pct` = `(Σ contributed_qty − primary calc's planned_size)/planned_size × 100` (signed, spec §3.2 most-contributing basis, mirrors T2.5 close-time size_delta); 0.0 when no junction/planned_size. **Deferred (Phase 4.4)**: the yellow/red deviation BADGE thresholding + TP/SL live deviation (need the order-amendment tracking that isn't wired yet). | [core/state.py](core/state.py) `PositionInfo`, [core/data_cache.py](core/data_cache.py) `_PRESERVE_FIELDS`, [core/order_manager.py](core/order_manager.py) `_enrich_positions_calc_id` |

### Tests

- `tests/test_phase2_junction.py`:
  - Single-fill position: junction row written; PositionInfo.calc_id set
  - Multi-fill same order: junction row updated cumulatively
  - Scale-in: 2nd calc appends new junction row; PositionInfo carries both
  - Closing fill: calc_id stamped from position primary
  - Deltas computed correctly at close (synthetic plan vs actual)
  - exit_reason classification: TP_PLANNED vs TP_AMENDED based on amendments
  - Bracket detection: Bybit link_id, Binance positionSide cluster, fallback time-window
  - Standalone TP/SL: auto-inherits position calc on existing position
  - Multi-TP: 3 TP fills → 3 partial_close events + final TP_LADDER_COMPLETE
  - Restart: junction rehydrates PositionInfo.calc_id correctly

### Acceptance criteria

- Junction populated for 100% of new fills post-deployment
- Closed_positions deltas non-null for all positions opened after Phase 2 deploy
- `closed_positions.calc_id` (most-contributing) + `closed_positions.lifecycle_id`
  set on all positions closed after P2.T6, and CONSISTENT with the
  position's `fills.calc_id`/`PositionInfo.calc_id` (R1 closed)
- All existing position-close tests still pass
- Restart with 5+ open positions correctly rehydrates calc attribution

---

## Phase 3: Link status + manual-link tab

**Goal**: Order `link_status` enum drives UI. Operator can manually
link via side-by-side diff panel. UNPLANNED auto-classification.

**Dependencies**: Phase 0, Phase 1.

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 3.1 | **SHIPPED (T241, P3.T1)**: route EVERY `orders.link_status` write through the `core/link_state` choke-point (spec §3.6 — no raw UPDATEs). Added `auto_classify()`, the ENGINE-classification sibling of `transition()`: the matcher assigns link_status from an UNDECIDED source (NULL on first arrival, or UNPLANNED on a re-run — an UNPLANNED→LINKED re-match upgrade is one `transition()` correctly rejects, since UNPLANNED is operator-terminal). Swept BOTH raw-UPDATE sites onto it — the matcher (`order_enrichment._try_correlate`) and bracket inheritance (`order_manager._propagate_bracket_calc_id`). `transition()` (validated decided→decided moves) is reserved for the operator endpoints (P3.T2/T3). The link_status set-on-arrival itself predates this (Phase-1 matcher). 14 tests in `tests/test_phase3_link_state.py`, incl. the load-bearing UNPLANNED→LINKED upgrade. | `core/link_state.py`, `core/order_enrichment.py`, `core/order_manager.py` |
| 3.2 | **SATISFIED (pre-existing matcher)**: the strict matcher already sets `link_status=UNPLANNED` when zero in-window candidates exist (verified by `test_phase3_link_state.test_no_candidate_routes_unplanned`). Residual gap (deferred): the order-side TP/SL early-return (`_try_correlate` returns before the matcher if the order lacks both trigger prices) — a no-TP/SL order never reaches the matcher to be classified. | `core/calc_correlation.py` |
| 3.3 | **SHIPPED (T242, P3.T2)**: `POST /orders/{id}/manual_link` (Form `calc_id`) → `core.link_actions.manual_link_order`: routes the order NEEDS_MANUAL_REVIEW\|UNLINKED → LINKED through the `link_state` choke-point (TOCTOU-guarded), flips the calc active\|released → matched (mirrors the auto-matcher), propagates calc_id to opening fills. 200 + discriminated HTML alert. | `api/routes_orders.py`, `core/link_actions.py` (new) |
| 3.4 | **SHIPPED (T242, P3.T2)**: `POST /orders/{id}/mark_unplanned` → `mark_order_unplanned`: NEEDS_MANUAL_REVIEW\|UNLINKED → UNPLANNED through the choke-point. Added `LinkTransitionRaceLost` (mirror of `CalcTransitionRaceLost`). | `api/routes_orders.py`, `core/link_actions.py`, `core/link_state.py` |
| 3.5 | **SHIPPED (T242, P3.T2)**: `GET /orders/needs_review` → `list_needs_review`: NEEDS_MANUAL_REVIEW + UNLINKED orders, each annotated with `find_candidate_calcs` per-criterion diff. Returns JSON (the data layer; P3.T3 renders it). | `api/routes_orders.py`, `core/link_actions.py` |
| 3.6 | **SHIPPED (T242, P3.T3)**: needs-link TAB — `templates/orders/needs_link.html` (page, lazy-loads the queue) + `templates/fragments/needs_link_queue.html` (Card-per-order, StatusIndicator badge, per-criterion diff via text-green/text-red, Link + Mark-UNPLANNED buttons → the choke-pointed P3.T2 endpoints). New routes `GET /orders/needs_link` + `GET /fragments/needs_link`; nav tab + page_meta in base.html (nav label humanized `\|capitalize`→`\|replace('_',' ')\|title`). Auto-refresh script inlined per the codebase page-script convention (deviation from `static/js/needs_link.js`). 10 compile-render wiring tests. | `templates/orders/needs_link.html` (new), `templates/fragments/needs_link_queue.html` (new), `api/routes_orders.py`, `templates/base.html` |
| 3.7 | **SHIPPED (T243, P3.T4)**: per-order link_status badge in the order tables (order_history + open_orders). New shared macro `templates/primitives/link_status_badge.html` (LINKED→green / NEEDS_MANUAL_REVIEW→yellow / UNLINKED→gray / UNPLANNED→blue; NULL→"—"). **Defined the missing `badge-green/red/gray/yellow/blue` family in base.html** (operator-approved Option A) — the link badge uses it AND it retroactively colors the existing status/exit_reason badges app-wide (closes the T235 gap). Deviation: CSS lives in base.html (codebase convention) not `static/css/badges.css`. | `templates/primitives/link_status_badge.html` (new), `templates/fragments/history/order_history_table.html`, `templates/fragments/history/open_orders_table.html`, `templates/base.html` |
| 3.8 | **SHIPPED (T243, P3.T4)**: live nav badge counter on the Needs-Link tab. `db.count_needs_link(account_id)` (cheap COUNT of NEEDS_MANUAL_REVIEW + UNLINKED) → `GET /fragments/needs_link_count` (amber badge, or empty when the queue is clear) → a nav `<span>` polling `load, every 5s`. Chose the htmx live-fragment (ws_status pattern) over a `_ctx` sync COUNT (avoids a per-render DB hit / MED-005). | `core/db_orders.py`, `api/routes_orders.py`, `templates/base.html` |

### Tests

- `tests/test_phase3_link_status.py`:
  - Order with full match → LINKED
  - Order with partial match → NEEDS_MANUAL_REVIEW; appears in /needs_review
  - Order with no candidates → UNPLANNED automatically
  - Operator manual-link transitions NEEDS_REVIEW → LINKED
  - Operator mark-unplanned transitions UNLINKED → UNPLANNED
  - Diff panel renders correct per-criterion matches/misses

### Acceptance criteria

- 100% of orders have non-null link_status post-deployment
- Manual-link UI usable end-to-end by operator (smoke test)
- Badge counter accurate; updates on link/dismiss actions

---

## Phase 4: Amendment tracking + deviation

**Goal**: Every TP/SL/entry/size amendment writes a row. Deviation
flags drive live position badges.

**Dependencies**: Phase 0, Phase 2.

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 4.1 | **SHIPPED (P4.T1, 2026-06-02)**: `OrderManager.detect_and_persist_amendment` writes an `order_amendments` row per changed working-order field (`entry_price`/`tp_price`/`sl_price`/`size`), invoked from `ws_manager._apply_order_update` **before** `process_order_update`. **Pre-gate placement is load-bearing**: an amendment arrives as a `new→new` self-transition, which the SR-1 `validate_transition` gate rejects (no self-edges — order_state.py / test_order_manager.py:121), so a post-gate hook would never see it. **Baseline (`old_value`) chains off the most recent prior amendment's `new_value`**, falling back to the stored order row — the orders row goes stale (the gate rejects the amend upsert), so the amendment ledger is the authoritative chain. **Deviations**: (a) `leverage` (spec §3.2 field) is account/position-level, not on a per-order WS update → not detectable, documented gap; (b) WS path only — REST reconciliation (`process_order_snapshot/algo`) amendments deferred (separate batch path, needs a dedup key since order_amendments is immutable-insert); (c) the existing `_detect_modification_events` is dead in production for the SAME gate reason — filed as a separate follow-up (HANDOFF). **Post-audit hardening**: `*_entry` stop/TP ENTRY orders (FE-13 suffix) read `stop_price` under the `entry_price` label — else a stop-market entry's trigger amendment silently drops (price==0; audit CORR-001/HIGH); `trailing_stop` excluded (venue-automatic, not an operator amendment); detection also wired into `_apply_algo_update` (defensive — no-op under Binance cancel-replace, but the engine observes Quantower). Tests: `tests/test_phase4_amendments.py` (24). | [core/order_manager.py](core/order_manager.py) `detect_and_persist_amendment`, [core/ws_manager.py](core/ws_manager.py) `_apply_order_update` |
| 4.2 | Compute `deviation_pct` per amendment row: `(new - old) / old * 100`. **Done in P4.T1** (the insert path computes it inline — trivial one-liner, avoids a NULL backfill); P4.T2 remainder is the `cumulative_amendment_count` rollup at close (row 4.3). | `core/db_orders.py` |
| 4.3 | **SHIPPED (P4.T2, 2026-06-02)**: `closed_positions.cumulative_amendment_count` computed at close in `_build_close_row_for_fill` via `db.count_amendments_for_calcs(contributing_calc_ids)` — counts `order_amendments` rows by the position's contributing calc_ids (entry legs carry the matcher calc_id, protective TP/SL legs the T2.9-inherited calc_id, both denormalized onto the amendment row). Added to `_CLOSED_POS_DELTA_COLS` so a non-computing REPLACE (backfill/rebuild) can't wipe a live-built count (T176/T232 pattern); nullable column → backfilled historical rows stay NULL. Recomputed on every close-row build (like the T2.5 deltas), so multi-TP partial rows carry the as-of count and the final row the total. Tests: `tests/test_phase4_amendment_rollup.py` (10) + updated the T2.5 deferred-column assertion (test_phase2_junction). | `core/order_manager.py:_build_close_row_for_fill()`, `core/db_orders.py` `count_amendments_for_calcs` + `insert_closed_position` |
| 4.4 | **SHIPPED (P4.T3, 2026-06-02)**: combined live deviation badge (spec §10.2 semantic ∪ §4.4 thresholds — operator-chosen). `core.state.deviation_badge_level` (pure): red = no-calc (UNPLANNED) OR \|size_delta_pct\| ≥ red_pct; yellow = amended (live amendment count > 0) OR \|size_delta_pct\| ≥ yellow_pct; green = linked/on-plan/no-amendments. `amendment_count` + `deviation_badge` stamped onto each `PositionInfo` in `_enrich_positions_calc_id` (ONE grouped `count_amendments_by_calcs` query + a single `read_account_config_async` per refresh — NO per-render DB hit), preserved via `DataCache._PRESERVE_FIELDS` like `size_delta_pct`. Rendered inline in the live positions row via the new `templates/primitives/deviation_badge.html` macro. **Deviation**: live TP/SL-vs-planned drift deferred — the badge uses the size-deviation magnitude (the live delta T2.12 already stores); TP/SL drift needs `planned_tp/sl` surfaced onto PositionInfo (follow-up). **Independent audit: 1 MED fixed** — thresholds now DEFAULT to the spec values (and config is read first), so a transient amendments-query failure can't strand `red_pct=0.0` (which would paint every linked position red); everything else (XSS/escaping, SQL params, hot-path, preserve-fields) verified clean. Tests: `tests/test_phase4_deviation_badge.py` (18). | `core/state.py`, `core/order_manager.py` `_enrich_positions_calc_id`, `core/db_orders.py`, `core/data_cache.py`, `templates/primitives/deviation_badge.html` |
| 4.5 | **SHIPPED (P4.T4, 2026-06-02)**: emit `position:amended` on each persisted `order_amendments` row, as a **trade event** (`log_trade_event` → `"position_amended"`, registered in `TradeEventType`) — same trade-event-now / event_bus-later split as `partial_close`/`position_opened` (the formal §9 in-process `event_bus` topic stays Phase 6, row 6.4). New sync helper `OrderManager._emit_amendment_event` (sibling of `_emit_fill_events`) called from **inside** `detect_and_persist_amendment`'s detection loop — NOT the ws_manager seam: the per-row `field`/`old`/`new` only exist there, it mirrors the `_emit_fill_events` convention, and it avoids double-emitting across both `_apply_order_update` + `_apply_algo_update`. `insert_order_amendment` now returns `bool`; the event fires **1:1 on a confirmed commit** (a swallowed insert → no event, keeping the "events = row count" parity). Payload = exact §9 keys (`position_id`/`order_id`/`field`/`old`/`new`/`ts`/`operator_id`); `position_id` from the stored order's `terminal_position_id` (`""` pre-fill), `operator_id` None (Phase 9). Completeness sweep: `position_amended` added to both `TradeEventType` mirror dropdowns (`templates/fragments/history/trade_events_table.html`, `templates/admin/trade_events.html`). **Independent audit (6 agents): 1 HIGH confirmed + fixed** — the sync `log_trade_event` (own sqlite3 conn) on the WS hot path is dispatched via `asyncio.to_thread` (T212/P3.T2 convention; safe — never touches the aiosqlite `_conn`); deviation from the initial sync-mirror-of-`_emit_fill_events` choice, which predates that convention (same exposure, filed as a consistency cleanup, not retrofitted — Rule 3). Tests: `tests/test_phase4_amendments.py` 31 (was 24; +7 `TestPositionAmendedEvent`) + autouse `log_trade_event` capture fixture (shields all tests from live-DB writes; verified 0 live `position_amended` after the full suite). | `core/order_manager.py` `_emit_amendment_event`, `core/db_orders.py` `insert_order_amendment`, `core/trade_event_log.py` |
| 4.6 | Populate `tp_drift_pct` and `sl_drift_pct` on closed_positions: drift = final TP/SL vs first calc's planned values | `core/order_manager.py:_build_close_row_for_fill()` |

### Tests

- `tests/test_phase4_amendments.py`:
  - Single TP modification writes row with correct deviation_pct
  - Multiple amendments on same order: all rows present, ordered by ts
  - Entry-price amendment before fill: link preserved, row written
  - SL amendment after position open: row + position:amended event
  - Deviation badge thresholds: 4% drift = green, 7% = yellow, 20% = red
  - Closed_positions.cumulative_amendment_count correct

### Acceptance criteria

- 100% of amendments captured (parity test: WS amendment events =
  `order_amendments` row count)
- Live deviation badge renders correctly for in-flight positions
- Drift columns populated on close for amended-stop positions

---

## Phase 5: Funding + fees attribution

**Goal**: Funding events written per-event; fees aggregated at close;
realized PnL includes funding.

**Dependencies**: Phase 0, Phase 2.

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 5.1 | Subscribe to venue income/funding WS stream per adapter | [core/adapters/binance/](core/adapters/binance/) + [core/adapters/bybit/](core/adapters/bybit/) WS handlers |
| 5.2 | On funding event arrival: look up active position for (account, symbol); if found, write `funding_events` row with (position_id, calc_id=primary, amount, mark_price, funding_rate, ts, venue_event_id) | new `core/funding_handler.py` |
| 5.3 | Deduplication on `venue_event_id` (idempotent in case of WS replay) | `core/funding_handler.py` |
| 5.4 | At position close, populate `closed_positions.funding_fees = SUM(funding_events.amount WHERE position_id=...)` | `core/order_manager.py:_build_close_row_for_fill()` |
| 5.5 | Recompute `closed_positions.net_pnl` = realized_pnl - total_fees + funding_fees | `core/order_manager.py:_build_close_row_for_fill()` |
| 5.6 | Per-fill fee already exists on `fills.fee`; ensure `closed_positions.total_fees = SUM(fills.fee)` is correctly populated (currently may be partial) | `core/order_manager.py:587` (refresh) |
| 5.7 | Live unrealized funding view: helper that returns `SUM(funding_events.amount)` for an open position; surface in position detail UI | `core/state.py`, position detail template |

### Tests

- `tests/test_phase5_funding.py`:
  - Funding event during open position: row written; linked to correct position_id
  - Multiple funding events: SUM correct at close
  - Duplicate venue_event_id ignored
  - Closed position has non-null funding_fees if any events accrued
  - net_pnl includes funding adjustment
  - Live unrealized funding helper returns correct sum

### Acceptance criteria

- 100% of venue funding events post-deployment attributed to a position
  (with optional "orphan funding" log for events without an open
  position — should be rare)
- Reconciliation against venue settlement statements: closed_position
  funding_fees within $0.01 of venue's per-position funding total

---

## Phase 6: Event bus enrichment + close payload

**Goal**: Hierarchical per-account event topics. Full close payload.
All new events from Phases 1-5 actually emitted.

**Dependencies**: Phases 1, 2, 4, 5.

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 6.1 | Wrap existing `event_bus.publish` to construct topic strings: `engine:account:{account_id}:{domain}:{event}` | [core/event_bus.py](core/event_bus.py) (or wherever event_bus lives) |
| 6.2 | Emit all calc:* events from Phase 1 (created, linked, superseded, expired, cancelled, completed, partially_filled, size_deviated, order_cancelled) | per Phase 1 task list |
| 6.3 | Emit all position:* events from Phase 2 (opened, scale_in, partial_close, closed, liquidated, size_drift) | per Phase 2 |
| 6.4 | Emit position:amended from Phase 4 — the **trade-event** trigger shipped in P4.T4 (`_emit_amendment_event`); Phase 6 catalogues the formal in-process `event_bus` topic `engine:account:{id}:position:amended` (payload already matches §9) and publishes it from the same seam | per Phase 4 / `core/order_manager.py` |
| 6.5 | Emit order:duplicate_detected when matcher sees 2+ near-identical orders within N ms window | new in `core/order_manager.py` order-arrival path |
| 6.6 | Position:closed payload expansion: replace anemic current payload at [core/order_manager.py:728-731](core/order_manager.py#L728-L731) with full payload per spec §9 (calc_ids, model_names, deltas, exit_reason, MFE/MAE, funding_fees, etc.) | `core/order_manager.py` |
| 6.7 | Position:liquidated dedicated event with liquidation-specific fields | `core/order_manager.py` close path when exit_reason=LIQUIDATION |
| 6.8 | Position:size_drift event when snapshot disagrees with fill-derived size beyond tolerance. **Read `snapshot_drift_tolerance_pct` from `accounts.config_json` (default 0.5%) — event fires only when delta exceeds tolerance**. Feature-flag the inversion behind `config_json.feature_flags.snapshot_wins_drift` so it can be reverted per-account without code change. | [core/data_cache.py:159-194](core/data_cache.py#L159-L194) — INVERT the WS-fills-win-within-5s policy to snapshot-wins-with-drift-event |

### Tests

- `tests/test_phase6_events.py`:
  - Each event type fires with correct topic and payload shape
  - position:closed payload includes all spec §9 fields
  - position:size_drift fires when synthetic snapshot disagrees
  - duplicate_detected fires for near-identical orders within window

### Acceptance criteria

- Subscriber test harness can consume all event types end-to-end
- Position:closed payload schema validated against spec
- No regression in existing event consumers (existing subscribers may
  need shape-compatibility shims if they assumed the old anemic shape)

---

## Phase 7: Reverse-query + audit export

**Goal**: External model can fetch full causal chain for any calc or
position. Audit export for compliance.

**Dependencies**: Phases 2, 4, 5, 6.

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 7.1 | New endpoint `GET /context/calc/{calc_id}` returning full graph payload per spec §11.1 | new `api/routes_context.py` |
| 7.2 | New endpoint `GET /context/position/{position_id}` returning full graph keyed on position | `api/routes_context.py` |
| 7.3 | Pagination + caching for endpoints if response > N KB (likely needed for multi-day positions with many amendments + funding events) | same |
| 7.4 | Position-closed webhook: single configured URL per account in `config_json.webhook_url`; engine POSTs `{event: position_closed, payload: <full §9>}` on every close | new `core/webhook_dispatcher.py` |
| 7.5 | Webhook retry with exponential backoff + dead-letter queue | `core/webhook_dispatcher.py` |
| 7.6 | New endpoint `POST /export/closed_position/{id}` generating JSON + PDF audit bundle with signed timestamp | new `api/routes_export.py`; PDF gen via reportlab or similar |
| 7.7 | Per-account batch export endpoint (date range) for compliance dumps | `api/routes_export.py` |

### Tests

- `tests/test_phase7_context.py`:
  - GET /context/calc/{id} returns complete graph for synthetic trade
  - GET /context/position/{id} aggregates correctly for multi-calc scale-in
  - Webhook fires on position close; retries on 5xx; dead-letters after N attempts
  - Audit export JSON has all required fields
  - PDF generation completes without errors

### Acceptance criteria

- External custom model can subscribe to webhook + fetch full context
  per close event with no engine modification
- Audit export passes structural validation against spec schema
- Webhook latency < 5s p95 on position close

---

## Phase 8: Operator UX

**Goal**: Multi-pane dashboard, modals, notifications, calculator
window config.

**Dependencies**: Phases 1, 2, 3, 4.

**Effort**: L (significant frontend work).

### Tasks

| # | Task | File(s) |
|---|---|---|
| 8.1 | Multi-pane dashboard: 4 panes (open positions, active calcs, needs-link, recent closes) visible simultaneously | `templates/dashboard.html` (new or refactor index.html), `static/js/dashboard.js` |
| 8.2 | Open positions pane: live deviation badges, MFE/MAE, uPnL | `templates/partials/positions_pane.html` |
| 8.3 | Active calcs pane: live countdown timers using frozen `window_seconds + created_ts`; cancel button per calc | `templates/partials/calcs_pane.html`, `static/js/calc_countdown.js` |
| 8.4 | Calculator tab: window dropdown (1/5/15 min) writing to `accounts.config_json.window_seconds`; override-aware size/TP/SL inputs (planned + overridden) | `templates/calculator.html` |
| 8.5 | Multi-TP UI: allow tp_levels array entry in calculator | same |
| 8.6 | Replacement modal (Q42): triggered at order-placement time when released calc near-matches; pre-submission decision | `static/js/replacement_modal.js` |
| 8.7 | Manual-close reason modal (Q33): triggered on opposite-side order detection without calc match; dropdown + optional note | `static/js/manual_close_modal.js` |
| 8.8 | Notification system: toast banners + persistent badge counters; subscriptions from `config_json.notification_subscriptions` | `static/js/notifications.js`, `templates/partials/toast.html` |
| 8.9 | Settings page for `accounts.config_json` (window, clock-skew, deviation thresholds, notification subscriptions) | `templates/settings.html` |
| 8.10 | Per-position trade events drilldown in Position History drawer: lazy-loaded timeline fragment that lists this position's events (calc_created, order_placed, order_canceled, order_filled, position_opened, partial_close, tp_modified, sl_modified, position_closed, etc.) in chronological order with timestamp, event type chip, and one-line payload summary. Backend reuses `core.trade_event_log.query_trade_events(account_id, calc_id, ...)`. Drawer's existing fills sub-table (`templates/fragments/history/position_fills.html`) stays; the new timeline lives alongside it as a second collapsible section. **For positions with no `calc_id` (legacy + Phase-0.0.6/0.0.7 rebuilt rows that pre-date the calculator workflow), render an empty-state explaining the position pre-dates the events log — NOT an error.** | new `api/routes_orders.py::frag_position_events`, new `templates/fragments/history/position_events.html`, drawer wiring in `templates/fragments/history/closed_positions_table.html` |

### Tests

- `tests/test_phase8_ui.py` (template render tests per CLAUDE.md
  discipline):
  - Dashboard renders all 4 panes with synthetic state
  - Countdown timer JS computes remaining time correctly from frozen ts
  - Replacement modal triggers on near-match scenario
  - Manual close modal triggers on opposite-side without calc
  - Notification badge increments on event arrival
  - Settings page persists config_json changes
  - Position events drilldown: renders timeline in chronological
    order for a synthetic position with multiple event types
  - Position events drilldown: renders empty-state (NOT error) when
    the position has no calc_id (legacy / rebuilt rows)
  - Position events drilldown: query is scoped to the position's
    own calc_id(s) — does not leak events from sibling positions

### Acceptance criteria

- Operator smoke test: full lifecycle (Calculate → paste → fill → close)
  visible end-to-end in dashboard
- Deviation badges update live when amendment events fire
- Replacement and manual-close modals not bypassed by edge cases
- Per-position events drilldown renders for at least one live and
  one historical (calc-attributable) position; empty-state renders
  for at least one legacy (no-calc) position

---

## Phase 9: Multi-operator + advanced

**Goal**: Single-operator-per-account lock with takeover. Operator_id
on all action rows.

**Dependencies**: Phases 0, 1, 2, 3 (operator_id columns must exist).

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 9.1 | Implement single-operator-per-account lock: on UI load, check `operator_sessions` for active session; if exists and not own session, show read-only + takeover prompt | new `core/auth_state.py` + frontend |
| 9.2 | Takeover endpoint: terminates prior session; writes new `operator_sessions` row with `takeover_from_session_id` | `api/routes_auth.py` (new or extend) |
| 9.3 | Propagate `operator_id` from active session to every action row write (calcs, orders, amendments, manual_links, close reasons) | call-site updates across `core/handlers.py`, `core/order_manager.py`, `core/ws_manager.py`, `api/routes_*` |
| 9.4 | Session timeout: idle session auto-terminated after N min (default 30) | `core/auth_state.py` background job |

### Tests

- `tests/test_phase9_multi_operator.py`:
  - Second operator login: sees read-only + takeover prompt
  - Takeover: prior session terminated; new operator_id propagates
  - operator_id correctly stamped on calcs, orders, amendments,
    manual_links, close_reasons
  - Idle session times out

### Acceptance criteria

- Two concurrent operators cannot both act on the same account
- Audit query "who created this calc" returns correct operator_id
- Session handoff visible in `operator_sessions` table

---

## 10. Test strategy across phases

### Levels

- **Unit**: per-module tests (matcher, junction CRUD, amendment
  detection, deviation computation) — each phase has its own test file
- **Integration**: end-to-end flows (calc → order → fill → close)
  exercising multiple phases together
- **Template wiring**: per CLAUDE.md, compile-and-render templates
  with synthetic context, assert structure
- **Migration**: pre/post migration state validation; rollback testing

### Golden datasets

Create `tests/fixtures/golden/`:
- `simple_trade.json` — 1 calc → 1 order → 1 fill → close
- `scale_in_trade.json` — 2 calcs → 2 orders → multiple fills → close
- `multi_tp_trade.json` — 1 calc with 3 TP levels → partial closes → final close
- `amended_trade.json` — operator widens SL mid-trade → close at amended SL
- `manual_close_trade.json` — operator manual-closes at +1R (NEW_OPPORTUNITY)
- `liquidation_trade.json` — venue liquidates position
- `replacement_trade.json` — order cancel → operator places replacement → matched to released calc
- `orphan_calc.json` — calc computed but no order placed
- `unplanned_order.json` — order placed with no calc in window
- `funding_trade.json` — multi-day position with 3 funding accruals
- `rehydrate_state.json` — engine restart mid-trade with all junction state

Each fixture runs against the full pipeline post-deployment and
verifies all expected events + DB rows.

### Performance

- Junction query benchmarks: position list with 1000+ open positions
  rehydrates < 2s
- Reverse-query endpoint: GET /context/calc/{id} < 200ms p95 for 30-day
  history
- WS event throughput: 100 fills/sec sustained without amendment-write
  contention

---

## 11. Migration / rollback plan

### Forward migration

Phase 0 is the only phase that touches the DB schema. Strategy:

1. **Pre-deployment**: backup full DB
2. **Run Phase 0 migration**: idempotent; safe to retry
3. **Verify**: run Phase 0 tests; verify backfill counts match
   expected (junction rows ≈ historical fills WHERE calc_id IS NOT NULL,
   grouped)
4. **Deploy code Phase 1+**: incrementally; each phase shippable
   independently to its dependencies
5. **Feature flags**: gate Phase 3 (link_status UI), Phase 6 (full
   event payload), Phase 7 (webhook) behind `config_json.feature_flags`
   so each can be enabled per-account incrementally

### Rollback

- **Phase 0 schema rollback**: drop new tables; remove new columns;
  re-cast `closed_positions.exit_reason` back to old values. DESTRUCTIVE
  — backfill data lost. **Recommended: forward-fix only, no rollback.**
- **Phase 1+ code rollback**: revert via git; schema stays in place
  (new tables become unused; no harm)
- **Webhook rollback** (Phase 7): disable webhook URL in config; engine
  retains events but doesn't dispatch

### Compatibility shims

- Existing subscribers to anemic `position_closed` event may break with
  Phase 6 payload expansion. Mitigation: emit both old and new event
  types for one release cycle; deprecate old after subscribers migrate.
- Existing `find_candidate_calcs()` manual UI ([core/order_enrichment.py:164-265](core/order_enrichment.py#L164-L265))
  remains during Phase 3 deployment as fallback; remove after needs-link
  tab proven stable.

---

## 12. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **Junction write contention on high fill volume** | Indexed by `(position_id)` + `(order_id)`; batch writes within same WS event handler; upsert-style; benchmark before Phase 2 deploy |
| **Migration backfill produces incomplete junction for old positions** | Documented as "full attribution from migration date forward"; historical reports get partial; new dashboards filter by date |
| **Per-criterion audit table grows fast** | Estimate: 5-6 rows per order × N orders/day; expect ~MB/day; partition by month if needed at scale |
| **Operator confused by strict 6/6 matching (more orders go to manual)** | Diff panel makes "why didn't this match" obvious; expected user feedback loop refines tolerances in config_json |
| **Bracket detection misclassifies non-bracket orders as siblings** | Time-window fallback is the fragile part; per-adapter venue-native takes priority; default 2s window tunable |
| **Snapshot-wins drift policy regresses on WS-fast / REST-slow venues** | Reconciler validates; rollback path: revert §12.6 inversion if drift events spike |
| **Webhook delivery failures lose model feedback** | Retry + dead-letter; subscriber polls reverse-query as backup |
| **Single-operator lock blocks legitimate concurrent operations across accounts** | Lock is per-account, not per-operator; operator can manage N accounts simultaneously, just one operator per account at a time |

---

## 13. Effort summary

| Phase | Effort | User-visible value at end of phase |
|---|---|---|
| 0.0 — Data quality pre-work | M-L | None directly visible; but historical MFE/MAE re-becomes trustworthy once 0.0.6 rebuild runs |
| 0 — Foundation | M | None (schema only) |
| 1 — Matcher | M | Strict matching live; per-criterion audit visible |
| 2 — Junction attribution | L | Open positions show calc_id; deltas at close |
| 3 — Link status UI | M | Needs-link tab; manual review workflow |
| 4 — Amendments + deviation | M | Live deviation badges on positions |
| 5 — Funding + fees | M | Closed positions show correct net PnL with funding |
| 6 — Event bus enrichment | M | Subscribers receive full context on close |
| 7 — Reverse query + export | M | External models can fetch; audit export works |
| 8 — Operator UX | L | Multi-pane dashboard; modals; settings |
| 9 — Multi-operator | M | Concurrent operator safety |

**Total estimated effort**: ~9-14 weeks single-developer (Phase 0.0
adds 5-10 days); parallelizable to ~5-7 weeks with phases 4/5/6 and
7/8/9 split across two developers post-Phase 2.

**Critical path**: Phase 0.0 → 0 → 1 → 2 → 6 → 7. Without these, no
end-to-end model-feedback loop exists.

**Lowest-risk early win**: Phase 0.0 (data quality — fixes already-
broken historical analysis) + Phase 0 + Phase 4 (amendment tracking) +
Phase 8.4-8.5 (calculator window config). Delivers operator-visible
deviation badges and configurable windows with minimal blast radius,
on top of clean historical data.

---

## 14. Task breakdown (Claude Code sizing)

Each "task" in this section is sized to be one Claude Code session
(1-4 hours focused work, <30 min review, ideally one commit). The
project's existing `task N: description` commit convention applies.

### 14.1 Sizing principles

| Dimension | Ideal | Tolerable | Too big — split |
|---|---|---|---|
| LOC change | 100–500 | 500–1500 | >2000 |
| Files touched | 2–5 | 5–10 | >15 |
| Test files added/modified | 1–2 | 2–4 | >5 |
| Goal coherence | 1 outcome | 1 outcome with 2-3 sub-bullets | unclear / multi-goal |
| Review burden | <30 min | 30-60 min | >1 hour |
| Maps to commits | 1 | 1-2 | >2 (split) |

**Sweeps** (e.g., `operator_id` propagation across many files) are a
special case — single goal but many touch points. Treat as one task
but expect higher review cost. Pre-grep all sites before starting.

**Tests live in the same task as the code** — don't defer to a "tests
for task N" follow-up. Merge.

### 14.2 Recommended task count per phase

| Phase | Sub-items listed | Recommended tasks | Rationale |
|---|---|---|---|
| 0 Foundation | 13 | **6** | Group by table family + state-machine helpers as own task |
| 1 Matcher | 10 | **7** | Each state-machine transition is its own task with event emission |
| 2 Junction attribution | 12 | **10** | Hottest-path phase; keep small for review safety |
| 3 Link status + UI | 8 | **4** | UI naturally bundles: backend (1), endpoints (1), tab (1), badges (1) |
| 4 Amendments + deviation | 6 | **5** | Each detection/computation/event surface = own task |
| 5 Funding + fees | 7 | **5** | Per-adapter WS split (Binance + Bybit = 2 tasks) |
| 6 Event bus enrichment | 8 | **6** | Topic wrapper, payload, each event family, drift inversion (isolated for revertability) |
| 7 Reverse query + export | 7 | **6** | Per-endpoint task; PDF isolated from JSON |
| 8 Operator UX | 10 | **9** | Each major UI surface is its own task |
| 9 Multi-operator | 4 | **4** | Lock+takeover, operator_id sweep, timeout, UI |
| **Total** | — | **~62 tasks** | ~6 weeks @ 2 tasks/day; ~12 weeks @ 1/day with review |

### 14.3 Concrete task lists

#### Phase 0 — Foundation (6 tasks)

| # | Task | Scope |
|---|---|---|
| P0.T1 | New tables + indexes + CRUD helpers (incl. `lifecycle_id` columns + indexes per spec §3.5) | `positions_calcs`, `order_amendments`, `funding_events`, `calc_match_audit` |
| P0.T2 | New table + scaffold | `operator_sessions` table + `core/auth_state.py` (logic deferred to Phase 9) |
| P0.T3 | Column additions to existing tables (part 1) | `pre_trade_log` (16 fields incl. `lifecycle_id`) + `accounts.config_json` (incl. `entry_tolerance_pct` and `snapshot_drift_tolerance_pct` defaults) |
| P0.T4 | Column additions to existing tables (part 2) | `orders` (6 fields incl. `lifecycle_id`) + `closed_positions` (16+ fields incl. `lifecycle_id`) |
| P0.T5 | Migration backfill script | Junction backfill from historical fills + `exit_reason` re-map + `lifecycle_id` back-fill per historical position lifecycle |
| P0.T6 | State-machine enforcement helpers | `core/calc_state.py` + `core/link_state.py` with valid-transition dicts + `transition()` choke-point + `IllegalStateTransition` exception (per spec §3.6) |

**Sequence**: T1-T4 loosely parallel (different tables); T5 depends on
all schema in place; T6 fully independent (no schema dep) — can ship
first or alongside.

#### Phase 1 — Matcher tightening (7 tasks)

| # | Task | Scope |
|---|---|---|
| P1.T1 | Strict matcher rewrite | strict 6/6 (limit + market; entry source differs); tolerance config (incl. `entry_tolerance_pct` from `config_json`); `calc_match_audit` row writes; **all calc.status transitions go through `core/calc_state.transition()` choke-point (P0.T6)** so events fire automatically and illegal transitions raise |
| P1.T2 | Per-account window from `config_json` | Read window_seconds + clock_skew_tolerance; freeze on calc creation |
| P1.T3 | Calc revision detection | Supersede prior calc + `calc:superseded` event |
| P1.T4 | Calc cancel by operator | Endpoint + status transition + `calc:cancelled` event |
| P1.T5 | Calc release on order cancel | Status back to `released` + replacement-modal scaffold |
| P1.T6 | Calc auto-complete on position close | Transition + `calc:completed` event (may shift to Phase 2) |
| P1.T7 | Nullable TP/SL handling | Auto-route to manual-link if TP or SL null |

**Sequence**: T1 is the bottleneck; T2-T7 depend on T1 and can run
loosely parallel after.

#### Phase 2 — Junction attribution (10 tasks)

| # | Task | Scope |
|---|---|---|
| P2.T1 | Opening-fill junction upsert + `lifecycle_id` generation | Single row per order, cumulative qty as fills arrive. **At first fill that opens a position, generate UUID `lifecycle_id`** and back-fill onto matched `pre_trade_log.lifecycle_id`, `orders.lifecycle_id`, and the junction row. Subsequent scale-in calcs inherit the position's existing `lifecycle_id`. |
| P2.T2 | Closing-fill calc_id + lifecycle_id stamping | Inherit from position's primary calc. Stamp `fills.calc_id` and `fills.lifecycle_id` on every closing fill. |
| P2.T3 | `PositionInfo.calc_id` field + restart rehydrate | From junction on first fill + on restart |
| P2.T4 | Scale-in junction-append | New calc → new junction row; per-calc planned values |
| P2.T5 | Delta computation at close | All 8 delta columns on `closed_positions`. **Use delta basis rule (spec §3.2)**: deltas computed against most-contributing calc (largest `contributed_qty`); tie-break first-entry. Same basis as live deviation badge (Phase 4) for consistency. |
| P2.T6 | Primary calc_id + `exit_reason` classification | Most-contributing calc; planned-vs-amended detection |
| P2.T8 | Bracket detection (all adapters) | `core/bracket_detection.py` engine + per-adapter `detect_bracket()`: Bybit `orderLinkId`, Binance/MEXC `positionSide`/symbol + 2s time-window fallback. OKX dropped (no adapter); MT4/MT5 forex forward-looking. (This roadmap view's P2.T# numbering predates and is superseded by the authoritative detailed §2 table above — bracket detection is detailed-table task 2.8.) |
| P2.T9 | Multi-TP partial-close lifecycle | `position:partial_close` events + final TP_LADDER_COMPLETE/MIXED |
| P2.T10 | Restart rehydrate + reconciliation pass | Full rehydrate + venue REST diff |

**Sequence**: Strict chain T1 → T2 → T3 → T4 → T5; T7+T8 parallel-safe;
T10 needs T1-T9 done.

#### Phase 3 — Link status + manual-link UI (4 tasks)

| # | Task | Scope |
|---|---|---|
| P3.T1 | **SHIPPED (T241)** — `link_status` auto-classification choke-point | All `orders.link_status` writes route through `core/link_state` (spec §3.6): `auto_classify()` for engine sets (matcher + bracket; undecided NULL/UNPLANNED source), `transition()` reserved for operator moves (P3.T2/T3). See detailed §3 table row 3.1. |
| P3.T2 | **SHIPPED (T242)** — Endpoints | `manual_link`, `mark_unplanned`, `needs_review` (+ `core/link_actions.py`, `LinkTransitionRaceLost`). All operator link_status writes through the choke-point. See detailed §3 rows 3.3–3.5. |
| P3.T3 | **SHIPPED (T242)** — Needs-link tab UI | Page + queue fragment + nav tab; per-criterion diff via primitives; choke-pointed action buttons; 10 compile-render wiring tests. See detailed §3 row 3.6. |
| P3.T4 | **SHIPPED (T243)** — Status badges + nav counter | Per-order link_status badge (shared `link_status_badge` macro) in order_history + open_orders tables; defined the app-wide badge color family; live needs-link nav counter via `/fragments/needs_link_count`. **Phase 3 COMPLETE.** See detailed §3 rows 3.7/3.8. |

#### Phase 4 — Amendments + deviation (5 tasks)

| # | Task | Scope |
|---|---|---|
| P4.T1 | **SHIPPED** — Amendment detection from WS | `detect_and_persist_amendment` invoked pre-gate from `ws_manager._apply_order_update`; entry/tp/sl/size; chained baseline; `deviation_pct` inline; `leverage` + REST deferred. See detailed §4 row 4.1. |
| P4.T2 | **SHIPPED** — Deviation pct + amendment count rollup | `deviation_pct` per row (done in P4.T1); `cumulative_amendment_count` at close via `count_amendments_for_calcs` (by contributing calc_ids), preserved across REPLACE. See detailed §4 row 4.3. |
| P4.T3 | **SHIPPED** — Live deviation badge logic + frontend | Combined badge (`deviation_badge_level`, spec §10.2 ∪ §4.4 thresholds) stamped onto PositionInfo in `_enrich_positions_calc_id` + rendered inline via `deviation_badge.html`. size-deviation magnitude basis (spec §3.2); TP/SL live drift deferred. See detailed §4 row 4.4. |
| P4.T4 | **SHIPPED** — `position:amended` event emission | One `position_amended` trade event per persisted `order_amendments` row via `_emit_amendment_event` (sibling of `_emit_fill_events`, dispatched `asyncio.to_thread`); 1:1-on-commit (`insert_order_amendment`→`bool`); §9 payload keys; event_bus topic stays Phase 6 (row 6.4). See detailed §4 row 4.5. |
| P4.T5 | TP/SL drift columns at close | `tp_drift_pct`, `sl_drift_pct` from amendments vs first calc |

#### Phase 5 — Funding + fees (5 tasks)

| # | Task | Scope |
|---|---|---|
| P5.T1 | Funding WS subscription — Binance | Income stream handler in Binance adapter |
| P5.T2 | Funding WS subscription — Bybit | Income stream handler in Bybit adapter |
| P5.T3 | `funding_events` writer + dedup | Per-event writes; idempotent on `venue_event_id` |
| P5.T4 | Funding aggregation + net_pnl recompute | At close: `funding_fees` = SUM; `net_pnl` includes funding |
| P5.T5 | Live unrealized funding helper + UI | Sum for open position; surface in position detail |

#### Phase 6 — Event bus enrichment (6 tasks)

| # | Task | Scope |
|---|---|---|
| P6.T1 | Topic naming wrapper + per-account scoping | `engine:account:{id}:{domain}:{event}` |
| P6.T2 | `position:closed` full payload expansion | Spec §9 shape; compat shim for old subscribers (emit both for 1 release) |
| P6.T3 | All `calc:*` event emissions (sweep) | Verify Phase 1 sites emit; backfill any missed |
| P6.T4 | All `position:*` event emissions (sweep) | Verify Phase 2 sites; add `position:opened`, `scale_in`, `liquidated` |
| P6.T5 | `order:duplicate_detected` | Near-dup detection + event + UI badge |
| P6.T6 | `position:size_drift` + snapshot-wins inversion | Invert WS-fills-win-within-5s. **Read `snapshot_drift_tolerance_pct` from `config_json` (default 0.5%) — event only fires when delta exceeds tolerance** (prevents drift-event noise during high-volume periods). Feature-flag the inversion behind `config_json.feature_flags.snapshot_wins_drift` for per-account revertability. |

#### Phase 7 — Reverse query + export (6 tasks)

| # | Task | Scope |
|---|---|---|
| P7.T1 | `GET /context/calc/{id}` + `GET /context/lifecycle/{lifecycle_id}` | Full graph payload assembly (shared helper). Lifecycle endpoint pivots on `lifecycle_id` (spec §3.5) and is the single-key audit query that joins every table for one trade. |
| P7.T2 | `GET /context/position/{id}` | Position-keyed equivalent (same helper as T1) |
| P7.T3 | Webhook dispatcher + retry + dead-letter | Per-account webhook URL from `config_json`; exponential backoff |
| P7.T4 | Audit export — JSON only | `POST /export/closed_position/{id}` |
| P7.T5 | PDF generation + signed timestamp | Add to audit export; reportlab or similar |
| P7.T6 | Batch export endpoint | Date-range zipped bundle |

#### Phase 8 — Operator UX (8 tasks)

| # | Task | Scope |
|---|---|---|
| P8.T1 | Multi-pane dashboard layout | 4-pane CSS grid; state passing scaffold |
| P8.T2 | Open positions pane | Deviation badges + uPnL refresh + MFE/MAE |
| P8.T3 | Active calcs pane | Countdown timers JS using frozen ts |
| P8.T4 | Calculator tab refresh | Window dropdown + planned/overridden inputs + multi-TP UI |
| P8.T5 | Replacement modal | Pre-submission near-match prompt + flow integration |
| P8.T6 | Manual-close reason modal | Opposite-side detection trigger + dropdown + note |
| P8.T7 | Notification system | Toast + badge counters from `config_json` subscriptions |
| P8.T8 | Settings page for `accounts.config_json` | All knobs editable; validation |
| P8.T9 | Per-position trade events drilldown in Position History drawer | Lazy-loaded timeline fragment beside the existing fills sub-table; reuses `core.trade_event_log.query_trade_events`. Empty-state (not error) for legacy / rebuilt positions with no `calc_id`. Depends on P6.T3/T4 (event-emission sweeps) for live positions; works against pre-existing `trade_events` rows for any calc-attributed historical position. |

**Sequence**: Largely independent (different templates); T2-T9 can fan
out after T1. P8.T9 is loosely coupled — its empty-state path lets it
ship before Phase 6 if needed, with the live-event path lighting up
once the upstream emit sweeps land.

#### Phase 9 — Multi-operator (4 tasks)

| # | Task | Scope |
|---|---|---|
| P9.T1 | `operator_sessions` lock + takeover endpoint + UI prompt | Read-only mode + takeover flow + audit row |
| P9.T2 | `operator_id` propagation sweep | All action-row writes (calcs, orders, amendments, manual_links, close_reasons) — biggest sweep, pre-grep first |
| P9.T3 | Session timeout + idle cleanup | Background job; configurable timeout |
| P9.T4 | UI: read-only mode for non-active operator | Visual indication + disabled controls |

### 14.4 Sequencing inside a phase

Most phases have one strict-sequential bottleneck task and several
parallel-safe tasks following:

| Phase | Bottleneck | Parallel-safe after | Final-dependency |
|---|---|---|---|
| 0 | (none — all loosely parallel) | T1-T4 | T5 (needs all schema) |
| 1 | T1 (matcher rewrite) | T2-T7 | — |
| 2 | T1 → T2 → T3 → T4 → T5 (chain) | T7+T8 parallel | T10 (needs T1-T9) |
| 3 | T1 (link_status logic) | T2 + T3 + T4 | — |
| 4 | T1 (amendment detection) | T2-T5 | — |
| 5 | T3 (writer) | T1+T2 (adapter subs) parallel; T4+T5 after T3 | — |
| 6 | T1 (topic wrapper) | T2-T6 all independent after T1 | — |
| 7 | (none — endpoints independent) | T1-T6 | T5 depends on T4 |
| 8 | T1 (dashboard layout) | T2-T9 fan out | — |
| 9 | T1 (lock) | T2 (sweep) needs T1; T3+T4 independent | — |

### 14.5 Practical recommendations

1. **Don't combine schema with behavior tasks** — Phase 0 ships
   atomically; behavior lands in Phase 1+ referencing schema as
   already-existing.
2. **One commit per task** — matches the `task N: description`
   convention visible in recent commits (`task 162`, `task 161`,
   `task 160`).
3. **Phase boundaries = smoke-test checkpoints** — at end of each
   phase, run the user-visible smoke test for that phase's value (see
   §13 Effort summary). If smoke fails, pause and fix before next
   phase.
4. **Largest single task is P9.T2** (`operator_id` propagation sweep).
   Pre-grep all action-row write sites before starting; treat as
   ~6-hour session with explicit audit checklist in the task report.
5. **Smallest tasks are Phase 0** (~1-2 hours each). Good warm-ups;
   cleanly verifiable.
6. **Phase 8 tasks have highest UI test surface** — apply CLAUDE.md
   template wiring discipline (compile-and-render tests, not just
   source grep).
7. **Phase 6 T6 (snapshot-wins inversion) is the riskiest single
   change** — isolate in its own commit, deploy behind feature flag
   if possible, monitor `position:size_drift` event rate post-deploy.
8. **Feature-flag candidates** for incremental rollout per account:
   - P3.T1-T4 (link_status UI)
   - P6.T2 (full close payload)
   - P7.T3 (webhook)
   - P6.T6 (snapshot-wins inversion)

---

## 15. Deferred (post-implementation)

- Engine-generated tag for deterministic linkage (gap #10 — explicitly
  out of scope per spec §13)
- Close-calc operator pathway (Q8/Q30 — walked back)
- External event delivery (Redis pub/sub, Slack, email) — webhook
  bridge in Phase 7 sufficient for now
- Live time-series snapshots for per-second position state history
- Multi-leg / pairs strategies
- Role-based access control beyond single-operator lock
- ~~Q19 vs Q54 unification~~ **RESOLVED 2026-05-24** (spec §15 R2): unified
  under standard-matcher rule. No auto-inherit; all standalone TP/SL
  through the 6/6 matcher. Plan P2.T10 (auto-inherit task) removed.

---

**End of implementation plan.**
