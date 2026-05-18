"""
Task 117 regression tests for HIGH-030 — Bybit account-field validation.

Parallel to Task 102's HIGH-013 Binance validation, adapted for Bybit's
two-layer (account-level aggregate + per-coin USDT) response structure.

Bybit V5 wallet-balance response (account type UNIFIED) shape:
    {"result": {"list": [{
        "totalEquity": "10000.0",
        "totalAvailableBalance": "8000.0",
        "totalPerpUPL": "0",
        "totalInitialMargin": "0",
        "totalMaintenanceMargin": "0",
        "coin": [{
            "coin": "USDT",
            "equity": "10000.0",
            "availableToWithdraw": "8000.0",
            "unrealisedPnl": "0",
        }],
    }]}}

The validation accepts either layer as the source of truth (UNIFIED
accounts may aggregate at zero account-level in some isolated-margin
configurations, in which case per-coin USDT is authoritative). It
fails loud only when BOTH layers are missing the required field —
structural violation of Bybit's V5 contract.

Anti-regression: re-exercises Task 102's Binance tests + Task 115's
Bybit reconciliation tests must still pass.

Run: pytest tests/test_task117_bybit_account_validation.py -v
"""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import MagicMock

import pytest


def _make_bybit_adapter(account_dict, *, fee_resp=None):
    """Construct a BybitLinearAdapter without invoking ccxt's network setup.

    `account_dict` becomes result.list[0]; pass an empty dict for an
    empty-but-present row, None to make result.list itself empty.
    """
    from core.adapters.bybit.rest_adapter import BybitLinearAdapter

    ad = BybitLinearAdapter.__new__(BybitLinearAdapter)
    ad._api_key = ""
    ad._api_secret = ""
    ad._proxy = ""
    ad._ex = MagicMock()
    ad._ex.last_response_headers = None
    ad._markets_loaded = False
    ad._weight_tracker = None
    ad._current_priority = "normal"

    if account_dict is None:
        info = {"result": {"list": []}}
    else:
        info = {"result": {"list": [account_dict]}}
    ad._ex.fetch_balance.return_value = {"info": info}
    ad._ex.privateGetV5AccountFeeRate.return_value = fee_resp or {
        "result": {"list": [{"makerFeeRate": "0.0002", "takerFeeRate": "0.00055"}]}
    }
    return ad


def _good_account(**overrides):
    """A canonical valid Bybit V5 UNIFIED wallet-balance row."""
    base = {
        "totalEquity": "10000.0",
        "totalAvailableBalance": "8000.0",
        "totalPerpUPL": "150.0",
        "totalInitialMargin": "2000.0",
        "totalMaintenanceMargin": "500.0",
        "coin": [{
            "coin": "USDT",
            "equity": "10000.0",
            "availableToWithdraw": "8000.0",
            "unrealisedPnl": "150.0",
        }],
    }
    base.update(overrides)
    return base


# ── Structural validation: list / dict integrity ─────────────────────────────

class TestBybitFetchAccountStructuralValidation:
    """HIGH-030: result.list missing/empty/non-dict → raise."""

    def test_empty_list_raises_value_error(self):
        ad = _make_bybit_adapter(None)  # result.list = []
        with pytest.raises(ValueError) as ei:
            asyncio.run(ad.fetch_account())
        msg = str(ei.value)
        assert "result.list" in msg
        assert "phantom-zero" in msg

    def test_list_first_not_a_dict_raises(self):
        """A response with list[0] being a non-dict (e.g., string from a
        bad cast) must fail loud, not crash later."""
        from core.adapters.bybit.rest_adapter import BybitLinearAdapter
        ad = BybitLinearAdapter.__new__(BybitLinearAdapter)
        ad._api_key = ""
        ad._api_secret = ""
        ad._proxy = ""
        ad._ex = MagicMock()
        ad._ex.last_response_headers = None
        ad._markets_loaded = False
        ad._weight_tracker = None
        ad._current_priority = "normal"
        ad._ex.fetch_balance.return_value = {
            "info": {"result": {"list": ["not-a-dict"]}}
        }
        ad._ex.privateGetV5AccountFeeRate.return_value = {"result": {"list": []}}
        with pytest.raises(ValueError) as ei:
            asyncio.run(ad.fetch_account())
        assert "not a dict" in str(ei.value)


# ── Required-field validation: both layers ───────────────────────────────────

