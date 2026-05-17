"""
Task 94 regression tests:

HIGH-021 — RESOLVED. core/contract_validation.py:CONTRACT_SPEC_TTL_SECONDS
reduced from 24h to 4h (operator-tunable via env). New admin endpoint
POST /admin/contract-specs/refresh clears the cache on demand. Tests pin
the TTL ceiling and verify the cache-clear function works.

HIGH-025 — VERIFIED FALSE. Audit claimed partial fills don't re-enrich
parent trigger snapshots, leaving slippage measurement stale. Investigation
found:
  1. Parent's tp/sl_trigger_price IS refreshed when child TP/SL orders
     arrive via _re_enrich_parent_on_child_arrival in core/order_manager.py.
  2. _classify_and_compute_slippage reads parent FRESH from DB on every
     fill via SELECT * FROM orders ... no in-memory stale-snapshot cache.
The audit's literal claim (enrich_fill doesn't call
_populate_tp_sl_trigger_prices directly) is true but the IMPACT is false
because the snapshot is refreshed on a different event (child order
arrival, not fill arrival) and slippage reads fresh per fill anyway.

Pin tests assert both mechanisms remain wired.

Run: pytest tests/test_task94_cache_freshness_and_reenrichment.py -v
"""
from __future__ import annotations

import inspect
import os
import re

import pytest


# ── HIGH-021: contract spec TTL ceiling + force-refresh function ────────────

def test_contract_spec_ttl_under_8h_ceiling():
    """HIGH-021 pin: CONTRACT_SPEC_TTL_SECONDS must be ≤ 8h (28800s).
    24h was the audit's "too long" baseline; 4h is the Task 94 default.
    Override via CONTRACT_SPEC_TTL_SECONDS env var if needed."""
    # Re-import to ensure env-var binding at module-load time is current
    import importlib
    from core import contract_validation
    importlib.reload(contract_validation)
    assert contract_validation.CONTRACT_SPEC_TTL_SECONDS <= 8 * 3600, (
        f"CONTRACT_SPEC_TTL_SECONDS={contract_validation.CONTRACT_SPEC_TTL_SECONDS}s "
        f"exceeds 8h ceiling. HIGH-021 reduced default from 24h to 4h. If a "
        f"deployment intentionally raises this, override via env and update the test."
    )


def test_contract_spec_ttl_default_when_env_unset(monkeypatch):
    """HIGH-021 pin: default value is 4h (14400s) when env var is unset."""
    monkeypatch.delenv("CONTRACT_SPEC_TTL_SECONDS", raising=False)
    import importlib
    from core import contract_validation
    importlib.reload(contract_validation)
    assert contract_validation.CONTRACT_SPEC_TTL_SECONDS == 14400, (
        "Default TTL should be 4h (14400s) when CONTRACT_SPEC_TTL_SECONDS env unset"
    )


def test_force_refresh_specs_clears_cache():
    """HIGH-021 pin: force_refresh_specs() clears _spec_cache and returns count."""
    from core import contract_validation
    from decimal import Decimal
    from datetime import datetime, timezone

    contract_validation._spec_cache["BTCUSDT"] = contract_validation.ContractSpec(
        symbol="BTCUSDT",
        tick_size=Decimal("0.1"),
        lot_step=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        min_notional=Decimal("5"),
        fetched_at=datetime.now(timezone.utc),
    )
    contract_validation._spec_cache["ETHUSDT"] = contract_validation.ContractSpec(
        symbol="ETHUSDT",
        tick_size=Decimal("0.01"),
        lot_step=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        min_notional=Decimal("5"),
        fetched_at=datetime.now(timezone.utc),
    )
    assert len(contract_validation._spec_cache) == 2

    cleared = contract_validation.force_refresh_specs()
    assert cleared == 2
    assert len(contract_validation._spec_cache) == 0


def test_admin_force_refresh_endpoint_registered():
    """HIGH-021 pin: POST /admin/contract-specs/refresh route is registered."""
    from api.routes_admin import router
    paths = {route.path for route in router.routes}
    assert "/admin/contract-specs/refresh" in paths, (
        f"Admin force-refresh endpoint missing. Registered paths: {sorted(paths)}"
    )


# ── HIGH-025: re-enrichment + fresh-DB-read invariants ──────────────────────

def test_re_enrich_parent_on_child_arrival_exists():
    """HIGH-025 VERIFIED FALSE pin (Task 94).

    Audit claimed partial fills don't trigger parent re-enrichment, leaving
    slippage measurement stale. Investigation found the re-enrichment
    happens on a different event: child TP/SL order arrival, not fill
    arrival. The function _re_enrich_parent_on_child_arrival in OrderManager
    is the load-bearing mechanism.

    This pin asserts the function exists and calls enrich_order. If a
    future contributor removes it, the audit's stale-snapshot impact
    becomes real — pin fails with explicit guidance.
    """
    from core.order_manager import OrderManager
    assert hasattr(OrderManager, "_re_enrich_parent_on_child_arrival"), (
        "HIGH-025 mechanism gone: OrderManager._re_enrich_parent_on_child_arrival "
        "was removed. The audit's stale-trigger-snapshot impact would become "
        "real without this. Re-evaluate HIGH-025 reachability."
    )

    src = inspect.getsource(OrderManager._re_enrich_parent_on_child_arrival)
    assert "enrich_order" in src, (
        "_re_enrich_parent_on_child_arrival no longer invokes enrich_order. "
        "The parent-refresh mechanism is broken; re-evaluate HIGH-025."
    )


def test_classify_and_compute_slippage_reads_parent_fresh_from_db():
    """HIGH-025 VERIFIED FALSE pin: _classify_and_compute_slippage reads the
    parent order fresh from DB on every fill, not from a cached snapshot.
    This is the second leg of why HIGH-025's "stale snapshot" impact
    doesn't materialize.

    Pin: function body must contain a `SELECT * FROM orders WHERE ...
    exchange_order_id` query inside it (read-fresh pattern), not a
    module-level cache lookup.
    """
    from core.order_enrichment import _classify_and_compute_slippage
    src = inspect.getsource(_classify_and_compute_slippage)
    # Look for the fresh-DB-read pattern
    has_orders_query = re.search(
        r"FROM\s+orders\s+WHERE.*exchange_order_id", src, re.DOTALL | re.IGNORECASE
    )
    assert has_orders_query is not None, (
        "HIGH-025 mechanism gone: _classify_and_compute_slippage no longer "
        "reads parent order fresh from DB on each fill. Audit's stale-snapshot "
        "impact could become real if an in-memory cache replaced the SELECT."
    )
