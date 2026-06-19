"""
Follow-up #2 (debug 2026-06-08): surface calc linkage in Position History.

The open-positions cockpit already shows a "Plan" deviation badge (#1); the
closed-positions Position History had no linkage indicator at all. This adds:
  - the closed-positions table route stamps a "Plan" deviation-badge LEVEL on
    rows that carry a calc_id, and "" on unlinked / legacy rows;
  - the table renders a Plan column (badge for linked, "—" for unlinked);
  - the per-position drilldown drawer surfaces WHICH calc(s) the position
    linked to (the operator asked the drilldown to "show the linked calc").

Intent (Rule 8) — these fail if the linkage display regresses:
  - a calc-linked close shows an on-plan/amended/off-plan badge (level reused
    from the SAME deviation_badge_level as the live path → surfaces consistent);
  - an UNLINKED (legacy) close shows "—", NOT a misleading red "off-plan"
    (≈150 historical rows must not all light up red);
  - the drilldown drawer lists the linked calc id(s) with a context link.

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


class _CapTemplates:
    def __init__(self):
        self.ctx = None
        self.name = None

    def TemplateResponse(self, request, name, ctx):
        from fastapi.responses import HTMLResponse
        self.name, self.ctx = name, ctx
        return HTMLResponse("ok")


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
    import api.routes_orders as ro
    from types import SimpleNamespace
    cap = _CapTemplates()
    monkeypatch.setattr(ro, "_table_ctx", lambda request, **extra: dict(extra))
    monkeypatch.setattr(ro, "templates", cap)
    monkeypatch.setattr(ro, "db", db)
    monkeypatch.setattr(ro, "app_state", SimpleNamespace(active_account_id=1))
    await ro.frag_closed_positions(request=None)
    return {r["id"]: r for r in cap.ctx["rows"]}


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


# ── table render: Plan column shows badge for linked, "—" for unlinked ─────────


def _render_table(rows):
    from api.helpers import templates
    return templates.env.get_template(
        "fragments/history/closed_positions_table.html"
    ).render(
        rows=rows, total=len(rows), page=1, per_page=20, total_pages=1,
        sort_by="exit_time_ms", sort_dir="DESC", search="",
        date_from="", date_to="",
    )


def _row(**kw):
    r = {
        "id": 1, "entry_time_ms": 1000, "exit_time_ms": 2000, "symbol": "BTCUSDT",
        "direction": "LONG", "quantity": 1.0, "entry_price": 100.0,
        "exit_price": 101.0, "net_pnl": 1.0, "realized_pnl": 1.0, "total_fees": 0.0,
        "hold_time_ms": 1000, "exit_reason": "TP_PLANNED", "tp_price": 0.0,
        "sl_price": 0.0, "mfe": 0.0, "mae": 0.0, "backfill_completed": 0,
        "close_note": "", "calc_id": None, "deviation_badge": "",
        "size_delta_pct": 0.0, "cumulative_amendment_count": 0,
    }
    r.update(kw)
    return r


class TestTableRender:
    def test_compiles(self):
        _render_table([_row()])   # raises on Jinja/syntax error

    def test_linked_row_shows_badge(self):
        html = _render_table([_row(calc_id="CALC-1", deviation_badge="green")])
        assert "on-plan" in html          # deviation_badge macro green label

    def test_unlinked_row_shows_dash_not_badge(self):
        html = _render_table([_row(calc_id=None, deviation_badge="")])
        assert "on-plan" not in html and "off-plan" not in html
        assert "—" in html                # the explicit no-plan marker

    def test_plan_header_present(self):
        html = _render_table([_row()])
        assert ">Plan<" in html


# ── drawer render: surfaces the linked calc id(s) ─────────────────────────────


def _render_drawer(calc_ids):
    from api.helpers import templates
    return templates.env.get_template(
        "fragments/history/position_events.html"
    ).render(events=[], has_calc=bool(calc_ids), calc_ids=calc_ids,
             truncated=False, events_cap=500, position_id=7)


class TestDrawerCalcSurface:
    def test_lists_linked_calc_with_context_link(self):
        html = _render_drawer(["03e664ebb4fd4131bec021557513dc18"])
        assert "linked calc" in html
        assert "/context/calc/03e664ebb4fd4131bec021557513dc18" in html
        assert "03e664eb" in html         # short id shown

    def test_plural_for_scale_in(self):
        html = _render_drawer(["aaaaaaaa1111", "bbbbbbbb2222"])
        assert "linked calcs" in html     # plural

    def test_no_calc_no_link(self):
        # (the template's HTML comment legitimately contains "no linked calc";
        # assert on the functional markers instead — the rendered label + link.)
        html = _render_drawer([])
        assert "linked calc:" not in html and "linked calcs:" not in html
        assert "/context/calc/" not in html


# ── cockpit Recent-Closes pane: same Plan badge as Position History ────────────


async def _call_cockpit_closes(monkeypatch, db):
    import api.routes_cockpit as rc
    from types import SimpleNamespace
    cap = _CapTemplates()
    monkeypatch.setattr(rc, "_table_ctx", lambda request, **extra: dict(extra))
    monkeypatch.setattr(rc, "templates", cap)
    monkeypatch.setattr(rc, "db", db)
    monkeypatch.setattr(rc, "app_state", SimpleNamespace(active_account_id=1))
    await rc.frag_cockpit_closes(request=None)
    return {r["id"]: r for r in cap.ctx["rows"]}


def _render_cockpit_closes(rows):
    from api.helpers import templates
    return templates.env.get_template(
        "fragments/cockpit/closes.html"
    ).render(rows=rows)


class TestCockpitRecentCloses:
    @pytest.mark.asyncio
    async def test_route_stamps_badge_linked_only(self, db, monkeypatch):
        linked = await _add_closed(db, calc_id="CALC-1", exit_ms=2000)
        legacy = await _add_closed(db, calc_id=None, exit_ms=1000)
        rows = await _call_cockpit_closes(monkeypatch, db)
        assert rows[linked]["deviation_badge"] == "green"
        assert rows[legacy]["deviation_badge"] == ""

    def test_render_linked_shows_badge(self):
        html = _render_cockpit_closes([_row(calc_id="CALC-1", deviation_badge="green")])
        assert "on-plan" in html and ">Plan<" in html

    def test_render_unlinked_shows_dash(self):
        html = _render_cockpit_closes([_row(calc_id=None, deviation_badge="")])
        assert "on-plan" not in html and "—" in html
