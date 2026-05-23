# Calc-Linkage System — Consolidated Spec

**Status**: design — pending implementation
**Created**: 2026-05-24
**Decisions captured**: 68 (Q1–Q68 from clarification session)
**Scope**: end-to-end linkage between pre-trade calculations, broker-placed
orders, fills, positions, amendments, funding, and closes — enabling
automatic model-feedback from exchange data.

---

## 1. Purpose

This engine sits **downstream** of the operator's broker (Quantower) and
the venue. It does not place orders directly. Its job is to:

1. Accept operator-computed risk plans (`calc`).
2. Observe orders/fills/positions arriving from the venue via WS.
3. Automatically link those venue events back to the originating calc.
4. Track the full causal chain (calc → orders → fills → position →
   amendments → close → funding) for every trade.
5. Expose plan-vs-realized deltas, deviations, and lifecycle context to
   downstream custom models.

The system targets **operator-mediated copy-paste workflow**: operator
clicks Calculate → engine logs a calc → operator copy-pastes setup to
Quantower → engine fuzzy-matches the resulting order back to the calc
within a configurable window.

---

## 2. Operational flow

```
[A] Calc lifecycle
  Operator types ticker/dir/entry/TP/SL → click Calculate
    → pre_trade_log row written (status='active', calc_id, window_seconds)
    → in-process event: calc:created
    → window countdown starts in calculator tab
  Operator clicks Calculate again same (symbol, direction) within window
    → old row: status='superseded', superseded_by_calc_id=new_id
    → in-process event: calc:superseded
    → new row gets fresh window
  Operator clicks "Cancel calc" mid-window
    → status='cancelled_by_operator' + optional reason note
    → in-process event: calc:cancelled
  Window expires without match
    → status='expired'
    → in-process event: calc:expired

[B] Order arrival
  Order arrives via WS
    → matcher attempts strict match:
        - limit: 5/5 (ticker, direction, in-window, entry, TP, SL)
        - market: 6/6 (entry compared against fill px loose tolerance)
    → per-criterion audit row written regardless of outcome
    → on FULL match: orders.calc_id stamped, link_status=LINKED
      → in-process event: calc:linked
    → on PARTIAL match (1+ candidates score < threshold):
      → link_status=NEEDS_MANUAL_REVIEW
      → order appears in needs-link tab with per-criterion diff panel
    → on NO match AND no candidates at all in window:
      → link_status=UNPLANNED (auto)
    → on NO match BUT candidates exist (matcher rejected all):
      → link_status=UNLINKED (operator can downgrade to UNPLANNED)

[C] Working order
  Limit sits in book
    → window may expire while order works → link persists (window
      governs match decision, not link lifetime)
    → calc may be superseded by a newer calc → link to old calc remains
    → operator amends entry price → order_amendments row; calc_id preserved
  Order cancels before fill
    → cancellation_reason captured (category + raw + ts)
    → in-process event: calc:order_cancelled
    → calc returns to "released" state, eligible for re-match within
      remaining window
  Operator places replacement order with similar criteria
    → modal at order placement: "Replace cancelled order X (calc Y)?"
    → operator picks: link to released calc OR treat as new

[D] Position lifecycle
  Fill arrives (partial or full)
    → fills.calc_id stamped from parent order
    → positions_calcs junction row inserted/updated
    → if first fill: PositionInfo carries calc_id list; engine derives
      from junction on rehydrate
  Scale-in: new calc fires within window of OPEN position, operator
  places add → matches new calc → second positions_calcs row appended;
  each calc carries its own planned_tp/sl/size
  Operator amends TP/SL on a stop order
    → order_amendments row {field, old, new, ts, operator}
    → live values diverge from planned; deviation badge updates per
      account's yellow/red thresholds

[E] Position close
  Venue TP fills (price matches plan)        → exit_reason=TP_PLANNED
  Venue TP fills (price was amended)         → exit_reason=TP_AMENDED
  Venue SL fills (price matches plan)        → exit_reason=SL_PLANNED
  Venue SL fills (price was amended)         → exit_reason=SL_AMENDED
  Multi-TP partial fills then completes      → exit_reason=TP_LADDER_COMPLETE
  Multi-TP + SL/manual finishes off          → exit_reason=MIXED
  Operator places opposite-side market order → modal pops asking reason:
    INTERVENTION / DISCIPLINE_BREAK / NEW_OPPORTUNITY / OTHER
  Venue liquidates                           → exit_reason=LIQUIDATION
  Venue ADL                                  → exit_reason=ADL

[F] Cross-cutting
  Funding event arrives from venue income WS
    → funding_events row written with (position_id, calc_id, amount, ts)
    → at close: closed_positions.funding_fees = SUM(funding_events)
  Engine restart
    → full rehydrate: positions_calcs, manual-link queue, in-flight calc
      windows (using frozen window_seconds + created_ts), deviation flags
    → reconciliation pass against venue REST to detect drift
  Multi-operator on same account
    → single-operator-per-account lock; second op sees read-only +
      takeover prompt; takeover writes session_change audit row
```

