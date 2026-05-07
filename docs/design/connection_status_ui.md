# Connection Status & Health Observability — Design Spec

**Status**: Forward-looking design. NOT for implementation now.  
**Prerequisites**: MN-1 (health surface expansion), SC-2 (ready-state gating), foundation structural redesigns (SR-1 through SR-3).  
**Build window**: v2.4-prep, after foundation redesigns land.  
**Audit cross-ref**: `docs/audit/AUDIT_REPORT.md` v2.4-readiness section.

---

## Purpose

User-facing health observability layer built on top of the health surface expanded by MN-1.

Two consumers of the same health surface:
1. **Engine (programmatic)** — reads health for v2.4 gating: halt entries when data is stale, fall back to neutral regime when signals are missing, refuse "ready" when account data hasn't loaded.
2. **UI (human-facing)** — displays the same health data as status pills, mode labels, and action hints so the trader can make informed decisions.

Both consumers read the same underlying data. The UI is the human view; the engine is the automated view. Building one without the other creates a gap — the trader sees "all green" while the engine silently degrades, or vice versa.

---

## Connection Groups (priority order)

| Priority | Group | Role | Failure impact |
|----------|-------|------|----------------|
| 1 | **3rd-party plugin** | Primary data feed (currently Quantower) | Loss of fills, positions, orders — engine falls back to direct exchange paths |
| 2 | **Exchange account** | Private account/position/order data | Loss of equity, position state — sizing impossible |
| 3 | **Exchange market data** | Public klines, mark price, orderbook | Loss of ATR, VWAP, slippage — sizing degraded |
| 4 | **Regime data** | Macro signals for regime classification | Loss of regime multiplier — falls back to 1.0x (neutral) |
| 5 | **News** | Economic calendar, crypto headlines | Loss of context for discretionary decisions — no financial calculation impact |

---

## Sub-Sources Per Group

### Group 1: Plugin (single connection, multiple health signals)

Plugin has **one underlying connection** (Quantower WS via `/ws/platform`) with 3 health signals. These are not independent feeds — they are different lenses on the same connection:

| Health signal | Source | What it tells you |
|---------------|--------|-------------------|
| Connection state | `platform_bridge.is_connected`, `_ws_clients` set size | Is the plugin connected at the TCP/WebSocket level? |
| Last message time | Derived from WS dispatch activity | Is the plugin sending data, or is the connection alive but idle? |
| Command relay health | Outbound push success rate / dead client detection in `_send_to_clients` | Can we push data back to the plugin? |

**Group is unhealthy if any signal is bad.** No in-group fallback because there is only one feed. Plugin loss cascades to engine policy: activate direct exchange paths (groups 2-3).

### Group 2: Exchange account (WS-primary / REST-reconciliation)

| Sub-source | Transport | Health signal | Role |
|------------|-----------|---------------|------|
| User-data WS | `websockets` client → exchange | `ws_status.connected`, `ws_status.last_update` | **Primary** — real-time account/position/order updates |
| Account REST | CCXT via `_REST_POOL` | Last successful `fetch_account` timestamp | **Reconciliation** — 30s safety-net poll |
| Listen key | REST create + 25-min keepalive | Last successful keepalive | **Supporting** — required for user-data WS |

`FALLBACK` is a meaningful intermediate state: WS is down, REST is compensating at reduced frequency. Not "healthy" (data is 5-30s stale) but not "offline" (data is still flowing).

### Group 3: Exchange market data (WS-primary / REST-reconciliation)

| Sub-source | Transport | Health signal | Role |
|------------|-----------|---------------|------|
| Market WS | `websockets` client → exchange | Last kline/mark-price timestamp per symbol | **Primary** — 1Hz mark price, closed klines |
| REST orderbook | CCXT `fetch_order_book` | Last successful fetch timestamp | **Fallback** — triggered by `_fallback_loop` when WS stale |

Same WS-primary/REST-reconciliation pattern as group 2.

### Group 4: Regime data (independent polled sources)

| Sub-source | Transport | Health signal | Provides |
|------------|-----------|---------------|----------|
| FRED API | httpx REST | Last successful fetch, response status | US 10Y yield, HY spread |
| Yahoo Finance | yfinance library | Last successful fetch | VIX |
| Exchange OI | CCXT (via adapter) | Last successful fetch | Aggregate open interest change |
| Exchange funding | CCXT (via adapter) | Last successful fetch | Average funding rate |

**No fallback semantics.** Each source provides different data. Partial degradation is tolerable: the regime classifier can produce a classification from any subset of signals (macro_only mode uses VIX/FRED/rvol only; full mode adds OI/funding).

### Group 5: News (independent sources, different signals)

