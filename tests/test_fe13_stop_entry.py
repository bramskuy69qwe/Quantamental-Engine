"""
FE-13: Stop entry vs stop_loss disambiguation.
Orders with reduceOnly=false and closePosition=false should get _entry suffix.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Classification logic ─────────────────────────────────────────────────────

def _classify(order_type: str, reduce_only: bool, close_position: bool = False) -> str:
    """Replicate the inline classification check."""
    if order_type in ("stop_loss", "take_profit") and not reduce_only and not close_position:
        return order_type + "_entry"
    return order_type


class TestClassification:
    def test_protective_sl_unchanged(self):
        assert _classify("stop_loss", reduce_only=True) == "stop_loss"

    def test_protective_tp_unchanged(self):
        assert _classify("take_profit", reduce_only=True) == "take_profit"

    def test_entry_stop_gets_suffix(self):
        assert _classify("stop_loss", reduce_only=False) == "stop_loss_entry"

    def test_entry_tp_gets_suffix(self):
        assert _classify("take_profit", reduce_only=False) == "take_profit_entry"

    def test_close_all_stop_no_suffix(self):
        """closePosition=true with reduceOnly=false → still a close, no _entry."""
        assert _classify("stop_loss", reduce_only=False, close_position=True) == "stop_loss"

    def test_close_all_tp_no_suffix(self):
        assert _classify("take_profit", reduce_only=False, close_position=True) == "take_profit"

    def test_limit_unaffected(self):
        assert _classify("limit", reduce_only=False) == "limit"

    def test_market_unaffected(self):
        assert _classify("market", reduce_only=False) == "market"

    def test_trailing_stop_unaffected(self):
        assert _classify("trailing_stop", reduce_only=False) == "trailing_stop"


# ── _TPSL_TYPES exclusion ───────────────────────────────────────────────────

class TestTpslExclusion:
    def test_entry_types_not_in_tpsl_set(self):
        """Entry types must NOT be in _TPSL_TYPES — prevents phantom enrichment."""
        from core.ws_manager import _TPSL_TYPES
        assert "stop_loss_entry" not in _TPSL_TYPES
        assert "take_profit_entry" not in _TPSL_TYPES

    def test_protective_types_still_in_tpsl_set(self):
        from core.ws_manager import _TPSL_TYPES
        assert "stop_loss" in _TPSL_TYPES
        assert "take_profit" in _TPSL_TYPES
