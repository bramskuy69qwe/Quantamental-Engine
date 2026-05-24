"""
Historical counterfactual replay — re-size past trades through a
candidate regime model.

Task 169 (regime build 2a). Single-candidate: replays the LIVE v1
JSON rule set across the full past-trade history. The multi-candidate
leaderboard is T-2b (out of scope here).

T156 verdict: feasible today via date-join between closed_positions
and regime_signals — no signal backfill prerequisite for trades within
the existing signal-history window.

Mechanism for each past trade:
  1. Take the trade's `entry_time_ms` (sizing is decided at entry,
     not exit) and derive `trade_date = YYYY-MM-DD UTC`.
  2. For each known signal, binary-search regime_signals for the
     most-recent value AT OR BEFORE trade_date (re-uses
     regime_classifier._lookup_nearest).
  3. Build signals dict; `has_crypto = "agg_oi_change" in signals or
     "avg_funding" in signals` picks `mode = "full" | "macro_only"`
     for this REPLAY (independent of what the live engine recorded —
     T168 caveat: counterfactual mode is determined by signal-data
     availability AT THAT DATE, not by config.REGIME_STALE_MINUTES
     etc.).
  4. classify_regime(signals, mode=cf_mode) → v1_label.
  5. v1_multiplier = config.REGIME_MULTIPLIERS[v1_label].
  6. Re-size under T167's linear-scaling assumption:
        x1_pnl = actual / actual_applied_mult
        v1_pnl = x1_pnl × v1_multiplier
              = actual × (v1_multiplier / actual_applied_mult)
     where actual_applied_mult = pre_trade_log.regime_multiplier
     if that row exists AND its value > 0, else 1.0 (pre-T157 trades
     + toggle-OFF trades + stale-fallback trades all had no regime
     scaling applied, so their actual P&L IS the x1 P&L).

Output framing — SCREENING ONLY:
  Historical counterfactual ranks are subject to curve-fitting bias
  (a model tuned to look good on past trades has zero out-of-sample
  predictive power). The output explicitly carries a "screening"
  framing so consumers can't accidentally read it as promotion.
  Promotion requires forward two-track confirmation per the regime-
  plan's promotion discipline (`v2.5_regime-plan.md` §Regime
  validation §2).

Per-mode segmentation (T168 carry-forward):
  Pre-window trades replay macro_only (crypto signals not available
  that far back — Binance API ~2-3yr limit). Recent trades replay
  full. The summary breaks down per-mode totals so consumers can see
  the macro_only-only window separately from the full-mode window
  and NEVER silently mix the two.

Conservative x1 bias (T167 carry-forward):
  The linear-scaling assumption ignores slippage's super-linear
  component. x1 (the no-regime baseline) is computed at the larger
  size and so the slippage bias UNDERSTATES x1's true loss vs the
  smaller regime-sized trade — i.e. the linear x1 under-credits
  regime de-sizing. Documented in the summary output so marginal
  numbers read correctly.

Edge cases (silently excluded, counted under `summary.excluded`):
  - No `entry_time_ms` (trade has DEFAULT 0 — can't derive date).
  - No signal coverage at trade_date (regime_signals doesn't cover
    that far back at all — even macro_only can't classify).
  - Pollution shape (entry<=0 AND quantity>0 AND exit>0 — defense-
    in-depth against pre-T168 pollution rows in closed_positions).
  - actual_applied_mult <= 0 (defensive; the SQL COALESCE guards
    this but the Python layer asserts too).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import config
from core.database import db
from core.regime_classifier import (
    ALL_SIGNALS,
    _lookup_nearest,
    classify_regime,
)

log = logging.getLogger("regime_counterfactual")


SCREENING_FRAMING = {
    "type": "screening",
    "warning": (
        "SCREENING ONLY — historical counterfactual rank does NOT promote "
        "a regime model. Promotion requires forward two-track confirmation "
        "(actual sizing decisions accruing over real time). Curve-fitting "
        "bias means a good historical number is necessary-but-not-sufficient. "
        "See v2.5_regime-plan.md §Regime validation §2."
    ),
    "linear_scaling_caveat": (
        "Linear-scaling assumption applies (T167 acceptance): P&L scales "
        "with size at retail volume; fees scale linearly with notional; "
        "slippage is super-linear (under-credits regime de-sizing — x1 "
        "would have eaten more book depth than the actual regime-sized "
        "trade). Marginal positive deltas should be read conservatively."
    ),
    "hysteresis_bypass_caveat": (
        "The replay uses raw classify_regime per trade — NO hysteresis. "
        "Deployed v1 includes T165/T166 asymmetric multiplier-keyed "
        "hysteresis (de-risk fast / re-risk slow, counted over distinct "
        "signal readings). The screen therefore measures 'does the v1 "
        "signal carry sizing value' — NOT 'what my live hysteresis-v1 "
        "would have done'. Hysteresis only diverges from raw on "
        "regime-transition days and averages out over many trades, so "
        "this is the right proxy for screening; do NOT read the number "
        "as deployed-model performance."
    ),
}


def _trade_date_iso(entry_time_ms: int) -> Optional[str]:
    """Derive YYYY-MM-DD UTC from a ms-epoch entry timestamp. Returns
    None for the DEFAULT-0 case so callers can exclude cleanly."""
    if not entry_time_ms or entry_time_ms <= 0:
        return None
    return datetime.fromtimestamp(entry_time_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


async def replay_v1_counterfactual(
    account_id: int = 1,
    from_ms: int = 0,
    to_ms: int = 9_999_999_999_000,
) -> Dict[str, Any]:
    """Replay the live v1 rule set across past trades in the window.

    Returns:
      {
        "framing": {... screening + linear-scaling caveat ...},
        "trades": [per-trade dicts],
        "summary": {
          "n_trades_total", "actual_total", "x1_total", "v1_total",
          "v1_minus_actual", "v1_minus_x1",
          "by_mode": {"full": {...}, "macro_only": {...}},
          "excluded": {"no_entry_ms", "no_signal_coverage",
                       "pollution_shape", "invalid_actual_mult"},
        },
      }
    """
    # ── Fetch trades: LEFT JOIN preserves pre-T157 closed_positions ──────
    # T168 pollution guard at READ time too (defense-in-depth even if
    # write-time guard fails on a non-canonical path). actual_applied_mult
    # falls back to 1.0 when the regime row is missing or invalid (NULL
    # or <= 0) — captures pre-T157, toggle-OFF, and stale-fallback in one
    # rule.
    trades_raw: List[Dict[str, Any]] = []
    excluded_pollution = 0
    async with db._conn.execute(
        """
        SELECT
            cp.account_id,
            cp.calc_id,
            cp.symbol,
            cp.entry_time_ms,
            cp.exit_time_ms,
            cp.net_pnl,
            cp.entry_price,
            cp.exit_price,
            cp.quantity,
            COALESCE(NULLIF(pt.regime_multiplier, 0), 1.0)  AS actual_applied_mult,
            pt.regime_label,
            pt.regime_mode,
            pt.apply_regime_multiplier,
            pt.regime_stale
        FROM closed_positions cp
        LEFT JOIN pre_trade_log pt
          ON pt.calc_id = cp.calc_id
        WHERE cp.account_id = ?
          AND cp.exit_time_ms BETWEEN ? AND ?
        ORDER BY cp.entry_time_ms ASC, cp.exit_time_ms ASC
        """,
        (account_id, from_ms, to_ms),
    ) as cur:
        for r in await cur.fetchall():
            entry_p = float(r[6] or 0)
            qty = float(r[8] or 0)
            exit_p = float(r[7] or 0)
            if entry_p <= 0 and qty > 0 and exit_p > 0:
                excluded_pollution += 1
                continue
            trades_raw.append({
                "account_id":          r[0],
                "calc_id":             r[1],
                "symbol":              r[2],
                "entry_time_ms":       int(r[3] or 0),
                "exit_time_ms":        int(r[4] or 0),
                "actual_pnl":          float(r[5] or 0),
                "actual_applied_mult": float(r[9]),
                "live_label":          r[10],
                "live_mode":           r[11],
                "apply_flag":          r[12],
                "regime_stale":        r[13],
            })

    if not trades_raw:
        return {
            "framing": SCREENING_FRAMING,
            "trades": [],
            "summary": _empty_summary(excluded_pollution=excluded_pollution),
        }

    # ── Fetch signal series ONCE for the window ──────────────────────────
    # Span is [earliest trade − 60d, latest trade]. The 60-day lead-in
    # absorbs any signal-publication lag (yfinance / FRED daily publish
    # close-of-day; using strictly trade_date can miss a same-day update).
    # _lookup_nearest does "most-recent at-or-before target_date" so the
    # extra lead-in just enlarges the search space without changing
    # semantics — the "no signal coverage" case is when the FIRST signal
    # date is AFTER trade_date.
    valid_entry_ms = [t["entry_time_ms"] for t in trades_raw if t["entry_time_ms"] > 0]
    if not valid_entry_ms:
        # Every fetched trade has entry_time_ms=0; per-trade loop below
        # will count them all under excluded.no_entry_ms. Skip the
        # signal fetch — there's nothing to look up against.
        signal_data: Dict[str, list] = {}
    else:
        earliest_ms = min(valid_entry_ms)
        latest_ms   = max(t["exit_time_ms"] for t in trades_raw)
        from_iso = datetime.fromtimestamp((earliest_ms / 1000) - 60 * 86400, tz=timezone.utc).strftime("%Y-%m-%d")
        to_iso   = datetime.fromtimestamp(latest_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        signal_data = await db.get_regime_signals(ALL_SIGNALS, from_iso, to_iso)

    # ── Per-trade replay ─────────────────────────────────────────────────
    out_trades: List[Dict[str, Any]] = []
    n_excluded_no_entry = 0
    n_excluded_no_coverage = 0
    n_excluded_invalid_mult = 0

    for t in trades_raw:
        trade_date = _trade_date_iso(t["entry_time_ms"])
        if trade_date is None:
            n_excluded_no_entry += 1
            continue

        actual_mult = t["actual_applied_mult"]
        if actual_mult <= 0:
            # Defensive — the COALESCE/NULLIF should prevent this but
            # belt-and-suspenders.
            n_excluded_invalid_mult += 1
            continue

        signals: Dict[str, float] = {}
        for sig_name, series in signal_data.items():
            val = _lookup_nearest(series, trade_date)
            if val is not None:
                signals[sig_name] = val

        # No signal coverage at all → can't classify even macro_only.
        # Even one macro signal (vix/us10y/hy) is enough for the JSON
        # rule set to produce something other than the default neutral.
        # Zero signals means trade pre-dates ALL backfill; replay
        # would just return "neutral" by default rule (multiplier 1.0)
        # which is mathematically a no-op vs actual under
        # actual_applied_mult=1.0. Exclude these so the screening
        # output doesn't pad with no-information rows.
        if not signals:
            n_excluded_no_coverage += 1
            continue

        has_crypto = "agg_oi_change" in signals or "avg_funding" in signals
        cf_mode = "full" if has_crypto else "macro_only"

        v1_label = classify_regime(signals, mode=cf_mode)
        v1_mult = config.REGIME_MULTIPLIERS.get(v1_label, 1.0)

        x1_pnl = t["actual_pnl"] / actual_mult
        v1_pnl = x1_pnl * v1_mult

        out_trades.append({
            "calc_id":             t["calc_id"],
            "symbol":              t["symbol"],
            "entry_time_ms":       t["entry_time_ms"],
            "exit_time_ms":        t["exit_time_ms"],
            "trade_date":          trade_date,
            "actual_pnl":          t["actual_pnl"],
            "actual_applied_mult": actual_mult,
            "x1_pnl":              x1_pnl,
            "v1_label":            v1_label,
            "v1_multiplier":       v1_mult,
            "v1_pnl":              v1_pnl,
            "v1_mode":             cf_mode,
            "delta_v1_vs_actual":  v1_pnl - t["actual_pnl"],
            "delta_v1_vs_x1":      v1_pnl - x1_pnl,
            # Live-engine fields preserved for cross-checking (NULL on
            # pre-T157 rows; populated post-T157).
            "live_label":          t["live_label"],
            "live_mode":           t["live_mode"],
        })

    summary = _build_summary(
        out_trades,
        excluded={
            "no_entry_ms":         n_excluded_no_entry,
            "no_signal_coverage":  n_excluded_no_coverage,
            "pollution_shape":     excluded_pollution,
            "invalid_actual_mult": n_excluded_invalid_mult,
        },
    )

    return {
        "framing": SCREENING_FRAMING,
        "trades": out_trades,
        "summary": summary,
    }


def _empty_summary(excluded_pollution: int = 0) -> Dict[str, Any]:
    return {
        "n_trades_total":      0,
        "actual_total":        0.0,
        "x1_total":            0.0,
        "v1_total":            0.0,
        "v1_minus_actual":     0.0,
        "v1_minus_x1":         0.0,
        "by_mode": {
            "full":       {"n": 0, "actual": 0.0, "x1": 0.0, "v1": 0.0,
                           "v1_minus_actual": 0.0, "v1_minus_x1": 0.0},
            "macro_only": {"n": 0, "actual": 0.0, "x1": 0.0, "v1": 0.0,
                           "v1_minus_actual": 0.0, "v1_minus_x1": 0.0},
        },
        "excluded": {
            "no_entry_ms":         0,
            "no_signal_coverage":  0,
            "pollution_shape":     excluded_pollution,
            "invalid_actual_mult": 0,
        },
    }


def _build_summary(trades: List[Dict[str, Any]], excluded: Dict[str, int]) -> Dict[str, Any]:
    by_mode: Dict[str, Dict[str, float]] = {
        "full":       {"n": 0, "actual": 0.0, "x1": 0.0, "v1": 0.0,
                       "v1_minus_actual": 0.0, "v1_minus_x1": 0.0},
        "macro_only": {"n": 0, "actual": 0.0, "x1": 0.0, "v1": 0.0,
                       "v1_minus_actual": 0.0, "v1_minus_x1": 0.0},
    }
    actual_total = x1_total = v1_total = 0.0
    for t in trades:
        bucket = by_mode[t["v1_mode"]]
        bucket["n"] += 1
        bucket["actual"]          += t["actual_pnl"]
        bucket["x1"]              += t["x1_pnl"]
        bucket["v1"]              += t["v1_pnl"]
        bucket["v1_minus_actual"] += t["delta_v1_vs_actual"]
        bucket["v1_minus_x1"]     += t["delta_v1_vs_x1"]
        actual_total += t["actual_pnl"]
        x1_total     += t["x1_pnl"]
        v1_total     += t["v1_pnl"]
    return {
        "n_trades_total":  len(trades),
        "actual_total":    actual_total,
        "x1_total":        x1_total,
        "v1_total":        v1_total,
        "v1_minus_actual": v1_total - actual_total,
        "v1_minus_x1":     v1_total - x1_total,
        "by_mode":         by_mode,
        "excluded":        excluded,
    }
