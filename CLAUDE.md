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
