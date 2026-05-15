"""
Exchange contract spec validation for calculator output.

Validates computed position sizes against exchange constraints (lot_step,
min_qty, min_notional). Uses Decimal arithmetic to avoid float rounding
artifacts. Snaps sizes DOWN to lot_step (never increases exposure).

Priority 2b — pre-trade validation before the calculator result is final.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP, InvalidOperation
from typing import Optional

log = logging.getLogger("contract_validation")

_CACHE_TTL_HOURS = 24


@dataclass
class ContractSpec:
    symbol: str
    tick_size: Decimal
    lot_step: Decimal
    min_qty: Decimal
    min_notional: Decimal
    fetched_at: datetime


# ── Contract spec cache ──────────────────────────────────────────────────────

_spec_cache: dict[str, ContractSpec] = {}


def get_contract_spec(symbol: str) -> Optional[ContractSpec]:
    """Read contract spec from cache. Refresh if stale (> 24h) or missing.

    Returns None if exchange_info is unavailable.
    """
    cached = _spec_cache.get(symbol)
    now = datetime.now(timezone.utc)

    if cached and (now - cached.fetched_at).total_seconds() < _CACHE_TTL_HOURS * 3600:
        return cached

    # Fetch from exchange adapter
    spec = _fetch_spec_from_adapter(symbol)
    if spec:
        _spec_cache[symbol] = spec
    return spec


def _fetch_spec_from_adapter(symbol: str) -> Optional[ContractSpec]:
    """Read contract constraints from the CCXT market info."""
    try:
        from core.exchange import _get_adapter
        adapter = _get_adapter()
        ex = adapter.get_ccxt_instance()
        if not ex.markets or symbol not in ex.markets:
            return None
        market = ex.markets[symbol]
        limits = market.get("limits", {})
        prec = market.get("precision", {})

        # CCXT stores precision as decimal places (int) or tick size (float)
        amount_prec = prec.get("amount", 8)
        price_prec = prec.get("price", 8)

        if isinstance(amount_prec, int):
            lot_step = Decimal(10) ** -amount_prec
        else:
            lot_step = Decimal(str(amount_prec))

        if isinstance(price_prec, int):
            tick_size = Decimal(10) ** -price_prec
        else:
            tick_size = Decimal(str(price_prec))

        amount_limits = limits.get("amount", {})
        cost_limits = limits.get("cost", {})

        min_qty = Decimal(str(amount_limits.get("min", 0) or 0))
        min_notional = Decimal(str(cost_limits.get("min", 0) or 0))

        return ContractSpec(
            symbol=symbol,
            tick_size=tick_size,
            lot_step=lot_step,
            min_qty=min_qty,
            min_notional=min_notional,
            fetched_at=datetime.now(timezone.utc),
        )
    except Exception:
        log.debug("Failed to fetch contract spec for %s", symbol, exc_info=True)
        return None


def inject_spec(symbol: str, spec: ContractSpec) -> None:
    """Inject a ContractSpec into the cache (for testing)."""
    _spec_cache[symbol] = spec


def clear_cache() -> None:
    """Clear the spec cache (for testing)."""
    _spec_cache.clear()


# ── Validation ───────────────────────────────────────────────────────────────


@dataclass
class ValidationResult:
    valid: bool
    snapped_size: Optional[Decimal] = None
    original_size: Decimal = Decimal(0)
    reason: Optional[str] = None
    suggested_size: Optional[Decimal] = None


def validate_and_snap_size(
    size: float,
    symbol: str,
    price: float,
) -> ValidationResult:
    """Validate and snap a computed position size to exchange constraints.

    Snaps DOWN to lot_step (never increases exposure). If snapped size
    violates min_qty or min_notional, returns invalid with suggested_size.
    """
    try:
        d_size = Decimal(str(size))
        d_price = Decimal(str(price))
    except (InvalidOperation, ValueError):
        return ValidationResult(
            valid=False, original_size=Decimal(0),
            reason="invalid_numeric_input",
        )

    spec = get_contract_spec(symbol)
    if spec is None:
        return ValidationResult(
            valid=False, original_size=d_size,
            reason="exchange_info_unavailable",
        )

    # Snap DOWN to lot_step
    if spec.lot_step > 0:
        snapped = (d_size // spec.lot_step) * spec.lot_step
    else:
        snapped = d_size

    # Check min_qty
    if spec.min_qty > 0 and snapped < spec.min_qty:
        return ValidationResult(
            valid=False, snapped_size=snapped, original_size=d_size,
            reason=f"below_min_qty ({snapped} < {spec.min_qty})",
            suggested_size=spec.min_qty,
        )

    # Check min_notional
    notional = snapped * d_price
    if spec.min_notional > 0 and notional < spec.min_notional:
        # Suggest size that meets min_notional, rounded UP to lot_step
        if d_price > 0 and spec.lot_step > 0:
            raw_min = spec.min_notional / d_price
            suggested = ((raw_min // spec.lot_step) + 1) * spec.lot_step
        else:
            suggested = spec.min_qty
        return ValidationResult(
            valid=False, snapped_size=snapped, original_size=d_size,
            reason=f"below_min_notional (notional={notional} < {spec.min_notional})",
            suggested_size=suggested,
        )

    return ValidationResult(
        valid=True, snapped_size=snapped, original_size=d_size,
    )
