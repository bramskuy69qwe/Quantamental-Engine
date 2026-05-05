"""
Adapter registry — decorator-based registration and lookup by exchange:market_type.
"""
from __future__ import annotations

import logging
from typing import Dict, Type

from core.adapters.protocols import ExchangeAdapter, WSAdapter

log = logging.getLogger("adapters.registry")

_REST_REGISTRY: Dict[str, Type] = {}
_WS_REGISTRY: Dict[str, Type] = {}


def register_adapter(exchange_id: str, market_type: str = "linear_perpetual"):
    """Class decorator to register a REST exchange adapter."""
    def decorator(cls):
        key = f"{exchange_id}:{market_type}"
        _REST_REGISTRY[key] = cls
        log.debug("Registered REST adapter: %s -> %s", key, cls.__name__)
        return cls
    return decorator


def register_ws_adapter(exchange_id: str, market_type: str = "linear_perpetual"):
    """Class decorator to register a WS exchange adapter."""
    def decorator(cls):
        key = f"{exchange_id}:{market_type}"
        _WS_REGISTRY[key] = cls
        log.debug("Registered WS adapter: %s -> %s", key, cls.__name__)
        return cls
    return decorator


def get_rest_adapter(
    exchange_id: str,
    market_type: str,
    **kwargs,
) -> ExchangeAdapter:
    """Look up and instantiate the REST adapter for a given exchange/market pair."""
    key = f"{exchange_id}:{market_type}"
    cls = _REST_REGISTRY.get(key)
    if cls is None:
        available = list(_REST_REGISTRY.keys())
        raise ValueError(
            f"No REST adapter registered for '{key}'. "
            f"Available: {available}"
        )
    return cls(**kwargs)


def get_ws_adapter(
    exchange_id: str,
    market_type: str,
    **kwargs,
) -> WSAdapter:
    """Look up and instantiate the WS adapter for a given exchange/market pair."""
    key = f"{exchange_id}:{market_type}"
    cls = _WS_REGISTRY.get(key)
    if cls is None:
        available = list(_WS_REGISTRY.keys())
        raise ValueError(
            f"No WS adapter registered for '{key}'. "
            f"Available: {available}"
        )
    return cls(**kwargs)


def list_registered() -> Dict[str, list]:
    """Return all registered adapter keys (for diagnostics)."""
    return {
        "rest": list(_REST_REGISTRY.keys()),
        "ws": list(_WS_REGISTRY.keys()),
    }
