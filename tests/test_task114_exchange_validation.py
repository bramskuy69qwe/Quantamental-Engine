"""
Task 114 regression tests for MED-048 — server-side exchange whitelist
validation on account-creation / update / preview routes.

Pre-fix:
  POST /accounts (and friends) accepted any client-supplied `exchange`
  string. Adapter lookup failure only surfaced later (during account
  activation or ccxt instance creation), and add-account-modal could
  silently persist a bad value into the DB.

Post-fix:
  - core.adapters.registry exposes `is_valid_rest_exchange()` and
    `get_supported_rest_exchanges()` — strict, case-sensitive lookup
    against the adapter registry.
  - api.routes_accounts._validate_exchange() composes those + market_type
    mapping, returns an operator-friendly error string on rejection.
  - Four route entry points call the validator before any DB / ccxt
    work; reject with 400 + structured message.

Design notes (per task spec):
  - Strict case-sensitive validation. Frontend dropdown emits lowercase
    canonical IDs (Task 111); a capitalized value implies tampering.
  - Tests avoid TestClient to dodge the LOW-023 deadlock pattern in
    full-suite runs. Validator is unit-tested directly; route wiring is
    source-pinned via inspect.getsource + ast.walk.

Run: pytest tests/test_task114_exchange_validation.py -v
"""
from __future__ import annotations

import ast
import inspect

import pytest


# ── Registry-level validator ─────────────────────────────────────────────────

class TestRegistryValidator:
    """`is_valid_rest_exchange` is the leaf check. Tests don't depend on
    HTTP — they just exercise the registry against known-good and
    known-bad inputs."""

    def test_canonical_lowercase_id_is_valid(self):
        from core.adapters.registry import is_valid_rest_exchange
        # 'binance' adapter is registered for linear_perpetual.
        assert is_valid_rest_exchange("binance", "linear_perpetual") is True

    def test_unknown_id_is_rejected(self):
        from core.adapters.registry import is_valid_rest_exchange
        assert is_valid_rest_exchange("fakeexch", "linear_perpetual") is False

    def test_empty_id_is_rejected(self):
        from core.adapters.registry import is_valid_rest_exchange
        assert is_valid_rest_exchange("", "linear_perpetual") is False

    def test_none_id_is_rejected(self):
        from core.adapters.registry import is_valid_rest_exchange
        # Defensive: client form field could in theory be missing
        # (though FastAPI would 422 before reaching this code path).
        assert is_valid_rest_exchange(None, "linear_perpetual") is False  # type: ignore[arg-type]

    def test_uppercase_id_is_rejected_strict_case(self):
        """MED-048 design decision: case-sensitive. Registry keys are
        lowercase; accepting "BINANCE" would mask frontend tampering."""
        from core.adapters.registry import is_valid_rest_exchange
        assert is_valid_rest_exchange("BINANCE", "linear_perpetual") is False
        assert is_valid_rest_exchange("Binance", "linear_perpetual") is False

    def test_unknown_market_type_rejects_known_exchange(self):
        """`binance` is registered for linear_perpetual, NOT for some
        arbitrary other market type. Validator must require both axes
        to match."""
        from core.adapters.registry import is_valid_rest_exchange
        assert is_valid_rest_exchange("binance", "options") is False

    def test_supported_list_includes_all_registered_exchanges(self):
        """The error-message helper enumerates what the operator should
        try instead. Must include all registered adapters for the same
        market_type."""
        from core.adapters.registry import (
            get_supported_rest_exchanges, _REST_REGISTRY,
        )
        supported = get_supported_rest_exchanges("linear_perpetual")
        registered_for_mt = {
            k.split(":", 1)[0]
            for k in _REST_REGISTRY.keys()
            if k.endswith(":linear_perpetual")
        }
        assert set(supported) == registered_for_mt
        # And it's deduped + sorted (deterministic message text).
        assert supported == sorted(supported)


# ── Route-level validator wrapper ────────────────────────────────────────────

