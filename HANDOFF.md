# Handoff — next Claude Code session

**Date**: 2026-05-31
**Current branch**: `v2.5/post-rewind-drop-regime-infra` @ `task 243 (P3.T4 link_status badges + needs-link nav counter)` — pushed to origin
**Tests**: 2862 passed, 7 skipped, 1 unrelated pre-existing failure
**Pre-existing failure**: `tests/test_data_cache_dd.py::TestRollingWindowPeak::test_old_high_excluded_from_window` — 30-day rolling-window boundary bug; unrelated to calc-linkage. Worth filing as its own task.

## ★ STATUS (2026-05-31) — PHASE 3 COMPLETE (T1–T4) + RE-AUDITED CLEAN; next = Phase 4 (amendment tracking + deviation)

**Phase 3 holistically RE-AUDITED (clean) — no code changes.** A 7-dimension adversarial
workflow (link-state-machine integrity, manual-link backend, UI/htmx render,
cross-surface consistency, spec §6 completeness, hot-path/DB safety, holistic test
coverage) over T1–T4 filed 5 candidate findings; **all 5 adversarially refuted**
(2 documented-deferral, 2 convention-followed, 1 mechanism-mismatch). I independently
re-verified the core spec §3.6 invariant by grep: EVERY production `orders.link_status`
WRITE routes through `core/link_state` — the matcher (`order_enrichment._try_correlate`)
+ bracket inheritance (`order_manager._propagate_bracket_calc_id`) via `auto_classify`,
and the operator handlers (`link_actions.manual_link_order` / `mark_order_unplanned`)
via `transition`. The legacy `/admin/calc_link` writes `calc_id` only (NOT link_status),
so it does not bypass the choke-point — it can only create the documented
calc_id-without-LINKED inconsistency. Two observations folded into the carry-forwards.

