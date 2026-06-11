# Correlation Log — Implementation Plan

**Status**: design rev 2 — audited (4 adversarial agents, 2026-06-10), pending implementation
**Created**: 2026-06-10
**Branch**: `v2.5/correlation-log`
**Spec**: [correlation_log_spec.md](correlation_log_spec.md)

This plan phases the build of the correlation log (spec §1). It is ordered so
the **spine ships and is proven before any tap depends on it**, and the
**highest-value taps (attribution decisions, spec §5.6) are reachable as
early as the spine allows**. Whole-engine coverage; NDJSON sink; daily
rotation, 7-day retention.

**Rev 2** incorporates the 4-agent audit: corrected Phase-3 dependencies
(bus-reached taps need the bus carry), split the oversized tasks (T2 →
T2a/T2b for the independently-revertable bus diff; T3b → entry/close/scenario
slices), corrected tap-site file lists (matcher lives in
`calc_correlation.py`/`order_enrichment.py`), added the missing boundary work
(platform WS, news WS, WS lifecycle, outbound-HTTP, pubsub, db_write,
orders-table taps), the category registry, the falsifiable perf gate, and
the known-bug replay acceptance.

---

## 1. Phasing rationale

Phases are ordered by **dependency** then **leverage**. The critical path is
**Phase 0 → 1 → 2a → 3** (spine → entry-point minting → bus carry → taps).
Phase 3 carries the payoff (attribution-decision taps). Phases 4–5 are the
reader surface + hardening/audit.

```
Phase 0: Spine (contextvars + envelope + registry + sink thread + config + isolation)
  │   no taps yet — proven in isolation
  │
  └─> Phase 1: Entry-point corr_id minting (HTTP mw, ALL WS streams, loop scopes,
        │       WS frame taps + WS connection-lifecycle taps)
        │
        ├─> Phase 2a: event_bus carry/re-bind + bus taps (isolated, revertable)
        │     │
        │     ├─> Phase 2b: REST + outbound-HTTP + pubsub taps, webhook-queue carry
        │     │
        │     └─> Phase 3: Internal taps (state/DB/orders + ATTRIBUTION §5.6)  ← the payoff
        │           (needs 2a: calc transitions fire inside bus subscribers)
        │
        └─> Phase 4: Reader (corr_tail.py + jq cookbook) — can start after Phase 1
              │
              └─> Phase 5: Volume tuning + perf gate + holistic audit + bug-replay check
```

Effort tiers: **S** (≤2 days), **M** (3–7 days), **L** (>7 days). The whole
program is **M–L** (**12 tasks**, §9.2). Each task = one commit, green +
audited before the next (CLAUDE.md "commit each task as soon as green +
audited"; the dev-environment mid-run-mutation hazard makes small frequent
commits load-bearing).

**Guiding constraints (from the spec):**
- Emission is **non-blocking**; never stall the WS path or bus dispatch (D7).
  The drain is a **dedicated writer thread** (D16/Q2) — not a coroutine.
- **Every queue hand-off carries corr_id** (D6): the bus (Phase 2a) and the
  webhook dispatcher's internal queue (Phase 2b).
- **Secret redaction** centralised in the sink (D10) — landed in Phase 0,
  exercised at every tap.
- **Volume control** is mandatory (D12) — registry groups + profiles land in
  Phase 0; on-change gating for refresh-driven taps lands with those taps.
- **No silent exits** on attribution taps (D17) — SKIPPED/ERROR outcomes are
  part of each tap's definition, not an afterthought.

---

## Phase 0: Spine

**Goal**: the correlation-log core — corr_id contextvar + mint/scope, the
envelope builder with the §6.1 pipeline order, the **category registry with
groups** (drift defense), the writer-thread sink (date-stamped NDJSON, daily
rollover, prune, per-day MB guard, overflow drop+count), config knobs +
derived profiles, secret redaction, and test isolation. **No boundary taps
yet** — the spine is proven standalone.