| Sub-source | Transport | Health signal | Provides |
|------------|-----------|---------------|----------|
| BWE News | WebSocket (persistent) | Connection state, last message time | Crypto headlines |
| Finnhub | httpx REST (15s poll) | Last successful fetch, HTTP status | Market news, economic calendar |

**No fallback semantics.** Each provides different content. Loss of one doesn't affect the other.

---

## Health Surface Model

Per source, the health surface exposes:

```
HealthStatus:
    source_id:    str           # e.g. "exchange_account_ws", "fred", "plugin_ws"
    group:        str           # e.g. "plugin", "exchange_account", "regime"
    transport:    str           # e.g. "websocket", "rest_poll", "library"
    status:       "green" | "yellow" | "red"
    mode:         "LIVE" | "FALLBACK" | "DEGRADED" | "OFFLINE" | "INITIALIZING"
    last_message_at: Optional[datetime]   # UTC, None if never received
    error_count:  int           # errors in last N minutes (rolling window)
    action_hint:  str           # one-line, when degraded or down (see taxonomy below)
```

**Implementation notes on `error_count`**: What counts as an error is implementation-dependent per source — connection drops, HTTP 4xx/5xx, parse failures, auth rejections, timeouts. The rolling window duration (e.g., 5 minutes) is TBD at implementation. Mode transition thresholds (when LIVE becomes DEGRADED, when DEGRADED becomes OFFLINE) are also TBD — documented here as categories, not numbers.

**Mode is transport-neutral.** Transport detail lives in `source_id` and `transport` fields, not in the mode enum. Mode carries decision-relevant semantics:

| Mode | Meaning | Applies to | Engine behavior |
|------|---------|-----------|-----------------|
| `LIVE` | Primary feed working, data fresh | All source types (WS, REST poll, library) | Normal operation |
| `FALLBACK` | Primary feed down, secondary compensating | Only sources with WS-primary/REST-reconciliation pattern (groups 2-3). Does NOT apply to single-feed sources (FRED, Yahoo, Finnhub, BWE, OI/funding). | Reduced frequency (5-30s stale); sizing still valid but mark-to-market delayed |
| `DEGRADED` | Data flowing but with errors or partial coverage (see categories below) | All source types | Log warnings; regime falls back to neutral if regime source |
| `OFFLINE` | No data for > threshold | All source types | Halt new entries through this venue (v2.4 gate) |
| `INITIALIZING` | First connection attempt in progress | All source types | Engine not ready; calculator refuses requests (RE-1 fix) |

**For single-feed sources** (REST-only polled: FRED, Yahoo, Finnhub, exchange OI/funding): the mode lifecycle is `INITIALIZING → LIVE → DEGRADED → OFFLINE`. `FALLBACK` never applies because there is no secondary feed to fall back to.

**DEGRADED trigger categories:**

| Category | Trigger | Example |
|----------|---------|---------|
| **Error-driven** | `error_count` exceeds threshold (TBD) but data still arriving between errors | Finnhub returning HTTP 429 intermittently; some polls succeed, some fail |
| **Coverage-driven** | Source nominally OK but providing partial data | Regime classifier missing VIX signal (Yahoo down) but FRED signals present; OI data returning for 7 of 10 symbols |

Numeric thresholds (error count, staleness duration) are TBD at implementation. The categories prevent DEGRADED from becoming a junk drawer — every DEGRADED source must be classifiable as error-driven or coverage-driven.

**Status pill is for at-a-glance UI.** Consumers (UI and engine) should read `mode` for behavior decisions, not color.

| Status | Mode mapping |
|--------|-------------|
| Green | `LIVE` |
| Yellow | `FALLBACK`, `DEGRADED`, `INITIALIZING` |
| Red | `OFFLINE` |

---

## Roll-Up Logic

**Default**: Per group, worst sub-status wins.

| Group | Roll-up rule | Rationale |
|-------|-------------|-----------|
| Plugin | Unhealthy if any of 3 health signals is bad (single connection, not 3 sources) | No in-group fallback — one feed |
| Exchange account | Worst wins | If WS is red but REST is green → group is yellow (REST_FALLBACK) |
| Exchange market | Worst wins | Same pattern |
| Regime | **Yellow if at least one source green** | Partial degradation; neutral regime computable from any subset. Red only if ALL sources offline. |
| News | Worst wins | Conservative — but news loss has no financial calculation impact |

---

## Degradation Policy (engine behavior)

The engine reads the health surface programmatically. These are the v2.4 gate-readiness rules:

