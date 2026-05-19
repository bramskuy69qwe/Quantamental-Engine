"""
Task 134 regression tests — FE-MED-019 htmx 5xx target-element handling
+ EmptyState `tone="error"` extension.

Task 108 added the FE-MED-015 global toast handler. FE-MED-019 closes
the remaining gap: the htmx target element stayed on its pre-swap
"Loading..." text indefinitely after the toast auto-dismissed. Task
134 extends the handler to ALSO swap the target's content with an
EmptyState error-tone fragment containing a Retry button.

Also extends EmptyState with `tone="error"` (third tone — second
consumer pattern from Bundle A; vocab now complete).

Source-pin tests (the handler is a <script> block inside base.html;
can't render-test JS execution without a browser).

Run: pytest tests/test_task134_htmx_error_target_swap.py -v
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


# ── EmptyState tone="error" extension ───────────────────────────────────────

class TestEmptyStateErrorTone:
    """Third tone added: error. Visual = --red palette. Mirrors info +
    action with consistent defensive fallthrough."""

    def _render(self, **kw):
        env = _make_env()
        src = (
            '{% from "primitives/empty_state.html" import empty_state %}'
            '{{ empty_state(message=message, tone=tone, '
            'action_label=action_label, action_url=action_url) }}'
        )
        return env.from_string(src).render(
            message=kw.get("message", "x"),
            tone=kw.get("tone", "info"),
            action_label=kw.get("action_label", ""),
            action_url=kw.get("action_url", ""),
        )

    def test_error_tone_applies_es_error_class(self):
        html = self._render(message="Failed.", tone="error")
        assert 'class="es es-error"' in html
        assert ">Failed.</div>" in html

    def test_error_tone_with_action_url_renders_retry_anchor(self):
        html = self._render(
            message="Couldn't load.",
            tone="error",
            action_label="Retry",
            action_url="/fragments/foo",
        )
        assert 'class="es-action"' in html
        assert 'href="/fragments/foo"' in html
        assert ">Retry</a>" in html

    def test_error_tone_with_action_attrs_only_renders_button(self):
        """No action_url + action_label set → <button>. Matches existing
        action-tone behavior (action_attrs path)."""
        env = _make_env()
        src = (
            '{% from "primitives/empty_state.html" import empty_state %}'
            '{{ empty_state(message="x", tone="error", '
            'action_label="Retry", '
            'action_attrs=\'hx-get="/r" hx-target="#out"\') }}'
        )
        out = env.from_string(src).render()
        assert "<button" in out
        assert 'hx-get="/r"' in out
        assert 'hx-target="#out"' in out

    def test_unknown_tone_still_falls_through_to_info(self):
        """Defensive fallthrough preserved across the tone extension —
        adding 'error' to allowed values doesn't break the bogus-value
        guard."""
        html = self._render(message="x", tone="bogus")
        assert 'class="es es-info"' in html
        assert "es-bogus" not in html

    def test_info_and_action_tones_unchanged(self):
        """Bundle A.4 anti-regression — info and action tones still
        emit their expected classes."""
        info_html = self._render(message="x", tone="info")
        assert 'class="es es-info"' in info_html
        action_html = self._render(message="x", tone="action")
        assert 'class="es es-action"' in action_html


# ── EmptyState error CSS ────────────────────────────────────────────────────

class TestEmptyStateErrorCss:

    def test_base_has_es_error_css(self):
        src = Path("templates/base.html").read_text(encoding="utf-8")
        assert ".es-error" in src
        # Specifically the message + action color overrides
        assert ".es-error .es-msg" in src
        # Anchor for traceability
        assert "Task 134" in src or "FE-MED-019" in src

    def test_es_error_uses_red_palette_token(self):
        src = Path("templates/base.html").read_text(encoding="utf-8")
        idx = src.find(".es-error .es-msg")
        assert idx > 0
        window = src[idx:idx + 200]
        # Either var(--red) or the red rgba hover
        assert "var(--red)" in window


# ── htmx handler target-swap extension ──────────────────────────────────────

class TestHtmxHandlerTargetSwap:
    """The global htmx:responseError + htmx:sendError handlers (Task
    108 originals) gained target-element swap logic in Task 134. Both
    toast (FE-MED-015) AND target swap (FE-MED-019) fire on each
    error event."""

    def _read(self) -> str:
        return Path("templates/base.html").read_text(encoding="utf-8")

    def test_handler_block_has_fe_med_019_anchor(self):
        src = self._read()
        assert "FE-MED-019" in src

    def test_response_error_handler_still_calls_show_error_toast(self):
        """FE-MED-015 anti-regression: toast still fires on response
        error. Locate the responseError listener and confirm it still
        calls showError()."""
        src = self._read()
        idx = src.find("htmx:responseError")
        assert idx > 0
        # Window covers the response-error handler body
        window = src[idx:idx + 1200]
        assert "showError(" in window

    def test_response_error_handler_also_swaps_target(self):
        """FE-MED-019: response-error handler now also calls
        swapTargetWithError() (defined in same script block)."""
        src = self._read()
        idx = src.find("htmx:responseError")
        window = src[idx:idx + 1200]
        assert "swapTargetWithError(" in window

    def test_send_error_handler_also_swaps_target(self):
        """FE-MED-019: send-error path (network failures) also swaps."""
        src = self._read()
        idx = src.find("htmx:sendError")
        window = src[idx:idx + 1200]
        assert "swapTargetWithError(" in window
        assert "showError(" in window

    def test_build_error_fragment_emits_es_error_classes(self):
        """The JS-built error fragment uses the same .es-* classes the
        macro emits — shared visual language pattern (Tasks 124, 125)."""
        src = self._read()
        idx = src.find("buildErrorFragment")
        assert idx > 0
        window = src[idx:idx + 800]
        assert 'class="es es-error"' in window
        assert 'class="es-msg"' in window
        assert 'class="es-action"' in window

    def test_retry_button_re_fires_htmx_ajax(self):
        """The retry button's onclick should re-fire htmx.ajax with
        the original (verb, path, target, swap). Installs a uniquely
        named retry function so the onclick can reference it."""
        src = self._read()
        # The installRetry helper is the retry-wiring site
        idx = src.find("installRetry")
        assert idx > 0
        # Range covers the helper body
        window = src[idx:idx + 1000]
        assert "window.htmx.ajax" in window
        # Re-fire preserves verb, path, target, swap
        assert "verb" in window
        assert "path" in window
        assert "target" in window

    def test_message_escape_helper_present(self):
        """The JS-built fragment must HTML-escape the message string —
        no XSS via error responses that include HTML metacharacters."""
        src = self._read()
        # The _esc helper escapes user-derived content
        assert "function _esc(" in src
        idx = src.find("function _esc(")
        window = src[idx:idx + 400]
        # The standard HTML-escape character mapping
        assert "&amp;" in window
        assert "&lt;" in window
        assert "&gt;" in window


# ── README docs ─────────────────────────────────────────────────────────────

class TestReadmeDocsErrorTone:
    """README must document the third tone and its use case."""

    def _read(self) -> str:
        return Path("templates/primitives/README.md").read_text(encoding="utf-8")

    def test_readme_lists_error_tone(self):
        content = self._read()
        # Error tone explicitly mentioned in the tone parameter docs
        assert '"error"' in content
        # And the use case (htmx:responseError target swap)
        assert "htmx" in content.lower()


# ── Compile pins (MED-047) ──────────────────────────────────────────────────

class TestTemplateCompiles:

    @pytest.mark.parametrize("path", [
        "primitives/empty_state.html",
        "base.html",
    ])
    def test_compiles(self, path):
        env = _make_env()
        tpl = env.get_template(path)
        assert tpl is not None

    def test_bundle_a_siblings_still_compile(self):
        """Tasks 121-125 primitive anti-regression — extending
        EmptyState with a tone shouldn't ripple."""
        env = _make_env()
        for path in (
            "primitives/status_indicator.html",
            "primitives/card.html",
            "primitives/table_row.html",
            "primitives/period_selector.html",
        ):
            assert env.get_template(path) is not None
