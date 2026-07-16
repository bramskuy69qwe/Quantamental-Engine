"""
Task 97 regression tests for HIGH-022 + HIGH-023 + MED-036.

HIGH-022: backtest date-range validation (api/routes_backtest.py).
HIGH-023: cross-parameter validation in validate_params (warning < limit pairs).
MED-036: runtime-state check in /params/update — reject max_position_count
         reductions below the current open-position count.

Run: pytest tests/test_task97_route_validation.py -v
"""
from __future__ import annotations

from unittest.mock import patch

import pytest


# ── HIGH-022: backtest date-range validation ─────────────────────────────────

class TestBacktestDateRangeValidation:
    """HIGH-022: bound the backtest date range to prevent DoS via
    crafted multi-year requests + reject malformed/inverted ranges."""

    def test_valid_30_day_range_accepted(self):
        from api.routes_backtest import _validate_date_range
        assert _validate_date_range("2025-01-01", "2025-01-31") is None

    def test_valid_1_year_range_accepted(self):
        from api.routes_backtest import _validate_date_range
        assert _validate_date_range("2024-01-01", "2024-12-31") is None

    def test_empty_strings_short_circuit(self):
        """Empty dates short-circuit to None — the metadata-style lane (used
        by the Quantower JSON importer until v2.7 P6 retired it)."""
        from api.routes_backtest import _validate_date_range
        assert _validate_date_range("", "") is None
        assert _validate_date_range("2025-01-01", "") is None
        assert _validate_date_range("", "2025-01-31") is None

    def test_inverted_range_rejected(self):
        from api.routes_backtest import _validate_date_range
        err = _validate_date_range("2025-01-31", "2025-01-01")
        assert err is not None
        assert ">=" in err

    def test_zero_day_range_rejected(self):
        from api.routes_backtest import _validate_date_range
        err = _validate_date_range("2025-01-15", "2025-01-15")
        assert err is not None
        assert "at least 1 day" in err

    def test_over_one_year_range_rejected(self):
        from api.routes_backtest import _validate_date_range
        err = _validate_date_range("2024-01-01", "2025-06-01")  # ~517 days
        assert err is not None
        assert "exceeds maximum" in err
        assert "365 days" in err

    def test_malformed_date_format_rejected(self):
        from api.routes_backtest import _validate_date_range
        err = _validate_date_range("01/15/2025", "01/31/2025")
        assert err is not None
        assert "invalid date format" in err


# ── HIGH-023: cross-parameter validation in validate_params ──────────────────

class TestCrossParameterValidation:
    """HIGH-023: warning thresholds must be strictly below their corresponding
    limit thresholds. Inverted relationships break DD / weekly-loss state machines."""

    def test_dd_warning_below_dd_limit_accepted(self):
        from core.state import validate_params
        errors = validate_params({
            "max_dd_warning_pct": 0.80,
            "max_dd_limit_pct": 0.95,
        })
        assert errors == []

    def test_dd_warning_equal_dd_limit_rejected(self):
        from core.state import validate_params
        errors = validate_params({
            "max_dd_warning_pct": 0.90,
            "max_dd_limit_pct": 0.90,
        })
        assert any("max_dd_warning_pct" in e and "max_dd_limit_pct" in e for e in errors)

    def test_dd_warning_above_dd_limit_rejected(self):
        from core.state import validate_params
        errors = validate_params({
            "max_dd_warning_pct": 0.95,
            "max_dd_limit_pct": 0.80,
        })
        assert any("strictly less than" in e for e in errors)

    def test_weekly_loss_warning_below_limit_accepted(self):
        from core.state import validate_params
        errors = validate_params({
            "weekly_loss_warning_pct": 0.80,
            "weekly_loss_limit_pct": 0.95,
        })
        assert errors == []

    def test_weekly_loss_warning_above_limit_rejected(self):
        from core.state import validate_params
        errors = validate_params({
            "weekly_loss_warning_pct": 0.99,
            "weekly_loss_limit_pct": 0.80,
        })
        assert any("weekly_loss_warning_pct" in e for e in errors)

    def test_only_warning_provided_no_cross_check(self):
        """If only one half of a pair is provided, cross-check skips."""
        from core.state import validate_params
        errors = validate_params({"max_dd_warning_pct": 0.90})
        # No cross-error; per-param bound check might still fail but that's
        # a separate validation
        cross_errors = [e for e in errors if "strictly less than" in e]
        assert cross_errors == []


