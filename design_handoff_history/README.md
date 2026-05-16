# Handoff: History Page — Quantamental Engine v2.1

## Overview

This package documents all changes and new features for the `/history` page of the
Quantamental Engine. The target stack is **FastAPI + Jinja2 + HTMX 1.9.12 + Idiomorph**,
matching the existing codebase exactly.

## About the Design Files

`reference_design.jsx` is a **high-fidelity HTML/React prototype** — a design reference
showing exact intended layout, column sets, colours, badge styles, and interactions.
Do not ship the JSX. Recreate everything in the existing Jinja2/HTMX template system,
following the patterns in `templates/base.html` and the existing fragment files.

## Fidelity

**High-fidelity.** Match colours, typography, spacing, and badge styles exactly from the
prototype. All CSS variables are already defined in `base.html`. New markup should use
the established CSS classes (`td-ts`, `td-symbol`, `td-sub`, `td-bold`, `pos-long`,
`pos-short`, `badge`, `badge-ok`, `badge-limit`, `badge-warning`, `badge-unknown`, etc.).

---

## Page Structure

The history page is restructured into **3 distinct cards** (previously 1 combined card).

```
┌─ Open Positions + Open Orders ─────────────────────────────────────────────┐  ← Card 1 (existing, columns updated)
└────────────────────────────────────────────────────────────────────────────┘
┌─ Toolbar ───────────────────────────────────────────────────────────────────┐  ← unchanged
└────────────────────────────────────────────────────────────────────────────┘
┌─ Position History │ Order History │ Trade History │ Live Trades ────────────┐  ← Card 2 (tabbed)
└────────────────────────────────────────────────────────────────────────────┘
┌─ Pre-Trade Log │ Execution Log ─────────────────────────────────────────────┐  ← Card 3 (tabbed)
└────────────────────────────────────────────────────────────────────────────┘
```

In `templates/history.html`, replace the existing single tabbed card (which held
Position History / Order History / Trade History) with the structure above.

### Tab switcher JS for Card 2 + Card 3

Follow the identical pattern already used for `htTab()` in `history.html`, creating
two independent switchers:

```js
// Card 2: main history tabs
(function(){
  var _t = window._histMainTab || 'positions';
  var tabs = ['positions','orders','trades','live'];
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
  var tabs = ['pretrade','executions'];
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

---

## Card 1 — Open Positions + Open Orders

**Fragment:** `templates/fragments/history/open_positions.html`  
**Endpoint:** `/fragments/history/open_positions` — `hx-trigger="load, every 1s"`  
**No new endpoint needed — update the existing fragment only.**

### Positions sub-tab — updated columns

Add the following columns to the positions table (they are already available on the
`TradePosition` model):

| New col | Source field | Notes |
|---|---|---|
| `Fees` | `individual_fees` | colour `var(--sub)` |
| `Net` | `individual_unrealized - individual_fees` | green/red bold |
| `MFE` | `session_mfe` | colour `var(--green)` |
| `MAE` | `session_mae` | colour `var(--red)` |
| `TP`  | `individual_tp_price` | colour `var(--green)`, `fmt(v,4)` |
| `SL`  | `individual_sl_price` | colour `var(--red)`, `fmt(v,4)` |

Full column order: Symbol · Dir · Hold · Entry · Mark · Size · Notional · uPnL ·
**Fees** · **Net** · **MFE** · **MAE** · **TP** · **SL**

---

## Card 2 — Tab 1: Position History  (MAJOR CHANGES)

**Fragment:** `templates/fragments/history/closed_positions_table.html`  
**Endpoint:** `GET /fragments/history/closed_positions`

### Updated columns

| Column | DB field | Render |
|---|---|---|
| Open | `entry_time_ms` | `ms_to_local()`, class `td-ts` |
| Close | `exit_time_ms` | `ms_to_local()`, class `td-ts` |
| Hold | computed | `hold_h`h |
| Symbol | `symbol` | class `td-symbol` |
| Dir | `direction` | class `pos-long` / `pos-short` |
| Qty | `quantity` | `fmt(v,4)` |
| Notional | `entry_price * quantity` | `fmt(v,2)` |
| PnL | `net_pnl` | green/red bold |
| **PnL %** | `(net_pnl / (entry_price*quantity))*100` | green/red `fmt(v,2)%` — **NEW** |
| **Exit Reason** | `exit_reason` | badge — **NEW** (see below) |
| TP | `tp_price` | colour `var(--green)`, `fmt(v,4)` — **NEW** |
| SL | `sl_price` | colour `var(--red)`, `fmt(v,4)` — **NEW** |
| MFE | `mfe` | `fmt(v,2)` green |
| MAE | `mae` | `fmt(v,2)` red |

> **DB fields to add to `closed_positions`:**  
> `tp_price REAL`, `sl_price REAL`, `exit_reason TEXT`  
> (`exit_reason` values: `tp_hit`, `sl_hit`, `trailing_stop`, `manual`, `liquidation`)

### Exit Reason badge

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

### Row expand — Fill Drawer  (NEW)

Each position row gets a leading chevron cell. Clicking toggles an inline `<tr>`
below it that lazy-loads the fills for that position.

**Add a leading `<th></th>` (width 18px) and `<td>` chevron to every row.**

```html
<!-- thead -->
<th style="width:18px;"></th>

