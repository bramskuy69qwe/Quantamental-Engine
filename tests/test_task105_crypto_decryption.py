"""
Task 105 regression tests for HIGH-010.

HIGH-010 — core/crypto.py:decrypt previously silent-fell-back to "" on
InvalidToken / generic Exception. Callers had no way to distinguish
"no credential stored" from "wrong master key." Engine ran credential-
less under wrong-key conditions with no operator signal.

Fix: decrypt now raises CredentialDecryptionError on bad key / corrupted
ciphertext. The empty-input fast-path is preserved (legitimate "no
credential stored"). Three call sites updated to catch the new exception
and mark the account/connection in app_state.auth_failed_accounts (Task
103's existing state) — the remediation blocker is the same (no
operations possible until operator intervenes), but the diagnostic log
distinguishes "decryption failed" from "API key rejected by exchange."

Run: pytest tests/test_task105_crypto_decryption.py -v
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── crypto.decrypt: raise vs silent fallback ─────────────────────────────────

class TestDecryptRaises:
    """The load-bearing pin: wrong key must raise, not return ''."""

    @pytest.fixture(autouse=True)
    def ensure_env_key(self, monkeypatch):
        # Provide a deterministic master key for tests
        monkeypatch.setenv("ENV_MASTER_KEY", "task105_test_master_key_for_crypto")
        yield

    def test_decrypt_succeeds_with_correct_key(self):
        """Anti-over-correction: round-trip works under the standard key."""
        from core.crypto import encrypt, decrypt
        plaintext = "my-secret-api-key-12345"
        ciphertext = encrypt(plaintext)
        assert decrypt(ciphertext) == plaintext

    def test_decrypt_empty_input_returns_empty(self):
        """Anti-over-correction: empty ciphertext is the legitimate
        'no credential stored' case — must NOT raise."""
        from core.crypto import decrypt
        assert decrypt("") == ""
        # None / falsy variant
        assert decrypt(None) == ""  # type: ignore[arg-type]

    def test_decrypt_raises_on_wrong_master_key(self, monkeypatch):
        """HIGH-010 load-bearing pin: ciphertext encrypted under key A
        cannot be decrypted under key B — must raise, not silently return ''."""
        from core.crypto import encrypt, decrypt, CredentialDecryptionError

        # Encrypt under key A
        monkeypatch.setenv("ENV_MASTER_KEY", "task105_key_A")
        ct = encrypt("real-credential")

        # Try to decrypt under key B
        monkeypatch.setenv("ENV_MASTER_KEY", "task105_key_B_different")
        with pytest.raises(CredentialDecryptionError) as ei:
            decrypt(ct)
        assert "ENV_MASTER_KEY" in str(ei.value)

    def test_decrypt_raises_on_corrupted_ciphertext(self):
        """HIGH-010 boundary: tampered ciphertext (a flipped char) must
        also raise — not silently return ''."""
        from core.crypto import encrypt, decrypt, CredentialDecryptionError
        ct = encrypt("plaintext-here")
        # Flip the last char to corrupt
        corrupted = ct[:-1] + ("A" if ct[-1] != "A" else "B")
        with pytest.raises(CredentialDecryptionError):
            decrypt(corrupted)

    def test_decrypt_error_message_is_operator_actionable(self):
        """HIGH-010 UX pin: error message must guide the operator. The
        log line + the exception message both reference ENV_MASTER_KEY so
        the operator knows where to look."""
        from core.crypto import encrypt, decrypt, CredentialDecryptionError
        ct = encrypt("plaintext")
        corrupted = ct[:-1] + ("A" if ct[-1] != "A" else "B")
        try:
            decrypt(corrupted)
        except CredentialDecryptionError as e:
            msg = str(e)
            assert "ENV_MASTER_KEY" in msg or "check" in msg.lower(), (
                f"Expected actionable guidance in error message; got: {msg!r}"
            )

    def test_decrypt_logs_error_with_exception_type(self, caplog):
        """The log line names the underlying exception type (InvalidToken
        on Fernet) so the operator can correlate with the cryptography
        library docs if needed."""
        from core.crypto import encrypt, decrypt, CredentialDecryptionError
        ct = encrypt("plaintext")
        corrupted = ct[:-1] + ("A" if ct[-1] != "A" else "B")
        caplog.set_level(logging.ERROR, logger="crypto")
        with pytest.raises(CredentialDecryptionError):
            decrypt(corrupted)
        errors = [r.getMessage() for r in caplog.records
                  if r.levelno >= logging.ERROR]
        assert any("decryption failed" in m.lower() for m in errors), (
            f"Expected an ERROR log naming the failure; got: {errors!r}"
        )


# ── Caller integration: account_registry.load_all ────────────────────────────

class TestAccountRegistryLoadAllHandlesDecryptionError:
    """When decrypt raises during load_all, the account must be loaded
    with blank credentials AND its account_id added to auth_failed_accounts
    so the scheduler skips it."""

    @pytest.mark.asyncio
    async def test_corrupted_credential_marks_auth_failed_and_loads_blank(self):
        from core.account_registry import AccountRegistry
        from core.crypto import CredentialDecryptionError
        from core.state import app_state

        ar = AccountRegistry.__new__(AccountRegistry)
        ar._lock = asyncio.Lock()
        ar._cache = {}
        ar._active_id = 1

        test_aid = 42
        app_state.auth_failed_accounts.discard(test_aid)

        # Mock the actual DB calls load_all makes:
        # get_all_accounts, get_setting, get_all_account_params, get_account
        mock_db = MagicMock()
        mock_db.get_all_accounts = AsyncMock(return_value=[{"id": test_aid}])
        mock_db.get_setting = AsyncMock(return_value="1")
        mock_db.get_all_account_params = AsyncMock(return_value={})
        mock_db.set_account_params = AsyncMock()
        mock_db.get_account = AsyncMock(return_value={
            "id": test_aid, "name": "broken-key-acct",
            "exchange": "binance", "market_type": "future",
            "api_key_enc": "encrypted_under_a_different_master_key",
            "api_secret_enc": "also_encrypted_differently",
            "is_active": 1, "broker_account_id": "",
            "maker_fee": 0.0002, "taker_fee": 0.0005,
            "environment": "live", "link_window_seconds": 21600,
        })

        def _raise_decrypt(_ct):
            raise CredentialDecryptionError("decryption failed — check ENV_MASTER_KEY")

        with patch("core.account_registry.db", mock_db), \
             patch("core.account_registry.decrypt", side_effect=_raise_decrypt):
            await ar.load_all()

        # Account should still be in cache (with blank creds) so the rest
        # of the engine doesn't crash on missing-account lookups
        assert test_aid in ar._cache
        assert ar._cache[test_aid]["api_key"] == ""
        assert ar._cache[test_aid]["api_secret"] == ""
        # Marked auth-failed so scheduler skips it (Task 103 integration)
        assert test_aid in app_state.auth_failed_accounts, (
            "HIGH-010 wiring regression: load_all caught the decryption "
            "error but did not mark the account in auth_failed_accounts."
        )
        # Cleanup
        app_state.auth_failed_accounts.discard(test_aid)


# ── Caller integration: connections.load_all ────────────────────────────────

class TestConnectionsLoadAllHandlesDecryptionError:
    """A corrupted credential in the connections table must not crash
    load_all. The connection is loaded with blank key + is_active=0."""

    @pytest.mark.asyncio
    async def test_corrupted_credential_loaded_inactive(self):
        from core.connections import ConnectionsManager
        from core.crypto import CredentialDecryptionError

        cm = ConnectionsManager()

        mock_db = MagicMock()
        mock_db.get_all_connections = AsyncMock(return_value=[
            {
                "provider": "fred", "label": "FRED",
                "api_key_enc": "broken_ciphertext", "extra_enc": "",
                "is_active": 1,
            },
        ])

        def _raise_decrypt(_ct):
            raise CredentialDecryptionError("decryption failed — check ENV_MASTER_KEY")

        with patch("core.connections.db", mock_db), \
             patch("core.connections.decrypt", side_effect=_raise_decrypt):
            await cm.load_all()

        # Connection present but disabled
        assert "fred" in cm._cache
        assert cm._cache["fred"]["api_key"] == ""
        assert cm._cache["fred"]["is_active"] == 0, (
            "HIGH-010 wiring regression: corrupted connection should be "
            "loaded with is_active=0 so the test/usage path skips it."
        )


# ── Source pins (Task 97.1 pattern) ─────────────────────────────────────────

class TestSourcePins:
    """Catch a future regression where someone removes the raise + restores
    the silent-fallback shape, or drops a caller's try/except block."""

    def test_decrypt_source_raises_credential_decryption_error(self):
        from core import crypto
        src = inspect.getsource(crypto.decrypt)
        assert "raise CredentialDecryptionError" in src, (
            "HIGH-010 regression: decrypt no longer raises "
            "CredentialDecryptionError. The silent-fallback bug is back."
        )
        # The empty-input fast-path must still be preserved
        assert "if not ciphertext:" in src

    def test_account_registry_imports_credential_decryption_error(self):
        from core import account_registry
        src = inspect.getsource(account_registry)
        assert "CredentialDecryptionError" in src

    def test_connections_imports_credential_decryption_error(self):
        from core import connections
        src = inspect.getsource(connections)
        assert "CredentialDecryptionError" in src

    def test_ws_manager_imports_credential_decryption_error(self):
        from core import ws_manager
        src = inspect.getsource(ws_manager)
        assert "CredentialDecryptionError" in src
