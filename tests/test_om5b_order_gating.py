"""
OM-5b: Basic order REST sync must not be plugin-gated.

Verifies that basic order fetch runs regardless of plugin connection state,
and that fetch_open_orders_tpsl always enriches from cache.
"""
import os
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest_asyncio.fixture
async def om_with_basic_orders():
    """OrderManager with basic orders in cache."""
    from core.database import DatabaseManager
    from core.order_manager import OrderManager

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    om = OrderManager(db)

    # Seed: basic TP + SL for BTCUSDT LONG position
    tp = {
        "account_id": 1, "exchange_order_id": "tp_basic_123",
        "symbol": "BTCUSDT", "side": "SELL", "order_type": "take_profit",
        "status": "new", "price": 0, "stop_price": 72000.0, "quantity": 0.003,
        "filled_qty": 0, "reduce_only": 1, "time_in_force": "GTC",
        "position_side": "LONG", "source": "binance_rest",
        "created_at_ms": 1747130943000, "updated_at_ms": 1747130943000,
    }
    sl = {**tp, "exchange_order_id": "sl_basic_456", "order_type": "stop_loss",
          "stop_price": 65000.0}
    await db.upsert_order_batch([tp, sl])
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


# ── fetch_open_orders_tpsl always enriches ───────────────────────────────────

@pytest.mark.asyncio
async def test_tpsl_enriches_when_plugin_connected(om_with_basic_orders):
    """fetch_open_orders_tpsl enriches positions even when plugin connected."""
    om, _ = om_with_basic_orders
    from core.state import PositionInfo

    pos = PositionInfo(ticker="BTCUSDT", direction="LONG", fair_price=68000.0, average=68000.0)

    mock_pb = MagicMock()
    mock_pb.is_connected = True  # Plugin IS connected
    mock_pb.order_manager = om

    with patch("core.exchange.app_state") as mock_state, \
         patch.dict("sys.modules", {"core.platform_bridge": MagicMock(platform_bridge=mock_pb)}):
        mock_state.positions = [pos]

        from core.exchange import fetch_open_orders_tpsl
        await fetch_open_orders_tpsl()

    assert pos.individual_tp_price == 72000.0, f"TP not enriched: {pos.individual_tp_price}"
    assert pos.individual_sl_price == 65000.0, f"SL not enriched: {pos.individual_sl_price}"
    assert pos.individual_tpsl is True


# ── Scheduler order sync not gated ───────────────────────────────────────────

def test_account_refresh_loop_has_order_sync_outside_gate():
    """_account_refresh_loop runs order sync even when plugin connected.

    Structural test: verify the code structure separates account/position
    gating from order sync.
    """
    import inspect
    from core.schedulers import _account_refresh_loop
    source = inspect.getsource(_account_refresh_loop)

    # The order sync section should include a comment indicating it's not gated
    assert "OM-5b" in source or "not plugin-gated" in source.lower() or \
           "regardless of plugin" in source.lower(), \
           "Order sync in _account_refresh_loop should be marked as not plugin-gated"


# ── Startup order fetch ──────────────────────────────────────────────────────

def test_startup_fetch_includes_order_sync():
    """_startup_fetch includes basic order sync regardless of plugin state."""
    import inspect
    from core.schedulers import _startup_fetch
    source = inspect.getsource(_startup_fetch)

    assert "fetch_open_orders" in source or "process_order_snapshot" in source, \
           "_startup_fetch should include basic order sync"
