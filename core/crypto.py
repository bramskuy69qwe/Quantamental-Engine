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
import os

from cryptography.fernet import Fernet, InvalidToken


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
    """Decrypt a Fernet token back to plaintext. Returns '' on invalid token."""
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except (InvalidToken, Exception):
        return ""
