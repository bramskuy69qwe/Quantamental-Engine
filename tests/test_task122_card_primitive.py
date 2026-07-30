"""
Task 122 regression tests — Bundle A primitive #2 (Card) +
FE-MED-001 fix (Analytics card-rhythm migration).

Card is the first slot-content primitive. Uses Jinja2's
``{% call %}`` + ``caller()`` mechanism for body content, with title
/ subtitle / footer / padding as keyword params. Defaults to tight
History-matching rhythm (`.card-p8`) so Analytics no longer drifts
loose against the rest of the engine.

MED-047 discipline: compile + render tests, not source-string greps.

Run: pytest tests/test_task122_card_primitive.py -v
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
    return env


def _render_card(body, **params):
    """Render a Card via {% call %} with the given body markup."""
    env = _make_env()
    src = (
        '{% from "primitives/card.html" import card %}'
        '{% call card('
        'title=title, subtitle=subtitle, footer=footer, padding=padding'
        ') %}' + body + '{% endcall %}'
    )
    tpl = env.from_string(src)
    return tpl.render(
        title=params.get("title", ""),
        subtitle=params.get("subtitle", ""),
        footer=params.get("footer", ""),
        padding=params.get("padding", "tight"),
    )


# ── Card macro: structural rendering ─────────────────────────────────────────

class TestCardRendering:

    def test_card_with_title_only_renders_header_with_sec_lbl(self):
        """Title param maps to .sec-lbl class (matching the existing
        section-label chrome elsewhere in the engine)."""
        html = _render_card("<p>body</p>", title="Equity & PnL")
        assert "card-header" in html
        # sec-lbl is the engine-wide section-label class; Card title uses it
        assert "sec-lbl" in html
        assert "Equity &amp; PnL" in html  # autoescaped &
        # No card-subtitle when subtitle is empty
        assert "card-subtitle" not in html

    def test_card_with_title_and_subtitle_renders_both(self):
        html = _render_card("<p>body</p>", title="Volume", subtitle="October 2025")
        assert "Volume" in html
        assert "October 2025" in html
        assert "card-subtitle" in html

    def test_card_without_title_or_subtitle_omits_header(self):
        """An untitled card renders just `.card-body` — no empty header
        row."""
        html = _render_card("<p>body</p>")
        assert "card-header" not in html
        assert "card-body" in html
        assert "<p>body</p>" in html

    def test_card_body_renders_caller_content(self):
        """The {% call %} body becomes the .card-body content via
        caller()."""
        body = '<div class="my-grid">grid content</div>'
        html = _render_card(body, title="X")
        assert "card-body" in html
        assert 'class="my-grid">grid content</div>' in html

    def test_card_with_footer_renders_footer_row(self):
        html = _render_card("body", title="X", footer='<a href="#">More</a>')
        assert "card-footer" in html
        # footer is rendered via | safe, so the anchor tag passes through
        assert '<a href="#">More</a>' in html

    def test_card_without_footer_omits_footer_row(self):
        html = _render_card("body", title="X")
        assert "card-footer" not in html

    def test_tight_padding_default_applies_card_p8(self):
        """Default padding is tight (History rhythm) via the existing
        .card-p8 utility class. New code uses tight."""
        html = _render_card("body", title="X")
        assert "card-p8" in html

    def test_loose_padding_omits_card_p8(self):
        """Back-compat: padding='loose' falls back to the original
        .card default. New code should NOT use loose."""
        html = _render_card("body", title="X", padding="loose")
        assert "card-p8" not in html
        # Still has the base .card class
        assert 'class="card ' in html or 'class="card"' in html

    def test_html_in_title_is_escaped(self):
        """XSS guard: title goes through autoescape."""
        html = _render_card("body", title="<script>alert(1)</script>")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_html_in_footer_is_safe_passthrough(self):
        """Footer accepts raw HTML via |safe (documented in macro
        docstring). Caller responsible for escaping user input."""
        html = _render_card("body", title="X",
                            footer='<button class="btn">Edit</button>')
        assert '<button class="btn">Edit</button>' in html


# ── FE-MED-001 migration: Analytics overview uses Card ──────────────────────


# ── Card primitives CSS shipped in base.html ─────────────────────────────────

class TestCardCssInBase:
    """The .card-header / .card-body / .card-footer / .card-title /
    .card-subtitle rules must live in base.html primitives section."""

    def test_base_has_card_primitive_css_block(self):
        src = Path("templates/base.html").read_text(encoding="utf-8")
        assert ".card-header" in src
        assert ".card-body" in src
        assert ".card-footer" in src
        assert ".card-subtitle" in src
        # Anchored under the Card primitive section comment for traceability
        assert "FE-MED-001" in src


# ── README + CLAUDE.md updates ──────────────────────────────────────────────

class TestDocsUpdates:

    def test_readme_documents_card_primitive(self):
        content = Path("templates/primitives/README.md").read_text(encoding="utf-8")
        assert "Card (Task 122)" in content
        assert "{% call card(" in content
        # README explains the slot pattern choice
        assert "Slot pattern" in content or "caller()" in content

    def test_readme_documents_jinja_nested_comment_gotcha(self):
        content = Path("templates/primitives/README.md").read_text(encoding="utf-8")
        # The gotcha section from Task 121 should be preserved + extended
        assert "Nested" in content or "nested" in content
        assert "{# #}" in content or "{#" in content

    def test_claude_md_has_nested_comment_gotcha(self):
        content = Path("CLAUDE.md").read_text(encoding="utf-8")
        assert "nested-comment" in content or "nested comment" in content
        assert "MED-047" in content  # cross-referenced


# ── Compile pins (MED-047 explicit) ─────────────────────────────────────────

class TestTemplateCompiles:

    def test_card_macro_compiles(self):
        env = _make_env()
        tpl = env.get_template("primitives/card.html")
        assert tpl is not None


    def test_status_indicator_macro_still_compiles(self):
        """Anti-regression for Task 121 — the sister primitive's
        macro file must still load (Card's CSS addition didn't break
        the primitives directory structure)."""
        env = _make_env()
        tpl = env.get_template("primitives/status_indicator.html")
        assert tpl is not None
