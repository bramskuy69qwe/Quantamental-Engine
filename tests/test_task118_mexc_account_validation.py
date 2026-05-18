"""
Task 118 regression tests for HIGH-031 — MEXC account-field validation.

Pure mirror of Task 102's HIGH-013 Binance fix with one Bybit-style
structural-path check (raw["USDT"] or raw["total"]). Simpler than
HIGH-030 because MEXC's adapter exposes only the two critical fields
(usdt["total"] → total_equity, usdt["free"] → available_margin); no
non-critical fields require warn-but-proceed handling.

Read-only adapter (capabilities.orders=False) bounds the blast radius
to display / analytics / BOD-SOW init / aggregate portfolio reporting
— no live-trade sizing impact. But the silent-corruption shape is
identical to HIGH-013/HIGH-030; operator must see the failure.

Run: pytest tests/test_task118_mexc_account_validation.py -v
"""
from __future__ import annotations

import asyncio
import inspect
from unittest.mock import MagicMock

import pytest


def _make_mexc_adapter(balance_response):
    """Construct a MexcLinearAdapter without invoking ccxt's network setup."""
    from core.adapters.mexc.rest_adapter import MexcLinearAdapter

    ad = MexcLinearAdapter.__new__(MexcLinearAdapter)
    ad._api_key = ""
    ad._api_secret = ""
    ad._proxy = ""
    ad._ex = MagicMock()
    ad._ex.fetch_balance.return_value = balance_response
    ad._ex.last_response_headers = None
    ad._markets_loaded = False
    ad._weight_tracker = None
    ad._current_priority = "normal"
    return ad


# ── Structural path: USDT or total must be present ───────────────────────────

class TestMexcFetchAccountStructuralPath:
    """HIGH-031: raw["USDT"] or raw["total"] must supply the per-currency
    dict. Both missing → raise."""

    def test_non_dict_response_raises(self):
        ad = _make_mexc_adapter(["not", "a", "dict"])
        with pytest.raises(ValueError) as ei:
            asyncio.run(ad.fetch_account())
        assert "not a dict" in str(ei.value)

    def test_neither_usdt_nor_total_present_raises(self):
        """A response with no USDT and no total key — silent zero
        pre-fix; loud failure post-fix."""
        ad = _make_mexc_adapter({"info": {"some": "other shape"}})
        with pytest.raises(ValueError) as ei:
            asyncio.run(ad.fetch_account())
        msg = str(ei.value)
        assert "phantom-zero" in msg
        assert "USDT" in msg or "total" in msg

    def test_total_key_used_when_usdt_missing(self):
        """Anti-over-correction: the `total` fallback path still works."""
        ad = _make_mexc_adapter({
            "total": {"total": 1500.0, "free": 1200.0},
        })
        result = asyncio.run(ad.fetch_account())
        assert result.total_equity == 1500.0
        assert result.available_margin == 1200.0

    def test_usdt_takes_precedence_over_total(self):
        """When both keys are present, raw['USDT'] is the source of
        truth (matches the existing fallback order)."""
        ad = _make_mexc_adapter({
            "USDT": {"total": 5000.0, "free": 4800.0},
            "total": {"total": 9999.0, "free": 8888.0},  # ignored
        })
        result = asyncio.run(ad.fetch_account())
        assert result.total_equity == 5000.0
        assert result.available_margin == 4800.0


# ── Required-field validation ────────────────────────────────────────────────

class TestMexcFetchAccountRequiredFields:
    """Critical fields: usdt['total'] + usdt['free']. Either missing
    or null → raise."""

    def test_missing_total_raises(self):
        ad = _make_mexc_adapter({"USDT": {"free": 1000.0}})  # total absent
        with pytest.raises(ValueError) as ei:
            asyncio.run(ad.fetch_account())
        assert "total" in str(ei.value)
        assert "phantom-zero" in str(ei.value)

    def test_missing_free_raises(self):
        ad = _make_mexc_adapter({"USDT": {"total": 1000.0}})  # free absent
        with pytest.raises(ValueError) as ei:
            asyncio.run(ad.fetch_account())
        assert "free" in str(ei.value)

    def test_null_total_raises(self):
        """Null is distinct from absent — CCXT may surface explicit None
        for partial responses. Both should raise."""
        ad = _make_mexc_adapter({"USDT": {"total": None, "free": 1000.0}})
        with pytest.raises(ValueError):
            asyncio.run(ad.fetch_account())

    def test_null_free_raises(self):
        ad = _make_mexc_adapter({"USDT": {"total": 1000.0, "free": None}})
        with pytest.raises(ValueError):
            asyncio.run(ad.fetch_account())

    def test_zero_values_succeed(self):
        """Anti-over-correction: legitimately empty USDT account
        (keys present, values zero) must NOT raise. Distinguishes
        'empty account' from 'broken response'."""
        ad = _make_mexc_adapter({"USDT": {"total": 0, "free": 0}})
        result = asyncio.run(ad.fetch_account())
        assert result.total_equity == 0.0
        assert result.available_margin == 0.0


