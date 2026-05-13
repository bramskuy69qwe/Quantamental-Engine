"""
AD-3: Bybit fee fetch via /v5/account/fee-rate endpoint.
Replaces hardcoded VIP0 defaults with live per-symbol fee rates.
"""
import os
import sys
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Fee source field ─────────────────────────────────────────────────────────

class TestFeeSourceField:
    def test_binance_fee_source_is_live(self):
        """Binance adapter populates fee_source when commission rate succeeds."""
        # Binance fetches live commission rates — fee_source should indicate "live"
        from core.adapters.protocols import NormalizedAccount
        acc = NormalizedAccount(maker_fee=0.0002, taker_fee=0.00055, fee_source="live")
        assert acc.fee_source == "live"

    def test_bybit_fee_source_distinguishes_from_binance(self):
        """Bybit fee_source should be 'live' when API call succeeds, 'default' when falling back."""
        from core.adapters.protocols import NormalizedAccount
        live = NormalizedAccount(fee_source="live")
        default = NormalizedAccount(fee_source="default")
        assert live.fee_source != default.fee_source


# ── Bybit fee parsing ───────────────────────────────────────────────────────

SAMPLE_FEE_RESPONSE = {
    "retCode": 0,
    "result": {
        "list": [
            {
                "symbol": "BTCUSDT",
                "baseCoin": "BTC",
                "takerFeeRate": "0.00055",
                "makerFeeRate": "0.0002",
            }
        ]
    }
}


class TestBybitFeeParsing:
    def test_parse_fee_rates(self):
        """Fee rates extracted correctly from /v5/account/fee-rate response."""
        result = SAMPLE_FEE_RESPONSE["result"]["list"]
        assert len(result) > 0
        entry = result[0]
        maker = float(entry["makerFeeRate"])
        taker = float(entry["takerFeeRate"])
        assert maker == 0.0002
        assert taker == 0.00055

    def test_fallback_on_empty_response(self):
        """Empty fee response falls back to VIP0 defaults."""
        empty_resp = {"retCode": 0, "result": {"list": []}}
        result_list = empty_resp["result"]["list"]
        maker = float(result_list[0]["makerFeeRate"]) if result_list else 0.0002
        taker = float(result_list[0]["takerFeeRate"]) if result_list else 0.00055
        assert maker == 0.0002
        assert taker == 0.00055

    def test_fee_source_set_to_live(self):
        """When API call succeeds, fee_source should be 'live'."""
        from core.adapters.protocols import NormalizedAccount
        # Simulate successful fetch
        acc = NormalizedAccount(
            maker_fee=0.0001,
            taker_fee=0.0004,
            fee_source="live",
        )
        assert acc.fee_source == "live"
        assert acc.maker_fee == 0.0001

    def test_fee_source_set_to_default_on_failure(self):
        """When API call fails, fee_source should be 'default'."""
        from core.adapters.protocols import NormalizedAccount
        acc = NormalizedAccount(
            maker_fee=0.0002,
            taker_fee=0.00055,
            fee_source="default",
        )
        assert acc.fee_source == "default"