**P3.T4 (task 243) shipped — link_status badges + needs-link nav counter (last Phase-3 task).**
*3.7 badges*: new shared macro `templates/primitives/link_status_badge.html` (LINKED→green /
NEEDS_MANUAL_REVIEW→yellow / UNLINKED→gray / UNPLANNED→blue; NULL→"—"), used in the
order_history + open_orders tables (new "Link" column). **Operator chose Option A: defined the
missing `badge-green/red/gray/yellow/blue` family in base.html** — the link badge uses it AND it
retroactively COLORS the existing status/exit_reason badges app-wide (closes the T235 "undefined
badge color classes" gap across ~6 templates). Additive CSS, zero functional risk. *3.8 counter*:
`db.count_needs_link(account_id)` (cheap COUNT of NEEDS_MANUAL_REVIEW + UNLINKED) → new
`GET /fragments/needs_link_count` (amber badge, EMPTY when the queue is clear) → a nav `<span>`
inside the needs_link tab polling `load, every 5s` (htmx live-fragment, ws_status pattern — chosen
over a `_ctx` sync COUNT to avoid a per-render DB hit / MED-005). Review: 5 dims → 2 confirmed
(both LOW test-coverage gaps — count account-scoping + Link-column position; both closed, the
production code was correct), 3 refuted. Tests: `test_phase3_t4_badges.py` (17).

**P3.T2 + P3.T3 (task 242) shipped — manual-link backend + tab UI.**
*P3.T2*: `core/link_actions.py` (new) — `manual_link_order` / `mark_order_unplanned` /
`list_needs_review`; every `orders.link_status` write routed through the
`link_state.transition()` choke-point (operator decided→decided moves, mirroring
`handlers.cancel_calc_by_operator`). `manual_link_order` also flips the calc
active|released→matched (mirrors the auto-matcher) + propagates calc_id to opening
fills. Added `LinkTransitionRaceLost` (mirror of `CalcTransitionRaceLost`). Endpoints:
`POST /orders/{id}/manual_link` (Form calc_id), `POST /orders/{id}/mark_unplanned`
(both → 200 + discriminated HTML alert), `GET /orders/needs_review` (JSON queue + per-
criterion candidate diff). Review: 2 confirmed (MED untested `race_lost` branch → tests
added; LOW new sync-sqlite-in-async callsite → `asyncio.to_thread`), both fixed.
*P3.T3*: needs-link TAB — `templates/orders/needs_link.html` (page, lazy-loads the
queue) + `templates/fragments/needs_link_queue.html` (Card-per-order, StatusIndicator
badge, per-criterion diff via text-green/text-red, Link + Mark-UNPLANNED buttons → the
choke-pointed T2 endpoints, per-order alert div). Routes `GET /orders/needs_link` +
`GET /fragments/needs_link`; nav tab + page_meta in base.html (nav label humanized
`|capitalize`→`|replace('_',' ')|title` for multi-word keys — backward-compatible).
Auto-refresh script inlined (deviation from `static/js/needs_link.js`, page-script
convention). Review clean (0 confirmed / 8 refuted; the hx-vals→`Form("calc_id")`
wiring verified — htmx 1.9.12 JSON-parses hx-vals into form params). Tests:
`test_phase3_endpoints.py` (19, incl. both race_lost) + `test_phase3_needs_link_ui.py`
(10 compile-render). **Legacy `/admin/calc_link`** (raw UPDATE, no choke-point) left as
the documented Phase-3 fallback (plan §11); late-manual-link junction backfill +
operator_id (Phase 9) deferred.

**P3.T1 (task 241) shipped** — every `orders.link_status` write now routes through
the `core/link_state` choke-point (spec §3.6). Added `auto_classify()`, the
ENGINE-classification sibling of `transition()`: the matcher assigns link_status
from an UNDECIDED source (NULL on first arrival, or UNPLANNED on a re-run —
`order_enrichment._try_correlate` re-runs UNPLANNED orders, and UNPLANNED→LINKED is
an upgrade `transition()` correctly REJECTS since UNPLANNED is operator-terminal in
`LINK_TRANSITIONS`). So initial/engine classification can't go through `transition()`
— hence the separate entry point. Swept both raw-UPDATE sites onto it: the matcher
and bracket inheritance (`order_manager._propagate_bracket_calc_id`). `transition()`
stays reserved for the operator moves P3.T2/T3 wire (NEEDS_MANUAL_REVIEW→LINKED,
UNLINKED→UNPLANNED). `_emit_link_event` is shared by both so Phase 6 lights up both
at once. `AUTO_CLASSIFY_TARGETS = {LINKED, NEEDS_MANUAL_REVIEW, UNPLANNED}` (UNLINKED
is operator-only — fails loud if auto-assigned). Tests: `tests/test_phase3_link_state.py`
(14), incl. the load-bearing UNPLANNED→LINKED re-run upgrade. Bundled a one-line P2
audit-follow-up hardening: `_determine_exit_reason` now lowercases `order_type` (was
case-sensitive; harmless today since adapters canonically lowercase, but now
consistent with `_classify_final_exit_reason`).

**⚠ Environment note (task 241):** mid-task, `core/order_enrichment.py` was reverted
on disk by something OUTSIDE the session (a linter/editor, not the operator) AFTER a
green full-suite run — the matcher routing silently vanished (`git diff` for that
file went empty while the other two P3.T1 files survived). Re-applied + re-verified.
If a stale editor buffer of that file exists, a save could clobber it again. The
review workflow caught this only after fixing an aggregation bug in the review script
itself (see [[feedback-workflow-audit-aggregation]] memory).

**Phase 2 holistically RE-AUDITED (clean).** A 7-dimension adversarial workflow
(R1 convergence, junction integrity, close deltas/exit_reason, multi-TP completion,
bracket detect/inherit, PositionInfo/cache/rehydrate, cross-DB/hot-path safety) over
T2.1–T2.12 filed 8 candidate findings; **all 8 were adversarially refuted** —
5 mechanism-mismatch (3 repeating the SAME wrong belief that SQLite `ON CONFLICT DO
UPDATE SET` nulls omitted columns — it does NOT; only `INSERT OR REPLACE` does, so
`calc_id`/`link_status` survive redelivery), 1 race-framing, 1 unreachable-path
(the exit_reason case-sensitivity, now hardened anyway), 1 correct-by-design. I
independently re-verified the two highest false-negative-risk refutations: (a) the
exit_reason case-sensitivity is unreachable (every adapter lowercases `order_type`,
incl. the `otype.lower()` fallback in binance ws/rest); (b) the R1 "closing-fill vs
close-row primary divergence" is benign — both call the SAME `_position_primary_calc`
→ `_most_contributing_calc_id`, so R1's single-shared-rule guarantee holds; a
transient lag in the denormalized `fills.calc_id` leaves the authoritative
`closed_positions.calc_id` correct. The documented deferrals (a)–(i) stand
unchanged — none worse than recorded. **No code changes from the audit beyond the
one-line hardening.**

**Phase 2 (position-level attribution, plan §2) is fully shipped + independently
audited, T2.1–T2.12** (T2.10 was removed per spec §15 R2). Commit trail on this
branch: T2.1–T2.7 (tasks 226–235), T2.8 bracket detection (236), T2.9 TP/SL
calc_id inheritance (237), T2.11 multi-TP lifecycle (239), T2.12 restart
rehydrate (240). Each task: implemented surgically → independent adversarial
review (Workflow when ultracode on) → findings fixed → full suite green. Detailed
per-task notes are in the sections below + `docs/design/calc_linkage_implementation_plan.md` §2.

**What Phase 2 established (the invariants a Phase-3 task must not break):**
- `positions_calcs` junction (TEXT `position_id` = `terminal_position_id`) is the
  source of truth for position↔calc attribution; `lifecycle_id` UUID minted at
  first opening fill, denormalized across pre_trade_log/orders/fills/closed_positions.
- **R1 convergence**: the position's PRIMARY calc (spec §3.2: largest *summed*
  `contributed_qty` per calc, tie-break earliest `first_fill_ts`) is computed by
  the SINGLE shared selector `core/order_manager._most_contributing_calc_id` and is
  identical across all surfaces — `fills.calc_id` (T2.2), live `PositionInfo.calc_id`
  (T2.3/T2.12), `closed_positions.calc_id` (T2.6), and the T2.5 delta basis. Do not
  reintroduce a second primary-selection rule (T240 fixed exactly that divergence).