---

## 3. Data model

### 3.1 New tables

**positions_calcs** (junction; source of truth for scale-in attribution)

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| position_id | INTEGER FK | references position lifecycle |
| calc_id | TEXT FK | references pre_trade_log.calc_id |
| order_id | INTEGER FK | references orders.id |
| account_id | INTEGER | denormalized for fast account-scoped queries |
| contributed_qty | REAL | total filled qty for this (calc, order, position) tuple |
| first_fill_ts | INTEGER | ms |
| last_fill_ts | INTEGER | ms |
| planned_size | REAL | from calc.overridden_size (or planned_size if no override) |
| size_delta_pct | REAL | (contributed_qty - planned_size) / planned_size * 100 |
| planned_tp | REAL | snapshot from calc at contribution time |
| planned_sl | REAL | snapshot from calc at contribution time |

Indexes: `(position_id)`, `(calc_id)`, `(order_id)`, `(account_id, calc_id)`.

**order_amendments** (polymorphic field-level audit)

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| order_id | INTEGER FK | |
| calc_id | TEXT | denormalized for fast filtering |
| field | TEXT | enum: entry_price, tp_price, sl_price, size, leverage |
| old_value | REAL | |
| new_value | REAL | |
| ts_ms | INTEGER | |
| operator_id | TEXT | |
| deviation_pct | REAL | (new - old) / old * 100; signed |

Indexes: `(order_id)`, `(calc_id)`, `(calc_id, ts_ms)`.

**funding_events** (per-event funding attribution)

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| position_id | INTEGER FK | |
| calc_id | TEXT | primary calc at the time of funding |
| account_id | INTEGER | |
| symbol | TEXT | |
| amount | REAL | signed (negative = paid funding) |
| mark_price | REAL | mark at funding event |
| funding_rate | REAL | venue-reported rate |
| ts_ms | INTEGER | |
| venue_event_id | TEXT | for dedup |

Indexes: `(position_id)`, `(account_id, ts_ms)`.

**calc_match_audit** (per-criterion match evidence)

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| order_id | INTEGER FK | |
| calc_id | TEXT | candidate calc; may be one of several per order |
| criterion | TEXT | enum: ticker, direction, window, entry, tp, sl |
| calc_value | TEXT | |
| order_value | TEXT | |
| tolerance_used | REAL | |
| matched | BOOLEAN | |
| ts_ms | INTEGER | match decision time |
| winning | BOOLEAN | true on the winning calc's rows |

Indexes: `(order_id)`, `(calc_id)`.

**operator_sessions** (multi-operator handoff audit)

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| account_id | INTEGER | |
| operator_id | TEXT | |
| session_start_ts | INTEGER | |
| session_end_ts | INTEGER | nullable; null if active |
| takeover_from_session_id | INTEGER | nullable FK self |

### 3.2 Modified tables

**pre_trade_log** (additions)

| Column | Type | Notes |
|---|---|---|
| status | TEXT | enum: active / matched / superseded / expired / cancelled_by_operator / completed_via_position / partially_actioned |
| window_seconds | INTEGER | frozen from accounts.config_json at creation |
| account_id | INTEGER | scoping |
| operator_id | TEXT | who computed the calc |
| superseded_by_calc_id | TEXT | nullable FK self |
| cancelled_reason | TEXT | nullable; only set when status=cancelled_by_operator |
| planned_size | REAL | engine's recommended size |
| overridden_size | REAL | operator's final size (== planned if not overridden) |
| planned_tp | REAL | engine's recommended TP |
| overridden_tp | REAL | |
| planned_sl | REAL | engine's recommended SL |
| overridden_sl | REAL | |
| tp_levels | TEXT (JSON) | multi-TP array: [{price, size_pct}, ...]; nullable |
| filled_pct | REAL | for partially_actioned state |
| tags | TEXT (JSON) | freeform array for secondary model attribution |

