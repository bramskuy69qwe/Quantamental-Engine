# Meridian v3.0 — Design Guidelines

> **Reference implementation:** `Meridian v3.0.html`
> **Stack:** React 18 (UMD + in-browser Babel), inline-style primitives, one global CSS-variable token sheet.
> **Tokens:** `v25/tokens.css` · **Primitives:** `v25/src/primitives.jsx` · **Charts:** ECharts (`v25/src/charts.jsx`)

The app loads as a flat set of `<script type="text/babel">` modules (no bundler). Each module ends with `Object.assign(window, {…})` to share components across files. Load order matters — it is fixed in the HTML: `primitives → charts → grid-workspace → nav-and-data → notifications → dash-tiled → pages → pages-analytics-exec → pages-regime → pages-models-mc-es → pages-models-data → pages-models-lib → pages-models-overview → pages-models-report → pages-models-detail → pages-models → link-data → link-primitives → linkage → app-shell`. (The `dash-tape` / `dash-command` / `dash-split-rail` / `pages-regime-v2` alternates are loaded only by the `v25/index.html` design canvas, not by the app.)

---

## 1. Design Philosophy

**High-contrast terminal.** Pure-black canvas, sharp corners, saturated neon accents. Density over decoration — data is the UI.

- Information hierarchy over visual flair; speed of comprehension over aesthetics
- Zero filler — no decorative elements, no lorem ipsum, no placeholder icons
- Dark only — no light mode
- Sharp edges only — **no `border-radius`** anywhere
- Colorblind safety — never rely on red/green alone; always pair with a label or symbol (`+`/`-`, `LONG`/`SHORT`, `TREND`/`PANIC`)

---

## 2. Color Tokens

All colors are CSS custom properties in `v25/tokens.css`. **Never hardcode hex in the DOM** — always use the variable. (Exception: ECharts option objects render to canvas and cannot read CSS vars; they source resolved hex from `QE_ECHARTS_THEME` in `charts.jsx` — still a single source, never inline literals.)

### Surfaces
| Variable | Value | Usage |
|---|---|---|
| `--qe-bg` | `#000000` | Page background (pure black) |
| `--qe-page` | `#04060a` | Page-header / sticky strip bg |
| `--qe-card` | `#0a0d14` | Card / pane surface |
| `--qe-panel` | `#0e131c` | Input bg, inner panels, button base |
| `--qe-hover` | `#131a26` | Row / control hover |
| `--qe-active` | `#1a2436` | Pressed / selected row |

### Lines & text
| Variable | Value | Usage |
|---|---|---|
| `--qe-line` | `#36486a` | Borders, dividers, table rules |
| `--qe-line-2` | `#46587a` | Stronger border / corner ticks |
| `--qe-line-foc` | `#4a6aa0` | Focus ring |
| `--qe-text` | `#ffffff` | Primary text, numbers |
| `--qe-text-dim` | `#e6eff8` | Slightly dimmed (e.g. hero cents) |
| `--qe-sub` | `#b6c8df` | Column headers, sublabels |
| `--qe-muted` | `#8298b4` | Timestamps, footnotes, neutral regime |
| `--qe-faint` | `#2c3a52` | Gauge tracks, dotted dividers |

### Neon accents (saturated — no pastels)
| Variable | Value | Usage |
|---|---|---|
| `--qe-blue` | `#2a8fff` | Primary button, secondary accent |
| `--qe-cyan` | `#00e7ff` | **Primary accent** — active tabs, focus, selection highlight, choppy regime |
| `--qe-green` | `#00ff7f` | Profit, long, OK, trending regime |
| `--qe-red` | `#ff2d4a` | Loss, short, limit, panic regime |
| `--qe-amber` | `#ffae00` | Warning, defensive regime, taker fee |
| `--qe-magenta` | `#ff2bcf` | Highlight / tertiary |
| `--qe-purple` | `#a87bff` | RVol / extra series |
| `--qe-yellow` | `#ffe600` | Reserved emphasis |

### Semantic wash backgrounds (for badges / tinted panels)
`--qe-bg-green #002816` · `--qe-bg-red #2a0a12` · `--qe-bg-amber #281b00` · `--qe-bg-cyan #001e2a` · `--qe-bg-blue #001a3a` · `--qe-bg-mag #1f0024`

