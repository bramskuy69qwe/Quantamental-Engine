"""
OM-5b: Basic order REST sync must always run.

Verifies that basic order fetch runs on every account refresh + at startup,
and that fetch_open_orders_tpsl always enriches from the OrderManager cache.

OM-5b was originally specified against the Quantower plugin: 'basic order sync
must NOT be plugin-gated' — i.e. it must run even while the plugin was
connected and claiming to be authoritative. v2.6 removed the plugin, so the
gate these tests guarded against no longer exists and the conditional framing
was dropped. The invariant that survives is unconditional: orders sync every
refresh, TP/SL enriches from cache. Kept because that half is what actually
protects Open Orders + TP/SL display on the Binance-direct path.
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
async def test_tpsl_enriches_from_order_manager_cache(om_with_basic_orders):
    """fetch_open_orders_tpsl enriches positions from the OrderManager cache.

    OM-5b's original phrasing was 'enriches EVEN WHEN the plugin is connected',
    and the premise was a `mock_pb.is_connected = True` that v2.6 removed with
    the attribute. What remains is the durable half: enrichment reads the cache
    the order-sync loops populate, with no REST fallback needed when it's warm.
    """
    om, _ = om_with_basic_orders
    from core.state import PositionInfo

    pos = PositionInfo(ticker="BTCUSDT", direction="LONG", fair_price=68000.0, average=68000.0)

    mock_pb = MagicMock()
    mock_pb.order_manager = om

    with patch("core.exchange.app_state") as mock_state, \
         patch("core.order_manager_singleton.order_manager", mock_pb.order_manager):
        mock_state.positions = [pos]

        from core.exchange import fetch_open_orders_tpsl
        await fetch_open_orders_tpsl()

    assert pos.individual_tp_price == 72000.0, f"TP not enriched: {pos.individual_tp_price}"
    assert pos.individual_sl_price == 65000.0, f"SL not enriched: {pos.individual_sl_price}"
    assert pos.individual_tpsl is True


# ── Scheduler order sync not gated ───────────────────────────────────────────

def test_account_refresh_loop_includes_order_sync():
    """_account_refresh_loop syncs basic orders on every refresh.

    Structural test, mirroring test_startup_fetch_includes_order_sync below:
    pin the CALL, not a comment.

    OM-5b originally phrased this invariant as 'order sync runs even when the
    plugin is connected', and this test used to assert that the source carried
    a comment saying so ("OM-5b" or "not plugin-gated" or "regardless of
    plugin"). That was a prose-pin: it would have passed with the entire
    order-sync block deleted, so long as one of those strings survived in any
    comment. v2.6 removed the plugin, so the distinction the prose drew no
    longer exists. Replaced with a call-pin on the load-bearing half — the
    refresh loop must sync orders, unconditionally.
    """
    import inspect
    from core.schedulers import _account_refresh_loop
    source = inspect.getsource(_account_refresh_loop)

    assert "process_order_snapshot" in source, \
        "_account_refresh_loop no longer syncs basic orders (OM-5b invariant)"


# ── Startup order fetch ──────────────────────────────────────────────────────

def test_startup_fetch_includes_order_sync():
    """_startup_fetch includes basic order sync."""
    import inspect
    from core.schedulers import _startup_fetch
    source = inspect.getsource(_startup_fetch)

    assert "fetch_open_orders" in source or "process_order_snapshot" in source, \
           "_startup_fetch should include basic order sync"
