# Project guidance for Claude Code

Operational notes for working in this codebase. Keep additions tight and
load-bearing.

## Test execution discipline

### Pytest timeouts

The project uses `pytest-timeout` with a 30-second default per test
configured in `pyproject.toml`. If a test exceeds this, pytest fails the
suite with a clear timeout message identifying the hung test.

**When the test suite appears stuck:**

1. Do NOT retry blindly. The 30 s timeout means any hang of multiple
   minutes is anomalous — either a test is genuinely slow, or pytest
   itself is stuck, or worker processes have deadlocked.
2. Check Python process count: `tasklist | findstr python.exe` (Windows)
   / `ps aux | grep python | wc -l` (Linux/macOS). If more than ~3-4
   Python processes exist when pytest is "running," workers may have
   piled up.
3. Kill stuck workers before retrying: Task Manager / `taskkill /F /IM
   python.exe` (Windows) or `pkill -9 -f pytest` (Linux/macOS). After
   killing, do NOT retry the same way — investigate which test hung
   first.
4. If a specific test class consistently hangs, surface in the task
   report rather than retrying. There may be a test-infrastructure bug
   (DB lock leak, subprocess wait, never-awaited coroutine) that needs
   addressing.

**Background:** Task 101 (commit `dda5519`) saw pytest hang for ~1 hour
with 7-8 worker processes consuming all 32 GB system RAM. Only resolved
by manually killing Python processes via Task Manager. The 30 s timeout
+ this guidance are the guardrails against recurrence.

### Per-test timeout override

For tests that legitimately need more than 30 s, mark them individually:

```python
@pytest.mark.timeout(60)
def test_slow_integration():
    ...
```

Use sparingly. A test needing >60 s is a smell — surface it for
refactoring rather than normalizing the slow path.

### Resource limits

The development environment has 32 GB RAM. Test runs should not approach
that limit. If a test or fixture causes resource exhaustion, surface as a
finding rather than working around it (e.g., do not silently lower test
coverage or skip the slow test — flag the root cause).

### Parallel execution

This project does not currently use `pytest-xdist`. If it is added later,
the per-test timeout still fires per worker, but worker accumulation is
still possible if many tests deadlock simultaneously. The timeout
shortens the wait but does not eliminate the failure mode — keep the
process-count check in step 2 above.

### Template wiring tests

When a task touches Jinja2 templates, source-string grep tests are
insufficient — Python-syntax-inside-Jinja errors (list comprehensions,
walrus, f-strings, etc.) slip through. Include a compile-and-render
test that loads the template via `jinja2.Environment(loader=FileSystemLoader("templates"))`
with a minimal synthetic context and asserts the rendered HTML contains
the expected structure. See MED-047 (filed Task 109) for the calibration
finding and Task 108's `TestAccountDetailTemplateCompiles` for the
reference pattern.

**Jinja2 nested-comment gotcha (Task 121 + Task 122 reinforcement):**
`{# ... #}` blocks do not nest. An inner `{# #}` closes the outer
block, leaving the remainder of the docstring as live template code
which usually fails with `UndefinedError` on the first identifier the
parser hits. Compile-render the macro file via
`jinja2.Environment.get_template(path)` BEFORE committing — the
failure is silent at file-level greps but loud the moment the template
is loaded. Same discipline applies to template-touching primitives
(`templates/primitives/`).

### Test isolation from live operator data (v2.7 Task E)

The suite runs in the SAME working tree as the operator's live
`data/` directory. Three standing mechanisms keep tests off it:

1. **Lifespan gates in `main.py`** — under pytest (`"pytest" in
   sys.modules`) the app lifespan SKIPS the SQL/data migration
   runners and `start_background_tasks()` (15 live schedulers with
   real API keys), and the rotating JSON log handler is not attached
   to the root logger. `main.TEST_LIFESPAN_GATED` flips True when the
   gates fire; `tests/test_routes.py::TestF5IsolationPins` pins all
   three. Do not add lifespan steps that touch `data/` outside these
   gates.
