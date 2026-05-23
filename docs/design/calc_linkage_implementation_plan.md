# Calc-Linkage System — Implementation Plan

**Status**: design — pending execution
**Created**: 2026-05-24
**Source spec**: [calc_linkage_spec.md](calc_linkage_spec.md) (68 decisions)
**Scope**: phased rollout of the calc-linkage data model, matcher,
event surface, and operator UX described in the spec.

---

## 1. Phasing rationale

Phases are ordered by **dependency** and **leverage** — each phase
delivers user-visible value while only depending on prior phases.
Critical path is **Phase 0 → 1 → 2** (schema + matcher + junction);
everything else builds on those.

```
Phase 0: Foundation (schema-only, no behavior change)
  │
  ├─> Phase 1: Matcher tightening (strict 5/5 + 6/6, audit table)
  │     │
  │     └─> Phase 3: Link status + manual-link tab
  │           │
  │           └─> Phase 8: Operator UX (dashboard, modals, notifications)
  │
  ├─> Phase 2: Position-level attribution (junction-aware lifecycle)
  │     │
  │     ├─> Phase 4: Amendment tracking + deviation
  │     │
  │     ├─> Phase 5: Funding + fees attribution
  │     │
  │     └─> Phase 6: Event bus enrichment + close payload
  │           │
  │           └─> Phase 7: Reverse-query + audit export
  │
  └─> Phase 9: Multi-operator + advanced (independent)
```

Effort tiers: S (≤2 days), M (3-7 days), L (>7 days).

---

## Phase 0: Foundation — schema additions

**Goal**: All new tables and columns exist in DB; no behavior change.
Safe to deploy independently.

**Dependencies**: none.

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 0.1 | Add `positions_calcs` junction table | `core/database.py` (migrate), `core/db_orders.py` (CRUD helpers) |
| 0.2 | Add `order_amendments` table | `core/database.py`, `core/db_orders.py` |
| 0.3 | Add `funding_events` table | `core/database.py`, `core/db_orders.py` |
| 0.4 | Add `calc_match_audit` table | `core/database.py`, `core/db_orders.py` |
| 0.5 | Add `operator_sessions` table | `core/database.py`, `core/auth_state.py` (new) |
| 0.6 | Add columns to `pre_trade_log`: status, window_seconds, account_id, operator_id, superseded_by_calc_id, cancelled_reason, planned_size, overridden_size, planned_tp, overridden_tp, planned_sl, overridden_sl, tp_levels (JSON), filled_pct, tags (JSON) | `core/database.py` |
| 0.7 | Add columns to `orders`: link_status, operator_id, cancel_reason_category, cancel_reason_raw, cancel_ts_ms | `core/database.py` |
| 0.8 | Add columns to `closed_positions`: exit_reason (re-mapped), close_note, entry_px_delta_pct, size_delta_pct, tp_drift_pct, sl_drift_pct, exit_vs_target_pct, realized_r, planned_r, hold_time_actual_ms, hold_time_planned_ms, cumulative_amendment_count, funding_fees (already exists, repurpose), liquidation_px, bankruptcy_px, insurance_fund_fee, adl_indicator | `core/database.py` |
| 0.9 | Add `accounts.config_json` column | `core/database.py` |
| 0.10 | Create all indexes per spec §3.1 | `core/database.py` |
| 0.11 | Migration script: backfill `positions_calcs` from existing `fills WHERE calc_id IS NOT NULL`, grouped by (position lifecycle, calc_id), `contributed_qty = SUM(fill_qty)` | `migrations/` (new dir or extend existing) |
| 0.12 | Re-map existing `closed_positions.exit_reason`: `'manual'`→`MANUAL_OTHER`; `'tp'`→`TP_PLANNED`; `'sl'`→`SL_PLANNED`; default to `MANUAL_OTHER` if NULL | same migration script |

### Tests

- `tests/test_phase0_schema.py`:
  - All tables exist with expected columns + indexes
  - All foreign-key relationships valid (no orphan rows after backfill)
  - `positions_calcs` rows correctly reconstructed from historical fills
    (synthetic golden dataset)
  - `pre_trade_log.status` default = `'active'` for existing rows
  - `orders.link_status` backfilled correctly (LINKED if calc_id present,
    UNPLANNED otherwise)

