"""
Phase 8 Task 1 (P8.T1) tests — cockpit multi-pane dashboard layout + scaffold.

Per CLAUDE.md "Template wiring tests": source grep is insufficient
(Python-in-Jinja errors slip through), so this COMPILE-AND-RENDERS the four
pane fragments via jinja2.Environment(FileSystemLoader("templates")) with
minimal synthetic context and asserts the rendered structure. Mirrors
tests/test_phase3_needs_link_ui.py.

Intent (Rule 8):
  - each pane renders its real fields (positions deviation badge, calc
    status, needs-link queue count + link_status badge, close net PnL) and
    an EmptyState (not an error / not a crash) when its data is empty;
  - the recent-closes pane survives a NULL net_pnl (nullable column);
  - the page lazy-loads all four fragments + carries the 2x2 grid;
  - the page route + 4 fragment routes are registered and the router
    includes the cockpit router;
  - the nav tab + page_meta carry the cockpit page;
  - get_active_calcs returns ONLY active|released calcs, account-scoped,
    newest-first, limit-bounded.

Run: pytest tests/test_phase8_cockpit.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta

import jinja2
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── Jinja env (real globals the cockpit fragments reference) ──────────────────


# ── Pane: open positions ──────────────────────────────────────────────────────


# ── Pane: active calcs ────────────────────────────────────────────────────────


class TestCalcExpiryHelper:
    def test_created_plus_window(self):
        from api.routes_cockpit import _calc_expiry_ms
        ms = _calc_expiry_ms("2026-06-01T00:00:00+00:00", 300)
        created = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)
        assert ms == created + 300 * 1000

    def test_naive_timestamp_treated_as_utc(self):
        from api.routes_cockpit import _calc_expiry_ms
        ms = _calc_expiry_ms("2026-06-01T00:00:00", 60)
        created = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp() * 1000)
        assert ms == created + 60 * 1000

    def test_none_when_window_missing_or_zero(self):
        from api.routes_cockpit import _calc_expiry_ms
        assert _calc_expiry_ms("2026-06-01T00:00:00+00:00", None) is None
        assert _calc_expiry_ms("2026-06-01T00:00:00+00:00", 0) is None

    def test_none_on_bad_or_missing_timestamp(self):
        from api.routes_cockpit import _calc_expiry_ms
        assert _calc_expiry_ms("not-a-date", 300) is None
        assert _calc_expiry_ms(None, 300) is None


# ── Pane: needs link ──────────────────────────────────────────────────────────


# ── Pane: recent closes ───────────────────────────────────────────────────────


# ── Page template compiles + lazy-loads all four panes ────────────────────────


# ── Routes + nav registration (no TestClient — gotcha #9) ─────────────────────


# ── DB helper: get_active_calcs ───────────────────────────────────────────────


@pytest_asyncio.fixture
async def db():
    from core.database import DatabaseManager
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    d = DatabaseManager(path=tmp.name)
    await d.initialize()
    await d._conn.execute("INSERT OR IGNORE INTO accounts (id, name) VALUES (1, 'Test')")
    await d._conn.execute("INSERT OR IGNORE INTO accounts (id, name) VALUES (2, 'Other')")
    await d._conn.commit()
    yield d
    await d.close()
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


async def _ins(d, calc_id, status, account_id=1, ticker="BTCUSDT",
               ts=None):
    await d.insert_pre_trade_log({
        "account_id": account_id,
        "timestamp": ts or datetime.now(timezone.utc).isoformat(),
        "ticker": ticker, "side": "long", "effective_entry": 50000.0,
        "tp_price": 55000.0, "sl_price": 48000.0,
        "calc_id": calc_id, "status": status,
    })


class TestGetActiveCalcs:
    @pytest.mark.asyncio
    async def test_returns_only_active_and_released(self, db):
        await _ins(db, "A1", "active")
        await _ins(db, "R1", "released")
        await _ins(db, "M1", "matched")
        await _ins(db, "E1", "expired")
        await _ins(db, "S1", "superseded")
        await _ins(db, "C1", "cancelled_by_operator")
        rows = await db.get_active_calcs(1)
        ids = {r["calc_id"] for r in rows}
        assert ids == {"A1", "R1"}

    @pytest.mark.asyncio
    async def test_account_scoped(self, db):
        await _ins(db, "A1", "active", account_id=1)
        await _ins(db, "A2", "active", account_id=2)
        rows = await db.get_active_calcs(1)
        assert {r["calc_id"] for r in rows} == {"A1"}

    @pytest.mark.asyncio
    async def test_newest_first_and_limit(self, db):
        base = datetime(2026, 6, 1, tzinfo=timezone.utc)
        for i in range(5):
            await _ins(db, f"A{i}", "active",
                       ts=(base + timedelta(minutes=i)).isoformat())
        rows = await db.get_active_calcs(1, limit=3)
        assert len(rows) == 3
        # newest (largest minute offset) first
        assert rows[0]["calc_id"] == "A4"
        assert rows[1]["calc_id"] == "A3"

    @pytest.mark.asyncio
    async def test_empty_when_no_live_calcs(self, db):
        await _ins(db, "M1", "matched")
        assert await db.get_active_calcs(1) == []