**Dependencies**: none.

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 0.1 | `corr_id_var: ContextVar[str]` + `mint(prefix)` + `correlation_scope(prefix)` ctx-mgr + `current_corr_id()` | `core/correlation_log.py` (new) (or `core/correlation.py` per spec Q1) |
| 0.2 | **Category registry**: module constants, each registered with a group (`http`/`market`/`lifecycle`/`state`/`attr`/`bus`/`ws_lifecycle`/`outbound`/`db`); profiles **derived** from groups; `enabled(category)` lookup | `core/correlation_log.py` |
| 0.3 | Envelope builder + `emit(component, peer, direction, category, payload, *, account_id=None, symbol=None)` — **pipeline order per spec §6.1**: enabled-check FIRST → envelope (ts, atomic `seq`, corr_id, `task` via the §4 try/except resolution rule, account/symbol) → redact + `json_safe` + ONE `json.dumps` (the line string; doubles as size-cap measurement; emit-side = mutation snapshot) → `SimpleQueue.put_nowait(string)` | `core/correlation_log.py` |
| 0.4 | Sink: **dedicated daemon writer thread** — blocking `get(timeout=0.25)` then `get_nowait()` drain, batched buffered append; date-stamped `corr-YYYY-MM-DD.jsonl`; UTC rollover (close+open, NO rename); prune at startup + rollover; **per-day MB guard** (`CORR_LOG_MAX_MB_PER_DAY`); overflow = drop + count + rate-limited `logging.error` + recovery marker envelope (**NOT engine_events** — D19). Queue + seq counter **module-level at import** (early emits buffer) | `core/correlation_log.py` |
| 0.5 | Central `_redact()` (deny auth/cookie headers, secret query params, API keys/signatures/listen-keys) | `core/correlation_log.py` |
| 0.6 | Config knobs (§8 table incl. `CORR_LOG_MAX_MB_PER_DAY`) | `config.py` |
| 0.7 | Startup/shutdown wiring: writer thread starts in **lifespan BEFORE `start_background_tasks()`** (not inside `_startup_fetch`'s try-block — spec §6.5); explicit `correlation_log.close()` (sentinel → drain → flush → join) in lifespan teardown (today's teardown cancels nothing, so an explicit call is the only reliable flush trigger); guarded by `CORR_LOG_ENABLED` | `main.py` |
| 0.8 | Test isolation: autouse conftest fixture **patching the sink-dir attribute/resolver on `core.correlation_log`** (NOT the env var — config reads at import; mirror `_isolate_live_per_account_logs`'s resolver-patch approach) | `tests/conftest.py` |

### Tests

`tests/test_correlation_log_spine.py` — split CL.T0a vs CL.T0b (§9.2):

- **T0a (envelope/registry; no file I/O — safe before the 0.8 guard exists;
  T0a leaves `emit` enqueueing with no drain, which is safe because no
  production callers exist until Phase 1):**
  - envelope shape: all fields, correct types, `ts` ISO-UTC, `seq` monotonic;
    `task` captured (asyncio task name; thread name off-loop — both branches)
  - concurrency: two tasks emitting interleaved → distinct `task` values,
    strictly increasing `seq` (atomic allocation)
  - `emit` outside any scope → `corr_id=""` (and flagged)
  - `correlation_scope` mints + resets symmetrically; nested scopes restore
  - `json_safe`: NaN/Inf → null; size cap → `_truncated` summary, never drop
  - redaction: API key / auth header / listen-key absent from output
  - registry: profiles derive from groups; `linkage` excludes market groups;
    unknown category → loud error (conformance precursor)
  - disabled category: emit returns before payload serialization (~lookup
    cost); `CORR_LOG_ENABLED=0` → no enqueue
- **T0b (sink/thread/file):**
  - writer thread drains; file contains well-formed NDJSON in seq order
  - rollover: simulated UTC-date change → new file, no rename
  - prune: older-than-retention deleted (incl. the startup-prune path);
    current kept
  - per-day MB guard: exceeding → stops writing + one marker line + loud log
  - overflow: enqueue past `CORR_LOG_MAX_INFLIGHT` → drop+count, no block;
    recovery marker envelope appears after pressure drops
  - `close()`: queued envelopes flushed, thread joined
  - conftest guard: suite writes land in tmp, never the live dir

### Acceptance criteria

- `emit` is non-blocking and callable from sync + async + thread contexts.
- A standalone test drives `emit` and reads back well-formed NDJSON.
- Rollover + prune + MB guard verified without any `os.rename`.
- Profiles have a single source of truth (the registry groups).
- Suite never writes to the live `data/logs/correlation/` dir.

---

## Phase 1: Entry-point minting + inbound-frame & WS-lifecycle taps

**Goal**: mint + scope a corr_id at **every** true entry point (spec §3.2 —
including the platform WS and news WS the rev-1 plan missed) so downstream
work auto-inherits it; tap the inbound frames; tap the WS **connection
lifecycle** (spec §5.4b — without it the subscription-leak bug class is
invisible); name the ws_manager tasks.

**Dependencies**: Phase 0.

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 1.1 | FastAPI middleware: mint `http-*` per request, set scope, emit `http_request` (redacted) + `http_response` (status, duration_ms; SSE/streaming routes report duration at stream close — spec §5.1) | `main.py` |
| 1.2 | Loop scopes, **blanket rule** ("every spawned root loop body gets a scope" — structural, not a hand-counted 15): all `_spawn`'d loops in `core/schedulers.py`, plus `ws_manager._keepalive_loop` + `_fallback_loop`, `MonitoringService.run`, `webhook_dispatcher.run`, the reconciler periodic pass; `boot` scope on `_startup_fetch` | `core/schedulers.py`, `core/ws_manager.py`, `core/monitoring.py`, `core/webhook_dispatcher.py` |
| 1.3 | Binance WS frame taps: user-data (`wsu-*` per frame; `ws_account_update`/`ws_order_update`/`ws_algo_update` with **dedup_key** `orderId:status:qty`) + market (`wsm-*`; kline/depth/markPrice, volume-gated) | `core/ws_manager.py` |
| 1.4 | **Quantower platform WS** (`wsp-*` per frame at the `platform_bridge` dispatch; `platform_fill`/`platform_snapshot`/`platform_hello` in, `platform_push` out — money-path critical: platform fills feed `process_fill`) + **BWE news WS** (`wsn-*`; `ws_news`) | `core/platform_bridge.py`, `core/news_fetcher.py` |
| 1.5 | **WS connection-lifecycle taps** (spec §5.4b): `ws_connect` (full stream list), `ws_connected`, `ws_disconnect`, `ws_stream_rebuild` (trigger + old→new diff), `calc_symbol_change`, `ws_listenkey_keepalive` — alongside the existing `ws_status.add_log` sites | `core/ws_manager.py` |
| 1.6 | **Name the ws_manager tasks** (`ws-user`, `ws-market`, …) at every `create_task` site **including reconnect respawns** (today unnamed → auto `Task-N`; one logical stream must keep a stable, lineage-readable name) | `core/ws_manager.py` |

### Tests

- `tests/test_correlation_log_entrypoints.py`:
  - HTTP request → one `http_request` + one `http_response`, same corr_id,
    `http-` prefix; secrets redacted; duration recorded
  - synthetic Binance user-data frame → `wsu-` corr_id set during dispatch;
    correct category per event_type; dedup_key present
  - synthetic platform frame → `wsp-` corr_id; `platform_fill` emitted;
    the corr_id is visible from inside a stubbed `process_fill`
  - market frame respects profile (`linkage` → no market envelope; `full` →
    emitted; mark-price sampling honoured; default OFF)
  - scheduler tick → `sch-<name>` corr_id for the tick's duration; fresh per
    iteration; keepalive/monitoring/webhook loops included
  - a REST call inside a scheduler tick shares the tick's corr_id
    (propagation proof, Phase-2-lite)
  - lifecycle: `calc_symbol_change` → `ws_stream_rebuild` with old→new diff;
    `ws_connect` carries the full stream list; reconnect keeps the task name

### Acceptance criteria

- Every §3.2 entry point sets a corr_id with the right prefix — including
  platform and news WS.
- A handler/REST call/bus publish made *during* an entry-point scope inherits
  that corr_id.
- The subscription-leak query (spec §9: `calc_symbol_change` with no
  `ws_stream_rebuild`, or a stream list still containing the old symbol) is
  answerable from a synthetic leak scenario.
- Market-data volume is controllable via profile/sampling from day one.

---

## Phase 2a: event_bus carry/re-bind + bus taps (isolated, revertable)

**Goal**: the bus carries the publisher's corr_id across its consumer task
and emits `bus_publish` + per-handler `bus_deliver` from the **instrumented
dispatch path** (NOT a subscribe_all subscriber — spec §5.2 rev-2
correction). Kept as its own minimal commit so it is independently
revertable (the plan's own rollback requirement — rev-1 self-contradicted by
bundling it).

**Dependencies**: Phase 1 (corr_ids exist to carry).

**Effort**: S–M (the diff is small; the test sweep is the work).

### Tasks

| # | Task | File(s) |
|---|---|---|
| 2a.1 | Queue item `(channel, payload)` → **`(channel, payload, corr_id)`**: capture `current_corr_id()` in `publish`/`publish_engine`/`publish_engine_nowait` | `core/event_bus.py` |
| 2a.2 | Dispatch loop: re-bind `corr_id_var` per event, reset in `finally` (dispatch swallows handler errors — reset must not depend on success); emit `bus_publish` at enqueue + `bus_deliver` per handler invocation (name, ok/err, duration_ms) | `core/event_bus.py` |
| 2a.3 | **Test sweep (scoped, not hand-waved)**: ~10 test files unpack the internal queue as 2-tuples (`test_phase1_calc_cancel/revision/release/expiry/complete`, `test_phase2_junction`, `test_phase5_funding` ×7 sites, `test_phase6_events` — which also drives `_dispatch(channel, payload)` directly). Update all; the 3-tuple fails loudly, which is the desired failure mode | `tests/` (sweep) |

### Tests

- `tests/test_correlation_log_boundaries.py` (bus half):
  - **task-boundary hand-off**: publish under corr_id `X` in one task →
    `bus_deliver` logged with `X` (not empty) from the consumer task
  - a subscriber emitting *during handler execution* inherits `X`; a
    handler-spawned `create_task` also inherits (context copied)
  - handler raises → `bus_deliver` records err; corr_id reset still happens
    (finally), next event unpolluted
  - structural coverage: any publish on any topic → `bus_publish` + one
    `bus_deliver` per registered handler (unit on the instrumented paths +
    representative end-to-end topics; NOT a pinned 21-topic list)
  - existing subscribers (webhook, notifications, reconciler handlers)
    behave unchanged — regression slice

### Acceptance criteria

- Every bus publish + each per-handler delivery is logged with the
  **publisher's** corr_id.
- The change is one small, isolated, revertable commit; the test sweep is
  complete (no 2-tuple unpacks remain).

---

## Phase 2b: REST + outbound-HTTP + pubsub taps; webhook-queue carry

**Goal**: tap the remaining out-boundaries — the venue REST chokepoint AND
the outbound families that bypass it (spec §5.3b: webhook POSTs, Finnhub,
FRED/yfinance) — plus the `core/pubsub` publish chokepoint; carry corr_id
across the webhook dispatcher's internal queue (hand-off #2).

**Dependencies**: Phase 1; 2a for the webhook worker's corr_id to mean
anything (the bus handler is where it's captured).

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 2b.1 | REST chokepoint tap in `_run`: `rest_call` (`out`) before dispatch + `rest_return` (`in`, ok/err, duration_ms, error_type, result-summary) after. **Emit on the loop side only — never inside the executor callable** (`run_in_executor` does not propagate contextvars; spec §3.3 thread rule); ambient corr_id else one-shot `rest-*` fallback | `core/adapters/base.py` |
| 2b.2 | Outbound-HTTP taps (`http_out_call`/`http_out_return`): webhook POST (peer=subscriber, attempt#), Finnhub news/calendar (peer=finnhub), FRED + yfinance callers (peer=fred/yahoo — tap the caller, not yfinance internals) | `core/webhook_dispatcher.py`, `core/news_fetcher.py`, `core/regime_fetcher.py` |
| 2b.3 | **Webhook internal-queue carry**: the bus handler enqueues `(account_id, payload, corr_id)`; the worker re-binds before POSTing so `http_out_call` correlates to the originating close (spec §3.3 hand-off #2) | `core/webhook_dispatcher.py` |
| 2b.4 | `pubsub_publish` tap at the `get_bus().publish` chokepoint (channel kind, backend), **volume-gated** (fires per recalc cycle) | `core/pubsub/bus.py` (or the publish wrapper) |

### Tests

- `tests/test_correlation_log_boundaries.py` (out half):
  - REST call → matched `rest_call`/`rest_return` pair, same corr_id,
    duration; failure path records `error_type`; no API key/signature/
    listen-key in any envelope
  - REST call with no ambient scope → `rest-*` fallback pair (and the
    fallback is counted — it's a missing-scope detector)
  - webhook: position-closed publish under corr_id `X` → worker's
    `http_out_call` carries `X` (the two-hop carry: bus → handler →
    internal queue → worker)
  - Finnhub/FRED taps fire under their loop scopes; pubsub_publish respects
    gating

### Acceptance criteria

- Every venue REST call AND every other outbound HTTP family appears as an
  out/return pair correlated to its trigger.
- The webhook chain stays correlated end-to-end (close frame → bus →
  dispatcher queue → POST).

---

## Phase 3: Internal taps — state, DB writes, orders, ATTRIBUTION

**Goal**: the payoff. Tap the state-mutation chokepoints, the **money-path
DB writers** (`db_write` — "what rows did this chain write?" is the HANDOFF
bug class), the **orders-table status surface** (`order_status_applied`,
`reconcile_promote` — the stale-orders bug class), and the **nine §5.6
attribution categories** with the three mandates (SKIPPED/ERROR outcomes,
verbatim identity tuple incl. `""`, dedup_key).

**Dependencies**: Phase 1 **+ Phase 2a** (rev-2 correction: calc transitions
fire inside bus subscribers — `handle_risk_calculated` is bus-delivered, so
without the bus carry those taps emit `corr_id=""` and the chain assertions
cannot pass. Phase 2b is NOT required.)

**Effort**: M–L, split into four tasks (§9.2).

### Tasks

| # | Task | File(s) |
|---|---|---|
| 3.1 | State/persistence taps (sweep-shaped): `position_snapshot_applied` (**closes_detected as (symbol, side, tpid) list**), `position_incremental_applied` (**tpid + tpid_minted/present flags** — makes the mint a visible racer), `account_update_applied`, `portfolio_recalculated` (on change only); `waited_ms`/`held_ms` **on the async lock-acquiring paths only**; `calc_transition` + `link_transition` at the chokepoints; `order_status_applied` (status before→after, **source ws/reconcile/stale-mark**, dedup_key) + `reconcile_promote`; **`db_write`** at the ~10 money-path writers (table, op, key ids verbatim incl. `""`, rowcount) | `core/data_cache.py`, `core/calc_state.py`, `core/link_state.py`, `core/order_manager.py`, `core/db_orders.py`, `core/db_trades.py`, `core/schedulers.py` |
| 3.2 | **Attribution — entry side**: `attr_match_attempt` (**site: `core/calc_correlation.py::correlate_order_to_calc` via `core/order_enrichment.py::_try_correlate` — NOT order_manager** (rev-2 file-list fix); + the manual-link candidate path), `attr_bracket_inherit`, `attr_junction_form`, `attr_reenrich_trigger` (the child→parent re-enrich decision, historical bug #g). All with the §5.6 mandates | `core/calc_correlation.py`, `core/order_enrichment.py`, `core/order_manager.py`, `core/link_actions.py` |
| 3.3 | **Attribution — close side**: `attr_tpid_resolve` (tier named), `attr_close_build` (**strict_key, opens_found_strict/walk, open_fill_tpids `{empty,populated}`** — root cause on one screen), `attr_enrich` (on-change gated), `attr_drift_check` (**planned vs live TP/SL + removed flags + badge before→after**, on transition — historical bug #h was invisible without it). All with the §5.6 mandates | `core/order_manager.py` |
| 3.4 | **Attribution — funding + scenario fixtures**: `attr_funding_assign` (resolution path, venue_event_id dedup); the **race fixture** + **duplicate fixture** (below) + replay wiring against the existing linkage regression scenarios | `core/funding_handler.py`, `tests/` |

### Tests

- `tests/test_correlation_log_attribution.py`:
  - a synthetic open→fill scenario emits `attr_match_attempt` with the full
    per-criterion trace + outcome, from the **calc_correlation** site
  - a fill with empty tpid emits `attr_tpid_resolve` naming the tier
  - a close with strict-lookup miss emits `attr_close_build` whose single
    line shows strict_key → 0 rows; walk → N rows (tpid-empty count);
    row written?; plus the paired `db_write` for `closed_positions`
  - snapshot recovery (restart-reseeded position, empty position_id) emits
    `attr_enrich` naming the re-derivation source
  - **every early-return path emits `outcome=SKIPPED` with its reason code**
    (no_position_key, empty_tpid, no_parent_found, …) — the historical
    silent-skip bugs (b)/(d)/(g) each pinned as a SKIPPED line
  - SL-removal scenario: `attr_drift_check` line carries planned_sl,
    live_sl, sl_removed, badge before→after
  - all taps carry the originating corr_id (chained to the inbound WS frame
    through the bus where applicable — needs 2a)
  - **race fixture** — a WS fill chain interleaved with a snapshot-refresh
    chain touching the same position: reconstructable from the log alone,
    (`ts`,`seq`) proving order + distinct `task` proving concurrency (§4.1)
  - **duplicate fixture (split assertion — rev-2 correction)**: (a)
    corr-log acceptance: same `dedup_key` delivered twice → two
    `ws_order_update` lines, one grep finds them; (b) the
    exactly-one-decision invariant is the ENGINE's, not the log's — verify
    it holds today first; if it doesn't, **file the engine bug** (reconciler
    program input), don't gate this phase on it
- Reuse/extend the live-debug regression fixtures
  (`tests/test_debug_20260609_followups.py`, `test_linkage_binance_ws.py`)
  so the taps are exercised by the same scenarios that surfaced the bugs.

### Acceptance criteria

- For a replayed open→amend→cancel→close scenario, the log shows the
  complete attribution narrative on one corr_id chain per inbound frame,
  each decision with inputs + rule + outcome — **including the skips**.
- All nine §5.6 categories fire at their (corrected) sites; `db_write`
  answers "what rows did this chain write".
- This is the baseline the reconciler (next program) will be diffed against.

---

## Phase 4: Reader surface

**Goal**: make the log usable for debugging — a CLI reader + shipped `jq`
recipes; an optional read-only admin route.

**Dependencies**: Phase 1 (something to read). May start early and grow with
the taps — dogfooding the reader while building Phases 2–3 is encouraged
(rev-2 note: it needs only the Phase-0 format, not Phases 2–3 complete).

**Effort**: S.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 4.1 | `scripts/corr_tail.py`: filter by corr_id / calc_id / symbol / category / time-window; pretty-print one chain in `seq` order; `--follow`; **`--interleave <from> <to>`** (every chain in a window, corr_id + task columns — race forensics); **`--dups`** (dedup_keys seen >1×); **tolerates unknown envelope fields** (forward compat across the 7-day window) | `scripts/corr_tail.py` (new) |
| 4.2 | `jq` recipe cookbook (spec §9) as a docs how-to | `docs/` |
| 4.3 | (opportunistic, spec Q3) read-only admin route `GET /admin/correlation?corr_id=` | `api/routes_admin.py` (defer unless asked) |

### Tests

- `tests/test_corr_tail.py`: each filter returns the right subset from a
  synthetic NDJSON fixture; chain output `seq`-ordered; interleave + dups
  modes; a fixture line with an unknown extra field parses fine.

### Acceptance criteria

- `corr_tail.py --corr-id X` reproduces a chain; `--calc-id` cross-cuts
  corr_ids; `--interleave` makes the §4.1 race walkthrough reproducible;
  `--follow` tails live.

---

## Phase 5: Volume control, performance, holistic audit, bug replay

**Goal**: tune the whole-engine noise floor, prove the hot-path budget with
a falsifiable gate, run the mandatory cross-task adversarial audit, and
**replay the 8 historical bugs against the built taps** (spec §10.10).

**Dependencies**: Phases 0–4.

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 5.1 | Tune per-category defaults via registry groups: depth OFF, mark-price OFF (sampling opt-in — the rev-1 sampled-vs-off contradiction is resolved as OFF-default), kline ON, pubsub sampled; verify `linkage` profile carries the full attr/state/db/ws_lifecycle signal | `core/correlation_log.py`, `config.py` |
| 5.2 | **Falsifiable perf gate** (rev-2): p95 over N=10k synthetic frame→state-apply iterations, `full` vs `CORR_LOG_ENABLED=0`, **delta < 5%**; `@pytest.mark.timeout(60)`; behind a `perf` marker excluded from the default suite, run deliberately here; if the writer thread's flush shows in the profile, adjust batch interval | `tests/test_correlation_log_perf.py` |
| 5.3 | **Known-bug replay** (spec §10.10): drive the 8 historical scenarios (close-recording, unminted-snapshot, close-tpid race, fill-mint race, ticker-switch leak, stale orders, child→parent re-enrich, SL-removal badge) through the taps; each must be diagnosable with ONE §9 query. Any MEDIUM/BLIND → add the missing field/tap in this task | `tests/` + tap files as needed |
| 5.4 | Holistic audit (parallel adversaries): hot-path-safety, redaction-completeness, corr_id-propagation (both queue hand-offs), rotation/prune/MB-guard/Windows-safety, registry-conformance, test-integrity, spec-fidelity; apply fixes; reconcile deferred items into spec §11/§13 | — |

### Tests

- perf gate as above; taxonomy-conformance test (emitted ⊆ registry) runs in
  the default suite; audit-driven regressions folded into existing files.

### Acceptance criteria

- All spec §10 program-level acceptance criteria pass — including §10.10
  (8/8 bugs FAST) and §10.11 (conformance + anchors).
- No BLOCKER/HIGH from the holistic audit (or all fixed).

---

## 6. Test strategy across phases

### Levels

- **Unit** — envelope shape, redaction, size cap, registry/profile
  derivation, rollover/prune/MB-guard, `seq`/`task` semantics (sink stubbed;
  assert envelopes, not files).
- **Integration** — entry-point → boundary → internal chains share a
  corr_id; both queue hand-offs; REST out/return pairing; the bus test
  sweep.
- **Scenario** — replay the live-debug linkage scenarios with taps on;
  assert the attribution narrative including SKIPPED lines.
- **Replay gate** — Phase 5.3: the 8 historical bugs, one query each.
- **Performance** — the marked perf gate (Phase 5.2), excluded from the
  default run.

### Golden datasets

Reuse the live-debug fixtures (open→amend→cancel→close, snapshot-recovery /
unminted-tpid, close-tpid race) as the scenario corpus — the log must
illuminate exactly the bugs that motivated it, and Phase 5.3 enforces that
as an acceptance gate rather than an aspiration.

### Isolation

The autouse conftest fixture (Phase 0.8) guarantees no test writes to the
live correlation dir — resolver-patch approach, mirroring
`_isolate_live_per_account_logs`.

---

## 7. Migration / rollback

- **Forward**: additive only. No schema changes (NDJSON sink). New module +
  taps + config + registry.
- **Rollback**: `CORR_LOG_ENABLED=0` no-ops every tap at runtime. Reverting
  the code removes the module + taps; nothing else depends on it. The one
  non-trivial revert is the bus carry/re-bind — which is why it is its own
  task and commit (**CL.T2a**, rev-2 split): revertable independently of
  every other tap. NB the bus change is NOT test-transparent: ~10 test
  files unpack the internal queue as 2-tuples and are updated in the same
  commit (Phase 2a.3) — a revert restores them too.
- **No data migration** — append-only files; old files prune themselves.

---

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Hot-path latency from emitting on the WS/dispatch path | enabled-check-first pipeline + writer-thread drain (zero loop interaction); falsifiable Phase-5 perf gate (<5% p95) |
| Drain blocks the event loop | **designed out**: the drain is a daemon thread doing blocking `get(timeout)` — not a coroutine (rev-2 correction of an unbuildable rev-1 mechanic) |
| Market-data / pubsub volume buries the signal | registry-group gating, depth/mark-price OFF by default, pubsub sampled, on-change gating for refresh-driven attr taps (§7.3) |
| Secret leakage into a plaintext file | central mandatory `_redact()` (D10); tested at every boundary tap incl. listen-keys |
| Windows rotation failure (MED-045 class) | date-stamped filenames, no rename (§6.3) |
| corr_id lost across queue hand-offs | bus AND webhook queues carry + re-bind (D6); explicit two-hop test (Phase 2b) |
| Silent skip bugs invisible (the historical bug shape) | D17 mandates: one envelope per attribution invocation, SKIPPED/ERROR outcomes, identity tuple verbatim incl. `""` |
| Runaway disk | line cap + daily rotate + 7-day prune + in-flight bound + **per-day MB guard** (D20); ~1.7 GB/day worst-case estimate documented for calibration |
| Category drift / typos / profile divergence | registry + groups + derived profiles + conformance test + `# corr-tap:` anchors (D8 rev 2); future-boundary discipline in spec §5.8 |
| Dev-environment mid-run source mutation (HANDOFF hazard) | commit each task as soon as green + audited; re-verify tree on a red run |
| Attribution taps capturing the *result* but not the *decision* | tap inputs + rule + outcome explicitly; scenario tests assert the per-criterion trace; Phase 5.3 replay gate |
| Tap-site drift (taps mapped to wrong files — happened in rev 1) | sites verified against code in spec §5.6's table; Phase-3 tests assert the emitting module |

---

## 9. Task breakdown (Claude Code sizing)

### 9.1 Sizing principles

Same as the calc-linkage plan: ideal 100–500 LOC / 2–5 files / 1–2 test
files per task; tests live in the same task as the code; commit per task.
Sweep-shaped tasks (many same-shaped one-line taps) are one task with
pre-grepped sites.

### 9.2 Recommended task list (12 tasks)

| # | Task | Scope | Effort |
|---|---|---|---|
| **CL.T0a** | **SHIPPED `db89ae0`** — Spine — contextvar + envelope + **registry/groups/profiles** + `emit` pipeline + redaction | plan 0.1–0.3, 0.5 | S–M |
| **CL.T0b** | **SHIPPED `3b7c6ca`** — Sink — writer thread + rollover/prune/MB-guard/overflow + config + lifespan wiring + conftest isolation (incl. the session-scoped floor, audit-driven) | plan 0.4, 0.6–0.8 | M |
| **CL.T1a** | **SHIPPED `9ad8764`** — HTTP middleware + blanket loop scopes (schedulers, keepalive/fallback, monitoring, webhook, reconciler, boot) | plan 1.1–1.2 | S–M |
| **CL.T1b** | **SHIPPED `9cb0efe`** — WS frame taps (Binance user/market + platform + news) + WS lifecycle taps + task naming | plan 1.3–1.6 | M |
| **CL.T2a** | **SHIPPED `a6d839d`** — Bus carry/re-bind + bus taps + the 2-tuple test sweep — isolated, revertable commit | plan 2a.1–2a.3 | S–M |
| **CL.T2b** | **SHIPPED `c421747`** — REST chokepoint + outbound-HTTP taps + webhook-queue carry + pubsub tap + the HA-1..5 closures | plan 2b.1–2b.4 | M |
| **CL.T3a** | State/DB/orders taps (sweep): data_cache + transitions + order_status/reconcile_promote + db_write | plan 3.1 | M |
| **CL.T3b-entry** | Attribution entry side: match (calc_correlation/order_enrichment) + bracket + junction + reenrich | plan 3.2 | M |
| **CL.T3b-close** | Attribution close side: tpid_resolve + close_build + enrich + drift_check | plan 3.3 | M |
| **CL.T3c** | Funding attribution + race/duplicate fixtures + scenario replay wiring | plan 3.4 | S–M |
| **CL.T4** | Reader — `corr_tail.py` + jq cookbook (may start after Phase 1) | plan 4.1–4.2 | S |
| **CL.T5** | Volume tuning + perf gate + **8-bug replay gate** + holistic audit + fixes | plan 5.1–5.4 | M |

**12 tasks**, ~1.5–3 weeks @ 1–2 tasks/day with per-task audit (rev-2: the
rev-1 "~8 tasks / 2–3 weeks @ 2/day" arithmetic didn't cohere). Each task =
one commit, green + audited before the next.

### 9.3 Sequencing

- **CL.T0a → CL.T0b** strict (envelope before sink wiring).
- **CL.T1a/T1b** need T0; parallel-safe with each other.
- **CL.T2a** before **CL.T3*** (rev-2: Phase 3's bus-reached taps — calc
  transitions inside bus subscribers — need the carry; "Phase 3 independent
  of Phase 2" was false). **CL.T2b** parallel-safe with CL.T3*.
- **CL.T3b-close is the headline** — the close-side attribution taps cover
  the worst historical bugs; T3a/T3b-entry/T3b-close/T3c are
  loosely ordered but can interleave.
- **CL.T4** any time after Phase 1 (dogfood early); **CL.T5** last.

### 9.4 Holistic-audit ledger — filed follow-ups (Phases 1–2, 2026-06-11)

**Phase-1 audit.** Two-agent holistic audit of Phase 0+1 (`9ad8764` + `9cb0efe` on
`db89ae0`/`3b7c6ca`): **COHERENT, NO PRODUCTION REGRESSIONS, no
BLOCKER/HIGH**. Acceptance scorecard 3.5/4 (the leak query is
component-proven, not scenario-proven — HA-6). Spec-side deviations are
recorded in spec §15 (E1–E12). Every actionable issue filed here with
its owner task; none blocks CL.T2a.

| ID | Sev | Issue | Owner |
|---|---|---|---|
| HA-1 | MED | REST-fallback plugin ingest (`POST /api/platform/event` → `_dispatch`) mints a `wsp-*` chain INSIDE the request's `http-*` chain — the http pair looks empty, the wsp chain has no visible trigger (the sibling `/api/platform/positions` route already behaves correctly). Fix: move `tick("wsp")` from `_dispatch` to the WS receive loop + update the dispatch test | **CLOSED — CL.T2b `c421747`** (mint moved to the `handle_ws` receive loop; dispatch-inherits + receive-loop-mints both tested) |
| HA-2 | MED | Middleware **registration** on `main.app` is unpinned — deleting the decorator darkens the whole HTTP boundary with the suite green. Add: `assert any(m.kwargs.get("dispatch") is main._corr_http_middleware for m in main.app.user_middleware)` | **CLOSED — CL.T2b `c421747`** |
| HA-3 | MED | No **registry snapshot test** — a silent re-group (e.g. `platform_fill`→market) drops a money-path category from the `linkage` profile undetected; `register()`'s conflict guard can't see an edit of the original line. Add `assert cl.registry() == {…45…}` | **CLOSED — CL.T2b `c421747`** (45-entry category→group snapshot — pins groups, not just names) |
| HA-4 | MED | No **session-floor self-test** — the guard against the PROVEN T0b live-dir leak (module-scoped TestClient lifespans) has no asserting observer. Add a module-scoped probe asserting the resolver ≠ `config.CORR_LOG_DIR` before any function-scoped patch | **CLOSED — CL.T2b `c421747`** (`tests/test_correlation_log_floor.py` — non-vacuous: instantiates before the function-scoped autouse patch) |
| HA-5 | MED-LOW | `_last_streams` no-streams reset is untested (the T1b audit's suggested test never landed) — deleting the reset re-corrupts the rebuild diff silently | **CLOSED — CL.T2b `c421747`** (mutation-effective) |
| HA-6 | LOW-MED | Composed **leak-scenario test** absent: no test executes the §9 leak predicate against a healthy AND a leaky trace (change+rebuild together vs change-with-suppressed-restart) | CL.T5 (bug-#4 replay) or earlier |
| HA-7 | LOW | **Taps → live writer** integration has zero direct assertions (all tap tests drain the queue with the writer off). One smoke: drive `_handle_user_event` → `start()`/`close()` → read the day file | CL.T5 or earlier |
| HA-8 | LOW | Plugin `ohlcv_bar` emits `ws_kline(peer=quantower)` per bar-UPDATE (Binance taps are closed-candle-gated; MEXC parse has no closed-gate, latent) — per-update volume at `full` when the plugin is connected | CL.T5 volume pass (or closed-gate at touch) |
| HA-9 | LOW | Payload code-gaps vs spec tables (spec §15 footer): `ws_kline` interval+close (close is free at `parsed["candle"][4]`), `ws_connected` duration, news `ws_connect` + disconnect `uptime_s`, `platform_snapshot` counts, `ws_depth` top-of-book; **Finnhub calendar success lacks `n_items` (T2b add, Phase-2 audit)** | CL.T5 at latest; ws_kline close + news ws_connect near-free at next touch |
| HA-10 | NIT | PWA endpoints (`/manifest.json`, `/service-worker.js`, `/favicon.ico`) escape the `/static` skip; overflow-RECOVERY marker rides the recovering emitter's chain (day-cap marker is correctly bare); `ws_depth` negative tests can't distinguish gated-off from tap-deleted (needs a positive companion via `_CATEGORY_DEFAULT_OFF` patch); tap-before-apply ordering unpinned; `# corr-tap` anchor style inconsistent at 2 news sites; `ws-news-ping` name + `sch-*` prefixes (beyond reaper/boot) unpinned | opportunistic |
| HA-11 | INFO | Frame types outside the §5.4 taxonomy mint a chain but emit no envelope (spec §15 E12) — decide a kind-only catch-all | CL.T5 |
| HA-12 | NOTE | Until CL.T2a, bus-consumer emissions ride the eternal `boot-*` chain (not `""`) — the empty-corr tripwire is blind to this class. Resolved by T2a itself | **RESOLVED — CL.T2a `a6d839d`** (carry/re-bind) |

**Phase-2 audit (CL.T2a `a6d839d` + CL.T2b `c421747`, filed
2026-06-11).** Two-agent holistic audit (code lens / docs+tests lens)
of both tasks as ONE unit: **COHERENT, NO BLOCKER/HIGH, no production
regressions.** The flagship chain was proven by a composition probe no
shipped test performs — real `EventBus` + real `WebhookDispatcher` +
real `BaseExchangeAdapter._run` across all three task boundaries,
19/19 checks: close→bus→queue→POST chain survival,
REST-inside-a-bus-handler carrying the publisher's chain (real path:
`reconciler.on_position_closed` → `exchange_market` → adapter `_run`),
retry-after-backoff, empty-corr carry, worker no-leak between jobs,
concurrent `rest-*` fallback isolation. The ccxt translation re-indent
verified byte-identical (`git diff -w`); the T2a sweep re-verified
complete repo-wide at HEAD (zero 2-tuple unpacks, incl. tests added
after the sweep); HA-1..5 closures + the HA-12 resolution verified
real (mutation-effectiveness checked per test). Spec-side deviations
filed as §15 E13–E18 + the E1 supplement. None of the below blocks
CL.T3a.

| ID | Sev | Issue | Owner |
|---|---|---|---|
| HA-13 | MED | The `linkage` profile drops the **entire `outbound` group** — incl. the webhook `http_out_*` taps, the terminal hop of the flagship close→bus→queue→POST chain (spec §15 E13; §7.3's "outbound-news" gloss named a non-existent group). Carry is profile-independent — only the envelopes are absent; default profile `full` unaffected. Decide: re-group the webhook taps (low-volume, high linkage value) into a linkage-visible group vs accept | CL.T5 (volume pass) |
| HA-14 | LOW | `pubsub_publish` ships group-gated only — NOT sampled at `full` despite spec §7.3 (E14); the dominant single category at `full`, bounded only by the day-MB guard; `_sample_rate` hook is generalized and ready | CL.T5 (plan 5.1) |
| HA-15 | LOW | REST-envelope secret-absence is unpinned: `TestRestChokepoint` (adapter built with keys `"k"`/`"s"`) asserts nothing about key/signature absence — the plan-2b "no API key in any envelope" bullet is pinned for webhook/Finnhub/FRED only. Surviving mutation: adding raw `args` to the `rest_call` payload passes the suite (redaction is key-based; bare-string secrets in a positional list pass through — the documented `_redact` limit). Code is clean today; test debt | next test-touching task (≤ CL.T5) |
| HA-16 | LOW | yahoo/VIX taps are source-pinned only — the placement assert (`"run_in_executor" in src`) is vacuous for placement because `_download` is nested inside `fetch_vix`: moving the emits INSIDE the executor callable (§3.3 thread-rule violation → `corr_id=""`) survives the suite. FRED has behavioral tests; yahoo has none | CL.T5 or next touch (stubbed-yfinance behavioral test) |
| HA-17 | LOW | No single test drives close-publish→bus→queue→POST on one corr_id: the T2b "2-hop test" simulates the bus hop with a bare `correlation_scope`, and `test_phase7_webhook`'s bus-composition test asserts no corr. The property holds compositionally (T2a pins bus re-bind for any handler; the 2-hop test pins handler→POST) and was proven by the audit probe — but no in-suite test composes it | CL.T3*/T5 scenario replay composes it naturally (or +5 lines to the phase7 composition test) |
| HA-18 | NIT | `bus_publish` tap-AFTER-enqueue ordering is unpinned (swapping the tap above `put` would pass the suite — phantom envelope on enqueue failure); practically unreachable today: the unbounded loop-side `put` never raises | accept / pin at next touch |
| HA-19 | NIT | `_tap_deliver` is unguarded (vs `_tap_publish` guarded): a raise via `repr(handler)` on a pathological handler would skip the event's remaining handlers + `task_done`. Theoretical-only for plain function/method handlers | accept / wrap at next touch |
| HA-20 | NIT | All per-account webhook bus handlers share one `bus_deliver` qualname (`WebhookDispatcher.make_handler.<locals>._handler`); the account is recoverable from the channel string in the same envelope | accept (forensics note) |
| HA-21 | NIT | `fetch_news` success-tap arg construction is unhardened (asymmetric with the FRED T2b-2 hardening): every `items` shape that makes `len()` raise also crashed pre-T2b three lines later — no caller-visible behavior change | opportunistic at next touch |
| HA-22 | NOTE | Commit-claim arithmetic, for the record: T2a "15 files' bus-queue drains normalized" = **14** pre-existing files + the NEW bus-test file; T2b "boundaries (12)" = **11** collected. The sweep itself is complete repo-wide at HEAD | record-only (this filing) |

### 9.5 After this program

The **attribution reconciler** (spec §12) is the next program — a separate
plan. The correlation log's §5.6 baseline (including SKIPPED lines) is its
safety net: diff the pre/post `attr_*` streams for the replayed scenarios to
prove the consolidation is faithful.

---

*End of implementation plan. Spec in
[correlation_log_spec.md](correlation_log_spec.md).*
