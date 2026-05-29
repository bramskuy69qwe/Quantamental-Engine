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

### closed_positions attribution — R1 CLOSED (T234 / P2.T6)

Surfaced by the holistic Phase-2 audit (after T229): `closed_positions.calc_id`
used the Phase-1 "earliest opening fill" rule + NULL `lifecycle_id`, while
`fills.calc_id` (T2.2), `PositionInfo.calc_id` (T2.3), and the T2.5 deltas
used the most-contributing (junction-primary) calc — so for a scale-in
where the larger order wasn't first, the closed row disagreed.

**Resolved in T234 (P2.T6)**: `_build_close_row_for_fill` now sets both
`closed_positions.calc_id` and `closed_positions.lifecycle_id` from
`_position_primary_calc` (most-contributing; tie-break first-entry),
falling back to the earliest-fill rule (calc_id only, lifecycle NULL)
only when the position has no junction (UNPLANNED / binance empty-tpid).
All four surfaces now converge — verified e2e (calc-A qty3 first +
calc-B qty7 → all = calc-B, lifecycle sealed) + a mutation-proven
convergence test. `insert_closed_position` REPLACE-preserves both (T232).

**T2.5 (T233) close-time deltas** (`entry_px_delta_pct`, `size_delta_pct`,
`exit_vs_target_pct`, `realized_r`, `planned_r`, `hold_time_actual_ms`)
remain as shipped. **Still deferred** (operator-approved): `tp_drift_pct`/
`sl_drift_pct` → P4.6 (need final amended TP/SL); `cumulative_amendment_count`
→ P4.3 (`order_amendments` unwired); `hold_time_planned_ms` → no source.

**T2.6 known limitations (T234 review):**
- **Rebuild reverts T2.6 attribution.** `scripts/rebuild_closed_positions.py`
  (the fills-only offline recovery tool) routes through
  `core/position_grouping.py::group_fills_into_positions`, which has NO
  `positions_calcs` access and so attributes `calc_id` by earliest-opening
  -fill (+ NULL `lifecycle_id`, + tp/sl from the earliest calc). Running
  `--apply` over a scale-in whose larger calc wasn't first will flip those
  attribution columns back to earliest (PnL/qty/prices recompute correctly
  — attribution-only drift, gated behind a manual operator action). Full
  convergence would re-couple the recovery tool to live junction state
  (out of scope for a fills-only reconstruction). Anchor-commented at
  `position_grouping.py`.
- **`closed_positions.model_name` is NOT keyed off the primary calc.** It's
  still sourced by symbol+entry-time window via `_compute_shortfall` /
  `get_pre_trade_for_shortfall` — the one closed-row attribution field not
  converged on the junction primary. Pre-existing; for single-calc or
  same-model scale-ins it agrees anyway. Converge opportunistically (read
  `model_name` from the primary calc) if it ever matters.

### exit_reason §3.4 enum — forward path (T235 / P2.T7)

The live close path now writes the spec §3.4 `exit_reason` enum
(`TP_PLANNED` / `SL_PLANNED` / `MANUAL_OTHER`) instead of legacy
tp_hit/sl_hit/manual/limit_close/trailing_stop — matching the §3.4 values
the P0.T5 backfill applied to historical rows (the forward path was the
last legacy-string emitter). The history template maps the enum to family
badge labels (TP/SL/Manual/Liq/…) — replacing the raw-enum-string
fallthrough — with legacy fallbacks for any un-backfilled rows. (The
badge color-hook classes are undefined in base CSS app-wide, as they were
for the pre-T2.7 legacy badges; the label mapping is the functional win.) **`*_AMENDED` is
deferred to Phase 4** (no amendment data + final-TP/SL unknowable at close,
continuing the T2.5 deferral) — so every TP/SL close reads `*_PLANNED`
until P4.1/4.3 wire amendment tracking; analytics filtering on
`TP_AMENDED`/`SL_AMENDED` returns empty by design until then. **Residual
legacy writer (flagged, not fixed):** `database.py` Task-76 startup
migration still defaults empty/NULL `exit_reason`→`'manual'` (legacy) — only
fires on empty rows (forward rows never are), cosmetically neutral (the
template maps `manual`→gray too); change to `MANUAL_OTHER` opportunistically.

