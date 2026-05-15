"""Tests for dashboard fragment endpoint split."""
import os

import pytest


class TestFragmentTemplatesExist:
    """Verify fragment templates exist and are fragments (not full pages)."""

    FRAGMENTS = [
        "dashboard_risk.html",
        "dashboard_positions.html",
        "dashboard_body.html",  # original (still exists as backward-compatible)
        "dashboard_top.html",
        "dashboard_secondary.html",
        "dashboard_exchange_info.html",
        "dashboard_journal_stats.html",
    ]

    @pytest.mark.parametrize("name", FRAGMENTS)
    def test_template_exists(self, name):
        path = os.path.join("templates", "fragments", name)
        assert os.path.exists(path), f"Template {name} not found"

    @pytest.mark.parametrize("name", ["dashboard_risk.html", "dashboard_positions.html"])
    def test_fragment_not_full_page(self, name):
        """Fragments should NOT contain <html> or <body> tags."""
        path = os.path.join("templates", "fragments", name)
        content = open(path, encoding="utf-8").read()
        assert "<html" not in content.lower()
        assert "<body" not in content.lower()
        assert "{% extends" not in content  # fragments don't extend base


class TestDashboardTemplateUsesFragments:
    def test_dashboard_references_risk_fragment(self):
        content = open("templates/dashboard.html", encoding="utf-8").read()
        assert "/fragments/dashboard/risk" in content

    def test_dashboard_references_positions_fragment(self):
        content = open("templates/dashboard.html", encoding="utf-8").read()
        assert "/fragments/dashboard/positions" in content

    def test_fragments_have_hx_trigger(self):
        content = open("templates/dashboard.html", encoding="utf-8").read()
        # Shell loads once; SSE triggers are on individual tbodies inside the shell
        assert 'hx-trigger="load"' in content


class TestFragmentContent:
    def test_risk_has_dd_gauge(self):
        content = open("templates/fragments/dashboard_risk.html", encoding="utf-8").read()
        assert "Rolling DD" in content
        assert "Weekly PnL" in content
        assert "Exposure" in content

    def test_positions_has_table(self):
        content = open("templates/fragments/dashboard_positions.html", encoding="utf-8").read()
        assert "<table" in content  # tables have id attrs now
        assert "Symbol" in content
        assert "Positions" in content

    def test_positions_has_orders_tab(self):
        content = open("templates/fragments/dashboard_positions.html", encoding="utf-8").read()
        assert "Open Orders" in content
        assert "Order History" in content


class TestRouteRegistration:
    def test_risk_route_exists(self):
        from api.routes_dashboard import frag_dashboard_risk
        assert callable(frag_dashboard_risk)

    def test_positions_route_exists(self):
        from api.routes_dashboard import frag_dashboard_positions
        assert callable(frag_dashboard_positions)

    def test_positions_rows_route_exists(self):
        from api.routes_dashboard import frag_dashboard_positions_rows
        assert callable(frag_dashboard_positions_rows)

    def test_original_dashboard_route_preserved(self):
        """Backward-compatible: /fragments/dashboard still works."""
        from api.routes_dashboard import frag_dashboard
        assert callable(frag_dashboard)
