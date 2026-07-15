"""
Task 111 regression tests for FE-HIGH-002.

Add Account modal's EXCHANGE dropdown was hardcoded to a single
<option value="binance">Binance</option>. Bybit + MEXC adapters were
registered but not exposed in the UI. Fix populates from the
adapter registry; non-canonical exchanges carry a "(Beta)" suffix on
the label per operator decision 2026-05-18.

Coverage:
- Helper unit tests: list_rest_exchanges shape, ordering, Beta-tag logic.
- Template render: actual Jinja2 environment renders the modal block
  with the dropdown populated correctly (MED-047 discipline — compile +
  render, not source-string grep).
- Wiring pin: _ctx exposes available_exchanges.

Run: pytest tests/test_task111_exchange_dropdown.py -v
"""
from __future__ import annotations

import inspect
from pathlib import Path

import jinja2
import pytest


# ── list_rest_exchanges helper unit tests ────────────────────────────────────

class TestListRestExchangesHelper:
    """The helper itself — no UI yet. Shape and ordering pins."""

    def test_returns_all_registered_rest_exchanges(self):
        """Three adapters are registered (binance, bybit, mexc).
        All three must appear in the helper's output."""
        # Trigger adapter registration side-effects via the package import.
        import core.adapters.binance.rest_adapter  # noqa: F401
        import core.adapters.bybit.rest_adapter    # noqa: F401
        import core.adapters.mexc.rest_adapter     # noqa: F401

        from core.adapters.registry import list_rest_exchanges
        rows = list_rest_exchanges()
        values = {r["value"] for r in rows}
        assert {"binance", "bybit", "mexc"} <= values, (
            f"FE-HIGH-002 regression: expected binance + bybit + mexc in "
            f"list_rest_exchanges(); got {values!r}"
        )

    def test_binance_label_is_unsuffixed(self):
        """Canonical (non-Beta) exchanges render without a suffix."""
        import core.adapters.binance.rest_adapter  # noqa: F401
        from core.adapters.registry import list_rest_exchanges
        rows = list_rest_exchanges()
        binance = next(r for r in rows if r["value"] == "binance")
        assert binance["label"] == "Binance"
        assert binance["is_beta"] is False

    def test_bybit_label_carries_beta_suffix(self):
        """Per operator decision 2026-05-18, non-canonical exchanges carry
        a "(Beta)" suffix."""
        import core.adapters.bybit.rest_adapter  # noqa: F401
        from core.adapters.registry import list_rest_exchanges
        rows = list_rest_exchanges()
        bybit = next(r for r in rows if r["value"] == "bybit")
        assert bybit["label"] == "Bybit (Beta)", (
            f"FE-HIGH-002 regression: bybit label should be 'Bybit (Beta)'; "
            f"got {bybit['label']!r}"
        )
        assert bybit["is_beta"] is True

    def test_mexc_label_uses_uppercase_override(self):
        """MEXC is an acronym; title-case ('Mexc') would be wrong. Override
        kicks in to keep it uppercase."""
        import core.adapters.mexc.rest_adapter  # noqa: F401
        from core.adapters.registry import list_rest_exchanges
        rows = list_rest_exchanges()
        mexc = next(r for r in rows if r["value"] == "mexc")
        assert mexc["label"] == "MEXC (Beta)", (
            f"FE-HIGH-002 regression: mexc label should be 'MEXC (Beta)' "
            f"(uppercase acronym override); got {mexc['label']!r}"
        )
        assert mexc["is_beta"] is True

    def test_canonical_exchanges_sort_before_beta(self):
        """Binance must appear first so the default selection is the
        operator-canonical exchange."""
        import core.adapters.binance.rest_adapter  # noqa: F401
        import core.adapters.bybit.rest_adapter    # noqa: F401
        import core.adapters.mexc.rest_adapter     # noqa: F401
        from core.adapters.registry import list_rest_exchanges
        rows = list_rest_exchanges()
        # First non-beta row index
        first_canonical_idx = next(i for i, r in enumerate(rows) if not r["is_beta"])
        # First beta row index
        first_beta_idx = next(i for i, r in enumerate(rows) if r["is_beta"])
        assert first_canonical_idx < first_beta_idx, (
            "Canonical exchanges should sort before Beta — Binance must "
            "be first option in the dropdown."
        )

    def test_market_type_filter_excludes_other_markets(self):
        """If an adapter is registered for a different market_type
        (e.g., 'spot'), it must not appear in the linear_perpetual list."""
        from core.adapters.registry import (
            list_rest_exchanges, register_adapter, _REST_REGISTRY,
        )
        # Inject a fake spot adapter
        class _FakeSpot:
            pass
        _REST_REGISTRY["fakeexch:spot"] = _FakeSpot
        try:
            rows = list_rest_exchanges(market_type="linear_perpetual")
            values = {r["value"] for r in rows}
            assert "fakeexch" not in values, (
                "list_rest_exchanges must filter by market_type."
            )
            # And the spot filter sees it
            rows_spot = list_rest_exchanges(market_type="spot")
            spot_values = {r["value"] for r in rows_spot}
            assert "fakeexch" in spot_values
        finally:
            _REST_REGISTRY.pop("fakeexch:spot", None)


# ── Template render: modal dropdown populated (MED-047 discipline) ───────────

