"""
v3.0 P8 wave 2 — backend pins for the two audit-mandated additions.

- L1-F1: `_journal_stats_context` carries a `daily_pnl` array (day-bucketed
  month PnL from get_daily_equity_series — the Monthly tile's bar chart).
- L1-F2: `/api/regime/signals/latest` ships each signal's 30d `series`
  (previously fetched and discarded).

Handler-direct with monkeypatched db methods (LOW-023 / F5 discipline —
no TestClient, no live data).
"""
from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import api.routes_dashboard as rd
import api.routes_regime as rr


class _StubDB:
    """Minimal async-db stub for _journal_stats_context's gather."""

    def __init__(self, daily):
        self._daily = daily

    async def get_journal_stats(self, *a, **k):
        return {"total_trades": 2, "winning_trades": 1, "losing_trades": 1,
                "avg_profit": 10.0, "avg_loss": -5.0}

    async def get_equity_period_boundaries(self, *a, **k):
        return {"initial_equity": 100.0, "final_equity": 110.0, "max_drawdown": 0.02}

    async def get_most_traded_pairs(self, *a, **k):
        return ["BTCUSDT"]

    async def get_daily_equity_series(self, *a, **k):
        return self._daily


@pytest.mark.asyncio
async def test_journal_context_carries_daily_pnl(monkeypatch):
    daily = [
        {"day": "2026-07-01", "total_equity": 101.0, "daily_pnl": 1.0,
         "daily_pnl_percent": 1.0, "drawdown": 0.0},
        {"day": "2026-07-02", "total_equity": 100.5, "daily_pnl": -0.5,
         "daily_pnl_percent": -0.5, "drawdown": 0.005},
        # a None-pnl row (no snapshot delta) must be DROPPED, not rendered 0
        {"day": "2026-07-03", "total_equity": 100.5, "daily_pnl": None,
         "daily_pnl_percent": None, "drawdown": 0.005},
    ]
    monkeypatch.setattr(rd, "db", _StubDB(daily))
    ctx = await rd._journal_stats_context(1, None)
    assert ctx["daily_pnl"] == [
        {"d": "2026-07-01", "pnl": 1.0},
        {"d": "2026-07-02", "pnl": -0.5},
    ]
    # JSON-serializable end to end (rides the snapshot response)
    json.dumps(ctx["daily_pnl"], allow_nan=False)


@pytest.mark.asyncio
async def test_journal_context_daily_pnl_degrades_empty(monkeypatch):
    class _Boom(_StubDB):
        async def get_daily_equity_series(self, *a, **k):
            raise RuntimeError("db down")
    monkeypatch.setattr(rd, "db", _Boom([]))
    ctx = await rd._journal_stats_context(1, None)
    assert ctx["daily_pnl"] == []


class _StubRegimeDB:
    def __init__(self, data):
        self._data = data

    async def get_regime_signals(self, names, from_date, to_date):
        return self._data


@pytest.mark.asyncio
async def test_signals_latest_ships_series(monkeypatch):
    from core.regime_classifier import ALL_SIGNALS
    name = list(ALL_SIGNALS)[0]
    pts = [{"date": f"2026-07-{i+1:02d}", "value": 10.0 + i} for i in range(35)]
    monkeypatch.setattr(rr, "db", _StubRegimeDB({name: pts}))
    resp = await rr.api_regime_signals_latest()
    body = json.loads(resp.body)
    by_name = {s["name"]: s for s in body["signals"]}
    s = by_name[name]
    # capped at the last 30 points, oldest-first, rounded
    assert len(s["series"]) == 30
    assert s["series"][0] == 15.0 and s["series"][-1] == 44.0
    assert s["v"] == 44.0
    # signal with no rows: series present and EMPTY (never fabricated)
    empty = [x for x in body["signals"] if x["name"] != name]
    assert empty and all(x["series"] == [] and x["v"] is None for x in empty)
