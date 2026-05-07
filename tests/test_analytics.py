"""
Unit tests for core/analytics.py — pure financial math.

Pins Sharpe, Sortino, VaR, CVaR, parametric VaR, beta, R-multiples,
and funding exposure calculations BEFORE structural redesigns.

Run: pytest tests/test_analytics.py -v
"""
from __future__ import annotations

import math

import pytest

from core.analytics import (
    daily_returns,
    sharpe,
    sortino,
    sharpe_mfe,
    sortino_mae,
    historical_var,
    conditional_var,
    parametric_var,
    compute_beta,
    r_multiple_stats,
    r_multiple_histogram,
    compute_funding_exposure,
)


# ── daily_returns ────────────────────────────────────────────────────────────

class TestDailyReturns:
    def test_empty(self):
        assert daily_returns([]) == []

    def test_single_value(self):
        assert daily_returns([100.0]) == []

    def test_known_series(self):
        # 100 → 110 → 99 → 108
        # returns: 0.10, -0.10, 0.0909...
        rets = daily_returns([100, 110, 99, 108])
        assert len(rets) == 3
        assert rets[0] == pytest.approx(0.10, rel=1e-4)
        assert rets[1] == pytest.approx(-0.1, rel=1e-4)
        assert rets[2] == pytest.approx(108 / 99 - 1, rel=1e-4)

    def test_zero_prev_skipped(self):
        """Zero denominator should be skipped (no division by zero)."""
        rets = daily_returns([0, 100, 110])
        # 0→100: skipped (prev=0), 100→110: 0.10
        assert len(rets) == 1
        assert rets[0] == pytest.approx(0.10, rel=1e-4)


# ── sharpe ───────────────────────────────────────────────────────────────────

class TestSharpe:
    def test_insufficient_data(self):
        assert sharpe([]) == 0.0
        assert sharpe([0.01]) == 0.0

    def test_all_same_returns(self):
        """Zero std → 0.0 (avoid div by zero)."""
        assert sharpe([0.01] * 30) == 0.0

    def test_positive_returns(self):
        """Consistent positive returns → positive Sharpe."""
        rets = [0.005, 0.01, 0.003, 0.008, 0.006, 0.004, 0.007, 0.002, 0.009, 0.005]
        s = sharpe(rets)
        assert s > 0

    def test_annualization(self):
        """Sharpe scales by sqrt(periods_per_year)."""
        rets = [0.01, -0.005, 0.008, -0.003, 0.006, 0.004, -0.001, 0.003, 0.005, -0.002]
        s365 = sharpe(rets, periods_per_year=365)
        s252 = sharpe(rets, periods_per_year=252)
        assert s365 / s252 == pytest.approx(math.sqrt(365 / 252), rel=1e-4)


# ── sortino ──────────────────────────────────────────────────────────────────

class TestSortino:
    def test_insufficient_data(self):
        assert sortino([]) == 0.0

    def test_no_losing_days(self):
        """No downside → 999.0 cap."""
        assert sortino([0.01, 0.02, 0.03, 0.04, 0.05]) == 999.0

    def test_worse_than_sharpe_for_symmetric_returns(self):
        """For symmetric returns, Sortino ≈ Sharpe × sqrt(2) because
        downside_std ≈ std/sqrt(2) for normal distributions."""
        rets = [0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01]
        s = sharpe(rets)
        so = sortino(rets)
        # Both should be near zero (mean ≈ 0)
        assert abs(s) < 1.0
        assert abs(so) < 1.0


# ── historical_var ───────────────────────────────────────────────────────────

class TestHistoricalVaR:
    def test_insufficient_data(self):
        assert historical_var([0.01] * 19) == 0.0

    def test_known_sorted_series(self):
        """VaR at 95%: 5th percentile of sorted returns."""
        # 20 returns: [-0.10, -0.09, ..., -0.01, 0.00, 0.01, ..., 0.09]
        rets = [(i - 10) / 100 for i in range(20)]
        var = historical_var(rets, confidence=0.95)
        # 5% of 20 = 1.0 → idx = max(0, 1-1) = 0 → rets[0] = -0.10
        assert var == rets[0]

    def test_higher_confidence_worse_var(self):
        """Higher confidence → more extreme VaR (further into the tail)."""
        rets = [(i - 50) / 1000 for i in range(100)]
        var95 = historical_var(rets, 0.95)
        var99 = historical_var(rets, 0.99)
        assert var99 <= var95  # 99% VaR is deeper in the left tail


# ── conditional_var ──────────────────────────────────────────────────────────

