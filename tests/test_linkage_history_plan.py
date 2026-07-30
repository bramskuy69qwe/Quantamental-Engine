"""
Follow-up #2 (debug 2026-06-08): surface calc linkage in Position History.

The open-positions cockpit already shows a "Plan" deviation badge (#1); the
closed-positions Position History had no linkage indicator at all. This adds:
  - the closed-positions route stamps a "Plan" deviation-badge LEVEL on
    rows that carry a calc_id, and "" on unlinked / legacy rows.

(Fragments slim-down 2026-07-30: the table/drawer RENDER classes retired with
their templates — the React History page renders the badge from the JSON rows;
the badge-STAMPING semantics below are the load-bearing survivors, pinned via
the route's JSON payload.)

Intent (Rule 8) — these fail if the linkage stamping regresses:
  - a calc-linked close carries an on-plan/amended/off-plan badge level
    (reused from the SAME deviation_badge_level as the live path);
  - an UNLINKED (legacy) close carries "", NOT a misleading red "off-plan"
    (≈150 historical rows must not all light up red).

Run: pytest tests/test_linkage_history_plan.py -v
"""
from __future__ import annotations

import os
import sys
import tempfile

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── helpers ───────────────────────────────────────────────────────────────────


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


async def _add_closed(db, *, calc_id=None, size_delta_pct=0.0, amend=0,
                      symbol="BTCUSDT", exit_ms=1000, tpsl_amended=None):
    cur = await db._conn.execute(
        "INSERT INTO closed_positions (account_id, symbol, direction, "
        "terminal_position_id, calc_id, size_delta_pct, cumulative_amendment_count, "
        "tpsl_amended, exit_time_ms, entry_price, quantity, net_pnl, realized_pnl, total_fees) "
        "VALUES (1, ?, 'LONG', 'tp', ?, ?, ?, ?, ?, 100.0, 1.0, 1.0, 1.0, 0.0)",
        (symbol, calc_id, size_delta_pct, amend, tpsl_amended, exit_ms),
    )
    await db._conn.commit()
    return cur.lastrowid


async def _call_table(monkeypatch, db):
    """Drive the (now JSON-only) closed-positions door and index its rows."""
    import json
    import api.routes_orders as ro
    from types import SimpleNamespace
    monkeypatch.setattr(ro, "db", db)
    monkeypatch.setattr(ro, "app_state", SimpleNamespace(active_account_id=1))
    resp = await ro.frag_closed_positions(request=None)
    rows = json.loads(resp.body.decode("utf-8"))["rows"]
    return {r["id"]: r for r in rows}


# ── route: deviation-badge level computation (linked vs unlinked) ──────────────


class TestRouteBadge:
    @pytest.mark.asyncio
    async def test_linked_on_plan_is_green(self, db, monkeypatch):
        pid = await _add_closed(db, calc_id="CALC-1", size_delta_pct=0.0, amend=0)
        rows = await _call_table(monkeypatch, db)
        assert rows[pid]["deviation_badge"] == "green"

    @pytest.mark.asyncio
    async def test_linked_amended_is_yellow(self, db, monkeypatch):
        pid = await _add_closed(db, calc_id="CALC-1", size_delta_pct=0.0, amend=2)
        rows = await _call_table(monkeypatch, db)
        assert rows[pid]["deviation_badge"] == "yellow"

    @pytest.mark.asyncio
    async def test_linked_far_off_plan_is_red(self, db, monkeypatch):
        # a large size deviation pushes past the red threshold even when linked.
        pid = await _add_closed(db, calc_id="CALC-1", size_delta_pct=999.0, amend=0)
        rows = await _call_table(monkeypatch, db)
        assert rows[pid]["deviation_badge"] == "red"

    @pytest.mark.asyncio
    async def test_unlinked_is_blank_not_red(self, db, monkeypatch):
        # the key calibration: a legacy/unlinked close must NOT be flagged red
        # (it had no plan to deviate from) — it gets "" → "—" in the table.
        pid = await _add_closed(db, calc_id=None)
        rows = await _call_table(monkeypatch, db)
        assert rows[pid]["deviation_badge"] == ""

    @pytest.mark.asyncio
    async def test_linked_tpsl_amended_is_yellow(self, db, monkeypatch):
        # 2026-06-15: a linked, on-plan-SIZE, zero-LEDGER-amendment close that
        # carries the persisted tpsl_amended flag (a venue cancel+new TP/SL edit,
        # which writes no order_amendments row → cumulative_amendment_count=0)
        # must read "amended" (yellow) in history — matching the live badge.
        # Before the fix it read green/on-plan (the gap the operator hit).
        pid = await _add_closed(db, calc_id="CALC-1", size_delta_pct=0.0,
                                amend=0, tpsl_amended=1)
        rows = await _call_table(monkeypatch, db)
        assert rows[pid]["deviation_badge"] == "yellow"

    @pytest.mark.asyncio
    async def test_unlinked_tpsl_amended_stays_blank(self, db, monkeypatch):
        # tpsl_amended only colors LINKED rows; an unlinked close stays "" even
        # if the column is somehow set (the has_calc gate wins).
        pid = await _add_closed(db, calc_id=None, tpsl_amended=1)
        rows = await _call_table(monkeypatch, db)
        assert rows[pid]["deviation_badge"] == ""

    @pytest.mark.asyncio
    async def test_linked_sl_removed_is_red(self, db, monkeypatch):
        # 2026-06-20 severity: tpsl_amended=2 means the STOP was removed during
        # life (unprotected — the "fatal" deviation). A linked close carrying it
        # must read RED in history, not yellow — distinct from a benign amend (1).
        pid = await _add_closed(db, calc_id="CALC-1", size_delta_pct=0.0,
                                amend=0, tpsl_amended=2)
        rows = await _call_table(monkeypatch, db)
        assert rows[pid]["deviation_badge"] == "red"


# ── table render: Plan column shows badge for linked, "—" for unlinked ─────────


# ── drawer render: surfaces the linked calc id(s) ─────────────────────────────


# ── cockpit Recent-Closes pane: same Plan badge as Position History ────────────