- TP/SL order rows get `calc_id` ONLY via bracket inheritance (T2.9
  `_propagate_bracket_calc_id`); the matcher skips reduce-only/close types.
- Multi-TP: per-partial `closed_positions` rows preserved; calc completion +
  ladder `exit_reason` (TP_LADDER_COMPLETE/MIXED) fire on the FINAL close (T2.11).

**NEXT — Phase 4 (amendment tracking + deviation, plan §4):** Phase 3 is fully shipped
(T1 task 241, T2+T3 task 242, T4 task 243). Phase 4 (depends on Phase 0 + Phase 2):
- **P4.T1 — SHIPPED (2026-06-02)**: `OrderManager.detect_and_persist_amendment` writes an
  `order_amendments` row per changed working-order field (entry_price/tp_price/sl_price/size),
  invoked from `ws_manager._apply_order_update` **before** `process_order_update`.
  **Pre-gate placement is load-bearing**: an amendment arrives as a `new→new` self-transition,
  which the SR-1 `validate_transition` gate REJECTS (no self-edges — order_state.py +
  test_order_manager.py:121, intentional anti-stale-replay), so a post-gate hook would never
  see it (my first attempt placed it post-gate in `process_order_update` — reverted). **Baseline
  chains off the last prior amendment's new_value** (the orders row goes stale because the gate
  rejects the amend upsert, so the amendment ledger is the authoritative chain). `deviation_pct`
  computed inline. **Deviations**: `leverage` is not on the per-order WS stream (documented gap);
  WS path only for the BATCH/REST path (deferred — needs a dedup key, order_amendments is
  immutable-insert). **Independent audit (9 agents) ran; 2 confirmed findings fixed**: (CORR-001/HIGH)
  `*_entry` stop/TP ENTRY orders (FE-13 suffix) read `stop_price` under the `entry_price` label —
  else a stop-market entry's trigger amendment silently drops (price==0); (ALGO-001) detection also
  wired into `_apply_algo_update` (defensive — no-op under Binance cancel-replace, but the engine
  observes Quantower). `trailing_stop` excluded (venue-automatic). 2 replay/out-of-order findings
  REFUTED (no reachable feeder; no-dedup-key is a deliberate spec/schema choice). Tests:
  `tests/test_phase4_amendments.py` (24) incl. chained-baseline + entry-stop regression; touched-path
  suites green.
- **⚠ FINDING (filed, fix as its own task) — `_detect_modification_events` is dead in production.**
  The existing TP/SL `tp_modified`/`sl_modified` trade-event detector (`order_manager.py`) is
  called from `process_order_update` AFTER the SR-1 transition gate, so for a pure price
  modification (`new→new`) it NEVER fires live (the gate returns False first). Its unit test
  (`test_modification_events.py`) only checks the comparison logic inline, masking this. Fix:
  relocate the call pre-gate to `ws_manager` (same shape as P4.T1), or fold the event emit into
  `detect_and_persist_amendment`. Surfaced during P4.T1; operator chose file-separately.
