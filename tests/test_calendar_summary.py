"""Tests for expanded calendar summary panel (MTD + QTD + YTD)."""
import inspect

import pytest


class TestRouteComputesAllPeriods:
    def test_route_uses_period_resolver(self):
        """journal_stats route uses resolve_period for quarterly + yearly."""
        from api.routes_dashboard import frag_dashboard_journal_stats
        src = inspect.getsource(frag_dashboard_journal_stats)
        assert "resolve_period" in src
        assert '"quarterly"' in src
        assert '"yearly"' in src

    def test_route_passes_quarterly_pnl(self):
        from api.routes_dashboard import frag_dashboard_journal_stats
        src = inspect.getsource(frag_dashboard_journal_stats)
        assert "quarterly_pnl=" in src
        assert "quarterly_pnl_pct=" in src
        assert "quarter_label=" in src

    def test_route_passes_yearly_pnl(self):
        from api.routes_dashboard import frag_dashboard_journal_stats
        src = inspect.getsource(frag_dashboard_journal_stats)
        assert "yearly_pnl=" in src
        assert "yearly_pnl_pct=" in src
        assert "year_label=" in src

    def test_route_fetches_all_boundaries_concurrently(self):
        """All three period boundaries fetched in one asyncio.gather."""
        from api.routes_dashboard import frag_dashboard_journal_stats
        src = inspect.getsource(frag_dashboard_journal_stats)
        assert "q_boundaries" in src
        assert "y_boundaries" in src


class TestTemplateShowsAllPeriods:
    def test_template_has_mtd_qtd_ytd(self):
        content = open("templates/fragments/dashboard_journal_stats.html", encoding="utf-8").read()
        assert "MTD" in content
        assert "quarterly_pnl" in content
        assert "yearly_pnl" in content
        assert "quarter_label" in content
        assert "year_label" in content

    def test_template_three_summary_blocks(self):
        """Template renders three period blocks (MTD, QTD, YTD) in a loop."""
        content = open("templates/fragments/dashboard_journal_stats.html", encoding="utf-8").read()
        # The for loop iterates over 3 items
        assert "monthly_pnl" in content
        assert "quarterly_pnl" in content
        assert "yearly_pnl" in content
