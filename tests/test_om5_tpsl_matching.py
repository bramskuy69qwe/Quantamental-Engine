"""
OM-5: TP/SL position matching — positionSide="BOTH" handling.

Binance one-way mode sends positionSide="BOTH" on all orders.
Positions have direction="LONG"/"SHORT". The matching helper must
resolve "BOTH" to the correct direction using the order's side field.

Close-order semantics: SELL reduces LONG, BUY reduces SHORT.
This is correct for TP/SL (reduceOnly) orders only — do not apply
to entry-order matching where the mapping inverts.
"""
import os
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.order_state import resolve_tpsl_direction


# ── Helper unit tests ────────────────────────────────────────────────────────

class TestResolveTpslDirection:
    """Test the shared helper for resolving position_side to direction."""

    def test_one_way_sell_resolves_to_long(self):
        """BOTH + SELL → LONG (SELL reduces a LONG position)."""
        assert resolve_tpsl_direction("BOTH", "SELL") == "LONG"

    def test_one_way_buy_resolves_to_short(self):
        """BOTH + BUY → SHORT (BUY reduces a SHORT position)."""
        assert resolve_tpsl_direction("BOTH", "BUY") == "SHORT"

    def test_hedge_long_preserved(self):
        """LONG in hedge mode passes through unchanged."""
        assert resolve_tpsl_direction("LONG", "SELL") == "LONG"

    def test_hedge_short_preserved(self):
        """SHORT in hedge mode passes through unchanged."""
        assert resolve_tpsl_direction("SHORT", "BUY") == "SHORT"

    def test_empty_position_side_uses_fallback(self):
        """Empty position_side falls back to side-based inference."""
        assert resolve_tpsl_direction("", "SELL") == "LONG"
        assert resolve_tpsl_direction("", "BUY") == "SHORT"

    def test_none_position_side_uses_fallback(self):
        """None position_side falls back to side-based inference."""
        assert resolve_tpsl_direction(None, "SELL") == "LONG"
        assert resolve_tpsl_direction(None, "BUY") == "SHORT"

    def test_negative_both_sell_not_short(self):
        """BOTH + SELL must NOT resolve to SHORT."""
        assert resolve_tpsl_direction("BOTH", "SELL") != "SHORT"

    def test_negative_both_buy_not_long(self):
        """BOTH + BUY must NOT resolve to LONG."""
        assert resolve_tpsl_direction("BOTH", "BUY") != "LONG"


# ── enrich_positions_tpsl integration ────────────────────────────────────────

@pytest_asyncio.fixture
async def order_manager_with_db():
    """OrderManager with a temp DB seeded with TP/SL orders."""
    from core.database import DatabaseManager
    from core.order_manager import OrderManager

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    om = OrderManager(db)

    # Seed orders: TP and SL with positionSide="BOTH" (one-way mode)
    tp_order = {
        "account_id": 1,
        "exchange_order_id": "tp_order_1",
        "symbol": "BTCUSDT",
        "side": "SELL",
        "order_type": "take_profit",
        "status": "new",
        "price": 0,
        "stop_price": 72000.0,
        "quantity": 0.003,
        "filled_qty": 0,
        "avg_fill_price": 0,
        "reduce_only": 1,
        "time_in_force": "GTC",
        "position_side": "BOTH",
        "source": "binance_rest",
        "created_at_ms": 1775300000000,
        "updated_at_ms": 1775300000000,
    }
    sl_order = {
        **tp_order,
        "exchange_order_id": "sl_order_1",
        "order_type": "stop_loss",
        "stop_price": 66000.0,
    }
    # Hedge-mode orders for SHORT position
    tp_hedge = {
        **tp_order,
        "exchange_order_id": "tp_hedge_short",
        "side": "BUY",
        "position_side": "SHORT",
        "stop_price": 64000.0,
    }
    sl_hedge = {
        **tp_order,
        "exchange_order_id": "sl_hedge_short",
        "side": "BUY",
        "order_type": "stop_loss",
        "position_side": "SHORT",
        "stop_price": 74000.0,
    }
    await db.upsert_order_batch([tp_order, sl_order, tp_hedge, sl_hedge])
    await om.refresh_cache(1)

    yield om, db

    await db.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


@pytest.mark.asyncio
async def test_enrich_one_way_long(order_manager_with_db):
    """enrich_positions_tpsl links BOTH+SELL TP/SL to LONG position."""
    om, _db = order_manager_with_db
    from core.state import PositionInfo

    pos = PositionInfo(ticker="BTCUSDT", direction="LONG", fair_price=68000.0, average=68000.0)
    om.enrich_positions_tpsl([pos])

    assert pos.individual_tp_price == 72000.0, f"TP not linked: {pos.individual_tp_price}"
    assert pos.individual_sl_price == 66000.0, f"SL not linked: {pos.individual_sl_price}"
    assert pos.individual_tpsl is True


@pytest.mark.asyncio
async def test_enrich_hedge_short(order_manager_with_db):
    """enrich_positions_tpsl links SHORT hedge-mode TP/SL to SHORT position."""
    om, _db = order_manager_with_db
    from core.state import PositionInfo

    pos = PositionInfo(ticker="BTCUSDT", direction="SHORT", fair_price=68000.0, average=68000.0)
    om.enrich_positions_tpsl([pos])

    assert pos.individual_tp_price == 64000.0, f"TP not linked: {pos.individual_tp_price}"
    assert pos.individual_sl_price == 74000.0, f"SL not linked: {pos.individual_sl_price}"
    assert pos.individual_tpsl is True


