"""Analytics metric fixes (2026-06-24): Max Drawdown, Cumulative PnL %, and the
R-multiple metrics that were reading stale/empty sources.

- get_equity_period_boundaries: max_drawdown is now period peak-to-trough off
  the equity curve (was MAX(account_snapshots.drawdown) — the rolling dd-GATE
  column, ≈0 at a rolling-window high → analytics showed 0%).
- get_cumulative_pnl: adds total_pnl_percent with an initial-equity fallback
  base (the template divided by deposits−withdrawals=0 → a stuck 0.00%).
- get_r_multiples: also sources closed_positions.realized_r (trade_history is
  the empty MANUAL journal → profit factor / expectancy read "—").
- overview_stats.html: Sortino (MAE) is inherently negative; the positive-biased
  ratio_card hid every val<=0 as "—" — now rendered directly.
"""
from __future__ import annotations

import os
import tempfile

import pytest
import pytest_asyncio
import jinja2
from pathlib import Path

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest_asyncio.fixture
async def db():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    d = DatabaseManager(path=tmp.name)
    await d.initialize()
    await d._conn.execute("INSERT OR IGNORE INTO accounts (id, name) VALUES (1, 'Test')")
    await d._conn.commit()
    yield d
    await d.close()
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(tmp.name + ext)
        except OSError:
            pass


async def _snap(db, ts_iso, equity, drawdown=0.0):
    await db._conn.execute(
        "INSERT INTO account_snapshots (account_id, snapshot_ts, total_equity, drawdown) "
        "VALUES (1, ?, ?, ?)",
        (ts_iso, equity, drawdown),
    )


class TestMaxDrawdownPeakToTrough:
    @pytest.mark.asyncio
    async def test_peak_to_trough_not_gate_column(self, db):
        # Equity curve 100 -> 150 -> 120 -> 200: max peak-to-trough = (150-120)/150 = 20%.
        # The rolling dd-GATE column is left 0.0 on every row — the old code read
        # MAX(that)=0; the fix must compute 20% from the curve regardless.
        from datetime import datetime, timezone
        base = datetime(2026, 6, 1, tzinfo=timezone.utc)
        for i, eq in enumerate([100.0, 150.0, 120.0, 200.0]):
            ts = base.replace(minute=i).strftime("%Y-%m-%dT%H:%M:%S")
            await _snap(db, ts, eq, drawdown=0.0)   # gate column deliberately 0
        await db._conn.commit()
        from_ms = int(base.timestamp() * 1000)
        to_ms = from_ms + 3600 * 1000
        b = await db.get_equity_period_boundaries(from_ms, to_ms, account_id=1)
        assert abs(b["max_drawdown"] - 0.20) < 1e-6   # 20%, NOT the 0.0 gate value
        assert b["initial_equity"] == 100.0 and b["final_equity"] == 200.0

    @pytest.mark.asyncio
    async def test_no_drawdown_monotonic(self, db):
        from datetime import datetime, timezone
        base = datetime(2026, 6, 2, tzinfo=timezone.utc)
        for i, eq in enumerate([50.0, 60.0, 70.0]):
            await _snap(db, base.replace(minute=i).strftime("%Y-%m-%dT%H:%M:%S"), eq)
        await db._conn.commit()
        from_ms = int(base.timestamp() * 1000)
        b = await db.get_equity_period_boundaries(from_ms, from_ms + 3600000, account_id=1)
        assert b["max_drawdown"] == 0.0   # monotonic up → no drawdown


class TestCumulativePnlPercent:
    @pytest.mark.asyncio
    async def test_percent_uses_initial_equity_when_no_deposits(self, db):
        # No TRANSFER income (deposits/withdrawals = 0) → must fall back to the
        # earliest snapshot equity as the base instead of dividing by 0.
        await _snap(db, "2026-06-01T00:00:00", 80.0)
        await db._conn.execute(
            "INSERT INTO exchange_history (account_id, symbol, income, income_type, time) "
            "VALUES (1, 'BTCUSDT', 40.0, 'REALIZED_PNL', ?)", (1780000000000,))
        await db._conn.commit()
        c = await db.get_cumulative_pnl(account_id=1)
        assert c["total_deposits"] == 0.0 and c["total_withdrawals"] == 0.0
        assert c["total_pnl"] == 40.0
        assert c["total_pnl_percent"] == 50.0   # 40 / 80 * 100

    @pytest.mark.asyncio
    async def test_percent_zero_when_no_base(self, db):
        # No snapshots, no deposits → base 0 → guard returns 0.0 (no div error).
        c = await db.get_cumulative_pnl(account_id=1)
        assert c["total_pnl_percent"] == 0.0


class TestRMultiplesFromClosedPositions:
    @pytest.mark.asyncio
    async def test_sources_closed_positions_realized_r(self, db):
        # trade_history (manual journal) is empty; the live R must come from
        # closed_positions.realized_r.
        for i, r in enumerate([0.5, -0.3, 1.2]):
            await db._conn.execute(
                "INSERT INTO closed_positions (account_id, symbol, direction, "
                "terminal_position_id, exit_time_ms, realized_r, entry_price, "
                "quantity, net_pnl, realized_pnl, total_fees) "
                "VALUES (1, 'BTCUSDT', 'LONG', ?, ?, ?, 100, 1, 1, 1, 0)",
                (f"tp{i}", 1781000000000 + i, r),
            )
        await db._conn.commit()
        rv = await db.get_r_multiples(1781000000000 - 1000, 1781000000000 + 10000, account_id=1)
        assert sorted(rv) == sorted([0.5, -0.3, 1.2])


_OVERVIEW_TPL = "templates/fragments/analytics/overview_stats.html"


class TestOverviewTemplateWiring:
    def test_template_compiles(self):
        # get_template compiles/parses the template -> raises TemplateSyntaxError
        # on a malformed edit (the 2026-06-24 cumulative-% set + the Sortino-MAE
        # inline render). The full-render path needs the entire live stats
        # context (brittle); a compile + source-wiring assertions match the
        # codebase's template-test pattern (test_task135) and catch the syntax
        # class this discipline targets.
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader("templates"),
            autoescape=jinja2.select_autoescape(["html"]),
        )
        env.get_template("fragments/analytics/overview_stats.html")  # compiles or raises

    def test_cumulative_percent_uses_backend_field(self):
        src = Path(_OVERVIEW_TPL).read_text(encoding="utf-8")
        assert "cumulative.total_pnl_percent" in src           # wired to backend %
        # the old div-by-zero base (deposits − withdrawals) must be gone
        assert "cumulative.total_deposits - cumulative.total_withdrawals" not in src

    def test_sortino_mae_not_positive_biased_card(self):
        src = Path(_OVERVIEW_TPL).read_text(encoding="utf-8")
        # Sortino (MAE) no longer routes through the positive-biased ratio_card
        # (which rendered every val<=0 as "—"); it's rendered inline so the
        # inherently-negative value shows.
        assert 'ratio_card("Sortino (MAE)"' not in src
        assert "ratios.sortino_mae" in src
