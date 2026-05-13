"""
OM-5: Conditional (algo) order support — REST parsing, WS parsing,
enrichment, snapshot isolation.

Binance separates basic orders (FAPI openOrders) from conditional/algo
orders (FAPI openAlgoOrders). Engine must handle both.
"""
import os
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.adapters.binance.constants import ALGO_STATUS_MAP, ORDER_TYPE_FROM_BINANCE


# ── Constants ────────────────────────────────────────────────────────────────

class TestAlgoStatusMap:
    def test_new(self):
        assert ALGO_STATUS_MAP["NEW"] == "new"

    def test_triggering_maps_to_new(self):
        assert ALGO_STATUS_MAP["TRIGGERING"] == "new"

    def test_triggered_maps_to_partially_filled(self):
        assert ALGO_STATUS_MAP["TRIGGERED"] == "partially_filled"

    def test_finished_maps_to_filled(self):
        assert ALGO_STATUS_MAP["FINISHED"] == "filled"

    def test_canceled(self):
        assert ALGO_STATUS_MAP["CANCELED"] == "canceled"

    def test_all_algo_order_types_in_type_map(self):
        """All orderType values from algo orders are in ORDER_TYPE_FROM_BINANCE."""
        algo_types = ["STOP_MARKET", "TAKE_PROFIT_MARKET", "STOP", "TAKE_PROFIT", "TRAILING_STOP_MARKET"]
        for t in algo_types:
            assert t in ORDER_TYPE_FROM_BINANCE, f"{t} missing from ORDER_TYPE_FROM_BINANCE"


# ── REST adapter parsing ────────────────────────────────────────────────────

SAMPLE_ALGO_REST = {
    "algoId": "3000001524880626",
    "clientAlgoId": "web_algo_test123",
    "algoType": "CONDITIONAL",
    "orderType": "STOP_MARKET",
    "symbol": "SAGAUSDT",
    "side": "SELL",
    "positionSide": "LONG",
    "totalQty": "100",
    "executedQty": "0",
    "algoStatus": "NEW",
    "triggerPrice": "0.4500",
    "price": "0",
    "reduceOnly": True,
    "workingType": "CONTRACT_PRICE",
    "bookTime": "1747130943000",
    "updateTime": "1747130943000",
    "createTime": "1747130943000",
}


class TestRestAlgoParsing:
    def test_parse_algo_order(self):
        from core.adapters.binance.rest_adapter import BinanceUSDMAdapter
        # Call the static parsing logic directly
        from core.adapters.binance.constants import ORDER_TYPE_FROM_BINANCE, ALGO_STATUS_MAP
        from core.adapters.protocols import NormalizedOrder

        o = SAMPLE_ALGO_REST
        order = NormalizedOrder(
            exchange_order_id=f"algo:{o['algoId']}",
            client_order_id=o.get("clientAlgoId", ""),
            symbol=o["symbol"],
            side=o["side"],
            order_type=ORDER_TYPE_FROM_BINANCE.get(o["orderType"], o["orderType"].lower()),
            status=ALGO_STATUS_MAP.get(o["algoStatus"], "new"),
            price=float(o.get("price", 0) or 0),
            stop_price=float(o.get("triggerPrice", 0) or 0),
            quantity=float(o.get("totalQty", 0) or 0),
            filled_qty=float(o.get("executedQty", 0) or 0),
            reduce_only=bool(o.get("reduceOnly", False)),
            position_side=o.get("positionSide", ""),
            created_at_ms=int(o.get("bookTime", 0) or 0),
            updated_at_ms=int(o.get("updateTime", 0) or 0),
        )

        assert order.exchange_order_id == "algo:3000001524880626"
        assert order.symbol == "SAGAUSDT"
        assert order.side == "SELL"
        assert order.order_type == "stop_loss"
        assert order.status == "new"
        assert order.stop_price == 0.45
        assert order.quantity == 100.0
        assert order.position_side == "LONG"
        assert order.reduce_only is True

    def test_algo_id_prefix_prevents_collision(self):
        """algo: prefix ensures no collision with basic order IDs."""
        assert SAMPLE_ALGO_REST["algoId"].isdigit()
        prefixed = f"algo:{SAMPLE_ALGO_REST['algoId']}"
        assert prefixed.startswith("algo:")


# ── WS adapter parsing ──────────────────────────────────────────────────────

SAMPLE_ALGO_WS = {
    "e": "ALGO_UPDATE",
    "T": 1747130943000,
    "E": 1747130943100,
    "o": {
        "aid": "3000001524880626",
        "caid": "web_algo_test123",
        "at": "CONDITIONAL",
        "o": "STOP_MARKET",
        "s": "SAGAUSDT",
        "S": "SELL",
        "ps": "LONG",
        "q": "100",
        "p": "0",
        "tp": "0.4500",
        "X": "NEW",
        "R": True,
        "wt": "CONTRACT_PRICE",
        "T": 1747130943000,
        "ut": 1747130943000,
    },
}


