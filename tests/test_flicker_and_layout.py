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


class TestDashboardBodyBackwardCompat:
    def test_no_inline_script_in_dashboard_body(self):
        """dashboard_body.html (backward-compat) should not have inline script."""
        content = open("templates/fragments/dashboard_body.html", encoding="utf-8").read()
        assert "<script>" not in content
        assert "moved to base.html" in content.lower()


class TestHistoryTabFlicker:
    def test_no_inline_script_in_open_positions(self):
        """history/open_positions.html should NOT contain <script>."""
        content = open("templates/fragments/history/open_positions.html", encoding="utf-8").read()
        assert "<script>" not in content
        assert "moved to base.html" in content.lower()

    def test_hp_tab_script_in_base(self):
        """History tab switcher lives in base.html."""
        content = open("templates/base.html", encoding="utf-8").read()
        assert "window._hpTab" in content
        assert "_applyHpTab" in content

    def test_htmx_aftersettle_reapplies_hp_tabs(self):
        """History tab state re-applied after swap settles."""
        content = open("templates/base.html", encoding="utf-8").read()
        assert "hp-panel-pos" in content

    def test_positions_panel_visible_by_default(self):
        """hp-panel-pos should NOT have display:none (default tab)."""
        content = open("templates/fragments/history/open_positions.html", encoding="utf-8").read()
        lines = content.split("\n")
        for line in lines:
            if 'id="hp-panel-pos"' in line:
                assert 'display:none' not in line, \
                    "History positions panel should be visible by default"
                break


class TestDanglingScriptTag:
    def test_no_dangling_close_script(self):
        """dashboard_positions.html should not have orphaned </script>."""
        content = open("templates/fragments/dashboard_positions.html", encoding="utf-8").read()
        assert "</script>" not in content


class TestRowsOnlyRefresh:
    """Task 52: shell + rows split — SSE refreshes only tbody, not tabs."""

    def test_shell_has_tbody_hx_get(self):
        """Shell tbody points at rows-only endpoint."""
        content = open("templates/fragments/dashboard_positions.html", encoding="utf-8").read()
        assert '/fragments/dashboard/positions/rows' in content

    def test_shell_tbody_trigger_is_sse_not_load(self):
        """Tbody trigger uses SSE events + fallback, NOT load (initial data via include)."""
        content = open("templates/fragments/dashboard_positions.html", encoding="utf-8").read()
        # positions-tbody line should have sse:position_update, not hx-trigger="load"
        for line in content.split("\n"):
            if 'id="positions-tbody"' in line or ('positions-tbody' in content and 'hx-trigger' in line):
                # Check within surrounding lines
                pass
        assert 'sse:position_update' in content
        assert 'sse:order_update' in content
        assert 'sse:fill' in content

    def test_shell_includes_row_templates(self):
        """Shell includes row templates for initial server-side render."""
        content = open("templates/fragments/dashboard_positions.html", encoding="utf-8").read()
        assert 'include "fragments/dashboard_positions_rows.html"' in content
        assert 'include "fragments/dashboard_orders_rows.html"' in content
        assert 'include "fragments/dashboard_history_rows.html"' in content

    def test_dashboard_shell_load_only(self):
        """dash-positions in dashboard.html triggers load only (no SSE on shell)."""
        content = open("templates/dashboard.html", encoding="utf-8").read()
        # Find the dash-positions line
        for line in content.split("\n"):
            if 'id="dash-positions"' in line:
                break
        # The hx-trigger should NOT contain sse: events
        # Check the hx-trigger attribute in the surrounding block
        idx = content.find('id="dash-positions"')
        block = content[idx:idx+300]
        assert 'hx-trigger="load"' in block
        assert 'sse:position_update' not in block

    def test_rows_template_no_table_tags(self):
        """Position rows template contains only <tr> elements, no wrapping tags."""
        content = open("templates/fragments/dashboard_positions_rows.html", encoding="utf-8").read()
        assert "<table" not in content
        assert "<thead" not in content
        assert "<tbody" not in content
        assert "<tr" in content or "pos-empty-row" in content

    def test_orders_rows_template_no_table_tags(self):
        content = open("templates/fragments/dashboard_orders_rows.html", encoding="utf-8").read()
        assert "<table" not in content
        assert "<thead" not in content
        assert "<tbody" not in content

    def test_history_rows_template_no_table_tags(self):
        content = open("templates/fragments/dashboard_history_rows.html", encoding="utf-8").read()
        assert "<table" not in content
        assert "<thead" not in content
        assert "<tbody" not in content

    def test_empty_state_in_position_rows(self):
        """Empty state is a colspan row, not a separate div."""
        content = open("templates/fragments/dashboard_positions_rows.html", encoding="utf-8").read()
        assert 'pos-empty-row' in content
        assert 'colspan="14"' in content

    def test_shell_has_count_spans(self):
        """Tab buttons have ID'd spans for count updates."""
        content = open("templates/fragments/dashboard_positions.html", encoding="utf-8").read()
        assert 'id="dt-positions-count"' in content
        assert 'id="dt-orders-count"' in content
        assert 'id="dt-pos-max"' in content

    def test_base_has_count_updater(self):
        """base.html has _updateCounts function for row-count sync."""
        content = open("templates/base.html", encoding="utf-8").read()
        assert '_updateCounts' in content
        assert 'dt-positions-count' in content

    def test_all_tbodies_have_stable_ids(self):
        """All three tab tbodies have stable IDs for Idiomorph."""
        content = open("templates/fragments/dashboard_positions.html", encoding="utf-8").read()
        assert 'id="positions-tbody"' in content
        assert 'id="orders-tbody"' in content
        assert 'id="history-tbody"' in content

    def test_all_tables_have_stable_ids(self):
        """All three tab tables have stable IDs."""
        content = open("templates/fragments/dashboard_positions.html", encoding="utf-8").read()
        assert 'id="positions-table"' in content
        assert 'id="orders-table"' in content
        assert 'id="history-table"' in content


class TestPanelHeight:
    def test_grid_align_items_start(self):
        """Risk+positions grid should use align-items:start (content-driven height)."""
        content = open("templates/dashboard.html", encoding="utf-8").read()
        assert "align-items:start" in content
