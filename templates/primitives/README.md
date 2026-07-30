# `templates/primitives/` — Bundle A primitive library

Reusable UI components extracted from the engine's chrome. Established
during Phase 5 Bundle A (Task 121, FE-HIGH-001 fix). This directory
holds the convention; future Bundle A tasks add primitives to it.

## What lives here vs `templates/fragments/`

| Directory                | Purpose                                                                                                                                       |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `templates/primitives/`  | Reusable stateless component macros. Called from any template via `{% from "primitives/X.html" import X %}`. No HTTP route serves these.      |
| `templates/fragments/`   | HTMX response targets — full template files returned by route handlers (e.g. `templates/fragments/needs_link_queue.html`). Stateful, route-bound. (Fragments slim-down 2026-07-30: only the 5 HTML-consumed fragments remain — the React pages read JSON doors.) |
| `templates/base.html`    | Page chrome + global styles + the singleton-style shell that other pages inherit.                                                             |

The split is **responsibility, not size**. A 200-line component lives
in `primitives/` if it's reusable + stateless. A 20-line HTMX response
fragment lives in `fragments/` if it's the body of a particular route's
HTMX swap.

## The 5-severity vocabulary

Every primitive that signals state uses the same severity word + colour:

| Severity   | CSS var       | Meaning                                                |
| ---------- | ------------- | ------------------------------------------------------ |
| `success`  | `--green`     | Connected, OK, ready, in-target.                       |
| `warning`  | `--amber`     | Degraded mode, stale data, near-limit, fallback path.  |
| `error`    | `--red`       | Disconnected, fault, hard fail, over-limit.            |
| `info`     | `--blue`      | Informational, in-progress, neutral-positive activity. |
| `neutral`  | `--muted`     | Disabled, N/A, unknown, "still initialising".          |

When new primitives need state, they reuse these five. **Do not introduce
custom severity words like `"online"`, `"alive"`, `"good"`.** The
operator should be able to read a colour and a word without
context-switching across components.

## Macro vs include — when to use which

| Pattern                                  | When to use                                                                                                  |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| **Jinja2 `{% macro %}`** (stateless)     | Parameter-driven, no slot content. StatusIndicator. Tight, fast, no per-call template load.                  |
| **`{% include %}` with context vars**    | Slot content via `{% block %}` overrides. Card (header + body + footer slots). More structure, more overhead. |
| **Scoped-call `{% call %}` macro**       | Single-slot primitives that still want macro semantics. EmptyState (icon + heading + message slot).          |

When in doubt, start with a macro. Move to `include` only when slot
content actually shows up in the requirement.

## CSS organisation

Primitive CSS lives in `templates/base.html` under the `── Primitives ──`
section of the main `<style>` block. Single load point — no extra HTTP
requests, no template-loader configuration changes.

**Namespace rule**: every primitive uses a short class prefix (2-3 letters):

| Primitive       | Prefix    | Examples                                  |
| --------------- | --------- | ----------------------------------------- |
| StatusIndicator | `si`      | `.si`, `.si-dot`, `.si-label`, `.si-value`, `.si-success` |
| Card            | `card`    | `.card-header`, `.card-body`, `.card-footer`, `.card-title`, `.card-subtitle` (builds on existing `.card` + `.card-p8` utility classes) |
| TableRow        | `tr-p`    | `.tr-p`, `.tr-p-clickable`, `.tr-p-selected` (composes on existing cell typography classes `.td-*` / `.mono`) |
| EmptyState      | `es`      | `.es`, `.es-msg`, `.es-action`, `.es-info`, `.es-action` (tone)  |
| PeriodSelector  | `ps`      | `.ps`, `.ps-label` (composes on existing `.preset-btn` for the button look + `.active`) |

When the inline-style block in base.html crosses ~500 lines of
primitive CSS, **extract to `static/css/primitives.css`** loaded via
`<link rel="stylesheet">` in base.html's `<head>`. Until then, inline
is fine — matches the codebase's existing convention.

## Adding a new primitive — checklist

1. **Decide macro vs include vs call** based on slot needs (see table above).
2. **Define API surface** — keyword params for clarity; required params
   first, optional after. Document each in the macro docstring.
3. **Pick a 2-3 letter class prefix** — check this README's table doesn't
   collide.
4. **Map severities** if the primitive signals state — reuse the five
   words above, do not invent new ones.
5. **Inline CSS in base.html** under `── Primitives ──`. When ~500 lines
   accrue, extract to `static/css/primitives.css`.
6. **Write MED-047-compliant tests** — `jinja2.Environment(loader=
   FileSystemLoader("templates")).get_template("primitives/X.html")` +
   render with synthetic context. Source-string greps are insufficient
   for Jinja2 syntax errors (the MED-047 calibration finding).
