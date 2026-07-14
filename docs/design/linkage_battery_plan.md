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
_process_single_fill`, ordered): ⑨ `_resolve_close_tpid` :1935 (tier-1 live
position (symbol,direction) → tier-2 entry-order fallback) → persist →
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
| LB-D4 | T2 | closed calc rule divergence live (junction-primary) vs offline rebuild (earliest-fill) — drive `db_orders` backfill path on the LB-D2 shape |
| LB-T2… | T2 | reversal split legs; partial→final ladder (`partially_actioned`); liquidation; window override (`link_window_seconds_override`); 0.25% entry-tolerance boundary; one-way BOTH gap; funding assign/orphan; HA-42 mid-fill double-junction repro (see LB-F6 side obs); fill-before-mint race; snapshot recovery (partially in test_linkage_binance_ws); `mark_stale_orders_canceled` (db_orders.py:774, the snapshot-reconciliation sibling of LB-F3's time-threshold path); `/history/log_close` route-handler drive |
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

Tier-1 battery result (2026-07-14): **24 tests = 17 passed + 7 strict-xfails**;
every xfail is a verified engine divergence (mechanism re-read at the write
site; `--runxfail` traceback confirms the mechanism assertion is what fails),
and every xfail has a passing current-behavior pin twin (shared drive helper
or explicit pin test) so a fixture regression can't silently masquerade as
the expected failure. Zero fixture-reason xfails.

| ID | Scenario | Verified mechanism | Status |
|---|---|---|---|
| LB-F1 | LB-E2 | `manual_link_order` (link_actions.py:127) stamps orders.calc_id + fills.calc_id + flips calc→matched but never forms the junction: `_ensure_junction_if_linked` has ONE call site (`order_manager.py:518`, inside `_enrich_order_best_effort` — auto lane only), and an already-filled order gets no later WS update to re-fire it. Manual-link-after-fill therefore creates a fresh VELVET/ETH-shaped `positions_calcs` gap TODAY (HANDOFF "live code prevents recurrence" is auto-lane-only). Downstream: live badge unattributed, `_stamp_closing_fill_attribution` no-ops (primary calc reads the junction); close ROW recovers via earliest-fill fallback — which masks the gap in history. Fix shape (not applied): call `_ensure_junction_if_linked` from `manual_link_order` post-link, mirroring Defect-8. | xfail(strict) `test_junction_exists_after_manual_link` |
| LB-F2 | LB-I1 | `/admin/calc_link/confirm` (routes_admin.py:290-291) raw-writes `orders.calc_id`+`fills.calc_id` via bare sqlite3 — no `link_status` write, no `auto_classify`, no `calc_state.transition`. Result: order NMR-with-calc_id (calc_id⟺LINKED invariant broken), calc stranded `active`, no junction. Deprecated-but-reachable choke-point bypass. | xfail(strict) + pin test |
| LB-F3 | LB-I2 | `mark_stale_orders` (db_orders.py:882-888, time-threshold path) bulk `UPDATE status='canceled'` never routes through `_release_calc_on_operator_cancel` → calc stranded `matched`; replacement order finds no candidates (matcher filter `status IN (active,released)`, calc_correlation.py:389) → UNPLANNED. The WS-cancel path releases correctly (LB-I4 passes) — asymmetry pinned as a pair. Same raw-bulk-cancel family as the order_manager.py:1205 NOTE (which names the sibling `mark_stale_orders_canceled`, db_orders.py:774, snapshot-reconciliation path — unpinned, on the T2 list). | xfail(strict) + pin test |
| LB-F4 | LB-I5 | Lifecycle mint/reuse lookup (order_manager.py:2254-2266) `SELECT lifecycle_id FROM positions_calcs WHERE position_id=? AND account_id=? AND lifecycle_id IS NOT NULL … LIMIT 1` has no closed/sealed filter → a reused tpid bleeds the CLOSED trade's lifecycle_id verbatim into the new economic trade (the :2239 ASSUMPTION-block hazard, "fix is seal-at-close, deferred"). | xfail(strict) + pin test |
| LB-F5 | LB-D3 | `_resolve_close_tpid` never consults the fill's own parent order: tier-1 (order_manager.py:1985-1989) scans `app_state.positions` by (symbol,direction); tier-2 is also symbol/side-keyed. A late close fill for a FULLY-CLOSED position resolves to the LIVE same-slot instance (POS-2) even though `orders.terminal_position_id` for its parent close order holds POS-1 in the DB. Fix shape candidate: tier-0 = parent-order tpid lookup by exchange_order_id. | xfail(strict) |
| LB-F6 | LB-D5 | `_link_position_calc_on_open` keys the junction on `fill.terminal_position_id` when present (:2175), order-tpid fallback only when empty (Defect-7 :2204); the Defect-1 backfill (:2221) only fills an EMPTY order tpid — nothing reconciles. Mixed-tpid fills on one order → junction rows under TWO position_ids + two minted lifecycles for one economic open. Side obs (LB-T2/HA-42 repro input): with a pre-seeded order tpid, the `_ensure_junction_if_linked` replay + direct builder double-accumulate `contributed_qty` under the fallback key. | xfail(strict) |
| LB-F7 | LB-D6 | `insert_closed_position` REPLACE binds `calc_id` unconditionally (db_orders.py:536, T234-intentional) while `lifecycle_id` carries forward when caller passes None (:462-465) → REPLACE (CALC-A,L1) with (CALC-B,None) yields ('CALC-B','L1') — calc B welded to calc A's lifecycle. Intentional per-column rules composing into mixed identity. | xfail(strict) |

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

### Mechanism-family triage (patch-vs-reconciler input, HANDOFF Track 1 §4)

The 7 findings collapse to **4 mechanism families**:

1. **Junction formation is auto-lane-only + key-fragile** (LB-F1, LB-F6, HA-42 side obs) — all inside `_link_position_calc_on_open`/`_ensure_junction_if_linked`. The junction is the identity ledger every consumer reads, and it can be missing (manual lane) or double-keyed (mixed tpids).
2. **Identity resolution by (symbol,side) instead of by parent order** (LB-F5) — ⑨'s tier order ignores the strongest identity signal it already has (the fill's own exchange_order_id → order tpid).
3. **Lifecycle identity has no seal** (LB-F4, LB-F7) — no seal-at-close on mint/reuse; REPLACE carry-forward welds lifecycles across calc rebinds.
4. **Choke-point bypasses** (LB-F2, LB-F3) — raw writers that predate the calc/link state machines. Two small surgical fixes (route admin-confirm through the choke-points or delete the endpoint; route bulk stale-cancel through the release helper).

Families 1–3 are all "identity derived ad-hoc at the consumer" — the
reconciler thesis (spec §12). Family 4 is patchable independently. Battery
verdict so far: **the structural root is real but bounded** — the reconciler
case strengthens if LB-T2 (HA-42 repro, reversal splits, fill-before-mint)
lands more findings in families 1–3.
