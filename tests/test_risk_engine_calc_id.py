"""Regression test: calc_id NameError in run_risk_calculator."""
import pytest

from core.risk_engine import run_risk_calculator


class TestCalcIdPresent:
    def test_no_name_error(self):
        """run_risk_calculator must not raise NameError for calc_id."""
        result = run_risk_calculator(
            ticker="BTCUSDT",
            average=50000.0,
            sl_price=49000.0,
            tp_price=52000.0,
            tp_amount_pct=100.0,
            sl_amount_pct=100.0,
        )
        # Should not raise NameError
        assert "calc_id" in result

    def test_calc_id_is_nonempty_string(self):
        result = run_risk_calculator(
            ticker="ETHUSDT",
            average=3000.0,
            sl_price=2900.0,
            tp_price=3200.0,
            tp_amount_pct=100.0,
            sl_amount_pct=100.0,
        )
        assert isinstance(result["calc_id"], str)
        assert len(result["calc_id"]) > 0

    def test_calc_id_unique_per_call(self):
        r1 = run_risk_calculator(
            ticker="BTCUSDT", average=50000, sl_price=49000,
            tp_price=52000, tp_amount_pct=100, sl_amount_pct=100,
        )
        r2 = run_risk_calculator(
            ticker="BTCUSDT", average=50000, sl_price=49000,
            tp_price=52000, tp_amount_pct=100, sl_amount_pct=100,
        )
        assert r1["calc_id"] != r2["calc_id"]

    def test_ineligible_path_has_calc_id(self):
        """Even when eligible=False, calc_id should be present."""
        result = run_risk_calculator(
            ticker="BTCUSDT",
            average=0.0,  # invalid → eligible=False
            sl_price=0.0,
            tp_price=0.0,
            tp_amount_pct=100.0,
            sl_amount_pct=100.0,
        )
        assert "calc_id" in result
        assert isinstance(result["calc_id"], str)
