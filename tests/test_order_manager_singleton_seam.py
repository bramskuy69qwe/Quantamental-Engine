"""Pin the ``order_manager_singleton`` patch seam (v2.6 audit finding 2).

v2.6 Phase 1 hoisted the process-wide ``OrderManager`` out of
``platform_bridge`` into ``core.order_manager_singleton``. That trade a
LATE-bound access (``platform_bridge.order_manager`` — the bridge OBJECT was
shared, so the attribute resolved at call time and
``patch.object(platform_bridge, "_order_manager", fake)`` reached EVERY
consumer) for an EARLY-bound one: ``schedulers.py`` and ``routes_dashboard.py``
did ``from core.order_manager_singleton import order_manager`` at module scope,
binding the instance into their own namespace at import time.

The consequence is a false green, not a crash. The one documented seam —
``patch("core.order_manager_singleton.order_manager", fake)``, the form every
migrated v2.6 test uses — rebinds only the singleton module's attribute. An
early-bound consumer keeps calling the REAL OrderManager against the REAL DB
while the test passes. No test tripped it at audit time purely because all 13
migrated patches happened to target the three late-import consumers
(``ws_manager`` / ``exchange`` / ``routes_history``).

These pins guard the fix from both directions:
  1. no consumer early-binds the name (attribute + tree-wide source pin), and
  2. the documented patch target actually intercepts a REAL consumer call.

Run: pytest tests/test_order_manager_singleton_seam.py -v
"""
from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Production modules that dereference the singleton. Late-import consumers
# (ws_manager / exchange / routes_history) re-resolve per call and are safe by
# construction; the module below holds a module-level import and is the one the
# Phase-1 extraction put at risk. (Fragments slim-down 2026-07-30:
# api.routes_dashboard dropped off this list — its only singleton consumers
# were the deleted dashboard fragment handlers; the tree-wide anti-revert pin
# below still catches any re-introduction.)
_MODULE_IMPORT_CONSUMERS = ["core.schedulers"]

# Column-0 anchored: an INDENTED (function-level) from-import re-resolves on
# every call and is seam-safe, so only the module-scope form is rejected. The
# optional paren covers `import (order_manager)`; `\b` (not `$`) covers the
# aliased `import order_manager as om` form, which the attribute pin above
# would miss. NOT matched, deliberately: `import core.order_manager_singleton`
# (binds the MODULE — dereferences at call time, so it is seam-safe too).
_EARLY_BIND_RE = re.compile(
    r"^from\s+core\.order_manager_singleton\s+import\s+\(?\s*order_manager\b"
)


# ── Pin 1: no consumer early-binds the instance ─────────────────────────────

class TestNoEarlyBinding:
    @pytest.mark.parametrize("mod_name", _MODULE_IMPORT_CONSUMERS)
    def test_consumer_has_no_early_bound_name(self, mod_name):
        """A module-level `from ... import order_manager` would show up as an
        attribute ON THE CONSUMER MODULE. Its absence is the defect's exact
        negative — this is the assertion that fails the moment someone
        re-introduces the trapping import form."""
        import importlib

        mod = importlib.import_module(mod_name)
        assert not hasattr(mod, "order_manager"), (
            f"v2.6 audit finding 2 regression: {mod_name} has a module-level "
            f"`order_manager` attribute, which means it early-bound the "
            f"singleton via `from core.order_manager_singleton import "
            f"order_manager`. patch('core.order_manager_singleton."
            f"order_manager', ...) can no longer intercept it — tests against "
            f"this module will pass while hitting the real OrderManager and "
            f"the real DB. Import the MODULE instead and dereference at call "
            f"time: `from core import order_manager_singleton` + "
            f"`order_manager_singleton.order_manager.<call>`."
        )

    @pytest.mark.parametrize("mod_name", _MODULE_IMPORT_CONSUMERS)
    def test_consumer_imports_the_module(self, mod_name):
        """Positive twin: the consumer resolves THROUGH the singleton module."""
        import importlib

        mod = importlib.import_module(mod_name)
        assert hasattr(mod, "order_manager_singleton"), (
            f"{mod_name} no longer imports core.order_manager_singleton as a "
            f"module. If it moved to a function-level `from`-import that is "
            f"also seam-safe (it re-resolves per call) — update this pin."
        )

    def test_no_module_level_from_import_anywhere_in_tree(self):
        """Tree-wide anti-revert: catches a NEW consumer added later that the
        parametrized list above doesn't know about. Function-level (indented)
        `from`-imports are FINE — they re-resolve on every call — so this only
        rejects the column-0 form.

        Scope covers every tree that could grow a consumer: core/, api/,
        scripts/, and the root modules (main.py, config.py). Today the only
        singleton references outside tests/ live in core/ + api/, but scripts/
        is where an operator tool would reach for the live cache."""
        root = Path(__file__).resolve().parent.parent
        offenders = []
        search = (
            list(root.glob("core/**/*.py"))
            + list(root.glob("api/**/*.py"))
            + list(root.glob("scripts/**/*.py"))
            + list(root.glob("*.py"))
        )
        for path in search:
            if "__pycache__" in path.parts:
                continue
            for ln, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if _EARLY_BIND_RE.match(line):
                    offenders.append(f"{path.relative_to(root)}:{ln}")
        assert not offenders, (
            f"v2.6 audit finding 2 regression: module-level early-binding "
            f"`from core.order_manager_singleton import order_manager` at "
            f"{offenders!r}. This defeats the "
            f"patch('core.order_manager_singleton.order_manager', ...) seam "
            f"for that module. Use `from core import order_manager_singleton` "
            f"at module scope, or move the from-import inside the function."
        )


# ── Pin 2: the documented patch target actually intercepts ──────────────────

class TestPatchSeamIntercepts:
    @pytest.mark.parametrize("mod_name", _MODULE_IMPORT_CONSUMERS)
    def test_patch_reaches_consumer_resolution_path(self, mod_name):
        """The object each consumer will dereference at call time IS the
        patched one. Mechanism-level proof, cheap and exact."""
        import importlib

        mod = importlib.import_module(mod_name)
        sentinel = MagicMock(name="fake_order_manager")
        with patch("core.order_manager_singleton.order_manager", sentinel):
            assert mod.order_manager_singleton.order_manager is sentinel

    # (test_dashboard_orders_fragment_uses_the_patched_singleton retired with
    # frag_dashboard_positions_rows in the fragments slim-down, 2026-07-30 —
    # the parametrized mechanism pin above exercises the identical
    # module-attribute resolution path for the surviving consumer.)