### TP/SL bracket detection (T236 / P2.T8) — detect-only + MEXC ingest gaps

`core/bracket_detection.py` (`detect_brackets`) + per-adapter
`detect_bracket()` (binance/bybit/mexc) ship the bracket-grouping primitive
(spec §4.5): two-tier (venue-native shared link → `(symbol, position_side)`
+ anchor-bounded 2s window; a bracket needs ≥1 entry + ≥1 protective leg).
**DETECT-ONLY** — unwired; P2.T9 consumes it to propagate the entry's
calc_id to TP/SL. OKX dropped (no adapter); MT4/MT5 forex forward-looking.

The review surfaced two **pre-existing MEXC ingest gaps** (MEXC is Beta /
not the live venue; both block MEXC bracket detection from functioning
until fixed):
- **FIXED in T236**: `upsert_order_batch` did `int(reduce_only)` which
  raised on MEXC's `reduce_only=None` and (inside the batch try/except)
  silently swallowed the WHOLE order batch → MEXC orders never reached the
  table. Now `int(reduce_only or 0)`. (Hardens all adapters; regression
  test in test_phase0_t1_schema.py.)
- **DEFERRED (documented)**: MEXC's WS `parse_order_update` doesn't populate
  `created_at_ms` → WS-sourced MEXC orders persist with `created_at_ms=0`,
  degenerating the time-window tier (all look simultaneous). Fix belongs to
  the MEXC WS adapter (extract the venue push timestamp); detection is
  reliable only for REST-sourced MEXC orders until then. Anchor-commented
  in `mexc/rest_adapter.detect_bracket`.

Heuristic limit (all venues, bounded): live Binance has no shared bracket
id (`exchange_position_id` empty, clientOrderId unique), so detection is
the (symbol, positionSide)+window heuristic; the false-positive risk
(two entries within the window) is bounded by P2.T9 only propagating from
an entry that carries a calc_id.

### TP/SL bracket calc_id inheritance (T237 / P2.T9) — consumes T2.8

`OrderManager._propagate_bracket_calc_id` (+ `_detect_brackets` adapter
resolver, + `_propagate_bracket_calc_id_for_orders` batch wrapper) wires
the T2.8 primitive into the order-arrival path (spec §4.5). For each
detected bracket whose ENTRY leg carries a `calc_id` (matcher-linked,
§4.1), it stamps that `calc_id` + `link_status='LINKED'` onto every
protective leg whose `calc_id` is still NULL. **This is the only path a
TP/SL order ROW gets a `calc_id`** — the strict matcher
(`order_enrichment._try_correlate`) returns early for reduce-only /
close-type orders.

