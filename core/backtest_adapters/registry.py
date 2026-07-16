"""
Backtest-adapter registry — decorator-based registration + lookup by
app_id (v2.7 Phase 2). Mirrors core/adapters/registry.py.
"""
from __future__ import annotations

import logging
from typing import Dict, List, Type

log = logging.getLogger("backtest_adapters.registry")

_REGISTRY: Dict[str, Type] = {}


def register_backtest_adapter(app_id: str):
    """Class decorator to register a backtest-import adapter."""
    def decorator(cls):
        _REGISTRY[app_id] = cls
        log.debug("Registered backtest adapter: %s -> %s", app_id, cls.__name__)
        return cls
    return decorator


def get_backtest_adapter(app_id: str):
    """Look up and instantiate the adapter for an app_id."""
    cls = _REGISTRY.get(app_id)
    if cls is None:
        available = sorted(_REGISTRY.keys())
        raise ValueError(
            f"No backtest adapter registered for '{app_id}'. "
            f"Available: {available}"
        )
    return cls()


def list_backtest_adapters() -> List[Dict[str, object]]:
    """All registered adapters, shaped for the upload dropdown (task 3.4):
    [{"app_id", "display_name", "accepted_extensions"}], sorted by app_id."""
    rows = []
    for app_id in sorted(_REGISTRY.keys()):
        cls = _REGISTRY[app_id]
        rows.append({
            "app_id": app_id,
            "display_name": getattr(cls, "display_name", app_id.title()),
            "accepted_extensions": list(getattr(cls, "accepted_extensions", ())),
        })
    return rows
