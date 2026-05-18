"""
Task 124 regression tests — Bundle A primitive #4 (EmptyState) +
FE-MED-006 + FE-MED-008 fixes.

EmptyState is the second plain-macro primitive (StatusIndicator was
first). Parameter-driven; no slot content. Two tones (info, action).
Optional CTA via action_label + action_url + action_attrs.

Consolidates 9 template-side "No X found" empty-state sites + 1
JS-side Regime not-backfilled chart card (which now emits the same
.es / .es-action / .es-msg class structure).

Run: pytest tests/test_task124_empty_state.py -v
"""
from __future__ import annotations

from pathlib import Path

import jinja2
import pytest


def _make_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    env.globals["fmt"] = lambda v, n=2: (
        f"{v:.{n}f}" if isinstance(v, (int, float)) else str(v)
    )
    env.globals["ms_to_local"] = lambda ms: "2026-05-19 10:00:00"
    env.globals["fmt_duration"] = lambda ms: "1h"
    return env


def _render_es(**params):
    env = _make_env()
    src = (
        '{% from "primitives/empty_state.html" import empty_state %}'
        '{{ empty_state('
        'message=message, tone=tone, '
        'action_label=action_label, action_url=action_url, '
        'action_attrs=action_attrs) }}'
    )
    return env.from_string(src).render(
        message=params.get("message", "No data."),
        tone=params.get("tone", "info"),
        action_label=params.get("action_label", ""),
        action_url=params.get("action_url", ""),
        action_attrs=params.get("action_attrs", ""),
    )


# ── EmptyState macro: rendering ─────────────────────────────────────────────

class TestEmptyStateRendering:

    def test_default_info_tone(self):
        html = _render_es(message="No closed positions found.")
        assert 'class="es es-info"' in html
        assert 'class="es-msg">No closed positions found.</div>' in html

    def test_action_tone_class(self):
        html = _render_es(message="x", tone="action")
        assert 'class="es es-action"' in html

    def test_unknown_tone_falls_through_to_info(self):
        """Defensive: bogus tone → info class. Mirrors StatusIndicator's
        bogus-severity fallthrough (Task 121)."""
        html = _render_es(message="x", tone="bogus")
        assert 'class="es es-info"' in html
        assert "es-bogus" not in html

    def test_message_is_html_escaped(self):
        html = _render_es(message="<script>alert(1)</script>")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_no_action_label_omits_button(self):
        """When action_label is empty, no <a> or <button> renders."""
        html = _render_es(message="x")
        assert "<a" not in html
        assert "<button" not in html
        assert "es-action" not in html or 'class="es es-action"' in html
        # Confirm not the action button class
        assert 'class="es-action"' not in html

    def test_action_label_with_url_renders_anchor(self):
        html = _render_es(
            message="Not yet backfilled.",
            tone="action",
            action_label="Use Backfill tab",
            action_url="/regime#backfill",
        )
        assert '<a class="es-action"' in html
        assert 'href="/regime#backfill"' in html
        assert ">Use Backfill tab</a>" in html

    def test_action_label_without_url_renders_button(self):
        html = _render_es(
            message="Load.",
            tone="action",
            action_label="Load",
        )
        assert '<button class="es-action"' in html
        assert "<a" not in html
        assert ">Load</button>" in html

    def test_action_attrs_pass_through_safe(self):
        """HTMX attrs render via | safe so attribute names with
        hyphens survive."""
        html = _render_es(
            message="x", tone="action",
            action_label="Load",
            action_attrs='hx-get="/load" hx-target="#x"',
        )
        assert 'hx-get="/load"' in html
        assert 'hx-target="#x"' in html

    def test_action_attrs_on_anchor_when_url_present(self):
        """attrs go on the <a> when action_url is set."""
        html = _render_es(
            message="x", tone="action",
            action_label="Load",
            action_url="/x",
            action_attrs='data-test="1"',
        )
        assert '<a class="es-action"' in html
        assert 'data-test="1"' in html
        assert "<button" not in html