**orders** (additions)

| Column | Type | Notes |
|---|---|---|
| link_status | TEXT | enum: LINKED / NEEDS_MANUAL_REVIEW / UNLINKED / UNPLANNED |
| operator_id | TEXT | |
| cancel_reason_category | TEXT | enum: OPERATOR / GTC_EXPIRED / IOC_NO_FILL / VENUE_REJECTED / AUTO_REPLACE / MARGIN_CALL / ENGINE_RESTART |
| cancel_reason_raw | TEXT | venue's raw reason string |
| cancel_ts_ms | INTEGER | |

**closed_positions** (additions)

| Column | Type | Notes |
|---|---|---|
| exit_reason | TEXT | enum: TP_PLANNED / TP_AMENDED / SL_PLANNED / SL_AMENDED / TP_LADDER_COMPLETE / MIXED / MANUAL_INTERVENTION / MANUAL_DISCIPLINE_BREAK / MANUAL_NEW_OPPORTUNITY / MANUAL_OTHER / LIQUIDATION / ADL / EXPIRED |
| close_note | TEXT | operator's free-text rationale on manual close |
| entry_px_delta_pct | REAL | (avg_actual_entry - planned_entry) / planned_entry * 100 |
| size_delta_pct | REAL | (actual_size - planned_size) / planned_size * 100 |
| tp_drift_pct | REAL | nullable; (final_tp - planned_tp) / planned_tp * 100 |
| sl_drift_pct | REAL | nullable; (final_sl - planned_sl) / planned_sl * 100 |
| exit_vs_target_pct | REAL | (actual_exit - relevant_planned_level) / planned * 100 |
| realized_r | REAL | (exit_px - entry_px) / (planned_entry - planned_sl) |
| planned_r | REAL | from calc estimate |
| hold_time_actual_ms | INTEGER | |
| hold_time_planned_ms | INTEGER | nullable |
| cumulative_amendment_count | INTEGER | count of order_amendments rows linked |
| funding_fees | REAL | SUM(funding_events.amount) for position |
| liquidation_px | REAL | nullable; populated only on LIQUIDATION |
| bankruptcy_px | REAL | nullable |
| insurance_fund_fee | REAL | nullable |
| adl_indicator | BOOLEAN | nullable |
| calc_id | TEXT | denormalized PRIMARY (most-contributing); junction has full detail |
| close_calc_id | TEXT | DROPPED — engine computes deviations automatically; no operator close-calc |

**accounts** (additions)

| Column | Type | Notes |
|---|---|---|
| config_json | TEXT (JSON) | single blob; see §3.3 |

### 3.3 accounts.config_json schema

```json
{
  "window_seconds": 300,                        // 60 / 300 / 900 = 1/5/15 min
  "clock_skew_tolerance_sec": 10,
  "deviation_thresholds": {
    "yellow_pct": 5,
    "red_pct": 15
  },
  "size_deviation_threshold_pct": 10,
  "notification_subscriptions": {
    "calc_expired": true,
    "position_liquidated": true,
    "position_size_drift": true,
    "duplicate_order_detected": true,
    "near_replacement_match": true
  }
}
```

### 3.4 Status / enum reference

**calc.status**: `active` → {`matched` | `superseded` | `expired` | `cancelled_by_operator` | `completed_via_position` | `partially_actioned`}

**order.link_status**: `LINKED` | `NEEDS_MANUAL_REVIEW` | `UNLINKED` | `UNPLANNED`

**closed_positions.exit_reason**: see table above.

**order_amendments.field**: `entry_price` | `tp_price` | `sl_price` | `size` | `leverage`

**cancel_reason_category**: `OPERATOR` | `GTC_EXPIRED` | `IOC_NO_FILL` | `VENUE_REJECTED` | `AUTO_REPLACE` | `MARGIN_CALL` | `ENGINE_RESTART`

---

## 4. Matcher specification

### 4.1 Auto-match thresholds

| Order type | Required matches | Criteria considered |
|---|---|---|
| LIMIT | 5/5 (all must match) | ticker, direction, in-window, TP, SL (entry uses loose tolerance) |
| MARKET | 6/6 (all must match) | ticker, direction, in-window, entry-vs-fill-px-loose, TP, SL |

**No scoring, no partial-auto-link**. Anything below the threshold falls
through to the needs-link tab for manual operator review.

### 4.2 Tolerances

