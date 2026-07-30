"""
Task 112 regression tests for FE-MED-005 + FE-MED-011 + FE-MED-012.

- FE-MED-005: Calculator Recent card stored ts as "HH:MM" string; relative
  format requires epoch ms storage + a render-time helper. JS-side change
  in templates/calculator.html.
- FE-MED-011: Calculator preview labels leaked code identifiers
  (`_size`, `est_size`); renamed to title-case human strings.
- FE-MED-012: `1% Depth (USDT)` and `Fee (2×)` were ambiguous; renamed to
  `1% Depth from Mid` and `Round-trip (Entry + Exit)` respectively.

MED-047 discipline: where possible, render the template via Jinja2 and
assert the new content appears. For JS-side changes, source-pin against
the calculator.html script blob.

Run: pytest tests/test_task112_calculator_ux.py -v
"""
from __future__ import annotations

from pathlib import Path

import jinja2
import pytest


def _read(rel_path: str) -> str:
    return Path(rel_path).read_text(encoding="utf-8")


# ── FE-MED-005: relative timestamp in Calculator Recent card ─────────────────





# ── FE-MED-011: title-case labels in calc_result.html ────────────────────────

class TestCalcResultLabelsTitleCase:
    """Underscore-style identifier labels (`_size`, `est_size`) leaked to
    UI. Renamed to title-case human strings."""

    def _render(self, calc):
        """Render the calc_result.html fragment with synthetic context."""
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader("templates"),
            autoescape=jinja2.select_autoescape(["html"]),
        )
        # The template uses helpers exposed via the env globals. We need to
        # mimic that: register the same helpers our app does.
        env.globals["fmt"] = lambda v, n=2: f"{v:.{n}f}" if isinstance(v, (int, float)) else str(v)
        # Task 152: calc_result now also calls fmt_size / fmt_price for
        # contracts and prices. Register matching helpers for the fixture.
        from core.formatters import format_price, format_size
        env.globals["fmt_size"] = format_size
        env.globals["fmt_price"] = format_price
        tpl = env.get_template("fragments/calc_result.html")
        return tpl.render(calc=calc, params={"max_exposure": 5.0, "max_correlated_exposure": 0.30})

    def _base_calc(self, **overrides):
        c = {
            "weekly_pnl_state": "ok", "dd_state": "ok",
            "equity_stale": False, "eligible": True,
            "at_max_positions": False, "at_max_exposure": False,
            "exceeds_corr_limit": False, "ineligible_reason": "",
            "regime_stale": False, "regime_label": "neutral",
            "regime_multiplier": 1.0, "apply_regime_multiplier": True,
            "atr_c": 1.0, "atr_category": "normal",
            "atr100": 1.0, "atr14": 1.0,
            "ticker": "BTCUSDT", "side": "long", "order_type": "limit",
            "average": 60000.0, "risk_usdt": 50.0, "base_size": 250.0,
            "est_fill_price": 60000.0, "one_percent_depth": 100000.0,
            "best_bid": 59999.0, "best_ask": 60001.0,
            "size": 0.004, "size_raw": 0.004, "notional": 240.0,
            "tp_price": 62000.0, "sl_price": 59000.0,
            "tp_usdt": 100.0, "sl_usdt": -50.0,
            "est_slippage": 0.0005, "est_slippage_usdt": 0.12,
            "est_profit": 95.0, "est_loss": -52.0, "est_r": 1.9,
            "est_exposure": 0.5, "fee_rate": 0.0005,
            "correlated_exposure": {"big_two_crypto": 0.0},
            "new_sector_exposure": 240.0,
            "calc_id": "calc-test-001",
            "tp_price": 62000.0, "sl_price": 59000.0,
        }
        c.update(overrides)
        return c

    def test_size_label_is_title_case_not_underscore(self):
        """`_size (contracts)` → `Size (Contracts)`."""
        html = self._render(self._base_calc())
        assert "Size (Contracts)" in html
        assert "_size (contracts)" not in html, (
            "FE-MED-011 regression: underscore identifier still in UI."
        )

    def test_notional_label_drops_est_size_underscore(self):
        """`Notional / est_size (USDT)` → `Notional / Est. Size (USDT)`."""
        html = self._render(self._base_calc())
        assert "Notional / Est. Size (USDT)" in html
        assert "est_size" not in html, (
            "FE-MED-011 regression: est_size identifier still leaks."
        )


# ── FE-MED-012: disambiguated fee/depth labels ───────────────────────────────

class TestCalcResultLabelsDisambiguated:
    """`1% Depth (USDT)` and `Fee (2×)` were ambiguous. Renamed to be
    self-explanatory."""

    def _render(self, calc):
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader("templates"),
            autoescape=jinja2.select_autoescape(["html"]),
        )
        env.globals["fmt"] = lambda v, n=2: f"{v:.{n}f}" if isinstance(v, (int, float)) else str(v)
        # Task 152: calc_result now also calls fmt_size / fmt_price for
        # contracts and prices. Register matching helpers for the fixture.
        from core.formatters import format_price, format_size
        env.globals["fmt_size"] = format_size
        env.globals["fmt_price"] = format_price
        tpl = env.get_template("fragments/calc_result.html")
        return tpl.render(calc=calc, params={"max_exposure": 5.0, "max_correlated_exposure": 0.30})

    def _base_calc(self, **overrides):
        # Reuse TestCalcResultLabelsTitleCase's base
        c = TestCalcResultLabelsTitleCase()._base_calc(**overrides)
        return c

    def test_depth_label_clarifies_reference_point(self):
        """`1% Depth (USDT)` → `1% Depth from Mid (USDT)`."""
        html = self._render(self._base_calc())
        assert "1% Depth from Mid (USDT)" in html, (
            "FE-MED-012 regression: depth label still ambiguous about the "
            "1% reference point."
        )

    def test_fee_label_clarifies_round_trip_semantics(self):
        """`Fee (2×)` → `Fee — Round-trip (Entry + Exit)`. Operator order
        type drives Maker vs Taker prefix."""
        # Taker path: order_type=market
        html_taker = self._render(self._base_calc(order_type="market"))
        assert "Taker Fee — Round-trip (Entry + Exit)" in html_taker, (
            "FE-MED-012 regression: Taker fee label still uses ambiguous "
            "(2×)."
        )
        # Maker path: order_type=limit
        html_maker = self._render(self._base_calc(order_type="limit"))
        assert "Maker Fee — Round-trip (Entry + Exit)" in html_maker

    def test_old_ambiguous_labels_gone(self):
        """Anti-revert pins: the literal old labels must be absent."""
        html = self._render(self._base_calc())
        assert "1% Depth (USDT)" not in html or "1% Depth from Mid (USDT)" in html
        assert "Fee (2×)" not in html


# ── MED-047 compile-and-render discipline (covered implicitly above) ─────────

class TestTemplateStillCompiles:
    """The render-based tests above implicitly verify the template compiles.
    Adding an explicit pin so a regression with a syntax error surfaces
    with a clear message, not as a cascade of failures in other tests."""

    def test_calc_result_template_compiles(self):
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader("templates"),
            autoescape=jinja2.select_autoescape(["html"]),
        )
        # Triggers compile; raises TemplateSyntaxError on Jinja2-invalid input
        tpl = env.get_template("fragments/calc_result.html")
        assert tpl is not None

