"""
Task 135 regression tests — FE-MED-018 Analytics page-level period
selector disabled on sub-tabs that ignore the `period` query param.

Investigation outcome (rejected the audit's "precedence ambiguity"
framing): the page-level period selector was a DEAD CONTROL on Equity
Curve / Calendar / Funding / Beta sub-tabs — those handlers in
api/routes_analytics.py don't read the `period` query param. Operator
clicking Month / Week / 30D etc. on those tabs caused no change.

Model D fix (rejected A/B/C from task spec which assumed actual
conflict): dim + disable the period bar when the active sub-tab
doesn't consume `period`. Reveals orthogonality without inventing
precedence semantics. Doesn't break sub-tabs that DO consume period.

Sub-tabs that consume period (verified empirically in routes_analytics.py):
  overview, pairs, excursions, rmultiples, risk
Sub-tabs that ignore period:
  equity, calendar, live (funding), beta

Source-pin tests (the dim/disable is JS-driven; can't render-test JS
without a browser).

Run: pytest tests/test_task135_analytics_period_bar.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import jinja2
import pytest


def _make_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    return env


def _read_analytics() -> str:
    return Path("templates/analytics.html").read_text(encoding="utf-8")


# ── Period bar wrapper id ───────────────────────────────────────────────────

class TestPeriodBarWrapper:
    """The period selector's container needs a stable id so JS can
    toggle disabled-state on it as a unit (vs touching each button
    individually)."""

    def test_period_bar_has_id(self):
        src = _read_analytics()
        assert 'id="analytics-period-bar"' in src, (
            "FE-MED-018 regression: page-level period bar wrapper has "
            "no stable id — JS dim/disable logic can't target it."
        )

    def test_period_bar_anchor_present(self):
        src = _read_analytics()
        assert "FE-MED-018" in src


# ── _periodTabs registry ────────────────────────────────────────────────────

class TestPeriodTabsRegistry:
    """JS-side registry of sub-tabs that consume the page-level
    `period` query param. Empirically verified against
    api/routes_analytics.py handlers."""

    def test_period_tabs_registry_present(self):
        src = _read_analytics()
        assert "_periodTabs" in src
        # Spot-check the entries — sub-tabs whose route handlers take
        # period= as a param.
        m = re.search(r"_periodTabs\s*=\s*\{[^}]+\}", src)
        assert m, "_periodTabs assignment not found"
        block = m.group(0)
        # These 5 consume period server-side
        for tid in ("overview", "pairs", "excursions", "rmultiples", "risk"):
            assert f"{tid}:" in block, (
                f"_periodTabs missing {tid!r} — that handler consumes "
                f"period and the bar should be ENABLED when active."
            )

    def test_dead_control_tabs_not_in_registry(self):
        """The 4 sub-tabs whose handlers ignore `period` must NOT be
        in _periodTabs. Otherwise the bar would be enabled on a tab
        where it has no effect."""
        src = _read_analytics()
        m = re.search(r"_periodTabs\s*=\s*\{[^}]+\}", src)
        assert m
        block = m.group(0)
        # These 4 do NOT consume period — must be absent from _periodTabs
        for tid in ("equity", "calendar", "live", "beta"):
            # `tid:` would only match if the tab were in the registry.
            # Use word-boundary so we don't catch 'equity_curve' etc.
            assert (
                re.search(r"\b" + re.escape(tid) + r":", block) is None
            ), (
                f"_periodTabs includes {tid!r} — that tab's handler "
                f"ignores period; the bar should be DISABLED when active."
            )


# ── Disable helper logic ────────────────────────────────────────────────────

class TestDisableHelper:
    """`_setPeriodBarEnabled(boolean)` flips opacity + pointer-events
    + each button's `disabled` attr."""

    def test_helper_defined(self):
        src = _read_analytics()
        assert "function _setPeriodBarEnabled(enabled)" in src

    def test_helper_toggles_opacity(self):
        src = _read_analytics()
        idx = src.find("function _setPeriodBarEnabled(enabled)")
        body = src[idx:idx + 1000]
        # Opacity goes to '.4' on disable (visible-but-dimmed)
        assert "opacity = enabled ? '1' : '.4'" in body

    def test_helper_toggles_pointer_events(self):
        src = _read_analytics()
        idx = src.find("function _setPeriodBarEnabled(enabled)")
        body = src[idx:idx + 1000]
        # pointerEvents = 'none' on disable (clicks pass through)
        assert "pointerEvents" in body
        assert "'none'" in body

    def test_helper_mirrors_disabled_attr(self):
        """Visual dim isn't enough — keyboard focus + screen readers
        also need to see the disabled state. Each button gets its
        `disabled` property toggled."""
        src = _read_analytics()
        idx = src.find("function _setPeriodBarEnabled(enabled)")
        body = src[idx:idx + 1000]
        assert "btns[i].disabled = !enabled" in body

    def test_helper_sets_title_attribute_explanation(self):
        """Hovering the disabled bar shows a tooltip explaining WHY
        it's inactive — operator learns the model without needing
        external docs."""
        src = _read_analytics()
        idx = src.find("function _setPeriodBarEnabled(enabled)")
        body = src[idx:idx + 1000]
        # The title attribute is set with an explanation
        assert "bar.title" in body
        assert "doesn" in body.lower() or "doesn&#x27;t" in body or "doesn\\'t" in body


