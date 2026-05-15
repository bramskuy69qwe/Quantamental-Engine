"""Tests for analytics period preference + timezone UI + full period wiring."""
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

    def test_timezone_dropdown_present(self):
        """Account detail form includes timezone dropdown."""
        content = open("templates/fragments/account_detail.html", encoding="utf-8").read()
        assert 'name="timezone"' in content
        assert "Timezone" in content
        assert "Asia/Bangkok" in content
        assert "UTC" in content


class TestPostHandler:
    def test_accepts_analytics_default_period(self):
        from api.routes_accounts import update_account_detail
        src = inspect.getsource(update_account_detail)
        assert "analytics_default_period" in src

    def test_accepts_timezone(self):
        from api.routes_accounts import update_account_detail
        src = inspect.getsource(update_account_detail)
        assert "timezone" in src

    def test_validates_period(self):
        from api.routes_accounts import update_account_detail
        src = inspect.getsource(update_account_detail)
        assert "VALID_PERIODS" in src

    def test_validates_timezone(self):
        """Timezone is validated via ZoneInfo before persisting."""
        from api.routes_accounts import update_account_detail
        src = inspect.getsource(update_account_detail)
        assert "ZoneInfo" in src


class TestGetRoutePassesSettings:
    def test_account_detail_passes_settings(self):
        from api.routes_accounts import frag_account_detail
        src = inspect.getsource(frag_account_detail)
        assert "get_account_settings" in src
        assert "settings=" in src


class TestAnalyticsUsesPreference:
    def test_analytics_route_reads_default_period(self):
        from api.routes_analytics import analytics_page
        src = inspect.getsource(analytics_page)
        assert "analytics_default_period" in src
        assert "default_period" in src

    def test_analytics_template_uses_default_period(self):
        content = open("templates/analytics.html", encoding="utf-8").read()
        assert "default_period" in content
        assert "_period" in content


class TestAnalyticsRangeAcceptsPeriod:
    def test_analytics_range_has_period_param(self):
        from api.routes_analytics import _analytics_range
        src = inspect.getsource(_analytics_range)
        assert "period" in src
        assert "resolve_period" in src

    def test_overview_route_accepts_period(self):
        from api.routes_analytics import frag_analytics_overview
        src = inspect.getsource(frag_analytics_overview)
        assert "period" in src
        assert "offset" in src

    def test_all_period_routes_accept_params(self):
        """All routes that call _analytics_range also accept period+offset."""
        from api import routes_analytics
        for name in ["frag_analytics_overview", "frag_analytics_pairs",
                      "frag_analytics_excursions", "frag_analytics_r_multiples",
                      "frag_analytics_var"]:
            fn = getattr(routes_analytics, name)
            src = inspect.getsource(fn)
            assert "period" in src, f"{name} missing period param"
            assert "offset" in src, f"{name} missing offset param"


class TestAnalyticsNavigation:
    def test_template_has_period_presets(self):
        """analytics.html has preset buttons for all 7 periods."""
        from core.period_resolver import VALID_PERIODS
        content = open("templates/analytics.html", encoding="utf-8").read()
        assert 'id="pp-{{ val }}"' in content  # Jinja loop pattern
        for period in VALID_PERIODS:
            assert f"'{period}'" in content, f"Missing period in presets: {period}"

    def test_nav_disabled_for_rolling(self):
        """Rolling/all_time periods disable nav buttons."""
        content = open("templates/analytics.html", encoding="utf-8").read()
        assert "_noNav" in content
        assert "rolling_30d" in content
        assert "all_time" in content


class TestDeadConstantRemoved:
    def test_no_timezone_offset_hours_in_config(self):
        """TIMEZONE_OFFSET_HOURS removed from config.py (dead constant)."""
        content = open("config.py", encoding="utf-8").read()
        assert "TIMEZONE_OFFSET_HOURS" not in content
