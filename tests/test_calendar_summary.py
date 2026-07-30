"""Tests for expanded calendar summary panel (MTD + QTD + YTD)."""
import inspect


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
        """The surviving consumer — /api/dashboard/snapshot — renders the
        shared builder's context. (Fragments slim-down 2026-07-30: the
        journal_stats fragment + template retired; the builder now feeds
        the React Dashboard through the snapshot alone.)"""
        from api.routes_dashboard import api_dashboard_snapshot
        src = inspect.getsource(api_dashboard_snapshot)
        assert "_journal_stats_context" in src