2. **Singleton rebinds at fixture time, not config patches.**
   `DatabaseManager` bakes `config.DB_PATH` at construction — in a
   full-suite run an alphabetically-earlier import constructs the
   singleton BEFORE any module-level `config.DB_PATH` patch runs, so
   such patches silently isolate nothing (the original F5 finding).
   Rebind the singleton's `path` ATTRIBUTE (see test_routes' client
   fixture) or instantiate your own `DatabaseManager(path=...)`.
3. **Conftest guards + tripwire** — runtime-resolver patches guard
   the per-account event logs, the correlation-log dir, and
   `core.audit`'s hardcoded live path; a SESSION-scoped tripwire
   hashes the live DB files + engine logs and raises a pytest
   WARNING naming any file whose CONTENT changed during the run.
   Treat that warning as a finding (unless the live engine was
   running alongside the suite — the message disambiguates).

**Do NOT re-attempt a session-wide `config.DATA_DIR` redirect**: it
was tried and broke 36 tests (many tests read OTHER live DBs off
`config.DATA_DIR` at runtime; an empty tmp gives `OperationalError`)
— recorded in `tests/conftest.py::_isolate_live_per_account_logs`'s
docstring. Full synthetic-data-dir isolation would first need a
seeded split-DB layout; until then the surgical guards above are the
supported shape.

### Fresh worktree / clone: red suite → provision data/ first

A fresh worktree fails ~110 tests (`no such table: account_settings` /
`pre_trade_log` / `engine_events` / `trade_events`): its `data/` lacks
the split layout (`.split-complete-v1` marker + global/per_account
DBs), so `db_router.split_done()` sends every resolver to an empty
legacy fallback. NOT a regression — do not file findings off it. Run

```
.venv/Scripts/python.exe scripts/provision_test_env.py
```

once (refuses primary checkouts and live-shaped data; `--wipe` to
reprovision), then run the gate with the `.venv` interpreter —
user-site Python lacks `pytest-timeout`, so the 30 s guardrail
silently vanishes there. Verified parity: worktree gate == main-tree
gate (4092/7/3, 2026-07-21). The script also PREVENTS the fresh-DB
credential seeds from materializing real `.env` keys (`config`
attr blanking + scrub verification — an independent audit caught the
seeds re-encrypting live keys into provisioned DBs via `load_dotenv`'s
parent-directory walk). Read its docstring before modifying either
seed path in `core/database.py`.

### Schema-change trap: executescript runs before ALTER (v2.7 P1)

Indexes (or any statement) referencing ALTER-added columns must live
in the post-ALTER block of `database.initialize()`, NEVER inside
`_CREATE_STATEMENTS` — `executescript` runs first, so a legacy-shaped
DB (fresh per-account shadow DBs are exactly that) dies at boot with
"no such column". Pinned by `test_initialize_upgrades_legacy_shaped_db`.

### Deviations belong in plan executed-notes, not only commit bodies

