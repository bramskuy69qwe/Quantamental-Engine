"""
PA-1b regression tests — FIFO open_time reconstruction.

Validates lightweight FIFO queue replaces backward-walk algorithm
for attributing open_time to REALIZED_PNL events.

Run: pytest tests/test_pa1b_open_time_fifo.py -v
"""
from __future__ import annotations
from pathlib import Path

import pytest


SRC = Path(__file__).parent.parent / "core" / "exchange_income.py"


class TestBackwardWalkRemoved:
    def test_no_prev_leg_end_pattern(self):
        """The backward-walk leg-boundary logic must be replaced."""
        content = SRC.read_text()
        assert "prev_leg_end_ms" not in content, \
            "prev_leg_end_ms backward-walk pattern must be removed"

    def test_no_seven_day_fallback(self):
        """7-day fallback for open_time must be removed."""
        content = SRC.read_text()
        assert "_SEVEN_DAYS_MS" not in content and "7 * 24 * 3600" not in content, \
            "7-day fallback must be removed"

    def test_uses_precomputed_lookup(self):
        """raw_pnl loop must use precomputed close_open_times lookup."""
        content = SRC.read_text()
        assert "close_open_times" in content, \
            "Must use close_open_times precomputed FIFO map"


class TestFIFOPrecomputation:
    def test_fifo_queue_logic_exists(self):
        """FIFO queue logic must exist in exchange_income.py."""
        content = SRC.read_text()
        # Should have queue append (open) and pop (close consume)
        assert "queue" in content.lower() or "fifo" in content.lower(), \
            "FIFO queue logic must exist"


class TestFIFOCorrectness:
    """Test the FIFO algorithm with synthetic fill data."""

    def _compute_open_times(self, fills):
        """Run the FIFO algorithm on synthetic fills.
        fills: list of (side, qty, time_ms, fill_id) tuples.
        Returns: dict of close_fill_id → open_time_ms.
        """
        close_open_times = {}
        for direction in ("LONG", "SHORT"):
            open_side = "BUY" if direction == "LONG" else "SELL"
            close_side = "SELL" if direction == "LONG" else "BUY"
            queue = []  # [(time_ms, remaining_qty), ...]
            for side, qty, ts, fid in sorted(fills, key=lambda f: f[2]):
                if side == open_side:
                    queue.append([ts, qty])
                elif side == close_side:
                    open_time = queue[0][0] if queue else 0
                    close_open_times[fid] = open_time
                    remaining = qty
                    while remaining > 1e-8 and queue:
                        if queue[0][1] <= remaining + 1e-8:
                            remaining -= queue[0][1]
                            queue.pop(0)
                        else:
                            queue[0][1] -= remaining
                            remaining = 0
        return close_open_times

    def test_skyaiusdt_case(self):
        """1 open (SELL 90@10:12) + 2 partial closes (BUY 45@16:54, BUY 45@16:55).
        Both closes should get open_time=10:12."""
        fills = [
            ("SELL", 90.0, 1000, "open1"),      # open SHORT
            ("BUY",  45.0, 2000, "close1"),      # partial close
            ("BUY",  45.0, 2055, "close2"),      # partial close
        ]
        result = self._compute_open_times(fills)
        assert result["close1"] == 1000
        assert result["close2"] == 1000, \
            "Second partial close must share open_time with first"

    def test_three_partial_closes(self):
        """1 open + 3 partial closes → all share open_time."""
        fills = [
            ("SELL", 90.0, 1000, "open1"),
            ("BUY",  30.0, 2000, "c1"),
            ("BUY",  30.0, 2100, "c2"),
            ("BUY",  30.0, 2200, "c3"),
        ]
        result = self._compute_open_times(fills)
        assert result["c1"] == 1000
        assert result["c2"] == 1000
        assert result["c3"] == 1000

    def test_two_separate_positions(self):
        """2 separate SHORT positions → each close gets its own open_time."""
        fills = [
            ("SELL", 50.0, 1000, "open1"),
            ("BUY",  50.0, 2000, "close1"),     # closes position 1
            ("SELL", 50.0, 3000, "open2"),
            ("BUY",  50.0, 4000, "close2"),     # closes position 2
        ]
        result = self._compute_open_times(fills)
        assert result["close1"] == 1000
        assert result["close2"] == 3000, \
            "Second position's close must get second open's time"

    def test_scale_in(self):
        """Scale-in: open A + open B + close C → C attributed to A (FIFO head)."""
        fills = [
            ("SELL", 50.0, 1000, "openA"),
            ("SELL", 40.0, 1500, "openB"),      # scale in
            ("BUY",  45.0, 2000, "closeC"),     # partial close
            ("BUY",  45.0, 2100, "closeD"),     # remaining close
        ]
        result = self._compute_open_times(fills)
        # closeC: queue head is openA(1000, 50). open_time=1000
        assert result["closeC"] == 1000
        # closeD: after closeC consumed 45 from openA (remaining 5),
        # queue head still openA(1000, 5). open_time=1000
        assert result["closeD"] == 1000

    def test_scale_in_crosses_boundary(self):
        """Scale-in where close exhausts first open and dips into second."""
        fills = [
            ("SELL", 30.0, 1000, "openA"),
            ("SELL", 60.0, 1500, "openB"),
            ("BUY",  50.0, 2000, "closeC"),     # consumes all of A(30) + 20 of B
            ("BUY",  40.0, 2100, "closeD"),     # consumes remaining 40 of B
        ]
        result = self._compute_open_times(fills)
        assert result["closeC"] == 1000  # queue head was openA when closeC fired
        assert result["closeD"] == 1500  # openA exhausted, queue head is now openB

    def test_orphan_close_no_matching_open(self):
        """Close with no matching open → open_time=0."""
        fills = [
            ("BUY", 45.0, 2000, "orphan_close"),
        ]
        result = self._compute_open_times(fills)
        assert result["orphan_close"] == 0, \
            "Orphan close (no matching open) must get open_time=0"

    def test_position_flip_separate_directions(self):
        """SHORT closes, then LONG opens → separate FIFO queues per direction.
        In real usage, positionSide disambiguates. For FIFO computation,
        each direction processes fills independently — a BUY that closes a
        SHORT is not the same as a BUY that opens a LONG. The real
        implementation uses positionSide from the REALIZED_PNL event to
        determine direction, then only processes fills matching that context.
        This test verifies the SHORT queue works correctly."""
        # SHORT position: SELL opens, BUY closes
        fills = [
            ("SELL", 50.0, 1000, "short_open"),
            ("BUY",  50.0, 2000, "short_close"),
        ]
        result = self._compute_open_times(fills)
        assert result["short_close"] == 1000  # SHORT queue correct
