# Correlation Log — Consolidated Spec

**Status**: design rev 2 — audited (4 adversarial agents, 2026-06-10), pending implementation
**Created**: 2026-06-10
**Branch**: `v2.5/correlation-log`
**Scope**: an observability spine — a uniform, correlation-id-threaded event
log spanning **every boundary of the engine** (HTTP in/out, all inbound WS
streams, venue + other outbound HTTP, internal state mutations, DB writes,
event_bus publishes, attribution decisions, WS connection lifecycle).
Whole-engine coverage; NDJSON sink; daily rotation, ~7-day retention.

**Operator decisions (2026-06-10, captured at scoping):**
- **Sink** = **JSON Lines (NDJSON)** file, daily-rotated — the institutional
  structured-log standard; not a DB table, not a delimited text format (D2).
- **Scope** = **whole-engine** from the first cut (not linkage-domain-first).
- **Retention** = daily rotate, keep ~7 days.
- **Process** = spec + implementation-plan docs first, audited before build.

**Rev 2 (2026-06-10)**: incorporates the 4-agent adversarial audit —
architectural feasibility (drain/overflow/bus mechanics), boundary
completeness (platform WS, news WS, pubsub/SSE, outbound-HTTP bypasses),
plan structure (deps, splits, drift defense, falsifiable perf), and the
known-bug replay (SKIPPED outcomes, WS lifecycle, drift-check, orders-table
taps). Replay target: all 8 historical linkage bugs must be FAST-diagnosable
(§10.10).

---

## 1. Purpose

The engine is **observe-only** (it watches Binance user-data + market WS
and reconciles fills → positions → calcs; it does not place orders). The
live calc-linkage debug session (2026-06-08/09) stabilised linkage but was
whack-a-mole: **the root cause of ~every bug was identity/attribution
reconciliation done ad-hoc across many sites** (matcher, close-builder,
live-enricher, drilldown, ⑨ close-tpid, bracket inheritance, …), each with a
different rule — so fixing one site shifted load onto another (the ⑨ →
close-recording regression was the textbook proof).

Two structural cures follow, in order:

1. **This program — the correlation log** (observability spine). Make every
   attribution decision, every boundary crossing, and every state mutation
   *visible*, threaded by a correlation id, in one uniform envelope.
2. **Next program — the attribution reconciler** (ONE module owning
   fill → position → calc, stamping identity once so the consumers stop
   re-deriving). The log de-risks it: you will *see* every attribution
   decision before and after the refactor.

This spec covers **#1 only**. The reconciler is explicitly out of scope
(§13), but the log is designed so its decisions are the highest-value thing
the log captures (§5.6).

### What the log is

A single, append-only, correlation-id-threaded record of *what crossed each
boundary and what the engine decided internally* — **including decisions NOT
taken** (skips, early-returns, misses; see §5.6) — in one envelope shape,
written to a rotating NDJSON file. It answers, for any single trigger
(an HTTP request, an inbound WS frame, a scheduler tick):

> "Show me everything that happened because of this — the inbound message,
> every internal decision it caused (or skipped, and why), every REST call it
> triggered, every bus event it published, every row it wrote, and the
> response that went back out — in causal order, on one screen."

### What the log is NOT (see §13 for the full list)

- **Not** a replacement for `app_state` (the source of truth for live state).
- **Not** a replacement for `engine_events` (typed engine-behaviour audit) or
  `trade_events` (typed trade-lifecycle audit). Those stay — queryable,
  per-account, typed. The correlation log is the *connective tissue between*
  them, not a third silo that duplicates them.
- **Not** a source of truth / event store. No event sourcing; the log is
  derived, lossy-tolerant, and safe to delete. (Event sourcing deferred —
  §13.)
- **Not** on the hot path. Emission is non-blocking; a slow or full disk must
  never stall WS ingestion, the bus dispatch loop, or an HTTP response.

---

## 2. Why extend, not add a fifth silo

The engine already has four relevant systems. The gap is narrow and
specific — do not rebuild what exists.

| System | File | What it is | What it lacks |
|---|---|---|---|
| `event_bus` | `core/event_bus.py` | in-process `asyncio.Queue` pub/sub; sequential dispatch; `subscribe_all()` catch-all | carries no correlation id across the publish→consume task boundary |
| `engine_events` | `core/event_log.py` | per-account SQLite; typed `EventType` enum (13); engine-behaviour audit | no correlation id; no envelope; rows are independent atomic facts |
| `trade_events` | `core/trade_event_log.py` | per-account SQLite; typed `TradeEventType` enum (13); `calc_id`-anchored lifecycle | `calc_id` threads *within one trade lifecycle only*; no `direction`/`peer`; no chain across non-trade boundaries |
| `core/pubsub` | `core/pubsub/bus.py` + `channels.py` | a SECOND pub/sub (InProcess or Redis) fanning position/fill/order/equity/dd updates to the browser via SSE (`api/routes_streams.py`) | entirely separate from `event_bus`; no correlation; high-frequency (per recalc cycle) |

**Confirmed gaps** (verified against the schemas + code, 2026-06-10):

1. **No correlation id threads a request → derived-actions → response
   chain.** `trade_events.calc_id` is a within-lifecycle anchor; it does not
   connect an inbound WS frame to the REST call it triggered, the bus event
   it published, and the response it produced. `engine_events` rows carry no
   correlation id at all.
2. **No uniform envelope across boundaries.** Each row in each system is
   ad-hoc-shaped. There is no `direction` (in/out/internal), no `peer` (who
   was on the other side of the boundary), no single shape that a tap at any
   boundary can fill.

The correlation log closes exactly these two gaps:
- **(1) a `corr_id`** minted at each entry point and carried via Python
  `contextvars` across every `await` in that task (`contextvars` is used
  nowhere in the codebase today — clean greenfield), plus carried explicitly
  across the **queue hand-offs** contextvars cannot cross (§6.2).
- **(2) one uniform envelope** (§4) that every boundary tap fills.

