"""Tests for unified data row styling across history tables."""
import re

import pytest


class TestSemanticClassesDefined:
    """Verify semantic cell classes exist in base.html CSS."""

    EXPECTED_CLASSES = ["td-symbol", "td-ts", "td-sub", "td-dim", "td-bold", "td-empty"]

    def test_all_classes_in_base_css(self):
        content = open("templates/base.html", encoding="utf-8").read()
        for cls in self.EXPECTED_CLASSES:
            assert f".{cls}" in content, f"Missing class .{cls} in base.html CSS"


class TestTablesUseSemanticClasses:
    """Target tables should use semantic classes instead of inline color styles."""

    TABLES = [
        "templates/fragments/history/closed_positions_table.html",
        "templates/fragments/history/order_history_table.html",
        "templates/fragments/history/trade_history_table.html",
        "templates/fragments/history/pre_trade_table.html",
    ]

    @pytest.mark.parametrize("filepath", TABLES)
    def test_symbol_cells_use_class(self, filepath):
        content = open(filepath, encoding="utf-8").read()
        assert "td-symbol" in content, f"{filepath} should use .td-symbol class"

    @pytest.mark.parametrize("filepath", TABLES)
    def test_timestamp_cells_use_class(self, filepath):
        content = open(filepath, encoding="utf-8").read()
        assert "td-ts" in content, f"{filepath} should use .td-ts class"

    @pytest.mark.parametrize("filepath", TABLES)
    def test_no_inline_symbol_style(self, filepath):
        """Symbol cells should not use inline color:var(--blue);font-weight:700."""
        content = open(filepath, encoding="utf-8").read()
        # The exact inline pattern that should be replaced by .td-symbol
        assert 'style="color:var(--blue);font-weight:700;"' not in content, \
            f"{filepath} still has inline symbol styling"


class TestStyleConsistency:
    """All four tables use the same timestamp font-size via .td-ts class."""

    def test_td_ts_has_consistent_size(self):
        """td-ts class should set font-size:.68rem (matching dashboard canonical)."""
        content = open("templates/base.html", encoding="utf-8").read()
        # Find the td-ts rule
        idx = content.find(".td-ts")
        assert idx != -1
        rule = content[idx:idx+80]
        assert ".68rem" in rule
