"""
Phase 0.0.4 (T186) tests for reversal-split.

Closes T178 Layer 4: a single Binance fill that crosses zero (LONG to
SHORT or SHORT to LONG in one event) was previously recorded as ONE
fill row with ``is_close=True``, losing the implicit "open of new
direction" entirely. The new behavior records TWO rows:

  1. Close of the OLD position. ``exchange_fill_id = {tradeId}``,
     ``qty = |qty_before|``, ``direction = old``, ``is_close = True``.
  2. Open of the NEW opposite-direction position.
     ``exchange_fill_id = "synth:{tradeId}:open"``,
     ``qty = fill_qty - |qty_before|``, ``direction = new``,
     ``is_close = False``.

Tests cover:

A. ``compute_fill_snapshot`` populates ``snapshot.splits`` correctly on
   reversal events (both LONG->SHORT and SHORT->LONG) and leaves
   ``splits == []`` on ordinary opens / closes / partials / scale-in.

B. ``OrderManager._process_reversal_split`` writes two fills with the
   right qty/direction/fill_id/is_close/fee/realized_pnl values when
   driven by a real position-state reversal.

Run: pytest tests/test_phase0_0_4_reversal_split.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from unittest.mock import patch

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.position_snapshot import (
    FillSnapshot,
    FillSplit,
    compute_fill_snapshot,
)


# Mock position object matching app_state.positions interface
@dataclass
class MockPosition:
    ticker: str = ""
    direction: str = ""   # "LONG" | "SHORT"
    contract_amount: float = 0.0
    position_id: str = ""


# ── A. compute_fill_snapshot: splits population ─────────────────────────


class TestSnapshotSplitsOnReversal:
    """When a single fill crosses zero, ``splits`` is populated with
    a (close_old, open_new) pair using the documented synthetic id
    format."""

    def test_long_to_short_reversal_populates_splits(self):
        # Net LONG 5; SELL 12 → net SHORT 7. The fill closes 5 LONG
        # then opens 7 SHORT.
        pos = MockPosition(ticker="BTCUSDT", direction="LONG", contract_amount=5.0)
        fill = {
            "exchange_fill_id": "tid-100",
            "symbol": "BTCUSDT",
            "side": "SELL",
            "quantity": 12.0,
            "timestamp_ms": 1000,
        }
        snap = compute_fill_snapshot(fill, [pos])
        assert snap.qty_before == 5.0
        assert snap.qty_after == pytest.approx(-7.0)
        assert snap.is_close is True
        assert snap.is_open is True   # also opens opposite-direction
        assert len(snap.splits) == 2

        close_split, open_split = snap.splits
        assert close_split.is_close is True
        assert close_split.direction == "LONG"
        assert close_split.quantity == pytest.approx(5.0)
        assert close_split.exchange_fill_id == "tid-100"

        assert open_split.is_close is False
        assert open_split.direction == "SHORT"
        assert open_split.quantity == pytest.approx(7.0)
        assert open_split.exchange_fill_id == "synth:tid-100:open"

    def test_short_to_long_reversal_populates_splits(self):
        # Net SHORT 3; BUY 8 → net LONG 5. The fill closes 3 SHORT
        # then opens 5 LONG.
        pos = MockPosition(ticker="ETHUSDT", direction="SHORT", contract_amount=3.0)
        fill = {
            "exchange_fill_id": "tid-200",
            "symbol": "ETHUSDT",
            "side": "BUY",
            "quantity": 8.0,
            "timestamp_ms": 2000,
        }
        snap = compute_fill_snapshot(fill, [pos])
        assert snap.qty_before == pytest.approx(-3.0)
        assert snap.qty_after == pytest.approx(5.0)
        assert len(snap.splits) == 2

        close_split, open_split = snap.splits
        assert close_split.is_close is True
        assert close_split.direction == "SHORT"
        assert close_split.quantity == pytest.approx(3.0)
        assert close_split.exchange_fill_id == "tid-200"

        assert open_split.is_close is False
        assert open_split.direction == "LONG"
        assert open_split.quantity == pytest.approx(5.0)
        assert open_split.exchange_fill_id == "synth:tid-200:open"

    def test_empty_fill_id_skips_split_to_avoid_synth_id_collision(self):
        # T187 audit fix: if the upstream adapter doesn't supply a fill_id
        # (shouldn't happen for real WS events, but defended for safety),
        # skip the split. Otherwise the synthetic open id would fall back
        # to "synth::open" and collide on the UNIQUE constraint across any
        # later empty-id reversal — silently losing the second fill.
        # Degrading to the single-write path is safer than producing
        # rows that lose to the UNIQUE constraint.
        pos = MockPosition(ticker="DOGEUSDT", direction="LONG", contract_amount=100.0)
        fill = {
            "exchange_fill_id": "",   # missing — adapter bug
            "symbol": "DOGEUSDT",
            "side": "SELL",
            "quantity": 150.0,
            "timestamp_ms": 3000,
        }
        snap = compute_fill_snapshot(fill, [pos])
        # Aggregate flags still reflect the reversal — only the per-split
        # routing is suppressed.
        assert snap.is_close is True
        assert snap.is_open is True
        assert snap.qty_after == pytest.approx(-50.0)
        # No splits → upstream takes the single-write path.
        assert snap.splits == []


class TestSnapshotSplitsEmptyOnNonReversal:
    """Splits is empty for any non-reversal — ordinary closes, opens,
    partial closes, scale-in. The single-write path stays in effect."""

    def test_partial_close_no_splits(self):
        pos = MockPosition(ticker="BTCUSDT", direction="LONG", contract_amount=5.0)
        fill = {
            "exchange_fill_id": "F1", "symbol": "BTCUSDT",
            "side": "SELL", "quantity": 2.0, "timestamp_ms": 1000,
        }
        snap = compute_fill_snapshot(fill, [pos])
        assert snap.is_close is True
        assert snap.is_partial_close is True
        assert snap.splits == []

    def test_full_close_no_splits(self):
        pos = MockPosition(ticker="BTCUSDT", direction="LONG", contract_amount=2.0)
        fill = {
            "exchange_fill_id": "F2", "symbol": "BTCUSDT",
            "side": "SELL", "quantity": 2.0, "timestamp_ms": 1000,
        }
        snap = compute_fill_snapshot(fill, [pos])
        assert snap.is_close is True
        assert snap.qty_after == 0.0
        assert snap.splits == []

    def test_open_from_flat_no_splits(self):
        fill = {
            "exchange_fill_id": "F3", "symbol": "BTCUSDT",
            "side": "BUY", "quantity": 1.0, "timestamp_ms": 1000,
        }
        snap = compute_fill_snapshot(fill, [])
        assert snap.is_open is True
        assert snap.is_close is False
        assert snap.splits == []

    def test_scale_in_no_splits(self):
        pos = MockPosition(ticker="BTCUSDT", direction="LONG", contract_amount=1.0)
        fill = {
            "exchange_fill_id": "F4", "symbol": "BTCUSDT",
            "side": "BUY", "quantity": 0.5, "timestamp_ms": 1000,
        }
        snap = compute_fill_snapshot(fill, [pos])
        assert snap.is_open is True
        assert snap.is_close is False
        assert snap.splits == []

    def test_hedge_mode_no_splits(self):
        # Hedge mode skips the one-way reversal logic entirely.
        pos = MockPosition(ticker="BTCUSDT", direction="LONG", contract_amount=1.0)
        fill = {
            "exchange_fill_id": "F5", "symbol": "BTCUSDT",
            "side": "SELL", "direction": "LONG", "quantity": 1.0,
            "is_close": True, "timestamp_ms": 1000,
        }
        snap = compute_fill_snapshot(fill, [pos], mode="hedge")
        assert snap.mode == "hedge"
        assert snap.splits == []


# ── B. OrderManager._process_reversal_split: end-to-end fill writes ────


@pytest_asyncio.fixture
async def test_db():
    from core.database import DatabaseManager

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(path=tmp.name)
    await db.initialize()
    yield db
    await db.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


@pytest_asyncio.fixture
async def order_manager(test_db):
    """OrderManager with a tempfile DB. Patches global db.execute paths
    where needed."""
    from core.order_manager import OrderManager
    om = OrderManager(test_db)
    # The deferred-close lambda calls _build_close_row_for_fill which
    # reads from the global db. For Phase 0.0.4 tests we don't exercise
    # the deferred path — the 2-second call_later schedules into the
    # event loop and is cancelled when the fixture tears down.
    yield om


async def _all_fills(db, account_id=1):
    async with db._conn.execute(
        "SELECT * FROM fills WHERE account_id=? ORDER BY id ASC",
        (account_id,),
    ) as cur:
        return [dict(r) for r in await cur.fetchall()]


def _make_fill(
    *, tradeId, symbol="BTCUSDT", side="SELL", quantity=12.0,
    price=80000.0, fee=0.4, realized_pnl=50.0,
    direction="BOTH",   # Binance one-way mode positionSide; triggers
                        # one_way branch in _snapshot_and_fix_isclose's
                        # mode-detection heuristic. Reversal-split only
                        # fires in one-way mode (hedge mode is per-side
                        # and never crosses zero in a single fill).
    timestamp_ms=1716000000000,
    exchange_order_id="ord-1", terminal_position_id="pos-old",
):
    return {
        "exchange_fill_id":     tradeId,
        "exchange_order_id":    exchange_order_id,
        "symbol":               symbol,
        "side":                 side,
        "direction":            direction,
        "price":                price,
        "quantity":             quantity,
        "fee":                  fee,
        "fee_asset":            "USDT",
        "realized_pnl":         realized_pnl,
        "timestamp_ms":         timestamp_ms,
        "terminal_position_id": terminal_position_id,
        "is_close":             1,
        "source":               "binance_ws",
    }


class TestProcessReversalSplitWritesTwoFills:
    """The end-to-end behavior: a process_fill on a reversal produces
    exactly two rows in the fills table with the documented shape."""

    @pytest.mark.asyncio
    async def test_long_to_short_writes_close_then_open(
        self, order_manager, test_db,
    ):
        # Pre-state: net LONG 5 on BTCUSDT. Fill: SELL 12 (closes 5
        # LONG, opens 7 SHORT).
        fake_pos = MockPosition(
            ticker="BTCUSDT", direction="LONG",
            contract_amount=5.0, position_id="pos-old",
        )
        fill = _make_fill(
            tradeId="tid-LR",
            quantity=12.0, fee=0.4, realized_pnl=50.0,
        )

        with patch("core.order_manager.app_state") as mock_state:
            mock_state.positions = [fake_pos]
            mock_state.active_account_id = 1
            await order_manager.process_fill(1, fill)

        fills = await _all_fills(test_db)
        assert len(fills) == 2, "reversal must produce 2 fill rows"

        # First written is the close portion (id ASC ordering).
        close, opn = fills[0], fills[1]

        # Close portion
        assert close["exchange_fill_id"] == "tid-LR"
        assert int(close["is_close"]) == 1
        assert close["direction"] == "LONG"
        assert close["quantity"] == pytest.approx(5.0)
        # Fee allocated by qty ratio: 5/12 of 0.4 = 0.1666...
        assert close["fee"] == pytest.approx(0.4 * 5 / 12)
        # Realized PnL retained on the close portion only.
        assert close["realized_pnl"] == pytest.approx(50.0)
        # Old position id preserved on the close portion.
        assert close["terminal_position_id"] == "pos-old"

        # Open portion
        assert opn["exchange_fill_id"] == "synth:tid-LR:open"
        assert int(opn["is_close"]) == 0
        assert opn["direction"] == "SHORT"
        assert opn["quantity"] == pytest.approx(7.0)
        # Fee remainder: 7/12 of 0.4 = 0.2333...
        assert opn["fee"] == pytest.approx(0.4 * 7 / 12)
        # PnL zeroed on the open portion.
        assert opn["realized_pnl"] == 0.0
        # terminal_position_id cleared on open — new position; pos_id
        # comes from the next ACCOUNT_UPDATE event.
        assert opn["terminal_position_id"] == ""

    @pytest.mark.asyncio
    async def test_short_to_long_writes_close_then_open(
        self, order_manager, test_db,
    ):
        fake_pos = MockPosition(
            ticker="ETHUSDT", direction="SHORT",
            contract_amount=3.0, position_id="pos-old-eth",
        )
        fill = _make_fill(
            tradeId="tid-RL",
            symbol="ETHUSDT", side="BUY",
            quantity=8.0, price=3000.0,
            fee=0.24, realized_pnl=30.0,
            # default direction="BOTH" — one-way mode; the snapshot
            # then reads the actual direction from mock_state.positions
            terminal_position_id="pos-old-eth",
        )

        with patch("core.order_manager.app_state") as mock_state:
            mock_state.positions = [fake_pos]
            mock_state.active_account_id = 1
            await order_manager.process_fill(1, fill)

        fills = await _all_fills(test_db)
        assert len(fills) == 2

        close, opn = fills[0], fills[1]
        assert close["exchange_fill_id"] == "tid-RL"
        assert close["direction"] == "SHORT"
        assert close["quantity"] == pytest.approx(3.0)
        assert close["fee"] == pytest.approx(0.24 * 3 / 8)
        assert close["realized_pnl"] == pytest.approx(30.0)
        assert int(close["is_close"]) == 1

        assert opn["exchange_fill_id"] == "synth:tid-RL:open"
        assert opn["direction"] == "LONG"
        assert opn["quantity"] == pytest.approx(5.0)
        assert opn["fee"] == pytest.approx(0.24 * 5 / 8)
        assert opn["realized_pnl"] == 0.0
        assert int(opn["is_close"]) == 0
        assert opn["terminal_position_id"] == ""


class TestProcessFillSingleWriteWhenNoReversal:
    """Non-reversal fills still take the single-write path (one row)."""

    @pytest.mark.asyncio
    async def test_partial_close_single_row(
        self, order_manager, test_db,
    ):
        fake_pos = MockPosition(
            ticker="BTCUSDT", direction="LONG",
            contract_amount=5.0, position_id="pos-keep",
        )
        fill = _make_fill(
            tradeId="tid-partial", quantity=2.0,
            fee=0.1, realized_pnl=20.0,
        )

        with patch("core.order_manager.app_state") as mock_state:
            mock_state.positions = [fake_pos]
            mock_state.active_account_id = 1
            await order_manager.process_fill(1, fill)

        fills = await _all_fills(test_db)
        assert len(fills) == 1
        f = fills[0]
        assert f["exchange_fill_id"] == "tid-partial"
        assert f["quantity"] == pytest.approx(2.0)
        # Fee NOT split — full fill stays as one row.
        assert f["fee"] == pytest.approx(0.1)


class TestWsPipelineIntegration:
    """T187 audit fix for H1: verify the FULL pipeline from raw Binance
    WS message → ws_manager._create_fill_from_ws → order_manager.process_fill
    → 2 DB rows. A regression in ws_manager.py:371's direction-inference
    logic (e.g., a Binance API contract change) would silently disable
    reversal-split, and the dispatcher-level Phase 0.0.4 tests would not
    catch it. This test pins the integration."""

    @pytest.mark.asyncio
    async def test_ws_one_way_reversal_writes_two_fills_end_to_end(
        self, test_db,
    ):
        from unittest.mock import MagicMock, patch
        from core import ws_manager
        from core.order_manager import OrderManager

        om = OrderManager(test_db)

        fake_pos = MockPosition(
            ticker="BTCUSDT", direction="LONG",
            contract_amount=5.0, position_id="pos-old",
        )

        # Real Binance one-way mode WS raw event. ps="BOTH" is the
        # critical token — anything else would route to hedge mode and
        # silently bypass reversal-split.
        raw_msg = {
            "o": {
                "t":  "binance-trade-99",   # tradeId
                "i":  "binance-order-1",    # orderId
                "s":  "BTCUSDT",            # symbol
                "S":  "SELL",               # side
                "ps": "BOTH",               # positionSide (one-way)
                "L":  80000.0,              # lastFilledPrice
                "l":  12.0,                 # lastFilledQty (crosses zero)
                "n":  0.4,                  # commission
                "N":  "USDT",
                "rp": 50.0,                 # realizedProfit
                "m":  False,
                "T":  1716000000000,
            }
        }

        with patch.object(ws_manager, "app_state") as mock_ws_state, \
             patch("core.order_manager.app_state") as mock_om_state, \
             patch("core.order_manager_singleton.order_manager", om):
            mock_ws_state.active_account_id = 1
            mock_ws_state.positions = [fake_pos]
            mock_om_state.active_account_id = 1
            mock_om_state.positions = [fake_pos]
            await ws_manager._create_fill_from_ws(order=None, raw_msg=raw_msg)

        fills = await _all_fills(test_db)
        assert len(fills) == 2, (
            "WS one-way mode reversal must produce 2 fill rows end-to-end. "
            "If this fails, check core/ws_manager.py:371 for changes to the "
            "direction-inference logic that may have re-routed one-way "
            "events into hedge mode."
        )

        close, opn = fills[0], fills[1]

        # Close portion
        assert close["exchange_fill_id"] == "binance-trade-99"
        assert int(close["is_close"]) == 1
        assert close["direction"] == "LONG"   # OLD direction
        assert close["quantity"] == pytest.approx(5.0)

        # Open portion — synthetic id, opposite direction.
        assert opn["exchange_fill_id"] == "synth:binance-trade-99:open"
        assert int(opn["is_close"]) == 0
        assert opn["direction"] == "SHORT"   # NEW direction
        assert opn["quantity"] == pytest.approx(7.0)


class TestSyntheticIdUniqueness:
    """The synthetic id never collides with Binance's numeric
    tradeIds — Binance tradeIds are decimal-digit-only strings, and the
    synth: prefix prevents collisions across re-imports."""

    def test_synth_prefix_distinguishes_from_numeric_tradeid(self):
        pos = MockPosition(
            ticker="BTCUSDT", direction="LONG", contract_amount=1.0,
        )
        fill = {
            "exchange_fill_id": "170796285",   # realistic Binance id
            "symbol": "BTCUSDT",
            "side": "SELL",
            "quantity": 3.0,
            "timestamp_ms": 1000,
        }
        snap = compute_fill_snapshot(fill, [pos])
        assert snap.splits[0].exchange_fill_id == "170796285"
        # Synthetic id is a non-numeric prefixed string — cannot collide
        # with any Binance numeric id.
        synth_id = snap.splits[1].exchange_fill_id
        assert synth_id == "synth:170796285:open"
        assert not synth_id.isdigit()
        assert synth_id.startswith("synth:")
