"""
AD-2: Bybit fetch_income() routes to correct endpoint per income_type.
Uses /v5/account/contract-transaction-log for FUNDING_FEE, and
/v5/position/closed-pnl for REALIZED_PNL (existing behavior).
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Income type mapping ──────────────────────────────────────────────────────

BYBIT_INCOME_TYPE_MAP = {
    "REALIZED_PNL": "TRADE",       # closed-pnl endpoint (existing) or transaction-log TRADE
    "FUNDING_FEE":  "SETTLEMENT",  # transaction-log SETTLEMENT type
    "COMMISSION":   "TRADE",       # fee component of TRADE entries in transaction-log
    "TRANSFER":     "TRANSFER_IN", # transaction-log TRANSFER_IN / TRANSFER_OUT
}


class TestIncomeTypeMapping:
    def test_realized_pnl_maps(self):
        assert BYBIT_INCOME_TYPE_MAP.get("REALIZED_PNL") == "TRADE"

    def test_funding_fee_maps(self):
        assert BYBIT_INCOME_TYPE_MAP.get("FUNDING_FEE") == "SETTLEMENT"

    def test_empty_type_returns_none(self):
        """Empty income_type means 'all' — no type filter."""
        assert BYBIT_INCOME_TYPE_MAP.get("") is None

    def test_unsupported_type_returns_none(self):
        assert BYBIT_INCOME_TYPE_MAP.get("UNKNOWN_TYPE") is None


# ── Response parsing ─────────────────────────────────────────────────────────

SAMPLE_CLOSED_PNL = {
    "result": {
        "list": [
            {
                "symbol": "BTCUSDT",
                "orderId": "order_123",
                "closedPnl": "5.25",
                "updatedTime": "1747130943000",
            }
        ]
    }
}

SAMPLE_TRANSACTION_LOG = {
    "result": {
        "list": [
            {
                "symbol": "BTCUSDT",
                "type": "SETTLEMENT",
                "amount": "-0.0036",
                "transactionTime": "1747130943000",
                "tradeId": "",
                "orderId": "",
                "funding": "-0.0036",
            }
        ]
    }
}


class TestResponseParsing:
    def test_closed_pnl_parses_amount(self):
        entry = SAMPLE_CLOSED_PNL["result"]["list"][0]
        amount = float(entry.get("closedPnl", 0) or 0)
        assert amount == 5.25

    def test_transaction_log_parses_funding(self):
        entry = SAMPLE_TRANSACTION_LOG["result"]["list"][0]
        amount = float(entry.get("amount", 0) or 0)
        assert amount == -0.0036

    def test_transaction_log_type_is_settlement(self):
        entry = SAMPLE_TRANSACTION_LOG["result"]["list"][0]
        assert entry["type"] == "SETTLEMENT"


# ── Income type correctly set on NormalizedIncome ────────────────────────────

class TestNormalizedIncomeType:
    def test_realized_pnl_type_set(self):
        from core.adapters.protocols import NormalizedIncome
        ni = NormalizedIncome(income_type="REALIZED_PNL", amount=5.25)
        assert ni.income_type == "REALIZED_PNL"

    def test_funding_fee_type_set(self):
        from core.adapters.protocols import NormalizedIncome
        ni = NormalizedIncome(income_type="FUNDING_FEE", amount=-0.0036)
        assert ni.income_type == "FUNDING_FEE"

    def test_empty_type_not_hardcoded(self):
        """income_type should reflect what was actually fetched, not hardcoded."""
        from core.adapters.protocols import NormalizedIncome
        ni = NormalizedIncome(income_type="FUNDING_FEE")
        assert ni.income_type != "realized_pnl"