It **taps `event_bus` dispatch** (so every bus publish AND per-handler
delivery is logged with the publisher's corr_id, §5.2), and taps the
`core/pubsub` publish chokepoint (§5.7). It **reuses** `json_safe()`
(`core/context_query.py`) for non-finite floats and the `audit.jsonl` NDJSON
precedent (`core/audit.py`) for the file sink.

---

## 3. Correlation id (`corr_id`)

### 3.1 Semantics

A `corr_id` identifies **one causal chain**: a single external/temporal
trigger and everything the engine does because of it. It is minted **only at
true entry points** and inherited everywhere downstream — so a REST call made
*during* an HTTP request or *during* a scheduler tick carries that entry
point's corr_id, not a fresh one.

### 3.2 Entry points (where a corr_id is minted)

| Entry point | Site | corr_id prefix | Notes |
|---|---|---|---|
| HTTP request | FastAPI middleware (`main.py`, new) | `http` | one per request; covers all (~150) routes across the 21 routers. **HTTP middleware does NOT run for WebSocket scope** — WS endpoints mint their own (below). |
| Inbound WS — Binance user-data | `core/ws_manager.py::_user_data_loop` receive (`async for raw in sock`) | `wsu` | one per frame (account/order/algo updates) |
| Inbound WS — Binance market-data | `core/ws_manager.py::_market_stream_loop` receive | `wsm` | one per frame (kline/depth/markPrice); **volume-gated** (§7.3) |
| Inbound WS — Quantower platform | `core/platform_bridge.py` message dispatch (frames: hello / fill / historical_fill / account_state / order_snapshot / position_snapshot via `/ws/platform`) | `wsp` | one per frame. **Money-path critical**: `_handle_fill` feeds `order_manager.process_fill`, so attribution taps fired from platform fills must carry a chain. |
| Inbound WS — BWE news | `core/news_fetcher.py::BweWsConsumer.run` | `wsn` | one per frame; not a scheduler tick loop |
| Scheduler / background loop tick | **blanket rule**: every `_spawn`'d root loop body (`core/schedulers.py`), PLUS the loops living elsewhere — `ws_manager._keepalive_loop`, `ws_manager._fallback_loop`, `MonitoringService.run` (`core/monitoring.py`), `webhook_dispatcher.run`, the reconciler periodic pass | `sch` | one per tick iteration; label carries the loop name, e.g. `sch-funding`, `sch-keepalive`. The rule is **structural** ("every spawned root loop gets a scope"), not a hand-counted list — counts drift. |
| Startup | `_startup_fetch` | `boot` | one scope for the whole startup fetch |
| Fallback (no ambient scope) | `core/adapters/base.py::_run` | `rest` | a one-shot `rest-{hex}` so the out/return pair still correlates to each other; reaching this fallback should be **rare** — a `corr_id=""`/fallback envelope is itself a finding that an entry point is missing a scope |

**Format**: `{prefix}-{8 hex}` (e.g. `http-7f3a2c91`, `wsu-1b9e04af`). Short,
greppable, prefix tells you the trigger class at a glance. Minted with
`uuid4().hex[:8]` (collision-irrelevant at this scale; not a security token).

### 3.3 Propagation

- A module-level `contextvars.ContextVar[str]` (`corr_id_var`, default `""`)
  holds the current chain. `contextvars` auto-propagates across `await`
  within the same task — **no signature threading** — and `asyncio.create_task`
  copies the context, so handler-spawned sub-tasks inherit automatically
  (verified: the deferred close-build `call_later`, `set_calculator_symbol`'s
  `create_task(restart_market_streams())`, and the `to_thread`'d sync writers
  all inherit with zero wiring).
- Entry points set it via a context-manager / decorator
  (`with correlation_scope(prefix):`) making mint+reset symmetric.
- **Queue hand-offs contextvars can NOT cross** — anywhere a producer
  `put`s onto a queue consumed by a *different* task, the corr_id must be
  carried in the queued item and re-bound by the consumer. There are
  exactly two such hand-offs today, both in scope:
  1. **`event_bus`** — the dispatch loop runs in its own task (§6.2).
  2. **`webhook_dispatcher`'s internal queue** — the bus handler enqueues;
     the POST happens in the separate worker task. The queued tuple gains
     the corr_id; the worker re-binds before POSTing so the outbound webhook
     tap stays correlated (§5.3b).
  (The notification center also buffers, but its delivery is operator
  **polling** — cross-chain by design; no carry needed. Noted in §13.)
- **Thread rule** (load-bearing; verified empirically on the project's
  Python): `asyncio.to_thread` **copies** context (corr_id survives);
  `loop.run_in_executor` does **NOT**. Therefore: **taps emit on the loop
  side of `_run`, never inside the executor callable.** Any future tap
  placed inside pool-thread code would silently read `corr_id=""` — this
  rule is the guardrail.

### 3.4 Relationship to existing ids

`corr_id` is **orthogonal** to the linkage ids (`calc_id`, `position_id` /
`terminal_position_id`, `lifecycle_id`, `order_id`). Those identify *trade
entities*; `corr_id` identifies *one processing chain*. The envelope's
`payload` carries whichever entity ids are in scope (so you can pivot the log
by `calc_id` AND by `corr_id`) — and for lifecycle/attribution categories the
identity tuple is **mandatory, verbatim, including empty** (§5.6). The log
does **not** mint or own any entity id — it only observes and records them.

---

## 4. The envelope

Every tap, at every boundary, emits exactly this shape. One JSON object per
line (NDJSON).

```json
{
  "ts":        "2026-06-10T13:27:45.123456Z",
  "seq":       148213,
  "corr_id":   "wsu-1b9e04af",
  "task":      "ws-user",
  "account_id": 2,
  "symbol":    "XAUUSDT",
  "component": "order_manager",
  "peer":      "binance",
  "direction": "in",
  "category":  "ws_order_update",
  "payload":   { "...": "category-specific, json_safe'd, size-capped" }
}
```

| Field | Type | Meaning |
|---|---|---|
| `ts` | str | ISO-8601 UTC, microsecond precision. Matches existing log convention. |
| `seq` | int | Process-local monotonic counter, allocated **atomically at emit time** (`itertools.count`; `next()` is atomic under the GIL) so it reflects true emission order. Exact total order = sort by (`ts`, `seq`); the file is near-sorted (drain order) but `seq` is the truth. The load-bearing field for ordering races. |
| `corr_id` | str | The chain id (§3). `""` if emitted outside any scope — rare by design; flagged (§3.2 fallback row). |
| `task` | str | **Which concurrent worker emitted this.** Resolution rule: `try: asyncio.current_task().get_name() except RuntimeError: threading.current_thread().name` (`current_task()` *raises* off-loop — verified). The ws_manager tasks must be **named** (`ws-user`, `ws-market`, …) at every `create_task` site *including reconnect respawns* (today they are unnamed → auto `Task-N`). The key field for *race* debugging (§4.1). |
| `account_id` | int \| null | Scope. Resolved from the message, else `app_state.active_account_id`. Null when genuinely account-agnostic (boot, exchange_info). |
| `symbol` | str \| null | The ticker this line concerns, **top-level because ticker is a primary debugging axis**. Canonical here; payload tables in §5 may repeat it for self-containedness, top-level wins. Null for account-/portfolio-/boot-level lines. |
| `component` | str | The subsystem emitting. Closed-ish set: `http`, `ws_manager`, `platform_bridge`, `news_fetcher`, `order_manager`, `data_cache`, `calc_state`, `link_state`, `adapters.binance` (`.bybit`/`.mexc`), `event_bus`, `pubsub`, `scheduler`, `webhook_dispatcher`, `funding_handler`, `reconciler`, `db`. |
| `peer` | str | The other side of the boundary. `binance`, `quantower`, `operator` (browser), `finnhub`, `fred`, `yahoo`, `bwenews`, `subscriber` (webhook receiver), `event_bus`, `internal`, `disk`. Every peer listed here is **reachable by at least one §5 category** (audit rule: no dead peers). |
| `direction` | enum | `in` (entering the engine), `out` (leaving the engine), `internal` (engine→engine). |
| `category` | str | The typed event kind within (component, direction). The taxonomy — §5. Backed by a **registry** (§5.8), not a closed Python `Literal`. |
| `payload` | obj | Category-specific. **`json_safe()`-coerced** (non-finite floats → null). **Size-capped** (§7.4): oversized payloads are summarised + truncation-flagged, never silently dropped. |

**Design notes:**
- `(component, direction, category)` is the discriminator — a reader filters
  on these the way you'd filter a typed enum.
- `corr_id` + `seq` together give you "everything in this chain, in order".
- The envelope is **flat** (no nesting except `payload`) so `jq` / grep
  recipes stay trivial (§9).
- **Format = JSON Lines (NDJSON)** — one JSON object per line. The
  institutional standard for structured logs (Elastic/Splunk/Loki/Datadog
  ingest it natively); robust to arbitrary field content + schema evolution
  (a delimited text line breaks on separator-in-data and can't add fields
  cleanly); and loads directly into DuckDB / sqlite / pandas for ad-hoc
  SQL-style sort/group/join when grep/`jq` isn't enough. A delimited
  text format was rejected as the legacy approach (fragile, non-evolvable).
- **Sliceable dimensions** = every top-level field (`ts`, `corr_id`, `task`,
  `account_id`, `symbol`, `component`, `category`, `direction`). Filter/sort
  by any combination; the details live in `payload`.

### 4.1 Race & duplicate debugging (a first-class goal)

Nearly every linkage bug in the 2026-06 debug session was a **race**
(fill-mint race, close-tpid race, the publish-vs-load race), a **silent
skip** (early-return on missing identity), or a **double-process**. A plain
log can't debug those — it doesn't say what ran *at the same time*, what
truly happened *first*, or what *didn't happen at all*. The envelope is
shaped so all three are answerable by reading, not guessing.

**Four mechanisms, built into the envelope/sink:**

1. **`seq` + single global stream → true ordering.** Every line is one
   append-only, time-ordered stream across all chains and all accounts.
   `seq` is stamped atomically at birth, so even two events in the same
   millisecond have a defined order. "What happened first?" = sort by
   (`ts`, `seq`).

2. **`task` → true concurrency.** Two lines with different `task` values in
   the same time window genuinely ran at once (the engine has real
   concurrency: the WS handlers, the scheduler loops, and the 8-thread
   REST pool all run alongside the sequential bus consumer). `task` turns
   "were these racing?" into a column you can read.

3. **`dedup_key` on lifecycle taps → duplicate detection.** Lifecycle-
   critical taps (WS order/fill updates, fill processing, attribution,
   funding — §5.6's `attr_funding_assign` included) include a
   `payload.dedup_key` built from the venue's own ids (e.g.
   `orderId:status:qty`, `venue_event_id`). The same key twice = a
   redelivery / re-process. One grep surfaces it; a second `attr_*` decision
   line for the same key = a double-process bug.

4. **Mandatory SKIPPED/ERROR outcomes → absences become lines** (§5.6).
   Three of the eight historical bugs were silent early-returns (`if not
   pos.position_id: continue`). A decision log that omits non-decisions
   renders the most common bug shape as an *absence* — the hardest thing to
   query. Every attribution tap emits exactly one envelope per invocation,
   including `outcome=SKIPPED` with a machine-readable reason.

**What a race looks like in the log** — a WS fill being attributed while a
position-snapshot refresh wipes the position out from under it (the close-
tpid race), two chains interleaved on one timeline:

```
seq   ts            corr_id      task       category
4471  …10.220       wsu-7c91     ws-user    ws_order_update  BTCUSDT id=8821 FILLED qty=0.42
4472  …10.221       sch-acct-3b  sched      rest_return      fetch_positions → 0 positions
4473  …10.222       sch-acct-3b  sched      position_snapshot_applied  closes_detected=[(BTCUSDT,LONG,POS-9)]
4474  …10.223       wsu-7c91     ws-user    attr_tpid_resolve  live PositionInfo GONE → entry-order fallback → POS-9
4475  …10.224       wsu-7c91     ws-user    attr_close_build   strict_key=POS-9 → 0 rows; walk → 2 rows (tpid empty:2) → close WRITTEN tpid=POS-9
4476  …10.225       wsu-7c91     ws-user    db_write           closed_positions INSERT tpid=POS-9
```

You can *read* that the scheduler (seq 4473) removed the position one
millisecond before the WS handler's tpid-resolve (seq 4474), and see the
fallback tier fire **because** the live position vanished. That is a race you
can point at.

**Supporting taps for race forensics:**
- **Lock-wait annotation.** The **async** `data_cache` mutation taps (§5.5)
  carry `waited_ms` (time blocked on the single-writer `asyncio.Lock`) and
  `held_ms`. Scoped to the lock-acquiring apply paths only — the sync
  mutators (`apply_mark_price`/`apply_kline`/`apply_depth`) never touch the
  lock, so they carry no lock fields. Long waits = contention; a mutation
  that "happened late" because it waited on the lock is visible, not
  inferred.
- **The bus is sequential** (one consumer), so bus deliveries never race each
  other — but a bus delivery CAN race a WS handler or a scheduler tick. The
  `task` field distinguishes the bus consumer (`task=bus`) from the others.

**Reader support:** the reader (§9) has an **interleave view** — show every
chain in a time window with `corr_id` and `task` as side-by-side columns, so
two stickers colliding are obvious at a glance.

---

## 5. Taxonomy (categories by boundary)

Whole-engine coverage — and "whole-engine" means **boundaries enumerated
from the code, not from memory** (the rev-1 audit found four missing
boundary families). Categories are grouped by the boundary they tap. This is
the target set; the implementation plan phases them in.

### 5.1 HTTP boundary (`component=http`, `peer=operator`)

| direction | category | payload essentials |
|---|---|---|
| `in` | `http_request` | method, path, query (sans secrets), client, content_length |
| `out` | `http_response` | status, path, duration_ms, content_length |

One corr_id spans the request; the response shares it. **Streaming/SSE
endpoints** (`/stream/*`, `EventSourceResponse`): `http_response` fires at
stream close with the total duration — a multi-hour `duration_ms` on an SSE
route is normal, not a bug; the reader should know this.

### 5.2 event_bus boundary (`component=event_bus`, `peer=event_bus`)

| direction | category | payload essentials |
|---|---|---|
| `internal` | `bus_publish` | channel, payload-summary, n_subscribers |
| `internal` | `bus_deliver` | channel, handler (subscriber name), ok/err, duration_ms |

**Mechanism (corrected in rev 2):** both taps are emitted by the
**instrumented dispatch path in `core/event_bus.py` itself** — `bus_publish`
at enqueue (publisher's context), `bus_deliver` from the dispatch loop,
one envelope **per handler invocation** (only the loop can see which handler
ran, whether it raised, and how long it took; a `subscribe_all` catch-all
cannot — it receives `(channel, payload)` only, after the per-channel
handlers, with exceptions already swallowed). There is NO separate
correlation-log bus subscriber.

Coverage is **structural**: any publish on any topic produces a
`bus_publish` + one `bus_deliver` per handler — verified by a unit test on
the instrumented paths plus representative end-to-end topics, **not** a
hand-pinned "all 21 topics" list (the topic set drifts; `calc:partially_filled`
is catalogued with no live producer, and `link_state.TRANSITION_EVENT_MAP`
adds topics when populated).

### 5.3 Venue REST boundary (`component=adapters.*`, `peer=binance|bybit|mexc`)

| direction | category | payload essentials |
|---|---|---|
| `out` | `rest_call` | endpoint (ccxt fn name), args-summary, priority |
| `in` | `rest_return` | endpoint, ok/err, duration_ms, error_type (on failure), result-summary |

Chokepoint: `core/adapters/base.py::_run` — covers every venue call routed
through the three adapters. **Tap placement rule:** emit on the **loop side**
of `_run` (before/after `await loop.run_in_executor(...)`), never inside the
executor callable (`run_in_executor` does not propagate contextvars — §3.3).
Consequently `task` on REST envelopes is the *calling* task, by design.

**Known bypasses** (direct ccxt / own HTTP stacks that do NOT route through
`_run`): the connection-test calls (`core/connections.py::_test_provider`)
and `core/account_registry.py`'s ad-hoc executor calls — operator-triggered,
rare, inside an HTTP-request scope anyway; and yfinance's internal requests
(`core/regime_fetcher.py`). Accepted gaps, listed in §13 — the *callers* of
the latter are covered by §5.3b.

### 5.3b Other outbound HTTP (`direction=out|in`, generic)

The venue chokepoint does not cover four real outbound families. Generic
categories, component = the emitting module:

| category | component | peer | payload essentials |
|---|---|---|---|
| `http_out_call` / `http_out_return` | `webhook_dispatcher` | `subscriber` | url-host, event, attempt#, ok/err, status, duration_ms |
| `http_out_call` / `http_out_return` | `news_fetcher` | `finnhub` | endpoint (news/calendar), ok/err, duration_ms, n_items |
| `http_out_call` / `http_out_return` | `regime_fetcher` | `fred` \| `yahoo` | series/ticker, ok/err, duration_ms |

The webhook tap is the one that needs the §3.3 queue-carry: the POST runs in
the dispatcher's worker task, re-bound to the originating close's corr_id.

### 5.4 Inbound WS frame boundary (`direction=in`)

| component | peer | category | payload essentials |
|---|---|---|---|
| `ws_manager` | `binance` | `ws_account_update` | event_type, balances/positions summary |
| `ws_manager` | `binance` | `ws_order_update` | order_id, status, side, qty, price, **dedup_key** (`orderId:status:qty`) |
| `ws_manager` | `binance` | `ws_algo_update` | algo type, status, **dedup_key** |
| `ws_manager` | `binance` | `ws_kline` | interval, close (volume-gated, §7.3) |
| `ws_manager` | `binance` | `ws_depth` | top-of-book (volume-gated, default OFF) |
| `ws_manager` | `binance` | `ws_mark_price` | mark (volume-gated, default OFF, sampling available) |
| `platform_bridge` | `quantower` | `platform_fill` / `platform_snapshot` / `platform_hello` | frame type, fill/order/position summary, **dedup_key** on fills |
| `news_fetcher` | `bwenews` | `ws_news` | headline id, source |

Outbound engine→Quantower sends (`push_risk_state`, `request_*`,
`_send_to_clients`) get the mirror category `platform_push` (`out`,
`peer=quantower`).

### 5.4b WS connection lifecycle (`component=ws_manager`, `direction=internal`)

**New in rev 2** — the rev-1 taxonomy covered WS *messages* but not the
*connection*, leaving the ticker-switch subscription-leak bug (historical #4)
completely invisible. Categories (cheap to add — `ws_status.add_log` already
exists at every one of these sites):

| category | payload essentials |
|---|---|
| `ws_connect` | stream (user/market/news/platform), **full subscribed-stream list**, attempt# |
| `ws_connected` | stream, duration-to-connect |
| `ws_disconnect` | stream, reason (error/close/reconnect), uptime_s |
| `ws_stream_rebuild` | trigger (`calc_symbol_change` \| `position_change` \| `reconnect`), **old-streams → new-streams diff** |
| `calc_symbol_change` | old symbol, new symbol, restart_scheduled? |
| `ws_listenkey_keepalive` | ok/err |

The leak bug becomes one query: a `calc_symbol_change` with no subsequent
`ws_stream_rebuild`, or a `ws_connect` stream list still containing the old
symbol. The market-loop self-respawn (the stale-`_market_ws_task` sub-bug)
is a `task`-field story: the respawned loop's task name shows the lineage.

### 5.5 State-mutation + persistence boundary (`direction=internal`)

| component | category | payload essentials |
|---|---|---|
| `data_cache` | `position_snapshot_applied` | n_positions, trigger, **closes_detected = list of (symbol, side, tpid)** (not just a count — the §4.1 walkthrough depends on it), waited_ms/held_ms |
| `data_cache` | `position_incremental_applied` | symbol, side, qty before/after, **terminal_position_id + tpid_minted/tpid_present flags** (makes the mint visible — the fill-mint race needs a visible second racer), waited_ms/held_ms |
| `data_cache` | `account_update_applied` | source (rest/platform), equity before/after, waited_ms/held_ms |
| `data_cache` | `portfolio_recalculated` | dd_state, weekly_pnl_state (**on change only**) |
| `calc_state` | `calc_transition` | calc_id, from, to, reason |
| `link_state` | `link_transition` | order_id, from, to |
| `order_manager`/`db` | `order_status_applied` | order_id, status before→after, **source (`ws` \| `reconcile` \| `stale-mark`)**, dedup_key of the triggering frame |
| `reconciler`/`scheduler` | `reconcile_promote` | promoted order_ids + count — each line doubles as a "venue terminal frame was missed" detector (the stale-orders bug, historical #f) |
| `db` | `db_write` | **table, op (INSERT/UPDATE/UPSERT/DELETE), key ids (tpid/calc_id/order_id, verbatim incl. `""`), rowcount** — at the ~10 money-path writer chokepoints: `upsert_order_batch`, `upsert_fill`, `upsert_fill_and_update_order`, `insert_closed_position`, the `positions_calcs` upsert, `insert_funding_event`, `insert_pre_trade_log`, MFE/MAE updates, `reconcile_filled_orders`, backfills | 

`db_write` makes `peer=disk` live and answers "**what rows did this chain
write?**" — the HANDOFF bugs were literally "close row NOT written / junction
missing", so the write boundary is tapped, not inferred. (The two audit-log
writers `log_event`/`log_trade_event` are also `db_write` sites — one line
each, giving the chain-join into the typed audit tables.)

Lock annotations (`waited_ms`/`held_ms`) apply **only** to the async
lock-acquiring apply paths; the sync mutators have no lock to measure (§4.1).

### 5.6 Attribution-decision boundary — **the highest-value taps**
(`direction=internal`, `peer=internal`)

These are the ad-hoc reconciliation sites the next program will unify.
Logging them is the whole point: every attribution decision becomes visible,
with its inputs, the rule applied, and the outcome.

**Three mandates (rev 2), binding on every category in this section:**

1. **One envelope per invocation, no silent exits.** Every tap emits exactly
   once per call — including `outcome=SKIPPED` with a machine-readable
   `reason` code (`no_position_key`, `empty_tpid`, `no_parent_found`,
   `not_linked`, …) on early-return paths, and `outcome=ERROR` on exception
   paths (tap in `try/finally`). Three of the eight historical bugs were
   silent early-returns; absences must be lines, not holes.
2. **The identity tuple is mandatory, verbatim, including empty.** Every
   payload carries `tpid`, `calc_id`, `exchange_order_id`, `lifecycle_id` —
   `""` when unresolved. `select(.payload.tpid=="")` is the canonical
   stranded-row query (the close-side tpid race is exactly a row written
   with `tpid=""`).
3. **`dedup_key` of the triggering fill/order** on every decision line, so a
   duplicate decision is a one-grep find (§4.1).

| category | site (verified) | payload essentials (beyond the mandates) |
|---|---|---|
| `attr_match_attempt` | `core/calc_correlation.py::correlate_order_to_calc` invoked from `core/order_enrichment.py::_try_correlate` (NOT order_manager — rev-1 had the wrong file); also the manual-link candidate path (`core/link_actions.py`) | candidate calc_ids, per-criterion pass/fail, tolerances (entry 0.25%), chosen calc_id or NEEDS_MANUAL_REVIEW + reason |
| `attr_tpid_resolve` | `order_manager::_resolve_close_tpid` + snapshot-recovery re-derivation | which tier resolved (live PositionInfo / entry-order fallback / strict / walk), inputs, result |
| `attr_close_build` | `order_manager::_build_close_row_for_fill` | **strict_key (the tpid queried), opens_found_strict, opens_found_walk, open_fill_tpids summary `{empty: N, populated: M}`**, fallback-walk used?, backfill count, close row written? — one line must read "strict key POS-9 → 0 rows; walk → 2 rows, both tpid-empty": root cause on one screen |
| `attr_bracket_inherit` | `order_manager::_propagate_bracket_calc_id` | parent order_id, child order_id, inheritance path, calc_id propagated |
| `attr_reenrich_trigger` | `order_manager::_reenrich_parent_on_child` + `_ensure_junction_if_linked` (**new in rev 2** — the child-arrival → parent-re-enrich decision, historical bug #g, commit 073f2de; the inverse inference of bracket-inherit) | child order_id, parent lookup key (symbol, position_side), parent_found?, re-match triggered? |
| `attr_junction_form` | `order_manager` junction (re)creation sites | order tpid, calc_id, junction created/updated |
| `attr_enrich` | `order_manager::_enrich_positions_calc_id` | position_id/tpid empty?, re-derivation source, badge stamped. **On-change gated**: this runs per position on every WS order update — emit on outcome change / first stamp, not every pass (§7.3) |
| `attr_drift_check` | the live TP/SL drift + removal check inside enrichment (**new in rev 2** — without it the SL-removal badge bug, historical #h, is invisible: the wrong verdict gets recorded self-consistently) | **planned_tp/sl, live_tp/sl, tp_drift/sl_drift, tp_removed/sl_removed flags, badge before→after** — emitted on badge *transition* + first stamp. One line shows "planned_sl=2310, live_sl=0, sl_removed=false, badge=green": the buggy guard visible in its own output |
| `attr_funding_assign` | `core/funding_handler.py` (**new in rev 2** — genuine identity attribution: open-position-cache hit vs closed-window fallback vs orphan; primary-calc resolution; has a documented close+reopen mis-attribution edge) | income row id (dedup `venue_event_id`), resolution path, tpid/calc assigned or orphan |

Nine categories. After the reconciler ships, these taps move to the single
owner and collapse toward one `attr_decide` — the log will *prove* the
consolidation is faithful (same decisions, one site; §12).

*Not* an attribution site (deliberate, so nobody re-adds it): the
**reconciler** (`core/reconciler.py`) re-derives price extremes (MFE/MAE),
never identity — its row mutations are covered by `db_write`.

### 5.7 UI pub/sub boundary (`component=pubsub`)

| direction | category | payload essentials |
|---|---|---|
| `internal` | `pubsub_publish` | channel kind (position_update/fill/order_update/equity_update/dd_state/weekly_pnl), backend (inproc/redis) |

One tap at the `get_bus().publish` chokepoint. **Volume-gated like
market-data** (it fires per recalc cycle). The SSE push to the browser
(`api/routes_streams.py`) is deliberately NOT tapped — deferred (§13); the
publish side already shows what the UI was offered.

### 5.8 The category registry (drift defense)

`category` is a free string in the envelope, but **backed by a registry** in
`core/correlation_log.py`: module-level constants, each registered with a
**group** (`http` / `market` / `lifecycle` / `state` / `attr` / `bus` /
`ws_lifecycle` / `outbound` / `db`). The profiles (§7.3) are **derived from
groups** — single source of truth, so a future `attr_*` category can never be
silently absent from the `linkage` profile (the rev-1 design's worst drift
trap: a hand-maintained profile whitelist silently dropping the program's
highest-value signal). A **taxonomy-conformance test** asserts every emitted
category ∈ registry (catches typos like `attr_tpid_resolved`). Adding a tap =
one registry line — which preserves D8's "no add-a-tap-touch-the-enum
coupling" while restoring drift resistance.

**Forward discipline**: every tap callsite carries a greppable anchor
comment `# corr-tap: <category>`. Any future module that crosses an engine
boundary MUST add a tap + registry entry — the same "don't extend the pattern
being removed" asymmetry CLAUDE.md documents for cleanups, inverted: features
that add boundaries faster than taps erode whole-engine coverage silently.

---

## 6. Mechanics

### 6.1 The sink

A new module **`core/correlation_log.py`** owns the spine:

- **`corr_id_var: ContextVar[str]`** + `mint(prefix)` + `correlation_scope(prefix)`
  context manager + `current_corr_id()`. (May live in a tiny
  `core/correlation.py` if an import cycle appears — decided at build time.)
- **`emit(component, peer, direction, category, payload, *, account_id=None,
  symbol=None)`** — the one public tap function, callable from sync OR async
  contexts and from pool threads. **Pipeline order (load-bearing):**
  1. **Enabled-check FIRST** — registry/profile lookup before ANY payload
     work; a disabled category costs ~a dict lookup. High-rate callsites
     whose payload *construction* is itself expensive gate on
     `correlation_log.enabled(category)` before building arguments.
  2. Build envelope (ts, atomic `seq`, corr_id from the contextvar, `task`
     per the §4 resolution rule, account_id/symbol).
  3. Redact (§7.2) + `json_safe` + **one `json.dumps` producing the final
     line string**. The dumps output doubles as the size-cap measurement
     (no double serialization), and **emit-side serialization is the
     mutation-snapshot guarantee**: the drain runs up to ~250 ms later and
     live dicts (positions, account state) mutate — serializing at emit
     freezes the values the race actually saw. (This is why serialization
     must NOT move to the drain.)
  4. Enqueue the **string** — `queue.SimpleQueue.put_nowait` (thread-safe,
     callable from any context).
- **Drain = a dedicated daemon writer THREAD** (not a coroutine — rev-2
  correction: `SimpleQueue.get()` blocks whatever thread calls it, so a
  coroutine drain would stall the event loop, and a `get_nowait`+sleep poll
  can't implement a batch-size wakeup). The writer thread does a blocking
  `q.get(timeout=0.25)`, then drains `get_nowait()` until empty, writes the
  batch (`"\n".join + "\n"`), flushes. Zero event-loop interaction; natural
  batching; shutdown = sentinel + `join` (§6.5). Single writer → ordered.
- **Backpressure**: a max in-flight bound (`CORR_LOG_MAX_INFLIGHT`,
  default 100k — tracked via a counter, since `SimpleQueue` has no maxsize).
  On overflow: **drop + count + rate-limited `logging.error`** (once per
  episode), and when the queue recovers below the bound, enqueue one
  self-describing envelope (`component=correlation_log`, `category=overflow`,
  payload = dropped count + episode span). **NOT an `engine_events` row**
  (rev-2 correction: `log_event` has a closed enum that would raise on an
  unknown type, requires an account_id overflow doesn't have, and is a sync
  sqlite write fired exactly when the system is already saturated).

### 6.2 event_bus carries corr_id (queue hand-off #1)

`event_bus.run()` dispatches in its own task, so a subscriber would lose the
publisher's contextvar. Change to `core/event_bus.py` (small, isolated,
independently revertable):

1. `publish`/`publish_engine`/`publish_engine_nowait` capture
   `current_corr_id()` at enqueue time → the queued item becomes
   **`(channel, payload, corr_id)`**. (`publish_engine_nowait` is called
   from sync code *within a task*, where contextvar capture works —
   verified.)
2. The dispatch loop **re-binds** `corr_id_var.set(stored)` before invoking
   handlers (per event) and resets in a `finally` (dispatch swallows handler
   errors; the reset must not depend on handler success).
3. The dispatch loop emits `bus_deliver` per handler; the publish wrapper
   emits `bus_publish` (§5.2).

**Scope of the inheritance claim (rev-2 correction):** re-binding covers
emits made *during handler execution* (incl. `create_task`-spawned sub-work —
context is copied at task creation). A subscriber that internally **queues**
work for another task starts a new gap — hand-off #2 (webhook dispatcher) is
therefore explicitly carried too (§3.3). Any future internal queue gets the
same treatment; "every queue hand-off carries corr_id" is the rule, not "the
bus is the only one".

**Compat (rev-2 correction):** existing *subscribers* are unaffected, but
~10 test files unpack the internal queue as 2-tuples
(`channel, payload = …`) and one drives `_dispatch(channel, payload)`
directly — the 3-tuple change **breaks them loudly**; the sweep is scoped
in-plan (CL.T2a), not hand-waved as "backward-compatible".

### 6.3 Rotation & retention (Windows-safe by design)

The codebase deliberately uses `ConcurrentRotatingFileHandler` because
stdlib rotating handlers call `os.rename`, which **fails on Windows when the
file is held open** (MED-045). Daily rotation here therefore does **not**
rename:

- The writer thread writes to a **date-stamped filename**:
  `data/logs/correlation/corr-YYYY-MM-DD.jsonl` (UTC date).
- It checks the current UTC date each flush; when it rolls, it closes the
  old handle and opens the new file. **No rename — sidesteps the Windows
  problem entirely** and matches "show me yesterday".
- A prune step (on rollover + at startup — startup covers
  engine-down-at-rollover) deletes `corr-*.jsonl` files older than
  `CORR_LOG_RETENTION_DAYS` (default 7).
- **Per-day size guard** (rev 2): retention bounds *days*, the line cap
  bounds *lines* — nothing bounded one day's file. `CORR_LOG_MAX_MB_PER_DAY`
  (default 512 MB): when the day file exceeds it, the writer stops writing
  envelopes, logs loudly once, and writes a single final `overflow`-style
  marker line. **Disk estimate** for calibration: at a sustained 50
  envelopes/s × ~400 B ≈ 1.7 GB/day uncapped — the default profile
  (market-data gated) is expected to run 1-2 orders of magnitude below
  that; the cap is the runaway-tap backstop.

### 6.4 Write path, threading, loss windows

- `emit` (any context) → serialized line string → `SimpleQueue` → writer
  thread → buffered append (`open(..., "a", encoding="utf-8")`), flush per
  batch/250 ms.
- **Crash loss window**: a hard crash loses the in-queue + unflushed tail
  (≤ ~250 ms + queue depth) — precisely acknowledged: the log is
  lossy-tolerant by design (§1); a best-effort `atexit` flush narrows it.
  Post-crash forensics get everything up to the last flush.
- The existing audit logs (`engine_events`/`trade_events`) write
  synchronously inside async code today; the correlation log is deliberately
  stricter (no sync disk on the hot path) because it taps the high-volume WS
  path.

### 6.5 Startup / shutdown wiring (rev-2 corrections)

- **The queue + `seq` counter are module-level, created at import** — emits
  from requests served before startup completes simply buffer until the
  writer drains them. (FastAPI can serve before `_startup_fetch` finishes:
  it is spawned fire-and-forget precisely so the server accepts connections
  immediately.)
- **The writer thread starts in `main.py` lifespan, BEFORE
  `start_background_tasks()`** — it has zero dependencies on REST/bus/
  Binance, and `_startup_fetch`'s try-block is the wrong home (a startup
  error above the spawn line would silently kill the sink while emits
  buffer to the cap).
- **Shutdown**: an explicit `correlation_log.close()` in lifespan teardown —
  sentinel → writer drains the queue → flush → close → `join`. (Today's
  teardown cancels no background tasks, so a cancellation-triggered flush
  would never run — the explicit call is the only reliable trigger.)
- Guarded by `CORR_LOG_ENABLED` (off = no thread, `emit` no-ops at the
  enabled-check).

---

## 7. Cross-cutting

### 7.1 Account scoping

`account_id` is resolved per-envelope: from the WS message / route where
available, else `app_state.active_account_id` (the SR-2 read-only property).
The log is **one file per day across all accounts** (not per-account like the
DBs) — the `account_id` field is the filter. Single-tenant localhost
(CLAUDE.md Task 163) makes a single multi-account file the simpler choice
(D15).

### 7.2 Secret redaction

Taps must never log secrets. The HTTP `in` tap drops `Authorization`/cookie
headers and known secret query params; the REST/outbound taps log function
names + args-summaries, never API keys/signatures/listen-keys. A central
`_redact()` allow-list/deny-list in the sink enforces this. **Mandatory**
even at localhost — the NDJSON file is a plaintext artifact.

### 7.3 Volume control (whole-engine ⇒ noise control is mandatory)

Whole-engine scope includes the market-data WS (`depth` ~10/s/symbol,
`markPrice` ~1/s/symbol) and the per-recalc `pubsub_publish`. Without
control the log is dominated by noise and the signal (attribution decisions)
is buried.

- Per-category enablement is **derived from the registry groups** (§5.8) per
  profile — no hand-maintained per-category whitelist.
- Defaults: `ws_depth` **OFF**; `ws_mark_price` **OFF** (enable via
  `CORR_LOG_MARK_PRICE_SAMPLE=N` for 1-in-N; rev 2 resolves the rev-1
  sampled-vs-off contradiction: **off is the default**, sampling is the
  opt-in); `ws_kline` ON (low rate); `pubsub_publish` sampled; everything
  else ON.
- **Refresh-driven internal taps are on-change gated**: `attr_enrich` /
  `attr_drift_check` run per position per WS order update — they emit on
  outcome/badge *transition* + first stamp, with a per-(position, outcome)
  dedup, not every pass. Otherwise the linkage profile buries its own
  signal.
- `CORR_LOG_PROFILE` (`full` | `linkage` | `off`): `linkage` = lifecycle +
  state + attr + bus + ws_lifecycle + db groups, market/outbound-news OFF —
  the linkage-first scope as a *runtime profile*, not a separate build.

### 7.4 Payload size cap

`payload` is capped (default 4 KB serialized — measured on the single emit-
side dumps, §6.1). Oversized payloads are replaced with a summary
(`{"_truncated": true, "_bytes": N, "keys": [...]}`) — never silently
dropped (CLAUDE.md "no silent caps"). The full object remains in `app_state`
/ the DBs; the log records that it happened + where to look.

### 7.5 Restart

The log is stateless across restarts except for the date-stamped file
(appended to if the engine restarts the same day). `seq` resets per process
(process-local ordering — settled, was Q4); readers order within a process
run by `seq`, across runs by `ts`. No rehydrate, no migration.

### 7.6 Test isolation

Tests must not write to the live `data/logs/correlation/` dir. Mirror the
existing conftest guard (`_isolate_live_per_account_logs`): an autouse
fixture **patches the sink-dir attribute/resolver on `core.correlation_log`**
(NOT the env var — config is read at import, an env monkeypatch lands too
late; the existing guard patches the resolver function for exactly this
reason) to a tmp path, or disables the sink. Emission helpers are unit-
testable with the sink stubbed (assert envelopes, not files).

### 7.7 Performance budget

- `emit` for a **disabled** category: ~a registry lookup (≈1 µs).
- `emit` for an enabled category: enabled-check + envelope + redact +
  json_safe + one dumps + enqueue — **target < ~50 µs** for typical payloads
  (rev 2: the rev-1 "<20 µs" predates the realization that the dumps is
  emit-side and load-bearing; 4 KB worst-case payloads dump in 10-30 µs
  alone).
- The writer thread is the only disk-touching component; zero event-loop
  interaction.
- Acceptance is **falsifiable** (rev 2): p95 over N=10k synthetic
  frame→state-apply iterations, `full` profile vs `CORR_LOG_ENABLED=0`,
  delta < 5%; `@pytest.mark.timeout(60)`; behind an explicit `perf` marker
  excluded from the default suite (run deliberately in CL.T5) — a wall-clock
  benchmark in the default run is flaky-by-design and trips the 30 s
  timeout discipline.

---

## 8. Configuration (`config.py` + env)

Following the existing env-knob convention (`os.getenv` + `_bounded_float_env`
for numerics):

| Knob | Default | Meaning |
|---|---|---|
| `CORR_LOG_ENABLED` | `1` | master switch (off = no writer thread, emit no-ops) |
| `CORR_LOG_PROFILE` | `full` | `full` \| `linkage` \| `off` — group bundle (§5.8/§7.3) |
| `CORR_LOG_DIR` | `{DATA_DIR}/logs/correlation` | sink directory |
| `CORR_LOG_RETENTION_DAYS` | `7` | prune files older than this |
| `CORR_LOG_MARK_PRICE_SAMPLE` | `0` (off) | 1-in-N sampling for `ws_mark_price` (0 = drop; off is the default, sampling is opt-in) |
| `CORR_LOG_MAX_PAYLOAD_BYTES` | `4096` | payload size cap |
| `CORR_LOG_MAX_INFLIGHT` | `100000` | backpressure bound before drop+count |
| `CORR_LOG_MAX_MB_PER_DAY` | `512` | per-day file size guard (runaway-tap backstop) |

Profiles and category enablement derive from the §5.8 registry groups — no
second source of truth.

---

## 9. Reading the log (operator surface)

NDJSON + flat envelope ⇒ standard tooling. Shipped recipes (Phase 4):

- **One chain in order**:
  `jq -c 'select(.corr_id=="wsu-1b9e04af")' corr-2026-06-10.jsonl`
- **Everything for a ticker** (the `symbol` top-level slice):
  `jq -c 'select(.symbol=="XAUUSDT")'`
- **All attribution decisions for a ticker**:
  `jq -c 'select(.symbol=="XAUUSDT" and (.category|startswith("attr_")))'`
- **Every NEEDS_MANUAL_REVIEW**:
  `jq -c 'select(.category=="attr_match_attempt" and .payload.outcome=="NEEDS_MANUAL_REVIEW")'`
- **Every skipped decision and why** (rev 2 — absences are lines now):
  `jq -c 'select(.payload.outcome=="SKIPPED") | {seq,category,reason:.payload.reason}'`
- **Stranded identity** (the canonical race-damage query):
  `jq -c 'select(.payload.tpid=="")'`
- **A trade's whole life by calc_id** (cross-cuts corr_ids):
  `jq -c 'select(.payload.calc_id=="CALC-...")'`
- **Interleave view — what ran together** (a time window, all chains, with
  task): `jq -c 'select(.seq>=4470 and .seq<=4480)|{seq,corr_id,task,category}'`
- **Find a duplicate** (a `dedup_key` that appears twice):
  `jq -r '.payload.dedup_key // empty' corr-2026-06-10.jsonl | sort | uniq -d`
- **Subscription leak** (rev 2): a `calc_symbol_change` with no later
  `ws_stream_rebuild`, or a `ws_connect` whose stream list still contains the
  old symbol.

For heavier slicing (sort/group/join across a whole day), the file loads
straight into **DuckDB** with no import step —
`SELECT category, count(*) FROM 'corr-2026-06-10.jsonl' GROUP BY 1 ORDER BY 2 DESC`
(DuckDB reads NDJSON natively). This is the sustainability win of NDJSON over
a delimited format.

A small **`scripts/corr_tail.py`** (Phase 4) wraps these: filter by corr_id /
calc_id / symbol / category / time-window and pretty-print one chain in `seq`
order; **`--interleave <from> <to>`** shows every chain in a window
side-by-side (corr_id + task columns) for race forensics; **`--dups`** lists
dedup_keys seen more than once; `--follow` tails live. The reader MUST
tolerate unknown envelope fields (forward compatibility — a mid-week field
addition coexists with older files inside the 7-day window). An optional
read-only admin route (`GET /admin/correlation?corr_id=...`) stays deferred
(Q3) — the file + `jq`/`corr_tail.py` is the primary surface.

---

## 10. Acceptance criteria (program-level)

1. For any single inbound frame (Binance WS, **platform WS**, news WS), HTTP
   request, or scheduler tick, the log contains the entry envelope and
   **every** REST/outbound-HTTP call, bus publish/delivery, state mutation,
   DB write, and attribution decision it caused — all sharing one corr_id,
   ordered by `seq`.
2. **Any** bus publish produces a `bus_publish` + one `bus_deliver` per
   handler, all carrying the **publisher's** corr_id (the task-boundary
   hand-off works) — verified structurally, not against a pinned topic list.
3. All **nine** §5.6 attribution categories fire at their sites with
   inputs + rule + outcome — **including `outcome=SKIPPED` on every
   early-return path** (one envelope per invocation, no silent exits).
4. No secret (API key, signature, listen-key, auth header) ever appears in
   the file.
5. Perf: p95 over N=10k synthetic frame→state iterations, `full` vs
   disabled, delta < 5% (§7.7) — measured by the marked perf test, not
   asserted by hand.
6. Daily rotation produces `corr-YYYY-MM-DD.jsonl`; files older than
   retention are pruned (incl. at startup); the per-day MB guard trips
   loudly; rotation never renames (Windows-safe).
7. The suite never writes to the live correlation dir (§7.6).
8. Disabling (`CORR_LOG_ENABLED=0`) fully no-ops every tap (no thread, no
   disk, ~1 µs per emit).
9. A known **race** (two chains touching the same position in the same ms)
   and a **duplicate** (same `dedup_key` twice) are each reconstructable
   from the log alone — order via (`ts`,`seq`), concurrency via `task`,
   double-process by counting decision lines per key (§4.1).
10. **Known-bug replay**: each of the 8 historical linkage bugs (HANDOFF
    2026-06-09) is FAST-diagnosable — one query — against the taps as built
    (the rev-2 additions §5.4b, §5.5 orders/db rows, §5.6 mandates +
    drift/funding/reenrich categories exist precisely because the rev-1
    replay scored 1 FAST / 5 MEDIUM / 2 BLIND).
11. Emitted categories ⊆ the §5.8 registry (conformance test); every tap
    callsite carries a `# corr-tap: <category>` anchor.

---

## 11. Open questions / decisions resolved at audit

| # | Question | Status |
|---|---|---|
| Q1 | `corr_id` module location — own `core/correlation.py` vs inside `core/correlation_log.py` | OPEN (build-time): inside `correlation_log.py`; split only if an import cycle forces it |
| Q2 | Drain mechanics | **RESOLVED (rev 2)**: dedicated daemon writer thread with blocking `get(timeout)` — a coroutine drain would block the loop; see §6.1 / D16 |
| Q3 | Admin read route (§9) — build now or defer | OPEN: defer (opportunistic); `corr_tail.py` is the committed reader |
| Q4 | `seq` — process-local only, or persist across restarts | **RESOLVED**: process-local (§7.5) |
| Q5 | `bus_publish` AND `bus_deliver`, or deliver-only | **RESOLVED**: both, emitted by the instrumented dispatch path (§5.2) |

---

## 12. Relationship to the next program (attribution reconciler)

Out of scope here, but the log is shaped to de-risk it:

- The §5.6 attribution taps make every current ad-hoc decision visible
  **before** the refactor — a baseline of real decisions, including the
  skips.
- The reconciler collapses the sites into one owner. The log then shows the
  **same** decisions from one site — a faithful-consolidation proof
  (diff the pre/post `attr_*` streams for a replayed scenario). The rev-1
  audit confirmed this diff would have caught the ⑨ → close-recording
  regression *as a regression* (`attr_close_build` flipping strict-hit →
  strict-miss across the ⑨ commit).
- The bus and webhook queues carry + re-bind corr_id (§6.2), so when the
  reconciler emits its single `attr_decide`, it is automatically correlated
  to the inbound frame that triggered it — no extra wiring.

---

## 13. Out of scope / deferred

| Item | Why deferred |
|---|---|
| **Attribution reconciler** | the *next* program; the log exists to de-risk it (§12) |
| **Event sourcing** (log = source of truth, replay-to-rebuild-state) | ~80% of the debuggability for ~20% of the risk comes from the correlation log alone (HANDOFF decision); event sourcing makes the log load-bearing and is a far larger rewrite |
| **Full event-driven core rewrite** | the engine is already reactive at the edges + has the bus for fan-out; "completely event-driven" makes control flow *implicit* (worse debugging) and does not fix attribution |
| **DB-backed correlation table / SQL query route** | operator chose NDJSON; DuckDB-over-NDJSON covers the SQL need; revisit only if proven insufficient |
| **Per-account correlation files** | single multi-account file + `account_id` filter is simpler at single-tenant localhost (D15) |
| **SSE push tap** (`api/routes_streams.py` outbound to browser) | the `pubsub_publish` tap (§5.7) already shows what the UI was offered; per-client SSE taps add volume without debugging value today |
| **Notification-center delivery correlation** | delivery is operator *polling* — cross-chain by design; the bus-side `bus_deliver` to the center is logged |
| **Direct-ccxt bypasses** (`core/connections.py` connection tests, `core/account_registry.py` ad-hoc executor calls) + yfinance's internal HTTP | operator-triggered/rare, already inside an HTTP-request scope; callers covered by §5.3b where they matter. Accepted gaps — listed so they're deliberate |
| **Cross-process / distributed tracing (OpenTelemetry, W3C traceparent)** | single-process localhost engine; homegrown corr_id is sufficient and zero-dependency. If ever distributed, map `corr_id` → `traceparent` then |
| **Sampling/aggregation analytics on the log** | the log is for debugging chains, not metrics |
| **Signed/tamper-evident correlation log** | derived + safe-to-delete; signing unwarranted |

---

## 14. Decisions index

| # | Decision | Rationale |
|---|---|---|
| D1 | Extend the existing systems, don't add another silo | the gap is narrow: a corr_id + a uniform envelope (§2) |
| D2 | **JSON Lines (NDJSON)** file sink — one JSON object per line (not a DB table, not a delimited text format) | operator choice + institutional best-practice: the structured-logging standard (Elastic/Splunk/Loki/Datadog; robust to separator-in-data + schema evolution; DuckDB/sqlite/pandas-loadable). Matches the `audit.jsonl` precedent; greppable + `tail -f`. A pretty reader (§9) preserves eyeball-readability without a delimited format's fragility. |
| D3 | Whole-engine scope — **enumerated from code, not memory** | operator choice; rev-2 audit added the boundaries rev 1 missed (platform WS, news WS, pubsub, outbound-HTTP families); runtime `linkage` profile collapses noise (§7.3) |
| D4 | Daily rotation, 7-day retention, date-stamped filenames (no rename) | operator choice; Windows-safe by construction (§6.3) |
| D5 | `corr_id` via `contextvars`, minted at entry points only | auto-propagation, no signature threading; greenfield (unused today) |
| D6 | **Every queue hand-off** carries + re-binds corr_id (bus AND webhook queue; rule, not a one-off) | contextvars can't cross consumer tasks; rev 2 corrected the "one explicit hand-off" overclaim (§3.3, §6.2) |
| D7 | Non-blocking emit + dedicated writer thread | the log taps the hot WS path; must never stall ingestion/dispatch (§6.1, §7.7) |
| D8 | `category` = free string **backed by a registry with groups**; profiles derive from groups; conformance-tested | taps grow without enum coupling, but rev 2 adds the drift defense rev 1 lacked (§5.8) |
| D9 | Attribution-decision taps (§5.6, nine categories) are the priority | they make the whack-a-mole sites visible and de-risk the reconciler (§12) |
| D10 | Mandatory secret redaction in the sink | plaintext artifact; non-negotiable even at localhost (§7.2) |
| D11 | Reuse `json_safe()`; cap payloads (no silent drop) | non-finite-float safety + bounded lines without losing the fact (§7.4) |
| D12 | Volume control is mandatory at whole-engine scope; refresh-driven attr taps are on-change gated | market-data + per-recalc pubsub would otherwise bury the signal (§7.3) |
| D13 | Envelope carries `task` + atomic `seq` | races need "what ran together" + "what was first" — the two questions a plain log can't answer (§4.1) |
| D14 | `dedup_key` on lifecycle taps + lock-wait annotation on async state taps | duplicates one-grep findable; lock contention visible, not inferred (§4.1) |
| D15 | One multi-account daily file; `symbol` + `account_id` top-level slice axes | single-tenant localhost; ticker is a primary debugging dimension (§4, §7.1) |
| D16 | Emit-side single-`dumps` serialization; queue carries strings | one serialization, doubles as size-cap measurement, and **freezes mutable state at emit time** — drain-side serialization would record post-mutation values, self-defeating for race forensics (§6.1) |
| D17 | **SKIPPED/ERROR outcomes mandatory** on attribution taps; identity tuple verbatim incl. `""` | 3 of 8 historical bugs were silent early-returns; stranded rows are found by `tpid==""`, not by absence (§5.6) |
| D18 | WS connection-lifecycle categories (§5.4b) + orders-table/`db_write` taps (§5.5) | the bug replay scored 2 BLIND without them (subscription leak; stale orders); "what rows did this chain write" is the HANDOFF bug class |
| D19 | Overflow dead-letter = rate-limited log + recovery marker envelope, NOT engine_events | `log_event`'s closed enum + account_id requirement + sync sqlite at saturation make it the wrong tool (§6.1) |
| D20 | Per-day MB guard (`CORR_LOG_MAX_MB_PER_DAY`) | retention bounds days, line-cap bounds lines; nothing else bounds a runaway tap's day file (§6.3) |

---

*End of spec. Implementation phasing, tasks, tests, and sequencing in
[correlation_log_implementation_plan.md](correlation_log_implementation_plan.md).*
