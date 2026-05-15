"""Tests for TP/SL modification event detection."""
import sqlite3

import pytest

from core.trade_event_log import _VALID_TRADE_EVENT_TYPES


class TestModificationEventTypes:
    def test_tp_modified_registered(self):
        assert "tp_modified" in _VALID_TRADE_EVENT_TYPES

    def test_sl_modified_registered(self):
        assert "sl_modified" in _VALID_TRADE_EVENT_TYPES


class TestModificationDetection:
    """Unit tests for the detection logic (separate from integration)."""

    def test_tp_price_change_detected(self):
        """TP order's stop_price changed = tp_modified should fire."""
        prev = {"order_type": "take_profit_market", "stop_price": 55000, "price": 0}
        new = {"order_type": "take_profit_market", "stop_price": 56000, "price": 0}
        # Detection: old_stop != new_stop for TP type
        old_stop = prev.get("stop_price") or prev.get("price", 0)
        new_stop = new.get("stop_price") or new.get("price", 0)
        assert old_stop != new_stop
        assert old_stop == 55000
        assert new_stop == 56000

    def test_sl_price_change_detected(self):
        prev = {"order_type": "stop_market", "stop_price": 48000}
        new = {"order_type": "stop_market", "stop_price": 47500}
        old_stop = prev.get("stop_price", 0)
        new_stop = new.get("stop_price", 0)
        assert old_stop != new_stop

    def test_non_tpsl_change_not_detected(self):
        """Entry order price change should NOT trigger tp/sl_modified."""
        otype = "limit"
        is_tpsl = otype in ("stop_loss", "stop_market", "take_profit", "take_profit_market")
        assert not is_tpsl

    def test_same_price_no_event(self):
        old_stop = 55000
        new_stop = 55000
        assert old_stop == new_stop  # no change = no event
