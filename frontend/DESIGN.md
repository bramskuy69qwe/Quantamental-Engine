# v3.0 UI — Design Guidelines

> **Ported from** the Meridian v3.0 design reference
> (`docs/design/meridian_v3/DESIGN.md`, imported at `5a24c66`). "Meridian" is the
> internal design codename; the shipped product identity is **config-driven**
> (`config.PROJECT_SHORT_NAME` / `PROJECT_VERSION_`), surfaced to the app via
> `window.QE_BOOTSTRAP`. Do not reintroduce the "Meridian" / "QE v2.5" strings in
> shipped UI.
>
> **Stack (v3.0 build model):** React 18 (production UMD) + inline-style
> primitives + one global CSS-variable token sheet. The JSX under
> `frontend/src/` is **precompiled** by `frontend/build.mjs` (esbuild,
> transform-and-concatenate in a fixed load order) into a single content-hashed
> bundle at `static/v3/app.<hash>.js`. Runtime deps (React, ReactDOM, ECharts,
> GridStack, fonts) are **vendored** under `static/vendor/` — no CDN, no
> in-browser Babel, no Node at runtime. FastAPI serves the shell at `/v3`
> (`api/routes_v3.py` → `templates/v3.html`).
>
> **Tokens:** `frontend/src/tokens.css` · **Primitives:**
> `frontend/src/primitives.jsx` · **Charts:** ECharts (`frontend/src/charts.jsx`)

Each module ends with `Object.assign(window, {…})` to share components across
files — the modules are **not** ES modules; they share via `window` globals, so
the **load order is fixed and load-bearing** (see `frontend/build.mjs`
`JSX_ORDER`): `primitives → charts → grid-workspace → nav-and-data →
notifications → sse-adapter → …page modules… → app-shell` (`app-shell` last — it
calls `ReactDOM.createRoot`). Page modules join in their build phases (P1–P7).

---

## 0. Build & serve (v3.0)

- **Author** in `frontend/src/` (JSX + `tokens.css` + `shell.css`).
- **Build**: `npm run build` in `frontend/` → vendors deps to `static/vendor/`,
  precompiles the bundle + hashed CSS to `static/v3/`, writes
  `static/v3/manifest.json` (the hashed asset names the shell reads).
- **Content-hashed filenames** are deliberate: the engine's service worker is
  root-scoped and cache-first on `/static/*`, so a query-string bust is not
  enough — a new build must change the *filename*. `/v3` registers no service
  worker of its own.
- **Bootstrap**: the shell injects `window.QE_BOOTSTRAP` = `{projectName,
  projectShortName, projectVersion, activeAccountId}`. Live data flows over
  **SSE** (`frontend/src/sse-adapter.js`, `window.QE_SSE`) — one `EventSource`
  per active account against `/stream/account/{id}`; **no browser WebSocket.**

---

## 1. Design Philosophy

**High-contrast terminal.** Pure-black canvas, sharp corners, saturated neon
accents. Density over decoration — data is the UI.

- Information hierarchy over visual flair; speed of comprehension over aesthetics
- Zero filler — no decorative elements, no lorem ipsum, no placeholder icons
- Dark only — no light mode
- Sharp edges only — **no `border-radius`** anywhere
  - **Carve-out — circular status dots.** The one exception: the small (5–8px)
    live/severity **status dots** are `border-radius:50%` on purpose (e.g. the
    notification unread dot `notifications.jsx:171`; the `NewsTickerBar` live/dot
    marks `tokens.css:694` / `:719`; the linkage/analytics/models live dots).
    Note the `StatusDot` *primitive* itself is deliberately **square** (a 6×6
    block, `tokens.css .qe-dot::before`). Everything else stays sharp.
- Colorblind safety — never rely on red/green alone; always pair with a label or
  symbol (`+`/`-`, `LONG`/`SHORT`, `TREND`/`PANIC`)

---

## 2. Color Tokens

All colors are CSS custom properties in `frontend/src/tokens.css`. **Never
hardcode hex in the DOM** — always use the variable.

- **Exception (ECharts):** ECharts option objects render to canvas and cannot
  read CSS vars; they source resolved hex from `QE_ECHARTS_THEME` in
  `charts.jsx` — still a single source, never inline literals.
