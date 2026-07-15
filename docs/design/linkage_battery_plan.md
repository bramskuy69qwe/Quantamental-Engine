# Linkage attribution battery — plan + scenario matrix

**Status**: Tier 1 IN PROGRESS (this doc + first battery files land together).
**Origin**: HANDOFF 2026-07-14 Track 1 — backend attribution battery, built by
durability (backend outputs survive v2.6 + v3.0; browser DOM does not).
**Method**: deterministic backend fixtures on the existing harness — no browser,
no live market, no TestClient(main.app). Each scenario asserts the attribution
OUTPUTS (DB rows first, corr-log envelopes second). Scenarios assert **desired
semantics**; where current behavior diverges, the scenario is marked
`xfail(strict=True, reason="LB-…")` and the divergence is recorded in §5 —
that is the discovery loop (triage before fixing, mechanism verified
independently per CLAUDE.md re-investigation discipline).

## 1. State model (verified against code 2026-07-14, three independent read agents)

**Axis A — calc lifecycle** (`pre_trade_log.status`, choke-point
`core/calc_state.py:210 transition()`, table `CALC_TRANSITIONS` :65):
`none →(calculate, handlers.py:505)→ active →(match/manual, TOCTOU-guarded)→
matched →(final close, order_manager.py:1313 _complete_calcs_on_close)→
completed_via_position`. Side edges: `active|released → superseded`
(recalc same (account,ticker,side), handlers.py:182), `→ expired`
(60s sweep, schedulers.py:866 → handlers.py:291), `→ cancelled_by_operator`
(handlers.py:411); `matched → released` (order-cancel release,
order_manager.py:1172, gate filled_qty==0) → re-matchable.

**Axis B — order link-state** (`orders.link_status`, `core/link_state.py:55`;
invariant **calc_id present ⟺ LINKED**): arriving `NULL →(auto_classify
:306)→ LINKED | NEEDS_MANUAL_REVIEW | UNPLANNED`; `UNPLANNED → LINKED|NMR`
(matcher re-run upgrade); NMR **sticky** for the matcher
(order_enrichment.py:313); operator edges NMR|UNLINKED → LINKED
(link_actions.py:127) / UNPLANNED (:320); LINKED + UNPLANNED terminal for
operators. Matcher = strict 6/6 (`calc_correlation.py:289`), candidates
`status IN (active,released)`, entry tolerance 0.25%.

**Axis C — fill/position pipeline** (`order_manager.py:1865
_process_single_fill`, ordered): ⑨ `_resolve_close_tpid` :1935 (tier-0
parent-order tpid via the fill's eoid, LB-F5 2026-07-15 → tier-1 live
position (symbol,direction) → tier-2 entry-order fallback) → persist
(+ LB-F5 close-order tpid stamp, reduce-only gated) →
`_reenrich_parent_after_fill` :1901 (matcher re-fire; `_ensure_junction_if_linked`
:552 replay) → `enrich_fill` (parent calc → fill) →
`_link_position_calc_on_open` :2102 (tpid backfill :2221, junction UPSERT
:2332, lifecycle mint :2266) → `_stamp_closing_fill_attribution` :2435
(position PRIMARY calc = most-contributed, tie earliest) → +2s
`_build_close_row_for_fill` :3055 (strict tpid → chronological walk →
`_backfill_open_fill_tpids` :2992 backstop; close calc = junction primary →
earliest-fill fallback :3296; `insert_closed_position` db_orders.py:299 —
REPLACE key (account, tpid, exit_time_ms), calc_id bound unconditionally :536,
lifecycle/deltas/tpsl carried across REPLACE :462).

**Interference mutators** (pairwise candidates): supersede-on-recalc;
expiry sweep; release-on-cancel; stale-cancel (bulk, does NOT release calc —
documented asymmetry order_manager.py:1205); reconciler (MFE/MAE only — no
identity writes); legacy `/admin/calc_link/confirm` (routes_admin.py:245 —
raw calc_id write, NO link_status, bypasses both choke-points); startup
re-derive `_enrich_positions_calc_id` :2536; DataCache tpid mint race.

## 2. Scenario matrix

Tiers: **T1** = this battery tranche (files below). **T2** = next tranche.
**T0** = believed covered by the existing suite (listed for completeness;
verify at next touch, do not reimplement).

