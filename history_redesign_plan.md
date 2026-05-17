# History Page Redesign — Implementation Plan (v2.4)

**Status:** Spec document. Source of truth for the multi-task implementation that follows.
**Predecessor audit:** `docs/audits/2026-05-15-history-redesign-data-audit.md`
**Target stack:** FastAPI + Jinja2 + HTMX 1.9.12 + Idiomorph (existing).

---

## Why This Plan Differs From the Initial README

A pre-implementation audit (see predecessor) discovered that the original design README's proposals were significantly larger than what's genuinely needed:

- `live_trades` table was a dead-code CSV path. Replaced with: no separate table or tab — Live Trades is what the dashboard's position card already shows.
- `closed_positions.exit_reason`, `mfe`, `mae` already exist (README incorrectly proposed adding them).
- `pre_trade_log.model_name`, `orders.tp_trigger_price`, `orders.sl_trigger_price`, `fills.calc_id`, `fills.slippage_actual` already exist.
- `execution_log` exists but is a **manual-entry** table — the README assumed auto-populated execution snapshots. The exec link feature is repurposed against `pre_trade_log` instead, where data is auto-populated for engine-traded positions.

Net effect: ~5 tasks instead of ~6, smaller LOC budget, two genuinely needed schema additions.

---

## Final Page Structure

```
┌─ Card 1: Open Positions + Open Orders ─────────────────────────────┐
│  (existing fragment, columns extended)                              │
└────────────────────────────────────────────────────────────────────┘
┌─ Toolbar (date range, search) ─────────────────────────────────────┐
│  (unchanged)                                                        │
└────────────────────────────────────────────────────────────────────┘
┌─ Card 2: Position History | Order History | Trade History ────────┐
│  (3 tabs — NO Live Trades tab)                                     │
└────────────────────────────────────────────────────────────────────┘
┌─ Card 3: Pre-Trade Log | Trade Events Log ────────────────────────┐
│  (2 tabs — Tab 2 is Trade Events Log, NOT Execution Log)          │
└────────────────────────────────────────────────────────────────────┘
```

---

## Architectural Decisions

1. **No new `live_trades` table.** Open positions are visible in the dashboard's position card. Building a parallel "live trades" view on the history page duplicates that information without adding value. The existing CSV-backed `update_live_trade()` function in `core/data_logger.py:94` (which is never called) should be removed as dead code.

2. **Exec link feature repurposed: fills ↔ pre_trade_log (via calc_id).** Original design matched fills against `execution_log`, which is a manual-entry table — limited utility. Repurposed: match each entry fill against the `pre_trade_log` entry with the same `calc_id` (auto-populated for all engine-traded positions since v2.4). Same 3-criteria tolerance-based matching algorithm.

3. **Card 3 Tab 2 is "Trade Events Log", not "Execution Log".** Reads from `trade_event_log` (12 event types actively emitted). Provides a chronological audit timeline — more informative than the manual execution_log for engine-traded positions.

4. **Denormalization scope: `tp_price`/`sl_price` on `closed_positions` only.** For Position History display, denormalize for fast queries. For Fill Drawer (single-position context, drawer-load only), use the join path: `fills.calc_id → pre_trade_log.tp_price/sl_price`. Avoids redundancy on fills.

---

## Schema Changes

### Migration: `closed_positions` add TP/SL columns

```sql
ALTER TABLE closed_positions ADD COLUMN tp_price REAL DEFAULT NULL;
ALTER TABLE closed_positions ADD COLUMN sl_price REAL DEFAULT NULL;
```

**Population**:
- On new closes: copy from the matching `pre_trade_log` row at close time, joining via `calc_id`.
- Backfill (one-shot): UPDATE existing rows by joining via `calc_id`; rows without calc_id remain NULL (legacy data acceptable as "—" in display).

### Optional: `fills` add exec-link tracking columns

