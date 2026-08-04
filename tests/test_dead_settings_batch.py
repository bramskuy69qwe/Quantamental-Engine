"""Dead-settings batch (wiring inventory M1-M4 + M8; operator go 2026-08-04).

Seven knobs, one seam: settings that render as live while nothing reads
them, or are read while nothing writes them. The decision table lives in
HANDOFF.md's twelfth block; the operator approved the recommendations on
2026-08-04 and the batch ships ONE TASK PER COMMIT. This file grows with
it — each class below documents its fix in the commit that lands it, and
a class for an unshipped sibling must not exist yet (first audit of this
very file caught its docstring claiming all seven as fixed while only
M2c was in the tree — the fabricated-provenance class).

Shipped so far (in commit order):
  M2c · EXCHANGE_REFRESH_HZ — REMOVED (zero consumers ever; git-verified
        back to its v2.4 introduction — it shipped without wiring).

Run: pytest tests/test_dead_settings_batch.py -v
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

_ROOT = Path(__file__).parent.parent


# ── M2c: EXCHANGE_REFRESH_HZ is gone and stays gone ─────────────────────────


class TestM2cExchangeRefreshHzRemoved:
    def test_config_module_has_no_attribute(self):
        """Executed pin: the module object itself, not the source text."""
        import config
        assert not hasattr(config, "EXCHANGE_REFRESH_HZ"), (
            "M2c regression: EXCHANGE_REFRESH_HZ reappeared in config.py. "
            "It had ZERO consumers for its whole life (v2.4→v3.1) — wire a "
            "consumer first if the knob is ever actually needed."
        )

    def test_no_assignment_in_config_source(self):
        """AST pin, not a substring scan: the removal note in config.py
        legitimately mentions the name in a comment, so a text grep would
        either false-fail or have to be written vacuously. Harvests
        Assign AND AnnAssign targets, including tuple unpacks (the first
        draft took plain Assign/Name only and an annotated
        `EXCHANGE_REFRESH_HZ: float = 1.0` walked straight through it —
        audit finding on this pin). The hasattr sibling above remains the
        backstop for any shape that actually executes."""
        tree = ast.parse((_ROOT / "config.py").read_text(encoding="utf-8"))

        def _names(t):
            if isinstance(t, ast.Name):
                yield t.id
            elif isinstance(t, (ast.Tuple, ast.List)):
                for e in t.elts:
                    yield from _names(e)

        targets = [
            name
            for node in ast.walk(tree)
            for t in (
                node.targets if isinstance(node, ast.Assign)
                else [node.target] if isinstance(node, (ast.AnnAssign, ast.AugAssign))
                else []
            )
            for name in _names(t)
        ]
        assert "EXCHANGE_REFRESH_HZ" not in targets

    def test_no_prod_consumer_ever_appeared(self):
        """The removal's justification, kept true: no executing code under
        api/ core/ or main.py may reference the name. Known scan lanes,
        accepted deliberately (audit-reviewed): the per-line '#'-tail strip
        also truncates a '#' inside a string literal (a consumer hiding the
        name AFTER one is invisible here — contrived, and the hasattr pin
        catches anything that executes); multi-line strings are scanned as
        code (fail-LOUD lane only); templates/ static/ scripts/ are out of
        scope (root executing modules are main.py + config.py — verified)."""
        hits = []
        for base in ("api", "core", "main.py"):
            p = _ROOT / base
            files = [p] if p.is_file() else sorted(p.rglob("*.py"))
            for f in files:
                for i, line in enumerate(
                    f.read_text(encoding="utf-8").splitlines(), 1
                ):
                    code_part = line.split("#", 1)[0]
                    if "EXCHANGE_REFRESH_HZ" in code_part:
                        hits.append(f"{f.relative_to(_ROOT)}:{i}")
        assert hits == [], (
            "EXCHANGE_REFRESH_HZ is referenced in executing code — it was "
            f"removed as consumer-less (M2c). Sites: {hits}"
        )
