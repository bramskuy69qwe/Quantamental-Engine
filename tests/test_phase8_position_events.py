"""
Phase 8 Task 9 (P8.T9) — per-position trade-events drilldown (plan §8.10).

The Position History drawer gains a second lazy-loaded section beside the fills
sub-table: a chronological timeline of THIS position's trade_events. The backend
(``GET /fragments/history/position_events``) resolves the position's calc_id(s)
from the positions_calcs junction and unions ``query_trade_events`` across them,
so a sibling position's events can never leak in. Positions with no linked calc
(legacy / Phase-0.0.6-0.0.7 rebuilt rows) get an empty-state, not an error.

Intent (Rule 8):
  - events are scoped to the position's own calc_id(s) — NO sibling leak;
  - multiple calcs (scale-in) union + merge chronologically (oldest-first);
  - no-calc position -> has_calc False -> "pre-dates" empty-state (not error);
  - the timeline renders chips + one-line summaries; the drawer is wired.

The endpoint returns a TemplateResponse, so its data assembly is tested by
capturing the context (no second TestClient — that hangs the suite); the
template itself is rendered separately via the app's Jinja env.

Run: pytest tests/test_phase8_position_events.py -v
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from types import SimpleNamespace

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── helpers ───────────────────────────────────────────────────────────────────


class _CapTemplates:
    """Stub for api.routes_orders.templates — captures the render context so the
    endpoint's data assembly can be asserted without rendering / a TestClient."""

    def __init__(self):
        self.ctx = None

    def TemplateResponse(self, request, name, ctx):
        from fastapi.responses import HTMLResponse
        self.name = name
        self.ctx = ctx
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
    try:
        os.unlink(tmp.name)
        for ext in ("-wal", "-shm"):
            p = tmp.name + ext
            if os.path.exists(p):
                os.unlink(p)
    except OSError:
        pass


async def _add_position(db, tpid, *, symbol="BTCUSDT", direction="LONG", exit_ms=1000):
    cur = await db._conn.execute(
        "INSERT INTO closed_positions (account_id, symbol, terminal_position_id, "
        "direction, exit_time_ms) VALUES (1, ?, ?, ?, ?)",
        (symbol, tpid, direction, exit_ms),
    )
    await db._conn.commit()
    return cur.lastrowid


async def _link(db, tpid, calc_id, *, order_id=1, first_fill_ts=0):
    await db._conn.execute(
        "INSERT INTO positions_calcs (position_id, calc_id, order_id, account_id, "
        "first_fill_ts) VALUES (?, ?, ?, 1, ?)",
        (tpid, calc_id, order_id, first_fill_ts),
    )
    await db._conn.commit()


def _emit(calc_id, event_type, ts, payload=None):
    # Writes through the conftest autouse guard -> throwaway iso trade_events DB
    # (no data_dir, real DATA_DIR). query_trade_events (also no data_dir) reads
    # the same iso DB, so write-then-read is consistent.
    from core.trade_event_log import log_trade_event
    log_trade_event(1, calc_id, event_type, payload or {}, "test", timestamp=ts)


async def _call(monkeypatch, db, position_id):
    import api.routes_orders as ro
    import api.helpers as helpers
    cap = _CapTemplates()
    monkeypatch.setattr(helpers, "_ctx", lambda request, **extra: dict(extra))
    monkeypatch.setattr(ro, "templates", cap)
    monkeypatch.setattr(ro, "db", db)
    monkeypatch.setattr(ro, "app_state", SimpleNamespace(active_account_id=1))
    await ro.frag_position_events(request=None, position_id=position_id)
    return cap.ctx


# ── endpoint: scoping / chronology / empty-state ──────────────────────────────


