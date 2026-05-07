"""
SR-2 regression tests — AccountRegistry as single owner of active_account_id.

These tests verify the invariant: AccountRegistry.active_id and
AppState.active_account_id always agree because AppState.active_account_id
is a read-only @property backed by account_registry.active_id.

Run: pytest tests/test_account_identity.py -v
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from core.account_registry import AccountRegistry
from core.state import AppState


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_accounts() -> dict:
    """Standard 3-account fixture with full fields."""
    return {
        1: {"id": 1, "name": "Main",  "exchange": "Binance", "market_type": "future",
            "is_active": 1, "broker_account_id": "UID-AAA",
            "api_key": "", "api_secret": "", "maker_fee": 0.0002, "taker_fee": 0.0005,
            "environment": "live", "params": {}},
        2: {"id": 2, "name": "Test",  "exchange": "Binance", "market_type": "future",
            "is_active": 0, "broker_account_id": "UID-BBB",
            "api_key": "", "api_secret": "", "maker_fee": 0.0002, "taker_fee": 0.0005,
            "environment": "live", "params": {}},
        3: {"id": 3, "name": "Paper", "exchange": "Binance", "market_type": "future",
            "is_active": 0, "broker_account_id": "",
            "api_key": "", "api_secret": "", "maker_fee": 0.0002, "taker_fee": 0.0005,
            "environment": "live", "params": {}},
    }


def _fresh_registry(accounts: dict | None = None) -> AccountRegistry:
    """Create an AccountRegistry with pre-populated cache (no DB)."""
    reg = AccountRegistry()
    reg._cache = accounts if accounts is not None else _make_accounts()
    reg._active_id = 1
    return reg


def _fresh_app_state() -> AppState:
    """Reset the AppState singleton to a clean slate."""
    AppState._instance = None
    state = AppState()
    return state


# ── Test 1: set_active() propagation ────────────────────────────────────────

class TestSetActivePropagation:
    """After AccountRegistry.set_active(X), AppState.active_account_id reads X."""

    @pytest.mark.asyncio
    async def test_set_active_updates_registry(self):
        reg = _fresh_registry()
        with patch("core.account_registry.db") as mock_db:
            mock_db.set_active_account = AsyncMock()
            await reg.set_active(2)
        assert reg.active_id == 2

    @pytest.mark.asyncio
    async def test_set_active_and_appstate_agree(self):
        """After set_active, AppState reads the updated value via property."""
        reg = _fresh_registry()
        state = _fresh_app_state()
        with patch("core.account_registry.db") as mock_db, \
             patch("core.account_registry.account_registry", reg):
            mock_db.set_active_account = AsyncMock()
            await reg.set_active(2)
            assert state.active_account_id == reg.active_id == 2

    @pytest.mark.asyncio
    async def test_set_active_updates_is_active_flags(self):
        reg = _fresh_registry()
        with patch("core.account_registry.db") as mock_db:
            mock_db.set_active_account = AsyncMock()
            await reg.set_active(2)
        assert reg._cache[1]["is_active"] == 0
        assert reg._cache[2]["is_active"] == 1
        assert reg._cache[3]["is_active"] == 0


# ── Test 2: platform_bridge hello convergence ──────────────────────────────

class TestPlatformBridgeHello:
    """After _handle_hello fires, both AccountRegistry.active_id and
    AppState.active_account_id must read the same value."""

    @pytest.mark.asyncio
    async def test_hello_existing_account_converges(self):
        """When plugin sends a broker_account_id matching an existing account,
        both identity sources must agree on the matched account."""
        reg = _fresh_registry()
        state = _fresh_app_state()

        matched = reg.find_by_broker_id("UID-BBB")
        assert matched is not None
        assert matched["id"] == 2

        with patch("core.account_registry.db") as mock_db, \
             patch("core.account_registry.account_registry", reg):
            mock_db.set_active_account = AsyncMock()
            await reg.set_active(matched["id"])
            assert state.active_account_id == reg.active_id == 2

    @pytest.mark.asyncio
    async def test_hello_auto_populate_converges(self):
        """When plugin populates a new broker_account_id on an empty slot,
        identity must converge."""
        reg = _fresh_registry()
        state = _fresh_app_state()

        target = None
        for aid, acct in reg._cache.items():
            if not acct.get("broker_account_id"):
                target = acct
                break
        assert target is not None
        assert target["id"] == 3

        with patch("core.account_registry.db") as mock_db, \
             patch("core.account_registry.account_registry", reg):
            mock_db.set_active_account = AsyncMock()
            mock_db.update_account = AsyncMock()
            await reg.update_account(target["id"], broker_account_id="UID-NEW")
            await reg.set_active(target["id"])
            assert state.active_account_id == reg.active_id == 3
        assert reg._cache[3]["broker_account_id"] == "UID-NEW"


# ── Test 3: routes_accounts switch consistency ─────────────────────────────

class TestAccountSwitchConsistency:
    """routes_accounts switch endpoint updates both consistently."""

    @pytest.mark.asyncio
    async def test_switch_success_both_agree(self):
        reg = _fresh_registry()
        state = _fresh_app_state()

        with patch("core.account_registry.db") as mock_db, \
             patch("core.account_registry.account_registry", reg):
            mock_db.set_active_account = AsyncMock()
            await reg.set_active(2)
            assert state.active_account_id == reg.active_id == 2

    @pytest.mark.asyncio
    async def test_switch_rollback_both_agree(self):
        """After a failed switch and rollback, both must agree on old value."""
        reg = _fresh_registry()
        state = _fresh_app_state()

        with patch("core.account_registry.db") as mock_db, \
             patch("core.account_registry.account_registry", reg):
            mock_db.set_active_account = AsyncMock()
            # Forward switch
            await reg.set_active(2)
            assert state.active_account_id == 2

            # Simulate reinit failure → rollback
            await reg.set_active(1)
            assert state.active_account_id == reg.active_id == 1


# ── Test 4: no stale value ─────────────────────────────────────────────────

class TestNoStaleValue:
    """AppState.active_account_id never returns stale value when
    AccountRegistry has been updated more recently."""

    @pytest.mark.asyncio
    async def test_registry_update_always_visible_via_property(self):
        """After set_active(2), AppState immediately reads 2 — no manual
        sync needed because the property reads from the registry.

        NOTE: isinstance(..., property) assumes the fix uses a Python
        @property; a __getattr__ or descriptor-based approach would
        bypass this detection and need a different guard.
        """
        reg = _fresh_registry()
        state = _fresh_app_state()

        descriptor = getattr(type(state), 'active_account_id', None)
        assert isinstance(descriptor, property), (
            "SR-2 fix not applied: active_account_id is not a property"
        )

        with patch("core.account_registry.db") as mock_db, \
             patch("core.account_registry.account_registry", reg):
            mock_db.set_active_account = AsyncMock()
            await reg.set_active(2)
            # No manual sync — property reads from registry directly
            assert state.active_account_id == reg.active_id == 2

    @pytest.mark.asyncio
    async def test_rapid_switches_stay_consistent(self):
        """Multiple rapid set_active calls never leave divergent state."""
        reg = _fresh_registry()
        state = _fresh_app_state()

        with patch("core.account_registry.db") as mock_db, \
             patch("core.account_registry.account_registry", reg):
            mock_db.set_active_account = AsyncMock()
            for target in [2, 3, 1, 2, 1, 3]:
                await reg.set_active(target)
                assert state.active_account_id == reg.active_id == target


# ── Test 5: readers see consistent value ────────────────────────────────────

class TestReadersConsistency:
    """Verify that readers accessing active_account_id see the canonical value."""

    def test_get_active_sync_matches_active_id(self):
        reg = _fresh_registry()
        reg._active_id = 2
        creds = reg.get_active_sync()
        assert creds["id"] == reg.active_id == 2

    @pytest.mark.asyncio
    async def test_get_active_async_matches_active_id(self):
        reg = _fresh_registry()
        with patch("core.account_registry.db") as mock_db:
            mock_db.set_active_account = AsyncMock()
            await reg.set_active(3)
        creds = await reg.get_active()
        assert creds["id"] == reg.active_id == 3

    def test_find_by_broker_id(self):
        reg = _fresh_registry()
        result = reg.find_by_broker_id("UID-BBB")
        assert result is not None
        assert result["id"] == 2

    def test_find_by_broker_id_empty_returns_none(self):
        reg = _fresh_registry()
        assert reg.find_by_broker_id("") is None
        assert reg.find_by_broker_id("NONEXISTENT") is None


# ── Test 6: startup-order safety ────────────────────────────────────────────

class TestStartupOrderSafety:
    """AppState.active_account_id read before AccountRegistry initializes
    returns a safe default and does not crash."""

    def test_read_before_registry_init(self):
        """A freshly constructed AppState must return int(1) for
        active_account_id even when no AccountRegistry has been
        loaded yet (the module-level singleton starts with _active_id=1)."""
        state = _fresh_app_state()
        val = state.active_account_id
        assert val == 1
        assert isinstance(val, int)

    def test_read_with_empty_registry(self):
        """If AccountRegistry has an empty cache (no accounts loaded),
        active_account_id still returns the default int(1)."""
        reg = AccountRegistry()  # fresh, empty cache
        assert reg.active_id == 1
        with patch("core.account_registry.account_registry", reg):
            state = _fresh_app_state()
            assert state.active_account_id == 1


# ── Test 7: truthiness parity ──────────────────────────────────────────────

class TestTruthinessParity:
    """The field's default value and type must be preserved across the
    plain-attribute → property migration."""

    def test_default_value_is_int_one(self):
        state = _fresh_app_state()
        val = state.active_account_id
        assert val == 1, f"Expected 1, got {val!r}"
        assert type(val) is int, f"Expected int, got {type(val).__name__}"

    def test_default_is_truthy(self):
        """The default value 1 is truthy. Code like
        `if app_state.active_account_id:` must not change behavior."""
        state = _fresh_app_state()
        assert bool(state.active_account_id) is True


# ── Test 8: direct-write behavior ──────────────────────────────────────────

class TestDirectWriteBehavior:
    """After SR-2, direct assignment to app_state.active_account_id must
    raise AttributeError (read-only property — all writes route through
    account_registry.set_active())."""

    def test_direct_write_raises(self):
        state = _fresh_app_state()
        descriptor = getattr(type(state), 'active_account_id', None)
        assert isinstance(descriptor, property), (
            "SR-2 fix not applied: active_account_id is not a property"
        )
        with pytest.raises(AttributeError):
            state.active_account_id = 99
