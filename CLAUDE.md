# CLAUDE.md — Working Discipline for the Quantamental Engine

This document captures the working discipline established during the v2.3.1 audit. Read it before non-trivial work on this codebase. It exists to make future audit cycles faster and to prevent rediscovering hard-won patterns from scratch.

## Project Context

The Quantamental Engine is a personal trading risk engine — semi-institutional data pooling, real-time portfolio monitoring, regime-aware risk management, and backtesting. It integrates with exchanges (Binance, Bybit; MEXC planned) and a Quantower platform plugin. Single-developer codebase; production reliability matters because real positions depend on it.

Tech stack: Python, FastAPI, HTMX, SQLite, ccxt, asyncio. v2.4 will add Redis pub/sub and WebSocket push.

## Architecture: Core + Adapter Ring

Every external connection is an adapter. The engine core is broker-agnostic; broker-specific code is CONFINED to the adapter layer.

Adapters exist for:
- Exchanges (binance, bybit, soon mexc)
- Platforms (Quantower plugin via platform_bridge)
- Data sources (regime_fetcher, ohlcv_fetcher — both went through adapter migration in the audit)

When adding a new external integration: it MUST be an adapter. If it doesn't fit the existing adapter protocol, extend the protocol — don't add broker-specific code in the core.

See `docs/adapters/binance.md` and `docs/adapters/bybit.md` for current maintenance interfaces.

## The Working Cycle: Find → Design → Fix → Verify

### Four-phase workflow

- **Phase 1 (Diagnose)**: read-only investigation. Identify root cause. No code changes.
- **Phase 2 (Design)**: propose fix shape, identify tradeoffs, write brief design doc.
- **Phase 3 (Migration)**: rarely needed; data model changes that need migration scripts.
- **Phase 4 (Implement)**: tests first, then implementation, then verification.

Skip phases when scope is clear. Direct-to-Phase-4 is fine for known-shape fixes (e.g., AD-4 pattern applied to a new domain). Add Phase 2 when there are real design decisions (retry semantics, semaphore sizing, etc.).

### One finding per branch, atomic commits

- Branch naming: `fix/<finding-id>-<short-description>`
- Atomic commits per finding (one commit per bug, even if batched)

### Stop and report at each commit

After every commit:
1. Summarize what was implemented (concise)
2. Note suite status (N/N green)
3. Note smoke-diff result (empty or expected changes)
4. Wait for review before proceeding to next finding

Do NOT chain through multiple commits silently. Each commit is a checkpoint for both implementer and reviewer judgment.

### Pre-phase gate

Before any code-modifying implementation phase:
- Engine must be stopped (no live process holding state)
- Long-running processes can hold stale code in memory; running on stale code masks bugs

Read-only investigation (Phase 1) does NOT need pre-phase gate.

## Phase 1: Diagnostic Discipline

### Auto-resolution check (standard)

Every Phase 1 starts with: "Did any audit fix between this finding being filed and now coincidentally resolve it?" Many findings auto-resolve through compounding work. Check before designing a fix for a problem that may no longer exist.

### Enumerate all causes before settling on one

When investigating a symptom, identify ALL plausible causes. Pick the most likely for the proposed fix, but list the others. "I found a cause" is not the same as "I found THE cause."

If a fix lands and the symptom persists, the diagnostic was incomplete — return to enumeration.

### "Would the user's full reported symptom be resolved?"

Phase 1 closing question. If the proposed fix doesn't cleanly predict every observed symptom, the diagnosis isn't done.

Example: FE-17 round 1 found `_livePrice = 0` blocks submit (real bug). But "second click works" wasn't explained by that fix alone. Asking the question revealed there was more.

### Layer-progressing vs layer-stuck iteration

When multiple diagnostic rounds happen, distinguish:
- **Layer-progressing**: each round eliminates a layer of possibilities. Keep going.
- **Layer-stuck**: each round finds another bug at the same layer without narrowing. Stop and defer.

Diminishing-returns thresholds apply to stuck iteration, not progressing iteration.

### Hypothesis-driven instrumentation

When direct code inspection isn't enough, instrument:
1. **Broad observation** — log everything in the chain
2. **Specific hypothesis** — based on observation, propose what's happening
3. **Falsifying instrumentation** — log specifically to test the hypothesis

