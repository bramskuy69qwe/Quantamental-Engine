"""
Task 135 regression tests — FE-MED-018 Analytics page-level period
selector disabled on sub-tabs that ignore the `period` query param.

Investigation outcome (rejected the audit's "precedence ambiguity"
framing): the page-level period selector was a DEAD CONTROL on Equity
Curve / Calendar / Funding / Beta sub-tabs — those handlers in
api/routes_analytics.py don't read the `period` query param. Operator
clicking Month / Week / 30D etc. on those tabs caused no change.

Model D fix (rejected A/B/C from task spec which assumed actual
conflict): dim + disable the period bar when the active sub-tab
doesn't consume `period`. Reveals orthogonality without inventing
precedence semantics. Doesn't break sub-tabs that DO consume period.

Sub-tabs that consume period (verified empirically in routes_analytics.py):
  overview, pairs, excursions, rmultiples, risk
Sub-tabs that ignore period:
  equity, calendar, live (funding), beta

Source-pin tests (the dim/disable is JS-driven; can't render-test JS
without a browser).

Run: pytest tests/test_task135_analytics_period_bar.py -v
"""
from __future__ import annotations

import re
from pathlib import Path

import jinja2
import pytest


def _make_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    return env


def _read_analytics() -> str:
    return Path("templates/analytics.html").read_text(encoding="utf-8")


# ── Period bar wrapper id ───────────────────────────────────────────────────



# ── _periodTabs registry ────────────────────────────────────────────────────



# ── Disable helper logic ────────────────────────────────────────────────────



# ── switchTab + init hooks ──────────────────────────────────────────────────



# ── Routes-handler invariant: registry matches actual params ────────────────

class TestRegistryMatchesHandlerSignatures:
    """The _periodTabs registry must match which handlers actually
    accept a `period` parameter. If a handler is changed to take/drop
    `period`, this test catches the drift."""

    def _handler_sigs(self) -> dict:
        """Map sub-tab id → True if the handler signature includes
        `period:` as a parameter."""
        src = Path("api/routes_analytics.py").read_text(encoding="utf-8")
        # Map endpoint path suffix → function name + signature window
        mapping = {
            "overview":   "frag_analytics_overview",
            "equity":     "frag_analytics_equity",
            "calendar":   "frag_analytics_calendar",
            "pairs":      "frag_analytics_pairs",
            "excursions": "frag_analytics_excursions",
            "rmultiples": "frag_analytics_r_multiples",
            "risk":       "frag_analytics_var",
            "live":       "frag_analytics_funding",
            "beta":       "frag_analytics_beta",
        }
        out = {}
        for tid, fn_name in mapping.items():
            idx = src.find(f"async def {fn_name}(")
            assert idx > 0, f"handler {fn_name} not found in routes_analytics.py"
            # Signature ends at the closing paren of the def line
            end = src.find("):", idx)
            sig = src[idx:end]
            out[tid] = "period:" in sig.replace(" ", "")
        return out



# ── Anti-regression ─────────────────────────────────────────────────────────



# ── Compile pins (MED-047) ──────────────────────────────────────────────────

