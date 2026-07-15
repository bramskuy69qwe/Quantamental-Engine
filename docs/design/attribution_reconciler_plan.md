# Attribution reconciler — design + phased plan

**Status**: DESIGN rev 2 (2026-07-15) — rev 1 + the 2-agent adversarial
design review folded (feasibility-vs-code + program-consistency; both
verdicts REVISE, all amendments incorporated below; review record in the
commit body). Operator go given for the design doc; each build phase below
is separately operator-gated.
**Origin**: linkage battery §7 decision (`docs/design/linkage_battery_plan.md`,
commit `dac427b`) — build the reconciler scoped to identity ownership
(families 1+3); corr-log spec §12 is the observability seed; HA-42 (mechanism
corrected as LB-F8) is the first filed input.
**Prime directive**: ONE module owns fill→position→calc identity. Consumers
read; they never re-derive. Retroactive reconciliation is a first-class duty,
not a per-site backfill.
**Code line refs are pinned @ `02eb743`** — guides, not contracts;
verify-first at each phase (battery plan §3 rule).

## 1. Problem statement (evidence, not theory)

Identity (terminal_position_id, lifecycle_id, junction membership, closed-row
calc/lifecycle pair) is currently derived ad-hoc at ~9 sites, each with its
own rule. The battery (53 deterministic tests = 48 green pins + 5
strict-xfails, 2026-07-14/15) proved the cost:

| Finding | Mechanism (verified at source) | Status |
|---|---|---|
| LB-F1 | manual-link lane never formed the junction (replay was auto-lane-only) | fixed `d9ff4bf` — a LANE patch; the root remains |
| LB-F6 (=LB-D5) | mixed-tpid fills of one order key TWO junction rows + two lifecycles | **fixed at R2** (key migration; xfail flipped) |
| LB-F8 (=HA-42, corrected) | replay guard checks the ORDER-stash tpid while the write lands under MAX(fills.tpid) → guard never satisfies → N-fold unbounded `contributed_qty` inflation per WS/bracket-child event (gated: needs a divergent stash — "unbounded amplifier behind a narrow gate", battery severity framing) | **fixed at R2** (guard≡write; xfail flipped) |
| LB-F9 (=LB-T2d) | fill-before-mint first fill permanently stranded from the junction (under-count, mirror of F8); reversal open legs land in the same shape | **fixed at R3** (mint-after-fill retro-sweep + delta-reconcile; xfail flipped) |
| LB-F4 (=LB-I5) | lifecycle mint/reuse has no seal-at-close → tpid reuse bleeds a closed trade's lifecycle into the new trade | **fixed at R4** (seal-at-close; xfail flipped) |
| LB-F7 (=LB-D6) | closed-row REPLACE binds calc_id unconditionally but carries lifecycle_id forward → mixed identity pair | **fixed at R4** (pair-gated carry-forward; xfail flipped) |
| LB-F5 | ⑨ resolved by (symbol,side) heuristics before the parent-order signal | fixed `02eb743` — tier-0 + stamp; heuristic tail pinned |
| LB-D4 | offline/rebuild close-row calc rule (earliest-fill) diverges from the live rule (junction-primary) — a consumer re-deriving with a DIFFERENT rule | **fixed at R4** (rule delegated to the owner's §3.2 helper; T3 scenario shipped) |

(Family 4 — LB-F2/F3 choke-point bypasses — fixed `c636772` and closed;
they are the proof that *routing* bugs patch cleanly.)

Decision rule the battery established (§7): **routing bugs patch cleanly;
derivation bugs multiply sites** — every family-1 spot fix either adds
another ad-hoc site (F9 needs a sibling-fill backfill lane) or answers
"which tpid is canonical?" per-site (F6, F8), which IS the reconciler
question.

## 2. The identity owner

New module `core/position_identity.py` (working name; NOT "reconciler" in
code — `core/reconciler.py` already exists for MFE/MAE). One class,
`PositionIdentity`, constructed by `OrderManager.__init__(db)` (preserves
v2.6 task 1.1's "takes only `db`" contract) and extracted WITH OrderManager
in v2.6.

### 2.1 Responsibilities

1. **Canonical tpid derivation** — `canonical_tpid(account_id, eoid) -> str`:
   ONE derivation policy (persisted order stamp → live mint → fills-derived),
   every consumer reads it. The ⑨ tier ladder and the Defect-7
   order-fallback become internal details of this one function instead of
   per-site copies. **No cross-call memo in R1** — derive per call (one SQL
   read; the fill path already runs 6-10 awaited statements). Memoization is
   a later, evidence-driven optimization and REQUIRES the §5-Q1
   invalidation contract first (key migration, the rebuild lane, and
   multi-instance construction all mutate what a memo would cache).
2. **Junction writes keyed only through the canonical tpid** — the
   guard-key ≡ write-key property holds BY CONSTRUCTION (kills F8: the
   exists-check and the UPSERT use the same key from the same call). All
   `upsert_position_calc_link` callers route here.
3. **Retroactive reconciliation** on late identity:
   - *mint-after-fill* (F9): when the canonical tpid first materializes for
     an eoid, sweep that order's earlier fills (tpid='' → stamp) and fold
     their qty into the junction (idempotency mechanism: §5 Q2).
   - *link-after-fill* (F1's generalization): the existing
     `_ensure_junction_if_linked` replay moves in and gains the canonical
     key. NB both replay lanes emit late `position:opened`/`scale_in`
     (LB-R3 residual) — R3 inherits that design consideration; suppression
     becomes mandatory the moment a `position:opened` subscriber exists.
   - *key migration* (F6): when fills arrive under a different tpid than the
     junction's existing key for the same economic open, MIGRATE the
     junction row to the canonical key AND re-stamp the affected fills'
     tpids in the same pass (a migration that moves only the junction row
     would break any fills-keyed recompute — feasibility-review MAJOR-2).
4. **Fill attribution stamping** — the fills.calc_id/lifecycle writers
   (matcher link-time backfill `order_enrichment.py:418`, fill-time
   propagation `:688`, manual-lane propagation `link_actions.py:241`)
   DELEGATE to the owner's stamp-at-registration so entry-fill parity has
   one governor (feasibility-review MAJOR-3).
5. **Lifecycle mint + seal** (F4): mint on first opening fill (as today);
   SEAL on the final close (the same event that fires
   `_complete_calcs_on_close`); the mint/reuse lookup ignores sealed
   lifecycles → tpid reuse mints fresh.
6. **Closed-row identity-pair coherence** (F7 + LB-D4): the close-row
   builder asks the owner for the (calc_id, lifecycle_id) PAIR;
   `insert_closed_position`'s per-column REPLACE rules collapse to one
   pair-coherent bind — and the OFFLINE rebuild lane (LB-D4) asks the SAME
   owner instead of re-deriving earliest-fill.

### 2.2 What it does NOT own (scope fences)

- The **matcher** (calc_correlation 6/6) and link_state/calc_state
  choke-points — linking WHO stays where it is; the owner consumes the
  result. (Family 4 proved the choke-points sound.)
- Badges/display (state.py), exit-reason classification, funding assignment
  (funding_handler consumes via the injected `primary_calc_resolver` —
  it just switches to the owner's resolver).
- **The engine-runtime offline-recovery rebuild lane**
  (`schedulers.py:529` → `exchange_income.py:727 recover_offline_trades` →
  `db_orders.py:1786-1864`): DELETEs closed rows per gapped symbol,
  re-mints deterministic `rebuilt:` tpids via `position_grouping.py`, and
  rewrites `fills.terminal_position_id` — a competing tpid policy running
  on a schedule (feasibility-review MAJOR-1). R1-R4 FENCE it with an
  explicit contract: the rebuild announces itself to the owner
  (invalidate/no-memo makes this trivial in R1; §5 Q1 governs later), its
  `rebuilt:`/`bf:` tpid namespaces never collide with live keys (existing
  invariant), and the owner's retro/heal passes are EVIDENCE-GATED so they
  never mutate rows whose fills live under rebuilt namespaces (§5 Q2).
  ABSORBING the lane (rebuild asks the owner for tpids) is a candidate
  R5+/T3 follow-up, alongside the LB-D4 close-calc rule delegation (§2.1.6).
- The one-way BOTH gap (LB-T2h) — documented deployment fence, unchanged.
- Historical residue backfill (SPCX ungrouped fills etc.) — optional
  follow-up script under the live-DB dry-run discipline, NOT part of the
  engine change (though §5-Q2's delta-reconcile, if adopted, heals
  F8-inflated / F9-starved junction rows for free).

### 2.3 Observability (corr-log §12 contract — with a NAMED deviation)

The 10 `attr_*` categories KEEP their names and payload shapes; their emit
sites move into the owner. **Deviation from spec §12's "single
`attr_decide`" (§12 :882, §5.6-close :488-491), named per the deviation
discipline**: keep-the-10 + add ONE new category `attr_identity_reconcile`
INSTEAD OF collapsing to `attr_decide`, BECAUSE the faithful-consolidation
proof §12 itself mandates (pre/post `attr_*` stream diff on replayed
scenarios) only works if category names are stable across the move —
collapsing would reduce the proof to a name-mapping exercise. Spec erratum
**E36** at R5 corrects §12/§5.6-close accordingly, plus the §3
`component` closed-ish set (gains `position_identity`) and the §5.6 site
column (verified: cookbook recipes and `corr_tail.py` filter by
category/corr_id/symbol, never by component — no tooling contract breaks).
`attr_identity_reconcile` covers the genuinely new decisions: retro-sweep,
key migration, lifecycle seal. Phase R1 (pure move) must produce an
envelope-equivalent stream (modulo `component`); later phases change
decisions ONLY where a ledger finding says so, each flipping a named
battery xfail.

**SUPERSEDED at R5 (second-order deviation, named)**: the
`attr_identity_reconcile` category proposed above was NEVER added — the
R2 implementation rode the new decisions as `attr_junction_form`
OUTCOMES (MIGRATED, then RECONCILED at R3, SEALED at R4) pending E36,
and E36 RATIFIES that as the final design (rationale in the erratum +
§4-R5). The keep-the-10 half of this paragraph stands as shipped; only
the new-category half is superseded.

## 3. Consumer disposition (the identity-writing sites @ `02eb743`)

| Site (today) | Disposition |
|---|---|
| `_resolve_close_tpid` (⑨, order_manager.py:2029) | MOVES — becomes `canonical_tpid` + close-context wrapper; tier policy unchanged from `02eb743` |
| close-order tpid stamp (`_process_single_fill`, LB-F5) | MOVES — owner stamps as part of canonical registration |
| `_link_position_calc_on_open` (:2225) | MOVED WHOLE incl. the `position:opened`/`scale_in` emissions — **R1 decision (2026-07-15): events moved WITH the builder**, because (a) at HEAD the emissions were already the TAIL of the builder itself (the ":2539-2556 stay at the call site" framing here was imprecise — R1 audit) and (b) the Defect-8 replay lane reaches the builder too and historically emitted through it; a contract-return would have dropped replay-lane events. See position_identity module docstring |
| `_ensure_junction_if_linked` (:559) | MOVES — the link-after-fill retro path, canonical-keyed (guard≡write). NB its HA-28 SKIP-dedup memo (`_attr_skip_is_repeat` :544) is SHARED with the bracket-inheritance tap (:776, stays behind) — R1 must state where the memo lives (split it; shared-LRU eviction coupling is not worth preserving) |
| `_backfill_open_fill_tpids` (:3115) | RETAINED as the close-time backstop (R3 correction — the mint-after-fill sweep covers the mint-event lane, but calc_id parity + the no-later-tpid-event tails still need close-time healing; reversal open legs heal here, on the walk path) |
| fills.calc_id writers: `order_enrichment.py:418` (link-time backfill, "the primary fix"), `:688` (fill-time propagation), `link_actions.py:241` (manual lane) | DELEGATE — owner stamps fills at registration/retro-sweep (feasibility-review MAJOR-3) |
| `_stamp_closing_fill_attribution` (:2558) | DELEGATES — reads the owner's (calc, lifecycle) pair for the position |
| `_build_close_row_for_fill` calc/lifecycle sealing (:3414/:3557) | DELEGATES — asks the owner for the pair; REPLACE coherence rule lands in `insert_closed_position` alongside. **R4: shipped** — pair-gated carry-forward + the builder now also calls the owner's `seal_position_lifecycles` at `is_final` |
| `_enrich_positions_calc_id` live re-derive (:2659) | DELEGATES for identity (tpid recovery), keeps display enrichment |
| offline-recovery rebuild lane (schedulers :529 → db_orders :1786-1864) | FENCED R1-R4 (contract in §2.2); ABSORB candidate at R5+/T3. **R4: the LB-D4 close-calc RULE delegated** (`position_grouping._build_row` → the owner's §3.2 helper); the tpid re-mint policy stays fenced |
| `scripts/` tooling (`backfill_calc_linkage.py:474` junction+lifecycle mint, `rebuild_closed_positions.py:297` + `synth_legacy_open_fills.py:623` fills.tpid, `backfill_entry_fill_calc_id.py`) | EXEMPT from acceptance #4 by name — operator-gated dry-run tooling, not engine runtime; revisit post-R5 |

## 4. Phased plan (each phase = one operator-gated task, full-suite + battery gates, independent audit, AND the acceptance-#4 broad re-grep — run per phase, not only at R5)

- **R0 — acceptance freeze** (THIS doc): the battery is the harness; the 5
  xfails (LB-D5, D6, I5, T2d, T2e) are the acceptance set; 48 pins are the
  behavior-preservation set (grows as phases add pins). LB-D4 gets its T3
  battery scenario before/with R4.
- **R1 — pure extraction**: create the owner; MOVE code with rules verbatim
  (no behavior change). Named frictions to resolve, not discover:
  `self._db._conn` carry (anchor-comment the deliberate Phase-6-pattern
  carry or route through public helpers at move time), the SKIP-dedup memo
  split, the `_link_position_calc_on_open` delegate return contract. Gate:
  all pins green, xfails still xfail, corr-log faithful-consolidation diff
  clean on the battery scenarios.
- **R2 — canonical key + guard≡write** (**DONE 2026-07-15**): killed F8 +
  F6 (`LB-T2e` + `LB-D5` xfails flipped). Replay derives the
  fills-aggregate write key first and guards on it (guard ≡ write by
  construction); builder migration pass merges/re-keys stale (calc,
  order) junction rows to the canonical key, re-stamps affected fills
  (§2.1.3), and — named extension — corrects the order's stale stash
  (a surviving stash keeps feeding ⑨ tier-0/the guard the dead key).
  New `MIGRATED` tap outcome (→ E36). `perf`-marked fill-pipeline
  micro-benchmark added (`tests/test_position_identity_perf.py`, 150 ms
  p50 tripwire). LB-F5 residual adopted: tier-0 reduce-only gate.
- **R3 — retroactive reconcile** (**DONE 2026-07-15**): killed F9
  (`LB-T2d` flipped). Mint-after-fill retro-sweep in the builder: a
  tpid-carrying fill stamps pre-mint sibling fills (tpid + lifecycle)
  and **delta-reconciles** the junction row — §5-Q2 DECIDED:
  delta-reconcile adopted with the review constraints (evidence-gated:
  no fills → NO-OP; keyed by ORDER eoid, never raw fills.tpid;
  SUM(ABS); on-change only, RECONCILED tap — the R2 MIGRATED-outcome
  precedent, → E36). The R2 direction gate EXTENDS to the sweep
  (traced: an ungated sweep double-counts the mirror-ordering
  mid-state). Free heal: F8-inflated/F9-starved HISTORICAL rows correct
  themselves at the next fill/replay event. Hand-off (b) fixed: replay
  guard now includes order_id (second-order-same-calc replays; battery
  pin). CORRECTION to this bullet's original claim: reversal open legs
  do NOT heal "on the next ACCOUNT_UPDATE mint" (no event reaches the
  order) — they heal AT CLOSE via the retained backfill backstop (on
  the strict-miss→walk path — R3-audit NIT-3 qualifier); the
  no-later-tpid-event tail (incl. hand-off (a)'s residue) remains
  bounded, noted for R5/T3. R5 riders from the R3 audit: lifecycle
  sweep gains a rebuilt-namespace tpid filter (NIT-6, fence-structural
  vs reachability-argued), T2d/T2e test banners get [FIXED] annotations
  (NIT-5).
- **R4 — lifecycle seal + pair coherence** (**DONE 2026-07-15**): killed
  F4 + F7 (`LB-I5` + `LB-D6` xfails flipped — the LAST two; the §6-1
  acceptance set {LB-D5, D6, I5, T2d, T2e} is now EMPTY).
  **Seal-at-close (F4)**: §5-Q3 DECIDED — `positions_calcs.sealed_ts`
  column (INTEGER NULL; CREATE + ALTER + the P2.T1-recreate DDL), NOT
  the no-DDL closed-row-existence gate, BECAUSE closed_positions has one
  row PER closing order (T2.11 partial rungs) so row-existence would
  seal on the first partial and break scale-in lifecycle continuity,
  and a fills-sum finality check is self-polluting in the exact reuse
  scenario it must detect (the new trade's first fill unbalances the
  sums before the lookup runs). `seal_position_lifecycles` (owner)
  stamps the FINAL close's `exit_time_ms` (data-derived, idempotent)
  on the position's junction rows, called from
  `_build_close_row_for_fill` at `is_final` — the
  `_complete_calcs_on_close` moment; partial rungs never seal. The
  mint/reuse lookup ignores sealed rows, with an OWN-TRIPLE exception
  (a sealed row for this exact (position, calc, order) still supplies
  its lifecycle — a late fill of a sealed trade's own order continues
  THAT trade instead of minting a phantom lifecycle + spurious
  position:opened; a new trade always arrives on a new order). SEALED
  tap rides `attr_junction_form` (→ E36), emitted on-change only.
  **Pair coherence (F7)**: `insert_closed_position`'s lifecycle
  carry-forward is PAIR-GATED on calc_id — carry only when the calc is
  unchanged (the T232 preserve case, deterministic re-derivation); a
  REPLACE that REBINDS the calc takes the REPLACing writer's whole
  pair. calc_id stays unconditionally bound (T234). The funding
  reconcile is a targeted UPDATE by row id (not a REPLACE) — no
  interaction (audit charge traced).
  **LB-D4**: `position_grouping._build_row` close-calc rule delegates
  to the owner's §3.2 selection helper (`_most_contributing_calc_id`
  over the opening fills — same RULE as the live builder; the evidence
  stays fills-only since the rebuild lane has no junction access, and
  junction `contributed_qty` IS SUM(fill qty) per calc so the two
  converge whenever opening fills carry calc stamps). T3 battery
  scenario drives `rebuild_closed_positions_for_symbol` on the LB-D2
  shape → rebuilt row takes B (primary), not A (earliest). The lane's
  tpid re-mint policy stays FENCED (§2.2) — only the RULE delegated.
  New pins: seal stamps/partial-no-seal/scale-in-continuity/own-triple
  late fill/carry-forward-when-calc-unchanged.
  **R4-audit folds (verdict SHIP-WITH-NITS; all three folded
  pre-commit)**: M1 — the disappearance backstop's
  recorded-but-never-final lane (`build_final_close_row`, unrecorded
  EMPTY — the WS-gap shape) completed calcs but never sealed; it now
  seals from the final recorded close row's `exit_time_ms` (fills-max
  fallback; no evidence → skip), battery-pinned. M2 — the R2
  key-migration RE-KEY branch transported a stale `sealed_ts` onto the
  canonical key (reversal-split stash mis-key shape → live trade's only
  lifecycle row frozen sealed → phantom mint on scale-in); re-key now
  resets `sealed_ts` to NULL (the canonical close re-seals; the MERGE
  branch was already correct). M3 — the builder's seal is
  EVIDENCE-GATED (`force_final or total_open_qty > 0`): the
  opens-unresolvable degraded lane sets `is_final` as a completion
  fallback, and sealing there on a partial would split a live
  lifecycle; that lane still seals at authoritative disappearance via
  M1.
  KNOWN RESIDUALS (documented, R5/T3 candidates): (a) with a
  venue-reused tpid, `position_primary_calc` still reads ALL junction
  rows for the tpid (sealed + fresh), so a close of trade 2 on a reused
  slot can rank trade 1's calc into the primary — identity keyed on
  position_id cannot fully separate two trades sharing a tpid; the seal
  fixes the LIFECYCLE bleed (the filed F4 mechanism). Live adapters
  never reuse tpids (mint includes entry_ms). (b) R4-audit N1: the seal
  rides the +2s-deferred close-row build — a reused-slot fill landing
  inside that window still bleeds; and a late-overfill re-run keeps the
  FIRST sealed_ts (`WHERE sealed_ts IS NULL` never refreshes).
  (c) R4-audit N2: offline-closed positions never seal (the
  recovery/rebuild lanes don't touch `positions_calcs`) — trades that
  final-closed while the engine was down keep unsealed junction rows
  under their venue tpids.
  (d) **R5-holistic MED-1 (filed, not fixed)**: a junction row formed
  AFTER the final-close seal on the same tpid (manual-link-after-close
  replay; a genuinely late different-order fill) is unsealed by
  construction, so the R5 unsealed-basis rule ranks the straggler ALONE
  on a later close-row rebuild — a minority late-linked calc can
  out-rank the sealed majority (pre-R5 the joint basis kept the
  majority; the straggler also mints a phantom lifecycle + spurious
  position:opened — the R4-known wart). ⚠ The audit's proposed fix
  (inherit the seal whenever all existing rows are sealed) is WRONG —
  it would seal a reused-slot NEW trade's first row at birth and break
  LB-I5's fix (scale-in would mint a third lifecycle). CORRECT fix
  shape (traced): inherit the seal only with FILL-TIMESTAMP EVIDENCE —
  the straggler's opening fills all predate sealed_ts; a new trade's
  post-date it. Needs its own battery scenario; reachability is
  operator-manual-link-onto-a-closed-trade + a late close rebuild.
  (e) R5-holistic LOW-2: on a reused tpid, T238's interleaved
  per-rung builds can seal between one build's primary read and its
  deltas read (basis flips mid-build) — fix shape: pass the primary
  pair into `_compute_close_deltas` instead of re-reading.
  (f) R5-holistic LOW-4 (pre-existing, not program-introduced): the
  sticky `_tpsl_amended_seen` stash is raw-tpid-keyed and prune-timed
  at the final build — a reused tpid can inherit the dead trade's
  amend level on its close row. Same reuse family; not junction-based
  so the basis rule can't cover it.
- **R5 — close-out** (**DONE 2026-07-15**): xfail markers were already
  gone (each flip removed its marker in-phase — verified zero live
  markers). **E36 FILED with a NAMED DEVIATION from this plan's §2.3**:
  `attr_identity_reconcile` was NOT added — the outcome-riding shipped
  at R2–R4 (MIGRATED/RECONCILED/SEALED on `attr_junction_form`) is
  RATIFIED as final, BECAUSE the new decisions are junction-row
  mutations inside the formation flow (same identity tuple / dedup_key
  family / corr chain as FORMED — a separate category would split one
  decision flow across two greps), category-name stability is what the
  §12 faithful-consolidation proof runs on, and outcome churn is
  cheaper than registry churn (46-category registry snapshot-pinned;
  no tooling filters between attr categories — verified). E36 also
  records the §3 component-set addition (`position_identity`) and the
  §5.6 site-column read; cookbook gained the outcome vocabulary + the
  seal dedup_key. **R3-audit riders shipped**: NIT-6 — the R3
  lifecycle sweep gained the STRUCTURAL `rebuilt:`/`bf:` namespace
  fence (was reachability-argued; battery-pinned), NIT-5 — T2d/T2e
  banners carry [FIXED] annotations. **R4 residual (a) FIXED**:
  `position_primary_calc` AND the live-enrich twin now rank the
  UNSEALED rows as the selection basis (fall back to ALL rows when
  none unsealed, so post-close REPLACE-rebuilds keep their original
  primary — no earliest-fill degradation); a reused-slot trade 2's
  close-fill stamp / close row / live badge carry ITS pair even when
  the sealed trade contributed more (battery-pinned, decisive 3.0-vs-
  1.0 shape). Residual narrows to two SEALED trades sharing a reused
  tpid (rebuild-time ranking joins them — documented, live adapters
  never reuse). COUNT CORRECTION (honesty): at R4 commit the battery's
  true count was **59** (5 files) — R4's "62" claim conflated a 6-file
  run; R5's three pins (NIT-6 sweep fence, reused-slot close identity
  + live-enrich twin, migration rebuilt-namespace fence) bring it to
  **62**. The optional
  historical-residue backfill script was DEFERRED (named deviation):
  the R3 delta-reconcile already self-heals junction rows on touch,
  the remaining residue is operator-parked cosmetic data (SPCX
  ungrouped fills), and building a destructive live-DB tool
  unprompted contradicts the operator-gated dry-run discipline —
  available on request. Holistic 3-agent audit run + folds recorded in
  the R5 commit. Remaining §6 acceptance item: **#5 live dogfood**
  (operator-driven open→amend→close with `CORR_LOG_PROFILE=linkage`)
  — flagged to the operator; everything self-verifiable is green.

Sequencing: R1–R5 BEFORE v2.6's OrderManager extraction. Precise rationale
(consistency-review MINOR-4): v2.6 Phase 1 moves the CONSTRUCTION site
(`core/order_manager_singleton.py`), not the class body — so the ordering
is not about moving owned code, it is about (a) not churning the same hot
file under two concurrent programs and (b) the battery pins guarding the
extraction for free. Cross-ref added to the v2.6 plan §6. LB-R1/R2
(admin-UI encoding, sweep compound-edge) are unaffected by this program.

## 5. Open questions (resolve in R1 review, not silently)

1. **Memo/instance contract**: rev-1 proposed an instance-owned memoized
   registry; the feasibility review killed the naive version — the LB-F1
   fix itself constructs a THROWAWAY OrderManager (link_actions.py:263) so
   two `PositionIdentity` instances over one DB would diverge silently,
   and key migration + the rebuild lane mutate what a memo caches.
   **Rev-2 position: R1 ships memo-less (derive per call)**; if profiling
   ever justifies a memo, it must come with explicit invalidation on
   migration/rebuild AND either the manual lane routes through the live
   owner (resolving the db-binding caveat) or cross-instance safety is
   proven. Decide at the phase that wants the memo, not before.
2. **Retro-sweep idempotency mechanism** — **DECIDED at R3:
   delta-reconcile adopted** with constraints (a)-(d) below, see §4-R3.
   Original framing kept for the record: per-fill `identity_applied`
   marker column vs qty-delta reconcile (recompute junction
   contributed_qty from fills as source of truth). Delta-reconcile heals
   F8-inflated and F9-starved historical rows for free, and fills are a
   sound source (UNIQUE(account_id, exchange_fill_id) collapses
   re-deliveries; reversal split legs carry distinct synthetic fids;
   LB-D2 separability holds via per-order junction keys) — BUT the naive
   tpid-keyed recompute is DESTRUCTIVE against rebuilt shapes: after the
   §2.2 rebuild lane runs, fills carry `rebuilt:` tpids while junction
   rows keep live tpids → `SUM(fills WHERE tpid=key)` returns 0 and the
   "heal" zeroes valid rows (feasibility-review MAJOR-2). If
   delta-reconcile is adopted: (a) EVIDENCE-GATE — zero matching fills →
   NO-OP, never reduce-to-zero; (b) key the recompute by ORDER
   (eoid → canonical_tpid), never raw `fills.terminal_position_id`;
   (c) `SUM(ABS(quantity))` (junction accumulates abs, :2447-precedent);
   (d) F6 migration re-stamps fills (§2.1.3) so keys stay coherent.
3. **DDL** — **DECIDED at R4: `positions_calcs.sealed_ts` column
   adopted** (see §4-R4 for the full rationale). The "no DDL required"
   premise here was WRONG: the closed-row-existence gate is unsound
   because T2.11 writes one closed row per partial rung (existence ≠
   finality), and no finality marker exists on the row; the column is
   the mechanism, not just observability. Original framing kept for
   the record.
4. **`attr_identity_reconcile` payload** shape — **RESOLVED at R5: the
   category does not exist** (superseded, §2.3 note). The decisions ship
   as `attr_junction_form` outcomes (MIGRATED/RECONCILED/SEALED), each
   following the §5.6 conventions (outcome + identity tuple verbatim +
   dedup_key) — documented in erratum E36 + the cookbook.

## 6. Acceptance criteria (verbatim checklist for R5)

1. Battery: 0 xfails remaining from {LB-D5, LB-D6, LB-I5, LB-T2d, LB-T2e};
   ALL pins green (48 at R0; grows as phases add pins); LB-D4's T3
   scenario green via the owner.
2. Full suite green SOLO. Perf: the existing `-m perf` gate covers
   corr-log emit/apply deltas ONLY (E29) — it CANNOT catch owner-added
   fill-path latency; R2 therefore adds a `perf`-marked
   `_process_single_fill` micro-benchmark and THAT gate holds (assessed
   risk is low: one added SQL read on a path already running 6-10).
3. Faithful-consolidation: pre/post `attr_*` stream diff on the battery
   scenarios shows identical decisions (modulo `component` + ledger-named
   flips).
4. Grep-proof (run EVERY phase): no `upsert_position_calc_link` /
   lifecycle-mint / junction exists-check / fills-or-orders tpid-write /
   fills.calc_id-write callers outside the owner — EXCEPT the §3-named
   fences: the offline-recovery rebuild lane (until absorbed) and the four
   named `scripts/` tools. The in-flight-cleanup discipline applies:
   feature tasks must not add new sites while R-phases run.
5. Live dogfood: one operator-driven open→amend→close on the running
   engine with `CORR_LOG_PROFILE=linkage`; chain shows owner-emitted attr
   lines.