# ── MED-036: runtime-state check on max_position_count ───────────────────────

class TestMaxPositionCountRuntimeCheck:
    """MED-036: reject max_position_count update if it would drop below the
    current open-position count, since the risk engine would mark all
    positions as over-limit until they close."""

    def test_validate_params_alone_does_not_catch_runtime_state(self):
        """Confirms validate_params (pure) does NOT see runtime state.
        The runtime check has to live in the route handler."""
        from core.state import validate_params
        # max_position_count=2 is within PARAM_BOUNDS — would pass pure validation
        errors = validate_params({"max_position_count": 2})
        runtime_errors = [
            e for e in errors if "current open position count" in e
        ]
        assert runtime_errors == [], (
            "validate_params should not perform runtime-state checks "
            "(those live in the route handler so we can mock app_state cleanly)"
        )

    @pytest.mark.asyncio
    async def test_update_params_rejects_max_below_open_count(self):
        """Route handler must reject updates that reduce max_position_count
        below the count of currently-open positions."""
        from fastapi import Request
        import api.routes_params as rp

        # Build a minimal mock Request (HTMLResponse rendering doesn't need much)
        class _FakeRequest:
            pass

        # Mock 3 active positions
        fake_positions = [object(), object(), object()]

        with patch.object(rp.app_state, "params", {}), \
             patch.object(rp.app_state, "_positions_legacy", fake_positions, create=True):
            # data_cache layer may shadow positions; force the property to return our list
            with patch("core.state.AppState.positions", new_callable=lambda: property(lambda self: fake_positions)):
                resp = await rp.update_params(
                    request=_FakeRequest(),
                    individual_risk_per_trade=0.01,
                    max_w_loss_percent=0.05,
                    max_dd_percent=0.10,
                    max_exposure=1.0,
                    max_position_count=2,  # < 3 open positions → must reject
                    max_correlated_exposure=0.5,
                    auto_export_hours=24,
                    weekly_loss_warning_pct=0.80,
                    weekly_loss_limit_pct=0.95,
                    max_dd_warning_pct=0.80,
                    max_dd_limit_pct=0.95,
                )

        body = resp.body.decode("utf-8")
        assert "alert-error" in body, f"Expected validation error response; got: {body}"
        assert "current open position count" in body or "below current" in body, (
            f"Expected runtime-state rejection message; got: {body}"
        )

    @pytest.mark.asyncio
    async def test_update_params_accepts_max_above_open_count(self):
        """Sanity: when new max >= open count, the update is allowed."""
        from fastapi import Request
        import api.routes_params as rp

        class _FakeRequest:
            pass

        # Mock 2 active positions; new max=5 is fine
        fake_positions = [object(), object()]

        async def _fake_save():
            return None

        async def _fake_publish(*a, **k):
            return None

        with patch.object(rp.app_state, "params", {}, create=True), \
             patch.object(rp.app_state, "save_params_async", _fake_save), \
             patch.object(rp, "event_bus") as mock_bus, \
             patch("core.state.AppState.positions", new_callable=lambda: property(lambda self: fake_positions)):
            mock_bus.publish = _fake_publish
            resp = await rp.update_params(
                request=_FakeRequest(),
                individual_risk_per_trade=0.01,
                max_w_loss_percent=0.05,
                max_dd_percent=0.10,
                max_exposure=1.0,
                max_position_count=5,  # >= 2 open positions → OK
                max_correlated_exposure=0.5,
                auto_export_hours=24,
                weekly_loss_warning_pct=0.80,
                weekly_loss_limit_pct=0.95,
                max_dd_warning_pct=0.80,
                max_dd_limit_pct=0.95,
            )

        body = resp.body.decode("utf-8")
        assert "alert-success" in body, f"Expected success response; got: {body}"