Wired into all three arrival handlers: `process_order_update` (WS, per
arriving symbol, AFTER enrichment so the entry's calc_id is committed) +
`process_order_snapshot` / `process_algo_snapshot` (REST reconciliation,
per distinct batch symbol). The candidate query reads orders by
`(account_id, symbol)` with a data-derived lookback (MAX(created_at_ms) −
5min, LIMIT 200) so it includes FILLED entries (the entry often fills
before the protective leg arrives) and works for both real epoch-ms live
timestamps and the small synthetic ones tests use. Idempotent
(`WHERE calc_id IS NULL`); best-effort; cheap pre-checks short-circuit.

`upsert_order_batch` uses `ON CONFLICT DO UPDATE` with a column set that
EXCLUDES `calc_id`/`link_status`, so an inherited calc_id survives later
WS order updates (no REPLACE-wipe, no self-heal needed).

**Deviations (deviation-discipline):**
- Propagates `calc_id` + `link_status` only, **NOT `lifecycle_id`** —
  the entry's lifecycle is minted at its first opening FILL (T2.1), which
  commonly hasn't happened when the protective leg arrives; a COALESCE
  would write NULL in the common case and the idempotency guard would
  never revisit it (half-correct partial). Protective-order
  `lifecycle_id` stamping stays a known gap, same as T2.1 (stamps only
  the entry order). Revisit if the Phase-7 lifecycle join needs
  protective-order rows.
- RAW `UPDATE orders SET link_status` matching the matcher's NULL→LINKED
  initial-arrival set — explicitly NOT routed through
  `link_state.transition` (link_state.py:53 — the choke-point validates
  current→target between existing enum values; a NULL current would raise
  `IllegalStateTransition`). P3.T1 sweeps both sites onto the choke-point
  together. Maintains "calc_id present ⟺ link_status=LINKED".

Bounded (same as T2.8): only a calc-bearing entry propagates, so a
mis-grouped window cluster cannot fabricate a link (worst case: a TP/SL
sharing the window with an UNPLANNED entry stays NULL → standard matcher).

**T237 review notes (independent audit, no BLOCKER/HIGH):**
- **Scale-in tie-break (MED→documented)**: the protective leg inherits the
  EARLIEST calc-bearing entry in its cluster — placement-time ORDER-level
  attribution, intentionally distinct from the close-time POSITION-level
  most-contributing primary (§3.2, T2.2/T2.3/T2.5/T2.6). The primary is
  uncomputable at order arrival (no fills / no junction yet). Diverges only
  when two entries with DIFFERENT calcs share one protective leg in the 2s
  window; bounded — closing fill + closed row re-derive from the junction
  primary, no consumer reads a protective leg's `orders.calc_id`. Anchor-
  commented at the `entry = next(...)` pick.
- **Junction-less Binance close-fill (LOW, benign/improvement)**: for a
  position with no junction (Binance observe-only empty-tpid path), the
  TP/SL order now carries the entry's calc_id, so `_propagate_calc_id_to_fill`
  populates the CLOSING fill's calc_id (previously NULL). NOT overridden by
  T2.2 (no junction → early return), but it AGREES with the T2.6
  earliest-entry fallback for `closed_positions.calc_id`, and the close row
  reads OPENING fills + the junction primary, never the closing fill — so no
  divergence, just better `fills.calc_id` coverage where there was none.
- **Adapter-fault visibility (MED, FIXED)**: `_detect_brackets` now separates
  the expected no-active-account fallback (silent → window-only) from a real
  `detect_bracket` exception (log.warning + window-only), so a future Bybit
  orderLinkId-grouping regression is visible instead of a silent downgrade.
- Cross-connection calc_id visibility (matcher writes via a separate sqlite3
  conn, propagation reads via `_conn`) verified CLEAN — same read-after-commit
  pattern T2.1 already relies on. 2 indexed reads per order event accepted at
  this localhost single-tenant scale.

### Multi-TP partial-close lifecycle (T238 / P2.T11) — completion timing + ladder exit_reason

Operator-confirmed model (Option A): **per-partial `closed_positions` rows
are PRESERVED** (one row per closing order). The fork (consolidate to one
row/position per spec §8 literal) was declined to keep history/PnL
semantics + the close path surgical. T2.11 layers three things on top:

1. **calc completion deferred to the FINAL close** (size→0). Pre-T2.11
   `_complete_calcs_on_close` ran on EVERY close-row build → for a multi-TP
   ladder the calc completed prematurely on the first partial (later
   partials no-op'd via the status guard). Now gated on `is_final` in
   `_build_close_row_for_fill`. Single full close → `is_final` immediately
   → unchanged for the common case.
2. **Final-close detection is data-derived from fills** — Σ(closing qty) ≥
   Σ(opening qty) for the position — NOT the ACCOUNT_UPDATE snapshot (which
   races fill ingest, reflecting pre- OR post-fill size). `force_final=True`
   on `build_final_close_row` (the position-disappearance safety net knows
   the position is gone). Empty-tpid (binance one-way) / missing-opens →
   `is_final=True` fallback (can't sum per position → preserve pre-T2.11
   complete-on-this-close rather than risk never completing).
3. **Ladder-aware FINAL exit_reason** (`_classify_final_exit_reason`):
   `TP_LADDER_COMPLETE` (≥2 distinct TP closing orders, no SL/manual);
   `MIXED` (≥1 TP + ≥1 SL/manual closing order); else fall back to the
   per-order `_determine_exit_reason` (single TP → TP_PLANNED, all-SL →
   SL_PLANNED, etc.). Non-final partial rows keep their per-order reason.
   Keys on DISTINCT closing ORDERS (a single TP filling in multiple partial
   fills is 1 order → not a ladder). Empty-tpid → fallback.

`partial_close` trade event enriched with position_id + qty_reduced +
remaining_qty + realized_pnl_partial (spec §8/§9 payload). `tp_level_idx`
omitted — needs `calc.tp_levels` parse + TP-price matching (deferred, not
load-bearing for the lifecycle). The formal §9 per-account event-bus topic
(`position:partial_close`) is Phase 6.

Tests: `tests/test_phase2_multi_tp.py` (14) — `_classify_final_exit_reason`
unit cases + full close-row path (partial→final completion deferral, ladder
vs MIXED, single-close-immediate, force_final-on-disappearance,
realistic-deferred-timing, disappearance backstop).

**T238 review (2 independent reviewers) — fixes applied:**
- **F1 (HIGH, FIXED)**: each closing fill schedules its OWN `+2s` close-row
  build, so in a real ladder the later rungs are already on disk when an
  earlier rung's build runs → the all-fills `is_final` sum saw the full qty
  → the EARLIER partial row got mis-stamped TP_LADDER_COMPLETE + the calc
  completed early. Fix: scope the sum to closing fills with `timestamp_ms ≤
  this build's exit_time` (cumulative AS OF this close). The shipped test
  had masked it by seeding the 2nd fill only AFTER building the 1st row —
  rewritten to the realistic both-fills-first ordering.
- **F1 backstop (HIGH, FIXED)**: a MISSED closing fill (WS gap) leaves the
  is_final sum permanently short → calc strands in `matched`; the
  disappearance safety net only rebuilt UNRECORDED fills, so a
  recorded-but-never-final position never completed. Fix:
  `build_final_close_row` now calls `_complete_position_calcs` unconditionally
  (disappearance = authoritative close), gathering contributing calc_ids
  from the junction (fallback: opening fills). Idempotent / status-guarded.
- **F4 (MED, FIXED)**: `is_final` epsilon was a flat `1e-9` (too tight for
  fractional crypto qty) → a full close short by float rounding could miss
  final. Now a 1ppm relative tolerance with an absolute floor.
- **F3 (MED, KNOWN/pre-existing)**: `closed_positions` natural key
  `(account_id, terminal_position_id, exit_time_ms)` → two DISTINCT closing
  orders filling at the IDENTICAL ms collide on INSERT OR REPLACE → a rung
  row is lost. Pre-existing (per-partial rows predate T2.11); fixing needs
  the key to include `exchange_order_id` + a migration → deferred. Rare
  (distinct TP orders triggering same-ms).
- **F5 (LOW, KNOWN)**: `_classify_final_exit_reason` INNER-JOINs fills→orders;
  a closing fill whose order row is missing is dropped, which can downgrade a
  real ladder to the single-TP fallback. Orders rows are normally present
  (upserted on arrival) → graceful-degradation edge, documented.
- **F6 (LOW, pre-existing)**: the `partial_close` event's `remaining_qty`
  reads `app_state` which reflects pre-fill size (per `_process_single_fill`'s
  own contract) → may overstate by one rung. Best-effort event (formal §9
  topic is Phase 6); `qty_reduced` + `realized_pnl_partial` are authoritative.

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
