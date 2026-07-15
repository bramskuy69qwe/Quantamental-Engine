"""
Task 173 regression tests — WS fill ingestion routes through
order_manager.process_fill so closed_positions rows are built.

Bug context: prior to this task, core/ws_manager.py:_create_fill_from_ws
wrote fills directly via db.upsert_fill, bypassing
order_manager.process_fill. As a result, the close-aggregation pipeline
(_build_close_row_for_fill → insert_closed_position) never fired for
WS-arriving fills.

Symptom: when the Quantower plugin is disconnected (engine's own
Binance user-data WS is the sole fill source), fills land in the
fills table but never produce a closed_positions row. Position History
freezes at whatever the last engine restart's startup backfill
populated, and new closed trades remain invisible until the next
restart's exchange_history sweep catches them up.

Repro: opened/closed ALTUSDT today; DB had 8 ALTUSDT fills
(source=binance_ws) but zero ALT* closed_positions rows.

Fix: route _create_fill_from_ws through
order_manager.process_fill, and populate
terminal_position_id from app_state.positions before the call so
_build_close_row_for_fill uses the indexed terminal_position_id path
instead of falling back to (symbol, direction).

These tests:
  1. Assert _create_fill_from_ws calls order_manager.process_fill (not
     bare db.upsert_fill) when the order_manager singleton is available.
  2. Assert terminal_position_id is populated from app_state.positions
     when a matching (symbol, direction) position exists.
  3. Assert the function falls back to db.upsert_fill when
     order_manager.process_fill raises (defense in depth — the fill
     must always be persisted).
  4. Source-grep pin: _create_fill_from_ws references
     order_manager.process_fill.
  (v2.6: the singleton is core.order_manager_singleton.order_manager,
  not platform_bridge.order_manager.)

Run: pytest tests/test_task173_ws_fill_routes_through_process_fill.py -v
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


SRC_WS = Path(__file__).parent.parent / "core" / "ws_manager.py"


# ── Source-grep pins ─────────────────────────────────────────────────────────


class TestSourceGrepPins:
    def test_function_references_order_manager_process_fill(self):
        """_create_fill_from_ws must invoke order_manager.process_fill."""
        content = SRC_WS.read_text()
        assert "process_fill" in content, (
            "_create_fill_from_ws must route through order_manager.process_fill "
            "so close-aggregation fires for WS-arriving fills"
        )

    def test_function_populates_terminal_position_id_from_app_state(self):
        """_create_fill_from_ws must look up app_state.positions to populate
        terminal_position_id (not hardcode to '')."""
        content = SRC_WS.read_text()
        idx = content.find("async def _create_fill_from_ws")
        assert idx > 0, "function definition must exist"
        body = content[idx:idx + 3500]
        assert "app_state.positions" in body, (
            "_create_fill_from_ws must look up app_state.positions to populate "
            "terminal_position_id from the matching open position"
        )
        assert "terminal_position_id" in body and "position_id" in body, (
            "Function must assign position_id to terminal_position_id"
        )

    def test_function_retains_fallback_to_upsert_fill(self):
        """Defensive: function must still have a path to db.upsert_fill so the
        fill is persisted even if process_fill raises."""
        content = SRC_WS.read_text()
        idx = content.find("async def _create_fill_from_ws")
        assert idx > 0, "function definition must exist"
        body = content[idx:idx + 3500]
        assert "upsert_fill" in body, (
            "Function must retain a fallback to db.upsert_fill so the fill is "
            "persisted even when process_fill raises"
        )


# ── Behavioral tests ─────────────────────────────────────────────────────────


def _make_raw_msg(
    *, sym="ALTUSDT", side="BUY", trade_id="123456",
    price=0.00795, qty=4476, realized_pnl=0.0, ps="LONG",
) -> dict:
    """Build a minimal WS ORDER_TRADE_UPDATE message (Binance format)."""
    return {
        "o": {
            "t":  trade_id,           # tradeId
            "i":  "987654",           # orderId
            "s":  sym,                # symbol
            "S":  side,               # side
            "ps": ps,                 # positionSide
            "L":  price,              # lastFilledPrice
            "l":  qty,                # lastFilledQty
            "n":  0.001,              # commission
            "N":  "USDT",             # commissionAsset
            "rp": realized_pnl,       # realizedProfit
            "m":  False,              # isMaker
            "T":  1716000000000,      # transactionTime
        }
    }


class _FakePosition:
    def __init__(self, ticker, direction, position_id):
        self.ticker = ticker
        self.direction = direction
        self.position_id = position_id


@pytest.mark.asyncio
async def test_routes_through_order_manager_process_fill_when_available():
    """When the order_manager singleton is available, _create_fill_from_ws
    must call its process_fill (not bare db.upsert_fill)."""
    from core import ws_manager

    raw = _make_raw_msg(trade_id="t-1001")
    fake_om = MagicMock()
    fake_om.process_fill = AsyncMock()


    fake_db_upsert = AsyncMock()

    with patch.object(ws_manager, "app_state") as mock_state, \
         patch("core.order_manager_singleton.order_manager", fake_om):
        mock_state.active_account_id = 1
        mock_state.positions = []
        with patch("core.database.db.upsert_fill", fake_db_upsert):
            await ws_manager._create_fill_from_ws(order=None, raw_msg=raw)

    fake_om.process_fill.assert_awaited_once()
    args, _ = fake_om.process_fill.call_args
    account_id, fill = args
    assert account_id == 1
    assert fill["exchange_fill_id"] == "t-1001"
    assert fill["symbol"] == "ALTUSDT"
    assert fill["source"] == "binance_ws"
    # Bare upsert_fill must NOT have been used as the primary path.
    fake_db_upsert.assert_not_awaited()


@pytest.mark.asyncio
async def test_populates_terminal_position_id_from_app_state():
    """When a matching (ticker, direction) position exists in
    app_state.positions, the fill's terminal_position_id must be set to
    that position's position_id."""
    from core import ws_manager

    raw = _make_raw_msg(sym="ALTUSDT", ps="LONG", trade_id="t-2002")
    fake_pos = _FakePosition("ALTUSDT", "LONG", "pos-abc-123")

    fake_om = MagicMock()
    fake_om.process_fill = AsyncMock()

    with patch.object(ws_manager, "app_state") as mock_state, \
         patch("core.order_manager_singleton.order_manager", fake_om):
        mock_state.active_account_id = 1
        mock_state.positions = [fake_pos]
        await ws_manager._create_fill_from_ws(order=None, raw_msg=raw)

    args, _ = fake_om.process_fill.call_args
    _, fill = args
    assert fill["terminal_position_id"] == "pos-abc-123", (
        "terminal_position_id must be populated from the matching "
        "app_state.positions entry"
    )