| Criterion | Tolerance source |
|---|---|
| ticker | exact match (hard) |
| direction | exact match (hard) |
| in-window | `\|order_ts - calc_ts\| ≤ window_seconds + clock_skew_tolerance_sec` |
| entry (loose) | `\|order_entry - calc_entry\| / calc_entry ≤ entry_tolerance_pct` (default 0.25%, in config_json) |
| TP | `\|order_tp - calc_tp\| ≤ N * tick_size` (N default 1) |
| SL | `\|order_sl - calc_sl\| ≤ N * tick_size` (N default 1) |

### 4.3 Match decision flow

```
for each incoming order:
  candidates = pre_trade_log
    WHERE account_id = order.account_id
      AND status IN ('active', 'released')
      AND ticker = order.ticker
      AND direction = order.direction
      AND \|order_ts - created_ts\| ≤ window_seconds + clock_skew_tolerance

  for each candidate: write calc_match_audit rows per criterion

  full_matches = candidates with ALL criteria matched
  if len(full_matches) == 1:
    LINK; status=matched; link_status=LINKED
  elif len(full_matches) > 1:
    pick most-recent by created_ts (tie-break)
    LINK; mark winning row in calc_match_audit
  elif len(candidates) > 0:
    link_status=NEEDS_MANUAL_REVIEW
  else:
    link_status=UNPLANNED  # no candidates in window at all
```

### 4.4 Released-calc preference (replacement orders)

When an order cancels with `cancel_reason_category=OPERATOR`, its calc
transitions to `released` (still within original window). If operator
then places a new order:

1. Engine detects near-match against released calc at order-placement
   time (pre-WS-arrival).
2. Modal pops: "This looks like a replacement for cancelled order X
   (calc Y). Link to released calc? [Yes / Treat as new]"
3. Decision made BEFORE order leaves; no race condition.

### 4.5 Bracket order detection

When operator places entry + TP + SL as a venue-native bracket, the
TP/SL orders inherit calc_id from the entry order.

Detection priority per adapter:
1. **Venue-native**: Bybit `orderLinkId`, Binance `positionSide` + symbol
   clustering, OKX `algoOrdId`.
2. **Fallback**: time-window clustering — orders for same
   `(symbol, direction)` within N seconds (default 2s) treated as
   bracket siblings.

If detection fails (e.g., operator places TP/SL separately after entry),
the standalone stop falls to needs-link tab (per §6.2). For TP/SL on
an already-OPEN position (operator adds protective stop mid-trade), see
Q19 / §6.2.

---

## 5. Calc lifecycle state machine

```
                  ┌──────────────────────────────┐
                  │                              │
                  ▼                              │
   [active] ──supersede──> [superseded]          │
      │                                          │
      ├──order full-match──> [matched] ─────────┤
      │                          │               │
      │                          ▼               │
      │                  [completed_via_position]
      │                          │
      │                  (on position close)
      │
      ├──partial fill + no further── [partially_actioned]
      │
      ├──operator cancel──> [cancelled_by_operator]
      │
      └──window expires──> [expired]
```

State transition events emitted (in-process `event_bus`):
- `calc:created` on insert
- `calc:linked` on transition to `matched`
- `calc:superseded` on transition to `superseded`
- `calc:cancelled` on `cancelled_by_operator`
- `calc:expired` on `expired` (also on rehydrate-time backfill)
- `calc:partially_filled` on `partially_actioned` + `{filled_pct}`
- `calc:completed` on `completed_via_position` (when its position closes)

---

## 6. Order link_status state machine

```
   [arriving] ──auto-match──> [LINKED]
       │
       ├──candidates exist, none full-match──> [NEEDS_MANUAL_REVIEW]
       │                                              │
       │                                              ├──operator-link──> [LINKED]
       │                                              └──operator-mark──> [UNPLANNED]
       │
       └──zero candidates in window──> [UNPLANNED] (auto)
```

Persistent badge in trades/history tab; no SLA escalation. Operator
decides pace; engine surfaces state clearly.

---

## 7. Position lifecycle state machine

