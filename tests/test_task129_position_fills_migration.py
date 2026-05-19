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


def _render_position_fills(fills):
    env = _make_env()
    src = '{% include "fragments/history/position_fills.html" %}'
    return env.from_string(src).render(fills=fills)


def _sample_fill(**overrides):
    base = {
        "id": 1, "is_close": False, "direction": "LONG",
        "timestamp_ms": 1, "exchange_order_id": "abc123def456",
        "price": 60000.0, "quantity": 1.0, "fee": 0.1,
        "fee_asset": "USDT", "role": "maker", "realized_pnl": 0,
        "exec_link_status": "linked", "exec_match_count": 1,
    }
    base.update(overrides)
    return base


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

class TestPositionFillsTableRow:

    def test_position_fills_imports_table_row(self):
        src = Path("templates/fragments/history/position_fills.html").read_text(encoding="utf-8")
        assert 'from "primitives/table_row.html" import tr_open, tr_close' in src

    def test_position_fills_uses_tr_open_close(self):
        src = Path("templates/fragments/history/position_fills.html").read_text(encoding="utf-8")
        assert "{{ tr_open() }}" in src
        assert "{{ tr_close() }}" in src

    def test_position_fills_renders_with_tr_p_class(self):
        out = _render_position_fills([_sample_fill()])
        assert 'class="tr-p"' in out

    def test_old_bare_tr_pattern_gone_in_data_loop(self):
        """Anti-revert: bare `<tr>` inside the for-loop body removed.
        The `<thead><tr>` header and the `<tr id="exec-link-...">`
        expansion-panel row stay — those are not data rows."""
        src = Path("templates/fragments/history/position_fills.html").read_text(encoding="utf-8")
        # Locate the for-loop body
        loop_start = src.find("{% for f in fills %}")
        loop_end = src.find("{% endfor %}")
        assert loop_start > 0 and loop_end > loop_start
        body = src[loop_start:loop_end]
        # Exec-link expansion <tr id="..."> is still present
        assert 'id="exec-link-' in body
        # But bare `<tr>\n          <td` is gone — the data row uses tr_open()
        assert "<tr>\n          <td " not in body


# ── ACTION/SIDE column split (calibration #3 closure) ───────────────────────

class TestActionSideColumnSplit:

    def test_action_column_header_added(self):
        src = Path("templates/fragments/history/position_fills.html").read_text(encoding="utf-8")
        # New header in <thead>
        assert "<th style=\"font-size:.58rem;\">Action</th>" in src

    def test_old_compound_side_label_gone(self):
        """Anti-revert: the prior `side_label = "Close " ~ dir` /
        `"Open " ~ dir` construction must be absent."""
        src = Path("templates/fragments/history/position_fills.html").read_text(encoding="utf-8")
        assert 'side_label = "Close "' not in src
        assert 'side_label = "Open "' not in src

    def test_render_open_long_renders_two_single_color_cells(self):
        """Open LONG fill: ACTION cell = 'Open' (pos-long), SIDE cell =
        'LONG' (pos-long)."""
        out = _render_position_fills([_sample_fill(is_close=False, direction="LONG")])
        # Old compound label absent
        assert "Open LONG" not in out
        # New single-word cells
        assert ">Open<" in out
        assert ">LONG<" in out
        # Both cells colored pos-long (green) for Open + LONG
        # Each cell has its own pos-long class on the <td>
        assert 'class="pos-long" style="font-weight:700;">Open<' in out
        assert 'class="pos-long" style="font-weight:700;">LONG<' in out

    def test_render_close_short_renders_two_single_color_cells(self):
        """Close SHORT fill: ACTION cell = 'Close' (pos-short — exiting
        exposure is bearish-coded), SIDE cell = 'SHORT' (pos-short)."""
        out = _render_position_fills([_sample_fill(is_close=True, direction="SHORT")])
        assert "Close SHORT" not in out
        assert 'class="pos-short" style="font-weight:700;">Close<' in out
        assert 'class="pos-short" style="font-weight:700;">SHORT<' in out

    def test_exec_link_row_colspan_updated_to_ten(self):
        """The split added a column, so the exec-link expansion-row's
        colspan must go from 9 → 10. Otherwise the expansion drawer
        doesn't span the full row."""
        src = Path("templates/fragments/history/position_fills.html").read_text(encoding="utf-8")
        assert 'colspan="10"' in src
        assert 'colspan="9"' not in src

    def test_action_color_logic_open_long_green_close_long_red(self):
        """ACTION color logic matches fills_table.html post-Task-123:
        Open → pos-long (green, establishing exposure),
        Close → pos-short (red, exiting exposure)."""
        out = _render_position_fills([
            _sample_fill(is_close=False, direction="LONG", id=1),
            _sample_fill(is_close=True, direction="LONG", id=2,
                         realized_pnl=100.0, exec_link_status=None),
        ])
        # Open cell is pos-long
        assert 'class="pos-long" style="font-weight:700;">Open<' in out
        # Close cell is pos-short
        assert 'class="pos-short" style="font-weight:700;">Close<' in out


