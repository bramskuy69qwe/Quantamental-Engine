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

def test_update_params_has_runtime_position_count_check_wiring():
    """MED-036 wiring pin: update_params's BODY (not signature) must reference
    both max_position_count AND a runtime measure of open positions
    (len(app_state.positions) or equivalent). Helper-only tests don't catch
    a route that drops the runtime check.

    Note: max_position_count appears in the function SIGNATURE as a Form
    parameter — that doesn't count. The pin scans only body nodes for a
    Name reference, ensuring an actual runtime usage exists."""
    from api import routes_params

    fn_node = _find_function_node(routes_params, "update_params")

    # Scan the body for a Compare node where one side is the Name
    # `max_position_count` and the other side references the runtime
    # position-count (len(app_state.positions) / app_state.position_count).
    # This catches the actual semantic — a comparison between the new
    # max and the current open count — rather than just any mention of
    # either name in the body (which would pass vacuously since
    # max_position_count appears as a dict value in the new_params
    # assembly even without the runtime check).
    def _is_max_pos_name(n):
        return isinstance(n, ast.Name) and n.id == "max_position_count"

    def _is_runtime_position_marker(n):
        # len(app_state.positions) or len(app_state._positions)
        if (isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name) and n.func.id == "len"
            and len(n.args) == 1
            and isinstance(n.args[0], ast.Attribute)
            and isinstance(n.args[0].value, ast.Name)
            and n.args[0].value.id == "app_state"
            and n.args[0].attr in ("positions", "_positions")):
            return True
        # app_state.position_count
        if (isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name) and n.value.id == "app_state"
            and n.attr == "position_count"):
            return True
        # Name referring to a local that was assigned from one of the above
        # (e.g., `open_count = len(app_state.positions)` then `if max_position_count < open_count`).
        # We accept any Name whose id is a known "count" alias.
        if isinstance(n, ast.Name) and n.id in (
            "open_count", "open_position_count", "current_open_count", "position_count",
        ):
            return True
        return False

    has_max_vs_runtime_compare = False
    for stmt in fn_node.body:
        for n in ast.walk(stmt):
            if not isinstance(n, ast.Compare):
                continue
            # Collect all sides of the Compare: left + comparators
            sides = [n.left, *n.comparators]
            # Check whether one side is max_position_count and another is a runtime marker
            has_max = any(_is_max_pos_name(s) for s in sides)
            has_runtime = any(_is_runtime_position_marker(s) for s in sides)
            if has_max and has_runtime:
                has_max_vs_runtime_compare = True
                break
        if has_max_vs_runtime_compare:
            break

    # Additionally require the literal source contains a runtime-marker pattern
    # so that a Compare against an unbound local can't slip through.
    src = inspect.getsource(routes_params.update_params)
    has_literal_runtime_marker = (
        "len(app_state.positions)" in src
        or "len(app_state._positions)" in src
        or "app_state.position_count" in src
    )

    assert has_max_vs_runtime_compare and has_literal_runtime_marker, (
        "MED-036 wiring regression: update_params no longer contains a "
        "comparison of max_position_count against a runtime position-count "
        "(len(app_state.positions) / app_state.position_count / equivalent "
        "local). The runtime cross-check is gone; param updates that violate "
        "the cap against the active position set will be accepted again. "
        f"compare-found={has_max_vs_runtime_compare}, "
        f"literal-marker-found={has_literal_runtime_marker}"
    )