```sql
ALTER TABLE fills ADD COLUMN exec_link_confirmed INTEGER DEFAULT 0;
ALTER TABLE fills ADD COLUMN exec_link_confirmed_at TEXT DEFAULT NULL;
ALTER TABLE fills ADD COLUMN exec_link_confirmed_by TEXT DEFAULT NULL;
```

These are only needed if pursuing the exec link feature with user-confirmed partial matches. If exec link is auto-only (3/3 matches always link, anything less is "PARTIAL" without persistent state), skip these and don't persist confirmations.

---

## Card 1 — Open Positions + Open Orders

**Fragment:** `templates/fragments/history/open_positions.html`
**Endpoint:** existing `/fragments/history/open_positions` (unchanged — `hx-trigger="load, every 1s"`)

### Positions sub-tab — columns to add

Source fields per audit: all already exist on `TradePosition` dataclass.

| New column | Source field | Styling |
|---|---|---|
| Fees | `individual_fees` | class `td-sub` |
| Net | `individual_unrealized - individual_fees` | green/red bold |
| MFE | `session_mfe` | green |
| MAE | `session_mae` | red |
| TP | `individual_tp_price` | green, `fmt(v,4)` |
| SL | `individual_sl_price` | red, `fmt(v,4)` |

Full column order: Symbol · Dir · Hold · Entry · Mark · Size · Notional · uPnL · **Fees** · **Net** · **MFE** · **MAE** · **TP** · **SL**

---

## Card 2 — Tab 1: Position History

**Fragment:** `templates/fragments/history/closed_positions_table.html` (exists but not wired to page)
**Endpoint:** `GET /fragments/history/closed_positions`
**Required wiring:** include in restructured `history.html`.

### Updated columns

| Column | DB field | Render notes |
|---|---|---|
| Open | `entry_time_ms` | `ms_to_local()`, class `td-ts` |
| Close | `exit_time_ms` | `ms_to_local()`, class `td-ts` |
| Hold | computed | `hold_h`h format |
| Symbol | `symbol` | class `td-symbol` |
| Dir | `direction` | class `pos-long` / `pos-short` |
| Qty | `quantity` | `fmt(v,4)` |
| Notional | `entry_price * quantity` | `fmt(v,2)` |
| PnL | `net_pnl` | green/red bold |
| **PnL %** | `(net_pnl / (entry_price*quantity))*100` | green/red `fmt(v,2)%` — NEW |
| **Exit Reason** | `exit_reason` | badge — NEW (already-existing field) |
| **TP** | `tp_price` | green, `fmt(v,4)` — NEW (requires migration) |
| **SL** | `sl_price` | red, `fmt(v,4)` — NEW (requires migration) |
| MFE | `mfe` | `fmt(v,2)` green |
| MAE | `mae` | `fmt(v,2)` red |

### Exit Reason badge mapping

```html
{% if r.exit_reason == 'tp_hit' %}
  <span class="badge badge-ok">TP</span>
{% elif r.exit_reason == 'sl_hit' %}
  <span class="badge badge-limit">SL</span>
{% elif r.exit_reason == 'trailing_stop' %}
  <span class="badge badge-warning">Trail</span>
{% elif r.exit_reason == 'manual' %}
  <span class="badge badge-unknown">Manual</span>
{% elif r.exit_reason == 'liquidation' %}
  <span class="badge badge-limit">Liq</span>
{% else %}
  <span class="badge badge-unknown">{{ r.exit_reason or '—' }}</span>
{% endif %}
```

### Fill Drawer (row expand)

Each position row gets a leading chevron cell (`<td>▸</td>`). Click toggles an inline `<tr>` below it that lazy-loads the fills for that position.

- Leading column: width 18px, chevron `▸` (collapsed) / `▾` (expanded).
- Row click handler: `onclick="togglePosRow('{{ r.id }}')"`.
- Hidden row: `<tr id="fills-row-{id}" style="display:none;"><td colspan="N">...</td></tr>` where N = total column count.
- On first expansion: lazy-load via `htmx.ajax('GET', '/fragments/history/position_fills?position_id=X')`.

