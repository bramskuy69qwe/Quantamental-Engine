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

  M9  · the History table's DataList tools (search/sort/filter — all ON
        by the operator's 2026-07-25 directive) refine only the LOADED
        PAGE of a server-paged set, and nothing on screen said so — the
        scope lived in a source comment. The DataList primitive gained
        tools.scope; History passes 'loaded page only' and the toolbar
        carries the caption beside the count, title-expanded ("the
        server-side controls above the table span the full set").

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


# ── M9: the page-scope of client-side table tools is SAID, not implied ──────


class TestM9PageScopeCaption:
    """History's table is server-paged; its DataList tools act on the rows
    in hand. That is the operator-ratified shape (tools LIFTED,
    2026-07-25) — the M9 defect was the SILENCE: the scope lived in a
    source comment while the operator saw a filter that 'found no
    matches' on rows sitting one page away. Both halves pinned: the
    primitive renders the caption, and the one server-paged caller
    passes it."""

    def test_the_primitive_renders_a_passed_scope(self):
        p = _src("primitives.jsx")
        # anchored on the JSX expression's OPENING BRACE — this pin's first
        # draft matched a substring that a `{false && toolsObj && …}` mutant
        # still contained (mutation-sweep finding, the recurring
        # substring-contains-mutant class)
        assert "{toolsObj && toolsObj.scope && (" in p
        assert "{false && toolsObj" not in p
        assert ">· {toolsObj.scope}</span>" in p
        # the caption's title carries a full-sentence explanation: the
        # caller-agnostic default, overridable per host via scopeTitle
        # (audit LOW: the first draft baked History's "controls above the
        # table" geography into the generic primitive)
        i = p.index("{toolsObj && toolsObj.scope && (")
        vicinity = p[i:i + 600]
        assert "toolsObj.scopeTitle" in vicinity
        assert ("Search, sort and filter here act only on the rows "
                "currently loaded.") in vicinity

    def test_history_passes_the_scope_on_its_paged_table(self):
        h = _src("pages-history.jsx")
        assert "scope: 'loaded page only'" in h
        # …with its host-specific hover sentence naming BOTH full-set
        # controls (the server filters above AND the pager below)
        assert "the pager below walks it." in h
        # …and the page-level summary strip carries the same qualifier
        # (audit LOW: the filing named the strip's silence too — a
        # page-level NET reads as period-level without it)
        assert "{ label: 'SCOPE', value: 'loaded page'" in h

    def test_no_other_paged_caller_is_silent(self):
        """Class sweep, DERIVED not enumerated: every module in
        frontend/src that renders the server-pager idiom must pass a
        tools.scope. (This pin's first draft hard-coded 4 files while the
        sibling completeness test maintains 9 DataList hosts — the
        audit-inventory-undercounts class, caught by the M9 audit. A glob
        cannot under-count.)"""
        hosts = []
        for f in sorted((_ROOT / "frontend" / "src").glob("*.jsx")):
            src = _code(f.read_text(encoding="utf-8"))
            if "page {page}/{totalPages}" in src:
                hosts.append(f.name)
                assert "scope: 'loaded page only'" in src, (
                    f"{f.name} renders a server pager without a DataList "
                    "scope caption (M9 / DESIGN.md usage rule)"
                )
        assert hosts == ["pages-history.jsx"], (
            f"server-pager hosts changed ({hosts}) — extend the M9 scope "
            "convention deliberately, don't just re-pin"
        )

    def test_the_caption_reaches_the_emitted_bundle(self):
        """Source is not what runs (the house stale-build guard — the M1
        audit filed the same gap on the bridge pin; the M9 audit filed it
        here)."""
        import json as _json

        man = _json.loads((_ROOT / "static" / "v3" / "manifest.json")
                          .read_text(encoding="utf-8"))
        bundle = (_ROOT / "static" / "v3" / man["app"]).read_text(
            encoding="utf-8")
        assert "qe-dl-scope" in bundle
        assert "loaded page only" in bundle
        tokens = (_ROOT / "static" / "v3" / man["tokens"]).read_text(
            encoding="utf-8")
        # selector + brace, not the bare name — a renamed `.qe-dl-scopex`
        # still CONTAINS the bare name (the session's recurring
        # substring-contains-mutant class, third instance)
        assert ".qe-dl-scope {" in tokens
