"""
Adapter-neutral error types.

Adapters translate exchange-specific (ccxt) exceptions into these neutral
types at the adapter boundary. Consumers catch neutral types only — never
import ccxt directly for exception handling.
"""
from __future__ import annotations

from typing import Optional


class AdapterError(Exception):
    """Base for all adapter-raised errors."""
    pass


class RateLimitError(AdapterError):
    """429 / rate-limit / DDoS protection.

    retry_after_ms: epoch-ms when the ban expires (from exchange response),
    or None if unknown (caller should use a default backoff).
    """
    def __init__(self, message: str = "", retry_after_ms: Optional[int] = None):
        super().__init__(message)
        self.retry_after_ms = retry_after_ms


class AuthenticationError(AdapterError):
    """API key invalid, expired, or insufficient permissions."""
    pass


class ConnectionError(AdapterError):
    """Network-level failure: timeout, DNS, connection refused."""
    pass


class ValidationError(AdapterError):
    """Request rejected by exchange: invalid params, insufficient margin."""
    pass


class ExchangeError(AdapterError):
    """Exchange-side error: maintenance, internal error, unknown."""
    pass
