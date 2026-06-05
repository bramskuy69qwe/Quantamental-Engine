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

class TestPositionHistoryMigration:

    def _read(self) -> str:
        return Path(
            "templates/fragments/history/closed_positions_table.html"
        ).read_text(encoding="utf-8")

    def test_imports_table_row_primitive(self):
        assert 'from "primitives/table_row.html" import tr_open, tr_close' in self._read()

    def test_uses_tr_open_with_on_click(self):
        """Position History rows are click-to-expand → on_click param
        drives the migration. Old `<tr style="cursor:pointer;"
        onclick="togglePosRow(...)">` must be gone."""
        src = self._read()
        assert "tr_open(on_click=" in src
        # Old pattern absent
        assert '<tr style="cursor:pointer;"' not in src

    def test_renders_with_clickable_class(self):
        env = _make_env()
        tpl = env.get_template(
            "fragments/history/closed_positions_table.html"
        )
        rows = [{
            "id": 1, "entry_time_ms": 1, "exit_time_ms": 2,
            "symbol": "BTCUSDT", "direction": "LONG", "quantity": 1.0,
            "entry_price": 60000.0, "exit_price": 62000.0,
            "net_pnl": 100.0, "total_fees": 0.1, "hold_time_ms": 60000,
            "exit_reason": "tp_hit", "tp_price": 62000.0, "sl_price": 59000.0,
            "mfe": 100.0, "mae": -50.0, "backfill_completed": True,
        }]
        out = tpl.render(
            rows=rows, total=1, page=1, per_page=20, total_pages=1,
            search="", sort_by="exit_time_ms", sort_dir="DESC",
            date_from="2026-01-01", date_to="2026-12-31",
        )
        assert 'class="tr-p tr-p-clickable"' in out
        assert 'onclick="togglePosRow(1)"' in out

    def _render_one(self, exit_reason):
        env = _make_env()
        tpl = env.get_template("fragments/history/closed_positions_table.html")
        rows = [{
            "id": 1, "entry_time_ms": 1, "exit_time_ms": 2,
            "symbol": "BTCUSDT", "direction": "LONG", "quantity": 1.0,
            "entry_price": 60000.0, "exit_price": 62000.0,
            "net_pnl": 100.0, "total_fees": 0.1, "hold_time_ms": 60000,
            "exit_reason": exit_reason, "tp_price": 62000.0, "sl_price": 59000.0,
            "mfe": 100.0, "mae": -50.0, "backfill_completed": True,
        }]
        return tpl.render(
            rows=rows, total=1, page=1, per_page=20, total_pages=1,
            search="", sort_by="exit_time_ms", sort_dir="DESC",
            date_from="2026-01-01", date_to="2026-12-31",
        )

    @pytest.mark.parametrize("exit_reason,badge_class,label", [
        # T2.7: spec §3.4 enum colorized by family.
        ("TP_PLANNED", "badge-green", "TP"),
        ("TP_AMENDED", "badge-green", "TP"),
        ("SL_PLANNED", "badge-red", "SL"),
        ("SL_AMENDED", "badge-red", "SL"),
        # P8.T6: MANUAL_* / legacy 'manual' now render a CLICKABLE reason badge
        # (see test_manual_exit_reason_is_clickable_reason_badge below).
        ("LIQUIDATION", "badge-red", "Liq"),
        ("ADL", "badge-red", "Liq"),
        ("EXPIRED", "badge-gray", "Exp"),
        ("MIXED", "badge-yellow", "Mixed"),
        # Legacy fallbacks (rows the P0.T5 backfill didn't reach).
        ("tp_hit", "badge-green", "TP"),
        ("sl_hit", "badge-red", "SL"),
    ])
    def test_exit_reason_badge_colorized(self, exit_reason, badge_class, label):
        out = self._render_one(exit_reason)
        assert f'class="badge {badge_class}">{label}</span>' in out

    @pytest.mark.parametrize("exit_reason,label", [
        ("MANUAL_OTHER", "Manual"),
        ("MANUAL_INTERVENTION", "Intervention"),
        ("MANUAL_DISCIPLINE_BREAK", "Discipline"),
        ("MANUAL_NEW_OPPORTUNITY", "New Opp"),
        ("manual", "Manual"),          # legacy → label falls back to Manual
        ("limit_close", "Manual"),     # legacy
    ])
    def test_manual_exit_reason_is_clickable_reason_badge(self, exit_reason, label):
        # P8.T6: a manual close renders a clickable badge (opens the reason
        # modal) carrying the MANUAL_* subtype label, inside a #cr-cell-{id}
        # wrapper so the PUT response can swap it.
        out = self._render_one(exit_reason)
        assert 'id="cr-cell-1"' in out
        assert "badge-gray" in out
        assert "openCloseReasonModal(this)" in out
        assert f'data-cr-reason="{exit_reason}"' in out
        assert f">{label}</span>" in out

    def test_unknown_exit_reason_falls_through_to_plain_badge(self):
        out = self._render_one("SOMETHING_NEW")
        assert '<span class="badge">SOMETHING_NEW</span>' in out


# ── Order History migration ─────────────────────────────────────────────────