JS toggle pattern lives in `history.html` `<script>` block (not in fragment — avoids the Phase 5 lesson about inline scripts re-executing on morph).

### Warning icon for unresolved exec links

If any entry fill for this position has `exec_link_status` in (`partial`, `unlinked`), render an amber ⚠ glyph next to the symbol cell. Compute `has_unresolved_exec_links` server-side when building the row queryset (count of fills with non-linked status).

---

## Card 2 — Tab 1 (sub): Fill Drawer Fragment (NEW)

**New endpoint:** `GET /fragments/history/position_fills?position_id={id}`
**New template:** `templates/fragments/history/position_fills.html`

Mini-table of all fills for a position. Each entry fill shows an exec link badge; close fills don't.

### Columns

Time · Order No. · Side · Price · Qty · Fee · Role · PnL · **Exec Link**

### Distinguishing entry vs close fills

Entry fills are determined by `fill.tp_price IS NOT NULL` (set when fill linked to a pre_trade_log calc with TP/SL). Close fills have NULL tp_price and skip the exec link badge.

> Implementation note: since fills don't currently store tp_price directly (per audit), this is resolved via the join: `fills.calc_id → pre_trade_log.tp_price`. The query builds an `is_entry_fill` boolean per row server-side.

### Exec link badge (Jinja macro)

```html
{% macro exec_link_badge(f) %}
{% if f.exec_link_status == 'linked' %}
  <span class="badge badge-ok" onclick="toggleExecLink('{{ f.id }}')">● LINKED</span>
{% elif f.exec_link_status == 'partial' %}
  <span class="badge badge-warning" onclick="toggleExecLink('{{ f.id }}')">⚠ {{ f.exec_match_count }}/3</span>
{% else %}
  <span class="badge badge-limit" onclick="toggleExecLink('{{ f.id }}')">✗ UNLINKED</span>
{% endif %}
{% endmacro %}
```

Below each entry-fill row, an empty hidden `<tr>` for the exec link panel. Toggle via `toggleExecLink(fillId)` which lazy-loads `/fragments/history/exec_link?fill_id=X`.

---

## Card 2 — Tab 1 (sub): Exec Link Panel (REPURPOSED)

**Original design:** match fills against `execution_log` (manual entries).
**Repurposed:** match fills against `pre_trade_log` (auto-populated for engine trades) **via `calc_id`**.

**New endpoint:** `GET /fragments/history/exec_link?fill_id={id}`
**New template:** `templates/fragments/history/exec_link_panel.html`

### Matching algorithm

Given an entry fill `F` (must have `calc_id`) and the corresponding pre_trade_log entry `P`:

```python
PRICE_TOL = 0.0005  # 0.05% relative tolerance (configurable)

def price_near(a: float, b: float) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(abs(a), abs(b)) * PRICE_TOL

def compute_exec_match(fill: Fill, pretrade: PreTradeLog) -> ExecMatchResult:
    is_market = fill.order_type in ('MARKET', 'STOP_MARKET')
    em = True if is_market else price_near(pretrade.effective_entry, fill.price)
    tm = price_near(pretrade.tp_price, fill_tp_price)  # fill_tp from join
    sm = price_near(pretrade.sl_price, fill_sl_price)
    cnt = sum([em, tm, sm])
    return dict(
        pretrade_id=pretrade.id,
        entry_match=em, tp_match=tm, sl_match=sm,
        match_count=cnt, auto_link=cnt == 3, is_market=is_market,
    )
```

Match outcomes:
- **3/3**: AUTO-LINKED (green badge, no user action needed)
- **2/3** or **1/3**: PARTIAL (amber badge, user can review & confirm)
- **0/3** or no calc_id: UNLINKED (red badge)

### Tolerance value

`PRICE_TOL = 0.0005` (0.05%) is the starting default. Add a config knob `EXEC_LINK_PRICE_TOL` so it can be tuned without code changes.

### Panel layout