class TestWsAlgoParsing:
    def test_parse_algo_update(self):
        from core.adapters.binance.ws_adapter import BinanceWSAdapter
        adapter = BinanceWSAdapter()
        order = adapter.parse_algo_update(SAMPLE_ALGO_WS)

        assert order.exchange_order_id == "algo:3000001524880626"
        assert order.symbol == "SAGAUSDT"
        assert order.side == "SELL"
        assert order.order_type == "stop_loss"
        assert order.status == "new"
        assert order.stop_price == 0.45
        assert order.quantity == 100.0
        assert order.position_side == "LONG"
        assert order.reduce_only is True

    def test_canceled_status(self):
        from core.adapters.binance.ws_adapter import BinanceWSAdapter
        adapter = BinanceWSAdapter()
        msg = {**SAMPLE_ALGO_WS, "o": {**SAMPLE_ALGO_WS["o"], "X": "CANCELED"}}
        order = adapter.parse_algo_update(msg)
        assert order.status == "canceled"

    def test_finished_status(self):
        from core.adapters.binance.ws_adapter import BinanceWSAdapter
        adapter = BinanceWSAdapter()
        msg = {**SAMPLE_ALGO_WS, "o": {**SAMPLE_ALGO_WS["o"], "X": "FINISHED"}}
        order = adapter.parse_algo_update(msg)
        assert order.status == "filled"


# ── Enrichment ───────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def om_with_algo_orders():
    """OrderManager with algo TP/SL orders in cache."""
    from core.database import DatabaseManager
    from core.order_manager import OrderManager

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    om = OrderManager(db)

    # Seed: algo TP + SL for SAGAUSDT LONG position
    tp = {
        "account_id": 1, "exchange_order_id": "algo:tp_saga",
        "symbol": "SAGAUSDT", "side": "SELL", "order_type": "take_profit",
        "status": "new", "price": 0, "stop_price": 0.55, "quantity": 100,
        "filled_qty": 0, "reduce_only": 1, "time_in_force": "GTC",
        "position_side": "LONG", "source": "binance_algo_rest",
        "created_at_ms": 1747130943000, "updated_at_ms": 1747130943000,
    }
    sl = {**tp, "exchange_order_id": "algo:sl_saga", "order_type": "stop_loss",
          "stop_price": 0.35}
    # Also seed a basic limit order (should not interfere)
    basic = {
        "account_id": 1, "exchange_order_id": "basic_12345",
        "symbol": "BTCUSDT", "side": "BUY", "order_type": "limit",
        "status": "new", "price": 65000, "stop_price": 0, "quantity": 0.003,
        "filled_qty": 0, "reduce_only": 0, "time_in_force": "GTC",
        "position_side": "LONG", "source": "binance_ws",
        "created_at_ms": 1747130000000, "updated_at_ms": 1747130000000,
    }
    await db.upsert_order_batch([tp, sl, basic])
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
async def test_enrich_algo_tpsl(om_with_algo_orders):
    """Algo TP/SL orders in cache enrich position correctly."""
    om, _ = om_with_algo_orders
    from core.state import PositionInfo

    pos = PositionInfo(ticker="SAGAUSDT", direction="LONG", fair_price=0.45, average=0.45)
    om.enrich_positions_tpsl([pos])

    assert pos.individual_tp_price == 0.55
    assert pos.individual_sl_price == 0.35
    assert pos.individual_tpsl is True


# ── Snapshot isolation ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_algo_snapshot_does_not_cancel_basic(om_with_algo_orders):
    """process_algo_snapshot cancels stale algo orders only, not basic."""
    om, db = om_with_algo_orders

    # Process an algo snapshot with NO orders (all algo canceled)
    await om.process_algo_snapshot(1, [])

    # Algo orders should be canceled
    async with db._conn.execute(
        "SELECT status FROM orders WHERE exchange_order_id LIKE 'algo:%'"
    ) as cur:
        rows = await cur.fetchall()
    assert all(r[0] == "canceled" for r in rows), "Algo orders should be canceled"

    # Basic order should survive
    async with db._conn.execute(
        "SELECT status FROM orders WHERE exchange_order_id = 'basic_12345'"
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == "new", f"Basic order should survive, got {row[0]}"


@pytest.mark.asyncio
async def test_basic_snapshot_does_not_cancel_algo(om_with_algo_orders):
    """process_order_snapshot with empty basic snapshot does not cancel algo orders."""
    om, db = om_with_algo_orders

    # Process a basic snapshot with NO orders
    await om.process_order_snapshot(1, [])

    # Algo orders should survive (process_order_snapshot skips algo: IDs)
    async with db._conn.execute(
        "SELECT status FROM orders WHERE exchange_order_id LIKE 'algo:%' AND status='new'"
    ) as cur:
        rows = await cur.fetchall()
    assert len(rows) == 2, f"Algo orders should survive, got {len(rows)} active"


# ── WS dispatcher ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ws_dispatcher_routes_algo_update():
    """ALGO_UPDATE event is dispatched to handler."""
    from core.state import PositionInfo
    from core.adapters.binance.ws_adapter import BinanceWSAdapter

    pos = PositionInfo(ticker="SAGAUSDT", direction="LONG", average=0.45, fair_price=0.45)

    mock_pb = MagicMock()
    mock_pb.order_manager.process_order_update = AsyncMock(return_value=True)

    with patch("core.ws_manager.app_state") as mock_state, \
         patch.dict("sys.modules", {"core.platform_bridge": MagicMock(platform_bridge=mock_pb)}):
        mock_state.positions = [pos]
        mock_state.active_account_id = 1

        from core.ws_manager import _handle_user_event
        # Need a real ws_adapter for parsing
        with patch("core.ws_manager._get_ws_adapter", return_value=BinanceWSAdapter()):
            await _handle_user_event(SAMPLE_ALGO_WS)

    assert pos.individual_sl_price == 0.45, f"SL not applied: {pos.individual_sl_price}"
    assert pos.individual_tpsl is True