class TestOrderHistoryMigration:

    def _read(self) -> str:
        return Path(
            "templates/fragments/history/order_history_table.html"
        ).read_text(encoding="utf-8")

    def test_imports_table_row_primitive(self):
        assert 'from "primitives/table_row.html" import tr_open, tr_close' in self._read()

    def test_uses_default_state_tr_open(self):
        """Order History rows are static (no click-to-expand). Should
        use the default (non-clickable) tr_open()."""
        src = self._read()
        assert "{{ tr_open() }}" in src

    def test_old_bare_tr_pattern_gone_in_body(self):
        """Anti-revert: in the rows-loop body, the bare `<tr>` open is
        replaced. (Header `<tr>` inside <thead> stays — it's a column
        header, not a data row.)"""
        src = self._read()
        # Locate the for-loop body and confirm no bare <tr> inside it.
        loop_start = src.find("{% for r in rows %}")
        loop_end = src.find("{% endfor %}")
        assert loop_start > 0 and loop_end > loop_start
        body = src[loop_start:loop_end]
        assert "<tr>" not in body, (
            "FE-MED-002 regression: bare <tr> back inside Order History "
            "row loop — migration reverted."
        )

    def test_renders_with_tr_p_class(self):
        env = _make_env()
        tpl = env.get_template(
            "fragments/history/order_history_table.html"
        )
        rows = [{
            "updated_at_ms": 1, "symbol": "BTCUSDT", "side": "BUY",
            "order_type": "LIMIT", "quantity": 1.0, "price": 60000.0,
            "stop_price": 0, "time_in_force": "GTC", "status": "filled",
            "exchange_order_id": "123456789", "avg_fill_price": 60000.0,
        }]
        out = tpl.render(
            rows=rows, total=1, page=1, per_page=20, total_pages=1,
            search="", sort_by="updated_at_ms", sort_dir="DESC",
            date_from="2026-01-01", date_to="2026-12-31",
        )
        assert 'class="tr-p"' in out
        # And no tr-p-clickable for static rows
        # (the row class should be exactly "tr-p", no extra state)
        assert 'class="tr-p tr-p-clickable"' not in out


# ── Trade History (fills_table) migration + ACTION/SIDE split ───────────────

class TestTradeHistoryMigrationAndColumnSplit:
    """FE-MED-002 calibration #3: split compound 'Close LONG' / 'Open
    SHORT' single cell into ACTION column (Open/Close) + SIDE column
    (LONG/SHORT), each single-coloured."""

    def _read(self) -> str:
        return Path(
            "templates/fragments/history/fills_table.html"
        ).read_text(encoding="utf-8")

    def test_imports_table_row_primitive(self):
        assert 'from "primitives/table_row.html" import tr_open, tr_close' in self._read()

    def test_old_compound_side_label_gone(self):
        """Anti-revert: the prior `side_label = "Close " ~ dir` /
        `"Open " ~ dir` construction must be absent."""
        src = self._read()
        assert 'side_label = "Close "' not in src
        assert 'side_label = "Open "' not in src

    def test_action_column_header_added(self):
        src = self._read()
        # New column header
        assert "<th>Action</th>" in src

    def test_renders_with_action_and_side_cells(self):
        env = _make_env()
        tpl = env.get_template(
            "fragments/history/fills_table.html"
        )
        rows = [
            {
                "timestamp_ms": 1, "exchange_order_id": "AAA111222",
                "symbol": "BTCUSDT", "is_close": False, "direction": "LONG",
                "price": 60000.0, "quantity": 1.0, "fee": 0.1,
                "fee_asset": "USDT", "role": "maker",
                "slippage_actual": 0.0001, "realized_pnl": 0,
            },
            {
                "timestamp_ms": 2, "exchange_order_id": "BBB111222",
                "symbol": "BTCUSDT", "is_close": True, "direction": "LONG",
                "price": 62000.0, "quantity": 1.0, "fee": 0.1,
                "fee_asset": "USDT", "role": "taker",
                "slippage_actual": 0.0001, "realized_pnl": 100.0,
            },
        ]
        out = tpl.render(
            rows=rows, total=2, page=1, per_page=20, total_pages=1,
            search="", sort_by="timestamp_ms", sort_dir="DESC",
            date_from="2026-01-01", date_to="2026-12-31",
        )
        # Old compound labels gone
        assert "Open LONG" not in out
        assert "Close LONG" not in out
        assert "Open SHORT" not in out
        # New single-word cells
        assert ">Open<" in out
        assert ">Close<" in out
        assert ">LONG<" in out
        # Action coloring: Open → pos-long (green), Close → pos-short (red)
        assert 'class="pos-long">Open<' in out
        assert 'class="pos-short">Close<' in out
        # SIDE coloring: LONG → pos-long; LONG renders both rows since
        # both rows have direction=LONG
        assert 'class="pos-long">LONG<' in out


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

    def test_closed_positions_table_compiles(self):
        env = _make_env()
        tpl = env.get_template("fragments/history/closed_positions_table.html")
        assert tpl is not None

    def test_order_history_table_compiles(self):
        env = _make_env()
        tpl = env.get_template("fragments/history/order_history_table.html")
        assert tpl is not None

    def test_fills_table_compiles(self):
        env = _make_env()
        tpl = env.get_template("fragments/history/fills_table.html")
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
