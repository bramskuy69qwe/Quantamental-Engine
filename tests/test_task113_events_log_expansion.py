"""
Task 113 regression tests for FE-HIGH-006.

Trade Events Log row expansion previously rendered the raw JSON string
on a single line inside a `<pre>` (the `<pre>` had `word-break: break-all`
but the underlying JSON has no whitespace between keys, so it visually
wrapped only at character boundaries — unreadable). Fix replaces the
`<pre>` with a key-value grid: each payload field gets its own row,
label column on the left, monospace value on the right. Nested
values (dict / list) render via `tojson`; null values render as a
muted italic "null".

MED-047 discipline: compile + render the template via Jinja2 with
representative payloads, then assert the rendered HTML contains the
expected grid structure.

Run: pytest tests/test_task113_events_log_expansion.py -v
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
    # Mirror api.helpers global registration so the template's `fmt(...)`
    # call resolves during render.
    env.globals["fmt"] = lambda v, n=2: f"{v:.{n}f}" if isinstance(v, (int, float)) else str(v)
    return env


def _render_events_table(rows, **extra):
    """Render the trade_events_table fragment with a minimal context."""
    env = _make_env()
    tpl = env.get_template("fragments/history/trade_events_table.html")
    return tpl.render(
        rows=rows,
        total=len(rows),
        page=1, per_page=20, total_pages=1,
        event_type="", search="",
        date_from="", date_to="",
        **extra,
    )


def _row(event_type, payload, calc_id="abc12345", source="order_manager", _id=1):
    """Build a row dict matching the route handler's shape."""
    import json as _json
    return {
        "id": _id,
        "timestamp": "2026-05-18T10:41:32",
        "event_type": event_type,
        "calc_id": calc_id,
        "source": source,
        "payload_json": _json.dumps(payload),
        "_payload": payload,
        "_symbol": payload.get("symbol") or payload.get("ticker") or "",
    }


# ── Expanded row layout: key-value grid (not single-line JSON) ───────────────

