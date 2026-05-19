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

class TestNoPageLevelPeriodBar:
    """Regime page has no page-level period bar like Analytics. The
    Task 135 _periodTabs registry + _setPeriodBarEnabled helper
    pattern would be a wrong fit — different problem shape."""

    def test_no_analytics_period_bar_id(self):
        """The Analytics-style page-period-bar id must NOT appear on
        Regime. Defensive against accidental cross-page copy-paste."""
        src = _read_regime()
        assert 'id="analytics-period-bar"' not in src
        # Regime has its own panel-scoped selector with a different id
        assert 'id="signal-cards-range"' in src

    def test_no_period_tabs_registry(self):
        """Regime sub-tabs don't read a `period` query param at the
        route level — _periodTabs registry pattern doesn't apply."""
        src = _read_regime()
        assert "_periodTabs" not in src


# ── Selector-regression fix (the actual Task 125 latent bug) ──────────────

class TestSelectorRegressionFix:
    """The pre-Task-136 code queried `.global-range-btn` which doesn't
    exist post-Task-125 PeriodSelector migration. The fix is the
    correct selector that reaches the migrated buttons."""

    def test_dead_selector_removed_from_executing_js(self):
        """The dead `.global-range-btn` selector class is no longer
        referenced inside any querySelectorAll/querySelector call.
        Anchor comments may still NAME the old selector to explain
        what was replaced (Task 136's regression-fix comments do
        this) — that's documentation, not executing code."""
        src = _read_regime()
        # Look at every line that calls querySelectorAll/Selector —
        # those are the executing ones. Comments are stripped by JS
        # parsing; we approximate by ignoring lines whose first non-
        # whitespace token is `//`.
        bad_lines = []
        for ln, line in enumerate(src.splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("//"):
                continue
            if ".global-range-btn" in line and "querySelector" in line:
                bad_lines.append((ln, line.strip()))
        assert not bad_lines, (
            f"FE-MED-007 regression: .global-range-btn appears in "
            f"executing JS at lines {bad_lines!r}. Post-Task-125 the "
            f"correct selector is .global-range-group .preset-btn."
        )

    def test_correct_selector_used_in_both_callsites(self):
        """Both setCardRange and setAllCardRanges use the correct
        post-migration selector to clear the global active state."""
        src = _read_regime()
        # The correct selector reaches the .preset-btn descendants of
        # the .global-range-group wrapper
        correct = ".global-range-group .preset-btn"
        # Should appear at least twice (once per callsite)
        count = src.count(correct)
        assert count >= 2, (
            f"FE-MED-007 fix: expected the correct selector "
            f"{correct!r} to appear in both setCardRange and "
            f"setAllCardRanges; found {count} occurrence(s)."
        )

    def test_setCardRange_clears_global(self):
        """setCardRange (per-card click) should clear the global's
        active state — the audit's "global no longer reflects state"
        visual signal."""
        src = _read_regime()
        idx = src.find("function setCardRange(key,days,btn)")
        assert idx > 0, "setCardRange function not found"
        # Window must span past the anchor comment block (~6 lines)
        body = src[idx:idx + 1200]
        # End at the next function definition so we don't bleed
        next_fn = body.find("function setAllCardRanges")
        if next_fn > 0:
            body = body[:next_fn]
        assert ".global-range-group .preset-btn" in body
        assert "classList.remove('active')" in body

    def test_setAllCardRanges_clears_other_globals(self):
        """setAllCardRanges (global click) should clear any prior
        global's active state before highlighting the new one."""
        src = _read_regime()
        idx = src.find("function setAllCardRanges(days,btn)")
        assert idx > 0, "setAllCardRanges function not found"
        body = src[idx:idx + 1500]
        # End at next function/section to stay scoped
        for boundary in ("\nfunction ", "\n// ──", "\nasync function "):
            nxt = body.find(boundary, 50)
            if nxt > 0:
                body = body[:nxt]
                break
        assert ".global-range-group .preset-btn" in body
        assert "classList.remove('active')" in body


# ── Wrapper id + init title attr ───────────────────────────────────────────

class TestGlobalSelectorWrapperHasId:
    """The PeriodSelector call passes id='signal-cards-range' so the
    init IIFE can target the wrapper and set the title= attribute."""

    def test_period_selector_call_has_id(self):
        src = _read_regime()
        # Locate the period_selector call site
        idx = src.find('on_change_template="setAllCardRanges')
        assert idx > 0
        # Look backward + forward for the call boundaries
        block_start = src.rfind("{{ period_selector(", 0, idx)
        block_end = src.find(") }}", idx)
        assert block_start > 0 and block_end > idx
        block = src[block_start:block_end]
        assert 'id="signal-cards-range"' in block, (
            "FE-MED-007 (Task 136): the global PeriodSelector call "
            "needs id='signal-cards-range' so init JS can find the "
            "wrapper to set the title= precedence-doc attribute."
        )


class TestInitSetsTitleAttribute:
    """The init IIFE sets a title= attribute on the global selector
    documenting the precedence model (audit recommendation b:
    'Document precedence in a tooltip on the global selector')."""

    def test_init_iife_sets_title(self):
        src = _read_regime()
        # Find the init IIFE
        idx = src.find("// ── Init")
        assert idx > 0, "Init IIFE comment header not found"
        iife = src[idx:idx + 1200]
        # title attr is set on the global selector via JS
        assert "signal-cards-range" in iife
        assert ".title=" in iife or ".title =" in iife

    def test_title_text_describes_precedence(self):
        """The title text must document the precedence model — that
        the global sets all, and per-card overrides clear the
        global's active highlight."""
        src = _read_regime()
        idx = src.find("// ── Init")
        iife = src[idx:idx + 1200]
        # Spot-check the text mentions the two key semantic pieces:
        # (1) global affects all cards, (2) per-card overrides
        # Lowercase the body for case-insensitive match
        body_lc = iife.lower()
        assert "all" in body_lc and "card" in body_lc
        assert "override" in body_lc or "overrides" in body_lc

    def test_anchor_comment_present(self):
        """FE-MED-007 anchor comment in the init IIFE so future
        readers know which audit finding the title= is responding to."""
        src = _read_regime()
        idx = src.find("// ── Init")
        iife = src[idx:idx + 1200]
        assert "FE-MED-007" in iife


# ── Pattern-level invariants ─────────────────────────────────────────────

class TestPrecedenceModelInvariants:
    """Behavior invariants of the existing precedence model — these
    test that setCardRange + setAllCardRanges are still doing what
    the precedence model expects them to do (anti-regression on the
    semantic shape, not just selector syntax)."""

    def test_setAllCardRanges_reloads_every_signal(self):
        """Clicking global must call loadSignalCard for every signal."""
        src = _read_regime()
        idx = src.find("function setAllCardRanges(days,btn)")
        body = src[idx:idx + 1500]
        # The forEach over SIGNALS calls loadSignalCard(sig)
        assert "SIGNALS.forEach" in body
        assert "loadSignalCard(sig)" in body

    def test_setCardRange_only_reloads_one_signal(self):
        """Clicking per-card must NOT iterate SIGNALS — only update
        the one whose key was clicked."""
        src = _read_regime()
        idx = src.find("function setCardRange(key,days,btn)")
        body = src[idx:idx + 1500]
        # End at the next function definition
        next_fn = body.find("function setAllCardRanges")
        if next_fn > 0:
            body = body[:next_fn]
        # find sig and loadSignalCard(sig) — single-card reload
        assert "SIGNALS.find" in body
        assert "loadSignalCard(sig)" in body
        # No mass iteration
        assert "SIGNALS.forEach" not in body

    def test_signalRanges_state_updates(self):
        """Both functions mutate signalRanges state so the per-card
        chart-loader picks up the new range."""
        src = _read_regime()
        for fn in ("function setCardRange", "function setAllCardRanges"):
            idx = src.find(fn)
            body = src[idx:idx + 1500]
            assert "signalRanges" in body, (
                f"{fn} doesn't touch signalRanges state — precedence "
                f"model relies on shared state for the data layer."
            )


# ── Compile pin (MED-047) ─────────────────────────────────────────────────

class TestTemplateCompiles:
    def test_regime_compiles(self):
        env = _make_env()
        tpl = env.get_template("regime.html")
        assert tpl is not None
