"""
Symmetric encryption for API credentials stored in SQLite.

Uses Fernet (from the `cryptography` package) with a master key derived
from the ENV_MASTER_KEY environment variable.

Usage:
    from core.crypto import encrypt, decrypt
    ciphertext = encrypt("my_api_key")
    plaintext  = decrypt(ciphertext)

ENV_MASTER_KEY must be set in .env before first use.
Generate a key once with:
    python -c "import secrets; print(secrets.token_hex(32))"
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import re

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger("crypto")


class CredentialDecryptionError(Exception):
    """HIGH-010 (Task 105): raised when credential decryption fails.

    Indicates the encryption key does not match the ciphertext — either
    the master key is wrong (operator entered the wrong ENV_MASTER_KEY)
    or the stored ciphertext is corrupted. Either way, the credential is
    unusable and the operator must be told. Distinct from a missing
    credential (which is a legitimate "no credential stored" state).
    """
    pass


def _fernet() -> Fernet:
    """Derive a stable 32-byte Fernet key from ENV_MASTER_KEY."""
    master = os.getenv("ENV_MASTER_KEY", "")
    if not master:
        raise RuntimeError(
            "ENV_MASTER_KEY is not set in .env — required for credential encryption. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    key_bytes = hashlib.sha256(master.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key_bytes))


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string. Returns a URL-safe base64 Fernet token."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet token back to plaintext.

    Returns '' for empty input (legitimate "no credential stored" case —
    e.g., a connection row whose api_key_enc is empty during initial
    account setup).

    HIGH-010 (Task 105): raises CredentialDecryptionError on key mismatch
    / corrupted ciphertext. Previously this path silently returned ''
    after logging an error — callers (account_registry.load_all,
    connections.load_all, ws_manager reconnect) had no way to
    distinguish "no credential" from "wrong master key," leaving the
    operator blind when keys were intact but ENV_MASTER_KEY drifted.

    HIGH-029 (Task 116): the non-empty return is wrapped in SensitiveStr
    so a traceback fired between this call and the consumer's cache
    write masks the credential in stack frames. SensitiveStr is a
    `str` subclass, so callers that pass the return through
    ``.encode()`` (e.g., HMAC, Fernet re-encrypt) are unaffected — the
    C-slot bypasses the Python-level ``__str__`` override. Callers that
    eventually store the value in a cache consumed by HTTP / urlencode
    code paths MUST call ``.unwrap()`` at the cache boundary; today
    those are ``account_registry.load_all``, ``connections.load_all``,
    and ``ws_manager`` user-data reconnect.
    """
    if not ciphertext:
        return ""
    try:
        plaintext = _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception) as e:
        log.error(
            "credential decryption failed (%s) — encryption-key mismatch "
            "or corrupted ciphertext. Check ENV_MASTER_KEY or re-enter "
            "credentials.",
            type(e).__name__,
        )
        raise CredentialDecryptionError(
            "decryption failed — check ENV_MASTER_KEY"
        ) from e
    from core.security import SensitiveStr
    return SensitiveStr(plaintext)


def safe_exchange_error(e: Exception) -> str:
    """Strip potential credential fragments from CCXT error messages."""
    msg = str(e)
    return re.sub(r"(apiKey|secret|signature|key|token)=[^&\s]+", r"\1=***", msg)


def mask_key(key: str, visible: int = 4) -> str:
    """Return a masked version of an API key showing only the last `visible` chars."""
    if not key or len(key) <= visible:
        return "****"
    return "•" * 8 + key[-visible:]
