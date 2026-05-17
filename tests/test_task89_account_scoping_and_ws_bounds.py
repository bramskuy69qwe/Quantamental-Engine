"""
Task 89 regression tests:

CRIT-006: core/data_logger.export_all_to_excel must scope to
app_state.active_account_id, not the db.get_all_* methods' default
account_id=1. Two tests — an explicit pin on all three call sites plus
an integration test that exercises the real DB layer with two accounts.

CRIT-005: core/ws_manager._reconnect_user is bounded by
config.WS_RECONNECT_ATTEMPTS via the line-477 guard. A pin test asserts
persistent create_listen_key failure does NOT cause RecursionError.

Run: pytest tests/test_task89_account_scoping_and_ws_bounds.py -v
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

import core.data_logger as data_logger
import core.ws_manager as ws_manager


# ── CRIT-006: explicit pin ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_passes_active_account_id_to_all_three_db_calls(tmp_path, monkeypatch):
    """All three db.get_all_* calls must receive account_id matching
    app_state.active_account_id. Catches partial fixes."""
    from core.account_registry import account_registry
    monkeypatch.setattr(account_registry, "_active_id", 7)
    ptl = AsyncMock(return_value=[])
    ex = AsyncMock(return_value=[])
    th = AsyncMock(return_value=[])
    with patch.object(data_logger.db, "get_all_pre_trade_log", ptl), \
         patch.object(data_logger.db, "get_all_execution_log", ex), \
         patch.object(data_logger.db, "get_all_trade_history", th), \
         patch.object(data_logger, "_ensure_dirs", lambda: None):
        await data_logger.export_all_to_excel(path=str(tmp_path / "out.xlsx"))
    ptl.assert_awaited_once_with(days=365, account_id=7)
    ex.assert_awaited_once_with(days=365, account_id=7)
    th.assert_awaited_once_with(days=365, account_id=7)


# ── CRIT-006: integration ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_export_returns_only_active_account_rows(tmp_path, monkeypatch):
    """Seed two accounts' worth of data; assert export reflects active account."""
    from core.database import DatabaseManager
    db_path = str(tmp_path / "task89.db")
    mgr = DatabaseManager(path=db_path)
    await mgr.initialize()
    try:
        # account 1 distinctive row
        await mgr._conn.execute(
            "INSERT INTO pre_trade_log (timestamp, ticker, account_id) VALUES (?, ?, ?)",
            ("2026-05-18T00:00:00", "ACC1_ONLY", 1),
        )
        # account 2 distinctive row
        await mgr._conn.execute(
            "INSERT INTO pre_trade_log (timestamp, ticker, account_id) VALUES (?, ?, ?)",
            ("2026-05-18T00:00:01", "ACC2_ONLY", 2),
        )
        await mgr._conn.commit()

        monkeypatch.setattr(data_logger, "db", mgr)
        from core.account_registry import account_registry
        monkeypatch.setattr(account_registry, "_active_id", 2)
        monkeypatch.setattr(data_logger, "_ensure_dirs", lambda: None)

        await data_logger.export_all_to_excel(path=str(tmp_path / "out.xlsx"))
        # Open the xlsx and verify
        import openpyxl
        wb = openpyxl.load_workbook(str(tmp_path / "out.xlsx"))
        ws = wb["pre_trade_log"]
        rows = list(ws.iter_rows(values_only=True))
        # header + data; collect ticker column
        header = list(rows[0])
        ticker_idx = header.index("ticker")
        tickers = [r[ticker_idx] for r in rows[1:]]
        assert "ACC2_ONLY" in tickers, "Active account's row missing from export"
        assert "ACC1_ONLY" not in tickers, (
            "CRIT-006: export leaked account 1's row when active_account_id=2"
        )
    finally:
        await mgr._conn.close()


# ── CRIT-005: recursion-bound pin ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reconnect_user_bounded_by_max_attempts_no_recursion_error(monkeypatch):
    """The line-477 guard bounds recursion at config.WS_RECONNECT_ATTEMPTS.
    Persistent create_listen_key failure must NOT cause RecursionError.

    Pin against future refactors that might remove or move the guard."""
    # Shrink the bound for fast test execution
    monkeypatch.setattr(ws_manager.config, "WS_RECONNECT_ATTEMPTS", 3)

    # create_listen_key always fails
    async def boom():
        raise RuntimeError("simulated auth failure")
    monkeypatch.setattr(ws_manager, "create_listen_key", boom)

    # Skip the exponential backoff sleep
    async def no_sleep(*a, **kw):
        return None
    monkeypatch.setattr(ws_manager.asyncio, "sleep", no_sleep)

    # Reset reconnect attempts counter via ws_status
    ws_manager.app_state.ws_status.reconnect_attempts = 0

    # Should return cleanly, no RecursionError
    await ws_manager._reconnect_user(0)

    # Bound asserted: counter is incremented (line 476) before the guard fires
    # (line 477), so it ends at config.WS_RECONNECT_ATTEMPTS + 1.
    assert ws_manager.app_state.ws_status.reconnect_attempts == 4
