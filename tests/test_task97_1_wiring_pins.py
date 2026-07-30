"""
Task 97.1 wiring pins for HIGH-022 + MED-036.

Closes the failure-before-fix gap from Task 97. The validator helpers
(`_validate_date_range` in api/routes_backtest.py, the runtime
position-count check in api/routes_params.update_params) are unit-tested
in isolation by Task 97. These pins assert the helpers are actually
WIRED into the route handlers — a future refactor that drops a helper
call would be caught by AST inspection here.

Runtime-marker chosen for MED-036's check: `len(app_state.positions)`,
matching the code added at api/routes_params.py:64 in Task 97.

Run: pytest tests/test_task97_1_wiring_pins.py -v
"""
from __future__ import annotations

import ast
import inspect


# ── Helpers ──────────────────────────────────────────────────────────────────

def _find_function_node(module, fn_name):
    """Return the AST node for `fn_name` defined in `module`."""
    src = inspect.getsource(module)
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn_name:
            return node
    raise AssertionError(f"function {fn_name} not found in {module.__name__}")


def _function_calls(fn_node, target_name):
    """Count direct calls to `target_name` within `fn_node`'s body."""
    return sum(
        1 for n in ast.walk(fn_node)
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == target_name
    )


# ── HIGH-022 wiring pins ─────────────────────────────────────────────────────

def test_api_backtest_run_calls_validate_date_range_wiring():
    """HIGH-022 wiring pin: api_backtest_run must call _validate_date_range.
    Helper unit tests don't catch a route that accidentally drops the helper
    call."""
    from api import routes_backtest

    fn_node = _find_function_node(routes_backtest, "api_backtest_run")
    assert _function_calls(fn_node, "_validate_date_range") >= 1, (
        "HIGH-022 wiring regression: api_backtest_run no longer calls "
        "_validate_date_range. The route now accepts unbounded date ranges, "
        "reviving HIGH-022's DoS vector. If intentional, explicitly close "
        "out HIGH-022's resolution in the audit doc."
    )


# v2.7 P6 (task 6.1): the Quantower-JSON-importer wiring pin was deleted
# WITH its route — the model library's adapter upload supersedes it.


# ── MED-036 wiring pin ───────────────────────────────────────────────────────

