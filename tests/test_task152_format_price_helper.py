"""
Task 152 regression tests — format_price / format_size helper consolidation
covering three audit findings:

  FE-MED-021 — MFE/MAE detail ENTRY column uses 4-decimal precision regardless
               of price scale (visual noise on $80k assets).
  FE-LOW-022 — Calculator SETUP SUMMARY size (6 decimals via fmtP) vs
               CALCULATED POSITION size (4 decimals via fmt) — same value,
               two formatters.
  FE-LOW-024 — Calculator percent values render 5-decimal precision on
               out-of-range TP/SL inputs (12314.75%) — sanity clamp at >100%.

The fix introduces:
  - core.formatters.format_price (magnitude-adaptive — mirrors JS fmtP)
  - core.formatters.format_size  (fixed 4 decimals)
  - JS fmtSize (calculator.html) — mirror of format_size for the SETUP
    SUMMARY contracts site
  - JS fmtPct (calculator.html) — clamps abs(pct)>100 to ">100%"

Run: pytest tests/test_task152_format_price_helper.py -v
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest


# ── Pure-function pins on the Python helpers ────────────────────────────────


class TestFormatPriceAdaptivePrecision:
    """Magnitude-adaptive precision per the audit's recommended fix."""

    def test_high_price_two_decimals_no_visual_noise(self):
        """FE-MED-021's BTC case — 80,816.30 not 80,816.3000."""
        from core.formatters import format_price
        assert format_price(80816.30) == "80,816.30"
        assert format_price(2340.31) == "2,340.31"
        assert format_price(676.77) == "676.7700" or format_price(676.77).startswith("676.77")
        # 676.77 is between 1 and 1000 → 4 decimals
        assert format_price(676.77) == "676.7700"

    def test_mid_price_four_decimals(self):
        """FE-MED-021's small-cap case — 4.1005 keeps 4 decimals."""
        from core.formatters import format_price
        assert format_price(4.1005) == "4.1005"

    def test_sub_unit_price_six_decimals(self):
        """Sub-$1 → 6 decimals (matches JS fmtP for round-trip parity)."""
        from core.formatters import format_price
        assert format_price(0.0749) == "0.074900"
        assert format_price(0.0001234) == "0.000123"

    def test_breakpoints_at_1000_and_1(self):
        """Boundary behaviour pinned — value exactly at 1000 → 2 decimals;
        exactly at 1 → 4 decimals."""
        from core.formatters import format_price
        assert format_price(1000.0) == "1,000.00"
        assert format_price(999.99) == "999.9900"
        assert format_price(1.0) == "1.0000"
        assert format_price(0.999999) == "0.999999"

    def test_negative_values_use_abs_magnitude(self):
        """abs(-80816.3) → 2 decimals (not 6)."""
        from core.formatters import format_price
        assert format_price(-80816.30) == "-80,816.30"
        assert format_price(-0.0749) == "-0.074900"

    def test_decimals_override(self):
        """Explicit decimals override takes precedence over magnitude rule."""
        from core.formatters import format_price
        assert format_price(80816.30, decimals=4) == "80,816.3000"
        assert format_price(0.0749, decimals=2) == "0.07"

    def test_separator_suppressed_for_copy_paste(self):
        """separator=False suppresses thousand commas (T149 paste-context flag)."""
        from core.formatters import format_price
        assert format_price(80816.30, separator=False) == "80816.30"

    def test_none_and_nan_collapse_to_dash(self):
        """Defensive: None, NaN, inf, non-numeric → '—'."""
        from core.formatters import format_price
        assert format_price(None) == "—"
        assert format_price(float("nan")) == "—"
        assert format_price(float("inf")) == "—"
        assert format_price("abc") == "—"


class TestFormatSizeFixedPrecision:
    """Fixed 4-decimal precision for contract sizes."""

    def test_typical_contract_count_four_decimals(self):
        """FE-LOW-022's exact case — 0.0314 contracts → '0.0314' (not '0.031400')."""
        from core.formatters import format_size
        assert format_size(0.0314) == "0.0314"

    def test_size_matches_engine_convention_at_all_magnitudes(self):
        """4 decimals regardless of magnitude — engine convention."""
        from core.formatters import format_size
        assert format_size(0.0001) == "0.0001"
        assert format_size(1.5) == "1.5000"
        assert format_size(1500.0) == "1,500.0000"

    def test_decimals_override(self):
        from core.formatters import format_size
        assert format_size(0.0314, decimals=6) == "0.031400"
        assert format_size(1.5, decimals=2) == "1.50"

    def test_none_and_nan_collapse(self):
        from core.formatters import format_size
        assert format_size(None) == "—"
        assert format_size(float("nan")) == "—"


