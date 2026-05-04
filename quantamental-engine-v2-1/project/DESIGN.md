# Quantamental Engine v2.1 — Design Guidelines

> Reference implementation: `Quantamental Engine.html` (React prototype)  
> Production stack: FastAPI + Jinja2 + HTMX — templates in `templates/`

---

## 1. Design Philosophy

**Terminal Precision.** Every pixel earns its place. Density over decoration. Data is the UI.

- Information hierarchy over visual flair
- Speed of comprehension over aesthetics
- Zero filler content — no decorative elements, no lorem ipsum, no placeholder icons
- Dark theme only — no light mode

---

## 2. Color Tokens

All colors are defined as CSS custom properties in `base.html`. **Never hardcode hex values** — always use the variable.

| Variable       | Value     | Usage                                      |
|----------------|-----------|--------------------------------------------|
| `--bg`         | `#07080f` | Page background                            |
| `--card`       | `#0c1118` | Card / panel surface                       |
| `--panel`      | `#101826` | Input backgrounds, inner panels            |
| `--hover`      | `#141f2e` | Row hover state                            |
| `--border`     | `#18253a` | All borders, row dividers, separators      |
| `--bfoc`       | `#2a4568` | Focus ring on inputs                       |
| `--text`       | `#e8f2ff` | Primary text — numbers, labels, headings   |
| `--sub`        | `#96b4d0` | Secondary text — column headers, sublabels |
| `--muted`      | `#526a88` | De-emphasised — timestamps, footnotes      |
| `--blue`       | `#3c8ff5` | Primary accent — active states, CTAs       |
| `--green`      | `#00c855` | Profit, long, OK, success                  |
| `--red`        | `#e83535` | Loss, short, limit, error                  |
| `--amber`      | `#e89020` | Warning, defensive regime, taker fee       |
| `--cyan`       | `#00b4d8` | Risk-on choppy regime, secondary accent    |
| `--purple`     | `#9b6ef5` | RVol signal                                |

### Semantic color rules
- **PnL positive** → `--green`, **PnL negative** → `--red`
- **LONG** direction → `--green`, **SHORT** → `--red`
- **Eligible** → `--green`, **Ineligible** → `--amber`
- **Hard stop / LIMIT** → `--red` badge, **Warning** → `--amber`, **OK** → `--green`
- **Row borders** → always `--border`, never `--muted`

### Colorblind-safe
- Never rely on red/green alone — always pair with a label or symbol (`+`/`-`, `LONG`/`SHORT`)
- Avoid pastels entirely — all accent colors are vivid and saturated

---

## 3. Typography

| Role              | Font                            | Size       | Weight |
|-------------------|---------------------------------|------------|--------|
| UI labels, nav    | `Space Grotesk`                 | varies     | 500–800 |
| Numbers, prices   | `JetBrains Mono`                | varies     | 600–700 |
| Section labels    | `Space Grotesk`, all-caps       | `0.6rem`   | 700    |
| Column headers    | `Space Grotesk`, all-caps       | `0.6rem`   | 700    |
| Body table cells  | `JetBrains Mono`                | `0.72rem`  | 400    |
| Stat values       | `JetBrains Mono`                | `0.92rem`  | 700    |
| Hero equity value | `JetBrains Mono`                | `2rem`     | 700    |

**Root font-size:** `107%` (set on `<html>`) — all `rem` sizes scale from this.

**Rules:**
- All numeric data (prices, PnL, sizes, percentages) must use `JetBrains Mono`
- Section labels: `0.6rem`, `700`, `letter-spacing: 0.1em`, `text-transform: uppercase`, color `--sub`
- Column headers: same as section labels
- Never use system fonts (Arial, sans-serif, etc.)

---

## 4. Spacing & Layout

- **Page padding:** `8px` on all sides
- **Gap between cards:** `6px`
- **Card padding:** `10px 12px` (default), `8px 10px` (compact variant `.card-p8`)
- **Input height:** `30px`
- **Button heights:** `sm=24px`, `md=28px`, `lg=34px`

### Grid patterns
- Use CSS `grid` with `repeat(auto-fill, minmax(Xpx, 1fr))` for stat grids — never fixed column counts that break at narrow widths
- Dashboard hero: `220px 1fr` (fixed left column, fluid chart)
- Risk row: `1fr 2fr` (risk panel narrower, positions wider)
- Two-column pages (Calculator): `minmax(0,1fr) minmax(0,1fr)`

---

## 5. Components

### Cards
```html
<div class="card">...</div>           <!-- 10px 12px padding -->
<div class="card card-p8">...</div>   <!-- 8px 10px padding, denser -->
```
Always `background: var(--card)`, `border: 1px solid var(--border)`, `border-radius: 5px`.

### Section labels
```html
<span class="sec-lbl">Risk & Exposure</span>
```
Used at the top of every card to name its content. Not used for page titles — the sticky `PageHeader` handles those.

### Stat cells
```html
<div class="stat">
  <span class="lbl">Total Equity</span>
  <div class="val">82.20</div>
  <div class="sub-val">USDT</div>  <!-- optional -->
</div>
```

### Badges
```html
<span class="badge badge-ok">OK</span>
<span class="badge badge-warning">WARNING</span>
<span class="badge badge-limit">LIMIT</span>
<span class="badge badge-unknown">—</span>
```
For regime states use: `regime-trending`, `regime-choppy`, `regime-neutral`, `regime-defensive`, `regime-panic`.

