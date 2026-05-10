"""
SR-7 Step 3 regression tests — SupportsListenKey + auth model.

Validates:
1. SupportsListenKey protocol exists and Binance implements it
2. Bybit does NOT implement SupportsListenKey (no stubs)
3. WSAdapter has post-connect auth methods
4. Consumer isinstance guards route correctly per adapter

Run: pytest tests/test_sr7_step3_listen_key.py -v
"""
from __future__ import annotations

import pytest


class TestSupportsListenKeyProtocol:
    def test_protocol_exists(self):
        from core.adapters.protocols import SupportsListenKey
        assert hasattr(SupportsListenKey, "create_listen_key")
        assert hasattr(SupportsListenKey, "keepalive_listen_key")

    def test_binance_implements(self):
        from core.adapters.protocols import SupportsListenKey
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
        # isinstance check on the class (Protocol uses structural typing)
        # Verify methods exist on the class
        assert hasattr(BinanceUSDMAdapter, "create_listen_key")
        assert hasattr(BinanceUSDMAdapter, "keepalive_listen_key")

    def test_bybit_does_not_implement(self):
        """Bybit adapter must NOT have create_listen_key or keepalive_listen_key."""
        from core.adapters.bybit.rest_adapter import BybitLinearAdapter
        # After SR-7 Step 3, these stubs should be removed
        assert not hasattr(BybitLinearAdapter, "create_listen_key"), \
            "Bybit must not have create_listen_key stub"
        assert not hasattr(BybitLinearAdapter, "keepalive_listen_key"), \
            "Bybit must not have keepalive_listen_key stub"

    def test_listen_key_not_on_base_protocol(self):
        """ExchangeAdapter must NOT have create_listen_key or keepalive_listen_key."""
        import inspect
        from core.adapters.protocols import ExchangeAdapter
        source = inspect.getsource(ExchangeAdapter)
        assert "create_listen_key" not in source, \
            "create_listen_key must be on SupportsListenKey, not ExchangeAdapter"
        assert "keepalive_listen_key" not in source, \
            "keepalive_listen_key must be on SupportsListenKey, not ExchangeAdapter"


class TestWSAdapterAuthMethods:
    def test_requires_post_connect_auth_exists(self):
        """WSAdapter protocol must define requires_post_connect_auth."""
        import inspect
        from core.adapters.protocols import WSAdapter
        source = inspect.getsource(WSAdapter)
        assert "requires_post_connect_auth" in source

    def test_build_auth_payload_exists(self):
        """WSAdapter protocol must define build_auth_payload."""
        import inspect
        from core.adapters.protocols import WSAdapter
        source = inspect.getsource(WSAdapter)
        assert "build_auth_payload" in source

    def test_build_subscribe_payload_exists(self):
        """WSAdapter protocol must define build_subscribe_payload."""
        import inspect
        from core.adapters.protocols import WSAdapter
        source = inspect.getsource(WSAdapter)
        assert "build_subscribe_payload" in source

    def test_binance_ws_no_post_connect_auth(self):
        """Binance WS adapter: requires_post_connect_auth should return False."""
        from core.adapters.binance.ws_adapter import BinanceWSAdapter
        ws = BinanceWSAdapter()
        assert ws.requires_post_connect_auth() is False

    def test_bybit_ws_requires_post_connect_auth(self):
        """Bybit WS adapter: requires_post_connect_auth should return True."""
        from core.adapters.bybit.ws_adapter import BybitWSAdapter
        ws = BybitWSAdapter()
        assert ws.requires_post_connect_auth() is True


class TestConsumerListenKeyGuards:
    """Consumers must guard listen-key calls with isinstance check."""

    def test_create_listen_key_has_isinstance_guard(self):
        """exchange.py create_listen_key must check SupportsListenKey."""
        import inspect
        from core import exchange
        source = inspect.getsource(exchange.create_listen_key)
        assert "SupportsListenKey" in source, \
            "create_listen_key must guard with isinstance(adapter, SupportsListenKey)"

    def test_keepalive_listen_key_has_isinstance_guard(self):
        """exchange.py keepalive_listen_key must check SupportsListenKey."""
        import inspect
        from core import exchange
        source = inspect.getsource(exchange.keepalive_listen_key)
        assert "SupportsListenKey" in source, \
            "keepalive_listen_key must guard with isinstance(adapter, SupportsListenKey)"
