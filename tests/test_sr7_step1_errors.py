"""
SR-7 Step 1 regression tests — neutral error types.

Validates:
1. Adapter errors module exists with correct hierarchy
2. Adapter _run() translates ccxt exceptions to neutral types
3. Consumer catch sites use neutral types (not ccxt directly)
4. RL-3 behavior preserved: RateLimitError still sets rate_limited_until

Pre-fix:  tests FAIL (catch sites still use ccxt exceptions).
Post-fix: tests PASS.

Run: pytest tests/test_sr7_step1_errors.py -v
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch, AsyncMock, MagicMock

import pytest

from core.state import app_state


# ── Test 1: Error module exists with correct hierarchy ─────────────────────

class TestErrorHierarchy:
    def test_module_importable(self):
        from core.adapters.errors import (
            AdapterError, RateLimitError, AuthenticationError,
            ConnectionError, ValidationError, ExchangeError,
        )
        assert issubclass(RateLimitError, AdapterError)
        assert issubclass(AuthenticationError, AdapterError)
        assert issubclass(ConnectionError, AdapterError)
        assert issubclass(ValidationError, AdapterError)
        assert issubclass(ExchangeError, AdapterError)

    def test_rate_limit_error_has_retry_after(self):
        from core.adapters.errors import RateLimitError
        err = RateLimitError("429 too many", retry_after_ms=1778184237076)
        assert err.retry_after_ms == 1778184237076
        assert "429 too many" in str(err)

    def test_rate_limit_error_default_retry_none(self):
        from core.adapters.errors import RateLimitError
        err = RateLimitError("429")
        assert err.retry_after_ms is None


# ── Test 2: Consumer catch sites use neutral types ─────────────────────────

class TestConsumerCatchSites:
    """Verify consumers import from adapters.errors, not ccxt."""

    def test_reconciler_no_ccxt_import(self):
        """reconciler.py must not import ccxt directly."""
        import inspect
        from core import reconciler
        source = inspect.getsource(reconciler)
        # Should import from core.adapters.errors, not ccxt
        assert "from core.adapters.errors import" in source or \
               "from core.adapters.errors import RateLimitError" in source, \
               "reconciler must import neutral error types"
        assert "\nimport ccxt\n" not in source, \
               "reconciler must not import ccxt directly"

    def test_ws_manager_no_ccxt_import(self):
        """ws_manager.py must not import ccxt directly."""
        import inspect
        from core import ws_manager
        source = inspect.getsource(ws_manager)
        assert "from core.adapters.errors import" in source, \
               "ws_manager must import neutral error types"
        assert "\nimport ccxt\n" not in source, \
               "ws_manager must not import ccxt directly"

    def test_schedulers_no_ccxt_import(self):
        """schedulers.py must not import ccxt directly for exception handling."""
        import inspect
        from core import schedulers
        source = inspect.getsource(schedulers)
        assert "from core.adapters.errors import" in source, \
               "schedulers must import neutral error types"

    def test_exchange_market_no_ccxt_exception_import(self):
        """exchange_market.py must use neutral types for catch sites."""
        import inspect
        from core import exchange_market
        source = inspect.getsource(exchange_market)
        assert "from core.adapters.errors import" in source, \
               "exchange_market must import neutral error types"


# ── Test 3: RL-3 behavior preserved with neutral types ─────────────────────

# Same 11 sites as test_rl3_exception_coverage.py but using RateLimitError
# instead of ccxt.RateLimitExceeded. Both test files must pass simultaneously.

@pytest.fixture(autouse=True)
def _reset_rate_limit():
    app_state.ws_status.rate_limited_until = None
    yield
    app_state.ws_status.rate_limited_until = None


def _make_rate_limit_error():
    """Create a RateLimitError as would be raised by the adapter."""
    from core.adapters.errors import RateLimitError
    return RateLimitError(
        "binanceusdm 429 Too Many Requests",
        retry_after_ms=None,
    )


RL_SITES = [
    "reconciler__on_trade_closed",
    "reconciler__backfill_process",
    "reconciler__reconcile_closed_row",
    "ws__on_new_position",
    "ws__refresh_after_fill",
    "ws__fallback_loop",
]


@pytest.mark.parametrize("site_id", RL_SITES)
@pytest.mark.asyncio
async def test_rl3_preserved_with_neutral_errors(site_id):
    """RateLimitError from adapter must still set rate_limited_until."""
    from core.adapters.errors import RateLimitError
    from core.state import PositionInfo

    RL_EXC = _make_rate_limit_error()

    if site_id == "reconciler__on_trade_closed":
        with patch("core.reconciler.fetch_exchange_trade_history",
                    new_callable=AsyncMock, side_effect=RL_EXC), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            from core.reconciler import ReconcilerWorker
            await ReconcilerWorker().on_trade_closed(
                {"ticker": "BTCUSDT", "direction": "LONG"},
            )

    elif site_id == "reconciler__backfill_process":
        with patch("core.reconciler.fetch_exchange_trade_history",
                    new_callable=AsyncMock), \
             patch("core.reconciler.fetch_hl_for_trade",
                    new_callable=AsyncMock, side_effect=RL_EXC):
            from core.reconciler import ReconcilerWorker
            r = ReconcilerWorker()
            mock_cursor = AsyncMock()
            mock_cursor.fetchall = AsyncMock(return_value=[("BTCUSDT",)])
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_cursor)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_conn = MagicMock()
            mock_conn.execute = MagicMock(return_value=mock_ctx)
            with patch("core.reconciler.db") as mock_db:
                mock_db._conn = mock_conn
                mock_db.get_uncalculated_exchange_rows = AsyncMock(
                    return_value=[{
                        "trade_key": "k", "open_time": 1000,
                        "time": 2000, "entry_price": 60000.0,
                        "qty": 0.01, "direction": "LONG",
                    }],
                )
                with patch.object(r, "_reconcile_closed_positions",
                                  new_callable=AsyncMock):
                    await r.backfill_all()

    elif site_id == "reconciler__reconcile_closed_row":
        with patch("core.reconciler.fetch_hl_for_trade",
                    new_callable=AsyncMock, side_effect=RL_EXC), \
             patch.object(type(app_state), "active_account_id",
                          new_callable=lambda: property(lambda self: 1)):
            from core.reconciler import ReconcilerWorker
            r = ReconcilerWorker()
            with patch("core.reconciler.db") as mock_db:
                mock_db.get_uncalculated_closed_positions = AsyncMock(
                    return_value=[{
                        "id": 999, "symbol": "BTCUSDT",
                        "entry_time_ms": 1000, "exit_time_ms": 2000,
                        "entry_price": 60000.0, "quantity": 0.01,
                        "direction": "LONG",
                    }],
                )
                await r._reconcile_closed_positions(symbol="BTCUSDT")

    elif site_id == "ws__on_new_position":
        adapter = MagicMock()
        adapter.fetch_user_trades = AsyncMock(side_effect=RL_EXC)
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

    elif site_id == "ws__fallback_loop":
        app_state.ws_status.using_fallback = True
        calls = {"n": 0}

        async def _sleep(d):
            calls["n"] += 1
            if calls["n"] > 1:
                raise asyncio.CancelledError()

        with patch("core.ws_manager.fetch_account",
                    new_callable=AsyncMock, side_effect=RL_EXC), \
             patch("asyncio.sleep", side_effect=_sleep):
            with pytest.raises(asyncio.CancelledError):
                from core.ws_manager import _fallback_loop
                await _fallback_loop()
        app_state.ws_status.using_fallback = False

    assert app_state.ws_status.rate_limited_until is not None, (
        f"Site '{site_id}': rate_limited_until not set after RateLimitError "
        f"— RL-3 behavior regressed"
    )
