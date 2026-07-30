"""
Task 149 regression tests — FE-MED-033 click-to-copy on calculator
Setup Summary outputs (Phase C prep).

Source motivation: user workflow needs calculator values copyable
into QT order entry. Pre-T149, each Setup Summary input was readonly
with `onclick="this.select()"` — user had to select-then-Ctrl+C.
Worse: the displayed values use `toLocaleString('en-US')` which
inserts thousand separators (`60,000.00`); QT order entry rejects
those.

Fix:
  - `data-copy-source` attr on each input maps to a key in
    `#calc-data` (raw float string, no formatting).
  - `copyField(el)` reads the raw, writes to clipboard via
    `navigator.clipboard.writeText()`, flashes green border for 1s.
  - LOT button hidden on non-commodity tickers (lot is a dead alias
    for contracts on crypto — observed at line 666 pre-T149,
    `else val=(commodity&&contracts>0)?fmtP(contracts):'—';`).

Tests are source-pin + render-pin only — clipboard behavior requires
a JS test harness (Playwright / jsdom) which doesn't exist in this
suite. The copyField function logic is fully visible in source so
source-pinning the key invariants gives strong fix coverage.

Run: pytest tests/test_task149_click_to_copy.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import jinja2
import pytest


def _read_calculator() -> str:
    return Path("templates/calculator.html").read_text(encoding="utf-8")


def _make_env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=jinja2.select_autoescape(["html"]),
    )


# ── Setup Summary input markup: data-copy-source + click handler ────────────

class TestSetupSummaryInputsHaveCopyAttrs:
    """Each Setup Summary input must declare data-copy-source +
    onclick=copyField(this) so the click-to-copy works."""

    INPUTS = {
        "ss-ticker": "ticker",
        "ss-entry": "entry",
        "ss-tp": "tp",
        "ss-sl": "sl",
        "ss-size": "size",
    }






# ── copyField JS function source-pins ───────────────────────────────────────



# ── LOT button hidden on non-commodity tickers ──────────────────────────────



# ── Compile-render: calculator template still renders cleanly ───────────────



# ── FE-MED-033 anchor present ───────────────────────────────────────────────

