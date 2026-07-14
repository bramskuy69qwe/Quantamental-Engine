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
| LB-F6 (=LB-D5) | mixed-tpid fills of one order key TWO junction rows + two lifecycles | **open xfail** |
| LB-F8 (=HA-42, corrected) | replay guard checks the ORDER-stash tpid while the write lands under MAX(fills.tpid) → guard never satisfies → N-fold unbounded `contributed_qty` inflation per WS/bracket-child event (gated: needs a divergent stash — "unbounded amplifier behind a narrow gate", battery severity framing) | **open xfail** |
| LB-F9 (=LB-T2d) | fill-before-mint first fill permanently stranded from the junction (under-count, mirror of F8); reversal open legs land in the same shape | **open xfail, always-on** |
| LB-F4 (=LB-I5) | lifecycle mint/reuse has no seal-at-close → tpid reuse bleeds a closed trade's lifecycle into the new trade | **open xfail** |
| LB-F7 (=LB-D6) | closed-row REPLACE binds calc_id unconditionally but carries lifecycle_id forward → mixed identity pair | **open xfail** |
| LB-F5 | ⑨ resolved by (symbol,side) heuristics before the parent-order signal | fixed `02eb743` — tier-0 + stamp; heuristic tail pinned |
| LB-D4 | offline/rebuild close-row calc rule (earliest-fill) diverges from the live rule (junction-primary) — a consumer re-deriving with a DIFFERENT rule | **open, un-battery'd** (T3 scenario owed; owned by R4 below) |

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

## 3. Consumer disposition (the identity-writing sites @ `02eb743`)

| Site (today) | Disposition |
|---|---|
| `_resolve_close_tpid` (⑨, order_manager.py:2029) | MOVES — becomes `canonical_tpid` + close-context wrapper; tier policy unchanged from `02eb743` |
| close-order tpid stamp (`_process_single_fill`, LB-F5) | MOVES — owner stamps as part of canonical registration |
| `_link_position_calc_on_open` (:2225) | SPLITS — junction/lifecycle writes move to the owner; the fill-pipeline call site remains a thin delegate with a SPECIFIED return contract `(lifecycle_id, is_first_open, scale_in, junction_ok)` so the `position:opened`/`scale_in` emissions (:2539-2556, keyed off mid-flow flags) stay at the call site — else the events move too (decide at R1, don't drift) |
| `_ensure_junction_if_linked` (:559) | MOVES — the link-after-fill retro path, canonical-keyed (guard≡write). NB its HA-28 SKIP-dedup memo (`_attr_skip_is_repeat` :544) is SHARED with the bracket-inheritance tap (:776, stays behind) — R1 must state where the memo lives (split it; shared-LRU eviction coupling is not worth preserving) |
| `_backfill_open_fill_tpids` (:3115) | ABSORBED by retro-reconcile (mint-after-fill sweep); the close-time call site becomes a no-op check |
| fills.calc_id writers: `order_enrichment.py:418` (link-time backfill, "the primary fix"), `:688` (fill-time propagation), `link_actions.py:241` (manual lane) | DELEGATE — owner stamps fills at registration/retro-sweep (feasibility-review MAJOR-3) |
| `_stamp_closing_fill_attribution` (:2558) | DELEGATES — reads the owner's (calc, lifecycle) pair for the position |
| `_build_close_row_for_fill` calc/lifecycle sealing (:3414/:3557) | DELEGATES — asks the owner for the pair; REPLACE coherence rule lands in `insert_closed_position` alongside |
| `_enrich_positions_calc_id` live re-derive (:2659) | DELEGATES for identity (tpid recovery), keeps display enrichment |
| offline-recovery rebuild lane (schedulers :529 → db_orders :1786-1864) | FENCED R1-R4 (contract in §2.2); ABSORB candidate at R5+/T3 with LB-D4 |
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
- **R2 — canonical key + guard≡write**: kills F8 + F6 (flip `LB-T2e`,
  `LB-D5` xfails). Includes key migration WITH fill re-stamping (§2.1.3).
  Adds a `perf`-marked fill-pipeline micro-benchmark (see §6.2).
  Opportunistic: the LB-F5 filed residual (tier-0 reduce-only gate —
  battery plan §5 LB-F5 row) naturally lands here if adopted.
- **R3 — retroactive reconcile**: mint-after-fill sweep kills F9 (flip
  `LB-T2d`); reversal open legs heal on the next ACCOUNT_UPDATE mint.
  LB-R3 (late-event parity) is the named design consideration.
- **R4 — lifecycle seal + pair coherence**: kills F4 + F7 (flip `LB-I5`,
  `LB-D6`); LB-D4's close-calc rule delegates to the owner (T3 scenario
  proves it).
- **R5 — close-out**: remove flipped xfail markers, holistic 3-agent audit,
  spec erratum **E36** (attr_identity_reconcile registry + §12/§5.6-close
  correction + component set + §5.6 site column), HANDOFF/memory refresh,
  optional historical-residue backfill script (dry-run-first).

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
2. **Retro-sweep idempotency mechanism**: per-fill `identity_applied`
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
3. **DDL**: none required for the core (`lifecycle seal` can gate on the
   final closed_positions row's existence); a `positions_calcs.sealed_ts`
   column is nice-to-have observability. Decide in R4.
4. **`attr_identity_reconcile` payload** shape — follow §5.6 conventions
   (outcome + identity tuple verbatim + dedup_key); erratum E36 at R5.

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
