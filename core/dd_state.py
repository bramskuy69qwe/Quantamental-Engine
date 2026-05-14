"""
Pure rolling-drawdown state logic.

No DB I/O, no side effects. Functions take numeric inputs and return
state strings + metrics. Integration with data_cache / account_snapshots
comes in a separate task.

Scalping preset reference (used by test fixtures):
  window=14d, warning=0.04, limit=0.08, recovery=0.50
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Callable, List, Literal, Optional, Tuple

DDState = Literal["ok", "warning", "limit"]


# ── Pure math ────────────────────────────────────────────────────────────────


def compute_rolling_drawdown(
    equity_series: List[Tuple[datetime, float]],
    current_equity: float,
    window_days: int,
    now: datetime,
) -> Tuple[float, float]:
    """Compute rolling drawdown from an equity time series.

    Args:
        equity_series: ``[(timestamp, equity), ...]`` within the window.
            Need not be pre-filtered — entries outside the window are
            skipped.
        current_equity: Live equity value.
        window_days: Rolling lookback in calendar days.
        now: Current timestamp (for window boundary).

    Returns:
        ``(drawdown_pct, peak_equity)`` where
        ``drawdown_pct = (peak - current) / peak`` (0.0 when at peak).
    """
    cutoff = now - timedelta(days=window_days)
    peak = current_equity
    for ts, eq in equity_series:
        if ts >= cutoff:
            peak = max(peak, eq)

    if peak <= 0:
        return 0.0, 0.0
    dd = (peak - current_equity) / peak
    return max(dd, 0.0), peak


def dd_state_from_drawdown(
    drawdown_pct: float,
    warning_threshold: float,
    limit_threshold: float,
) -> DDState:
    """Map a drawdown percentage to a state string.

    Pure threshold comparison — no recovery logic.
    """
    if drawdown_pct >= limit_threshold:
        return "limit"
    if drawdown_pct >= warning_threshold:
        return "warning"
    return "ok"


def dd_state_with_recovery(
    previous_state: DDState,
    drawdown_pct: float,
    episode_peak_dd: float,
    warning_threshold: float,
    limit_threshold: float,
    recovery_threshold: float,
) -> Tuple[DDState, float]:
    """Evaluate DD state with early-unblock recovery rule.

    Recovery fires when ``previous_state == "limit"`` AND the current
    drawdown has recovered within ``recovery_threshold`` of the episode
    peak drawdown::

        drawdown_pct <= episode_peak_dd * (1 - recovery_threshold)

    Example: peak DD = 0.10, recovery_threshold = 0.50
    → unblock when DD <= 0.10 * 0.50 = 0.05.

    Returns:
        ``(new_state, updated_episode_peak_dd)``

    Episode peak resets to 0.0 on transition to ``"ok"``.
    """
    # Track the worst DD in this episode
    episode_peak_dd = max(episode_peak_dd, drawdown_pct)

    # Limit is sticky — once in limit, only recovery or manual override exits.
    # Normal threshold re-evaluation does NOT apply (prevents limit→warning
    # on partial equity recovery that doesn't meet the recovery threshold).
    if previous_state == "limit" and episode_peak_dd > 0:
        recovery_level = episode_peak_dd * (1 - recovery_threshold)
        if drawdown_pct <= recovery_level:
            return "ok", 0.0  # episode ends, peak resets
        return "limit", episode_peak_dd

    # Normal threshold evaluation (for ok → warning → limit transitions)
    new_state = dd_state_from_drawdown(drawdown_pct, warning_threshold, limit_threshold)

    # Reset episode peak on transition to ok (from warning)
    if new_state == "ok":
        episode_peak_dd = 0.0

    return new_state, episode_peak_dd


# ── Stateful evaluator for harness ──────────────────────────────────────────


def derive_dd_evaluator(
    warning_threshold: float,
    limit_threshold: float,
    recovery_threshold: float,
) -> Callable[[str, float, "TestClock"], str]:
    """Create a stateful evaluator closure for the state-machine harness.

    The evaluator tracks ``_episode_peak_dd`` across calls.  Feed it
    equity values via the harness runner; it returns the new DD state.

    The equity series is accumulated internally — the evaluator records
    each (clock.now(), equity) pair and recomputes rolling drawdown on
    every tick.  ``window_days`` is effectively unbounded (all history
    within the fixture).

    Args:
        warning_threshold: Absolute DD ratio for warning.
        limit_threshold: Absolute DD ratio for limit.
        recovery_threshold: Fraction of episode-peak DD required for recovery.

    Returns:
        Callable matching the harness ``Evaluator`` signature:
        ``(current_state, equity, clock) -> new_state``.
    """
    _episode_peak_dd: float = 0.0
    _equity_history: List[Tuple[datetime, float]] = []

    def evaluator(current_state: str, equity: float, clock) -> str:
        nonlocal _episode_peak_dd, _equity_history

        now = clock.now()
        _equity_history.append((now, equity))

        dd_pct, _peak = compute_rolling_drawdown(
            _equity_history, equity, window_days=9999, now=now,
        )

        new_state, _episode_peak_dd = dd_state_with_recovery(
            current_state, dd_pct, _episode_peak_dd,
            warning_threshold, limit_threshold, recovery_threshold,
        )
        return new_state

    return evaluator