| Condition | Engine action |
|-----------|--------------|
| Plugin group OFFLINE | Fall back to direct exchange paths (groups 2-3). Log mode change. If groups 2-3 also OFFLINE → halt. |
| Exchange account group OFFLINE | **Halt new entries through that venue.** Existing positions monitored at last-known state. Calculator returns ineligible with reason "Account data offline." |
| Exchange account group FALLBACK | Sizing permitted but calculator output includes staleness warning. Mark-to-market delayed 5-30s. |
| Exchange market group OFFLINE | **Halt new entries through that venue.** ATR/slippage cannot be computed without market data. |
| Exchange market group FALLBACK | Sizing permitted with degraded slippage estimate (REST orderbook, not live depth). |
| Regime group OFFLINE | Use neutral regime multiplier (1.0x). **Do not halt.** Log warning. Calculator output shows "regime: neutral (data offline)." |
| Regime group DEGRADED | Use classification from available signals (macro_only mode if crypto signals missing). Log which signals are absent. |
| News group OFFLINE | Disable news-dependent strategies only (if any exist). Others continue unaffected. |
| Any group INITIALIZING | Engine refuses "ready" status (SC-2 fix). Calculator returns ineligible. |

---

## Notifications

### Action Hint Taxonomy

Action hints are one-line strings categorized to help implementation produce consistent messages:

| Category | Template | Example |
|----------|----------|---------|
| **Reconnecting** | `"{source} reconnecting (attempt {N})"` | "Exchange WS reconnecting (attempt 3)" |
| **Auth failure** | `"Check {source} API key"` / `"Auth rejected by {source}"` | "Check Finnhub API key" |
| **Rate limit** | `"Rate-limited by {source}; backing off {N}s"` | "Rate-limited by FRED; backing off 60s" |
| **Stale** | `"No data from {source} for {duration}"` | "No data from Yahoo Finance for 2h 15m" |
| **Initializing** | `"Awaiting first message from {source}"` | "Awaiting first message from Quantower plugin" |
| **Unknown** | `"Connection error — see logs"` | "Connection error — see logs" |

Implementation should select the most specific category that applies. "Unknown" is the fallback when the error doesn't match a known pattern.

### Phase A (initial): Banner

Single dismissible banner at top of dashboard. Appears when any group is yellow or red. Shows:
- Worst-affected group name
- Current mode
- Count of affected groups (if > 1)
- Action hint from the worst source

Example: `Exchange Account: FALLBACK — Exchange WS reconnecting (attempt 3). 1 other group degraded.`

### Anti-patterns to avoid from day one

| Anti-pattern | Mitigation |
|-------------|------------|
| **Flapping** | Notify only on state change AND if new state holds for > 30 seconds. Suppress transitions that resolve within the debounce window. |
| **Duplicates** | Same error 5x/min = 1 notification with count badge. No repeated banners for the same condition. |
| **Severity flatness** | Red (action needed) and yellow (auto-recovering) must have visually distinct treatment — red banner is persistent + prominent; yellow is informational + auto-dismisses when resolved. |

### Phase B (later, only if Phase A proves insufficient)

- Notification center with history (last 24h)
- Dismiss/snooze per notification
- Optional desktop notifications (via Service Worker push)
- Per-group expand/collapse detail view

**Do not build Phase B until Phase A has been in use for at least 2 weeks.** Premature complexity.

---

## Sequencing

**Do NOT skip steps. Each depends on the previous.**

```
Step 1 ─── Phase 2 cheap CRITICALs + foundation redesigns (SR-1, SR-2, SR-3)
            │
            │   These fix the state-ownership bugs that would make
            │   health readings unreliable.
            │
Step 2 ─── MN-1: expand health surface to ~9 checks
           SC-2: add ready-state gating
            │
            │   The health surface MUST exist before the UI.
            │   Without this, UI shows "all green" because it has
            │   no visibility into the unmonitored 6 of 9 surfaces.
            │
Step 3 ─── Engine reads health surface for degradation policy
           Wire programmatic consumers: gating logic, mode-aware sizing
            │
            │   Engine behavior changes before UI changes.
            │   This validates the health surface is correct.
            │
Step 4 ─── UI layer on top of the now-real health data
           Banner (Phase A) only.
            │
Step 5 ─── Incremental: expand only if Phase A proves insufficient
           Notification center (Phase B)
```

**Critical constraint**: Do not build the UI (step 4) before step 2 completes. A UI on a half-complete health surface displays misleading "all green" because it has no visibility into the unmonitored 6 of 9 surfaces. This is worse than no UI — it creates false confidence.

---

## Out of Scope

Deferred until step 4 implementation begins:

- UI auth/permissions (who sees health vs who can dismiss)
- Performance/latency requirements for health polling
- Mobile responsiveness of the banner
- Dashboard layout integration with existing HTMX templates
- WebSocket push for real-time status updates to the browser