<!-- tbody row -->
<tr class="pos-row" onclick="togglePosRow('{{ r.id }}')" style="cursor:pointer;">
  <td id="chv-{{ r.id }}" class="td-sub"
      style="text-align:center;font-size:.65rem;font-weight:700;">▸</td>
  {# ... all other tds as normal ... #}
</tr>
<tr id="fills-row-{{ r.id }}" style="display:none;">
  <td colspan="15" style="padding:0;">
    <div id="fills-container-{{ r.id }}"
         style="background:#050810;border-top:1px solid var(--border);
                border-bottom:2px solid rgba(60,143,245,.2);
                padding:8px 10px 10px 32px;">
    </div>
  </td>
</tr>
```

> **colspan** = total column count for this table (chevron col + all data cols).

**JS toggle + lazy HTMX load (add to history.html `<script>` block):**

```js
function togglePosRow(posId) {
  var row  = document.getElementById('fills-row-' + posId);
  var chv  = document.getElementById('chv-' + posId);
  var open = row.style.display !== 'none';
  if (open) {
    row.style.display = 'none';
    chv.textContent  = '▸';
    chv.style.color  = 'var(--muted)';
  } else {
    row.style.display = '';
    chv.textContent  = '▾';
    chv.style.color  = 'var(--blue)';
    var box = document.getElementById('fills-container-' + posId);
    if (!box.dataset.loaded) {
      box.innerHTML = '<div class="ghost ghost-row" style="margin:8px 0;"></div>';
      htmx.ajax('GET', '/fragments/history/position_fills?position_id=' + posId, {
        target: '#fills-container-' + posId, swap: 'innerHTML'
      });
      box.dataset.loaded = '1';
    }
  }
}
```

**⚠ Warning icon on symbol cell:** if any entry fill for this position has
`exec_link_status` = `partial` or `unlinked`, render a `⚠` amber glyph next to the
symbol:

```html
<td class="td-symbol">
  {{ r.symbol }}
  {% if r.has_unresolved_exec_links %}
  <span style="color:var(--amber);font-size:.65rem;" title="Exec link needs confirmation">⚠</span>
  {% endif %}
</td>
```

Compute `has_unresolved_exec_links` server-side when building the row queryset.

---

## Card 2 — Tab 1 (sub): Fill Drawer fragment  (NEW)

**New endpoint:** `GET /fragments/history/position_fills`  
**Query param:** `position_id: str`  
**New template:** `templates/fragments/history/position_fills.html`

This fragment renders a mini-table of all fills (entry + exit) for a position.
Only **entry fills** (those with `tp_price IS NOT NULL`) show an exec link badge.

### Columns

Time · Order No. · Side · Price · Qty · Fee · Role · PnL · **Exec Link**

```html
{% for f in fills %}
<tr>
  <td class="td-ts">{{ ms_to_local(f.timestamp_ms) }}</td>
  <td class="td-dim" style="font-size:.62rem;">#{{ f.exchange_order_id[-6:] if f.exchange_order_id else '—' }}</td>
  <td class="{{ 'pos-long' if f.is_open else 'pos-short' }}" style="font-weight:700;">
    {{ ('Open ' if f.is_open else 'Close ') + f.direction }}
  </td>
  <td>{{ fmt(f.price, 6) }}</td>
  <td>{{ fmt(f.quantity, 4) }}</td>
  <td class="td-sub">{{ fmt(f.fee, 4) }} {{ f.fee_asset }}</td>
  <td class="td-sub">{{ f.role }}</td>
  <td class="{{ 'text-green' if f.realized_pnl and f.realized_pnl > 0 else 'text-red' if f.realized_pnl and f.realized_pnl < 0 else 'td-sub' }}">
    {{ fmt(f.realized_pnl, 2) if f.realized_pnl else '—' }}
  </td>
  <td>
    {% if f.tp_price %}  {# entry fill only #}
    {{ exec_link_badge(f) }}
    <span style="color:var(--muted);font-size:.6rem;cursor:pointer;"
          onclick="toggleExecLink('{{ f.id }}')">
      {{ '▲' if exec_panel_open[f.id] else '▼' }}
    </span>
    {% else %}
    <span class="td-sub">—</span>
    {% endif %}
  </td>
</tr>
{% if f.tp_price %}
<tr id="exec-row-{{ f.id }}" style="display:none;">
  <td colspan="9" style="padding:0 8px 8px 0;">
    <div id="exec-container-{{ f.id }}"></div>
  </td>
</tr>
{% endif %}
{% endfor %}
```

**`exec_link_badge(fill)` Jinja2 macro:**

```html
{% macro exec_link_badge(f) %}
{% if f.exec_link_status == 'linked' %}
  <span class="badge badge-ok" style="cursor:pointer;font-size:.58rem;letter-spacing:.04em;"
        onclick="toggleExecLink('{{ f.id }}')">● LINKED</span>
{% elif f.exec_link_status == 'partial' %}
  <span class="badge badge-warning" style="cursor:pointer;font-size:.58rem;"
        onclick="toggleExecLink('{{ f.id }}')">⚠ {{ f.exec_match_count }}/3</span>
{% else %}
  <span class="badge badge-limit" style="cursor:pointer;font-size:.58rem;"
        onclick="toggleExecLink('{{ f.id }}')">✗ UNLINKED</span>
{% endif %}
{% endmacro %}
```

**JS toggle (add globally or inside the fills fragment's `<script>` tag):**

```js
function toggleExecLink(fillId) {
  var row = document.getElementById('exec-row-' + fillId);
  if (!row) return;
  if (row.style.display === 'none') {
    row.style.display = '';
    var box = document.getElementById('exec-container-' + fillId);
    if (box && !box.dataset.loaded) {
      box.innerHTML = '<div class="ghost ghost-row" style="margin:8px 0;"></div>';
      htmx.ajax('GET', '/fragments/history/exec_link?fill_id=' + fillId, {
        target: '#exec-container-' + fillId, swap: 'innerHTML'
      });
      box.dataset.loaded = '1';
    }
  } else {
    row.style.display = 'none';
  }
}
```

---

## Card 2 — Tab 1 (sub): Execution Link Panel  (NEW)

**New endpoint:** `GET /fragments/history/exec_link`  
**Query param:** `fill_id: str`  
**New template:** `templates/fragments/history/exec_link_panel.html`

### Matching algorithm

**Tolerance:** `abs(a - b) <= max(abs(a), abs(b)) * 0.0005`

Three criteria are checked between an entry fill and an execution log record.
**All three must match for auto-link.** If 1–2 match, the user must confirm manually.

```python
PRICE_TOL = 0.0005  # 0.05% relative tolerance

def price_near(a: float, b: float) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(abs(a), abs(b)) * PRICE_TOL

def compute_exec_match(fill: Fill, exec_candidates: list[ExecutionLog]) -> ExecMatchResult | None:
    """
    Returns the best matching ExecutionLog for an entry fill.
    Returns None if the fill has no tp/sl (i.e. it is a close fill).
    """
    if not fill.tp_price and not fill.sl_price:
        return None

    is_market = fill.order_type in ('MARKET', 'STOP_MARKET')

    def score(e: ExecutionLog) -> dict:
        em = True if is_market else price_near(e.entry_price_actual, fill.price)
        tm = price_near(e.tp_price, fill.tp_price) if fill.tp_price else True
        sm = price_near(e.sl_price, fill.sl_price) if fill.sl_price else True
        cnt = sum([em, tm, sm])
        return dict(
            exec_id=e.id, exec=e,
            entry_match=em, tp_match=tm, sl_match=sm,
            match_count=cnt, auto_link=cnt == 3,
            is_market=is_market,
        )

    # If fill already has a linked exec record, score it directly
    if fill.exec_log_id:
        linked = next((e for e in exec_candidates if e.id == fill.exec_log_id), None)
        if linked:
            result = score(linked)
            result['pre_confirmed'] = (
                fill.exec_link_confirmed or result['auto_link']
            )
            return result

    # Otherwise find best candidate with same ticker + account
    candidates = [e for e in exec_candidates if e.ticker == fill.ticker]
    if not candidates:
        return None
    best = max([score(e) for e in candidates], key=lambda x: x['match_count'])
    best['pre_confirmed'] = False
    return best
```

### Template: `exec_link_panel.html`

```html
{% set m = match %}
{% if not m or not m.exec %}
<div style="background:var(--panel);border:1px solid var(--border);border-radius:4px;
            padding:10px 14px;display:flex;align-items:center;justify-content:space-between;">
  <span class="td-sub">No execution log candidate found for <b>{{ fill.ticker }}</b></span>
</div>
{% else %}
{% set resolved = m.auto_link or m.pre_confirmed %}
<div style="background:#0a0f1a;
            border:1px solid {{ 'rgba(0,200,85,.27)' if resolved else 'rgba(232,144,32,.27)' }};
            border-radius:4px;padding:10px 14px;">

  {# Header #}
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
    <div style="display:flex;align-items:center;gap:10px;">
      <span class="lbl">Execution Log Link</span>
      <span class="td-dim font-mono">{{ m.exec.id }}</span>
      <span class="td-dim" style="font-size:.62rem;">{{ m.exec.entry_timestamp[:19] }}</span>
    </div>
    {% if resolved %}
    <span class="badge badge-ok" style="font-size:.58rem;letter-spacing:.05em;">
      {{ '● AUTO-LINKED' if m.auto_link else '✓ CONFIRMED' }}
    </span>
    {% else %}
    <span class="badge badge-warning" style="font-size:.58rem;">⚠ {{ m.match_count }}/3 MATCH</span>
    {% endif %}
  </div>

  {# Criteria comparison table #}
  <table style="width:100%;border-collapse:collapse;margin-bottom:10px;">
    <thead><tr>
      <th style="color:var(--muted);font-size:.57rem;font-weight:700;letter-spacing:.07em;
                 text-transform:uppercase;padding:4px 10px;border-bottom:1px solid var(--border);
                 text-align:left;">Criterion</th>
      <th style="color:var(--muted);font-size:.57rem;font-weight:700;letter-spacing:.07em;
                 text-transform:uppercase;padding:4px 10px;border-bottom:1px solid var(--border);
                 text-align:left;">Fill Trade</th>
      <th style="color:var(--muted);font-size:.57rem;font-weight:700;letter-spacing:.07em;
                 text-transform:uppercase;padding:4px 10px;border-bottom:1px solid var(--border);
                 text-align:left;">Exec Log</th>
      <th style="width:32px;border-bottom:1px solid var(--border);"></th>
    </tr></thead>
    <tbody>

      {# Row 1: Entry Price #}
      <tr>
        <td class="td-sub" style="padding:6px 10px;border-bottom:1px solid var(--border);">Entry Price</td>
        <td class="font-mono" style="padding:6px 10px;border-bottom:1px solid var(--border);
            color:{{ 'var(--muted)' if m.is_market else 'var(--text)' }};
            font-style:{{ 'italic' if m.is_market else 'normal' }};">
          {{ 'MARKET ORDER' if m.is_market else fmt(fill.price, 6) }}
        </td>
        <td class="font-mono" style="padding:6px 10px;border-bottom:1px solid var(--border);
            color:{{ 'var(--muted)' if m.is_market else ('var(--text)' if m.entry_match else 'var(--red)') }};
            font-style:{{ 'italic' if m.is_market else 'normal' }};">
          {{ fmt(m.exec.entry_price_actual, 6) }}
          {% if not m.entry_match and not m.is_market %}
          <span style="margin-left:6px;font-size:.62rem;font-weight:700;color:var(--red);">≠</span>
          {% endif %}
        </td>
        <td style="padding:6px 10px;border-bottom:1px solid var(--border);text-align:center;">
          {% if m.is_market %}<span class="td-dim" style="font-size:.6rem;font-style:italic;">skip</span>
          {% elif m.entry_match %}<span style="color:var(--green);font-size:.8rem;">✓</span>
          {% else %}<span style="color:var(--red);font-size:.8rem;">✗</span>{% endif %}
        </td>
      </tr>

      {# Row 2: Take Profit #}
      <tr>
        <td class="td-sub" style="padding:6px 10px;border-bottom:1px solid var(--border);">Take Profit</td>
        <td class="font-mono" style="padding:6px 10px;border-bottom:1px solid var(--border);">
          {{ fmt(fill.tp_price, 6) if fill.tp_price else '—' }}
        </td>
        <td class="font-mono" style="padding:6px 10px;border-bottom:1px solid var(--border);
            color:{{ 'var(--text)' if m.tp_match else 'var(--red)' }};">
          {{ fmt(m.exec.tp_price, 6) if m.exec.tp_price else '—' }}
          {% if not m.tp_match %}
          <span style="margin-left:6px;font-size:.62rem;font-weight:700;color:var(--red);">≠</span>
          {% endif %}
        </td>
        <td style="padding:6px 10px;border-bottom:1px solid var(--border);text-align:center;">
          {% if m.tp_match %}<span style="color:var(--green);font-size:.8rem;">✓</span>
          {% else %}<span style="color:var(--red);font-size:.8rem;">✗</span>{% endif %}
        </td>
      </tr>

      {# Row 3: Stop Loss #}
      <tr>
        <td class="td-sub" style="padding:6px 10px;border-bottom:1px solid var(--border);">Stop Loss</td>
        <td class="font-mono" style="padding:6px 10px;border-bottom:1px solid var(--border);">
          {{ fmt(fill.sl_price, 6) if fill.sl_price else '—' }}
        </td>
        <td class="font-mono" style="padding:6px 10px;border-bottom:1px solid var(--border);
            color:{{ 'var(--text)' if m.sl_match else 'var(--red)' }};">
          {{ fmt(m.exec.sl_price, 6) if m.exec.sl_price else '—' }}
          {% if not m.sl_match %}
          <span style="margin-left:6px;font-size:.62rem;font-weight:700;color:var(--red);">≠</span>
          {% endif %}
        </td>
        <td style="padding:6px 10px;border-bottom:1px solid var(--border);text-align:center;">
          {% if m.sl_match %}<span style="color:var(--green);font-size:.8rem;">✓</span>
          {% else %}<span style="color:var(--red);font-size:.8rem;">✗</span>{% endif %}
        </td>
      </tr>

    </tbody>
  </table>

  {# Action buttons — only shown for partial matches not yet confirmed #}
  {% if not resolved %}
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">
    <button class="btn btn-success btn-sm"
            hx-post="/history/exec_link/confirm"
            hx-vals='{"fill_id":"{{ fill.id }}","exec_id":"{{ m.exec.id }}"}'
            hx-target="#exec-container-{{ fill.id }}"
            hx-swap="innerHTML">
      Confirm Link
    </button>
    <button class="btn btn-ghost btn-sm"
            onclick="reloadExecLink('{{ fill.id }}')">
      Search Other
    </button>
    <span class="td-dim" style="font-size:.62rem;">
      {{ 3 - m.match_count }} criterion{{ 'a' if (3 - m.match_count) != 1 else 'ion' }} differ
      — review values above before confirming
    </span>
  </div>
  {% endif %}

  {# Execution log detail strip #}
  <div style="display:flex;gap:20px;flex-wrap:wrap;padding-top:8px;border-top:1px solid var(--border);">
    <div>
      <div class="lbl" style="margin-bottom:1px;">Order Type</div>
      <div class="td-sub font-mono">{{ m.exec.order_type }}</div>
    </div>
    <div>
      <div class="lbl" style="margin-bottom:1px;">Size Filled</div>
      <div class="td-sub font-mono">{{ fmt(m.exec.size_filled, 4) }}</div>
    </div>
    <div>
      <div class="lbl" style="margin-bottom:1px;">Slippage</div>
      <div class="td-sub font-mono">{{ fmt(m.exec.slippage * 100, 3) }}%</div>
    </div>
    <div>
      <div class="lbl" style="margin-bottom:1px;">Maker Fee</div>
      <div class="td-sub font-mono">{{ fmt(m.exec.maker_fee * 100, 2) }}%</div>
    </div>
    <div>
      <div class="lbl" style="margin-bottom:1px;">Latency</div>
      <div class="td-sub font-mono">{{ fmt(m.exec.latency_snapshot, 1) }} ms</div>
    </div>
  </div>

</div>
{% endif %}
```

### New POST endpoint: Confirm Link

```python
@router.post("/history/exec_link/confirm")
async def confirm_exec_link(
    fill_id: str = Form(...),
    exec_id:  str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Persist a manually confirmed execution log link for a fill.
    Returns the updated exec_link_panel fragment.
    """
    fill = await db.get(Fill, fill_id)
    exec_entry = await db.get(ExecutionLog, exec_id)

    fill.exec_log_id            = exec_id
    fill.exec_link_confirmed    = True
    fill.exec_link_confirmed_at = datetime.utcnow()
    fill.exec_link_confirmed_by = 'user'
    await db.commit()

    match = compute_exec_match(fill, [exec_entry])
    match['pre_confirmed'] = True

    return templates.TemplateResponse(
        "fragments/history/exec_link_panel.html",
        {"request": request, "fill": fill, "match": match},
    )
```

---

## Card 2 — Tab 2: Order History

**Fragment:** `templates/fragments/history/order_history_table.html`  
**No schema changes.** Minor update: use `td-ts`, `td-symbol`, `td-sub`, `td-dim`
CSS classes instead of inline styles where not already done. Already complete.

---

## Card 2 — Tab 3: Trade History (updated format)

**Fragment:** `templates/fragments/history/trade_history_table.html`  
**Endpoint:** `GET /fragments/history/trade_history`

This table shows **round-trip closed trades** (one row per position entry+exit pair),
not individual fills. Already exists but add the following columns:

| Column | DB field | Notes |
|---|---|---|
| Exit Time | `exit_timestamp` | `[:19]`, class `td-ts` |
| Ticker | `ticker` | class `td-symbol` |
| Dir | `direction` | `pos-long` / `pos-short` |
| Entry | `entry_price` | `fmt(v,4)` |
| Exit | `exit_price` | `fmt(v,4)` |
| Realized | `individual_realized` | green/red bold |
| **R** | `individual_realized_r` | `fmt(v,2)R`, class `td-sub` |
| **Funding** | `total_funding_fees` | `fmt(v,4)`, class `td-sub` — **NEW** |
| Fees | `total_fees` | `fmt(v,4)`, class `td-sub` |
| **Slip Exit** | `slippage_exit * 100` | `fmt(v,4)%`, class `td-sub` — **NEW** |
| Hold Time | `holding_time` | class `td-sub` |
| Notes | `notes` | inline editable via `editNote()` |

> **DB fields to add to `trade_history`:**  
> `total_funding_fees REAL DEFAULT 0`, `slippage_exit REAL DEFAULT 0`

---

## Card 2 — Tab 4: Live Trades  (NEW)

**New endpoint:** `GET /fragments/history/live_trades`  
**New template:** `templates/fragments/history/live_trades_table.html`  
**Trigger:** `hx-trigger="load, every 5s"`

### Columns

Ticker · Dir · Entry Time · Max Profit · Max Loss · Hold Time · Stop Adj.

```html
{% for r in rows %}
<tr>
  <td class="td-symbol">{{ r.ticker }}</td>
  <td class="{{ 'pos-long' if r.direction == 'LONG' else 'pos-short' }}">{{ r.direction }}</td>
  <td class="td-ts">{{ r.entry_timestamp[:19] if r.entry_timestamp else '—' }}</td>
  <td class="text-green">{{ fmt(r.max_profit) }}</td>
  <td class="text-red">{{ fmt(r.max_loss) }}</td>
  <td class="td-sub">{{ r.hold_time }}</td>
  <td class="td-sub">{{ r.stop_adjustments }}</td>
</tr>
{% endfor %}
```

> **New `live_trades` table (or view):**  
> `id`, `account_id`, `ticker TEXT`, `direction TEXT`, `entry_timestamp TEXT`,  
> `max_profit REAL`, `max_loss REAL`, `stop_adjustments INT DEFAULT 0`  
> Populated by the trade management loop whenever a stop is moved or a new high/low is reached.

---

## Card 3 — Tab 1: Pre-Trade Log (updated)

**Fragment:** `templates/fragments/history/pre_trade_table.html`  
**One new column:** `Model`

Add after `Eligible`:

```html
{{ sort_th("Model", "model_name", ep, tid, sort_by, sort_dir, qs) }}
```

Row cell:

```html
<td class="td-sub">{{ r.model_name or '—' }}</td>
```

> **DB field to add to `pre_trade_log`:** `model_name TEXT DEFAULT NULL`  
> Populated from the strategy/model that generated the signal.

---

## Card 3 — Tab 2: Execution Log

**Fragment:** `templates/fragments/history/execution_table.html`  
**No changes to columns.** The exec link feature is accessed via the Fill Drawer
(Card 2 drill-down), not directly from this table.

---

## DB Schema Summary

```sql
-- closed_positions (add)
ALTER TABLE closed_positions ADD COLUMN tp_price       REAL;
ALTER TABLE closed_positions ADD COLUMN sl_price       REAL;
ALTER TABLE closed_positions ADD COLUMN exit_reason    TEXT;  -- 'tp_hit'|'sl_hit'|'trailing_stop'|'manual'|'liquidation'

-- fills (add)
ALTER TABLE fills ADD COLUMN exec_log_id              TEXT REFERENCES execution_log(id);
ALTER TABLE fills ADD COLUMN exec_link_confirmed      INTEGER DEFAULT 0;
ALTER TABLE fills ADD COLUMN exec_link_confirmed_at   TEXT;
ALTER TABLE fills ADD COLUMN exec_link_confirmed_by   TEXT;  -- 'auto' | 'user'

-- trade_history (add)
ALTER TABLE trade_history ADD COLUMN total_funding_fees REAL DEFAULT 0;
ALTER TABLE trade_history ADD COLUMN slippage_exit      REAL DEFAULT 0;

-- pre_trade_log (add)
ALTER TABLE pre_trade_log ADD COLUMN model_name TEXT;

-- live_trades (new table)
CREATE TABLE IF NOT EXISTS live_trades (
    id               TEXT PRIMARY KEY,
    account_id       TEXT NOT NULL,
    ticker           TEXT NOT NULL,
    direction        TEXT NOT NULL,
    entry_timestamp  TEXT,
    max_profit       REAL DEFAULT 0,
    max_loss         REAL DEFAULT 0,
    stop_adjustments INTEGER DEFAULT 0
);

-- execution_log — ensure these columns exist (may already):
-- tp_price REAL, sl_price REAL, order_type TEXT
```

---

## New Endpoints Summary

| Method | Path | Template | Notes |
|---|---|---|---|
| GET | `/fragments/history/position_fills` | `position_fills.html` | `?position_id=X` |
| GET | `/fragments/history/exec_link` | `exec_link_panel.html` | `?fill_id=X` |
| POST | `/history/exec_link/confirm` | `exec_link_panel.html` | form: `fill_id`, `exec_id` |
| GET | `/fragments/history/live_trades` | `live_trades_table.html` | standard pagination |

---

## Matching Logic — Quick Reference

```
For an entry fill F and exec log candidate E:

is_market   = F.order_type in ('MARKET', 'STOP_MARKET')
entry_match = True  if is_market  else  |E.entry_price_actual - F.price| ≤ max(|E|,|F|) × 0.0005
tp_match    = |E.tp_price - F.tp_price| ≤ max(|E|,|F|) × 0.0005   (if F.tp_price exists)
sl_match    = |E.sl_price - F.sl_price| ≤ max(|E|,|F|) × 0.0005   (if F.sl_price exists)

match_count = entry_match + tp_match + sl_match   (0–3)

match_count == 3  →  AUTO-LINKED    (badge: ● LINKED, green)
match_count == 2  →  PARTIAL        (badge: ⚠ 2/3, amber) — user must confirm
match_count == 1  →  PARTIAL        (badge: ⚠ 1/3, amber) — user must confirm
match_count == 0  →  UNLINKED       (badge: ✗ UNLINKED, red)
```

---

## CSS / Design Tokens

All tokens are CSS variables already declared in `base.html`:

```
--blue   : #3c8ff5     (links, active tabs, chevrons)
--green  : #00c855     (long, profit, TP, linked)
--red    : #e83535     (short, loss, SL, unlinked)
--amber  : #e89020     (warnings, partial match, ⚠)
--sub    : #96b4d0     (secondary text)
--muted  : #526a88     (dimmed text)
--border : #18253a     (table borders, card borders)
--panel  : #101826     (input background)
--hover  : #141f2e     (row hover background)
```

Exec link panel backgrounds (inline, not in base.html):
```
auto-linked border : rgba(0, 200, 85, 0.27)   →  rgba(0,200,85,.27)
partial border     : rgba(232, 144, 32, 0.27)  →  rgba(232,144,32,.27)
panel background   : #0a0f1a
```

---

## Files

| File | Purpose |
|---|---|
| `reference_design.jsx` | High-fidelity React prototype (design reference only) |
| `templates/history.html` | Main page — restructure to 3 cards |
| `templates/fragments/history/closed_positions_table.html` | Add PnL%, Exit Reason, chevron rows, fill drawer rows |
| `templates/fragments/history/position_fills.html` | **NEW** — fill drawer fragment |
| `templates/fragments/history/exec_link_panel.html` | **NEW** — execution link comparison panel |
| `templates/fragments/history/trade_history_table.html` | Add Funding, Slip Exit columns |
| `templates/fragments/history/live_trades_table.html` | **NEW** — live trades table |
| `templates/fragments/history/pre_trade_table.html` | Add Model column |
| `templates/fragments/history/open_positions.html` | Add Fees, Net, MFE, MAE, TP, SL columns |