class TestValidateExchangeRouteHelper:
    """`_validate_exchange` is the route-layer wrapper that maps the
    legacy `future` market_type to the registry's `linear_perpetual`
    key and produces the operator-friendly error message."""

    def test_valid_pair_returns_empty_string(self):
        from api.routes_accounts import _validate_exchange
        # The routes accept market_type='future' (legacy DB form) and
        # the helper maps to 'linear_perpetual' before lookup.
        assert _validate_exchange("binance", "future") == ""

    def test_invalid_exchange_returns_message_with_supported_list(self):
        from api.routes_accounts import _validate_exchange
        msg = _validate_exchange("fakeexch", "future")
        assert msg, "validator should return non-empty error for unknown exchange"
        assert "fakeexch" in msg, "error message should quote the bad value"
        # Operator-friendly: should mention at least one supported exchange.
        assert "binance" in msg
        assert "Supported:" in msg

    def test_uppercase_rejected_with_message(self):
        from api.routes_accounts import _validate_exchange
        msg = _validate_exchange("BINANCE", "future")
        assert msg, "uppercase should be rejected (strict case)"
        assert "BINANCE" in msg

    def test_empty_string_rejected_with_message(self):
        from api.routes_accounts import _validate_exchange
        assert _validate_exchange("", "future") != ""


# ── Route wiring (source-pinned, no HTTP) ────────────────────────────────────

class TestRouteWiring:
    """Source-pin: each of the four client-trust gaps must call
    `_validate_exchange` before any DB / ccxt work. Catches a future
    revert that drops the validator from one route while keeping the
    others wired."""

    def _route_source(self, name: str) -> str:
        import api.routes_accounts as m
        fn = getattr(m, name)
        return inspect.getsource(fn)

    def test_create_account_calls_validator(self):
        src = self._route_source("create_account")
        assert "_validate_exchange(" in src, (
            "MED-048 regression: POST /accounts no longer validates "
            "exchange before account_registry.add_account."
        )

    def test_add_account_modal_calls_validator(self):
        src = self._route_source("add_account_modal")
        assert "_validate_exchange(" in src, (
            "MED-048 regression: POST /accounts/add-and-reload no longer "
            "validates exchange. Bad value would persist to DB."
        )

    def test_test_account_preview_calls_validator(self):
        src = self._route_source("test_account_preview")
        assert "_validate_exchange(" in src, (
            "MED-048 regression: POST /accounts/test-preview no longer "
            "validates exchange before _make_ccxt_instance."
        )

    def test_update_account_detail_calls_validator(self):
        src = self._route_source("update_account_detail")
        assert "_validate_exchange(" in src, (
            "MED-048 regression: POST /accounts/{id}/update no longer "
            "validates exchange on edit."
        )

    def test_create_account_validator_call_precedes_add_account(self):
        """AST-pin: in `create_account`, the validator call must appear
        before the `account_registry.add_account(...)` call. Otherwise
        a bad exchange would be persisted before the 400 is returned."""
        src = self._route_source("create_account")
        tree = ast.parse(src)
        # Find line numbers of the two calls
        val_line = None
        add_line = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "_validate_exchange":
                    val_line = node.lineno if val_line is None else val_line
                if isinstance(func, ast.Attribute) and func.attr == "add_account":
                    add_line = node.lineno if add_line is None else add_line
        assert val_line is not None and add_line is not None
        assert val_line < add_line, (
            "MED-048 regression: validator runs AFTER add_account — "
            "bad exchange would persist before rejection."
        )


# ── Error-response shape (HTTP status code intent) ───────────────────────────

class TestRejectionResponseShape:
    """The route source must return status_code=400 on validator
    rejection — pin via source-grep. (Full HTTP exercise would require
    TestClient; LOW-023 pattern keeps tests at the source level.)"""

    def test_create_account_returns_400_on_validator_error(self):
        import api.routes_accounts as m
        src = inspect.getsource(m.create_account)
        # The two lines we care about are paired: the validator-error
        # branch returns JSONResponse(..., status_code=400).
        assert "status_code=400" in src, (
            "MED-048 regression: create_account no longer returns 400 "
            "on unknown exchange."
        )

    def test_test_account_preview_returns_400_on_validator_error(self):
        import api.routes_accounts as m
        src = inspect.getsource(m.test_account_preview)
        assert "status_code=400" in src, (
            "MED-048 regression: test_account_preview no longer returns "
            "400 on unknown exchange."
        )

    def test_add_account_modal_returns_400_on_validator_error(self):
        import api.routes_accounts as m
        src = inspect.getsource(m.add_account_modal)
        assert "status_code=400" in src, (
            "MED-048 regression: add_account_modal no longer returns "
            "400 on unknown exchange."
        )
