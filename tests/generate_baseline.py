"""
Generate pre-audit baseline CSV from deterministic inputs.

Calls every pure-math function in core/risk_engine.py and core/analytics.py
with fixed inputs, captures outputs, and writes to
tests/baselines/pre_audit_baseline.csv.

Run:  python -m tests.generate_baseline
"""
from __future__ import annotations

import csv
import math
import os
import sys
from typing import List
from unittest.mock import patch, MagicMock

# Ensure project root is on sys.path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.risk_engine import (
    _wilder_atr,
    calculate_atr_coefficient,
    estimate_vwap_fill,
    calculate_slippage,
    calculate_one_percent_depth,
    calculate_position_size,
)
from core.analytics import (
    daily_returns,
    sharpe,
    sortino,
    historical_var,
    conditional_var,
    parametric_var,
    compute_beta,
    r_multiple_stats,
    r_multiple_histogram,
    compute_funding_exposure,
)

OUT_PATH = os.path.join(ROOT, "tests", "baselines", "pre_audit_baseline.csv")
ROWS: list[dict] = []


def record(function: str, case: str, key: str, value):
    """Append one row to the global baseline."""
    ROWS.append({
        "function": function,
        "case": case,
        "output_key": key,
        "value": repr(value),
    })


# ── Helpers (identical to test fixtures) ────────────────────────────────────

def _make_candles(closes: List[float], spread: float = 2.0) -> List[list]:
    candles = []
    for i, c in enumerate(closes):
        o = closes[i - 1] if i > 0 else c
        h = c + spread / 2
        lo = c - spread / 2
        candles.append([i * 3600000, o, h, lo, c, 1000.0])
    return candles


def _make_orderbook(asks: list, bids: list) -> dict:
    return {"asks": asks, "bids": bids}


# ── _wilder_atr ─────────────────────────────────────────────────────────────

def baseline_wilder_atr():
    fn = "_wilder_atr"

    # Case 1: insufficient data
    candles = _make_candles([100.0] * 5)
    r = _wilder_atr(candles, period=14)
    record(fn, "insufficient_5bars_p14", "result", r)

    # Case 2: constant spread, gentle trend
    closes = [100.0 + i * 0.1 for i in range(120)]
    candles = _make_candles(closes, spread=2.0)
    r = _wilder_atr(candles, period=14)
    record(fn, "constant_spread_trend_p14", "atr", r)

    # Case 3: minimum data for period
    candles = _make_candles([100.0] * 16, spread=4.0)
    r = _wilder_atr(candles, period=15)
    record(fn, "min_data_p15_spread4", "atr", r)

    # Case 4: flat constant
    candles = _make_candles([100.0] * 120, spread=2.0)
    r = _wilder_atr(candles, period=14)
    record(fn, "flat_120bars_p14", "atr", r)

    # Case 5: flat constant, period=100
    r100 = _wilder_atr(candles, period=100)
    record(fn, "flat_120bars_p100", "atr", r100)


# ── calculate_atr_coefficient ───────────────────────────────────────────────

def baseline_atr_coefficient():
    fn = "calculate_atr_coefficient"

    # Case 1: empty cache
    mock_state = MagicMock()
    mock_state.ohlcv_cache = {}
    with patch("core.risk_engine.app_state", mock_state), \
         patch("core.risk_engine.config") as mock_cfg:
        mock_cfg.ATR_SHORT_PERIOD = 14
        mock_cfg.ATR_LONG_PERIOD = 100
        atr_c, cat, atr14, atr100 = calculate_atr_coefficient("X")
    record(fn, "empty_cache", "atr_c", atr_c)
    record(fn, "empty_cache", "category", cat)

    # Case 2: stable data (120 bars, constant)
    candles = _make_candles([100.0] * 120, spread=2.0)
    mock_state = MagicMock()
    mock_state.ohlcv_cache = {"X": candles}
    with patch("core.risk_engine.app_state", mock_state), \
         patch("core.risk_engine.config") as mock_cfg:
        mock_cfg.ATR_SHORT_PERIOD = 14
        mock_cfg.ATR_LONG_PERIOD = 100
        atr_c, cat, atr14, atr100 = calculate_atr_coefficient("X")
    record(fn, "stable_120", "atr_c", atr_c)
    record(fn, "stable_120", "category", cat)
    record(fn, "stable_120", "atr14", atr14)
    record(fn, "stable_120", "atr100", atr100)

    # Case 3: mocked ATR values → too_volatile
    mock_state = MagicMock()
    mock_state.ohlcv_cache = {"X": [[0]] * 120}
    with patch("core.risk_engine.app_state", mock_state), \
         patch("core.risk_engine.config") as mock_cfg, \
         patch("core.risk_engine._wilder_atr") as mock_atr:
        mock_cfg.ATR_SHORT_PERIOD = 14
        mock_cfg.ATR_LONG_PERIOD = 100
        mock_atr.side_effect = lambda data, period: 100.0 if period == 14 else 10.0
        atr_c, cat, atr14, atr100 = calculate_atr_coefficient("X")
    record(fn, "too_volatile_mocked", "atr_c", atr_c)
    record(fn, "too_volatile_mocked", "category", cat)


