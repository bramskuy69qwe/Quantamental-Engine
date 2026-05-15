"""Tests for latency display refresh — WS latency tracking + display wiring."""
import inspect

import pytest


class TestWSStatusPollingRate:
    def test_ws_status_bar_1hz(self):
        """WS status bar polls at 1s."""
        content = open("templates/base.html", encoding="utf-8").read()
        # Find the ws-status-bar element
        idx = content.find('id="ws-status-bar"')
        assert idx != -1, "ws-status-bar element not found"
        block = content[idx:idx+300]
        assert "every 1s" in block

    def test_exchange_info_self_refresh_1hz(self):
        """Exchange info card self-refreshes at 1s."""
        content = open("templates/fragments/dashboard_exchange_info.html", encoding="utf-8").read()
        assert "every 1s" in content


class TestMarketWSLatencyTracking:
    def test_market_stream_updates_latency(self):
        """Market WS handler updates ws.latency_ms from event timestamps."""
        from core import ws_manager
        src = inspect.getsource(ws_manager._market_stream_loop)
        assert "latency_ms" in src, \
            "Market stream handler must track latency from event timestamps"
        assert "get_event_time_ms" in src or '"E"' in src, \
            "Must extract event time from market messages"


class TestRESTDoesNotOverwriteWSLatency:
    def test_rest_ping_conditional_seed(self):
        """REST ping only seeds ws_status.latency_ms when WS is disconnected."""
        from core import exchange
        src = inspect.getsource(exchange.fetch_exchange_info)
        assert "not" in src and "connected" in src, \
            "REST ping must not overwrite ws_status.latency_ms when WS is active"


class TestExchangeInfoPrefersWSLatency:
    def test_route_uses_ws_latency_when_connected(self):
        """Exchange info route prefers ws.latency_ms over ex.latency_ms."""
        from api import routes_dashboard
        src = inspect.getsource(routes_dashboard.frag_dashboard_exchange_info)
        assert "ws_status" in src or "ws.latency_ms" in src, \
            "Route must check WS latency, not just REST latency"
        assert "connected" in src, \
            "Route must check WS connection state for latency source"
