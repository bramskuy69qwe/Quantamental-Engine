# Handoff — next Claude Code session

**Date**: 2026-07-30 (**MERIDIAN v3.1 — DD-OVERRIDE + PRE-TRADE NOTES PORTED TO REACT (seventh block). Same day: fragments slim-down · primitives sweep + folder-boundary answer · Jinja retirement `1afc9f8` · archive/launcher sweep · E2E carry-forwards.**)

## ▶ SESSION CLOSE 2026-07-30 (eighth block) — ADD ACCOUNT WIRED IN REACT

**Operator report**: "add account in config not working."

**★ MECHANISM (investigated, not assumed): the button was `disabled`.**
React's Config page shipped `+ Add Account` with
`disabled title="Not wired in P2 — add accounts via the current /config
page"`. So on the React app clicking it did *nothing*, and the workaround
it named was the Jinja `/config` page — the last of its kind after the
retirement. Two things had blocked the wiring, both fixed:
1. `POST /accounts` (the JSON door React can use) accepted neither
   `environment` nor `params_source` — only the HTML-returning
   `/accounts/add-and-reload` twin did. The JSON lane therefore could not
   create a testnet/paper account or seed params from an existing one.
   Both are now on it, **additively** (defaults preserve prior behaviour;
   pinned on the signature, since a direct handler call bypasses FastAPI's
   dependency resolution and would otherwise test the test's own defaults).
2. Nothing exposed the adapter catalog as JSON, so React could not build
   the exchange dropdown → new **`GET /api/config/exchanges`** (same
   `list_rest_exchanges()` source the Jinja modal used, Beta flags intact).

**Shipped**: a real `CfgAddAccountDialog` — name · exchange · market type ·
environment · initial-params (defaults or copy-from-account) · API key ·
secret (masked). Submit is blocked until name+key+secret are non-empty
(the engine rejects a blank name, so the client must not offer a
guaranteed-fail submit); on success the account list reloads and the NEW
account is selected. Mounted as a sibling of the workspace, not inside a
Pane — same clipping trap as the DD-override dialog — and the Config page
root gained the `position:relative` anchor the other dialog-hosting pages
carry. The dialog does NOT activate the account or test the connection:
both already exist per-account and stay one deliberate step away.

**Also fixed, same feature**: the Jinja modal's `<form hx-post="/accounts">`
meant a bare **Enter-key** submit hit the JSON door and painted
`{"status":"ok","id":7}` into the result div, never reloading (the submit
BUTTON overrode with add-and-reload, so only the keyboard path was broken —
filed as MED by the fragments-slim-down audit, now closed).

**Gate: 4117 passed / 6 skipped / 3 deselected + 1 KNOWN FLAKE** —
`test_periodic_loop_survives_reconcile_exception` (the 50 ms-budget timing
test); re-ran 7/7 solo and the diff touches nothing near the reconciler.
Bundle `a1eab22c04` → **`7268075fd2`**. New pins in
`tests/test_add_account_react.py`; the comment-stripper moved to a shared
`tests/_srcpin.py` (second file needed it) and **all 8 new source pins were
mutation-checked** — including two bugs in my own harness (the password
attribute shares a line with the value binding; one case was a no-op).

## ▶ SESSION CLOSE 2026-07-30 (seventh block) — dd_override + notes PORTED TO REACT

**Operator ask**: "port the dd_override and notes endpoints to react" (from
the UI-orphaned list filed in the fifth block), then — on the finding that
two of them had nowhere to go — **"retire the trade_history and position
notes endpoints"**.

### ▶ RETIREMENT (the operator's follow-up call)

`PUT /history/notes/trade_history/{id}` and `PUT /history/notes/position`
are **GONE**, together with the DB helpers that existed only for them:
`update_trade_history_notes`, `upsert_position_note`, and the
already-caller-less `get_position_notes`. Verified caller-by-caller before
cutting; the only surviving mentions are tombstone comments, this file, and
the pins that name them on purpose.

**DATA DELIBERATELY PRESERVED** — retiring an API is not a data migration.
The `position_history_notes` TABLE and the `trade_history.notes` COLUMN
stay in the schema; the diff contains no `DROP`/`DELETE` of any kind.
Re-exposing them later is a matter of adding a READER, not recovering data.
Pinned by `test_retiring_the_api_did_not_drop_the_data`.
**Two precisions the audit made me state properly** (my first wording
overclaimed): (1) the split migration's copy of `position_history_notes` is
best-effort — only rows whose `trade_key` appears in that account's
`exchange_history` reach a per-account DB; anything else survives only in
the `.pre-split-backup` legacy file (rename-not-delete, pre-existing
behaviour). (2) `position_history_notes` now has neither reader nor writer,
whereas `trade_history.notes` lost only its EDIT path — `POST
/history/log_close` still writes that column on insert, so new orphan notes
can still be created there until that endpoint's own call is made.

**NOT retired, deliberately**: `db.query_trade_history` is also
caller-less, but it is the trade_history TABLE's reader — not a notes
symbol — and `POST /history/log_close` still writes that table. Retiring it
would prejudge that endpoint's own port-or-retire call, which is still on
the filed list.

**Gate after the retirement: 4095 passed / 6 skipped / 3 deselected**
(`test_react_port_dd_notes` 42 → 44: the two retired-route lanes swapped for
three guards — routes gone, helpers gone, DATA KEPT).

**★ INVESTIGATION FIRST — only 2 of the 4 endpoints had a destination.**
Traced each one's read surface before writing any UI:
- `dd_override` → portable. The read side ALREADY existed: `/api/state`
  ships `dd_state` + `dd_manually_unblocked`, and Pre-Trade's halt banner
  already told the operator to "override via **Dashboard**" — so the
  Dashboard Risk Monitor was the intended home, not a new invention.
- `notes/pre_trade` → portable. `pre_trade_log.notes` already rides the
  JSON rows (`_paginated_query` is `SELECT *`), and the React History page
  has the Pre-Trade Log tab. No backend read change needed.
- `notes/trade_history` + `notes/position` → **NO destination**. The tables
  they annotate had lost their last reader in the slim-down:
  `db.query_trade_history` and `db.get_position_notes` were caller-less
  (their consumers were `/fragments/history/trade_history` and
  `/fragments/history/exchange`). Porting them would have meant first
  resurrecting those tables in React. → **operator chose RETIRE; both
  routes and `get_position_notes` are now DELETED** (see the retirement
  section above; `query_trade_history` is deliberately kept).

**Shipped**:
- Backend: all four routes JSON-in/JSON-out with real status codes.
  `dd_override` keeps every rule (reason ≥10 chars stripped · must be in
  `limit` · already-active → 200 `already_active` · malformed body → 400)
  and still writes the `manual_override` event. The notes routes stop
  emitting `onclick="editNote(...)"` markup — **that function was deleted
  from base.html in the slim-down**, so those responses had been calling
  into nothing (closes the earlier audit's MED finding #2).
- React · Dashboard: `Override` button in the Risk Monitor DD-STATE cell
  (only when `dd_state == 'limit'` and not already overridden; otherwise an
  `OVERRIDDEN` badge), opening a reason dialog that MIRRORS the engine's
  ≥10-char rule so the operator is never sent into a guaranteed 400.
- React · History: `NOTES` column on the Pre-Trade Log tab — click to
  edit, Enter/blur commits, Escape cancels, then the page re-reads so the
  text comes from the server.
- **Two design traps caught during implementation, not after**: (1)
  `ModelDialog` is `position:absolute` and `Pane` is `position:relative`,
  so a dialog rendered inside the tile would have been CLIPPED to it —
  hence `DdOverrideHost`, a page-level leaf sibling of `<TiledGrid />`
  (pinned, because a future refactor moving it back in would look
  harmless). (2) `_lkForm` decided success by sniffing the body for
  `alert-error`; against a JSON door that ECHOES operator text, a note
  containing "alert-error" would have read as a failed save — added an
  explicit `opts.jsonOk` mode (status-only) and switched the notes save
  plus BOTH `/history/close_reason/` sites onto it. That second one was a
  latent false-negative I introduced yesterday when close_reason started
  echoing `close_note`.

**★★ THE 2-AGENT AUDIT FOUND REAL DEFECTS IN THE PORT — all fixed before
commit.** Both agents independently confirmed the worst one. Do not treat
"I checked the analogous path" as verification again:

| Sev | Defect | Fix |
|---|---|---|
| **HIGH** | **Wrong-account override.** `QE_BOOTSTRAP.activeAccountId` is baked at page load; Config's Activate refetches data WITHOUT reloading (only the nav switcher reloads — I checked that one path and generalised). So the write targeted a stale id, and the route made it worse: it validated the ACTIVE account's `portfolio` but wrote + logged the PATH id, behind a 200. Net: the wrong account got a persisted, un-approved future gate bypass; the real one stayed halted. | Route now **409s** unless the path id IS the active account; `/api/state` gained `account_id`; the client reads `st.account_id` and the `\|\| 1` fallback is GONE (account 1 exists live). |
| **HIGH** | **Silent note-save failure.** On error the cell kept `editing` with no error surface and a blurred input → no retry trigger, note lost, operator believes it saved. Plus a sticky false `⚠ retry` that HID the note text. | Error keeps the editor open with a red border + "save failed · edit + Enter"; guard re-arms on the next keystroke (not immediately, which would let a failed Enter's blur double-PUT); the no-change return clears `phase`. |
| **HIGH** | **False-success notes write.** `UPDATE … WHERE id = ?` was unscoped with no rowcount check, so a stale/foreign id "succeeded" and the text then reverted with no error. | Account-scoped + rowcount → **404**, mirroring `update_close_reason`. |
| MED | Blur wrote the OPEN-TIME snapshot, clobbering a concurrent update with text the operator never typed | `openedWith` ref — an untouched cell never writes |
| MED | Successful save showed the OLD text for the whole reload round trip (forever if the reload failed) | optimistic paint until the server value catches up |
| MED | The 30 s auto-refresh unmounted an in-progress edit (server-paged, newest-first) | poll skips while `HNOTE_EDITING` is non-empty |
| MED | `already_active` returned 200 → client counted it a success and dropped the reason | now **409** with an `error` |
| MED | Override offered in ADVISORY mode, where nothing is gated | gate is `dd_state=='limit' && enforced` |
| MED | `close_reason`'s 400/404 were the last HTML spans behind a JSON decorator | now `{"error": …}` |
| MED | `JSON.parse('null')` → `data.error` throws, mislabelled "engine unreachable" | `|| {}` in both wrappers |
| MED | dialog flag was module-level and never reset → re-raised itself on Dashboard re-entry | reset in `stop()` |
| INFO | Dashboard root lacked the `position:relative` every other dialog-hosting page has | added |

**★ AND THE PINS THEMSELVES WERE WEAK — the adversarial agent proved it by
mutation.** `_code()` stripped only `//`, but these modules are commented
with `/* */` block headers, so three pins SURVIVED deletion of the code they
protected (the notes PUT, the refreshState wiring, the guard's early
return). Fixed: `_code()` now strips both comment forms and has its own
tests (incl. a no-delimiters-inside-string-literals pin); every source pin
routes through it; the min-reason pin now parses BOTH sides and asserts they
agree; the gate pin asserts ternary STRUCTURE, not a substring that predated
the change. **A scratch mutation harness now verifies 7 pins fail when
their subject is deleted** — that check is the thing to repeat for future
source pins.

**Gate: 4093 passed / 6 skipped / 3 deselected** (4051 + the 42 pins in
`test_react_port_dd_notes`, up from 24). Bundle `fc0125476b` →
**`a1eab22c04`**.

**Process note — I twice wrote a PREDICTED gate count into this file before
the run finished** (4082 → actual 4051; 4102 → actual 4093), both corrected.
Never write a number you have not read off the run.

**⚠ ENGINE IS DOWN — could not browser-verify.** `data/engine.pid` holds a
stale **43692**, nothing is listening on :8000, and `risk_engine.jsonl`
ends at **18:09:46** with no crash line in the tail (last entries are a
rate-limited reconciler abort + a normal Finnhub upsert). The operator
restarted it earlier this session, so this may be **OBS-001 recurring**
(silent engine stop, still unexplained) — or a deliberate/window-close
stop. NOT diagnosed; surfaced per the audit-time-environment rule rather
than guessed at. **A restart IS required for this feature**: the bundle
alone is picked up on a hard refresh (v3.html re-reads `manifest.json` per
request), but the JSON route changes need the process restarted.

## ▶ SESSION CLOSE 2026-07-30 (sixth block) — PRIMITIVES SWEEP + the folder-boundary answer

**Operator ask**: "simplify the frontend folder by using either frontend or
templates folder only can we?" — **investigated and answered: no, not by
moving files.** The two folders are split by LIFECYCLE, not duplication:
`frontend/` is build-time source (its own header says it never runs at
runtime) that emits `static/v3/`; `templates/` is runtime Jinja read per
request. The React app needs exactly ONE runtime-rendered file —
`templates/v3.html` — because it injects `active_account_id` (changes on
account switch) and the config.py identity constants (Release-hygiene: a
version bump must show WITHOUT a rebuild). Verified `Jinja2Templates`
accepts a directory LIST (starlette 1.0.0), so moving the shell into
`frontend/` is *technically* trivial — **advised against and not done**: it
would put a runtime-served file inside a folder whose stated invariant is
"build-time only", trading a clean lifecycle split for a cosmetic one.

**Operator chose the sweep-and-document option** (offered 3: sweep /
port-program / shell-move). Shipped:
- **4 consumer-less primitives DELETED** — `deviation_badge`,
  `link_status_badge`, `period_selector`, `table_row`. Independently
  re-verified: ZERO surviving-template importers (their consumers were all
  fragments deleted in the slim-down); every other reference was a test or
  prose. templates/ **23 → 18 files**, primitives 7 → **3 live**
  (`status_indicator`, `card`, `empty_state` — all imported by
  `fragments/needs_link_queue.html`).
- **Dead CSS removed from base.html with its macros**: the `.tr-p*` block,
  the `.ps*` block, and `.preset-btn` (period_selector was its only
  consumer; every date-range surface it styled is React now).
- **Pins**: 2 whole files retired (`test_task123_table_row`,
  `test_task125_period_selector` — 100% macro-render), plus AST-scripted
  class/test removal in 4 files (`TestBadgeTemplates`,
  `TestLinkStatusBadgeMacro` + `_render_badge`, `TestBadgeMacroLabel`,
  `test_table_row_macro_still_compiles`) and 2 compile-list trims. **The
  Python-side badge logic was KEPT** — `TestDeviationBadgeLevel` /
  `CountAmendments` / `EnrichBadge` pin the levels that feed the JSON doors
  React reads; only the Jinja-macro RENDER pins died. Orphan sweep after:
  `_REPO` ×2, `_make_env`, a `jinja2` import.
- **README slim**: primitives README 444 → ~300 lines (7 macro sections →
  3). The "open/close pair" how-to SURVIVES (it's teaching material) but
  was rewritten generically with a `git show 70f5f10^:...` pointer to the
  retired reference impl; the **Decision tree stays** — `test_task124`
  pins it and needs `EmptyState` within 1500 chars of it.
- **`frontend/README.md` + `templates/README.md` WRITTEN** — the
  build-time-vs-runtime boundary, a per-file "why it's still here" table
  for all 18 templates, and the recorded path to one folder (port
  `/config` account CRUD + the 5 admin pages to React) so this question
  doesn't get re-derived. **Deferred by operator decision, not forgotten.**

**Gate: 4051 passed / 6 skipped / 3 deselected** (was 4100 — the 49-test
delta is the 2 retired macro-test files + the 4 retired classes/tests).
All 18 surviving templates compile-render. Checked and deliberately NOT touched:
`frontend/DESIGN.md`'s `PeriodSelector` is the **React** primitive (same
name, unrelated), and CLAUDE.md's `TableRow`/`.preset-btn` mentions are
inside a historical "Background:" narrative whose lesson is still valid.

**(fifth block, same day — the slim-down itself:)**

## ▶ SESSION CLOSE 2026-07-30 (fifth block) — FRAGMENTS SLIM-DOWN + Dashboard-first landing

**Landing fix first (operator ask, `0c0f126`)**: the shell restored the
last-visited page from localStorage (`qe.page`) — a fresh load of `/` now
ALWAYS lands on Dashboard. Explicit `#hash` deep-links still win; refresh
keeps the current pane via the hash. `qe.page` write removed + e2e storage
inventory updated. **Bundle `30e626377e` → `fc0125476b`** (hard-refresh
after the pending engine restart).

**THE SLIM-DOWN (audit per HANDOFF charge; consumer map built from
hx-*/include/htmx.ajax grep over surviving Jinja + /fragments/ grep over
frontend/src + e2e)**:
- **KEEPERS — exactly 5 of 67 templates** (the charge's list confirmed):
  `ws_status` (base 1s poll) · `needs_link_queue` (orders/needs_link) ·
  `account_list`/`account_detail`/`account_config` (config.html) — plus
  `needs_link_count` + `connections` (inline-HTML routes) and all
  `primitives/*`.
- **62 templates DELETED**; **35 routes DELETED** (9 dashboard, 4 cockpit,
  5+3 models fragments + htmx form-lane CRUD [POST /models,
  POST /models/{id}/update, DELETE /models/{id} — React uses /api/models],
  2 backtest, 7 history [exchange, open_positions, trade_history,
  open_orders, position_events, exec_link GET + POST confirm], analytics
  equity_curve, ws_log, GET /fragments/accounts + activate-frag,
  GET /calculator/refresh). Dead helpers went WITH last consumers
  (_get_cached_recent_orders, _has_tpsl_modification, _render_fragment/
  _oob_list/_parse_model_form family).
- **18 doors JSON-ONLY** (`format` param stays accepted-and-inert):
  8 analytics, closed_positions/order_history/fills/position_fills,
  pre_trade/trade_events, POST /calculator/calculate +
  link-window-status, backtest-upload (dry_run now honored on every
  lane — the P7 LOW-1 400-guard existed only for the htmx lane),
  PUT /history/close_reason (JSON ok; React checks resp.ok). DELETE
  /accounts/{id} returns JSON (its render was discarded via
  hx-swap="none" anyway). Decorators switched to
  response_class=JSONResponse.
- **base.html de-dashboarded** (post-migration JS-drift sweep): ghost
  CSS, dashboard/history tab switchers + row-counter, [data-entry-ts]
  ticker, editNote + note-textarea, echarts CDN + theme + dispose hook
  all removed (every DOM target lived in deleted fragments);
  `static/echarts-theme-qe.js` deleted (base.html was its only ref).
- **Tests**: ~440 pins retired/adapted across ~45 files (AST-scripted node
  deletion + orphan-helper sweeps; 8 whole files rm'd incl.
  test_fragment_routes/test_ghost_interface/test_flicker_and_layout/
  test_task112/test_task113). LIVE semantics RE-PINNED on JSON, not
  dropped: the t0/PENDING/ERROR chain (task146), close-reason endpoint,
  closed-positions badge STAMPING (linkage_history_plan drives the JSON
  door), upload error lanes with real status codes, validator/wiring
  count pins updated with reasons. One comment-trap caught in-session:
  a retired-ticker pin stayed green off my own residue COMMENT
  (the 786b610 class) — class deleted.
- **Decisions**: `/params` KEEPS its 302 → /config (bookmarks, 2 lines).
  The two docs/archive legacy CSVs (Quantower-era exchange-history/fills
  snapshots, 37 KB) KEPT — recovery-program provenance.
- **Filed, not deleted — UI-ORPHANED action endpoints** (template-
  independent; their only triggers lived in deleted fragments; operator
  call whether to port to React or retire): POST /account/{id}/dd_override
  (DD manual override has NO UI since the retirement), PUT
  /history/notes/{pre_trade,trade_history,position} (note editing),
  POST /params/update, POST /history/log_execution + /history/log_close
  (manual-entry forms).
  **▶ DISPOSED in the seventh block (same day): dd_override + notes/pre_trade
  PORTED to React; notes/trade_history + notes/position RETIRED. Still
  awaiting a call: POST /params/update, log_execution, log_close.**

**Gate: 4099 passed / 6 skipped / 3 deselected** (was 4480/6/3 — the
delta is exactly the retired pins; the intermittent aiosqlite teardown
warning fired once, standing carry-forward). Surviving-template
compile-render CLEAN; post-delete template-name + route-path greps CLEAN
(inert comments only); e2e untouched (trade-oracles use the two surviving
JSON doors' `?format=json`, unchanged behavior).

**Independent 2-agent audit (house cycle): 0 CRIT on both lenses.**
Lens 1 (broken consumers): all 79 React engine-URLs resolve, all 8 htmx
verb targets inside the 5 keepers point at live routes, zero executable
references to deleted surfaces. Lens 2 (payload drift): all 19 converted
doors verified expression-identical to their old format=json branch;
pin-retirement sampling (20 nodes + all 8 deleted files) confirmed no
capability loss; mechanical removed-pin-vs-live-attribute cross-check
clean. Findings FIXED in the hygiene follow-up commit: the skipped
SQL-injection e2e class re-pointed off the deleted open_orders door
(its skip reason had gone false — the one thing the "route greps clean"
claim missed: tests/ wasn't in that grep), the untagged model_display
lane re-pinned as JSON, 3 dead cockpit/orders constants
(_CLOSES_LIMIT now actually feeds api_linkage_closes;
_NEEDS_LINK_PREVIEW retired — /orders/needs_review is uncapped by
design), ~10 orphan test constants/imports, .notes-cell CSS, the
close_reason sniff.ts entry, backtest-upload's missing response_class,
and 5 stale prose sites (routes_dashboard hot-path comment,
exec_link docstring, routes_backtest, routes_models, routes_history).
ACCEPTED as residue: close_reason/delete_account error lanes still
return HTML spans under a JSONResponse decorator (status codes
unchanged; React surfaces r.text on failure — converting them to JSON
would WORSEN the operator-facing error text), 4 consumer-less primitives
kept per the charge, htmx sse.js/idiomorph loads in base.html
(pre-existing since the retirement, opportunistic cleanup). Pre-existing
drift SURFACED (not caused) by the audit, left for a later pass: the
add-account form's bare-Enter submit (hx-post /accounts) swaps a raw
JSON body into #add-account-result (the button's add-and-reload lane is
correct), and the `account-added` listener in base.html has no emitter.

## ▶ SESSION CLOSE 2026-07-30 (fourth block) — archive sweep + launcher

Operator-directed. Root 30 → **13 files**. `9c1ae53`: 9 tracked
historicals git-mv'd to `docs/archive/` (v2.4/v2.5-era plans+specs, the
1.1.5 PDF, the Quantower-era .sln, test_multi_tp_scenario.txt,
extract_purposes.sh; README links + 2 code-comment citations
re-pointed); 7 untracked June debug artifacts (5 png + 2 multi-MB logs)
moved on disk to `docs/archive/debug-2026-06/` (gitignored — NOT in
history). KEPT deliberately: `pyproject.toml` (pytest-timeout guardrail —
the operator listed it, refused with reason). `23824e0`+`786b610`:
**launch.bat ARCHIVED** (its `--reload` double-ran live schedulers) —
`launch-v3.bat` is THE launcher, URLs promoted to `/`, title/banner
de-versioned; launcher pins re-pointed with hard reads + a NEW
never-reload pin (executable-lines-only after a first version tripped on
its own warning comment and briefly pushed red — fixed forward, gate now
conditional before push).

## ▶ SESSION CLOSE 2026-07-30 (third block) — JINJA RETIREMENT SHIPPED · v3.1

Operator-directed ("lets start the jinja retirement"); the gate was the
Phase-7 acceptance report. Executed from the 07-25 constraint map — nothing
re-derived, every recorded trap confirmed live (the v3.html "extends"
false-positive grep hit, the orphaned-handler risk, the 6 base.html
extenders, /config's account-CRUD dependency).

**ONE atomic commit `1afc9f8`** (a half-retired tree is never green):
- `/` = React shell (routes_v3); `/v3` → 307 `/` (fragment survives).
- 8 page GETs + templates deleted; full-body handler removals;
  post-delete template-name grep CLEAN.
- Survivors intact: /config · /params · ALL /fragments/* · POST /models ·
  POST /calculator/* · base.html + admin/* + orders/needs_link (nav
  trimmed to App + Needs Link, hx-boost dropped; page_meta trimmed).
- fragments/model_detail.html's calculator link → `/#Pre-Trade`.
- **129 pins retired across 28 files** (AST-scripted deletion off the
  gate's failure list + whole-class collapse; 1 file emptied → git rm;
  truncated-name collisions in the terminal failure list required a
  second per-file pass with full names — the failure list is a SAMPLE,
  sweep until green). NEW pins: `/` serves the v3 shell, `/v3` 307s,
  retired GETs stay 404 (resurrection = drift).
- e2e harness re-pointed to `/` (preflight would have died on the 307).
- service-worker CACHE_NAME → qre-v2 (purges every browser's Jinja-era
  cache; the deferred plan-§1.4/1.5 coexistence item).
- **v3.1**: config.py bump + README Status rewrite + v3.html title now
  derives from project_version_ (was hardcoded "v3").

**Gate: 4480 passed / 6 skipped / 3 deselected** (was 4608/7 — exactly
the retired pins + 1 skip inside a retired file); version-shape pins
green; e2e selftest 4/4.

**Independent-agent audit (house cycle): contract holds, NO functional
defects.** Sampled deleted pins all targeted retired surfaces (no
capability-coverage loss); route table, survivors, nav, SW, version pins
all CLEAN. Three hygiene findings (empty test shells with template-reading
helper booby traps · orphan helper classes · commit-orphaned imports)
fixed in the follow-up hygiene commit, which also corrects the retirement
message's extender count (7, incl. config.html — not 6). Doc-rot INFO
residue accepted (inert comments naming retired files).

**OPERATOR: restart the engine to land the promotion** (hard-refresh;
the SW bump then self-purges old caches). First post-restart check:
`/` shows the React app, `/v3` bounces to `/`, `/config` still renders.

**Standing carry-forwards (unchanged, don't lose)**: `no-undef` lint
dev-dep · `entry_ms` rename + P1 stub · news ~16 s cadence ·
`account_snapshots` migration + R1b per-account mint · the intermittent
aiosqlite teardown warning · REST-fill gap masking + weight_tracker
reconcile window/lock (filed 07-30) · Finnhub key rotation · SOL
`MANUAL_INTERVENTION` question · cold-restart time-to-first-price
measurement.

**(superseded, kept for context) — the pre-retirement close below:**
**Date**: 2026-07-30 (**MERIDIAN v3.0 — E2E program COMPLETE Phases 0–7 AND the carry-forward pass is DONE: all five P5-R residuals + LOW-001 + the Finnhub log leak fixed, the PID guard built, the harness debt cleared — 7 commits on top of the acceptance wrap. NEXT PROGRAM = THE JINJA RETIREMENT (operator-gated).**)
**Branch**: **`v3.0/e2e-debug`** — pushed through the P7 wrap (`5739dfd`); the 7 carry-forward commits push at session close (see the 07-30 block).
**Tests**: **4608 passed / 7 skipped / 3 deselected** (post-carry-forward gate, 2026-07-30; first run flaked ONCE on `test_periodic_loop_survives_reconcile_exception` — a 50 ms-budget timing test under live-engine machine load, passed solo AND on the identical full re-run — recorded, not chased). ALWAYS run SOLO on the **`.venv`** interpreter (user-site Python lacks `pytest-timeout` → drops the 30 s guardrail). NEVER run the gate concurrently with live-engine driving (conftest tripwire + weight budget).
**Bundle**: **`30e626377e`** (was `929f95bffc`; the FILLS chrome dot ships in it) — hard-refresh after restart.
**Engine**: RUNNING; boot `22:11:14 07-29`. **The running engine PREDATES every 07-30 fix** (`30cf1ad` + the 7 carry-forward commits) — **RESTART at the operator's convenience** to land: the P7-001 settings upsert, the P5-R1 close-row backstop, the truthful user-WS flag + FILLS dot + user_ws door, the monitoring binding + new checks, the boot-priority tiering, the PID guard (writes `data/engine.pid` on first post-fix boot), and the httpx token-log silence. **w32time FIXED 2026-07-30 (OBS-002 CLOSED)**: operator set `StartType=Automatic` (service Running, source cloudflare, corrections ≤1 ms while running — root cause was Manual start + workgroup trigger never firing, so every manual sync was a one-shot against a ~+2.5 s/day free-running crystal; full diagnosis in the 07-30 close block). Restart discipline: **one restart, then wait**.

## ▶ SESSION CLOSE 2026-07-30 (second block) — CARRY-FORWARDS ALL FIXED

Operator directive: "push then fix the still open bugs (carry forwards out
of this program)". Pushed `30cf1ad`+`5739dfd`, then fixed the whole fixable
list — one investigated commit per finding, three parallel read-only
investigation agents up front, mechanisms verified at the cited lines
before every fix (3 of 5 filings needed mechanism correction):

| Commit | Fix |
|---|---|
| `c9b1640` | **P5-R4** — unmeasured excursions emit NULL at the JSON boundary (the filed "write NULL to storage" hits the NOT NULL schema; only the React lane lied) |
| `19aa8b0` | **P5-R1 (HIGH)** — `build_final_close_row` was DEAD CODE (closed_positions had exactly one producer: the WS fill path); now wired to `CH_TRADE_CLOSED` (+`position_id` in the payload) with a bounded REST fill fetch first (the refresh loop only fetches fills for OPEN positions) |
| `3f6a220` | **P5-R2+R3** — `/api/state.user_ws` door + FILLS dot (bundle `30e626377e`) + THREE unfiled defects: clean-close fall-through (`connected` stuck True on code-1000 — the lying flag), 15-attempt permanent surrender (now hands off to the persistent retry loop), anonymous MonitoringService (events door returned [] forever); ws_stale is an emit/resolve event + new critical `user_ws_down` check |
| `0f0cd25` | **P5-R5** — calc-symbol exempt from the 30 s cache eviction (the unnamed compounding cause) + 3 boot backfills tiered background + the fill-sync urgent leak plugged. Priority table untouched — 95-101% stays listen-key-only |
| `2c6de73` | **LOW-001** — linkage resolvers default to the legacy store |
| `ea0db81` | **PID guard** (refuses double-launch; Windows trap: `os.kill(pid,0)` = TerminateProcess — the probe would have KILLED the engine; OpenProcess instead) + **Finnhub token** (httpx/httpcore → WARNING; old logs carry tokens until rotation — rotating the key is the operator complement) |
| `a8b5939` | **Harness debt** — sandbox pid rewrite · X1 delta oracle (unverified until next T run) · provision `e2e:` seed exemption; A1 budget was ALREADY raised in `918c6f4` (stale OPEN entry corrected) |

**Dispositions written**: phase-5 ledger (Phase-7 disposition section),
phase-6 ledger (A1/X1 row), acceptance report (carry-forward list closed,
2 NEW watch items filed: REST-fill gap masking + weight_tracker reconcile
window/lock). **Remaining open = operator-side only**: OBS-001 (watch;
the PID guard removes the double-launch class), the SOL
`MANUAL_INTERVENTION` question, Finnhub key rotation, and a cold-restart
time-to-first-price measurement (P5-R5 verification — the e2e specs poll
past the starvation window by design). ~~OBS-002~~ **CLOSED 2026-07-30**:
root-caused (Manual start type + domain-join-only trigger on a workgroup
machine = one-shot syncs against a ~+30 ppm crystal; corrections while
running were always ≤1 ms; the "Sync now button is clickable again" was a
UI misread, verified by live measurement +122 ms post-sync) and FIXED by
the operator (`StartType=Automatic`, verified Running).

**Post-restart addendum (`93ad0b5`)**: the operator's first boot on the
new build surfaced TWO more defects, both fixed same-session: (1) FALSE
CLOCK criticals — the offset math midpointed across the weight-tracker's
in-path throttle sleep (3465 ms throttle → −1747 ms "drift" on a clock
reading −27 ms; samples >1500 ms elapsed are now DISCARDED); the running
engine predates the fix, so a throttle-window banner can still flash until
the NEXT restart — it self-clears on the next clean sample and is NOT the
OS clock. (2) The SECOND Finnhub token leak path — httpx exception
messages embed the full URL; news_fetcher's four error sites now scrub
`token=***`. The Finnhub calendar 403 is most likely a premium-endpoint
plan restriction, not a dead key — but the token has now been pasted in a
terminal too: **rotation is due**.

**NEXT PROGRAM = JINJA RETIREMENT** — unchanged, operator-gated; recipe +
constraints in the 07-25 block (§ "v3.0 RENAME SHIPPED · RETIREMENT
DEFERRED"). Release-hygiene version bump at program close.

## ▶ SESSION CLOSE 2026-07-30 — PHASE 7 COMPLETE · gate PASSED · retirement unblocked

**The acceptance report is the deliverable**:
`docs/audits/2026-07-29-v3.0-e2e-phase7-acceptance.md` — counts by phase,
bundle hash, monkey seed (`20260729`), mutation ledger, the (now 9-) defect
table, the false-positive ledger, and the manifest-drift review. Read IT
first; this block is the session index.

| Re-run | Result |
|---|---|
| selftest · smoke | 4/4 · 10/10 |
| crawl (drift pin) | 10/10 after a REVIEWED manifest merge — 522→**528** controls, 11 flagged `dataDependent` (all 6 added + 5 vanished were live-data-cardinality, mechanisms verified at source; NO UI regression) |
| sweep | 102/102, 406/466 acted, findings = 21 INFO (Primitives demo toasts) |
| perm + monkey | 10/10 · 9/9 (1,080 steps, seed 20260729, breadcrumbed) |
| sandbox | first run 9/11 → **E2E-P7-001 found**; after fix **11/11 — first fully-green sandbox suite in program history** |
| pytest | 4565/7/3 green |

**★ E2E-P7-001 (HIGH, fixed `30cf1ad`, 9 pins)**: settings writes fail for
EVERY account added after the first — `add_account` never creates an
`account_settings` row (migration 001 seeds `LIMIT 1`), the writer was
UPDATE-only, and post-split `_resolve_db_path` had no legacy fallback for
accounts added after the split (nothing mints a per-account DB until the
deferred R1b). Loud half: apply-preset 500s (the exact config-2 workflow).
Silent half: `routes_accounts`' settings writes are except-pass → no-op.
Fix: writer upserts the row (table defaults == dataclass defaults, pinned)
iff the account exists + resolver falls back to legacy iff the account
exists there. Dormant on live today (single account).

**★★ Process finding — phase 4 closed with 2 undispositioned reds** (run
`4-20260728-1800` was 9/2; the preset red was P7-001, the close-reason red a
spec locator wrong since inception — `/^Intervention$/` vs the compound
title+description button text). Both fixed in `30cf1ad`; the phase-4 ledger
carries a Phase-7 correction section. **Rule going forward: a phase ledger
states the closing run's counts and dispositions every red.**

**Harness debt (filed in the report, not fixed)**: `provision_test_env.py`
refuses sandbox re-provision over `e2e:`-marked seed rows (safe-but-noisy;
candidate: exempt the marker) · m2's engine relaunch doesn't rewrite
`.sandbox.pid` so `sandbox-down` misses it (swept manually twice — check
:8010 listeners) · A1 linked-position budget + X1 row-count-delta oracle
(carried from phase 6).

**Sandbox state**: torn down, :8010 free; worktree `E:\tmp\qe-sandbox` at
`30cf1ad`, data freshly provisioned+seeded (reusable; re-seed before any m1
re-run — the suite consumes seeds).

### ▶ NEXT = JINJA RETIREMENT (operator-gated — do not start unprompted)
The gate condition is met. Everything needed is in the 07-25 block below
(§ "v3.0 RENAME SHIPPED · RETIREMENT DEFERRED"): `base.html` + `/config`
CANNOT retire, all 50 `/fragments/*` + `POST /models` SURVIVE, cost ≈ 126
pins across 25 files, JS-drift grep after, Release-hygiene version bump at
program close. Standing carry-forwards unchanged: Finnhub-token log leak ·
news ~16 s cadence · `account_snapshots` migration (now joined by the R1b
per-account-DB mint for new accounts — P7-001's resolver fallback is the
interim shape) · `entry_ms` rename · `no-undef` lint. Operator actions
pending: **push the 2 local commits** · w32time fix · restart engine at
convenience (lands `30cf1ad`).

## ▶ SESSION CLOSE 2026-07-29 — E2E program Phases 0–6 COMPLETE · 8 defects fixed · Phase 7 next

One continuous program (2026-07-28 → 07-29), operator-gated per phase. Harness
lives in **top-level `e2e/`** (own package.json — `frontend/` stays BUILD-ONLY);
4 Playwright projects (`live-r` read-only :8000 · `sandbox-w` :8010 · `live-m`
approved mutations · `trade-t` headed+traced, operator overlay). Run from `e2e/`:
`$env:E2E_CONFIRM_LIVE='1'; npx playwright test --project=<proj> [-g "<id>"]`.

| Phase | Commit | Result |
|---|---|---|
| 0 skeleton | `79280b8` | collector/guard/oracles, selftests 4/4 |
| 1 manifest | `7cf4e5c` | 522 controls classified, drift-pinned (UI-surface regression pin) |
| 2 sweep | `0895898`+`abc6d34` | CLEAN GATE 100/100 panes, 409/460 acted, 0 errors |
| 3 perm+monkey | `d69ad31` | 240 orderings + 1080 seeded monkey steps, 0 app findings |
| 4 sandbox | `5587c6f` | full excluded-mutation list + degraded tiers on :8010 |
| 5 live-mut | `b2b9436`..`bd522c0` | 3/3, 0 findings, all cleanups verified |
| 6 trade | `90365fb`..`831b745` | **all 8 scenarios complete** (H1 · H1b · L1 · L2 · A1 · A2 · X1 · X2) |

**★ THE 8 ENGINE DEFECTS (all fixed, pinned, live-verified, ledgered):**

| ID | Sev | Commit | One-liner |
|---|---|---|---|
| E2E-P2-001 | CRIT | `0895898` | `all_time` → 500 on every analytics door (negative epoch clamp) + silent stats |
| E2E-P4-001 | HIGH | `5587c6f` | Apply Preset NEVER worked in v3 — unawaited `list_accounts()` coroutine |
| E2E-P5-001 | CRIT | `7e6cf62` | user-data WS died at boot, never retried → fill pipeline dead 2 days (operator's SNXX report); + per-symbol backfill SNXX 16 / SNDK 10 rows, 0 deleted |
| E2E-P5-002 | MED | `b2b9436` | countdown chip reported LINKABLE for cancelled/terminal calcs |
| E2E-P6-001 | HIGH | `e48ce0b` | order-form (conditional) TP/SL NEVER linked — algo snapshot path skipped parent re-enrich; live-proven 6/6 after fix |
| E2E-P6-002 | HIGH | `918c6f4` | manual-link candidates EMPTY for every MARKET order (loose finder read `price`=0, never `avg_fill_price`; strict matcher knew better) — the recovery path was unusable for the most common entry type |
| E2E-P6-003 | MED | `8eaa196` | link/unplanned confirm was a native `window.confirm` (off-standard vs ModelDialog, and any automation layer eats it — operator: "dialog glitches ver fast"); + display half of P6-002 (`MARKET @ 0.000000` at 3 sites → `_lkEntryPx`) |
| E2E-P6-004 | MED | `7c0926f` | boot bound the fill stream LAST — after trade history, 90-day recovery, per-position OHLCV — so the listen key lost to the engine's own boot burst (live: 106→117 %, `urgent` shed). Now binds right after positions load; verified boot: 0 failures |

**★★ Phase 6 proved the linkage machinery at the DATA layer**, not just the UI:
auto-link 6/6 (repeatedly, incl. both hedge legs to their own side's calc);
**manual link proven MANUAL** — L2's `calc_match_audit` reads 4/6 with
`winning=0` on every row (tp 75.40 vs 75.42, sl 71.80 vs 71.82), so the strict
matcher REFUSED it and `link_status=LINKED` could only come from the operator's
click; near-miss → `NEEDS_MANUAL_REVIEW`; no-calc → `UNPLANNED`; SL-removal →
sticky `tpsl_amended=2` into History; partial close → ONE closed row PER closing
order; hedge amendment isolated to its own leg; close tail →
`completed_via_position` + closing fill `source=binance_ws`.

**★★★ FALSE-POSITIVE / SELF-CORRECTION LEDGER (recorded in the phase-6 ledger —
do not re-file):**
- **"Zombie engine" diagnosis WRONG**: two `uvicorn main:app` processes are the
  SUPERVISOR + its worker (one app process per launch — check `ParentProcessId`
  before calling anything a duplicate). The real weight-saturation cause was
  restart storms.
- **Monitor false "WS BOUND"**: grep matched a stale success line from an
  earlier boot. Time-scope every log assertion (scratch `boot_verify.py` shape:
  isolate the LATEST boot via last "EventBus: in-process mode active").
- **Calc-scoped oracle**: P6's first "confirmed finding" was my ticker-scoped
  `calc-row-absent` oracle misreading an ordinary same-ticker re-calc; oracles
  now key on `calc_id`.
- **Harness manufactured 3 operator-adjudicated misses** (budgets too tight for
  the 15 s algo-sweep hop / first-paint): budgets raised, row-wait added.
- **Blind calc re-click MUTATES**: a manual submit INSERTS `pre_trade_log` and
  SUPERSEDES the prior calc — the retry left 3 chained calcs on the LIVE
  account before the guard (`storedCalcId` check) was added.
- Open harness debt (marked OPEN in the ledger): raise A1's linked-position
  budget; make X1's `closed-row-present` assert a row-count DELTA.

**Filed, still open**: P5-R1 (REST fill path builds no close rows) · P5-R2 (no
door exposes user-data WS state) · P5-R3 (WS-stale alert unactioned) · P5-R4
(rebuild writes 0.0 not NULL excursions) · P5-R5 (post-restart weight
saturation starves Pre-Trade sizing — largely mitigated by P6-004) · LOW-001
(stale per-account default in `find_candidate_calcs`) · OBS-001 (two silent
engine stops, still unexplained — the "dual instance" theory is DISPROVEN) ·
OBS-002 (w32time stopped, fix is operator-elevated) · Finnhub token cleartext
in `risk_engine.jsonl` (pre-existing) · **not implemented, recommended**:
startup singleton/PID guard (nothing stops a second engine instance today).
Open question for the operator: SOL close on 07-29 recorded
`MANUAL_INTERVENTION` — did you set that via the modal, or is it a defect?
Operator's 4USDT + ENAUSDT positions are DELIBERATE swing tests — not residue.

### ▶ NEXT SESSION = PHASE 7 (the acceptance gate)
1. Engine running, single instance, bundle `929f95bffc` (hard-refresh).
2. Clean re-run vs live: `--project=live-r` smoke + sweep + perm (+ monkey,
   seed recorded). Then sandbox re-run per runbook (worktree OUTSIDE the repo,
   shadow `.env`, `provision_test_env.py`, `seed-sandbox.py`, :8010, never
   `--reload`).
3. Gate: **zero new CRIT/HIGH**. Consolidated acceptance report →
   `docs/audits/` (counts by phase, bundle hash, monkey seed, mutation ledger,
   the 8-defect table, the false-positive ledger).
4. That report is the **live-acceptance evidence → Jinja retirement opens**
   (retirement → promotion `/v3`→`/` → carry-forwards, per the deferred plan in
   the 07-26 block below). Standing carry-forwards untouched: Finnhub-token log
   leak, news cadence, account_snapshots migration, entry_ms rename, no-undef
   lint.

## ▶ SESSION CLOSE 2026-07-26 — audit fully disposed · 3 UI standards · rename · retirement deferred

**12 commits, all pushed.** In order:

| Commit | What |
|---|---|
| `5a58331` | excursion cleanup APPLIED (67 rows) — **after fixing a self-undoing defect in the tool** |
| `e92e8be` | Meridian design-consistency audit ledger — 34 confirmed, 0 CRIT/HIGH |
| `414aace` | the **5 MED** closed (2 materially corrected by an adversarial fix-review) |
| `98a93f7` | **DataList tools sweep** — search+sort+filter on every pane (24 sites, 21 fixed) |
| `a39bc58` | **no-data standard** — dashed frame inset 2× the pane gap, 30 sites |
| `f99faf9` | **`HeatBar` primitive** — the excursion cell's 3 channels restored; both standards written into DESIGN.md |
| `83b3d2c` | LOW/NIT slice 1 — History + Linkage (10) |
| `c9da97a` | LOW/NIT slice 2 — analytics · dashboard · models · pretrade · chrome (14) |
| `c57cab7` | LOW/NIT slice 3 — the final five (backend-touching). **ALL 29 CLOSED** |
| `cd4145f` | rename → **MERIDIAN v3.0**; retirement built, measured, REVERTED |
| `a033889` | un-abbreviate the name; news ticker at a constant, readable speed |

**★ THE AUDIT IS FULLY DISPOSED: 34 confirmed findings — 5 MED + 29 LOW/NIT — all
closed or explicitly refuted.** The ledger
(`docs/audits/2026-07-25-v3.0-meridian-design-consistency-audit.md`) carries
per-finding detail, a Disposition section per slice, and a **Refuted** section
recording the false-positive classes so they are not re-filed.

**★★ THE LESSON OF THIS SESSION — distrust a comment that explains an omission.**
FOUR in-source rationales proved FALSE, each one having justified dropping
something real:
1. `"no real per-message latency source exists"` (nav-and-data) — `ws_manager`
   stamps one on every market frame.
2. `"no engine feed"` for the RegimeBadge tone (pages-pretrade) — `NAV_REGIME_TONE`
   ships in the build and the workspace strip already renders a live badge from it.
3. `"exit PnL already has its own NET column"` (the excursion cell) — the tick's
   job is to place the close INSIDE the range, not restate a number.
4. `"a stable category-size indicator"` (History tab counts) — the active slot was
   never stable, so the badge row meant two things at once.
See [[feedback-verify-the-audits-cited-source]]; the same discipline caught two
WRONG fixes of my own before commit (below).

**★★★ TWO OF MY OWN FIXES WERE WRONG AND CAUGHT BY REVIEW, NOT BY TESTS.** Both
passed a green gate because each was faithful to the source it read and wrong
about WHICH source to read:
- **`shell-chrome-3`**: wired the feed dot to `ws.connected`, which is the
  **USER-DATA** socket (`ws_manager` writes it only in `_user_data_loop`; the
  market loop only logs), and `ws.last_update` is floored by the 30 s REST
  refresh. The dot would have lied BOTH ways. Now backed by real
  `WSStatus.market_connected` / `market_last_update` / `market_latency_ms`.
- **`config-1`**: "blank = keep stored" let one half of a warn/limit pair be
  cleared, which SKIPS `validate_params`' cross-check (it gates on both keys
  being present and validates the SUPPLIED subset) → `warn >= limit` behind a
  200 "Saved.". Now posted pairwise + a client pre-check.

**Verification shape that earned its keep**: rendering the SHIPPED bundle in a
browser and MEASURING, rather than eyeballing. It proved the no-data inset is
8/8/8/8 across three body paddings, that `HeatBar` draws all three channels
across 7 data shapes, and that the ticker holds ~52 px/s at 3/8/40 items. Recipe
lives in `scratchpad/` (`scope.mjs` vm identifier check + the HTML harnesses).

### The three UI standards (now in `frontend/DESIGN.md` § Data display)
1. **DataList tools** — every pane offers search + sort + filter. The gaps were
   almost never `tools={false}`: they were columns whose `key` NO ROW CARRIES
   (render ignores the key, so the header sorts on `undefined` and the column
   can never facet — 18 of them), and `showFilter` true with zero derivable
   facets. Fixes are `sortVal`/`filterVal`/`searchVal` + forced facets.
   ONE primitive change: the `distinct < 2` bail now runs only when NOT forced,
   so a declared facet survives a homogeneous table.
2. **No-data** — dashed frame `inset: calc(var(--qe-pane-gap) * 2)`, surrounding
   the whole pane body, content centred. ABSOLUTE, not margin (body padding
   varies per call site); the rule is SCOPED to `.qe-pane-body` so modal/inline
   uses stay in flow; `fill` is opt-in so a zero-state beside siblings cannot
   cover them. **Never fill the DataList "no matches" state** — the sticky
   toolbar above it is the only way to clear the filter.
3. **Excursion** — `HeatBar` / `HeatBarLabelled`, three load-bearing channels
   (centre ENTRY rule · MAE/MFE extents · EXIT tick). Truthfulness: both values
   null → `—`, never a zero bar; `pnl` null → omit the tick.

### Operator decisions taken this session
- **#7 Calendar-PnL cell ratio → KEEP `3 / 2`** (landscape, as shipped); the
  "unconfirmed" flag is dropped. Recorded but NOT acted on: the ratio treats a
  symptom — the cells are flat because our grid carries `alignContent: 'start'`
  (pages-analytics.jsx) which the design does not.
- **Desktop notifications → keep plan §7's deferral**, make the control honest
  (rendered disabled) rather than wiring it.
- **Retirement → "rename only, hold the promotion."**


## ▶ SESSION CLOSE 2026-07-25 — operator bug-list pass (8 bugs) + 2 design-parity rounds

The operator live-drove `/v3` and reported 8 bugs, then twice more caught
design mismatches against Claude-design screenshots. All are shipped. **Every
fix was verified SOLO — subagents were not enabled this session, so there are
NO independent-agent audits on any of these commits** (a deliberate,
operator-known deviation from the house cycle; each commit says so).

| # | Bug | Commit | Mechanism (investigated, not assumed) |
|---|---|---|---|
| 1 | Equity curve flips to $278 | `23d04de` | Binance adapter mapped `totalWalletBalance` (wallet, EXCLUDES uPnL) onto `total_equity`; every REST poll knocked equity down by exactly the open uPnL, the next mark tick restored it. Same class as **FE-9**, on the REST path. |
| — | phantom rows already persisted | `ff368be` | cleanup tool; **operator APPLIED it** — 4569 rows corrected, then I cleared the `min_total_equity` ratchet latch. |
| 2 | No search/sort/filter in DataLists | `f5b5f93`+`9125d6e` | 16 sites forced `tools={false}`; lifting them wasn't enough — `DL_AUTO_MIN=5` was tuned to the design's DENSE mock data, so sparse live tables stayed dark. |
| 3 | No daily-PnL bar | — | NOT A BUG — engine predated wave-2 Python. |
| 4 | Log says "snapshot 82.19" | `4ce6516` | split-migration residue: writer → legacy `risk_engine.db` (current), reader → `per_account/*.db` (frozen at 2026-04-28). |
| 5 | Manual-link ≠ design | `4b21db6` | backend never SELECTed `quantity/operator_id/client_order_id`; candidates carried no model/R/tags. |
| 6 | Cancel-calc dialog undesigned | `c39119f` | `ModelDialog` hoisted to primitives; replaced `window.confirm`. |
| 7 | Calendar cells flat | `c39119f` | `aspect-ratio: 3/2` (interpreted 2:3 as height:width — **flagged, unconfirmed**). |
| 8 | SPCX MAE −284/−270 never lost | `7617b73`+`74e687f` | `exchange_history` stores excursions PER income-row; reconciler assigns ONE full-position hi/lo to every partial scaled by qty. `calc_mfe_mae`'s own docstring had flagged this over-reporting as "needs separate investigation". |
| + | OS clock drift | `88ce716`·`a1390a1`·`c871c18` | "synced" came from the UNSIGNED `/fapi/v1/time`; SIGNED reads failed **-1021** (>1000ms ahead, recvWindow only tolerates being LATE). |

**Design-parity rounds** (operator screenshots as benchmark): `0988882`
REASON-resolver fields (Hold / Closed at / Detected / P&L% / closed-time /
Later) · `7fb64fc` linkage inbox 3-line strip (side badge, timestamp,
`#order·age`, context line) — all were P8-era trims, all data already in the
payload · `5251d0d` history tab-counts on INACTIVE tabs + SIDE/REASON facets +
default page 75→50.

**★ THE 3 P8 DECISION POINTS ARE ANSWERED** (were blocking retirement):
1. **Primitives in nav** → **KEEP the DEV chip** ("still in development phase").
2. **`tools={false}` convention** → **LIFTED** (bug #2 answered it); History
   page size 25/50/**75**/100, default **50**.
3. **WS account-namespacing** → **DEFERRED** (operator: "defer first").

**★★ THE INCONSISTENCY AUDIT IS DONE (2026-07-25) — ledger
`docs/audits/2026-07-25-v3.0-meridian-design-consistency-audit.md`.**
14 agents (10 surface finders → dedupe barrier → 4 adversarial verifiers,
run `wf_e6568dce-4d1`, 0 errors/0 empty). **34 confirmed: 0 CRIT, 0 HIGH,
5 MED, 21 LOW, 8 NIT; 5 refuted; 17 of 34 severities corrected by the verify
pass** (treat finder output as a draft — that ratio is the calibration record).
The port is materially faithful: no missing page/tab/pane anywhere, and 6 of 10
surfaces carry nothing above LOW (`primitives` byte-clean, `regime` 0 confirmed).
Drift is concentrated in dropped derived readouts + a few lost affordances.
**★ THE 5 MED ARE FIXED + PUSHED** (gate 4369/7/3, bundle `2ba081894e`; pins
`tests/test_meridian_med_fixes.py` + 1 `/api/state` contract in test_routes):
Config ratios editable again (posted PAIRWISE) · History TRIGGER column +
PRICE/AVG-FILL blank on 0 · Pre-Trade foot on a real `netPx` pipe · Desktop
switch DISABLED ("deferred, plan §7" — **operator decision: keep the deferral,
make the control honest**, via a new additive `disabled` prop on `Switch`) ·
`/api/state.exchange_ws` + FEED dot / LAT cell / footer dot.
**LOW + NIT (29) REMAIN OPEN — operator picks scope.** The ledger's Refuted
section records the false-positive classes; don't re-file them.

**★★ READ THE LEDGER'S DISPOSITION BEFORE TRUSTING ANY FINDING TEXT.** A 5-lens
fix-review returned 3 DO-NOT-SHIP / 24 findings and materially corrected TWO of
the five fixes — both invisible to a green gate:
- **shell-chrome-3 named the WRONG SOURCE.** `app_state.ws_status.connected` is
  the **user-data** socket (ws_manager writes it only in `_user_data_loop`
  :529/:621 + `stop()`; the market loop :755/:795 only logs), and `last_update`
  is stamped by BOTH loops AND floored by the 30 s REST refresh. As first built
  the FEED dot lied BOTH ways. Now backed by real market-socket tracking:
  `WSStatus.market_connected` / `market_last_update` / `market_latency_ms` +
  `market_seconds_since_update`. **Symptom real, mechanism wrong** —
  audit-impact-imprecision, this time inside an audit finding.
- **config-1's first fix could write an INVERTED risk config.**
  `validate_params` gates warn<limit on BOTH keys present and validates the
  SUPPLIED subset, so "blank = keep" skipped the check → `warn >= limit` behind a
  200 "Saved.". The weekly pair is consumed unconditionally and the limit branch
  is first, so an inversion deletes the warning tier. Now pairwise + a
  client-side pre-check.
Also folded: fabricated `0ms` latency (legacy Jinja falsy guard not carried
over) · `_navFeed` ignoring `ch.stateErr` · REST-fallback showing a frozen
latency as current · Pre-Trade 200-with-no-price painting health over a latched
stale sizing price · **revert of this pass's own TRIGGER tp/sl fallback** (it
printed an entry order's TP PLAN level as its trigger and desynced the column
from its sort). Copy corrections: the DD ratios are read ONLY in the rolling-DD
`except` fallback, and `PRESET_PARAMS` carries no ratios.

**▶ (superseded, kept for context) NEXT SESSION = INCONSISTENCY AUDIT vs the Meridian standalone.**
The operator downloaded a **fully self-contained** design export, now committed
at **`docs/design/meridian_v3/Meridian v3.0 (standalone).html`** (2.1 MB).
It is NOT redundant with the existing `Meridian v3.0.html` (9.3 KB) — that one
is a *loader* needing CDN React + Google Fonts + localhost HTTP; the standalone
inlines React/ReactDOM/ECharts/GridStack/fonts/all 20 modules and **runs
offline by double-click**. Charge: audit the BUILT `/v3` frontend against it
and fix the drift.

**★ VERIFIED THIS SESSION — the benchmark and the in-repo reference AGREE.**
I extracted all 34 manifest entries and diffed the 20 app modules against
`docs/design/meridian_v3/v25/src/*.jsx`: **16 byte-identical, 4 differing ONLY
by unicode escaping** (`·`→`·`, `—`→`—`, `×`→`×`). So the
vendored reference is CURRENT and trustworthy — **the operator's repeated
mismatches were genuine PORT gaps in our React implementation, never a stale
reference.** Practical consequence: audit **source-to-source against
`v25/src/*.jsx`** (fast, greppable) and use the standalone as the *rendered*
oracle. Extraction recipe if needed again:
```python
# sources live gzip+base64 inside <script type="__bundler/manifest">
import re, json, base64, gzip
s = open("docs/design/meridian_v3/Meridian v3.0 (standalone).html", encoding="utf-8", errors="replace").read()
man = json.loads(re.search(r'<script type="__bundler/manifest">(.*?)</script>', s, re.S).group(1).strip())
for k, v in man.items():
    raw = base64.b64decode(v["data"])
    if v.get("compressed"): raw = gzip.decompress(raw)   # skip b"wOF2" (fonts) + the 5 vendor blobs
```
Audit-scope warning: the design is **mock-data-shaped** (dense tables, fabricated
values). Judge STRUCTURE/affordances, not the numbers — several "missing" design
elements are deliberately-dropped fabrications (P8 wave 1 killed that class).
Named still-open deviations to NOT re-file as new: History search sits ABOVE the
tabs (server-paged — a client box would miss other pages); "Detected" shows the
real `exit_reason`, not the mock's "opposite-side mkt"; models-report keeps
`tools={false}` (verbatim-capture fidelity).

## ▶ DATALIST TOOLS SWEEP (2026-07-25, operator directive)

**Directive**: every pane whose main component is a DataList must offer all
three tools — SEARCH, SORT, FILTER. Inventory = 10 agents, one per file:
**24 call sites, 21 with a gap.** All closed. Bundle `e834aba062`.

**★ The gaps were almost never `tools={false}`.** Three distinct shapes:
1. **`tools={false}` / `{search:false}`** — the obvious one, and the RAREST.
2. **A column whose `key` NO ROW CARRIES.** `render()` ignores the key so the
   cell looks perfect, but `presentKeys` AND `_dlDeriveFacets` both skip the
   column: the header sorts on `undefined` and it can never facet. Found on
   `mer` · `impact` · `tpsl` · `dev` · `cd` · `vix` · `hy` · `rvol` ·
   `funding` · `status` · `plan` · `pct` · `mr` · `heat` · `summary` · `exec` ·
   `file` · `window`. Fix = `sortVal`/`filterVal`/`searchVal`, the primitive's
   documented escape hatch.
3. **`showFilter` TRUE but ZERO facets derived** — `_dlDeriveFacets`
   independently rejects a column when it is ≥70% numeric, has <2 distinct
   values, >6 distinct, high cardinality, or any value >16 chars. Fix = a
   FORCED facet on a genuinely categorical column, bucketing a number through
   `filterVal` where needed (WIN/LOSS/FLAT, PAY/EARN, UP/DOWN).

**One PRIMITIVE change**: the `distinct < 2` bail sat BEFORE the `forced`
branch, so a forced facet could never render on a homogeneous table — i.e. the
filter vanished exactly when the table was small (one open position, one
regime), which is the normal live shape. Now `distinct.length < 2 && !forced`.
AUTO still bails; only an explicitly-declared facet survives.

**Also corrected while in there** (display/sort disagreements): funding `pays`
faceted as EARN on rate-null rows while the cell rendered '—'; Per-Fill `LINK`
sorted raw `link_status` while rendering a derived 5-bucket label; dashboard
`PnL`/`AGE` sorted on fields the cells don't use; `exit_reason` sorted the raw
enum while rendering the LP label.

**Two prior rationales were overridden by the directive, both deliberately:**
History's `search:false` (paging/search are server-side — the two are now
COMPLEMENTARY: the box above the tabs spans all pages, the DataList box refines
the page in view) and models-report `tools={false}` (verbatim-capture fidelity —
the capture still renders in workbook order by DEFAULT; sort is user-initiated
and non-destructive).

Pins: `tests/test_datalist_tools_completeness.py` (45) — including a
brace-balanced column extractor, because a naive `.*?\},\n` regex stops at the
inner `filter: {...}` object and makes the pin vacuous. Runtime scope verified
by evaluating the emitted bundle in a stubbed vm (13 cross-module identifiers
resolve) — the esbuild guard is parse-only.

## ▶ NO-DATA STANDARD (2026-07-25, operator directive)

**Directive**: the dashed frame sits **2× the standard inter-pane space** inside
the pane wall, surrounds the **entire pane body**, content centred both axes.

**Geometry**: the standard inter-pane space IS `--qe-pane-gap` (GridStack insets
each tile by GAP/2 per edge ⇒ the gap BETWEEN panes is the full token). So the
offset is `calc(var(--qe-pane-gap) * 2)` = 8px.

**Why absolute and NOT a margin** (the load-bearing decision): the pane body
carries its own padding — `'5px 7px'` by default, overridden per call site
(`padding:0` is common, 47 `bodyStyle` overrides exist). A margin would land at a
DIFFERENT offset on every pane, which is the exact inconsistency the directive
removes. An absolutely-positioned box resolves `inset` against its ancestor's
PADDING BOX, whose edge is the pane's inner border ⇒ exactly 2× the gap
regardless of body padding. **Measured in a real browser before commit: 8/8/8/8
uniform across default padding, `padding:0`, AND `padding:18px 24px`.**

**Two guards, both deliberate and both pinned:**
1. The CSS selector REQUIRES a `.qe-pane-body` ancestor
   (`.qe-pane-body .qe-empty.fill`). Without it an EmptyState inside a modal
   would position against the dialog panel and cover its head + footer. With it,
   modal/inbox/inline uses keep normal flow AUTOMATICALLY.
2. `fill` is **opt-in** (`EmptyState fill`). A zero-state rendered ALONGSIDE
   siblings in a pane body (a list's "none yet" notice above the list) must stay
   in flow or it would cover them.

**Applied at 30 sites** = 2 central + 28 page-level. The 2 central ones carry
most of the app: `DataList`'s truly-empty short-circuit (ONE line = the no-data
state of **21 table panes**) and `PaneErrorBoundary`.

**★ ONE HARD EXCLUSION — do not "finish the job" by adding fill here:** the
DataList **filtered-to-zero** branch (`.qe-dl-empty`). Rows exist but the
search/facets excluded them all, so the sticky toolbar is STILL rendered above
and is the only way out of that state. An absolute inset box would paint over it
and trap the operator with no way to clear the filter. Pinned by
`test_filtered_to_zero_does_NOT_fill`.

Inventory that drove this: 8 agents, **154 no-data treatments** (68 EmptyState ·
21 DataList-emptyMsg · 46 ad-hoc · 19 spinner-only), 55 verified absolute-fill
SAFE, 99 unsafe — which is why a blanket rule was rejected. Spinner-only sites
were left alone: a loading state is not a no-data state.

**Both standards are now WRITTEN DOWN in `frontend/DESIGN.md` § Data display**
(the operator asked "have you put that principle in primitives?" — the mechanism
was in primitives.jsx/tokens.css but the RULE was not documented; per
[[feedback-cross-page-ui-convention-drift]] a shared-primitive usage rule has to
live in DESIGN.md once or it drifts).

## ▶ EXCURSION (MFE/MAE) STANDARD — `HeatBar` primitive (2026-07-25)

The built heat cell differed materially from the design and is now ONE
primitive, `HeatBar` (+ `HeatBarLabelled` for detail panes), ported from the
design's `HistHeat` (`v25/src/pages.jsx:56-73`).

**It has THREE load-bearing channels; the build shipped only ONE:**
1. centre **ENTRY rule** — the datum both excursions are measured from. Without
   it the two halves float and the cell says nothing about direction.
2. red extent LEFT = **MAE**, green extent RIGHT = **MFE**, scaled to
   `max(|mfe|,|mae|,|pnl|)` so the tick can never fall outside the box.
3. bright **EXIT tick** — where the close landed INSIDE that range. This turns
   "how far it swung" into "…and how much of it we kept"; it is NOT a
   restatement of the NET column (the old local `HistHeat` header claimed it was,
   which is why the channel had been dropped).

The old implementation also used detached half-bars with a 2px gap, no border,
height 7 vs 12, opacity 0.75 vs 0.42, and no minimum extent. Column label
restored to the design's `MAE ◂ HEAT ▸ MFE`.

**Our truthfulness rules on top of the mock-fed design** (keep them): `mfe` AND
`mae` both null = NOT MEASURED → `—`, never a zero-width bar (the P8 audit's F2
class — a `||0` coercion fabricates certainty on un-backfilled rows); `pnl` null
→ the exit tick is OMITTED, not parked at centre, which would assert a
break-even close that was never measured.

Verified by rendering the SHIPPED bundle's own `HeatBar` in a real browser with
vendored React across 7 shapes: every drawn bar carries the entry rule, the tick
appears iff `pnl` is present, and the unmeasured row renders a dash.
`dash-tiled`'s `PosMfeMae` text pair is CORRECT as-is — the design uses a text
pair there too, not a bar. Pins: `tests/test_empty_state_standard.py`
(21 total). Bundle `96c240a869`.

## ▶ CLOCK DRIFT — the CCXT auto-sync answer (2026-07-25)

Operator saw `CLOCK DRIFT: local clock is -9987ms vs binance (severity=critical)`
after restart. **The auto-fix IS working and the warning is BY DESIGN.**
`adjustForTimeDifference: True` (`core/exchange_factory.py:59`) makes CCXT offset
every signed request, and EVERY signed path routes through that instance —
including `listenKey` (`fapiPrivatePostListenKey`). `time_sync` deliberately
still measures + warns (the comment at `:56-58` says so), so the banner reports
the OS clock, not a data failure. Sign convention: `offset = exchange − local`,
so −9987 ms = local ~10 s AHEAD, the `-1021` direction.

**Two limits worth keeping (verified against the installed CCXT 4.5.47, not
assumed):** (1) `nonce()` = `milliseconds() - options['timeDifference']`
(`binance.py:2869`) and `load_time_difference()` is called from exactly ONE site,
`fetch_markets()` (`binance.py:3431`) — i.e. during `load_markets()`. The offset
is measured ONCE at adapter init and cached: it cancels a CONSTANT offset, it does
NOT track ongoing drift. (2) It only fixes the outgoing request timestamp —
everything computed from the local clock is still ~10 s wrong (position AGE, the
linkage match window, BOD boundaries, correlation-log stamps, the new FEED
`stale_s`). The Pre-Trade countdown is the exception: receipt-anchored,
skew-immune by construction. **So: fix the OS clock (`w32tm /resync /force`);
reads are safe, time-derived displays are not.**

## ▶ v3.0 RENAME SHIPPED · RETIREMENT DEFERRED (2026-07-25)

**Identity is now MERIDIAN v3.0** (`config.py` only, per CLAUDE.md § "Release
hygiene"): `PROJECT_NAME_ = "MERIDIAN"` · `PROJECT_VERSION_ = "v3.0"` ·
`PROJECT_SHORT_NAME = "MRDN"`. Every displayed surface derives from these (page
titles, header/footer, startup overlay, FastAPI metadata, PWA manifest,
launch.bat title, and the React chrome via `QE_BOOTSTRAP`). **MERIDIAN is
ALL-CAPS on purpose** — `test_time_sync.py` pins that shape. UNTOUCHED, and must
stay so: the KDF domain salt `b"qe-kdf-salt-v2:"` (renaming it breaks decryption
of every stored credential) and the `risk_engine.db` / `.jsonl` filenames (a
rename there is a data migration, not cosmetics).

**★ THE RETIREMENT WAS BUILT, MEASURED, AND DELIBERATELY REVERTED.**
It works — `/` served the React shell, `/v3` 307'd to it, 8 Jinja twins and
their routes were gone, and the app booted with 4360 green. **Operator chose
"rename only, hold the promotion"** after seeing the true cost. Everything below
is what a future attempt needs, so nobody re-derives it:

- **COST: 126 tests across 25 files.** All `FileNotFoundError` source-greps of
  the deleted page templates — mostly `task-NNN` files encoding ~15
  operator-driven Jinja fixes (108 · 112 · 124 · 125 · 135 · 136 · 149 ·
  152-154 · 104b). The BEHAVIOURS were ported to React and have their own pins,
  so capability coverage is not lost — but 126 pins must be retired with them.
- **`base.html` CANNOT be retired** (the plan says "+ base.html plumbing" — that
  part is wrong). SIX templates still extend it: `admin/{calc_link,
  dd_enforcement, equity_gaps, shadow_events, trade_events}.html` and
  `orders/needs_link.html`. None has a React replacement. `v3.html` is
  standalone and does NOT extend it (its own header says so — a naive grep hits
  that comment and reports a false dependency).
- **`/config` CANNOT be retired**: React renders Add/Delete Account DISABLED
  with the title "add accounts via the current /config page". Retiring it
  strands account creation and deletion.
- **Every `/fragments/*` route must SURVIVE** (50 of them) — they carry the
  `?format=json` doors the React pages read. Only the 8 page GETs retire.
- `POST /models` also survives — a live fragment form still posts to it
  (pinned by `test_v27_phase3_model_routes.py`).
- Mechanical trap hit on the first pass: deleting a route decorator with a regex
  that stops at the next `def` leaves the HANDLER BODY orphaned. It still
  parses, so a syntax check passes while dead functions keep referencing deleted
  templates. Grep for the template names afterwards, not just `ast.parse`.
- Sequencing: the acceptance gate is "operator has driven React LIVE". The
  engine was stopped this whole session, so nothing since the DataList sweep,
  the no-data standard, HeatBar and the 29 LOW/NIT fixes has been seen running.
  **Restart + live-drive BEFORE retiring the fallback.**

## ▶▶ NEXT SESSION STARTS HERE

**1. The retirement is SCOPED AND READY — but gated on live acceptance.**
It was fully built this session and reverted on operator call; every fact needed
to redo it is in § "v3.0 RENAME SHIPPED · RETIREMENT DEFERRED" below. Do NOT
re-derive: `base.html` CANNOT retire (6 admin/orders templates extend it; and
`v3.html` only LOOKS like an extender to a naive grep because its header comment
says it deliberately isn't), `/config` CANNOT retire (React's Add/Delete Account
are disabled and point at it), all 50 `/fragments/*` + `POST /models` must
SURVIVE, and the cost is **126 pins across 25 files**. Gate first on the operator
having driven React live.

**2. Then**: promote `/v3` → `/`, retire the 8 twins + their pins, JS-drift grep.

**3. Standing carry-forward** (unchanged, don't lose): `no-undef` lint dev-dep ·
`entry_ms` rename + the P1 stub that hid it · Finnhub-token-in-log leak · news
~16 s cadence · `account_snapshots` migration · the intermittent aiosqlite
teardown warning (reproduce before chasing).

**4. OS clock drift — advice given, operator to apply.** Engine thresholds are
WARN 500 ms / CRITICAL 1000 ms on abs(offset); Binance `-1021` fires only when
local is AHEAD >1000 ms. The operator's `-9987 ms` was ~10× critical. Root cause
is almost certainly NOT the NTP server but the POLL INTERVAL: standalone Windows
defaults `SpecialPollInterval` to 604800 s (one week), so the RTC free-runs
between syncs and sleep/resume makes it worse. Recommended: `time.cloudflare.com`
(anycast) + a regional pool via `w32tm /config /manualpeerlist` with `,0x8`, and
`SpecialPollInterval` at 900. Avoid mixing leap-SMEARING sources (Google/Amazon)
with non-smearing ones — Binance is standard UTC. CCXT's
`adjustForTimeDifference` only cancels a CONSTANT offset measured once at
`load_markets()`, so it does not track ongoing drift, and it corrects only the
request timestamp — every locally-computed time (position AGE, link window, BOD
boundaries, FEED `stale_s`) stays wrong. **These are system settings — the
operator runs them, not the assistant.**

**▶ OPERATOR ACTIONS PENDING:**
1. **Restart the engine** (see the Engine line — lands 4 backend changes).
2. ~~Optional `--apply`~~ **DONE 2026-07-25** —
   `scripts/clean_overattributed_excursions.py --apply`: **67 rows / 10 symbols**
   nulled (SPCX 34 worst −284; SAGA 60%, LAB 45%, BSB 27% adverse). Backup
   `data/risk_engine.db.bak_pre_excursion_clean_20260724_174246`. Changed no
   displayed number (analytics read `closed_positions` since `7617b73`).
   **A LATENT DEFECT WAS FIXED FIRST — the tool was self-undoing.** It wrote
   `backfill_completed=0`, which is the reconciler's WORK-QUEUE flag, not an
   inert "unknown": `backfill_all()` is spawned unconditionally at every engine
   start (`core/schedulers.py:409`) and selects
   `WHERE NOT backfill_completed AND open_time>0 AND trade_key NOT LIKE 'qt:%'`
   (`core/db_exchange.py:240`), recomputing through the same
   full-position-window `calc_mfe_mae` that over-attributed the rows. Applying
   as-written would have durably cleaned **5 of 67** — the pending restart would
   have restored the other 62. Now writes `backfill_completed=1`
   (reconciler-DONE). Verified post-apply against the backup: 67/67 zeroed +
   flagged, **0 re-queued**, zero drift in income/notional/entry_price/qty/
   open_time, reconciler backlog unchanged at 349. NB the 67 rows are now
   permanently out of the reconciler — correct today (a per-partial excursion
   is not recoverable from a full-position window), reversible via the backup
   or `UPDATE exchange_history SET backfill_completed=0 WHERE ...`.
   **Contrast worth keeping**: `core.database`'s v1-v4 `reset_mfe_mae_*`
   migrations DO leave the flag alone — their intent is the opposite (zero so
   the reconciler RECOMPUTES with a corrected formula).
3. ~~Confirm #7's aspect direction~~ **RATIFIED 2026-07-25: keep `3 / 2`**
   (landscape, as shipped). NB the re-investigation found the ratio is treating
   a SYMPTOM: the cells were flat because our grid carries
   `alignContent: 'start'` (pages-analytics.jsx) which the design does NOT — it
   collapses the 6 week-rows to the 46px floor and packs them at the top,
   leaving the pane's remaining height empty. Operator chose the current look,
   so this is recorded, not acted on. Removing `alignContent` (and the two
   aspectRatio literals) is the design-faithful alternative if it ever looks
   wrong at another pane size.
4. Push/merge `v3.0/ui-plan-audit` at your call (still local-only).

**★ MECHANISMS + GOTCHAS worth keeping:**
- **`NormalizedAccount` now splits `total_equity` (margin balance) vs
  `wallet_balance` (settled cash).** `data_cache.balance_usdt` MUST take the
  wallet figure — it's the base `apply_mark_price` adds uPnL onto. Feeding it
  equity double-counts. MEXC is a **named residue**: CCXT gives no uPnL split,
  so wallet==equity there (unverified; ledger candidate).
- **`DL_AUTO_MIN = 1`** (was 5). Empty tables short-circuit to EmptyState
  ABOVE the toolbar and facets need ≥2 distinct values, so 1-row tables show
  search+sort only. Don't "restore" 5 — sparse live data is the real shape.
- **The v3 bundle is ONE concatenated top-level scope** (`build.mjs` joins with
  `;`, no IIFE). A duplicate top-level `const` is a BUILD-TIME parse failure —
  that's why hoisting `ModelDialog` into primitives required DELETING it from
  `pages-models.jsx`. The `vm.Script` guard is PARSE-only: it still cannot
  catch unbound identifiers (the P6-arc CRIT class).
- **`pre_trade_log.tags` is a DORMANT column** — `insert_pre_trade_log` never
  writes it (session tags ride the `calc_created` EVENT), so it is NULL on
  every live row; the resolver's tag chips stay empty by design. Live
  `model_name` is `''` too — the meta line honestly shows R + created/age only.
- **`account_snapshots` split residue**: writer → legacy DB, an orphan copy
  sits in `per_account/*.db` (frozen 2026-04-28, 82.19) and a third in
  `global.db`. Bug #4 pointed the reader at the writer's store; a real
  migration is still unfiled.
- **`get_trade_distribution_series` deliberately still reads
  `exchange_history`** — its `income` is per-event realized PnL (correct); only
  the excursion columns were over-attributed.
- Two live-DB cleanup tools now exist and share one discipline (dry-run
  default, verbatim planned changes, timestamped backup, refuse on non-empty
  `-wal`): `clean_phantom_equity_snapshots.py` (APPLIED) and
  `clean_overattributed_excursions.py` (**APPLIED 2026-07-25** — 67 rows; see
  Operator-action 2 for the self-undoing `backfill_completed` defect fixed
  first). **Discipline addition for the next such tool**: a cleanup that resets
  a column ALSO owns the question "does a background worker treat this value as
  its work queue?" — grep the sentinel's readers before writing it.

## ▶ SESSION CLOSE 2026-07-24 — P7 Models + the whole P8 audit-and-remediation arc

**What this session shipped (7 code/doc commits + 5 wraps, all gated + audited):**

| # | Commit | What |
|---|---|---|
| 1 | `22b03b9` | **P7 Models** — G-M1..7 + 6 React modules (verbatim workbook capture, render-as-is report) |
| 2 | `3e6bb45` | **PaneFoot completeness** — 24 foot-less panes (operator-caught); sweep moved to the EMITTED bundle |
| 3 | `d8bd5c8` | **P8 directive-#7 audit ledger** — 9 parallel lenses, built frontend vs the Meridian design |
| 4 | `37d012e` | **P8 wave 1** — the fabrication mechanism killed (chrome + notifications) |
| 5 | `15e77bb` | **P8 wave 2** — Dashboard restores, hedge-safe SSE merges, History substance |
| 6 | `0c2da37` | **P8 doc wave** — doc-truth MEDs, residue backfills, ECharts literal sweep |
| 7 | `2f05663` | this wrap |

**Every P8 audit finding is CLOSED** (D1 fabrication · D2 Dashboard drops ·
D3 linkage/history · 4 doc MEDs · the LOW/NIT tail). The ledger
(`docs/audits/2026-07-23-v3.0-p8-design-consistency-audit.md`) carries the
per-lens detail and a Disposition section tracking execution state — **read
it before touching P8 leftovers.**

**▶▶ NEXT SESSION — TWO INPUTS FROM THE OPERATOR:**

**(A) A BUG LIST.** The operator has bugs observed while live-driving `/v3`
and will paste them next session. **Handle them FIRST, before the decision
points.** Discipline for that pass: CLAUDE.md § "Re-investigation" —
reproduce/pin the symptom, investigate the MECHANISM independently (a
reported cause is a hypothesis, not a contract), fix the investigated one,
and note any divergence. Cheap context for triage: the engine is running
but PREDATES wave-2's Python routes (see the Engine line above), so
"Monthly bar chart empty" / "macro sparklines missing" are EXPECTED until
restart, not bugs. Bundle on disk = `36ffe0a5ee`; a stale browser cache is
the other standard false positive (hard-refresh first).

**(B) The 3 P8 DECISION POINTS** (answers pending — do not guess):
1. **Primitives in production nav** — it ships as a divider-separated
   amber DEV-chip tab in `NAV_ITEMS` (faithful to the design). Strip it
   for the `/v3` → `/` promotion (hash `#Primitives` keeps it reachable)
   or keep the chip? DESIGN.md §9/§10 now describe the shipped state and
   name this as your call.
2. **`tools={false}` fleet convention** — every shipped page disables
   DataList's built-in search/sort/filter (server owns paging/search),
   while DESIGN.md §5 still advertises them as auto. Ratify the
   convention in §5, or lift the suppression on the big tables
   (Per-Fill Log 500 rows, History pages)?
3. **Workspace-layout account-namespacing** — keys are
   `qe.ws.layout.${id}` with no account component (deferred §1.5).
   Implement namespacing, or leave it (doc now states the truth)?
**THEN retirement** (promote `/v3` → `/`, retire the Jinja twins +
base.html plumbing, CLAUDE.md OLD-class JS-drift grep) — gated on operator
acceptance of P2-P7 live — plus the Release-hygiene bump
(`PROJECT_VERSION_` + README Status) at program close (CLAUDE.md §
"Release hygiene": the displayed version froze for 3 minor versions once
because nothing named the bump).

**▼ OPERATOR BUG LIST — paste next session (slot kept deliberately empty):**

```
(next session: paste the observed /v3 bugs here, then triage per the
discipline in (A) above — reproduce, investigate the mechanism
independently, fix the investigated one, name any divergence.)
```

**Open, no owner yet** (carry forward, don't lose):
- **INTERMITTENT gate warning — `PytestUnhandledThreadExceptionWarning`,
  seen 3× (2026-07-25).** `RuntimeError: Event loop is closed` raised inside
  `aiosqlite/core.py::_connection_worker_thread` → `call_soon_threadsafe`: an
  orphaned aiosqlite worker posting back to a loop that already closed. The test
  pytest attributes it to varies and is incidental (once
  `test_phase1_matcher_t211::test_norm_side_buy_maps_to_long`, a pure-function
  test that touches no DB) — it is whatever was running when the stray thread
  fired. Appears in ~half of full runs (31 warnings vs 30); an immediate re-run
  of an IDENTICAL tree came back clean, and it pre-dates the slice-3 Python
  changes. Suite stays green, so it is a TEARDOWN artifact, not a failure. Fix
  shape if picked up: find the async DB test that leaves a connection unclosed
  and close it in teardown (CLAUDE.md's process-count discipline is the related
  guardrail). Do NOT chase it from a single sighting — reproduce it first.
- `no-undef` lint pass over the concatenated bundle — needs an
  eslint/acorn dev-dep (operator call). Until then the guard is the
  targeted identifier grep + the audit-time vm-render sweep; the esbuild
  `vm.Script` check is PARSE-only and has twice missed unbound identifiers.
- `entry_ms` MISNOMER on snapshot position rows (it is
  `PositionInfo.entry_timestamp`, an ISO string) + the P1 test stub that
  baked a numeric and hid it. Rename server-side + fix the stub.
- Live-log observations, unfiled: news fetcher upserts 100 items every
  ~16 s (intended?); httpx INFO writes the **Finnhub API token in
  cleartext** into `data/logs/risk_engine.jsonl`.
- Jinja stays the parity reference until each React page is accepted —
  never retire a template before its twin is accepted.

### P8 remediation detail (all three waves)

**P8 wave 2 SHIPPED `15e77bb`** — D2+D3 closed; full detail
in the ledger's Disposition EXECUTION STATE. Headlines: Monthly daily-PnL
chart end-to-end (backend `daily_pnl` + BarChart) · signal sparklines
(backend `series`) · sector_lines + Weekly-Loss gauge + AGE + real OHLC
header restored · hedge-safe symbol|side SSE merges BOTH files (+composite
row keys/live-ids) · History M·R/HistHeat + corrected false header +
Trade-Events SUMMARY (Jinja-exact) · period future-clamp · err toast ·
label de-snaking · `_ptJson` hoisted to primitives. 3 pins
tests/test_p8_wave2.py. Audit catch worth remembering: **`entry_ms` on
snapshot position rows is a MISNAMED ISO STRING** (PositionInfo.
entry_timestamp passthrough; the P1 test stub baked a numeric — the
stub-fidelity trap); PosAge is parse-tolerant; renaming the field +
fixing the stub = backend cleanup candidates. Bundle **`47f92434ad`**;
gate 4255/7/3.

**P8 doc wave SHIPPED `0c2da37`** — the 4 doc-truth MEDs + residue
backfills + the 11-site ECharts `'#000'` → `QE_ECHARTS_THEME.bg` sweep
(behaviour-identical; theme.bg = `#000000`). Plan P4 note retitled out of
stale "frontend pending" text (F13 class) with `b55d317`'s own deviations
restored; P3/P5/P7 residue lists backfilled from file headers (incl. the
StepperInput mis-attribution CORRECTED — price-mode = ratified Task-152,
pct-mode = plain uniformity); DESIGN.md §9 nav rules + §10's contradicting
Don't-row + §9's stale "P0 status" body + §6 namespacing + de-lined §1/§2
citations; regime + linkage file-header truth. **Audit lesson worth
keeping: a doc MED can be HALF-closed** — the §9 rewrite left §10's
quick-reference row still forbidding what ships; grep the WHOLE doc for a
claim, not just the section you're editing.

**P8 audit ledger `d8bd5c8`** — 9-lens directive-#7 audit (headline: 5/6
pages CLEAN at material tiers; drift = D1 fabrication (consensus HIGH) +
D2 Dashboard drops + D3 linkage/history trims + 4 doc MEDs) ·
**`37d012e` wave 1** — D1 CLOSED: `chrome-live.js`
QE_CHROME store + chrome rebound to real data ('—' when absent), real
account picker (activate+reload, failures surfaced), honest StatusFooter
(uptime real, ornaments dropped), NotificationProvider wired to
`/notifications/poll` (real-4 channels; N_SEED + REGIME/NEWS fiction gone),
the whole mock family deleted (QE_LIVE/QE_POS/MOCK/MOCK_WATCHLIST/
mockOhlc/mockEquity/mockSpark/LiveNumber/LivePct/useLiveTicker/
MOCK_REGIME-fallback/qeMockClockFmt), DEV demo rows relabeled EXAMPLE.
Bundle `ebb1d4e12a`; 2 audits SHIP-WITH-NITS 0 CRIT/HIGH/MED, all folded
(poll in-flight guard, /accounts retry, switch-failure surface,
unknown-regime '—'). The old P8-work list items now DONE by wave 1: the
shared-chrome adapter; still open: the no-undef lint follow-up (operator
call) + Release hygiene (PROJECT_VERSION_ bump at program close).

### Phase detail (P7 back through P0)

**P7 SHIPPED `22b03b9`** — the Models page on the
verbatim-capture backend; full detail in the plan's **P7 SHIPPED-STATE**
note. Headlines: G-M2 = ONE generic lossless serializer
(`core/backtest_adapters/workbook_capture.py`, `workbook.v1` — every
sheet/cell, type+SIGN preserved, non-finite F2-encoded, 250k-cell
fail-loud cap; the v2.7 ~9-scalar parse stays as the derived aggregate);
G-M1 `report_json` + per-run report endpoint; G-M3 overview feed (4
queries, spark ≤48); G-M4 source+tags + §6-3b seed-if-empty; G-M5
dry-run (writes nothing; bare dry_run w/o format=json 400s) + combined
create+import w/ rollback; G-M6 usage feed (closed+plans; open lane
deliberately absent); G-M7 filename + contracts. Schema = twins +
migration 015. Frontend = 6 `pages-models-*` modules: render-as-is =
RENDER-TIME label-lookup over the capture (generic sheet sectionizer +
bespoke KPI/paired-trades/equity/hourly panes, each degrading to the
generic render); `_synthReport` NOT ported; all foots qeFootState/
last-submit; `useAnaJson` gained an additive null-url skip. **2
independent audits, SHIP-WITH-NITS ×2, 0 CRIT/HIGH** (frontend auditor
EXECUTED the built bundle across all 26 component states — zero unbound
identifiers, the P6-arc CRIT class); ALL findings folded pre-commit
(headline folds: create-flow bounce await-reload; report-fetch error →
tier-3 EmptyState+Retry, was an infinite spinner; dry-run fail-loud).
31 pins `tests/test_p7_models.py`; 2 v2.7 pins updated to the new truth
(trade-key parity +`contracts`; the to_thread spy asserts parse AND
capture off-loop).

**P6 SHIPPED `81a6594`** — the Regime page; full detail in the
plan's **P6 SHIPPED-STATE** note. Headlines: verify-first found the surface
ALREADY all-JSON (zero doors; the row's "none new" TRUE in substance — but
News binds `/api/news/*` + `/api/calendar`, NOT `/api/regime/*`); ONE additive
endpoint `GET /api/regime/multipliers` (config map; deliberately not nested in
the FLAT /thresholds response); 9 pins `tests/test_p6_regime.py`;
`frontend/src/pages-regime.jsx` (4 tabs: 5-style ECharts timeline, 6 signal
cards w/ Task-136 precedence + Task-124 discrimination, PAGE-level backfill
job + 1500ms poll w/ 4-fail terminal, news magazine/detail + scroll-to-NOW
calendar, Config w/ decision-tree copy CORRECTED to the real classify_regime
cascade + confirm-gated Reclassify). **2 independent audits (relaunched after
a session-limit kill — plan-audit precedent), SHIP-WITH-NITS ×2, 0 CRIT/HIGH,
ALL findings folded pre-commit** (rule-copy divergence verified against the
classifier first; ECharts re-init memoization; _rgPost never rejects;
unknown-label guards; synthesized coverage rows; category-not-impact chips;
"open ↗" article links). Deviations + residues named in the plan note + file
header.

**★ PaneFoot arc (post-P6, operator-driven, TWO commits):**
(1) `0116083` — operator caught that only Dashboard had footers (P5/P6 had
dropped them citing a FALSE "P1-P4 parity" claim; P1's carried fabricated
`id:`/`ms:` ornaments). First pass: truthful prose foots everywhere + the
primitive's fake reload telemetry (`nextEventId`/animation-timer-ms/false
"resynced") fixed. (2) **`e43a7e1` — the DATA-STATE redesign (HEAD; supersedes the
prose approach — operator redirect):** foots are now 4-TIER STATE LINES
derived through **`qeFootState({loading, err, corrupt, status, hasData,
empty, ms, retrying})`** (primitives.jsx, window-exported): ok
`connected [12ms]` (real measured fetch ms) · warn degraded keep-last-good
(`delayed [Nms]` >500ms / `response corrupt · showing last data` /
`no network · showing last data`, `· retrying` appended ONLY for
interval-driven callers) · err named-cause (`endpoint not found (404)` /
`no network — engine unreachable` / `server error (5xx)` / `unauthorized` /
`corrupt response`) · sub+busy `loading…`/`reconnecting…`. 2-vs-3 rule:
data on screen → warn, none → err. Plumbing: `_ptJson`/`_cfgJson` attach
`err.status` (0=network) + `err.corrupt` (ADDITIVE); `useAnaJson` measures
ms + returns a ready `foot` (NB its `err` is now the ERROR OBJECT, not a
string — use `qeFootCause(err)` for text); QE_DASH tracks per-source
`state.net`; config/linkage/history/pretrade track per-loader `{err,ms}`
(linkage per-SOURCE, not per-lane — the lanes span /orders/* vs
/api/linkage/*). Non-fetch panes: `ok · local` (forms/localStorage),
`_ptCalcFoot` last-submit state (calc family), backfill job-state foot.
Audit was **DO-NOT-SHIP first**: two unbound-identifier CRITs in the built
bundle (a foot reading `d` inside the subscription-free TiledGrid memo —
fixed by extracting `EngineLogPane` as a useDash leaf; `curFoot` never
passed as a prop to RegimeTabOverview) — the esbuild `vm.Script` guard is
PARSE-only and cannot catch free identifiers. Both fixed + verified in the
rebuilt bundle; HIGH (drilldown's dead outer catch → per-leg error capture)
+ MED×3 + LOWs folded. Bundle **`94ac1f0c60`**. LESSONS for P7/P8:
(a) cross-page pane-anatomy consistency is an audit dimension; never cite
"parity with shipped pages" without re-grepping them; (b) the bundle guard
does not catch unbound identifiers — a `no-undef` lint pass over the
concatenated bundle is a NAMED FOLLOW-UP (needs an eslint/acorn dev-dep —
operator call); until then, grep new cross-component identifiers against
their defining scope before rebuild.
Operator acceptance of P2 (gear → Config), P3 (`/v3` Pre-Trade), P4
(History+Linkage), P5 (Analytics), P6 (Regime), and P7 (Models — incl. a
real `@ES` import rendered as-in-file from the verbatim capture) is still
pending — engine restart required (launch-v3.bat).

**Program state:**
| Phase | State |
|---|---|
| P0 Foundation | **SHIPPED `1221b16`** — precompiled React `/v3` (esbuild, vendored offline deps under `static/vendor/`, content-hashed bundle + `static/v3/manifest.json`; build in `frontend/`, `npm run build`), shared primitive/token/chart/grid layer, Primitives proving ground, SSE client-adapter skeleton (`frontend/src/sse-adapter.js`, `window.QE_SSE`), `frontend/DESIGN.md`. 2 audits clean. |
| P1 Dashboard | **SHIPPED `8b23417`** — `frontend/src/dash-tiled.jsx` wired: `/api/dashboard/snapshot` (initial) + SSE (`equity_update`/`position_update`/`dd_state`; no-flicker leaf `LiveValue`s; `TiledGrid` stays `React.memo`) + polls (state 5s / engine-log 4s / macro 60s / snapshot 15s). 5 backend gaps G-O1/O2/O3/O5 + snapshot. Mocks stripped; watchlist→open positions; halt banner on real `/api/state`. 2 audits, HIGH+MED+4×LOW folded. |
| **P2 Config** | **SHIPPED** — backend `35ffff1` (5 JSON endpoints: `/api/system` G-O8, `/api/connections`, `/api/config/account/{id}`, `POST /api/config/apply-preset` FULL, `/api/config/presets`; operator decisions: **preset Apply = FULL**, **enforcement flip = display-only/deferred**) + the frontend-port commit: `frontend/src/pages-config.jsx`, 4 tabs wired (account update form-encoded + activate + test · connections add/test/delete via the existing HTML endpoints, responses stripped to text · confirm-gated FULL preset Apply · read-only System), DD/weekly posture DISPLAY-only, mocks stripped, Add/Delete Account deliberately NOT wired (disabled — safe-writes scope; Jinja `/config` stays the management surface). **2 independent audits: SHIP-WITH-NITS ×2, 0 CRIT/HIGH; folded**: MED-1 cross-account reload guard (endpoint-echoed `account_id` + `acctRef`), MED-2 accounts-list refresh after save, add-form clear only on success, presets catch scoping, "Save" relabel (POST /connections doesn't test), 422-JSON prettifier, credential trim, ↻ onRefresh on both Accounts panes, "Saved." anchor comment in `routes_accounts.py`. **Accepted residues (named)**: Spot market-type option 400s by design (Jinja parity; only linear_perpetual adapters registered); update-endpoint partial-write-before-params-validation masking (pre-existing backend semantics, shared with Jinja — ledger candidate). Deviations recorded in the plan's **P2 SHIPPED-STATE** note. |
| **P3 Pre-Trade** | **SHIPPED** (the P3 commit) — backend: `?format=json` doors on `POST /calculator/calculate` (success-only; error exits stay HTML) + the countdown route (in-route `_out` shim, Task-139/146 literals intact in the pinned scan window) + `GET /api/calculator/orderbook/{t}` + `/api/calculator/context` + `_json_safe` (F2 discipline); 13 pins `tests/test_p3_pretrade.py`. Frontend `pages-pretrade.jsx`: full calc form (TP ladder / size override / model picker + `?model_id=` handoff + prefill-on-change / link override / match window), countdown chip = the PENDING(1s+t0)→stable(5s)→terminal machine w/ receipt-anchored local tick, auto-refresh w/ persistence-suppressor + cross-ticker guard, 1 Hz price poll (drives backend calc-symbol sub), **§1.3 overlay exact** (enforced→blur/freeze/scrim card; advisory→warn banner; corrected copy). "positions frozen" fiction PURGED bundle-wide (notifications.jsx + app-shell demo). **2 audits (SHIP-WITH-NITS · DO-NOT-SHIP→fixed): both HIGHs + all MEDs + LOW sweep folded pre-commit** (manual-only result cache; cross-ticker guard; queued manual; picker prefill; STOP=TAKER badge; interval stabilization; skew-immune countdown; …). Residues named in the plan's P3 SHIPPED-STATE note. |
| **P4 History+Linkage** | **SHIPPED** — backend `319daa3`: G-O7 = PositionInfo `planned_tp/planned_sl/tp_drift_pct/sl_drift_pct` stamped in `_enrich_positions_calc_id` (display-only; badge/sticky logic untouched; cleared in the no-junction branch; `_PRESERVE_FIELDS`). G-O6 = `GET /api/linkage/funding`. Mirrors: `/api/linkage/{positions,calcs,closes}` (closes carries DERIVED `pending_reason` = un-annotated MANUAL_OTHER). History `?format=json` doors: closed_positions (stamped badge) · order_history · fills · pre_trade (`model_display` F11) · trade_events (`_payload`/`_symbol`; rows carry ISO `timestamp`, not ms) · open_positions (serializer + working orders) · position_fills (`exec_link_status`). Drilldown events/amendments ride the EXISTING `/context/position/{id}`. 12 pins `tests/test_p4_linkage.py`. Writes stay choke-pointed (manual_link / mark_unplanned / close_reason / cancel — POST the existing endpoints from React, never write link_status directly). Frontend `b55d317`: `link-primitives.jsx` (lpPx magnitude rule; DevBadge ±0.1% deadband) + `pages-linkage.jsx` (needs_review inbox + 3-leg diff + reason picker; monitor wall on the mirrors; SSE uPnL merge; alert-class failure discrimination on the 200-always endpoints) + `pages-history.jsx` (5 tabs on the doors, server paging/search/date presets, drilldown, close-reason modal, page-scope CSV). Audit SHIP-WITH-NITS folded; residues in file headers (no server column-sort; ctx.events + Export-Audit → P8). |
| **P5 Analytics** | **SHIPPED `13c62de`** — G-O4 `/api/analytics/execution` (fills ⋈ pre_trade_log ⋈ orders; residual-vs-plan slippage semantics per audit H-1; time-to-fill, not latency — no signal→fill source exists) + `/api/analytics/distributions` (account-tz hour/dow per-trade tuples + R histogram); 8 `?format=json` doors + `_json_safe` F2-fold on `equity_ohlc`; `frontend/src/pages-analytics.jsx` (11 tabs; FE-MED-018 dim rule; real offset nav); 22 pins `tests/test_p5_analytics.py`; 2 independent audits, ALL findings folded pre-commit. Full detail: the plan's **P5 SHIPPED-STATE** note. |
| **P6 Regime** | **SHIPPED `81a6594`** — verify-first: surface already ALL-JSON (zero doors; News = `/api/news/*` + `/api/calendar`, not `/api/regime/*`); +`GET /api/regime/multipliers`; 9 pins `tests/test_p6_regime.py`; `frontend/src/pages-regime.jsx` (4 tabs; 5-style timeline; Task-136/124 semantics; page-level backfill job w/ terminal poll; scroll-to-NOW calendar; decision-tree copy corrected to the real classifier cascade; confirm-gated Reclassify). 2 audits SHIP-WITH-NITS, all folded. Full detail: the plan's **P6 SHIPPED-STATE** note. Followed by the **PaneFoot arc** (`0116083` prose pass → **`e43a7e1` 4-tier data-state**, ★ block above). |
| **P7 Models** | **SHIPPED `22b03b9`** — G-M1..7 backends (verbatim `workbook.v1` capture · report store/endpoint · overview feed · source+tags+seed · dry-run/create+import · usage · filename+contracts; schema twins + migration 015) + 6 React modules (render-as-is via render-time label-lookup; generic sheet sectionizer + degrading bespoke panes). 31 pins `tests/test_p7_models.py`; 2 audits SHIP-WITH-NITS, 0 CRIT/HIGH, all folded. Full detail: the plan's **P7 SHIPPED-STATE** note. |
| P8 retire+re-audit | not started (plan §5: retirement after acceptance + directive-#7 re-audit + JS-drift grep + promote `/v3` → `/`). |

**★ P2 KEY FACTS (shipped shape — still binding for later phases):**
- **Two disjoint risk stores** — `account_params` (sizing knobs; write via
  `POST /accounts/{id}/update`, form-encoded, `validate_params` + publishes
  `risk:params_updated`) vs `account_settings` (DD/weekly enforcement modes + absolute
  thresholds — the store the REAL DD gate reads). The full preset writes BOTH.
- **DD-enforcement flip is DEFERRED (display-only)** — read `dd_enforcement_mode` from
  `/api/config/account/{id}` `settings`; do NOT wire the write (its `advisory→enforced`
  flip needs the name-confirm safety gate — a later phase).
- ConfigPage is reached via the **gear button**, not the top nav (DESIGN.md §9).
  (Its P2-era "entirely inline-mock" note is SUPERSEDED — the page was wired to
  the 5 real config endpoints in the P2 frontend commit, and P8 wave 1 removed
  the last mock chrome around it.)

**★ LIVE-DB INCIDENT (the P2 session, 2026-07-22 — RESOLVED, no residual):** a draft P2 test POSTed
`/api/config/apply-preset {swing}` **through the shared TestClient**, which wrote the
swing preset onto **LIVE account 1's `account_settings`** — that writer resolves
`config.DATA_DIR` (live), which the temp-DB rebind does NOT isolate (**F5**). The F5
content-hash tripwire caught it. Restored the 6 overwritten fields from
`data/per_account/*.bak_pollution_20260605` (account 1 is CUSTOM / no preset: window 30 /
warn 0.08 / limit 0.095 / recovery 0.50 / analytics monthly); verified via
`get_account_settings`; pre-restore safety `.bak_pre_p2_restore_*` kept. Engine stopped +
mode advisory ⇒ **no trading impact**. The write-test was removed + replaced with a
stubbed-writer unit test (`tests/test_p2_config.py`). **LESSON (new memory
`no-write-tests-through-shared-testclient`): NEVER POST a write-endpoint through the
`test_routes` client — settings/config writers bypass the temp-DB rebind and mutate live
operator data; stub the writers. Only READS are TestClient-safe.**

**★ Standing execution facts:** Jinja UI is the live parity ref until each React page is
operator-accepted (never retire a template before its React twin is accepted); the SHARED
nav/workspace-bar/status-footer chrome (`nav-and-data.jsx`) still shows the P0 placeholder
random-walk (cross-page residual — a small shared `/api/state`+SSE adapter feeding the
chrome on every page is a follow-up, NOT bolted onto Dashboard/Config-only data);
SSE payloads carry no `mark`/daily-%/weekly-% (those refresh at the 15s snapshot);
DesignSync MCP is main-loop only (subagents can't see it). Memory: [[project-v3-ui-rebuild]].

(The block below — "▶ STATUS 2026-07-22 — v3.0 UI PLAN AUDIT DONE" — is the plan-audit
session that PRECEDED this execution; it remains as history.)

## ▶ STATUS 2026-07-22 — v3.0 UI PLAN AUDIT DONE + REV-1 RATIFIED; NEXT SESSION = execute P0 (Foundation)

**▶▶ (SUPERSEDED — this was the 2026-07-22 start marker; the live one is at the top of this file.)** Read, in order: (1) `docs/design/v3.0_ui_rebuild_plan.md`
(the plan, REV-1 — §0 decisions, §5 phase sequence, §1-§4 architecture/gaps/mock-strip),
(2) `docs/audits/2026-07-22-v3.0-ui-plan-audit.md` (the 6-lens ledger + the REV-1
fidelity section) as needed, (3) the design reference under `docs/design/meridian_v3/`.
Then **execute P0 (Foundation)** per plan §5 under the house cycle (one commit, gate SOLO
on `.venv` once code exists, ≥1 independent audit, fold, STOP for operator acceptance).
**One OPEN question for the operator** (flagged, not decided): Models sits at P7 to honor
the cockpit-first directive, but its parser rebuild (G-M2) is the heaviest backend lift
and is transport-independent — offer to pull it earlier. **Do NOT re-open §0** (ratified)
or re-litigate the sequence (operator-directed).


**Branch `v3.0/ui-plan-audit`** (forked off `5d2fe17`, the naming-hygiene wrap;
NOT off `v2.7/model-library`'s tip label — same commit). Two commits:
- **`5a24c66`** — imported the **Meridian v3.0** React design reference into
  `docs/design/meridian_v3/` (23 files, the full app dependency closure:
  `Meridian v3.0.html` + `DESIGN.md` + `v25/tokens.css` + 20 JSX modules). Fetched
  via the design MCP (`DesignSync` — **main-loop only; subagents cannot see the
  tool**, verified). Deliberately skipped the design-canvas scratch (screens/,
  uploads/, v25/index.html + design-canvas.jsx, the dash-tape/dash-command/
  dash-split-rail/pages-regime-v2 alternates, the History-blotter/refresh-control
  explorations) — recoverable in the design project. **Verified live**: served over
  localhost HTTP (file:// blocks Babel's XHR of the external `src` scripts — CORS,
  not an import defect), the app boots and renders Dashboard + Models incl. the real
  parsed @ES MultiCharts run.
- **this wrap commit** — the audit + the plan (docs only; **tests NOT re-run —
  docs-only branch**, engine untouched).

**The audit** (`docs/audits/2026-07-22-v3.0-ui-plan-audit.md`): **6 parallel
read-only agents**, each a lens (Models data-contract · other-pages data-contract ·
architecture/feasibility · design internal-consistency + mock-traps · plan-doc
staleness/scope · phasing/risk). Two agents died mid-run on a session limit and were
relaunched clean after the reset; all 6 are folded. **The plan**:
`docs/design/v3.0_ui_rebuild_plan.md` (folds every finding; house precedent = v2.7
rev-2 folded 24 findings pre-execution). The old `v3.0_models_tab_design_prompt.md`
is banner-marked CONSUMED and points at the new plan.

**★ GATING DECISIONS — RATIFIED by operator 2026-07-22 (plan REV-1, §0):**
1. **Decision A → A2 (React).** Adopt the Meridian React reference as v3.0's UI,
   served as **AOT-precompiled static JS from FastAPI** (production UMD + vendored CDN
   deps + one-shot esbuild — no standing Node server, no runtime `package.json`).
2. **Decision B → precompiled static JS** + vendored offline assets.
3. **§3 source-binding → REVERSED** from the audit's recommendation: **models DO carry
   source binding** (backtest provenance — "where we backtested them"); the
   exchange-agnostic invariant applies to the **live trading account**, not the model.
   G-M4 (source_json + tags_json on `potential_models` + auto-seed from the import's
   Settings) is IN as designed.

**★ SEQUENCE — REV-1 (operator directive: implement AND backend-wire ALL pages,
cockpit-first):** P0 Foundation → **P1 Dashboard** (forces the SSE live-data transport
early) → **P2 Config** → **P3 Pre-Trade** (carries the halt→blur/freeze overlay) →
**P4 History+Linkage** → **P5 Analytics** → **P6 Regime** → **P7 Models** (full
render-as-is report; heaviest backend lift = adapter rebuild; can pull earlier since
it's transport-independent) → **P8** retire Jinja + directive-#7 re-audit + JS-drift
grep. One commit/phase, house cycle, Jinja serves as parity ref until each React page
is accepted.

**★ Directive-specific rulings folded into the plan:**
- **#3 halt → freeze Pre-Trade**: the "positions frozen" fiction lives in TWO places
  (notification banner `notifications.jsx:148` AND the Pre-Trade `<Banner>`
  `pages.jsx:453`, hardcoded `const halt=null` at `:433`). Rewire both to real
  `dd_state`/`weekly_pnl` SSE + a `halted` flag on `/api/state` (G-O2). Overlay
  attaches to the Pre-Trade `<GridWorkspace>` (`pages.jsx:470`, wraps exactly its 7
  panes); enforced-mode breach → blur+`pointer-events:none`+reason card; advisory →
  warn only. Enforcement mode read from Config's DD Enforcement select
  (`pages.jsx:1649`).
- **#4 render-as-is**: G-M2 adapter rebuild must reproduce the uploaded MultiCharts
  file faithfully (all sheets/columns/signs), stored verbatim in `report_json`.
- **#7 re-audit**: P8 re-audits the plan vs. the BUILT frontend + fixes drift.

**★ Plan-vs-frontend fidelity VERIFIED (2 agents):** all 23 descriptive plan claims
about the Meridian frontend are ACCURATE — the plan is faithful. 3 nuances recorded in
the ledger's "REV 1" section (persist wired only for dashboard+linkage today; "9 of 11
Analytics" is a backend-binding count; `_synthReport` has a 2nd call site).

**Headline audit findings folded into the plan:**
- **HIGH — halt-state authority conflict.** The design persists a "TRADING HALTED ·
  positions frozen" banner in `localStorage` with a client countdown, but the engine
  is **advisory-only** (log/calculator-block; it's a pre-trade gatekeeper, never in
  the order path). The banner is fiction → rewire to real `dd_state`/`weekly_pnl`
  SSE + corrected copy. This is a correctness fix, not a port choice.
- **The biggest Models gap is the PARSER, not the UI.** The MultiCharts adapter reads
  only cols A/B of one sheet + keeps ~9 scalars; the design renders the full report
  (All/Long/Short grid, 8 ratios, Trade Analysis, hourly Periodical, per-trade
  run-up) — **all parseable from the file already uploaded but discarded**. G-M1
  (per-run `report_json` store + endpoint) + G-M2 (adapter rebuild) is P1's critical
  path.
- **Most non-Models surface is already SERVED** — Pre-Trade, History, all Regime,
  Config accounts/connections, 9/11 Analytics tabs, the whole Linkage cockpit bind
  to existing endpoints. Concentrated gaps only: Dashboard Engine-Log live feed,
  Analytics Execution-Quality/Distributions tabs, Linkage funding-book JSON, the
  notification taxonomy (6 claimed / 4 produced). All enumerated per-phase in plan §2.
- **PREMISE CORRECTION** the phasing agent caught: the Linkage per-criterion match
  diff **already has a full backend** (`routes_orders.py:524-557` + `calc_correlation`
  + `match_audit`) — Linkage is a lower-risk target than assumed.
- **Serving/transport**: precompile to static JS; live data over **SSE** (engine
  already exposes it; `LiveValue` is SSE-shaped); add no browser WebSocket. Vendor all
  CDN deps (localhost/offline doctrine + PWA precache). Mock devices to STRIP
  (frozen clock, random-walk tickers, `Math.random()` in the dash render path, seeded
  synth reports, localStorage halt, DEMO panel) are mapped file:line in the ledger.

(The audit's ORIGINAL recommendation was Models-first; the operator's REV-1 directive
re-sequenced to cockpit-first — see the "★ SEQUENCE — REV-1" line above, which is the
one in force. The audit's Lens-6 Models-first rationale is preserved in the ledger for
context.)

**Not pushed** — `v3.0/ui-plan-audit` is local only; operator merge/push at their call.
Memory: [[project-v3-ui-rebuild]].

---

## ▶ STATUS 2026-07-21 (later) — naming hygiene `92b753b` SHIPPED + merged + PUSHED; engine LIVE on the v2.7 identity; NEXT = v3.0 UI plan audit

**Supersedes the green-gate block below on branch topology** (its "operator merges/pushes" step is
DONE — `v2.7/model-library` fast-forwarded `03f7236 → 92b753b` and pushed; origin in sync).

**The naming-hygiene task (`92b753b`, gate 4119/7/3, 2 independent audits clean, house cycle):**
- **Identity is now config-only**: `config.py` `PROJECT_NAME_` / `PROJECT_VERSION_` (bumped
  v2.4.1.1 → **v2.7**; it had been git-verified frozen since task 108 `4ecd75d`) + new
  `PROJECT_SHORT_NAME` / `PROJECT_DESCRIPTION`. FastAPI metadata + the PWA manifest now derive
  from config; templates/launch.bat already did. **The post-v3.0 product rename = a config.py
  edit only** (+ `test_time_sync.py`'s ALL-CAPS shape pin on `PROJECT_NAME_` if the new name
  isn't uppercase).
- **De-trapped tests**: task-108's `startswith("v2.4.1")` exact-prefix pin RETIRED (it made every
  version bump a red test — the mechanism behind the freeze); `test_project_meta.py` scans made
  major-agnostic (the old `v2.`-anchored regexes would have gone blind at v3.0); +7 pins incl. a
  monkeypatch end-to-end manifest wiring check.
- **Service worker**: display strings de-branded (raw static file — cannot read config) + an
  ADJACENT FUNCTIONAL FIX: `PRECACHE_URLS` pointed at the deleted `/static/manifest.json`; atomic
  `cache.addAll` meant that one dead URL silently voided the ENTIRE pre-cache. Now `/manifest.json`
  — PWA offline pre-cache works for the first time.
- **Docs**: README Status v2.4-era → v2.7 truth; CLAUDE.md § "Release hygiene" (bump
  `PROJECT_VERSION_` at program close; never exact-prefix-pin a version; never-rename list:
  `qe-kdf-salt`, `risk_engine.*` filenames).
- **Frontend live-verified** post-push: `/` renders "QUANTAMENTAL ENGINE v2.7" (zero v2.4.1.1),
  manifest name/short_name/description correct, OpenAPI title + version 2.7. NB stale-display
  causes are SERVING-layer: Jinja globals bake config at process import (restart required) and
  the SW's offline fallback replays the last cached page when the engine is down. Installed-PWA
  OS-level app name refreshes lazily from the manifest (cosmetic lag; reinstall if it lingers).

**▶ NEXT SESSION = v3.0 UI plan audit** — the operator will open a NEW Claude Code session **with
the Claude design frontend MCP connected** for this program. Charge: audit
`docs/design/v3.0_models_tab_design_prompt.md` BEFORE any execution — multi-agent read-only PLAN
audit, findings folded into the plan first (v2.7 rev-2 precedent: 6 agents, 24 findings folded).
Base is pushed + green as the green-gate wrap required. Reminder for that session: v3.0 rebuilds
the presentation layer (Track-2 doctrine — today's DOM is throwaway; browser-level tests come
AFTER the new DOM stabilizes).

**Open / opportunistic after this session:**
1. **CHANGELOG backfill** — top entry is still v2.4.4; v2.5/v2.6/v2.7 entries were never written.
2. **Branch tidy (post-push, optional)**: delete the `v2.7/naming-hygiene` label (== tip) and
   retire the merged `claude/nice-taussig-4dc2ef` worktree + branch.
3. Optional `main` fast-forward; ~678-row live per_account test-pollution DRY-RUN clean
   (ledger § operator action); the v2.7 operator live-verify checklist (plan §5 items 5+7).

## ▶ STATUS 2026-07-21 — true green gate reproduced everywhere; provisioning tool shipped; NEXT = v3.0 UI plan audit

**Supersedes the ▶ AUDIT STATUS block below**: Tasks **D (`76b01d7`) and E (`fefc54a`) SHIPPED**
2026-07-17 (+ `03f7236` clean_test_pollution extension for the Task-E position_fill_snapshots leak).
Holistic-audit ledger F1–F18 fully dispositioned; the block below is history.

**This session** (worktree `nice-taussig-4dc2ef`, operator-driven "accomplish the true green gate"):

| Commit | What |
|---|---|
| `dc9e963` | dead `templates/fragments/history_tables.html` deleted (Task D sweep). Caveat that cost the prior session: the worktree was CREATED ON A WRONG BASE (`cb28563`, v2.4.4) — re-pointed onto the v2.7 tip before committing; deletion proven inert via identical before/after full-suite counts. |
| `9ea7e30` | **`scripts/provision_test_env.py`** + `tests/test_provision_test_env.py` (20 pins) + CLAUDE.md § "Fresh worktree / clone". |

**Root cause of the fresh-worktree red suite** (~110 failures, all `no such table:`
account_settings / pre_trade_log / engine_events / trade_events): the worktree `data/` lacks the
SPLIT LAYOUT — `db_router` bakes `SPLIT_MARKER` off `config.DATA_DIR` and
`db_account_settings._resolve_db_path` short-circuits to the legacy `risk_engine.db` fallback
whenever `split_done()` is False, even when the test patched `config.DATA_DIR` to a perfect tmp
split layout. Interpreter ruled out (identical 110 on user-site Python and the venv).

**Gate evidence chain** (all solo, `.venv` interpreter): main tree **4092/7/3** green (no tripwire
findings, live data mtime-verified untouched) → worktree pre-provision baseline 110 failed →
post-provision **4092/7/3** → post-credential-scrub **4092/7/3** (green is credential-independent)
→ final gate on the environment the committed script itself produced **4112/7/3**.

**Independent-audit catch (HIGH, remediated)**: the first provision run re-encrypted the operator's
real `.env` keys into worktree DBs — `config.py`'s bare `load_dotenv()` parent-walks a worktree into
the MAIN tree's live `.env`, then `core/database.py`'s fresh-DB seeds (v1.3-seed on `accounts`,
`_migrate_env_connections` on `connections`) encrypt `BINANCE_*`/FRED/FINNHUB/COINGECKO into every
empty DB `initialize()` touches. Scrubbed everywhere; the shipped script PREVENTS it (blanks the
`config` credential attrs pre-init — live-verified "prevention held") and a source-pin test goes red
if `database.py` grows a new seed not covered by `CREDENTIAL_ATTRS`.

**Unfiled observations for a future ledger pass** (surfaced, operator-gated — NOT filed):
1. The main-tree gate run touched live `global.db`'s WAL/shm (0-byte, no content committed) — the
   suite opens live DBs write-mode even when writing nothing.
2. The `.env` parent-walk + auto-credential-seed pair means ANY fresh-DB `initialize()` on this
   machine absorbs real keys (the provisioning tool guards itself; the seed paths remain) —
   hardening candidate.

**▶ NEXT SESSION = v3.0 UI plan audit**: `docs/design/v3.0_models_tab_design_prompt.md` — v2.7
shipped minimal-UI by design; v3.0 rebuilds the presentation layer. House precedent: multi-agent
read-only PLAN audit with findings folded into the plan BEFORE execution (v2.7's rev-2 plan audit
folded 24 findings — reuse that shape). Housekeeping first: operator merges/pushes the session
branch (header ▲), then the plan audit starts from a pushed, green base.

## ▶ AUDIT STATUS 2026-07-17 — holistic program audit F1–F18; Tasks A–C SHIPPED, D–E NEXT

**The ledger is the source of truth: `docs/audits/2026-07-17-v2.7-holistic-audit.md`** (6 parallel
read-only agents over the whole program diff `e05e359..c0c2c37`; findings F1–F18 tiered, fix plan =
Tasks A–E; incl. the F13 commit-message errata and the named accepted residues). Every fix task ran
the house cycle: targeted + full gate SOLO + 2 independent audits + folds pre-commit.

| Commit | Task | Closed | Gate |
|---|---|---|---|
| `329018e` | A | **F3** Model sort-header 400 (allowlist + a 7-table template↔allowlist class pin) · **F2** non-finite JSON poisoning (both doors + a direct-poison mechanism test) · F16 null-name/description 400s | 4033 |
| `f03b24d` | B | **F1** calculator restore races (ONE mechanism: provisional-option injection — synchronous serialization; history stores/restores modelId) · **F4** the order_manager gate pins (mutation-kill DEMONSTRATED) · F13d real containment check | 4035 |
| `85e7c1c` | C | **F7** parse body-wrap (logged; discriminating pin) · **F8** parse via asyncio.to_thread · **F9** boot sweep for interrupted imports + FAILED badge (txn shape = documented deliberate non-fix) · **F10** zero-label warn + PF fallback symmetry · **F14** double-submit/accept/size-precheck · the ledger doc | 4046 |

**▶ NEXT = Task D — attribution surfaces + docs truth** (one commit, house cycle):
1. **F6**: `calc:position_closed`'s `model_names` emits `[]` for exactly the calc-linked positions
   (the P5 gate blanks the variable the event reads at `core/order_manager.py:~2986`) — and the
   **webhook dispatcher forwards this payload externally**, so the P6 "no consumer" disposition was
   internal-only. Fix = build `model_names` from the ENRICHED row / the stamp (post-insert), and
   correct the stale comment at `~:2964`.
2. **F11**: picker-tagged calcs render "—" in the Pre-Trade Log (`pre_trade_table.html:72` reads
   free text only) — render via the `model_id` FK when free text is empty.
3. **F12**: `summary_json["settings"]` is persisted but NOTHING renders it (§6-3b described as
   shipped) — ship a tiny read-only render in the run list/detail OR re-document as deferred.
4. **F13 residue**: P2 plan rows still contradict shipped state (2.4/§6-2 ElementTree "stays" →
   detect-and-reject; 2.7 "~20 trades" → 10); `tests/test_routes.py` docstring falsely claims temp-DB
   isolation (coordinate wording with Task E); plan §2 qt-import present-tense.
5. **F15/F17 sweeps**: dead `asdict` noqa re-export in `multicharts.py`; `Tuple` unused in
   `routes_backtest.py`; non-dict JSON body → 400 in `/api/models` (pre-existing 500); "~265"→266.

**Then Task E — test-isolation hardening (F5, its own mini-program, dry-run discipline):**
`test_routes`' `config.DB_PATH` patch is VOID in full-suite runs (the `db` singleton binds path at
first import — alphabetically-earlier test files trigger it) → the TestClient lifespan initializes
the LIVE `data/risk_engine.db`, the migration runner hits the live split DBs, and
`start_background_tasks()` runs **15 live schedulers with the operator's real API keys** (calc-expiry
/ stale-order / session-reaper are live-mutation vectors). Conftest guards cover none of it. Scope:
session-scoped DB/DATA_DIR binding before any singleton import; gate the runner + schedulers out of
test lifespans; root-logger handler guard; + the F18 CLAUDE.md notes (executescript-before-ALTER
trap; lifespan-boot-touches-live-DB; deviations-into-plan-notes).

**Still outstanding after D+E**: the operator live-verify checklist (unchanged, below) and the
optional main fast-forward.

## ▶ STATUS 2026-07-17 — v2.7 MODEL LIBRARY COMPLETE (P1–P6, all audited, PUSHED)

The v2.7 program (`docs/design/v2.7_model_library_plan.md`, **Status: EXECUTED** — rev 2 after a
6-agent plan audit folded 24 findings pre-execution): a DB-backed library of reusable,
exchange-agnostic models + a per-app backtest-import adapter framework (MultiCharts first) +
calculator pre-fill + close-time model tagging + retirement of the superseded surfaces.
Minimal UI by design — v3.0 rebuilds the presentation layer. Memory: [[project-v27-model-library]].

| Commit | Phase | What |
|---|---|---|
| `fd085e1` | plan | rev 2 — 6-agent audit folded (1.7 redesigned to `get_model_for_calc`; +1.8 backtest-tab filter; +5.4 close-stamp; +Phase 6) |
| `574bb37` | 1 | schema + DB layer (CREATE/ALTER twins; dual-track migrations 013/014; atomic `create_model_backtest`; gate 3956) |
| `d24b754` | 2 | `core/backtest_adapters/` + MultiCharts parser built against the REAL `@ES` export; 10 KB synthetic fixture (gate 3973) |
| `06f5f4a` | 3 | routes: JSON CRUD + fragments + the codebase's FIRST multipart upload + prefill; 5 fragment templates (gate 4003) |
| `6478e03` | 4 | `/models` page + nav/page_meta + Load-into-Calculator anchor (gate 4008) |
| `c914ccf` | 5 | calculator picker (+`?model_id=` consumption) → `pre_trade_log.model_id` → close-row stamp + history Model column (gate 4021) |
| `0d90f32` | 6 | retirement: Quantower JSON importer (L5) + old Models sub-tab GONE; Run-panel config selector + microstructure render KEPT (gate 4027) |

**Key facts / landmines for future sessions:**
- **Attribution rules**: position→model resolution goes `PositionIdentity.position_primary_calc`
  → `get_model_stamp_for_calc` (row free-text wins → FK-join name → "(deleted model)"). The
  close-row stamp is CHOKE-POINT enrichment in `insert_closed_position` (covers live + rebuild +
  scripts); the order_manager gate BLANKS the shortfall-heuristic name whenever the position has
  a calc (T234 collision can't mismatch the stamp). Model columns are re-derived, not preserved,
  on REPLACE — the stamp travels with `calc_id`.
- **FK policy**: every `model_id` column is FK-in-name-only (cross-file FK impossible —
  `potential_models` lives in global scope); ids dangle by design after a model delete; readers
  LEFT JOIN + "(deleted model)".
- **Backtest tab**: `list_backtest_sessions` filters `model_id IS NULL` — imported model runs
  render ONLY in the model library. Historical `type='microstructure'` (Quantower JSON) sessions
  still render via the KEPT `results.html` branch (anchor-commented; do not sweep as dead).
  The Run panel's `#model-selector`/`loadModelConfig` (legacy `config.signals/risk` prefill of
  the RUN form) deliberately SURVIVES the P6 retirement — read-only, fed by `/api/models`.
- **Gotchas learned (pinned by tests)**: indexes on ALTER-added columns must live in the
  post-ALTER block, NEVER inside `_CREATE_STATEMENTS` (executescript runs first — legacy DBs die
  at boot; `test_initialize_upgrades_legacy_shaped_db`). MultiCharts real-file facts: trades
  header on ROW 3 (scan, don't hardcode), `Max Strategy Drawdown`/`(%)`/trade `Drawdown ($)`
  signed-NEGATIVE, `Profit Factor` cell signed-negative → RECOMPUTE from gross, `Point Value` is
  the string `"$50"`, the `.xml` export IS an OOXML zip (sniff PK bytes). Percent-string cells
  convert to fractions (silent-100x guard). Route tests: append GETs to `test_routes.py` lists /
  call handlers directly — never a second TestClient (LOW-023).
- ⚠ **Test-infra disclosure**: `test_routes`' TestClient lifespan runs the migration runner
  against the REAL `data/` dir — this session's runs applied migrations 013/014 to the live
  `global.db` + per-account DB (additive columns only; `risk_engine.db` untouched). Pre-existing
  isolation gap, not v2.7-introduced — hardening candidate for a future task.
- **Corr-log**: untouched — model writers are not money-path (spec §5.5/E22 closed list); the
  `insert_pre_trade_log` db_write tap payload verified byte-identical (frozen pins).

## ▶ NEXT SESSION — operator live-verify, then next program (operator's call)

1. **Live dogfood v2.7 (plan §5 items 5+7)**: `w32tm /resync` → start engine → open `/models` →
   create a model with a risk preset → import the real `@ES` MultiCharts report (both the `.xlsx`
   and renamed `.xml` should work) → "Load into Calculator" → confirm the picker+preset prefill →
   submit a plan → confirm `pre_trade_log.model_id` set → after a close, the Model column in
   Position History shows the name (free text left EMPTY is the acceptance shape). Also confirm
   the Backtest tab still renders engine sessions + historical Quantower rows, and the model
   library is the only management surface.
2. **Deferred by design (recorded in the plan's executed notes)**: v3 styling/equity-chart polish,
   extra adapters, §6-3b Settings auto-seed, the post-create stale-form UX (oob detail swap),
   `calc:position_closed.model_names` heuristic-sourced (deferred-opportunistic), browser-level
   JS tests (post-v3, Track-2 doctrine).
3. **Optional**: fast-forward `main` to the v2.7 tip; push `archive/quantower-plugin` (still
   local-only).
4. **Next program candidates**: v3.0 ground-up UI rebuild (`docs/design/v3.0_models_tab_design_prompt.md`)
   — the durable backend it will be rebuilt against is now in place; or the parked reconciler
   residuals / startup-REST-throttling item (v2.6 block below). Operator decides.

## ★ HISTORICAL (below — superseded by the v2.7-COMPLETE status above)

## ★ HISTORICAL — v2.6 STATUS 2026-07-16 — COMPLETE + AUDITED (15/15 findings CLOSED) + PUSHED

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

## ★ HISTORICAL — v2.6 AUDIT 2026-07-16 — 15 findings, ALL CLOSED (4 commits, each gate-green + agent-audited)

| Commit | Closes | What |
|---|---|---|
| `19ecac1` | **#2** | **The only real regression.** P1's extraction early-bound the singleton (`from core.order_manager_singleton import order_manager` at module scope in `schedulers.py` + `routes_dashboard.py`), so the ONE documented seam — `patch("core.order_manager_singleton.order_manager", …)` — could not intercept them: a test would pass while the REAL OrderManager ran against the REAL DB. Pre-v2.6 `patch.object(platform_bridge, "_order_manager", …)` reached every consumer via the shared bridge OBJECT. Fixed to the module-import form (deref at call time). **Demonstrated, not theorized**: reverting to the pre-fix shape turns the new pin RED. +8 pins in `tests/test_order_manager_singleton_seam.py` |
| `425cf87` | #3b, #4-#8, #13 | MED truth sweep — ~20 comments/docstrings describing the plugin (and its gating) in the present tense. PROSE ONLY. Incl. `schedulers.py:142` claiming *"Account/position refresh: plugin-gated (plugin is authoritative)"* (false since P2) and `_order_staleness_loop`'s docstring advertising a sweep P2 DELETED. **LB-R2's v2.6 re-open trigger EVALUATED (not just reworded) → RISK UNCHANGED**: the removed time-path was `is_connected`-gated → never ran standalone → v2.6 deleted dead code. LB-F3's "3 wired call sites" → 2 |
| `9983429` | **#1** (HIGH), #14 | Corr-log spec purge + **registry 46 → 42**, **E37 filed**. P6's doc sweep NEVER OPENED `correlation_log_spec.md`: it listed the deleted `platform_bridge` as a **"money-path critical"** `wsp` entry point and kept `quantower` in §4's peer set under the spec's OWN *"no dead peers"* rule — the invariant it asserts about itself was FALSE. Operator chose PURGE over a rule carve-out. **Rule HOLDS again**, independently verified (all 10 surviving peers emitter-reachable; `quantower` = 0) |
| `c418268` | #9, #10, #12, #15, **#3a REVERSED** | Deleted monitoring **Check 6** (plugin health — nothing could set `_ever_plugin_connected`; `run()` paid a call/tick for a guaranteed early-return; 9→8 checks everywhere) + **`active_platform`** (zero readers). **#3a reversed to WONTFIX** — see below |

**★ #3a — `db.mark_stale_orders` is DELIBERATELY caller-less. Do NOT delete it.** The audit filed it as orphaned dead code; investigation proved the filing over-called. The battery pins it as the **TIME twin** of the live snapshot sibling `mark_stale_orders_canceled` — LB-T2i's own docstring says so — and that PAIR is why the LB-F3 sweep exists; `test_correlation_log_state` pins its `via=time` tap. It is a generic DB primitive, same disposition as landmines L2-L5. Un-gating it was REJECTED, not overlooked: without plugin order snapshots a time threshold wrongly cancels real working stops. Anchored in-place (as is its L3 twin `data_cache.apply_account_update_platform`). *The real defect was the docstrings calling it LIVE — fixed in 425cf87.*

**Contrast worth remembering — both labels were BACKWARDS**: `active_platform` was called a "landmine" but was plain dead code (deleted); `mark_stale_orders` was filed as dead code but is a genuine landmine (kept). Neither survives pattern-matching; both needed investigating.

**Boot path: CLEAN.** The operator live-started the engine (clock synced) — the one class the `import main` smokes could never reach. Nothing found.

## ★ HISTORICAL — the v2.7 program pointer (EXECUTED — see the top block)

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
