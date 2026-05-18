"""
Task 125 regression tests — Bundle A primitive #5 (PeriodSelector) +
FE-MED-007 fix (segmented period-control drift across Regime + History).

PeriodSelector is the third plain-macro primitive in Bundle A
(StatusIndicator and EmptyState were the first two). Parameter-driven
options list + current value. Two transition modes:
on_change_template (JS) and hx_get_template (HTMX). Both may coexist
(HTMX wins at runtime); caller picks one.

Migrations in this task:
  - Regime global "All:" selector (template-side).
  - History page presets (template-side, with dataset.preset →
    dataset.value JS update).
  - Regime per-card signal selectors (JS-rendered — emits same
    .ps + .preset-btn classes the macro emits).

MED-047 discipline: compile + render via Jinja2.

Run: pytest tests/test_task125_period_selector.py -v
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
    return env


def _render_ps(**params):
    env = _make_env()
    src = (
        '{% from "primitives/period_selector.html" import period_selector %}'
        '{{ period_selector('
        '  options=options, current=current,'
        '  on_change_template=on_change_template,'
        '  hx_get_template=hx_get_template,'
        '  extra_btn_attrs=extra_btn_attrs,'
        '  label_prefix=label_prefix,'
        '  id=id, extra_class=extra_class) }}'
    )
    return env.from_string(src).render(
        options=params.get("options", []),
        current=params.get("current", ""),
        on_change_template=params.get("on_change_template", ""),
        hx_get_template=params.get("hx_get_template", ""),
        extra_btn_attrs=params.get("extra_btn_attrs", ""),
        label_prefix=params.get("label_prefix", ""),
        id=params.get("id", ""),
        extra_class=params.get("extra_class", ""),
    )


# ── Macro rendering ──────────────────────────────────────────────────────────

class TestPeriodSelectorRendering:

    def test_renders_each_option_button(self):
        html = _render_ps(
            options=[
                {"value": "30d", "label": "Last 30 days"},
                {"value": "7d",  "label": "Last 7 days"},
            ],
            current="30d",
        )
        assert "Last 30 days" in html
        assert "Last 7 days" in html
        assert 'data-value="30d"' in html
        assert 'data-value="7d"' in html

    def test_current_option_gets_active_class(self):
        html = _render_ps(
            options=[
                {"value": "30d", "label": "A"},
                {"value": "7d",  "label": "B"},
            ],
            current="30d",
        )
        # The active button has 'preset-btn active'
        assert 'class="preset-btn active" data-value="30d"' in html
        # Non-active is bare 'preset-btn'
        assert 'class="preset-btn" data-value="7d"' in html

    def test_unknown_current_marks_nothing_active(self):
        """Defensive: bogus current → no .active class, no crash."""
        html = _render_ps(
            options=[
                {"value": "30d", "label": "A"},
                {"value": "7d",  "label": "B"},
            ],
            current="999",
        )
        assert " active" not in html

    def test_int_value_matches_int_current(self):
        """Int and string values both supported; string-cast comparison."""
        html = _render_ps(
            options=[
                {"value": 30,  "label": "30d"},
                {"value": 365, "label": "1y"},
            ],
            current=365,
        )
        assert 'class="preset-btn active" data-value="365"' in html

    def test_int_value_matches_string_current(self):
        """String-cast comparison: int option vs string current."""
        html = _render_ps(
            options=[{"value": 365, "label": "1y"}],
            current="365",
        )
        assert " active" in html

    def test_on_change_template_interpolates_value_raw(self):
        """{value} interpolated as raw text — caller controls quoting.
        Note: autoescape HTML-encodes single quotes inside attribute
        values to &#39;. Browsers decode at parse time, so the
        runtime JS expression is still setPreset('30d')."""
        html = _render_ps(
            options=[{"value": "30d", "label": "A"}],
            current="30d",
            on_change_template="setPreset('{value}')",
        )
        # Match HTML-escaped form (what's emitted) — browser decodes
        # &#39; back to ' before evaluating the onclick handler.
        assert "onclick=\"setPreset(&#39;30d&#39;)\"" in html

    def test_on_change_template_integer_value_unquoted(self):
        html = _render_ps(
            options=[{"value": 365, "label": "1y"}],
            current=365,
            on_change_template="setAllCardRanges({value},this)",
        )
        assert "onclick=\"setAllCardRanges(365,this)\"" in html

    def test_hx_get_template_interpolates_value(self):
        html = _render_ps(
            options=[{"value": "30d", "label": "A"}],
            current="30d",
            hx_get_template="/fragments/period?p={value}",
        )
        assert 'hx-get="/fragments/period?p=30d"' in html

    def test_both_modes_emit_both_attrs(self):
        """If caller sets both, primitive emits both — HTMX wins at
        runtime. Defensive (no crash), but caller should pick one."""
        html = _render_ps(
            options=[{"value": "30d", "label": "A"}],
            current="30d",
            on_change_template="setPreset('{value}')",
            hx_get_template="/x?p={value}",
        )
        assert "onclick=" in html
        assert "hx-get=" in html

    def test_extra_btn_attrs_pass_through_safe(self):
        html = _render_ps(
            options=[{"value": "30d", "label": "A"}],
            current="30d",
            hx_get_template="/x?p={value}",
            extra_btn_attrs='hx-target="#out" hx-swap="innerHTML"',
        )
        assert 'hx-target="#out"' in html
        assert 'hx-swap="innerHTML"' in html

    def test_label_prefix_renders_ps_label_span(self):
        html = _render_ps(
            options=[{"value": "30d", "label": "A"}],
            current="30d",
            label_prefix="All:",
        )
        assert '<span class="ps-label">All:</span>' in html

    def test_label_prefix_empty_omits_span(self):
        html = _render_ps(
            options=[{"value": "30d", "label": "A"}],
            current="30d",
        )
        assert "ps-label" not in html

    def test_id_and_extra_class_emitted(self):
        html = _render_ps(
            options=[{"value": "30d", "label": "A"}],
            current="30d",
            id="my-picker",
            extra_class="global-range-group special",
        )
        assert 'id="my-picker"' in html
        assert 'class="ps global-range-group special"' in html

    def test_label_html_escaped(self):
        """Autoescape applies to label text."""
        html = _render_ps(
            options=[{"value": "x", "label": "<b>boom</b>"}],
            current="x",
        )
        assert "<b>boom</b>" not in html
        assert "&lt;b&gt;" in html


# ── CSS present in base.html ────────────────────────────────────────────────

class TestPeriodSelectorCssInBase:
    def test_base_has_ps_css(self):
        src = Path("templates/base.html").read_text(encoding="utf-8")
        assert ".ps {" in src
        assert ".ps-label" in src
        assert "FE-MED-007" in src  # anchor


# ── Migration: History presets ──────────────────────────────────────────────

class TestHistoryMigration:

    def _read(self) -> str:
        return Path("templates/history.html").read_text(encoding="utf-8")

    def test_history_imports_period_selector(self):
        assert 'from "primitives/period_selector.html" import period_selector' in self._read()

    def test_history_uses_call_period_selector(self):
        """The 6 hand-rolled <button class="preset-btn" data-preset=...>
        is replaced with a single period_selector call."""
        src = self._read()
        assert "period_selector(" in src

    def test_history_old_hand_rolled_buttons_gone(self):
        """Anti-revert: the explicit `data-preset="..."` attr (used by
        the old hand-rolled buttons) is gone."""
        src = self._read()
        assert "data-preset=" not in src, (
            "FE-MED-007 regression: data-preset attr back — old hand-"
            "rolled History presets reintroduced."
        )

    def test_history_js_reads_dataset_value(self):
        """highlightPreset JS updated to read dataset.value (primitive
        emits data-value)."""
        src = self._read()
        assert "b.dataset.value===active" in src, (
            "FE-MED-007 regression: highlightPreset still reads "
            "dataset.preset — won't match primitive's data-value attr."
        )

    def test_history_renders_six_presets_with_30d_active(self):
        env = _make_env()
        tpl = env.get_template("history.html")
        out = tpl.render(
            active_page="history",
            active_account_id=1,
            active_platform="standalone",
            available_exchanges=[],
            project_name="x", tz_display="UTC", now="2026-05-19",
            accounts=[],
        )
        # Six preset values present
        for v in ("90d", "30d", "15d", "7d", "yesterday", "today"):
            assert f'data-value="{v}"' in out
        # 30d is initial active (default selection)
        assert 'class="preset-btn active" data-value="30d"' in out


# ── Migration: Regime global selector ───────────────────────────────────────

class TestRegimeGlobalMigration:

    def _read(self) -> str:
        return Path("templates/regime.html").read_text(encoding="utf-8")

    def test_regime_imports_period_selector(self):
        assert 'from "primitives/period_selector.html" import period_selector' in self._read()

    def test_regime_global_old_hand_rolled_gone(self):
        """Anti-revert: the old hand-rolled `setAllCardRanges` button
        chain with manual {% for %} is gone."""
        src = self._read()
        # The pre-fix had `class="global-range-btn preset-btn` inline
        assert "global-range-btn preset-btn" not in src, (
            "FE-MED-007 regression: hand-rolled Regime global selector "
            "is back."
        )

    def test_regime_global_uses_label_prefix(self):
        src = self._read()
        # The new migration uses label_prefix="All:" inside the macro call
        assert 'label_prefix="All:"' in src


# ── Migration: Regime per-card JS uses same primitive classes ───────────────

class TestRegimePerCardJsMigration:
    """Regime per-card signal selectors are JS-rendered (in
    buildSignalCards's template literal). Can't call the macro from JS,
    so JS emits the same .ps wrapper + .preset-btn buttons that the
    primitive emits. Shared visual language across server/client."""

    def test_regime_per_card_uses_ps_wrapper(self):
        src = Path("templates/regime.html").read_text(encoding="utf-8")
        # The buildSignalCards inline JS emits `<div class="ps" ...>` around
        # the per-card range buttons
        assert 'class="ps" style="margin-left:auto;"' in src

    def test_regime_per_card_emits_data_value_attr(self):
        """Per-card buttons emit data-value too — matches primitive
        convention. (Old hand-roll didn't have data-value.)"""
        src = Path("templates/regime.html").read_text(encoding="utf-8")
        assert 'data-value="${d}"' in src


# ── README documentation pins ───────────────────────────────────────────────

class TestReadmeDocumentsPeriodSelector:

    def _read(self) -> str:
        return Path("templates/primitives/README.md").read_text(encoding="utf-8")

    def test_readme_has_period_selector_section(self):
        assert "PeriodSelector (Task 125)" in self._read()

    def test_readme_decision_tree_includes_period_selector(self):
        content = self._read()
        idx = content.find("Decision tree")
        assert idx > 0
        section = content[idx:idx + 1500]
        assert "PeriodSelector" in section

    def test_readme_documents_both_transition_modes(self):
        content = self._read()
        assert "on_change_template" in content
        assert "hx_get_template" in content


# ── Compile pins (MED-047) ──────────────────────────────────────────────────

class TestTemplateCompiles:

    @pytest.mark.parametrize("path", [
        "primitives/period_selector.html",
        "regime.html",
        "history.html",
        "base.html",
    ])
    def test_compiles(self, path):
        env = _make_env()
        assert env.get_template(path) is not None

    def test_bundle_a_siblings_still_compile(self):
        """Bundle A.1/A.2/A.3/A.4 anti-regression."""
        env = _make_env()
        for path in (
            "primitives/status_indicator.html",
            "primitives/card.html",
            "primitives/table_row.html",
            "primitives/empty_state.html",
        ):
            assert env.get_template(path) is not None
