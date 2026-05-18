"""
Task 100 regression tests for HIGH-024 (credential traceback leak).

HIGH-024 narrow scope: api/routes_connections.upsert_connection wraps the
form-supplied api_key in SensitiveStr before invoking
connections_manager.upsert, so any exception raised during encrypt() or the
DB write shows the masked representation in the traceback frame locals
rather than the raw key.

Coverage:
- SensitiveStr semantics (repr/str/format mask; encode/HMAC bypass mask;
  unwrap returns raw; standard str operations transparent).
- End-to-end traceback proof: f-string interpolation of a SensitiveStr in
  an exception message masks the raw value.
- Wiring pin: source-pin asserting upsert_connection wraps api_key.
- Cache-unwrap pin: ConnectionsManager.upsert unwraps before cache store
  so the downstream httpx path keeps working.

Run: pytest tests/test_task100_sensitive_str.py -v
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import inspect
import textwrap
import urllib.parse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── SensitiveStr unit semantics ──────────────────────────────────────────────

class TestSensitiveStr:
    """HIGH-024: the wrapper class must mask in repr/str/format but pass
    bytes operations through unchanged."""

    def test_repr_masks_value(self):
        from core.security import SensitiveStr
        key = SensitiveStr("abc123def456")
        r = repr(key)
        assert "abc123" not in r
        assert "masked" in r.lower()

    def test_str_masks_value(self):
        from core.security import SensitiveStr
        key = SensitiveStr("abc123def456")
        assert "abc123" not in str(key)
        assert "<masked>" == str(key)

    def test_f_string_masks_value(self):
        from core.security import SensitiveStr
        key = SensitiveStr("abc123def456")
        msg = f"key={key}"
        assert "abc123" not in msg
        assert "<masked>" in msg

    def test_format_explicit_spec_still_masks(self):
        """format() with an explicit spec must still mask — anti-bypass."""
        from core.security import SensitiveStr
        key = SensitiveStr("abc123def456")
        assert "abc123" not in format(key, "")
        assert "abc123" not in format(key, ">20")  # right-pad spec

    def test_encode_returns_raw_bytes(self):
        """Load-bearing: .encode() must produce real bytes for HMAC use.
        This relies on str.encode going through a C-level slot that bypasses
        the Python-level __str__ override. If this test fails, the wrapper
        is broken — encrypt() and HMAC signing would produce <masked> bytes."""
        from core.security import SensitiveStr
        key = SensitiveStr("abc123")
        assert key.encode() == b"abc123"
        # Also verify explicit utf-8 encoding
        assert key.encode("utf-8") == b"abc123"

    def test_hmac_signing_unaffected(self):
        """Real-world sanity: HMAC over a SensitiveStr key must match the
        same operation over the plain str — encryption/signing is the
        single most important thing not to break."""
        from core.security import SensitiveStr
        plain = "secret_key_material"
        wrapped = SensitiveStr(plain)
        sig_plain = hmac.new(plain.encode(), b"data", hashlib.sha256).hexdigest()
        sig_wrapped = hmac.new(wrapped.encode(), b"data", hashlib.sha256).hexdigest()
        assert sig_plain == sig_wrapped

    def test_traceback_message_does_not_expose_value(self):
        """HIGH-024 audit-scenario regression: when a function using
        SensitiveStr raises, an f-string-interpolated exception message
        must not include the raw key value."""
        from core.security import SensitiveStr
        key = SensitiveStr("secret_payload_123")
        try:
            raise ValueError(f"connection failed with key: {key}")
        except ValueError as e:
            tb_msg = str(e)
            assert "secret_payload_123" not in tb_msg
            assert "masked" in tb_msg.lower()

    def test_failure_before_fix_proof_with_plain_str(self):
        """Anti-regression contrast: the same f-string with a plain str
        would have LEAKED the value. This documents the failure mode the
        fix prevents — if a future refactor reverts SensitiveStr to a
        plain str alias, this test stays passing while the masking pins
        above fail, making the regression unambiguous."""
        plain_key = "secret_payload_123"
        msg = f"connection failed with key: {plain_key}"
        assert "secret_payload_123" in msg  # leak path

    def test_unwrap_returns_raw(self):
        from core.security import SensitiveStr
        key = SensitiveStr("abc123")
        assert key.unwrap() == "abc123"
        assert type(key.unwrap()) is str  # plain str, not SensitiveStr

    def test_string_operations_still_work(self):
        """Standard str operations must remain transparent — caller code
        that uses startswith/slice/len doesn't need to know about wrapping."""
        from core.security import SensitiveStr
        key = SensitiveStr("abc123def")
        assert key.startswith("abc")
        assert key.endswith("def")
        assert "123" in key
        assert key[:3] == "abc"   # slicing returns plain str — fine
        assert len(key) == 9


# ── Wiring pin: routes_connections wraps api_key ─────────────────────────────

class TestRoutesConnectionsWiring:
    """HIGH-024 wiring pin: upsert_connection must wrap api_key in
    SensitiveStr before calling connections_manager.upsert. Source-pin
    pattern from Task 97.1."""

    def test_upsert_connection_wraps_api_key_in_sensitive_str(self):
        from api import routes_connections
        fn = getattr(routes_connections, "upsert_connection", None)
        assert fn is not None, "upsert_connection function not found"
        src = inspect.getsource(fn)
        assert "SensitiveStr" in src, (
            "HIGH-024 wiring regression: upsert_connection no longer "
            "wraps api_key in SensitiveStr. Raw credentials would propagate "
            "into traceback frames if encrypt() or the DB write raises."
        )

    def test_module_imports_sensitive_str(self):
        """Module-level import pin — catches a refactor that removes the
        SensitiveStr import but leaves a now-broken bare reference."""
        from api import routes_connections
        src = inspect.getsource(routes_connections)
        assert "from core.security import SensitiveStr" in src, (
            "HIGH-024 import pin: routes_connections must import "
            "SensitiveStr from core.security."
        )


