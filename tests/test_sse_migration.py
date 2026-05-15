"""Tests for SSE migration: publishers + multiplexed endpoint + fragment triggers."""
import pytest

from core.pubsub.channels import (
    channel_pattern, extract_event_type,
    position_channel, fill_channel, order_channel,
    equity_channel, dd_state_channel, weekly_pnl_channel,
)


class TestChannelHelpers:
    def test_channel_pattern(self):
        assert channel_pattern(1) == "account:1:*"

    def test_extract_event_type(self):
        assert extract_event_type("account:1:position_update") == "position_update"
        assert extract_event_type("account:42:fill") == "fill"
        assert extract_event_type("account:1:dd_state") == "dd_state"

    def test_weekly_pnl_channel(self):
        assert weekly_pnl_channel(1) == "account:1:weekly_pnl"


class TestPublisherHooks:
    """Verify publisher hooks exist in source code."""

    def test_position_publisher_in_data_cache(self):
        import inspect
        from core.data_cache import DataCache
        src = inspect.getsource(DataCache.apply_position_snapshot)
        assert "position_channel" in src

    def test_dd_state_publisher_in_data_cache(self):
        import inspect
        from core.data_cache import DataCache
        src = inspect.getsource(DataCache._do_recalculate_portfolio)
        assert "dd_state_channel" in src

    def test_equity_publisher_in_handlers(self):
        import inspect
        from core import handlers
        src = inspect.getsource(handlers.handle_account_updated)
        assert "equity_channel" in src

    def test_order_publisher_in_order_manager(self):
        import inspect
        from core.order_manager import OrderManager
        src = inspect.getsource(OrderManager._publish_order_update)
        assert "order_channel" in src

    def test_fill_publisher_in_order_manager(self):
        import inspect
        from core.order_manager import OrderManager
        src = inspect.getsource(OrderManager._publish_fill)
        assert "fill_channel" in src


class TestMultiplexedEndpoint:
    def test_route_registered(self):
        from api.routes_streams import stream_account
        assert callable(stream_account)

    def test_per_channel_preserved(self):
        from api.routes_streams import stream_positions
        assert callable(stream_positions)


class TestSSEExtension:
    def test_sse_script_in_base(self):
        content = open("templates/base.html", encoding="utf-8").read()
        assert "ext/sse.js" in content

    def test_sse_connect_in_dashboard(self):
        content = open("templates/dashboard.html", encoding="utf-8").read()
        assert "sse-connect" in content
        assert "/stream/account/" in content


class TestFragmentTriggers:
    def test_positions_triggers_on_sse(self):
        # SSE triggers moved from dashboard.html to individual tbodies in the shell
        content = open("templates/fragments/dashboard_positions.html", encoding="utf-8").read()
        assert "sse:position_update" in content

    def test_risk_triggers_on_sse(self):
        content = open("templates/dashboard.html", encoding="utf-8").read()
        assert "sse:dd_state" in content

    def test_equity_triggers_on_sse(self):
        content = open("templates/dashboard.html", encoding="utf-8").read()
        assert "sse:equity_update" in content

    def test_fallback_polling_present(self):
        content = open("templates/dashboard.html", encoding="utf-8").read()
        assert "every 30s" in content

    def test_journal_stats_no_sse(self):
        """Low-frequency data stays on pure polling."""
        content = open("templates/dashboard.html", encoding="utf-8").read()
        lines = content.split("\n")
        for line in lines:
            if "journal_stats" in line:
                # Should NOT have sse: trigger
                if "hx-trigger" in line:
                    assert "sse:" not in line
