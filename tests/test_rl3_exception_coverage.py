"""
RL-3 regression tests — rate-limit exception coverage.

Validates that all 11 REST-calling exception handlers propagate
rate-limit errors to handle_rate_limit_error(), setting
app_state.ws_status.rate_limited_until.

Pre-fix:  all 11 tests FAIL (rate_limited_until stays None).
Post-fix: all 11 tests PASS.

Run: pytest tests/test_rl3_exception_coverage.py -v
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from core.adapters.errors import RateLimitError
from core.state import app_state, PositionInfo


RL_EXC = RateLimitError(
    'binanceusdm 429 Too Many Requests '
    '{"code":-1003,"msg":"Too many requests"}'
)

SITES = [
    "exchange__populate_metadata",
    "exchange__fetch_open_orders_tpsl",
    "reconciler__on_trade_closed",
    "reconciler__backfill_history",
    "reconciler__backfill_process",
    "reconciler__on_position_closed",
    "reconciler__reconcile_closed_row",
    "ws__on_new_position",
    "ws__refresh_after_fill",
    "ws__keepalive_loop",
    "ws__fallback_loop",
]


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """Ensure rate_limited_until is None before and after each test."""
    app_state.ws_status.rate_limited_until = None
    yield
    app_state.ws_status.rate_limited_until = None


# ── Helpers for loop-based tests ─────────────────────────────────────────────

def _loop_sleep_factory():
    """Return an async side_effect that exits the loop after one body execution.

    First call: return immediately (lets the loop body run).
    Subsequent calls: raise CancelledError (exits the while-True loop).
    """
    calls = {"n": 0}

    async def _sleep(duration):
        calls["n"] += 1
        if calls["n"] > 1:
            raise asyncio.CancelledError()

    return _sleep


def _mock_adapter(*, raise_on: str):
    """Build a MagicMock adapter where `raise_on` method raises RL_EXC."""
    adapter = MagicMock()
    setattr(adapter, raise_on, AsyncMock(side_effect=RL_EXC))
    # Default stubs for methods that might be called before the raising one
    if raise_on != "fetch_user_trades":
        adapter.fetch_user_trades = AsyncMock(return_value=[])
    if raise_on != "fetch_open_orders":
        adapter.fetch_open_orders = AsyncMock(return_value=[])
    if raise_on != "fetch_account":
        adapter.fetch_account = AsyncMock()
    if raise_on != "fetch_positions":
        adapter.fetch_positions = AsyncMock(return_value=[])
    return adapter


# ── Mock DB cursor for reconciler tests ──────────────────────────────────────

def _mock_db_with_symbols(symbols: list[str]):
    """Return a mock db whose execute returns `symbols` for the backfill query."""
    mock_cursor = AsyncMock()
    mock_cursor.fetchall = AsyncMock(return_value=[(s,) for s in symbols])
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_cursor)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_conn = MagicMock()
    mock_conn.execute = MagicMock(return_value=mock_ctx)
    return mock_conn


def _mock_closed_pos_rows():
    """Return one closed-position row for reconciler tests."""
    return [
        {
            "id": 999,
            "symbol": "BTCUSDT",
            "entry_time_ms": 1000000,
            "exit_time_ms": 2000000,
            "entry_price": 60000.0,
            "quantity": 0.01,
            "direction": "LONG",
        }
    ]


# ── Parametrized test ────────────────────────────────────────────────────────

@pytest.mark.parametrize("site_id", SITES)
@pytest.mark.asyncio
async def test_rl3_rate_limit_propagation(site_id):
    """ccxt.RateLimitExceeded at each site must set rate_limited_until."""

    if site_id == "exchange__populate_metadata":
        adapter = _mock_adapter(raise_on="fetch_user_trades")
        pos = PositionInfo(
            ticker="BTCUSDT", direction="LONG",
            contract_amount=1.0, average=60000.0,
        )
        app_state.positions = [pos]
        with patch("core.exchange._get_adapter", return_value=adapter):
            from core.exchange import populate_open_position_metadata
            await populate_open_position_metadata()

    elif site_id == "exchange__fetch_open_orders_tpsl":
        adapter = _mock_adapter(raise_on="fetch_open_orders")
        mock_pb = MagicMock()
        mock_pb.is_connected = False
        with patch("core.exchange._get_adapter", return_value=adapter), \
             patch("core.platform_bridge.platform_bridge", mock_pb):
            from core.exchange import fetch_open_orders_tpsl
            await fetch_open_orders_tpsl()

    elif site_id == "reconciler__on_trade_closed":
        with patch("core.reconciler.fetch_exchange_trade_history",
                    new_callable=AsyncMock, side_effect=RL_EXC), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            from core.reconciler import ReconcilerWorker
            await ReconcilerWorker().on_trade_closed(
                {"ticker": "BTCUSDT", "direction": "LONG"},
            )

    elif site_id == "reconciler__backfill_history":
        with patch("core.reconciler.fetch_exchange_trade_history",
                    new_callable=AsyncMock, side_effect=RL_EXC):
            from core.reconciler import ReconcilerWorker
            r = ReconcilerWorker()
            # Patch _conn so the DB query after history fetch doesn't crash
            with patch.object(r, "_reconcile_closed_positions",
                              new_callable=AsyncMock):
                mock_conn = _mock_db_with_symbols([])
                with patch("core.reconciler.db") as mock_db:
                    mock_db._conn = mock_conn
                    await r.backfill_all()

    elif site_id == "reconciler__backfill_process":
        with patch("core.reconciler.fetch_exchange_trade_history",
                    new_callable=AsyncMock), \
             patch("core.reconciler.fetch_hl_for_trade",
                    new_callable=AsyncMock, side_effect=RL_EXC):
            from core.reconciler import ReconcilerWorker
            r = ReconcilerWorker()
            mock_conn = _mock_db_with_symbols(["BTCUSDT"])
            with patch("core.reconciler.db") as mock_db:
                mock_db._conn = mock_conn
                mock_db.get_uncalculated_exchange_rows = AsyncMock(
                    return_value=[{
                        "trade_key": "test_key", "open_time": 1000,
                        "time": 2000, "entry_price": 60000.0,
                        "qty": 0.01, "direction": "LONG",
                    }],
                )
                with patch.object(r, "_reconcile_closed_positions",
                                  new_callable=AsyncMock):
                    await r.backfill_all()

    elif site_id == "reconciler__on_position_closed":
        with patch("asyncio.sleep", new_callable=AsyncMock):
            from core.reconciler import ReconcilerWorker
            r = ReconcilerWorker()
            with patch.object(r, "_reconcile_closed_positions",
                              new_callable=AsyncMock, side_effect=RL_EXC):
                await r.on_position_closed({"symbol": "BTCUSDT"})

    elif site_id == "reconciler__reconcile_closed_row":
        with patch("core.reconciler.fetch_hl_for_trade",
                    new_callable=AsyncMock, side_effect=RL_EXC), \
             patch.object(type(app_state), "active_account_id",
                          new_callable=lambda: property(lambda self: 1)):
            from core.reconciler import ReconcilerWorker
            r = ReconcilerWorker()
            with patch("core.reconciler.db") as mock_db:
                mock_db.get_uncalculated_closed_positions = AsyncMock(
                    return_value=_mock_closed_pos_rows(),
                )
                await r._reconcile_closed_positions(symbol="BTCUSDT")

    elif site_id == "ws__on_new_position":
        adapter = _mock_adapter(raise_on="fetch_user_trades")
        with patch("core.ws_manager._get_adapter", return_value=adapter), \
             patch("core.ws_manager.restart_market_streams",
                    new_callable=AsyncMock):
            from core.ws_manager import _on_new_position
            await _on_new_position("BTCUSDT")

    elif site_id == "ws__refresh_after_fill":
        with patch("core.ws_manager.fetch_account",
                    new_callable=AsyncMock, side_effect=RL_EXC):
            from core.ws_manager import _refresh_positions_after_fill
            await _refresh_positions_after_fill()

    elif site_id == "ws__keepalive_loop":
        import core.ws_manager as wsm
        original_key = wsm._listen_key
        wsm._listen_key = "test_key"
        try:
            with patch("core.ws_manager.keepalive_listen_key",
                        new_callable=AsyncMock, side_effect=RL_EXC), \
                 patch("asyncio.sleep", side_effect=_loop_sleep_factory()):
                with pytest.raises(asyncio.CancelledError):
                    await wsm._keepalive_loop()
        finally:
            wsm._listen_key = original_key

    elif site_id == "ws__fallback_loop":
        app_state.ws_status.using_fallback = True
        with patch("core.ws_manager.fetch_account",
                    new_callable=AsyncMock, side_effect=RL_EXC), \
             patch("asyncio.sleep", side_effect=_loop_sleep_factory()):
            with pytest.raises(asyncio.CancelledError):
                from core.ws_manager import _fallback_loop
                await _fallback_loop()
        app_state.ws_status.using_fallback = False

    else:
        pytest.fail(f"Unknown site_id: {site_id}")

    # ── Common assertion ─────────────────────────────────────────────────────
    assert app_state.ws_status.rate_limited_until is not None, (
        f"Site '{site_id}': rate_limited_until was NOT set after "
        f"ccxt.RateLimitExceeded — handle_rate_limit_error not called"
    )