7. **Update this README** — add the primitive to the prefix table.

## Adding a primitive that needs slot content

Slot primitives use Jinja2's `{% call %}` mechanism:

```jinja2
{% from "primitives/card.html" import card %}

{% call card(title="Volume & Activity", subtitle="October 2025") %}
  <div style="display:grid;...">
    ... body content ...
  </div>
{% endcall %}
```

Inside the macro, `{{ caller() }}` renders whatever the caller passes
between `{% call %}` and `{% endcall %}`. Header + footer remain
parameters so callers don't have to thread markup through `caller()`
twice. Card is the convention example — see its source for the shape.

When a primitive's "header" needs richer content than text (e.g.,
action buttons in the header right corner), the choice is:

1. **Add more macro params** for the slot — e.g., `header_actions=""`
   accepting raw HTML. Simple but rigid.
2. **Add an `open` / `close` pair**: `{{ card_open(...) }} body
   {{ card_close() }}` — explicit, no `caller()`, callers can put
   arbitrary template structure between. More verbose at call sites.

Defer the open/close pair until a real consumer needs it. Adding
params one-by-one as needs surface is fine; over-engineering ahead of
that is what bloats primitives.

## Adding a primitive that wraps a sibling list (open/close pair)

When the primitive body is a **list of sibling elements**, not one
contiguous block, `{% call %}` + `caller()` doesn't fit naturally —
callers would have to wrap their siblings in a single block, losing
per-sibling structure. The convention is an **open/close pair**:

```jinja2
{% from "primitives/table_row.html" import tr_open, tr_close %}

{{ tr_open(state="clickable", on_click="togglePosRow(7)") }}
  <td>cell 1</td>
  <td>cell 2</td>
  <td>cell 3</td>
{{ tr_close() }}
```

TableRow is the convention example. Reasons:
- `<tr>` body is naturally a sibling list of `<td>` cells.
- Existing markup is `<tr><td>...</td>...</tr>` — open/close lets
  callers migrate incrementally without restructuring cells.
- Adds structural hooks (hover/selection state classes) without
  reinventing cell typography.