@pytest.mark.asyncio
async def test_terminal_position_id_empty_when_no_matching_position():
    """When no app_state.positions entry matches (e.g., closing fill arrived
    after the position was already cleared from state), terminal_position_id
    falls back to empty string. Phase 0.0.5 (T188) made get_position_fills
    strict — empty pos_id returns []; the close-row builder then resolves
    opens via core.position_grouping.find_opens_for_position_close_at
    (chronological walk per (account, symbol, direction))."""
    from core import ws_manager

    raw = _make_raw_msg(sym="ALTUSDT", ps="LONG", trade_id="t-3003")
    other_pos = _FakePosition("BTCUSDT", "SHORT", "pos-other")

    fake_om = MagicMock()
    fake_om.process_fill = AsyncMock()

    with patch.object(ws_manager, "app_state") as mock_state, \
         patch("core.order_manager_singleton.order_manager", fake_om):
        mock_state.active_account_id = 1
        mock_state.positions = [other_pos]
        await ws_manager._create_fill_from_ws(order=None, raw_msg=raw)

    args, _ = fake_om.process_fill.call_args
    _, fill = args
    assert fill["terminal_position_id"] == "", (
        "No matching position → terminal_position_id is empty. Phase 0.0.5 "
        "removed the get_position_fills (symbol, direction) fallback; "
        "the close-row builder now uses position_grouping's chronological "
        "walk to resolve opens for this case."
    )


@pytest.mark.asyncio
async def test_falls_back_to_upsert_fill_when_process_fill_raises():
    """If process_fill raises, the fill must still be persisted via
    db.upsert_fill so we don't lose the fact of the fill."""
    from core import ws_manager

    raw = _make_raw_msg(trade_id="t-4004")
    fake_om = MagicMock()
    fake_om.process_fill = AsyncMock(side_effect=RuntimeError("simulated failure"))

    fake_db_upsert = AsyncMock()

    with patch.object(ws_manager, "app_state") as mock_state, \
         patch("core.order_manager_singleton.order_manager", fake_om):
        mock_state.active_account_id = 1
        mock_state.positions = []
        with patch("core.database.db.upsert_fill", fake_db_upsert):
            await ws_manager._create_fill_from_ws(order=None, raw_msg=raw)

    fake_om.process_fill.assert_awaited_once()
    fake_db_upsert.assert_awaited_once()
    args, _ = fake_db_upsert.call_args
    persisted = args[0]
    assert persisted["exchange_fill_id"] == "t-4004", (
        "Fallback must persist the same fill dict that process_fill failed on"
    )


@pytest.mark.asyncio
async def test_skips_when_trade_id_missing():
    """Pre-existing guard: trade_id absent or '0' → no DB writes at all."""
    from core import ws_manager

    raw = {"o": {"t": "0", "s": "ALTUSDT", "L": 1.0, "l": 1.0}}
    fake_om = MagicMock()
    fake_om.process_fill = AsyncMock()

    fake_db_upsert = AsyncMock()

    with patch.object(ws_manager, "app_state") as mock_state, \
         patch("core.order_manager_singleton.order_manager", fake_om):
        mock_state.active_account_id = 1
        mock_state.positions = []
        with patch("core.database.db.upsert_fill", fake_db_upsert):
            await ws_manager._create_fill_from_ws(order=None, raw_msg=raw)

    fake_om.process_fill.assert_not_awaited()
    fake_db_upsert.assert_not_awaited()
