# `templates/primitives/` — Bundle A primitive library

Reusable UI components extracted from the engine's chrome. Established
during Phase 5 Bundle A (Task 121, FE-HIGH-001 fix). This directory
holds the convention; future Bundle A tasks add primitives to it.

## What lives here vs `templates/fragments/`

| Directory                | Purpose                                                                                                                                       |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `templates/primitives/`  | Reusable stateless component macros. Called from any template via `{% from "primitives/X.html" import X %}`. No HTTP route serves these.      |
| `templates/fragments/`   | HTMX response targets — full template files returned by route handlers (e.g. `templates/fragments/history/trade_events_table.html`). Stateful, route-bound. |
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
| TableRow (future)| `tr-p`   | `.tr-p`, `.tr-p-cell`, `.tr-p-actions`                    |
| EmptyState      | `es`      | `.es`, `.es-icon`, `.es-msg`                              |
| PeriodSelector  | `ps`      | `.ps`, `.ps-pill`, `.ps-pill-active`                      |

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
component. Used at the header plugin/connection indicator
(FE-HIGH-001 fix). See the macro docstring for full API.

```jinja2
{% from "primitives/status_indicator.html" import status_indicator %}

{# Minimal: just label + dot, no value #}
{{ status_indicator("neutral", "Quantower") }}

{# With value (most common shape) #}
{{ status_indicator("success", "Quantower", value="Connected") }}
{{ status_indicator("error",   "Quantower", value="Disconnected") }}
{{ status_indicator("warning", "API",       value="rate-limited") }}

{# With id for JS targeting #}
{{ status_indicator("neutral", "Quantower",
                    value="Connecting…",
                    id="plugin-indicator") }}
```

JS pattern for state transitions:

```javascript
var indicator = document.getElementById('plugin-indicator');
var value     = indicator.querySelector('.si-value');

function setSeverity(el, sev){
  el.classList.remove('si-success','si-warning','si-error','si-info','si-neutral');
  el.classList.add('si-'+sev);
}

setSeverity(indicator, 'success');
value.textContent = 'Connected';
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

### TableRow (planned)

TBD.

### EmptyState (planned)

TBD.

### PeriodSelector (planned)

TBD.
