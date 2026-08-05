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
    unread dot in `NotifRow` (`notifications.jsx`, cited by NAME — the line
    drifts); the `NewsTickerBar` live/dot marks `tokens.css:694` / `:719`;
    the linkage/analytics/models live dots).
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
  the canonical case is `PaneFoot`'s tone-background washes (the `toneColors`
  map in `primitives.jsx` — `ok/info/warn/err` at 5–6% alpha; cited by NAME,
  not line, since the line drifts), plus small darken scrims/shadows behind
  timers/toasts/drawers/dialogs, the `HeatStrip`/calendar magnitude-heat
  fills, and the row tints (`ANA_LINK_META`; the regime near-threshold row
  wash) — same 5–6% shape as the PaneFoot washes. The list is
  ILLUSTRATIVE, not exhaustive: re-grep the class before assuming a new
  site is a violation. This is a documented carve-out parallel to the ECharts exception:
  prefer a `--qe-bg-*` token where one fits; use `rgba()` only for the
  alpha-wash tints that have no token. Do not reach for `rgba()` for solid
  colors that a token already covers.

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
- **Live numbers:** `LiveValue`, `LiveClock`, `FlashCell` — streaming values that flash on change and show a stale indicator. Bind them to real data via the SSE adapter (`window.QE_SSE.onChannel(...)` → fold into the page's own module store → `notify()`, the shape `dash-tiled.jsx`'s `_wireSSE` established) or a poll, never a client random-walk. `LiveValue` takes its value as a PROP; its `data-live-id` attribute is a RESERVED hook for a server-side htmx/OOB swap target and currently has no instances (`/v3` is a React SPA — an OOB swap into React-managed DOM would be reconciled away), so never treat it as a lookup key. (This rule used to name a `useLiveId` hook and a live-value registry — P1 shipped the store-fold instead, the registry never gained a writer, and both were deleted 2026-08-05.) (The reference's `LiveNumber`/`LivePct`/`useLiveTicker` random-walk family was stripped in P8 wave 1 — zero production callers.) The shared chrome (TopNav / WorkspaceBar / StatusFooter) binds the `QE_CHROME` store (`chrome-live.js`: `/api/state` 10s · snapshot 30s · `/api/system` 60s · `/accounts` · SSE status), rendering `—` when a source has no data.

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
- **`DataList`** `{columns, rows, dense, onClick, selected, summary, tools}` — the canonical table (built-in search · click-to-sort · auto filters); falls back to `EmptyState` when empty. **Usage rule (M9, 2026-08-04): a host whose `rows` are one SERVER page of a larger set must pass `tools.scope` (e.g. `'loaded page only'`, optional `scopeTitle` for the hover sentence) — the tools refine the rows in hand, and that must be said on screen, not in a comment. Any page-level aggregates beside such a table carry the same qualifier.** Enforced by `tests/test_med_tail_batch.py::TestM9PageScopeCaption` (glob sweep over the pager idiom).
- **`FieldList`** `{rows, cols, dense}` — vertical key→value rows (20px pane-head rhythm).
- **`Gauge`** `{label, value, max, ticks}` — auto-tones `ok<60 / warn 60–80 / err>80`.
- **`EmptyState`** `{tone, glyph, msg, hint, cta, fill}` — the one empty/placeholder treatment. See **No-data standard** below for `fill`.
- **`HeatBar`** `{mfe, mae, pnl, w, h}` — THE excursion cell. See **Excursion (MFE/MAE) standard** below.
- **`HeatBarLabelled`** `{mfe, mae, pnl, pct, h}` — the detail-size heat bar with MAE / ENTRY / MFE labels and an exit line.
- **`Strip`** `{items, dense}` · **`Banner`**, **`Toast`** · **`NewsTickerBar`**.

#### No-data standard (operator-ratified 2026-07-25)
Every pane whose content is "nothing to show" renders **one** treatment: a dashed
frame **inset `calc(var(--qe-pane-gap) * 2)` from the pane wall — twice the
standard inter-pane space — surrounding the entire pane body, with its message
centred on both axes.**

- Pass **`fill`** when the empty state IS the pane's whole content. `DataList`
  and `PaneErrorBoundary` already do this for you, which covers most panes.
- **Do NOT pass `fill`** when the empty state renders *alongside* siblings (a
  list's "none yet" notice above the list) — it would cover them.
- The geometry is `position:absolute` against `.qe-pane-body`, **not a margin**:
  the pane body's own padding varies per call site, so a margin would land at a
  different offset on every pane. `inset` resolves against the padding box,
  whose edge is the pane's inner border, so the offset is exact everywhere.
- The rule is **scoped to a `.qe-pane-body` ancestor**, so an `EmptyState` in a
  modal or an inline list keeps normal flow automatically.
- **Never fill the DataList "no matches" state.** Rows exist and the sticky
  toolbar above is the only way to clear the filter; covering it traps the
  operator. Pinned by `tests/test_empty_state_standard.py`.

#### Excursion (MFE/MAE) standard
Any MFE/MAE bar is **`HeatBar`** — never a hand-rolled pair of bars. It has
**three load-bearing channels**; shipping a subset changes what the cell means:
1. **centre ENTRY rule** — the datum both excursions are measured from. Without
   it the halves float and the cell says nothing about direction.
2. **red extent LEFT = MAE**, **green extent RIGHT = MFE**, scaled to the row's
   own span (`max(|mfe|,|mae|,|pnl|)`) so the tick can never fall outside.
3. **bright EXIT tick** — where the close landed *inside* that range. This is
   what turns "how far it swung" into "…and how much of it we kept". It is not
   a restatement of the PnL column.

Truthfulness rules (these are ours, not the mock-fed design's): `mfe` and `mae`
both null = **not measured** → render `—`, never a zero-width bar; `pnl` null →
**omit the tick** rather than park it at centre, which would assert a
break-even close that was never measured. Column label: `MAE ◂ HEAT ▸ MFE`.

### Pane (tiling tile)
- **`Pane`** `{title, count, right, hot, tag, foot, onRefresh}` — head (20px) + scrolling body + optional `foot`. Independently reloadable; body wrapped in `PaneErrorBoundary` (a throwing child shows a recoverable error state, not a blank app).
- **PaneFoot policy (operator-ratified, rev 2): foots are DATA-STATE lines,
  never descriptive prose.** A foot reports the health of the pane's data
  pipe on a 4-tier model, derived through **`qeFootState({loading, err,
  corrupt, status, hasData, empty, ms})`** (primitives.jsx, exported on
  window) — panes bind the result, they do not hand-craft messages:
  1. **fine** → tone `ok` — `connected [12ms]` (REAL measured fetch ms,
     `performance.now()` around the fetch).
  2. **degraded** → tone `warn` — something is on screen but imperfect:
     `delayed [640ms]` (ms > 500) · `response corrupt · showing last data`
     · `no network · showing last data · retrying` (the keep-last-good
     states; **`· retrying` is appended only when the caller genuinely
     re-polls** — pass `retrying: true` for interval-driven fetches, never
     for one-shots).
  3. **error** → tone `err` — nothing usable to show, and the CAUSE is
     named: `endpoint not found (404)` · `no network — engine unreachable`
     · `server error (500)` · `unauthorized (403)` · `corrupt response`.
  4. **attempt** → tone `sub` + `busy:true` (braille spinner) —
     `loading…` / `reconnecting…`.
  **2-vs-3 rule: data on screen → tier 2 (warn, cause appended); no data →
  tier 3 (err, cause displayed).** Fetch plumbing: `_ptJson`/`_cfgJson`
  attach `err.status` (0 = network-level) and `err.corrupt` to thrown
  errors; `useAnaJson` measures `ms` and returns a ready `foot`; custom
  loaders (QE_DASH, config/linkage/history/pretrade) track `{err, ms}` per
  source and derive through the same helper. Non-fetch panes carry their
  nearest truthful state: `ok · local` for forms/localStorage, the
  last-submit result for POST-result panes (`calculating…` / `calc ok` /
  `calc failed · showing last result`). Never hand-write `id`/`ms` foot
  props (DEV proving-ground demos excepted); the ↻ reload line stays
  honest (`reloaded · refetched` with `onRefresh`, `reloaded · body
  remounted` without). A successful-but-empty fetch is tier 1 — the BODY
  owns empty-state display (EmptyState); the foot reports the pipe.
  **MULTI-PIPE RULE (2026-07-31): a pane fed by more than one source must
  report the WORST of them, never a chosen one — each pipe carrying its
  OWN `hasData`.** Derive the 4-tier state per pipe, then reduce by
  SEVERITY: `err` > never-answered > errored-showing-last-data >
  merely-delayed > `ok`, ties breaking to the slower pipe. Use a helper
  taking a list of `{src, hasData}` (`_dashFootWorst(d, [{src:'snapshot',
  hasData:d.loaded}, …])`); single-pipe panes call the same path with one
  entry. Three things here are load-bearing, and each was learned by
  shipping it wrong:
  1. **`hasData` is per-pipe.** `qeFootState` pivots BOTH decisions on it
     — tier 4 is `loading && !hasData`, the 2-vs-3 split is `if
     (hasData)` — so one OR'd flag across N pipes judges every pipe by
     another pipe's data.
  2. **`hasData` is void until the pipe has answered.** The callers'
     expressions are PROXIES with a SECOND WRITER (SSE writes
     `st.dd_state` and `equity.total_equity` straight into the store), so
     a hung poll still satisfies them. Gate on
     `answered = ms != null || err`.
  3. **Rank by severity, not by tone.** Both `warn` flavours — "errored ·
     showing last data" and a merely slow "delayed [Nms]" — assert that
     data is on screen, and a never-answered pipe has none, so it
     outranks both. Order: `err` > never-answered > errored-with-data >
     delayed > `ok`, following the doctrine's own tiering (3 and 4 alike
     have nothing usable; 2 does). Tone-ranking let any >500ms sibling
     mask a hung pipe with `delayed [Nms]`.
  Each of those three, alone, reproduced the same observable: **a pipe
  that had never answered reporting healthy, carrying its sibling's
  latency.** Why the rule exists at all: Risk Monitor keyed its foot to
  `/api/state` while four of its five readouts came from
  `/api/dashboard/snapshot`, so a snapshot outage painted stale exposure,
  drawdown, weekly-loss and positions under a green `connected`. **An
  affirmative WRONG signal is worse than no signal** — the one failure
  mode a data-state foot exists to prevent, and invisible to any test
  that only checks a foot is present. When adding a pane, list every
  source its body AND its leaf children read, and pass them all.
  **Scope caveat:** `_dashFootWorst` lives in `dash-tiled.jsx`, so only
  the Dashboard is mechanically pinned
  (`tests/test_dash_foot_covers_its_sources.py`). Other pages hand-roll
  `qeFootState` per source and must apply this rule by hand until the
  helper is lifted into `primitives.jsx`. The formerly-known violation —
  `pages-pretrade.jsx`'s Regime · ATR pane (read the CALC pipe, footed
  the REGIME pipe alone) — was closed 2026-08-04 by exactly that hand
  application: `_ptWorstFoot` reduces two ALREADY-DERIVED feet by the
  ratified severity order, with the calc entry participating only once
  that pipe exists (before the first calc, the ATR half honestly shows
  its run-Calculate instruction). The primitives lift itself is still
  open.
- **THE READ DEADLINE — every read pipe is bounded (closed 2026-08-01;
  was the filed WARM HANG).** `fetch` has no default timeout, and a
  promise that never settles runs neither the resolve nor the catch
  branch. So a pipe that succeeded once and went dark kept its
  `{err:null, ms}` entry unchanged and its foot read `ok · connected
  [12ms]` indefinitely — executed: 24 h of hanging (≈17k outstanding
  polls) still green, with Net Exposure / Drawdown / Weekly Loss /
  Positions frozen at hours-old values. Every foot in the app answers
  "did this pipe ever report?", never "did it report RECENTLY", so
  nothing downstream could see it.
  **THE RULE: every READ carries a deadline, and a POLLED read's
  deadline is its own interval, floored at 5 s** (`qePollDeadline`,
  `primitives.jsx`). A request that has not answered by the time its
  successor is due is superseded — cancelling costs nothing (the
  successor is going out anyway) and frees the connection it needs; the
  floor keeps sub-second pollers from cancelling a merely slow but
  healthy response. One-shot reads get `QE_READ_DEADLINE_MS` (30 s),
  generous because aborting a request with no successor coming needs a
  manual reload to recover. **Derive the deadline from the SAME literal
  that feeds `setInterval`** — every polled module now names its cadence
  once (`_POLL`, `PT_PRICE_MS`, `LK_FAST_MS`, …) so the two cannot
  drift; a poller with two cadences (the link-window countdown) is
  sized from the SLOWER one. **★ EXCEPTION — a client deadline must
  never be tighter than the ENGINE's own upstream budget**, or it kills
  requests the server was about to answer and the pane then never loads
  at all, which is the same lie pointing the other way. Exactly two
  polled reads have a handler that awaits a third-party call —
  `/api/price/{ticker}` and `/api/calculator/orderbook/{ticker}`, both
  via `fetch_orderbook` → ccxt, whose default timeout is 10 s with no
  override and no retry — so those two take
  `QE_UPSTREAM_READ_DEADLINE_MS` (12 s) instead of the poll floor. It
  costs nothing: both are chained-`setTimeout` pollers that reschedule
  only after their await, so each holds at most one request outstanding
  whatever the deadline. The backend half of that premise is pinned too
  (`TestTheUpstreamBudget`), so a third such endpoint cannot silently
  inherit the tight floor. Deadline errors carry `status: 0` (so every existing
  network-sentinel branch keeps working) plus `timeoutMs`, which
  `qeFootCause` and `qeFootState` check FIRST — `no response in 5s —
  engine not answering` rather than the false `no network — engine
  unreachable`.
  **WHY AT THE REQUEST AND NOT AT THE FOOT.** The originally filed shape
  was a timestamp on every net write plus a `now - at > k × interval`
  threshold. It was not taken, and the reason generalises: **a timestamp
  needs a clock to evaluate it, and every clock a page has —
  `setInterval`, `setTimeout`, a render tick — is throttled by exactly
  the conditions that strand a pipe** (hidden pages ~1/min, frozen pages
  not at all), so the detector sleeps precisely when it is needed. It
  also cannot repaint on its own (nothing changes when data merely gets
  old) and leaves the hung sockets outstanding, so it does not touch the
  connection-cap aggravator at all. A deadline is self-triggering: the
  rejection IS the event, it lands in the `err` channel the 4-tier
  deriver already renders correctly, and **no foot call site changes.**
  **WRITES ARE DELIBERATELY EXEMPT.** Aborting a mutation in flight
  cannot cancel what the server already did, so it trades a stuck
  spinner for "did my save land?". Reads carry no such ambiguity.
  **The half a deadline cannot reach** is a throttled poller: no request
  is outstanding to time out, so the app-lifetime stores (`QE_CHROME`,
  `QE_DASH`) re-poll on return-to-visible via `qeOnVisible` — a fresh
  answer beats a staleness label, and it is the operator's real pattern
  (place in Quantower, alt-tab back). One helper, because it has two
  easy-to-get-wrong parts: it must ignore the HIDE transition, and it
  must rate-limit (the event fires on every toggle, so alt-tabbing
  quickly would burst one request per pipe per toggle against the same
  ~6-connection cap named above as the hang's aggravator).
  The fabrications filed alongside it were closed 2026-08-04: the Risk
  Monitor Positions gauge (and the Open Positions summary cap) now dash
  their READOUTS until the snapshot delivers — the numeric fallbacks
  survive only as bar geometry — and `WatchlistTape` dashes its MARK
  prices (title names the failing endpoint, the `_navStaleDash` shape)
  when the snapshot pipe errs, while uPnL% keeps rendering off its own
  SSE writer.
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
- Layouts persist per workspace via `qeWorkspaceSave` / `qeWorkspaceLoad` / `qeWorkspaceReset` (localStorage keyed `qe.ws.layout.${id}` — **NOT account-namespaced**; namespacing is a deferred §1.5 coexistence item, P8 decision point); **⤓ Save / ⤒ Load** live in the `WorkspaceBar` (Dashboard only — disabled elsewhere in the reference). The **+** beside them is disabled EVERYWHERE (2026-08-05): multi-workspace is not implemented, and the handler it used to carry just re-ran the same `qeWorkspaceReset` the `Default` preset calls — a misleading label on a duplicate control. Reviving it means real workspace creation (naming, its own `persistId`, a switcher), not re-pointing the old handler.

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

**Nav placement rules** (corrected in the P8 doc wave — the ported §9 had
claimed Primitives was "not in NAV_ITEMS", contradicting both the design
reference and the shipped code, audit L7-F2):

- **`Config`** is reached via the **gear button (⚙)** on the right of the top nav
  — not a nav tab. (Accurate as shipped.)
- **`Primitives`** is a **DEV-only** page (the design-system proving ground).
  It IS currently in `NAV_ITEMS` as a divider-separated amber **DEV-chip tab**
  (faithful to the design reference) and also reachable via `#Primitives`.
  **Whether the tab ships past the `/v3` → `/` promotion is a named P8
  retirement decision point** — strip it from NAV_ITEMS (hash routing keeps
  the page reachable) or keep the DEV chip; the operator decides.

**Status (P8):** ALL 8 production pages (`Dashboard`, `Pre-Trade`, `Linkage`,
`History`, `Analytics`, `Models`, `Regime`, `Config`) are shipped and wired —
`QE_PAGES` carries real components for every one. (This line read "only
Primitives is ported … placeholders until P1–P7" until the P8 doc wave — the
same stale-pre-execution-text class the wave retitled out of the plan's P4
note.)

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
| Bind live values via `QE_SSE.onChannel` → page store → `notify()` | Drive live values from a client random-walk (or reach for the deleted `useLiveId` registry) |
| Put tileable panes in `GridWorkspace`/`GridItem` | Lay panes out in a fixed CSS grid |
| Let `GridWorkspace` own the pane gutter (`--qe-pane-gap`) | Wrap a workspace in a padded container |
| Reach `Config` via the gear; keep `Primitives` DEV-badged (§9) | Add a PRODUCTION page to `NAV_ITEMS` (the Primitives DEV chip rides there pending the P8 retirement call) |
| Keep corners sharp | Add `border-radius` (outside the status-dot carve-out) |
| Pair color with a label/symbol | Convey meaning with color alone |
