"""
Task 99 regression tests for HIGH-007 + HIGH-014 + HIGH-015 + LOW-019.

Adapter observability/reliability bundle:
- HIGH-007: weight-tracker except blocks now log (init failure + reserve failure).
- HIGH-014: Binance _run() reconciles tracker.current_weight from
  X-MBX-USED-WEIGHT-1M header on every successful call (previously deferred
  to v2.5; spec called it out as source of truth).
- HIGH-015: fee-fetch swallows now log.warning (Binance commission + Bybit fee).
- LOW-019: binance _agg_extremes + fetch_current_funding_rates swallows
  now log.warning (was silent None/zero return).

All four are observability fixes — the swallow behavior is preserved
(callers depend on defaults). Tests pin the log emission + the
reconciliation wiring, and anti-over-correction tests check the
swallow itself is still in place.

Run: pytest tests/test_task99_adapter_bundle.py -v
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import textwrap
from unittest.mock import MagicMock, patch

import pytest


def _src(obj) -> str:
    """inspect.getsource keeps class-body indent; dedent for ast.parse."""
    return textwrap.dedent(inspect.getsource(obj))


# ── HIGH-007: weight-tracker swallow now logs ────────────────────────────────

class TestWeightTrackerSwallowLogs:
    """HIGH-007: both except blocks in core/adapters/base.py must log.
    The 'pass' was justified (tracker must not block requests), but silent
    pass hid tracker bugs and made HIGH-014's drift unattributable."""

    def test_weight_tracker_reserve_except_calls_log(self):
        """Source-level pin: the reserve()-except branch must call log.* —
        not just `pass`. Uses AST to verify the body of the catch-Exception
        block in BaseExchangeAdapter._run."""
        import ast
        from core.adapters import base

        src = _src(base.BaseExchangeAdapter._run)
        tree = ast.parse(src)

        # Walk the AST for a Try whose handlers include `except Exception`
        # immediately following `except RateLimitError: raise`.
        found_logged = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            handler_names = []
            for h in node.handlers:
                if isinstance(h.type, ast.Name):
                    handler_names.append(h.type.id)
            if handler_names != ["RateLimitError", "Exception"]:
                continue
            # The Exception handler is handler_names[-1]
            exc_handler = node.handlers[-1]
            # Walk the body looking for a log.* call
            for body_node in ast.walk(exc_handler):
                if isinstance(body_node, ast.Call):
                    func = body_node.func
                    if (isinstance(func, ast.Attribute)
                            and isinstance(func.value, ast.Name)
                            and func.value.id == "log"):
                        found_logged = True
                        break
            if found_logged:
                break

        assert found_logged, (
            "HIGH-007 regression: BaseExchangeAdapter._run's "
            "`except Exception` (post-RateLimitError) must call log.* — "
            "silent pass hides tracker bugs and erases evidence of "
            "estimate-vs-server drift (HIGH-014)."
        )

    def test_weight_tracker_init_except_calls_log(self):
        """Source pin for the lazy-init swallow in _get_weight_tracker."""
        import ast
        from core.adapters import base

        src = _src(base.BaseExchangeAdapter._get_weight_tracker)
        tree = ast.parse(src)

        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for h in node.handlers:
                    for body_node in ast.walk(h):
                        if isinstance(body_node, ast.Call):
                            func = body_node.func
                            if (isinstance(func, ast.Attribute)
                                    and isinstance(func.value, ast.Name)
                                    and func.value.id == "log"):
                                return  # success
        pytest.fail(
            "HIGH-007 regression: _get_weight_tracker's except must log; "
            "silent swallow means every request runs un-throttled with no "
            "visible cause when tracker import/init fails."
        )


# ── HIGH-014: Binance response-header reconciliation ─────────────────────────

