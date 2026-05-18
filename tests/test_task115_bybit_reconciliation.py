"""
Task 115 regression tests for HIGH-028 — Bybit weight-tracker
reconciliation via V5 rate-limit response headers.

Approach: adapted mirror of Task 99's Binance reconciliation
(HIGH-014). Bybit's V5 rate-limit model differs from Binance's —
per-endpoint countdown of *remaining* requests vs. Binance's global
*used* weight — so the adapter computes a saturation ratio
(`(limit - status) / limit`) and scales it to the tracker's
``max_weight`` for a unit-compatible reconcile signal.

Test parity with `tests/test_task99_adapter_bundle.py
::TestBinanceHeaderReconciliation` (same shape: load-bearing pin,
lowercase header acceptance, missing-header anti-over-correction,
garbage value rejected). Plus Bybit-specific edge cases (limit=0,
status>limit, reset timestamp).

Run: pytest tests/test_task115_bybit_reconciliation.py -v
"""
from __future__ import annotations

import ast
import inspect
from unittest.mock import MagicMock

import pytest


def _build_adapter(headers: dict | None, max_weight: int = 600):
    """Construct a BybitLinearAdapter without invoking ccxt's network setup."""
    from core.adapters.bybit.rest_adapter import BybitLinearAdapter
    from core.rate_limit.weight_tracker import WeightTracker

    ad = BybitLinearAdapter.__new__(BybitLinearAdapter)
    ad._api_key = ""
    ad._api_secret = ""
    ad._proxy = ""
    ad._ex = MagicMock()
    ad._ex.last_response_headers = headers if headers is not None else {}
    ad._markets_loaded = False
    ad._weight_tracker = WeightTracker(adapter_name="bybit", max_weight=max_weight)
    ad._current_priority = "normal"
    return ad


# ── Load-bearing pin: saturation → reconcile ─────────────────────────────────

class TestBybitHeaderReconciliation:
    """HIGH-028: after a successful call, tracker.current_weight reflects
    the saturation of the most-constrained endpoint, scaled to max_weight."""

    @pytest.mark.asyncio
    async def test_reconciles_from_v5_status_and_limit_headers(self):
        """Load-bearing: limit=100, status=10 → 90% saturation → 540 of 600."""
        ad = _build_adapter(
            {"X-Bapi-Limit-Status": "10", "X-Bapi-Limit": "100"},
            max_weight=600,
        )

        def _fn():
            return {"ok": True}
        _fn.__name__ = "fetch_account"

        await ad._run(_fn)

        # saturation = (100 - 10) / 100 = 0.9 → 0.9 * 600 = 540
        assert ad._weight_tracker.current_weight == 540, (
            "HIGH-028 regression: tracker.current_weight should reflect "
            "saturation scaled to max_weight, not the local estimate."
        )

    @pytest.mark.asyncio
    async def test_lowercase_headers_also_accepted(self):
        """ccxt may lowercase header names; tolerate both."""
        ad = _build_adapter(
            {"x-bapi-limit-status": "25", "x-bapi-limit": "50"},
            max_weight=1000,
        )

        def _fn():
            return None
        _fn.__name__ = "fetch_ohlcv"

        await ad._run(_fn)

        # saturation = 25/50 = 0.5 → 500
        assert ad._weight_tracker.current_weight == 500

    @pytest.mark.asyncio
    async def test_reset_timestamp_snaps_window_when_present(self):
        """Bybit V5 publishes X-Bapi-Limit-Reset-Timestamp. When present
        the helper passes it through to tracker.reconcile so the budget
        window aligns with the server's view."""
        ad = _build_adapter(
            {
                "X-Bapi-Limit-Status": "5",
                "X-Bapi-Limit": "50",
                "X-Bapi-Limit-Reset-Timestamp": "1700000000000",
            },
        )

        def _fn():
            return None
        _fn.__name__ = "fetch_account"

        await ad._run(_fn)

        # Reset ms should land on the budget's window_start_ms
        assert ad._weight_tracker._budget.window_start_ms == 1700000000000


# ── Fail-safe paths (parity with Task 99 anti-over-correction tests) ─────────