**Decision tree:**
- Body is **one contiguous block** (Card's title-and-grid) → `{% call %}` + `caller()`.
- Body is a **list of sibling elements** (TableRow's `<td>` cells) → open/close pair.
- Body is **stateless parameter-driven** (StatusIndicator's label+value, EmptyState's message+action, PeriodSelector's options+current) → plain macro.

## Jinja2 gotchas (learned-the-hard-way)

- **Nested `{# ... #}` comments don't nest.** An inner `{# #}` closes
  the outer block, leaving the rest of your docstring as live template
  code (which usually parses as undefined-symbol errors). Compile-
  render the macro file via `jinja2.Environment.get_template()` BEFORE
  committing — source-string greps will not catch this. Surfaced in
  Task 121 during StatusIndicator's docstring; MED-047's discipline
  applies.

- **`call` / `caller` requires a body slot.** If your primitive has
  no body slot (StatusIndicator), use plain `{% macro %}` and have
  callers `{{ status_indicator(...) }}` not `{% call status_indicator(...) %}{% endcall %}`.

- **`safe` filter on caller-supplied footer markup.** Card's footer
  param accepts raw HTML via `{{ footer | safe }}`. Caller is
  responsible for escaping anything user-derived. Don't pass raw user
  input as footer.

## Current primitives

### StatusIndicator (Task 121)

`templates/primitives/status_indicator.html` — single labeled status
component (a ●-dot + label + optional value). Used in the Needs-Link
queue, and available to any surface that needs a labeled status. See
the macro docstring for full API.

```jinja2
{% from "primitives/status_indicator.html" import status_indicator %}

{# Minimal: just label + dot, no value #}
{{ status_indicator("neutral", "Matcher") }}

{# With value (most common shape) #}
{{ status_indicator("success", "Matcher", value="Linked") }}
{{ status_indicator("error",   "Matcher", value="Needs link") }}
{{ status_indicator("warning", "API",     value="rate-limited") }}
{{ status_indicator("info",    "Regime",  value="recomputing") }}

{# With id for JS targeting #}
{{ status_indicator("neutral", "Matcher",
                    value="Checking…",
                    id="match-indicator") }}
```

JS pattern for state transitions:

```javascript
var indicator = document.getElementById('match-indicator');
var value     = indicator.querySelector('.si-value');

function setSeverity(el, sev){
  el.classList.remove('si-success','si-warning','si-error','si-info','si-neutral');
  el.classList.add('si-'+sev);
}

setSeverity(indicator, 'success');
value.textContent = 'Linked';
```

### Card (Task 122)

`templates/primitives/card.html` — slot-content panel. Used at the
Analytics Overview migration (FE-MED-001 fix). Defaults to tight
History-matching rhythm (8px × 10px padding via the existing
`.card-p8` utility class). Header has optional title + subtitle;
body is a required slot via `caller()`; footer is optional raw HTML.

```jinja2
{% from "primitives/card.html" import card %}

{# Minimal — title + body only #}
{% call card(title="Equity & PnL") %}
  ... body ...
{% endcall %}

{# Title + subtitle (period label, etc.) #}
{% call card(title="Volume & Activity", subtitle=period_label) %}
  ... body ...
{% endcall %}

{# With footer #}
{% call card(title="Section", footer='<a href="#">More</a>') %}
  ... body ...
{% endcall %}

{# Loose padding (back-compat with original .card default) #}
{% call card(title="Section", padding="loose") %}
  ... body ...
{% endcall %}
```

Slot pattern: `{% call %}` + `caller()` for the body. Why this over
alternatives: (a) extends/blocks is for page layouts, heavyweight;
(b) include-with-context can't take arbitrary template structure;
(c) the open/close pair is more verbose for a primitive whose 95% case
is title + body. When a primitive needs more than one slot, revisit.

### TableRow (Task 123)

`templates/primitives/table_row.html` — sibling-list-slot primitive
via open/close pair. Used at all three history tables (Position
History, Order History, Trade History — fills) to lock consistent
hover / selection / clickable state behaviour without reinventing
cell typography. Resolves FE-MED-002.

```jinja2
{% from "primitives/table_row.html" import tr_open, tr_close %}

{# Default (non-clickable) — Order History pattern #}
{{ tr_open() }}
  <td class="td-ts">{{ ms_to_local(r.updated_at_ms) }}</td>
  <td class="td-symbol">{{ r.symbol }}</td>
  ...
{{ tr_close() }}

{# Clickable + on_click — Position History click-to-expand pattern.
   on_click implies state="clickable" automatically. #}
{{ tr_open(on_click="togglePosRow(" ~ r.id ~ ")") }}
  ...
{{ tr_close() }}

{# Explicit state + id for JS targeting #}
{{ tr_open(state="clickable", on_click="select(7)", id="row-7") }}
  ...
{{ tr_close() }}

{# Selected state is dynamic — JS toggles .tr-p-selected at runtime
   via classList. Macro params don't model selection (since the
   initial-state render is rarely "already selected"). #}
```

States exposed via class:
- `.tr-p` (always) — base, faint hover background.
- `.tr-p-clickable` — cursor:pointer + stronger hover. Set by
  `state="clickable"` or implied by `on_click=...`.
- `.tr-p-selected` — selection background. JS-driven, not macro-param.

Cell typography classes (`.td-symbol`, `.td-ts`, `.td-sub`,
`.td-dim`, `.mono`, badges, etc.) keep working unchanged — TableRow
only owns the row-level state structure.

### EmptyState (Task 124)

`templates/primitives/empty_state.html` — parameter-driven "No X
found" / "Not yet backfilled" / etc. Consolidates 7 ad-hoc empty-state
treatments inventoried in FE-MED-006. Plain-macro pattern (third
pattern in the decision tree, alongside Card's call/caller and
TableRow's open/close).

```jinja2
{% from "primitives/empty_state.html" import empty_state %}

{# Info tone (default) — the 90% case #}
{{ empty_state(message="No closed positions found for this period.") }}

{# Action tone with navigational CTA — Regime not-backfilled pattern #}
{{ empty_state(
    message="Not yet backfilled.",
    tone="action",
    action_label="Use Backfill tab",
    action_url="/regime#backfill",
) }}

{# Action tone with HTMX attrs (rendered on the button) #}
{{ empty_state(
    message="No data loaded yet.",
    tone="action",
    action_label="Load",
    action_attrs='hx-get="/load" hx-target="#x"',
) }}
```

Parameters:
- `message` (required) — plain-text message, HTML-escaped.
- `tone` — `"info"` (default, muted grey), `"action"` (slightly
  brighter when paired with a CTA), or `"error"` (recoverable
  failure state, --red palette; Task 134 addition triggered by the
  htmx:responseError target-swap handler in base.html). Unknown
  tones fall through to `"info"` (defensive, parallel to
  StatusIndicator's bogus-severity fallthrough). Tone vocabulary
  now considered complete — any future tone proposals follow the
  same consumer-driven defer-discipline.
- `action_label` — button text. Empty omits the button row entirely.
- `action_url` — href; when set, renders `<a class="es-action">`.
- `action_attrs` — raw attrs string for HTMX or similar (`hx-get=
  "..." hx-target="..."`). Renders via `| safe` — caller is
  responsible for escaping. Without `action_url`, attrs render on a
  `<button>` instead.
- `padding` (Task 129) — `"default"` (20 px y-padding, the 90% case),
  `"tight"` (10 px y-padding + smaller font, for inline sub-tables /
  drawer expansions where the surrounding chrome already provides
  spacing), or `"loose"` (32 px y-padding, for full-page empty states
  like equity_ohlc landing). Unknown values fall through to
  `"default"`. Mirrors Card's tight/loose padding precedent.

**Wrapper semantics** (load-bearing — read before using):
- Renders as `<div class="es es-{tone}">`.
- **NOT suitable for placement directly inside `<tbody>`.** Browsers
  drop non-`<tr>` children of `<tbody>`. Use in the parent
  container's empty branch (the `else` of the row loop's `if rows`
  block, OUTSIDE the `<table>`), or inside a Card body slot, or as
  a standalone block on a page.

When **JS** renders an empty state (e.g., the Regime chart card
`chartEl.innerHTML = ...`), reuse the same `.es / .es-action /
.es-info / .es-msg` class names. The primitive's CSS becomes the
shared visual language; JS just composes HTML with the same classes.
See `templates/regime.html` `loadSignalCard` for the convention.

Out of EmptyState's scope:
- **Placeholder text** like "—" / "awaiting calculation" — different
  semantic (a value isn't yet computed; the slot is reserved).
- **Page-layout empty states** like "right half of Backtest is
  empty" — that's a layout decision (collapse to one column when
  right empty), not an empty-message component.

### PeriodSelector (Task 125)

`templates/primitives/period_selector.html` — segmented control for
selecting a period / range / time-window from a list of options.
Third plain-macro primitive in Bundle A (StatusIndicator + EmptyState
were the first two). Stateless from the primitive's POV — server
renders buttons with the current selection marked `.active`; JS or
HTMX handles transitions. Resolves FE-MED-007 visual normalization
across 3 distinct option-set shapes.

```jinja2
{% from "primitives/period_selector.html" import period_selector %}

{# History presets — string values, single-quoted in JS handler #}
{{ period_selector(
    options=[
      {"value":"90d", "label":"Last 90 days"},
      {"value":"30d", "label":"Last 30 days"},
    ],
    current="30d",
    on_change_template="setPreset('{value}')",
) }}

{# Regime global — integer values, with inline label prefix #}
{{ period_selector(
    options=[
      {"value":30,   "label":"30d"},
      {"value":365,  "label":"1y"},
      {"value":1825, "label":"5y"},
      {"value":0,    "label":"All"},
    ],
    current=365,
    on_change_template="setAllCardRanges({value},this)",
    label_prefix="All:",
    extra_class="global-range-group",
) }}

{# HTMX-driven (server fragment swap) #}
{{ period_selector(
    options=[...],
    current="30d",
    hx_get_template="/fragments/period?p={value}",
    extra_btn_attrs='hx-target="#out" hx-swap="innerHTML"',
) }}
```

Parameters (load-bearing):
- `options` (required) — list of `{value, label}` dicts. Caller
  controls the option set; primitive doesn't pick.
- `current` (required) — selected value. Compared via string-cast,
  so int values match int options and string values match string
  options consistently. Unknown current → no `.active` anywhere
  (defensive, no crash).
- `on_change_template` — JS expression template; `{value}` is
  interpolated raw. Caller controls quoting + arg shape.
- `hx_get_template` — HTMX URL template; `{value}` interpolated.
  Pair with `extra_btn_attrs` for `hx-target` / `hx-swap`.
- `extra_btn_attrs` — raw attrs on every button (via `| safe`;
  caller escapes).
- `label_prefix` — inline text prefix (e.g. `"All:"`) before the
  buttons. Renders as `<span class="ps-label">`. Empty omits.
- `id`, `extra_class` — optional wrapper customization.

Mutual exclusivity: if both `on_change_template` and `hx_get_template`
are set, both attributes are emitted (HTMX wins at runtime). Caller
should pick one.

`data-value="{value}"` is emitted on every button. JS callers
target by value via `b.dataset.value` (History migration renamed the
existing `dataset.preset` reading to `dataset.value` to match).

**Placement constraint**: `.ps` wrapper is `display:inline-flex` with
gap. Works inside flex / grid / block parents. Same `<tbody>` warning
as EmptyState — don't place inside table-row contexts.

**For JS-rendered selectors** (e.g. Regime per-card chart selectors
built in `buildSignalCards`'s template literal): JS emits the same
`.ps` + `.preset-btn` class structure as the primitive. Primitive
becomes a shared visual language across server- and client-rendered
selectors — same pattern as Task 124's EmptyState Regime migration.