### Semantic rules
- PnL / direction: positive·LONG → `--qe-green`, negative·SHORT → `--qe-red`, flat → `--qe-sub`
- Eligible → green, ineligible/warning → amber, halt/limit/error → red, info → cyan
- Row borders → `--qe-line` (headers) / `--qe-faint` (body rows), never `--qe-muted`

---

## 3. Typography

| Variable | Stack |
|---|---|
| `--qe-mono` | `JetBrains Mono`, `Fira Code`, ui-monospace |
| `--qe-ui` | `Space Grotesk`, `Inter`, ui-sans-serif |

**All numeric data uses `--qe-mono` with `font-variant-numeric: tabular-nums`.** UI chrome (labels, nav, tabs, buttons) uses `--qe-ui`.

### Type scale (CSS vars)
| Variable | Size | Role |
|---|---|---|
| `--qe-fs-xs` | `0.55rem` | meta, badge text, tiny labels |
| `--qe-fs-sm` | `0.6rem` | column headers, section labels |
| `--qe-fs-md` | `0.68rem` | body, table cells, inputs |
| `--qe-fs-lg` | `0.78rem` | primary numbers |
| `--qe-fs-xl` | `0.94rem` | stat values |
| `--qe-fs-2xl` | `1.5rem` | hero number |
| `--qe-fs-3xl` | `2.2rem` | mega number |

`.qe-scope` sets base `font-size: 12px`, `line-height: 1.3`. Labels (`.qe-lbl` / `.qe-sec-lbl`) are uppercase, weight 700, letter-spacing `0.14–0.18em`, color `--qe-sub`.

---

## 4. Spacing & Layout

Spacing scale: `--qe-1 2px` · `--qe-2 4px` · `--qe-3 6px` · `--qe-4 8px` · `--qe-5 10px` · `--qe-6 12px` · `--qe-7 16px` · `--qe-8 20px`.

- **Pane gutter:** `--qe-pane-gap` (`4px`) — THE standard space between workspace tiles **and** from tiles to the workspace edges. `GridWorkspace` owns it: GridStack margin = gap/2 (neighbours sit exactly one gap apart) + wrap padding = gap/2 (edges match that same gap). Never wrap a workspace in an extra padded container and never pass ad-hoc `padding`/`margin` — every page inherits the standard; change the token once to reflow the whole app.

- **Card padding:** `6px 8px` default (`.qe-card`); `4px 6px` tight; `10px 12px` padded (`pad` prop)
- **Button height:** `18px` sm · `22px` base · `28px` lg
- **Input height:** `22px`
- **Pane head:** `20px` (FieldList rows lock to this rhythm); **pane foot:** `16px`
- Every page is wrapped in `.qe-scope` (the styling boundary) and carries a `data-screen-label` for comment context.

---

## 5. Primitives (React components on `window`)

Defined in `v25/src/primitives.jsx`. Use these — do not re-implement their look with inline styles.

### Surfaces & text
- **`Card`** `{tight, pad, hot, ticks}` — the one card. Sharp corners; `hot` = cyan border; `ticks` = terminal corner marks.
- **`Lbl`** / **`SecLbl`** `{count, rule, right}` — micro label / section header with optional count + rule line.
- **`KV`** `{l, v, color, span}` — compact label-over-value cell for detail grids.

### Numbers
- **`Stat`** `{label, value, sub, color}` · **`HeroNumber`** `{value, ccy}` (dims the cents) · **`Delta`** `{value, pct, flat}` (arrow + color).
- **Live numbers:** `LiveValue`, `LiveNumber`, `LivePct`, `LiveClock`, `FlashCell` + the `useLiveTicker` hook — streaming values that flash on change and show a stale indicator.

### Status & badges
- **`StatusDot`** `{tone, label, value, sq}` — the single status indicator (tones: `ok|warn|err|info|off`). Replaces all ad-hoc dots.
- **`Badge`** `{tone, solid}` — tones `ok|warn|err|info|blue|mag|mute`. **`RegimeBadge`** `{tone}` — tones `trend|chop|neut|def|panic`.

