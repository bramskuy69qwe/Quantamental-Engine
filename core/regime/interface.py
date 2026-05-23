"""
RegimeResult + Classifier protocol — the stable seam for regime
classification.

Task 163 (regime build 1a). Per build-order:
  - Stage A: JSON rule interpreter (this task).
  - Stage B (later): ML model behind the same Classifier protocol.

`signals` is per-model — the caller declares what to feed in. The
interpreter doesn't enforce a fixed signal vocabulary. ``mode`` is
the convention-name for the macro/full signal-set indicator the
existing engine has used since the original hand-rolled cascade.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol


@dataclass(frozen=True)
class RegimeResult:
    """Output of any Classifier.

    label : the regime name (e.g. "neutral", "risk_off_panic"). Caller
            decides which labels are meaningful for its model.
    multiplier : sizing factor in [0, ∞). Default 1.0 (no size change);
            rule-set / model overrides as needed.
    """

    label: str
    multiplier: float = 1.0


class Classifier(Protocol):
    """Anything that takes a signal dict and emits a regime decision."""

    def classify(self, signals: Dict[str, Any]) -> RegimeResult:  # noqa: D401
        ...