# ── estimate_vwap_fill ──────────────────────────────────────────────────────

def baseline_vwap_fill():
    fn = "estimate_vwap_fill"

    # Case 1: no orderbook
    mock_state = MagicMock()
    mock_state.orderbook_cache = {}
    with patch("core.risk_engine.app_state", mock_state):
        r = estimate_vwap_fill("X", "long", 1000, 50000)
    record(fn, "no_orderbook", "fill", r)

    # Case 2: single level sufficient
    ob = _make_orderbook(asks=[[50000, 10.0]], bids=[])
    mock_state = MagicMock()
    mock_state.orderbook_cache = {"X": ob}
    with patch("core.risk_engine.app_state", mock_state):
        r = estimate_vwap_fill("X", "long", 100000, 50000)
    record(fn, "single_level", "fill", r)

    # Case 3: sweep two levels
    ob = _make_orderbook(asks=[[100, 50.0], [102, 50.0]], bids=[])
    mock_state = MagicMock()
    mock_state.orderbook_cache = {"X": ob}
    with patch("core.risk_engine.app_state", mock_state):
        r = estimate_vwap_fill("X", "long", 7000, 100)
    record(fn, "sweep_two_levels", "fill", r)

    # Case 4: short side
    ob = _make_orderbook(asks=[], bids=[[50000, 10.0], [49900, 10.0]])
    mock_state = MagicMock()
    mock_state.orderbook_cache = {"X": ob}
    with patch("core.risk_engine.app_state", mock_state):
        r = estimate_vwap_fill("X", "short", 100000, 50000)
    record(fn, "short_single_level", "fill", r)


# ── calculate_slippage ──────────────────────────────────────────────────────

def baseline_slippage():
    fn = "calculate_slippage"

    # Case 1: no orderbook
    mock_state = MagicMock()
    mock_state.orderbook_cache = {}
    with patch("core.risk_engine.app_state", mock_state):
        slip, fill = calculate_slippage("X", "long", 1000, 100)
    record(fn, "no_orderbook", "slippage", slip)
    record(fn, "no_orderbook", "fill", fill)

    # Case 2: single level zero slippage
    ob = _make_orderbook(asks=[[100, 1000.0]], bids=[])
    mock_state = MagicMock()
    mock_state.orderbook_cache = {"X": ob}
    with patch("core.risk_engine.app_state", mock_state):
        slip, fill = calculate_slippage("X", "long", 5000, 100)
    record(fn, "single_level_zero", "slippage", slip)
    record(fn, "single_level_zero", "fill", fill)

    # Case 3: multi level
    ob = _make_orderbook(asks=[[100, 10.0], [105, 10.0], [110, 10.0]], bids=[])
    mock_state = MagicMock()
    mock_state.orderbook_cache = {"X": ob}
    with patch("core.risk_engine.app_state", mock_state):
        slip, fill = calculate_slippage("X", "long", 2500, 100)
    record(fn, "multi_level_long", "slippage", slip)
    record(fn, "multi_level_long", "fill", fill)

    # Case 4: short multi level
    ob = _make_orderbook(asks=[], bids=[[100, 10.0], [95, 10.0], [90, 10.0]])
    mock_state = MagicMock()
    mock_state.orderbook_cache = {"X": ob}
    with patch("core.risk_engine.app_state", mock_state):
        slip, fill = calculate_slippage("X", "short", 2500, 100)
    record(fn, "multi_level_short", "slippage", slip)
    record(fn, "multi_level_short", "fill", fill)


