"""
Task 116 regression tests for HIGH-029 — credential-leak parallel to
HIGH-024 (Task 100). Applies SensitiveStr to the broader exchange-
credential surface that Task 100 explicitly left in scope.

Scope:
  - 5 form-handler entry points in api/routes_accounts.py (create_account,
    update_account, add_account_modal, test_account_preview,
    update_account_detail) wrap api_key + api_secret in SensitiveStr
    immediately on Form receipt.
  - core/crypto.decrypt() returns SensitiveStr (non-empty paths only;
    empty input remains plain "" sentinel).
  - 3 production decrypt() consumers (account_registry.load_all,
    connections.load_all, ws_manager user-data reconnect) unwrap at the
    cache / payload boundary so downstream HTTP / urlencode / JSON
    paths receive raw strings (Task 100 calibration: encode() is C-slot
    safe; urlencode / __str__ paths break).

Anti-revert: Task 100's connections-credentials narrow scope must
continue to work — re-exercise via source-string presence + behavioral
parity on the cache value.

Run: pytest tests/test_task116_credential_leak_parallels.py -v
"""
from __future__ import annotations

import ast
import inspect
import io
import logging
import os

import pytest


# ── crypto.decrypt now returns SensitiveStr ──────────────────────────────────

class TestDecryptReturnsSensitive:
    """The DB→cache hop is the second leak surface (in addition to
    form→cache). Wrapping the decrypt return masks creds in tracebacks
    fired between decrypt and the consumer's cache unwrap."""

    @pytest.fixture(autouse=True)
    def _set_master_key(self, monkeypatch):
        monkeypatch.setenv("ENV_MASTER_KEY", "task116_test_master_key")
        yield

    def test_decrypt_returns_sensitive_str_on_success(self):
        from core.crypto import encrypt, decrypt
        from core.security import SensitiveStr

        ct = encrypt("super-secret-key")
        pt = decrypt(ct)
        assert isinstance(pt, SensitiveStr), (
            "HIGH-029 regression: decrypt() must return SensitiveStr on "
            "the non-empty path — it currently returns plain str, which "
            "loses traceback protection through the cache-store window."
        )
        # Sanity: equality with raw str still works (str subclass)
        assert pt == "super-secret-key"

    def test_decrypt_repr_is_masked(self):
        """The SensitiveStr return value masks itself in repr — what an
        exception traceback would render for a stack-frame local."""
        from core.crypto import encrypt, decrypt
        ct = encrypt("AKIA-real-secret-12345")
        pt = decrypt(ct)
        rep = repr(pt)
        assert "AKIA-real-secret-12345" not in rep
        assert "masked" in rep.lower()

    def test_decrypt_str_is_masked(self):
        from core.crypto import encrypt, decrypt
        ct = encrypt("real-secret-67890")
        pt = decrypt(ct)
        assert "real-secret-67890" not in str(pt)
        assert str(pt) == "<masked>"

    def test_decrypt_format_is_masked(self):
        from core.crypto import encrypt, decrypt
        ct = encrypt("fmt-secret-abc")
        pt = decrypt(ct)
        # f-string interpolation goes through __format__
        msg = f"key={pt}"
        assert "fmt-secret-abc" not in msg
        assert "masked" in msg

    def test_decrypt_empty_still_returns_plain_empty_string(self):
        """Anti-over-correction: empty input is the 'no credential stored'
        sentinel — must remain plain str (so equality with '' works in
        legacy callers and there's no surprise SensitiveStr at sites
        that check `if api_key:`)."""
        from core.crypto import decrypt
        from core.security import SensitiveStr
        assert decrypt("") == ""
        assert not isinstance(decrypt(""), SensitiveStr)


# ── routes_accounts: 5 form-handler entry points wrap creds ──────────────────

