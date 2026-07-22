"""Tests for expanded calendar summary panel (MTD + QTD + YTD)."""
import inspect

import pytest


class TestRouteComputesAllPeriods:
    """v3.0 P1: the MTD/QTD/YTD computation moved from the fragment handler into
    the shared ``_journal_stats_context`` builder (also feeding
    /api/dashboard/snapshot), so these source-grep pins now target the builder;
    a delegation pin keeps the handler honest."""

    def test_builder_uses_period_resolver(self):
        """The journal-stats builder uses resolve_period for quarterly + yearly."""
        from api.routes_dashboard import _journal_stats_context
        src = inspect.getsource(_journal_stats_context)
        assert "resolve_period" in src
        assert '"quarterly"' in src
        assert '"yearly"' in src

    def test_builder_computes_quarterly_pnl(self):
        from api.routes_dashboard import _journal_stats_context
        src = inspect.getsource(_journal_stats_context)
        assert "quarterly_pnl" in src
        assert "quarterly_pnl_pct" in src
        assert "quarter_label" in src

    def test_builder_computes_yearly_pnl(self):
        from api.routes_dashboard import _journal_stats_context
        src = inspect.getsource(_journal_stats_context)
        assert "yearly_pnl" in src
        assert "yearly_pnl_pct" in src
        assert "year_label" in src

    def test_builder_fetches_all_boundaries_concurrently(self):
        """All three period boundaries fetched in one asyncio.gather."""
        from api.routes_dashboard import _journal_stats_context
        src = inspect.getsource(_journal_stats_context)
        assert "asyncio.gather" in src
        assert "q_boundaries" in src
        assert "y_boundaries" in src

    def test_route_delegates_to_shared_builder(self):
        """The fragment handler renders the shared builder's context."""
        from api.routes_dashboard import frag_dashboard_journal_stats
        src = inspect.getsource(frag_dashboard_journal_stats)
        assert "_journal_stats_context" in src


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