class TestEndpoint:
    @pytest.mark.asyncio
    async def test_scoped_to_own_calc_no_sibling_leak(self, db, monkeypatch):
        pid_a = await _add_position(db, "TPID-A")
        await _add_position(db, "TPID-B")
        await _link(db, "TPID-A", "CALC-A")
        await _link(db, "TPID-B", "CALC-B")
        _emit("CALC-A", "calc_created",    "2026-06-01T10:00:00")
        _emit("CALC-A", "order_filled",    "2026-06-01T10:02:00", {"price": 1, "quantity": 1})
        _emit("CALC-B", "calc_created",    "2026-06-01T10:01:00")   # sibling — must NOT appear
        ctx = await _call(monkeypatch, db, pid_a)
        assert ctx["has_calc"] is True
        assert all(e["calc_id"] == "CALC-A" for e in ctx["events"])  # no leak
        assert [e["event_type"] for e in ctx["events"]] == ["calc_created", "order_filled"]

    @pytest.mark.asyncio
    async def test_chronological_oldest_first_across_calcs(self, db, monkeypatch):
        # scale-in: one position, two calcs; events interleave in time and must
        # merge oldest-first regardless of which calc they came from.
        pid = await _add_position(db, "TPID-S")
        await _link(db, "TPID-S", "CALC-1", order_id=1)
        await _link(db, "TPID-S", "CALC-2", order_id=2)
        _emit("CALC-1", "calc_created",    "2026-06-01T09:00:00")
        _emit("CALC-2", "calc_created",    "2026-06-01T09:00:30")
        _emit("CALC-1", "order_filled",    "2026-06-01T09:01:00", {"price": 1, "quantity": 1})
        _emit("CALC-2", "order_filled",    "2026-06-01T09:00:45", {"price": 1, "quantity": 1})
        ctx = await _call(monkeypatch, db, pid)
        ts = [e["timestamp"] for e in ctx["events"]]
        assert ts == sorted(ts)                                      # oldest-first
        assert len(ctx["events"]) == 4

    @pytest.mark.asyncio
    async def test_distinct_calc_ids_no_double_count(self, db, monkeypatch):
        # same calc on two orders (two junction rows) must be queried ONCE.
        pid = await _add_position(db, "TPID-D")
        await _link(db, "TPID-D", "CALC-X", order_id=1)
        await _link(db, "TPID-D", "CALC-X", order_id=2)
        _emit("CALC-X", "calc_created", "2026-06-01T08:00:00")
        ctx = await _call(monkeypatch, db, pid)
        assert len(ctx["events"]) == 1                               # not duplicated

    @pytest.mark.asyncio
    async def test_empty_state_no_calc(self, db, monkeypatch):
        pid = await _add_position(db, "TPID-LEGACY")               # no junction rows
        ctx = await _call(monkeypatch, db, pid)
        assert ctx["events"] == [] and ctx["has_calc"] is False

    @pytest.mark.asyncio
    async def test_empty_terminal_id_is_empty_state(self, db, monkeypatch):
        pid = await _add_position(db, "")                          # legacy: blank tpid
        ctx = await _call(monkeypatch, db, pid)
        assert ctx["events"] == [] and ctx["has_calc"] is False

    @pytest.mark.asyncio
    async def test_payload_parsed_for_summary(self, db, monkeypatch):
        pid = await _add_position(db, "TPID-P")
        await _link(db, "TPID-P", "CALC-P")
        _emit("CALC-P", "order_filled", "2026-06-01T07:00:00", {"price": 100.5, "quantity": 2})
        ctx = await _call(monkeypatch, db, pid)
        assert ctx["events"][0]["_payload"] == {"price": 100.5, "quantity": 2}

    @pytest.mark.asyncio
    async def test_no_position_id_is_empty_state(self, db, monkeypatch):
        ctx = await _call(monkeypatch, db, 0)
        assert ctx["events"] == [] and ctx["has_calc"] is False

    @pytest.mark.asyncio
    async def test_truncation_flagged_not_silent(self, db, monkeypatch):
        # No silent caps (CLAUDE.md): with >cap events on one calc, the endpoint
        # returns the newest `cap` AND flags truncated=True (oldest omitted).
        import api.routes_orders as ro
        monkeypatch.setattr(ro, "_POSITION_EVENTS_CAP", 2)
        pid = await _add_position(db, "TPID-T")
        await _link(db, "TPID-T", "CALC-T")
        _emit("CALC-T", "calc_created",   "2026-06-01T10:00:00")
        _emit("CALC-T", "order_filled",   "2026-06-01T10:01:00", {"price": 1, "quantity": 1})
        _emit("CALC-T", "position_closed","2026-06-01T10:02:00", {"pnl": 1})
        ctx = await _call(monkeypatch, db, pid)
        assert ctx["truncated"] is True
        assert len(ctx["events"]) == 2                              # newest 2 kept
        assert [e["event_type"] for e in ctx["events"]] == ["order_filled", "position_closed"]

    @pytest.mark.asyncio
    async def test_not_truncated_when_under_cap(self, db, monkeypatch):
        pid = await _add_position(db, "TPID-U")
        await _link(db, "TPID-U", "CALC-U")
        _emit("CALC-U", "calc_created", "2026-06-01T10:00:00")
        ctx = await _call(monkeypatch, db, pid)
        assert ctx["truncated"] is False

    @pytest.mark.asyncio
    async def test_position_id_threaded_for_export_button(self, db, monkeypatch):
        # Phase-8 deferred #2: the drawer needs the closed_positions PK to build
        # the Export-Audit form action; the endpoint must pass it through even
        # for a no-calc row (export still works via the closed-row fallback).
        pid = await _add_position(db, "TPID-EXP")
        ctx = await _call(monkeypatch, db, pid)
        assert ctx["position_id"] == pid