If step 3 falsifies the hypothesis, return to step 2 with new evidence. If it doesn't falsify, fix is in hand.

### Trust user observations, verify severity independently

Users report what they see. Don't dismiss as "user error" without investigation. But also don't accept the user's framing of severity without independent assessment. "User reports a small thing" is a starting point for severity investigation, not the final severity.

## Phase 2: Design Discipline

### Briefly, when warranted

Design docs are short — a few hundred words capturing root cause, fix shape, alternatives considered, LOC estimate, tradeoffs.

Skip Phase 2 when:
- Fix shape is obvious from Phase 1
- Pattern is established elsewhere
- Total scope is <30 LOC

Add Phase 2 when:
- Real design decisions exist (retry semantics, sizing constants, tradeoffs)
- Pattern is novel to the codebase
- Multiple subsystems are affected

### Watch items for sub-enumeration uncertainties

When authorizing batched work or scope-uncertain fixes, flag any sub-enumeration uncertainty as a watch item:
- "If X turns out to need a new endpoint, PAUSE and report"
- "If Y data doesn't populate as expected, PAUSE and report"

Watch items are conditional triggers that activate during implementation. They prevent silent scope absorption.

### Scope-contraction is also a failure mode

User reports often describe one instance of a broader pattern. Before authorizing a narrow fix, ask: "Is this finding's natural scope wider than the report suggests?" FE-16 was framed as "tab indicator flicker on positions tab" but the actual issue applied to multiple tab bars — narrow framing led to incomplete fix.

## Phase 4: Implementation Discipline

### Tests first

For non-trivial fixes, write the failing test FIRST. Test specifies expected behavior; implementation makes it pass.

Label-only changes, CSS adjustments, or display-only fixes may skip tests — judgment call.

### Smoke-diff against pure-math baseline

The smoke baseline (`data/smoke_baseline.csv`) is pure-math: sizing, ATR, slippage, VWAP, analytics. After any fix:
- Run smoke
- Diff against baseline
- Empty = no regression in baseline-exercised math
- Non-empty = expected behavior change (verify it matches) OR regression (investigate)

**Important limitation**: baseline is pure-math, not DB-dependent. Database-mutating fixes won't produce smoke-diff signal even when behavior changes. For those, regression tests + operational verification are the detection mechanism.

### Commit messages

Include:
- Root cause (concise)
- Fix approach
- Cross-references (related findings, design docs)
- Verification plan (especially for event-dependent fixes)

## Verification Discipline

### Structural correctness ≠ operational confirmation

Static analysis is necessary for many fixes. It is NOT sufficient as proof of resolution.

"This template is not inside an HTMX swap container, therefore it cannot exhibit HTMX-swap flicker" is true, but it doesn't mean the template never flickers — CSS animations, JS state, browser quirks can cause flicker independently.

When a fix is justified by structural analysis, verification needs to be operational. Restart the engine, observe actual user-visible behavior, compare to pre-fix.

### Differential verification by change type

- **Pure refactors**: 1-2 hour smoke
- **Behavior changes**: 6-12 hours operational + smoke-diff matches expectation
- **Event-dependent signals**: verify on next natural occurrence; don't block on artificial events

### Verification gaps to watch

- DB-dependent fixes don't show in smoke-diff (use targeted regression tests)
- Event-dependent fixes can't verify until events occur (note as "verification accumulating")

## Architectural Principles

### Core + adapter ring

Every external connection is an adapter. Core engine knows nothing about specific exchanges, platforms, news feeds, or ML models. If something doesn't fit, extend the adapter protocol — don't break the boundary.

### Vendor-neutrality in the protocol

Adapter protocol uses neutral types: `NormalizedPosition`, `RateLimitError`, etc. Vendor-specific names get normalized at the adapter boundary.

### Adapter-boundary normalization makes downstream code look simple

If downstream code has a single-field check where you expected multi-field logic, that's often a sign the adapter is doing its job — normalizing complexity at the boundary so consumers don't have to.

### Defensive code should actually defend

`if not pos_dir:` doesn't catch `"BOTH"` (truthy string). Explicit sentinel checks (`if pos_dir == "BOTH"`) preferred when failure modes involve specific values, not just falsy values.

### Don't conflate distinct concerns

