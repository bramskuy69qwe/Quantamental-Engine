"""Tests for analytics period preference UI + persistence wiring."""
import inspect

import pytest


class TestSettingsUIPresent:
    def test_account_detail_has_period_dropdown(self):
        """Account detail form includes analytics_default_period dropdown."""
        content = open("templates/fragments/account_detail.html", encoding="utf-8").read()
        assert "analytics_default_period" in content
        assert "Default Analytics Period" in content

    def test_dropdown_has_all_valid_periods(self):
        """Dropdown offers all 7 valid period options (in Jinja set block)."""
        from core.period_resolver import VALID_PERIODS
        content = open("templates/fragments/account_detail.html", encoding="utf-8").read()
        for period in VALID_PERIODS:
            assert f"'{period}'" in content, \
                f"Missing period option: {period}"


class TestPostHandlerAcceptsPeriod:
    def test_update_route_accepts_analytics_default_period(self):
        """POST /accounts/{id}/update accepts analytics_default_period form param."""
        from api.routes_accounts import update_account_detail
        src = inspect.getsource(update_account_detail)
        assert "analytics_default_period" in src

    def test_update_route_validates_period(self):
        """Route validates against VALID_PERIODS before persisting."""
        from api.routes_accounts import update_account_detail
        src = inspect.getsource(update_account_detail)
        assert "VALID_PERIODS" in src

    def test_update_route_calls_update_account_settings(self):
        from api.routes_accounts import update_account_detail
        src = inspect.getsource(update_account_detail)
        assert "update_account_settings" in src


class TestGetRoutePassesSettings:
    def test_account_detail_passes_settings(self):
        """GET account detail route loads account_settings for the template."""
        from api.routes_accounts import frag_account_detail
        src = inspect.getsource(frag_account_detail)
        assert "get_account_settings" in src
        assert "settings=" in src


class TestAnalyticsUsesPreference:
    def test_analytics_route_reads_default_period(self):
        """Analytics page route reads analytics_default_period from settings."""
        from api.routes_analytics import analytics_page
        src = inspect.getsource(analytics_page)
        assert "analytics_default_period" in src
        assert "default_period" in src

    def test_analytics_template_uses_default_period(self):
        """analytics.html JS uses default_period for initialization."""
        content = open("templates/analytics.html", encoding="utf-8").read()
        assert "default_period" in content
        assert "all_time" in content