# ── template render ───────────────────────────────────────────────────────────


def _render(events, has_calc, truncated=False, events_cap=500, position_id=0):
    from api.helpers import templates           # app Jinja env (fmt/etc. globals)
    return templates.env.get_template(
        "fragments/history/position_events.html"
    ).render(events=events, has_calc=has_calc, truncated=truncated,
             events_cap=events_cap, position_id=position_id)


def _evt(ts, event_type, payload=None):
    payload = payload or {}
    return {
        "id": 0, "timestamp": ts, "event_type": event_type, "source": "ws",
        "calc_id": "C", "payload_json": json.dumps(payload), "_payload": payload,
    }


class TestRender:
    def test_compiles(self):
        _render([], False)                       # raises on Jinja/syntax error

    def test_chips_in_given_order(self):
        html = _render([
            _evt("2026-06-01T10:00:00", "calc_created"),
            _evt("2026-06-01T10:01:00", "order_filled", {"price": 1, "quantity": 1}),
            _evt("2026-06-01T10:02:00", "position_closed", {"pnl": 5}),
        ], True)
        i_calc = html.index("calc_created")
        i_fill = html.index("order_filled")
        i_close = html.index("position_closed")
        assert i_calc < i_fill < i_close          # timeline preserves order

    def test_detail_summaries(self):
        html = _render([
            _evt("2026-06-01T10:01:00", "order_filled", {"price": 100.5, "quantity": 2}),
            _evt("2026-06-01T10:02:00", "position_closed", {"pnl": 25}),
        ], True)
        assert "Price:" in html and "Qty:" in html
        assert "PnL:" in html

    def test_timestamp_rendered_without_T(self):
        html = _render([_evt("2026-06-01T10:01:30", "calc_created")], True)
        assert "2026-06-01 10:01:30" in html      # ISO 'T' replaced with space

    def test_empty_state_no_calc_message(self):
        html = _render([], False)
        assert "pre-dates" in html.lower()        # informational empty-state...
        assert "<table" not in html               # ...not the events table / an error

    def test_empty_state_has_calc_message(self):
        html = _render([], True)
        assert "No trade events recorded" in html

    def test_truncation_banner_only_when_truncated(self):
        ev = [_evt("2026-06-01T10:00:00", "calc_created")]
        assert "older events omitted" in _render(ev, True, truncated=True, events_cap=500)
        assert "older events omitted" not in _render(ev, True)   # default False


# ── Export-Audit button (Phase-8 deferred #2 — wires P7.T4/T5 onto the drawer) ──


class TestExportButton:
    """The signed-audit-export endpoints (POST /export/closed_position/{id}?
    format=json|pdf) get a UI: a native download form in the events drawer.
    Intent (Rule 8): the form is keyed by the closed_positions PK (so the
    download hits the right row), offers both formats, and renders for EVERY
    closed row — including no-calc / legacy ones, since the export has a
    closed-row-only fallback. A GET <a> or htmx post would be wrong (the
    endpoint is POST and returns a file)."""

    def test_both_format_buttons_keyed_by_position_id(self):
        html = _render([], True, position_id=42)
        assert 'formaction="/export/closed_position/42?format=json"' in html
        assert 'formaction="/export/closed_position/42?format=pdf"' in html
        assert 'method="post"' in html            # native POST download, not GET/htmx

    def test_export_renders_even_for_no_calc_legacy_row(self):
        # no linked calc -> empty-state, but export still offered (closed-row
        # fallback in build_closed_position_export).
        html = _render([], False, position_id=7)
        assert "/export/closed_position/7?format=json" in html
        assert "pre-dates" in html.lower()        # still the legacy empty-state

    def test_no_export_form_without_position_id(self):
        # position_id=0 (param default / never-set) must NOT emit a form that
        # would POST to /export/closed_position/0 (a guaranteed 404).
        html = _render([], True, position_id=0)
        assert "/export/closed_position/" not in html


# ── wiring ────────────────────────────────────────────────────────────────────


class TestWiring:
    def test_route_registered(self):
        import api.routes_orders as ro
        paths = {getattr(r, "path", None) for r in ro.router.routes}
        assert "/fragments/history/position_events" in paths

    def test_drawer_has_events_row(self):
        with open("templates/fragments/history/closed_positions_table.html", encoding="utf-8") as fh:
            src = fh.read()
        assert "events-row-{{ r.id }}" in src

    def test_toggle_lazy_loads_events(self):
        with open("templates/history.html", encoding="utf-8") as fh:
            src = fh.read()
        assert "/fragments/history/position_events?position_id=" in src
        assert "events-row-" in src
