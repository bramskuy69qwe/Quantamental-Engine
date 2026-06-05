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


def _make_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader("templates"),
        autoescape=jinja2.select_autoescape(["html"]),
    )
    env.globals["fmt"] = lambda v, n=2: (
        f"{v:.{n}f}" if isinstance(v, (int, float)) else str(v)
    )
    env.globals["ms_to_local"] = lambda ms: "2026-06-05 12:00:00" if ms else "—"
    env.globals["project_name"] = "TestEngine"
    return env


def _render(template: str, **ctx) -> str:
    return _make_env().get_template(template).render(**ctx)


# ── Pane: open positions ──────────────────────────────────────────────────────


def _pos(ticker="BTCUSDT", direction="LONG", upnl=12.5, badge="yellow",
         size_delta=8.0, amend=1, mfe=30.0, mae=-8.0):
    return {
        "ticker": ticker, "direction": direction,
        "individual_unrealized": upnl, "deviation_badge": badge,
        "size_delta_pct": size_delta, "amendment_count": amend,
        "session_mfe": mfe, "session_mae": mae,
    }


class TestPositionsPane:
    def test_renders_position_with_deviation_badge(self):
        html = _render("fragments/cockpit/positions.html", positions=[_pos()])
        assert "BTCUSDT" in html
        assert "pos-long" in html
        assert "12.50" in html
        # P4.T3 deviation badge: yellow level -> "amended" label + badge-yellow
        assert "badge-yellow" in html
        assert "amended" in html

    def test_negative_upnl_is_red(self):
        html = _render("fragments/cockpit/positions.html",
                       positions=[_pos(upnl=-5.0)])
        assert "text-red" in html

    def test_renders_mfe_and_mae(self):
        # P8.T2: session MFE/MAE columns. MFE green, MAE red (fixed colors,
        # mirroring the dashboard table).
        html = _render("fragments/cockpit/positions.html",
                       positions=[_pos(mfe=30.0, mae=-8.0)])
        assert ">MFE<" in html and ">MAE<" in html      # column headers
        assert "30.00" in html                          # MFE value
        assert "8.00" in html                           # MAE value (magnitude)
        # MFE cell is green, MAE cell is red
        assert 'class="text-green" style="text-align:right;">30.00' in html
        assert 'class="text-red" style="text-align:right;">-8.00' in html

    def test_mfe_mae_null_safe(self):
        html = _render("fragments/cockpit/positions.html",
                       positions=[_pos(mfe=None, mae=None)])
        assert "BTCUSDT" in html       # renders without crashing

    def test_no_badge_when_level_empty(self):
        # binance one-way / no junction -> deviation_badge "" -> no badge span
        html = _render("fragments/cockpit/positions.html",
                       positions=[_pos(badge="")])
        assert "badge-yellow" not in html and "badge-green" not in html

    def test_null_upnl_does_not_crash(self):
        # parity with the closes pane: guard a None/missing uPnL so the pane
        # renders the EmptyState arithmetic safely rather than 500-ing.
        html = _render("fragments/cockpit/positions.html",
                       positions=[_pos(upnl=None)])
        assert "BTCUSDT" in html
        assert "0.00" in html

    def test_empty_renders_empty_state_not_error(self):
        html = _render("fragments/cockpit/positions.html", positions=[])
        assert "No open positions" in html
        assert 'class="es' in html  # EmptyState wrapper


# ── Pane: active calcs ────────────────────────────────────────────────────────


def _calc(ticker="ETHUSDT", side="long", average=3000.0, status="active"):
    return {"ticker": ticker, "side": side, "average": average, "status": status}


class TestCalcsPane:
    def test_renders_active_calc(self):
        html = _render("fragments/cockpit/calcs.html", calcs=[_calc()])
        assert "ETHUSDT" in html
        assert "LONG" in html            # side uppercased
        assert "pos-long" in html
        assert "3000.00" in html
        assert "badge-blue" in html      # active -> blue badge
        assert ">active<" in html        # status text in the badge (not the empty-state msg)

    def test_released_calc_is_gray(self):
        html = _render("fragments/cockpit/calcs.html",
                       calcs=[_calc(status="released")])
        assert "badge-gray" in html
        assert "released" in html

    def test_missing_entry_renders_dash(self):
        html = _render("fragments/cockpit/calcs.html",
                       calcs=[_calc(average=0.0)])
        assert "—" in html

    def test_empty_renders_empty_state(self):
        html = _render("fragments/cockpit/calcs.html", calcs=[])
        assert "No active calcs" in html


# ── Pane: needs link ──────────────────────────────────────────────────────────