# ── Source-pins on the migrated call sites ──────────────────────────────────


class TestExcursionsTemplateUsesFmtPrice:
    """FE-MED-021 fix surface — ENTRY column in MFE/MAE detail table."""

    def _read(self) -> str:
        return Path(
            "templates/fragments/analytics/excursions.html"
        ).read_text(encoding="utf-8")

    def test_entry_column_uses_fmt_price_not_fmt_4(self):
        """ENTRY column must route through fmt_price; uniform fmt(...,4)
        was the bug. Anchor comment ties the call site to FE-MED-021.
        Scope: ignore Jinja `{# ... #}` and `{## ... #}` comment regions
        so the anchor 'Was: fmt(t.entry_price, 4)' doesn't trip us."""
        src = self._read()
        assert "fmt_price(t.entry_price)" in src, (
            "FE-MED-021 regression: ENTRY column is not using fmt_price."
        )
        import re
        executing = re.sub(r"\{#.*?#\}", "", src, flags=re.DOTALL)
        assert "fmt(t.entry_price, 4)" not in executing, (
            "FE-MED-021 regression: uniform-4-decimal call reintroduced "
            "in executing (non-comment) template code."
        )

    def test_anchor_comment_references_fe_med_021(self):
        src = self._read()
        assert "FE-MED-021" in src and "Task 152" in src, (
            "Anchor comment missing — future maintainer might revert."
        )


class TestCalcResultTemplateUsesFmtSize:
    """FE-LOW-022 fix surface — CALCULATED POSITION SIZE in calc_result."""

    def _read(self) -> str:
        return Path(
            "templates/fragments/calc_result.html"
        ).read_text(encoding="utf-8")

    def test_size_uses_fmt_size_not_fmt_4(self):
        src = self._read()
        # Three size references in this fragment: main, size_raw, and the
        # regime-adjusted variant. All three must route through fmt_size.
        assert "fmt_size(c.size)" in src
        assert "fmt_size(c.size_raw)" in src
        assert "fmt_size(c.size_raw * c.regime_multiplier)" in src
        # Pre-fix call must be gone
        assert "fmt(c.size, 4)" not in src, (
            "FE-LOW-022 regression: hardcoded fmt(c.size, 4) reintroduced."
        )

    def test_anchor_comment_references_fe_low_022(self):
        src = self._read()
        assert "FE-LOW-022" in src and "Task 152" in src


class TestCalculatorHtmlJsHelpers:
    """FE-LOW-022 + FE-LOW-024 fix surfaces — JS helpers in calculator.html."""

    def _read(self) -> str:
        return Path("templates/calculator.html").read_text(encoding="utf-8")

    def test_fmt_size_js_helper_present(self):
        """fmtSize must be defined and applied to SETUP SUMMARY contracts.
        Anchor comment ties it to FE-LOW-022."""
        src = self._read()
        assert "function fmtSize(" in src, (
            "FE-LOW-022 regression: fmtSize JS helper missing."
        )
        # Applied at the contracts display site
        assert "fmtSize(contracts)" in src, (
            "FE-LOW-022 regression: SETUP SUMMARY contracts not routed "
            "through fmtSize — fmtP's 6-decimal sub-$1 behaviour is back."
        )

    def test_fmt_pct_clamp_helper_present(self):
        """fmtPct must clamp at >100% per FE-LOW-024 recommended fix."""
        src = self._read()
        assert "function fmtPct(" in src, (
            "FE-LOW-024 regression: fmtPct JS helper missing."
        )
        assert ">100%" in src, (
            "FE-LOW-024 regression: >100% clamp string missing."
        )
        # Applied to TP/SL preview
        assert "fmtPct((tpP-entry)/entry*100)" in src, (
            "FE-LOW-024 regression: TP preview not routed through fmtPct."
        )
        assert "fmtPct((slP-entry)/entry*100)" in src, (
            "FE-LOW-024 regression: SL preview not routed through fmtPct."
        )

    def test_pre_fix_toFixed_call_pattern_removed(self):
        """Pre-fix inline pattern `Math.abs(...).toFixed(2)+'%'` for TP/SL
        preview must be gone — the route now goes through fmtPct."""
        src = self._read()
        # The single line containing both TP and SL inline-toFixed calls
        # is the exact pre-fix shape. Match defensively.
        bad = "Math.abs((tpP-entry)/entry*100).toFixed(2)+'%'"
        assert bad not in src, (
            f"FE-LOW-024 regression: pre-fix inline pattern reintroduced: {bad}"
        )

    def test_anchor_comments_reference_fe_low_022_and_fe_low_024(self):
        src = self._read()
        assert "FE-LOW-022" in src and "Task 152" in src
        assert "FE-LOW-024" in src


