# Handoff — next Claude Code session

**Date**: 2026-07-16 (**v2.6 QUANTOWER-PLUGIN REMOVAL is COMPLETE + AUDITED + DEBUGGED + PUSHED** — 6 phases shipped, then holistically audited: 15 findings, **all 15 closed**. Engine live-verified. **Next program = v2.7 model library** — see ▶ NEXT SESSION.)
**Branch**: **`v2.6/remove-quantower-plugin`** — **PUSHED, in sync with origin** (P1-6 + the 4 audit commits). Forked off `3a55f3e` (the `v2.5/usertrades-backfill-fix` tip). Verify `git status -sb` at session start.
**Tests**: full suite **3943 passed / 7 skipped / 3 deselected / 0 xfailed** — green (~4:40). Run SOLO. (Was 3939 pre-audit: +8 new singleton-seam pins, −4 removed plugin tests.) ⚠ A **transient `concurrent_log_handler` flush timeout** has been seen once (0 lingering pythons after; re-run clean) — the CLAUDE.md test-hang class; re-run once before treating it as real.
**Engine**: **LAUNCHES FINE** (operator-verified 2026-07-16) — exchange-only, Binance-direct HEDGE, observe-only, force-kill safe. Start: `.venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000` (**no `--reload`**). ⚠ **HARD PRECONDITION — SYNCED OS CLOCK**: a drifted clock → `-1021 Timestamp ahead` on signed Binance REST → the startup fetches stall in weight-tracker throttling and the engine hangs forever on the "Connecting to exchange…" overlay (never flips `is_initializing=False`). **`w32tm /resync` BEFORE starting.** This WAS the "connecting endlessly" incident this session and the resync fixed it — NOT a v2.6 bug (incident note below).

## ▶ STATUS 2026-07-16 — v2.6 COMPLETE + AUDITED (15/15 findings CLOSED) + PUSHED

The v2.6 program (`docs/design/v2.6_remove_quantower_plugin_plan.md`) is DONE — the engine is now **exchange-only** (Binance-direct); the Quantower plugin, its bridge, routes, `PLATFORM_TOKEN` auth, platform UI, and the C# project are gone. Every phase followed the discipline: verify-first (plan line-refs were pinned pre-reconciler — they drifted, always re-grep) → targeted + full-suite gate SOLO → 2 independent read-only audits → fold findings → ONE commit → STOP. Memory: [[project-v26-quantower-removal]].

**The holistic audit then ran (xhigh /code-review, 10 angles + sweep) and is CLOSED OUT — see ▶ AUDIT below. Headline: NO correctness bugs in the production fold.** All 8 `is_connected` sites were provably dead before deletion (`len(_ws_clients) > 0` on a bridge nothing ever connected to), so every constant-fold preserved live behavior. The 15 findings were one real test-seam regression + doc/comment rot + dead code.

| Phase | Commit | What |
|---|---|---|
| 1 | `9531c6a` | Extract `OrderManager` into `core/order_manager_singleton.py` (out of `platform_bridge`); L1 single-instance invariant preserved (import smoke asserts bridge OM ≡ singleton) |
| 2 | `157bd20` | Constant-fold `platform_bridge.is_connected → False` (standalone-only); delete the dead plugin branches |
| 3 | `574fe76` | Collapse the `active_platform` setting (no writer/loader; `state.py` default "standalone"; render-safe — Jinja default lenient Undefined) |
| 4 | `523e0d1` | Remove the Quantower platform UI from `base.html` + the dedup legacy comment |
| 5 | `aeb397f` | Archive + DELETE bridge/routes/C# plugin + `PLATFORM_TOKEN` + QT maps (dependency-ordered: de-reference → delete) |
| 6 | `8efce34` | Test-mock hygiene (dead `sys.modules` platform_bridge mocks) + Quantower doc sweep |

**Key facts:**
- **Plugin source ARCHIVED** in local branch **`archive/quantower-plugin`** (at pre-deletion HEAD `523e0d1`) — the 14 C# files + `platform_bridge.py` + `routes_platform.py` are recoverable there. Local only; push it if you want the archive on origin. The leftover on-disk `QuantowerRiskPlugin/{obj,bin}/` build cruft was deleted (P6).
- **The 62-pin linkage battery is the extraction's safety net** — it guarded the OrderManager move (any silent attribution regression turns pins red); all green.
- **Landmines KEPT (plan §2 — do NOT "clean" these; each is now ANCHORED in-file so a future sweep re-reads the reason before re-filing):** **L2** `resolve_tpsl_direction` (`order_state.py`, used live by exchange/ws_manager/order_manager); **L3** `UpdateSource.PLATFORM` + `data_cache.apply_account_update_platform` (dead-but-retained — deleting = wide test rewrite for no gain; ~6 tests pin the PLATFORM precedence rules); **L4** historical `source='quantower'` fills + `scripts/dedup_fills.py "quantower": 0` + `test_dedup_fills`/`test_an2_quantower_cleanup`/`migrations/000_split_databases.py`; **L5 — RETIRED 2026-07-16 (v2.7 P6)**: `/api/backtest/qt-import` + its backtest.html UI deleted, superseded by the model library's adapter upload (`POST /models/{id}/backtest-upload`); the `results.html` microstructure render branch KEPT for historical rows. NB L5 was never anchored in-file — the "each is now ANCHORED" claim above held for L2–L4/L6 only (corrected v2.7 P6); **L6 (new, audit #3a)** `db_orders.mark_stale_orders` — caller-less by design, battery-pinned as the TIME twin of the live `mark_stale_orders_canceled`.
- **Named per-phase deviations (full text in commit bodies):** P4 deferred tasks 4.2 (`PLATFORM_TOKEN`) + 4.3 (QT maps) to P5 — both consumed only by the P5-deleted modules, and the QT maps' MODULE-LEVEL import in `platform_bridge` would break boot (via `api/router.py → routes_platform → platform_bridge`) if removed early. P2 kept `monitoring._check_plugin_connection_sync` (folded read→False) + its 3 tests rather than deleting — **superseded: the audit DELETED the method + all 3 tests in `c418268`** (Check 6 could never fire). Obsolete plugin tests were removed per-phase (P2 standby regression; P4 7 plugin-UI tests in test_task121/time_sync/phase8_deferred; P5 `TestPlatformFrames` + `TestNoDbConnInExecutingCode`).
- ~~**DEFERRED / opportunistic:** the corr-log `platform_*` categories are producer-less dead-but-present~~ → **DONE 2026-07-16 (v2.6 audit, spec erratum E37)**: `CAT_PLATFORM_FILL/SNAPSHOT/HELLO/PUSH` REMOVED from `core/correlation_log.py`; **registry is now 42, not 46**. The snapshot pin (`test_correlation_log_spine.py::test_registry_snapshot_ha3`) moved in the same commit — they must always move together. The spec's plugin surface (§3.2 `wsp` entry point, §4 `component`+`peer` sets, §5.4 rows, §10 criterion #1) is purged, E34 closed not-applicable, E36's count superseded. §4's "no dead peers" audit rule HOLDS AGAIN with no carve-out — independently verified: all 10 surviving peers are emitter-reachable, `quantower` is zero.

## ▶ AUDIT 2026-07-16 — 15 findings, ALL CLOSED (4 commits, each gate-green + agent-audited)

| Commit | Closes | What |
|---|---|---|
| `19ecac1` | **#2** | **The only real regression.** P1's extraction early-bound the singleton (`from core.order_manager_singleton import order_manager` at module scope in `schedulers.py` + `routes_dashboard.py`), so the ONE documented seam — `patch("core.order_manager_singleton.order_manager", …)` — could not intercept them: a test would pass while the REAL OrderManager ran against the REAL DB. Pre-v2.6 `patch.object(platform_bridge, "_order_manager", …)` reached every consumer via the shared bridge OBJECT. Fixed to the module-import form (deref at call time). **Demonstrated, not theorized**: reverting to the pre-fix shape turns the new pin RED. +8 pins in `tests/test_order_manager_singleton_seam.py` |
| `425cf87` | #3b, #4-#8, #13 | MED truth sweep — ~20 comments/docstrings describing the plugin (and its gating) in the present tense. PROSE ONLY. Incl. `schedulers.py:142` claiming *"Account/position refresh: plugin-gated (plugin is authoritative)"* (false since P2) and `_order_staleness_loop`'s docstring advertising a sweep P2 DELETED. **LB-R2's v2.6 re-open trigger EVALUATED (not just reworded) → RISK UNCHANGED**: the removed time-path was `is_connected`-gated → never ran standalone → v2.6 deleted dead code. LB-F3's "3 wired call sites" → 2 |
| `9983429` | **#1** (HIGH), #14 | Corr-log spec purge + **registry 46 → 42**, **E37 filed**. P6's doc sweep NEVER OPENED `correlation_log_spec.md`: it listed the deleted `platform_bridge` as a **"money-path critical"** `wsp` entry point and kept `quantower` in §4's peer set under the spec's OWN *"no dead peers"* rule — the invariant it asserts about itself was FALSE. Operator chose PURGE over a rule carve-out. **Rule HOLDS again**, independently verified (all 10 surviving peers emitter-reachable; `quantower` = 0) |
| `c418268` | #9, #10, #12, #15, **#3a REVERSED** | Deleted monitoring **Check 6** (plugin health — nothing could set `_ever_plugin_connected`; `run()` paid a call/tick for a guaranteed early-return; 9→8 checks everywhere) + **`active_platform`** (zero readers). **#3a reversed to WONTFIX** — see below |

**★ #3a — `db.mark_stale_orders` is DELIBERATELY caller-less. Do NOT delete it.** The audit filed it as orphaned dead code; investigation proved the filing over-called. The battery pins it as the **TIME twin** of the live snapshot sibling `mark_stale_orders_canceled` — LB-T2i's own docstring says so — and that PAIR is why the LB-F3 sweep exists; `test_correlation_log_state` pins its `via=time` tap. It is a generic DB primitive, same disposition as landmines L2-L5. Un-gating it was REJECTED, not overlooked: without plugin order snapshots a time threshold wrongly cancels real working stops. Anchored in-place (as is its L3 twin `data_cache.apply_account_update_platform`). *The real defect was the docstrings calling it LIVE — fixed in 425cf87.*

**Contrast worth remembering — both labels were BACKWARDS**: `active_platform` was called a "landmine" but was plain dead code (deleted); `mark_stale_orders` was filed as dead code but is a genuine landmine (kept). Neither survives pattern-matching; both needed investigating.

**Boot path: CLEAN.** The operator live-started the engine (clock synced) — the one class the `import main` smokes could never reach. Nothing found.

## ▶ NEXT SESSION — v2.7 model library (operator-gated)

v2.6 is closed. Next program: **`docs/design/v2.7_model_library_plan.md`**. Retire `/api/backtest/qt-import` (landmine L5 — the Quantower BACKTEST-RESULTS file upload, NOT the plugin) as part of it. **→ DONE: v2.7 shipped P1–P6 2026-07-16 (branch `v2.7/model-library`); L5 retired in P6.**