def _nl_order(symbol="BTCUSDT", side="BUY",
              link_status="NEEDS_MANUAL_REVIEW", n_cand=2):
    return {
        "id": 1, "symbol": symbol, "side": side,
        "link_status": link_status,
        "candidates": [{"calc_id": "C%d" % i} for i in range(n_cand)],
    }


class TestNeedsLinkPane:
    def test_renders_count_and_badge_and_candidates(self):
        html = _render("fragments/cockpit/needs_link.html",
                       orders=[_nl_order()], total=1)
        assert "1 order(s) awaiting manual link" in html
        assert "BTCUSDT" in html
        # P3.T4 link_status_badge primitive
        assert "NEEDS REVIEW" in html and "badge-yellow" in html
        assert ">2<" in html             # candidate count

    def test_preview_truncation_note(self):
        # total exceeds shown -> "showing N" note
        html = _render("fragments/cockpit/needs_link.html",
                       orders=[_nl_order()], total=5)
        assert "showing 1" in html

    def test_empty_renders_empty_state(self):
        html = _render("fragments/cockpit/needs_link.html", orders=[], total=0)
        assert "Nothing needs manual review" in html
        assert "manual_link" not in html  # no action wiring in the compact pane


# ── Pane: recent closes ───────────────────────────────────────────────────────


def _close(symbol="BTCUSDT", direction="LONG", net_pnl=42.0,
           exit_reason="TP_PLANNED", exit_time_ms=1700000000000):
    return {
        "symbol": symbol, "direction": direction, "net_pnl": net_pnl,
        "exit_reason": exit_reason, "exit_time_ms": exit_time_ms,
    }


class TestClosesPane:
    def test_renders_close_row(self):
        html = _render("fragments/cockpit/closes.html", rows=[_close()])
        assert "BTCUSDT" in html
        assert "pos-long" in html
        assert "42.00" in html
        assert "text-green" in html      # positive net
        assert "TP_PLANNED" in html

    def test_negative_net_is_red(self):
        html = _render("fragments/cockpit/closes.html",
                       rows=[_close(net_pnl=-7.0)])
        assert "text-red" in html

    def test_null_net_pnl_does_not_crash(self):
        # closed_positions.net_pnl is nullable; the pane must guard (r.net_pnl or 0)
        html = _render("fragments/cockpit/closes.html",
                       rows=[_close(net_pnl=None, exit_reason=None)])
        assert "BTCUSDT" in html
        assert "0.00" in html
        assert "—" in html               # null exit_reason -> dash

    def test_empty_renders_empty_state(self):
        html = _render("fragments/cockpit/closes.html", rows=[])
        assert "No closed positions yet" in html


# ── Page template compiles + lazy-loads all four panes ────────────────────────


class TestCockpitPage:
    def test_page_compiles(self):
        # catches Jinja syntax / nested-comment in the content + extra_head blocks
        _make_env().get_template("cockpit.html")

    def test_page_lazy_loads_all_four_fragments(self):
        with open("templates/cockpit.html", encoding="utf-8") as fh:
            src = fh.read()
        assert 'hx-get="/fragments/cockpit/positions"' in src
        assert 'hx-get="/fragments/cockpit/calcs"' in src
        assert 'hx-get="/fragments/cockpit/needs_link"' in src
        assert 'hx-get="/fragments/cockpit/closes"' in src
        # 2x2 grid scaffold present
        assert "ck-grid" in src
        assert "grid-template-columns:repeat(2" in src


# ── Routes + nav registration (no TestClient — gotcha #9) ─────────────────────


class TestCockpitRoutesAndNav:
    def test_routes_registered(self):
        import api.routes_cockpit as rc

        def _has(path):
            return any(
                getattr(r, "path", None) == path and "GET" in getattr(r, "methods", set())
                for r in rc.router.routes
            )

        assert _has("/cockpit")
        assert _has("/fragments/cockpit/positions")
        assert _has("/fragments/cockpit/calcs")
        assert _has("/fragments/cockpit/needs_link")
        assert _has("/fragments/cockpit/closes")

    def test_router_includes_cockpit(self):
        # the combined app router must mount the cockpit routes
        import api.router as r
        paths = {getattr(rt, "path", None) for rt in r.router.routes}
        assert "/cockpit" in paths

    def test_nav_and_page_meta_registered(self):
        with open("templates/base.html", encoding="utf-8") as fh:
            base = fh.read()
        assert "('cockpit',    '/cockpit')" in base or "('cockpit', '/cockpit')" in base
        assert "'cockpit':" in base


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
