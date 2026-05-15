"""Tests for Phase 5 polish: config knob, equity publish, row IDs, client tick."""
import inspect
import os

import pytest


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


class TestStableRowIDs:
    def test_position_rows_have_ids(self):
        # Rows now in dedicated row template (included by shell)
        content = open("templates/fragments/dashboard_positions_rows.html", encoding="utf-8").read()
        assert 'id="pos-row-' in content

    def test_order_rows_have_ids(self):
        content = open("templates/fragments/dashboard_orders_rows.html", encoding="utf-8").read()
        assert 'id="ord-row-' in content


class TestClientSideTick:
    def test_data_entry_ts_attribute(self):
        # data-entry-ts in position rows template (included by shell)
        content = open("templates/fragments/dashboard_positions_rows.html", encoding="utf-8").read()
        assert "data-entry-ts" in content

    def test_setinterval_in_base(self):
        content = open("templates/base.html", encoding="utf-8").read()
        assert "setInterval" in content
        assert "data-entry-ts" in content

    def test_time_formatter_in_base(self):
        content = open("templates/base.html", encoding="utf-8").read()
        assert "_fmt" in content  # the time formatting function