# ── Cache-unwrap boundary in ConnectionsManager.upsert ───────────────────────

class TestConnectionsManagerUnwraps:
    """HIGH-024: ConnectionsManager.upsert must unwrap SensitiveStr before
    storing in the cache. The cache value is read by _test_provider and
    fed into httpx URL params / headers — urlencode serializes via str(),
    which would otherwise emit '<masked>' into the live HTTP request and
    break authentication."""

    @pytest.mark.asyncio
    async def test_cache_value_is_plain_str_after_upsert(self):
        from core.security import SensitiveStr
        from core.connections import ConnectionsManager

        cm = ConnectionsManager()
        # Patch DB write + encrypt to no-ops so we can exercise the cache path
        with patch("core.connections.encrypt", return_value="enc"), \
             patch("core.connections.db", MagicMock(upsert_connection=AsyncMock())), \
             patch("core.connections._audit"):
            wrapped = SensitiveStr("real_key_value")
            await cm.upsert("fred", "FRED", wrapped)

        cached = cm._cache["fred"]["api_key"]
        # Plain str, not SensitiveStr — so urlencode/httpx will see the real value
        assert type(cached) is str, (
            f"HIGH-024 regression: cache stored {type(cached).__name__}, "
            "not plain str. Downstream httpx URL/header serialization would "
            "mask the key and break the test_provider HTTP path."
        )
        assert cached == "real_key_value"

    @pytest.mark.asyncio
    async def test_plain_str_input_still_works(self):
        """Anti-over-correction: passing a plain str (e.g., from a non-route
        caller) still works — isinstance check skips the unwrap."""
        from core.connections import ConnectionsManager

        cm = ConnectionsManager()
        with patch("core.connections.encrypt", return_value="enc"), \
             patch("core.connections.db", MagicMock(upsert_connection=AsyncMock())), \
             patch("core.connections._audit"):
            await cm.upsert("fred", "FRED", "plain_key")

        assert cm._cache["fred"]["api_key"] == "plain_key"

    @pytest.mark.asyncio
    async def test_encrypt_receives_real_bytes_via_sensitive_str(self):
        """The encrypt() call inside upsert uses str.encode() under the
        hood (via Fernet). Verify the wrapped key produces the same
        encryption input as the raw key."""
        from core.security import SensitiveStr
        from core.connections import ConnectionsManager

        captured = {}
        def _fake_encrypt(s):
            captured["arg"] = s
            captured["encoded"] = s.encode() if hasattr(s, "encode") else b""
            return "enc"

        cm = ConnectionsManager()
        with patch("core.connections.encrypt", side_effect=_fake_encrypt), \
             patch("core.connections.db", MagicMock(upsert_connection=AsyncMock())), \
             patch("core.connections._audit"):
            await cm.upsert("fred", "FRED", SensitiveStr("real_key_value"))

        # encrypt() saw the SensitiveStr instance (because SensitiveStr is a str),
        # and .encode() on it produced real bytes (C-slot, not masked override).
        assert captured["encoded"] == b"real_key_value"


# ── End-to-end: traceback frame locals would show masked, not raw ────────────

class TestTracebackLocalsMasked:
    """Simulates the audit scenario: an exception in encrypt() leaves
    api_key in the upsert() frame's locals. When the traceback is
    formatted, the local would historically render the raw value via
    repr()-style display."""

    @pytest.mark.asyncio
    async def test_repr_in_simulated_traceback_frame_is_masked(self):
        """Direct proof: take a SensitiveStr local and apply the same
        machinery a traceback formatter uses (repr) — must be masked."""
        from core.security import SensitiveStr
        from core.connections import ConnectionsManager

        cm = ConnectionsManager()

        # Force encrypt() to raise, capturing the api_key local at the raise site.
        captured_locals = {}
        def _exploding_encrypt(s):
            # Mimic what a traceback formatter would do: repr the local
            captured_locals["api_key_repr"] = repr(s)
            raise RuntimeError("simulated DB write failure")

        with patch("core.connections.encrypt", side_effect=_exploding_encrypt), \
             patch("core.connections.db", MagicMock()), \
             patch("core.connections._audit"):
            wrapped = SensitiveStr("secret_to_protect")
            with pytest.raises(RuntimeError, match="simulated"):
                await cm.upsert("fred", "FRED", wrapped)

        assert "secret_to_protect" not in captured_locals["api_key_repr"], (
            "HIGH-024 audit-scenario regression: the api_key local in a "
            "raising frame still renders the raw value via repr(). The "
            "SensitiveStr wrap didn't survive into the manager's frame."
        )
        assert "masked" in captured_locals["api_key_repr"].lower()


# ── urlencode/httpx breakage acknowledgement (documents the unwrap reason) ───

class TestUrlencodeBreakageDocumented:
    """Documents the urlencode/httpx breakage that the cache-unwrap protects
    against. If someone removes the cache-unwrap in a future refactor,
    they should hit this test as the explanation of why it was there."""

    def test_urlencode_serializes_sensitive_str_as_masked(self):
        """If SensitiveStr leaked into urlencode, the HTTP request would
        carry '<masked>' as the literal value — breaking authentication."""
        from core.security import SensitiveStr
        encoded = urllib.parse.urlencode({"api_key": SensitiveStr("real")})
        # urlencode goes through str() → __str__ override → "<masked>"
        assert "real" not in encoded
        assert "masked" in encoded
        # This is why ConnectionsManager.upsert unwraps before cache store.
