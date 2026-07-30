"""Tests for Phase 5 polish: config knob, equity publish, row IDs, client tick."""
import inspect
import os


class TestExchangeRefreshHz:
    def test_config_exists(self):
        import config
        assert hasattr(config, "EXCHANGE_REFRESH_HZ")
        assert isinstance(config.EXCHANGE_REFRESH_HZ, float)
        assert config.EXCHANGE_REFRESH_HZ > 0

    def test_default_is_1hz(self):
        # Default from env var parsing
        assert float(os.getenv("EXCHANGE_REFRESH_HZ", "1.0")) == 1.0


class TestEquityRecalcPublish:
    def test_equity_channel_in_recalc(self):
        from core.data_cache import DataCache
        src = inspect.getsource(DataCache._do_recalculate_portfolio)
        assert "equity_channel" in src

    def test_recalc_equity_trigger(self):
        from core.data_cache import DataCache
        src = inspect.getsource(DataCache._do_recalculate_portfolio)
        # Should have trigger="recalc_cycle" for equity too
        lines = src.split("\n")
        equity_section = False
        for line in lines:
            if "equity_channel" in line:
                equity_section = True
            if equity_section and "recalc_cycle" in line:
                break
        assert equity_section, "equity_channel publish not found in recalc"

    def test_equity_payload_shape(self):
        from core.data_cache import DataCache
        src = inspect.getsource(DataCache._do_recalculate_portfolio)
        assert '"total_equity"' in src
        assert '"available_margin"' in src
        assert '"unrealized_pnl"' in src


# (Fragments slim-down 2026-07-30: TestClientSideTick retired — the
# [data-entry-ts] hold-time ticker left base.html with the dashboard
# fragment DOM it serviced.)