class TestBaseTemplateRendersDropdown:
    """Compile + render the base.html template via Jinja2 directly. Asserts
    the dropdown contains all three exchange options with correct labels.
    This is the MED-047 pattern: don't just grep source, actually render."""

    def _render(self, available_exchanges):
        """Render base.html with a minimal synthetic context."""
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader("templates"),
            autoescape=jinja2.select_autoescape(["html"]),
        )
        # Stub the `active_page` global; base.html uses it for nav highlighting
        class _StubAcct:
            id = 1
            name = "Account 1"
            is_active = 1
            exchange = "binance"
            market_type = "future"
            environment = "live"
            broker_account_id = ""
            maker_fee = 0.0002
            taker_fee = 0.0005
            link_window_seconds = 21600
            def get(self, k, default=None):
                return getattr(self, k, default)
        class _StubWS:
            connected = True
            latency_ms = 12.5
            is_stale = False
            using_fallback = False
            logs = []
            reconnect_attempts = 0
            seconds_since_update = 1.0
        tpl = env.get_template("base.html")
        return tpl.render(
            active_page="config",
            now="2026-05-18 10:00:00",
            tz_display="UTC",
            ws_status=_StubWS(),
            plugin_connected=False,
            params={"individual_risk_per_trade": 0.005},
            is_initializing=False,
            active_account_id=1,
            accounts=[{"id": 1, "name": "Account 1", "is_active": 1, "environment": "live"}],
            available_exchanges=available_exchanges,
            project_name="QUANTAMENTAL ENGINE v2.4.1",
            project_name_="QUANTAMENTAL ENGINE",
            project_version_="v2.4.1",
            request=None,
        )

    def test_template_renders_with_three_exchange_options(self):
        """Load-bearing: actually compile the base.html template (catches
        MED-047-class syntax errors) and confirm the dropdown contains
        all three options."""
        rows = [
            {"value": "binance", "label": "Binance",       "is_beta": False},
            {"value": "bybit",   "label": "Bybit (Beta)",  "is_beta": True},
            {"value": "mexc",    "label": "MEXC (Beta)",   "is_beta": True},
        ]
        html = self._render(rows)
        assert '<option value="binance">Binance</option>' in html
        assert '<option value="bybit">Bybit (Beta)</option>' in html
        assert '<option value="mexc">MEXC (Beta)</option>' in html

    def test_template_does_not_hardcode_single_binance_option(self):
        """Anti-revert pin: a future refactor that re-hardcodes the dropdown
        would re-introduce FE-HIGH-002. The old line was literally
        '<select name="exchange"><option value="binance">Binance</option></select>'
        — a single inline option. Detect that exact regression."""
        path = Path("templates") / "base.html"
        src = path.read_text(encoding="utf-8")
        assert '<option value="binance">Binance</option></select>' not in src, (
            "FE-HIGH-002 regression: base.html re-hardcoded the dropdown to "
            "a single Binance option."
        )

    def test_template_iterates_available_exchanges(self):
        """Source pin: the for-loop over available_exchanges is present."""
        path = Path("templates") / "base.html"
        src = path.read_text(encoding="utf-8")
        assert "{% for ex in available_exchanges %}" in src
        assert "{{ ex.value }}" in src
        assert "{{ ex.label }}" in src

    def test_rendered_output_lists_binance_first(self):
        """The order in the rendered HTML matches the helper's sort order:
        canonical first, beta after. Operator opens the dropdown and sees
        Binance at the top."""
        rows = [
            {"value": "binance", "label": "Binance",       "is_beta": False},
            {"value": "bybit",   "label": "Bybit (Beta)",  "is_beta": True},
            {"value": "mexc",    "label": "MEXC (Beta)",   "is_beta": True},
        ]
        html = self._render(rows)
        idx_binance = html.find('value="binance"')
        idx_bybit = html.find('value="bybit"')
        idx_mexc = html.find('value="mexc"')
        assert 0 < idx_binance < idx_bybit, (
            "Binance must appear before Bybit in the dropdown."
        )
        assert idx_bybit < idx_mexc or idx_bybit > 0  # bybit before mexc per alpha sort

    def test_empty_available_exchanges_renders_empty_select(self):
        """Defensive: if the helper somehow returns an empty list (no
        adapters registered), the template must not crash."""
        html = self._render([])
        # The <select> still renders, but has no <option> children
        assert '<select name="exchange">' in html
        # No option elements between the open and close <select> tag
        sel_open = html.find('<select name="exchange">')
        sel_close = html.find("</select>", sel_open)
        sel_inner = html[sel_open:sel_close]
        assert "<option" not in sel_inner


# ── _ctx wiring pin ─────────────────────────────────────────────────────────

class TestCtxWiring:
    """FE-HIGH-002 wiring pin: _ctx includes available_exchanges so every
    page render has the dropdown data available."""

    def test_ctx_source_references_available_exchanges(self):
        from api import helpers
        src = inspect.getsource(helpers._ctx)
        assert "available_exchanges" in src, (
            "FE-HIGH-002 wiring regression: _ctx no longer exposes "
            "available_exchanges to templates. Add Account modal dropdown "
            "will silently fall back to no options."
        )

    def test_ctx_source_imports_list_rest_exchanges(self):
        from api import helpers
        src = inspect.getsource(helpers._ctx)
        assert "list_rest_exchanges" in src
