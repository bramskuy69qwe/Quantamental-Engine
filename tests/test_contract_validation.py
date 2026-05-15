"""Tests for exchange contract spec validation (Priority 2b)."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from core.contract_validation import (
    ContractSpec,
    ValidationResult,
    clear_cache,
    inject_spec,
    validate_and_snap_size,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_cache()
    yield
    clear_cache()


def _make_spec(symbol="BTCUSDT", lot_step="0.001", min_qty="0.001",
               min_notional="5", tick_size="0.01"):
    spec = ContractSpec(
        symbol=symbol,
        tick_size=Decimal(tick_size),
        lot_step=Decimal(lot_step),
        min_qty=Decimal(min_qty),
        min_notional=Decimal(min_notional),
        fetched_at=datetime.now(timezone.utc),
    )
    inject_spec(symbol, spec)
    return spec


class TestSnapToLotStep:
    def test_exact_lot_step(self):
        _make_spec(lot_step="0.001", min_qty="0.001", min_notional="5")
        vr = validate_and_snap_size(0.005, "BTCUSDT", 50000.0)
        assert vr.valid
        assert vr.snapped_size == Decimal("0.005")

    def test_snap_down(self):
        _make_spec(lot_step="0.001", min_qty="0.001", min_notional="5")
        vr = validate_and_snap_size(0.0057, "BTCUSDT", 50000.0)
        assert vr.valid
        assert vr.snapped_size == Decimal("0.005")

    def test_decimal_precision_no_float_artifact(self):
        """0.1 + 0.2 in Decimal gives exact 0.3, not 0.30000000000000004."""
        _make_spec(lot_step="0.1", min_qty="0.1", min_notional="0")
        vr = validate_and_snap_size(0.3, "BTCUSDT", 100.0)
        assert vr.valid
        assert vr.snapped_size == Decimal("0.3")


class TestMinQty:
    def test_below_min_qty(self):
        _make_spec(lot_step="0.001", min_qty="0.01", min_notional="0")
        vr = validate_and_snap_size(0.005, "BTCUSDT", 50000.0)
        assert not vr.valid
        assert "below_min_qty" in vr.reason
        assert vr.suggested_size == Decimal("0.01")


class TestMinNotional:
    def test_below_min_notional(self):
        _make_spec(lot_step="0.001", min_qty="0.001", min_notional="100")
        # 0.001 * 50000 = 50 < 100
        vr = validate_and_snap_size(0.001, "BTCUSDT", 50000.0)
        assert not vr.valid
        assert "below_min_notional" in vr.reason
        assert vr.suggested_size is not None
        # suggested should meet min_notional: suggested * 50000 >= 100
        assert vr.suggested_size * Decimal("50000") >= Decimal("100")

    def test_notional_just_above(self):
        _make_spec(lot_step="0.001", min_qty="0.001", min_notional="5")
        # 0.001 * 50000 = 50 >= 5
        vr = validate_and_snap_size(0.001, "BTCUSDT", 50000.0)
        assert vr.valid


class TestMissingSpec:
    def test_unknown_symbol(self):
        vr = validate_and_snap_size(0.01, "NONEXISTENT", 100.0)
        assert not vr.valid
        assert "exchange_info_unavailable" in vr.reason


class TestCacheTTL:
    def test_stale_cache_treated_as_miss(self):
        spec = _make_spec()
        # Backdate fetched_at beyond TTL
        spec.fetched_at = datetime.now(timezone.utc) - timedelta(hours=25)
        inject_spec("BTCUSDT", spec)

        # Without a real adapter, fresh fetch fails → None → unavailable
        vr = validate_and_snap_size(0.01, "BTCUSDT", 50000.0)
        # The stale spec was rejected; fresh fetch failed → unavailable
        assert not vr.valid
        assert "exchange_info_unavailable" in vr.reason


class TestEventType:
    def test_calc_blocked_contract_registered(self):
        from core.event_log import _VALID_EVENT_TYPES
        assert "calc_blocked_contract" in _VALID_EVENT_TYPES