# ── CSS present in base.html ────────────────────────────────────────────────

class TestEmptyStateCssInBase:
    def test_base_has_es_css_block(self):
        src = Path("templates/base.html").read_text(encoding="utf-8")
        assert ".es {" in src
        assert ".es-msg" in src
        assert ".es-info" in src
        assert ".es-action" in src
        assert "FE-MED-006" in src or "FE-MED-008" in src  # anchor


# ── Migration pins: history tables + dashboard + analytics ──────────────────

class TestHistoryTableMigrations:

    @pytest.mark.parametrize("path", [
        "templates/fragments/history/closed_positions_table.html",
        "templates/fragments/history/order_history_table.html",
        "templates/fragments/history/fills_table.html",
        "templates/fragments/history/pre_trade_table.html",
        "templates/fragments/history/trade_events_table.html",
    ])
    def test_imports_empty_state(self, path):
        src = Path(path).read_text(encoding="utf-8")
        assert 'from "primitives/empty_state.html" import empty_state' in src, (
            f"FE-MED-006 regression: {path} no longer imports EmptyState."
        )

    @pytest.mark.parametrize("path,old_msg", [
        ("templates/fragments/history/closed_positions_table.html",
         "No closed positions found for this period."),
        ("templates/fragments/history/order_history_table.html",
         "No order history found for this period."),
        ("templates/fragments/history/fills_table.html",
         "No trade history found for this period."),
        ("templates/fragments/history/pre_trade_table.html",
         "No pre-trade entries found for this period."),
        ("templates/fragments/history/trade_events_table.html",
         "No trade events found for this period."),
    ])
    def test_old_inline_empty_div_gone(self, path, old_msg):
        """Anti-revert: the old `<div style="color:var(--muted);padding:
        20px 0;...">No X found...</div>` pattern is gone."""
        src = Path(path).read_text(encoding="utf-8")
        old_inline = (
            f'<div style="color:var(--muted);padding:20px 0;'
            f'text-align:center;font-size:.78rem;">{old_msg}</div>'
        )
        assert old_inline not in src, (
            f"FE-MED-006 regression: old inline empty <div> pattern back "
            f"in {path}"
        )

    def test_closed_positions_renders_empty_state_when_no_rows(self):
        env = _make_env()
        tpl = env.get_template(
            "fragments/history/closed_positions_table.html"
        )
        out = tpl.render(
            rows=[], total=0, page=1, per_page=20, total_pages=1,
            search="", sort_by="exit_time_ms", sort_dir="DESC",
            date_from="2026-01-01", date_to="2026-12-31",
        )
        assert 'class="es es-info"' in out
        assert "No closed positions found for this period." in out


class TestDashboardMigration:

    def test_dashboard_body_renders_empty_state_when_no_positions(self):
        src = Path("templates/fragments/dashboard_body.html").read_text(encoding="utf-8")
        assert "empty_state(message=\"No open positions.\")" in src

    def test_old_dashboard_inline_empty_gone(self):
        src = Path("templates/fragments/dashboard_body.html").read_text(encoding="utf-8")
        old = '<div style="text-align:center;padding:24px 0;color:var(--muted);font-size:.78rem;">No open positions.</div>'
        assert old not in src


class TestAnalyticsMigrations:

    @pytest.mark.parametrize("path", [
        "templates/fragments/analytics/pairs_table.html",
        "templates/fragments/analytics/beta_exposure.html",
        "templates/fragments/analytics/funding_tracker.html",
    ])
    def test_imports_empty_state(self, path):
        src = Path(path).read_text(encoding="utf-8")
        assert 'from "primitives/empty_state.html" import empty_state' in src


# ── Regime JS migration (FE-MED-008 partial) ────────────────────────────────