- **P4.T2 — SHIPPED (2026-06-02)**: `closed_positions.cumulative_amendment_count` computed at
  close in `_build_close_row_for_fill` via `db.count_amendments_for_calcs(contributing_calc_ids)`
  — counts `order_amendments` by the position's contributing calc_ids (entry + T2.9-inherited
  TP/SL legs, both denormalize calc_id). Added to `_CLOSED_POS_DELTA_COLS` (REPLACE-preserved like
  the T2.5 deltas; nullable → backfilled rows stay NULL). `deviation_pct` was already done in P4.T1.
  Tests: `tests/test_phase4_amendment_rollup.py` (10) + updated the T2.5 deferred-column assertion.
  240 touched-path tests green. **NOT yet committed** (audit pending).
- **P4.T3 — SHIPPED (2026-06-02)**: combined live deviation badge (spec §10.2 semantic ∪ §4.4
  thresholds — operator-chosen). `core.state.deviation_badge_level` (pure): red = no-calc OR
  |size_delta_pct| ≥ red_pct; yellow = amended (live amendment count > 0) OR |size_delta_pct| ≥
  yellow_pct; green = linked/on-plan/no-amendments. `amendment_count` + `deviation_badge` stamped
  onto each PositionInfo in `_enrich_positions_calc_id` (ONE grouped `count_amendments_by_calcs`
  query + one `read_account_config_async` per refresh — NO per-render DB hit; both in
  `_PRESERVE_FIELDS`). Inline render via new `templates/primitives/deviation_badge.html` macro on
  the live positions row. **Deviation**: live TP/SL-vs-planned drift deferred (needs `planned_tp/sl`
  on PositionInfo). **Audit: 1 MED fixed** — thresholds DEFAULT to spec values (config read first)
  so a transient amendments-query failure can't strand `red_pct=0.0` (would paint every linked
  position red); rest verified clean. Tests: `tests/test_phase4_deviation_badge.py` (18); touched-path green.
- **P4.T4 — SHIPPED (2026-06-02, task 249)**: emit `position:amended` on each persisted
  `order_amendments` row, as a **trade event** (`log_trade_event` → `"position_amended"`, registered in
  `TradeEventType`). **Mechanism = trade event, NOT event_bus** — the §9 event_bus topic map
  (`TRANSITION_EVENT_MAP` in calc_state/link_state) is empty-until-Phase-6 by design, plan §6 row 6.4
  explicitly schedules the event_bus emission for Phase 6, and the precedent (`partial_close`/
  `position_opened`, T238) emits trade events now with the event_bus topic deferred. New sync helper
  `OrderManager._emit_amendment_event` (sibling of `_emit_fill_events`) called from **inside**
  `detect_and_persist_amendment`'s loop — **NOT** the ws_manager seam the prior HANDOFF suggested: the
  per-row `field`/`old`/`new` only exist inside the detection loop, it mirrors the `_emit_fill_events`
  convention (trade-event emission lives in order_manager), and it avoids double-emitting across both
  `_apply_order_update` + `_apply_algo_update`. `insert_order_amendment` now returns `bool`; the event
  fires **1:1 on a confirmed commit** (swallowed insert → no event → "events = row count" parity holds).
  Payload = exact §9 keys (`position_id`/`order_id`/`field`/`old`/`new`/`ts`/`operator_id`);
  `position_id` from the stored order's `terminal_position_id` (`""` for a pre-fill entry order),
  `operator_id` None (Phase 9). **Completeness sweep**: `position_amended` added to both `TradeEventType`
  mirror dropdowns (`templates/fragments/history/trade_events_table.html`, `templates/admin/trade_events.html`)
  — exhaustive lists, leaving them stale is silent enumerated-mirror drift. **Independent audit (6 agents):
  1 HIGH confirmed + fixed** — the sync `log_trade_event` (its own sqlite3 conn) on the WS hot path is now
  dispatched via `asyncio.to_thread` (T212/P3.T2 convention for new sync-sqlite-in-async; **safe** — verified
  `_emit_amendment_event` never touches the aiosqlite `_conn`). This **reverses** my initial sync-mirror-of-
  `_emit_fill_events` decision: the more-recent audit-established convention (Rule 6) is to_thread; the
  sibling `_emit_fill_events` predates it (same exposure → **filed**, not retrofitted, Rule 3). Tests:
  `tests/test_phase4_amendments.py` 31 (was 24; +7 `TestPositionAmendedEvent`) + an autouse `log_trade_event`
  capture fixture that shields ALL tests (incl. the 24 P4.T1 ones) from live-DB writes — verified **0** live
  `position_amended` rows after the full 2921-test suite. Full suite: 2921 passed, 7 skipped, 1 pre-existing
  failure (TestRollingWindowPeak), 0 new failures.
