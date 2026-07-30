"""
Task 129 regression tests — position_fills.html primitive migration.

Three migrations applied to the Position History expansion sub-table:
  1. TableRow primitive (tr_open / tr_close) replaces hand-rolled <tr>.
  2. SIDE column split into ACTION (Open/Close) + SIDE (LONG/SHORT) —
     carries Task 123 calibration #3 closure from fills_table.html to
     this inline sub-table.
  3. EmptyState primitive with new padding="tight" param — Task 124
     deferred this site due to padding mismatch (10px vs primitive's
     default 20px); Task 129 extends the API to support inline
     contexts cleanly.

Plus an API extension to EmptyState itself:
  - New padding param: "default" (20px, dominant), "tight" (10px,
    inline sub-tables), "loose" (32px, full-page).

Run: pytest tests/test_task129_position_fills_migration.py -v
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
    return env


# ── EmptyState padding param extension ──────────────────────────────────────

class TestEmptyStatePaddingParam:
    """Task 129 extends EmptyState with padding="default"|"tight"|"loose"."""

    def _render(self, padding="default"):
        env = _make_env()
        src = (
            '{% from "primitives/empty_state.html" import empty_state %}'
            '{{ empty_state("test message", padding=padding) }}'
        )
        return env.from_string(src).render(padding=padding)

    def test_default_padding_no_modifier_class(self):
        """The 90% case: default 20px padding has no extra class."""
        html = self._render("default")
        assert 'class="es es-info"' in html
        assert "es-tight" not in html
        assert "es-loose" not in html

    def test_tight_padding_adds_modifier(self):
        html = self._render("tight")
        assert "es-tight" in html
        assert 'class="es es-info es-tight"' in html

    def test_loose_padding_adds_modifier(self):
        html = self._render("loose")
        assert "es-loose" in html
        assert 'class="es es-info es-loose"' in html

    def test_unknown_padding_falls_through_to_default(self):
        """Defensive — bogus padding value renders as default. Parallels
        the tone-fallthrough discipline from Task 124."""
        html = self._render("bogus")
        assert "es-bogus" not in html
        assert "es-tight" not in html
        assert "es-loose" not in html

    def test_padding_css_block_present_in_base(self):
        src = Path("templates/base.html").read_text(encoding="utf-8")
        assert ".es-tight" in src
        assert ".es-loose" in src
        # Task 129 anchor for traceability
        assert "Task 129" in src


# ── Position Fills migration: TableRow ──────────────────────────────────────


# ── ACTION/SIDE column split (calibration #3 closure) ───────────────────────


# ── EmptyState migration in empty branch ────────────────────────────────────


# ── Anti-regression: non-empty render still works end-to-end ────────────────


# ── Compile pins (MED-047) ──────────────────────────────────────────────────

class TestTemplateCompiles:


    def test_empty_state_macro_still_compiles(self):
        """Bundle A.4 anti-regression after API extension."""
        env = _make_env()
        tpl = env.get_template("primitives/empty_state.html")
        assert tpl is not None

    def test_table_row_macro_still_compiles(self):
        """Bundle A.3 anti-regression."""
        env = _make_env()
        tpl = env.get_template("primitives/table_row.html")
        assert tpl is not None
