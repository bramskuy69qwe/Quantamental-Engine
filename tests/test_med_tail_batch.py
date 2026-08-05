"""MED-tail batch (wiring inventory M5/M7/M9/M11/M12/M13; operator go
2026-08-04 "do remaining meds").

Each class documents its fix in the commit that lands it — an unshipped
sibling must not have a class here (the dead-settings batch's
fabricated-provenance lesson). Companion file:
tests/test_dead_settings_batch.py holds the M1-M4+M8 pins.

Shipped so far (in commit order):
  M13 · the Primitives page badge said "NOT IN PRODUCTION NAV" while the
        page IS in production nav (kept there by a recorded operator
        decision — the inventory's third NOT-DEFECT). The badge now says
        what the page is (design-system reference, demo data) instead of
        where it isn't.
  M12 · CLOSED WITHOUT CODE — investigated, already resolved: the
        WorkspaceBar's workspace controls off-Dashboard have been dimmed
        + pointer-inert + captioned "· dashboard only" since P0
        (git-verified, 1221b16), which IS the honest-disable contract
        (FE-MED-018: a dead control must look dead). Making them WORK
        off-Dashboard is DEFERRED by the ratified plan's own defer list
        — docs/design/v3.0_ui_rebuild_plan.md §7: "gates Save/Load to
        the Dashboard; ship one persisted default layout per page,
        defer per-page named presets" (audit-corrected citation: the
        UI-rebuild close's decision #3 defers ACCOUNT-namespacing, a
        different axis). The pins below keep the honest-disable from
        silently regressing; the ⊞ Pane / ⤢ Pop stubs are the LOW
        tier's, not M12's.
  M5  · OrderManager.check_dd_gate_for_order REMOVED — added by v2.4
        Priority 1c for an engine-side order-placement lane and never
        called by prod code ever (git -S: exactly two CODE commits — its
        introduction 5391042 and its tests b63e06b; the third -S hit is
        the inventory's own doc filing e6c7bde — audit-corrected count;
        no caller was ever added or removed, verified on every branch
        incl. the quantower archive). The premise died with the v2.6
        Quantower removal: the observe-only engine has no order to gate.
        core/dd_gate stays THE gate (calculator lane + /api/state).

Run: pytest tests/test_med_tail_batch.py -v
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tests._srcpin import code as _code  # noqa: E402

_ROOT = Path(__file__).parent.parent


def _src(name: str) -> str:
    return _code((_ROOT / "frontend" / "src" / name).read_text(encoding="utf-8"))


# ── M13: the Primitives badge stops denying the nav ─────────────────────────


class TestM13PrimitivesBadgeTruthful:
    def test_the_badge_no_longer_denies_the_nav(self):
        """Two-sided: NAV_ITEMS asserts Primitives IS in production nav
        (parsed, not assumed), so no executing string in app-shell may
        claim otherwise."""
        nav = _src("nav-and-data.jsx")
        m = re.search(r"const NAV_ITEMS = \[([^\]]*)\];", nav)
        assert m, "NAV_ITEMS literal not found"
        items = [s.strip().strip("'\"") for s in m.group(1).split(",")]
        assert "Primitives" in items, (
            "Primitives left production nav — if that was a deliberate "
            "reversal of the recorded keep-the-DEV-chip decision, the badge "
            "copy AND this pin change together"
        )
        assert "NOT IN PRODUCTION NAV" not in _src("app-shell.jsx")

    def test_the_badge_says_what_the_page_is(self):
        assert "DEV · DESIGN-SYSTEM REFERENCE · DEMO DATA" in _src("app-shell.jsx")


# ── M12: WorkspaceBar honest-disable, pinned (closed without code) ──────────


class TestM12WorkspaceBarHonestlyScoped:
    """The M12 filing ("WorkspaceBar is inert off the Dashboard") describes
    a state that is deliberate and already honestly labeled — see the
    module docstring. These pins hold the three legs of the honest
    disable together: the guard, the caption, and the single truthful
    interactive grant."""

    def test_controls_are_guarded_captioned_and_dashboard_granted(self):
        nav = _src("nav-and-data.jsx")
        assert nav.count("pointerEvents: interactive ? 'auto' : 'none'") == 2, (
            "the preset row + action row both carry the pointer guard"
        )
        assert ">· dashboard only</span>" in nav, (
            "the caption is the operator-visible half of the honest "
            "disable — dimming alone does not say WHY"
        )
        assert "interactive={page === 'Dashboard'}" in nav


# ── M5: the order-placement dd gate is gone; the real gate stays ────────────


class TestM5OrderGateRemoved:
    def test_the_dead_method_is_gone(self):
        """Executed + AST: no OrderManager attribute named
        check_dd_gate_for_order, and no call to it anywhere in executing
        prod code (api/ core/ main.py — comments excluded via AST)."""
        import ast

        from core.order_manager import OrderManager

        assert not hasattr(OrderManager, "check_dd_gate_for_order")
        hits = []
        for base in ("api", "core", "main.py"):
            p = _ROOT / base
            files = [p] if p.is_file() else sorted(p.rglob("*.py"))
            for f in files:
                tree = ast.parse(f.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if (isinstance(node, ast.Attribute)
                            and node.attr == "check_dd_gate_for_order") or (
                            isinstance(node, (ast.FunctionDef,
                                              ast.AsyncFunctionDef))
                            and node.name == "check_dd_gate_for_order"):
                        hits.append(str(f.relative_to(_ROOT)))
        assert hits == [], f"check_dd_gate_for_order reappeared: {hits}"

    def test_the_real_gate_is_still_consumed(self):
        """M5's justification must stay true: core/dd_gate remains THE
        gate — dd_gate_allows_new_entry is CALLED (AST) by the /api/state
        surface. If this dies, the removal's premise needs re-deciding,
        not re-pinning."""
        import ast

        src = (_ROOT / "api" / "routes_dashboard.py").read_text(
            encoding="utf-8")
        called = {
            node.func.attr if isinstance(node.func, ast.Attribute)
            else getattr(node.func, "id", None)
            for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.Call)
        }
        assert "dd_gate_allows_new_entry" in called