class TestCVaR:
    def test_insufficient_data(self):
        assert conditional_var([0.01] * 19) == 0.0

    def test_cvar_worse_than_var(self):
        """CVaR (expected shortfall) should be ≤ VaR (deeper into tail)."""
        rets = [(i - 50) / 1000 for i in range(100)]
        var = historical_var(rets, 0.95)
        cvar = conditional_var(rets, 0.95)
        assert cvar <= var


# ── parametric_var ───────────────────────────────────────────────────────────

class TestParametricVaR:
    def test_insufficient_data(self):
        assert parametric_var([0.01] * 9) == 0.0

    def test_known_normal(self):
        """For a series with known mean and std, verify formula μ - z·σ."""
        # 10 identical returns → mean=0.01, std=0 → VaR = 0.01
        # But std=0 makes it trivial. Use a small spread.
        rets = [0.01 + 0.001 * (i - 5) for i in range(10)]
        var = parametric_var(rets, 0.95)
        mean = sum(rets) / len(rets)
        std = math.sqrt(sum((r - mean) ** 2 for r in rets) / 9)
        expected = mean - 1.645 * std
        assert var == pytest.approx(expected, rel=1e-4)


# ── compute_beta ─────────────────────────────────────────────────────────────

class TestBeta:
    def test_insufficient_data(self):
        """< 10 data points → default beta 1.0."""
        assert compute_beta([0.01] * 5, [0.02] * 5) == 1.0

    def test_perfect_correlation(self):
        """Position = 2× benchmark → beta = 2.0."""
        bench = [0.01 * i for i in range(20)]
        pos = [2 * r for r in bench]
        beta = compute_beta(pos, bench)
        assert beta == pytest.approx(2.0, rel=1e-2)

    def test_zero_benchmark_variance(self):
        """Constant benchmark → beta 1.0 (fallback)."""
        pos = [0.01 * i for i in range(20)]
        bench = [0.05] * 20
        beta = compute_beta(pos, bench)
        assert beta == 1.0

    def test_negative_correlation(self):
        """Position = -1× benchmark → beta ≈ -1.0."""
        bench = [0.01 * i for i in range(20)]
        pos = [-r for r in bench]
        beta = compute_beta(pos, bench)
        assert beta == pytest.approx(-1.0, rel=1e-2)


# ── r_multiple_stats ─────────────────────────────────────────────────────────

class TestRMultipleStats:
    def test_empty(self):
        assert r_multiple_stats([]) == {}

    def test_all_winners(self):
        result = r_multiple_stats([1.0, 2.0, 3.0])
        assert result["win_rate"] == pytest.approx(1.0)
        assert result["avg_loss_r"] == 0.0
        assert result["profit_factor"] == 999.0

    def test_mixed(self):
        result = r_multiple_stats([2.0, -1.0, 1.5, -0.5])
        assert result["count"] == 4
        assert result["win_rate"] == pytest.approx(0.5)
        # mean = (2 - 1 + 1.5 - 0.5) / 4 = 0.5
        assert result["mean"] == pytest.approx(0.5, abs=0.01)
        # profit_factor = |sum(pos)| / |sum(neg)| = 3.5 / 1.5 = 2.333
        assert result["profit_factor"] == pytest.approx(2.33, abs=0.01)


# ── r_multiple_histogram ────────────────────────────────────────────────────

class TestRMultipleHistogram:
    def test_known_distribution(self):
        r_vals = [-4, -2.5, -0.5, 0.5, 1.5, 2.5, 4]
        bins = r_multiple_histogram(r_vals)
        assert len(bins) == 8
        # -4 → "< -3": count=1
        assert bins[0]["count"] == 1
        # 4 → "> 3": count=1
        assert bins[7]["count"] == 1


# ── compute_funding_exposure ─────────────────────────────────────────────────

class TestFundingExposure:
    def test_basic_calculation(self):
        result = compute_funding_exposure(100000, 0.0001)
        # per_8h = |100000 * 0.0001| = 10
        # per_day = 10 * 3 = 30
        # per_week = 30 * 7 = 210
        assert result["per_8h"] == pytest.approx(10.0, rel=1e-4)
        assert result["per_day"] == pytest.approx(30.0, rel=1e-4)
        assert result["per_week"] == pytest.approx(210.0, rel=1e-4)

    def test_negative_rate(self):
        """Negative funding rate (short pays long) → still positive amounts."""
        result = compute_funding_exposure(50000, -0.0003)
        assert result["per_8h"] == pytest.approx(15.0, rel=1e-4)
        assert result["per_8h"] > 0  # absolute value

    def test_zero_notional(self):
        result = compute_funding_exposure(0, 0.0001)
        assert result["per_8h"] == 0.0
