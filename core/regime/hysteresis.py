"""
Temporal hysteresis wrapper around any Classifier.

Task 163 (regime build 1a) — addresses MED-029. Lives at the wrapper
layer, NOT inside the JSON interpreter. Reason:

  - The interpreter is pure / stateless / deterministic; test in
    isolation, no caching surprises.
  - Hysteresis is a state-machine concern, not a rule-shape concern.
  - A future Stage B (ML) classifier behind the same Classifier
    Protocol gets the same hysteresis for free.

Mechanism — confirmation-count: hold the current label until the same
DIFFERENT label appears N consecutive calls. A single border-crossing
reading (VIX 24.99 → 25.01 → 24.99) does NOT flip the regime; it
takes N≥2 confirmations to commit.

State per instance: (current_result, pending_label, pending_count).
First call seeds current; subsequent calls either reinforce or count
toward a pending flip.

Task 165 (regime build 1b) — asymmetric, multiplier-direction-keyed
confirmations. Production wants de-risking to confirm fast (protect
capital under a worsening regime) and re-risking to confirm slow
(don't lift exposure on a single benign tick). The direction is
keyed on the PENDING result's multiplier vs the CURRENT result's
multiplier:
  - pending.multiplier <  current.multiplier  →  DE-RISK (N_derisk)
  - pending.multiplier >  current.multiplier  →  RE-RISK (N_rerisk)
  - pending.multiplier == current.multiplier  →  immediate flip
    (no size change; label-only flip carries no risk asymmetry)

Multiplier-keyed (not label-keyed) makes this robust to new regimes:
adding a "risk_off_severe" at 0.5× automatically gets the de-risk
fast path without rule-set edits. Equal-multiplier label changes
(e.g. risk_on_choppy ↔ neutral, both 1.0×) bypass hysteresis
entirely since there's no sizing delta to suppress.

Task 166 — reading-id mode. T165 counted confirmations per call to
step(); compute_current_regime fires every 10 min but the underlying
signals are daily (VIX/FRED) / 8h (funding), so within a day every
tick saw identical values and re-risk's N=2 collapsed to ~20 min of
holding before a single improved daily reading "earned its way back
up". MED-029's day-to-day flap suppression also failed because each
day produced many more than N ticks. T166 changes the COUNTING UNIT:

  step(raw, reading_id=X) — pending advances only on calls where
  reading_id changes from the last accepted call. Intra-reading
  re-ticks return current unchanged without touching state.

reading_id is whatever the caller can name the "this is one piece of
input data" by — typically the latest signal date (compute_current_
regime uses `recent_db["date"]` for the DB-backfilled path and the
max series[-1]["date"] across all signals for the live path).

Back-compat: step(raw) without reading_id falls through to the
T165 behaviour (every call counts). classify(signals) — also
T165-compat (single source-data → single call → one count).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from core.regime.interface import Classifier, RegimeResult


class HysteresisWrapper:
    """Suppress single-tick flaps near threshold boundaries.

    confirmations         : symmetric N >= 1. Applied in both directions
                            when neither asymmetric arg is given.
                            N=1 disables hysteresis (immediate flip).
                            Backwards-compat with the T163 single-N API.
    confirmations_derisk  : N for de-risk flips (pending mult < current).
                            Defaults to `confirmations` if not given.
    confirmations_rerisk  : N for re-risk flips (pending mult > current).
                            Defaults to `confirmations` if not given.

    Equal-multiplier label changes always flip immediately (no sizing
    delta to suppress; the label distinction matters for analytics
    but not for capital protection).
    """

    def __init__(
        self,
        classifier: Classifier,
        confirmations: int = 2,
        *,
        confirmations_derisk: Optional[int] = None,
        confirmations_rerisk: Optional[int] = None,
    ):
        if confirmations < 1:
            raise ValueError(f"confirmations must be >= 1, got {confirmations}")
        n_derisk = confirmations_derisk if confirmations_derisk is not None else confirmations
        n_rerisk = confirmations_rerisk if confirmations_rerisk is not None else confirmations
        if n_derisk < 1:
            raise ValueError(f"confirmations_derisk must be >= 1, got {n_derisk}")
        if n_rerisk < 1:
            raise ValueError(f"confirmations_rerisk must be >= 1, got {n_rerisk}")
        self._classifier = classifier
        self._n_derisk = n_derisk
        self._n_rerisk = n_rerisk
        self._current: Optional[RegimeResult] = None
        self._pending_label: Optional[str] = None
        self._pending_count: int = 0
        # Task 166: gate state-machine advancement on the caller-supplied
        # reading_id changing. None until first reading-id call; once
        # set, only calls with a DIFFERENT reading_id mutate state.
        self._last_reading_id: Any = None

    @property
    def current(self) -> Optional[RegimeResult]:
        """Last committed result; None before the first classify() call."""
        return self._current

    def reset(self) -> None:
        """Clear state. Useful for tests + per-backtest-run resets."""
        self._current = None
        self._pending_label = None
        self._pending_count = 0
        self._last_reading_id = None

    def _required_confirmations(self, pending: RegimeResult, current: RegimeResult) -> int:
        """Pick N based on the multiplier-direction of the pending flip.

        Task 165: multiplier-keyed (not label-keyed) so new regimes
        inherit the right direction automatically. Equal multipliers
        return 1 → immediate flip (the caller's hot path uses this for
        the equal-mult bypass too, but resolving here keeps the rule
        in one place).
        """
        if pending.multiplier < current.multiplier:
            return self._n_derisk
        if pending.multiplier > current.multiplier:
            return self._n_rerisk
        return 1

    def classify(self, signals: Dict[str, Any]) -> RegimeResult:
        """Classify via the wrapped classifier, then apply hysteresis."""
        raw = self._classifier.classify(signals)
        return self.step(raw)

    def step(self, raw: RegimeResult, reading_id: Any = None) -> RegimeResult:
        """Apply hysteresis to a pre-computed result.

        Task 165: separate entry point for callers that already have a
        RegimeResult (e.g. compute_current_regime sources its label
        from either the DB-backfilled regime_labels table or a live
        classify_regime() call, then funnels both through hysteresis).
        Uses the same state machine as classify(); the only difference
        is no inner classifier invocation.

        Task 166: optional `reading_id` switches the counting unit
        from "every call" to "every distinct source reading". When
        reading_id is supplied AND matches the last accepted call's
        reading_id, the state machine no-ops and returns the held
        current — intra-reading re-ticks must not advance confirmations.
        When reading_id differs (or is None — back-compat), the state
        machine runs as before. reading_id can be any hashable;
        compute_current_regime uses the latest signal date.
        """
        # T166 reading-id gate. None preserves T165 behaviour.
        if reading_id is not None and reading_id == self._last_reading_id:
            # Same source reading as last accepted call — no state
            # change. Return held current (or raw if first call hasn't
            # seeded current yet; the only way we hit that is if the
            # caller passes a reading_id BEFORE the wrapper sees any
            # data, which they shouldn't, but handle defensively).
            return self._current if self._current is not None else raw
        # Accept this reading as the new "last" — even if state machine
        # below results in a hold (raw differs from current but pending
        # count not yet at N), we've consumed this reading toward the
        # pending-counter, so subsequent same-id calls must no-op.
        if reading_id is not None:
            self._last_reading_id = reading_id

        if self._current is None:
            # First reading — commit immediately.
            self._current = raw
            return raw

        if raw.label == self._current.label:
            # Re-confirmation of current — reset any pending flip.
            self._pending_label = None
            self._pending_count = 0
            # Multiplier may legitimately differ across observations of
            # the same label (e.g., if a future rule set tunes the
            # multiplier dynamically). Trust the latest raw multiplier.
            self._current = raw
            return raw

        # Different label from current. Equal-multiplier shortcut
        # (Task 165): no sizing delta to protect against — flip
        # immediately, clear any pending state. The label change still
        # matters for analytics (e.g. risk_on_choppy vs neutral) but
        # the multiplier-directional hysteresis is irrelevant.
        if raw.multiplier == self._current.multiplier:
            self._current = raw
            self._pending_label = None
            self._pending_count = 0
            return raw

        # Multiplier-directional flip — accumulate against the right N.
        if raw.label == self._pending_label:
            self._pending_count += 1
        else:
            self._pending_label = raw.label
            self._pending_count = 1

        required = self._required_confirmations(raw, self._current)
        if self._pending_count >= required:
            # Flip confirmed (de-risk or re-risk).
            self._current = raw
            self._pending_label = None
            self._pending_count = 0
            return raw

        # Hold the current label. Return the held label with its
        # multiplier (NOT the raw multiplier — would emit a sized
        # decision that disagrees with the held label).
        return self._current
