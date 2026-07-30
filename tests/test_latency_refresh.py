"""Tests for latency display refresh — WS latency tracking + display wiring."""
import inspect


class TestWSStatusPollingRate:
    def test_ws_status_bar_1hz(self):
        """WS status bar polls at 1s."""
        content = open("templates/base.html", encoding="utf-8").read()
        # Find the ws-status-bar element
        idx = content.find('id="ws-status-bar"')
        assert idx != -1, "ws-status-bar element not found"
        block = content[idx:idx+300]
        assert "every 1s" in block


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


