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


def is_valid_rest_exchange(
    exchange_id: str, market_type: str = "linear_perpetual"
) -> bool:
    """MED-048 (Task 114): server-side whitelist check for client-supplied
    exchange values.

    Strict, case-sensitive: only the exact lowercase IDs used at adapter
    registration match. Every registered adapter uses a lowercase key
    (``binance``, ``bybit``, ``mexc``); accepting case variants would only
    hide frontend bugs that pass through non-canonical strings. Reject
    rather than normalize.
    """
    if not isinstance(exchange_id, str) or not exchange_id:
        return False
    return f"{exchange_id}:{market_type}" in _REST_REGISTRY


def is_valid_market_type(market_type: str) -> bool:
    """MED-049 (Task 119): server-side whitelist check for client-supplied
    ``market_type`` form fields.

    Accepts engine-canonical market types (any registered adapter key)
    plus the legacy DB alias ``future`` (which `map_market_type` rewrites
    to `linear_perpetual`). Strict, case-sensitive — matches the
    MED-048 case-sensitivity decision for `exchange`.
    """
    if not isinstance(market_type, str) or not market_type:
        return False
    if market_type == "future":
        # Legacy DB alias — map_market_type rewrites this to linear_perpetual,
        # which is currently the only registered market_type. Accept as long
        # as at least one adapter is registered under linear_perpetual.
        return any(k.endswith(":linear_perpetual") for k in _REST_REGISTRY)
    # Canonical form — must appear as the suffix of at least one registered
    # adapter key.
    return any(k.split(":", 1)[1] == market_type for k in _REST_REGISTRY)


def get_supported_market_types() -> list:
    """MED-049 (Task 119): flat list of accepted market_type form values
    (canonical + legacy aliases). Used to build operator-friendly error
    messages."""
    canonical = sorted(
        {k.split(":", 1)[1] for k in _REST_REGISTRY}
    )
    # Surface the legacy alias when it routes to a registered adapter.
    has_linear = "linear_perpetual" in canonical
    legacy = ["future"] if has_linear else []
    return legacy + canonical


def get_supported_rest_exchanges(market_type: str = "linear_perpetual") -> list:
    """MED-048 (Task 114): flat list of exchange_id strings for a given
    market_type — used to build operator-friendly error messages when
    validation rejects a client-supplied value."""
    out = []
    for key in _REST_REGISTRY.keys():
        ex_id, mt = key.split(":", 1)
        if mt == market_type:
            out.append(ex_id)
    return sorted(set(out))


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