Three-criterion comparison table showing fill values vs pre_trade_log values side-by-side, with ✓/✗ icons per row. For market orders, the entry-price row shows "MARKET ORDER" instead of the planned price (since plan doesn't constrain entry for market). Action buttons appear only for partial matches: "Confirm Link" (POST to confirm endpoint), "Search Other" (re-fetch with broader candidates — TBD if needed).

### Confirm endpoint

`POST /history/exec_link/confirm`
- Body: `fill_id`, `pretrade_id` (or `calc_id`)
- Updates: `fills.exec_link_confirmed = 1`, `fills.exec_link_confirmed_at = now()`, `fills.exec_link_confirmed_by = 'user'`
- Returns: updated panel fragment

---

## Card 2 — Tab 2: Order History

**Fragment:** `templates/fragments/history/order_history_table.html` (exists, wired)
**No schema changes. No major content changes.** Already follows the unified row styling from Tasks 66-67.

---

## Card 2 — Tab 3: Trade History (NOT to be confused with `trade_events`)

**Fragment:** `templates/fragments/history/trade_history_table.html` (exists, NOT wired)
**Endpoint:** `GET /fragments/history/trade_history`
**Required wiring:** include in restructured page.

Shows round-trip closed trades (one row per position entry+exit pair).

### Columns to add

| Column | Source | Notes |
|---|---|---|
| Exit Time | `exit_timestamp` | `[:19]`, class `td-ts` |
| Ticker | `ticker` | class `td-symbol` |
| Dir | `direction` | `pos-long` / `pos-short` |
| Entry | `entry_price` | `fmt(v,4)` |
| Exit | `exit_price` | `fmt(v,4)` |
| Realized | `individual_realized` | green/red bold |
| **R** | `individual_realized_r` | `fmt(v,2)R`, class `td-sub` (already on schema) |
| **Funding** | `total_funding_fees` | `fmt(v,4)`, class `td-sub` — NEW (DB field needed) |
| Fees | `total_fees` | `fmt(v,4)`, class `td-sub` |
| **Slip Exit** | `slippage_exit * 100` | `fmt(v,4)%`, class `td-sub` — NEW (DB field needed) |
| Hold Time | `holding_time` | class `td-sub` |
| Notes | `notes` | inline editable |

### Schema additions for trade_history

```sql
ALTER TABLE trade_history ADD COLUMN total_funding_fees REAL DEFAULT 0;
ALTER TABLE trade_history ADD COLUMN slippage_exit REAL DEFAULT 0;
```

> **RESOLVED (Task 69):** Verified — `trade_history` CREATE TABLE in `core/database.py:137` already includes both `total_funding_fees` and `slippage_exit` as original schema columns. No ALTER needed.

---

## Card 3 — Tab 1: Pre-Trade Log

**Fragment:** `templates/fragments/history/pre_trade_table.html`
**No schema changes** — `model_name` already exists per audit.

Add a `Model` column displayed after `Eligible`:

```html
<td class="td-sub">{{ r.model_name or '—' }}</td>
```

---

## Card 3 — Tab 2: Trade Events Log (replaces "Execution Log")

**Source:** existing `trade_events` table (per audit section 1).
**New endpoint:** `GET /fragments/history/trade_events`
**New template:** `templates/fragments/history/trade_events_table.html`

### Columns

| Column | Source | Notes |
|---|---|---|
| Time | `timestamp` | class `td-ts` |
| Account | `account_id` | dim |
| Symbol | inferred from payload | from payload_json |
| Event Type | `event_type` | colored badge per category |
| Calc ID | `calc_id` | class `td-dim`, monospace, truncated |
| Source | `source` | class `td-sub`, originating module |
| Detail | `payload_json` | summarized inline, expandable on click |

### Event type badge colors

| Event types | Badge style |
|---|---|
| `calc_created`, `order_placed` | `badge-ok` (green) |
| `position_opened` | `badge-ok` |
| `order_filled`, `partial_close` | `badge-ok` (subtle) |
| `tp_modified`, `sl_modified` | `badge-warning` (amber) |
| `order_canceled` | `badge-limit` (red, soft) |
| `position_closed` | `badge-ok` (green or red based on payload PnL sign) |
| `liquidated`, `manual_close` | `badge-limit` (red) |
| `manual_link_added` | `badge-unknown` (gray) |

### Query

Uses `core/trade_event_log.py:116` — `query_trade_events()` (already implemented). Add pagination + filter UI (date range from existing toolbar, ticker search, event_type dropdown).

### Detail expansion

`payload_json` is structured. For each event type, define a small renderer that formats relevant fields nicely (e.g., for `tp_modified`: "Old TP: 4.21 → New TP: 4.30"). Click row to toggle a detail row beneath with full JSON for power users.

---

## Fragments — Wire-Up vs Delete

| Fragment | Status | Action |
|---|---|---|
| `closed_positions_table.html` | Exists, NOT wired | Wire + extend columns (PnL%, Exit Reason, TP, SL) |
| `order_history_table.html` | Exists, wired | Keep |
| `trade_history_table.html` | Exists, NOT wired | Wire + extend columns (Funding, Slip Exit) |
| `pre_trade_table.html` | Exists, wired | Add Model column |
| `execution_table.html` | Exists, NOT wired | DELETE (manual execution_log is out of scope) |
| `live_trades_table.html` | Exists, NOT wired | DELETE (live trades concept dropped) |
| `position_fills.html` | NEW | Create (Fill Drawer) |
| `exec_link_panel.html` | NEW | Create (Exec Link Panel, against pre_trade_log) |
| `trade_events_table.html` | NEW | Create (Card 3 Tab 2) |

Also: `core/data_logger.py:94` `update_live_trade()` and the CSV at `data/live_trades_log.csv` are dead code — delete.

---

## New Endpoints Summary

| Method | Path | Template | Purpose |
|---|---|---|---|
| GET | `/fragments/history/position_fills?position_id=X` | `position_fills.html` | Fill drawer content |
| GET | `/fragments/history/exec_link?fill_id=X` | `exec_link_panel.html` | Exec link comparison panel |
| POST | `/history/exec_link/confirm` | `exec_link_panel.html` | Persist confirmed match |
| GET | `/fragments/history/trade_events` | `trade_events_table.html` | Trade Events Log tab content |

---

## Tab Switcher JS Pattern (Card 2 + Card 3)

Two independent switchers in `history.html` `<script>` block, following the existing `htTab` pattern:

```js
// Card 2: main history tabs
(function(){
  var _t = window._histMainTab || 'positions';
  var tabs = ['positions','orders','trades'];  // NOTE: no 'live'
  function histMainTab(t){ window._histMainTab=t; _apply(t); }
  function _apply(t){
    tabs.forEach(function(k){
      var p=document.getElementById('hm-panel-'+k);
      var b=document.getElementById('hm-tab-'+k);
      if(!p||!b)return;
      p.style.display=k===t?'':'none';
      b.style.color=k===t?'var(--blue)':'var(--muted)';
      b.style.borderBottomColor=k===t?'var(--blue)':'transparent';
    });
  }
  _apply(_t);
  window.histMainTab=histMainTab;
})();

// Card 3: log tabs
(function(){
  var _t = window._histLogTab || 'pretrade';
  var tabs = ['pretrade','events'];  // NOTE: 'events' not 'executions'
  function histLogTab(t){ window._histLogTab=t; _apply(t); }
  function _apply(t){
    tabs.forEach(function(k){
      var p=document.getElementById('hl-panel-'+k);
      var b=document.getElementById('hl-tab-'+k);
      if(!p||!b)return;
      p.style.display=k===t?'':'none';
      b.style.color=k===t?'var(--blue)':'var(--muted)';
      b.style.borderBottomColor=k===t?'var(--blue)':'transparent';
    });
  }
  _apply(_t);
  window.histLogTab=histLogTab;
})();
```

Scripts placed in `history.html` body (page-level, not fragment-level) — avoids the Phase 5 inline-script-re-executes-on-morph bug pattern.

---

## CSS / Design Tokens (already in base.html)

```
--blue   : #3c8ff5   (links, active tabs, chevrons)
--green  : #00c855   (long, profit, TP, linked)
--red    : #e83535   (short, loss, SL, unlinked)
--amber  : #e89020   (warnings, partial match, ⚠)
--sub    : #96b4d0   (secondary text)
--muted  : #526a88   (dimmed text)
--border : #18253a   (table borders)
--panel  : #101826   (input background)
--hover  : #141f2e   (row hover)
```

Existing cell classes from Task 66: `.td-symbol`, `.td-ts`, `.td-sub`, `.td-dim`, `.td-bold`, `.td-empty`.

Existing badge classes: `.badge`, `.badge-ok`, `.badge-limit`, `.badge-warning`, `.badge-unknown`.

---

## Implementation Task Breakdown

| Task | Scope | Approx LOC |
|------|-------|-----------|
| 69 | **Schema migrations**: closed_positions add tp_price/sl_price + backfill from pre_trade_log via calc_id. Optionally trade_history add total_funding_fees/slippage_exit (verify existence first). Optionally fills add exec_link_confirmed fields (only if pursuing user-confirmable links). | 100-150 |
| 70 | **Page restructure**: rewrite history.html into 3 cards + 2 tab switchers (`histMainTab`, `histLogTab`). Wire existing fragments. Delete `execution_table.html`, `live_trades_table.html`, dead `update_live_trade` code path. | 200 |
| 71 | **Column additions** to existing tables: Open Positions (Fees/Net/MFE/MAE/TP/SL); Position History (PnL%, Exit Reason badge, TP, SL); Trade History (Funding, Slip Exit); Pre-Trade Log (Model). Verify trade_history fields with audit step. | 250 |
| 72 | **Fill Drawer**: chevron expand pattern + `/fragments/history/position_fills` endpoint + template. Warning icon on positions with unresolved exec links (server-side `has_unresolved_exec_links` boolean). | 200 |
| 73 | **Trade Events Log** (Card 3 Tab 2): new fragment + endpoint reading from existing `trade_event_log`. Pagination, filtering, event-type badge styling, detail expansion. | 200 |
| 74 | **Exec Link feature** (repurposed against pre_trade_log): `compute_exec_match()` function + `/fragments/history/exec_link` endpoint + `/history/exec_link/confirm` POST + template. Add `EXEC_LINK_PRICE_TOL` config. | 300 |

Total: ~1100-1300 LOC across 6 tasks.

---

## Open Decisions for Implementation Phase

1. **fills.exec_link_confirmed columns**: include in Task 69 schema migration, OR defer until Task 74 confirms they're needed for the UX? Recommend: defer to Task 74 to keep Task 69 minimal.

2. **Backfill of `closed_positions.tp_price/sl_price`**: how aggressive? Recommend: one-shot UPDATE in migration for rows with non-null calc_id; pre-v2.4 rows stay NULL (display "—").

3. **Detail expansion in Trade Events Log**: per-event-type renderers, or single generic JSON pretty-printer? Recommend: generic JSON for v1, per-type renderers as polish later.

4. **Exec link "Search Other" button**: keep or drop? README had it; not clear it's useful when matching is by `calc_id` (no alternative pre_trade_log entry to find). Recommend: drop. Replace with link to admin override path if mismatch is real.

5. **What happens when a fill has no `calc_id`?** (legacy fills, manually-placed orders.) Exec link badge shows UNLINKED. No further action available. Confirm acceptable.

---

## References

- Predecessor audit: `docs/audits/2026-05-15-history-redesign-data-audit.md`
- Original design README: (shared by user, kept for visual reference)
- Original JSX prototype: (shared, design reference only — do not ship)
- Existing fragment patterns: `templates/fragments/dashboard_positions.html` (Tasks 41-52 reference for HTMX/morph/SSE patterns)