```
   (no position) ──first fill──> [OPEN]
         │                          │
         │                          ├──scale-in fill──> [OPEN] (junction grows)
         │                          │
         │                          ├──TP/SL/MANUAL/LIQUIDATION fill──> reduces size
         │                          │
         │                          ├──multi-TP partial fill──> [OPEN] (reduced)
         │                          │    │
         │                          │    └──final fill──> [CLOSED]
         │                          │
         │                          └──size reaches 0──> [CLOSED]
         │
         │  on CLOSED: closed_positions row built; deltas computed;
         │  position:closed event emitted with full payload; all contributing
         │  calcs transition to completed_via_position
         ▼
   [size_drift detected] ──snapshot wins──> [reconciler investigates]
         │
         └──discrepancy resolved or escalated
```

Events emitted:
- `position:opened` on first fill
- `position:scale_in` on each subsequent same-side fill
- `position:amended` on each `order_amendments` row touching a position-linked order
- `position:partial_close` on each TP fill in multi-TP plan
- `position:closed` on size→0 — full payload (see §9)
- `position:liquidated` on `LIQUIDATION` close — payload includes liquidation_px, bankruptcy_px, insurance_fund_fee, adl_indicator
- `position:size_drift` when snapshot disagrees with fill-derived size

---

## 8. Multi-TP partial close lifecycle

Calc has `tp_levels = [{price: 64500, size_pct: 50}, {price: 65000, size_pct: 30}, {price: 65500, size_pct: 20}]`.

- Position opens at 0.5 BTC; TP orders placed at all three levels
  with corresponding sizes.
- TP1 fills (0.25 BTC closed) → `position:partial_close` event +
  position remains OPEN at 0.25 BTC. `realized_pnl_partial`
  accumulated.
- TP2 fills → another `position:partial_close` + position at 0.10 BTC.
- TP3 fills → position size = 0 → `position:closed` with
  `exit_reason=TP_LADDER_COMPLETE`.

If a SL hits before all TPs complete, or operator manual-closes a
remaining piece, `exit_reason=MIXED` with breakdown in event payload.

---

## 9. Event catalog (in-process `event_bus`)

Topics use hierarchical naming, scoped per account:
`engine:account:{account_id}:{domain}:{event}`.

| Topic suffix | Payload (essential fields) |
|---|---|
| `calc:created` | calc_id, ticker, direction, window_seconds, model_name, tags, operator_id |
| `calc:linked` | calc_id, order_id, link_audit_summary |
| `calc:superseded` | old_calc_id, new_calc_id, reason='operator_recalc' |
| `calc:cancelled` | calc_id, reason_note |
| `calc:expired` | calc_id, age_seconds, ticker, direction, model_name |
| `calc:partially_filled` | calc_id, planned_size, filled_size, pct |
| `calc:completed` | calc_id, position_id |
| `calc:size_deviated` | calc_id, planned_size, contributed_qty, delta_pct |
| `calc:order_cancelled` | calc_id, order_id, cancel_reason_category, raw |
| `position:opened` | position_id, calc_ids[], symbol, direction, entry_px, size |
| `position:scale_in` | position_id, new_calc_id, added_qty |
| `position:amended` | position_id, order_id, field, old, new, ts, operator_id |
| `position:partial_close` | position_id, tp_level_idx, qty_reduced, remaining_qty, realized_pnl_partial |
| `position:closed` | **full payload** (see below) |
| `position:liquidated` | position_id, liquidation_px, bankruptcy_px, insurance_fund_fee, adl_indicator |
| `position:size_drift` | position_id, fill_derived_size, snapshot_size, delta |
| `order:duplicate_detected` | order_ids[], dup_window_ms |

**`position:closed` full payload**:
```json
{
  "position_id": 12345,
  "symbol": "BTCUSDT",
  "direction": "LONG",
  "contributing_calc_ids": ["calc_a", "calc_b"],
  "primary_calc_id": "calc_a",
  "model_names": ["momentum_v3", "trend_v1"],
  "model_tags": ["asia_session", "low_vol_regime"],
  "open_ts_ms": 1700000000000,
  "close_ts_ms": 1700000180000,
  "hold_time_actual_ms": 180000,
  "hold_time_planned_ms": 240000,
  "avg_entry_px": 64500,
  "avg_exit_px": 65500,
  "realized_pnl": 500,
  "total_fees": 12.5,
  "funding_fees": -1.2,
  "net_pnl": 486.3,
  "deltas": {
    "entry_px_delta_pct": 0.31,
    "size_delta_pct": -20.0,
    "tp_drift_pct": 0.0,
    "sl_drift_pct": 1.7,
    "exit_vs_target_pct": 0.0,
    "realized_r": 1.85,
    "planned_r": 2.0
  },
  "exit_reason": "TP_PLANNED",
  "was_manually_closed": false,
  "close_note": null,
  "cumulative_amendment_count": 1,
  "mfe": 720,
  "mae": -50
}
```