# ── EmptyState migration in empty branch ────────────────────────────────────

class TestEmptyStateMigration:

    def test_position_fills_imports_empty_state(self):
        src = Path("templates/fragments/history/position_fills.html").read_text(encoding="utf-8")
        assert 'from "primitives/empty_state.html" import empty_state' in src

    def test_empty_branch_uses_empty_state_with_tight_padding(self):
        src = Path("templates/fragments/history/position_fills.html").read_text(encoding="utf-8")
        # The empty branch should call empty_state(...) with padding="tight"
        assert 'empty_state(message="No fills found for this position.", padding="tight")' in src

    def test_old_inline_empty_div_gone(self):
        """Anti-revert: the prior `<div style="color:var(--muted);
        font-size:.72rem;padding:10px 0;">No fills found...</div>`
        pattern is gone."""
        src = Path("templates/fragments/history/position_fills.html").read_text(encoding="utf-8")
        old = '<div style="color:var(--muted);font-size:.72rem;padding:10px 0;">No fills found for this position.</div>'
        assert old not in src

    def test_empty_render_uses_es_tight(self):
        """End-to-end: empty fills list renders `.es .es-info .es-tight`."""
        out = _render_position_fills([])
        assert "es-tight" in out
        assert "No fills found for this position." in out
        # Old inline div pattern gone from render too
        assert 'padding:10px 0;">No fills found' not in out


# ── Anti-regression: non-empty render still works end-to-end ────────────────

class TestAntiRegression:

    def test_full_row_render_with_linked_exec_badge(self):
        """Non-empty fill renders with the new structure: tr-p class +
        ACTION/SIDE cells + exec-link badge."""
        out = _render_position_fills([_sample_fill(
            is_close=False, direction="LONG", exec_link_status="linked",
        )])
        # TableRow class
        assert 'class="tr-p"' in out
        # ACTION + SIDE columns rendered
        assert ">Open<" in out
        assert ">LONG<" in out
        # Exec-link badge rendered (the "linked" status)
        assert "● LINKED" in out

    def test_close_fill_renders_no_exec_link_badge(self):
        """Close fills don't get an exec link (the `not is_close`
        check). Sanity: the badge HTML is absent for close fills."""
        out = _render_position_fills([_sample_fill(
            id=1, is_close=True, direction="LONG", realized_pnl=100.0,
            exec_link_status=None,
        )])
        assert "● LINKED" not in out
        assert "✗ UNLINKED" not in out


# ── Compile pins (MED-047) ──────────────────────────────────────────────────

class TestTemplateCompiles:

    def test_position_fills_compiles(self):
        env = _make_env()
        tpl = env.get_template("fragments/history/position_fills.html")
        assert tpl is not None

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
