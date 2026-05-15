"""Tests for account detail form input validation attributes."""
import re

import pytest


def _parse_inputs(html: str) -> dict:
    """Extract name, step, min, max from all <input type=number> elements."""
    pattern = r'<input\s+type="number"[^>]*>'
    inputs = {}
    for match in re.finditer(pattern, html):
        tag = match.group()
        name = re.search(r'name="([^"]+)"', tag)
        step = re.search(r'step="([^"]+)"', tag)
        mn   = re.search(r'min="([^"]+)"', tag)
        mx   = re.search(r'max="([^"]+)"', tag)
        if name:
            inputs[name.group(1)] = {
                "step": step.group(1) if step else None,
                "min":  mn.group(1) if mn else None,
                "max":  mx.group(1) if mx else None,
            }
    return inputs


class TestStepGridValid:
    """Ensure step+min don't create grids that exclude common values."""

    COMMON_VALUES = {
        "individual_risk_per_trade": [0.005, 0.01, 0.02, 0.05],
        "max_w_loss_percent": [0.01, 0.03, 0.05, 0.10],
        "max_dd_percent": [0.05, 0.08, 0.10, 0.15],
    }

    def test_common_values_pass_validation(self):
        content = open("templates/fragments/account_detail.html", encoding="utf-8").read()
        inputs = _parse_inputs(content)
        for name, values in self.COMMON_VALUES.items():
            assert name in inputs, f"Input {name} not found"
            inp = inputs[name]
            step = float(inp["step"])
            mn = float(inp["min"])
            for v in values:
                # HTML5: valid if (value - min) / step is integer (within float tolerance)
                remainder = (v - mn) / step
                assert abs(remainder - round(remainder)) < 1e-9, \
                    f"{name}: value {v} fails step validation (step={step}, min={mn})"


class TestNoPercentInFractionLabels:
    """Labels for fraction fields should not include (%) to avoid confusion."""

    def test_risk_per_trade_no_pct_suffix(self):
        content = open("templates/fragments/account_detail.html", encoding="utf-8").read()
        # Find the label near individual_risk_per_trade
        idx = content.find("individual_risk_per_trade")
        block = content[max(0, idx-200):idx]
        assert "(%)" not in block

    def test_max_weekly_loss_no_pct_suffix(self):
        content = open("templates/fragments/account_detail.html", encoding="utf-8").read()
        idx = content.find("max_w_loss_percent")
        block = content[max(0, idx-200):idx]
        assert "(%)" not in block

    def test_max_dd_no_pct_suffix(self):
        content = open("templates/fragments/account_detail.html", encoding="utf-8").read()
        idx = content.find("max_dd_percent")
        block = content[max(0, idx-200):idx]
        assert "(%)" not in block


class TestHintTextPresent:
    def test_fraction_hints_shown(self):
        """Fraction fields show conversion hint (e.g., '0.01 = 1%')."""
        content = open("templates/fragments/account_detail.html", encoding="utf-8").read()
        assert "0.01 = 1%" in content
        assert "0.05 = 5%" in content
        assert "0.10 = 10%" in content