class TestBybitFetchAccountRequiredFields:
    """Critical fields gate risk sizing. Either account-level OR per-coin
    USDT must supply the value; both missing → raise."""

    def test_both_layers_missing_total_equity_raises(self):
        """Neither totalEquity at account level nor coin.USDT.equity →
        raise. Mirror of HIGH-013's totalWalletBalance check."""
        ad = _make_bybit_adapter({
            # totalEquity ABSENT at account level
            "totalAvailableBalance": "8000.0",
            "coin": [{"coin": "USDT", "availableToWithdraw": "8000.0"}],
            # coin.USDT.equity also ABSENT
        })
        with pytest.raises(ValueError) as ei:
            asyncio.run(ad.fetch_account())
        msg = str(ei.value)
        assert "totalEquity" in msg
        assert "phantom-zero" in msg

    def test_both_layers_missing_available_raises(self):
        ad = _make_bybit_adapter({
            "totalEquity": "10000.0",
            # totalAvailableBalance ABSENT
            "coin": [{"coin": "USDT", "equity": "10000.0"}],
            # coin.USDT.availableToWithdraw ABSENT
        })
        with pytest.raises(ValueError) as ei:
            asyncio.run(ad.fetch_account())
        msg = str(ei.value)
        assert "totalAvailableBalance" in msg or "availableToWithdraw" in msg

    def test_account_level_present_succeeds_even_without_usdt_coin(self):
        """Anti-over-correction: account-level fields alone are
        sufficient when no USDT coin entry exists."""
        ad = _make_bybit_adapter({
            "totalEquity": "5000.0",
            "totalAvailableBalance": "4500.0",
            "totalPerpUPL": "0",
            "totalInitialMargin": "0",
            "totalMaintenanceMargin": "0",
            # no `coin` key at all
        })
        result = asyncio.run(ad.fetch_account())
        assert result.total_equity == 5000.0
        assert result.available_margin == 4500.0

    def test_usdt_coin_compensates_for_missing_account_total(self):
        """Anti-over-correction: per-coin USDT covers when account-level
        is missing (some Bybit isolated-margin configurations aggregate
        at zero or omit the totalEquity field at the UNIFIED layer)."""
        ad = _make_bybit_adapter({
            # totalEquity / totalAvailableBalance ABSENT at account level
            "coin": [{
                "coin": "USDT",
                "equity": "7500.0",
                "availableToWithdraw": "7000.0",
                "unrealisedPnl": "0",
            }],
        })
        result = asyncio.run(ad.fetch_account())
        assert result.total_equity == 7500.0
        assert result.available_margin == 7000.0


# ── Phantom-equity scenario (HIGH-013 downstream parallel) ───────────────────

class TestPhantomEquityScenarioBlocked:
    """The audit-doc evidence for HIGH-013 was that a phantom-zero
    cascade flows into risk_engine.py:440's `total_equity > 0 else 1.0`
    micro-position fallback. The validation here is the upstream gate
    that prevents the cascade from starting."""

    def test_malformed_response_cannot_produce_zero_equity_silently(self):
        """The key behavioral guarantee: a malformed response (which
        would have silently produced equity=0 pre-fix) must now raise.
        The caller's exception handler preserves prior known-good state."""
        ad = _make_bybit_adapter({})  # totally empty result row
        with pytest.raises(ValueError):
            asyncio.run(ad.fetch_account())


# ── Non-critical fields: warn but proceed ───────────────────────────────────

class TestBybitFetchAccountNonCriticalFields:
    """Margins / unrealized PnL absent → log.warning + default 0; do NOT
    raise. Same shape as Binance's non-critical handling (HIGH-013)."""

    def test_missing_margins_logged_not_raised(self, caplog):
        ad = _make_bybit_adapter({
            "totalEquity": "10000.0",
            "totalAvailableBalance": "8000.0",
            # totalPerpUPL, totalInitialMargin, totalMaintenanceMargin absent
        })
        import logging
        with caplog.at_level(logging.WARNING, logger="adapters.bybit.rest"):
            result = asyncio.run(ad.fetch_account())
        assert result.total_equity == 10000.0
        # All three non-critical fields should have warning records
        log_text = caplog.text
        assert "totalPerpUPL" in log_text
        assert "totalInitialMargin" in log_text
        assert "totalMaintenanceMargin" in log_text


# ── Source-pin: HIGH-030 reference present ───────────────────────────────────

class TestSourceHasHigh030Reference:
    """Anti-revert: catch a future cleanup that removes the validation
    block without the test failures being clear about which finding
    was reverted."""

    def test_fetch_account_source_references_high_030(self):
        from core.adapters.bybit.rest_adapter import BybitLinearAdapter
        src = inspect.getsource(BybitLinearAdapter.fetch_account)
        assert "HIGH-030" in src, (
            "HIGH-030 regression: BybitLinearAdapter.fetch_account no "
            "longer references HIGH-030 — validation block may have "
            "been removed."
        )
        assert "phantom-zero" in src
        # Specifically, must call ValueError somewhere
        assert "ValueError" in src


# ── Anti-regression: HIGH-013 + HIGH-028 still hold ──────────────────────────

class TestAntiRegression:
    """Task 117's Bybit-specific change must not touch Binance HIGH-013
    or Bybit HIGH-028 reconciliation behavior."""

    def test_binance_fetch_account_validation_still_raises_on_missing(self):
        """HIGH-013 anti-regression — Binance still raises on missing
        totalWalletBalance."""
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
        ad = BinanceUSDMAdapter.__new__(BinanceUSDMAdapter)
        ad._api_key = ""
        ad._api_secret = ""
        ad._proxy = ""
        ad._ex = MagicMock()
        ad._ex.fapiPrivateV2GetAccount.return_value = {
            # totalWalletBalance MISSING
            "availableBalance": "1000",
        }
        ad._ex.fapiPrivateGetCommissionRate.return_value = {}
        ad._ex.last_response_headers = None
        ad._markets_loaded = False
        ad._weight_tracker = None
        ad._current_priority = "normal"
        with pytest.raises(ValueError):
            asyncio.run(ad.fetch_account())

    def test_bybit_reconciliation_override_still_present(self):
        """HIGH-028 anti-regression — Bybit's _reconcile_from_response
        override is still in place, not collateral-damaged by the
        validation work."""
        from core.adapters.bybit.rest_adapter import BybitLinearAdapter
        from core.adapters.base import BaseExchangeAdapter
        assert (
            BybitLinearAdapter._reconcile_from_response
            is not BaseExchangeAdapter._reconcile_from_response
        )
