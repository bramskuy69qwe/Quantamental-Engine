"""
Regime classification subsystem (Task 163 — regime build 1a).

Provides a stable `classify(signals) -> RegimeResult` seam behind which
implementations sit. Stage A: JSON rule interpreter (the migrated v1
hand-rolled rules). Stage B (future): ML implementation behind the same
interface.

Caller injects ``mode`` ("full" | "macro_only") into the signals dict
before calling classify. ``mode`` is the synthesized signal that
disambiguates the original cascade's full-vs-macro branches without
introducing OR / nesting in the JSON grammar.
"""
from core.regime.interface import RegimeResult, Classifier
from core.regime.json_interpreter import JsonRuleClassifier
from core.regime.hysteresis import HysteresisWrapper

__all__ = [
    "RegimeResult",
    "Classifier",
    "JsonRuleClassifier",
    "HysteresisWrapper",
]
