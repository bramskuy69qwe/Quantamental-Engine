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

MED-004 (Task 148): the KDF was upgraded from plain SHA256 to PBKDF2-
HMAC-SHA256 (200k iterations) with a domain-derived salt. New writes
prefix the ciphertext with `v2:` so legacy v1 (SHA256-derived) tokens
remain readable for backward compatibility. Migration is lazy — old
stored credentials decrypt via the v1 path; new writes use v2. See
`_fernet_v2` and `_fernet_v1` below.
"""
from __future__ import annotations

import base64
import functools
import hashlib
import logging
import os
import re

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger("crypto")


# MED-004 (Task 148): KDF v2 parameters. PBKDF2-HMAC-SHA256, 200k
# iterations, 16-byte salt deterministically derived from a domain
# constant + master. For the 256-bit-random master (documented:
# `secrets.token_hex(32)`), the iteration count is the real defense
# against brute-force; the salt prevents rainbow tables across
# distinct masters (single-user installation so this is mostly
# future-proofing if the master gets weakened to a passphrase later).
PBKDF2_ITERATIONS_V2 = 200_000
_KDF_SALT_DOMAIN_V2 = b"qe-kdf-salt-v2:"
_V2_PREFIX = "v2:"


class CredentialDecryptionError(Exception):
    """HIGH-010 (Task 105): raised when credential decryption fails.

    Indicates the encryption key does not match the ciphertext — either
    the master key is wrong (operator entered the wrong ENV_MASTER_KEY)
    or the stored ciphertext is corrupted. Either way, the credential is
    unusable and the operator must be told. Distinct from a missing
    credential (which is a legitimate "no credential stored" state).
    """
    pass


def _require_master() -> str:
    master = os.getenv("ENV_MASTER_KEY", "")
    if not master:
        raise RuntimeError(
            "ENV_MASTER_KEY is not set in .env — required for credential encryption. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    return master


@functools.lru_cache(maxsize=4)
def _fernet_v2_cached(master: str) -> Fernet:
    """MED-004 (Task 148): PBKDF2-HMAC-SHA256 Fernet key, cached per
    master. Amortizes the ~200ms PBKDF2 cost across all encrypt/decrypt
    calls. Cache key is the master (passed as arg, not read from env
    inside the cached function) so test fixtures can monkeypatch
    ENV_MASTER_KEY between calls and bypass stale cache.
    """
    salt = hashlib.sha256(_KDF_SALT_DOMAIN_V2 + master.encode()).digest()[:16]
    key_bytes = hashlib.pbkdf2_hmac(
        "sha256", master.encode(), salt, PBKDF2_ITERATIONS_V2, dklen=32,
    )
    return Fernet(base64.urlsafe_b64encode(key_bytes))


@functools.lru_cache(maxsize=4)
def _fernet_v1_cached(master: str) -> Fernet:
    """Legacy SHA256-derived Fernet for reading pre-Task-148 ciphertext.
    Preserved verbatim from the pre-Task-148 implementation. Same
    cache-key shape as v2 — keep test-fixture pattern aligned.
    """
    key_bytes = hashlib.sha256(master.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key_bytes))


def _fernet_v2() -> Fernet:
    """MED-004 (Task 148): PBKDF2-derived Fernet, current scheme."""
    return _fernet_v2_cached(_require_master())


def _fernet_v1() -> Fernet:
    """Legacy SHA256-derived Fernet, for reading pre-Task-148 ciphertext."""
    return _fernet_v1_cached(_require_master())


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string. Returns a URL-safe base64 Fernet token
    prefixed with `v2:` (MED-004, Task 148 — PBKDF2-derived key)."""
    if not plaintext:
        return ""
    token = _fernet_v2().encrypt(plaintext.encode()).decode()
    return _V2_PREFIX + token


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet token back to plaintext.

    Returns '' for empty input (legitimate "no credential stored" case —
    e.g., a connection row whose api_key_enc is empty during initial
    account setup).

    MED-004 (Task 148): version-prefix routing.
      - `v2:`-prefixed: PBKDF2-derived Fernet key (new writes).
      - no prefix: legacy SHA256-derived Fernet key (v1) — reads
        existing stored credentials transparently. New writes are
        always v2; v1 path is read-only legacy support.

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
        if ciphertext.startswith(_V2_PREFIX):
            plaintext = _fernet_v2().decrypt(
                ciphertext[len(_V2_PREFIX):].encode()
            ).decode()
        else:
            # Legacy v1: SHA256-derived Fernet key. Operator's pre-Task-148
            # stored credentials land here. Lazy migration — these stay
            # v1 until rewritten via account-edit / re-connect.
            plaintext = _fernet_v1().decrypt(ciphertext.encode()).decode()
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
