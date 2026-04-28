"""
Rule-based macro regime classifier.

Maps macro signal values to one of five regime states:
  - risk_on_trending    (1.2x multiplier — confirmed bull, low vol, expanding leverage)
  - risk_on_choppy      (1.0x — bullish bias but volatile, elevated short-term vol)
  - neutral             (1.0x — default / insufficient signal)
  - risk_off_defensive  (0.7x — warning signs, VIX elevated or spreads widening)
  - risk_off_panic      (0.4x — crisis conditions, extreme VIX + credit stress)

Two modes:
  - "macro_only": Uses VIX, US10Y yield, HY spread, BTC dominance, BTC rvol ratio.
                  Works for deep historical backtests (5-30+ years of data).
  - "full":       Adds Binance OI change and funding rate.
                  Only works for recent data (~2-3 years).

The classifier auto-detects mode when not specified.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import config
from core.database import db
from core.state import RegimeState

log = logging.getLogger("regime_classifier")

REGIMES = [
    "risk_on_trending",
    "risk_on_choppy",
    "neutral",
    "risk_off_defensive",
    "risk_off_panic",
]

ALL_SIGNALS = [
    "vix_close", "us10y_yield", "hy_spread",
    "btc_rvol_ratio",
    "agg_oi_change", "avg_funding",
]

MACRO_ONLY_SIGNALS = [
    "vix_close", "us10y_yield", "hy_spread",
    "btc_rvol_ratio",
]


def classify_regime(
    signals: Dict[str, Optional[float]],
    mode: str = "auto",
    thresholds: Optional[Dict[str, float]] = None,
) -> str:
    """
    Classify the current macro regime from signal values.

    signals: {"vix_close": 15.2, "us10y_yield": 4.3, ...}
    mode: "full", "macro_only", or "auto" (auto-detect based on available signals)
    thresholds: override config.REGIME_THRESHOLDS if provided

    Returns one of the 5 regime labels.
    """
    t = thresholds or config.REGIME_THRESHOLDS

    vix = signals.get("vix_close")
    hy = signals.get("hy_spread")
    rvol = signals.get("btc_rvol_ratio")

    # Crypto-native signals (full mode)
    oi_change = signals.get("agg_oi_change")
    funding = signals.get("avg_funding")

    if mode == "auto":
        mode = "full" if (oi_change is not None or funding is not None) else "macro_only"

    # ── PANIC ────────────────────────────────────────────────────────────────
    # VIX spiking + credit stress OR extreme negative funding (liquidation cascade)
    if vix is not None and vix > t.get("vix_panic", 30):
        if hy is not None and hy > t.get("hy_spread_panic", 5.0):
            return "risk_off_panic"
        if mode == "full" and funding is not None and funding < t.get("funding_panic", -0.01):
            return "risk_off_panic"
        # VIX alone above panic threshold is at minimum defensive
        return "risk_off_panic" if (hy is not None and hy > t.get("hy_spread_defensive", 4.5)) else "risk_off_defensive"

    # ── DEFENSIVE ────────────────────────────────────────────────────────────
    # Elevated VIX or widening HY spreads
    if vix is not None and vix > t.get("vix_defensive", 25):
        return "risk_off_defensive"
    if hy is not None and hy > t.get("hy_spread_defensive", 4.5):
        return "risk_off_defensive"

    # ── HY NEUTRAL FLOOR ─────────────────────────────────────────────────────
    # Credit spreads at or above this level cap the regime at neutral —
    # below the defensive line, but still elevated enough that risk-on is unsafe.
    if hy is not None and hy >= t.get("hy_spread_neutral", 4.0):
        return "neutral"

    # Risk-on requires HY below this gate — uninfluenced if HY signal is missing.
    hy_allows_risk_on = hy is None or hy < t.get("hy_spread_risk_on", 3.5)

    # ── RISK-ON TRENDING ─────────────────────────────────────────────────────
    # Low VIX + vol compressing + (in full mode) OI expanding with positive funding
    is_low_vix = vix is not None and vix < t.get("vix_risk_on", 20)
    is_vol_compressed = rvol is not None and rvol < t.get("rvol_ratio_trending", 1.2)

    if hy_allows_risk_on:
        if mode == "full":
            is_leverage_expanding = (
                oi_change is not None and oi_change > 0
                and funding is not None and funding > 0
            )
            if is_low_vix and is_vol_compressed and is_leverage_expanding:
                return "risk_on_trending"
            if is_low_vix and is_leverage_expanding:
                return "risk_on_trending"
        else:
            # macro_only: low VIX + vol compressed is sufficient (no btc_dominance)
            if is_low_vix and is_vol_compressed:
                return "risk_on_trending"

        # ── RISK-ON CHOPPY ───────────────────────────────────────────────────
        # Moderately low VIX but short-term vol elevated (rvol > threshold)
        is_moderate_vix = vix is not None and vix < t.get("vix_choppy", 22)
        is_vol_elevated = rvol is not None and rvol > t.get("rvol_ratio_choppy", 1.3)

        if is_moderate_vix and is_vol_elevated:
            return "risk_on_choppy"

    # ── NEUTRAL ──────────────────────────────────────────────────────────────
    return "neutral"


async def classify_range(
    from_date: str,
    to_date: str,
    thresholds: Optional[Dict[str, float]] = None,
    progress_cb=None,
) -> int:
    """
    Bulk-classify a date range using stored regime_signals data.
    Writes results to regime_labels table.
    Returns count of labels written.
    """
    # When no date range specified, classify all available data
    if not from_date:
        from_date = "1970-01-01"
    if not to_date:
        to_date = datetime.utcnow().strftime("%Y-%m-%d")

    signal_data = await db.get_regime_signals(ALL_SIGNALS, from_date, to_date)

    if not signal_data:
        log.warning("No regime signals found for %s to %s", from_date, to_date)
        return 0

    # Build a date → {signal: value} lookup
    all_dates = set()
    for series in signal_data.values():
        for entry in series:
            all_dates.add(entry["date"])

    # Sort dates
    sorted_dates = sorted(d for d in all_dates if d >= from_date and d <= to_date)

    if not sorted_dates:
        return 0

    # For each date, look up signal values (use most recent available value)
    labels: List[Dict[str, Any]] = []
    total = len(sorted_dates)

    for i, date_str in enumerate(sorted_dates):
        signals: Dict[str, Optional[float]] = {}

        for sig_name, series in signal_data.items():
            val = _lookup_nearest(series, date_str)
            if val is not None:
                signals[sig_name] = val

        has_crypto = "agg_oi_change" in signals or "avg_funding" in signals
        mode = "full" if has_crypto else "macro_only"

        label = classify_regime(signals, mode=mode, thresholds=thresholds)

        labels.append({
            "date": date_str,
            "label": label,
            "mode": mode,
            "signals": {k: v for k, v in signals.items() if v is not None},
        })

        if progress_cb and i % 50 == 0:
            try:
                await progress_cb(i / total * 100, f"Classifying {date_str}")
            except Exception:
                pass

    # Write to DB
    count = await db.upsert_regime_labels(labels)
    log.info("Classified %d dates (%s to %s)", count, from_date, to_date)

    if progress_cb:
        try:
            await progress_cb(100, f"Classified {count} dates")
        except Exception:
            pass

    return count


def _lookup_nearest(series: List[Dict], target_date: str) -> Optional[float]:
    """Binary search for the closest value at or before target_date."""
    if not series:
        return None
    lo, hi, result = 0, len(series) - 1, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if series[mid]["date"] <= target_date:
            result = series[mid]["value"]
            lo = mid + 1
        else:
            hi = mid - 1
    return result


async def _compute_stability(label: str) -> Tuple[int, str]:
    """Count consecutive recent days with the same label in the DB."""
    recent = await db.get_recent_regime_labels(30)
    count = 0
    for entry in recent:          # already sorted DESC
        if entry["label"] == label:
            count += 1
        else:
            break
    if count >= 10:
        confidence = "high"
    elif count >= 5:
        confidence = "medium"
    else:
        confidence = "low"
    return count, confidence


async def compute_current_regime():
    """
    Return the current regime, preferring the most recent backfilled label.

    Priority:
      1. Most recent regime_labels entry (written by backfill with full signal data)
         — used when that entry is within the last 7 days.
      2. Live classification from regime_signals table (fallback when no recent label).

    This ensures the calculator badge always agrees with the timeline chart, both
    of which are ultimately sourced from regime_labels when a backfill has run.
    """
    # ── 1. Try the backfilled regime_labels table first ──────────────────────
    recent_db = await db.get_latest_regime_label()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")

    if recent_db and recent_db["date"] >= cutoff:
        label   = recent_db["label"]
        signals = recent_db.get("signals", {})
        mode    = recent_db.get("mode", "full")
        log.info(
            "compute_current_regime: using DB label '%s' from %s",
            label, recent_db["date"],
        )
    else:
        # ── 2. Fall back to live classification from regime_signals ──────────
        today    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        lookback = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

        signal_data = await db.get_regime_signals(ALL_SIGNALS, lookback, today)

        signals: Dict[str, Optional[float]] = {}
        for sig_name, series in signal_data.items():
            if series:
                signals[sig_name] = series[-1]["value"]

        has_crypto = "agg_oi_change" in signals or "avg_funding" in signals
        mode  = "full" if has_crypto else "macro_only"
        label = classify_regime(signals, mode=mode)

        log.info(
            "compute_current_regime: live classification → '%s' (signals: %s)",
            label, list(signals.keys()),
        )

    multiplier = config.REGIME_MULTIPLIERS.get(label, 1.0)
    stability_bars, confidence = await _compute_stability(label)

    return RegimeState(
        label=label,
        multiplier=multiplier,
        confidence=confidence,
        stability_bars=stability_bars,
        computed_at=datetime.now(timezone.utc),
        mode=mode,
        signals={k: float(v) for k, v in signals.items() if v is not None},
    )