### Buttons
```html
<button class="btn btn-primary btn-md">Calculate</button>
<button class="btn btn-secondary btn-sm">Clear</button>
<button class="btn btn-ghost btn-sm">⧉ Copy</button>
<button class="btn btn-danger btn-sm">Delete</button>
```
Variants: `btn-primary`, `btn-secondary`, `btn-ghost`, `btn-danger`, `btn-success`, `btn-amber`.
Sizes: `btn-sm` (24px), `btn-md` (28px), `btn-lg` (34px).

### Gauge bars
```html
<div class="gauge-track">
  <div class="gauge-fill" style="width: 35%; background: var(--blue);"></div>
</div>
```
Color shifts: `< 60%` → `--blue`, `60–80%` → `--amber`, `> 80%` → `--red`.

### Tables
- `<th>` → `--sub`, `0.6rem`, `700`, all-caps, `border-bottom: 1px solid var(--border)`
- `<td>` → `JetBrains Mono`, `0.72rem`, `border-bottom: 1px solid var(--border)` (**not** `--muted`)
- Row hover: `background: var(--hover)` via `tr:hover td`

### Tab bars
Two variants — set via class on the wrapper:

**Line style** (default, used on Analytics and Regime):
```html
<div class="tabs-line">
  <button class="tab-btn active">Overview</button>
  <button class="tab-btn">Equity Curve</button>
</div>
```

**Pill style:**
```html
<div class="tabs-pill">
  <button class="tab-btn active">Overview</button>
</div>
```

### Alerts
```html
<div class="alert alert-error">⛔ Trading HALTED — hard stop active.</div>
<div class="alert alert-warning">⚠ Weekly loss approaching limit.</div>
<div class="alert alert-success">✓ Parameters saved.</div>
```

---

## 6. Page Structure

Every page follows this DOM order:

```
<header>          ← sticky top nav (38px, in base.html)
<PageHeader>      ← sticky page title bar (below nav, ~32px)
<main>
  <div style="padding:8px;">
    <div style="display:flex;flex-direction:column;gap:6px;">
      <!-- page content as stacked cards -->
    </div>
  </div>
</main>
<footer>
```

**PageHeader** is rendered by `App` in `qe-app.jsx` and sticks at `top: 50px` (below the 50px nav). It shows the page name (`JetBrains Mono`, `0.82rem`, `700`) and a short descriptor (`0.62rem`, `--muted`). **Do not add a title inside the page content** — the PageHeader is the only title.

---

## 7. HTMX Patterns

- **Polling fragments** use `hx-trigger="load, every Ns"` — dashboard fragments poll at 500ms (exchange), 2s (equity/risk), 30s (stats)
- **User-triggered** actions use `hx-trigger="change"` or form submit
- Always show a loading skeleton (not a blank div) as the initial content before HTMX swaps in
- Use `hx-indicator` for spinner visibility — class `.htmx-indicator` handles opacity transition
- Fragment URLs follow: `/fragments/{page}/{section}` (e.g. `/fragments/dashboard/top`)

---

## 8. Charts (ApexCharts)

All charts use ApexCharts. Standard config:

```js
{
  chart: { background: 'transparent', toolbar: { show: false }, animations: { enabled: false } },
  grid: { borderColor: '#18253a', strokeDashArray: 2 },
  tooltip: { theme: 'dark' },
  xaxis: { labels: { style: { colors: '#526a88', fontSize: '8px' } } },
  yaxis: { labels: { style: { colors: '#526a88', fontSize: '9px' } } },
}
```

- **Equity curve** → `area` chart, color `--green` (`#00c855`)
- **Candlestick** → upward `#00c855`, downward `#e83535`
- **Regime timeline** → rendered as pure SVG (no ApexCharts), see `qe-regime-params.jsx`

---

## 9. Regime Color Map

| Key                   | Background | Text / Fill | Short label |
|-----------------------|------------|-------------|-------------|
| `risk_on_trending`    | `#0a2018`  | `#00c855`   | `TREND`     |
| `risk_on_choppy`      | `#082028`  | `#00b4d8`   | `CHOP`      |
| `neutral`             | `#101826`  | `#96b4d0`   | `NEUT`      |
| `risk_off_defensive`  | `#251500`  | `#e89020`   | `DEF`       |
| `risk_off_panic`      | `#250808`  | `#e83535`   | `PANIC`     |

---

## 10. Do's and Don'ts

| ✅ Do | ❌ Don't |
|-------|---------|
| Use CSS variables for all colors | Hardcode hex values |
| Use `JetBrains Mono` for all numbers | Use system fonts for numbers |
| Use `border: 1px solid var(--border)` for row separators | Use `--muted` for row borders |
| Show loading skeletons before HTMX swap | Show empty blank divs |
| Use `auto-fill` grids for stat rows | Use fixed column counts |
| Keep cards dense — `6px` gap, `8–10px` padding | Add excessive whitespace |
| Pair color with label for colorblind safety | Use color alone to convey meaning |
| Use `badge-ok / badge-warning / badge-limit` for states | Invent new badge colors |
| Use the sticky `PageHeader` for page title | Repeat page title inside card content |
| Use vivid, saturated colors | Use pastel or washed-out tones |