When implementation deviates from a plan row (shape, count, mechanism),
annotate the PLAN ROW in the same commit ("shipped-state note: X
instead of Y because Z"). A deviation recorded only in the commit
message rots invisibly — the next session re-reads the plan, not the
log (the v2.7 holistic audit filed F13 for exactly this: two P2 plan
rows contradicted shipped state until Task D annotated them).

### Audit-time environment verification

Browser-driven audit sessions (Claude in Chrome, Cowork, or similar)
MUST verify engine reachability before filing findings. A 503 /
connection-refused cluster across multiple endpoints is almost always
an audit-time artifact — engine stopped, restarted mid-session, or
unreachable from the browser-driver — NOT an engine bug.

Pre-flight check before opening sub-tab navigation:
1. Hit `/` (or any cheap page-load endpoint) and confirm a 200 + valid
   HTML response.
2. Confirm at least one fragment endpoint resolves with 200 (e.g.,
   `/fragments/ws_status` or whichever fragment the audit prompt
   exercises first).

If endpoints start 503ing mid-session: HALT and surface the
observation to the operator before filing any 503-based findings.
"Engine appears unreachable — please confirm engine is running"
is the right next action.

**Background:** Task 127 reconciled audit-02 Session A and filed
FE-CRIT-002 (Analytics 7/8 sub-tabs return 503) as a real bug. Task 128
discovered post-operator-verification that the engine was stopped
during Session A. FE-CRIT-002 was retracted as VERIFIED-FALSE and
FE-HIGH-007 (the downstream htmx-error-handling finding driven by the
503 cluster) was reframed to MED-tier (FE-MED-019). Cost: one full
reconciliation task spent on a false-positive cluster, plus a brief
push-to-origin freeze on v2.4.3 while the CRIT was investigated.
This discipline addition is the guardrail against recurrence —
audit-time-artifact is a new false-positive class alongside
race-framing FPs (8/15 ≈ 53%) and audit-impact-imprecision.

### Audit-doc source documents

Audit / inventory tasks that reference external source documents
(audit reports, planning notes, screenshots) must commit those source
documents in the same commit. References to docs outside the repo
dangle and degrade traceability. Task 107's frontend-audit merge
referenced `docs/audits/2026-05-18-v2.4-frontend-audit-01.md` but
didn't commit it; Task 108 had to backfill the file. Don't repeat.

### Post-primitive-migration sweep

When a primitive migration renames or removes CSS classes, JS
callsites that query the old class drift silently — template wiring
tests pass (correct render output) while runtime behavior breaks
(clicks don't update state, selectors return empty NodeLists,
visual cross-clearing stops working). Compile-render assertions
catch Jinja syntax bugs (MED-047), not stale JS selectors.

After any class-renaming migration, grep the codebase for the OLD
class names — across JS, inline `<script>` blocks, HTMX attrs, and
any `static/` assets. Don't trust template wiring tests alone. The
rename catches the template; the JS drift is invisible to template
tests.

Practical checklist when renaming or removing a CSS class:
1. Grep the old class name across `templates/`, `static/`, inline
   scripts (`<script>` blocks inside templates).
2. Check `querySelector`/`querySelectorAll`/`classList.*`/
   `getElementsByClassName` calls — those are the executing
   callsites that depend on the old name.
3. For each surfaced callsite, update to the new selector AND
   verify the semantic intent still holds (the new class may live
   on a different element, requiring a different selector path —
   e.g., `.foo` on a button became `.bar` on the wrapper).
4. Anchor-comment any non-obvious selector with the migration's
   task reference so future maintainers can trace.

**Background:** Task 125 migrated Regime's global signal-card range
selector to the PeriodSelector primitive, renaming the button class
from `.global-range-btn` to `.preset-btn` (under a `.global-range-
group` wrapper). Two JS callsites — `setCardRange` and
`setAllCardRanges` in `templates/regime.html` — still queried the
dead `.global-range-btn` class. Visual cross-clearing (per-card
override clears global active state; clicking a second global
clears the first) silently stopped working. Surfaced 11 tasks later
during Task 136's orthogonality investigation (commit `cd367c8`).
Task 137 swept the other 4 Bundle A primitives (StatusIndicator,
Card, TableRow, EmptyState) — no further drift. This discipline
is the guardrail against future regressions of the same shape.

### In-flight Phase cleanup — don't extend the pattern being removed

When a Phase-N cleanup task is in flight (refactor removing pattern X
across the codebase), in-flight Phase-M tasks must not extend
pattern X. Task specs for parallel work should explicitly forbid the
pattern being removed.

The asymmetry: refactor tasks complete a finite set of known sites;
feature work introduces new sites. If feature work adds sites
faster than the refactor removes them, the cleanup never converges.

Practical checklist when starting a feature task during a Phase-N
cleanup:
1. Identify the pattern being removed (`db._conn` direct access,
   inline `<style>`, raw `<button>` outside StatusIndicator, etc.).
2. Confirm the task spec forbids the pattern; if it doesn't, ask
   before introducing new sites.
3. When the task naturally needs a similar operation, route through
   the public helper / primitive being established by the cleanup.
4. Anchor-comment any deliberate use of an old pattern with
   justification — "intentional, see Task X spec" — so future
   refactor sweeps can distinguish drift from legitimate use.

**Background:** Task 139 introduced 3 new `db._conn` direct-access
sites in `api/routes_calculator.py` (the PENDING-state fix for
FE-HIGH-009) during the active Phase 6 `db._conn` cleanup. Task
144's broad re-grep surfaced these mid-Phase-6, requiring scope
extension to cover them. Spec did not forbid the pattern; the
introduction was inadvertent. Tasks 142 + 143 had locked in the
"public helper, no `db._conn`" convention by then, so the right
shape was discoverable — just not specified. This discipline closes
that gap for future Phase-N work.

Related: audit-inventory-incomplete pattern in the audit doc
(`docs/audits/2026-05-17-v2.4-backend-audit.md`). The same
broad-re-grep discipline catches both "audit missed sites" and
"in-flight tasks added sites." Two failure modes, one detection
mechanism.

### Re-investigation discipline — verify mechanism before applying recommended fix

Audit / spec filings name a mechanism (race, shutdown, precedence, etc.)
and propose a fix. Both can be wrong while the bug-as-reported is real.
Read the filing for the symptom; investigate the mechanism
**independently** before scoping the fix. Don't pattern-match the
filing's framing onto the recommended remediation.

Practical checklist when starting a fix task:

1. Reproduce or pin the symptom from the filing.
2. Trace the actual call path / data flow / scope rules that produce
   it. Don't assume the filing's mechanism is correct.
3. If the investigated mechanism diverges from the filing's, FIX THE
   INVESTIGATED ONE — not the one the filing proposed remediation for.
   The recommended fix is a hypothesis, not a contract.
4. Report the divergence: update the audit doc with the corrected
   mechanism + increment the audit-impact-imprecision counter.
5. The corrected-mechanism fix is usually smaller, more surgical, and
   has fewer regression surfaces than the spec-recommended one.

**Calibration examples** (audit-impact-imprecision pattern, 10 examples
as of v2.7 Task E):

- **Task 139 (FE-HIGH-009)**: filing framed Calculator countdown bug
  as semantic-tracking mismatch ("widget tracks last-submitted calc
  rather than current form"). Investigation found the actual
  mechanism was event-bus-publish-vs-htmx-load race causing the
  FIRST poll to render terminal EXPIRED. Single PENDING-state fix
  closed both FE-HIGH-009 + FE-MED-030 — the spec's per-widget
  tracking semantics never needed to change.

- **Task 151 (FE-MED-034)**: filing framed `_user_data_loop`
  UnboundLocalError as a shutdown race ("cancelled during shutdown
  before app_state is initialized"). Investigation found the actual
  mechanism was Python local-shadow caused by a redundant inline
  `from core.state import app_state` inside an except branch (the
  module-level import already provided the binding). Fix was a
  one-line deletion of the inline import, NOT the spec's proposed
  init+nil-check shutdown-defense.

- **Task 152 (FE-LOW-024)**: T138 filing cross-linked the finding with
  FE-MED-021 + FE-LOW-022 as "centralized number-formatting helper
  family" — implying `format_price` would close all three.
  Investigation: FE-LOW-024's mechanism is a display-layer **sanity
  clamp** (`abs(percent) > 100` → render `>100%`), not per-symbol
  formatting. No helper closes it; the fix is a JS `fmtPct` clamp.
  The audit grouped by surface symptom ("noisy number display")
  rather than mechanism. **Pattern**: when a filing tags a finding
  cluster as "family", verify mechanism overlap before trusting the
  leverage claim. Loose "same family" tags are hints, not proofs.

- **v2.7 Task E (F5)**: filing recommended "session-scoped DB/DATA_DIR
  binding before any singleton import". Investigation found the
  session-wide redirect EMPIRICALLY tried-and-broken (36 read-coupled
  tests, recorded in conftest's own docstring) and that binding order
  doesn't cure empty-tmp read coupling. Shipped the surgical shape
  instead: singleton `path` rebind at fixture time + pytest lifespan
  gates + resolver guards + a content-hash tripwire. The filed
  SYMPTOM (live-DB exposure) was fully real — live per-account DB and
  both engine logs were observed changing mid-gate the same day.

**Implication for fix-task specs**: when a spec lists a recommended
fix, treat it as auxiliary information. The fix-task report should
explicitly note when the investigated mechanism differs from the
filed one, so the calibration record grows. If the recommended fix
turns out to be wrong shape, the task summary should explain why —
that's the operator-facing trace of the pattern's strength.

**Anti-pattern**: applying the recommended fix without investigation,
then discovering the bug isn't fixed (or worse, a different bug is
introduced because the wrong site was touched). The cost of a
30-minute re-investigation is small compared to a partial fix that
ships and decays. Prefer slow + correct over fast + speculative.

### Deviation discipline — explain "X instead of Y because Z"

Task specs frequently list multiple candidate fix shapes (Option A /
B / C) or carry implicit assumptions (e.g., "per-symbol tick-size
lookup", "Show details toggle"). When implementation deviates from
what the spec lists or assumes, the deviation is almost always
defensible — but if the reasoning lives only in your head (or only
in a "latent obs" footnote), the operator has to reverse-engineer
why you took the path you did.

**Practical rule**: in the task report's *Fix shape* section, write
"X instead of Y because Z" — not just "X". The deviation and the
reason go in the same sentence, in the load-bearing section, not
buried in a latent-obs aside.

Examples that triggered this discipline:

- **Task 152 (format_price spec deviation)**: spec described
  `format_price(symbol, value)` with adapter-spec tick-size lookup
  for sub-$1 prices. Implementation shipped magnitude-only
  (no symbol arg, no tick-size dependency). Reasoning was sound
  ("tick-size adds adapter-metadata coupling without proven
  benefit for audit-cited examples") but lived only in the commit
  message body. Operator had to infer from the absence of the
  symbol parameter.

- **Task 153 (Show details toggle deviation)**: spec recommended
  "wrap error messages with friendly prose + optional 'Show
  details' expand". Implementation shipped always-visible dim
  second line (no toggle). Reasoning ("5s toast auto-dismiss makes
  click-to-reveal impractical; always-visible respects diagnostic
  need without adding interaction complexity") landed in the
  T153 latent-obs section, not the Fix-shape report.

- **Task 149 (LOT button visibility, click-to-copy)**: spec said
  per-field click-to-copy on Setup Summary; implementation also
  hid the LOT button on non-commodity tickers (out-of-scope
  addition) on the grounds it was dead-aliased to contracts.
  Defensible cleanup but the *why* (LOT is contracts in disguise
  on crypto pairs) only surfaced when the test class probed for
  it during T149 implementation, not when the spec was scoped.

**Anti-pattern**: shipping a defensible deviation without naming
it. The implementation may be correct, but the operator's mental
model of "what the spec asked for vs. what shipped" diverges
silently. Future tasks that re-read the spec will be surprised by
the codebase state.

**Symmetric rule for the operator side**: when a spec lists Option
A / B / C without picking, the report should name the chosen
option AND the one-line rationale ("Option B: server-side N=5s
timeout — htmx-native idiom over client-side setTimeout because
no inactive-tab throttling concern", T146 did this correctly).
When a spec implies a fix shape via wording (e.g., "tick-size
lookup", "Show details toggle"), the report should either confirm
that shape OR call out the deviation explicitly.

### Deployment context (settled 2026-05-24, Task 163)

**Single-tenant local.** The engine binds to localhost only; no
external exposure (no LAN access, no cloud, no multi-tenant). Auth,
CSRF, CSP, SRI hardening, and similar exposure-driven hardening
work are **not required** at this deployment shape.

What this changes in the audit ledger:
- **HIGH-001** (no API authentication) — closed / not-applicable.
  Re-open trigger: any deployment change that exposes the engine
  beyond localhost.
- **Phase 7 remainder** (MED-040 SRI, MED-041 CSP, LOW-001 ticker
  regex) — downgraded to opportunistic. Real findings, but not
  audit-cycle priority work at this deployment shape.
- **MED-023** (empty PLATFORM_TOKEN bypass) — CLOSED / not-applicable:
  v2.6 removed the Quantower plugin, its `/api/platform` routes, and
  `PLATFORM_TOKEN` entirely, so the bypass no longer exists.

Future tasks SHOULD reference this section before doing
exposure-driven hardening. If the deployment context changes,
update this section + re-elevate the deferred items.

The threat model is now: corrupt local state, faulty exchange
adapter, miscalibrated math, silent data drift. Auth is not the
operative concern; **correctness + observability + recovery** are.

### Live-DB dry-run before any destructive --apply (Tasks 193, 194)

Development-time tests + audit passes catch a lot of bugs, but they
can't catch every real-data-shape class. Phase 0.0's six development
audits found three BLOCKER-class issues (T184, T187, T191) — all
ultimately structural and reachable in tests. Then running the
cleanup tools against the live DB surfaced TWO MORE production bugs
that only manifest with real data:

- **T193** (`dedup_fills.py`): the dedup rule wrongly collapsed
  Binance matching-engine splits (sequential tradeIds, same source,
  identical data). Development tests used synthetic fixtures that
  didn't include the matching-engine-split shape. Caught only because
  the live-DB dry-run output showed `binance_ws` rows being marked
  for deletion.
- **T194** (`rebuild_closed_positions.py`): the rebuild would wipe
  closed_positions rows for "orphan symbols" (symbols with rows but
  no usable fills — pre-Phase-0.0.2 backfill artifacts). Development
  tests didn't include this asymmetric shape. Caught only because
  the live-DB dry-run output showed `rebuild=0 vs existing=N` for
  ~19 symbols.

Both would have shipped silent data loss if the operator had run
`--apply` without inspecting the dry-run first.

**Discipline**: for any destructive operator script that mutates the
live DB on `--apply`:

1. **Default to `--dry-run`**. Make `--apply` an explicit opt-in.
2. **Print the planned changes verbatim in dry-run**. Counts alone
   are insufficient — the operator + the auditing assistant need to
   see WHICH rows / WHICH fills / WHICH symbols to spot
   misclassifications.
3. **ALWAYS run dry-run against the live DB before `--apply`**, even
   if the dev-time test suite is green. The dry-run is the last
   real-data check; treat it as a mandatory step in the operator
   workflow.
4. **Read the dry-run output critically.** Look for shapes the
   dev-time tests didn't cover: same-source pairs, asymmetric
   patterns (rows on one side without counterparts on the other),
   N-fold inflations or deflations vs expectations. Anything
   surprising = stop and investigate.
5. **When a live-DB-only bug surfaces, fix the script + add a
   regression test** for the shape that surfaced it. Then re-run
   dry-run. Then `--apply`.

This is the discipline that turned Path A from "shipped data loss"
into "shipped clean cleanup". Apply it to any future destructive
operator script (`scripts/dedup_fills.py`,
`scripts/rebuild_closed_positions.py`, future migration scripts,
etc.).