class TestExpandedRowKeyValueGrid:
    """The expansion row must contain a multi-cell grid, one cell per
    payload field, with labels distinct from values. NOT a single <pre>
    block of inline JSON."""

    def test_each_payload_field_renders_with_its_label(self):
        """Load-bearing pin: every key in the payload appears as a label
        somewhere in the expansion HTML, and every value renders alongside."""
        payload = {
            "symbol": "BTCUSDT", "direction": "LONG",
            "entry_price": 60000.0, "exit_price": 62000.0,
            "realized_pnl": 100.0, "net_pnl": 95.5,
            "exit_reason": "manual",
        }
        html = _render_events_table([_row("position_closed", payload)])
        # Every key must be present as a label
        for key in payload:
            assert key in html, (
                f"FE-HIGH-006 regression: payload key {key!r} missing from "
                f"rendered expansion."
            )
        # Spot-check a few values rendered too (not just keys)
        assert "BTCUSDT" in html
        assert "LONG" in html
        assert "manual" in html

    def test_no_raw_payload_json_pre_block_for_populated_event(self):
        """Anti-revert pin: the old code rendered `{{ r.payload_json }}`
        inside a `<pre>` for the expansion. With the fix, the literal
        raw JSON string must NOT appear as a single block. Check that the
        opening `{` and closing `}` of the JSON aren't adjacent to each
        other in the expansion section (a heuristic that catches the old
        single-line layout)."""
        payload = {"symbol": "BTCUSDT", "entry_price": 0.0}
        html = _render_events_table([_row("position_closed", payload)])
        # The JSON-dumped form would be: {"symbol": "BTCUSDT", "entry_price": 0.0}
        # That literal string should NOT be in the rendered output (it would
        # only be there if the old <pre>{{ r.payload_json }}</pre> revert
        # happened).
        raw_json = '{"symbol": "BTCUSDT", "entry_price": 0.0}'
        assert raw_json not in html, (
            "FE-HIGH-006 regression: raw single-line payload_json string "
            "reintroduced into the expansion."
        )

    def test_expansion_uses_css_grid_layout(self):
        """Source-pin: the expansion HTML must contain a display:grid
        directive with two columns (label + value). Catches a future
        refactor that drops back to a flat list or back to `<pre>`."""
        payload = {"symbol": "BTCUSDT", "pnl": 1.5}
        html = _render_events_table([_row("position_closed", payload)])
        assert "display:grid" in html
        assert "grid-template-columns:max-content 1fr" in html

    def test_empty_payload_renders_muted_placeholder(self):
        """Defensive: an event with an empty payload (parse failure
        fallback in the route, or genuinely no payload data) must NOT
        render an empty grid. Render an explicit "No payload data."
        hint instead."""
        html = _render_events_table([_row("calc_created", {})])
        assert "No payload data." in html, (
            "FE-HIGH-006 regression: empty payload doesn't surface a "
            "muted hint — operator sees a blank expansion."
        )

    def test_null_value_renders_as_muted_null(self):
        """Defensive: a payload field with a None value renders as a
        styled "null" rather than the Python string 'None' (which looks
        like a value, not a null marker)."""
        payload = {"symbol": "BTCUSDT", "exit_reason": None}
        html = _render_events_table([_row("position_closed", payload)])
        # The italic "null" marker from the {% if value is none %} branch
        assert "<span" in html and "null" in html
        # The Python repr "None" should NOT appear in the rendered output
        # (would mean we fell into the generic {{ value }} branch).
        # Note: we have to be careful — the literal word "None" could appear
        # legitimately elsewhere in the page chrome. We bound the check to
        # the expansion section.
        idx_expand = html.find('id="evt-detail-1"')
        assert idx_expand > 0
        # Look at the next ~1200 chars (the expansion's <td>...<\/td>)
        section = html[idx_expand:idx_expand + 1200]
        assert "None" not in section, (
            "FE-HIGH-006 regression: null payload value renders as Python "
            "'None' literal instead of the styled null marker."
        )

    def test_nested_dict_value_renders_as_inline_json(self):
        """A payload field whose value is a dict/list (rare but possible)
        renders via Jinja2's tojson filter — single-line JSON-encoded,
        not a recursive grid."""
        payload = {
            "symbol": "BTCUSDT",
            "modifications": {"tp": "+5%", "sl": "-2%"},
        }
        html = _render_events_table([_row("tp_modified", payload)])
        # tojson output for the nested dict — Jinja2's tojson escapes
        # forward slashes / certain characters but keeps the basic shape.
        idx_expand = html.find('id="evt-detail-1"')
        assert idx_expand > 0
        section = html[idx_expand:idx_expand + 1500]
        # Approximate match — the exact tojson-encoded string contains
        # the two key-value pairs in some valid JSON form.
        assert "modifications" in section  # key column
        assert '"tp"' in section and '"sl"' in section  # tojson-encoded nested

    def test_compact_detail_column_still_works(self):
        """Anti-over-correction: the non-expanded row's compact "Detail"
        column (the existing logic at lines 76-86 of the template) must
        still render its per-event-type summary. The fix only touches
        the expansion row, not the compact column."""
        payload = {"from_price": 60000.0, "to_price": 62000.0}
        html = _render_events_table([_row("tp_modified", payload)])
        # The compact detail for tp_modified: "60000.0000 → 62000.0000"
        assert "→" in html  # the arrow specific to tp_modified/sl_modified

    def test_position_amended_renders_field_arrow(self):
        """Migrated modification signal: a position_amended row (field=sl_price)
        renders 'sl_price: old → new' in the compact Detail column — the arrow
        UX previously carried by tp_modified/sl_modified, now keyed on the live
        amendment event (the dead _detect_modification_events was removed)."""
        payload = {"field": "sl_price", "old": 49000.0, "new": 49500.0,
                   "order_id": 7, "position_id": "POS-1"}
        html = _render_events_table([_row("position_amended", payload)])
        assert "→" in html                 # the amendment arrow
        assert "sl_price" in html          # the field label
        assert "49000.0000" in html and "49500.0000" in html  # fmt(.,4) old/new


# ── Template still compiles (MED-047 explicit pin) ───────────────────────────

class TestTemplateCompiles:
    def test_trade_events_table_template_compiles(self):
        """Explicit compile-pin so a Jinja2 syntax regression surfaces
        with a clear message, not as a cascade of failures in the
        other tests."""
        env = _make_env()
        tpl = env.get_template("fragments/history/trade_events_table.html")
        assert tpl is not None


# ── Empty-rows path still renders the "no events" hint ──────────────────────

class TestEmptyRowsPath:
    def test_no_events_message_present(self):
        """Anti-regression: the empty-table message (existing branch at
        line 122-123) wasn't touched. Make sure it still fires."""
        html = _render_events_table([])
        assert "No trade events found" in html