### Controls
- **`PeriodSelector`** `{options, value, onChange}` — the one segmented period control.
- **`Switch`**, **`Chip`** `{active, muted, onMute}`, **`StepperInput`** `{step, decimals, min}`, **`LockButton`** `{locked, onToggle}`.
- **`Spinner`** `{size, label, color}` / **`BrailleSquares`** — the engine's ONE loading / busy indicator: the square 2×2 braille spinner (sharp dots, one edge rotating clockwise, centered; `SQUARE_EDGES` via `useSpinFrame`). Use it anywhere a loading/fetching/computing state needs an indicator (boot splash, pane reloads, …) instead of hand-rolling a glyph or "…". This is the single standard — used engine-wide.
- **`RefreshButton`** `{onClick, spinning, tone}` / **`ReloadGlyph`** / **`ReloadIconSVG`** — the one async-reload control. Resting glyph = the circular-arrow `ReloadIconSVG` (viewBox centered on the circle so it sits true); while reloading it shows the braille loading spinner over a darken veil that stops above the `PaneFoot` (last-response line stays lit). `tone='err'` when the pane is errored. Loading is the braille spinner only — no animation or icon alternatives. Don't hand-roll reload affordances.

### Data display
- **`Tabs`** `{tabs:[id,label,count], value, onChange}` — **the only tab primitive.** Renders `.qe-tabs` (cyan underline on active). Do not hand-roll tab strips.
- **`TabStrip`** `{tabs, value, onChange, right}` — **THE canonical sub-tab navigator bar** wrapping `Tabs`: `--qe-page` bg, `0 4px` padding, 1px bottom rule, hidden-scrollbar overflow (active underline never clips), optional `right` slot for strip-end controls (run selector, `+` button). Every page/section tab row uses it — History, Analytics, Regime, Config, Models ×2. Never compose the bar by hand.
- **`DataList`** `{columns, rows, dense, onClick, selected, summary, tools}` — the canonical table; falls back to `EmptyState` when empty. **Built-in search · click-to-sort headers · auto filters.** Tools turn on automatically for record lists (≥5 rows, or ≥3 rows when a categorical column is present) and operate on the **raw row data**, so they work even when a column renders a badge/JSX. `tools` forces on (`true` / `{search,sort,filter}`) or off (`false`). Per-column hints: `filter:false|true|{label,options}`, `sort:false`, `search:false`, plus `filterVal/sortVal/searchVal` accessors. Categorical filters are auto-derived from low-cardinality, non-numeric columns; `onClick(row, origIndex)` stays stable under sort/filter.
- **`FieldList`** `{rows, cols, dense}` — vertical key→value rows (the table's vertical sibling); rows lock to 20px pane-head rhythm.
- **`Gauge`** `{label, value, max, ticks}` — auto-tones `ok<60 / warn 60–80 / err>80`.
- **`EmptyState`** `{tone, glyph, msg, hint, cta}` — the one empty/placeholder treatment.
- **`Strip`** `{items, dense}` — horizontal label/value strip (exchange info, nav stats).
- **`Banner`**, **`Toast`** — alert surfaces. **`NewsTickerBar`** — scrolling feed.

### Pane (tiling tile)
- **`Pane`** `{title, count, right, hot, tag, foot, onRefresh}` — head (20px) + scrolling body + optional `foot` (mirrors the engine event that last updated it). This is the standard tile placed inside a workspace. **Every pane is independently reloadable:** the head carries a `RefreshButton` that shows the braille loading spinner over a darken veil and remounts the body subtree (re-runs streams/effects). **The reload is itself an engine event, so the foot tracks it:** while reloading the foot shows a busy `reloading…` line (braille glyph), and on completion it advances to a fresh event — new monotonic id, real elapsed ms, `✓ reloaded · resynced from source`. The body is wrapped in a `PaneErrorBoundary`: a child that throws shows a recoverable error state (Reload CTA) instead of blanking the app, the head ↻ turns red, and the foot shows an err line. Title-bar info (`right`, count, tag) sits beside the title; the right edge is the ↻ + `···` controls only.
- **`PageHeader`** `{title, subtitle, left, children}` — the 34px page title bar. **Never repeat the page title inside content** — PageHeader owns it.

---

## 6. Workspace / Tiling (drag · resize)

`v25/src/grid-workspace.jsx` wraps GridStack into a reusable shell. **Every workspace page composes the same two components:**

```jsx
<GridWorkspace>
  <GridItem x={0} y={0} w={16} h={24} minW={8} minH={6}>
    <Pane title="…" style={{height:'100%'}}> … </Pane>
  </GridItem>
  …
</GridWorkspace>
```

- 24-column grid. Drag a tile by its **pane head**; resize from any **edge/corner**.
- **Gutter:** tile-to-tile gap AND workspace edge inset are both `--qe-pane-gap` (4px), applied by `GridWorkspace` itself — pages must not add padding around a workspace (see §4).
- A **`LockButton`** in the top nav freezes/unfreezes drag+resize across all workspaces (`useWorkspaceLock`).
- Layouts persist per workspace via `qeWorkspaceSave` / `qeWorkspaceLoad` / `qeWorkspaceReset` (localStorage); **⤓ Save / ⤒ Load / +** live in the `WorkspaceBar`.
- Multi-tab pages (e.g. Regime) wrap **each tab's** panes in their own `GridWorkspace` so every tab is independently tileable.

---

## 7. Charts (ECharts)

`v25/src/charts.jsx` exports `QE_ECHARTS_THEME` (the resolved token→hex map for canvas) plus `CandlestickChart`, `EquityChart`, `Sparkline`, `BarChart`.

- Transparent background, no toolbar, animations off, grid lines in `--qe-line` territory.
- Candles: up `--qe-green`, down `--qe-red`. Equity: area in green. Regime timeline colors come from `QE_ECHARTS_THEME` keyed by regime — never hardcoded.
- Keep chart containers sharp (`.qe-chart`, no rounding).

---

## 8. Regime Color Map

| Key | Badge class | Accent | Label |
|---|---|---|---|
| `risk_on_trending` | `.qe-rg-trend` | `--qe-green` | `TREND` |
| `risk_on_choppy` | `.qe-rg-chop` | `--qe-cyan` | `CHOP` |
| `neutral` | `.qe-rg-neut` | `--qe-sub` | `NEUT` |
| `risk_off_defensive` | `.qe-rg-def` | `--qe-amber` | `DEF` |
| `risk_off_panic` | `.qe-rg-panic` | `--qe-red` | `PANIC` |

Use `RegimeBadge` for badges. For ECharts series, derive hex from `QE_ECHARTS_THEME` (the `REGIME_HEX` map in `pages-regime.jsx` is built from it — one source of truth).

---

## 9. Pages & Navigation

`NAV_ITEMS` (in `nav-and-data.jsx`) drives the top nav; `QE_PAGES` (in `app-shell.jsx`) maps names → page components: `Dashboard (DashTiled)`, `Pre-Trade (CalculatorPage)`, `Linkage (DashLinkA)`, `History`, `Analytics`, `Models`, `Regime`, `Config`, `Primitives`. Each page renders `TopNavStd` → `PageHeader` → workspace/content → `StatusFooter`.

---

## 10. Do's and Don'ts

| ✅ Do | ❌ Don't |
|---|---|
| Use `--qe-*` variables for every DOM color | Hardcode hex in the DOM |
| Source chart hex from `QE_ECHARTS_THEME` | Re-type regime/series hex inline |
| Use `--qe-mono` + tabular-nums for all numbers | Use UI/system fonts for numbers |
| Compose pages from the primitives in §5 | Re-implement a card/tab/badge with inline styles |
| Use the single `Tabs` primitive | Hand-roll a tab strip |
| Put tileable panes in `GridWorkspace`/`GridItem` | Lay panes out in a fixed CSS grid |
| Let `GridWorkspace` own the pane gutter (`--qe-pane-gap`) | Wrap a workspace in a padded container or hardcode tile margins |
| Keep corners sharp | Add `border-radius` |
| Let `PageHeader` own the page title | Repeat the title inside content |
| Pair color with a label/symbol | Convey meaning with color alone |
| Use vivid, saturated accents | Use pastels or washed tones |