# ── switchTab + init hooks ──────────────────────────────────────────────────

class TestSwitchTabHook:
    """switchTab() and the init IIFE both call _setPeriodBarEnabled
    so the bar's state stays in sync with the active tab."""

    def test_switch_tab_calls_helper(self):
        src = _read_analytics()
        idx = src.find("function switchTab(tid)")
        body = src[idx:idx + 800]
        assert "_setPeriodBarEnabled(!!_periodTabs[tid])" in body

    def test_init_calls_helper(self):
        """Page load: the initial tab is 'overview' (which IS in the
        registry → bar enabled). The init IIFE explicitly calls
        _setPeriodBarEnabled to set the starting state."""
        src = _read_analytics()
        # Locate the init IIFE (after // Init comment)
        idx = src.find("// Init")
        assert idx > 0
        body = src[idx:idx + 600]
        assert "_setPeriodBarEnabled" in body


# ── Routes-handler invariant: registry matches actual params ────────────────

class TestRegistryMatchesHandlerSignatures:
    """The _periodTabs registry must match which handlers actually
    accept a `period` parameter. If a handler is changed to take/drop
    `period`, this test catches the drift."""

    def _handler_sigs(self) -> dict:
        """Map sub-tab id → True if the handler signature includes
        `period:` as a parameter."""
        src = Path("api/routes_analytics.py").read_text(encoding="utf-8")
        # Map endpoint path suffix → function name + signature window
        mapping = {
            "overview":   "frag_analytics_overview",
            "equity":     "frag_analytics_equity",
            "calendar":   "frag_analytics_calendar",
            "pairs":      "frag_analytics_pairs",
            "excursions": "frag_analytics_excursions",
            "rmultiples": "frag_analytics_r_multiples",
            "risk":       "frag_analytics_var",
            "live":       "frag_analytics_funding",
            "beta":       "frag_analytics_beta",
        }
        out = {}
        for tid, fn_name in mapping.items():
            idx = src.find(f"async def {fn_name}(")
            assert idx > 0, f"handler {fn_name} not found in routes_analytics.py"
            # Signature ends at the closing paren of the def line
            end = src.find("):", idx)
            sig = src[idx:end]
            out[tid] = "period:" in sig.replace(" ", "")
        return out

    def test_registry_matches_handler_params(self):
        sigs = self._handler_sigs()
        src = _read_analytics()
        m = re.search(r"_periodTabs\s*=\s*\{[^}]+\}", src)
        assert m
        registry_block = m.group(0)

        for tid, takes_period in sigs.items():
            in_registry = re.search(
                r"\b" + re.escape(tid) + r":", registry_block
            ) is not None
            assert in_registry == takes_period, (
                f"Drift: handler frag_analytics_*{tid}* "
                f"{'takes' if takes_period else 'does NOT take'} period, "
                f"but _periodTabs registry has it "
                f"{'present' if in_registry else 'absent'}."
            )


# ── Anti-regression ─────────────────────────────────────────────────────────

class TestAntiRegression:
    """The visual change shouldn't break unrelated Analytics chrome."""

    def test_setperiod_function_unchanged(self):
        """setPeriod() still mutates _period + reloads the active tab."""
        src = _read_analytics()
        idx = src.find("function setPeriod(p)")
        body = src[idx:idx + 400]
        assert "_period = p" in body
        assert "loadTab(_activeTab)" in body

    def test_load_tab_passes_period_query(self):
        """loadTab() still appends period= + offset= to the endpoint
        URL. (Even on dead-control tabs — the handler will simply
        ignore the param. Cheap defensive default.)"""
        src = _read_analytics()
        idx = src.find("function loadTab(tid)")
        body = src[idx:idx + 600]
        assert "period=" in body
        assert "offset=" in body


# ── Compile pins (MED-047) ──────────────────────────────────────────────────

class TestTemplateCompiles:
    def test_analytics_compiles(self):
        env = _make_env()
        tpl = env.get_template("analytics.html")
        assert tpl is not None