---

## 10. UI requirements

### 10.1 Calculator tab

- Form: ticker, direction, entry, TP (or `tp_levels` array), SL, size
  (engine-recommended + operator-overridable)
- Window config per account (1/5/15 min dropdown stored in
  `accounts.config_json.window_seconds`)
- Calculate button → posts to risk engine → writes `pre_trade_log` row
- Active calcs list with countdown timers (live; uses frozen
  `window_seconds + created_ts`)
- Cancel calc button per active calc

### 10.2 Multi-pane dashboard

Four panes visible simultaneously:

1. **Open positions** — list with inline deviation badges (green
   on-plan / yellow amended / red no-calc), live MFE/MAE, current uPnL
2. **Active calcs** — list with countdown timer per calc, status,
   model_name, ticker/direction/TP/SL
3. **Needs-review queue** — orders awaiting manual link with side-by-side
   per-criterion diff panel; click candidate to link
4. **Recent closes** — last N closed positions with realized_pnl,
   exit_reason, deviation summary; click for full audit

### 10.3 Needs-link tab

- Order details on left; candidate calcs on right
- Per-criterion diff highlighted:
  `entry: order=64.5k, calcA=64.7k, diff=0.31% (within 5% tolerance, but
  TP missed: order=65.5k, calcA=66.0k, diff=0.76% > tick_size)`
- Color-coded per-criterion: green match / red miss / gray N/A
- Buttons: "Link to this calc" per candidate; "Mark UNPLANNED"
- Visible badge in main nav for count

### 10.4 Replacement modal

- Triggered at order-PLACEMENT time (pre-submission) when:
  - operator is about to send an order
  - a released calc near-matches
- Modal: "This looks like a replacement for cancelled order X (calc Y).
  Link to released calc? [Yes — link] [Treat as new]"

### 10.5 Manual close reason modal

- Triggered post-WS when engine detects an opposite-side order against
  an open position with no calc match (= manual close)
- Dropdown: `INTERVENTION` | `DISCIPLINE_BREAK` | `NEW_OPPORTUNITY` |
  `OTHER`
- Optional free-text note
- Required to submit; captured to `closed_positions.exit_reason` +
  `close_note`

### 10.6 Trade audit export

- Per closed-position row: "Export Audit" button
- Generates JSON + PDF with signed-timestamp footer
- Includes: pre_trade_log, all orders, all fills, all amendments,
  junction, deviations, full event timeline, operator_id chain

---

## 11. API surface

### 11.1 Reverse-query endpoints

**`GET /context/calc/{calc_id}`** — full graph for a single calc

Returns:
```json
{
  "calc": <pre_trade_log row + overrides>,
  "orders": [<order rows with link_status>],
  "fills": [<fill rows>],
  "amendments": [<order_amendments rows>],
  "positions_calcs": [<junction rows>],
  "position": <PositionInfo if open> | <closed_positions if closed>,
  "funding_events": [<funding_events for the position>],
  "deviations": {<computed from amendments and planned vs actual>},
  "events": [<filtered event_bus history>]
}
```

**`GET /context/position/{position_id}`** — full graph for a position

Same shape but keyed on position_id; returns all contributing
calc_ids and aggregates.

### 11.2 Export endpoint

**`POST /export/closed_position/{id}`** — generates audit bundle
(JSON + PDF, signed timestamp)

### 11.3 Out-of-process subscriber bridge

- **Polling**: out-of-process model polls
  `GET /context/calc/{calc_id}` or `GET /positions/open` for live state
- **Webhook**: engine fires single webhook event type on position
  close → subscriber re-fetches via reverse-query
- Future: Redis bridge or WS endpoint when scale demands

---

## 12. Cross-cutting

### 12.1 Multi-operator

- Single-operator-per-account lock
- Second operator opens UI → read-only mode + "Operator X is active.
  Take over?" prompt
- Takeover: writes `operator_sessions` row with
  `takeover_from_session_id` set; old session terminated; new
  operator_id propagates to subsequent action rows

### 12.2 Cross-account

- Calcs are per-account (cannot span); operator computes once per account
- Matches Q22 calc-scoping decision

### 12.3 Restart

On engine startup:
1. Rehydrate `positions_calcs` from DB; recompute PositionInfo.calc_id
   from junction
