"""
Analytics computations — pure functions, no I/O.

All functions gracefully return 0.0 / {} / [] on insufficient data
so callers never need try/except for the math itself.

Annualisation factor: 365 (crypto markets run 24/7/365).
Risk-free rate:       0.0  (default; pass explicitly to override).
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional


# ── Return series helpers ─────────────────────────────────────────────────────

def daily_returns(equity_series: List[float]) -> List[float]:
    """Day-over-day percentage returns from an equity series."""
    if len(equity_series) < 2:
        return []
    out = []
    for i in range(1, len(equity_series)):
        prev = equity_series[i - 1]
        if prev != 0:
            out.append((equity_series[i] - prev) / prev)
    return out


# ── Standard ratio calculations ───────────────────────────────────────────────

def sharpe(
    returns: List[float],
    risk_free_daily: float = 0.0,
    periods_per_year: int = 365,
) -> float:
    """Annualised Sharpe ratio from a daily returns series."""
    if len(returns) < 2:
        return 0.0
    excess = [r - risk_free_daily for r in returns]
    n = len(excess)
    mean = sum(excess) / n
    variance = sum((r - mean) ** 2 for r in excess) / (n - 1)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(periods_per_year)


def sortino(
    returns: List[float],
    risk_free_daily: float = 0.0,
    periods_per_year: int = 365,
) -> float:
    """Annualised Sortino ratio — only penalises downside deviation."""
    if len(returns) < 2:
        return 0.0
    excess = [r - risk_free_daily for r in returns]
    n = len(excess)
    mean = sum(excess) / n
    downside = [r for r in excess if r < 0]
    if not downside:
        return 999.0   # No losing days — effectively infinite; cap at display value
    downside_var = sum(r ** 2 for r in downside) / len(downside)
    downside_std = math.sqrt(downside_var)
    if downside_std == 0:
        return 0.0
    return (mean / downside_std) * math.sqrt(periods_per_year)


# ── Excursion-based ratio variants ────────────────────────────────────────────

def sharpe_mfe(
    trades: List[Dict],
    periods_per_year: int = 365,
) -> float:
    """
    MFE-based Sharpe.

    Treats each trade's (mfe / notional) as a 'best-case return observation'.
    Measures consistency of profit capture relative to excursion volatility.
    Requires trades with keys: mfe, notional (both non-zero).
    """
    mfe_returns = [
        t["mfe"] / t["notional"]
        for t in trades
        if t.get("notional", 0) > 0 and t.get("mfe") is not None
    ]
    if len(mfe_returns) < 2:
        return 0.0
    n = len(mfe_returns)
    mean = sum(mfe_returns) / n
    variance = sum((r - mean) ** 2 for r in mfe_returns) / (n - 1)
    std = math.sqrt(variance)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(periods_per_year)


def sortino_mae(
    trades: List[Dict],
    periods_per_year: int = 365,
) -> float:
    """
    MAE-based Sortino.

    Downside deviation computed over each trade's (mae / notional).
    Lower = tighter adverse excursions relative to position size.
    Requires trades with keys: mae, notional (both non-zero).
    Note: mae values are negative (adverse), so no sign flip needed.
    """
    mae_returns = [
        t["mae"] / t["notional"]
        for t in trades
        if t.get("notional", 0) > 0 and t.get("mae") is not None
    ]
    if len(mae_returns) < 2:
        return 0.0
    n = len(mae_returns)
    mean = sum(mae_returns) / n
    downside = [r for r in mae_returns if r < 0]
    if not downside:
        return 999.0
    downside_var = sum(r ** 2 for r in downside) / len(downside)
    downside_std = math.sqrt(downside_var)
    if downside_std == 0:
        return 0.0
    return (mean / downside_std) * math.sqrt(periods_per_year)


# ── Risk metrics ──────────────────────────────────────────────────────────────

def historical_var(returns: List[float], confidence: float = 0.95) -> float:
    """
    Historical VaR at given confidence level.
    Returns a negative number representing the loss threshold.
    Requires at least 20 data points; returns 0.0 otherwise.
    """
    if len(returns) < 20:
        return 0.0
    sorted_r = sorted(returns)
    idx = max(0, int(len(sorted_r) * (1 - confidence)) - 1)
    return sorted_r[idx]


def conditional_var(returns: List[float], confidence: float = 0.95) -> float:
    """
    CVaR / Expected Shortfall — mean of returns at or below VaR.
    Returns 0.0 when insufficient data.
    """
    var = historical_var(returns, confidence)
    if var == 0.0 and len(returns) < 20:
        return 0.0
    tail = [r for r in returns if r <= var]
    return sum(tail) / len(tail) if tail else 0.0


def parametric_var(returns: List[float], confidence: float = 0.95) -> float:
    """
    Parametric (Gaussian) VaR: μ - z·σ where z=1.645 for 95%.
    Returns 0.0 when insufficient data.
    """
    if len(returns) < 10:
        return 0.0
    n = len(returns)
    mean = sum(returns) / n
    std = math.sqrt(sum((r - mean) ** 2 for r in returns) / max(n - 1, 1))
    # z-scores: 90%=1.282, 95%=1.645, 99%=2.326
    z = {0.90: 1.282, 0.95: 1.645, 0.99: 2.326}.get(confidence, 1.645)
    return mean - z * std


# ── Beta ──────────────────────────────────────────────────────────────────────

def compute_beta(
    position_returns: List[float],
    benchmark_returns: List[float],
) -> float:
    """
    OLS beta of a position series vs a benchmark (e.g., BTC daily returns).
    Returns 1.0 when fewer than 10 aligned data points.
    """
    n = min(len(position_returns), len(benchmark_returns))
    if n < 10:
        return 1.0
    px = position_returns[-n:]
    bx = benchmark_returns[-n:]
    mean_p = sum(px) / n
    mean_b = sum(bx) / n
    cov    = sum((px[i] - mean_p) * (bx[i] - mean_b) for i in range(n)) / n
    var_b  = sum((bx[i] - mean_b) ** 2 for i in range(n)) / n
    return cov / var_b if var_b != 0 else 1.0


# ── R-multiple statistics ─────────────────────────────────────────────────────

def r_multiple_stats(r_multiples: List[float]) -> Dict:
    """
    Full distribution summary for a list of R-multiple values.
    Returns an empty dict when the list is empty.
    """
    if not r_multiples:
        return {}
    pos = [r for r in r_multiples if r > 0]
    neg = [r for r in r_multiples if r <= 0]
    n   = len(r_multiples)
    sorted_r = sorted(r_multiples)
    median   = sorted_r[n // 2] if n % 2 == 1 else (sorted_r[n // 2 - 1] + sorted_r[n // 2]) / 2
    profit_factor = (
        abs(sum(pos) / sum(neg))
        if neg and sum(neg) != 0
        else 999.0
    )
    return {
        "count":          n,
        "mean":           round(sum(r_multiples) / n, 3),
        "median":         round(median, 3),
        "win_rate":       round(len(pos) / n, 4),
        "avg_win_r":      round(sum(pos) / len(pos), 3) if pos else 0.0,
        "avg_loss_r":     round(sum(neg) / len(neg), 3) if neg else 0.0,
        "expectancy":     round(sum(r_multiples) / n, 3),
        "profit_factor":  round(profit_factor, 2),
        "best":           round(max(r_multiples), 3),
        "worst":          round(min(r_multiples), 3),
    }


def r_multiple_histogram(r_multiples: List[float]) -> List[Dict]:
    """
    Bucket R-multiples into display-friendly histogram bins.
    Returns list of {label, count, pos} dicts for template rendering.
    """
    bins = [
        ("< -3",   lambda r: r < -3),
        ("-3–-2",  lambda r: -3 <= r < -2),
        ("-2–-1",  lambda r: -2 <= r < -1),
        ("-1–0",   lambda r: -1 <= r < 0),
        ("0–1",    lambda r: 0  <= r < 1),
        ("1–2",    lambda r: 1  <= r < 2),
        ("2–3",    lambda r: 2  <= r < 3),
        ("> 3",    lambda r: r >= 3),
    ]
    out = []
    for label, test in bins:
        count = sum(1 for r in r_multiples if test(r))
        out.append({"label": label, "count": count, "pos": label.startswith(("0", "1", "2", ">"))})
    return out


# ── Calendar helpers ──────────────────────────────────────────────────────────

def build_calendar_grid(
    year: int,
    month: int,
    daily_pnl: Dict[str, float],
    daily_stats: Dict[str, Dict] = None,
) -> List[List[Dict]]:
    """
    Build a 7-column calendar grid for the given month.

    daily_pnl:   {"YYYY-MM-DD": pnl_float, ...}
    daily_stats: {"YYYY-MM-DD": {"trades": int, "volume": float, "win_rate": float}}
    Returns: list of weeks, each week = list of 7 day-dicts.
    """
    import calendar as _cal
    first_weekday, num_days = _cal.monthrange(year, month)
    _stats = daily_stats or {}
    cells: List[Dict] = []
    for _ in range(first_weekday):
        cells.append({"day": None, "date": None, "pnl": None, "pct": None,
                      "trades": None, "volume": None, "win_rate": None})
    for day in range(1, num_days + 1):
        date_str = f"{year:04d}-{month:02d}-{day:02d}"
        pnl  = daily_pnl.get(date_str)
        stat = _stats.get(date_str, {})
        cells.append({
            "day":      day,
            "date":     date_str,
            "pnl":      pnl,
            "pct":      None,
            "trades":   stat.get("trades"),
            "volume":   stat.get("volume"),
            "win_rate": stat.get("win_rate"),
        })
    while len(cells) % 7 != 0:
        cells.append({"day": None, "date": None, "pnl": None, "pct": None,
                      "trades": None, "volume": None, "win_rate": None})
    return [cells[i:i + 7] for i in range(0, len(cells), 7)]


# ── Funding helpers ───────────────────────────────────────────────────────────

def compute_funding_exposure(
    position_notional: float,
    funding_rate: float,
) -> Dict[str, float]:
    """
    Compute expected funding payments.
    Binance settles every 8h, so 3 payments per day.
    Returns: per_8h, per_day, per_week amounts in USDT.
    """
    per_8h   = abs(position_notional * funding_rate)
    per_day  = per_8h * 3
    per_week = per_day * 7
    return {
        "per_8h":   round(per_8h,   4),
        "per_day":  round(per_day,  4),
        "per_week": round(per_week, 4),
    }
