"""
Task 96 regression pin for HIGH-012 (VERIFIED FALSE).

Audit framed core/order_manager.py:594-601's deferred-close lambda as a
closure-binding race: account_id captured by the lambda could change
before the 2-second `call_later` deferred action fires.

Investigation (Task 96) traced the closure:
  lambda f=fill: asyncio.ensure_future(
      self._build_close_row_for_fill(account_id, f)
  )

Free variables: self, account_id. The fill is explicit-value-captured
via `f=fill` default arg (already correct).

`account_id` is the function parameter of `process_fill(self, account_id,
fill)`. Python parameter-binding semantics:
  - Each process_fill call has its own frame.
  - account_id is a local variable in that frame, bound to the value
    passed at call time.
  - The lambda captures the cell holding this binding.
  - The function body doesn't reassign account_id (grep confirmed).
  - External code (app_state.active_account_id = ...) cannot mutate
    process_fill's local account_id; the function's frame is private.

Therefore the audit's "outer scope changes on account switch" mechanism
is structurally impossible. The captured account_id stays pinned to the
value at process_fill's call time, regardless of subsequent account
switches.

This pin asserts the capture pattern via AST: every account_id reference
inside lambdas of process_fill must be a bare ast.Name (the function
parameter), not an ast.Attribute access (which would be self.account_id,
app_state.active_account_id, or similar mutable path).

If a future refactor changes the lambda to capture from an attribute
path, the pin fails with explicit guidance: HIGH-012's race becomes
reachable and the audit's recommended fix (explicit value capture +
verify-active-account-before-insert) becomes warranted.

Run: pytest tests/test_task96_high012_closure_pin.py -v
"""
from __future__ import annotations

import ast
import inspect
import textwrap


def test_process_fill_deferred_close_lambda_captures_function_param():
    """HIGH-012 VERIFIED FALSE pin: the lambda in process_fill must reference
    account_id as a bare Name (the function parameter), not as an Attribute
    access (which would be a mutable-state capture exposing the audit's race)."""
    from core.order_manager import OrderManager

    src = textwrap.dedent(inspect.getsource(OrderManager.process_fill))
    tree = ast.parse(src)

    # Find every lambda inside process_fill
    lambdas = [n for n in ast.walk(tree) if isinstance(n, ast.Lambda)]
    assert len(lambdas) >= 1, (
        "Expected at least one lambda in OrderManager.process_fill (the "
        "deferred-close-row scheduler). If the lambda disappeared, the "
        "deferred-close pathway may have been refactored — re-evaluate "
        "HIGH-012 reachability against the new structure."
    )

    # For each lambda, scan its body for any Attribute node whose .attr is
    # account_id-like — that would be the race-shape pattern.
    forbidden_attrs = {"account_id", "active_account_id", "current_account_id"}

    for lam_idx, lam in enumerate(lambdas):
        for node in ast.walk(lam):
            if isinstance(node, ast.Attribute) and node.attr in forbidden_attrs:
                raise AssertionError(
                    f"HIGH-012 closure pattern changed in process_fill: lambda #{lam_idx} "
                    f"now references attribute `.{node.attr}` instead of the function "
                    f"parameter `account_id`. The audit's closure-race becomes reachable: "
                    f"the captured value can now be mutated by external code between "
                    f"lambda creation and the 2.0s call_later firing. Apply the audit's "
                    f"recommended fix: snapshot account_id to a local before the lambda, "
                    f"and verify-active-account-before-insert inside the deferred action."
                )

        # Additionally verify that at least one Name node referring to account_id
        # is present (the function-parameter reference). If account_id isn't
        # referenced AT ALL inside the lambda, the lambda's purpose changed —
        # surface for re-evaluation.
        account_id_refs = [
            n for n in ast.walk(lam)
            if isinstance(n, ast.Name) and n.id == "account_id"
        ]
        if not account_id_refs:
            # Not a hard failure — some lambdas in process_fill may not use
            # account_id at all. But if NO lambda references it, the
            # deferred-close path may have been removed.
            continue

    # Final sanity: at least one lambda in process_fill should reference
    # account_id as a Name (the function parameter). If none do, the
    # deferred-close path's account-scoping invariant is broken in a
    # different way.
    any_param_capture = any(
        any(
            isinstance(n, ast.Name) and n.id == "account_id"
            for n in ast.walk(lam)
        )
        for lam in lambdas
    )
    assert any_param_capture, (
        "No lambda in process_fill references account_id as a bare Name. "
        "Either the deferred-close path was removed or account scoping is "
        "now threaded differently. Re-evaluate HIGH-012 against the new "
        "structure."
    )