- **Carve-out (rgba alpha-washes):** a handful of translucent tint-washes are
  written as raw `rgba()` because **no token exists for the alpha variant** —
  the canonical case is `PaneFoot`'s tone-background washes
  (`primitives.jsx:571` — `ok/info/warn/err` at 5–6% alpha), plus small darken
  scrims/shadows behind timers/toasts/drawers. This is a documented carve-out
  parallel to the ECharts exception: prefer a `--qe-bg-*` token where one fits;
  use `rgba()` only for the alpha-wash tints that have no token. Do not
  reach for `rgba()` for solid colors that a token already covers.

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
`--qe-bg-green #002816` · `--qe-bg-red #2a0a12` · `--qe-bg-amber #281b00` ·
`--qe-bg-cyan #001e2a` · `--qe-bg-blue #001a3a` · `--qe-bg-mag #1f0024`

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

**All numeric data uses `--qe-mono` with `font-variant-numeric: tabular-nums`.**
UI chrome (labels, nav, tabs, buttons) uses `--qe-ui`. Both families are
**vendored** as local woff2 (`static/vendor/fonts/`, weights 400/500/600/700) —
no Google Fonts CDN.

### Type scale (CSS vars)
`--qe-fs-xs 0.55rem` (meta/badge) · `--qe-fs-sm 0.6rem` (headers/labels) ·
`--qe-fs-md 0.68rem` (body/cells) · `--qe-fs-lg 0.78rem` (primary numbers) ·
`--qe-fs-xl 0.94rem` (stat values) · `--qe-fs-2xl 1.5rem` (hero) ·
`--qe-fs-3xl 2.2rem` (mega). `.qe-scope` sets base `font-size: 12px`,
`line-height: 1.3`. Labels (`.qe-lbl` / `.qe-sec-lbl`) are uppercase, weight 700,
letter-spacing `0.14–0.18em`, color `--qe-sub`.

---

## 4. Spacing & Layout

Spacing scale: `--qe-1 2px` · `--qe-2 4px` · `--qe-3 6px` · `--qe-4 8px` ·
`--qe-5 10px` · `--qe-6 12px` · `--qe-7 16px` · `--qe-8 20px`.

- **Pane gutter:** `--qe-pane-gap` (`4px`) — THE standard space between workspace
  tiles **and** from tiles to the workspace edges. `GridWorkspace` owns it:
  GridStack margin = gap/2 (neighbours sit exactly one gap apart) + wrap padding
  = gap/2 (edges match). Never wrap a workspace in an extra padded container and
  never pass ad-hoc `padding`/`margin`.
- **Card padding:** `6px 8px` default (`.qe-card`); `4px 6px` tight; `10px 12px` padded (`pad` prop)
- **Button height:** `18px` sm · `22px` base · `28px` lg · **Input height:** `22px`
- **Pane head:** `20px` (FieldList rows lock to this rhythm); **pane foot:** `16px`
- Every page is wrapped in `.qe-scope` (the styling boundary) and carries a `data-screen-label`.

---

## 5. Primitives (React components on `window`)

Defined in `frontend/src/primitives.jsx`. Use these — do not re-implement their
look with inline styles.

### Surfaces & text
- **`Card`** `{tight, pad, hot, ticks}` — the one card. `hot` = cyan border; `ticks` = corner marks.
- **`Lbl`** / **`SecLbl`** `{count, rule, right}` — micro label / section header.
- **`KV`** `{l, v, color, span}` — compact label-over-value cell.

### Numbers
- **`Stat`** `{label, value, sub, color}` · **`HeroNumber`** `{value, ccy}` · **`Delta`** `{value, pct, flat}`.
- **Live numbers:** `LiveValue`, `LiveNumber`, `LivePct`, `LiveClock`, `FlashCell` + the `useLiveTicker` hook — streaming values that flash on change and show a stale indicator. Bind them to real data via the SSE adapter (`window.QE_SSE` / `useLiveId`), never a client random-walk.

### Status & badges
- **`StatusDot`** `{tone, label, value, sq}` — the single status indicator (tones `ok|warn|err|info|off`).
- **`Badge`** `{tone, solid}` — tones `ok|warn|err|info|blue|mag|mute`. **`RegimeBadge`** `{tone}` — `trend|chop|neut|def|panic`.