# ── calculate_one_percent_depth ─────────────────────────────────────────────

def baseline_depth():
    fn = "calculate_one_percent_depth"

    ob = _make_orderbook(
        asks=[[100, 5.0], [100.5, 5.0], [102, 5.0]],
        bids=[[99.5, 5.0], [97, 5.0]],
    )
    mock_state = MagicMock()
    mock_state.orderbook_cache = {"X": ob}
    with patch("core.risk_engine.app_state", mock_state):
        depth = calculate_one_percent_depth("X", 100)
    record(fn, "mixed_in_out_range", "depth", depth)


# ── calculate_position_size ─────────────────────────────────────────────────

def baseline_position_size():
    fn = "calculate_position_size"

    def run(symbol, avg, sl, equity, side, ohlcv=None, ob=None, params=None):
        mock_state = MagicMock()
        mock_state.ohlcv_cache = {symbol: ohlcv or []}
        mock_state.orderbook_cache = {symbol: ob} if ob else {}
        mock_state.params = params or {"individual_risk_per_trade": 0.01}
        with patch("core.risk_engine.app_state", mock_state), \
             patch("core.risk_engine.config") as mock_cfg:
            mock_cfg.ATR_SHORT_PERIOD = 14
            mock_cfg.ATR_LONG_PERIOD = 100
            return calculate_position_size(symbol, avg, sl, equity, side)

    # Case 1: zero entry
    r = run("X", 0, 100, 10000, "long")
    record(fn, "zero_entry", "eligible", r["eligible"])
    record(fn, "zero_entry", "size", r["size"])

    # Case 2: SL equals entry
    r = run("X", 100, 100, 10000, "long")
    record(fn, "sl_eq_entry", "eligible", r["eligible"])
    record(fn, "sl_eq_entry", "reason", r["ineligible_reason"])

    # Case 3: basic long, no OHLCV
    r = run("X", 100, 95, 10000, "long", params={"individual_risk_per_trade": 0.01})
    record(fn, "basic_long_5pct_sl", "base_size", r["base_size"])
    record(fn, "basic_long_5pct_sl", "risk_usdt", r["risk_usdt"])
    record(fn, "basic_long_5pct_sl", "eligible", r["eligible"])
    record(fn, "basic_long_5pct_sl", "atr_c", r["atr_c"])

    # Case 4: basic short, no OHLCV
    r = run("X", 100, 105, 10000, "short", params={"individual_risk_per_trade": 0.01})
    record(fn, "basic_short_5pct_sl", "base_size", r["base_size"])
    record(fn, "basic_short_5pct_sl", "risk_usdt", r["risk_usdt"])

    # Case 5: tight SL
    r = run("X", 100, 98, 10000, "long")
    record(fn, "tight_2pct_sl", "base_size", r["base_size"])

    # Case 6: wide SL
    r = run("X", 100, 90, 10000, "long")
    record(fn, "wide_10pct_sl", "base_size", r["base_size"])


# ── Analytics: daily_returns ────────────────────────────────────────────────

def baseline_daily_returns():
    fn = "daily_returns"

    record(fn, "empty", "result", daily_returns([]))
    record(fn, "single", "result", daily_returns([100.0]))

    rets = daily_returns([100, 110, 99, 108])
    for i, r in enumerate(rets):
        record(fn, "known_series", f"ret[{i}]", r)

    rets = daily_returns([0, 100, 110])
    record(fn, "zero_prev", "length", len(rets))
    for i, r in enumerate(rets):
        record(fn, "zero_prev", f"ret[{i}]", r)


# ── Analytics: sharpe ───────────────────────────────────────────────────────

def baseline_sharpe():
    fn = "sharpe"

    record(fn, "empty", "result", sharpe([]))
    record(fn, "single", "result", sharpe([0.01]))
    record(fn, "constant", "result", sharpe([0.01] * 30))

    rets = [0.01, -0.005, 0.008, -0.003, 0.006, 0.004, -0.001, 0.003, 0.005, -0.002]
    record(fn, "mixed_365", "result", sharpe(rets, periods_per_year=365))
    record(fn, "mixed_252", "result", sharpe(rets, periods_per_year=252))


# ── Analytics: sortino ──────────────────────────────────────────────────────

