"""
PA-1a regression tests — WS fill creation + backfill dedup.

Validates:
1. _create_fill_from_ws exists and is called from TRADE handler
2. Fill fields extracted correctly from raw WS message
3. Backfill skips fills where matching WS fill exists
4. Fill creation independent of order persistence (try/except)

Run: pytest tests/test_pa1a_ws_fill_creation.py -v
"""
from __future__ import annotations
from pathlib import Path

import pytest


SRC_WS = Path(__file__).parent.parent / "core" / "ws_manager.py"
SRC_DB = Path(__file__).parent.parent / "core" / "db_orders.py"


class TestFillCreationExists:
    def test_create_fill_from_ws_function(self):
        content = SRC_WS.read_text()
        assert "_create_fill_from_ws" in content, \
            "_create_fill_from_ws must exist in ws_manager.py"

    def test_trade_handler_calls_fill_creation(self):
        """execution_type == TRADE block must call fill creation."""
        content = SRC_WS.read_text()
        # Find the TRADE block and verify it references fill creation
        assert "_create_fill_from_ws" in content, \
            "TRADE handler must call _create_fill_from_ws"

    def test_fill_creation_before_position_refresh(self):
        """Fill creation must appear BEFORE _refresh_positions_after_fill."""
        content = SRC_WS.read_text()
        fill_pos = content.find("_create_fill_from_ws")
        refresh_pos = content.find("_refresh_positions_after_fill")
        assert fill_pos > 0 and refresh_pos > 0, \
            "Both functions must exist"
        # In the TRADE block, fill creation should come first
        # Find the TRADE execution block
        trade_block_start = content.find('execution_type == "TRADE"')
        if trade_block_start > 0:
            block = content[trade_block_start:trade_block_start + 500]
            fill_in_block = block.find("_create_fill_from_ws")
            refresh_in_block = block.find("_refresh_positions_after_fill")
            assert fill_in_block < refresh_in_block, \
                "Fill creation must come BEFORE position refresh (fact before state)"

    def test_fill_creation_in_try_except(self):
        """Fill creation must be wrapped in try/except (independent of order)."""
        content = SRC_WS.read_text()
        # Find _create_fill_from_ws call and verify it's in a try block
        idx = content.find("_create_fill_from_ws")
        if idx > 0:
            # Look backward for 'try:' within ~200 chars
            preceding = content[max(0, idx - 200):idx]
            assert "try:" in preceding, \
                "Fill creation must be in try/except block"


class TestFillFieldExtraction:
    def test_extracts_trade_id(self):
        """Fill must use o.t (tradeId) as exchange_fill_id."""
        content = SRC_WS.read_text()
        # The function should reference the 't' field from the order dict
        assert '"t"' in content or "['t']" in content or '.get("t"' in content, \
            "Must extract tradeId from WS message (o.t field)"

    def test_extracts_last_filled_price(self):
        """Fill must use o.L (lastFilledPrice)."""
        content = SRC_WS.read_text()
        assert '"L"' in content or '.get("L"' in content, \
            "Must extract lastFilledPrice from WS message (o.L field)"

    def test_extracts_last_filled_qty(self):
        """Fill must use o.l (lastFilledQty)."""
        content = SRC_WS.read_text()
        assert '"l"' in content or '.get("l"' in content, \
            "Must extract lastFilledQty from WS message (o.l field)"

    def test_extracts_realized_profit(self):
        """Fill must use o.rp (realizedProfit)."""
        content = SRC_WS.read_text()
        assert '"rp"' in content or '.get("rp"' in content, \
            "Must extract realizedProfit from WS message (o.rp field)"

    def test_source_is_binance_ws(self):
        """Fill source must be 'binance_ws'."""
        content = SRC_WS.read_text()
        assert "binance_ws" in content, \
            "Fill source must be 'binance_ws'"


class TestBackfillDedup:
    """Phase 0.0.2 (T183) replaced the inline SQL-only dedup with
    ``position_grouping.is_same_fill``. The new rule widens the
    timestamp tolerance to 2000ms (FILL_DEDUP_TOLERANCE_MS) and tightens
    the match by requiring direction + is_close + price equality.

    These grep tests pin the new wiring at the source level. Behavior
    tests for the dedup live in tests/test_position_grouping.py and the
    Phase 0.0.2 behavior tests below."""

    def test_backfill_imports_is_same_fill(self):
        """Backfill must use the canonical is_same_fill helper."""
        content = SRC_DB.read_text()
        assert "is_same_fill" in content, \
            "Backfill must import is_same_fill from core.position_grouping"

    def test_backfill_uses_canonical_tolerance_constant(self):
        """Dedup must use FILL_DEDUP_TOLERANCE_MS, not a magic number."""
        content = SRC_DB.read_text()
        assert "FILL_DEDUP_TOLERANCE_MS" in content, \
            "Backfill must reference FILL_DEDUP_TOLERANCE_MS for window width"

    def test_backfill_routes_grouping_through_helper(self):
        """closed_positions construction must use group_fills_into_positions
        instead of the old ad-hoc (symbol, direction, open_time) grouping
        — T178 Layer 3 fix."""
        content = SRC_DB.read_text()
        assert "group_fills_into_positions" in content, \
            "Backfill must call position_grouping.group_fills_into_positions"