class TestBinanceHeaderReconciliation:
    """HIGH-014: tracker.current_weight should reflect server-side truth from
    X-MBX-USED-WEIGHT-1M after each successful _run call. Previously the
    tracker only had upfront client estimates and drifted from server reality."""

    @pytest.mark.asyncio
    async def test_reconciles_from_x_mbx_used_weight_header(self):
        """Load-bearing pin: after a successful call, tracker.current_weight
        must equal the header value, not the client-side estimate."""
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
        from core.rate_limit.weight_tracker import WeightTracker

        # Build adapter without invoking ccxt (skip __init__'s network setup)
        ad = BinanceUSDMAdapter.__new__(BinanceUSDMAdapter)
        ad._api_key = ""
        ad._api_secret = ""
        ad._proxy = ""
        ad._ex = MagicMock()
        # ccxt stores last_response_headers post-call
        ad._ex.last_response_headers = {"X-MBX-USED-WEIGHT-1M": "742"}
        ad._markets_loaded = False
        ad._weight_tracker = WeightTracker(adapter_name="binance", max_weight=1200)
        ad._current_priority = "normal"

        def _fn():
            return {"ok": True}
        _fn.__name__ = "fetch_account"  # weight 5 in registry

        await ad._run(_fn)

        assert ad._weight_tracker.current_weight == 742, (
            "HIGH-014 regression: tracker.current_weight should have been "
            "reconciled to the server's X-MBX-USED-WEIGHT-1M=742 — pre-fix it "
            "would only reflect the local estimate (5)."
        )

    @pytest.mark.asyncio
    async def test_lowercase_header_also_accepted(self):
        """ccxt sometimes lowercases header names; accept both."""
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
        from core.rate_limit.weight_tracker import WeightTracker

        ad = BinanceUSDMAdapter.__new__(BinanceUSDMAdapter)
        ad._api_key = ""
        ad._api_secret = ""
        ad._proxy = ""
        ad._ex = MagicMock()
        ad._ex.last_response_headers = {"x-mbx-used-weight-1m": "300"}
        ad._markets_loaded = False
        ad._weight_tracker = WeightTracker(adapter_name="binance", max_weight=1200)
        ad._current_priority = "normal"

        def _fn():
            return None
        _fn.__name__ = "fetch_ohlcv"

        await ad._run(_fn)
        assert ad._weight_tracker.current_weight == 300

    @pytest.mark.asyncio
    async def test_missing_header_leaves_estimate_intact(self):
        """Anti-over-correction: when the header is absent the tracker's
        client-side estimate must stand (i.e. we don't zero it out)."""
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
        from core.rate_limit.weight_tracker import WeightTracker

        ad = BinanceUSDMAdapter.__new__(BinanceUSDMAdapter)
        ad._api_key = ""
        ad._api_secret = ""
        ad._proxy = ""
        ad._ex = MagicMock()
        ad._ex.last_response_headers = {"content-type": "application/json"}
        ad._markets_loaded = False
        ad._weight_tracker = WeightTracker(adapter_name="binance", max_weight=1200)
        ad._current_priority = "normal"

        def _fn():
            return None
        _fn.__name__ = "fetch_account"  # estimate=5

        await ad._run(_fn)
        # Should be the estimate (5), not 0 or some default
        assert ad._weight_tracker.current_weight == 5, (
            "Missing header should NOT zero the tracker — the upfront "
            "estimate must stand. Found %d." % ad._weight_tracker.current_weight
        )

    @pytest.mark.asyncio
    async def test_garbage_header_value_ignored(self):
        """Anti-over-correction: a non-numeric header doesn't poison the budget."""
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
        from core.rate_limit.weight_tracker import WeightTracker

        ad = BinanceUSDMAdapter.__new__(BinanceUSDMAdapter)
        ad._api_key = ""
        ad._api_secret = ""
        ad._proxy = ""
        ad._ex = MagicMock()
        ad._ex.last_response_headers = {"X-MBX-USED-WEIGHT-1M": "not-an-int"}
        ad._markets_loaded = False
        ad._weight_tracker = WeightTracker(adapter_name="binance", max_weight=1200)
        ad._current_priority = "normal"

        def _fn():
            return None
        _fn.__name__ = "fetch_account"

        await ad._run(_fn)
        # estimate=5 still in place
        assert ad._weight_tracker.current_weight == 5


# ── HIGH-015: fee-fetch except now logs ──────────────────────────────────────

class TestFeeFetchLogsOnFailure:
    """HIGH-015: Binance commissionRate + Bybit fee-rate except blocks must
    log.warning. Silent swallow → maker_fee/taker_fee read as 0/default with
    no visible cause; PnL/slippage calcs systematically understate costs."""

    def test_binance_fee_fetch_except_calls_log_warning(self):
        """Source pin: the inner-fetch except in fetch_account must call
        log.warning (or similar). Use grep on the source — the except block
        is inside a nested function so AST-walking through fetch_account
        catches it."""
        import ast
        from core.adapters.binance import rest_adapter

        src = _src(rest_adapter.BinanceUSDMAdapter.fetch_account)
        tree = ast.parse(src)

        # Look for any except Exception inside fetch_account that includes
        # a log.* call in its body (excluding the no-op pass that was there
        # pre-fix).
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            for body_node in ast.walk(node):
                if isinstance(body_node, ast.Call):
                    func = body_node.func
                    if (isinstance(func, ast.Attribute)
                            and isinstance(func.value, ast.Name)
                            and func.value.id == "log"):
                        return  # success
        pytest.fail(
            "HIGH-015 regression: binance fetch_account's except must "
            "call log.* — silent comm={} drives maker/taker fees to 0, "
            "understating PnL/slippage cost estimates."
        )

    def test_bybit_fee_fetch_except_calls_log_warning(self):
        """Source pin matching binance test."""
        import ast
        from core.adapters.bybit import rest_adapter

        src = _src(rest_adapter.BybitLinearAdapter.fetch_account)
        tree = ast.parse(src)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            for body_node in ast.walk(node):
                if isinstance(body_node, ast.Call):
                    func = body_node.func
                    if (isinstance(func, ast.Attribute)
                            and isinstance(func.value, ast.Name)
                            and func.value.id == "log"):
                        return
        pytest.fail(
            "HIGH-015 regression: bybit fetch_account's except must call "
            "log.* — silent fees={} falls through to VIP0 defaults with no "
            "visible signal that live fees weren't actually read."
        )


