"""Window-aware income fetch (2026-07-10): cover offline gaps longer than
Binance's ~7-day income window so gap detection sees the older trades.

Root cause of the miss: a single no-startTime income fetch returns only the
recent ~7 days; after a >7-day offline gap the older trades (e.g. 2026-06-28/29
PUNDIX/TAC/IN) never reach exchange_history → never detected → never recovered
into closed_positions / Position History. _fetch_income_windowed pages the
window forward from an anchor to now.
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import core.exchange_income as ei

DAY = 86_400_000
BASE = 1_000_000_000_000


def _rows(specs):
    return [
        {"time": t, "symbol": s, "incomeType": "REALIZED_PNL",
         "tradeId": f"{s}-{t}-{i}", "income": inc}
        for i, (t, s, inc) in enumerate(specs)
    ]


def _fake_income(all_rows):
    """Simulate Binance income: startTime selects rows in [start, start+7d],
    ascending, capped at `limit`."""
    async def fake(income_type="", start_ms=None, limit=1000):
        lo = int(start_ms or 0)
        hi = lo + 7 * DAY
        sel = [r for r in all_rows
               if (not income_type or r["incomeType"] == income_type)
               and lo <= r["time"] < hi]
        sel.sort(key=lambda r: r["time"])
        return sel[:limit]
    return fake


@pytest.mark.asyncio
async def test_covers_gap_beyond_7_days():
    rows = _rows([(BASE, "A", -1), (BASE + 3 * DAY, "B", -2),
                  (BASE + 10 * DAY, "C", -3), (BASE + 20 * DAY, "D", -4)])
    with patch.object(ei, "fetch_income_history", _fake_income(rows)):
        got = await ei._fetch_income_windowed("REALIZED_PNL", BASE, BASE + 21 * DAY)
    assert sorted(r["time"] for r in got) == [BASE, BASE + 3 * DAY, BASE + 10 * DAY, BASE + 20 * DAY]


@pytest.mark.asyncio
async def test_single_fetch_would_miss_but_windowed_captures():
    # The bug in miniature: one 7-day fetch sees only the first window.
    rows = _rows([(BASE, "A", -1), (BASE + 10 * DAY, "C", -3)])
    fake = _fake_income(rows)
    single = await fake(income_type="REALIZED_PNL", start_ms=BASE, limit=1000)
    assert len(single) == 1                       # day-10 row invisible = the bug
    with patch.object(ei, "fetch_income_history", fake):
        got = await ei._fetch_income_windowed("REALIZED_PNL", BASE, BASE + 11 * DAY)
    assert len(got) == 2                           # windowed captures both


@pytest.mark.asyncio
async def test_burst_exceeds_page_limit():
    # 1200 events in one span > the 1000-row page → full-page advance must
    # continue from max_time (IN had 841 in a day; a busy scalp day can exceed
    # a page). 1s apart so each has a distinct timestamp.
    rows = _rows([(BASE + i * 1000, "X", -0.1) for i in range(1200)])
    with patch.object(ei, "fetch_income_history", _fake_income(rows)):
        got = await ei._fetch_income_windowed("REALIZED_PNL", BASE, BASE + 8 * DAY)
    assert len(got) == 1200


@pytest.mark.asyncio
async def test_full_page_same_ms_boundary_not_dropped():
    # Heavy week: >1000 rows in one 7-day window with a same-millisecond group
    # straddling the 1000-row page boundary. Advancing by max_t+1 would drop the
    # rows at max_t beyond the 1000th; advancing by max_t (re-fetch + dedup)
    # keeps them. rows 0..993 distinct, then 16 rows ALL at time T (so the 1000th
    # oldest lands mid-group).
    T = BASE + 994 * 1000
    specs = [(BASE + i * 1000, "X", -0.1) for i in range(994)]
    specs += [(T, "X", -0.1) for _ in range(16)]   # 16 events sharing one ms
    rows = _rows(specs)                              # 1010 total
    with patch.object(ei, "fetch_income_history", _fake_income(rows)):
        got = await ei._fetch_income_windowed("REALIZED_PNL", BASE, BASE + 8 * DAY)
    assert len(got) == 1010                          # none lost at the tie boundary


@pytest.mark.asyncio
async def test_skips_empty_windows():
    # 30-day quiet gap between two rows — the empty-window step must reach day 30.
    rows = _rows([(BASE, "A", -1), (BASE + 30 * DAY, "Z", -9)])
    with patch.object(ei, "fetch_income_history", _fake_income(rows)):
        got = await ei._fetch_income_windowed("REALIZED_PNL", BASE, BASE + 31 * DAY)
    assert len(got) == 2


@pytest.mark.asyncio
async def test_dedup_on_overlap():
    # Overlapping windows (the anchor re-fetches the boundary) must not duplicate.
    rows = _rows([(BASE, "A", -1), (BASE + DAY, "A", -1)])
    with patch.object(ei, "fetch_income_history", _fake_income(rows)):
        got = await ei._fetch_income_windowed("REALIZED_PNL", BASE, BASE + 2 * DAY)
    keys = {(r["symbol"], r["time"], r["tradeId"]) for r in got}
    assert len(got) == len(keys) == 2


@pytest.mark.asyncio
async def test_empty_ledger_returns_empty():
    with patch.object(ei, "fetch_income_history", _fake_income([])):
        got = await ei._fetch_income_windowed("REALIZED_PNL", BASE, BASE + 30 * DAY)
    assert got == []