2. Rehydrate `accounts.config_json` per account
3. Rehydrate active calcs; compare `now` against `created_ts +
   window_seconds`:
   - If still in window → keep `status=active`
   - If expired → set `status=expired` + emit `calc:expired` event
     (backfill)
4. Rehydrate manual-link queue (orders with
   `link_status=NEEDS_MANUAL_REVIEW`)
5. Run reconciliation pass against venue REST:
   - Pull current positions; compare to engine state
   - If mismatch → emit `position:size_drift` event
   - Pull recent fills since last seen ts; ingest missing ones

### 12.4 Migration / backfill

- Add new tables + columns via SQL migration script
- Backfill `positions_calcs` from existing `fills WHERE calc_id IS NOT
  NULL`, grouped by (position lifecycle, calc_id), `contributed_qty =
  SUM(fill_qty)`
- Historical data: partial junction completeness; documented as
  "full attribution from migration date forward"
- Existing `closed_positions.calc_id` retained as denormalized primary
- Existing `closed_positions.exit_reason` re-mapped to new enum
  (current `'manual'` → `MANUAL_OTHER`; current `'tp'`/`'sl'` →
  `TP_PLANNED`/`SL_PLANNED` if no amendments present, else `_AMENDED`)

### 12.5 Operator notifications

- In-app banner (transient toast) + persistent badge counter on
  relevant tab
- Per-account `config_json.notification_subscriptions` picks which
  event types trigger banners
- Future: external delivery (Slack/email/webhook) as add-on

### 12.6 Snapshot drift detection

- Venue position snapshot is authoritative; fills are advisory
- Inverts current `core/data_cache.py:159-194` policy (WS-fills-win-
  within-5s)
- On drift > tolerance: `position:size_drift` event; reconciler pulls
  venue trade history to investigate

---

## 13. Out of scope / deferred