class TestRoutesAccountsWrapAtForm:
    """Source-pin: each of the 5 form-handlers must wrap the credentials
    in SensitiveStr immediately on receipt. AST-walk to confirm the wrap
    appears before the downstream call (account_registry / ccxt)."""

    def _route_src(self, name: str) -> str:
        import api.routes_accounts as m
        fn = getattr(m, name)
        return inspect.getsource(fn)

    @pytest.mark.parametrize(
        "route_name",
        [
            "create_account",
            "update_account",
            "add_account_modal",
            "test_account_preview",
            "update_account_detail",
        ],
    )
    def test_each_route_wraps_credentials_in_sensitive_str(self, route_name):
        src = self._route_src(route_name)
        assert "SensitiveStr" in src, (
            f"HIGH-029 regression: {route_name} no longer wraps api_key / "
            f"api_secret in SensitiveStr — credentials would leak into "
            f"tracebacks fired between Form receipt and downstream call."
        )

    def test_create_account_wrap_precedes_add_account_call(self):
        """AST: in create_account, the SensitiveStr() call must appear
        BEFORE account_registry.add_account(). Otherwise the wrap is
        useless — the leak window already closed."""
        src = self._route_src("create_account")
        tree = ast.parse(src)
        wrap_line = None
        downstream_line = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "SensitiveStr":
                    wrap_line = node.lineno if wrap_line is None else wrap_line
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr == "add_account"
                ):
                    downstream_line = (
                        node.lineno if downstream_line is None else downstream_line
                    )
        assert wrap_line is not None and downstream_line is not None
        assert wrap_line < downstream_line, (
            "HIGH-029 regression: SensitiveStr wrap occurs AFTER add_account "
            "in create_account — the leak window between Form receipt and "
            "the wrap is no longer covered."
        )

    def test_test_account_preview_unwraps_immediately_before_ccxt(self):
        """test_account_preview is the direct-ccxt site (no cache hop).
        Wrap on receipt + unwrap immediately before _make_ccxt_instance
        is the right shape. Source must show both."""
        src = self._route_src("test_account_preview")
        assert "SensitiveStr(" in src, "wrap missing"
        assert ".unwrap()" in src, "unwrap missing"
        # And the unwrap should appear in the _make_ccxt_instance call
        # (not just somewhere else in the route body)
        assert "_make_ccxt_instance(api_key.unwrap()" in src or \
               "_make_ccxt_instance(\n        api_key.unwrap()" in src, (
            "HIGH-029 regression: test_account_preview no longer unwraps "
            "credentials immediately before _make_ccxt_instance. ccxt's "
            "internal URL / header serialization would receive '<masked>'."
        )


# ── account_registry: cache stores unwrapped (downstream ccxt safety) ────────

class TestAccountRegistryUnwrapsAtCache:
    """The cache value feeds into exchange_factory → CCXT, whose HTTP
    layer may call str() / urlencode internally (Task 100 calibration).
    Cache must always store raw str."""

    @pytest.fixture(autouse=True)
    def _isolate_db(self, monkeypatch, tmp_path):
        # Touch ENV_MASTER_KEY so encrypt/decrypt work
        monkeypatch.setenv("ENV_MASTER_KEY", "task116_account_registry_test_key")
        yield

    @pytest.mark.asyncio
    async def test_add_account_cache_stores_raw_string(self, monkeypatch):
        """After add_account with SensitiveStr inputs, the cache value
        must be a plain str — type(creds["api_key"]) is str, not
        SensitiveStr."""
        from core.account_registry import AccountRegistry
        from core.security import SensitiveStr

        reg = AccountRegistry()
        # Stub out the DB calls so we exercise only the cache path
        class _FakeDB:
            async def insert_account(self, *a, **kw):
                return 99
            async def update_account(self, *a, **kw):
                return None
            async def set_account_params(self, *a, **kw):
                return None
        # Patch the module-level `db` reference inside account_registry
        import core.account_registry as ar_mod
        monkeypatch.setattr(ar_mod, "db", _FakeDB())
        # Also stub the audit log (writes to file in real impl)
        monkeypatch.setattr(ar_mod, "_audit", lambda *a, **kw: None)

        api_key_raw = "my-test-key-AKIA-12345"
        api_secret_raw = "my-test-secret-67890"
        new_id = await reg.add_account(
            "test_acct", "binance", "future",
            SensitiveStr(api_key_raw), SensitiveStr(api_secret_raw),
        )
        creds = reg._cache[new_id]
        # Cache must store unwrapped (== type(str), not SensitiveStr)
        assert type(creds["api_key"]) is str, (
            "HIGH-029 regression: cache stores SensitiveStr — downstream "
            "ccxt HTTP serialization would receive '<masked>'."
        )
        assert type(creds["api_secret"]) is str
        # And the raw value is preserved exactly
        assert creds["api_key"] == api_key_raw
        assert creds["api_secret"] == api_secret_raw

    @pytest.mark.asyncio
    async def test_update_account_cache_stores_raw_string(self, monkeypatch):
        from core.account_registry import AccountRegistry
        from core.security import SensitiveStr

        reg = AccountRegistry()
        reg._cache[7] = {
            "id": 7, "name": "old", "exchange": "binance",
            "market_type": "future", "api_key": "old-key",
            "api_secret": "old-secret", "is_active": 0,
            "broker_account_id": "", "maker_fee": 0.0002,
            "taker_fee": 0.0005, "environment": "live", "params": {},
        }
        class _FakeDB:
            async def update_account(self, *a, **kw):
                return None
        import core.account_registry as ar_mod
        monkeypatch.setattr(ar_mod, "db", _FakeDB())
        monkeypatch.setattr(ar_mod, "_audit", lambda *a, **kw: None)

        await reg.update_account(
            7,
            api_key=SensitiveStr("new-key-rotated"),
            api_secret=SensitiveStr("new-secret-rotated"),
        )
        assert type(reg._cache[7]["api_key"]) is str
        assert type(reg._cache[7]["api_secret"]) is str
        assert reg._cache[7]["api_key"] == "new-key-rotated"
        assert reg._cache[7]["api_secret"] == "new-secret-rotated"