def baseline_sortino():
    fn = "sortino"

    record(fn, "empty", "result", sortino([]))
    record(fn, "no_downside", "result", sortino([0.01, 0.02, 0.03, 0.04, 0.05]))

    rets = [0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01, 0.01, -0.01]
    record(fn, "symmetric", "result", sortino(rets))


# ── Analytics: historical_var ───────────────────────────────────────────────

def baseline_historical_var():
    fn = "historical_var"

    record(fn, "insufficient_19", "result", historical_var([0.01] * 19))

    rets = [(i - 10) / 100 for i in range(20)]
    record(fn, "20_uniform_95", "result", historical_var(rets, 0.95))

    rets100 = [(i - 50) / 1000 for i in range(100)]
    record(fn, "100_uniform_95", "result", historical_var(rets100, 0.95))
    record(fn, "100_uniform_99", "result", historical_var(rets100, 0.99))


# ── Analytics: conditional_var ──────────────────────────────────────────────

def baseline_cvar():
    fn = "conditional_var"

    record(fn, "insufficient_19", "result", conditional_var([0.01] * 19))

    rets = [(i - 50) / 1000 for i in range(100)]
    record(fn, "100_uniform_95", "result", conditional_var(rets, 0.95))


# ── Analytics: parametric_var ───────────────────────────────────────────────

def baseline_parametric_var():
    fn = "parametric_var"

    record(fn, "insufficient_9", "result", parametric_var([0.01] * 9))

    rets = [0.01 + 0.001 * (i - 5) for i in range(10)]
    record(fn, "small_spread_95", "result", parametric_var(rets, 0.95))


# ── Analytics: compute_beta ─────────────────────────────────────────────────

def baseline_beta():
    fn = "compute_beta"

    record(fn, "insufficient_5", "result", compute_beta([0.01] * 5, [0.02] * 5))

    bench = [0.01 * i for i in range(20)]
    pos2x = [2 * r for r in bench]
    record(fn, "perfect_2x", "result", compute_beta(pos2x, bench))

    pos_neg = [-r for r in bench]
    record(fn, "negative_1x", "result", compute_beta(pos_neg, bench))

    record(fn, "zero_bench_var", "result", compute_beta([0.01 * i for i in range(20)], [0.05] * 20))


# ── Analytics: r_multiple_stats ─────────────────────────────────────────────

def baseline_r_stats():
    fn = "r_multiple_stats"

    record(fn, "empty", "result", r_multiple_stats([]))

    r = r_multiple_stats([1.0, 2.0, 3.0])
    for k, v in sorted(r.items()):
        record(fn, "all_winners", k, v)

    r = r_multiple_stats([2.0, -1.0, 1.5, -0.5])
    for k, v in sorted(r.items()):
        record(fn, "mixed", k, v)


# ── Analytics: r_multiple_histogram ─────────────────────────────────────────

def baseline_r_histogram():
    fn = "r_multiple_histogram"

    r_vals = [-4, -2.5, -0.5, 0.5, 1.5, 2.5, 4]
    bins = r_multiple_histogram(r_vals)
    for i, b in enumerate(bins):
        record(fn, "known_dist", f"bin[{i}]_label", b["label"])
        record(fn, "known_dist", f"bin[{i}]_count", b["count"])


# ── Analytics: compute_funding_exposure ─────────────────────────────────────

def baseline_funding():
    fn = "compute_funding_exposure"

    r = compute_funding_exposure(100000, 0.0001)
    for k, v in sorted(r.items()):
        record(fn, "basic_100k", k, v)

    r = compute_funding_exposure(50000, -0.0003)
    for k, v in sorted(r.items()):
        record(fn, "negative_rate_50k", k, v)

    r = compute_funding_exposure(0, 0.0001)
    for k, v in sorted(r.items()):
        record(fn, "zero_notional", k, v)


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    baseline_wilder_atr()
    baseline_atr_coefficient()
    baseline_vwap_fill()
    baseline_slippage()
    baseline_depth()
    baseline_position_size()
    baseline_daily_returns()
    baseline_sharpe()
    baseline_sortino()
    baseline_historical_var()
    baseline_cvar()
    baseline_parametric_var()
    baseline_beta()
    baseline_r_stats()
    baseline_r_histogram()
    baseline_funding()

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["function", "case", "output_key", "value"])
        writer.writeheader()
        writer.writerows(ROWS)

    print(f"Wrote {len(ROWS)} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
