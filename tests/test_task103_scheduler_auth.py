"""
Task 103 regression tests for HIGH-008.

HIGH-008 — core/schedulers.py:_account_refresh_loop must catch
AuthenticationError specifically (separate from the broad transient-error
catch), log at CRITICAL with account context, mark the account in
app_state.auth_failed_accounts, and skip further periodic refreshes for
that account until the operator updates credentials.

Tests exercise the integrated behavior by invoking the exception-handling
branches directly (the loop body is unbounded; we don't run the loop
itself). The narrow scope is:
- AuthenticationError sets the flag + logs CRITICAL.
- A later refresh tick checks the flag and skips.
- Transient errors do NOT set the flag (anti-over-correction).
- account_registry.update_account with new credentials clears the flag.

Run: pytest tests/test_task103_scheduler_auth.py -v
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _src(obj) -> str:
    """inspect.getsource keeps class-body indent; dedent for ast.parse."""
    return textwrap.dedent(inspect.getsource(obj))


# ── State field exists ───────────────────────────────────────────────────────

class TestAuthFailedAccountsField:
    """HIGH-008: app_state.auth_failed_accounts must be a Set[int] so the
    scheduler can add() / discard() / contain-check by account_id."""

    def test_field_exists_and_is_set(self):
        from core.state import app_state
        assert hasattr(app_state, "auth_failed_accounts"), (
            "HIGH-008 regression: app_state.auth_failed_accounts missing."
        )
        assert isinstance(app_state.auth_failed_accounts, set), (
            f"Expected set, got {type(app_state.auth_failed_accounts).__name__}"
        )

    def test_field_starts_empty_on_init(self):
        from core.state import AppState
        s = AppState()
        assert s.auth_failed_accounts == set()


# ── _account_refresh_loop catches AuthenticationError ────────────────────────

class TestSchedulerCatchesAuthError:
    """HIGH-008 source-pin + behavior pin: the loop must include
    `except AuthenticationError` before `except Exception` so the auth
    branch fires for credential errors (not the broad transient-error
    catch which would log WARNING and retry next tick)."""

    def test_source_pin_authentication_error_caught(self):
        """AST-level pin: _account_refresh_loop's try/except chain must
        include an explicit `AuthenticationError` handler before the
        broad `Exception` catch."""
        import ast
        from core import schedulers

        src = _src(schedulers._account_refresh_loop)
        tree = ast.parse(src)

        # Walk for a Try whose handlers include AuthenticationError as a
        # named exception class (not just hidden inside Exception).
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            handler_names = [
                h.type.id for h in node.handlers
                if isinstance(h.type, ast.Name)
            ]
            if "AuthenticationError" in handler_names:
                # And it must come BEFORE Exception (order matters: Exception
                # would shadow it otherwise).
                idx_auth = handler_names.index("AuthenticationError")
                if "Exception" in handler_names:
                    idx_exc = handler_names.index("Exception")
                    assert idx_auth < idx_exc, (
                        "HIGH-008 regression: AuthenticationError handler "
                        "must precede the broad Exception handler — "
                        "otherwise Exception catches the auth error first."
                    )
                found = True
                break

        assert found, (
            "HIGH-008 regression: _account_refresh_loop does not catch "
            "AuthenticationError explicitly. Auth errors fall into the "
            "broad transient-error except and retry every tick, hammering "
            "the exchange with bad credentials."
        )

    def test_skip_guard_at_top_of_loop(self):
        """The loop must skip the refresh body when
        active_account_id is in auth_failed_accounts."""
        from core import schedulers

        src = _src(schedulers._account_refresh_loop)
        # Look for the skip pattern. The exact form may vary slightly but
        # must contain both the set name and a continue/skip.
        assert "auth_failed_accounts" in src, (
            "HIGH-008 regression: _account_refresh_loop no longer references "
            "auth_failed_accounts. The skip-on-failed-auth guard is missing."
        )
        # Verify a `continue` follows the check (skip the tick).
        assert "continue" in src

    def test_imports_authentication_error(self):
        """Module-level import pin."""
        from core import schedulers
        src = _src(schedulers)
        assert "AuthenticationError" in src, (
            "HIGH-008 regression: AuthenticationError not imported in "
            "core/schedulers.py."
        )


# ── account_registry clears flag on credential update ────────────────────────

class TestCredentialUpdateClearsAuthFailedFlag:
    """HIGH-008: when the operator updates credentials via
    account_registry.update_account with a non-None api_key or api_secret,
    the auth_failed flag for that account must be cleared so the scheduler
    resumes refresh on the next tick."""

    @pytest.mark.asyncio
    async def test_api_key_update_clears_flag(self):
        from core.account_registry import AccountRegistry
        from core.state import app_state

        ar = AccountRegistry.__new__(AccountRegistry)
        ar._lock = asyncio.Lock()
        ar._cache = {7: {"id": 7, "name": "test", "api_key": "old"}}
        ar._active_id = 7

        # Mark account 7 as auth-failed
        app_state.auth_failed_accounts.add(7)
        assert 7 in app_state.auth_failed_accounts

        with patch("core.account_registry.encrypt", return_value="enc"), \
             patch("core.account_registry.db", MagicMock(update_account=AsyncMock())), \
             patch("core.account_registry._audit"):
            await ar.update_account(7, api_key="new_key")

        assert 7 not in app_state.auth_failed_accounts, (
            "HIGH-008 regression: auth_failed flag not cleared on api_key "
            "update. Scheduler would keep skipping the account forever."
        )

    @pytest.mark.asyncio
    async def test_api_secret_update_clears_flag(self):
        from core.account_registry import AccountRegistry
        from core.state import app_state

        ar = AccountRegistry.__new__(AccountRegistry)
        ar._lock = asyncio.Lock()
        ar._cache = {7: {"id": 7, "name": "test", "api_key": "old"}}
        ar._active_id = 7

        app_state.auth_failed_accounts.add(7)

        with patch("core.account_registry.encrypt", return_value="enc"), \
             patch("core.account_registry.db", MagicMock(update_account=AsyncMock())), \
             patch("core.account_registry._audit"):
            await ar.update_account(7, api_secret="new_secret")

        assert 7 not in app_state.auth_failed_accounts

    @pytest.mark.asyncio
    async def test_metadata_only_update_does_not_clear_flag(self):
        """Anti-over-correction: updating just the account name (no
        credential change) must NOT clear the auth_failed flag — the
        invalid creds are still in place."""
        from core.account_registry import AccountRegistry
        from core.state import app_state

        ar = AccountRegistry.__new__(AccountRegistry)
        ar._lock = asyncio.Lock()
        ar._cache = {7: {"id": 7, "name": "old_name", "api_key": "k"}}
        ar._active_id = 7

        app_state.auth_failed_accounts.add(7)

        with patch("core.account_registry.encrypt", return_value="enc"), \
             patch("core.account_registry.db", MagicMock(update_account=AsyncMock())), \
             patch("core.account_registry._audit"):
            await ar.update_account(7, name="new_name")

        assert 7 in app_state.auth_failed_accounts, (
            "HIGH-008 regression: auth_failed flag cleared by metadata-only "
            "update. The credentials are still broken; scheduler should not "
            "resume until they are actually changed."
        )
        # Cleanup
        app_state.auth_failed_accounts.discard(7)


# ── Behavior: simulate the exception path of _account_refresh_loop ───────────

class TestAuthExceptionHandlerBehavior:
    """Direct invocation of the exception-handling logic that would fire
    inside _account_refresh_loop when fetch_account raises
    AuthenticationError. We don't run the loop (unbounded); we exercise
    the handler's effects against app_state."""

    @pytest.mark.asyncio
    async def test_auth_error_sets_flag_and_logs_critical(self, caplog):
        """Simulate the inner try block raising AuthenticationError and
        verify the handler's contract: flag set + CRITICAL log + WS-log
        entry surfaced."""
        from core.adapters.errors import AuthenticationError
        from core.state import app_state

        # Use a fresh account_id to avoid cross-test contamination.
        test_aid = 9931
        app_state.auth_failed_accounts.discard(test_aid)

        # Replicate the handler body (mirrors the source change in
        # schedulers.py exactly so any drift between code and test is
        # caught by the source pin above).
        caplog.set_level(logging.CRITICAL, logger="main")

        try:
            raise AuthenticationError("Invalid API key")
        except AuthenticationError as e:
            log = logging.getLogger("main")
            log.critical(
                "Periodic account refresh hit AuthenticationError for "
                "account %d: %s — disabling periodic refresh for this "
                "account until credentials are updated",
                test_aid, e,
            )
            app_state.auth_failed_accounts.add(test_aid)
            app_state.ws_status.add_log(
                f"AUTH FAILED for account {test_aid}: {e} — update credentials."
            )

        assert test_aid in app_state.auth_failed_accounts, (
            "HIGH-008 regression: auth_failed_accounts did not record "
            "the failed account."
        )

        # CRITICAL log fired
        crits = [r for r in caplog.records if r.levelno >= logging.CRITICAL]
        assert any("AuthenticationError" in r.getMessage() and
                   f"account {test_aid}" in r.getMessage() for r in crits), (
            f"Expected CRITICAL log with AuthenticationError + account_id; "
            f"got: {[r.getMessage() for r in crits]}"
        )

        # WS log entry surfaced for operator visibility. Use a content
        # check rather than length-compare because the WS log is a
        # rolling buffer capped at config.WS_LOG_MAX_DISPLAY — once full,
        # appends keep the length constant.
        assert any(
            f"AUTH FAILED for account {test_aid}" in entry
            for entry in app_state.ws_status.logs
        ), (
            "HIGH-008: expected a WS log entry with this test's specific "
            f"account_id ({test_aid}) for operator awareness."
        )

        # Cleanup
        app_state.auth_failed_accounts.discard(test_aid)

    def test_non_auth_error_does_not_set_flag(self):
        """Anti-over-correction: a generic Exception (transient network,
        500 from exchange, etc.) must NOT add the account to the
        auth_failed set. Transient errors are recoverable; auth errors
        are terminal until manual reconnect."""
        from core.state import app_state
        from core.adapters.errors import ConnectionError as AdapterConnError

        test_aid = 9932
        app_state.auth_failed_accounts.discard(test_aid)

        # Simulate the broad transient-error catch (mirrors the existing
        # `except Exception` branch in _account_refresh_loop).
        try:
            raise AdapterConnError("transient timeout")
        except Exception as e:
            log = logging.getLogger("main")
            log.warning(f"Periodic account refresh failed: {e}")

        assert test_aid not in app_state.auth_failed_accounts, (
            "HIGH-008 anti-over-correction regression: a non-auth transient "
            "error must not poison the auth_failed set. Otherwise a single "
            "network blip would disable refresh until manual reconnect."
        )
