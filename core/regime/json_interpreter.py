"""
Stage A — JSON rule interpreter for regime classification.

Task 163 (regime build 1a). Minimal grammar:

  rule_set = {
      "rules": [
          {
              "regime":     "<label>",
              "when":       { "<signal_name>": "<op> <value>", ... },   # AND
              "multiplier": <float>,
          },
          ...
      ],
      "default": { "regime": "<label>", "multiplier": <float> },        # optional
  }

Operators: ``> < >= <= ==``. ``==`` accepts numeric or string RHS.
Conditions inside one rule's ``when`` block are AND-ed; rule list
order is first-match-wins. A signal missing from the input dict (or
present with ``None``) causes every numeric condition referencing
it to FAIL — the rule does not match. ``==`` with a string RHS only
matches when the input value is the same string (None still fails).

NO OR / nesting yet. Mode-conditional branches in v1 rules are
encoded via the caller-injected ``mode`` signal (``"== full"`` /
``"== macro_only"``).

If no rule matches, the ``default`` block fires (or neutral / 1.0 if
the rule set has no default).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.regime.interface import RegimeResult

log = logging.getLogger("regime.json_interpreter")


_NUMERIC_OPS: Dict[str, Callable[[float, float], bool]] = {
    ">":  lambda a, b: a > b,
    "<":  lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
}


@dataclass(frozen=True)
class _Condition:
    """Compiled single-signal condition (signal, op, rhs)."""
    signal: str
    op: str
    rhs: Any              # float for numeric, str for ==-string
    rhs_is_string: bool   # True → string equality; False → numeric op


def _parse_condition_str(raw: str) -> Tuple[str, Any, bool]:
    """Parse a single condition string like ``"> 30"`` or ``"== full"``.

    Returns (op, rhs, rhs_is_string). Raises ValueError on bad input —
    rule loading fails fast rather than producing silently-wrong matches.
    """
    s = raw.strip()
    # Order matters: check 2-char ops before 1-char so ">=" doesn't
    # match ">" first.
    for op in (">=", "<=", "==", ">", "<"):
        if s.startswith(op):
            rhs_str = s[len(op):].strip()
            if not rhs_str:
                raise ValueError(f"empty RHS in condition: {raw!r}")
            try:
                rhs = float(rhs_str)
                return op, rhs, False
            except ValueError:
                # Non-numeric — only valid for `==`. Treat as string.
                if op != "==":
                    raise ValueError(
                        f"non-numeric RHS {rhs_str!r} only allowed with "
                        f"`==`; got op {op!r} in condition {raw!r}"
                    )
                return op, rhs_str, True
    raise ValueError(
        f"condition {raw!r} missing operator (expected one of >= <= == > <)"
    )


@dataclass
class _CompiledRule:
    regime: str
    multiplier: float
    conditions: List[_Condition]


def _compile_rule(rule: Dict[str, Any], idx: int) -> _CompiledRule:
    if not isinstance(rule, dict):
        raise ValueError(f"rule {idx}: must be a dict, got {type(rule).__name__}")
    if "regime" not in rule:
        raise ValueError(f"rule {idx}: missing 'regime'")
    if "when" not in rule:
        raise ValueError(f"rule {idx}: missing 'when'")
    when = rule["when"]
    if not isinstance(when, dict):
        raise ValueError(f"rule {idx}: 'when' must be a dict")
    conditions: List[_Condition] = []
    for sig, cond_str in when.items():
        if not isinstance(cond_str, str):
            raise ValueError(
                f"rule {idx}: condition value for {sig!r} must be a "
                f"string like '> 30', got {type(cond_str).__name__}"
            )
        op, rhs, is_str = _parse_condition_str(cond_str)
        conditions.append(_Condition(signal=sig, op=op, rhs=rhs, rhs_is_string=is_str))
    return _CompiledRule(
        regime=str(rule["regime"]),
        multiplier=float(rule.get("multiplier", 1.0)),
        conditions=conditions,
    )


def _evaluate(cond: _Condition, signals: Dict[str, Any]) -> bool:
    """A single condition. Missing signal OR None value → False (rule
    won't match). String `==` requires exact string equality; numeric
    ops require a numeric-coercible value."""
    if cond.signal not in signals:
        return False
    val = signals[cond.signal]
    if val is None:
        return False
    if cond.rhs_is_string:
        # String equality
        return str(val) == cond.rhs
    # Numeric path
    try:
        v = float(val)
    except (TypeError, ValueError):
        return False
    return _NUMERIC_OPS[cond.op](v, cond.rhs)


class JsonRuleClassifier:
    """Stateless first-match-wins rule interpreter."""

    def __init__(self, rule_set: Dict[str, Any]):
        if "rules" not in rule_set:
            raise ValueError("rule set missing 'rules' list")
        rules = rule_set["rules"]
        if not isinstance(rules, list):
            raise ValueError("rule set 'rules' must be a list")
        self._compiled: List[_CompiledRule] = [
            _compile_rule(r, i) for i, r in enumerate(rules)
        ]
        # Default fallback when no rule matches. Convention: neutral / 1.0.
        d = rule_set.get("default", {})
        self._default = RegimeResult(
            label=str(d.get("regime", "neutral")),
            multiplier=float(d.get("multiplier", 1.0)),
        )

    @classmethod
    def from_file(cls, path: Path | str) -> "JsonRuleClassifier":
        with open(path, encoding="utf-8") as f:
            return cls(json.load(f))

    def classify(self, signals: Dict[str, Any]) -> RegimeResult:
        for rule in self._compiled:
            if all(_evaluate(c, signals) for c in rule.conditions):
                return RegimeResult(label=rule.regime, multiplier=rule.multiplier)
        return self._default
