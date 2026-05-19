"""
Centralized number-formatting helpers.

Task 152 (FE-MED-021 + FE-LOW-022 family):
- `format_price(value)`: magnitude-adaptive precision for prices.
    >= 1000  → 2 decimals
    >= 1     → 4 decimals
    < 1      → 6 decimals
  Mirrors the JS `fmtP` in templates/calculator.html so server-rendered
  and client-rendered price strings agree.
- `format_size(value)`: fixed 4-decimal precision for contract sizes /
  lot counts. Engine convention is "size at 4 decimals" — matches Binance
  USDM-M contract precision for the visible-trade range.

Both retain thousand separators (default) for display readability.
Pass `separator=False` for copy-paste contexts (T149 click-to-copy
already routes raw values via `data-*` attrs, so this flag is mostly
defensive — exposed for future paste-target helpers).

Non-finite (NaN / inf) or unparseable inputs collapse to "—" rather than
raising. None collapses to "—" too — calling templates use the result
directly without an `is none` check.
"""
from __future__ import annotations

import math
from typing import Any

__all__ = ["format_price", "format_size"]


def _to_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return f


def format_price(value: Any, *, decimals: int | None = None, separator: bool = True) -> str:
    """
    Magnitude-adaptive price formatter.

    Default rule (mirrors JS fmtP):
      abs(value) >= 1000 → 2 decimals
      abs(value) >= 1    → 4 decimals
      else               → 6 decimals

    Override with `decimals=N`. Suppress thousand separators with
    `separator=False`.
    """
    f = _to_float_or_none(value)
    if f is None:
        return "—"
    if decimals is None:
        a = abs(f)
        if a >= 1000:
            d = 2
        elif a >= 1:
            d = 4
        else:
            d = 6
    else:
        d = decimals
    sep = "," if separator else ""
    return f"{f:{sep}.{d}f}"


def format_size(value: Any, *, decimals: int = 4, separator: bool = True) -> str:
    """
    Fixed-precision size / contracts formatter. Defaults to 4 decimals
    (engine-wide convention for contract sizes — matches Binance
    USDM-M lot precision in the visible-trade range).
    """
    f = _to_float_or_none(value)
    if f is None:
        return "—"
    sep = "," if separator else ""
    return f"{f:{sep}.{decimals}f}"
