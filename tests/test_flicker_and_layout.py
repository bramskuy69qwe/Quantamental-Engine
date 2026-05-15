"""Tests for flicker fix + panel height fix."""
import pytest


class TestFlickerFix:
    def test_no_inline_script_in_fragment(self):
        """Fragment should NOT contain <script> — moved to base.html."""
        content = open("templates/fragments/dashboard_positions.html", encoding="utf-8").read()
        # Should have a comment noting the move, not the actual script
        assert "<script>" not in content
        assert "moved to base.html" in content.lower()

    def test_tab_script_in_base(self):
        """Tab switcher script lives in base.html (survives morphs)."""
        content = open("templates/base.html", encoding="utf-8").read()
        assert "window.dtab" in content
        assert "_applyTab" in content

    def test_htmx_aftersettle_reapplies_tabs(self):
        """Tab state re-applied after morph settles."""
        content = open("templates/base.html", encoding="utf-8").read()
        assert "htmx:afterSettle" in content
        assert "_applyTab" in content

    def test_positions_panel_visible_by_default(self):
        """Positions panel should NOT have display:none (it's the default tab)."""
        content = open("templates/fragments/dashboard_positions.html", encoding="utf-8").read()
        # Find the dp-positions div
        lines = content.split("\n")
        for line in lines:
            if 'id="dp-positions"' in line:
                assert 'display:none' not in line, \
                    "Positions panel should be visible by default"
                break


class TestContainerIDs:
    def test_tbody_has_id(self):
        content = open("templates/fragments/dashboard_positions.html", encoding="utf-8").read()
        assert 'id="positions-tbody"' in content

    def test_table_has_id(self):
        content = open("templates/fragments/dashboard_positions.html", encoding="utf-8").read()
        assert 'id="positions-table"' in content


class TestPanelHeight:
    def test_grid_align_items_start(self):
        """Risk+positions grid should use align-items:start (content-driven height)."""
        content = open("templates/dashboard.html", encoding="utf-8").read()
        assert "align-items:start" in content