### Acceptance criteria

- All migrations run idempotently (re-running has no effect)
- All existing tests still pass (no behavior change)
- Backfill report logged: count of junction rows created, count of
  orders re-categorized
- DB size growth measured and documented

---

## Phase 1: Matcher tightening

**Goal**: Replace existing 3/3 (limit) / 2/2 (market) matcher with
strict 5/5 / 6/6. Add per-criterion audit. Per-account window from
`config_json`. Clock-skew tolerance. Calc revision supersede.

**Dependencies**: Phase 0.

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 1.1 | Rewrite matcher to strict-all-or-fall-through | [core/calc_correlation.py](core/calc_correlation.py) — replace `correlate_order_to_calc()` |
| 1.2 | Read `window_seconds` and `clock_skew_tolerance_sec` from `accounts.config_json` per-account | new `core/account_config.py` helper |
| 1.3 | Freeze `window_seconds` onto `pre_trade_log.window_seconds` at calc creation | [core/handlers.py:182-260](core/handlers.py#L182-L260) `handle_risk_calculated()` |
| 1.4 | Write per-criterion `calc_match_audit` rows for every match attempt (winning + losing candidates) | `core/calc_correlation.py` + `core/db_orders.py` |
| 1.5 | Implement calc-revision detection on Calculate: if existing `active` calc for (account, ticker, direction) exists, set `status='superseded'`, `superseded_by_calc_id`, emit `calc:superseded` event | `core/handlers.py` |
| 1.6 | Implement calc-cancel-by-operator endpoint + status transition | `api/routes_calculator.py`, `core/handlers.py` |
| 1.7 | Implement calc-released state after order cancel: when order's `cancel_reason_category='OPERATOR'`, set linked calc's status back to `released` (within original window) | [core/order_manager.py](core/order_manager.py) (cancel-path handler) |
| 1.8 | Implement calc auto-complete on position close: when position closes, transition all contributing calcs to `completed_via_position` + emit `calc:completed` | `core/order_manager.py:_build_close_row_for_fill()` |
| 1.9 | Implement entry-tolerance band separate from tick-size (default 0.25% via config) | `core/calc_correlation.py` |
| 1.10 | Allow nullable TP/SL on calc; if either is null, auto-route to manual-link (link_status=NEEDS_MANUAL_REVIEW regardless of other criteria) | `core/calc_correlation.py` |

### Tests

- `tests/test_phase1_matcher.py`:
  - Strict 5/5 limit: missing 1 criterion → NEEDS_MANUAL_REVIEW
  - Strict 6/6 market: missing 1 criterion → NEEDS_MANUAL_REVIEW
  - Full match: LINKED + audit row per criterion
  - Window frozen: config change after calc creation does not affect
    in-flight calc expiry
  - Clock-skew: ±tolerance padding works at window boundary
  - Calc revision: 2nd calc for same (symbol, direction) marks 1st as
    superseded + emits event
  - Calc cancel: status transition + event emitted
  - Order cancel released calc: re-match eligible for replacement
  - Calc auto-complete on position close: status + event
  - Nullable TP or SL: routes to manual-link

### Acceptance criteria

- All Phase 0 tests still pass
- No silent regression in existing match success rate (compare audit-log
  link rate before/after on a golden dataset)
- Per-criterion audit rows present for 100% of order arrivals
- Calc state machine transitions verified end-to-end

---

## Phase 2: Position-level attribution

**Goal**: Junction-aware position lifecycle. `PositionInfo.calc_id`
populated. Scale-in append-to-junction. Closing fills stamped.
Deltas computed at close.

**Dependencies**: Phase 0, Phase 1.

**Effort**: L (touches the hottest path in the engine).

### Tasks

| # | Task | File(s) |
|---|---|---|
| 2.1 | On every opening fill, insert/update `positions_calcs` row (single row per order, `contributed_qty` updated on each fill) | [core/order_manager.py](core/order_manager.py) `process_fill()` |
| 2.2 | Stamp `calc_id` on every closing fill (inherited from position's primary calc_id) | `core/order_manager.py` close-side fill handler |
| 2.3 | Add `calc_id` field to `PositionInfo`; populate from junction on first fill + on rehydrate | [core/state.py:115-160](core/state.py#L115-L160), `core/exchange.py:350` |
| 2.4 | Scale-in path: if new calc fires while position open and resulting fill arrives, append to junction with new calc_id; per-calc planned_tp/sl/size copied from calc at contribution time | `core/order_manager.py` |
| 2.5 | At position close, compute all deltas: `entry_px_delta_pct`, `size_delta_pct`, `tp_drift_pct`, `sl_drift_pct`, `exit_vs_target_pct`, `realized_r`, `cumulative_amendment_count`, `hold_time_actual_ms` | `core/order_manager.py:_build_close_row_for_fill()` |
| 2.6 | At close, set `closed_positions.calc_id` = most-contributing calc (largest contributed_qty); tie-break first-entry | `core/order_manager.py` |
| 2.7 | At close, set `exit_reason` based on plan-vs-realized + close-detection: PLANNED if final TP/SL prices match plan within tolerance, AMENDED if `cumulative_amendment_count > 0` and prices differ | `core/order_manager.py` |
| 2.8 | TP/SL bracket detection: implement per-adapter `detect_bracket()` using venue-native fields (Bybit `orderLinkId`, Binance `positionSide` clustering, OKX `algoOrdId`) with 2s time-window fallback | [core/adapters/bybit/rest_adapter.py](core/adapters/bybit/rest_adapter.py), [core/adapters/binance/rest_adapter.py](core/adapters/binance/rest_adapter.py) |
| 2.9 | TP/SL inheritance from entry: when bracket detected, propagate entry's `calc_id` to TP and SL orders | `core/order_manager.py` order-arrival handler |
| 2.10 | Standalone TP/SL on existing position: auto-inherit from position's latest calc (per Q19 rule) | `core/order_manager.py` |
| 2.11 | Multi-TP partial-close lifecycle: on each TP fill, emit `position:partial_close`; position stays OPEN until size=0; final `exit_reason=TP_LADDER_COMPLETE` or `MIXED` | `core/order_manager.py` |
| 2.12 | Restart rehydrate: pull all open positions; for each, populate `calc_id` and `contributing_calc_ids` from `positions_calcs`; recompute deviation flags | `core/state.py`, `core/exchange.py`, startup hook |

### Tests

- `tests/test_phase2_junction.py`:
  - Single-fill position: junction row written; PositionInfo.calc_id set
  - Multi-fill same order: junction row updated cumulatively
  - Scale-in: 2nd calc appends new junction row; PositionInfo carries both
  - Closing fill: calc_id stamped from position primary
  - Deltas computed correctly at close (synthetic plan vs actual)
  - exit_reason classification: TP_PLANNED vs TP_AMENDED based on amendments
  - Bracket detection: Bybit link_id, Binance positionSide cluster, fallback time-window
  - Standalone TP/SL: auto-inherits position calc on existing position
  - Multi-TP: 3 TP fills → 3 partial_close events + final TP_LADDER_COMPLETE
  - Restart: junction rehydrates PositionInfo.calc_id correctly

### Acceptance criteria

- Junction populated for 100% of new fills post-deployment
- Closed_positions deltas non-null for all positions opened after Phase 2 deploy
- All existing position-close tests still pass
- Restart with 5+ open positions correctly rehydrates calc attribution

---

## Phase 3: Link status + manual-link tab

**Goal**: Order `link_status` enum drives UI. Operator can manually
link via side-by-side diff panel. UNPLANNED auto-classification.

**Dependencies**: Phase 0, Phase 1.

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 3.1 | Set `link_status` on every order arrival based on matcher outcome (LINKED, NEEDS_MANUAL_REVIEW, UNLINKED) | `core/order_manager.py` |
| 3.2 | Auto-UNPLANNED logic: if matcher finds zero candidates in window for (account, ticker, direction), set `link_status=UNPLANNED` immediately | `core/calc_correlation.py` |
| 3.3 | New endpoint `POST /orders/{id}/manual_link` accepting `calc_id` | `api/routes_orders.py` |
| 3.4 | New endpoint `POST /orders/{id}/mark_unplanned` for operator downgrade UNLINKED→UNPLANNED | `api/routes_orders.py` |
| 3.5 | New endpoint `GET /orders/needs_review` returning all NEEDS_MANUAL_REVIEW + UNLINKED orders with candidate calcs per-criterion diff | `api/routes_orders.py` |
| 3.6 | Build needs-link tab UI: side-by-side per-criterion diff panel (order on left, candidates with color-coded matches on right); "Link to this calc" / "Mark UNPLANNED" buttons | `templates/needs_link.html` (new), `static/js/needs_link.js` (new) |
| 3.7 | Persistent status badge in trades/history tab per order: green LINKED / yellow NEEDS_REVIEW / gray UNLINKED / blue UNPLANNED | `templates/history.html`, `static/css/badges.css` |
| 3.8 | Nav badge counter for needs-link tab (count of NEEDS_REVIEW + UNLINKED orders) | base template |

### Tests

- `tests/test_phase3_link_status.py`:
  - Order with full match → LINKED
  - Order with partial match → NEEDS_MANUAL_REVIEW; appears in /needs_review
  - Order with no candidates → UNPLANNED automatically
  - Operator manual-link transitions NEEDS_REVIEW → LINKED
  - Operator mark-unplanned transitions UNLINKED → UNPLANNED
  - Diff panel renders correct per-criterion matches/misses

### Acceptance criteria

- 100% of orders have non-null link_status post-deployment
- Manual-link UI usable end-to-end by operator (smoke test)
- Badge counter accurate; updates on link/dismiss actions

---

## Phase 4: Amendment tracking + deviation

**Goal**: Every TP/SL/entry/size amendment writes a row. Deviation
flags drive live position badges.

**Dependencies**: Phase 0, Phase 2.

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 4.1 | Detect order amendments from WS: compare incoming order_update against stored order; if `entry_price` / `tp_price` / `sl_price` / `size` / `leverage` changed, write `order_amendments` row | [core/ws_manager.py:141-205](core/ws_manager.py#L141-L205) |
| 4.2 | Compute `deviation_pct` per amendment row: `(new - old) / old * 100` | `core/db_orders.py` |
| 4.3 | Update `closed_positions.cumulative_amendment_count` at close from junction × amendments | `core/order_manager.py:_build_close_row_for_fill()` |
| 4.4 | Implement deviation badge logic: per open position, compute `live_tp` vs `planned_tp` (from junction's most recent calc); apply yellow/red thresholds from `config_json` | `core/state.py` PositionInfo computation, frontend rendering |
| 4.5 | Emit `position:amended` event on each amendment row insert | `core/ws_manager.py` or `core/order_manager.py` |
| 4.6 | Populate `tp_drift_pct` and `sl_drift_pct` on closed_positions: drift = final TP/SL vs first calc's planned values | `core/order_manager.py:_build_close_row_for_fill()` |

### Tests

- `tests/test_phase4_amendments.py`:
  - Single TP modification writes row with correct deviation_pct
  - Multiple amendments on same order: all rows present, ordered by ts
  - Entry-price amendment before fill: link preserved, row written
  - SL amendment after position open: row + position:amended event
  - Deviation badge thresholds: 4% drift = green, 7% = yellow, 20% = red
  - Closed_positions.cumulative_amendment_count correct

### Acceptance criteria

- 100% of amendments captured (parity test: WS amendment events =
  `order_amendments` row count)
- Live deviation badge renders correctly for in-flight positions
- Drift columns populated on close for amended-stop positions

---

## Phase 5: Funding + fees attribution

**Goal**: Funding events written per-event; fees aggregated at close;
realized PnL includes funding.

**Dependencies**: Phase 0, Phase 2.

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 5.1 | Subscribe to venue income/funding WS stream per adapter | [core/adapters/binance/](core/adapters/binance/) + [core/adapters/bybit/](core/adapters/bybit/) WS handlers |
| 5.2 | On funding event arrival: look up active position for (account, symbol); if found, write `funding_events` row with (position_id, calc_id=primary, amount, mark_price, funding_rate, ts, venue_event_id) | new `core/funding_handler.py` |
| 5.3 | Deduplication on `venue_event_id` (idempotent in case of WS replay) | `core/funding_handler.py` |
| 5.4 | At position close, populate `closed_positions.funding_fees = SUM(funding_events.amount WHERE position_id=...)` | `core/order_manager.py:_build_close_row_for_fill()` |
| 5.5 | Recompute `closed_positions.net_pnl` = realized_pnl - total_fees + funding_fees | `core/order_manager.py:_build_close_row_for_fill()` |
| 5.6 | Per-fill fee already exists on `fills.fee`; ensure `closed_positions.total_fees = SUM(fills.fee)` is correctly populated (currently may be partial) | `core/order_manager.py:587` (refresh) |
| 5.7 | Live unrealized funding view: helper that returns `SUM(funding_events.amount)` for an open position; surface in position detail UI | `core/state.py`, position detail template |

### Tests

- `tests/test_phase5_funding.py`:
  - Funding event during open position: row written; linked to correct position_id
  - Multiple funding events: SUM correct at close
  - Duplicate venue_event_id ignored
  - Closed position has non-null funding_fees if any events accrued
  - net_pnl includes funding adjustment
  - Live unrealized funding helper returns correct sum

### Acceptance criteria

- 100% of venue funding events post-deployment attributed to a position
  (with optional "orphan funding" log for events without an open
  position — should be rare)
- Reconciliation against venue settlement statements: closed_position
  funding_fees within $0.01 of venue's per-position funding total

---

## Phase 6: Event bus enrichment + close payload

**Goal**: Hierarchical per-account event topics. Full close payload.
All new events from Phases 1-5 actually emitted.

**Dependencies**: Phases 1, 2, 4, 5.

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 6.1 | Wrap existing `event_bus.publish` to construct topic strings: `engine:account:{account_id}:{domain}:{event}` | [core/event_bus.py](core/event_bus.py) (or wherever event_bus lives) |
| 6.2 | Emit all calc:* events from Phase 1 (created, linked, superseded, expired, cancelled, completed, partially_filled, size_deviated, order_cancelled) | per Phase 1 task list |
| 6.3 | Emit all position:* events from Phase 2 (opened, scale_in, partial_close, closed, liquidated, size_drift) | per Phase 2 |
| 6.4 | Emit position:amended from Phase 4 | per Phase 4 |
| 6.5 | Emit order:duplicate_detected when matcher sees 2+ near-identical orders within N ms window | new in `core/order_manager.py` order-arrival path |
| 6.6 | Position:closed payload expansion: replace anemic current payload at [core/order_manager.py:728-731](core/order_manager.py#L728-L731) with full payload per spec §9 (calc_ids, model_names, deltas, exit_reason, MFE/MAE, funding_fees, etc.) | `core/order_manager.py` |
| 6.7 | Position:liquidated dedicated event with liquidation-specific fields | `core/order_manager.py` close path when exit_reason=LIQUIDATION |
| 6.8 | Position:size_drift event when snapshot disagrees with fill-derived size beyond tolerance | [core/data_cache.py:159-194](core/data_cache.py#L159-L194) — INVERT the WS-fills-win-within-5s policy to snapshot-wins-with-drift-event |

### Tests

- `tests/test_phase6_events.py`:
  - Each event type fires with correct topic and payload shape
  - position:closed payload includes all spec §9 fields
  - position:size_drift fires when synthetic snapshot disagrees
  - duplicate_detected fires for near-identical orders within window

### Acceptance criteria

- Subscriber test harness can consume all event types end-to-end
- Position:closed payload schema validated against spec
- No regression in existing event consumers (existing subscribers may
  need shape-compatibility shims if they assumed the old anemic shape)

---

## Phase 7: Reverse-query + audit export

**Goal**: External model can fetch full causal chain for any calc or
position. Audit export for compliance.

**Dependencies**: Phases 2, 4, 5, 6.

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 7.1 | New endpoint `GET /context/calc/{calc_id}` returning full graph payload per spec §11.1 | new `api/routes_context.py` |
| 7.2 | New endpoint `GET /context/position/{position_id}` returning full graph keyed on position | `api/routes_context.py` |
| 7.3 | Pagination + caching for endpoints if response > N KB (likely needed for multi-day positions with many amendments + funding events) | same |
| 7.4 | Position-closed webhook: single configured URL per account in `config_json.webhook_url`; engine POSTs `{event: position_closed, payload: <full §9>}` on every close | new `core/webhook_dispatcher.py` |
| 7.5 | Webhook retry with exponential backoff + dead-letter queue | `core/webhook_dispatcher.py` |
| 7.6 | New endpoint `POST /export/closed_position/{id}` generating JSON + PDF audit bundle with signed timestamp | new `api/routes_export.py`; PDF gen via reportlab or similar |
| 7.7 | Per-account batch export endpoint (date range) for compliance dumps | `api/routes_export.py` |

### Tests

- `tests/test_phase7_context.py`:
  - GET /context/calc/{id} returns complete graph for synthetic trade
  - GET /context/position/{id} aggregates correctly for multi-calc scale-in
  - Webhook fires on position close; retries on 5xx; dead-letters after N attempts
  - Audit export JSON has all required fields
  - PDF generation completes without errors

### Acceptance criteria

- External custom model can subscribe to webhook + fetch full context
  per close event with no engine modification
- Audit export passes structural validation against spec schema
- Webhook latency < 5s p95 on position close

---

## Phase 8: Operator UX

**Goal**: Multi-pane dashboard, modals, notifications, calculator
window config.

**Dependencies**: Phases 1, 2, 3, 4.

**Effort**: L (significant frontend work).

### Tasks

| # | Task | File(s) |
|---|---|---|
| 8.1 | Multi-pane dashboard: 4 panes (open positions, active calcs, needs-link, recent closes) visible simultaneously | `templates/dashboard.html` (new or refactor index.html), `static/js/dashboard.js` |
| 8.2 | Open positions pane: live deviation badges, MFE/MAE, uPnL | `templates/partials/positions_pane.html` |
| 8.3 | Active calcs pane: live countdown timers using frozen `window_seconds + created_ts`; cancel button per calc | `templates/partials/calcs_pane.html`, `static/js/calc_countdown.js` |
| 8.4 | Calculator tab: window dropdown (1/5/15 min) writing to `accounts.config_json.window_seconds`; override-aware size/TP/SL inputs (planned + overridden) | `templates/calculator.html` |
| 8.5 | Multi-TP UI: allow tp_levels array entry in calculator | same |
| 8.6 | Replacement modal (Q42): triggered at order-placement time when released calc near-matches; pre-submission decision | `static/js/replacement_modal.js` |
| 8.7 | Manual-close reason modal (Q33): triggered on opposite-side order detection without calc match; dropdown + optional note | `static/js/manual_close_modal.js` |
| 8.8 | Notification system: toast banners + persistent badge counters; subscriptions from `config_json.notification_subscriptions` | `static/js/notifications.js`, `templates/partials/toast.html` |
| 8.9 | Settings page for `accounts.config_json` (window, clock-skew, deviation thresholds, notification subscriptions) | `templates/settings.html` |

### Tests

- `tests/test_phase8_ui.py` (template render tests per CLAUDE.md
  discipline):
  - Dashboard renders all 4 panes with synthetic state
  - Countdown timer JS computes remaining time correctly from frozen ts
  - Replacement modal triggers on near-match scenario
  - Manual close modal triggers on opposite-side without calc
  - Notification badge increments on event arrival
  - Settings page persists config_json changes

### Acceptance criteria

- Operator smoke test: full lifecycle (Calculate → paste → fill → close)
  visible end-to-end in dashboard
- Deviation badges update live when amendment events fire
- Replacement and manual-close modals not bypassed by edge cases

---

## Phase 9: Multi-operator + advanced

**Goal**: Single-operator-per-account lock with takeover. Operator_id
on all action rows.

**Dependencies**: Phases 0, 1, 2, 3 (operator_id columns must exist).

**Effort**: M.

### Tasks

| # | Task | File(s) |
|---|---|---|
| 9.1 | Implement single-operator-per-account lock: on UI load, check `operator_sessions` for active session; if exists and not own session, show read-only + takeover prompt | new `core/auth_state.py` + frontend |
| 9.2 | Takeover endpoint: terminates prior session; writes new `operator_sessions` row with `takeover_from_session_id` | `api/routes_auth.py` (new or extend) |
| 9.3 | Propagate `operator_id` from active session to every action row write (calcs, orders, amendments, manual_links, close reasons) | call-site updates across `core/handlers.py`, `core/order_manager.py`, `core/ws_manager.py`, `api/routes_*` |
| 9.4 | Session timeout: idle session auto-terminated after N min (default 30) | `core/auth_state.py` background job |

### Tests

- `tests/test_phase9_multi_operator.py`:
  - Second operator login: sees read-only + takeover prompt
  - Takeover: prior session terminated; new operator_id propagates
  - operator_id correctly stamped on calcs, orders, amendments,
    manual_links, close_reasons
  - Idle session times out

### Acceptance criteria

- Two concurrent operators cannot both act on the same account
- Audit query "who created this calc" returns correct operator_id
- Session handoff visible in `operator_sessions` table

---

## 10. Test strategy across phases

### Levels

- **Unit**: per-module tests (matcher, junction CRUD, amendment
  detection, deviation computation) — each phase has its own test file
- **Integration**: end-to-end flows (calc → order → fill → close)
  exercising multiple phases together
- **Template wiring**: per CLAUDE.md, compile-and-render templates
  with synthetic context, assert structure
- **Migration**: pre/post migration state validation; rollback testing

### Golden datasets

Create `tests/fixtures/golden/`:
- `simple_trade.json` — 1 calc → 1 order → 1 fill → close
- `scale_in_trade.json` — 2 calcs → 2 orders → multiple fills → close
- `multi_tp_trade.json` — 1 calc with 3 TP levels → partial closes → final close
- `amended_trade.json` — operator widens SL mid-trade → close at amended SL
- `manual_close_trade.json` — operator manual-closes at +1R (NEW_OPPORTUNITY)
- `liquidation_trade.json` — venue liquidates position
- `replacement_trade.json` — order cancel → operator places replacement → matched to released calc
- `orphan_calc.json` — calc computed but no order placed
- `unplanned_order.json` — order placed with no calc in window
- `funding_trade.json` — multi-day position with 3 funding accruals
- `rehydrate_state.json` — engine restart mid-trade with all junction state

Each fixture runs against the full pipeline post-deployment and
verifies all expected events + DB rows.

### Performance

- Junction query benchmarks: position list with 1000+ open positions
  rehydrates < 2s
- Reverse-query endpoint: GET /context/calc/{id} < 200ms p95 for 30-day
  history
- WS event throughput: 100 fills/sec sustained without amendment-write
  contention

---

## 11. Migration / rollback plan

### Forward migration

Phase 0 is the only phase that touches the DB schema. Strategy:

1. **Pre-deployment**: backup full DB
2. **Run Phase 0 migration**: idempotent; safe to retry
3. **Verify**: run Phase 0 tests; verify backfill counts match
   expected (junction rows ≈ historical fills WHERE calc_id IS NOT NULL,
   grouped)
4. **Deploy code Phase 1+**: incrementally; each phase shippable
   independently to its dependencies
5. **Feature flags**: gate Phase 3 (link_status UI), Phase 6 (full
   event payload), Phase 7 (webhook) behind `config_json.feature_flags`
   so each can be enabled per-account incrementally

### Rollback

- **Phase 0 schema rollback**: drop new tables; remove new columns;
  re-cast `closed_positions.exit_reason` back to old values. DESTRUCTIVE
  — backfill data lost. **Recommended: forward-fix only, no rollback.**
- **Phase 1+ code rollback**: revert via git; schema stays in place
  (new tables become unused; no harm)
- **Webhook rollback** (Phase 7): disable webhook URL in config; engine
  retains events but doesn't dispatch

### Compatibility shims

- Existing subscribers to anemic `position_closed` event may break with
  Phase 6 payload expansion. Mitigation: emit both old and new event
  types for one release cycle; deprecate old after subscribers migrate.
- Existing `find_candidate_calcs()` manual UI ([core/order_enrichment.py:164-265](core/order_enrichment.py#L164-L265))
  remains during Phase 3 deployment as fallback; remove after needs-link
  tab proven stable.

---

## 12. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **Junction write contention on high fill volume** | Indexed by `(position_id)` + `(order_id)`; batch writes within same WS event handler; upsert-style; benchmark before Phase 2 deploy |
| **Migration backfill produces incomplete junction for old positions** | Documented as "full attribution from migration date forward"; historical reports get partial; new dashboards filter by date |
| **Per-criterion audit table grows fast** | Estimate: 5-6 rows per order × N orders/day; expect ~MB/day; partition by month if needed at scale |
| **Operator confused by strict 5/5 matching (more orders go to manual)** | Diff panel makes "why didn't this match" obvious; expected user feedback loop refines tolerances in config_json |
| **Bracket detection misclassifies non-bracket orders as siblings** | Time-window fallback is the fragile part; per-adapter venue-native takes priority; default 2s window tunable |
| **Snapshot-wins drift policy regresses on WS-fast / REST-slow venues** | Reconciler validates; rollback path: revert §12.6 inversion if drift events spike |
| **Webhook delivery failures lose model feedback** | Retry + dead-letter; subscriber polls reverse-query as backup |
| **Single-operator lock blocks legitimate concurrent operations across accounts** | Lock is per-account, not per-operator; operator can manage N accounts simultaneously, just one operator per account at a time |

---

## 13. Effort summary

| Phase | Effort | User-visible value at end of phase |
|---|---|---|
| 0 — Foundation | M | None (schema only) |
| 1 — Matcher | M | Strict matching live; per-criterion audit visible |
| 2 — Junction attribution | L | Open positions show calc_id; deltas at close |
| 3 — Link status UI | M | Needs-link tab; manual review workflow |
| 4 — Amendments + deviation | M | Live deviation badges on positions |
| 5 — Funding + fees | M | Closed positions show correct net PnL with funding |
| 6 — Event bus enrichment | M | Subscribers receive full context on close |
| 7 — Reverse query + export | M | External models can fetch; audit export works |
| 8 — Operator UX | L | Multi-pane dashboard; modals; settings |
| 9 — Multi-operator | M | Concurrent operator safety |

**Total estimated effort**: ~8-12 weeks single-developer; parallelizable
to ~4-6 weeks with phases 4/5/6 and 7/8/9 split across two developers
post-Phase 2.

**Critical path**: Phase 0 → 1 → 2 → 6 → 7. Without these, no
end-to-end model-feedback loop exists.

**Lowest-risk early win**: Phase 0 + Phase 4 (amendment tracking) +
Phase 8.4-8.5 (calculator window config). Delivers operator-visible
deviation badges and configurable windows with minimal blast radius.

---

## 14. Deferred (post-implementation)

- Engine-generated tag for deterministic linkage (gap #10 — explicitly
  out of scope per spec §13)
- Close-calc operator pathway (Q8/Q30 — walked back)
- External event delivery (Redis pub/sub, Slack, email) — webhook
  bridge in Phase 7 sufficient for now
- Live time-series snapshots for per-second position state history
- Multi-leg / pairs strategies
- Role-based access control beyond single-operator lock
- Q19 vs Q54 unification (auto-inherit vs manual-link for standalone
  TP/SL); defer to operator feedback after Phase 3 ships

---

**End of implementation plan.**
