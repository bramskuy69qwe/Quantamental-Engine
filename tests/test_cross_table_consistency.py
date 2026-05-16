"""Tests for cross-table presentation consistency."""
import pytest


TABLES = [
    "templates/fragments/history/closed_positions_table.html",
    "templates/fragments/history/order_history_table.html",
    "templates/fragments/history/trade_history_table.html",
    "templates/fragments/history/pre_trade_table.html",
]


class TestTitleFormat:
    @pytest.mark.parametrize("filepath", TABLES)
    def test_title_has_entries_suffix(self, filepath):
        """Title shows '(N entries)', not just '(N)'."""
        content = open(filepath, encoding="utf-8").read()
        assert "entries)" in content, \
            f"{filepath} title missing 'entries' suffix"


class TestSearchPlaceholder:
    @pytest.mark.parametrize("filepath", TABLES)
    def test_search_uses_symbol(self, filepath):
        """Search placeholder uses 'Search symbol...' consistently."""
        content = open(filepath, encoding="utf-8").read()
        assert 'Search symbol...' in content, \
            f"{filepath} should use 'Search symbol...' placeholder"

    @pytest.mark.parametrize("filepath", TABLES)
    def test_no_unicode_ellipsis(self, filepath):
        """Placeholders use three dots, not unicode ellipsis."""
        content = open(filepath, encoding="utf-8").read()
        # Check inside placeholder attributes only
        import re
        for m in re.finditer(r'placeholder="([^"]*)"', content):
            assert '\u2026' not in m.group(1), \
                f"{filepath} has unicode ellipsis in placeholder"


class TestTimestampFormat:
    """Timestamps should use space separator (YYYY-MM-DD HH:MM:SS), not ISO T."""

    def test_trade_history_replaces_t(self):
        content = open("templates/fragments/history/trade_history_table.html", encoding="utf-8").read()
        assert "replace('T', ' ')" in content

    def test_pre_trade_replaces_t(self):
        content = open("templates/fragments/history/pre_trade_table.html", encoding="utf-8").read()
        assert "replace('T', ' ')" in content

    def test_execution_replaces_t(self):
        content = open("templates/fragments/history/execution_table.html", encoding="utf-8").read()
        assert "replace('T', ' ')" in content


class TestSearchInputWidth:
    @pytest.mark.parametrize("filepath", TABLES)
    def test_input_width_140(self, filepath):
        """All search inputs use width:140px."""
        content = open(filepath, encoding="utf-8").read()
        import re
        for m in re.finditer(r'class="hist-input"[^>]*style="([^"]*)"', content):
            assert "140px" in m.group(1), \
                f"{filepath} search input not 140px wide"
