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
| Card (future)   | `card`    | `.card-header`, `.card-body`, `.card-footer`              |
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

### Card (planned — Task 122)

TBD.

### TableRow (planned)

TBD.

### EmptyState (planned)

TBD.

### PeriodSelector (planned)

TBD.
