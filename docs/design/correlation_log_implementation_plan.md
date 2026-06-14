# Correlation Log — Implementation Plan

**Status**: **COMPLETE — all 12 tasks shipped (Phases 0–5, 2026-06-14)**; design rev 2 audited (4 adversarial agents, 2026-06-10). Ledger disposition in §9.4.
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
| **CL.T3a** | **SHIPPED `3646a4d`** — State/DB/orders taps (sweep): data_cache + transitions + order_status/reconcile_promote + db_write (12 writers incl. the audit-fold log_event/log_trade_event) | plan 3.1 | M |
| **CL.T3b-entry** | **SHIPPED `331f00c`** — Attribution entry side: match (calc_correlation/order_enrichment) + bracket + junction + reenrich | plan 3.2 | M |
| **CL.T3b-close** | **SHIPPED `b35389a`** — Attribution close side: tpid_resolve + close_build + enrich + drift_check (on-change memo) | plan 3.3 | M |
| **CL.T3c** | **SHIPPED `fd5b56e`** — Funding attribution + race/duplicate fixtures + the one-chain narrative (named deviation: replay wiring shipped self-contained, not by editing the live-debug fixture files — per-bug envelope asserts are CL.T5 5.3's job) | plan 3.4 | S–M |
| **CL.T4** | **SHIPPED `3b66da5`** — Reader — `corr_tail.py` + jq cookbook | plan 4.1–4.2 | S |
| **CL.T5** | **SHIPPED (2026-06-14)** — Volume tuning (HA-14/23/28) + perf gate + 8-bug replay gate + HA-35/40/41 seam taps + holistic audit + §15/§9.4 reconciliation. **PROGRAM COMPLETE** | plan 5.1–5.4 | M |

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

### 9.4 Holistic-audit ledger — filed follow-ups (Phases 1–3)

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
| HA-15 | LOW | REST-envelope secret-absence is unpinned: `TestRestChokepoint` (adapter built with keys `"k"`/`"s"`) asserts nothing about key/signature absence — the plan-2b "no API key in any envelope" bullet is pinned for webhook/Finnhub/FRED only. Surviving mutation: adding raw `args` to the `rest_call` payload passes the suite (redaction is key-based; bare-string secrets in a positional list pass through — the documented `_redact` limit). Code is clean today; test debt | CL.T5 (the "next test-touching task" clause decayed — four test-touching tasks passed without it; P3 filing) |
| HA-16 | LOW | yahoo/VIX taps are source-pinned only — the placement assert (`"run_in_executor" in src`) is vacuous for placement because `_download` is nested inside `fetch_vix`: moving the emits INSIDE the executor callable (§3.3 thread-rule violation → `corr_id=""`) survives the suite. FRED has behavioral tests; yahoo has none | CL.T5 or next touch (stubbed-yfinance behavioral test) |
| HA-17 | LOW | No single test drives close-publish→bus→queue→POST on one corr_id: the T2b "2-hop test" simulates the bus hop with a bare `correlation_scope`, and `test_phase7_webhook`'s bus-composition test asserts no corr. The property holds compositionally (T2a pins bus re-bind for any handler; the 2-hop test pins handler→POST) and was proven by the audit probe — but no in-suite test composes it. **P3 extension**: the Phase-3 narrative/race fixtures likewise open bare `correlation_scope`s — no Phase-3 test drives a BUS delivery into an attr/state tap either; frame→bus→attr remains composition-proven only | CL.T5 scenario replay composes it naturally (or +5 lines to the phase7 composition test) |
| HA-18 | NIT | `bus_publish` tap-AFTER-enqueue ordering is unpinned (swapping the tap above `put` would pass the suite — phantom envelope on enqueue failure); practically unreachable today: the unbounded loop-side `put` never raises | accept / pin at next touch |
| HA-19 | NIT | `_tap_deliver` is unguarded (vs `_tap_publish` guarded): a raise via `repr(handler)` on a pathological handler would skip the event's remaining handlers + `task_done`. Theoretical-only for plain function/method handlers | accept / wrap at next touch |
| HA-20 | NIT | All per-account webhook bus handlers share one `bus_deliver` qualname (`WebhookDispatcher.make_handler.<locals>._handler`); the account is recoverable from the channel string in the same envelope | accept (forensics note) |
| HA-21 | NIT | `fetch_news` success-tap arg construction is unhardened (asymmetric with the FRED T2b-2 hardening): every `items` shape that makes `len()` raise also crashed pre-T2b three lines later — no caller-visible behavior change | opportunistic at next touch |
| HA-22 | NOTE | Commit-claim arithmetic, for the record: T2a "15 files' bus-queue drains normalized" = **14** pre-existing files + the NEW bus-test file; T2b "boundaries (12)" = **11** collected. The sweep itself is complete repo-wide at HEAD | record-only (this filing) |

**Phase-3 audit (CL.T3a `3646a4d` + T3b-entry `331f00c` + T3b-close
`b35389a` + T3c `fd5b56e`, filed 2026-06-12).** Two-agent holistic
audit (docs/tests lens full; code lens re-run lean after two
session-limit kills) of the four tasks as ONE unit: **COHERENT, NO
BLOCKER/HIGH, no production regressions.** All 12 per-task audit folds
verified real + mutation-effective at HEAD; the task101 stub sweep and
both fixture-schema fixes verified correct; no Phase-3 emit site
inside an executor callable; registry untouched (45 — zero additions,
all pre-registered at T0a; 9/9 attr categories live); suite arithmetic
3681→3715→3747→3761→3771 (+34/+32/+14/+10) coheres; 90 Phase-3 tests
green standalone. Plan-fidelity: tasks 3.1–3.4 SHIPPED at the
corrected sites; acceptance #2 (nine categories) and #3 (db_write
answers what-rows) MET; acceptance #1 PARTIAL — open→close replays on
one chain exist, but **no replay exercises an amend or cancel leg**
and the narrative contains no in-replay SKIPPED line (the class-wide
skip pins are unit-level) → closes at CL.T5 5.3. The historical
silent-skip bugs (b)/(d)/(g) are each literally pinned as SKIPPED
lines. No HA-1..22 item was closed by Phase 3 (HA-6/HA-7 confirmed
still open). Spec-side deviations filed as §15 E19–E28 + the footer
adds; highest-value NEW findings: E23 (the spec's canonical
stranded-row query uses a key that doesn't exist in the envelopes),
HA-35 (an envelope-less post-LINKED write-failure seam), HA-36 (an
untapped funding-rollup writer), HA-40 (the close-fill attribution
stamp is an envelope-less §5.6-class decision the spec table never
listed), HA-42 (a latent pre-existing double-junction engine corridor
the new dedup keys make one-grep findable — reconciler-program input).
**Scenario envelope counts at `full`** (code-lens tables): a routine
update of a linked order = 7 envelopes (3 of them attr nothing-to-do
lines — the per-update `junction_exists` replay line is the largest
single contributor); first-link ~10; TP/SL child arrival ~14; opening
fill ~12; closing fill ~9 + deferred close-build ~8. **Disabled-mode
parity probe: PASS** (a representative order→fill→close flow: 24
envelopes enabled / 0 disabled, identical
orders/fills/closed_positions/positions_calcs end-state). None of the
below blocks CL.T4.

| ID | Sev | Issue | Owner |
|---|---|---|---|
| HA-23 | MED-LOW | `closes_detected` is unbounded vs the §7.4 4 KB whole-payload cap — at ~75+ simultaneous closes the WHOLE snapshot payload truncates to the `_truncated` summary, losing the per-close tpids (the §4.1 walkthrough's load-bearing field). Cap/split with `n_omitted` like the `ids[:20]` convention | CL.T5 volume pass (T3a-3) |
| HA-24 | LOW | Platform `account_update_applied` is ungated at the plugin's ~5 Hz (per-frame emit at `full`; the plugin is not connected at this deployment) | CL.T5 volume pass (T3a-7) |
| HA-25 | NOTE | Accepted T3a residue, for the record: the ws `order_status_applied` emits on guard-rejected writes (intent vs application — the paired db_write rowcount=0 is the truth); the bulk stale/reconcile pre-SELECT-vs-UPDATE skew window (line-set vs count can diverge under concurrent writers; self-visible as count≠lines) | record-only |
| HA-26 | LOW | Two-party envelopes (reenrich child/fill, bracket INHERITED) carry `parent_`/`child_exchange_order_id` but no bare `exchange_order_id` key — uniform mandate-2 queries miss them | CL.T5 (T3bE-6) |
| HA-27 | LOW | Manual-path handled-"error" maps to SKIPPED (`reason=result`), not ERROR; manual + enrich/drift envelopes hardcode `lifecycle_id=""` (their reads don't select it — one extra column at next touch) | CL.T5 (T3bE-7 + T3bC-7) |
| HA-28 | MED-LOW | The periodic order-snapshot loops drive `_propagate_bracket_calc_id` per symbol per pass → steady bracket SKIPPED lines (~17 MB/day @ 5 symbols) — a §7.3 on-change-dedup candidate; the envelope also lacks a `via=order_arrival\|snapshot` discriminator to even measure the split (HA-29b). **P3 code-lens add**: the per-update `attr_junction_form via=post_link_replay SKIPPED junction_exists` line is the same class and the LARGEST single nothing-to-do generator (every routine update of a linked order) — fold into the same on-change-dedup decision | CL.T5 volume pass (T3bE-8) |
| HA-29 | NIT | Payload nits (T3bE-10 concretized + P3 adds): (a) bracket INHERITED lacks the "inheritance path"/detection tier; (b) bracket SKIPPED lines carry no triggering-order dedup_key and no `via=`; (c) reenrich lacks the literal `position_side`; (d) the MFE/MAE db_write is `row_id`-only; (e) the funding ERROR twin lacks `dedup_key` though the aborting row is in scope; (f) the `{eoid}:reenrich_fill` dedup tag vs the normalized-triple convention; (g) the `junction_write_failed` ERROR lacks `error_type` — the single remaining attr-ERROR site without it (the paired db_write twin one line away carries the cause) | opportunistic / CL.T5 |
| HA-30 | NIT | Anchor style: `corr-tap:` lives inside DOCSTRINGS (no `#`) at the matcher + both link_actions taps — the §5.8 `# corr-tap:` grep misses 3 of the highest-value sites | opportunistic (HA-10 fold; T3bE-11) |
| HA-31 | NIT-LOW | Disabled-mode cost: the matcher and close_build `finally` blocks build their payloads without an `enabled()` pre-gate (same class: the funding envelope dicts) — §7.7's "disabled ≈ 1 µs" doesn't hold for these categories; no test pins the disabled-cost contract | CL.T5 perf pass (T3bE-12) |
| HA-32 | NOTE | Accepted T3b-close residue → the CL.T4 cookbook: dedup tag-styles are heterogeneous (`{fid}:tpid_resolve`, `close:{fid}`, `junction:{fid}`, `replay:{eoid}`, `manual:{oid}:{calc}`, `{eid}:inherit:{calc}`, `{eid}:{status}:{qty}`, `venue_event_id`) — readers must not assume one shape; post-persist exceptions read `outcome=ERROR` with `row_written:true` (the landed-row predicate is `payload.row_written`); the `__dict__.setdefault` enrich-memo pattern | CL.T4 cookbook + record (T3bC-5/6/8) |
| HA-33 | LOW | Funding follow-ups: `reconcile_queued:false` (open path) + `n_rows_processed` (batch-abort) pins absent; cookbook caveat that funding re-polls are routine benign dedup-key repeats (`inserted:false` disambiguates `--dups` output); the close+reopen mis-attribution edge's log heuristic = `open_position` with stale `ts_ms` (diagnosable; single-line certainty would need an entry-ts read the handler deliberately avoids) | CL.T4 cookbook + CL.T5 pins (T3c) |
| HA-34 | NOTE | TERMINAL replays (`filled→filled`) bypass SR-1 BY DESIGN and are decided by the DB ON-CONFLICT guard — the discriminator is the paired db_write `rowcount=0`; outside the duplicate-fixture's tested class (which pins the non-terminal `new→new` SR-1 path) | CL.T4 cookbook; CL.T5 replay gate may pin (T3c) |
| HA-35 | LOW-MED | **Post-decision link-write failure is envelope-less**: the matcher emits LINKED, then the actual `orders.calc_id`/`link_status` stamp is an UNTAPPED raw sqlite3 UPDATE (`order_enrichment._update_orders_sync`, not in the named-10) inside `auto_classify`'s apply_fn; if it raises there is no link_transition (emit is post-apply), no db_write, no ERROR twin — and `_enrich_order_best_effort` swallows. The chain reads LINKED while the DB has no link — the historical "decision recorded, write missing" class. Today's detection = join absence (a LINKED match with no following link_transition). Candidates: an ERROR twin at the write step, or a db_write tap on the stamp | CL.T5 (the 8-bug replay gate exercises this seam) — NEW (P3B-2) |
| HA-36 | LOW | `reconcile_closed_position_funding` (the deferred-funding rollup UPDATE of `closed_positions.funding_fees`/`net_pnl`; called from the funding poll AND at close) is not a tapped writer — "what rows did this chain write" has a hole on the funding-rollup UPDATE. Spec's named-10 doesn't include it either, so code matches spec — a scope decision, not drift | CL.T5 decision (add to named writers or accept+document) — NEW (P3B-3) |
| HA-37 | NIT | Test-integrity: the drift gate-sig's flag members are unpinned (no flag-flip-with-same-badge case → a `(badge,)`-only sig survives the suite); no generic "every attr envelope carries the 4-key identity tuple" conformance test (single-key deletions on low-assert envelopes survive). Pin one flag-flip; add a drain-time attr-envelope validator | CL.T5 test pass — NEW (P3B-4) |
| HA-38 | NOTE | Cancellation vs mandate 1 (E15's internal sibling): the attr taps' `except Exception` doesn't see `CancelledError` — most emit nothing on cancellation; close_build's `finally` DOES emit but labels it `ERROR/build_incomplete` (reachable: the deferred close-build task cancelled at shutdown). A line, not an absence — but mislabeled; accepted per the E15 precedent | record + CL.T4 cookbook — NEW (P3B-11) |
| HA-39 | NOTE | Claim arithmetic, for the record (HA-22 sibling): tapped money-path writers = **11 functions** (12 success-path table lines — `upsert_fill_and_update_order` emits one per table); the suite chain 3681→3715→3747→3761→3771 (+34/+32/+14/+10) verified; file counts 34 (state) + 56 (attribution) = 90 collected | record-only (this filing) |
| HA-40 | MED | **The closing-fill attribution stamp is envelope-less**: `_stamp_closing_fill_attribution` (the T2.2 primary-calc/lifecycle inheritance onto the closing fill — a §5.6-CLASS decision the spec table never listed) emits no attr line on stamp / no-junction-skip / failure, and its raw `fills` UPDATE has no db_write tap. Same family (untapped decisions/writers on the attribution paths): `enrich_fill`'s fills calc_id/fill_type/slippage UPDATEs, the lifecycle backfill UPDATEs in the junction builder, `_populate_tp_sl_*`'s orders UPDATE, the `calc_match_audit` batch INSERT. A spec-scope gap, not implementation drift — fold the remediation with HA-35's | CL.T5 (one batch with HA-35; reconciler-program input) — NEW (P3A-1) |
| HA-41 | LOW | `log_event`/`log_trade_event` db_write taps are success-side only: an INSERT/connect failure raises out with NO ok:false twin and every caller swallows at debug — engine_events/trade_events write failures are envelope-less (the money tables got both twins in T3a; these two got success + the pollution-reject twin) | CL.T5 (the T3a twin pattern) — NEW (P3A-2) |
| HA-42 | LOW | **Latent ENGINE defect surfaced by the audit's envelope-table construction** (pre-existing defect-8 replay logic, NOT introduced by Phase 3): if the matcher first links a MARKET parent during fill-N's (N≥2) `_reenrich_parent_after_fill` and fill #1 already backfilled the order's tpid, `_ensure_junction_if_linked` DELEGATEs a synthetic fill summing ALL opening fills (incl. the in-flight one, already upserted) and the same fill's `_link_position_calc_on_open` then UPSERTs it AGAIN → `contributed_qty` over-counts (f1+2·f2) + two FORMED envelopes + two positions_calcs db_writes on one chain. The new dedup keys (`junction:{fid}` + `replay:{eoid}`) make it a one-grep find — the tap working as designed. Fix shape: exclude the in-flight fill from the synthetic SUM, or skip the replay when invoked mid-fill | engine follow-up (reconciler-program input; out of the log program's scope) — NEW (P3A-3, code-read derivation) |

**Phase-5 close-out (CL.T5, 2026-06-14) — PROGRAM COMPLETE.** Three-agent
holistic audit (code-correctness / test-integrity / spec-ledger
reconciliation): code **SHIP** (no BLOCKER/HIGH/MED; the taps are pure
observability — no engine-outcome perturbation), tests **mutation-solid**
after one folded gap, ledger **reconciled**. Audit folds landed in this
task: the HA-28 transition-re-emit branch was an unpinned dead branch (a
surviving mutation) → pinned; the perf gate's aggregator was min-of-rounds
(lenient) → median; the amend/cancel replay asserted "any SKIPPED line" →
now leg-specific; **HA-41 closed** (the audit flagged it as the same cheap
T3a-twin shape as the seams already being closed). Spec deviations filed as
§15 E29–E34. Full suite green SOLO; live corr dir byte-identical; perf gate
green (`-m perf`, p50 ≈3.5% < 5%).

**CL.T5 disposition of the open ledger** (every HA-6..HA-42 item resolved
to CLOSED / ACCEPTED-verdict / DOWNGRADED-with-reason / out-of-scope — no
MISSED-by-silence):

| HA-id | CL.T5 disposition |
|---|---|
| HA-6 | **CLOSED** — `test_bug5_ticker_switch_leak` runs the §9 leak predicate against a healthy trace (change+rebuild → none) AND a leaky trace (change, no rebuild → 1). |
| HA-7 | DOWNGRADED → opportunistic. Taps→live-writer is component-proven (every tap test drains the queue; T0b proves the writer); a full `_handle_user_event`→`start()`→read-file smoke adds a real-socket/thread harness for little marginal assurance at program close. |
| HA-8 | ACCEPTED (sibling of HA-24) — plugin `ohlcv_bar` closed-gate; plugin not connected at this deployment. |
| HA-9 | DOWNGRADED → opportunistic. Payload-FIELD-completeness nits (`ws_kline` interval+close, `ws_connected` duration, news `ws_connect`, `platform_snapshot` counts, `ws_depth` top-of-book, Finnhub `n_items`) — NOT diagnostic-capability gaps; the 8-bug replay + acceptance criteria pass without them; `ws_kline`/depth are market-group (OFF in `linkage`). One-liners at next touch of each file. |
| HA-10 | DOWNGRADED → opportunistic (NIT bag, by charter). |
| HA-11 | ACCEPTED — exotic frame types (`MARGIN_CALL`, unknown platform kinds) mint a chain but emit no frame envelope (E12). A kind-only catch-all is declined: the taxonomy defines what is logged; an untyped catch-all adds noise without a known consumer. Re-open if an exotic frame ever needs chain-visibility. |
| HA-13 | **ACCEPTED** (spec §15 E33) — webhook `http_out_*` stays out of `linkage`. |
| HA-14 | **CLOSED** — `pubsub_publish` sampled (`CORR_LOG_PUBSUB_SAMPLE=10`); E14 resolved (E32); `test_pubsub_sampling` pins it. |
| HA-15 | DOWNGRADED → opportunistic. REST-envelope secret-absence is TEST-DEBT (the `_redact` code is clean; the gap is an unpinned assertion). LOW; next test-touch of `boundaries.py`. |
| HA-16 | DOWNGRADED → opportunistic. yahoo/VIX placement pin is source-level only; LOW test-debt (FRED has behavioral coverage). |
| HA-17 | DOWNGRADED → opportunistic. The close→bus→queue→POST chain is composition-proven (T2a pins bus re-bind; the 2-hop test pins handler→POST; the Phase-2 audit probe ran the full real composition). No single in-suite test composes it; +5 lines at next webhook-test touch. |
| HA-23 | **CLOSED** — `closes_detected[:20]` + `n_closes`/`n_closes_omitted`; `test_mass_close_caps_list_but_keeps_honest_counts`. |
| HA-24 | **ACCEPTED** (spec §15 E34) — platform `account_update_applied` 5 Hz; plugin not connected. |
| HA-26 | DOWNGRADED → opportunistic. Two-party envelopes' bare `exchange_order_id` key (mandate-2 uniform queries) — the `corr_tail.py --calc-id` substring match (CL.T4) already finds the `parent_`/`child_`-prefixed ids, so the operator-facing gap is covered; the jq-uniformity nit remains LOW. |
| HA-27 | DOWNGRADED → opportunistic. Manual SKIPPED-vs-ERROR mapping + `lifecycle_id=""` on enrich/drift/manual (E27) — honest-verbatim-empty; one extra SELECT column at next touch. |
| HA-28 | **CLOSED** — bracket SKIP + `junction_exists` replay SKIP on-change-deduped (bounded LRU `_attr_skip_is_repeat`); first-emit + transition-re-emit + steady-suppress all pinned. |
| HA-29 | DOWNGRADED → opportunistic (NIT payload bag). |
| HA-30 | DOWNGRADED → opportunistic (3 docstring `corr-tap:` anchors miss the `#` grep). |
| HA-31 | DOWNGRADED → opportunistic. Disabled-cost-of-payload-build at the matcher/close_build/funding `finally` blocks: a pre-`enabled()` gate is a micro-optimization for `CORR_LOG_ENABLED=0`, which is NOT the operating mode (the log runs enabled); the cost is a discarded dict-build of a few µs; the generic disabled-emit no-op IS pinned (`test_per_emit_budget` disabled p95 < 3 µs). Adding pre-gates at 3 sites = speculative churn (CLAUDE.md). |
| HA-33 | DOWNGRADED → opportunistic. Funding pins (`reconcile_queued:false`, `n_rows_processed`); the cookbook caveat (CL.T4) is the operator-facing close. LOW test-debt. |
| HA-34 | out-of-scope here — cookbook-owned (CL.T4 documents the terminal-replay `rowcount=0` discriminator). |
| HA-35 | **CLOSED** — `db_write ok:false table=orders` failure twin in `order_enrichment._apply_link`; `test_ha35_…` pins LINKED + twin + ABSENT `link_transition`. |
| HA-36 | ACCEPTED — `reconcile_closed_position_funding` rollup UPDATE stays untapped; the spec's named-10 doesn't include it (code matches spec). The funding-rollup write is a derived re-summation, not a money-path identity write; the underlying `insert_funding_event` IS tapped. Re-elevate if the reconciler needs the rollup write visible. |
| HA-37 | DOWNGRADED → opportunistic. (a) flag-flip-with-same-badge drift-sig: the flags-drive-re-emit property IS exercised by `test_stamped_then_sl_removal_badge_transition` (a flag change re-emits); the residual is a NIT same-badge variant. (b) a generic "every attr envelope carries the 4-key identity tuple" drain-time validator conflicts with the KNOWN per-category deviations (E26 two-party prefixes, E27 `lifecycle_id=""`) — it would have to encode those exceptions, duplicating the per-category tests. |
| HA-38 | out-of-scope here — record-only / E15 precedent (cancelled deferred close-build reads `ERROR/build_incomplete`); CL.T4 cookbook documents it. |
| HA-40 | **CLOSED** — `attr_close_stamp` (10th attr; spec §15 E30/E31) taps `_stamp_closing_fill_attribution`; `test_ha40_…` pins ASSIGNED/SKIPPED/domain-filter. |
| HA-41 | **CLOSED** — `log_event`/`log_trade_event` got `db_write ok:false` failure twins (the T3a pattern); two HA-41 twin tests (factory-subclass INSERT-fail injection). |
| HA-42 | out-of-scope — latent ENGINE defect; the **first input to the attribution-reconciler program** (§9.5). The new dedup keys make it one-grep findable. |

### 9.5 After this program

**The correlation-log program is COMPLETE** (Phases 0–5, 12 tasks,
2026-06-10 → 2026-06-14). All §10 acceptance criteria are met (criterion
#5 met-by-substitution — §15 E29). Whole-engine coverage; NDJSON sink;
46-category registry (10 attribution); `corr_tail.py` + jq/DuckDB cookbook
reader; falsifiable perf gate; the 8 historical linkage bugs each
one-query diagnosable.

The **attribution reconciler** (spec §12) is the next program — a separate
plan + spec. The correlation log's §5.6 baseline (including SKIPPED lines)
is its safety net: diff the pre/post `attr_*` streams for the replayed
scenarios to prove the consolidation is faithful. Its **first filed input
is HA-42** (the latent mid-fill double-junction `contributed_qty`
over-count corridor) — now one-grep findable via the `junction:{fid}` +
`replay:{eoid}` dedup keys this program shipped; alongside the §5.6
baseline-diff method (spec §12).

---

*End of implementation plan. Spec in
[correlation_log_spec.md](correlation_log_spec.md).*