**Open / opportunistic (nothing blocking):**
1. **Startup REST-throttling (NOT a v2.6 bug):** on a stale/long-offline snapshot the startup's heavy backfills (`fetch_exchange_trade_history` income paging + `recover_offline_trades days=90` + per-position `fetch_ohlcv`, at `_startup_fetch` in `core/schedulers.py`) run BEFORE `is_initializing=False`, so a rate-limited or clock-drifted start blocks "ready" for minutes. Candidate fix: flip the ready flag first, defer to background. Own task.
2. **Live dogfood (reconciler acceptance §6-#5):** operator-driven open→amend→close with `CORR_LOG_PROFILE=linkage`; everything self-verifiable is green.
3. Reconciler leftovers: plan §4-R4 residuals (d)-(f) + N1/N2, and the optional residue-backfill script (operator-requested, dry-run-first).
4. `archive/quantower-plugin` is **LOCAL ONLY** — push it if you want the archive on origin. (Git history holds the deleted lines regardless; that branch is a convenience, not the durable record.)

**★ The "connecting endlessly" incident (RESOLVED 2026-07-16 — read before debugging):** the operator restarted on v2.6 and the engine hung on "Connecting to exchange…". Diagnosed from `data/logs/risk_engine.jsonl`: **NOT a v2.6 bug** — the startup fetches were stalling in Binance REST weight-tracker throttling (86-89%) + `fetch_time` throttling, the signature of **OS clock drift** (`-1021 Timestamp ahead`). `w32tm /resync` fixed it; the app launched. Evidence v2.6 was innocent: (a) no error in the live log; (b) `Startup order sync` (the P1 singleton) + account/position fetch SUCCEEDED; (c) every removed `is_connected` guard already took the standalone path pre-v2.6, so v2.6 added ZERO new REST calls (all 8 sites re-checked); (d) operator confirmed little/no offline trading → the 82→285 equity delta was a stale 2-day snapshot, not a trade gap. **Two lessons: clock-sync is a hard startup precondition; and `import main` smoke does NOT exercise the connect path — only a live start (or `TestClient(main.app)` lifespan) does.**

## ★ HISTORICAL (below — superseded by the v2.6-COMPLETE status above; kept for reconciler/linkage-arc context)

## ▶ STATUS 2026-07-15 — reconciler R0–R5 COMPLETE (ALL 9 battery findings fixed; program CLOSED)

The attribution-reconciler program (`docs/design/attribution_reconciler_plan.md`, phases in §4) executed R0–R3 in one session, R4 + R5 in the next; every phase: full-suite gate SOLO + independent-agent audit + folds + one commit.

- **R5 (close-out)**: **E36 FILED** (spec §15 + inline §12/§5.6 superseded-pointers + cookbook) with the named second-order deviation — `attr_identity_reconcile` NOT added; the R2–R4 outcome-riding (MIGRATED/RECONCILED/SEALED on `attr_junction_form`) RATIFIED as final. **R3-audit riders shipped**: NIT-6 structural rebuilt:/bf: fence on the lifecycle sweep (+pin), NIT-5 [FIXED] banners. **R4 residual (a) FIXED**: unsealed-basis in `position_primary_calc` + the live-enrich twin (fall back to ALL rows when none unsealed — rebuilds keep their primary); pinned with the decisive 3.0-sealed-vs-1.0-live shape + enrich assert. **Holistic 3-agent audit (code/tests/docs): 3× SHIP-WITH-NITS, folds applied** — migration gained the symmetric rebuilt-namespace guard (+pin), E36 mixed-component caveat, cookbook dedup caveats, len-guard, v2.6-plan precondition-satisfied annotation. **Filed not fixed (plan §4-R4 residuals d–f)**: post-seal straggler row can out-rank the sealed majority on a rebuild (audit's proposed fix was traced WRONG for the reuse case — correct shape = fill-timestamp-evidence seal inherit, needs its own battery scenario); interleaved-rung basis flip; pre-existing `_tpsl_amended_seen` raw-tpid stash. **Perf gate (`-m perf`): 3 passed** — acceptance #2 fully met. Optional residue-backfill script DEFERRED (named: delta-reconcile self-heals on touch; destructive tooling stays operator-requested). **Remaining acceptance item: §6-#5 live dogfood** — operator-driven open→amend→close with `CORR_LOG_PROFILE=linkage`; everything self-verifiable is green.

- **R4 (this session) — lifecycle seal + pair coherence + LB-D4**: **LB-F4 DEAD** (seal-at-close: new `positions_calcs.sealed_ts`, §5-Q3 DECIDED as a COLUMN — closed-row existence ≠ finality because T2.11 writes one row per partial rung, and a fills-sum check self-pollutes in the exact reuse scenario; owner's `seal_position_lifecycles` stamps exit_time_ms at `is_final` only; mint/reuse lookup ignores sealed rows with an OWN-TRIPLE exception so a late fill of a sealed trade's own order continues that trade). **LB-F7 DEAD** (insert_closed_position's lifecycle carry-forward PAIR-GATED on calc equality — a calc rebind takes the writer's whole pair; T232 same-calc preserve intact, pinned). **LB-D4 DEAD** (position_grouping close-calc rule delegates to the owner's §3.2 `_most_contributing_calc_id` over opening fills; T3 scenario drives the real rebuild lane on the LB-D2 shape). New pins: sealed_ts stamp, partial-no-seal + scale-in continuity, own-triple late fill, carry-forward-when-calc-unchanged, backstop-seal (audit M1). Battery = **59 plain-passing tests at R4 → 62 after R5's three pins (the R4-time "62" claim conflated a 6-file run — corrected at R5), xfail set EMPTY**. **R4-audit (SHIP-WITH-NITS) folded 3 findings pre-commit**: M1 the disappearance backstop's recorded-but-never-final lane completed calcs but never sealed (now seals from the final row's exit_time_ms, battery-pinned); M2 the R2 re-key branch transported a stale sealed_ts onto the canonical key (now resets NULL — a live trade's row must never arrive frozen-sealed); M3 the seal is EVIDENCE-GATED (`force_final or total_open_qty > 0` — the opens-unresolvable degraded lane must not seal a live position on a partial). KNOWN RESIDUALS (plan §4-R4): sealed+fresh rows both feed `position_primary_calc` on a reused tpid; seal rides the +2s deferred build (N1); offline lanes never seal (N2) — all R5/T3 candidates; live adapters never reuse tpids.

- **R1 `665e804` — pure extraction**: `core/position_identity.py` (the identity owner) now holds ⑨ tpid resolution, the LB-F5 stamp, junction formation + lifecycle mint (WITH the position:opened/scale_in emissions — audit proved events-move was forced), the Defect-8 replay, the §3.2 primary-calc rule, the close-time backfill. OrderManager keeps every method name as a thin delegate — caller/test surface unchanged; gate counts were IDENTICAL pre/post (pure-move proof). The owner is the SOLE junction writer + lifecycle mint in `core/` (acceptance-#4 grep; fences: rebuild lane + scripts/).
- **R2 `aa20957` — canonical key**: replay guard ≡ write key by construction (**LB-F8/HA-42 DEAD** — N-fold junction inflation pinned 1.0→1.0→1.0); builder key-migration pass merges dual-keyed rows + re-stamps fills + corrects the stale order stash (**LB-F6 DEAD**); ⑨ tier-0 reduce-only gate (LB-F5 residual closed); perf tripwire added. **R2-audit caught a MAJOR pre-commit**: ungated migration would drag CORRECT rows onto stale stash keys → the DIRECTION GATE (only a fill carrying its OWN tpid migrates) + mirror-ordering pin.
- **R3 `b50b59c` — retro-reconcile**: mint-after-fill sweep + **delta-reconcile** (**LB-F9 DEAD**; §5-Q2 DECIDED: evidence-gated, ORDER-keyed, SUM(ABS), on-change, direction-gated — the ungated sweep's mirror mid-state double-count was traced pre-implementation); replay guard gained order_id (second-order-same-calc now replays, pinned). FREE HEAL: historically F8-inflated/F9-starved junction rows self-correct at their next fill/replay event. Honesty correction in the plan: reversal open legs heal AT CLOSE via the retained walk-path backstop, NOT at ACCOUNT_UPDATE.

**Battery score**: LB-F1..F9 → **ALL 9 FIXED + battery-flipped** (F1/F2/F3 pre-program, F5 patch, F6+F8 at R2, F9 at R3, F4+F7 at R4; LB-D4's owed T3 scenario also shipped at R4). Battery = 5 `tests/test_linkage_battery_*` files + helpers + the perf file, **62 tests, 0 xfails**; ledger + §7 decision in `docs/design/linkage_battery_plan.md`.

## ▶ NEXT SESSION — the v2.6 program (operator-gated per phase)

**PROGRAM MAP (settled with the operator 2026-07-15 — don't re-confuse
the two "extractions"):** the LINKAGE-DEBUGGING ARC (correlation log →
linkage battery → attribution reconciler R0–R5) is **CLOSED**; its R1
extracted identity LOGIC out of the OrderManager *class* into
`core/position_identity.py`. The NEXT program is **v2.6 = REMOVE THE
QUANTOWER PLUGIN INTEGRATION** (`docs/design/v2.6_remove_quantower_plugin_plan.md`)
— Binance-direct becomes the only data path. It is an
**extract-then-delete** (plan §2 critical finding): **Phase 1 extracts
the OrderManager OBJECT out of `platform_bridge` into a standalone
singleton** (relocates the construction site, NOT the class body; the
"OrderManager extraction" belongs to v2.6, NOT to linkage), Phases 2–5
constant-fold the plugin gates and delete bridge/routes/plugin
(archive first), Phase 6 tests+docs. The v2.6 §6 reconciler-first
precondition is **SATISFIED**; the **62-pin battery is the
extraction's safety net** — any silent attribution regression turns
pins red. Per-phase: one task → green + audited + commit → STOP.

**Operator items (open, non-blocking for v2.6 Phase 1):**
1. **Live dogfood (reconciler acceptance §6-#5, operator-driven)**: sync clock (`w32tm /resync`), start the engine with `CORR_LOG_PROFILE=linkage`, drive one open→amend→close, confirm ONE coherent chain with owner-emitted attr lines (`component:"position_identity"` on junction/tpid decisions; any MIGRATED/RECONCILED on a healthy trade = investigate). Cookbook has the recipes.
2. Reconciler leftovers if ever needed: plan §4-R4 residuals (d)–(f) + N1/N2, and the optional residue-backfill script (operator-requested, dry-run-first).

**Working discipline (proven across R1–R5 — reuse for v2.6 phases)**: read the plan's phase bullet + its hand-offs FIRST; targeted tests, then FULL GATE SOLO + independent audit agent (read-only, NO pytest while the gate runs) + fold before commit; ONE commit per phase, then STOP for the operator. The battery caught implementer errors 4× across the reconciler — trust a red battery over your own diff. R-phase-specific precedent (identity work lands in `core/position_identity.py`; OrderManager delegates stay thin) still binds any future identity touch.

**Gotchas added this session**: future tests must patch `core.state.app_state` (NOT `core.order_manager.app_state`) to reach ⑨ tier-1; the ERROR-twin test matches the replay's SQL text verbatim (update it if the SELECT changes); PowerShell line-splices must verify inter-method neighbors (a splice once ate `_process_reversal_split` — the battery caught it same-run); corr-tap outcome additions (MIGRATED/RECONCILED) ride `attr_junction_form` per R2 precedent — do NOT add registry categories before E36.

## ▶ STATUS 2026-07-14/15 — linkage battery COMPLETE + 4 fixes + reconciler DECIDED (PUSHED)

**Track 1 is DONE** (supersedes the "NEXT SESSION — TWO tracks" block below, kept for context). The backend attribution battery shipped: 5 files (`tests/test_linkage_battery_{e2e,disagreement,interference,t2_pipeline,t2_lanes}.py` + `tests/linkage_battery_helpers.py`), **53 deterministic tests = 48 pins + 5 strict-xfails**; spec + findings ledger + decision in **`docs/design/linkage_battery_plan.md`**. 9 findings (LB-F1..F9), 4 mechanism families.

- **Fixed + battery-flipped**: LB-F1 (manual-link junction replay, `d9ff4bf`), LB-F2 (admin confirm → choke-pointed lane) + LB-F3 (bulk stale-cancel release sweep, both siblings) (`c636772`), LB-F5 (⑨ tier-0 parent-order tpid + reduce-only-gated close-order stamp, `02eb743`, spec erratum E35).
- **Headline discovery — LB-F8 = HA-42 with the filed mechanism CORRECTED** (audit-impact-imprecision +1): NO per-fill dual-path exists; the real bug is the guard-key/write-key divergence in `_ensure_junction_if_linked` (guard checks the ORDER-stash tpid, the replay writes under MAX(fills.tpid)) → N-fold unbounded `contributed_qty` inflation per WS/bracket-child event, behind a narrow stash gate. **LB-F9** (new): fill-before-mint first fill permanently stranded — junction UNDER-count, always-on, the mirror image. Do NOT trust the old HA-42 wording further down this file.
- The battery caught its own author pre-commit (LB-T2a failed the ungated LB-F5 stamp — reversal orders are both closer and opener). The net works.

**§7 DECISION** (`dac427b`, battery plan): **BUILD THE ATTRIBUTION RECONCILER**, scoped to identity ownership (families 1+3); family 4 closed surgically; LB-F5 patched. Decision rule: routing bugs patch cleanly, derivation bugs multiply sites. The 5 remaining xfails (LB-D5, LB-D6, LB-I5, LB-T2d, LB-T2e) ARE the acceptance set.

## ★ HISTORICAL (2026-07-15 midday — superseded; R1–R3 EXECUTED same day, see the EOD status block at the top)

**`docs/design/attribution_reconciler_plan.md`** (rev 2 — 2-agent adversarial design review folded) is the program doc: `core/position_identity.py` owner, 11-row consumer disposition, phases R0→R5, per-phase gates + audits + the acceptance-#4 broad re-grep. Sequencing: R1–R5 **before** v2.6 Phase 1 (cross-ref in the v2.6 plan §6). Memory: [[project-linkage-battery]].

## ▶ STATUS 2026-07-13 — offline income-window incident (DONE + PUSHED)

Operator made several offline (engine-down) trades — mostly losses — that never appeared in Position History. **Root cause = BACKEND** (not frontend): `fetch_exchange_trade_history` called `fetch_income_history` with NO startTime, and Binance's income endpoint returns only ~7 days from a given startTime → after a >7-day offline gap the older trades never entered `exchange_history` → gap detection never flagged them → no userTrades recovery → no `closed_positions` → missing from History.

- **Code fix (`ee4a4dd`, prevention)**: `get_last_income_time` anchor + `_fetch_income_windowed` pages income in ≤7-day windows to now (full-page → re-fetch from `max_t` for same-ms tie-safety; `MAX_PAGES=200` backstop; dedup). `fetch_exchange_trade_history` anchors at last-income − 1h; new `since_ms` param for a one-time wide reach-back. **Forward PREVENTION, not self-heal** — data already stranded behind an advanced anchor still needs the manual userTrades recovery. +7 tests (`tests/test_income_windowed_fetch.py`); 2-agent audit (pager SHIP; integration flagged the prevention-vs-self-heal split).
- **Data recovery (DB, not a commit)**: refix_fills_from_usertrades + per-symbol rebuild → **IN 101 / TAC 18 / NFP 20 / PUNDIX 1 = 140 positions, −323.71 net** (reconciles the ~606→291 equity drop). The `since_ms` `exchange_history` backfill also surfaced a 4th symbol the ad-hoc probe missed (NFPUSDT). Gap set converged to `[]`.
- **UI-surface note (verified live)**: engine-reconstructed offline closes render in **History → "Closed Positions" tab** (`/fragments/history/closed_positions`, reads `closed_positions`) + the **Exchange tab** (income ledger) + Analytics + cockpit recent-closes. They do NOT appear in the **"Trade History" tab** — that reads a SEPARATE `trade_history` table populated only by the manual `/history/log_close` journal (`insert_trade_history`, api/routes_history.py:84; NO auto-projection from `closed_positions`). Don't confuse the two tabs when verifying.
- Full detail in **[[project_spcx_offline_backfill_bug]]** memory (2026-07-13 block).

## ▶ STATUS 2026-06-24/25 — live dogfood + debug session (DONE)

The corr-log dogfood (HA-6/HA-7) is **VERIFIED live**; the session then fixed a series of calc-linkage + analytics bugs on the running engine. Every fix: targeted tests + an independent-agent (or multi-agent workflow) audit + full-suite gate + live UI verify. Full detail + the parked items live in the **[[project_spcx_offline_backfill_bug]]** memory.

**Fixed on this branch:**
- **SPCX offline-history corruption** — rebuilt from Binance userTrades (`fromId` paginator); live-remediated to 70 correct positions; gap set converged to `[]`. (`b579db6`/`f80636a`/`0ce2120`, PUSHED.)
- **Calc-linkage**: entry-fill `calc_id`/`lifecycle_id` attribution — a link-timing race (the entry fill is enriched BEFORE the matcher links the order) left every linked position's ENTRY fill unattributed (exec-link drawer "—", `/context/calc` missing the entry fill); fixed at link-time (`order_enrichment`) + a close-time backstop (`_backfill_open_fill_tpids`) + a one-time backfill script (`90a9da4`). Position-History **"amended" label** (`9838ca7`, on the `43c2c09` backend column). **SL-removal = RED** severity (`32df20e`). Matcher / junction / exec-link all verified HEALTHY.
- **Analytics metrics** (`17976af`): Max Drawdown (read the rolling dd-GATE column → 0%; now period peak-to-trough off the equity curve), Cumulative PnL % (div-by-0 on uncaptured deposits → 0%; now initial-equity base + clarifying tooltip), Profit Factor/Expectancy (empty manual `trade_history` journal → "—"; now `closed_positions.realized_r`), Sortino(MAE) (positive-biased `ratio_card` hid the inherently-negative metric → "—"; now rendered inline).
- **Calculator**: verified mathematically sound (`risk_usdt × atr_c / sl_pct` → size, `× regime_mult`, lot-snapped). NOTE: `atr_c ≤ 1`, so realized risk = `atr_c × the displayed 1%` (volatility-defensive — never over-risks; volatile symbols risk notably less).

## ★ HISTORICAL (2026-07-14, Track 1 COMPLETED 07-15 — see the status block above) — the two-track strategy that produced the battery

**Goal (as set)**: continue debugging calc → order → fill → position → closed_position attribution + the plan-badge / exec-link / history render layer. Track 1 executed in full (53 tests vs the ~30-40 estimate); Track 2 remains deferred to post-v3.0 as designed.

**Strategy (settled 2026-07-14) — separate by DURABILITY, not just by layer.** The roadmap forces it: **v3.0 is a ground-up UI rewrite** (design doc: *"v3.0 is a ground-up visual refresh… the polished design it will be **rebuilt against**"*) → every current cockpit/calc/history DOM selector + click-flow is throwaway. **v2.6 extracts the `OrderManager` out of `platform_bridge`** (`docs/design/v2.6_remove_quantower_plugin_plan.md` §2 — the single object every linkage decision flows through). So the two layers have OPPOSITE lifespans: backend attribution is durable through both releases; the browser UI dies at v3.0. Invest accordingly:

| Layer | Survives v2.6 | Survives v3.0 | Verdict |
|---|---|---|---|
| Attribution logic + DB outputs (`calc_id`, junction, `badge_level`, closed rows) | ✅ behavior preserved | ✅ visual-only | **invest now — durable** |
| Endpoint/fragment data contract (what `/fragments/*` returns) | ✅ | ~partial (endpoints may be reworked) | cheap HTTP tests, opportunistic |
| Browser DOM / selectors / click sequences | ✅ | ❌ **thrown away** | **don't build now** |

### ▸ TRACK 1 — Backend attribution battery (NOW; heavy; doubles as the v2.6 safety net)
Linkage is a backend problem and the corr-log ("booklog") already makes it observable. Build the scenario battery as **deterministic backend fixtures**, NOT browser walks:
1. **Model the linkage state machine — 3 axes** (from the real state-mutating actions): **calc lifecycle** (`/calculator/calculate`·`/cancel`·`/clear`·`/window` → none/active/expired), **order link-state** (`/orders/{id}/manual_link`·`/mark_unplanned`·`/history/exec_link/confirm` → unlinked/auto-linked/manually-linked/marked-unplanned/needs-link), **manual journal** (`/history/log_close`·`/log_execution` → the SEPARATE `trade_history` table, NOT `closed_positions`). The bug-bearing dimension is **calc-timing vs order-arrival** (calc-before-order = auto-link; calc-after = needs-link — the ETH case).
2. **Scenarios = each transition once + pairwise-interference (two actions sharing a state axis) + the known end-to-end flows** (place→auto-link→amend→close→history; place→needs-link→manual-link→close; place→mark-unplanned→confirm-not-in-linkage). **~30–40 total, NOT the button factorial** (~2M+ permutations, ~99% waste). Combinatorial-testing reality: bugs are ≤2–3-factor, and every past frontend linkage bug here (ticker-leak, cross-clear drift, PENDING/EXPIRED race, amended-vs-off-size label) was ≤2-factor.
3. **Assert the attribution OUTPUTS** (`calc_id`, `lifecycle_id`, junction row, tpid grouping, `badge_level`, `closed_position` row), observed via `CORR_LOG_PROFILE=linkage` + `scripts/corr_tail.py` (cookbook recipes). **Build on the EXISTING harness** — `tests/test_correlation_log_attribution.py` (2185 L), `test_correlation_log_replay.py` (626 L, the 8-bug replays), `test_linkage_binance_ws.py`, `test_linkage_history_plan.py`, `test_phase1_matcher*.py`, `test_phase2_junction.py`, `test_exec_link.py`. Seconds to run, no browser, no live market.
4. **Triage BEFORE fixing** — dedup by MECHANISM: most symptoms collapse to the shared ad-hoc-attribution root (whack-a-mole history: fixing one of ~6 attribution sites shifts load to another — ⑨→close-recording is the proof). Then **independently verify each mechanism** (CLAUDE.md re-investigation discipline — ~53% of race-framed findings were false positives; a filing's named mechanism is often wrong even when the symptom is real). Kill false-positives HERE.
5. **Each fixture becomes a permanent regression test** — the net this whack-a-mole subsystem has never had, AND the exact guard that tells you **v2.6's `OrderManager` extraction didn't silently regress** `calc_id` propagation / junction / tpid grouping. **Build (most of) Track 1 before/alongside v2.6** — it pays for itself twice.

**Meta-lever**: this battery IS the acceptance harness for the deferred **attribution reconciler** (ONE module owning fill→position→calc — the structural cure; spec §12, HA-42 first input). If discovery confirms most bugs share the ad-hoc root → build the reconciler instead of patching N sites. **The battery decides patch-vs-reconciler.**

### ▸ TRACK 2 — Frontend browser battery (DEFER to post-v3.0; do NOT build against today's DOM)
v3.0 rewrites the DOM → a Playwright suite against current selectors is throwaway. So:
- **Now**: fix only *acute* current frontend bugs, minimally + ad-hoc — no durable browser suite. If a frontend safety net is wanted in the interim, put it at the **fragment-HTTP-contract** layer (assert `GET /fragments/history/closed_positions` returns the right rows/badges — fast, no browser, more durable than DOM).
- **Post-v3.0 (UI stable)**: build the real Playwright battery against the NEW DOM using the state-machine/pairwise model above, and **seed state at the backend** (DB/API fixture) so each browser test is ONE transition + assert — never click through 5 prerequisite steps. That seeding is the single biggest Playwright speedup.
- **Why deferring is ~free**: once Track 1 proves attribution is correct and the fragment endpoint returns the right data, the only residue for the browser is pure presentation — which v3.0 rebuilds anyway. Browser-layer linkage testing is the lowest-durability work.

## ▶ OPEN / PARKED
- **PARKED — historical residue, operator-deferred, NOT live bugs**: SPCX 80 ungrouped fills (cosmetic drill-down gap; P&L correct); 2 historical `positions_calcs` junction gaps (VELVET/ETH); ~106 ungrouped fills total. NB the reconciler plan's §5-Q2 delta-reconcile (if adopted at R3) heals the F8-inflated/F9-starved junction shapes for free, and R5 lists an optional dry-run backfill for the rest. (2026-07-15 correction: "live code prevents recurrence" was auto-lane-only — the manual-lane gap was reproducible until `d9ff4bf`.)
- **PLANNED (separate sessions, design docs committed)**: `docs/design/v2.6_remove_quantower_plugin_plan.md` (remove the Quantower plugin → Binance-direct only; the `platform_bridge` / `_user_data_loop` plugin gate then becomes dead code), `v2.7_model_library_plan.md`, `v3.0_models_tab_design_prompt.md`.
- **Deferred lever (gated)**: deterministic linkage via engine-placed `clientOrderId` tagging — the fuzzy 6/6 matcher exists *because* Quantower placement can't tag; reachable once the engine becomes the order-entry point (post-v2.6).

---

### Historical playbook — corr-log dogfood (build COMPLETE; steps below were used 2026-06-24, kept for the `corr_tail.py` recipes)

The correlation-log program (Phases 0–5, 12 tasks) is **COMPLETE + AUDITED + PUSHED**.

**Playbook (operator drives trades; ask before probes that touch their stream):**

1. **Start the engine** (observe-only, force-kill safe): `.venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000`. Confirm `GET / → 200` + Binance WS up. The correlation log starts in the lifespan (writer thread) and begins writing **`data/logs/correlation/corr-2026-06-14.jsonl`** (UTC daily, append-only, no-rename rotation, 7-day prune).
   - **Profile**: default `CORR_LOG_PROFILE=full` (everything). For linkage-focused debugging set **`CORR_LOG_PROFILE=linkage`** (drops market/http/outbound noise; keeps lifecycle/state/attr/db/bus/ws_lifecycle — NB it also drops the webhook POST + venue REST, by design — E33).
   - **`pubsub_publish` is now SAMPLED 1-in-10** by default (E32) — set `CORR_LOG_PUBSUB_SAMPLE=1` to see every UI publish when debugging the SSE path.
2. **Read it** — `scripts/corr_tail.py` (CL.T4); recipes + the as-built keys + benign-class caveats in **`docs/correlation_log_cookbook.md`**:
   - one chain in order: `corr_tail.py --corr-id wsu-…`
   - a trade's whole life (substring; works for calc_id / terminal_position_id / eoid): `corr_tail.py --calc-id <id> --days N`
   - attribution for a ticker: `corr_tail.py --symbol XAUUSDT --category "attr_*"`
   - **race forensics**: `corr_tail.py --interleave <from_seq> <to_seq>` (corr_id + task columns)
   - **duplicates**: `corr_tail.py --dups` (per-(category,key); funding re-polls hidden by default)
   - **live tail**: `corr_tail.py --follow --category "attr_*"`
   - stranded identity (E23 — the REAL key, not the spec's `tpid` shorthand): `jq 'select(.payload.terminal_position_id=="")'`
3. **Live-verify the log (HA-6/HA-7 — the open live-smoke items)**: drive a real open→fill→close (operator) and confirm ONE coherent chain end-to-end. Tripwires: any `corr_id=""` or `rest-*` fallback envelope = a missing-scope entry point (a finding); any unexpected `db_write ok:false` = the HA-35/HA-41 write-failure seams firing; the §4.1 leak query (a `calc_symbol_change` with no following `ws_stream_rebuild`) = bug #4.
4. **The 8 historical bugs each have a one-query signature** (cookbook "Reading a race" + the `q_*` recipes) — use them if linkage misbehaves live. The disabled-parity probe PASSED in tests (24 env-on / 0 env-off, identical DB), so the log adds zero engine-behavior risk — observe freely.

**AFTER dogfooding** (operator-gated, separate program): the **attribution reconciler** (spec §12) — ONE module owning fill→position→calc so the ~6 ad-hoc sites stop re-deriving (the structural cure). ~~Needs its own plan + spec~~ **PLAN EXISTS (2026-07-15): `docs/design/attribution_reconciler_plan.md`**. ⚠ **HA-42's filed mechanism here is RETRACTED** — the battery (LB-F8, `85656aa`) proved there is NO per-fill double-junction path; the real over-count is the guard-key/write-key divergence in `_ensure_junction_if_linked` (see the 07-14/15 status block at the top). The §5.6 baseline-diff method stands.

## Operating rules (operator-set — binding)

- **ONE task → green + audited + commit → STOP** and wait for the operator's explicit "continue/proceed" ([[feedback_one_task_then_wait]]). A standing "proceed" covers ONE task, not the list.
- **Independent-agent audit before each task's commit** — it caught real issues on EVERY task (incl. a BLOCKER on T3b-entry: a widened SELECT broke two hand-rolled test fixtures the targeted slice missed); fold blocking fixes pre-commit.
- **★ NEVER assert history in a comment/docstring from memory — check `git show` first** ([[feedback_no_fabricated_provenance]]). The v2.6 audit session wrote TWO fabricated provenance claims, both caught by auditors, both in commits whose stated purpose was making docs truthful: (1) "removing this comment would have turned the test RED" — it wouldn't; the string it keyed on survived in kept text; (2) "this test was misfiled inside TestRegimeFreshness" — `git show HEAD` disproved it, AND the edit itself had CAUSED it (removing a `class` header re-parents its orphaned methods into the preceding class; pytest reported it there; a plausible history got invented for it). **Green tests cannot detect a false sentence** — 3943 passed with both in the tree. If you can't verify a provenance claim cheaply, omit it: a comment stating the current invariant beats one with an unverified origin story. When a test fails somewhere surprising right after your edit, suspect YOUR edit (`ast.parse` + dump the class/method map).
- **★ A finding list is a SAMPLE, not an inventory — broad-re-grep the defect CLASS before AND after folding** ([[feedback_audit_inventory_undercounts]]). The v2.6 audit under-counted 3×, the third time AFTER two review rounds. Derive the grep from the MECHANISM and probe several phrasings; scope it to `core/ api/ tests/ scripts/` + root `*.py` + live docs. This is CLAUDE.md's own audit-inventory-incomplete pattern — mandatory, not opportunistic.
- **Run the gate full-suite SOLO** — concurrent pytest runs contend (DB/CPU) → timeout artifacts (audit-time-artifact discipline: re-verify before chasing).
- **Keep audit-agent briefs LEAN** — two big holistic-audit agents died to session limits (~160 tool calls lost; SendMessage is NOT available in this environment to recover a cut-off agent). Cap the charge list, set an explicit tool-call budget in the brief, run heavy agents in background, and demand the report even if abbreviated.
- Commit conventions: `feat(correlation-log): …` / `docs(correlation-log): …`; deviations named "X instead of Y because Z". Holistic filings are docs-only commits (b757d94/fed5ac0/c408780 precedent — no full-suite gate needed).

## Correlation-log program state — COMPLETE: Phases 0–5, all 12 tasks (TEN §5.6 attribution categories live; **42**-category registry since v2.6/E37, was 46) — PUSHED

| Commit | Task | Content |
|---|---|---|
| `8ccd90b` | docs | spec rev 2 + implementation plan (4-agent design audit) |
| `db89ae0` | CL.T0a | spine: corr_id contextvar, envelope, 45-category registry→derived profiles, emit pipeline, redaction |
| `3b7c6ca` | CL.T0b | sink: writer THREAD, daily rotation (no rename), prune, MB-guard, overflow; conftest session-floor |
| `9ad8764` | CL.T1a | HTTP middleware (SSE close-tap, /static skip) + set-only `tick()` on all 18 loop bodies |
| `9cb0efe` | CL.T1b | per-frame mints wsu/wsm/wsp/wsn + §5.4 frame taps w/ dedup_keys + §5.4b WS-lifecycle taps + ws tasks named |
| `b757d94` | docs | Phase-1 holistic audit FILED: spec §15 E1–E12 + plan §9.4 HA-1..12 |
| `a6d839d` | CL.T2a | bus queue carries + re-binds the publisher's corr_id; bus_publish/bus_deliver from the instrumented dispatch; 15-file sweep |
| `c421747` | CL.T2b | REST chokepoint taps, webhook hand-off #2 (close→bus→queue→POST = ONE chain), Finnhub/FRED/yahoo/pubsub taps, HA-1..5 |
| `fed5ac0` | docs | Phase-2 holistic audit FILED: E13–E18 + HA-13..22 (MED HA-13: `linkage` profile drops the whole outbound group) |
| `3646a4d` | CL.T3a | spec §5.5 sweep: data_cache applies (closes_detected list, tpid_minted flags, waited/held_ms, portfolio on-change), calc/link transition taps, order_status_applied ws/reconcile/stale-mark, reconcile_promote, db_write at 12 writers w/ failure twins ("row not written" = a line) |
| `331f00c` | CL.T3b-entry | attr_match_attempt (matcher wrapper+trace — query_failed no longer ambiguous w/ UNPLANNED; 7 gate skips; manual paths), attr_junction_form (no_position_key = the historical empty-tpid shape + post_link_replay), attr_bracket_inherit (applied:false visible), attr_reenrich_trigger (child+fill arrival) |
| `b35389a` | CL.T3b-close | attr_tpid_resolve (tiers: live_position/entry_order_fallback + snapshot_recovery), attr_close_build (strict→walk→backfill→row_written on ONE line; insert_closed_position→ok bool), attr_enrich + attr_drift_check (on-change memo, PRUNE ON ENTRY; bug #h = one line) |
| `fd5b56e` | CL.T3c | attr_funding_assign (open/closed/orphan paths) + §4.1 race fixture (two named tasks, reconstructable from envelopes alone) + duplicate fixture (split: log accepts 2 lines / ENGINE invariant verified HOLDS) + one-chain narrative — FIRST SHIP-verdict audit (differential probe) |
| `c408780` | docs | Phase-3 holistic audit FILED: E19–E28 + HA-23..42 + §9.2 shas; disabled-parity PASS (24 env on / 0 off, identical DB); scenario envelope counts (linked routine update=7, first-link~10, child~14, open fill~12, close ~9+8) |
| `3b66da5` | CL.T4 | reader: `scripts/corr_tail.py` (filters/--interleave/--dups/--follow/--raw, tolerates unknown fields) + `docs/correlation_log_cookbook.md` (as-built keys: E23 terminal_position_id, HA-32 dedup table + row_written, HA-33/34/38 benign classes) |
| `52e609a` | CL.T5 | **close-out**: HA-14 pubsub sample (default 10) + HA-23 closes-cap + HA-28 SKIP-dedup; perf gate (`perf` marker, p50<5%); 8-bug replay + amend/cancel legs; **HA-35** link-write twin + **HA-40** attr_close_stamp (10th attr) + **HA-41** audit-log twins; 3-agent audit; spec §15 E29–E34; both doc headers → COMPLETE |
| `3309b15` | docs | CL.T5 post-commit audit (3 agents: code PURE-OBSERVABILITY / tests SOLID / docs HONEST) + honesty folds (stale "nine"→"ten as-built/E30" cross-refs, HA-9 footnote, HA-41 connect-comment NIT) |

**Where things live**: `core/correlation_log.py` (registry/_PROFILES/emit/sink — the spine; **42 categories** incl. 10 attr, snapshot-pinned — was 46 until v2.6/E37 dropped the four producer-less `platform_*`). Taps: `main.py`, `core/{ws_manager,news_fetcher,event_bus,webhook_dispatcher,regime_fetcher,schedulers,monitoring,data_cache,calc_state,link_state,order_manager,position_identity,order_enrichment,calc_correlation,link_actions,db_orders,db_trades,event_log,trade_event_log,funding_handler}.py`, `core/adapters/base.py`, `core/pubsub/*` (`platform_bridge` removed — v2.6 P5 deleted it; `position_identity` added — reconciler R1). **Reader**: `scripts/corr_tail.py` + `docs/correlation_log_cookbook.md`. Conftest: `_corr_log_session_floor` (SESSION) + `_isolate_correlation_log_dir` + per-test corr reset. Tests: `tests/test_correlation_log_{spine,entrypoints,ws,bus,boundaries,floor,state,attribution,replay,perf}.py` + `test_corr_tail.py` (~310 corr tests; `perf` excluded from default). Governing docs: `docs/design/correlation_log_spec.md` (§15 errata E1–**E37**; status COMPLETE) + `docs/design/correlation_log_implementation_plan.md` (§9.2 SHIPPED shas, §9.4 ledger HA-1..42 with full Phase-5 disposition).

**Open ledger = fully dispositioned** (plan §9.4 Phase-5 table — no MISSED-by-silence). CLOSED: HA-6/14/23/28/35/40/41 (+ all P1/P2 closures). ACCEPTED-verdict: HA-8/11/13/24/36. Out-of-scope: HA-34/38 (cookbook/E15), **HA-42** (ENGINE defect → reconciler-program input). DOWNGRADED-to-opportunistic-with-reason (test-debt + payload-field nits, NONE a diagnostic gap): HA-7/9/10/15/16/17/26/27/29/30/31/33/37 — pick up at "next touch" of each file if desired, but none blocks anything.

## Gotchas / environment (hard-won across the program)

- **LOW-023**: the engine app tolerates exactly ONE in-process `with TestClient(main.app)` lifespan per pytest process (`test_routes.py` owns it). Middleware tests mount the real middleware fn on a tiny lifespan-free app — never add a second real-app TestClient.
- `tick()` is SET-ONLY (loop tasks own their context); conftest resets corr per test.
- The 0-byte `data/logs/correlation/corr-2026-06-10.jsonl` is a pre-floor-fix artifact deliberately LEFT in place (operator no-delete rule). Suites must leave the live dir byte-identical — snapshot before/after every gate run. **When the engine runs live today it creates `corr-2026-06-14.jsonl` ALONGSIDE it** — that's the real live log to read; the 0-byte file stays.
- **Live-debugging knobs (CL.T5)**: `pubsub_publish` is sampled 1-in-10 by default — `CORR_LOG_PUBSUB_SAMPLE=1` to see all. `CORR_LOG_PROFILE=linkage` cuts market/http/outbound noise (also drops webhook POST + venue REST, by design). Registry is **46** categories (10 attr — `attr_close_stamp` is the 10th, HA-40). The `perf` gate is excluded from the default run (`addopts = -m 'not perf'`); run it deliberately with `-m perf`.
- **Matcher entry tolerance is 0.25%** — a live market fill >0.25% off the planned average won't auto-LINK (use a limit order or widen `entry_tolerance_pct`); snapshot-recovery + close-tpid fallback are HEDGE-mode-keyed `(symbol, position_side)` (a one-way `BOTH` order won't match — documented observe-path gap).
- **Test-author note (CL.T5)**: to force an INSERT failure in a sqlite path, inject a `sqlite3.Connection` SUBCLASS via the `factory=` arg — the C-level Connection forbids per-instance `.execute=` assignment (it silently no-ops). See `tests/test_correlation_log_state.py::_fail_insert_connect`.
- Binance ALGO frames key their id as `aid` (not `i`); dedup_keys are OMITTED when the id is missing.
- **Hand-rolled `orders`-table test fixtures must carry `terminal_position_id` + `lifecycle_id`** — the matcher's widened SELECT reads them (the T3b-entry BLOCKER: `test_production_parity` + `test_calc_id_wiring` broke; both fixed).
- **DB `execute` stubs must be dual awaitable/async-CM** — the T3a corr-tap pre-SELECTs consume cursors via `async with conn.execute(...)`; a bare async-def stub breaks (the task101 sweep has the reference fake, `_stale_exec_stub`).
- The enrich/drift on-change memo (`om._attr_enrich_memo`) PRUNES ON ENTRY; tests that reuse one OrderManager across passes rely on it.
- Throwaway probe/commit-msg artifacts live in `e:/tmp` (`cl_parity_probe.py` disabled-parity proof, `cl_perf_probe.py` perf-baseline calibration, per-audit probes + commit-message files); not in the repo, regenerable.
- Memory: `project_correlation_log_design.md` carries the full per-task state + audit history; `feedback_one_task_then_wait`, `feedback_audit_each_task`, `feedback_workflow_dies_on_idle` (direct parallel Agents, not the Workflow orchestrator) are binding.

---

## ★ HISTORICAL (2026-06-09) — the directive that started this program: DEBUGGING PAUSED → CORRELATION LOG (now Phases 0-3 SHIPPED, see top), then the attribution reconciler, THEN resume linkage debugging

**Operator directive (2026-06-09): HOLD all calc-linkage debugging until the correlation log is upgraded.** The live debug session stabilized linkage (every reported bug fixed + regression-tested + live-verified through a full open→amend→cancel→close scenario) — but it was whack-a-mole. **Root cause of ~every bug: identity/attribution reconciliation on the observe-only Binance stream is done AD-HOC across ~6 sites** (matcher, close-builder, live-enricher, drilldown, ⑨, bracket inheritance), each with a different rule (strict-tpid / chronological-walk / symbol+window / calc_id) → fixing one site shifts load onto another (⑨ → close-recording regression was the textbook proof). Build observability BEFORE more debugging.

### The agreed plan
1. **Correlation log FIRST** (this branch) — an observability spine. Design below.
2. **THEN an attribution reconciler** — ONE module owning fill→position→calc, stamping identity once so the 6 consumers stop re-deriving (the structural cure for whack-a-mole). The log de-risks it (you'll SEE every attribution decision).
3. **Event-driven decision: NO full rewrite.** The engine is already event-driven at the edges (WS-reactive) + has an `event_bus` for fan-out. "Completely event-driven" makes control flow implicit (WORSE debugging — the current pain) and does NOT fix attribution. Keep: edges reactive, bus for decoupled fan-out (the log subscribes to it), explicit traceable core + one attribution owner. Event sourcing (log = source of truth) DEFERRED — the correlation log gets ~80% of the debuggability for ~20% of the risk.

### Correlation-log design (agreed direction — finalize in `docs/design/correlation_log.md`)
The engine ALREADY has `event_bus` (pub/sub) + `engine_events` (engine-behavior audit, typed enum) + `trade_events` (trade lifecycle). The GAP is **(1) a correlation id** threading a chain (request → derived actions → response) and **(2) one uniform envelope** across boundaries. EXTEND these, don't add a 4th silo.
- **corr_id** minted at each entry point (HTTP route / inbound WS message / scheduler tick), carried via Python **`contextvars`** (auto-propagates across `await` within a task — no signature threading).
- **Uniform envelope** = the operator's taxonomy: `{ts, corr_id, component, peer, direction(in|out|internal), category, payload}`.
- **Taps at boundaries only**: HTTP in/out, WS message in, venue REST out+return, state mutation, event_bus publish. **The log SUBSCRIBES to `event_bus`** (every bus event logged with its corr_id — this is where "bus for fan-out" earns its keep).
- **Does NOT**: replace `app_state`; replace `engine_events`/`trade_events`; become the source of truth.
- **DECISIONS PENDING from operator** (defaults if unspecified): sink = **JSONL file** (vs DB table) · scope = **linkage-domain first** (vs whole-engine) · retention = **daily rotate, keep ~7d**.

### What the debug session shipped (this commit — observe-only Binance / HEDGE; all regression-tested + live-verified)
- **close-recording** (critical data-loss): ⑨ stamped the closing-fill tpid but opening fills stayed empty → strict open-lookup missed → NO close row. `_build_close_row_for_fill` now falls back to the symbol+direction walk when the strict lookup is empty + backfills opening-fill tpids (`_backfill_open_fill_tpids`). Fixes vanishing closes + empty drilldown.
- **#1 badge**: "off-size" (size deviation) vs "amended" (ledger amendment OR live TP/SL drift) — distinct labels; detects TP/SL price-drift AND **removal** of a planned protective leg (canceling a stop the calc planned → no longer falsely "on-plan"; operator-flagged as fatal).
- **#2 stale orders**: `db.reconcile_filled_orders` (TRUTH-based `filled_qty>=quantity` → filled), wired at startup + un-gated in the staleness loop (the time-based `mark_stale_orders` stays plugin-gated — it would wrongly cancel real working stops). Clears the Binance-direct stale pileup.
- **#3 drilldown**: attribute order-lifecycle events by **symbol + the position's time-window** (they carry no calc_id on the observe-only path); `query_trade_events` gained a `symbol` filter; drilldown unions calc_id ∪ symbol-window.
- **#2 ticker leak**: `set_calculator_symbol` made unconditional in `/api/price` (was only in the cache-miss fallback → skipped for liquid symbols like BTC); market-stream loop self-respawn now tracks `_market_ws_task` across reconnects.
- **#4/#5 sizing**: `max_correlated_exposure` 0.5→1.0 (account_params); `check_correlated_limit` excludes the held same-(symbol,side) position (no double-count on re-calc). Dashboard positions table got the missing `<th>Funding</th>` (header/cell alignment).
- **Recovered data**: rebuilt the 2 lost closes (XAU + BNB) via `e:/tmp/rebuild_missing_closes.py` (dry-run-first; XAU kept its calc link). Both now in Position History.

### Live-scenario verification (all ✓)
on-plan auto-link (ZEC, 6/6 match) · amend → "amended" (Binance cancel+new detected via drift) · cancel → clean Open Orders · close → row + calc link + 9-event drilldown lifecycle · SL-removal → "amended" (fixed the fatal green-while-unprotected). NB the auto-link needs the eligible calc to exist (with matching SL) BEFORE the order — a calc finalized AFTER the order lands in Needs-Link (the ETH case).

### OPEN follow-ups (DEFERRED per the hold-directive — do AFTER the log)
1. **Attribution reconciler** (the structural lever above) — the priority after the log.
2. **Closed-row Plan badge can't show Binance cancel+new amendments** — `order_amendments` stays empty (cancel+new ≠ in-place modify) + no live TP/SL post-close, so a position that WAS amended/removed reads "on-plan" in history. Fix: persist bracket amendments (attribute the reduce-only cancel+new to the position by symbol+side+window → write an `order_amendment`); then live badge AND closed row both reflect it.
3. (optional) re-match a NEEDS_MANUAL_REVIEW order when a better eligible calc lands within the window (the ETH calc-after-order case).
4. matcher entry tolerance **0.25%** + hedge-mode-keyed recovery (one-way `BOTH` won't match) — unchanged latent gaps.

### Engine / artifacts
- **Engine: STOPPED** (was PID 53484). Restart when resuming: `.venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000`. Observe-only — force-kill safe.
- **Debug artifacts gitignored** (`.gitignore`): `.playwright-mcp/`, root `*.png` screenshots (kept locally, NOT committed).
- **Recovery script** `e:/tmp/rebuild_missing_closes.py` — one-off, already applied for XAU/BNB; NOT in the repo. Formalize into `scripts/` (dry-run discipline) if reused.

---

## ★ HISTORICAL — debug-session per-defect detail (2026-06-08; superseded by the summary above)

**Context.** Continuation of the live calc-linkage debug (operator trades **Binance-direct, observe-only WS, HEDGE mode** — positionSide LONG/SHORT; engine on real Binance). The earlier part of this session committed **8 defect fixes** (commits `30f4c2e`..`32c04de`, UNPUSHED) that made auto-linkage work end-to-end on the pure-Binance path (mint tpid, bracket sourcing, junction formation, LINKED countdown). Auto-link is **CONFIRMED LIVE**. See `[[project_calc_linkage_binance_ws_broken]]` memory.

**This session fixed 4 display/robustness follow-ups — all code-complete + unit-tested, full suite green:**

1. **#1 — cockpit "Plan" column blank for linked positions** → root cause = **unminted-snapshot gap**: on engine restart an already-open position is re-seeded via REST snapshot with EMPTY `terminal_position_id` (the snapshot path deliberately doesn't mint — no stable first-open time), so `_enrich_positions_calc_id` skipped it (line ~2196 `if not pos.position_id: continue`) → no junction match → blank badge. **Fix:** `_enrich_positions_calc_id` now RE-DERIVES the tpid from the position's persisted entry order (new `db.get_open_entry_tpids_by_symbol_side(account_id)` → `(symbol,position_side)→tpid`, hedge-keyed) when `position_id` is empty; self-persists via `DataCache._preserve_metadata`. Files: `core/order_manager.py`, `core/db_orders.py`, `core/data_cache.py` (KNOWN-GAP comment updated). **LIVE-VERIFIED** ✓ (cockpit shows "on-plan" for XAUUSDT after restart; live-DB dry-run pre-confirmed both open positions recover).

2. **⑨ — close-side tpid race** → a closing fill arriving with empty tpid stranded the `closed_positions` row (`terminal_position_id=""`), close events (`position_id=""`), and calc/lifecycle attribution. **Fix:** `_process_single_fill` resolves the tpid BEFORE the upsert via new `_resolve_close_tpid` (tier-1 live `PositionInfo` for (symbol,direction) → tier-2 entry-order fallback, survives full-close snapshot removal). File: `core/order_manager.py`. Unit-tested; **NOT yet live-verified** (needs an operator close).

3. **#2 — calc linkage invisible in Position History** → added a "Plan" deviation badge (on-plan/amended/off-plan; **"—" for unlinked/legacy** — deliberately NOT red, unlike open positions, so ~150 historical rows don't all light up) to the **Position History table** AND **cockpit Recent-Closes pane**, plus the **linked calc id(s)** (clickable → `/context/calc/{id}`) in the **drilldown drawer**. Shared helper `core.state.stamp_close_deviation_badges`. Files: `api/routes_orders.py`, `api/routes_cockpit.py`, `core/state.py`, `templates/fragments/history/closed_positions_table.html` (colspan 18→19), `templates/fragments/history/position_events.html`, `templates/fragments/cockpit/closes.html`. Unit-tested; **NOT yet live-verified** (needs a fresh linked close).

4. **#4 — calculator ticker-switch WS subscription leak** → switching the calc ticker updated `_calculator_symbol` (which feeds `_build_market_streams`) but NEVER rebuilt the WS (restart only fired on POSITION changes), so the old symbol's `@depth20`/ticker kept streaming (operator saw BOTH symbols' prices+orderbooks; cmd "still subscribing to velvetusdt"). **Fix:** `set_calculator_symbol` now schedules `restart_market_streams()` on an ACTUAL symbol change (gated so the 1 Hz `/api/price` poll doesn't thrash; no-loop guard for sync/startup callers). File: `core/ws_manager.py`. Unit-tested; **NOT yet live-verified** (needs an operator ticker switch).

**Working tree (uncommitted):** modified `api/routes_cockpit.py api/routes_orders.py core/data_cache.py core/db_orders.py core/order_manager.py core/state.py core/ws_manager.py` + 3 templates + `tests/test_linkage_binance_ws.py`; **new** `tests/test_calc_symbol_stream_rebuild.py` (5 tests, #4), `tests/test_linkage_history_plan.py` (14 tests, #2). `test_linkage_binance_ws.py` gained 5 tests (#1 ×2, ⑨ ×3). **Untracked artifacts to triage** (NOT mine to silently drop — [[feedback_untracked_files]]): `.playwright-mcp/`, `bug1-empty-drilldown.png`, `bug2-fixed-open-orders-zero.png`, `bug2-orphan-open-orders.png`, `cockpit-linked-xau-open.png` — Playwright debug screenshots; decide gitignore-vs-commit.

**▶ ENGINE IS RUNNING.** Started by me as background task **`bj3at25kv`** (`.venv/Scripts/python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000`, PID was 49740, output at `…/tasks/bj3at25kv.output`). It loaded ALL fixes (committed + uncommitted, since they're on disk). `GET / → 200`, Binance WS up, XAUUSDT open+linked. If the next session needs a clean engine, stop it first (`Stop-Process -Id <pid> -Force`; re-resolve the pid via `Get-NetTCPConnection -LocalPort 8000 -State Listen`). Engine is observe-only (no orders) — force-kill is safe.

**▶ IMMEDIATE NEXT STEPS:**
1. **Live-verify ⑨ / #2 / #4** (the operator drives trades — they invited it: "free to ask me to open/close/amend"). Script: (a) switch calc ticker without Clear → old symbol's price+orderbook stop within ~2s, cmd stops subscribing to old ticker (#4); (b) open a fresh position via calculator (calculate→copy→place) → cockpit Plan badge appears (#1 fresh); (c) close it → Position History row shows the Plan badge + drawer shows the linked calc id + trade-events (#2, ⑨ — also check `closed_positions.terminal_position_id` is non-empty + `calc_id` sealed in the live DB). `#4` can also be self-driven via curl: `GET /api/price/<A>` then `GET /api/price/<B>` and watch `/fragments/ws_status` for a fresh "Market WS connecting" after each switch (the operator REJECTED that probe last turn — ask before re-trying it).
2. **COMMIT the 4 follow-ups** once the operator OKs (commit message convention: `fix(linkage): …` / `fix(calculator): …`, matching the 7 prior). Then the whole stack (`30f4c2e`..new) is still UNPUSHED — push only when asked.
3. The 1 flaky teardown test is pre-existing suite-wide noise (CLAUDE.md "Task was destroyed" pattern) — surface, don't chase, unless it blocks.

**GOTCHAS:** matcher entry tolerance is **0.25%** — a market fill >0.25% off the planned average won't LINK (use limit or widen `entry_tolerance_pct`). The snapshot-recovery + close-tpid fallback are **hedge-mode keyed** (`(symbol, position_side)`); a one-way `BOTH` order won't match — documented latent gap, consistent with the other observe-path one-way deferrals.

---
**[BELOW = pre-debug HISTORICAL handoff; the calc-linkage program was "done" at task 314, then live debugging reopened it. Kept for Phase 0→9 context + the regime-build direction.]**

**🎉 CALC-LINKAGE COMPLETE — Phases 0 → 9 all shipped + holistically audited.** Phase 9 (multi-operator) finished: T1 advisory banner + T2 takeover-core were task 306; T3 operator_id propagation (309 + audit-fix 310); T4 idle timeout (311); holistic audit (313). Plus P7 deferred #1 — calc_match_audit in reverse-query/export — (312). All pushed.

## ★ STATUS (2026-06-07) — 🎉 PHASE 9 (multi-operator) COMPLETE + HOLISTICALLY AUDITED; calc-linkage Phases 0→9 done + PUSHED

**Phase 9 is fully shipped + holistically audited (task 313). Commits 309–313 are PUSHED to origin (HEAD `df845de`).** Calc-linkage now spans **Phase 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9.** The deployment is single-tenant **localhost** (CLAUDE.md Task 163; threat model = correctness/observability/recovery, NOT auth/exposure) — which is why Phase 9's exposure-driven half (hard lock, CSRF) was consciously deferred and the value lives in `operator_id` audit-trail completeness.

### Phase-9 build (this session)
- **P9.T1 (306) — advisory multi-session banner** (minimal; NO hard lock) + per-browser seat token (localStorage UUID = `operator_id`). `api/routes_auth.py` (new), `core/auth_state.py`, guarded banner IIFE in `base.html`. Detail in the HISTORICAL 2026-06-06 block below.
- **P9.T2 (306) — core takeover endpoint** `POST /operator/session/takeover` (end foreign active → start mine with `takeover_from_session_id`). Richer UX + `operator:*` event emission still deferred.
- **P9.T3 (309 + audit-fix 310) — operator_id propagation.** Stamps the active operator-session seat onto the THREE action-row tables that carry the column — `pre_trade_log` (calc creation, DB-resolved via `auth_state.current_operator_id` → correct even when the cache is cold), `orders` (WS arrival) + `order_amendments` (WS) (O(1) `cached_operator_id` read of the `app_state.operator_id_by_account` cache, write-through from register/takeover) — plus the `calc:created` / `position:amended` payloads. `orders` ON CONFLICT `COALESCE(orders.operator_id, excluded.operator_id)` = first-known-wins (placement operator, never reattributed). Out of scope (no column): closed_positions/fills/positions_calcs/calc_match_audit. **NB `insert_pre_trade_log` lives in `core/db_trades.py`** (not db_orders.py as the old scope block claimed). 310 = empty-seat→None symmetry one-liner. Tests `tests/test_phase9_t3_operator_id.py` (23).
- **P9.T4 (311) — idle session timeout.** `operator_sessions.last_seen_ts` (CREATE + duplicate-tolerant ALTER); heartbeat (`POST /operator/session/heartbeat`, 60s ping from the banner IIFE) bumps it; a 60s background reaper (`schedulers._operator_session_reaper_loop` → `auth_state.reap_idle_sessions`, default `OPERATOR_SESSION_IDLE_SEC=30min`) ends quiet sessions AND invalidates the T3 cache for reaped (account, seat). Idle is **heartbeat-driven** (now − COALESCE(last_seen_ts, session_start_ts)), so an actively-open page is never reaped; only a closed/asleep browser is. Tests `tests/test_phase9_t4_session_timeout.py` (29).

### Holistic Phase-9 audit (task 313) — 6 parallel adversaries (cache-coherence / e2e-lifecycle / spec-Q56 / security / test-integrity / consistency)
**VERDICT: production code COHERENT, no BLOCKER/HIGH.** Agents PROVED (probes, not just reads) that no wrong-operator attribution is possible (the cache only ever holds None or a confirmed-owner seat; reaper invalidation is account+seat double-keyed; the takeover lifecycle is coherent — incl. the deliberate two-columns/two-questions design: `orders.operator_id` = who PLACED [first-known COALESCE], `order_amendments.operator_id` = who AMENDED). Security clean (no SQLi/XSS/crash; CSRF + seat-spoof correctly N-A at localhost). Spec fidelity STRONG.
**Audit fixes (task 313):**
- **HIGH (test gap)**: the load-bearing cross-task chain was UNTESTED — the route write-through tests asserted against a throwaway `SimpleNamespace`, never the real `app_state`, so a dropped register/takeover/heartbeat→cache write-through would mis-attribute every post-takeover order yet pass all per-task tests. New **`tests/test_phase9_holistic.py`** drives the REAL chain end-to-end (6 tests).
- **MED (plan §9.3)**: manual-link operator attribution — recorded WHO linked on the `manual_link_added` trade event, **NOT** on `orders.operator_id` (which holds the placement operator; the auditor's suggested fix was wrong-shaped — re-investigation caught it). `core/link_actions.py`.
- **LOW (docs)**: reconciled stale in-code docs (`auth_state.py` "future P9.T4" → shipped; the `operator:*` topic constants re-labelled SPECULATIVE — spec §9 lists NO operator events; deferral-note accuracy).

### ⚠ Phase-9 report-only deferrals (single-tenant localhost — LOW value; re-elevate if exposed/multi-seat)
- **Hard read-only LOCK** + read-only UI for non-active operators (full P9.T1) — the banner is advisory only; nothing is blocked. Verify-first call (operator-confirmed) deferred it as low-value at one local operator.
- **P9.T2 richer takeover UX + `operator:*` event emission** (the 3 topic constants in `auth_state.py` are a SPECULATIVE reservation, NOT spec-mandated).
- **operator attribution for close-reason** (needs a `closed_positions.operator_id` column) + **mark-unplanned** (no event carrier).
- **foreign-banner periodic re-check** (banner is on-load + heartbeat only — won't raise if a second session opens after your load).
- **unbounded `operator_sessions` growth** — ended rows are never pruned; a retention DELETE in the reaper is a policy call on handoff-audit history.
- **client-minted forgeable seat** — move to server-mint (HttpOnly) if a second human ever shares an account.
- **CSRF on the 3 POST endpoints** — N-A at localhost; re-elevate the moment a hard lock lands OR the deployment exposes beyond localhost.
- Plan **§14.3 task-numbering is stale** (swaps T3/T4); the impl + this HANDOFF follow the §9-row convention (T3=operator_id, T4=timeout).

### P7 deferred #1 CLOSED (task 312) — calc_match_audit in reverse-query + export
The per-criterion matcher decision trace (WHY a calc matched/failed each criterion of an order) is now a `match_audit` section in all three `core/context_query.py` assemblers (calc/lifecycle/position) + the signed JSON **and** PDF export (audit-fixed JSON/PDF parity). Reused the existing `get_calc_match_audit` read (no new read). Tests in `test_phase7_context.py` + `test_phase7_export.py`.

### Calc-linkage deferred backlog (opportunistic; all low-priority at localhost)
- **P7 #2** `/positions/open` JSON endpoint (= P8 deferred #1) — speculative, no consumer wired; build when an out-of-process model needs live polling.
- **P7 #3–6** pagination/caching on reverse-query, cross-language float contract doc, algorithmic signing-downgrade (set `EXPORT_SIGNING_KEY` if exposed), replayable webhook dead-letter — all bounded + deployment-acceptable.
- Opportunistic hardening (CLAUDE.md Task 163): MED-040 SRI, MED-041 CSP, LOW-001 ticker regex — exposure-driven, N-A at localhost.

### ▶ Likely NEXT major direction — the REGIME BUILD (⚠ verify-first against the rewind)
`v2.5_regime-plan.md` (operator opened it) is the regime-classifier roadmap: Stage A JSON rule interpreter behind a `classify(signals) -> RegimeResult{label, multiplier}` seam → historical counterfactual re-sizing + a regime analytics/leaderboard sub-section → MultiCharts results converter → Stage B ML behind the same interface. The plan's "Build order" says step 1 (interface + Stage A + dual-P&L) is "CLOSED post-T167" — **but that was on the PRE-rewind branch.** This branch is `post-rewind-drop-regime-infra`; only the load-bearing fixes in the "Surviving the rewind" section below were preserved (e.g. T157 regime columns on `pre_trade_log`, T165 clamps). **VERIFY-FIRST what regime infra actually exists here** (`core/regime/*`? `regime_signals`/`regime_labels` tables? the live-sizing wire in `risk_engine.py`?) before trusting any "shipped" claim in the plan ([[feedback_verify_first_default]]). The build-order's own warning — "this chain has gone stale twice; verify shipped state before scoping" — applies doubly post-rewind.

---

## ★ HISTORICAL STATUS (2026-06-06) — 🎉 PHASE 8 (operator UX) COMPLETE + HOLISTICALLY AUDITED; next = Phase 9 (multi-operator) — but ⚠ VERIFY-FIRST whether it's warranted at this deployment

**Phase 8 (operator UX, plan §8) is fully shipped (tasks 291–302) + holistically audited (303).** The calc-linkage system now has its operator surface: a multi-pane cockpit, a refreshed calculator, the post-arrival decision/close flows, in-app notifications, a config editor, and a per-position event drilldown. Calc-linkage now spans **Phase 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8**.

### Phase-8 build (tasks 291–302)
- **P8.T1 (291)** — cockpit multi-pane dashboard: 4-pane layout (open positions / active calcs / needs-link / recent closes) + scaffold. `api/routes_cockpit.py`, `templates/cockpit.html` + `fragments/cockpit/*`.
- **P8.T2 (292)** — open-positions pane: deviation badges + uPnL + MFE/MAE columns (T174 display-together rule honored). Reads `app_state.positions` server-side.
- **P8.T3 (293)** — active-calcs pane: client-side countdown timers from a server-frozen `expiry_ms = created_ts + window_seconds`, + a per-calc cancel button. **Cancel = RELEASE the calc record** (`calc_state.transition` → `calc:cancelled`), NOT a venue cancel (observe-only engine).
- **P8.T4a/b/c (294/295/296)** — calculator: account match-window dropdown (writes `config_json.window_seconds`); operator size override (planned vs overridden both recorded for deviation); multi-TP ladder (`tp_levels` JSON array; `_parse_tp_levels` validates finiteness/bounds/count/Σ≤100).
- **P8.T5 (297)** — **REFRAMED** replacement decision: the spec's *pre-submission* modal is impossible (observe-only). Built the post-arrival equivalent in the needs-link queue — `find_candidate_calcs` now `status IN ('active','released')` (matcher-aligned + fixed a released-exclusion bug) + REPLACEMENT badge + cancelled-order annotation. NO `replacement_modal.js`.
- **P8.T6 (299)** — **REFRAMED** manual-close reason: not opposite-side order-stream detection (impossible) — a post-arrival **clickable reason badge** on the history close-reason cell → MANUAL_* dropdown + note → `update_close_reason`, **REPLACE-preserved** across a close-row rebuild (`_REFINED_MANUAL` guard in `insert_closed_position`).
- **P8.T7 (301)** — in-app notifications: per-account ring buffer (`core/notifications.py`) fed by an `event_bus.subscribe_all` catch-all → toasts + bell badge, gated by `config_json.notification_subscriptions`; POLL delivery (`GET /notifications/poll`). Audit fixed 2 MED (cross-account cursor replay; badge-blank-after-boosted-nav).
- **P8.T8 (300)** — config_json settings editor: a "Calc-Linkage" tab in `/config` (NOT a separate page) editing every knob (window/skew/tolerances/deviation thresholds/webhook/flags/notification subs) via the T4a `write_account_config` writer; validated (incl. `math.isfinite`).
- **P8.T9 (302)** — per-position trade-events drilldown: a second lazy-loaded drawer section (`GET /fragments/history/position_events`) — calc_id(s) from the `positions_calcs` junction, `query_trade_events` unioned + chronological, scoped (no sibling leak), empty-state for no-calc rows; audit fixed a silent >500-cap.

### Holistic Phase-8 audit (task 303) — 5 parallel auditors (dashboard / calculator / decision+modals / cross-cutting integration / test-quality)
Suite was healthy (192 phase-8 tests green); one real HIGH + several LOW/defensive, all fixed:
- **HIGH — NaN/Inf poison on the calc money-path**: `float("nan")/"inf"/"1e400"` parse via `Form(float)` but slip every downstream `<= 0`/range guard (NaN comparisons all False) → an **ELIGIBLE calc with NaN size/notional** persisted into `pre_trade_log`, read by the matcher + deviation analytics. Fixed at the calculator route (400 on non-finite average/sl/tp/pcts) AND in `calculate_position_size` (`math.isfinite` guard — plus the **missing `import math`** it depended on, which a test caught as a NameError-on-every-calc).
- LOW: `size_override` requires `isfinite` (+inf was persisting); `find_candidate_calcs`/`_cancelled_order_for_calc` are account-scoped (combined-DB fallback safety); `db_trades` tp_levels `json.dumps(allow_nan=False)`; `_fmt` renders non-finite as `—` (app-wide — fixes cockpit uPnL/MFE/MAE on a bad WS tick).
- DOC: reframed plan rows 8.7 + P8.T6 in-place. TESTS: `test_phase8_audit_followup.py` (24) — regressions for every fix + the gaps the per-task suites missed (MANUAL_DISCIPLINE_BREAK/NEW_OPPORTUNITY preserve+endpoint+label; position_size_drift notification; position_events detail-summary branches).
- **Verified clean (no change)**: config_json multi-writer consistency (top-level merge preserves siblings; settings writes full nested snapshots); all phase-8 templates compile-render; REPLACE-preserve key correctness; notification dispatch/XSS/cursor; position-events scoping.

### Phase-8 deferred — items #2/#3a/#3b CLOSED (task 305, 2026-06-06); #1 left deferred; #3c NEW

**Task 305** closed three of the four deferred items (+ 3 parallel adversarial auditors; 1 confirmed bug fixed). Full suite **3415 passed / 7 skipped / 0 fail** (was 3402 + 13 new tests).
1. **`/positions/open` JSON endpoint — LEFT DEFERRED (operator decision, task 305).** No JSON consumer is wired today, so building it now is speculative (Rule 2). Spec §11.3 names it as the out-of-process model's live-polling endpoint — re-open when an external model actually needs it. (Cockpit positions pane still reads `app_state.positions` server-side.)
2. **✅ Export-Audit button — WIRED (task 305).** Native download form (⤓ JSON / ⤓ PDF) in the Position History drawer's **trade-events section** (`templates/fragments/history/position_events.html`), keyed by the closed_positions PK threaded through `frag_position_events` (`api/routes_orders.py`). POST `formaction` → the P7.T4/T5 endpoints (NOT htmx — the nav is the only hx-boost region; NOT a GET `<a>` — endpoint is POST). Renders for every closed row incl. no-calc/legacy (export has a closed-row-only fallback). **Audit-fixed bug**: the JSON export path (`api/routes_export.py`) returned `JSONResponse` with **no `Content-Disposition: attachment`**, so the native form would navigate the SPA to a raw JSON dump instead of downloading (the PDF branch already set attachment). Added the attachment header (advisory — programmatic `json.loads` callers unaffected). The compact cockpit closes pane stays read-only (comment updated). Tests: `test_phase8_position_events.py::TestExportButton` (3) + ctx-thread (1) + `test_phase7_export.py` JSON-disposition assertion.
3. **✅ 3a + 3b CLOSED (task 305)**:
   - **(a) base.html poll-IIFE guards** — guarded the connection-poll `setInterval` with `window._connPoll` (timer-only: the platform-selector change listener still re-binds to the fresh DOM each boosted nav) and early-returned the whole hold-time-ticker IIFE with `window._holdTick`. Both mirror the P8.T7 notif `window._notifPoll` guard. Tests: `test_phase8_deferred.py::TestPollIifeGuards`.
   - **(b) cockpit per-calc cancel → 200** — `cancel_calc` (`api/routes_calculator.py`) now returns **200 for every outcome** with a status-discriminated alert body (success/warning/error) so htmx swaps it into `#ck-calc-alert` (was 404/409/500 → swallowed by the global `htmx:responseError` handler into a generic toast + retry). Docstring's own option (a). Handler tests (`test_phase1_calc_cancel.py`) assert the handler result string, not the route status — unaffected. Tests: `test_phase8_deferred.py::TestCancelRouteReturns200` (mutation-verified).
4. **✅ #3c — CLOSED (task 307, 2026-06-06).** Same hx-boost re-execution root cause as #3a but for `addEventListener`, not `setInterval`: body-level IIFEs re-registered `document(.body).addEventListener(...)` on every boosted nav, and because hx-boost swaps the body's **innerHTML** (the `<body>` NODE persists) the listeners ACCUMULATED one copy per navigation — the user-visible symptom being `htmx:responseError`/`htmx:sendError` → N duplicate error toasts + N target-swaps after N navs (incl. every still-non-2xx path like `calculate_risk`'s 400 validation bodies, which #3b did NOT convert to 200). **Fix (task 307):** guarded all 6 previously-unguarded persistent-node listeners behind `window._X` flags — `account-added` (`_acctAddedBound`), ECharts `htmx:beforeSwap` dispose (`_echartsDisposeBound`), the `htmx:responseError`+`htmx:sendError` pair (`_htmxErrBound`, early-return — nothing runs after them in that IIFE), steppers `htmx:afterSettle` (`_stepperBound`, partial guard — the initial `attachSteppers()` still runs per nav), and the dashTab + hpTab `htmx:afterSettle` (`_dashTabBound`/`_hpTabBound`). The notif (`_notifPoll`) + #3a (`_connPoll`/`_holdTick`) were already guarded. **Audit (2 agents) caught a regression THIS task introduced + fixed it**: the early-return guard on the error IIFE kept only the FIRST page-load's listener, whose `showError` had captured `#htmx-error-toast` once at IIFE scope — after the first boosted nav that node is swapped out, so the global error toast would silently stop appearing. Fixed by re-querying the toast inside `showError` (mirrors the notif `paintBadge` re-query). JS verified by Node `--check` (0 syntax errors). Tests: `test_phase8_deferred.py::TestListenerStackingGuards` (7, proximity + completeness anchor). NB the notif IIFE's comment ("body is replaced by the swap") was subtly wrong — the body node persists; that misframing is what hid this listener-stacking class.

---

## ✅ [SUPERSEDED — Phase 9 COMPLETE; see top STATUS 2026-06-07] Phase 9 (multi-operator) — P9.T1 shipped MINIMAL (task 306); T1-full/T2/T3/T4 remain

### ✅ P9.T1 — SHIPPED MINIMAL (task 306, 2026-06-06) — advisory multi-session banner, NO hard lock

**Verify-first scoping call (made + operator-confirmed):** the engine has **no auth, no cookies/session middleware, and a single global `app_state.active_account_id`** (two browser tabs share it) — so a "single-operator lock" has no per-seat identity to key on, and at single-tenant localhost its only payoff is one human's two-tab self-clobber (low value). Operator chose the **minimal advisory banner** over the full lock.

**What shipped:** a per-browser **seat token** (localStorage UUID = `operator_id`) + two endpoints in **`api/routes_auth.py` (new)** — `POST /operator/session/register` (no active → start mine = owner; same token active → owner/reuse; different token active → `foreign`, don't start) and `POST /operator/session/takeover` (end the foreign active session → start mine with `takeover_from_session_id`). Logic in **`core/auth_state.py`** (`register_session`/`takeover_session`, on the P0.T2 scaffold CRUD). A dismissible **`#operator-session-banner`** in `base.html` + a **guarded** IIFE (`window._opSeat`, per the #3a lesson) that on load mints the token, registers, and shows the banner only on `foreign` (populated with the foreign seat suffix + since-time via `textContent`). Scoped to the global active account. Tests: `tests/test_phase9_multi_operator.py` (15). Audited by 3 agents — no correctness/security bugs; fixes folded in (banner now consumes the plumbed data; localStorage-clear self-grief + non-atomic-takeover documented).

**STILL DEFERRED (so the next session doesn't think P9 is done):**
- **Hard read-only enforcement** (the full P9.T1 lock) — the banner is advisory only; nothing is actually blocked.
- **P9.T2 takeover endpoint** — its CORE is already built (`/operator/session/takeover` in `routes_auth.py`); "P9.T2" now reduces to any richer takeover UX + the `operator:*` event emission (topics reserved in `auth_state.py`, NOT emitted).
- **P9.T3 operator_id propagation** — UNTOUCHED (operator chose to checkpoint + execute fresh, task 308). The seat token is NOT yet stamped onto action rows. **Pre-grep + design are DONE — see the "P9.T3 — EXECUTION-READY SCOPE" block below; pick it up directly.**
- **P9.T4 idle timeout** — UNTOUCHED. Active `operator_sessions` rows are never cleaned; a closed browser leaves an active row forever, and clearing localStorage makes the same human see a foreign banner on themselves (self-heals via one Take-over click).
- **Best-effort single-active** — `register`/`register` races (or a takeover with >1 pre-existing active) can leave >1 active row; the next register/takeover converges. The atomic acquire-under-lock is the full P9.T1.
- **CSRF on takeover** — a local page could POST `/operator/session/takeover`. Benign at localhost single-tenant (no lock to weaponize, no second human); **re-elevate the moment a hard lock lands OR the deployment exposes beyond localhost** (add a same-origin/CSRF check then).
- **Periodic re-check** — the banner is an on-load check only; it won't raise if a second session opens AFTER your page load.

### ✅ [DONE — shipped as tasks 309/310; scope below is the archived pre-grep] P9.T3 — EXECUTION-READY SCOPE (pre-grepped + design settled, task 308, 2026-06-07)

The roadmap's **biggest** task (§14.5 "~6h"). Checkpointed for a fresh session with full budget — the pre-grep + design below are done; execute directly + audit (these are money-path-adjacent inserts; the #3c audit just caught a subtle bug, so audit is mandatory).

**Columns (verified):** `operator_id` exists `DEFAULT NULL` and is currently **unwritten** on exactly THREE action-row tables — `pre_trade_log`, `orders`, `order_amendments`. **No `operator_id` column** on `closed_positions` / `fills` / `positions_calcs` / `calc_match_audit` / manual-link / close-reason rows → those are NOT T3 targets and need **no schema change**. (If a future spec wants operator on manual-link/close-reason, that's a column-add, out of this scope.)

**Design (SETTLED):** add `current_operator_id(db, account_id) -> Optional[str]` to `core/auth_state.py` — returns the ACTIVE `operator_session`'s `operator_id` (via `get_active_operator_session`), best-effort, `None` on no-session/error. Stamp it at write time. **NOT** client-seat-token threading: the WS-driven order/amendment writes have no browser request to carry a token, so the active-session resolver is the only option there, and uniform is cleaner. **Caveats to document in-code:** (a) WS-driven rows get "operator on duty at observation time" (weak but honest); (b) a foreign seat submitting a calc mis-attributes to the active owner — acceptable at single-tenant.

**⚠ HOT-PATH NOTE (decide first):** resolving the active session per WS order/amendment write adds a `get_active_operator_session` DB read on the WS hot path. **Prefer caching** the current operator_id on `app_state` (set on register/takeover in `routes_auth.py`, read O(1) at the write sites) over a per-write DB query. The calc-creation path (not hot) can resolve directly.

**Write sites to stamp (exact):**
1. **`pre_trade_log` (calc creation — HIGH VALUE, "who created this calc"):** `core/handlers.py::handle_risk_calculated` → `core/db_orders.py::insert_pre_trade_log`. The INSERT does NOT currently carry `operator_id` — add the column + placeholder + thread the resolved id in. Also wire the real id into the `calc:created` event payload (`handlers.py:619`, currently `payload.get("operator_id")` → None today).
2. **`orders` (WS-driven):** `core/db_orders.py::upsert_order_batch` (~:72) — add `operator_id` to the column/placeholder/`ON CONFLICT` set; resolve at the WS order-arrival site (`order_manager.process_order_update`). Weak attribution.
3. **`order_amendments` (WS-driven):** replace `None` at `order_manager.py:1179` (the `insert_order_amendment` call) with the resolved id — `insert_order_amendment` ALREADY reads `row.get("operator_id")` (`db_orders.py:1686`), so just pass it. ALSO the two payloads: the `position:amended` event-bus payload (`order_manager.py:1212`) + the `position_amended` trade event (`order_manager.py:1251`).

**Tests:** `tests/test_phase9_t3_operator_id.py` — calc-creation stamps the active session's id; `None` when no active session; amendment + order stamped; best-effort (resolver fault → `None`, write still succeeds); the foreign-seat mis-attribution caveat pinned. **Sequencing:** the calc-creation slice (site 1) is the standalone-valuable headline and could ship alone first if splitting; sites 2-3 are the WS-driven remainder.

### ⚠ VERIFY-FIRST (original guidance — kept for the remaining T1-full/T3/T4 decisions)

**Before scoping ANY further Phase-9 code, make the scoping call + surface it to the operator** ([[feedback_verify_first_default]]). Phase 9 is "single-operator-per-account lock + takeover + `operator_id` on all action rows" (plan §9). The deployment is **single-tenant localhost** (CLAUDE.md "Deployment context", Task 163 — HIGH-001 auth closed / N-A). Phase 9 is **NOT** auth/exposure hardening; its value is (a) operator-SESSION consistency / two-tab-clobber prevention, and (b) audit-trail `operator_id` completeness ("who created this calc"). At a single local operator, (a) is low-value; (b) has standalone worth. So the real options are:
- **Build Phase 9 in full** — only if multi-tab / future multi-seat clobbering is a real concern;
- **Cherry-pick P9.T3 (`operator_id` propagation)** for audit-trail completeness only, and defer the lock/takeover/timeout (T1/T2/T4);
- **Defer Phase 9 entirely** and instead close the Phase-8 deferred UI items (export button, `/positions/open`) + the opportunistic hardening backlog (CLAUDE.md "Deployment context": MED-040 SRI, MED-041 CSP, LOW-001 ticker regex — all downgraded-to-opportunistic).

**Phase-9 scaffold ALREADY EXISTS (Phase 0.5 / P0.T2 — logic is deferred stubs):**
- `operator_sessions` table (`core/database.py:556`) + indexes; `core/db_auth.py` (134 lines — operator_sessions CRUD scaffold); `core/auth_state.py` (82 lines — `OperatorSession` dataclass + `is_active` + reserved Phase-9 event topics).
- `operator_id TEXT DEFAULT NULL` columns are already on `pre_trade_log`, `orders`, `order_amendments` — the **None placeholders** Phases 1–7 stamped (every calc/order/`position_amended` write passes `operator_id=None` today). These are P9.T3's write targets.

**Phase-9 tasks (plan §9 rows 9.1–9.4 / summary P9.T1–T4):**
- **P9.T1 (bottleneck)** — single-operator lock: on UI load check `operator_sessions` for an active *foreign* session → read-only + takeover prompt. `core/auth_state.py` + frontend. **⚠ MINIMAL version SHIPPED (task 306) as an advisory banner — see the "✅ P9.T1 SHIPPED MINIMAL" block above; the HARD read-only lock is what remains.**
- **P9.T2** — takeover endpoint: terminate the prior session, write a new row with `takeover_from_session_id`. `api/routes_auth.py` (new). **Needs T1.** **⚠ CORE endpoint SHIPPED (task 306, `POST /operator/session/takeover`); only richer UX + `operator:*` event emission remain.**
- **P9.T3** — `operator_id` propagation sweep (**the BIGGEST task — pre-grep ALL action-row write sites first**, per CLAUDE.md broad-re-grep discipline): stamp the active session's operator_id on every action-row write (calcs, orders, amendments, manual_links, close_reasons) across `handlers.py`/`order_manager.py`/`ws_manager.py`/`api/routes_*`. **Standalone audit-trail value even without the lock.**
- **P9.T4** — session timeout: idle auto-terminate after N min (default 30); background job in `auth_state`. Independent.

Sequencing: **T1 → T2; T3 + T4 independent after T1.** Tests: `tests/test_phase9_multi_operator.py` (plan §9). Acceptance: two operators can't both act on one account; "who created this calc" returns `operator_id`; handoff visible in `operator_sessions`.

---

## ★ HISTORICAL STATUS (2026-06-04) — PHASE 6 COMPLETE + PHASE 7 COMPLETE (reverse-query + audit export, T1–T6); next = Phase 8 (operator UX) or Phase 9 (multi-operator)

**Tasks 268–269 (this session):**
- **task 268 — 4 deferred follow-ups (pre-Phase-7 cleanup)**: (1) aiosqlite `PRAGMA busy_timeout=5000` on
  the writer (`database.py`); (2) **`_emit_fill_events` split async** — the `position:partial_close` bus
  event stays on-loop (`put_nowait` not thread-safe), the blocking `log_trade_event` writes go via
  `asyncio.to_thread` in `_write_fill_trade_events` (mirrors `_emit_amendment_event`); caller now `await`s
  it; (3) **DELETED dead `_detect_modification_events`** (ran POST the SR-1 gate, which rejects the
  `new→new` amendment self-transition → never fired live) + migrated the TP/SL-modification signal to
  `position_amended` (field∈{tp_price,sl_price}) via `routes_orders._has_tpsl_modification` + the history
  table's arrow branch; legacy `tp_modified`/`sl_modified` TYPES kept (no producer) for historical rows;
  (4) **per-account log test-pollution guard** — `tests/conftest.py::_isolate_live_per_account_logs`
  (autouse) patches `_resolve_db_path` in BOTH `core.trade_event_log` AND `core.event_log` so un-isolated
  process_fill/close/calc tests redirect their `trade_events`/`engine_events` writes off the LIVE
  per-account DB. (A session-wide `config.DATA_DIR` redirect was tried first and broke 36 tests that
  resolve OTHER DBs off DATA_DIR — the narrow resolver patch is the fix.) Audited (4 agents): all four
  correct, LOW nits fixed. ⚠ **The live DB still holds the PRE-guard pollution** (~thousands of `calc_id=C1`
  etc. test rows in trade_events + engine_events); cleanup is a deferred operator-confirmed task — see
  `[[project_live_db_test_pollution]]`.
- **task 269 — P7.T1 (reverse-query)**: `GET /context/calc/{calc_id}` + `GET /context/lifecycle/{id}`. New
  `core/context_query.py` (shared assembly `assemble_calc_context`/`assemble_lifecycle_context`; cross-DB
  §12.7 — `trade_events` from the per-account DB joined in Python via `asyncio.to_thread`; §3.2
  most-contributing `position` resolution open-or-closed; `json_safe()` coerces non-finite REAL floats→null
  so the JSON layer can't 500). 6 keyed reads in `db_orders.py` (orders/fills/closed_positions by
  calc_id/lifecycle_id/terminal_position_id). `api/routes_context.py` + `api/router.py` registration.
  Audited (3 agents): assembly correct; fixes = inf-guard, route tests, e2e cross-DB sentinel, multi-partial
  pinning. Tests `test_phase7_context.py` (29). Plan §7 row 7.1.

**Phase 6 (event-bus enrichment) is COMPLETE** (tasks 260–267) — per-task detail in the "PHASE 6 IN
PROGRESS" section below + `[[project_phase6_event_bus_state]]`. **Phase 7 (reverse-query + audit export) is
now IN PROGRESS:**
- **P7.T1 shipped (269)** — `GET /context/calc/{id}` + `GET /context/lifecycle/{id}` (assembler in
  `core/context_query.py`; cross-DB §12.7; `json_safe` inf-guard; 6 keyed db_orders reads).
- **P7.T2 shipped (271)** — `GET /context/position/{id}` (`assemble_position_context`, keyed on
  `terminal_position_id`; extracted a shared `_aggregate_tail` reused by lifecycle + position — lifecycle
  unchanged; `position` resolves THIS position open-or-closed; works for junction-less/UNPLANNED positions;
  2 new `get_{orders,fills}_by_position_id` reads).
- **P7.T3 shipped (274 + audit-fixes 275)** — `core/webhook_dispatcher.py`, the FIRST in-process event_bus
  `position:closed` subscriber. Per-account handler closures ENQUEUE the §9 payload (non-blocking — the
  event_bus dispatch loop is sequential); a worker POSTs `{event: position_closed, payload: <§9>}` to the
  account's `webhook_url` with exp-backoff (cap 30s, 5 tries) + an `engine_events` `webhook_dispatch_failed`
  dead-letter. `webhook_url` + STRICT-bool `feature_flags.webhook_enabled` on `AccountConfig` (default OFF).
  `json_safe` keeps NaN/Inf off the wire + out of the dead-letter. Wired via `start_webhook_dispatcher` in
  `_startup_fetch` (subscribe-before-run, guarded). Deviation: engine_events dead-letter ROW not a replay
  table (spec §11.3 fire-and-forget + reverse-query re-fetch → miss self-heals). Tests (19).
- **P7.T4 shipped (277 + audit-fixes 278)** — `core/audit_export.py` + `POST /export/closed_position/{id}`:
  a SIGNED JSON audit bundle. Resolves the closed row by PK → `terminal_position_id` →
  `assemble_position_context` (REUSES the P7.2 assembler → the full §10.6 graph), with lifecycle +
  closed-row-only fallbacks. Signed-timestamp envelope = signature over canonical(header+bundle):
  HMAC-SHA256 if `config.EXPORT_SIGNING_KEY` set, else unkeyed SHA-256 (tamper-evidence; localhost
  default). `json_safe` keeps NaN/Inf out. `get_closed_position_by_id` (new). Tests (15).
- **P7.T5 shipped (280 + audit-fixes 281)** — `render_export_pdf` + the VENDORED dependency-free
  `core/pdf_writer.py` (operator chose no PDF dependency): a paginated Courier-text PDF of the audit bundle
  with the SAME signature in a footer. `POST /export/closed_position/{id}?format=pdf` (case-insensitive) →
  `Response(application/pdf)`; `?format=json` (default) unchanged. The PDF's byte-validity (xref offsets,
  /Length, escaping) was independently audited + test-pinned. Tests (26).
- **P7.T6 shipped (283 + audit-fixes 284)** — `POST /export/closed_positions?account_id=&from_ms=&to_ms=
  &format=json|pdf`: a per-account compliance ZIP of one signed bundle per closed position in the
  (epoch-ms) range + a signed `manifest.json`. `build_batch_export` reuses `build_closed_position_export`,
  dedups multi-partial rows by tpid, signs the manifest over its own canonical form (incl. every member
  signature → tamper-evident whole), surfaces a `MAX_BATCH_POSITIONS` cap via `manifest.truncated`.
  `get_closed_positions_in_range` (new). Account-scoped. Tests (38).

**🎉 PHASE 7 (reverse-query + audit export) is COMPLETE** — T1 (`/context/calc` + `/context/lifecycle`),
T2 (`/context/position`), T3 (position-closed webhook dispatcher), T4 (signed JSON audit export), T5
(audit PDF via the vendored `core/pdf_writer.py`), T6 (batch/date-range export). The end-to-end
model-feedback loop now exists: a downstream model can subscribe via webhook (T3) AND re-fetch the full
causal graph via reverse-query (T1/T2), and compliance can export signed audit bundles (T4-T6).
- **next = Phase 8 (operator UX)** — multi-pane dashboard, replacement/manual-close modals, notifications,
  calculator window config, AND the per-position events drilldown (P8.T9). Phase 8 would also wire an
  **Export-Audit button** to the P7.T4/T5 endpoints (`POST /export/closed_position/{id}?format=json|pdf`)
  and a settings UI for `accounts.config_json` (incl. the P7.T3 `webhook_url` + `feature_flags`). OR
  **Phase 9 (multi-operator)** — single-operator-per-account lock + `operator_id` propagation (the
  `operator_id` columns + the None placeholders Phases 1-7 left are its inputs). Plan §8 / §9 / §14.3.
  ⚠ See the **DEV-ENVIRONMENT HAZARD** section directly below before trusting a red test run or running
  destructive git.

- **task 286 — Phase-7 HOLISTIC cross-task audit** (6 adversarial agents: spec-fidelity/completeness,
  cross-DB/reused-assembler, account-scoping/tpid-invariant, signing/tamper-evidence, webhook-as-first-
  subscriber, test-integrity). **No BLOCKER/HIGH.** Fixes applied this task:
  - **MED — export reproducibility (the load-bearing fix)**: a SIGNED compliance export was reading live
    `app_state` (it preferred a live OPEN position over the persisted closed row). A signed bundle that
    depends on volatile in-memory state isn't DB-reproducible. Threaded a `prefer_open` flag through
    `_resolve_position → _aggregate_tail → assemble_{position,lifecycle}_context`; `build_closed_position_export`
    now calls both assemblers with **`prefer_open=False`** → the export bundle is SEALED to the DB (a re-open
    under the same tpid surfaces OPEN on `/context` but the export stays CLOSED → the signature recomputes).
    Default `prefer_open=True` keeps `/context` live-preferred (unchanged behaviour).
  - **LOW — falsy-guard consistency**: `get_position_calc_links` + `get_position_funding_events` lacked the
    `if not position_id: return []` guard the sibling by-position reads have (2-of-5 inconsistency). Added.
  - **LOW — docs**: account-scoping/tpid-invariant + re-open anchor on `assemble_position_context`;
    receiver-MUST-be-idempotent (at-least-once delivery) note in `webhook_dispatcher`'s module docstring.
  - **5 new cross-task tests** (`test_phase7_export.py`): /context≡/export bundle equivalence (fully-closed),
    the prefer_open=False seal (export CLOSED while live OPEN), a mixed-shape batch (position+lifecycle+
    closed_row_only in one ZIP), and the `?format=` alias→`fmt` route-dependant wiring (the handler tests
    pass `fmt=` directly, bypassing alias resolution). Phase-7 suite now **100 passed**.

### Phase-7 deferred follow-ups (filed task 286; none blocking — file/pick up opportunistically)

The holistic audit confirmed these are bounded, deliberate gaps — not bugs. Listed so a future phase
doesn't rediscover them as surprises:

1. **`calc_match_audit` absent from the export bundle** — the audit table that records WHY a calc matched
   an order (spec §10.x) is not assembled into the reverse-query graph / export. The bundle carries the
   matched result (junction + deviations) but not the match-decision trace. Add a `get_calc_match_audit_by_*`
   read + a `match_audit` bundle section if a downstream model needs the matcher's reasoning.
2. **No JSON `/positions/open` endpoint** — open positions are resolvable only *through* a calc/lifecycle/
   position key (the assembler's open-resolution). There is no "list all open positions" read API. Phase 8's
   dashboard will likely need one (currently the UI reads `app_state` server-side).
3. **§7.3 pagination / caching skipped** on the reverse-query reads — `get_{orders,fills}_by_position_id`
   are full-scans (orders has no `terminal_position_id` index), and `/context` has no cache. **Acceptable
   at localhost single-tenant scale** (CLAUDE.md Task 163 deployment context); revisit only if a position
   accrues thousands of orders or the deployment shape changes.
4. **Cross-language float contract undocumented** — `json_safe` coerces non-finite REALs → `null` at the
   JSON boundary (so the engine never emits `Infinity`/`NaN`), but there is no published receiver contract
   stating "a null in a numeric field MAY mean non-finite-at-source". A webhook/export *consumer* in another
   language can't distinguish a true null from a coerced inf. Document in the spec if a non-Python consumer
   is built.
5. **Algorithmic signing-downgrade for exposure — N/A at this deployment**: the export falls back to an
   *unkeyed* SHA-256 digest when `EXPORT_SIGNING_KEY` is unset (tamper-evidence, not authenticity). That's
   correct for localhost single-tenant (threat model = silent data drift, not forgery — CLAUDE.md Task 163).
   If the engine is ever exposed, set `EXPORT_SIGNING_KEY` (→ HMAC) and re-elevate this to a hardening item.
6. **Shutdown task-cancellation drops an in-flight webhook** — the dispatcher worker (and funding loop) are
   cancelled on shutdown; a job mid-POST is lost. **Covered by design**: delivery is at-least-once + the
   §11.3 model has the subscriber RE-FETCH via reverse-query, so a dropped webhook self-heals on the next
   poll. A replayable dead-letter QUEUE (vs the current `engine_events` row) would close it fully — deferred
   (see `webhook_dispatcher` docstring deviation note).

---

## ⚠ DEV-ENVIRONMENT HAZARD (observed 2026-06-04) — something rewrites source files mid-run

**Symptom.** During tasks 269 + 271 (Phase 7), an external process in this dev environment was observed
**mutating tracked source files on disk MID-SESSION**, independent of any edit I made:
- The T1 *and* T2 audits (independent subagents) each caught `core/db_orders.py` transiently containing a
  bogus `exit_time_ms_RENAMED` column in a helper's `ORDER BY` — producing **spurious, non-deterministic
  red test runs** (`sqlite3.OperationalError: no such column`) that vanished on the next run. The working
  tree was clean before and after; the mutation was momentary. (This looks like an external
  mutation-testing / chaos harness rewriting files.)
- Separately, an **audit subagent ran `git checkout tests/<file>`** (to revert its own scratch edits),
  which **silently reverted my UNCOMMITTED P7.T2 test additions** back to the last commit. Caught via
  `git status` (production code still `M`, test file not) + `grep`; the 9 tests were re-authored and the
  audit's improvements folded in. (Precedent: Task 241's `order_enrichment.py` on-disk revert.)

**Why it matters.** A red run may be an **artifact**, not a real failure (cf. CLAUDE.md audit-time-artifact
discipline). And uncommitted work is not safe between a task's implementation and its commit.

**Mitigations (do these):**
1. **COMMIT each task as soon as it's green + audited** — don't leave a task's code/tests uncommitted across
   a long audit fan-out. Tasks 268–272 followed this (small, frequent commits).
2. **On a red run, re-verify the working tree first**: `git status` + `git diff` + grep the failing
   symbol/column in the source. A failure citing a column/identifier that *shouldn't exist*
   (`*_RENAMED`, etc.) is the tell — re-run once before investigating as a real bug.
3. **Instruct audit/subagents NOT to run destructive git** (`checkout`/`reset`/`restore`) on the working
   tree — they should revert their own edits with the Edit tool, or work read-only. If one must, commit
   first so the working tree is recoverable.
4. If files keep mutating, **find + stop the external process** (mutation-testing harness, file watcher,
   linter-on-save, sync agent) before the next session.

---

## ★ HISTORICAL STATUS (2026-06-02) — PHASE 5 COMPLETE (T1–T7) + HOLISTICALLY AUDITED

**Phase 5 (funding + fees, plan §5) is fully shipped + holistically audited.** Tasks 255–257:
- **P5.T1** funding feed — `schedulers._funding_refresh_loop` REST-polls FUNDING_FEE income (reuses
  `exchange_income.fetch_income_history`; inclusive cursor; dedup-idempotent; non-fatal).
- **P5.T2/T3** attribution + dedup — `core/funding_handler.py` maps symbol→open-position tpid, resolves
  the PRIMARY calc via the shared `_position_primary_calc` (no second rule — R1/T240), writes a
  `funding_events` row deduped on a deterministic synthetic `venue_event_id`.
- **P5.T4/T5** close aggregation — `closed_positions.funding_fees = SUM(funding_events)` on the FINAL
  close row only (per-partial rows preserved → final-only avoids overcount); `net_pnl = realized −
  total_fees + funding_fees`. **P5.T6** verified `total_fees == SUM(fills.fee)` (close + prorated entry).
- **P5.T7** live unrealized-funding view — grouped `sum_funding_by_positions` populates
  `PositionInfo.individual_funding_fees` each refresh (hoisted above the junction-read early-returns so
  a junction fault can't strand it); a Funding column folded into Net across the 3 open-position views.
- **Schema reconcile** — `funding_events.position_id` INTEGER→TEXT (match the universal
  `terminal_position_id` key; fail-loud, re-runnable, empty-table guarded migration).
- **Holistic audit (task 257)** — 8 adversarial dims (end-to-end key-match, ingestion, close, schema,
  live-view, spec-fidelity, test-integrity, completeness) + my re-verification. **Core verified sound**:
  the TEXT key-match holds at every hop (write→close-read→live-read), single-DB, R1 intact, net_pnl
  sign, preserve-deviation, no live-DB pollution (md5-verified). Fixes: 2 misleading-comment
  corrections (the "recoverable" claim; migration "reads-0"→numeric-collision), the T7 funding-stamp
  hoist, 6 anchor-noted deferrals, +5 Rule-8 tests.
Full Phase-5 detail: `docs/design/calc_linkage_implementation_plan.md` §5 + the task 255/256/257 commits.

**Calc-linkage now spans Phase 0 → 1 → 2 → 3 → 4 → 5. Phase 6 (event-bus enrichment + close payload) is next.**

### ⚠ Phase-5 deferred follow-ups (filed in-code; the headline is real, the rest bounded)
- **✅ Deferred-funding-at-close / venue reconciliation (HEADLINE) — CLOSED (2026-06-02, first P6 step).**
  **Re-investigation corrected the filed mechanism**: the filing said the late row "is written but
  never folded into closed_positions" — WRONG. The attribution map is built from OPEN positions only,
  so a closed position's late funding ORPHANED (never written). Fix is two-part: (1) late attribution —
  `db.find_closed_position_for_funding` matches the closed lifecycle whose `[entry,exit]` window
  contains the settlement ts (excludes empty-tpid; sealed calc/lifecycle); (2) reconcile —
  `db.reconcile_closed_position_funding` recomputes `funding_fees=SUM`/`net_pnl` on the FINAL close row
  (no-op when unchanged). `handle_funding_incomes` falls back to (1)+(2) on open-cache miss and returns
  a `reconciled` count; also wired into the `build_final_close_row` backstop (WS-gap half). **Audit
  (6-dim workflow): 1 MED confirmed + FIXED** — a swallowed reconcile fault left the row stale with no
  retry (dedup blocked re-trigger) and my comment falsely claimed later-poll recovery; fixed by
  collecting the closed tpid for reconcile regardless of `inserted` (self-heals on the next poll, since
  reconcile is idempotent + no-op-when-unchanged). Tests: `test_phase5_funding.py` §7 (+18; incl. the
  Rule-8 fault-injection self-heal test). Full suite 2989 passed / 7 skip / 1 pre-existing fail / 0 new.
  See `[[project_deferred_funding_reconcile]]` memory.
  - **⚠ FILED (audit, not fixed — pre-existing, engine-wide)**: the aiosqlite `_conn`
    (`database.py:624`) sets WAL but **no `PRAGMA busy_timeout`**, so a concurrent write-lock collision
    raises `OperationalError` immediately (the trigger for the swallowed-reconcile fault above, and any
    other best-effort aiosqlite write). Self-heal makes the funding path resilient regardless, but a
    `busy_timeout=5000` on the connection would reduce transient-lock raises engine-wide. Own task
    (touches all aiosqlite writes — out of this funding fix's surgical scope).
- **Overfill-split funding double-count**: closing fills exceeding open qty across distinct orders at
  distinct ts → each can satisfy `is_final` and stamp the full SUM. Anomaly-gated; documented, not
  guarded (don't destabilize the T238 `is_final`).
- **Multi-account**: funding loop is active-account-only (like all REST loops); `last_seen_ms` cursor
  not reset on account switch (dedup prevents double-writes; the new account's pre-cursor funding can skip).
- **Non-binance key prefix**: synthetic `venue_event_id` hard-codes `binance:` — gate/parametrize before Bybit/MEXC.
- **Funding-loop observability**: no heartbeat — a silently-stopped poll reads funding 0 with no operator signal.
- **`mark_price`/`funding_rate`** on `funding_events` intentionally NULL (not on the income feed).
- **`position:closed` payload `funding_fees`/`net_pnl`**: Phase 6 (close-payload expansion).
- **Hedge-mode `tranId`** + `fetch_income` pagination: deferred (one-way live is collision-free; pagination
  only matters after a >1000-row multi-day-outage backlog).
- **Two-views-not-two-totals**: funding lives in BOTH `exchange_history` (equity/wallet, abs, FIFO) AND
  `funding_events` (per-position, signed) — no double-count today, but a future report must NOT sum
  `closed_positions.net_pnl` with an `exchange_history`-derived total.

## PHASE 6 IN PROGRESS (event-bus enrichment + close payload)

**Spec**: `docs/design/calc_linkage_spec.md` §9 (event catalog + `position:closed` full payload), §3.4
(exit_reason enum). **Plan**: `docs/design/calc_linkage_implementation_plan.md` §6 (rows 6.1–6.8).
**Depends on**: Phases 1–5 (the events' data is now all produced). **Effort: M.**
Goal: hierarchical per-account topics (`engine:account:{id}:{domain}:{event}`); the full `position:closed`
payload (now incl. `funding_fees`/`net_pnl`); sweep all calc:*/position:* emissions; `order:duplicate_detected`;
the snapshot-wins drift inversion (feature-flagged — the riskiest single change; isolate + monitor).

### Phase-6 progress
- **✅ P6.T1 — SHIPPED (task 260)**: the per-account topic wrapper — `event_bus.ch_engine(account_id,
  domain, event)` → `engine:account:{id}:{domain}:{event}` + `EventBus.publish_engine(...)` +
  `DOMAIN_CALC/POSITION/ORDER` constants. Purely additive; audit clean. Tests `test_phase6_events.py` (6).
- **✅ P6.T3 — SHIPPED (task 261)**: rescoped the **6 calc-status-transition events** (linked/superseded/
  expired/cancelled/completed/partially_filled) from FLAT topics to the per-account hierarchical topics via
  `publish_engine`. `calc_state.transition()` gained a **required kw-only `account_id`**; all 7 callers
  thread it (handlers ×3, order_enrichment matcher=`aid`, order_manager ×2, link_actions). `TRANSITION_EVENT_MAP`
  values are now the bare event suffix. **Zero subscriber risk** (no in-process subscriber consumes flat
  `calc:*`). Audit (5-dim workflow): 7 candidates → 2 confirmed, **both Rule-8 test-coverage gaps + fixed** —
  (a) the phase1 `_drain` helpers kept a `c == channel` flat fallback so a flat-topic regression passed
  undetected (dropped → suffix-only); (b) only `linked`/`cancelled` had full-topic+account assertions →
  added a parametrized `test_state_machines` test covering ALL 6 events × a non-default account (7). Full
  suite 3001 passed / 7 skip / 1 pre-existing fail / 0 new.
- **✅ NEW-PRODUCER calc:* events — 2 of 3 SHIPPED (task 262, P6.T3-follow-up)**: `calc:created` (emitted
  from `handle_risk_calculated`, gated on `calc_id and eligible`, payload = §9 keys
  calc_id/ticker/direction/window_seconds/model_name/tags/operator_id) + `calc:order_cancelled` (emitted
  from `_release_calc_on_operator_cancel` on a SUCCESSFUL release only; payload = calc_id/order_id(internal,
  matches calc:linked)/cancel_reason_category='OPERATOR'/raw). Both route through
  `event_bus.publish_engine(account_id, DOMAIN_CALC, "<event>", payload)` — NOT status transitions, so NOT
  via `calc_state.transition()`/`TRANSITION_EVENT_MAP`. Audit clean (payloads match §9; mutation-verified
  Rule-8 tests). Tests: `test_phase1_calc_revision::TestCalcCreatedEvent` (2) + `test_phase1_calc_release`
  (+2). **⚠ STILL DEFERRED — `calc:size_deviated`**: its only data source (`_enrich_positions_calc_id`)
  recomputes `size_delta_pct` EVERY refresh, so a naive emit spams every poll; it needs a
  threshold-crossing / anti-spam producer (emit once per crossing, per-(position,calc) dedup state) — its
  own task, NOT a small add.
- **✅ P6.T4 + P6.T2 — SHIPPED (task 263)**: the five `position:*` events on the per-account event_bus.
  `position:opened` (lifecycle MINT) + `position:scale_in` (lifecycle reuse + calc new to the junction) in
  `_link_position_calc_on_open` — POSITION-level semantics from the mint-vs-reuse signal (the per-CALC
  `position_opened` TRADE event is unchanged). `position:partial_close` in `_emit_fill_events` via the NEW
  sync **`EventBus.publish_engine_nowait`** (put_nowait; `_emit_fill_events` is sync but on the loop thread).
  `position:amended` from the on-loop `detect_and_persist_amendment` caller (NOT the to_thread'd worker —
  asyncio.Queue isn't thread-safe). **P6.T2** `position:closed` FULL §9 payload (FINAL-only via `is_final`)
  beside the KEPT flat `risk:position_closed` (compat shim — the reconciler subscriber is untouched).
  Audit (6-dim workflow): 6 candidates → 3 confirmed, all LOW/MED (NO functional/money/thread-safety bug):
  (a/b) the nested `position:closed` `deltas` leaked `hold_time_actual_ms` (a TOP-LEVEL §9 field) — FIXED
  (filter it from the nested block; the close-ROW `**deltas` spread keeps the column) + pinned the deltas
  key set in the test; (c) the partial_close test seeded equal qty_reduced/remaining_qty so a source-swap
  passed — FIXED (distinct seeds 1.0/3.0). Documented payload limits: `position:closed` model_names=[primary],
  model_tags=[], hold_time_planned_ms/close_note=None, mfe/mae=None (reconciler-computed post-close). Tests:
  `test_phase6_events` (+2 nowait), `test_phase2_junction` (opened/scale_in/same-calc + partial_close),
  `test_phase4_amendments` (+2 amended event_bus), `test_phase5_funding` (+2 closed). Full suite 3015 / 7 skip
  / 1 pre-existing fail / 0 new.
- **✅ P6.T5 — SHIPPED (task 264)**: `order:duplicate_detected` — `_detect_duplicate_orders` in
  `process_order_update` (WS, NEW arrivals only, `prev_order is None`) flags 2+ orders with an IDENTICAL
  shape `(symbol, side, order_type, price, stop_price, quantity)` arriving within `DUP_WINDOW_MS=2000`
  (created_at_ms window; `>0` guard for the MEXC-WS gap). Emits `order_ids[]` (internal ids) + `dup_window_ms`
  via `publish_engine(account_id, DOMAIN_ORDER, "duplicate_detected", …)`. The just-persisted order is in the
  cluster query, so ≥2 ⇒ ≥1 other dup. REST snapshot/algo paths intentionally NOT wired (reconciliation,
  not live submission); `exchange_order_id` upsert key collapses WS+REST/re-delivery to one row (no
  inflation). **Audit clean (single agent, 0 findings; §9 payload exact; 4 mutations all caught).** Known
  bounded false-positives (documented, no consumer yet): deliberate scale-in at identical price+qty within
  2s; cancel-then-repaste (status NOT filtered — tight window is the discriminator). **UI badge deferred**
  (no event consumer until Phase 7/8). Tests: `test_phase2_junction::TestDuplicateOrderDetection` (8, incl.
  the real-path wiring test). Full suite 3023 / 7 skip / 1 pre-existing fail / 0 new.
- **✅ P6.T7 — SHIPPED (task 265, operator chose "emit + minimal detection")**: `position:liquidated`.
  **Detection**: a close order whose `order_type` contains `"liquidation"` → `exit_reason="LIQUIDATION"`
  (Binance forced-liq sends `o="LIQUIDATION"`, NOT in `ORDER_TYPE_FROM_BINANCE` → `otype.lower()` fallback).
  Added to BOTH classifiers — `_determine_exit_reason` (highest priority) + `_classify_final_exit_reason`
  (a liquidation among the closing orders DOMINATES → LIQUIDATION over MIXED/TP_LADDER). **liquidation_px**
  persisted to `closed_positions` (added to `insert_closed_position` INSERT; column existed since Phase 0.8
  but was never written) = the **liquidation-fill VWAP** (`_liquidation_vwap`, order-scope-independent — NOT
  this row's exit_price; audit-fixed). **Emit** `position:liquidated` gated on `is_final AND
  exit_reason=="LIQUIDATION"`, alongside `position:closed`; payload `{position_id, liquidation_px,
  bankruptcy_px:None, insurance_fund_fee:None, adl_indicator:None}` — the latter 3 have NO venue-event
  source (deferred "venue status signals"). Audit (3-dim workflow): 2 confirmed LOW + FIXED — (1)
  liquidation_px order-scope decoupling (partial-liq-then-non-liq-final → wrong price) → fixed via
  `_liquidation_vwap`; (2) the `is_final` gate (suppresses the event on a Binance PARTIAL liquidation) was
  untested → added the partial-liq-no-event test. Tests: `test_phase5_funding::TestPositionLiquidatedEvent`
  (6). Full suite 3029 / 7 skip / 1 pre-existing fail / 0 new.
- **✅ P6.T6 — SHIPPED (task 266) — the riskiest change, feature-flagged default-OFF**:
  `position:size_drift` + the snapshot-wins inversion of `data_cache`'s WS-fills-win-within-5s POSITION
  policy. Gated behind `config_json.feature_flags.snapshot_wins_drift` (default OFF → **provably zero
  behaviour change**; the full suite passing at 0-new confirms it). `AccountConfig.snapshot_wins_drift`
  (STRICT bool parse — a string "false" must NOT enable a money-path flag). The inversion is isolated in a
  SYNC `_apply_snapshot_wins_inversion(source, incoming, base_accept, cfg)` that only acts on the REST-within-
  window rejection: flag ON → accept the snapshot (venue authoritative) + emit `position:size_drift`
  `{position_id, fill_derived_size, snapshot_size, delta}` per position disagreeing beyond
  `snapshot_drift_tolerance_pct`. **Config is read OFF the lock** (only for REST-non-force) and passed in, so
  `self._lock` is never held across a DB await (the DataCache single-writer invariant). Scope: positions only
  (`_should_accept_account_update` untouched); out-of-window REST drift not detected (documented). Audit
  (4-dim workflow): 8 confirmed → 2 distinct real fixes (await-under-lock → hoisted off-lock; bare `bool()`
  flag coercion → strict `isinstance(bool)`) + test-coverage (multi-position, safe-default, string-flag) + an
  untracked-test-file reminder. Tests: `test_phase6_size_drift.py` (11) + `test_phase1_account_config` (+3).
  Full suite 3043 / 7 skip / 1 pre-existing fail / 0 new. (NB a flaky aiosqlite-teardown thread warning is
  pre-existing — not from this change; non-deterministic across runs.)
- **🎉 Phase 6 (event-bus enrichment) is FUNCTIONALLY COMPLETE** — P6.T1–T7 all shipped (tasks 260–266; the
  §5 funding reconcile was 259). The full §9 calc:*/position:*/order:* event catalog now emits on the
  per-account in-process event_bus.
- **✅ HOLISTIC Phase-6 audit — RAN + RECONCILED (task 267)**: a 5-dim cross-task workflow over 259–266 (the
  whole-phase view the per-task audits couldn't see) found 11 confirmed, all LOW/MED, **none blocking** (all
  forward-scaffolding — no event_bus subscribers yet). Fixed in 267: (1 real) `position:closed`/`liquidated`
  now idempotent per (account,tpid,exit_time) — emit only on a NEW close row, not a REPLACE, so the per-fill
  build + the disappearance backstop can't double-emit (residual narrow race → AT-LEAST-ONCE; a subscriber
  dedups on position_id+close_ts_ms). Plus: `calc:linked` link_audit_summary deferral DOCUMENTED (recoverable
  from calc_match_audit; full threading = Phase-7); `_read_drift_config` docstring corrected (runs per REST
  poll off-lock, not rare-only); `position:closed` lifecycle_id (§3.5 key) + funding_fees/net_pnl
  (post-close-mutable, like mfe/mae) clarified; `calc:partially_filled` no-producer + `partial_close`
  stale-remaining_qty (T238 F6) anchor-noted. +Rule-8 tests: account-scope (non-default acct 7) for
  position:opened + order:duplicate_detected, position:closed value-pins, size_drift account segment, the
  idempotency gate. Full suite 3046 / 7 skip / 1 pre-existing fail / 0 new.
- **Phase-6 DEFERRED (own tasks)**: `calc:size_deviated` producer (needs a threshold-crossing/anti-spam
  emitter — naive emit spams every refresh); liquidation-field ingestion (bankruptcy_px/insurance_fund_fee/
  adl_indicator — "venue status signals"); always-on (flag-off) `position:size_drift` observability if ever
  wanted. **Next phase: Phase 7 (reverse-query + audit export)** — see plan §7 / spec §11.
  See `[[project_phase6_event_bus_state]]`.

### VERIFY-FIRST before scoping Phase 6 — DONE 2026-06-02 (corrects the prior claim; see `[[project_phase6_event_bus_state]]`)
- ⚠ **CORRECTION**: the prior handoff said `TRANSITION_EVENT_MAP` in **calc_state/link_state** is
  empty-until-Phase-6 — **imprecise**. `core/calc_state.py:111` is **POPULATED**: 6 `calc:*` events
  ALREADY fire on the event_bus via `transition()` (`calc:linked/superseded/expired/cancelled/completed/
  partially_filled`) — but as **FLAT topics** (`"calc:linked"`), NOT the §9 per-account hierarchical
  `engine:account:{id}:calc:{event}`. So **P6.T1/T3 is a topic-RESCOPE of existing emissions, not
  add-from-scratch.** Only **`link_state.TRANSITION_EVENT_MAP` is genuinely empty** (the real link:* gap).
  `calc:created`/`calc:size_deviated`/`calc:order_cancelled` are NOT on the event_bus (not transitions).
- **position:* events: NONE on the event_bus** — emitted today only as trade events (`log_trade_event`:
  `position_opened` om.py:1245, `partial_close` :1272, `position_amended` :1190, `position_closed`
  :2261). P6.T4 lights up the event_bus topics from those SAME seams (this part of the claim holds).
- ⚠ **`risk:position_closed` (flat, anemic, om.py:2253) HAS a LIVE subscriber** —
  `_reconciler.on_position_closed` (`schedulers.py:390`). So **P6.T2 (full close payload) is NOT
  zero-subscriber**: expand additively / preserve the reconciler's keys (compat-shim). (Lesson 10's
  "zero calc:* subscribers" still holds — nothing subscribes to `calc:linked` etc.)
- **P6.T6** snapshot-wins inversion target confirmed = `data_cache._should_accept_position_update`
  (`_WS_PRIORITY_WINDOW_MS` priority window), ~`data_cache.py:173-204`.
- **✅ §5 deferred-funding reconcile is now SHIPPED** (see the CLOSED headline above) — no longer a Phase-6 item.
- §3.4 `*_PLANNED → *_AMENDED` exit_reason reclassification (the T2.7/T235 deferral — now HAS the
  amendment data) is a natural Phase-6 close-row-rebuild-seam item.

### Phase-4-adjacent follow-ups still OPEN (file/pick up opportunistically — none blocking)
- `_detect_modification_events` dead-path (the legacy `tp_modified`/`sl_modified` detector runs
  post-gate so never fires live — relocate pre-gate like P4.T1, or fold into the amendment path).
- §3.4 `*_PLANNED → *_AMENDED` exit_reason reclassification (the T2.7 deferral — now HAS the
  amendment data it was waiting on; reclassify on the close-row rebuild seam).
- `_emit_fill_events` `asyncio.to_thread` consistency cleanup (same sync-sqlite-in-async exposure
  the P4.T4 audit fixed on `_emit_amendment_event`; pre-existing, un-retrofitted).
- Multi-TP per-rung `planned_tp` drift refinement (SPEC-001 — junction is per-entry not per-rung;
  match the closing rung's planned level; see `test_multi_tp_scenario.txt`).
- Matcher-side / legacy `/admin/calc_link` amendment-calc_id backfill is COVERED now for the
  live matcher; the legacy admin endpoint is still slated for retirement.
- Trade-event TEST POLLUTION of the live per-account DB (`test_order_manager`/`test_om5` write real
  `position_closed`/`order_filled` rows via the un-isolated `_emit_fill_events`/close-row
  `log_trade_event` — needs a session-scoped conftest that points `config.DATA_DIR` at a tmp dir).

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

**Phase 4 — SHIPPED + AUDITED + RE-AUDITED (tasks 246–253, plan §4)** — the per-task record
(read for the deviations + audit trail; the Phase-5 orientation is at the TOP of this file):
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
- **P4.T5 — SHIPPED (2026-06-02, task 250)**: populate `closed_positions.tp_drift_pct` / `sl_drift_pct`
  = (final amended TP/SL − planned) / planned × 100, in `_compute_close_deltas` (the T2.5 delta home).
  **planned_tp/sl from the PRIMARY (most-contributing) calc's junction snapshot — NOT literally the
  "first" calc** the plan row 4.6 wording implies (§3.2 delta-basis rule; consistent with every other
  close-row delta + T2.6 convergence — deviation surfaced). **final_tp/sl = the latest
  `order_amendments.new_value` for `tp_price`/`sl_price` on the primary calc's legs** (reuses
  `get_calc_amendments`, last-wins per field; the orders row goes stale post-amendment so the ledger is
  authoritative — P4.T1). **Amended-only**: NULL when never amended (the §4 acceptance criterion
  "populated for amended-stop positions") or planned missing. Persisted + REPLACE-preserved: added to
  `_CLOSED_POS_DELTA_COLS` AND to `insert_closed_position`'s INSERT column/placeholder lists — **the
  columns were in the schema but the INSERT never wrote them; the real-close-path test caught the gap**.
  **Independent audit (6 agents): 1 MED confirmed + FIXED at the root** — SCOPING-001: a protective leg
  amended BEFORE bracket inheritance assigned its calc_id leaves an orphaned `calc_id=NULL` amendment
  that the calc_id-scoped drift (AND P4.T2's `cumulative_amendment_count`) silently miss. Fixed in
  `_propagate_bracket_calc_id` (`_apply_leg` now backfills `UPDATE order_amendments SET calc_id WHERE
  order_id=? AND calc_id IS NULL` alongside the orders update — same propagate-on-link discipline as
  `fills.calc_id`; covers WS + REST; guarded so an already-attributed amendment isn't clobbered). I
  verified the mechanism + the all-sites coverage independently before applying (the batch REST wrapper
  delegates to the same `_apply_leg`). **Residual documented edge**: a scale-in protective leg inherited
  under a NON-primary calc_id (T2.9 earliest-entry pick) → drift NULL on the §3.2 primary basis (a
  genuine basis limitation, not a bug). **Residual minor edge (filed below)**: the matcher's
  UNPLANNED→LINKED re-match can likewise orphan an ENTRY amendment for P4.T2's count (drift unaffected —
  it reads only tp/sl). Tests: `tests/test_phase4_drift.py` (13) + 2 bracket-backfill tests
  (`test_phase2_bracket_inheritance.py`) + 2 refreshed T2.5 deferred-column assertions. Full suite:
  2936 passed, 7 skipped, 1 pre-existing failure (TestRollingWindowPeak), 0 new.
- **⚠ FILED (P4.T5 audit, minor) — matcher-side orphaned-amendment count edge.** Symmetric to the
  bracket-inheritance backfill (now fixed): if an ENTRY order is amended while UNPLANNED (calc_id NULL)
  and LATER re-matched UNPLANNED→LINKED (the auto_classify upgrade), its amendment stays
  `calc_id=NULL` → P4.T2's `cumulative_amendment_count` (scoped by calc_id) under-counts. Drift is
  UNAFFECTED (it reads only tp_price/sl_price on protective legs, never entry amendments). Narrow
  (needs amend-while-UNPLANNED then re-match). Fix mirror: backfill in `order_enrichment` auto_classify
  the same way `_apply_leg` now does. Filed, not fixed (out of P4.T5 drift scope).
- **NEXT**: P4.T1–T5 are all shipped → **Phase 4 plan tasks complete.** Remaining Phase-4-adjacent work:
  the `_detect_modification_events` dead-path fix (filed earlier); the §3.4 `*_PLANNED → *_AMENDED`
  exit_reason reclassification (the T2.7 deferral — now has the amendment data it needed); plus the
  P4.T4-filed items (`_emit_fill_events` to_thread consistency; trade-event test pollution) and this
  matcher-side count edge. Then Phase 5 (funding + fees) / Phase 6 (event_bus topics).
- **PHASE 4 HOLISTIC AUDIT — RAN + FIXES SHIPPED (2026-06-02, task 252).** An 8-dimension
  adversarial workflow (amendment capture, calc_id-scoping consistency, "amended" semantics +
  badge, close persistence, event emission, hot-path/txn, test integrity, spec/cross-task) +
  completeness critic over all of T1–T5. **The workflow process died mid-run during a long idle**
  (machine sleep) — 30/31 agents had completed; I **salvaged all results from the run journal**
  (`wf_d552334e-f58/journal.jsonl`) rather than re-run: **22 candidates → 8 CONFIRMED, 13 REFUTED**
  (1 verifier was the hung agent). Re-investigated each (CLAUDE.md mechanism-before-fix discipline):
  - **FIXED — orphaned-amendment-calc_id backfill family** (COMPLETENESS-001/002 + SCHEMA-INVARIANT-001):
    SCOPING-001 (bracket inheritance) was only ONE of the calc_id-assignment sites. An order amended
    while calc-less records the amendment with calc_id=NULL; manual-link (`link_actions.manual_link_order`)
    and the matcher (`order_enrichment._update_orders_sync`, the UNPLANNED→LINKED re-match) ALSO assign
    calc_id but didn't backfill → the calc_id-scoped consumers (count/badge/drift) silently miss the
    amendment. Extracted a shared `db.backfill_amendment_calc_id(order_id, calc_id)` (best-effort —
    a denormalization sync must never break the link path; an older DB without `order_amendments` is
    swallowed) and wired ALL THREE sites (bracket via the helper + a rowcount guard, manual-link via
    the helper, matcher via an inline sync UPDATE keyed by the order's id). Legacy `/admin/calc_link`
    noted (slated for retirement). Tests: matcher (`test_phase1_matcher`), manual-link
    (`test_phase3_endpoints`), bracket (`test_phase2_bracket_inheritance`).
  - **FIXED — drift temporal filter** (P4-CLOSE-001 + TEST-INTEGRITY-004, HIGH): `_compute_close_deltas`
    read amendments with no time bound, so a multi-TP PARTIAL row (recomputed each build / on REPLACE)
    could pick up an amendment that post-dates its own close → as-of-wrong drift. Added
    `if ts_ms <= exit_time` (mirrors the existing is_final closing-fill cut). Tests in `test_phase4_drift`.
  - **FIXED — badge query-fail visibility** (P4T3-001 + TEST-INTEGRITY-002, HIGH→MED): in
    `_enrich_positions_calc_id` the config read + amendment count shared one try/except; an amendment-
    query failure masked live amendments (false-green). Split into two try/excepts; the amendment
    failure now logs at **WARNING** (was silent debug). The miss is transient/self-healing (htmx-polled)
    — an "unknown" badge state would be over-engineering. Test in `test_phase4_deviation_badge`.
  - **REFRAMED — HOT-TXN-001 (filed BLOCKER → actually defensive)**: claimed the bracket backfill
    re-attributes amendments on a re-run. **Unreachable** — after a leg is linked, NEW amendments carry
    the now-set calc_id (not NULL), and there's no concurrent linker, so the "unconditional" UPDATE is a
    no-op. Applied the cheap `rowcount>0` guard anyway (makes the "alongside" coupling explicit).
  - **DOCUMENTED — SPEC-001 (filed HIGH)**: the specific junction mechanism is wrong (the junction is
    per-entry-order, NOT per-TP-rung), but the high-level concern IS the known multi-TP drift
    approximation (planned_tp = single junction snapshot vs final_tp = last-wins across the primary
    calc's TP legs; exact for single-TP/SL). Anchor-commented in `_compute_close_deltas` +
    `test_multi_tp_scenario.txt`; a per-rung-matched planned_tp is a future refinement (own task).
  - **REFUTED (13)** incl. AMEND-CAPTURE-001 ("partial fills recorded as size amendments" — wrong:
    `order.quantity` maps to Binance `q` = original qty, constant across fills; I'd independently traced
    this before the audit confirmed the refutation).
  Full suite after fixes: **2941 passed, 7 skipped, 1 pre-existing failure (TestRollingWindowPeak), 0 new.**
- **PHASE 4 FIXES RE-AUDITED — CLEAN (2026-06-02, task 253).** A focused 5-dimension re-audit of the
  task-252 fixes (matcher hot-path, aiosqlite swallow-then-commit durability, backfill attribution,
  drift temporal filter, badge split) completed without stalling (17 agents): **12 candidates → 2
  confirmed, 10 REFUTED.** Every substantive concern was refuted — the matcher sync-backfill durability
  (a swallowed missing-table error still commits the orders calc_id), the aiosqlite best-effort
  durability, rowcount-guard reliability, and wrong-calc attribution are all CLEAN. The 2 confirmed were
  both badge-split: **BADGE-003 (MED)** = the already-documented transient false-green on amendment-query
  failure (the verifier's own verdict: "no fix needed — accepted trade-off"); **BADGE-001 (LOW)** = the
  config `try/except` I added in T252 was dead code (`read_account_config_async` is contract-safe, never
  raises) — **removed** (the amendment-count try stays; `refresh_cache` calls the enricher directly, and
  the now-unguarded config call + frozen-dataclass attribute access can't raise, so no propagation risk).
  Tests: `test_phase4_deviation_badge` + `test_phase2_rehydrate` green.
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
- **`calc:order_cancelled` event** (spec §9): ✅ NOW EMITTED (task 262) from
  `_release_calc_on_operator_cancel` on a successful release — separate from the
  RELEASED transition (which still has no TRANSITION_EVENT_MAP entry). No
  consumers yet (forward-scaffolding).
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
