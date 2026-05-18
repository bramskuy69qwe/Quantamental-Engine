"""
Sensitive value wrappers — mask credentials in repr/str/format paths.

HIGH-024 (Task 100): credentials leaked into tracebacks if an exception fired
between form-receipt and DB-encryption. SensitiveStr is a str subclass: the
underlying bytes operations (encode, slicing, hashing) work transparently via
C-level slots, so HMAC code that calls ``key.encode()`` is unaffected. Only
the Python-level repr/str/format paths see the masked representation.

Caveat — URL/header serialization breaks under SensitiveStr:
  urllib.parse.urlencode({"k": SensitiveStr("v")}) → "k=%3Cmasked%3E"
  httpx.URL("https://x", params={...}) calls __str__ on values → masked
Anywhere a SensitiveStr would be serialized into an HTTP request URL or
header, call ``.unwrap()`` first. The narrow Task-100 fix avoids this trap
by unwrapping before the credential reaches the in-memory cache consumed by
core/connections._test_provider's httpx calls.
"""
from __future__ import annotations


class SensitiveStr(str):
    """str subclass that masks itself in repr/str/format.

    Drop-in for credential strings within scopes where the value might be
    exposed in tracebacks (e.g., function arguments shown in stack frames,
    f-string interpolation in error messages, log records). Use ``unwrap()``
    to recover the raw value at boundaries that require it.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return f"<SensitiveStr len={len(self)} masked>"

    def __str__(self) -> str:
        return "<masked>"

    def __format__(self, spec: str) -> str:
        return "<masked>"

    def unwrap(self) -> str:
        """Return the underlying plain string value.

        Use only at boundaries that require the raw value (URL / header
        serialization, dict storage that feeds urlencode/httpx, etc.).
        Prefer letting .encode() and other C-slot operations work directly
        on the SensitiveStr instance — those bypass the Python-level
        __str__ override.
        """
        return str.__str__(self)
