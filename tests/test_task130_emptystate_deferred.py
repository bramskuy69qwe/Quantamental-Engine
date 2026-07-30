"""
Task 130 regression tests — close out the Task 124-deferred EmptyState
migrations.

Two sites migrated:
  - equity_ohlc.html (32px → padding="loose")
  - exchange_table.html (16px → default padding="default", with
    left→center alignment shift to converge with primitive convention)

Both rely on the Task 129 EmptyState API extension (padding param).

Decision recorded: NO "medium" (16px) preset added — exchange_table's
16px was a single-consumer outlier; per Bundle A defer-discipline,
single-consumer API extensions are over-engineering. Wait for a second
consumer.

Run: pytest tests/test_task130_emptystate_deferred.py -v
"""
from __future__ import annotations


import jinja2
import pytest


def _make_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    env.globals["fmt"] = lambda v, n=2: (
        f"{v:.{n}f}" if isinstance(v, (int, float)) else str(v)
    )
    env.globals["ms_to_local"] = lambda ms: "2026-05-19 10:00:00"
    return env


# ── equity_ohlc.html migration (padding="loose") ────────────────────────────


# ── exchange_table.html migration (default padding + alignment shift) ───────


# ── Anti-regression: EmptyState API extension intact ────────────────────────

class TestEmptyStateApiIntact:
    """The Task 129 API extension (padding param) must still work — no
    drift from these migrations."""

    def test_padding_default_no_modifier(self):
        env = _make_env()
        src = (
            '{% from "primitives/empty_state.html" import empty_state %}'
            '{{ empty_state("test", padding="default") }}'
        )
        html = env.from_string(src).render()
        assert "es-tight" not in html
        assert "es-loose" not in html

    def test_padding_tight_emits_modifier(self):
        env = _make_env()
        src = (
            '{% from "primitives/empty_state.html" import empty_state %}'
            '{{ empty_state("test", padding="tight") }}'
        )
        html = env.from_string(src).render()
        assert "es-tight" in html

    def test_padding_loose_emits_modifier(self):
        env = _make_env()
        src = (
            '{% from "primitives/empty_state.html" import empty_state %}'
            '{{ empty_state("test", padding="loose") }}'
        )
        html = env.from_string(src).render()
        assert "es-loose" in html


# ── Compile pins (MED-047) ──────────────────────────────────────────────────