### Controls
- **`PeriodSelector`** `{options, value, onChange}` — the one segmented period control.
- **`Switch`**, **`Chip`** `{active, muted, onMute}`, **`StepperInput`** `{step, decimals, min}`, **`LockButton`** `{locked, onToggle}`.
- **`Spinner`** / **`BrailleSquares`** — the engine's ONE loading indicator (square 2×2 braille). Used engine-wide (boot splash, pane reloads).
- **`RefreshButton`** / **`ReloadGlyph`** / **`ReloadIconSVG`** — the one async-reload control; loading state is the braille spinner over a darken veil that stops above the `PaneFoot`.

### Data display
- **`Tabs`** `{tabs:[id,label,count], value, onChange}` — the only tab primitive (`.qe-tabs`, cyan underline).
- **`TabStrip`** `{tabs, value, onChange, right}` — THE canonical sub-tab navigator bar wrapping `Tabs`.
- **`DataList`** `{columns, rows, dense, onClick, selected, summary, tools}` — the canonical table (built-in search · click-to-sort · auto filters); falls back to `EmptyState` when empty.
- **`FieldList`** `{rows, cols, dense}` — vertical key→value rows (20px pane-head rhythm).
- **`Gauge`** `{label, value, max, ticks}` — auto-tones `ok<60 / warn 60–80 / err>80`.
- **`EmptyState`** `{tone, glyph, msg, hint, cta}` — the one empty/placeholder treatment.
- **`Strip`** `{items, dense}` · **`Banner`**, **`Toast`** · **`NewsTickerBar`**.

### Pane (tiling tile)
- **`Pane`** `{title, count, right, hot, tag, foot, onRefresh}` — head (20px) + scrolling body + optional `foot`. Independently reloadable; body wrapped in `PaneErrorBoundary` (a throwing child shows a recoverable error state, not a blank app).
- **PaneFoot policy (operator-ratified, post-P6 consistency pass): foots
  everywhere, REAL data only.** Every major data pane carries a
  `foot={{tone, msg}}` whose message is truthful and derivable at the call
  site: row/item counts, poll cadence, source attribution, window
  descriptions, real state summaries. **Never pass `id` or `ms`** — the
  design reference's `[00123]` event-ids and `Nms` latency readouts were
  fabricated ornaments (a real telemetry feed may re-introduce them later).
  The ↻ reload's own status line is honest too: `reloaded · refetched` when
  the pane has an `onRefresh` hook, `reloaded · body remounted` when it
  doesn't (a child remount cannot re-run the PARENT's data hooks — never
  claim "resynced" without one). `tone` must reflect real state (`warn`
  only when something is genuinely warning-worthy; guard loading states to
  `loading…` rather than rendering zero-counts). Micro/KPI tiles,
  pure-form panes, and panes whose head/right slot already carries the
  same truthful readout may omit the foot — don't pad with filler.
- **`PageHeader`** `{title, subtitle, left, children}` — the 34px page title bar. **Never repeat the page title inside content.**

---

## 6. Workspace / Tiling (drag · resize)

`frontend/src/grid-workspace.jsx` wraps GridStack into a reusable shell. Every
workspace page composes the same two components:

```jsx
<GridWorkspace persistId="dashboard">
  <GridItem x={0} y={0} w={16} h={24} minW={8} minH={6}>
    <Pane title="…"> … </Pane>
  </GridItem>
  …
</GridWorkspace>
```

- 24-column grid. Drag a tile by its **pane head**; resize from any **edge/corner**. Positions are applied imperatively to `gs-*` (React never manages them, so content re-renders / live tickers never reset the layout).
- **Gutter:** tile-to-tile gap AND workspace edge inset are both `--qe-pane-gap` (4px), applied by `GridWorkspace` — pages must not add padding around a workspace (§4).
- A **`LockButton`** in the top nav freezes/unfreezes drag+resize across all workspaces (`useWorkspaceLock`, persisted).
- Layouts persist per workspace via `qeWorkspaceSave` / `qeWorkspaceLoad` / `qeWorkspaceReset` (localStorage, namespaced by account); **⤓ Save / ⤒ Load / +** live in the `WorkspaceBar` (Dashboard only — disabled elsewhere in the reference).

---

## 7. Charts (ECharts)

`frontend/src/charts.jsx` exports `QE_ECHARTS_THEME` (the resolved token→hex map
for canvas) plus the chart components:

- **ECharts (canvas):** `CandlestickChart`, `EquityChart`, `Sparkline`, `BarChart`.
- **DOM/SVG marks (also exported here):** `RegimeRibbon` (stacked regime-over-time
  segments), `HeatStrip` (calendar-PnL cells), `ScatterChart` (MFE/MAE etc.).
  `RegimeRibbon` renders with token-var backgrounds directly; `HeatStrip` uses
  variable-alpha `rgba()` heat fills (`charts.jsx:236` — a 4th instance of the §2
  rgba-wash carve-out, keyed on green/red magnitude); only the true ECharts
  components go through `QE_ECHARTS_THEME`.

Rules: transparent background, no toolbar, animations off, grid lines in
`--qe-line` territory. Candles: up `--qe-green`, down `--qe-red`. Equity: area in
green. Regime series colors come from `QE_ECHARTS_THEME` keyed by regime — never
hardcoded. Keep chart containers sharp (`.qe-chart`).

ECharts version is **5.5.1** (vendored) — reconciled with the engine's existing
`static/echarts-theme-qe.js` surface (the design reference pinned 5.5.0).

---

## 8. Regime Color Map

| Key | Badge class | Accent | Label |
|---|---|---|---|
| `risk_on_trending` | `.qe-rg-trend` | `--qe-green` | `TREND` |
| `risk_on_choppy` | `.qe-rg-chop` | `--qe-cyan` | `CHOP` |
| `neutral` | `.qe-rg-neut` | `--qe-sub` | `NEUT` |
| `risk_off_defensive` | `.qe-rg-def` | `--qe-amber` | `DEF` |
| `risk_off_panic` | `.qe-rg-panic` | `--qe-red` | `PANIC` |

Use `RegimeBadge` for badges. For ECharts series, derive hex from
`QE_ECHARTS_THEME` (the `REGIME_HEX` map in `pages-regime.jsx` is built from it —
one source of truth).

---

## 9. Pages & Navigation

`NAV_ITEMS` (`nav-and-data.jsx`) drives the top nav; `QE_PAGES` (`app-shell.jsx`)
maps names → page components. Each page renders `TopNavStd` → `PageHeader` →
workspace/content → `StatusFooter`.

**Two pages are NOT in `NAV_ITEMS` on purpose** (an implementer would otherwise
wrongly build them into the top nav):

- **`Config`** is reached via the **gear button (⚙)** on the right of the top nav
  — not a nav tab.
- **`Primitives`** is a **DEV-only** page (the design-system proving ground),
  reachable via `#Primitives` / the DEV chip — **not in production nav**. It is
  the P0 foundation surface and carries the GridStack + ECharts proving grounds.

**P0 status:** only `Primitives` + the shared foundation are ported. The 8
production pages (`Dashboard`, `Pre-Trade`, `Linkage`, `History`, `Analytics`,
`Models`, `Regime`, `Config`) render a labelled placeholder until their phase
(P1–P7) lands.

---

## 10. Do's and Don'ts

| ✅ Do | ❌ Don't |
|---|---|
| Use `--qe-*` variables for every DOM color | Hardcode hex in the DOM |
| Source chart hex from `QE_ECHARTS_THEME` | Re-type regime/series hex inline |
| Use `rgba()` only for the documented alpha-wash carve-out (§2) | Reach for `rgba()` where a token exists |
| Keep the `border-radius:50%` carve-out to small status dots (§1) | Round cards / panes / buttons |
| Use `--qe-mono` + tabular-nums for all numbers | Use UI/system fonts for numbers |
| Compose pages from the primitives in §5 | Re-implement a card/tab/badge with inline styles |
| Bind live values to `window.QE_SSE` / `useLiveId` | Drive live values from a client random-walk |
| Put tileable panes in `GridWorkspace`/`GridItem` | Lay panes out in a fixed CSS grid |
| Let `GridWorkspace` own the pane gutter (`--qe-pane-gap`) | Wrap a workspace in a padded container |
| Reach `Config` via the gear, keep `Primitives` DEV-only | Add either to `NAV_ITEMS` |
| Keep corners sharp | Add `border-radius` (outside the status-dot carve-out) |
| Pair color with a label/symbol | Convey meaning with color alone |