# ── Jinja-global exposure pin ───────────────────────────────────────────────


class TestJinjaGlobalsExposed:
    """fmt_price and fmt_size must be exposed to templates."""

    def test_helpers_module_imports_formatters(self):
        from api import helpers
        assert hasattr(helpers, "_fmt_price")
        assert hasattr(helpers, "_fmt_size")

    def test_templates_env_has_fmt_price_and_fmt_size_globals(self):
        from api.helpers import templates
        assert "fmt_price" in templates.env.globals
        assert "fmt_size" in templates.env.globals
        # Smoke: invoke through the Jinja-bound callable
        assert templates.env.globals["fmt_price"](80816.30) == "80,816.30"
        assert templates.env.globals["fmt_size"](0.0314) == "0.0314"


# ── FBF: render the excursions fragment with a high-priced row ──────────────


class TestExcursionsCompileAndRender:
    """Compile-and-render pin (MED-047 discipline): synthesize a trades
    list with a high-priced symbol; the rendered HTML must contain the
    2-decimal form (not 4-decimal) for the ENTRY cell."""

    def test_rendered_entry_cell_adaptive(self):
        from jinja2 import Environment, FileSystemLoader
        from core.formatters import format_price, format_size

        env = Environment(loader=FileSystemLoader("templates"))
        env.globals["fmt"] = lambda v, d=2: f"{float(v):,.{d}f}" if v is not None else "—"
        env.globals["fmt_price"] = format_price
        env.globals["fmt_size"] = format_size
        env.globals["fmt_duration"] = lambda ms: "—"

        tmpl = env.get_template("fragments/analytics/excursions.html")
        ctx = {
            "period_label": "30D",
            "filter_dir": "all",
            "trades": [
                {
                    "symbol": "BTCUSDT", "direction": "LONG",
                    "entry_price": 80816.30,
                    "mfe": 100.0, "mae": -50.0,
                    "income": 25.0, "hold_ms": 60000,
                },
                {
                    "symbol": "AIAUSDT", "direction": "SHORT",
                    "entry_price": 0.0749,
                    "mfe": 5.0, "mae": -2.0,
                    "income": 1.5, "hold_ms": 60000,
                },
            ],
            "avg_mfe": 52.5, "avg_mae_abs": 26.0,
            "avg_mer": 2.0, "pct_favorable": 50,
            "scatter_data": [],
        }
        html = tmpl.render(**ctx)
        # BTC ENTRY rendered with magnitude-adaptive precision (2 decimals)
        assert "80,816.30" in html, (
            "FE-MED-021 fix surface: BTC entry not rendered at 2 decimals. "
            f"Rendered HTML excerpt: {html[:2000]}"
        )
        # Pre-fix 4-decimal form must NOT appear
        assert "80,816.3000" not in html, (
            "FE-MED-021 regression: 4-decimal form reintroduced."
        )
        # Sub-$1 keeps higher precision (audit endorses both 4 and 6 here;
        # we ship 6 to match JS fmtP — pin the actual behaviour)
        assert "0.074900" in html


# ── FE-LOW-024 JS clamp logic verification ──────────────────────────────────


class TestFmtPctLogic:
    """Replicate the JS clamp rule in Python to verify the inline pattern
    is sound. The JS itself isn't executed here — the Python mirror lets us
    pin the contract."""

    @staticmethod
    def _fmt_pct(pct):
        if pct is None or (isinstance(pct, float) and math.isnan(pct)):
            return "—"
        a = abs(pct)
        return ">100%" if a > 100 else f"{a:.2f}%"

    def test_in_range_two_decimals(self):
        assert self._fmt_pct(3.45) == "3.45%"
        assert self._fmt_pct(-12.7) == "12.70%"

    def test_at_100_renders_two_decimals(self):
        """Exactly 100% is in-range; >100 triggers the clamp."""
        assert self._fmt_pct(100.0) == "100.00%"
        assert self._fmt_pct(100.001) == ">100%"

    def test_audit_observed_value_clamped(self):
        """FE-LOW-024 audit case — 12314.75 → '>100%', not '12314.75%'."""
        assert self._fmt_pct(12314.75) == ">100%"
        assert self._fmt_pct(-11694.81) == ">100%"
