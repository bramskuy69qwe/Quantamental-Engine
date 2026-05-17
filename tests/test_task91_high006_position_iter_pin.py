"""
Task 91 regression pin for HIGH-006 (VERIFIED FALSE).

Audit framed core/ws_manager.py:159's `for pos in app_state.positions` loop
inside `_apply_order_update` as a concurrent-modification risk. Deep-read
during Task 91 found:

  1. The loop body (lines 159-195) contains ZERO `await` statements — pure
     attribute assignments and conditionals, then `break`.
  2. All mutations to `_positions` happen via async methods on the same
     asyncio event loop (apply_position_update_incremental, etc.) and are
     gated by `self._lock`. No `to_thread` / `run_in_executor` path mutates
     `_positions` from a separate OS thread.

Python's single-threaded asyncio event loop means no other coroutine can
interleave between iterations of this loop. The audit's failure mode is
structurally unreachable under current code.

This pin asserts the await-free invariant. If a future contributor adds an
`await` to the loop body, a yield point is created where concurrent
modification becomes possible — and HIGH-006's risk becomes real. The pin
fails loudly with guidance to re-evaluate reachability and consider
applying the `list(app_state.positions)` snapshot fix.

Run: pytest tests/test_task91_high006_position_iter_pin.py -v
"""
from __future__ import annotations

import ast
import inspect


def test_apply_order_update_tpsl_loop_body_has_no_awaits():
    """HIGH-006 VERIFIED FALSE pin: loop body must remain await-free."""
    from core import ws_manager

    src = inspect.getsource(ws_manager._apply_order_update)
    tree = ast.parse(src)

    # Find every `for ... in app_state.positions:` loop inside the function.
    target_loops = []
    for node in ast.walk(tree):
        if isinstance(node, ast.For):
            try:
                iter_src = ast.unparse(node.iter)
            except Exception:
                continue
            if iter_src == "app_state.positions":
                target_loops.append(node)

    assert len(target_loops) >= 1, (
        "Expected at least one `for ... in app_state.positions` loop in "
        "_apply_order_update; loop disappeared? Investigate HIGH-006 status."
    )

    for loop in target_loops:
        awaits = [
            n for n in ast.walk(loop)
            if isinstance(n, ast.Await)
        ]
        assert len(awaits) == 0, (
            f"HIGH-006 reachability changed: the `for pos in app_state.positions` "
            f"loop in core.ws_manager._apply_order_update gained "
            f"{len(awaits)} `await` statement(s). The loop is no longer atomic "
            f"under asyncio cooperative scheduling, and concurrent modification "
            f"of app_state.positions by other coroutines (e.g., "
            f"DataCache.apply_position_update_incremental) becomes reachable. "
            f"Re-evaluate HIGH-006 and consider applying the audit's "
            f"recommended `for p in list(app_state.positions):` snapshot fix."
        )