class TestRegimeMigration:

    def _read(self) -> str:
        return Path("templates/regime.html").read_text(encoding="utf-8")

    def test_regime_uses_es_action_class_for_not_backfilled(self):
        """FE-MED-008 visual normalization: the BTC Market Cap +
        Aggregate OI Change cards previously had ad-hoc layouts for
        the not-backfilled state. Now they emit the same .es-action
        markup the primitive defines."""
        src = self._read()
        assert 'class="es es-action"' in src, (
            "FE-MED-008 regression: Regime not-backfilled state no "
            "longer uses .es-action class — visual treatment may have "
            "drifted from the primitive."
        )
        assert "Use Backfill tab" in src

    def test_regime_no_data_in_range_uses_es_info(self):
        """The 'no data in range' state (data exists but filtered out)
        uses info tone — distinct from action-tone 'not backfilled'."""
        src = self._read()
        assert 'class="es es-info"' in src

    def test_regime_old_inline_empty_div_gone(self):
        """Anti-revert: the prior ad-hoc inline style for the
        not-backfilled chart div is gone."""
        src = self._read()
        # The old pattern had `display:flex;align-items:center;
        # justify-content:center;height:100%;font-size:.65rem;
        # color:var(--muted);` inline AND the "Not yet backfilled —
        # use Backfill tab" text directly.
        old_marker = (
            ">Not yet backfilled \\u2014 use Backfill tab<"
        )
        # Use rfind for safety; the new code splits "Not yet backfilled"
        # from "Use Backfill tab" into separate elements
        assert "Not yet backfilled — use Backfill tab" not in src, (
            "FE-MED-008 regression: the old single-string "
            "'Not yet backfilled — use Backfill tab' is back."
        )

    def test_regime_action_cta_calls_showpanel(self):
        """The action CTA is a navigation into the Backfill tab —
        uses the existing showPanel function (not a fictional
        switchTab)."""
        src = self._read()
        # The onclick handler should invoke showPanel('backfill')
        assert "showPanel('backfill')" in src or "showPanel(\\'backfill\\')" in src


# ── README + decision-tree update ───────────────────────────────────────────

class TestReadmeDocumentsEmptyState:

    def _read(self) -> str:
        return Path("templates/primitives/README.md").read_text(encoding="utf-8")

    def test_readme_has_empty_state_section(self):
        assert "EmptyState (Task 124)" in self._read()

    def test_readme_documents_both_tones(self):
        content = self._read()
        assert '"info"' in content
        assert '"action"' in content

    def test_readme_documents_wrapper_semantics_warning(self):
        """The 'not inside <tbody>' warning is load-bearing for
        correct usage. Must be in README."""
        content = self._read()
        assert "tbody" in content.lower() or "<tbody>" in content
        # Some "NOT" / "don't use" framing must be present
        assert "NOT" in content or "not suitable" in content.lower()

    def test_readme_decision_tree_includes_empty_state(self):
        """The decision tree should mention EmptyState alongside
        StatusIndicator as a plain-macro example."""
        content = self._read()
        # Locate the decision tree section
        idx = content.find("Decision tree")
        assert idx > 0
        section = content[idx:idx + 1500]
        assert "EmptyState" in section


# ── Compile pins (MED-047 explicit) ─────────────────────────────────────────

class TestTemplateCompiles:

    @pytest.mark.parametrize("path", [
        "primitives/empty_state.html",
        "fragments/history/closed_positions_table.html",
        "fragments/history/order_history_table.html",
        "fragments/history/fills_table.html",
        "fragments/history/pre_trade_table.html",
        "fragments/history/trade_events_table.html",
        "fragments/dashboard_body.html",
        "fragments/analytics/pairs_table.html",
        "fragments/analytics/beta_exposure.html",
        "fragments/analytics/funding_tracker.html",
        "regime.html",
    ])
    def test_compiles(self, path):
        env = _make_env()
        tpl = env.get_template(path)
        assert tpl is not None

    def test_bundle_a_siblings_still_compile(self):
        """Bundle A.1/A.2/A.3 anti-regression."""
        env = _make_env()
        for path in (
            "primitives/status_indicator.html",
            "primitives/card.html",
            "primitives/table_row.html",
        ):
            assert env.get_template(path) is not None