class TestBybitHeaderReconciliationFailSafe:
    """Anti-over-correction: each fail-safe path leaves the estimate intact."""

    @pytest.mark.asyncio
    async def test_missing_headers_leave_estimate_intact(self):
        """Headers absent → tracker keeps the client-side estimate."""
        ad = _build_adapter({"content-type": "application/json"})

        def _fn():
            return None
        _fn.__name__ = "fetch_account"  # estimate=5 from Binance default map

        await ad._run(_fn)
        assert ad._weight_tracker.current_weight == 5, (
            "HIGH-028 regression: missing rate-limit headers must NOT zero "
            "the tracker — estimate must stand."
        )

    @pytest.mark.asyncio
    async def test_only_status_present_no_reconcile(self):
        """Need both status AND limit to compute saturation."""
        ad = _build_adapter({"X-Bapi-Limit-Status": "10"})

        def _fn():
            return None
        _fn.__name__ = "fetch_account"

        await ad._run(_fn)
        # Estimate-only path: 5 still in place
        assert ad._weight_tracker.current_weight == 5

    @pytest.mark.asyncio
    async def test_only_limit_present_no_reconcile(self):
        ad = _build_adapter({"X-Bapi-Limit": "100"})

        def _fn():
            return None
        _fn.__name__ = "fetch_account"

        await ad._run(_fn)
        assert ad._weight_tracker.current_weight == 5

    @pytest.mark.asyncio
    async def test_garbage_status_value_ignored(self):
        ad = _build_adapter(
            {"X-Bapi-Limit-Status": "not-an-int", "X-Bapi-Limit": "100"},
        )

        def _fn():
            return None
        _fn.__name__ = "fetch_account"

        await ad._run(_fn)
        assert ad._weight_tracker.current_weight == 5

    @pytest.mark.asyncio
    async def test_zero_limit_ignored(self):
        """limit=0 would divide-by-zero downstream."""
        ad = _build_adapter(
            {"X-Bapi-Limit-Status": "0", "X-Bapi-Limit": "0"},
        )

        def _fn():
            return None
        _fn.__name__ = "fetch_account"

        await ad._run(_fn)
        assert ad._weight_tracker.current_weight == 5

    @pytest.mark.asyncio
    async def test_status_greater_than_limit_ignored(self):
        """status > limit would produce negative used_proxy — clearly
        bogus header pair, ignore."""
        ad = _build_adapter(
            {"X-Bapi-Limit-Status": "150", "X-Bapi-Limit": "100"},
        )

        def _fn():
            return None
        _fn.__name__ = "fetch_account"

        await ad._run(_fn)
        assert ad._weight_tracker.current_weight == 5

    @pytest.mark.asyncio
    async def test_negative_status_ignored(self):
        ad = _build_adapter(
            {"X-Bapi-Limit-Status": "-5", "X-Bapi-Limit": "100"},
        )

        def _fn():
            return None
        _fn.__name__ = "fetch_account"

        await ad._run(_fn)
        assert ad._weight_tracker.current_weight == 5

    @pytest.mark.asyncio
    async def test_garbage_reset_timestamp_falls_back_to_zero(self):
        """A bogus reset timestamp must not abort the reconcile — just
        skip the window snap."""
        ad = _build_adapter(
            {
                "X-Bapi-Limit-Status": "10",
                "X-Bapi-Limit": "100",
                "X-Bapi-Limit-Reset-Timestamp": "not-a-number",
            },
            max_weight=600,
        )

        def _fn():
            return None
        _fn.__name__ = "fetch_account"

        await ad._run(_fn)
        # Saturation reconcile still happens
        assert ad._weight_tracker.current_weight == 540


# ── Override hook is present (source-pin) ────────────────────────────────────

class TestBybitOverridesReconcileHook:
    """Source-pin: the Bybit adapter must override
    `_reconcile_from_response`. Without the override the base-class no-op
    runs and headers are ignored entirely."""

    def test_override_present(self):
        from core.adapters.bybit.rest_adapter import BybitLinearAdapter
        from core.adapters.base import BaseExchangeAdapter
        # Confirm the subclass defines its own override (not inheriting
        # the base-class no-op)
        assert (
            BybitLinearAdapter._reconcile_from_response
            is not BaseExchangeAdapter._reconcile_from_response
        ), (
            "HIGH-028 regression: BybitLinearAdapter no longer overrides "
            "_reconcile_from_response — header reconciliation is dead code."
        )

    def test_override_references_v5_headers(self):
        """AST-pin: the override must reference the V5 header names by
        string. Catches a future refactor that drops to a registry without
        actually reading the headers."""
        from core.adapters.bybit.rest_adapter import BybitLinearAdapter
        src = inspect.getsource(BybitLinearAdapter._reconcile_from_response)
        # Either case form is acceptable (we look up both)
        assert (
            "X-Bapi-Limit-Status" in src
            or "x-bapi-limit-status" in src
        ), "V5 status header missing"
        assert (
            "X-Bapi-Limit" in src
            or "x-bapi-limit" in src
        ), "V5 limit header missing"
        assert "tracker.reconcile" in src, "must call tracker.reconcile"


# ── Anti-regression: Binance behavior unchanged ──────────────────────────────

class TestBinanceBehaviorUnchanged:
    """Anti-regression for Task 99 (HIGH-014). The Bybit change must not
    touch Binance's reconciliation. Re-exercise one of the original Task
    99 cases against the current source to confirm parity."""

    @pytest.mark.asyncio
    async def test_binance_still_reconciles_from_x_mbx_header(self):
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
        from core.rate_limit.weight_tracker import WeightTracker

        ad = BinanceUSDMAdapter.__new__(BinanceUSDMAdapter)
        ad._api_key = ""
        ad._api_secret = ""
        ad._proxy = ""
        ad._ex = MagicMock()
        ad._ex.last_response_headers = {"X-MBX-USED-WEIGHT-1M": "742"}
        ad._markets_loaded = False
        ad._weight_tracker = WeightTracker(adapter_name="binance", max_weight=1200)
        ad._current_priority = "normal"

        def _fn():
            return None
        _fn.__name__ = "fetch_account"

        await ad._run(_fn)
        assert ad._weight_tracker.current_weight == 742


# ── MEXC parallel observation (informational, not a regression pin) ──────────

class TestMexcStillUnreconciled:
    """Informational only: MEXC adapter does NOT (and currently is not
    expected to) implement reconciliation — HIGH-031 covers the broader
    MEXC account-field parity, and MEXC's `capabilities.orders=False`
    means it's read-only / observability-only. If MEXC ever graduates
    to full trading, parallel reconciliation needs to be filed.

    This test pins the current state so future work knows the gap exists.
    """

    def test_mexc_adapter_does_not_override_reconcile(self):
        from core.adapters.mexc.rest_adapter import MexcLinearAdapter
        from core.adapters.base import BaseExchangeAdapter
        # Currently MEXC inherits the base no-op. When MEXC graduates,
        # this test should flip to assert `is not`.
        assert (
            MexcLinearAdapter._reconcile_from_response
            is BaseExchangeAdapter._reconcile_from_response
        ), (
            "Informational: MEXC adapter now overrides "
            "_reconcile_from_response. Update this test to `is not` and "
            "ensure a parallel test class exercises the MEXC headers."
        )
