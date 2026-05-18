"""
Task 121 regression tests — Bundle A primitive #1 + FE-HIGH-001 fix.

StatusIndicator macro lives at `templates/primitives/status_indicator.html`
and is consumed at the FE-HIGH-001 site (`templates/base.html` plugin
indicator) to replace the bare ``◌ Plugin`` / ``● Plugin`` markup that
visually grouped with the adjacent WS status into a misleading
composite ("engine offline · 437ms").

MED-047 discipline: render the macro via jinja2.Environment, assert on
the rendered HTML — not source-string greps. Source-string pins are
still used for the FE-HIGH-001 site wiring (where the macro is
imported + called inside base.html).

Run: pytest tests/test_task121_status_indicator.py -v
"""
from __future__ import annotations

import inspect
from pathlib import Path

import jinja2
import pytest


def _make_env() -> jinja2.Environment:
    """Build a Jinja2 env rooted at the templates dir, matching how the
    engine loads templates at runtime."""
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    return env


def _render_indicator(severity, label, value="", dot=True, id=""):
    env = _make_env()
    # The macro lives in primitives/status_indicator.html; render via a
    # small wrapper template that imports + calls it. This is the same
    # shape consumers use.
    src = (
        '{% from "primitives/status_indicator.html" import status_indicator %}'
        "{{ status_indicator(severity, label, value=value, dot=dot, id=id) }}"
    )
    tpl = env.from_string(src)
    return tpl.render(
        severity=severity, label=label, value=value, dot=dot, id=id
    )


# ── Macro renders: severity × value × dot × id ────────────────────────────────

class TestStatusIndicatorRendering:

    def test_severity_class_applied_for_each_of_the_five(self):
        """Load-bearing pin: the five severity words map 1:1 to
        si-{severity} classes. Adding a 6th severity is a Bundle A
        convention change — should require a deliberate audit-doc /
        README update, not slip in via a typo."""
        for sev in ("success", "warning", "error", "info", "neutral"):
            html = _render_indicator(sev, "Foo")
            assert f"si-{sev}" in html, (
                f"severity {sev!r} doesn't apply si-{sev} class"
            )
            # Always carries the base .si class too
            assert 'class="si si-' in html

    def test_unknown_severity_falls_through_to_neutral(self):
        """Defensive: a typo or future-severity-word renders as neutral
        rather than emitting an unknown class name. Prevents
        unstylesheeted markup from shipping silently."""
        html = _render_indicator("bogus", "Foo")
        assert "si-neutral" in html
        assert "si-bogus" not in html

    def test_label_rendered_inside_si_label_span(self):
        html = _render_indicator("success", "Quantower")
        assert '<span class="si-label">Quantower</span>' in html

    def test_value_rendered_when_supplied(self):
        html = _render_indicator("success", "Quantower", value="Connected")
        assert '<span class="si-value">Connected</span>' in html
        # data-has-value attribute is the macro's "value-present" marker —
        # JS / future selectors can target it.
        assert 'data-has-value="1"' in html

    def test_value_span_absent_when_empty(self):
        """Empty value omits the entire .si-value span. Prevents an
        empty separator from rendering when there's nothing after the
        label."""
        html = _render_indicator("neutral", "Quantower")
        assert "si-value" not in html
        assert "data-has-value" not in html

    def test_dot_rendered_by_default(self):
        html = _render_indicator("success", "Foo")
        assert '<span class="si-dot" aria-hidden="true">' in html

    def test_dot_suppressed_when_dot_false(self):
        html = _render_indicator("success", "Foo", dot=False)
        assert "si-dot" not in html

    def test_id_attribute_emitted_when_supplied(self):
        html = _render_indicator("neutral", "Foo", id="plugin-indicator")
        assert 'id="plugin-indicator"' in html

    def test_id_attribute_absent_when_empty(self):
        """An empty id string shouldn't emit `id=""` — would clutter
        the DOM and confuse JS selectors."""
        html = _render_indicator("neutral", "Foo")
        assert 'id="' not in html

    def test_label_is_html_escaped(self):
        """XSS guard: the autoescape env (matches runtime config) must
        escape angle brackets in the label."""
        html = _render_indicator("neutral", "<script>alert(1)</script>")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html