# ── LOW-019: binance price-extremes / funding-rates swallows now log ─────────

class TestBinanceSilentSwallowsLog:
    """LOW-019: _agg_extremes and fetch_current_funding_rates except blocks
    that return safe defaults must log so the operator sees the degradation."""

    def test_agg_extremes_except_calls_log(self):
        """Source pin: _agg_extremes is a nested function inside
        fetch_price_extremes; walk the source of the outer method."""
        import ast
        from core.adapters.binance import rest_adapter

        src = _src(rest_adapter.BinanceUSDMAdapter.fetch_price_extremes)
        tree = ast.parse(src)

        # Find the except handler that returns None, None and verify it logs.
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            # Must contain a `return None, None` somewhere
            returns_nones = any(
                isinstance(n, ast.Return)
                and isinstance(n.value, ast.Tuple)
                and len(n.value.elts) == 2
                and all(
                    isinstance(e, ast.Constant) and e.value is None
                    for e in n.value.elts
                )
                for n in ast.walk(node)
            )
            if not returns_nones:
                continue
            # Now check it logs
            for body_node in ast.walk(node):
                if isinstance(body_node, ast.Call):
                    func = body_node.func
                    if (isinstance(func, ast.Attribute)
                            and isinstance(func.value, ast.Name)
                            and func.value.id == "log"):
                        return
        pytest.fail(
            "LOW-019 regression: _agg_extremes' `return None, None` except "
            "must call log.* — silent None,None falls back to OHLCV with no "
            "diagnostic for the original failure."
        )

    def test_funding_rates_except_calls_log(self):
        """Source pin: fetch_current_funding_rates' top-level except."""
        import ast
        from core.adapters.binance import rest_adapter

        src = _src(rest_adapter.BinanceUSDMAdapter.fetch_current_funding_rates)
        tree = ast.parse(src)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            for body_node in ast.walk(node):
                if isinstance(body_node, ast.Call):
                    func = body_node.func
                    if (isinstance(func, ast.Attribute)
                            and isinstance(func.value, ast.Name)
                            and func.value.id == "log"):
                        return
        pytest.fail(
            "LOW-019 regression: fetch_current_funding_rates' except must "
            "call log.* — silent zero-funding default makes upstream "
            "carry-cost calcs look free of charge."
        )


# ── Anti-over-correction: swallow behavior preserved ─────────────────────────

class TestSwallowBehaviorPreserved:
    """Confirm the *swallow* (not the log) is unchanged. Callers depend on
    the default returns; turning these into raises would crash account
    refresh / price-extreme paths."""

    def test_binance_fee_fetch_still_returns_default_on_failure(self):
        """Anti-over-correction: comm={} default still in place."""
        # Mock ccxt instance whose commissionRate raises
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter

        ad = BinanceUSDMAdapter.__new__(BinanceUSDMAdapter)
        ad._api_key = ""
        ad._api_secret = ""
        ad._proxy = ""
        ad._ex = MagicMock()
        ad._ex.fapiPrivateV2GetAccount.return_value = {
            "totalWalletBalance": "100",
            "availableBalance": "100",
            "totalUnrealizedProfit": "0",
            "totalInitialMargin": "0",
            "totalMaintMargin": "0",
            "feeTier": "0",
        }
        ad._ex.fapiPrivateGetCommissionRate.side_effect = RuntimeError("boom")
        ad._ex.last_response_headers = None
        ad._markets_loaded = False
        ad._weight_tracker = None  # no tracker → skip reconciliation
        ad._current_priority = "normal"

        # Should NOT raise; should return NormalizedAccount with fees=0
        acct = asyncio.run(ad.fetch_account())
        assert acct.maker_fee == 0.0
        assert acct.taker_fee == 0.0
        assert acct.total_equity == 100.0
