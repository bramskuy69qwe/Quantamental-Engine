"""Tests for unified data row styling across history tables."""


class TestSemanticClassesDefined:
    """Verify semantic cell classes exist in base.html CSS."""

    EXPECTED_CLASSES = ["td-symbol", "td-ts", "td-sub", "td-dim", "td-bold", "td-empty"]

    def test_all_classes_in_base_css(self):
        content = open("templates/base.html", encoding="utf-8").read()
        for cls in self.EXPECTED_CLASSES:
            assert f".{cls}" in content, f"Missing class .{cls} in base.html CSS"


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
