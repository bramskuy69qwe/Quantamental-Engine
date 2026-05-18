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


# FE-HIGH-002 (Task 111): canonical (non-Beta) exchanges. Anything registered
# but not listed here renders with a "(Beta)" suffix in the Add Account
# modal — operator-verified production-trading status determines membership.
# When an adapter graduates from Beta (e.g., after Phase 5 Bundle B verifies
# Bybit / MEXC end-to-end), add its exchange_id here.
_CANONICAL_EXCHANGES = frozenset({"binance"})

# Display-label overrides for exchanges where simple title-case is wrong.
# Most exchange IDs are lowercase and title-case correctly; capitalize
# acronyms here.
_EXCHANGE_LABEL_OVERRIDES = {
    "mexc": "MEXC",
}


def list_rest_exchanges(market_type: str = "linear_perpetual") -> list:
    """FE-HIGH-002 (Task 111): list registered REST exchanges for the
    Add Account modal dropdown.

    Returns a list of dicts shaped for direct template iteration:
        [{"value": "binance", "label": "Binance",       "is_beta": False},
         {"value": "bybit",   "label": "Bybit (Beta)",  "is_beta": True},
         {"value": "mexc",    "label": "MEXC (Beta)",   "is_beta": True}]

    Sort order: canonical exchanges first (alphabetical), then Beta
    exchanges (alphabetical). Canonical-first means Binance always appears
    at the top of the dropdown so the default selection is operator-friendly.

    Filtered by ``market_type``: only adapters registered under the given
    market type appear. Default ``linear_perpetual`` matches all current
    adapters (binance / bybit / mexc).
    """
    rows = []
    for key in _REST_REGISTRY.keys():
        exchange_id, mt = key.split(":", 1)
        if mt != market_type:
            continue
        is_beta = exchange_id not in _CANONICAL_EXCHANGES
        base_label = _EXCHANGE_LABEL_OVERRIDES.get(
            exchange_id, exchange_id.title()
        )
        label = f"{base_label} (Beta)" if is_beta else base_label
        rows.append({
            "value":   exchange_id,
            "label":   label,
            "is_beta": is_beta,
        })
    rows.sort(key=lambda r: (r["is_beta"], r["value"]))
    return rows
