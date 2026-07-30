"""
Task 97 regression tests for HIGH-022 + HIGH-023 + MED-036.

HIGH-022: backtest date-range validation (api/routes_backtest.py).
HIGH-023: cross-parameter validation in validate_params (warning < limit pairs).
MED-036: runtime-state check in /params/update — reject max_position_count
         reductions below the current open-position count.

Run: pytest tests/test_task97_route_validation.py -v
"""
from __future__ import annotations

from types import SimpleNamespace
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
        """Confirms validate_params (pure) does NOT see runtime state — which
        is why the check has to live in the route handler. Its home moved on
        2026-07-30: POST /params/update was retired and the guard was REHOMED
        into POST /accounts/{id}/update (pinned below)."""
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


def _upd_kwargs(**over):
    """Every optional parameter explicitly None.

    A DIRECT handler call bypasses FastAPI's dependency resolution, so an
    omitted argument arrives as the raw `Form(None)` object — which is not
    None, and then gets compared/cast. Pass them all.
    """
    import inspect
    import api.routes_accounts as ra
    sig = inspect.signature(ra.update_account_detail)
    kwargs = {name: None for name, p in sig.parameters.items()
              if name not in ("account_id", "request")}
    kwargs["request"] = None
    kwargs.update(over)
    return kwargs


class TestMed036RehomedToAccountUpdate:
    """MED-036 survived the retirement of POST /params/update by moving into
    the surviving per-account params writer. Dropping a risk guard as a side
    effect of a UI cleanup would have been a silent capability loss."""

    @pytest.mark.asyncio
    async def test_rejects_cap_below_open_count_on_the_active_account(self):
        import api.routes_accounts as ra
        state = SimpleNamespace(active_account_id=1,
                                positions=[object(), object(), object()])
        with patch.object(ra, "app_state", state):
            resp = await ra.update_account_detail(
                1, **_upd_kwargs(max_position_count=2))
        body = resp.body.decode("utf-8")
        assert "below current open" in body, body

    @pytest.mark.asyncio
    async def test_allows_cap_at_or_above_open_count(self, monkeypatch):
        import api.routes_accounts as ra
        # the accept lane reaches the live-state write, so `params` must exist
        state = SimpleNamespace(active_account_id=1, positions=[object(), object()],
                                params={})
        seen = {}
        monkeypatch.setattr(ra.account_registry, "get_account_params", lambda aid: {})

        async def _upd(aid, params):
            seen["params"] = params
        monkeypatch.setattr(ra.account_registry, "update_account_params", _upd)
        with patch.object(ra, "app_state", state):
            resp = await ra.update_account_detail(
                1, **_upd_kwargs(max_position_count=2))
        assert "below current open" not in resp.body.decode("utf-8")
        assert seen["params"]["max_position_count"] == 2

    @pytest.mark.asyncio
    async def test_inactive_account_is_not_gated_by_live_positions(self, monkeypatch):
        """app_state.positions is ACTIVE-account state — applying it to another
        account's cap would reject a legitimate edit."""
        import api.routes_accounts as ra
        state = SimpleNamespace(active_account_id=1,
                                positions=[object(), object(), object()])
        called = {}
        monkeypatch.setattr(ra.account_registry, "get_account_params", lambda aid: {})

        async def _upd(aid, params):
            called["aid"] = aid
        monkeypatch.setattr(ra.account_registry, "update_account_params", _upd)
        with patch.object(ra, "app_state", state):
            resp = await ra.update_account_detail(
                9, **_upd_kwargs(max_position_count=2))
        assert "below current open" not in resp.body.decode("utf-8")
        assert called.get("aid") == 9