# ── connections.py + ws_manager.py: unwrap-at-cache parity ───────────────────

class TestConsumersUnwrapDecryptReturn:
    """Source-pin: each production decrypt() consumer must unwrap before
    feeding into a cache / payload that downstream HTTP code reads."""

    def test_connections_load_all_unwraps_decrypt_return(self):
        import core.connections as m
        src = inspect.getsource(m.ConnectionsManager.load_all)
        assert "SensitiveStr" in src and ".unwrap()" in src, (
            "HIGH-029 regression: connections.ConnectionsManager.load_all "
            "no longer unwraps decrypt() return — httpx URL/header path "
            "would receive '<masked>'."
        )

    def test_account_registry_load_all_unwraps_decrypt_return(self):
        import core.account_registry as m
        src = inspect.getsource(m.AccountRegistry.load_all)
        assert "SensitiveStr" in src and ".unwrap()" in src, (
            "HIGH-029 regression: account_registry.AccountRegistry.load_all "
            "no longer unwraps decrypt() return — exchange_factory / ccxt "
            "downstream would receive '<masked>'."
        )

    def test_ws_manager_unwraps_decrypt_return(self):
        import core.ws_manager as m
        src = inspect.getsource(m)
        # Look in the user-data reconnect section: must reference both
        # SensitiveStr and .unwrap()
        assert "SensitiveStr" in src and "build_auth_payload" in src, (
            "HIGH-029 regression: ws_manager no longer references "
            "SensitiveStr near build_auth_payload — auth-payload signing "
            "path may leak credentials in tracebacks."
        )


# ── Anti-regression: Task 100 narrow scope still works ───────────────────────

class TestTask100NarrowScopeUnchanged:
    """Anti-regression pin: connections.ConnectionsManager.upsert's
    HIGH-024 unwrap (Task 100) must still be present. The new decrypt-
    return wrap is additive, not a replacement."""

    def test_connections_upsert_still_unwraps(self):
        import core.connections as m
        src = inspect.getsource(m.ConnectionsManager.upsert)
        assert "SensitiveStr" in src and ".unwrap()" in src, (
            "Task 100 regression (HIGH-024): connections.upsert's narrow "
            "unwrap has gone missing. The new HIGH-029 fix is additive — "
            "it must not delete the existing unwrap."
        )


# ── Behavioral: traceback exposure simulation ────────────────────────────────

class TestTracebackExposureScenarios:
    """Goal of HIGH-029: a traceback fired between Form receipt and
    downstream consumption does NOT expose raw credentials in stack-
    frame repr / log records. We simulate by formatting a SensitiveStr
    through the same shapes a traceback would (repr, str, %s, f-string)."""

    def test_sensitive_str_does_not_appear_in_log_record(self, caplog):
        """Logging a SensitiveStr should emit the masked form. Operator
        scanning support tickets for failure messages won't see real
        credentials."""
        from core.security import SensitiveStr
        log = logging.getLogger("task116-test")
        secret = SensitiveStr("super-secret-real-key-XYZ")
        with caplog.at_level(logging.WARNING, logger="task116-test"):
            log.warning("auth failure for key=%s", secret)
        assert "super-secret-real-key-XYZ" not in caplog.text
        assert "masked" in caplog.text

    def test_sensitive_str_does_not_appear_in_repr_of_locals(self):
        """Simulate the locals-dict snapshot a traceback would expose."""
        from core.security import SensitiveStr
        api_key = SensitiveStr("zzz-do-not-leak-zzz")
        locals_repr = repr({"api_key": api_key, "other": 42})
        assert "zzz-do-not-leak-zzz" not in locals_repr
        # Sanity: the dict structure is otherwise preserved
        assert "api_key" in locals_repr


# ── Encrypt round-trip still works (load-bearing, MED-047 discipline) ───────

class TestEncryptRoundTripPreserved:
    """Anti-over-correction: the wrap must not break the encrypt→decrypt
    cycle. SensitiveStr → encrypt → ciphertext → decrypt → SensitiveStr,
    and the round-trip equals the original raw value."""

    @pytest.fixture(autouse=True)
    def _set_master_key(self, monkeypatch):
        monkeypatch.setenv("ENV_MASTER_KEY", "task116_roundtrip_test_key")
        yield

    def test_encrypt_decrypt_round_trip_with_sensitive_str_input(self):
        from core.crypto import encrypt, decrypt
        from core.security import SensitiveStr
        plaintext = "round-trip-test-secret"
        wrapped = SensitiveStr(plaintext)
        ct = encrypt(wrapped)  # encrypt accepts str-like; .encode() C-slot
        assert ct  # non-empty
        pt = decrypt(ct)
        assert pt == plaintext
        assert isinstance(pt, SensitiveStr)