# ── FE-HIGH-001 migration: header site uses the primitive ────────────────────

class TestFeHigh001HeaderMigration:
    """The plugin indicator in base.html must now use the
    StatusIndicator primitive, not the bare `◌ Plugin` markup."""

    def _base_html(self) -> str:
        return Path("templates/base.html").read_text(encoding="utf-8")

    def test_base_html_imports_status_indicator_primitive(self):
        src = self._base_html()
        assert 'from "primitives/status_indicator.html" import status_indicator' in src, (
            "FE-HIGH-001 regression: base.html no longer imports the "
            "StatusIndicator macro. The plugin indicator may have "
            "regressed to the old ◌ Plugin markup."
        )

    def test_base_html_calls_status_indicator_for_plugin(self):
        src = self._base_html()
        # The macro call sets id="plugin-indicator" for JS targeting
        assert 'id="plugin-indicator"' in src
        assert 'label="Quantower"' in src

    def test_old_plugin_glyph_text_removed(self):
        """Anti-revert: the old `● Plugin` / `◌ Plugin` text strings
        must NOT appear in base.html anymore. The new design uses
        full words ('Connected' / 'Disconnected') via the value slot."""
        src = self._base_html()
        assert "● Plugin" not in src, (
            "FE-HIGH-001 regression: the old ● Plugin glyph text is "
            "back in base.html — the StatusIndicator migration was "
            "reverted."
        )
        assert "◌ Plugin" not in src

    def test_js_sets_value_text_via_si_value_selector(self):
        """The JS must drive the new DOM: querySelector('.si-value')
        and textContent assignment to 'Connected' / 'Disconnected'."""
        src = self._base_html()
        assert ".si-value" in src
        assert "'Connected'" in src
        assert "'Disconnected'" in src

    def test_js_swaps_severity_classes(self):
        """JS swaps `.si-success` / `.si-error` on the indicator
        wrapper. The helper `setSeverity()` is the convention — future
        JS that interacts with StatusIndicators should reuse it."""
        src = self._base_html()
        assert "setSeverity" in src
        assert "si-success" in src
        assert "si-error" in src
        assert "si-neutral" in src

    def test_primitives_css_block_present(self):
        """The .si CSS rules must live in base.html's <style> block
        under the Primitives section."""
        src = self._base_html()
        assert "── Primitives" in src or "Primitives (Bundle A" in src
        # Anchor class rules
        assert ".si {" in src
        assert ".si-dot" in src
        assert ".si-success" in src


# ── README convention doc ───────────────────────────────────────────────────

class TestPrimitivesReadme:
    """The convention doc must exist + capture the 5-severity vocab +
    the macro/include decision tree. Future Bundle A tasks follow it."""

    def test_readme_exists(self):
        assert Path("templates/primitives/README.md").exists()

    def test_readme_documents_severity_vocab(self):
        content = Path("templates/primitives/README.md").read_text(encoding="utf-8")
        for sev in ("success", "warning", "error", "info", "neutral"):
            assert sev in content, f"severity {sev!r} not documented in README"

    def test_readme_lists_status_indicator(self):
        content = Path("templates/primitives/README.md").read_text(encoding="utf-8")
        assert "StatusIndicator" in content
        assert "Task 121" in content


# ── Macro template still compiles (MED-047 explicit pin) ────────────────────

class TestPrimitiveTemplateCompiles:
    def test_status_indicator_template_compiles(self):
        env = _make_env()
        tpl = env.get_template("primitives/status_indicator.html")
        assert tpl is not None

    def test_base_html_still_compiles_after_migration(self):
        """The migration touched base.html — ensure it still parses.
        (MED-047 pattern: template-touching changes need a compile
        test, not just source greps.)"""
        env = _make_env()
        tpl = env.get_template("base.html")
        assert tpl is not None
