"""
Task 136 regression tests — FE-MED-007 Regime period selector parallel
investigation.

Investigation outcome (rejected the audit's "precedence ambiguity"
framing the same way Task 135 did for FE-MED-018):

  Regime page is structurally different from Analytics. There is NO
  page-level period bar; sub-tabs (Overview / Backfill / News /
  Config) switch via client-side `showPanel(name)` not fragment
  endpoints, so the cross-sub-tab dead-control problem (Analytics
  Model D) doesn't apply. The "global" range selector lives INSIDE
  the Macro Signals card on the Overview panel — it's panel-scoped,
  not page-scoped.

  Both the global "All:" selector and the per-card selectors are
  functional (drive `loadSignalCard()`). The precedence model
  already exists in code:
    - setAllCardRanges(days, btn): sets every per-card range to
      `days`, reloads all cards, marks the global button active.
    - setCardRange(key, days, btn): updates one card, clears the
      global's active state (visual signal that cards are no
      longer all-in-sync).

  BUT — orthogonality investigation surfaced a TASK-125 MIGRATION
  REGRESSION: the PeriodSelector primitive migration renamed the
  global buttons from `.global-range-btn` to `.preset-btn` (under
  the `.global-range-group` wrapper class). Two JS callsites
  (setCardRange + setAllCardRanges) still queried the dead
  `.global-range-btn` class. Effects:
    1. Clicking "All: 30d" then "All: 90d" left both active.
    2. Per-card override didn't clear the global "active" indicator.

  Task 136 fix: replace `.global-range-btn` with
  `.global-range-group .preset-btn` (2 lines) + add an `id` to the
  PeriodSelector wrapper + init IIFE sets a `title=` attribute on
  the global selector documenting the precedence model (audit
  recommendation b).

  Audit-impact-imprecision counter: stays at 6 (Task 135's example
  was the dead-control variant; Task 136's example is a
  migration-regression variant — different mechanism, same root
  cause of "orthogonality investigation surfaces a different bug
  than the audit framed").

Source-pin tests (selectors + JS handlers are JS-driven; can't
render-test JS state changes without a browser).

Run: pytest tests/test_task136_regime_period_precedence.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import jinja2


def _make_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    return env


def _read_regime() -> str:
    return Path("templates/regime.html").read_text(encoding="utf-8")


# ── No-page-level-period-bar invariant ────────────────────────────────────



# ── Selector-regression fix (the actual Task 125 latent bug) ──────────────






# ── Wrapper id + init title attr ───────────────────────────────────────────





# ── Pattern-level invariants ─────────────────────────────────────────────



# ── Compile pin (MED-047) ─────────────────────────────────────────────────