| ID | Tier | Scenario (drive → assert) |
|---|---|---|
| LB-E1 | T1 | Happy path: calc → 6/6 order → entry fill → junction+lifecycle+tpid backfill → close fill → closed row (calc=primary, lifecycle sealed) → calc `completed_via_position` |
| LB-E2 | T1 | Calc-timing race (90a9da4 regression net): order → NMR → manual_link → opening-fill calc_id propagated + junction replay (`_ensure_junction_if_linked`) → close row attributed |
| LB-E3 | T1 | Unplanned lane + journal separation: order → 0 candidates → UNPLANNED → close → closed row calc NULL, badge "" ; journal DB layer (`insert_trade_history`, the sink behind `/history/log_close`) writes `trade_history` ONLY (no linkage-id columns exist; `closed_positions` untouched). Route-handler drive = T2 opportunistic |
| LB-D1 | T1 | `orders.calc_id` single-winner: matcher links entry; bracket legs inherit; late `manual_link` → `already_linked`; no overwrite anywhere (`calc_id IS NULL` guards) |
| LB-D2 | T1 | Scale-in divergence: calc A (qty 1) + calc B (qty 3) same tpid → primary=B; close fill stamped B; A's opening fill keeps parent calc A; closed row calc=B. Pins parent-rule vs primary-rule split |
| LB-D3 | T1 | ⑨ same-slot reopen hazard: POS-1 (BTC LONG) fully closed; POS-2 live same (symbol,side); late POS-1 close fill w/ empty tpid → tier-1 resolves to POS-2 (wrong instance?) — assert desired = correct instance |
| LB-D5 | T1 | Junction dual-key: entry order tpid=POS-A, first fill tpid="" (Defect-7 order-fallback keys POS-A), second fill tpid=POS-B → two junction rows same (order,calc)? Pins the HA-42-adjacent double-count shape |
| LB-D6 | T1 | closed_positions REPLACE asymmetry: row (calc A, lifecycle L1) REPLACEd by (calc B, lifecycle NULL) → calc rebound to B while L1 carried forward — mixed identity pinned |
| LB-D7 | T1 | Badge live-vs-history: live = current-state (`deviation_badge_level` state.py:169, fed by `_enrich_positions_calc_id` — def :2536, badge call in-body ~:2926), history = sticky worst `tpsl_amended` (`state.py:225`); SL removed (2) then re-added → live green/yellow, history red. Unit-level on both fns |
| LB-I1 | T1 | Admin raw confirm invariant break: `/admin/calc_link/confirm` → calc_id set, link_status NOT LINKED; matcher re-run skips (already-correlated gate reads calc_id); junction still forms on fill. Assert desired = invariant holds |
| LB-I2 | T1 | Stale-cancel asymmetry: matched calc + order; `mark_stale_orders` bulk-cancel → calc stays `matched` (never released) → identical new order → no candidates → UNPLANNED. Assert desired = calc released (documented gap :1205) |
| LB-I3 | T1 | Expiry-vs-match TOCTOU: matcher decided LINKED off `active` snapshot; calc flips `expired` pre-transition → guarded UPDATE race-lost → order LINKED + calc expired coexist. Pin the composite state |
| LB-I4 | T1 | Release → re-match: WS cancel (filled_qty=0) of linked order → calc `released` + cancel_reason stamped → new 6/6 order → LINKED again, calc `matched` |
| LB-I5 | T1 | Lifecycle bleed on tpid reuse (docstring hazard :2239): trade 1 on POS-1 mints L1, closes; trade 2 reuses tpid POS-1 → reuses L1 for a new economic trade. Assert desired = fresh lifecycle |
| LB-I6a | T1 | NMR sticky vs calc-after-order (ETH case): order → NMR (candidate failed 1 criterion); perfect calc created after; fill-arrival re-fire → still NMR (sticky gate). Pin (deferred follow-up #3) |
| LB-I6b | T1 | UNPLANNED upgrade: order → 0 candidates → UNPLANNED; calc created after; fill re-fire → LINKED + junction replay + fills attributed |
| LB-D4 | T2→T3 | closed calc rule divergence live (junction-primary) vs offline rebuild (earliest-fill) — drive `db_orders` backfill path on the LB-D2 shape. **SHIPPED at reconciler R4** (`TestLBD4RebuildCloseCalcRule`): `position_grouping._build_row` now delegates the calc rule to the owner's §3.2 helper (`_most_contributing_calc_id` over opening fills); the T3 scenario drives `rebuild_closed_positions_for_symbol` on the LB-D2 shape and asserts the rebuilt row takes the primary (B), not earliest (A) |
| LB-T2a..e | **SHIPPED** | `tests/test_linkage_battery_t2_pipeline.py` (2026-07-14): reversal split both-legs attribution (T2a pin — open leg has NO identity until next ACCOUNT_UPDATE, partial attribution by design); partial→final ladder (T2b pin — `partially_actioned` has NO producer, calc_state.py:124-126 documented pre-Phase-6 gap; exit reasons TP_PLANNED→MIXED; completion at final only); liquidation (T2c pin — order-type detection, liq VWAP px, reason dominates ladder); fill-before-mint (T2d → **LB-F9** xfail); HA-42 repro (T2e → **LB-F8** xfail + filed-mechanism CORRECTION) |
| LB-T2f..l | **SHIPPED** | `tests/test_linkage_battery_t2_lanes.py` (2026-07-14): window per-calc + **override-duality pin** (T2f — `link_window_seconds_override` persisted but NEVER read by the matcher, only legacy exec_link countdown; T215 L2 "intentional-for-now", db_trades.py:176-191 — flag to operator: the calc form's override does NOT extend auto-link); entry-tolerance boundary (T2g — pure-pct criterion, tick feeds TP/SL only; 6/6 vs 5/6 audit rows pinned); one-way BOTH gap (T2h pin — hedge-keyed tier-2 map key-disjoint from BOTH fills; full-pipeline strand: empty tpid, no stamp, no junction); snapshot-cancel sibling (T2i — db strands, LB-F3 sweep releases); `/history/log_close` route drive (T2j — journal-only at route level); funding assign/closed-reconcile/orphan (T2k — funding_events keyed to tpid w/ junction-primary calc; closed-window reconciles funding_fees+net_pnl; orphan writes nothing); snapshot recovery (T2l — already covered in test_linkage_binance_ws:513/:559, only the DataCache position_id self-persist leg was unpinned, now pinned) |
| T0 | T0 | matcher 6/6 single criteria (test_phase1_matcher*), junction formation/accumulation (test_phase2_junction), link/calc choke-point transitions (link/calc state tests), badges render (test_linkage_history_plan), replay of 8 historical bugs (test_correlation_log_replay), entry-fill attribution + ⑨ tiers (test_correlation_log_attribution, test_linkage_binance_ws) |

## 3. Harness conventions (binding for battery files)

- Files: `tests/test_linkage_battery_e2e.py` (LB-E*), `tests/test_linkage_battery_disagreement.py` (LB-D*), `tests/test_linkage_battery_interference.py` (LB-I*). Shared helpers: `tests/linkage_battery_helpers.py` (not collected).
- Fixture = the `real` pattern (test_phase2_junction.py:516): ONE tmpfile DB behind both `DatabaseManager` and `config.DB_PATH` (monkeypatch), accounts row `{"window_seconds": 300}`; drive `om._process_single_fill` / `om.process_order_update` / `link_actions` / `handlers` coroutines directly. NO TestClient (gotcha LOW-023).
- Determinism: fixed string ids; timestamps anchored to module-import `RECENT`/`RECENT_MS` (the 1fe4178 flake-fix pattern — orders carry `created_at_ms=RECENT_MS`, calcs `timestamp=RECENT_ISO`); no sleeps; close-row built by awaiting `_build_close_row_for_fill` directly (never the +2s scheduled task).
- Matcher-grade seeds: calc rows need `ticker, side, effective_entry, tp_price, sl_price, average, status, window_seconds, timestamp`; order rows need `symbol, side, order_type, price, tp_trigger_price, sl_trigger_price, avg_fill_price, created_at_ms` (+ `terminal_position_id`/`lifecycle_id` — hand-rolled rows MUST carry both).
- app_state hygiene: snapshot/restore `app_state.positions` when a scenario needs a live position (⑨ tier-1); never assign `app_state._data_cache`.
- corr-log: optional secondary asserts via the `_pin`/`_drain` idiom; DB rows are the primary contract.
- Verify-first: before implementing a scenario, READ the target function(s) at the cited lines — the map above is a guide, not a contract.

## 4. Triage protocol (per failing scenario)

1. Re-read the mechanism at the write sites involved; confirm the divergence is real (not a fixture artifact — cf. 53% false-positive rate on race-framed filings).
2. Convert to `xfail(strict=True, reason="LB-xx: <one-line mechanism>")`.
3. Record in §5: symptom, verified mechanism, disagreement pair involved, patch-vs-reconciler leaning.
4. NO fixes in the battery task — fixes are separate operator-gated tasks. The §5 ledger + xfail set IS the patch-vs-reconciler decision input (HANDOFF Track 1 meta-lever).

## 5. Findings ledger

Tier-1 battery result (2026-07-14): **24 tests = 17 passed + 7 strict-xfails**
(dated snapshot — LB-F1/F2/F3 fixed 2026-07-14, LB-F5 fixed 2026-07-15,
LB-F6/LB-F8 fixed 2026-07-15 at reconciler R2, LB-F9 at R3, LB-F4/LB-F7
at R4 2026-07-15; the live xfail set is now **EMPTY** — all 9 findings
FIXED, the battery is **62** plain-passing tests after R5's three pins:
NIT-6 sweep fence, reused-slot close identity + live-enrich twin,
migration rebuilt-namespace fence);
every xfail is a verified engine divergence (mechanism re-read at the write
site; `--runxfail` traceback confirms the mechanism assertion is what fails),
and every xfail has a passing current-behavior pin twin (shared drive helper
or explicit pin test) so a fixture regression can't silently masquerade as
the expected failure. Zero fixture-reason xfails.

| ID | Scenario | Verified mechanism | Status |
|---|---|---|---|
| LB-F1 | LB-E2 | `manual_link_order` (link_actions.py:127) stamped orders.calc_id + fills.calc_id + flipped calc→matched but never formed the junction: `_ensure_junction_if_linked` had ONE call site (`order_manager.py:518`, auto lane only), and an already-filled order gets no later WS update to re-fire it → fresh VELVET/ETH-shaped `positions_calcs` gap (live badge unattributed, close-fill stamp no-ops; close ROW masked it via earliest-fill fallback). | **FIXED 2026-07-14**: `manual_link_order` step 4 replays `_ensure_junction_if_linked` post-link via a throwaway `OrderManager(db)` on link_actions' own db binding (X instead of `platform_bridge.order_manager` because that singleton's DB handle diverges from la's in test/startup contexts; construction is three attribute assignments). Covers the admin lane too (LB-F2 delegation). Battery asserts junction formation on both lanes |
| LB-F2 | LB-I1 | `/admin/calc_link/confirm` (routes_admin.py:290-291) raw-wrote `orders.calc_id`+`fills.calc_id` via bare sqlite3 — no `link_status` write, no `auto_classify`, no `calc_state.transition`. Result: order NMR-with-calc_id (calc_id⟺LINKED invariant broken), calc stranded `active`, no junction. | **FIXED 2026-07-14**: handler delegates to `manual_link_order` (choke-pointed lane); legacy calc-linked-elsewhere guard dropped (junction is many-to-many), legacy `link_status=NULL` rows now get `invalid_transition` instead of a raw write. Battery asserts the routed behavior |
| LB-F3 | LB-I2 | `mark_stale_orders` (db_orders.py:882-888, time-threshold path) + sibling `mark_stale_orders_canceled` (db_orders.py:774, snapshot path) bulk `UPDATE status='canceled'` never routed through `_release_calc_on_operator_cancel` → calc stranded `matched`; replacement order finds no candidates → UNPLANNED. WS-cancel path was already correct (LB-I4). | **FIXED 2026-07-14**: new `OrderManager.release_calcs_for_stale_cancels` sweep (scan canceled/zero-fill/non-reduce-only linked orders with no cancel_reason stamp + calc still `matched`, route each through the ONE existing release rule), wired after all 3 bulk call sites (basic snapshot, algo snapshot, scheduler time path). Sweep is idempotent (reason stamp = processed marker) and self-heals historically stranded calcs. Covers BOTH siblings — the T2 sibling item is closed by the same sweep. **v2.6 UPDATE (2026-07-16 audit)**: 2 wired call sites, not 3 — the scheduler time path was deleted with the plugin-gated `_order_staleness_loop` block (`157bd20`), taking `mark_stale_orders`' only production caller with it. The fix is UNWEAKENED: the sweep scans DB state, not the caller, so it still covers the time-path shape (LB-I2 drives it directly) if it is ever re-wired |
| LB-F4 | LB-I5 | Lifecycle mint/reuse lookup (order_manager.py:2254-2266) `SELECT lifecycle_id FROM positions_calcs WHERE position_id=? AND account_id=? AND lifecycle_id IS NOT NULL … LIMIT 1` has no closed/sealed filter → a reused tpid bleeds the CLOSED trade's lifecycle_id verbatim into the new economic trade (the :2239 ASSUMPTION-block hazard, "fix is seal-at-close, deferred"). | **FIXED 2026-07-15 (reconciler R4)**: seal-at-close — new `positions_calcs.sealed_ts` (§5-Q3 DECIDED: column, not the closed-row-existence gate — one closed row per T2.11 partial rung means existence ≠ finality) stamped by the owner's `seal_position_lifecycles` at the FINAL close (`is_final`, the `_complete_calcs_on_close` moment; exit_time_ms, idempotent); the mint/reuse lookup ignores sealed rows with an OWN-TRIPLE exception (a late fill of a sealed trade's own (position,calc,order) continues that trade — no phantom lifecycle/position:opened). Battery pins: fresh mint on reuse, sealed_ts stamp, partial-no-seal + scale-in continuity, own-triple late fill. Side effect (correct): a reused-slot trade 2 now emits position:opened instead of a bogus scale_in |
| LB-F5 | LB-D3 | `_resolve_close_tpid` never consulted the fill's own parent order: tier-1 scanned `app_state.positions` by (symbol,direction); tier-2 also symbol/side-keyed → a late close fill for a FULLY-CLOSED position resolved to the LIVE same-slot instance. | **FIXED 2026-07-15**: ⑨ **tier-0 `parent_order`** (fill's exchange_order_id → orders.tpid, before the heuristics; silent fall-through on read failure — spec E35) **PLUS the close-side Defect-1 twin stamp** in `_process_single_fill` (first tpid-carrying closing fill copies its ws-stamped tpid onto the parent close order; empty-only + **reduce-only gates** — the reduce-only gate exists because battery LB-T2a caught the ungated version pre-commit: a reversal order is both closer and opener, and the close-leg stamp handed the OLD tpid to the open leg's Defect-7 fallback). Deviation named: stamp added beyond the §7-sanctioned tier-0 **because** the investigated mechanism showed close orders NEVER carry a tpid live (only Defect-1 stamps entry orders) — tier-0 alone would have been a live no-op; the stamp is the same fill→order copy-rule as Defect-1, not a re-derivation (no new identity site). Residuals pinned/filed: rows with no parent stamp (pre-fix history) still fall to the tier-1 heuristic (`test_pin_heuristic_fallback_without_parent_stamp`); the latent one-way shape (audit MINOR-3) was **RESOLVED at reconciler R2** — the tier-0 SELECT now carries the reduce-only gate (reads exactly what the stamp twin writes) |
| LB-F6 | LB-D5 | `_link_position_calc_on_open` keyed the junction on `fill.terminal_position_id` when present, order-tpid fallback only when empty (Defect-7); nothing reconciled mixed-tpid fills → junction rows under TWO position_ids + two minted lifecycles for one economic open. | **FIXED 2026-07-15 (reconciler R2)**: key-migration pass in `position_identity.link_position_calc_on_open` — stale (calc, order) junction rows under a different key are merged/re-keyed to the canonical key, affected fills re-stamped (plan §2.1.3), AND the order's stale stash corrected (named extension: a surviving stash keeps feeding ⑨ tier-0 + the replay guard the dead key). New `MIGRATED` tap outcome (→ E36). Battery pins the full shape incl. re-stamp + stash correction |
| LB-F7 | LB-D6 | `insert_closed_position` REPLACE binds `calc_id` unconditionally (db_orders.py:536, T234-intentional) while `lifecycle_id` carries forward when caller passes None (:462-465) → REPLACE (CALC-A,L1) with (CALC-B,None) yields ('CALC-B','L1') — calc B welded to calc A's lifecycle. Intentional per-column rules composing into mixed identity. | **FIXED 2026-07-15 (reconciler R4)**: the lifecycle carry-forward is PAIR-GATED on calc_id — carry only when the existing row's calc equals the caller's (the T232 preserve case: a deterministic re-derivation supplies the SAME calc); a calc REBIND takes the REPLACing writer's whole pair. calc_id stays unconditionally bound (T234 unchanged). Battery pins the coherent rebind AND the calc-unchanged carry-forward (over-fix guard). Funding reconcile traced: targeted UPDATE by row id, no REPLACE interaction |

| LB-F8 | LB-T2e | **HA-42 CONFIRMED — mechanism CORRECTED vs both the HA-42 filing and the LB-D5 side obs** (audit-impact-imprecision +1): the filed per-fill dual-path is wrong — no replay runs in the fill hot path, and the prescribed Defect-7 shape does NOT over-count (pinned passing). The REAL over-count was a **guard-key/write-key divergence inside `_ensure_junction_if_linked`**: the guard exists-checked the ORDER's stashed tpid while the replayed synthetic fill carried `MAX(fills.tpid)` + `SUM(qty)`, which the builder prefers — a divergent stash never satisfied the guard → **N-fold, unbounded** contributed_qty inflation per WS/bracket-child event (behind a narrow stash gate; see the T2-audit severity framing in the git history of this row). | **FIXED 2026-07-15 (reconciler R2)**: `position_identity.ensure_junction_if_linked` now derives the fills-aggregate write key FIRST and exists-checks THAT key — guard ≡ write BY CONSTRUCTION. Consequences (named): `no_position_key` fires only when both fills-tpid AND stash are empty (a stash-empty order with tpid-carrying fills legitimately replays), and the no_opening_fill/junction_exists skip precedence swaps (fills read first). Battery pins the idempotent progression 1.0→1.0→1.0 |
| LB-F9 | LB-T2d | **fill-before-mint UNDER-count (mirror of LB-F8)**: first fill with tpid="" + order tpid="" SKIPped; the mint landed with the SECOND fill which formed the junction with only its own qty; nothing folded the first fill in (Defect-1 stamps the ORDER only; the replay guard was satisfied by fill 2's row). The LB-T2a reversal open leg lands in the same shape. | **FIXED 2026-07-15 (reconciler R3)**: mint-after-fill retro-sweep in the builder — the tpid-carrying fill stamps pre-mint siblings (tpid+lifecycle) and **delta-reconciles** the junction row to `SUM(ABS(qty))` of the ORDER's opening fills (§5-Q2 decision: delta-reconcile adopted — evidence-gated, order-keyed, on-change; also heals F8/F9-shaped historical rows at the next event). Direction-gated like the R2 migration (stash-derived events never sweep). Companion NIT-6 fix: the replay guard now includes order_id (second order of the same calc replays). Residual tails (no-later-tpid-event opens; reversal legs) heal at close via the retained backstop |

**Pinned composites / by-design (plain asserts, no xfail)**: LB-I3 — order can
end LINKED to an `expired` calc (orders write gated only on `calc_id IS NULL`,
order_enrichment.py:378-384, while the calc flip TOCTOU-loses at :517-524 and
is swallowed :556). LB-I6a — NMR is matcher-sticky by design
(order_enrichment.py:313); a perfect calc arriving later is never auto-linked
(deferred follow-up #3). LB-D2 — opening fills keep the parent-order calc
while close fill + close row take the position PRIMARY calc (the two-rule
split, working as designed). LB-D7 — live badge memoryless vs history badge
sticky-worst (32df20e design). LB-D1 bracket legs carry `lifecycle_id=NULL`
(documented deviation, order_manager.py:735-744).
T2 additions: LB-T2f — `link_window_seconds_override` is persisted but the
matcher NEVER reads it (T215 L2 column duality, db_trades.py:176-191
"intentional-for-now"; read only by the countdown path —
routes_calculator.py:397 / db_orders.py:1370 → exec_link.py:145 —
**operator note: the calc form's window override does NOT extend
auto-link**). LB-T2b — `partially_actioned` has NO producer
(calc_state.py:124-126, pre-Phase-6 deferred); a calc stays `matched`
through partial closes. LB-T2h — one-way BOTH close fills strand through
the whole pipeline (hedge-keyed tier-2 map is key-disjoint;
ws_manager.py:431-435 KNOWN LATENT GAP; operator runs HEDGE). LB-T2a — the
reversal open leg carries no position identity at split time (lands in
the LB-F9 shape; heals at close via the walk-path backstop — R3
correction: no mint event ever reaches the order).

### Mechanism-family triage (patch-vs-reconciler input, HANDOFF Track 1 §4)

The 9 findings collapse to **4 mechanism families**:

1. **Junction identity keying is fragile** (LB-F1 ✅fixed, LB-F6, **LB-F8**, **LB-F9**) — all inside `_link_position_calc_on_open`/`_ensure_junction_if_linked`. The junction is the identity ledger every consumer reads, and it can be missing (manual lane — fixed), double-keyed (mixed tpids), N-fold inflated (guard-key/write-key divergence), or permanently under-counted (fill-before-mint). Four independent bugs, ONE root: the junction key is re-derived per event from whichever tpid happens to be visible, with no single owner of position identity.
2. **Identity resolution by (symbol,side) instead of by parent order** (LB-F5) — ⑨'s tier order ignores the strongest identity signal it already has (the fill's own exchange_order_id → order tpid).
3. **Lifecycle identity has no seal** (LB-F4, LB-F7) — no seal-at-close on mint/reuse; REPLACE carry-forward welds lifecycles across calc rebinds.
4. **Choke-point bypasses** (LB-F2 ✅fixed, LB-F3 ✅fixed) — raw writers that predated the calc/link state machines; both routed through the existing rules.

Families 1–3 are all "identity derived ad-hoc at the consumer" — the
reconciler thesis (spec §12). Family 4 is CLOSED by surgical patches.
**T2 verdict: the tranche landed BOTH new findings in family 1** (over-count
+ under-count, mirror images of the same key-derivation root) and corrected
the HA-42 filing's mechanism — the family-1 concentration is now 4 bugs on
one root. See §7 for the patch-vs-reconciler decision.

## 6. Filed residual observations (audit-sourced, NOT fixed — opportunistic)

Surfaced by the three pre-commit audits (Tier-1 / Task A / Task B); every
other audit finding was folded into its commit. These three were left
unfixed deliberately; filed here so they don't dangle in task transcripts.

| ID | Tier | Observation | Trigger to act |
|---|---|---|---|
| LB-R1 | LOW (pre-existing) | The admin calc-link UI flow was likely never end-to-end functional: `templates/admin/_calc_link_candidates.html` sends `hx-vals` FORM-encoded with a forced `application/json` header → `request.json()` fails → `body={}` → 400 "Missing order_id or calc_id"; no `json-enc` extension exists anywhere, and htmx default doesn't swap 4xx bodies (the only `beforeSwap` listener is the ECharts-dispose in base.html), so the error div never renders either. Unchanged by the LB-F2 delegation (same failure before/after). | Next touch of the admin surface: either fix the encoding (hx-post form params) or delete the page per plan §11 (needs-link tab is the modern path) |
| LB-R2 | LOW (theoretical) | `release_calcs_for_stale_cancels` could wrongly release ONCE in a compound edge: an old WS cancel whose reason-stamp DB-write failed (swallowed at order_manager.py:~1250) AND whose calc later re-matched to a different live order. Live-DB probe at audit time: zero candidate rows of any shape. Optional tightening: `AND NOT EXISTS (other live order on same calc)`. | **TRIGGER FIRED + EVALUATED 2026-07-16 (v2.6 audit) → RISK UNCHANGED, tightening still optional.** The trigger anticipated that v2.6 would ELEVATE bulk snapshots into the primary cancel path. It did not: the path it removed (`_order_staleness_loop`'s time-threshold `mark_stale_orders` block) was `platform_bridge.is_connected`-gated, so it never executed in standalone — bulk snapshots were ALREADY the only live bulk cancel path before v2.6. v2.6 deleted dead code and changed zero live behavior here, so the compound edge's likelihood is exactly what it was when first probed (zero candidate rows). Remaining trigger, unchanged: if the sweep ever logs a release for a calc with a live working order |
| LB-R3 | NOTE (parity) | The LB-F1 junction replay emits `position:opened`/`scale_in` at manual-link time — potentially long after the fill, possibly for an already-closed position. Exact parity with the auto-lane Defect-8 replay (same late-event property); no live `position:opened` subscriber exists today (only `position:closed` has consumers). | The moment a `position:opened` subscriber is added, both replay lanes need a suppress-or-timestamp decision |

## 7. PATCH-vs-RECONCILER DECISION (2026-07-14, on the full T1+T2 evidence)

**Decision: BUILD THE RECONCILER, scoped to identity ownership (families
1 + 3), with ONE pre-reconciler surgical patch (LB-F5 / family 2).**
Operator-gated: the reconciler needs its own design/plan doc (spec §12 is
the seed; HA-42→LB-F8 is the first input) — this section is the decision
record, not the build plan.

**Why not patch family 1 (the 3 open junction-keying bugs)?** Each spot
fix fails the whack-a-mole test that motivated this battery:
- LB-F9 (under-count, ALWAYS-ON live) can only be spot-fixed by adding a
  retroactive sibling-fill backfill lane — a **7th ad-hoc attribution
  site**, the exact pattern (⑨→close-recording) that proved fixing one
  site shifts load to another.
- LB-F6 (dual-key) and LB-F8 (N-fold inflation) both reduce to "which
  tpid is canonical for this order's junction row?" — answering that
  per-site IS the reconciler question; answering it in one place is the
  reconciler.
- Family-1 evidence: 4 independent bugs (F1 fixed, F6, F8, F9), one root
  — the junction key is re-derived per event from whichever tpid is
  visible (fill tpid / order stash / MAX(fills)), with no owner and no
  retroactive reconcile when late identity (mint, link) arrives.
- Counter-evidence honestly weighed: family 4 (F2, F3) WAS surgically
  patchable — but those were missing *routings* into existing rules, not
  identity derivation. The distinction predicts patchability: routing
  bugs patch cleanly; derivation bugs multiply sites.

**Why fold family 3 (lifecycle: F4 seal, F7 REPLACE weld) into the
reconciler?** Lifecycle is the same identity, one level up: seal-at-close
is naturally the identity owner's close-transition duty, and F7's
calc-vs-lifecycle REPLACE asymmetry is a coherence rule that belongs to
whoever owns identity stamping (T234 made the calc half intentional —
the pair-coherence decision needs one owner, not another per-column rule).

**Why patch family 2 (LB-F5) now, outside the reconciler?** It is a
resolution-ORDER change inside one existing resolver (⑨ tier-0 = parent
order's tpid via the fill's own exchange_order_id, before the live
(symbol,direction) scan) — no new site, no canonical-key question, and it
kills a live misattribution shape (same-slot reopen) cheaply. Ship as a
normal fix task; the LB-D3 xfail flips on it.

**Reconciler scope sketch** (for the design doc, not binding): one module
owns (a) canonical tpid per (account, entry-order) — single derivation,
consumers read, never re-derive; (b) junction writes keyed ONLY through
it, replay/idempotency by construction (guard key ≡ write key kills F8);
(c) retroactive reconcile on late identity — mint-after-fill (F9),
link-after-fill (F1's generalization), key migration (F6); (d) lifecycle
mint/seal at open/close transitions (F4) + closed-row identity-pair
coherence (F7).

**Acceptance harness = THIS battery.** Reconciler done ⟺ the remaining
xfails flip strict-xfail → XPASS → markers removed, with all pins still
green (behavior-preservation proof — the same guard the v2.6
OrderManager extraction gets for free). Progress: LB-D3 flipped via the
F5 patch (02eb743); LB-D5 + LB-T2e flipped at R2; LB-T2d flipped at R3
(2026-07-15); **LB-D6 + LB-I5 flipped at R4 (2026-07-15) — the
acceptance xfail set is EMPTY**; LB-D4's owed T3 scenario shipped at R4
too. **R5 close-out DONE 2026-07-15** (E36 + NIT-5/6 riders + R4
residual (a) unsealed-basis + holistic 3-agent audit; residuals
(d)-(f) filed in the reconciler plan §4-R4). The program's remaining
acceptance item is §6-#5 live dogfood (operator-driven).

**Sequencing vs the roadmap**: ~~LB-F5 patch next~~ **done 2026-07-15**
(tier-0 + reduce-only-gated stamp; LB-D3 xfail flipped), then the
reconciler design doc (operator-gated separate session), then build —
ideally BEFORE v2.6's OrderManager extraction so the extraction moves
already-owned identity code instead of re-scattering it.