- **Engine-generated tag for deterministic linkage**: explicitly walked
  back (gap #10 stays open by deliberate choice). Fuzzy 5/5 / 6/6
  remains the only auto-link path.
- **Close-calc pathway**: operator cannot compute calcs at close.
  Engine auto-computes deviations; manual close categorized via
  modal dropdown.
- **External event delivery (Redis / Slack / email)**: deferred to
  future phase; in-process `event_bus` + REST polling is sufficient
  for initial model-feedback loop.
- **Live time-series snapshots of position state**: only point-in-time
  PositionInfo + MFE/MAE on close. No per-second history table.
- **Multi-leg / pairs strategies**: out of scope; treat each leg as
  independent calc.
- **Role-based access control**: single-operator lock is the
  concurrency model; no permission tiers below that.

---

## 14. Decisions index

| Q# | Topic | Decision |
|---|---|---|
| Q1 | Window scope | Per-account global (single value per account) |
| Q2 | Calc revision | New supersedes old; emit `calc:superseded` |
| Q3 | Order cancel | Releases calc to pool; re-match eligible |
| Q4 | Stop amend | Preserve link, log to `order_amendments`, planned values immutable |
| Q5 | Manual queue | Dedicated needs-link tab (later refined: no SLA, persistent badges) |
| Q6 | Position calc storage | Junction table `positions_calcs` |
| Q7 | Exit reason | Plan-aware enum (TP_PLANNED / TP_AMENDED / etc.) |
| Q8 | Close calc | Optional close calc (later WALKED BACK — engine auto-computes deviations; no operator close calc) |
| Q9 | Match audit | Full per-criterion evidence row per match attempt |
| Q10 | Expiry event | Mark + event + payload |
| Q11 | QT linkage | Engine-generated tag (later WALKED BACK — fuzzy 5/5 / 6/6 only, no tag) |
| Q12 | Cancel reason | Categorized + raw + ts + emit `calc:order_cancelled` |
| Q13 | TP/SL link | Inherit from entry via bracket detection |
| Q14 | Scale plan | Per-calc planned values in junction |
| Q15 | Funding | Both at-event + at-close aggregate |
| Q16 | Replacement | Operator-prompted on near-match (modal at placement) |
| Q17 | Window freeze | Frozen at calc creation; immune to mid-flight config changes |
| Q18 | Close event | Full payload |
| Q19 | Standalone stop | Inherit from position's latest calc |
| Q20 | Live deviation | Per-position badge (green/yellow/red) |
| Q21 | Partial fill | `partially_actioned` state + `filled_pct` + event |
| Q22 | Calc scope | Per-account |
| Q23 | Size delta | Stored on junction; flag if > threshold |
| Q24 | Reverse query | Full graph in single payload |
| Q25 | Liquidation | Full detail columns + event |
| Q26 | Restart state | Full rehydrate + reconciliation pass |
| Q27 | Null TP/SL | Allow nullable but auto-route to manual-link |
| Q28 | Bracket detect | Venue-native + clustering fallback |
| Q29 | Tag conflict | N/A — Q11 walked back |
| Q30 | Close calc UX | N/A — Q8 walked back |
| Q31 | Fees | Per-fill + closed_positions aggregate |
| Q32 | Drift thresholds | Per-account configurable defaults |
| Q33 | Manual close | Dropdown + optional note (INTERVENTION / DISCIPLINE_BREAK / NEW_OPPORTUNITY / OTHER) |
| Q34 | Clock skew | Padded window with configurable tolerance |
| Q35 | Manual UX | Side-by-side per-criterion diff |
| Q36 | Amend schema | Single polymorphic `order_amendments` table |
| Q37 | Calc post-close | Auto-complete at position close |
| Q38 | Model attr | Single `model_name` + freeform `tags[]` |
| Q39 | Size drift | Snapshot wins + drift event + reconciler |
| Q40 | Config shape | Single JSON blob `accounts.config_json` |
| Q41 | Closed calc_id | Keep as denormalized "primary" (most-contributing) |
| Q42 | Replace prompt | Modal at order-placement time (pre-submission) |
| Q43 | Link SLA | No SLA — persistent status badge in history tab (LINKED / NEEDS_REVIEW / UNLINKED / UNPLANNED) |
| Q44 | Notifications | In-app banner + badge counter |
| Q45 | Unplanned | Auto-UNPLANNED if zero calcs in window; operator can downgrade UNLINKED |
| Q46 | Multi-operator | Single-operator-per-account lock with takeover |
| Q47 | Cross-account | Per-account; operator computes per account |
| Q48 | Delta set | Full set as columns on closed_positions |
| Q49 | Close fill ID | Stamp calc_id on every close fill |
| Q50 | Manual detect | Auto-detect opposite-side, no engine UI close button |
| Q51 | Event topics | Hierarchical per-account on in-process `event_bus` (NOT Redis) |
| Q52 | Hedge mode | Natural fit via (account, symbol, direction) keying |
| Q53 | Migration | Backfill `positions_calcs` from existing `fills.calc_id` |
| Q54 | Loose TP/SL | Manual-link tab |
| Q55 | Dashboard | Multi-pane workspace |
| Q56 | Operator ID | On every action row + session-handoff audit |
| Q57 | Junction grain | Single row per order; per-fill via JOIN to fills |
| Q58 | Stale calcs | Mark expired on rehydrate + emit `calc:expired` |
| Q59 | Multi-TP | `calc.tp_levels` JSON array `[{price, size_pct}]` |
| Q60 | Venue stop | Standalone → manual-link tab |
| Q61 | Partial close | Position stays open + `position:partial_close` event |
| Q62 | Duplicate | Detect + emit `order:duplicate_detected` + badge |
| Q63 | Subscriber bridge | Polling + position-closed webhook |
| Q64 | Risk override | `planned_size` + `overridden_size`; matcher uses overridden |
| Q65 | TP/SL override | Same pattern: `planned_X` + `overridden_X`; matcher uses overridden |
| Q66 | Calc cancel | `cancelled_by_operator` status + emit `calc:cancelled` |
| Q67 | Indexes | Standard query-pattern coverage |
| Q68 | Audit export | Full graph per closed position (JSON + PDF, signed-timestamp) |

---

## 15. Open / pending review

- **Q19 vs Q54 reconciliation**: standalone stop on existing position
  auto-inherits (Q19), but TP+SL placed separately just after entry
  goes to manual-link (Q54). Distinction is timing/context — may
  warrant a unified rule like "auto-inherit if ≥N seconds after
  position open OR if position has had any reduce activity". Defer to
  implementation phase 3.
- **Multi-TP `exit_reason=MIXED` payload shape**: needs sub-breakdown
  of which legs hit which exit (TP1=planned, TP2=amended, remainder=SL).
- **`entry_tolerance_pct` default**: 0.25% suggested in §4.2; needs
  calibration against historical operator paste behavior.
- **Bracket-detection clustering window**: default 2s in §4.5; may
  need per-venue tuning.

---

**End of spec.**
