"""
Task 123 regression tests — Bundle A primitive #3 (TableRow) +
FE-MED-002 fix (history-table row drift).

TableRow is the first sibling-list-slot primitive in Bundle A. Uses
the open/close pair pattern (counterpart to Card's call/caller),
since `<tr>` body is a list of `<td>` cells, not one contiguous block.

Migrates all three history tables:
  - Position History (closed_positions_table.html) — clickable rows.
  - Order History    (order_history_table.html)    — static rows.
  - Trade History    (fills_table.html)            — static rows +
    SIDE column split into ACTION + SIDE (calibration #3 specifically).

MED-047 discipline: compile + render via Jinja2; source-string greps
only for migration anti-revert pins.

Run: pytest tests/test_task123_table_row.py -v
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


def _render_tr(body="<td>x</td>", **params):
    env = _make_env()
    src = (
        '{% from "primitives/table_row.html" import tr_open, tr_close %}'
        '{{ tr_open(state=state, on_click=on_click, id=id, extra_class=extra_class) }}'
        + body +
        '{{ tr_close() }}'
    )
    return env.from_string(src).render(
        state=params.get("state", "default"),
        on_click=params.get("on_click", ""),
        id=params.get("id", ""),
        extra_class=params.get("extra_class", ""),
    )


# ── TableRow macro: open/close primitives ────────────────────────────────────

class TestTableRowRendering:

    def test_default_open_emits_tr_with_base_class(self):
        html = _render_tr()
        assert '<tr class="tr-p">' in html
        assert "</tr>" in html
        assert "<td>x</td>" in html

    def test_clickable_state_adds_class(self):
        html = _render_tr(state="clickable")
        assert "tr-p tr-p-clickable" in html

    def test_on_click_alone_implies_clickable(self):
        """Ergonomic shortcut: passing on_click without state="clickable"
        still emits the clickable class, so callers don't repeat
        themselves."""
        html = _render_tr(on_click="foo(1)")
        assert 'class="tr-p tr-p-clickable"' in html
        assert 'onclick="foo(1)"' in html

    def test_id_attribute_emitted_when_set(self):
        html = _render_tr(id="row-7")
        assert 'id="row-7"' in html

    def test_id_attribute_absent_when_empty(self):
        html = _render_tr()
        # Don't emit id=""
        assert 'id="' not in html

    def test_on_click_attribute_absent_when_empty(self):
        html = _render_tr()
        assert "onclick" not in html

    def test_extra_class_appended(self):
        html = _render_tr(extra_class="my-row pending")
        assert 'class="tr-p my-row pending"' in html

    def test_close_renders_only_closing_tag(self):
        env = _make_env()
        src = (
            '{% from "primitives/table_row.html" import tr_close %}'
            "{{ tr_close() }}"
        )
        out = env.from_string(src).render()
        assert out.strip() == "</tr>"


# ── CSS shipped in base.html ────────────────────────────────────────────────

class TestTableRowCssInBase:

    def test_base_has_tr_p_css_block(self):
        src = Path("templates/base.html").read_text(encoding="utf-8")
        assert ".tr-p {" in src
        assert ".tr-p-clickable" in src
        assert ".tr-p-selected" in src
        # FE-MED-002 anchored for traceability
        assert "FE-MED-002" in src


# ── Position History migration ──────────────────────────────────────────────


# ── Order History migration ─────────────────────────────────────────────────


# ── Trade History (fills_table) migration + ACTION/SIDE split ───────────────


# ── README + class-prefix table update ──────────────────────────────────────

class TestReadmeDocumentsTableRow:

    def _read(self) -> str:
        return Path("templates/primitives/README.md").read_text(encoding="utf-8")

    def test_readme_has_table_row_section(self):
        assert "TableRow (Task 123)" in self._read()

    def test_readme_documents_open_close_pattern(self):
        content = self._read()
        # Either explicit open/close mention or the decision-tree line
        assert "open/close pair" in content or "tr_open" in content

    def test_readme_decision_tree_present(self):
        content = self._read()
        assert "Decision tree" in content
        # Three patterns enumerated
        assert "sibling" in content
        assert "contiguous" in content


# ── Compile pins (MED-047 explicit) ─────────────────────────────────────────

class TestTemplateCompiles:

    def test_table_row_macro_compiles(self):
        env = _make_env()
        tpl = env.get_template("primitives/table_row.html")
        assert tpl is not None


    def test_status_indicator_macro_still_compiles(self):
        """Bundle A.1 anti-regression — sibling primitive intact."""
        env = _make_env()
        tpl = env.get_template("primitives/status_indicator.html")
        assert tpl is not None

    def test_card_macro_still_compiles(self):
        """Bundle A.2 anti-regression."""
        env = _make_env()
        tpl = env.get_template("primitives/card.html")
        assert tpl is not None