- **NEXT after T4**: P4.T5 (`tp_drift_pct`/`sl_drift_pct` at close — needs final-amended TP/SL, the same
  data the deferred AMENDED exit_reason reclassification wants). Then the `_detect_modification_events`
  dead-path fix (filed). Phase 4 is then complete (T1–T5).
- **⚠ FILED (P4.T4 audit) — `_emit_fill_events` sync-sqlite-in-async consistency cleanup.** The sibling
  trade-event emitter `_emit_fill_events` (called sync from `process_fill`, hot fill path) has the SAME
  blocking exposure P4.T4's audit flagged on `_emit_amendment_event` (sync `log_trade_event` → its own
  sqlite3 conn, no `asyncio.to_thread`). It predates the T212/P3.T2 to_thread convention and was left
  un-retrofitted (Rule 3 — P4.T4 stayed surgical). Wrap it (and grep for any other un-retrofitted
  sync-`log_trade_event`-in-async callsites) in its own cleanup task. Safe pattern: it must not touch the
  aiosqlite `_conn` (it doesn't — `log_trade_event` opens a separate sqlite3 conn).
- **⚠ FILED (observed during P4.T4) — trade-event test pollution of the LIVE per-account DB.** Running
  `test_order_manager` / `test_om5_tpsl_matching` (and any process_fill/close-row test with `account_id=1`,
  which EXISTS live) writes real `position_closed`/`order_filled` rows into
  `data/per_account/quantower__binancefutures__binance.db` via the un-isolated `_emit_fill_events` /
  close-row `log_trade_event` calls (they resolve `config.DATA_DIR`, not a temp dir, and don't monkeypatch
  it the way `test_trade_event_producers` does). PRE-EXISTING (P4.T4 did NOT introduce it — its own emit is
  fully isolated by an autouse capture fixture, verified 0 live `position_amended`). Fix: a session-scoped
  conftest autouse that points `config.DATA_DIR` at a tmp dir for the suite, OR per-file capture fixtures.
  Not touched here (live-DB rows are operator-owned; the cleanup is its own task).
- **P4.T3** — live deviation badge logic + frontend (yellow/red thresholds from
  `config_json`; spec §3.2 most-contributing-calc basis). **Consumes T2.12's
  `PositionInfo.size_delta_pct`** (already stored; the badge threshold logic is the
  Phase-4.4 consumer).
- **P4.T4** — `position:amended` event; **P4.T5** — `tp_drift_pct`/`sl_drift_pct` at close.
- Reclassify `exit_reason` *_PLANNED → *_AMENDED on the close-row rebuild seam once
  amendment data lands (the T2.7 deferral).

**Phase-3 deferred carry-forwards** (file/address as Phase 3 follow-up):
- **`UNLINKED` is defined-but-unproduced forward scaffolding** (Phase-3 audit observation).
  Nothing sets `link_status='UNLINKED'`: the matcher emits `NEEDS_MANUAL_REVIEW` for the
  "candidates exist but no full match" case (calc_correlation.py:52-56 — a deliberate
  Rule-6 pin), `auto_classify` excludes UNLINKED, and the operator handlers reach only
  LINKED / UNPLANNED. So the UNLINKED branches in the needs-link queue/counter `WHERE`,
  the `link_status_badge` macro, and the `LINK_TRANSITIONS` edges are harmlessly DEAD —
  but fully wired to activate the moment a producer is added (like Phase-1's
  `partially_actioned`, spec §16). Decide later: wire a producer (operator "unlink", or
  matcher "rejected-all" → UNLINKED per spec §2[B]) OR prune the dead branches.
- Order-side TP/SL early-return gate: a no-TP/SL order never reaches the matcher → never
  classified (link_status stays NULL → "—" badge; plan §3 row 3.2 residual).
- Late-manual-link does NOT retro-create `positions_calcs` junction rows (offline rebuild).
- The legacy `/admin/calc_link` raw-UPDATE surface (sets calc_id WITHOUT link_status, no
  choke-point) should be REMOVED now the needs-link tab is shipped (plan §11 compat shim).
  The audit confirmed it can now create a `calc_id`-without-`LINKED` order that the new
  badge/queue assume away — bounded (operator must use the legacy admin page), but the
  cleanest fix is to retire the page (or route its confirm through `manual_link_order`).
- Deployment context is single-tenant localhost (CLAUDE.md, Task 163): no auth/CSRF
  work; threat model is correctness + observability + recovery.

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
| P1.T1 | Strict 6/6 matcher (LIMIT + MARKET; entry source differs) + per-criterion audit | 210 (b667616); audits 211 (fbd3569), 212 (f174511) |
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

### Restart rehydrate — contributing_calc_ids + live size deviation (T240 / P2.T12)

The LAST Phase-2 task. `PositionInfo` gained two fields (state.py):
`contributing_calc_ids: List[str]` (all junction calcs for the position,
primary-first then contributed_qty desc) and `size_delta_pct: float` (live
size deviation). Both populated by EXTENDING T2.3's
`_enrich_positions_calc_id` — the key insight is that method **already runs
at startup** (`_startup_fetch` → `process_order_snapshot` → `refresh_cache`)
and authoritatively re-derives from the persisted `positions_calcs` junction,
so "restart rehydrate" needed no new exchange.py/startup hook (a separate one
would duplicate the authoritative re-derivation and risk divergence —
deliberate deviation from the plan's stated files).

All three junction-derived fields (calc_id, contributing_calc_ids,
size_delta_pct) are AUTHORITATIVE (mirror the junction each refresh; CLEARED
to ""/[]/0.0 when no junction) and added to `DataCache._PRESERVE_FIELDS` so a
snapshot rebuild between refreshes doesn't blank them.

`size_delta_pct = (Σ contributed_qty − primary calc's planned_size) /
planned_size × 100` (signed; spec §3.2 most-contributing basis; mirrors the
T2.5 close-time size_delta). 0.0 when no junction or no planned_size snapshot.
Per-(position,calc) contributed_qty is summed (a calc may place >1 order on a
position → multiple junction rows); ties on contributed_qty resolve to the
earliest first_fill_ts (same rule as `_position_primary_calc`).

**Deferred (Phase 4.4, documented)**: the yellow/red deviation BADGE
thresholding + TP/SL live deviation — they need the order-amendment tracking
(Phase 4.1/4.3) + live TP/SL that isn't wired yet. T2.12 stores the size
DELTA (the badge input); the badge/threshold logic is the Phase-4.4 consumer.
The `calc:size_deviated` event is Phase 6.2.

Tests: `tests/test_phase2_rehydrate.py` (14) — single/scale-in/tie-break/
multi-order-same-calc/no-junction-clear/underfill/no-planned/empty-tpid/
multi-position + _PRESERVE_FIELDS membership + dataclass defaults + the
convergence pair below.

**T240 review (4 dimensions → adversarial verify; 24 candidates, 1 confirmed)
— HIGH primary-selection divergence FOUND + FIXED:** the review confirmed
(and I'd independently flagged) that the new live `_enrich_positions_calc_id`
selected the primary by **summed-per-calc** contributed_qty, while
`_position_primary_calc` (the canonical helper behind the close path —
T2.2 closing-fill stamp, T2.5 deltas, T2.6 closed_positions.calc_id) selected
the max **single ROW**. For a calc placing >1 opening order on one position
(multiple `(pos,calc,order)` junction rows) these diverge → the live
PositionInfo.calc_id could disagree with the sealed closed_positions.calc_id
+ wrong close-delta basis — violating the R1 convergence guarantee T2.6
asserted closed. **Root cause was `_position_primary_calc`, not the new code**:
spec §3.2 ("largest contributed_qty") + §12.4 (junction
`contributed_qty = SUM(fill_qty)` grouped by `(position, calc_id)`) intend
the per-CALC SUM, so the aggregated side was spec-correct. **Fix**: extracted
a shared pure selector `_most_contributing_calc_id(ordered_rows)` (sums per
calc, earliest-first_fill tie-break) and routed BOTH `_position_primary_calc`
and `_enrich_positions_calc_id` through it — all four surfaces now converge on
the spec-correct aggregated rule by construction. Existing close-path tests
(one-order-per-calc → summed == max-row) are unaffected; added a convergence
test seeding a multi-order calc that out-sums a larger-single-row rival. The
other 23 review candidates were adversarially refuted (size_delta basis is
spec-compliant, _PRESERVE_FIELDS list-aliasing is safe since enrich reassigns,
no positional-construction/serialization breakage).

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
