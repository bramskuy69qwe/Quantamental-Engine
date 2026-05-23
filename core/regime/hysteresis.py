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

NOT applied automatically — the caller (compute_current_regime, etc.)
explicitly constructs a HysteresisWrapper for paths where flapping
must be suppressed. classify_range, which replays history, may choose
to apply or skip depending on the analysis goal.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from core.regime.interface import Classifier, RegimeResult


class HysteresisWrapper:
    """Suppress single-tick flaps near threshold boundaries.

    confirmations : N >= 1. N=1 disables hysteresis (immediate flip).
                    N=2 means the new label must appear twice in a row
                    before committing (default).
    """

    def __init__(self, classifier: Classifier, confirmations: int = 2):
        if confirmations < 1:
            raise ValueError(f"confirmations must be >= 1, got {confirmations}")
        self._classifier = classifier
        self._n = confirmations
        self._current: Optional[RegimeResult] = None
        self._pending_label: Optional[str] = None
        self._pending_count: int = 0

    @property
    def current(self) -> Optional[RegimeResult]:
        """Last committed result; None before the first classify() call."""
        return self._current

    def reset(self) -> None:
        """Clear state. Useful for tests + per-backtest-run resets."""
        self._current = None
        self._pending_label = None
        self._pending_count = 0

    def classify(self, signals: Dict[str, Any]) -> RegimeResult:
        raw = self._classifier.classify(signals)

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

        # Different label from current. Accumulate confirmations toward
        # a flip.
        if raw.label == self._pending_label:
            self._pending_count += 1
        else:
            self._pending_label = raw.label
            self._pending_count = 1

        if self._pending_count >= self._n:
            # Flip confirmed.
            self._current = raw
            self._pending_label = None
            self._pending_count = 0
            return raw

        # Hold the current label. Return the held label with its
        # multiplier (NOT the raw multiplier — would emit a sized
        # decision that disagrees with the held label).
        return self._current