# ── Valid-response anti-over-correction ──────────────────────────────────────

class TestMexcFetchAccountValidResponse:
    def test_complete_response_applies_normally(self):
        ad = _make_mexc_adapter({
            "USDT": {"total": 10000.5, "free": 8000.25},
        })
        result = asyncio.run(ad.fetch_account())
        assert result.total_equity == 10000.5
        assert result.available_margin == 8000.25
        # unrealized_pnl is hardcoded to 0 for MEXC (CCXT limitation)
        assert result.unrealized_pnl == 0.0


# ── Source-pin: HIGH-031 reference present ───────────────────────────────────

class TestSourceHasHigh031Reference:
    def test_fetch_account_source_references_high_031(self):
        from core.adapters.mexc.rest_adapter import MexcLinearAdapter
        src = inspect.getsource(MexcLinearAdapter.fetch_account)
        assert "HIGH-031" in src, (
            "HIGH-031 regression: MexcLinearAdapter.fetch_account no "
            "longer references HIGH-031 — validation block may have "
            "been removed."
        )
        assert "phantom-zero" in src
        assert "ValueError" in src


# ── Anti-regression: HIGH-013, HIGH-028, HIGH-030 still hold ─────────────────

class TestAntiRegression:
    """Task 118 must not touch Binance or Bybit validation or
    reconciliation behavior."""

    def test_binance_validation_still_raises_on_missing(self):
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
        ad = BinanceUSDMAdapter.__new__(BinanceUSDMAdapter)
        ad._api_key = ""
        ad._api_secret = ""
        ad._proxy = ""
        ad._ex = MagicMock()
        ad._ex.fapiPrivateV2GetAccount.return_value = {
            "availableBalance": "1000",  # totalWalletBalance MISSING
        }
        ad._ex.fapiPrivateGetCommissionRate.return_value = {}
        ad._ex.last_response_headers = None
        ad._markets_loaded = False
        ad._weight_tracker = None
        ad._current_priority = "normal"
        with pytest.raises(ValueError):
            asyncio.run(ad.fetch_account())

    def test_bybit_validation_still_raises_on_missing(self):
        from core.adapters.bybit.rest_adapter import BybitLinearAdapter
        ad = BybitLinearAdapter.__new__(BybitLinearAdapter)
        ad._api_key = ""
        ad._api_secret = ""
        ad._proxy = ""
        ad._ex = MagicMock()
        ad._ex.fetch_balance.return_value = {
            "info": {"result": {"list": []}}  # empty list → raise
        }
        ad._ex.privateGetV5AccountFeeRate.return_value = {"result": {"list": []}}
        ad._ex.last_response_headers = None
        ad._markets_loaded = False
        ad._weight_tracker = None
        ad._current_priority = "normal"
        with pytest.raises(ValueError):
            asyncio.run(ad.fetch_account())

    def test_bybit_reconciliation_override_still_present(self):
        """HIGH-028 anti-regression — sibling Bybit task still wired."""
        from core.adapters.bybit.rest_adapter import BybitLinearAdapter
        from core.adapters.base import BaseExchangeAdapter
        assert (
            BybitLinearAdapter._reconcile_from_response
            is not BaseExchangeAdapter._reconcile_from_response
        )

    def test_mexc_capabilities_still_read_only(self):
        """The read-only capability flag context for HIGH-031 must hold —
        if MEXC ever graduates to live trading the impact assessment in
        the audit doc needs revision."""
        from core.adapters.mexc.rest_adapter import MexcLinearAdapter
        assert MexcLinearAdapter.capabilities["orders"] is False, (
            "HIGH-031 context regression: MEXC adapter now claims "
            "orders=True. Revisit HIGH-031's impact assessment — the "
            "validation is the same but blast radius widens to live "
            "trade sizing."
        )