Two issues that look similar may be distinct. PA-1 was two separate bugs (WS event miss + position split heuristic). Same outer symptom, different root causes, different fixes.

### Fixes can have implicit dependencies

Timing code, in particular, often does multi-purpose double duty. The setTimeout(100) in FE-2 served two purposes (delay submit, allow HTMX to settle) — only one identified at fix time. When removing or changing timing code, check ALL execution paths that pass through it, not just the path being fixed.

## Documentation Discipline

### Capture before context fades

After deep investigation, the cheapest moment to capture learnings is right after the investigation ends. Five minutes of writing now saves five days later.

### Verified / Listed / Assumed for adapter docs

When documenting an adapter:
- **VERIFIED** (date): tested against live API or used in audited code
- **LISTED** (date): present in code but not exercised during audit
- **ASSUMED**: inferred from docs/introspection, not verified

Honest tagging prevents future readers from over-trusting unverified claims.

### Function names over line numbers

Reference functions by name, not line number. Line numbers go stale fast; function names are durable.

### Maintenance log for credibility

Any "Last reviewed: <date>" claim should be backed by a maintenance log. Without history, the date is just a number and ages into mistrust.

### Cross-check canonical docs over inferred knowledge

When integrating with an external API:
- Fetch canonical docs directly
- Don't infer from docs page URLs (URL structure ≠ API path)
- Test against live API before committing implementation
- Verify each surface (REST endpoint, WS event, response shape) independently

## Communication Discipline

### Stop and report at checkpoints

Each commit is a moment for multi-layer judgment. Reviewer expectations being wrong is healthy — multiple judgment layers doing their work.

### Watch items as explicit triggers

When authorizing batched work, name the conditions under which implementation should pause. Don't rely on the implementer to notice scope expansion silently.

### Be honest about iteration counts

When a finding has had multiple diagnostic rounds, say so. "This is round 3, threshold for deferring to v2.4" is the kind of explicit accounting that protects against indefinite iteration.

### Distinguish confidence levels

When asserting a claim:
- Verified (tested, observed)
- Likely (based on evidence)
- Possible (consistent with available info)
- Speculative (would need investigation)

Mixing these creates false confidence.

## Common Patterns (Reusable)

### Multi-field deterministic check over single-field heuristic

When classifying things (order type, is_close, etc.), prefer multi-field deterministic checks:
- Bad: `if order_type == "STOP_MARKET": classification = "stop_loss"` (misses entry stops)
- Good: `if reduce_only or close_position: classification = "stop_loss" else: "stop_entry"`

### Idempotency for retry safety

If a callable might fire multiple times, make it idempotent. Use exchange-native IDs as deduplication keys.

### Snapshot isolation for parallel data flows

When multiple data sources update the same model (basic orders + algo orders), use prefix-based or other isolation so snapshots from one source don't invalidate data from another.

### Auto-resolution check on every Phase 1

Before designing a fix: "Did any audit fix since this was filed already resolve it?"

## Common Anti-patterns (Avoid)

### Absorbing scope mid-fix

If a fix turns out larger than estimated, PAUSE and re-classify. Don't quietly absorb scope creep.

### Single-field heuristic for multi-field problem

`realizedPnl != 0` for is_close fails on break-even closes. Multi-field deterministic checks are usually available — use them.

### Trusting enumeration without verification

Phase 0 enumeration claims about external APIs need verification. AD-2/3/4 enumeration was wrong about Bybit's API surface on 2 of 3 findings.

### "Structurally not affected" treated as "operationally clean"

Static analysis is necessary, not sufficient.

### "WS not handled" can mask "WS not subscribed"

When adding WS event handlers, verify the subscription topic exists too. Engine may not be receiving events in the first place.

### Indefinite iteration on a stuck layer

Three rounds at the same layer without narrowing is the threshold to defer.

## References

- `docs/audit/AUDIT_CLOSEOUT.md` — Audit v2.3.1 closing synthesis
- `docs/adapters/binance.md` — Binance adapter maintenance interface
- `docs/adapters/bybit.md` — Bybit adapter maintenance interface
- `docs/past/` — Historical audit artifacts
- `README.md` — Project landing page

---

This file is subject to maintenance. When new patterns emerge or existing ones prove insufficient, update it. The discipline only persists if the discipline document persists.