@pytest.mark.asyncio
async def test_enrich_both_sell_not_linked_to_short(order_manager_with_db):
    """BOTH+SELL TP/SL must NOT link to SHORT position (only to LONG)."""
    om, _db = order_manager_with_db
    from core.state import PositionInfo

    # Only SHORT position — BOTH+SELL orders should not match
    # (hedge SHORT orders should match though)
    pos = PositionInfo(ticker="BTCUSDT", direction="SHORT", fair_price=68000.0, average=68000.0)
    om.enrich_positions_tpsl([pos])

    # Should get hedge SHORT TP/SL (64000 / 74000), NOT BOTH+SELL (72000 / 66000)
    assert pos.individual_tp_price == 64000.0
    assert pos.individual_sl_price == 74000.0


# ── _apply_order_update WS path ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ws_tpsl_one_way_mode():
    """WS TP order with positionSide=BOTH enriches LONG position."""
    from core.state import PositionInfo
    from core.adapters.protocols import NormalizedOrder

    pos = PositionInfo(ticker="ETHUSDT", direction="LONG", average=3800.0, fair_price=3800.0)

    order = NormalizedOrder(
        exchange_order_id="ws_tp_1",
        symbol="ETHUSDT",
        side="SELL",
        order_type="take_profit",
        status="new",
        stop_price=4200.0,
        quantity=0.1,
        position_side="BOTH",
        execution_type="NEW",
    )

    mock_pb = MagicMock()
    mock_pb.order_manager.process_order_update = MagicMock(return_value=True)

    with patch("core.ws_manager.app_state") as mock_state, \
         patch.dict("sys.modules", {"core.platform_bridge": MagicMock(platform_bridge=mock_pb)}):
        mock_state.positions = [pos]
        mock_state.active_account_id = 1

        from core.ws_manager import _apply_order_update
        mock_adapter = MagicMock()
        mock_adapter.parse_order_update.return_value = order
        await _apply_order_update({"o": {}}, mock_adapter)

    assert pos.individual_tp_price == 4200.0, f"WS TP not applied: {pos.individual_tp_price}"
    assert pos.individual_tpsl is True


@pytest.mark.asyncio
async def test_ws_tpsl_hedge_mode():
    """WS SL order with positionSide=SHORT enriches SHORT position."""
    from core.state import PositionInfo
    from core.adapters.protocols import NormalizedOrder

    pos = PositionInfo(ticker="ETHUSDT", direction="SHORT", average=3800.0, fair_price=3800.0)

    order = NormalizedOrder(
        exchange_order_id="ws_sl_1",
        symbol="ETHUSDT",
        side="BUY",
        order_type="stop_loss",
        status="new",
        stop_price=4000.0,
        quantity=0.1,
        position_side="SHORT",
        execution_type="NEW",
    )

    mock_pb = MagicMock()
    mock_pb.order_manager.process_order_update = MagicMock(return_value=True)

    with patch("core.ws_manager.app_state") as mock_state, \
         patch.dict("sys.modules", {"core.platform_bridge": MagicMock(platform_bridge=mock_pb)}):
        mock_state.positions = [pos]
        mock_state.active_account_id = 1

        from core.ws_manager import _apply_order_update
        mock_adapter = MagicMock()
        mock_adapter.parse_order_update.return_value = order
        await _apply_order_update({"o": {}}, mock_adapter)

    assert pos.individual_sl_price == 4000.0, f"WS SL not applied: {pos.individual_sl_price}"
    assert pos.individual_tpsl is True


# ── fetch_open_orders_tpsl REST path ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_tpsl_one_way_mode():
    """fetch_open_orders_tpsl maps BOTH+SELL TP to LONG position."""
    from core.state import PositionInfo
    from core.adapters.protocols import NormalizedOrder

    pos = PositionInfo(ticker="BTCUSDT", direction="LONG", average=68000.0, fair_price=68000.0)
    tp = NormalizedOrder(
        symbol="BTCUSDT", side="SELL", order_type="take_profit",
        stop_price=72000.0, quantity=0.003, position_side="BOTH",
    )
    sl = NormalizedOrder(
        symbol="BTCUSDT", side="SELL", order_type="stop_loss",
        stop_price=65000.0, quantity=0.003, position_side="BOTH",
    )

    mock_adapter = MagicMock()
    mock_adapter.fetch_open_orders = AsyncMock(return_value=[tp, sl])
    mock_pb = MagicMock()
    mock_pb.is_connected = False

    with patch("core.exchange.app_state") as mock_state, \
         patch("core.exchange._get_adapter", return_value=mock_adapter), \
         patch.dict("sys.modules", {"core.platform_bridge": MagicMock(platform_bridge=mock_pb)}):
        mock_state.positions = [pos]

        from core.exchange import fetch_open_orders_tpsl
        await fetch_open_orders_tpsl()

    assert pos.individual_tp_price == 72000.0, f"REST TP not applied: {pos.individual_tp_price}"
    assert pos.individual_sl_price == 65000.0, f"REST SL not applied: {pos.individual_sl_price}"
    assert pos.individual_tpsl is True
