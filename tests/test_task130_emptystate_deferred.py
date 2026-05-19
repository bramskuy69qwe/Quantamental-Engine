"""
Task 130 regression tests — close out the Task 124-deferred EmptyState
migrations.

Two sites migrated:
  - equity_ohlc.html (32px → padding="loose")
  - exchange_table.html (16px → default padding="default", with
    left→center alignment shift to converge with primitive convention)

Both rely on the Task 129 EmptyState API extension (padding param).

Decision recorded: NO "medium" (16px) preset added — exchange_table's
16px was a single-consumer outlier; per Bundle A defer-discipline,
single-consumer API extensions are over-engineering. Wait for a second
consumer.

Run: pytest tests/test_task130_emptystate_deferred.py -v
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


# ── equity_ohlc.html migration (padding="loose") ────────────────────────────

class TestEquityOhlcMigration:

    def _read(self) -> str:
        return Path("templates/fragments/equity_ohlc.html").read_text(encoding="utf-8")

    def test_imports_empty_state(self):
        assert 'from "primitives/empty_state.html" import empty_state' in self._read()

    def test_uses_loose_padding(self):
        """Full-page empty state — uses padding="loose" (32px) preset."""
        src = self._read()
        assert 'empty_state(message="No snapshot data available yet.", padding="loose")' in src

    def test_old_inline_empty_div_gone(self):
        """Anti-revert: the prior `<div style="...padding:32px 0;
        text-align:center;">No snapshot...</div>` pattern is gone."""
        src = self._read()
        old = '<div style="color:var(--muted);font-size:.78rem;padding:32px 0;text-align:center;">No snapshot data available yet.</div>'
        assert old not in src

    def test_renders_es_loose_when_no_candles(self):
        """End-to-end: candles=None empty branch renders the .es-loose class."""
        env = _make_env()
        src = '{% include "fragments/equity_ohlc.html" %}'
        out = env.from_string(src).render(candles=None, active_tf="1m")
        assert "es-loose" in out
        assert "No snapshot data available yet." in out
        # Old inline empty div gone
        assert 'padding:32px 0;text-align:center;">No snapshot' not in out


# ── exchange_table.html migration (default padding + alignment shift) ───────

class TestExchangeTableMigration:

    def _read(self) -> str:
        return Path("templates/fragments/history/exchange_table.html").read_text(encoding="utf-8")

    def test_imports_empty_state(self):
        assert 'from "primitives/empty_state.html" import empty_state' in self._read()

    def test_uses_default_padding(self):
        """Default padding (20px) — accepts 4px shift from prior 16px
        rather than adding a single-consumer 'medium' preset."""
        src = self._read()
        # Default padding means no padding= param passed (or padding="default")
        assert 'empty_state(message="No position history found for this period.")' in src
        # Should NOT be using tight or loose for this site
        assert 'padding="tight"' not in src
        assert 'padding="loose"' not in src

    def test_old_inline_empty_div_gone(self):
        """Anti-revert: the prior 16px-padding left-aligned `<div>`
        pattern is gone."""
        src = self._read()
        old = '<div style="color:var(--muted);font-size:.78rem;padding:16px 0;">No position history found for this period.</div>'
        assert old not in src

    def test_renders_default_es_when_no_rows(self):
        """End-to-end: rows=[] empty branch renders default EmptyState
        (no es-tight, no es-loose modifier)."""
        env = _make_env()
        tpl = env.get_template("fragments/history/exchange_table.html")
        out = tpl.render(
            rows=[], total=0, page=1, per_page=20, total_pages=1,
            search="", sort_by="exit_time_ms", sort_dir="DESC",
            date_from="2026-01-01", date_to="2026-12-31",
        )
        assert "No position history found for this period." in out
        assert 'class="es es-info"' in out
        # No padding modifier — converges to centered, 20px primitive convention
        assert "es-tight" not in out
        assert "es-loose" not in out


# ── Anti-regression: EmptyState API extension intact ────────────────────────

class TestEmptyStateApiIntact:
    """The Task 129 API extension (padding param) must still work — no
    drift from these migrations."""

    def test_padding_default_no_modifier(self):
        env = _make_env()
        src = (
            '{% from "primitives/empty_state.html" import empty_state %}'
            '{{ empty_state("test", padding="default") }}'
        )
        html = env.from_string(src).render()
        assert "es-tight" not in html
        assert "es-loose" not in html

    def test_padding_tight_emits_modifier(self):
        env = _make_env()
        src = (
            '{% from "primitives/empty_state.html" import empty_state %}'
            '{{ empty_state("test", padding="tight") }}'
        )
        html = env.from_string(src).render()
        assert "es-tight" in html

    def test_padding_loose_emits_modifier(self):
        env = _make_env()
        src = (
            '{% from "primitives/empty_state.html" import empty_state %}'
            '{{ empty_state("test", padding="loose") }}'
        )
        html = env.from_string(src).render()
        assert "es-loose" in html


# ── Compile pins (MED-047) ──────────────────────────────────────────────────

class TestTemplateCompiles:

    @pytest.mark.parametrize("path", [
        "fragments/equity_ohlc.html",
        "fragments/history/exchange_table.html",
        "primitives/empty_state.html",
    ])
    def test_compiles(self, path):
        env = _make_env()
        tpl = env.get_template(path)
        assert tpl is not None
